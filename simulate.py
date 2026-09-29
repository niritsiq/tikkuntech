"""A dependency-free paired social-feed benchmark. Run: python simulate.py."""

import argparse
import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from sample_data import COMMUNITIES, get_agents, get_posts, get_scenarios, stable_random

VERSION = "1.1.0"
CONFIG = {"agents_count": 50, "rounds": 6, "feed_size": 3, "cap": 2,
          "seeds": [11, 23, 37, 51, 71], "communities": list(COMMUNITIES)}
# The pre-registered headline comparison. Lab runs with other rules are exploratory.
PREREGISTERED = {"rule": "capped", "cap": 2}
SWEEP_CAPS = [1, 2, 3, 4, 5, 6]
# Display thresholds for automatic feedback only; acceptance thresholds belong to the experts.
FEEDBACK_THRESHOLDS = {"harm_pp": 1.0, "retention_low": 0.9, "retention_high": 1.1}

# Each rule sees only per-community counts of distinct endorsers; labels and text are never inputs.
RULES = {
    "baseline": {"name": "Total endorsements", "uses_cap": False,
                 "formula": "sum over communities of n[g,p]",
                 "score": lambda counts, cap: sum(counts)},
    "capped": {"name": "Community-capped endorsements", "uses_cap": True,
               "formula": "sum over communities of min(n[g,p], cap)",
               "score": lambda counts, cap: sum(min(n, cap) for n in counts)},
    "sqrt": {"name": "Diminishing returns per community", "uses_cap": False,
             "formula": "sum over communities of sqrt(n[g,p])",
             "score": lambda counts, cap: sum(math.sqrt(n) for n in counts)},
    "breadth": {"name": "Communities reached", "uses_cap": False,
                "formula": "number of communities with n[g,p] >= 1",
                "score": lambda counts, cap: sum(1 for n in counts if n)},
    "chronological": {"name": "Newest first (control)", "uses_cap": False,
                      "formula": "0 for every post; recency tie-break decides",
                      "score": lambda counts, cap: 0},
}
COMPARISON_KEYS = ("harmful_exposure_delta_pp", "harmful_reach_delta", "ordinary_engagement_retention",
                   "ordinary_reach_retention", "counterspeech_exposure_retention",
                   "counterspeech_engagement_retention", "jewish_life_reach_retention")


def community_counts(endorser_ids, agents_by_id):
    counts = [0] * len(COMMUNITIES)
    for agent_id in set(endorser_ids):
        counts[agents_by_id[agent_id]["community"]] += 1
    return counts


def score(counts, policy, cap=2):
    if policy not in RULES:
        raise ValueError("Unknown ranking policy: " + policy)
    return round(RULES[policy]["score"](counts, cap), 3)


def ratio(numerator, denominator):
    return numerator / float(denominator) if denominator else None


def choose_action(agent, feed, posts_by_id, endorsers, agents_by_id, seed, round_number):
    """One action at most. Content text and evaluation labels are never read."""
    if stable_random(seed, round_number, agent["id"], "active") >= agent["activity"]:
        return None, "none"
    choices = []
    for item in feed:
        post_id = item["post_id"]
        if agent["id"] in endorsers[post_id]:
            continue
        post = posts_by_id[post_id]
        affinity = agent["interests"].get(post["topic"], 0.3)
        social_tie = 0.2 if post["author_id"] in agent["follows"] else 0.0
        weight = 0.2 + affinity + social_tie
        draw = max(stable_random(seed, round_number, agent["id"], post_id, "choice"), 1e-15)
        choices.append((-math.log(draw) / weight, post_id))
    if not choices:
        return None, "none"
    post_id = min(choices)[1]
    action = "reshare" if stable_random(seed, round_number, agent["id"], post_id, "action") < 0.25 else "like"
    return post_id, action


