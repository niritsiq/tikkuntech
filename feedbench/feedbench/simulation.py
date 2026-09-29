"""Experiment runner on top of CAMEL OASIS.

One run = one (policy, seed). Runs with the same seed share the same population,
follower graph, scenario authors and per-agent random draws (common random
numbers), so differences between policies come from the feed, not from luck.

Round loop (state is frozen while feeds are built):
  1. scheduled scenario posts are published (e.g. the shared event at round 5)
  2. each non-churned agent opens the app with P = activity
  3. FeedBenchPlatform ranks feeds for everyone who opened the app
  4. agents refresh through OASIS (impressions logged), then act
  5. clock advances
"""
from __future__ import annotations

import asyncio
import os
import random
from dataclasses import dataclass, field

os.makedirs("log", exist_ok=True)   # OASIS writes ./log/*.log on import

from oasis.social_agent.agent import SocialAgent                    # noqa: E402
from oasis.social_agent.agent_graph import AgentGraph               # noqa: E402
from oasis.social_agent.agents_generator import generate_custom_agents  # noqa: E402
from oasis.social_platform.channel import Channel                   # noqa: E402
from oasis.social_platform.config import UserInfo                   # noqa: E402
from oasis.social_platform.typing import ActionType                 # noqa: E402

from .agents import ScriptedAgent                                   # noqa: E402
from .config import ExperimentConfig                                # noqa: E402
from .content import load_scenario, resolve_author                  # noqa: E402
from .llm import make_model, stub_model                             # noqa: E402
from .network import build_population                               # noqa: E402
from .oasis_platform import FeedBenchPlatform                       # noqa: E402
from .profiles import load_oasis_profiles, make_profiles            # noqa: E402
from .oasis_db import run_from_db, write_feedbench_tables           # noqa: E402

AGENT_ACTIONS = [ActionType.LIKE_POST, ActionType.REPOST, ActionType.CREATE_COMMENT,
                 ActionType.CREATE_POST, ActionType.DO_NOTHING]


@dataclass
class RunResult:
    policy: str
    seed: int
    impressions: list[dict]
    actions: list[dict]
    sessions: list[dict]
    posts: dict[int, dict]
    agents: list
    db_path: str
    errors: list[str] = field(default_factory=list)
    snapshots: list[dict] = field(default_factory=list)
    scenario: str = ""
    profiles: dict = field(default_factory=dict)


