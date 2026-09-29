# TikkunTech — minimal ranking benchmark demo

Working scope: a usable prototype in 3–4 hours, followed by optional improvements during the hackathon. This is a proposed plan; no simulation has been run and no outcome is claimed.

**Pitch:** Compare two feed-ranking rules in the same synthetic social network, measuring antisemitic exposure and the cost to ordinary participation.

The deliverable is a reproducible benchmark prototype and a visual replay. It illustrates a mechanism under declared assumptions; it does not estimate effects on a real platform or establish a legal conclusion.

## Scope card — ready to copy

**Team name:** TikkunTech Ranking Lab (working name).

**Challenge route / pillar:** AI & language technologies; content moderation as a secondary fit.

**1. Problem**
Policy analysts and civil-society researchers need transparent ways to compare how feed-ranking choices affect antisemitic exposure and ordinary participation. Our prototype makes one ranking tradeoff visible and reproducible in a controlled synthetic setting.

**2. Intended user / who is affected**
Primary users: civil-society researchers and public-policy analysts evaluating platform design proposals. Potential beneficiaries: Jewish users and communities affected by antisemitic amplification. Platform policy teams are a later audience.

**3. What we plan to build**
A small benchmark with 50 synthetic agents, one fictional event, and two ranking rules: total endorsements versus capped endorsements per network community. A dashboard compares exposure, reach, and ordinary engagement, with a replay and downloadable results.

**4. What we will test**
Whether limiting popularity boosts from endorsements concentrated in one community reduces antisemitic exposure in the chosen scenario, and what it costs ordinary content and counterspeech. We also test a benign concentrated cascade and harmful content supported across communities.

**5. Out of scope**
Real-platform predictions, production integration, model training, automatic community detection, live scraping, multilingual coverage, legal-compliance scoring, and a general-purpose hate-speech classifier.

**6. Key mentor question**
What evidence and safeguards would make this comparison useful for policy discussion, especially when a community cap can also reduce the reach of legitimate minority-community speech?

**7. Scribe / note taker**
Developer 3 owns the decision log, configuration, seeds, and exported runs. One domain expert records label rationales, disagreements, and limitations. Assign actual names at kickoff.

## Minimum experiment

| Component | Fixed choice for the prototype |
|---|---|
| Population | 50 synthetic agents in five network communities of ten |
| Scenario | One fictional shared news event, one language |
| Corpus | Approximately 40 short, frozen, expert-reviewed posts |
| Horizon | Six rounds, three feed items per agent per round |
| Actions | Like, reshare, or skip; at most one action per agent per round |
| Generation | Optional LLM assistance before the run; freeze all text afterward |
| Action selection | Small, documented probabilistic policy; use an existing model only if already working |
| Policies | Total unique endorsements; community-capped unique endorsements |
| Repetitions | Five paired seeds; one selected seed for the replay |
| Storage | Local JSON/CSV; SQLite if OASIS already supplies it |

Network communities are synthetic social clusters. Political views and topic interests are separate attributes; neither community membership nor political identity automatically determines harmfulness. Do not infer real people's attributes.

Use a shared initial endorsement snapshot so the ranking has a signal at the first round. Document how it was constructed. Include both harmful and ordinary posts with concentrated support, and both with broader support. The result depends on this fixture and the behavior assumptions.

Keep the horizon short: with a small fixed corpus, a long run that hides previously seen posts eventually shows nearly everything to everyone. For the prototype, hide posts already shown to that agent and use the same eligibility rule in both policies. Log an impression only for a delivered feed item. A reshare references the original post rather than creating a new independently ranked copy.

### Ranking rule

Let `n[g,p]` be the number of distinct agents in community `g` who endorsed post `p` through a like or reshare. One agent contributes at most one endorsement to that post, even if they perform both actions.

```text
Baseline score(p)     = sum over communities of n[g,p]
Alternative score(p)  = sum over communities of min(n[g,p], 2)
```

Use the same candidate eligibility and the same recency tie-break followed by a stable seeded tie-break. For this first comparison, omit additional relevance weights and ranking features. Call the baseline a simplified engagement ranking, not a reproduction of a commercial platform.

Example: ten supporters from one community give a baseline score of 10 and a capped score of 2. Two supporters from each of five communities give 10 under both rules. The intervention rewards breadth of support; it does not recognize antisemitism.

### Fair comparison and labels

- Clone the same initial state for the two policies. Keep personas, graph, posts, initial endorsements, exposure budget, and behavior rules identical.
- Fix the cap at two before inspecting results. Do not tune it on the displayed run.
- Match random decisions by stable keys such as `(seed, round, agent, post, decision)`. A single shared RNG seed is insufficient if different feeds consume draws in a different order.
- Use a simple behavioral rule based on topic affinity, social ties, and fixed activity preferences. Keep evaluation labels out of ranking and action selection. Document any correlation built into the scenario.
- Experts label posts before results are shown: antisemitic; ordinary; counterspeech/reporting; ambiguous. Include Jewish community life, legitimate policy criticism, and benign concentrated discussion. Record rationale and disputed examples.
- Exclude ambiguous posts from the primary harmful numerator, keep all delivered impressions in its denominator, and display ambiguous exposure separately. Count a reference to hate differently from endorsement of it when context warrants.
- Preserve initial and final state plus a delivered-impression/action log. Labels are joined only for evaluation.

