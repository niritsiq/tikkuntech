"""Run the TikkunTech ranking benchmark on CAMEL OASIS and export results for the replay.

Examples
  python run_benchmark.py                         # all scenarios, 5 seeds, cap sweep
  python run_benchmark.py --quick                 # 2 seeds, no sweep (~30 s)
  python run_benchmark.py --cap 3                 # try a different community cap
  python run_benchmark.py --scenarios coordinated --seeds 1 2 3 4 5 6 7 8 9 10
  python run_benchmark.py --extra chronological   # add a further-work rule as a third condition

Then:  python build_replay.py   ->  replay.html
"""
from __future__ import annotations

import argparse
import asyncio
import time

from feedbench.config import PRIMARY, POLICIES, SCENARIOS, make_config
from feedbench.export import scenario_block, write_outputs
from feedbench.metrics import summarize
from feedbench.simulation import run_many


async def main(args) -> None:
    blocks, sensitivity = [], []
    for scen in args.scenarios:
        cfg = make_config(scen, seeds=args.seeds, workdir=args.workdir,
                          policies=PRIMARY + args.extra)
        cfg.ranking.community_cap = args.cap
        t = time.time()
        runs = await run_many(cfg, snapshot_seed=args.seeds[0])
        blocks.append(scenario_block(cfg, runs, replay_seed=args.seeds[0]))
        s, _ = summarize(runs, cfg.rounds, cfg.baseline, cfg)
        print(f"\n[{scen}] {SCENARIOS[scen]['title']}  ({len(runs)} OASIS runs, {time.time() - t:.0f}s)")
        for _, r in s.iterrows():
            print(f"  {r['label']:<42} antisemitic impr. {r['harmful_impressions']:6.1f}"
                  f"  x{r['harm_ratio']:.2f}  | ordinary eng. x{r['engagement_ratio']:.2f}"
                  f"  | counterspeech x{r['counterspeech_ratio'] if r['counterspeech_ratio'] == r['counterspeech_ratio'] else float('nan'):.2f}"
                  f"  | {r['verdict']}")

    if args.sweep:
        scen = args.scenarios[0]
        base_cfg = make_config(scen, seeds=args.seeds, workdir=args.workdir, policies=["total_endorsements"])
        base = await run_many(base_cfg)
        for cap in args.sweep:
            cfg = make_config(scen, seeds=args.seeds, workdir=args.workdir, policies=["community_capped"])
            cfg.ranking.community_cap = cap
            runs = await run_many(cfg)
            s, _ = summarize(base + runs, cfg.rounds, cfg.baseline, cfg)
            r = s[s["policy"] == "community_capped"].iloc[0]
            sensitivity.append({"scenario": scen, "cap": cap,
                                **{k: r[k] for k in ("harm_ratio", "harm_ratio_min", "harm_ratio_max",
                                                     "engagement_ratio", "engagement_ratio_min", "engagement_ratio_max",
                                                     "counterspeech_ratio", "control_ratio")}})
            print(f"  cap={cap}: antisemitic x{r['harm_ratio']:.2f}  ordinary x{r['engagement_ratio']:.2f}"
                  f"  counterspeech x{r['counterspeech_ratio']:.2f}")

    path = write_outputs(blocks, sensitivity, args.out)
    print(f"\nWrote {path} (+ CSVs). Build the replay with: python build_replay.py")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenarios", nargs="+", default=list(SCENARIOS), choices=list(SCENARIOS))
    ap.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    ap.add_argument("--cap", type=int, default=2, help="community cap for rule B")
    ap.add_argument("--sweep", nargs="*", type=int, default=[1, 2, 3, 4],
                    help="cap values for the sensitivity sweep on the first scenario (empty = skip)")
    ap.add_argument("--extra", nargs="*", default=[], choices=[p for p in POLICIES if p not in PRIMARY],
                    help="further-work rules to add as extra conditions")
    ap.add_argument("--quick", action="store_true", help="2 seeds, no sweep")
    ap.add_argument("--workdir", default="runs", help="OASIS SQLite databases")
    ap.add_argument("--out", default="results")
    a = ap.parse_args()
    if a.quick:
        a.seeds, a.sweep = a.seeds[:2], []
    asyncio.run(main(a))
