# FeedBench: developer guide

The OASIS-based ranking benchmark behind `FeedBench-Algorithm-Lab.html`. For what the project is and how to read the results, start with the [project README](../README.md). This file explains how the code fits together.

## Setup

OASIS (`camel-oasis 0.2.5`) supports Python 3.10 and 3.11 only.

```powershell
py -m pip install --user uv
py -m uv python install 3.11
py -m uv venv --python 3.11 .venv
py -m uv pip install --python .venv\Scripts\python.exe -r requirements.txt
.venv\Scripts\python.exe -m pytest tests -q            # add  -m "not oasis"  to skip the 1-minute OASIS test
```

## Commands

| Command | What it does |
|---|---|
| `python build_lab.py` | Runs every scenario × rule × seed on OASIS, writes `results/lab.json` and `../FeedBench-Algorithm-Lab.html` |
| `python build_lab.py --quick` | 1 seed, 2 scenarios |
| `python build_lab.py --rules total_endorsements my_rule` | Only these rules (the baseline is always added) |
| `python build_lab.py --profiles data/oasis/user_data_36.json` | Use an OASIS profile file for the population |
| `python build_lab.py --from-json results/lab.json` | Rebuild the page without simulating (e.g. after editing `lab_template.html`) |
| `python run_llm.py [--yes]` | LLM agents through the OASIS quick-start API (cost estimate first; needs `OPENAI_API_KEY`) |
| `python run_llm.py --model stub --agents 10 --rounds 5` | Free offline check of the LLM pipeline |
| `python db_to_lab.py --dir runs_full` | Build the page from existing OASIS databases |
| `python check_oasis_profiles.py FILE` | Validate an OASIS profile file (JSON or Twitter CSV) |
| `python run_benchmark.py`, `python build_replay.py` | Earlier CLI summary and `replay.html` page |

## How one run works (`feedbench/simulation.py`)

One run = one (scenario, rule, seed). For each run:

1. **Population.** `network.build_population(seed)` creates the agents (community, political lean, activity, harm affinity, counter-speaker flag, follow graph). `profiles.make_profiles` gives them names, @handles and bios, or `profiles.load_oasis_profiles` takes them from an OASIS file.
2. **OASIS setup.** A `FeedBenchPlatform` (an OASIS `Platform` subclass) is created with the rule. Agents sign up through OASIS (`generate_custom_agents`) and follow each other through OASIS actions.
3. **Each round `t`:**
   1. Scheduled scenario posts from `data/scenario.json` are published via OASIS `create_post`.
   2. Each agent opens the app with probability `activity`. The draw is keyed by seed/round/agent, so it is identical under every rule.
   3. `platform.update_rec_table()` ranks every active user's feed with `ranking.build_feed`.
   4. Agents call OASIS `refresh`, which returns the ranked posts **in order** and writes a `trace` row with the posts, slots and scores.
   5. `agents.ScriptedAgent` decides likes, reposts, replies and new posts, executed as OASIS actions.
4. **Annotate and read back.** `oasis_db.write_feedbench_tables` adds the labels, roles, sessions and snapshots to the database. `oasis_db.run_from_db` reads the whole run back from the database, and that is what gets measured and exported.

**Why a Platform subclass:** stock OASIS `refresh()` random-samples cached recommendations and merges them with followed posts via `set()`, so the order a rule computes is not the order agents see. For a ranking benchmark the delivered order *is* the experiment.

**Why results are paired:** population, graph, scenario authors and every random draw are keyed by seed, never by rule. Two runs with the same seed differ only through the feed.

## Interfaces

| Interface | File | Input → output |
|---|---|---|
| **A · Ranking** | `ranking.py`, `custom_rules.py` | eligible posts (`content.PostView`: endorsers per community, author, age) + viewer → ordered feed with score parts. Never reads `label`. |
| **B · Behaviour** | `agents.py`, `llm.py` | agent + ordered feed → decisions. Scripted by default; LLM agents act through OASIS tool calls. |
| **C · Evaluation** | `metrics.py` | impressions + actions + sessions + labels → totals, per-round series, paired ratios, verdict text |
| **Export** | `export.py`, `build_lab.py` | runs → `lab.json` → page |
| **Storage** | `oasis_db.py` | OASIS SQLite ⇄ run object |

### Adding a rule
```python
# feedbench/custom_rules.py
from .ranking import register_rule

def my_popularity(p, cfg):
    return float(sum(min(cfg.community_cap, e) for e in p.endorsers_by_comm.values()))

def my_adjust(parts, p, viewer, now, cfg):      # optional: change any score part
    parts["recency"] *= 2
    return parts

register_rule("my_rule", "M · My rule", popularity=my_popularity, adjust=my_adjust)
```
`tests/test_ranking.py::test_every_registered_rule_ignores_labels` checks that every registered rule orders feeds identically when labels change.

### Changing assumptions
Every number is in `config.py`: network (`NetworkConfig`), feed layout and weights (`RankingConfig`), behaviour probabilities (`BehaviorConfig`), rounds, seeds and thresholds (`ExperimentConfig`), and the scenario presets (`SCENARIOS`). The fictional event and its posts are in `data/scenario.json`. Harmful posts there are placeholders that the expert team replaces.

## Database schema

Standard OASIS tables used: `user`, `follow`, `post`, `comment`, `like`, `trace` (refresh rows). The FeedBench tables `feedbench_run`, `feedbench_user`, `feedbench_post_label`, `feedbench_comment_label`, `feedbench_session` and `feedbench_snapshot` are documented at the top of `feedbench/oasis_db.py`.

A database without FeedBench tables (from another OASIS project) still loads. Labels then come from `--labels` (CSV `kind,id,label`), then from matching `data/scenario.json` text, and otherwise are "unlabeled". Sessions are inferred from refreshes.

## The page (`lab_template.html`)

The page is plain HTML/CSS/JS with no libraries. `build_lab.py` replaces `/*__DATA__*/null` with the exported JSON. Main parts of the script:
- `paired()`: before/after totals over paired seeds.
- `feedHTML()`: Twitter-style timelines.
- `liveEvents()` / `liveDraw()`: the live network, drawn on a canvas with fixed node positions per community.
- `lineChart()`: charts over time.
- `renderLeader()`: the all-rules table.

## Tests

| Test | Checks |
|---|---|
| `test_ranking.py` | Capped vs total arithmetic, reordering, rules ignore labels, profiles deterministic and unique |
| `test_oasis_db.py` (marker `oasis`) | A real OASIS run: the database alone reproduces totals, feed order, slots, scores, labels and profiles |

## Data sources

`data/oasis/` holds sample files from the [OASIS repository](https://github.com/camel-ai/oasis/tree/main/data): `user_data_36.json` (the quick-start Reddit profiles), and `197_progressive.csv` and `False_Business_0.csv` (Twitter datasets). Twitter CSV profiles are treated as real accounts and pseudonymized when loaded.
