"""Read and annotate OASIS SQLite databases: the single source of truth for the lab page.

Everything the replay shows comes from the standard OASIS tables:

    user      user_id (= agent_id), user_name (@handle), name, bio, num_followings, num_followers
    follow    follower_id, followee_id
    post      post_id, user_id, original_post_id (NULL = original, else repost), content, created_at (= round)
    comment   comment_id, post_id, user_id, content, created_at
    like      user_id, post_id, created_at
    trace     action = 'refresh', info = {"posts": [...delivered, in order...], ...}

FeedBench adds its own tables to the same file (prefix `feedbench_`) for what OASIS
does not store: expert labels, simulation roles, sessions and ranking snapshots.
OASIS never reads them, so the database stays a normal OASIS database.

    feedbench_run            key, value            (policy, seed, scenario, cap, engine)
    feedbench_user           user_id, community, community_name, location, joined, jewish_identity,
                             in_harm_cluster, counter_speaker, activity, persona
    feedbench_post_label     post_id, label, scenario_key, is_control, lean
    feedbench_comment_label  comment_id, label
    feedbench_session        round, user_id, left_early, churned
    feedbench_snapshot       round, post_id, e0, e1, e2, pop_total, pop_capped, pop_rule

A database from another OASIS run (e.g. your own integration) works without the
feedbench tables: labels default to "unlabeled" and sessions are inferred from refreshes.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .profiles import COMMUNITY_NAMES, Profile

SLOT_NAMES = {"i": "in-network", "r": "recommended", "e": "exploration"}


# ---------- writing (after a FeedBench run) ----------

def write_feedbench_tables(db_path: str, run, cfg) -> None:
    con = sqlite3.connect(db_path)
    c = con.cursor()
    c.executescript("""
        DROP TABLE IF EXISTS feedbench_run;
        DROP TABLE IF EXISTS feedbench_user;
        DROP TABLE IF EXISTS feedbench_post_label;
        DROP TABLE IF EXISTS feedbench_comment_label;
        DROP TABLE IF EXISTS feedbench_session;
        DROP TABLE IF EXISTS feedbench_snapshot;
        CREATE TABLE feedbench_run (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE feedbench_user (user_id INTEGER PRIMARY KEY, community INTEGER, community_name TEXT,
            location TEXT, joined TEXT, jewish_identity INTEGER, in_harm_cluster INTEGER, counter_speaker INTEGER,
            activity REAL, persona TEXT, driver TEXT);
        CREATE TABLE feedbench_post_label (post_id INTEGER PRIMARY KEY, label TEXT, scenario_key TEXT,
            is_control INTEGER, lean REAL);
        CREATE TABLE feedbench_comment_label (comment_id INTEGER PRIMARY KEY, label TEXT);
        CREATE TABLE feedbench_session (round INTEGER, user_id INTEGER, left_early INTEGER, churned INTEGER);
        CREATE TABLE feedbench_snapshot (round INTEGER, post_id INTEGER, e0 INTEGER, e1 INTEGER, e2 INTEGER,
            pop_total REAL, pop_capped REAL, pop_rule REAL);
    """)
    meta = {"policy": run.policy, "seed": run.seed, "scenario": run.scenario, "cap": cfg.ranking.community_cap,
            "rounds": cfg.rounds, "config": json.dumps(cfg.to_dict())}
    c.executemany("INSERT INTO feedbench_run VALUES (?, ?)", [(k, str(v)) for k, v in meta.items()])
    for a in run.agents:
        p = run.profiles.get(a.id) if run.profiles else None
        c.execute("INSERT INTO feedbench_user VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (a.id, a.community, p.community_name if p else COMMUNITY_NAMES[a.community % 3],
                   p.location if p else "", p.joined if p else "", int(bool(p and p.jewish_identity)),
                   int(a.in_harm_cluster), int(a.counter_speaker), a.activity, a.persona(), a.driver))
    c.executemany("INSERT INTO feedbench_post_label VALUES (?,?,?,?,?)",
                  [(pid, m.get("label", "unlabeled"), m.get("key", "organic"), int(bool(m.get("control"))),
                    m.get("lean", 0.0)) for pid, m in run.posts.items()])
    c.executemany("INSERT INTO feedbench_comment_label VALUES (?,?)", list(getattr(run, "comment_labels", {}).items()))
    c.executemany("INSERT INTO feedbench_session VALUES (?,?,?,?)",
                  [(s["round"], s["agent"], int(s["left_early"]), int(s["churned"])) for s in run.sessions])
    c.executemany("INSERT INTO feedbench_snapshot VALUES (?,?,?,?,?,?,?,?)",
                  [(s["round"], s["post_id"], *(s["e"] + [0, 0, 0])[:3], s["popA"], s["popB"], s.get("pop", 0))
                   for s in run.snapshots])
    con.commit()
    con.close()


# ---------- reading ----------

class DbAgent:
    """What the exporters need from an agent, rebuilt from the database."""

    def __init__(self, row: dict):
        self.id = row["user_id"]
        self.community = row.get("community", 0) or 0
        self.in_harm_cluster = bool(row.get("in_harm_cluster"))
        self.counter_speaker = bool(row.get("counter_speaker"))
        self.activity = row.get("activity") or 0.0
        self.driver = row.get("driver") or "scripted"
        self._persona = row.get("persona") or ""

    def persona(self) -> str:
        return self._persona


@dataclass
class DbRun:
    """Same fields as simulation.RunResult, rebuilt from an OASIS database."""
    policy: str
    seed: int
    impressions: list
    actions: list
    sessions: list
    posts: dict
    agents: list
    db_path: str
    errors: list = field(default_factory=list)
    snapshots: list = field(default_factory=list)
    scenario: str = ""
    profiles: dict = field(default_factory=dict)


def _has(con, table: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _rows(con, sql: str, params=()) -> list[dict]:
    cur = con.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def load_label_csv(path: str | Path) -> tuple[dict, dict]:
    """Expert labels for a database without feedbench tables. CSV columns: kind (post|comment), id, label."""
    import csv
    posts, comments = {}, {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            (comments if row.get("kind", "post") == "comment" else posts)[int(row["id"])] = row["label"].strip()
    return posts, comments


def scenario_text_labels(scenario_path: str | Path) -> dict:
    """Map exact post text -> scenario entry, to label scenario posts found in any OASIS database."""
    data = json.loads(Path(scenario_path).read_text(encoding="utf-8"))
    return {p["text"]: p for p in data["posts"]}


def run_from_db(db_path: str | Path, policy: str | None = None, seed: int | None = None,
                post_labels: dict | None = None, comment_labels: dict | None = None,
                text_labels: dict | None = None) -> DbRun:
    con = sqlite3.connect(str(db_path))
    fb = _has(con, "feedbench_run")
    meta = dict(con.execute("SELECT key, value FROM feedbench_run").fetchall()) if fb else {}
    policy = policy or meta.get("policy", Path(db_path).stem)
    seed = int(seed if seed is not None else meta.get("seed", 0))

    users = {r["user_id"]: r for r in _rows(con, "SELECT user_id, user_name, name, bio, num_followings, num_followers FROM user")}
    extra = {r["user_id"]: r for r in _rows(con, "SELECT * FROM feedbench_user")} if _has(con, "feedbench_user") else {}
    follows: dict[int, set] = {}
    for f, e in con.execute("SELECT follower_id, followee_id FROM follow"):
        follows.setdefault(f, set()).add(e)
    agents, profiles = [], {}
    for uid in sorted(users):
        u, x = users[uid], extra.get(uid, {"user_id": uid})
        agents.append(DbAgent({**x, "user_id": uid}))
        comm = x.get("community", 0) or 0
        profiles[uid] = Profile(id=uid, name=u["name"] or f"User {uid}", handle=u["user_name"] or f"user{uid}",
                                bio=u["bio"] or "", location=x.get("location", "") or "", joined=x.get("joined", "") or "",
                                community_name=x.get("community_name") or COMMUNITY_NAMES[comm % 3],
                                following=u["num_followings"] or len(follows.get(uid, ())),
                                followers=u["num_followers"] or 0, jewish_identity=bool(x.get("jewish_identity")))
    comm_of = {a.id: a.community for a in agents}

    labels = ({r["post_id"]: r for r in _rows(con, "SELECT * FROM feedbench_post_label")}
              if _has(con, "feedbench_post_label") else {})
    posts = {}
    for r in _rows(con, "SELECT post_id, user_id, content, CAST(created_at AS INTEGER) AS t FROM post "
                        "WHERE original_post_id IS NULL ORDER BY post_id"):
        lab = labels.get(r["post_id"])
        if lab is None:     # no feedbench table: expert CSV, then scenario text, then unlabeled
            text = r["content"] or ""
            sc = (text_labels or {}).get(text)
            lab = {"label": (post_labels or {}).get(r["post_id"]) or (sc["label"] if sc else None)
                   or ("harmful" if text.startswith("[HARMFUL PLACEHOLDER") else "unlabeled"),
                   "scenario_key": sc["id"] if sc else "organic", "is_control": bool(sc and sc.get("control")),
                   "lean": sc["lean"] if sc else 0.0}
        posts[r["post_id"]] = {"label": lab.get("label", "unlabeled"), "key": lab.get("scenario_key", "organic"),
                               "text": r["content"] or "", "lean": lab.get("lean", 0.0), "author": r["user_id"],
                               "round": r["t"], "control": bool(lab.get("is_control"))}
    clabels = dict(con.execute("SELECT comment_id, label FROM feedbench_comment_label").fetchall()) \
        if _has(con, "feedbench_comment_label") else {}
    comments = _rows(con, "SELECT comment_id, post_id, user_id, content, CAST(created_at AS INTEGER) AS t "
                          "FROM comment ORDER BY comment_id")
    if not _has(con, "feedbench_comment_label"):
        from .profiles import COUNTER_REPLIES
        for cm in comments:
            text = cm["content"] or ""
            clabels[cm["comment_id"]] = ((comment_labels or {}).get(cm["comment_id"])
                                         or ("harmful" if text.startswith("[HARMFUL PLACEHOLDER") else
                                             "counter" if text in COUNTER_REPLIES or text.startswith("Counterspeech")
                                             else "unlabeled"))

    # impressions: every OASIS refresh, in delivered order
    counter_by_post: dict[int, list[int]] = {}
    for cm in comments:
        if clabels.get(cm["comment_id"]) == "counter":
            counter_by_post.setdefault(cm["post_id"], []).append(cm["t"])
    impressions = []
    for r in _rows(con, "SELECT user_id, CAST(created_at AS INTEGER) AS t, info FROM trace WHERE action='refresh' "
                        "ORDER BY rowid"):
        try:
            info = json.loads(r["info"] or "{}")
        except ValueError:
            continue
        slots, scores = info.get("slots") or [], info.get("scores") or []
        for pos, pid in enumerate(info.get("posts") or []):
            m = posts.get(pid, {"label": "unlabeled", "key": "", "author": None})
            sc = scores[pos] if pos < len(scores) else [0, 0, 0, 0]
            impressions.append({
                "round": r["t"], "agent": r["user_id"], "agent_community": comm_of.get(r["user_id"], 0),
                "post_id": pid, "key": m["key"], "label": m["label"], "position": pos,
                "slot": SLOT_NAMES.get(slots[pos], slots[pos]) if pos < len(slots) else "recommended",
                "score": sc[0], "popularity": sc[1], "social": sc[2], "recency": sc[3],
                "author_community": comm_of.get(m["author"], 0),
                "counter_replies_shown": sum(1 for ct in counter_by_post.get(pid, []) if ct < r["t"]),
            })

    # actions: canonical OASIS tables
    def row(t, uid, action, pid, text_label="", text=None):
        target = posts.get(pid, {"label": "unlabeled", "key": "", "author": None})
        out = {"round": t, "agent": uid, "agent_community": comm_of.get(uid, 0), "action": action, "post_id": pid,
               "target_label": target["label"], "text_label": text_label,
               "driver": "scenario" if action == "create_post" and target["key"] not in ("organic", "") else "agent",
               "target_author_community": comm_of.get(target["author"])}
        if text is not None:
            out["text"] = text[:200]
        return out

    actions = [row(p["round"], p["author"], "create_post", pid, p["label"]) for pid, p in posts.items()]
    actions += [row(r["t"], r["user_id"], "like", r["post_id"])
                for r in _rows(con, "SELECT user_id, post_id, CAST(created_at AS INTEGER) AS t FROM 'like' ORDER BY like_id")]
    actions += [row(r["t"], r["user_id"], "repost", r["original_post_id"])
                for r in _rows(con, "SELECT user_id, original_post_id, CAST(created_at AS INTEGER) AS t FROM post "
                                    "WHERE original_post_id IS NOT NULL ORDER BY post_id")]
    actions += [row(cm["t"], cm["user_id"], "comment", cm["post_id"], clabels.get(cm["comment_id"], "unlabeled"),
                    cm["content"] or "") for cm in comments]
    actions.sort(key=lambda a: a["round"])

    if _has(con, "feedbench_session"):
        sessions = [{"round": r["round"], "agent": r["user_id"], "community": comm_of.get(r["user_id"], 0),
                     "driver": "", "left_early": bool(r["left_early"]), "churned": bool(r["churned"])}
                    for r in _rows(con, "SELECT * FROM feedbench_session")]
    else:   # infer: a user who refreshed in a round opened the app
        seen = sorted({(i["round"], i["agent"]) for i in impressions})
        sessions = [{"round": t, "agent": a, "community": comm_of.get(a, 0), "driver": "", "left_early": False,
                     "churned": False} for t, a in seen]
    snapshots = ([{"round": r["round"], "post_id": r["post_id"], "e": [r["e0"], r["e1"], r["e2"]],
                   "popA": r["pop_total"], "popB": r["pop_capped"], "pop": r["pop_rule"]}
                  for r in _rows(con, "SELECT * FROM feedbench_snapshot")] if _has(con, "feedbench_snapshot") else [])
    con.close()
    run = DbRun(policy, seed, impressions, actions, sessions, posts, agents, str(db_path),
                snapshots=snapshots, scenario=meta.get("scenario", ""), profiles=profiles)
    run.has_harm_labels = any(m["label"] == "harmful" for m in posts.values())
    return run
