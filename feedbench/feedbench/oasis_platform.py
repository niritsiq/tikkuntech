"""OASIS integration: a Platform subclass whose feed is exactly what ranking.py returns.

Why a subclass: stock OASIS `Platform.refresh()` random-samples cached
recommendations, merges them with followed posts via set(), and re-queries with
SQL `IN (...)`, so the order a ranking rule computes is not the order agents see.
For a ranking benchmark the delivered order IS the experiment, so we:

  * override `update_rec_table()` -> rank feeds with ranking.py (and fill OASIS' rec table)
  * override `refresh()`          -> return those posts in exactly that order and log every impression

Sign-up, follow, like, repost, comment, the trace table, the SQLite database and
LLM agents via CAMEL are stock OASIS.
"""
from __future__ import annotations

import random

from oasis.social_platform.platform import Platform
from oasis.social_platform.typing import ActionType

from .config import RankingConfig
from .content import PostView
from .ranking import POPULARITY, Viewer, build_feed, pop_community_capped, pop_total_endorsements


class FeedBenchPlatform(Platform):

    def __init__(self, *args, policy: str, ranking_cfg: RankingConfig, agents, post_meta: dict,
                 seed: int, record_snapshots: bool = False, **kwargs):
        # recsys_type "random" keeps OASIS in Twitter mode (integer time steps); ranking is ours.
        super().__init__(*args, recsys_type="random", **kwargs)
        self.policy = policy
        self.rcfg = ranking_cfg
        self.agents = {a.id: a for a in agents}
        self.post_meta = post_meta                 # post_id -> {label, key, text, lean, ...}
        self.comment_labels: dict[int, str] = {}   # comment_id -> label
        self.seed = seed
        self.feeds: dict[int, list[tuple[PostView, dict]]] = {}
        self.seen: dict[int, set[int]] = {}
        self.impressions: list[dict] = []
        self.snapshots: list[dict] = []            # per round, per eligible post (for the inspector)
        self.record_snapshots = record_snapshots
        self.feed_users: set[int] | None = None

    @property
    def now(self) -> int:
        return int(self.sandbox_clock.time_step)

    def _q(self, sql: str, params: tuple = ()) -> list[tuple]:
        self.pl_utils._execute_db_command(sql, params)
        return self.db_cursor.fetchall()

    def _by_comm(self, users: set[int]) -> dict[int, int]:
        out: dict[int, int] = {}
        for u in users:
            c = self.agents[u].community
            out[c] = out.get(c, 0) + 1
        return out

    def post_views(self) -> dict[int, PostView]:
        now = self.now
        views: dict[int, PostView] = {}
        for pid, uid, created in self._q("SELECT post_id, user_id, CAST(created_at AS INTEGER) FROM post "
                                         "WHERE original_post_id IS NULL"):
            if now - created > self.rcfg.candidate_window:
                continue
            meta = self.post_meta.get(pid, {})
            views[pid] = PostView(post_id=pid, author=uid, author_community=self.agents[uid].community,
                                  created_round=created, label=meta.get("label", "benign"),
                                  key=meta.get("key", ""))
        endorsers = {pid: set() for pid in views}
        engagers = {pid: set() for pid in views}
        for uid, pid in self._q("SELECT user_id, post_id FROM 'like'"):
            if pid in views:
                endorsers[pid].add(uid)
        for uid, pid in self._q("SELECT user_id, original_post_id FROM post WHERE original_post_id IS NOT NULL"):
            if pid in views:
                endorsers[pid].add(uid)
                views[pid].reposters.add(uid)
        for uid, pid in self._q("SELECT user_id, post_id FROM comment"):
            if pid in views:
                engagers[pid].add(uid)
        for pid, v in views.items():
            v.endorsers = endorsers[pid]
            v.endorsers_by_comm = self._by_comm(endorsers[pid])
            v.engagers_by_comm = self._by_comm(endorsers[pid] | engagers[pid])
        return views

    async def update_rec_table(self):
        views = self.post_views()
        follows: dict[int, set[int]] = {}
        for f, e in self._q("SELECT follower_id, followee_id FROM follow"):
            follows.setdefault(f, set()).add(e)
        affinity: dict[int, dict[int, int]] = {}
        for uid, author in self._q(
                "SELECT l.user_id, p.user_id FROM 'like' l JOIN post p ON l.post_id = p.post_id "
                "UNION ALL SELECT c.user_id, p.user_id FROM comment c JOIN post p ON c.post_id = p.post_id "
                "UNION ALL SELECT r.user_id, o.user_id FROM post r JOIN post o ON r.original_post_id = o.post_id"):
            d = affinity.setdefault(uid, {})
            d[author] = d.get(author, 0) + 1

        if self.record_snapshots:
            for v in views.values():
                self.snapshots.append({
                    "round": self.now, "post_id": v.post_id,
                    "e": [v.endorsers_by_comm.get(c, 0) for c in range(3)],
                    "popA": pop_total_endorsements(v, self.rcfg),
                    "popB": pop_community_capped(v, self.rcfg),
                    "pop": POPULARITY[self.policy](v, self.rcfg),
                })

        self.feeds = {}
        users = self.feed_users if self.feed_users is not None else set(self.agents)
        for uid in sorted(users):
            seen = self.seen.setdefault(uid, set())
            cands = [v for v in views.values() if v.author != uid and v.post_id not in seen]
            viewer = Viewer(uid, follows.get(uid, set()), affinity.get(uid, {}))
            rng = random.Random(f"explore-{self.seed}-{self.now}-{uid}")
            self.feeds[uid] = build_feed(cands, viewer, self.now, self.policy, self.rcfg, rng)

        self.pl_utils._execute_db_command("DELETE FROM rec", commit=True)
        vals = [(u, p.post_id) for u, feed in self.feeds.items() for p, _ in feed]
        if vals:
            self.pl_utils._execute_many_db_command("INSERT INTO rec (user_id, post_id) VALUES (?, ?)",
                                                   vals, commit=True)

    async def refresh(self, agent_id: int):
        feed = self.feeds.get(agent_id, [])
        seen = self.seen.setdefault(agent_id, set())
        rows = []
        for pos, (p, s) in enumerate(feed):
            seen.add(p.post_id)
            comment_ids = [r[0] for r in self._q("SELECT comment_id FROM comment WHERE post_id = ?", (p.post_id,))]
            self.impressions.append({
                "round": self.now, "agent": agent_id, "agent_community": self.agents[agent_id].community,
                "post_id": p.post_id, "key": p.key, "label": p.label, "position": pos, "slot": s["slot"],
                "popularity": s["popularity"], "social": s["social"], "recency": round(s["recency"], 3),
                "score": round(s["total"], 3), "author_community": p.author_community,
                "endorsements": p.total_endorsements,
                # counterspeech replies shown under this post (OASIS displays comments with posts)
                "counter_replies_shown": sum(self.comment_labels.get(c) == "counter" for c in comment_ids),
            })
            rows += self._q("SELECT post_id, user_id, original_post_id, content, quote_content, created_at, "
                            "num_likes, num_dislikes, num_shares FROM post WHERE post_id = ?", (p.post_id,))
        if not rows:
            return {"success": False, "message": "No posts found."}
        posts = self.pl_utils._add_comments_to_posts(rows)
        # Standard OASIS trace row; "posts" keeps OASIS' own meaning (delivered post ids, here in ranked order).
        # FeedBench adds the slot and score parts [total, popularity, social, recency] per post.
        self.pl_utils._record_trace(agent_id, ActionType.REFRESH.value,
                                    {"posts": [r[0] for r in rows], "policy": self.policy,
                                     "slots": [s["slot"][0] for _, s in feed],
                                     "scores": [[round(s["total"], 3), round(s["popularity"], 3), round(s["social"], 3),
                                                 round(s["recency"], 3)] for _, s in feed]}, str(self.now))
        return {"success": True, "posts": posts}