def evaluate(rounds, posts_by_id, agent_count):
    totals = {"total_impressions": 0, "harmful_impressions": 0, "ordinary_impressions": 0,
              "ordinary_actions": 0, "counterspeech_impressions": 0, "counterspeech_actions": 0,
              "ambiguous_impressions": 0, "jewish_life_impressions": 0, "jewish_life_actions": 0,
              "total_actions": 0}
    harmful_agents, ordinary_pairs = set(), set()
    for snapshot in rounds:
        for agent_id, feed in snapshot["feeds"].items():
            for item in feed:
                post = posts_by_id[item["post_id"]]
                label = post["label"]
                acted = item["action"] in ("like", "reshare")
                totals["total_impressions"] += 1
                totals["total_actions"] += int(acted)
                if label == "antisemitic":
                    totals["harmful_impressions"] += 1
                    harmful_agents.add(agent_id)
                elif label == "ordinary":
                    totals["ordinary_impressions"] += 1
                    totals["ordinary_actions"] += int(acted)
                    ordinary_pairs.add((agent_id, item["post_id"]))
                    if post.get("about_jewish_life"):
                        totals["jewish_life_impressions"] += 1
                        totals["jewish_life_actions"] += int(acted)
                elif label == "counterspeech":
                    totals["counterspeech_impressions"] += 1
                    totals["counterspeech_actions"] += int(acted)
                elif label == "ambiguous":
                    totals["ambiguous_impressions"] += 1
    totals.update({"harmful_exposure_rate": ratio(totals["harmful_impressions"], totals["total_impressions"]),
                   "harmful_reach_count": len(harmful_agents),
                   "harmful_reach_rate": ratio(len(harmful_agents), agent_count),
                   "ordinary_reach": len(ordinary_pairs)})
    return totals


def rank_posts(eligible, scores, seed, round_number, agent_id):
    """Score, then recency, then a stable seeded draw. The draw is hashed only when needed."""
    primary = lambda p: (-scores[p["id"]], -p["created_at"])
    ranked = sorted(eligible, key=primary)
    if any(primary(a) == primary(b) for a, b in zip(ranked, ranked[1:])):
        ranked.sort(key=lambda p: primary(p) + (stable_random(seed, round_number, agent_id, p["id"], "tie"),))
    return ranked


def run_policy(agents, posts, initial_endorsements, seed, policy, config=None):
    config = config or CONFIG
    agents_by_id = {a["id"]: a for a in agents}
    posts_by_id = {p["id"]: p for p in posts}
    endorsers = {p["id"]: set(initial_endorsements.get(p["id"], [])) for p in posts}
    seen = {a["id"]: set() for a in agents}
    rounds = []
    for round_number in range(1, config["rounds"] + 1):
        counts = {p["id"]: community_counts(endorsers[p["id"]], agents_by_id) for p in posts}
        scores = {pid: score(c, policy, config["cap"]) for pid, c in counts.items()}
        feeds, pending = {}, []
        # All agents see the same start-of-round state. Mutations occur afterward.
        for agent in agents:
            eligible = [p for p in posts if p["author_id"] != agent["id"] and p["id"] not in seen[agent["id"]]]
            ranked = rank_posts(eligible, scores, seed, round_number, agent["id"])
            feed = [{"post_id": p["id"], "score": scores[p["id"]],
                     "community_counts": counts[p["id"]][:], "action": "none"}
                    for p in ranked[:config["feed_size"]]]
            chosen, action = choose_action(agent, feed, posts_by_id, endorsers, agents_by_id, seed, round_number)
            for item in feed:
                seen[agent["id"]].add(item["post_id"])
                if item["post_id"] == chosen:
                    item["action"] = action
                    pending.append((agent["id"], chosen))
            feeds[agent["id"]] = feed
        for agent_id, post_id in pending:
            endorsers[post_id].add(agent_id)
        snapshot = {"round": round_number, "feeds": feeds,
                    "post_counts": counts, "post_scores": scores}
        rounds.append(snapshot)
        snapshot["metrics"] = evaluate(rounds, posts_by_id, len(agents))
    return {"rounds": rounds, "metrics": rounds[-1]["metrics"],
            "final_endorsements": {pid: sorted(ids) for pid, ids in endorsers.items()}}


def compare(baseline, candidate):
    return {
        "harmful_exposure_delta_pp": 100 * (candidate["harmful_exposure_rate"] - baseline["harmful_exposure_rate"]),
        "harmful_reach_delta": candidate["harmful_reach_count"] - baseline["harmful_reach_count"],
        "ordinary_engagement_retention": ratio(candidate["ordinary_actions"], baseline["ordinary_actions"]),
        "ordinary_reach_retention": ratio(candidate["ordinary_reach"], baseline["ordinary_reach"]),
        "counterspeech_exposure_retention": ratio(candidate["counterspeech_impressions"], baseline["counterspeech_impressions"]),
        "counterspeech_engagement_retention": ratio(candidate["counterspeech_actions"], baseline["counterspeech_actions"]),
        "jewish_life_reach_retention": ratio(candidate["jewish_life_impressions"], baseline["jewish_life_impressions"]),
    }


def summarize(runs):
    summaries = {}
    for key in COMPARISON_KEYS:
        values = [run["comparison"][key] for run in runs]
        valid = [v for v in values if v is not None]
        summaries[key] = {"values": values, "mean": sum(valid) / len(valid) if valid else None,
                          "min": min(valid) if valid else None, "max": max(valid) if valid else None}
    return summaries


