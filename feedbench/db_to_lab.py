"""Build the lab page directly from OASIS SQLite databases.

Use this to plug in OASIS runs produced elsewhere (your own integration, another team, an
LLM run). Every figure on the page is recomputed from the databases' standard OASIS tables
(user, follow, post, comment, like, trace); FeedBench's `feedbench_*` tables add labels and
roles when present.

  python db_to_lab.py runs_full/coordinated_*_seed1.db
  python db_to_lab.py --dir runs_full --baseline total_endorsements
  python db_to_lab.py a.db b.db --policy-from-name --title "Our integration"

Databases are grouped by (scenario, seed, policy) from their feedbench_run table, or from
the file name with --policy-from-name (<anything>_<policy>_seed<N>.db).
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
from collections import defaultdict
from pathlib import Path

from build_lab import build_page, rule_docs
from feedbench.config import POLICIES, SCENARIOS, make_config
from feedbench.export import _versions, scenario_block
from feedbench.oasis_db import run_from_db
from feedbench.ranking import POPULARITY

HERE = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dbs", nargs="*")
    ap.add_argument("--dir", help="use every *.db in this folder")
    ap.add_argument("--baseline", default="total_endorsements")
    ap.add_argument("--policy-from-name", action="store_true")
    ap.add_argument("--title", default="")
    ap.add_argument("--labels", help="expert labels CSV: kind,id,label (kind = post or comment)")
    ap.add_argument("--scenario-json", default=str(HERE / "data" / "scenario.json"),
                    help="label posts whose text matches this scenario file")
    ap.add_argument("--out", default=str(HERE.parent / "FeedBench-Algorithm-Lab.html"))
    a = ap.parse_args()
    paths = [Path(p) for p in a.dbs] + (sorted(Path(a.dir).glob("*.db")) if a.dir else [])
    if not paths:
        raise SystemExit("No databases given.")

    from feedbench.oasis_db import load_label_csv, scenario_text_labels
    post_labels, comment_labels = load_label_csv(a.labels) if a.labels else ({}, {})
    text_labels = scenario_text_labels(a.scenario_json) if a.scenario_json and Path(a.scenario_json).exists() else {}
    groups = defaultdict(list)
    for path in paths:
        policy = seed = None
        if a.policy_from_name:
            m = re.search(r"_([a-z_]+?)(?:_cap\d+)?_seed(\d+)\.db$", path.name)
            if m:
                policy, seed = m.group(1), int(m.group(2))
        run = run_from_db(path, policy, seed, post_labels, comment_labels, text_labels)
        groups[run.scenario or "imported"].append(run)
        print(f"{path.name}: scenario={run.scenario or 'imported'} policy={run.policy} seed={run.seed} "
              f"impressions={len(run.impressions)} actions={len(run.actions)}")

    blocks, rules = [], set()
    for scen, runs in groups.items():
        rounds = max((i["round"] for r in runs for i in r.impressions), default=0) + 1
        cfg = make_config(scen if scen in SCENARIOS else "coordinated", rounds=rounds, baseline=a.baseline,
                          seeds=sorted({r.seed for r in runs}), policies=sorted({r.policy for r in runs}))
        cfg.scenario = scen
        block = scenario_block(cfg, runs, replay_seed=min(r.seed for r in runs))
        block["mode"] = "llm" if any(ag.driver == "llm" for ag in runs[0].agents) else "scripted"
        block["has_harm_labels"] = any(getattr(r, "has_harm_labels", False) for r in runs)
        if a.title:
            block["title"] = a.title + ("" if len(groups) == 1 else f" · {scen}")
        blocks.append(block)
        rules |= {r.policy for r in runs}
    known = [k for k in rules if k in POPULARITY]
    docs = rule_docs(known)
    docs.update({k: {"label": POLICIES.get(k, k), "doc": "Imported from an OASIS database."} for k in rules - set(known)})
    doc = {"generated": dt.datetime.now().isoformat(timespec="seconds"),
           "engine": "CAMEL OASIS databases (user, follow, post, comment, like, trace)", "versions": _versions(),
           "baseline": a.baseline, "cap": "see config", "rules": docs, "scenarios": blocks,
           "disclaimer": ("Synthetic users under declared assumptions. Illustrates a ranking mechanism; does not "
                          "estimate effects on a real platform or establish a legal conclusion.")}
    build_page(doc, Path(a.out))


if __name__ == "__main__":
    main()
