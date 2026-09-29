"""Experiment configuration. Every number here is an explicit, adjustable assumption."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field, asdict
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Ranking rules (see ranking.py). The first two are the headline comparison.
POLICIES = {
    "total_endorsements": "A · Total endorsements",
    "community_capped": "B · Capped endorsements per community",
    "total_with_replies": "A′ · Total, replies count as endorsements",
    "capped_with_replies": "B′ · Capped, replies count as endorsements",
    "bridging": "T · Bridging (Törnberg et al. 2023-style)",
    "chronological": "N · No popularity (network + recency)",
}
PRIMARY = ["total_endorsements", "community_capped"]


@dataclass
class NetworkConfig:
    n_agents: int = 50
    n_communities: int = 3
    follows_per_agent: int = 8
    p_follow_same_community: float = 0.8   # homophily
    # Small, tightly connected, highly active group willing to endorse antisemitic content
    harm_cluster_size: int = 8
    # 1.0 = whole cluster sits in one community; 0.0 = spread across communities
    harm_concentration: float = 1.0
    harm_cluster_community: int = 2
    # Engagement multiplier of cluster members on antisemitic posts (0.7 ≈ enthusiastic,
    # 2.5 ≈ coordinated: they endorse almost everything the cluster posts)
    harm_affinity_mean: float = 0.7
    counter_speaker_share: float = 0.2     # agents inclined to post counterspeech


@dataclass
class RankingConfig:
    feed_size: int = 5
    in_network_slots: int = 2           # posts from followed accounts (ranked by the rule)
    exploration_slots: int = 1          # random eligible post, same rule under A and B
    candidate_window: int = 6           # posts older than this many rounds are not eligible
    community_cap: int = 2              # rule B: max endorsements counted per community
    w_popularity: float = 1.0
    w_follow_author: float = 1.5
    w_followed_endorser: float = 1.0    # per followed account that endorsed (max 3)
    w_author_affinity: float = 1.0      # per past engagement of the viewer with this author (max 3)
    w_recency: float = 1.0
    recency_decay: float = 0.8


@dataclass
class BehaviorConfig:
    base_like: float = 0.30
    base_repost: float = 0.10
    base_reply: float = 0.06
    position_decay: float = 0.85        # attention falls with feed position
    same_community_boost: float = 1.3
    lean_sensitivity: float = 1.2
    social_proof: float = 0.15          # herd effect on visible endorsements; same under A and B
    outrage_reply: float = 0.15         # low-affinity users replying to/arguing with harmful posts
    organic_post_rate: float = 0.3      # chance an active agent writes a new post
    # Explicit assumption: seeing antisemitic content drives some users away
    harm_aversion: float = 0.15         # P(end session early | harmful post seen, low affinity)
    churn_rate: float = 0.03            # P(leave platform for good | harmful post seen, low affinity)


@dataclass
class ExperimentConfig:
    scenario: str = "coordinated"
    rounds: int = 20
    seeds: list[int] = field(default_factory=lambda: [1, 2, 3, 4, 5])
    policies: list[str] = field(default_factory=lambda: list(PRIMARY))
    baseline: str = "total_endorsements"
    # Pre-registered thresholds — decide BEFORE looking at results
    target_harm_reduction: float = 0.20        # antisemitic impressions at least 20% lower
    min_engagement_retained: float = 0.95      # ordinary engagement at least 95% of baseline
    min_counterspeech_retained: float = 0.90   # counterspeech exposure at least 90% of baseline
    include_harmful_posts: bool = True
    network: NetworkConfig = field(default_factory=NetworkConfig)
    ranking: RankingConfig = field(default_factory=RankingConfig)
    behavior: BehaviorConfig = field(default_factory=BehaviorConfig)
    scenario_path: str = str(DATA_DIR / "scenario.json")
    profiles_path: str = ""          # OASIS profile file (JSON or Twitter CSV); empty = generated users
    # LLM action policy — a SEPARATE configuration, off by default
    llm_agent_share: float = 0.0
    llm_model: str = ""
    llm_base_url: str = ""
    workdir: str = "runs"

    def to_dict(self) -> dict:
        return asdict(self)


# ---- scenario presets (scope card §4) --------------------------------------------

SCENARIOS = {
    "coordinated": {
        "title": "Concentrated, coordinated cluster",
        "question": "Main test: a tight cluster inside one community endorses nearly every antisemitic "
                    "post it sees. This is the situation the cap is designed for.",
        "overrides": {"network.harm_affinity_mean": 2.5},
    },
    "concentrated": {
        "title": "Concentrated, uncoordinated cluster",
        "question": "Same cluster, but members endorse only some antisemitic posts. "
                    "Does the cap still matter when concentrated popularity is weak?",
        "overrides": {"network.harm_affinity_mean": 0.7},
    },
    "cross_community": {
        "title": "Antisemitism supported across communities",
        "question": "Stress test: the coordinated cluster is spread over all three communities. "
                    "The cap is expected to help less.",
        "overrides": {"network.harm_affinity_mean": 2.5, "network.harm_concentration": 0.0},
    },
    "benign_cascade": {
        "title": "Benign concentrated cascade (no antisemitic content)",
        "question": "Cost test: only ordinary content, incl. a Jewish community-center post endorsed "
                    "heavily by its own community. What does the cap cost legitimate minority speech?",
        "overrides": {"network.harm_cluster_size": 0, "include_harmful_posts": False},
    },
}


def make_config(scenario: str = "coordinated", **overrides) -> ExperimentConfig:
    cfg = ExperimentConfig(scenario=scenario)
    for key, val in {**SCENARIOS[scenario]["overrides"], **overrides}.items():
        if "." in key:
            section, attr = key.split(".", 1)
            setattr(getattr(cfg, section), attr, val)
        else:
            setattr(cfg, key, val)
    return copy.deepcopy(cfg)
