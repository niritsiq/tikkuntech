"""Turn computed runs into reproducible artifacts: benchmark.json (drives the replay) + CSVs."""
from __future__ import annotations

import datetime as dt
import json
import platform as _platform
from importlib import metadata
from pathlib import Path

import pandas as pd

from .config import POLICIES, SCENARIOS
from .metrics import per_round, summarize

SERIES = ["harmful_impressions_cum", "ordinary_engagement_cum", "counterspeech_exposure_cum",
          "harmful_reach_cum", "control_reach_cum"]


def _versions() -> dict:
    out = {"python": _platform.python_version()}
    for pkg in ("camel-oasis", "camel-ai"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = "not installed"
    return out


def _clean(x):
    if isinstance(x, float) and x != x:   # NaN -> null
        return None
    return x


def scenario_block(cfg, runs, replay_seed: int) -> dict:
    summary, totals = summarize(runs, cfg.rounds, cfg.baseline, cfg)
    rounds = pd.concat([per_round(r, cfg.rounds) for r in runs])
    series = {}
    for pol, g in rounds.groupby("policy", sort=False):
        series[pol] = {k: {"mean": g.groupby("round")[k].mean().round(2).tolist(),
                           "min": g.groupby("round")[k].min().tolist(),
                           "max": g.groupby("round")[k].max().tolist()} for k in SERIES}

    replay = {}
    for r in runs:
        if r.seed != replay_seed:
            continue
        imp = pd.DataFrame(r.impressions)
        feeds: dict[int, dict] = {}
        for (t, a), g in imp.sort_values("position").groupby(["round", "agent"]):
            feeds.setdefault(int(t), {})[int(a)] = [
                [int(p), s[0], round(float(sc), 2), round(float(pop), 2), round(float(soc), 2), round(float(rec), 2)]
                for p, s, sc, pop, soc, rec in zip(g["post_id"], g["slot"], g["score"], g["popularity"],
                                                   g["social"], g["recency"])]
        snaps: dict[int, list] = {}
        for s in r.snapshots:
            snaps.setdefault(int(s["post_id"]), []).append([s["round"], s["e"], s["popA"], s["popB"],
                                                            round(float(s.get("pop", 0)), 2)])
        replay[r.policy] = {
            "posts": {int(pid): {"key": m.get("key", ""), "label": m["label"], "text": m["text"][:220],
                                 "author": m["author"], "round": m["round"], "control": bool(m.get("control"))}
                      for pid, m in r.posts.items()},
            "feeds": feeds,
            "snapshots": snaps,
            "sessions": [[s["round"], s["agent"], int(s["left_early"]), int(s["churned"])] for s in r.sessions],
            # [round, agent, action, post_id, label of reply text]  (likes, reposts, replies, new posts)
            "actions": [[a["round"], a["agent"], a["action"], a["post_id"], a.get("text_label", "")]
                        for a in r.actions if a.get("post_id") is not None],
            "replies": {int(k): v for k, v in _reply_texts(r).items()},
        }
    profiles = next((r.profiles for r in runs if r.seed == replay_seed), runs[0].profiles)
    agents = [{"id": a.id, "community": a.community, "cluster": a.in_harm_cluster,
               "counter": a.counter_speaker, "activity": round(a.activity, 2),
               **({k: v for k, v in vars(profiles[a.id]).items() if k != "id"} if profiles else {})}
              for a in next(r for r in runs if r.seed == replay_seed).agents]
    return {
        "key": cfg.scenario, "title": SCENARIOS.get(cfg.scenario, {}).get("title", cfg.scenario),
        "question": SCENARIOS.get(cfg.scenario, {}).get("question", "Imported OASIS databases."),
        "config": cfg.to_dict(),
        "summary": [{k: _clean(v) for k, v in row.items()} for row in summary.to_dict("records")],
        "per_seed": totals.to_dict("records"),
        "series": series,
        "replay_seed": replay_seed,
        "replay": replay,
        "agents": agents,
    }


def _reply_texts(run) -> dict:
    """post_id -> replies [round, author, label, text], oldest first."""
    out: dict[int, list] = {}
    for a in run.actions:
        if a["action"] == "comment" and a.get("post_id") is not None:
            out.setdefault(a["post_id"], []).append([a["round"], a["agent"], a.get("text_label", ""), a.get("text", "")])
    return out


def write_outputs(blocks: list[dict], sensitivity: list[dict], outdir: str | Path) -> Path:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    doc = {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "engine": "CAMEL OASIS (custom FeedBenchPlatform: ranked feeds delivered in exact order)",
        "versions": _versions(),
        "policies": POLICIES,
        "scenarios": blocks,
        "sensitivity": sensitivity,
        "disclaimer": ("Synthetic agents under declared assumptions. Illustrates a ranking mechanism; "
                       "does not estimate effects on a real platform or establish a legal conclusion."),
    }
    path = outdir / "benchmark.json"
    path.write_text(json.dumps(doc, separators=(",", ":"), default=_clean))
    rows = []
    for b in blocks:
        for r in b["per_seed"]:
            rows.append({"scenario": b["key"], **r})
    pd.DataFrame(rows).to_csv(outdir / "runs_per_seed.csv", index=False)
    pd.DataFrame([{"scenario": b["key"], **r} for b in blocks for r in b["summary"]]).to_csv(
        outdir / "summary.csv", index=False)
    if sensitivity:
        pd.DataFrame(sensitivity).to_csv(outdir / "cap_sensitivity.csv", index=False)
    return path