async def run_single(cfg: ExperimentConfig, policy: str, seed: int, record_snapshots: bool = False) -> RunResult:
    os.makedirs(cfg.workdir, exist_ok=True)
    tag = f"cap{cfg.ranking.community_cap}"
    db_path = os.path.join(cfg.workdir, f"{cfg.scenario}_{policy}_{tag}_seed{seed}.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    agents = build_population(cfg.network, seed)
    by_id = {a.id: a for a in agents}
    # same seed -> same users in every policy (generated, or real OASIS profiles from a file)
    profiles = load_oasis_profiles(cfg.profiles_path, agents) if cfg.profiles_path else make_profiles(agents, seed)
    for a in agents:
        a.display_name, a.handle = profiles[a.id].name, profiles[a.id].handle
    driver_rng = random.Random(f"drivers-{seed}")
    n_llm = round(cfg.llm_agent_share * len(agents))
    for a in driver_rng.sample(agents, n_llm):
        a.driver = "llm"
    scenario = load_scenario(cfg.scenario_path)
    author_rng = random.Random(f"authors-{seed}")
    schedule: dict[int, list[dict]] = {}
    for p in scenario["posts"]:
        author_id = resolve_author(p["author"], agents, author_rng, profiles, p.get("author_trait"))
        if author_id is None or (p["label"] == "harmful" and not cfg.include_harmful_posts):
            continue
        schedule.setdefault(p["round"], []).append({**p, "author_id": author_id})

    channel = Channel()
    post_meta: dict[int, dict] = {}
    platform = FeedBenchPlatform(db_path=db_path, channel=channel, policy=policy,
                                 ranking_cfg=cfg.ranking, agents=agents, post_meta=post_meta, seed=seed,
                                 record_snapshots=record_snapshots)
    platform.sandbox_clock.time_step = 0

    graph = AgentGraph()
    stub = stub_model()
    llm = make_model(cfg) if n_llm else None
    for a in agents:
        graph.add_agent(SocialAgent(
            agent_id=a.id,
            user_info=UserInfo(user_name=profiles[a.id].handle, name=profiles[a.id].name,
                               description=profiles[a.id].bio,
                               profile={"other_info": {"user_profile": a.persona()}}, recsys_type="twitter"),
            model=llm if a.driver == "llm" else stub,
            agent_graph=graph, available_actions=AGENT_ACTIONS))

    platform_task = asyncio.create_task(platform.running())
    graph = await generate_custom_agents(channel=channel, agent_graph=graph)
    oa = {aid: ag for aid, ag in graph.get_agents()}
    await asyncio.gather(*[oa[a.id].env.action.follow(f) for a in agents for f in sorted(a.follows)])

    scripted = ScriptedAgent(cfg.behavior)
    actions: list[dict] = []
    sessions: list[dict] = []
    errors: list[str] = []
    llm_sem = asyncio.Semaphore(4)

    for t in range(cfg.rounds):
        platform.sandbox_clock.time_step = t
        for p in schedule.get(t, []):
            res = await oa[p["author_id"]].env.action.create_post(p["text"])
            post_meta[res["post_id"]] = {"label": p["label"], "key": p["id"], "text": p["text"],
                                         "lean": p["lean"], "author": p["author_id"], "round": t,
                                         "control": p.get("control", False),
                                         "community_boost": p.get("community_boost")}
            actions.append(_row(t, by_id[p["author_id"]], "create_post", res["post_id"], p["label"], p["label"], "scenario"))

        open_rng = random.Random(f"open-{seed}-{t}")
        draws = {a.id: open_rng.random() for a in agents}      # same draws in every policy
        active = [a for a in agents if not a.churned and draws[a.id] < a.activity]
        platform.feed_users = {a.id for a in active}
        await platform.update_rec_table()

        scripted_active = [a for a in active if a.driver == "scripted"]
        await asyncio.gather(*[oa[a.id].env.action.refresh() for a in scripted_active])

        tasks = []
        for a in scripted_active:
            feed = [{"post_id": p.post_id, "label": p.label, "lean": post_meta.get(p.post_id, {}).get("lean", 0.0),
                     "author_community": p.author_community, "endorsements": p.total_endorsements,
                     "community_boost": post_meta.get(p.post_id, {}).get("community_boost")}
                    for p, _ in platform.feeds.get(a.id, [])]
            res = scripted.session(a, feed, random.Random(f"behave-{seed}-{t}-{a.id}"),
                                   event_started=t >= scenario.get("event_round", 0))
            if res.churned:
                a.churned = True
            sessions.append({"round": t, "agent": a.id, "community": a.community, "driver": "scripted",
                             "feed_len": len(feed), "left_early": res.left_early, "churned": res.churned})
            for d in res.decisions:
                tasks.append(_execute(oa[a.id], a, d, t, post_meta, actions, by_id, platform))
        await asyncio.gather(*tasks)

        llm_tasks = [_llm_turn(oa[a.id], a, t, llm_sem, sessions, errors)
                     for a in active if a.driver == "llm"]
        await asyncio.gather(*llm_tasks)

    if n_llm:
        actions += _llm_actions_from_trace(platform, by_id, post_meta)

    await channel.write_to_receive_queue((None, None, ActionType.EXIT))
    await platform_task
    result = RunResult(policy, seed, platform.impressions, actions, sessions,
                       post_meta, agents, db_path, errors, platform.snapshots, cfg.scenario, profiles)
    result.comment_labels = dict(platform.comment_labels)
    # The OASIS database is the source of truth: annotate it, then read the run back from it.
    write_feedbench_tables(db_path, result, cfg)
    from_db = run_from_db(db_path)
    from_db.errors = errors
    from_db.logged = result          # in-memory logs, kept for consistency checks
    return from_db


def _row(t, agent, action, post_id, target_label, text_label, driver="scripted") -> dict:
    return {"round": t, "agent": agent.id, "agent_community": agent.community, "action": action,
            "post_id": post_id, "target_label": target_label, "text_label": text_label, "driver": driver}


async def _execute(oagent, agent, d, t, post_meta, actions, by_id, platform):
    act = oagent.env.action
    target = post_meta.get(d.post_id, {"label": "benign"}) if d.post_id else None
    if d.action == "like":
        r = await act.like_post(d.post_id)
    elif d.action == "repost":
        r = await act.repost(d.post_id)
    elif d.action == "comment":
        r = await act.create_comment(d.post_id, d.text)
        if r.get("success"):
            platform.comment_labels[r["comment_id"]] = d.label
    elif d.action == "create_post":
        r = await act.create_post(d.text)
        if r.get("success"):
            post_meta[r["post_id"]] = {"label": d.label, "key": "organic", "text": d.text, "lean": agent.lean,
                                       "author": agent.id, "round": t}
            actions.append(_row(t, agent, "create_post", r["post_id"], d.label, d.label))
        return
    else:
        return
    if r.get("success"):
        row = _row(t, agent, d.action, d.post_id, target["label"], d.label if d.action == "comment" else "")
        if d.action == "comment":
            row["text"] = d.text[:200]
        author = target.get("author")
        row["target_author_community"] = by_id[author].community if author is not None else None
        actions.append(row)


async def _llm_turn(oagent, agent, t, sem, sessions, errors):
    async with sem:
        try:
            await oagent.perform_action_by_llm()
            sessions.append({"round": t, "agent": agent.id, "community": agent.community, "driver": "llm",
                             "feed_len": None, "left_early": False, "churned": False})
        except Exception as e:  # refusals / timeouts are recorded, not hidden
            errors.append(f"round {t} agent {agent.id}: {e!r}")


def _llm_actions_from_trace(platform, by_id, post_meta) -> list[dict]:
    """LLM agents act through OASIS tool calls; recover their actions from the trace table."""
    import json
    rows = platform._q("SELECT user_id, action, info, CAST(created_at AS INTEGER) FROM trace")
    out = []
    llm_ids = {a.id for a in by_id.values() if a.driver == "llm"}
    for uid, action, info, t in rows:
        if uid not in llm_ids or action not in ("like_post", "repost", "create_comment", "create_post"):
            continue
        try:
            info = json.loads(info)
        except Exception:
            info = {}
        pid = info.get("post_id")
        name = {"like_post": "like", "create_comment": "comment"}.get(action, action)
        row = _row(t, by_id[uid], name, pid, post_meta.get(pid, {}).get("label", "benign"),
                   "unlabeled" if name in ("comment", "create_post") else "", driver="llm")
        author = post_meta.get(pid, {}).get("author")
        row["target_author_community"] = by_id[author].community if author is not None else None
        out.append(row)
    return out


async def run_many(cfg: ExperimentConfig, policies=None, seeds=None, progress=None,
                   snapshot_seed: int | None = None) -> list[RunResult]:
    """All (policy, seed) runs concurrently; each has its own OASIS platform + SQLite DB."""
    policies = policies or cfg.policies
    seeds = seeds or cfg.seeds
    jobs = [(p, s) for s in seeds for p in policies]
    done = 0

    async def one(p, s):
        nonlocal done
        r = await run_single(cfg, p, s, record_snapshots=(s == snapshot_seed))
        done += 1
        if progress:
            progress(done, len(jobs))
        return r

    return await asyncio.gather(*[one(p, s) for p, s in jobs])


def run_experiment(cfg: ExperimentConfig, progress=None) -> list[RunResult]:
    return asyncio.run(run_many(cfg, progress=progress))
