# TikkunTech Ranking Lab

Compare feed-ranking rules in the same synthetic social network. The lab measures antisemitic exposure and what each rule costs ordinary participation, counterspeech, and posts about Jewish community life. It illustrates a mechanism under declared assumptions; it does not predict effects on a real platform. See [HACKATHON_PLAN.md](HACKATHON_PLAN.md) for the full design.

## Run

Requires Python 3.8+ and no other dependencies.

```bash
python app.py            # computes the benchmark, then serves http://127.0.0.1:8000
python simulate.py       # regenerate web/data only
python simulate.py --rule sqrt           # print feedback for an exploratory rule
python simulate.py --rule capped --cap 4
```

## Dashboard

- **Headline**: antisemitic exposure change, plus retention of ordinary engagement, counterspeech exposure, and Jewish community-life reach. Each shows raw counts and the range across seeds, with automatic plain-language feedback per fixture.
- **Replay**: the same 50 agents shown side by side under two rules, round by round. Click an agent to see their feed and scores.
- **Post inspector**: per-community endorsement counts and the score arithmetic under each rule, with a harmful focus post and a benign control.
- **Algorithm lab**: test a ranking change (capped, square-root diminishing returns, breadth only, chronological control) on all fixtures and seeds. Each run is added to a comparison table. Lab runs are labelled *exploratory*; only the capped rule at cap 2 is pre-registered.
- **Cap sensitivity**: caps 1–6 per fixture, with seed-range bands.
- **Reviewer feedback**: mentors and experts leave notes. Each note is tied to the rule, cap, fixture, and config hash. Notes go to `runs/feedback_log.jsonl`, and every lab run is logged to `runs/experiment_log.jsonl`.

## Files

| File | Purpose |
|---|---|
| `sample_data.py` | Frozen fictional agents, posts, draft labels, and the three fixtures |
| `simulate.py` | Ranking rules, paired simulation, metrics, feedback, cap sweep, exports |
| `app.py` | Local server with `/api/experiment` and `/api/feedback` |
| `web/index.html` | Dashboard, with no external dependencies |
| `web/data/` | Saved pre-registered run: `results.json`, `events.csv`, `config.json`, `posts.json`, `agents.json` |