def assess(comparisons):
    """Plain-language feedback for one fixture. Levels: good, neutral, serious, critical."""
    t = FEEDBACK_THRESHOLDS
    findings = []
    harm = comparisons["harmful_exposure_delta_pp"]
    spread = "in every seed" if harm["min"] == harm["max"] else "across seeds (%.1f to %.1f pp)" % (harm["min"], harm["max"])
    if harm["max"] <= -t["harm_pp"]:
        findings.append({"level": "good", "metric": "harm",
                         "text": "Antisemitic exposure falls by %.1f pp %s." % (-harm["mean"], spread)})
    elif harm["min"] >= t["harm_pp"]:
        findings.append({"level": "critical", "metric": "harm",
                         "text": "Antisemitic exposure rises by %.1f pp %s." % (harm["mean"], spread)})
    else:
        findings.append({"level": "neutral", "metric": "harm",
                         "text": "No consistent change in antisemitic exposure (%.1f to %.1f pp)." % (harm["min"], harm["max"])})
    for key, label in (("ordinary_engagement_retention", "Ordinary engagement"),
                       ("counterspeech_exposure_retention", "Counterspeech exposure"),
                       ("jewish_life_reach_retention", "Jewish community-life reach")):
        value = comparisons[key]
        if value["mean"] is None:
            findings.append({"level": "neutral", "metric": key, "text": label + ": N/A (baseline count is zero)."})
        elif value["min"] < t["retention_low"]:
            findings.append({"level": "serious", "metric": key,
                             "text": "%s drops to %.0f%%-%.0f%% of baseline." % (label, 100 * value["min"], 100 * value["max"])})
        elif value["max"] > t["retention_high"] and value["min"] >= 1:
            findings.append({"level": "good", "metric": key,
                             "text": "%s rises to %.0f%%-%.0f%% of baseline." % (label, 100 * value["min"], 100 * value["max"])})
        else:
            findings.append({"level": "neutral", "metric": key,
                             "text": "%s roughly unchanged (%.0f%%-%.0f%%)." % (label, 100 * value["min"], 100 * value["max"])})
    return findings


def overall_verdict(scenarios):
    helped = [s["name"] for s in scenarios if s["feedback"][0]["level"] == "good"]
    harmed = [s["name"] for s in scenarios if s["feedback"][0]["level"] == "critical"]
    costs = ["%s (%s)" % (s["name"], f["text"].split(" drops")[0])
             for s in scenarios for f in s["feedback"] if f["level"] == "serious"]
    parts = ["Reduces antisemitic exposure in %d of %d fixtures%s." % (
        len(helped), len(scenarios), ": " + ", ".join(helped) if helped else "")]
    if harmed:
        parts.append("Increases it in: " + ", ".join(harmed) + ".")
    parts.append("Costs: " + "; ".join(costs) + "." if costs else "No retention metric fell below the display threshold.")
    return " ".join(parts)


def validate_rule(rule, cap):
    if rule not in RULES or rule == "baseline":
        raise ValueError("Choose a candidate rule other than baseline: " + ", ".join(r for r in RULES if r != "baseline"))
    cap = int(cap)
    if not 1 <= cap <= 10:
        raise ValueError("Cap must be between 1 and 10.")
    return rule, cap


