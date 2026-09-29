"""Scenario loading and the per-post view the ranking rules receive.

Posts, likes, reposts and comments live in the OASIS SQLite database.
Every round, oasis_platform.py rebuilds a `PostView` for each eligible post from
that database and hands it to ranking.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import random

HARMFUL = "harmful"
LABELS = ("benign", "news", "counter", "harmful")


@dataclass
class PostView:
    post_id: int                # OASIS post_id
    author: int
    author_community: int
    created_round: int
    # distinct likers/reposters per community  (the endorsement signal)
    endorsers_by_comm: dict[int, int] = field(default_factory=dict)
    # distinct likers/reposters/commenters per community (only for *_with_replies variants)
    engagers_by_comm: dict[int, int] = field(default_factory=dict)
    endorsers: set[int] = field(default_factory=set)
    reposters: set[int] = field(default_factory=set)
    # NOT visible to ranking rules; used only by the evaluator, agents and the inspector
    label: str = "benign"
    key: str = ""               # scenario id, e.g. "H1", "M1", or "organic"

    @property
    def total_endorsements(self) -> int:
        return sum(self.endorsers_by_comm.values())


def load_scenario(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def resolve_author(spec: str, agents, rng: random.Random, profiles: dict | None = None,
                   trait: str | None = None) -> int | None:
    """Map an author spec from the scenario file to a concrete agent id (deterministic per seed).

    `trait="jewish"` narrows the pool to users whose generated profile has a Jewish identity
    (falls back to the whole pool if there is none in that community).
    """
    if spec == "harm_cluster":
        pool = [a for a in agents if a.in_harm_cluster]
    elif spec.startswith("community:"):
        c = int(spec.split(":")[1])
        pool = [a for a in agents if a.community == c and not a.in_harm_cluster]
    else:
        return int(spec)
    if trait == "jewish" and profiles:
        pool = [a for a in pool if profiles[a.id].jewish_identity] or pool
    return rng.choice(pool).id if pool else None
