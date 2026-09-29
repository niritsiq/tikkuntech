"""Run the ranking rules on CAMEL OASIS and build FeedBench-Algorithm-Lab.html.

The page replays genuinely computed OASIS runs: the same synthetic Twitter users,
follow graph and posts under a "before" rule and an "after" rule, with the feeds
each user was shown, antisemitic exposure and ordinary engagement.

Examples
  python build_lab.py                        # scripted agents (free, offline), all scenarios
  python build_lab.py --quick                # 1 seed, 2 scenarios: fast check of the page
  python build_lab.py --rules total_endorsements community_capped my_rule
  python build_lab.py --from-json results/lab.json      # rebuild the page only

LLM agents (OpenAI, per the OASIS quick start) are produced by run_llm.py and can
be merged here with --add-json results/lab_llm.json.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import time
from pathlib import Path

from feedbench.config import POLICIES, SCENARIOS, make_config
from feedbench.export import _clean, _versions, scenario_block
from feedbench.ranking import ADJUSTERS, POPULARITY
from feedbench.simulation import run_many

HERE = Path(__file__).resolve().parent
DEFAULT_RULES = ["total_endorsements", "community_capped", "diminishing", "breadth_bonus", "bridging", "chronological"]


def rule_docs(keys) -> dict:
    out = {}
    for k in keys:
        fn = ADJUSTERS.get(k) or POPULARITY[k]
        out[k] = {"label": POLICIES.get(k, k), "doc": (fn.__doc__ or "").strip().split("\n")[0]}
    return out


async def run_all(args) -> dict:
    blocks = []
    for scen in args.scenarios:
        cfg = make_config(scen, seeds=args.seeds, workdir=args.workdir, policies=args.rules, rounds=args.rounds)
        if args.profiles:
            from feedbench.profiles import count_oasis_profiles
            cfg.profiles_path = args.profiles
            cfg.network.n_agents = count_oasis_profiles(args.profiles)
        cfg.ranking.community_cap = args.cap
        t = time.time()
        runs = await run_many(cfg, snapshot_seed=args.seeds[0])
        block = scenario_block(cfg, runs, replay_seed=args.seeds[0])
        block["mode"] = "scripted"
        blocks.append(block)
        print(f"[{scen}] {len(runs)} OASIS runs in {time.time() - t:.0f}s", flush=True)
    return {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "engine": "CAMEL OASIS, Twitter mode, custom FeedBenchPlatform (ranked feeds delivered in exact order)",
        "versions": _versions(),
        "baseline": "total_endorsements",
        "cap": args.cap,
        "rules": rule_docs(args.rules),
        "scenarios": blocks,
        "disclaimer": ("Synthetic users under declared assumptions. Illustrates a ranking mechanism; does not "
                       "estimate effects on a real platform or establish a legal conclusion."),
    }


def build_page(doc: dict, out: Path) -> None:
    payload = json.dumps(doc, separators=(",", ":"), ensure_ascii=False, default=_clean).replace("</", "<\\/")
    page = (HERE / "lab_template.html").read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote {out} ({len(page) / 1e6:.1f} MB)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenarios", nargs="+", default=list(SCENARIOS), choices=list(SCENARIOS))
    ap.add_argument("--rules", nargs="+", default=DEFAULT_RULES, choices=list(POPULARITY))
    ap.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--cap", type=int, default=2)
    ap.add_argument("--profiles", default="", help="real OASIS profile file, e.g. data/oasis/user_data_36.json")
    ap.add_argument("--quick", action="store_true", help="1 seed, coordinated + benign_cascade")
    ap.add_argument("--workdir", default="runs")
    ap.add_argument("--json", default=str(HERE / "results" / "lab.json"))
    ap.add_argument("--from-json", help="skip simulation and rebuild the page from this file")
    ap.add_argument("--add-json", nargs="*", default=[], help="merge extra scenario blocks (e.g. LLM runs)")
    ap.add_argument("--out", default=str(HERE.parent / "FeedBench-Algorithm-Lab.html"))
    a = ap.parse_args()
    if a.quick:
        a.seeds, a.scenarios = a.seeds[:1], ["coordinated", "benign_cascade"]
    if "total_endorsements" not in a.rules:
        a.rules = ["total_endorsements"] + a.rules

    if a.from_json:
        doc = json.loads(Path(a.from_json).read_text(encoding="utf-8"))
    else:
        doc = asyncio.run(run_all(a))
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False, default=_clean),
                                encoding="utf-8")
        print(f"Wrote {a.json}")
    for extra in a.add_json:
        more = json.loads(Path(extra).read_text(encoding="utf-8"))
        doc["scenarios"] += more["scenarios"]
        doc["rules"].update(more.get("rules", {}))
    build_page(doc, Path(a.out))


if __name__ == "__main__":
    main()
