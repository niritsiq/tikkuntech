"""Model backends for OASIS agents (CAMEL ModelFactory).

* Scripted agents get CAMEL's StubModel: OASIS requires a model object, but the
  scripted agents never call it, so runs are free and offline.
* LLM agents use any OpenAI-compatible endpoint, which covers:
    - OpenAI / Anthropic-compatible gateways           (FEEDBENCH_API_KEY)
    - Together AI  (e.g. together/Tev1-4B-experimental) base_url https://api.together.xyz/v1
    - TypeSafe Jev (check their docs for the base URL / model name)
    - a self-hosted fine-tune served by vLLM / TGI on your GPU box
  Set FEEDBENCH_API_KEY in the environment; never commit keys.

Note: OASIS LLM agents act through tool calls. Decision-only models (Jev/Tev-style)
that return a choice rather than tool calls need a thin adapter: have them pick
from the options [like, repost, comment, ignore] per post and translate the pick
into the same OASIS actions the scripted agent uses (see simulation._execute).
"""
from __future__ import annotations

import os

from camel.models import ModelFactory
from camel.types import ModelPlatformType, ModelType


def stub_model():
    return ModelFactory.create(model_platform=ModelPlatformType.OPENAI, model_type=ModelType.STUB)


def make_model(cfg):
    if not cfg.llm_model:
        raise ValueError("llm_agent_share > 0 but no llm_model configured")
    key = os.environ.get("FEEDBENCH_API_KEY")
    if not key:
        raise ValueError("Set FEEDBENCH_API_KEY to use LLM agents")
    return ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
        model_type=cfg.llm_model,
        url=cfg.llm_base_url or "https://api.openai.com/v1",
        api_key=key,
        model_config_dict={"temperature": 0.7, "max_tokens": 300},
    )
