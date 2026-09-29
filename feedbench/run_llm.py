"""LLM-driven OASIS run, following the OASIS quick start (oasis.make + ManualAction + LLMAction).

  1. generate fictional Twitter users   -> data/twitter_users_seed<N>.csv  (OASIS Twitter profile format)
  2. generate_twitter_agent_graph(...)  -> one OASIS SocialAgent per user, driven by an OpenAI model
  3. oasis.make(platform=FeedBenchPlatform)  -> OASIS environment whose feeds follow OUR ranking rule
  4. every round: scenario posts as ManualAction, active users as LLMAction, env.step()
  5. export in the same format as build_lab.py, so the lab page can show it

Costs money. The script prints an estimate and stops unless you pass --yes.

  set OPENAI_API_KEY=...                    (PowerShell: $env:OPENAI_API_KEY="...")
  python run_llm.py --agents 20 --rounds 10                 # estimate only
  python run_llm.py --agents 20 --rounds 10 --yes           # run
  python build_lab.py --from-json results/lab.json --add-json results/lab_llm.json

Caveats: LLM-written posts and replies are NOT labelled (shown as "unlabeled"); experts must
review them before any claim. Scenario antisemitic posts are still placeholders, so LLM
reactions to them only become meaningful once experts supply reviewed examples.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import random
from pathlib import Path

os.makedirs("log", exist_ok=True)   # OASIS writes ./log/*.log on import

import oasis                                                        # noqa: E402
from camel.models import ModelFactory                               # noqa: E402
from camel.types import ModelPlatformType, ModelType                # noqa: E402
from oasis import ActionType, LLMAction, ManualAction, generate_twitter_agent_graph  # noqa: E402
from oasis.social_platform.channel import Channel                   # noqa: E402

from feedbench.config import SCENARIOS, make_config                 # noqa: E402
from feedbench.content import load_scenario, resolve_author         # noqa: E402
from feedbench.export import _clean, _versions, scenario_block      # noqa: E402
from feedbench.network import build_population                      # noqa: E402
from feedbench.oasis_platform import FeedBenchPlatform              # noqa: E402
from feedbench.profiles import (make_profiles, load_oasis_profiles, count_oasis_profiles,  # noqa: E402
                                write_oasis_twitter_csv, enrich_bios_with_llm)
from feedbench.simulation import RunResult, _llm_actions_from_trace  # noqa: E402
from feedbench.oasis_db import run_from_db, write_feedbench_tables  # noqa: E402
from build_lab import rule_docs                                     # noqa: E402

HERE = Path(__file__).resolve().parent
ACTIONS = [ActionType.LIKE_POST, ActionType.REPOST, ActionType.CREATE_COMMENT,
           ActionType.CREATE_POST, ActionType.DO_NOTHING]
# Measured OASIS reference: ~3,356 input and ~168 output tokens per agent action (100 agents, QWEN_TURBO).
TOKENS_IN, TOKENS_OUT = 3356, 168


def make_openai_model(name: str):
    if name == "stub":                     # offline pipeline check; agents take no real actions
        return ModelFactory.create(model_platform=ModelPlatformType.OPENAI, model_type=ModelType.STUB)
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY first (see the docstring).")
    model_type = {"gpt-4o-mini": ModelType.GPT_4O_MINI, "gpt-4o": ModelType.GPT_4O}.get(name, name)
    return ModelFactory.create(model_platform=ModelPlatformType.OPENAI, model_type=model_type,
                               model_config_dict={"temperature": 0.7})


async def run_one(cfg, policy: str, seed: int, model, model_name: str, llm_bios: bool) -> RunResult:
    os.makedirs(cfg.workdir, exist_ok=True)
    db_path = os.path.join(cfg.workdir, f"llm_{cfg.scenario}_{policy}_seed{seed}.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    # 1. fictional users (same seed -> same users under every rule)
    agents = build_population(cfg.network, seed)
    by_id = {a.id: a for a in agents}
    for a in agents:
        a.driver = "llm"
    profiles = load_oasis_profiles(cfg.profiles_path, agents) if cfg.profiles_path else make_profiles(agents, seed)
    if llm_bios and model_name != "stub":
        enrich_bios_with_llm(agents, profiles, model)
    for a in agents:
        a.display_name, a.handle = profiles[a.id].name, profiles[a.id].handle
    csv_path = write_oasis_twitter_csv(agents, profiles, HERE / "data" / f"twitter_users_seed{seed}.csv")

    # 2. OASIS agent graph from the profile file (as in the quick start)
    agent_graph = await generate_twitter_agent_graph(profile_path=str(csv_path), model=model,
                                                     available_actions=ACTIONS)

    # 3. environment with our ranking platform
    post_meta: dict[int, dict] = {}
    platform = FeedBenchPlatform(db_path=db_path, channel=Channel(), policy=policy, ranking_cfg=cfg.ranking,
                                 agents=agents, post_meta=post_meta, seed=seed, record_snapshots=True)
    env = oasis.make(agent_graph=agent_graph, platform=platform, database_path=db_path)
    await env.reset()
    oa = dict(env.agent_graph.get_agents())
    await asyncio.gather(*[oa[a.id].env.action.follow(f) for a in agents for f in sorted(a.follows)])

    scenario = load_scenario(cfg.scenario_path)
    author_rng = random.Random(f"authors-{seed}")
    schedule: dict[int, list[dict]] = {}
    for p in scenario["posts"]:
        author = resolve_author(p["author"], agents, author_rng, profiles, p.get("author_trait"))
        if author is not None and (p["label"] != "harmful" or cfg.include_harmful_posts):
            schedule.setdefault(p["round"], []).append({**p, "author_id": author})

    sessions, errors = [], []
    for t in range(cfg.rounds):
        platform.sandbox_clock.time_step = t
        # 4a. scripted scenario posts (ManualAction)
        for p in schedule.get(t, []):
            res = await oa[p["author_id"]].perform_action_by_data(ActionType.CREATE_POST, content=p["text"])
            post_meta[res["post_id"]] = {"label": p["label"], "key": p["id"], "text": p["text"], "lean": p["lean"],
                                         "author": p["author_id"], "round": t, "control": p.get("control", False)}
        # 4b. who opens the app: same draws as the scripted runs
        rng = random.Random(f"open-{seed}-{t}")
        draws = {a.id: rng.random() for a in agents}
        active = [a for a in agents if draws[a.id] < a.activity]
        platform.feed_users = {a.id for a in active}
        actions = {oa[a.id]: LLMAction() for a in active}
        for a in active:
            sessions.append({"round": t, "agent": a.id, "community": a.community, "driver": "llm",
                             "feed_len": None, "left_early": False, "churned": False})
        await env.step(actions)          # ranks feeds (our rule), agents refresh + act through OASIS tools
        print(f"  {policy} round {t}: {len(active)} LLM agents acted", flush=True)

    # 5. recover LLM-written posts/replies from the OASIS database
    for pid, uid, content, created in platform._q(
            "SELECT post_id, user_id, content, CAST(created_at AS INTEGER) FROM post WHERE original_post_id IS NULL"):
        post_meta.setdefault(pid, {"label": "unlabeled", "key": "organic", "text": content or "", "lean": 0.0,
                                   "author": uid, "round": created})
    actions = _llm_actions_from_trace(platform, by_id, post_meta)
    for cid, pid, uid, content, created in platform._q(
            "SELECT comment_id, post_id, user_id, content, CAST(created_at AS INTEGER) FROM comment"):
        for row in actions:
            if row["action"] == "comment" and row["agent"] == uid and row["post_id"] == pid and "text" not in row:
                row["text"] = (content or "")[:200]
                break
    await env.close()
    result = RunResult(policy, seed, platform.impressions, actions, sessions, post_meta, agents, db_path,
                       errors, platform.snapshots, cfg.scenario, profiles)
    result.comment_labels = {}          # LLM replies stay unlabeled until experts review them
    write_feedbench_tables(db_path, result, cfg)
    return run_from_db(db_path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", default="coordinated", choices=list(SCENARIOS))
    ap.add_argument("--rules", nargs="+", default=["total_endorsements", "community_capped"])
    ap.add_argument("--agents", type=int, default=20)
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--model", default="gpt-4o-mini", help='OpenAI model name, or "stub" for an offline dry run')
    ap.add_argument("--llm-bios", action="store_true", help="let the model write the user bios too")
    ap.add_argument("--profiles", default="", help="OASIS profile file, e.g. data/oasis/user_data_36.json")
    ap.add_argument("--price-in", type=float, default=0.15, help="USD per 1M input tokens (check current pricing)")
    ap.add_argument("--price-out", type=float, default=0.60, help="USD per 1M output tokens (check current pricing)")
    ap.add_argument("--yes", action="store_true", help="actually run (costs money unless --model stub)")
    ap.add_argument("--workdir", default="runs_llm")
    ap.add_argument("--out", default=str(HERE / "results" / "lab_llm.json"))
    a = ap.parse_args()

    cfg = make_config(a.scenario, rounds=a.rounds, seeds=[a.seed], workdir=a.workdir, policies=a.rules)
    cfg.network.n_agents = count_oasis_profiles(a.profiles) if a.profiles else a.agents
    cfg.profiles_path = a.profiles
    cfg.network.harm_cluster_size = min(cfg.network.harm_cluster_size, max(0, a.agents // 5))
    agents = build_population(cfg.network, a.seed)
    calls = sum(a_.activity for a_ in agents) * a.rounds * len(a.rules)
    usd = calls * (TOKENS_IN * a.price_in + TOKENS_OUT * a.price_out) / 1e6
    print(f"Estimate: ~{calls:.0f} LLM calls, ~{calls * TOKENS_IN / 1e6:.1f}M input tokens, "
          f"~${usd:.2f} at ${a.price_in}/${a.price_out} per 1M tokens (model {a.model}).")
    if not a.yes and a.model != "stub":
        print("Dry estimate only. Re-run with --yes to start.")
        return

    model = make_openai_model(a.model)

    async def go():
        return [await run_one(cfg, rule, a.seed, model, a.model, a.llm_bios) for rule in a.rules]

    runs = asyncio.run(go())
    block = scenario_block(cfg, runs, replay_seed=a.seed)
    block.update({"mode": "llm", "model": a.model, "key": cfg.scenario + "_llm",
                  "title": SCENARIOS[cfg.scenario]["title"] + f" · {a.model} agents"})
    doc = {"generated": dt.datetime.now().isoformat(timespec="seconds"),
           "engine": "CAMEL OASIS (oasis.make + LLMAction) with FeedBenchPlatform", "versions": _versions(),
           "baseline": a.rules[0], "cap": cfg.ranking.community_cap, "rules": rule_docs(a.rules),
           "scenarios": [block]}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False, default=_clean), encoding="utf-8")
    print(f"Wrote {a.out}. Add it to the page: python build_lab.py --from-json results/lab.json --add-json {a.out}")


if __name__ == "__main__":
    main()
