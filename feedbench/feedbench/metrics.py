"""Interface C: evaluation. Computed ONLY from logged impressions/actions + expert labels.

Headline measures (scope card):
  antisemitic exposure        delivered feed slots holding an antisemitic post
  ordinary engagement         likes, reposts and replies on non-antisemitic posts + new ordinary posts
  counterspeech exposure      impressions of counterspeech posts + counterspeech replies shown under posts
Supporting measures:
  antisemitic reach           distinct agents shown >= 1 antisemitic post
  benign control reach        distinct agents shown the control post M1 (the cost of the cap)
"""
from __future__ import annotations

import pandas as pd

from .config import POLICIES

TOTAL_KEYS = ["harmful_impressions", "harmful_reach", "ordinary_engagement", "counterspeech_exposure",
              "counterspeech_post_impressions", "counterspeech_replies_shown",
              "control_reach", "control_impressions", "impressions", "churned", "harmful_endorsements"]


def _frames(run):
    imp = pd.DataFrame(run.impressions)
    act = pd.DataFrame(run.actions)
    ses = pd.DataFrame(run.sessions)
    if imp.empty:
        imp = pd.DataFrame(columns=["round", "agent", "label", "key", "counter_replies_shown", "post_id"])
    if act.empty:
        act = pd.DataFrame(columns=["round", "action", "target_label", "text_label", "driver", "agent"])
    if ses.empty:
        ses = pd.DataFrame(columns=["round", "agent", "churned", "left_early"])
    return imp, act, ses


def _ordinary_mask(act: pd.DataFrame) -> pd.Series:
    engaged = act["action"].isin(["like", "repost", "comment"])
    ordinary_target = act["target_label"] != "harmful"
    not_harm_reply = act["text_label"] != "harmful"
    new_post = (act["action"] == "create_post") & (act["target_label"] != "harmful") & (act["driver"] != "scenario")
    return (engaged & ordinary_target & not_harm_reply) | new_post


def per_round(run, rounds: int) -> pd.DataFrame:
    imp, act, ses = _frames(run)
    control_ids = {pid for pid, m in run.posts.items() if m.get("control")}
    imp = imp.assign(cs=imp["counter_replies_shown"].fillna(0) + (imp["label"] == "counter").astype(int))
    act = act.assign(ordinary=_ordinary_mask(act))
    rows, reached, ctrl = [], set(), set()
    for t in range(rounds):
        it, at, st = imp[imp["round"] == t], act[act["round"] == t], ses[ses["round"] == t]
        h = it[it["label"] == "harmful"]
        reached |= set(h["agent"])
        ctrl |= set(it[it["post_id"].isin(control_ids)]["agent"])
        rows.append({
            "round": t,
            "impressions": len(it),
            "harmful_impressions": len(h),
            "harmful_reach_cum": len(reached),
            "ordinary_engagement": int(at["ordinary"].sum()),
            "counterspeech_exposure": int(it["cs"].sum()),
            "control_reach_cum": len(ctrl),
            "active_agents": len(st),
        })
    df = pd.DataFrame(rows)
    for k in ("harmful_impressions", "ordinary_engagement", "counterspeech_exposure"):
        df[k + "_cum"] = df[k].cumsum()
    df["policy"], df["seed"] = run.policy, run.seed
    return df


def run_totals(run, rounds: int) -> dict:
    df = per_round(run, rounds)
    imp, act, ses = _frames(run)
    control_ids = {pid for pid, m in run.posts.items() if m.get("control")}
    harm_endorse = act[act["action"].isin(["like", "repost"]) & (act["target_label"] == "harmful")]
    return {
        "policy": run.policy, "seed": run.seed,
        "harmful_impressions": int(df["harmful_impressions"].sum()),
        "harmful_reach": int(df["harmful_reach_cum"].iloc[-1]),
        "ordinary_engagement": int(df["ordinary_engagement"].sum()),
        "counterspeech_exposure": int(df["counterspeech_exposure"].sum()),
        "counterspeech_post_impressions": int((imp["label"] == "counter").sum()),
        "counterspeech_replies_shown": int(imp["counter_replies_shown"].fillna(0).sum()),
        "control_reach": int(df["control_reach_cum"].iloc[-1]),
        "control_impressions": int(imp["post_id"].isin(control_ids).sum()),
        "impressions": int(df["impressions"].sum()),
        "churned": int(ses["churned"].sum()) if len(ses) else 0,
        "harmful_endorsements": len(harm_endorse),
        "llm_errors": len(run.errors),
    }


def _ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    """Paired per-seed ratio; NaN where the baseline is 0 (nothing to compare)."""
    den = den.where(den > 0)
    return (num / den).dropna()


def summarize(runs, rounds: int, baseline: str, cfg=None):
    """Paired comparison vs baseline: same seed = same population, graph, authors and random draws."""
    tot = pd.DataFrame([run_totals(r, rounds) for r in runs])
    base = tot[tot["policy"] == baseline].set_index("seed")
    out = []
    for pol, g in tot.groupby("policy", sort=False):
        g = g.set_index("seed")
        row = {"policy": pol, "label": POLICIES.get(pol, pol), "seeds": len(g)}
        for k in TOTAL_KEYS:
            row[k] = float(g[k].mean())
            row[k + "_min"], row[k + "_max"] = int(g[k].min()), int(g[k].max())
        for k, name in (("harmful_impressions", "harm_ratio"), ("ordinary_engagement", "engagement_ratio"),
                        ("counterspeech_exposure", "counterspeech_ratio"), ("control_reach", "control_ratio"),
                        ("harmful_reach", "reach_ratio")):
            r = _ratio(g[k], base[k])
            paired = base[k].reindex(g.index)
            # headline = ratio of summed counts over paired seeds (robust to tiny per-seed baselines);
            # min/max = range of per-seed ratios
            row[name] = float(g[k].sum() / paired.sum()) if paired.sum() > 0 else float("nan")
            row[name + "_min"] = float(r.min()) if len(r) else float("nan")
            row[name + "_max"] = float(r.max()) if len(r) else float("nan")
        out.append(row)
    s = pd.DataFrame(out)
    if cfg is not None:
        s["verdict"] = s.apply(lambda r: verdict(r, baseline, cfg), axis=1)
    return s, tot


def verdict(r, baseline: str, cfg) -> str:
    if r["policy"] == baseline:
        return "baseline"
    parts = []
    if pd.isna(r["harm_ratio"]):
        parts.append("no antisemitic exposure to compare")
    elif r["harm_ratio"] <= 1 - cfg.target_harm_reduction:
        parts.append("meets harm-reduction target")
    elif r["harm_ratio"] < 1:
        parts.append("reduces exposure, below target")
    else:
        parts.append("does NOT reduce exposure")
    parts.append("keeps ordinary engagement" if r["engagement_ratio"] >= cfg.min_engagement_retained
                 else "costs ordinary engagement")
    if not pd.isna(r["counterspeech_ratio"]):
        parts.append("keeps counterspeech" if r["counterspeech_ratio"] >= cfg.min_counterspeech_retained
                     else "costs counterspeech")
    return "; ".join(parts)
