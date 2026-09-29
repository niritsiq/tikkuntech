"use strict";

const $ = (id) => document.getElementById(id);
const communities = ["Cedar", "Willow", "Maple", "Birch", "Olive"];
const labelNames = {antisemitic: "Antisemitic · draft", ordinary: "Ordinary · draft", counterspeech: "Counterspeech · draft", ambiguous: "Ambiguous · draft"};
const state = {bundle: null, scenario: 0, seed: 11, agent: "a01", round: 1, timer: null};
const escapeHTML = (value) => String(value).replace(/[&<>"']/g, (char) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]));
const percent = (value, digits = 1) => value == null ? "N/A" : `${(value * 100).toFixed(digits)}%`;
const pp = (value) => value == null ? "N/A" : `${value > 0 ? "+" : ""}${value.toFixed(1)} pp`;
const scenario = () => state.bundle.scenarios[state.scenario];
const run = () => scenario().runs.find((item) => item.seed === state.seed);
const postById = (id) => state.bundle.posts.find((post) => post.id === id);
const agentById = (id) => state.bundle.agents.find((agent) => agent.id === id);

function stopReplay() {
  if (state.timer) clearInterval(state.timer);
  state.timer = null;
  $("play-button").innerHTML = '<span aria-hidden="true">▶</span> Replay run';
}

function renderMetrics() {
  const current = run();
  const a = current.policies.baseline.metrics;
  const b = current.policies.capped.metrics;
  const c = current.comparison;
  $("run-context").textContent = `Full run · all six rounds · seed ${state.seed}`;
  $("metrics").innerHTML = `
    <article class="metric-card"><div class="metric-label">Antisemitic exposure <span aria-hidden="true">↘</span></div><div class="metric-value">${percent(a.harmful_exposure_rate)}<span class="metric-arrow">→</span><span class="alternative-value">${percent(b.harmful_exposure_rate)}</span></div><div class="metric-caption">${a.harmful_impressions} / ${a.total_impressions} → ${b.harmful_impressions} / ${b.total_impressions} impressions</div><div class="metric-detail"><span class="delta">${pp(c.harmful_exposure_delta_pp)}</span> capped minus baseline</div></article>
    <article class="metric-card"><div class="metric-label">Ordinary engagement retained <span aria-hidden="true">↔</span></div><div class="metric-value">${percent(c.ordinary_engagement_retention, 0)}</div><div class="metric-caption">${b.ordinary_actions} capped / ${a.ordinary_actions} baseline actions</div><div class="metric-detail">Ordinary reach retained: ${percent(c.ordinary_reach_retention, 0)}</div></article>
    <article class="metric-card"><div class="metric-label">Counterspeech exposure retained <span aria-hidden="true">↔</span></div><div class="metric-value">${percent(c.counterspeech_exposure_retention, 0)}</div><div class="metric-caption">${b.counterspeech_impressions} capped / ${a.counterspeech_impressions} baseline impressions</div><div class="metric-detail">Engagement retained: ${percent(c.counterspeech_engagement_retention, 0)}</div></article>
    <article class="metric-card reach"><div class="metric-label">Agents exposed to antisemitism <span aria-hidden="true">◎</span></div><div class="metric-value">${a.harmful_reach_count}<small> / 50</small><span class="metric-arrow">→</span><span class="alternative-value">${b.harmful_reach_count}<small> / 50</small></span></div><div class="metric-caption">At least one harmful feed impression</div><div class="metric-detail">Ambiguous exposure: ${a.ambiguous_impressions} → ${b.ambiguous_impressions}</div></article>`;
  $("scenario-description").textContent = scenario().description;
  const range = scenario().summary.comparisons.harmful_exposure_delta_pp;
  $("seed-range").textContent = `Five-seed change: ${pp(range.min)} to ${pp(range.max)}`;
}

function renderChart() {
  const policies = run().policies;
  const width = 660, height = 190, left = 37, right = 16, top = 12, bottom = 26;
  const values = ["baseline", "capped"].flatMap((policy) => policies[policy].rounds.map((r) => r.metrics.harmful_exposure_rate * 100));
  const maximum = Math.max(10, Math.ceil(Math.max(...values) / 10) * 10);
  const x = (i) => left + i * (width - left - right) / 5;
  const y = (value) => height - bottom - value * (height - top - bottom) / maximum;
  let elements = `<title>Antisemitic exposure for seed ${state.seed}</title><desc>Baseline and community-capped cumulative exposure across six rounds. Values are percentages of delivered impressions.</desc>`;
  for (let tick = 0; tick <= 4; tick++) {
    const value = maximum * tick / 4;
    elements += `<line x1="${left}" y1="${y(value)}" x2="${width - right}" y2="${y(value)}" stroke="#eef0e9"/><text x="${left - 9}" y="${y(value) + 3}" text-anchor="end" fill="#849084" font-size="9">${value.toFixed(0)}%</text>`;
  }
  elements += `<line x1="${x(state.round - 1)}" y1="${top}" x2="${x(state.round - 1)}" y2="${height - bottom}" stroke="#d1c8ec" stroke-dasharray="4 4"/>`;
  for (let i = 0; i < 6; i++) elements += `<text x="${x(i)}" y="${height - 6}" text-anchor="middle" fill="#849084" font-size="9">Round ${i + 1}</text>`;
  for (const [policy, color] of [["baseline", "#344b5d"], ["capped", "#6b58c8"]]) {
    const points = policies[policy].rounds.map((snapshot, i) => [x(i), y(snapshot.metrics.harmful_exposure_rate * 100)]);
    elements += `<polyline points="${points.map((p) => p.join(",")).join(" ")}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linejoin="round"/>`;
    points.forEach((point, i) => {elements += `<circle cx="${point[0]}" cy="${point[1]}" r="${i === state.round - 1 ? 4.5 : 3}" fill="${color}" stroke="white" stroke-width="1.5"><title>${policy}, round ${i + 1}: ${percent(policies[policy].rounds[i].metrics.harmful_exposure_rate)}</title></circle>`;});
  }
  $("exposure-chart").innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Baseline and capped cumulative harmful exposure">${elements}</svg>`;
}

function renderFeed(policy) {
  const feed = run().policies[policy].rounds[state.round - 1].feeds[state.agent];
  $(`${policy}-feed`).innerHTML = feed.map((item, index) => {
    const post = postById(item.post_id);
    const author = agentById(post.author_id);
    const actionText = {none: "No action on this post", like: "♡ Liked this post", reshare: "↗ Reshared the original post"}[item.action];
    return `<button class="post-card" data-policy="${policy}" data-post="${post.id}" aria-label="Inspect ${escapeHTML(post.id)}, ${escapeHTML(labelNames[post.label])}, score ${item.score}"><div class="post-top"><span class="post-author"><span class="mini-avatar">${escapeHTML(author.name.slice(0, 1))}${author.name.slice(-2)}</span>${escapeHTML(author.name)}</span><span class="post-rank">#${index + 1} · ${post.id}</span></div><p class="post-text">${escapeHTML(post.text)}</p><div class="post-bottom"><span class="label-pill ${post.label}">${escapeHTML(labelNames[post.label])}</span><span>${escapeHTML(post.topic)}</span><span class="post-score">Score ${item.score}</span><span class="inspect-hint" aria-hidden="true">↗</span></div><div class="action-text ${item.action === "none" ? "" : "acted"}">${actionText}</div></button>`;
  }).join("");
}

function renderReplay() {
  const agent = agentById(state.agent);
  $("agent-profile").innerHTML = `<span class="agent-avatar">${escapeHTML(agent.name.slice(0, 1))}${agent.name.slice(-2)}</span><div><strong>${escapeHTML(agent.name)} · ${escapeHTML(communities[agent.community])} community</strong><small>${escapeHTML(agent.political_view)} · ${Math.round(agent.activity * 100)}% activity propensity</small></div>`;
  $("round-label").textContent = `Round ${state.round} / 6`;
  $("round-slider").value = state.round;
  $("previous-round").disabled = state.round === 1;
  $("next-round").disabled = state.round === 6;
  renderFeed("baseline"); renderFeed("capped"); renderChart();
}

function renderSeeds() {
  $("seed-table").innerHTML = scenario().runs.map((item) => `<tr class="${item.seed === state.seed ? "selected-row" : ""}"><td><button data-seed="${item.seed}" aria-label="View seed ${item.seed}">${item.seed} ${item.seed === state.seed ? "·" : ""}</button></td><td>${percent(item.policies.baseline.metrics.harmful_exposure_rate)}</td><td>${percent(item.policies.capped.metrics.harmful_exposure_rate)}</td><td>${pp(item.comparison.harmful_exposure_delta_pp)}</td><td>${percent(item.comparison.ordinary_engagement_retention, 0)}</td><td>${percent(item.comparison.counterspeech_exposure_retention, 0)}</td></tr>`).join("");
}

function render() { renderMetrics(); renderReplay(); renderSeeds(); }

function inspectPost(policy, postId) {
  const post = postById(postId);
  const item = run().policies[policy].rounds[state.round - 1].feeds[state.agent].find((entry) => entry.post_id === postId);
  const counts = item.community_counts;
  const baseline = counts.reduce((a, b) => a + b, 0);
  const capped = counts.reduce((a, b) => a + Math.min(b, state.bundle.config.cap), 0);
  const largest = Math.max(...counts, 1);
  $("post-inspector").innerHTML = `<span class="label-pill ${post.label}">${escapeHTML(labelNames[post.label])}</span><h2 id="dialog-title">Post ${post.id}: support behind the score</h2><p class="inspector-text">${escapeHTML(post.text)}</p><p class="metric-caption">${policy === "baseline" ? "Baseline" : "Capped"} state · round ${state.round} · seed ${state.seed}. Both formulas below use this same snapshot.</p><div class="inspector-scores"><div><span>Total endorsements</span><strong>${baseline}</strong></div><div><span>Capped at ${state.bundle.config.cap} per community</span><strong>${capped}</strong></div></div>${counts.map((count, i) => `<div class="community-bar"><span class="community-name">${communities[i]}</span><div class="bar-track"><div class="bar-fill" style="width:${100 * count / largest}%"></div></div><span class="count">${count} → ${Math.min(count, state.bundle.config.cap)}</span></div>`).join("")}<p class="inspector-note"><strong>Evaluation only · awaiting expert review</strong><br>${escapeHTML(post.label_reason)}<br>The ranking and action model cannot read this label.</p>`;
  $("post-dialog").showModal();
}

function changeRound(number) { state.round = Math.max(1, Math.min(6, number)); renderReplay(); }

function wireControls() {
  $("scenario-select").addEventListener("change", (event) => {stopReplay(); state.scenario = Number(event.target.value); state.round = 1; render();});
  $("seed-select").addEventListener("change", (event) => {stopReplay(); state.seed = Number(event.target.value); state.round = 1; render();});
  $("agent-select").addEventListener("change", (event) => {state.agent = event.target.value; renderReplay();});
  $("round-slider").addEventListener("input", (event) => {stopReplay(); changeRound(Number(event.target.value));});
  $("previous-round").addEventListener("click", () => {stopReplay(); changeRound(state.round - 1);});
  $("next-round").addEventListener("click", () => {stopReplay(); changeRound(state.round + 1);});
  $("play-button").addEventListener("click", () => {
    if (state.timer) {stopReplay(); return;}
    changeRound(1);
    $("play-button").innerHTML = '<span aria-hidden="true">Ⅱ</span> Pause replay';
    state.timer = setInterval(() => {changeRound(state.round + 1); if (state.round === 6) stopReplay();}, 1400);
  });
  $("dashboard").addEventListener("click", (event) => {
    const card = event.target.closest(".post-card");
    if (card) {stopReplay(); inspectPost(card.dataset.policy, card.dataset.post);}
    const seedButton = event.target.closest("[data-seed]");
    if (seedButton) {stopReplay(); state.seed = Number(seedButton.dataset.seed); $("seed-select").value = state.seed; state.round = 1; render();}
  });
  $("close-dialog").addEventListener("click", () => $("post-dialog").close());
  $("post-dialog").addEventListener("click", (event) => {if (event.target === $("post-dialog")) {const box = event.target.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) event.target.close();}});
  document.addEventListener("visibilitychange", () => {if (document.hidden) stopReplay();});
}

async function init() {
  try {
    const response = await fetch("data/results.json");
    if (!response.ok) throw new Error(`Results could not be loaded (${response.status}).`);
    state.bundle = await response.json();
    $("scenario-select").innerHTML = state.bundle.scenarios.map((item, i) => `<option value="${i}">${escapeHTML(item.name)}</option>`).join("");
    $("seed-select").innerHTML = state.bundle.config.seeds.map((seed) => `<option value="${seed}">${seed}</option>`).join("");
    $("agent-select").innerHTML = state.bundle.agents.map((agent) => `<option value="${agent.id}">${escapeHTML(agent.name)}</option>`).join("");
    $("build-info").textContent = `Python simulator · v${state.bundle.meta.version} · fixture ${state.bundle.meta.config_hash.slice(0, 8)}`;
    wireControls(); render();
    $("loading").hidden = true; $("dashboard").hidden = false;
  } catch (error) {
    $("loading").hidden = true; $("error").hidden = false;
    $("error").textContent = `${error.message} Start the demo with “python app.py” and open http://127.0.0.1:8000.`;
  }
}
init();
