"""Interface A: ranking rules (the thing researchers modify).

Input : eligible posts (PostView), the viewer, the ranking config.
Output: an ORDERED list of posts — exactly what the agent sees in OASIS.

Rules never read the expert `label`. Antisemitism is measured afterwards, so any
difference between rules comes from the scoring mechanics alone.

Endorsement e_i = number of DISTINCT agents from network community i who liked or
reposted the post. Replies are not endorsements (declared choice; see the
*_with_replies variants for the alternative).

The two rules compared in the benchmark:
    A  total_endorsements : popularity = sum_i e_i
    B  community_capped   : popularity = sum_i min(cap, e_i)

Everything else in the score is identical for every rule:
    + follow bonus (viewer follows the author)
    + endorsements by accounts the viewer follows (max 3)
    + viewer's past engagement with the author (max 3)
    + recency decay

To add a rule: write a popularity function and register it in POPULARITY.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable

from .config import RankingConfig
from .content import PostView


# ---- primary rules --------------------------------------------------------------

def pop_total_endorsements(p: PostView, cfg: RankingConfig) -> float:
    """A: every distinct endorsement adds to the boost."""
    return float(sum(p.endorsers_by_comm.values()))


def pop_community_capped(p: PostView, cfg: RankingConfig) -> float:
    """B: endorsements beyond `cap` from the same community stop adding boost."""
    return float(sum(min(cfg.community_cap, e) for e in p.endorsers_by_comm.values()))


# ---- further-work variants (not part of the headline comparison) ----------------

def pop_total_with_replies(p: PostView, cfg: RankingConfig) -> float:
    return float(sum(p.engagers_by_comm.values()))


def pop_capped_with_replies(p: PostView, cfg: RankingConfig) -> float:
    return float(sum(min(cfg.community_cap, e) for e in p.engagers_by_comm.values()))


def pop_bridging(p: PostView, cfg: RankingConfig) -> float:
    """Törnberg et al. 2023-style: only endorsements from OTHER communities count."""
    return float(sum(e for c, e in p.endorsers_by_comm.items() if c != p.author_community))


def pop_none(p: PostView, cfg: RankingConfig) -> float:
    """Chronological/network control: no popularity term."""
    return 0.0


POPULARITY: dict[str, Callable[[PostView, RankingConfig], float]] = {
    "total_endorsements": pop_total_endorsements,
    "community_capped": pop_community_capped,
    "total_with_replies": pop_total_with_replies,
    "capped_with_replies": pop_capped_with_replies,
    "bridging": pop_bridging,
    "chronological": pop_none,
}


# Optional per-rule adjustment of the full score (see custom_rules.py):
#   adjust(parts, post, viewer, now, cfg) -> parts   with keys popularity / social / recency
ADJUSTERS: dict[str, Callable] = {}


def register_rule(key: str, label: str, popularity: Callable | None = None, adjust: Callable | None = None):
    """Add a ranking rule. It then appears in run_benchmark/build_lab choices and in the lab UI."""
    from .config import POLICIES
    POPULARITY[key] = popularity or pop_total_endorsements
    if adjust:
        ADJUSTERS[key] = adjust
    POLICIES[key] = label


@dataclass
class Viewer:
    """What the ranker knows about the viewer (identical under every rule)."""
    id: int
    follows: set[int] = field(default_factory=set)
    author_affinity: dict[int, int] = field(default_factory=dict)   # past engagements per author


def score_post(p: PostView, viewer: Viewer, now: int, policy: str, cfg: RankingConfig) -> dict:
    pop = POPULARITY[policy](p, cfg)
    social = cfg.w_follow_author if p.author in viewer.follows else 0.0
    social += cfg.w_followed_endorser * min(3, len(p.endorsers & viewer.follows))
    social += cfg.w_author_affinity * min(3, viewer.author_affinity.get(p.author, 0))
    recency = cfg.w_recency * (cfg.recency_decay ** max(0, now - p.created_round))
    parts = {"popularity": pop, "social": social, "recency": recency}
    if policy in ADJUSTERS:
        parts = ADJUSTERS[policy](dict(parts), p, viewer, now, cfg)
    return {**parts, "total": cfg.w_popularity * parts["popularity"] + parts["social"] + parts["recency"]}


def build_feed(candidates: list[PostView], viewer: Viewer, now: int, policy: str,
               cfg: RankingConfig, rng: random.Random) -> list[tuple[PostView, dict]]:
    """Feed = in-network slots + recommended slots + exploration slot(s).

    In-network = posts by (or reposted by) accounts the viewer follows. Both the
    in-network and recommended sections are ordered by the rule's score. The
    exploration slot is a random eligible post, identical rule under A and B, so new
    posts can reach people outside their home community.
    """
    scored = [(p, score_post(p, viewer, now, policy, cfg)) for p in candidates]
    scored.sort(key=lambda ps: (-ps[1]["total"], -ps[0].created_round, ps[0].post_id))
    in_net = [ps for ps in scored if ps[0].author in viewer.follows or ps[0].reposters & viewer.follows]
    feed = [(p, {**s, "slot": "in-network"}) for p, s in in_net[:cfg.in_network_slots]]
    taken = {p.post_id for p, _ in feed}
    n_rec = max(0, cfg.feed_size - cfg.exploration_slots - len(feed))
    rec = [ps for ps in scored if ps[0].post_id not in taken][:n_rec]
    feed += [(p, {**s, "slot": "recommended"}) for p, s in rec]
    taken |= {p.post_id for p, _ in rec}
    rest = [ps for ps in scored if ps[0].post_id not in taken]
    n_explore = min(cfg.feed_size - len(feed), len(rest))
    for i in (sorted(rng.sample(range(len(rest)), n_explore)) if n_explore > 0 else []):
        p, s = rest[i]
        feed.append((p, {**s, "slot": "exploration"}))
    return feed


from . import custom_rules  # noqa: E402,F401  (registers user-supplied rules)
