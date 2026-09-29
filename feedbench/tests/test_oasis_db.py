"""The OASIS database alone reproduces the run (python -m pytest tests -q -m oasis; ~1 min)."""
import asyncio

import pytest

from feedbench.config import make_config
from feedbench.metrics import run_totals
from feedbench.simulation import run_single


@pytest.mark.oasis
def test_database_reproduces_logged_run(tmp_path):
    cfg = make_config("coordinated", rounds=8, workdir=str(tmp_path))
    run = asyncio.run(run_single(cfg, "community_capped", 1, record_snapshots=True))
    logged = run.logged
    assert run_totals(run, cfg.rounds) == run_totals(logged, cfg.rounds)
    key = lambda imps: sorted((i["round"], i["agent"], i["position"], i["post_id"], i["slot"], i["score"]) for i in imps)
    assert key(run.impressions) == key(logged.impressions)
    assert {p: m["label"] for p, m in run.posts.items()} == {p: m["label"] for p, m in logged.posts.items()}
    assert [u.handle for u in run.profiles.values()] == [p.handle for p in logged.profiles.values()]
