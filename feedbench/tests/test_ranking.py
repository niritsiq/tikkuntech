"""Acceptance checks for Interface A (run: python -m pytest tests -q)."""
import random

from feedbench.config import RankingConfig
from feedbench.content import PostView
from feedbench.ranking import Viewer, build_feed, pop_community_capped, pop_total_endorsements


def post(pid, by_comm, label="benign", author=99, comm=0, created=5):
    return PostView(post_id=pid, author=author, author_community=comm, created_round=created,
                    endorsers_by_comm=by_comm, label=label)


def test_worked_example_from_scope():
    cfg = RankingConfig(community_cap=2)
    x = post(1, {0: 12})               # concentrated support
    y = post(2, {0: 2, 1: 2, 2: 2})    # support across communities
    assert pop_total_endorsements(x, cfg) == 12 and pop_total_endorsements(y, cfg) == 6
    assert pop_community_capped(x, cfg) == 2 and pop_community_capped(y, cfg) == 6


def test_same_candidates_different_order():
    cfg = RankingConfig(feed_size=2, in_network_slots=0, exploration_slots=0)
    cands = [post(1, {0: 12}), post(2, {0: 2, 1: 2, 2: 2})]
    v = Viewer(id=0)
    a = [p.post_id for p, _ in build_feed(cands, v, 5, "total_endorsements", cfg, random.Random(0))]
    b = [p.post_id for p, _ in build_feed(cands, v, 5, "community_capped", cfg, random.Random(0))]
    assert a == [1, 2] and b == [2, 1]


def test_rules_never_read_labels():
    cfg = RankingConfig(feed_size=3, in_network_slots=0, exploration_slots=0)
    base = [post(1, {0: 5}), post(2, {1: 3}), post(3, {2: 1})]
    relabeled = [post(p.post_id, p.endorsers_by_comm, label="harmful") for p in base]
    v = Viewer(id=0)
    for rule in ("total_endorsements", "community_capped"):
        o1 = [p.post_id for p, _ in build_feed(base, v, 5, rule, cfg, random.Random(0))]
        o2 = [p.post_id for p, _ in build_feed(relabeled, v, 5, rule, cfg, random.Random(0))]
        assert o1 == o2


def test_every_registered_rule_ignores_labels():
    from feedbench.ranking import POPULARITY
    cfg = RankingConfig(feed_size=3, in_network_slots=0, exploration_slots=0)
    base = [post(1, {0: 5}), post(2, {1: 3, 2: 1}), post(3, {2: 1})]
    relabeled = [post(p.post_id, p.endorsers_by_comm, label="harmful") for p in base]
    v = Viewer(id=0)
    for rule in POPULARITY:
        o1 = [p.post_id for p, _ in build_feed(base, v, 5, rule, cfg, random.Random(0))]
        o2 = [p.post_id for p, _ in build_feed(relabeled, v, 5, rule, cfg, random.Random(0))]
        assert o1 == o2, rule


def test_profiles_are_deterministic_and_unique():
    from feedbench.config import NetworkConfig
    from feedbench.network import build_population
    from feedbench.profiles import make_profiles
    agents = build_population(NetworkConfig(), 1)
    a, b = make_profiles(agents, 1), make_profiles(agents, 1)
    assert [p.handle for p in a.values()] == [p.handle for p in b.values()]
    assert len({p.handle.lower() for p in a.values()}) == len(agents)
