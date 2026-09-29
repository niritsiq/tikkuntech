"""Your ranking rules go here.

A rule changes how posts are ordered; everything else (population, follow graph,
posts, agent behaviour, random draws) stays identical, so any difference in the
replay comes from the rule alone.

Two ways to write one:

1. Popularity rule: replace the endorsement boost.
       p.endorsers_by_comm   {community: distinct likers/reposters}
       p.engagers_by_comm    same, including repliers
       p.endorsers, p.reposters, p.author, p.author_community, p.created_round
       cfg.community_cap and the other RankingConfig weights

2. Score adjustment: change any part of the score (popularity / social / recency).
       adjust(parts, p, viewer, now, cfg) -> parts
       viewer.follows, viewer.author_affinity

Rules must NOT read p.label: antisemitism is measured afterwards, never used by the ranker.
(A rule that simulates a classifier must model its errors explicitly.)

Then:  python build_lab.py --rules total_endorsements community_capped <your_key>
"""
from __future__ import annotations

from .ranking import register_rule


# --- example (remove or edit) ------------------------------------------------------------
def _diminishing(p, cfg):
    """Each community's support counts with diminishing returns: sum of sqrt(e_i)."""
    return float(sum(e ** 0.5 for e in p.endorsers_by_comm.values()))


register_rule("diminishing", "D · Diminishing returns per community (√eᵢ)", popularity=_diminishing)


def _cross_community_bonus(parts, p, viewer, now, cfg):
    """Keep total endorsements, but add +1 for every community beyond the first that endorsed."""
    reached = sum(1 for e in p.endorsers_by_comm.values() if e > 0)
    parts["popularity"] += max(0, reached - 1)
    return parts


register_rule("breadth_bonus", "E · Total + bonus for cross-community support", adjust=_cross_community_bonus)