def run_experiment(rule, cap, include_rounds=True):
    """Baseline versus one candidate rule on every fixture and seed."""
    rule, cap = validate_rule(rule, cap)
    config = dict(CONFIG, cap=cap)
    agents, posts, scenarios = get_agents(), get_posts(), get_scenarios()
    for scenario in scenarios:
        scenario["runs"] = []
        for seed in config["seeds"]:
            policies = {"baseline": run_policy(agents, posts, scenario["initial_endorsements"], seed, "baseline", config),
                        "candidate": run_policy(agents, posts, scenario["initial_endorsements"], seed, rule, config)}
            run = {"seed": seed, "comparison": compare(policies["baseline"]["metrics"], policies["candidate"]["metrics"]),
                   "metrics": {name: result["metrics"] for name, result in policies.items()}}
            if include_rounds:
                run["policies"] = policies
            scenario["runs"].append(run)
        comparisons = summarize(scenario["runs"])
        scenario["summary"] = {"seed_count": len(config["seeds"]), "comparisons": comparisons}
        scenario["feedback"] = assess(comparisons)
    fingerprint = json.dumps({"config": config, "rule": rule, "agents": agents, "posts": posts,
                              "fixtures": [(s["id"], s["initial_endorsements"]) for s in scenarios]},
                             sort_keys=True, ensure_ascii=False).encode("utf-8")
    preregistered = rule == PREREGISTERED["rule"] and cap == PREREGISTERED["cap"]
    return {
        "meta": {"title": "TikkunTech Ranking Lab", "event": "Riverton community festival funding debate",
                 "engine": "Python synthetic simulator", "version": VERSION, "review_status": "draft",
                 "generated_at": datetime.now(timezone.utc).isoformat(),
                 "config_hash": hashlib.sha256(fingerprint).hexdigest(), **config,
                 "candidate": {"rule": rule, "cap": cap, **{k: v for k, v in RULES[rule].items() if k != "score"}},
                 "baseline": {"rule": "baseline", **{k: v for k, v in RULES["baseline"].items() if k != "score"}},
                 "status": "pre-registered" if preregistered else "exploratory",
                 "feedback_thresholds": FEEDBACK_THRESHOLDS,
                 "verdict": overall_verdict(scenarios),
                 "limitations": ["All sample labels await expert review.",
                                 "Harmful items are abstract descriptions; the action model does not read text.",
                                 "Behavior is a fixed probabilistic model, without live LLM calls.",
                                 "Initial endorsements are authored fixtures, not empirical measurements.",
                                 "The benchmark illustrates a mechanism under assumptions; it does not predict real-platform effects.",
                                 "Five seeds show variability, not statistical significance.",
                                 "Exploratory rules and caps were chosen after seeing results; only the pre-registered run is a test."]},
        "config": config, "rules": {k: {kk: vv for kk, vv in v.items() if kk != "score"} for k, v in RULES.items()},
        "agents": agents, "posts": posts, "scenarios": scenarios,
    }


def sweep(rule="capped", caps=None):
    """Sensitivity of the headline metrics to the cap. Metrics only, no traces."""
    caps = caps or SWEEP_CAPS
    points = {}
    for cap in caps:
        result = run_experiment(rule, cap, include_rounds=False)
        for scenario in result["scenarios"]:
            points.setdefault(scenario["id"], {"name": scenario["name"], "points": []})["points"].append(
                {"cap": cap, **{key: scenario["summary"]["comparisons"][key] for key in COMPARISON_KEYS}})
    return {"rule": rule, "caps": caps, "fixtures": points}


def write_bundle(output_dir="web/data"):
    bundle = run_experiment(PREREGISTERED["rule"], PREREGISTERED["cap"])
    bundle["sweep"] = sweep("capped")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    for name, data in (("results", bundle), ("agents", bundle["agents"]),
                       ("posts", bundle["posts"]), ("config", {**bundle["config"], "meta": bundle["meta"]})):
        (output / (name + ".json")).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    write_events_csv(bundle, output / "events.csv")
    return bundle


def write_events_csv(bundle, path):
    fields = ["fixture", "policy", "seed", "round", "agent", "post", "rank", "score", "label", "action"]
    policy_names = {"baseline": "baseline", "candidate": bundle["meta"]["candidate"]["rule"]}
    labels = {p["id"]: p["label"] for p in bundle["posts"]}
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for scenario in bundle["scenarios"]:
            for run in scenario["runs"]:
                for policy, result in run["policies"].items():
                    for snapshot in result["rounds"]:
                        for agent_id, feed in snapshot["feeds"].items():
                            for rank, item in enumerate(feed, 1):
                                writer.writerow({"fixture": scenario["id"], "policy": policy_names[policy],
                                                 "seed": run["seed"], "round": snapshot["round"], "agent": agent_id,
                                                 "post": item["post_id"], "rank": rank, "score": item["score"],
                                                 "label": labels[item["post_id"]], "action": item["action"]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="web/data", help="Output directory for JSON and CSV exports")
    parser.add_argument("--rule", choices=[r for r in RULES if r != "baseline"],
                        help="Print feedback for an exploratory rule instead of writing the bundle")
    parser.add_argument("--cap", type=int, default=CONFIG["cap"])
    args = parser.parse_args()
    if args.rule:
        result = run_experiment(args.rule, args.cap, include_rounds=False)
    else:
        result = write_bundle(args.output)
        print("Generated %d paired runs across %d fixtures in %s" % (
            len(CONFIG["seeds"]) * len(result["scenarios"]), len(result["scenarios"]), args.output))
    print("Rule: %s, cap %d (%s)" % (result["meta"]["candidate"]["rule"], result["meta"]["candidate"]["cap"],
                                     result["meta"]["status"]))
    for scenario in result["scenarios"]:
        print("\n" + scenario["name"])
        for finding in scenario["feedback"]:
            print("  [%s] %s" % (finding["level"], finding["text"]))
    print("\n" + result["meta"]["verdict"])
