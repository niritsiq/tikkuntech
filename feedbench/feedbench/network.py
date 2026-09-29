"""Simulated population and follower graph. Same seed -> identical network in every policy."""
from __future__ import annotations

from dataclasses import dataclass, field
import random

from .config import NetworkConfig

COMMUNITY_LEAN = [-0.6, 0.0, 0.6]  # average political lean per community (illustrative)

# ANES-style persona fields (synthetic; Törnberg et al. 2023 sampled real ANES respondents).
# Replace with real survey rows for a serious run.
AGE_GROUPS = ["18-29", "30-44", "45-64", "65+"]
NEWS_BY_SIDE = {
    "left": ["NYT", "NPR", "The Guardian"],
    "center": ["Reuters", "AP", "local TV news"],
    "right": ["Fox News", "WSJ opinion", "talk radio"],
}
INTERESTS = ["sports", "cooking", "local politics", "tech", "music", "gardening",
             "personal finance", "movies", "hiking", "gaming", "parenting", "history"]


@dataclass
class Agent:
    id: int
    community: int
    lean: float                 # political lean, -1..1
    activity: float             # P(opens the app in a round)
    harm_affinity: float        # willingness to endorse antisemitic content (separate from lean!)
    counter_speaker: bool
    in_harm_cluster: bool = False
    follows: set[int] = field(default_factory=set)
    followers: set[int] = field(default_factory=set)
    churned: bool = False
    driver: str = "scripted"    # "scripted" or "llm"
    age_group: str = ""
    news_sources: list[str] = field(default_factory=list)
    interests: list[str] = field(default_factory=list)
    persona_text: str = ""      # set when real OASIS profiles are loaded
    display_name: str = ""      # filled from profiles.py
    handle: str = ""

    @property
    def side(self) -> str:
        return "left" if self.lean < -0.25 else "right" if self.lean > 0.25 else "center"

    def persona(self) -> str:
        """Persona text given to OASIS (and to LLM agents as their system prompt).

        Deliberately does NOT mention the research question, the ranking policy,
        or any instruction to become more or less extreme.
        """
        if self.persona_text:
            return self.persona_text
        party = {"left": "a Democrat", "right": "a Republican", "center": "an independent"}[self.side]
        use = "several times a day" if self.activity > 0.6 else "daily" if self.activity > 0.4 else "a few times a week"
        who = f"You are {self.display_name} (@{self.handle}), {party}" if self.handle else f"You are {party}"
        return (f"{who}, aged {self.age_group}. You get news from {', '.join(self.news_sources)}. "
                f"You use social media {use}. Outside politics you care about {', '.join(self.interests)}.")


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def build_population(cfg: NetworkConfig, seed: int) -> list[Agent]:
    rng = random.Random(f"network-{seed}")
    agents: list[Agent] = []
    for i in range(cfg.n_agents):
        c = i % cfg.n_communities
        agents.append(Agent(
            id=i,
            community=c,
            lean=_clip(rng.gauss(COMMUNITY_LEAN[c % len(COMMUNITY_LEAN)], 0.25), -1, 1),
            activity=_clip(rng.betavariate(2, 3) + 0.15, 0.05, 0.95),
            harm_affinity=rng.betavariate(1, 30),       # ~0.03 on average
            counter_speaker=rng.random() < cfg.counter_speaker_share,
        ))
    for a in agents:
        a.age_group = rng.choice(AGE_GROUPS)
        a.news_sources = rng.sample(NEWS_BY_SIDE[a.side], 2)
        a.interests = rng.sample(INTERESTS, 2)

    # Place the harm cluster: a share in one community, the rest anywhere.
    n_conc = round(cfg.harm_cluster_size * cfg.harm_concentration)
    in_target = [a for a in agents if a.community == cfg.harm_cluster_community]
    others = [a for a in agents if a.community != cfg.harm_cluster_community]
    chosen = rng.sample(in_target, min(n_conc, len(in_target)))
    # "spread" members are drawn from the rest of the population
    rest_pool = others + [a for a in in_target if a not in chosen]
    chosen += rng.sample(rest_pool, min(cfg.harm_cluster_size - len(chosen), len(rest_pool)))
    for a in chosen:
        a.in_harm_cluster = True
        a.harm_affinity = _clip(rng.gauss(cfg.harm_affinity_mean, 0.1), 0.4, 3.0)
        a.counter_speaker = False
        a.activity = _clip(a.activity + 0.2, 0.05, 0.95)  # small, highly active group

    # Follower graph with homophily
    by_comm: dict[int, list[Agent]] = {}
    for a in agents:
        by_comm.setdefault(a.community, []).append(a)
    for a in agents:
        while len(a.follows) < cfg.follows_per_agent:
            if rng.random() < cfg.p_follow_same_community:
                target = rng.choice(by_comm[a.community])
            else:
                target = rng.choice(agents)
            if target.id != a.id:
                a.follows.add(target.id)
                target.followers.add(a.id)
    # Harm-cluster members tend to follow each other (tight group)
    cluster = [a for a in agents if a.in_harm_cluster]
    for a in cluster:
        for b in cluster:
            if a.id != b.id and rng.random() < 0.7:
                a.follows.add(b.id)
                b.followers.add(a.id)
    return agents