### Metrics

| Metric | Definition |
|---|---|
| Antisemitic exposure | Antisemitic feed impressions / all delivered feed impressions; also show the raw numerator |
| Antisemitic reach | Number of agents exposed at least once / 50 |
| Ordinary engagement retention | Ordinary likes and reshares under the cap / ordinary likes and reshares under baseline |
| Ordinary reach retention | Distinct agent–ordinary-post exposures under the cap / the same quantity under baseline |
| Counterspeech retention | Report exposure and engagement retention separately from ordinary posts |

Show raw counts alongside ratios. If a baseline denominator is zero, show `N/A` and the counts. Describe these as simulated engagement and communication proxies, not measurements of human satisfaction or conversation quality.

Report paired differences for all five seeds and their range. Do not present five runs as evidence of statistical significance. A zero or adverse effect is a valid benchmark result.

### Minimum validity checks

Keep one event and reuse its posts for three named fixtures:

1. Harmful amplification concentrated in one community: the proposed mechanism may help.
2. Ordinary or counterspeech amplification concentrated in one community: reveals collateral loss.
3. Harmful amplification distributed across communities: reveals where the cap may provide little benefit.

Do not choose the headline seed after seeing which result looks best. Freeze the fixtures, cap, seed list, and metrics before the final comparison. Display each fixture separately rather than pooling them into an unexplained average.

**Engineering success:** both policies run from the same fixture; feed impressions are logged; all metrics can be reproduced; the dashboard replays actual saved output.

**Research question:** does the cap reduce harmful exposure, and at what cost? Do not promise a positive finding or choose a target reduction after observing results. Any numerical acceptance threshold should be agreed with the experts before running the comparison.

## Technology and budget decisions

OASIS documents custom recommendation systems through a specialized `Platform` overriding `update_rec_table`. Its quickstart also supports `ManualAction`, which can help inject controlled actions. Verify these paths against the installed version.

- [OASIS recommendation documentation](https://github.com/camel-ai/oasis/blob/main/docs/key_modules/recommendation_system.mdx)
- [OASIS quickstart](https://github.com/camel-ai/oasis/blob/main/docs/quickstart.mdx)

**Decision gate at 30 minutes:** continue with OASIS only if a tiny run completes and you can control the feed ranking and capture delivered impressions. Otherwise implement the same small loop in plain Python and keep an OASIS adapter as a later task. Label which engine produced the results.

“Jev-style models” is not sufficiently specified here to choose an implementation. If the team already has a working action selector, keep it behind a small interface and use it identically for both policies. Otherwise defer it. Do not train or integrate a new model for the first demo.

Use one machine for the simulation and an optional familiar web dashboard stack. Other team members can prepare data and UI concurrently. Avoid distributed inference and GPU setup.

Live LLM action selection would require up to `50 × 6 × 2 × 5 = 3,000` decisions for one fixture, before retries or additional fixtures. A frozen corpus plus a simple stochastic action policy makes the benchmark cheap and repeatable. Describe it accurately as AI-assisted synthetic simulation rather than claiming every action is an LLM decision.

Set a **$20 initial API spending cap**, not a cost estimate. Track actual usage and reserve the remaining credits. A later LLM-agent run is an extension, with its own disclosed configuration and results.

## Parallel delivery plan

| Time | Developer 1: simulation | Developer 2: dashboard | Developer 3: evaluation/integration | Two experts |
|---|---|---|---|---|
| 0–30 min | Tiny engine run; decide OASIS or Python | Static side-by-side screen | Freeze input/output schema and configuration | Choose event, rubric, and control examples |
| 30–90 min | Agents, feed selection, both rankers, action log | Load sample results; metrics and replay controls | Metrics, seed pairing, export format | Review frozen corpus and label disagreements |
| 90–150 min | Run paired fixtures; resolve engine bugs | Connect actual outputs and inspectable feed | Verify formulas and controls; run seed batch | Review tradeoffs and proposed claims |
| 150–180 min | Freeze working run | Polish readability and reset/replay | Save reproducible demo bundle | Write limitations and pitch |
| Optional hour 4 | Fix failures only; add small polish if stable | Rehearse presentation | Record a backup demo | Rehearse answers to judging questions |

Suggested shared contract: `agents.json`, `posts.json`, `config.json`, `events.csv`, and `results.json`. Each run records its fixture, policy, seed, cap, and code/configuration version.

## Demo in 90 seconds

1. State: “We test how ranking rules change exposure in a controlled synthetic network.”
2. Show the same agents and initial posts in two panels. Press replay.
3. Show three headline values: antisemitic exposure, ordinary engagement retention, and counterspeech exposure retention. Put raw counts and the seed range nearby.
4. Inspect one post to show how concentrated endorsements change its score. Show a benign control to make the tradeoff visible.
5. Finish with the measured result, including a neutral or negative result, and the limitation: the simulator tests a proposed mechanism, not real-world effectiveness.

Use saved, genuinely computed traces for reliable playback and label them as a replay. A graph visualization is optional; the first useful screen is two feeds, a comparison chart, and inspectable ranking scores.

Further work only after the prototype is stable: more scenarios, larger seed batches, sensitivity to community assignments and cap size, a chronological control, and an LLM action policy evaluated as a separate configuration.
