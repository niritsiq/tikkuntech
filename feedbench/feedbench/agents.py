"""Interface B: agent behaviour.

Input : agent persona/state + the ORDERED feed OASIS delivered.
Output: a list of decisions (like / repost / comment / ignore) and whether the session ends.

`ScriptedAgent` is the transparent, zero-cost baseline. It is a set of explicit
assumptions, not a model of real people. LLM-driven agents (llm.py) plug into the
same OASIS platform and see the same ranked feed, so the two can be compared.

Important: the scripted agent never knows which ranking policy is running.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import random

from .config import BehaviorConfig
from .profiles import BENIGN_REPLIES, COUNTER_REPLIES, organic_tweet


@dataclass
class Decision:
    action: str                 # "like" | "repost" | "comment" | "create_post"
    post_id: int | None = None
    text: str = ""
    label: str = "benign"       # expert-rubric label of any text the agent produces


@dataclass
class SessionResult:
    decisions: list[Decision]
    left_early: bool = False
    churned: bool = False


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


class ScriptedAgent:
    def __init__(self, cfg: BehaviorConfig):
        self.cfg = cfg

    def affinity(self, agent, item: dict) -> float:
        """How much this agent 'wants' to engage with a post (0..~1.3)."""
        if item["label"] == "harmful":
            return agent.harm_affinity
        a = math.exp(-abs(agent.lean - item["lean"]) * self.cfg.lean_sensitivity)
        if item["author_community"] == agent.community:
            a *= self.cfg.same_community_boost
        boost = item.get("community_boost")
        if boost and boost["community"] == agent.community:
            a *= boost["factor"]            # benign concentrated cascade (control post)
        return a

    def session(self, agent, feed: list[dict], rng: random.Random, event_started: bool = False) -> SessionResult:
        c = self.cfg
        out: list[Decision] = []
        for pos, item in enumerate(feed):
            if rng.random() > 0.9 * (c.position_decay ** pos):
                continue                                   # scrolled past without reading
            aff = self.affinity(agent, item)
            proof = 1 + c.social_proof * math.log1p(item["endorsements"])
            harmful = item["label"] == "harmful"

            p_like = _clip(c.base_like * aff * proof)
            p_repost = _clip(c.base_repost * aff * proof)
            if harmful:
                p_reply_support = c.base_reply * aff * 1.3
                p_reply_counter = (c.outrage_reply + (0.10 if agent.counter_speaker else 0.0)) * max(0.0, 1 - aff)
            else:
                p_reply_support = c.base_reply * aff
                p_reply_counter = 0.0

            r = rng.random()
            acc = 0.0
            for action, p in (("like", p_like), ("repost", p_repost),
                              ("comment", p_reply_support), ("counter", p_reply_counter)):
                acc += p
                if r < acc:
                    if action == "comment":
                        lbl = "harmful" if harmful else "benign"
                        txt = (f"[HARMFUL PLACEHOLDER: supportive reply to post {item['post_id']}]"
                               if harmful else rng.choice(BENIGN_REPLIES))
                        out.append(Decision("comment", item["post_id"], txt, lbl))
                    elif action == "counter":
                        out.append(Decision("comment", item["post_id"], rng.choice(COUNTER_REPLIES), "counter"))
                    else:
                        out.append(Decision(action, item["post_id"], label=item["label"]))
                    break

            # Explicit, adjustable assumption: exposure to antisemitism drives some users away.
            if harmful and aff < 0.3:
                if rng.random() < c.churn_rate:
                    return SessionResult(out, left_early=True, churned=True)
                if rng.random() < c.harm_aversion:
                    return SessionResult(out, left_early=True)

        if rng.random() < c.organic_post_rate:
            if event_started and agent.in_harm_cluster and rng.random() < agent.harm_affinity:
                # Scenario assumption: after the event the cluster keeps producing antisemitic posts.
                # Placeholder text only; the expert team supplies reviewed examples.
                out.append(Decision("create_post", None,
                                    "[HARMFUL PLACEHOLDER: antisemitic post about the bank collapse]",
                                    "harmful"))
            else:
                out.append(Decision("create_post", None, organic_tweet(agent, rng, event_started), "benign"))
        return SessionResult(out)
