"""Ollama client via its OpenAI-compatible endpoint.

The blueprint's swap table allows "any OpenAI-compatible" LLM, so on the GB10
this module points at the Nemotron NIM instead — only OLLAMA_BASE_URL and
MODEL change, no code.
"""

import json
import os

import httpx

# THREE-TIER BONSAI FAMILY RUNTIME (measured 2026-08-21, LM Studio on :1234).
# The tiers exist because latency, not quality, decides what can serve a live
# phone call. Measured on this machine, same prompt:
#
#   27b@q1_0   25.9s   always emits ~2.2k chars of reasoning   -> post-hangup only
#   8b          1.9s   no reasoning                            -> live, concerning turns
#   4b          1.2s   no reasoning                            -> live, routine turns
#   1.7b        1.1s   no reasoning                            -> spare
#
# So the whole runtime is Bonsai: routine turns on 4B, concerning turns lean on
# 8B, and the 27B does end-of-call extraction where its 26s is hidden after
# hangup. Nothing leaves the machine.
BASE_URL = os.environ.get("CARELINE_LLM_BASE_URL", "http://localhost:1234/v1")
MODEL = os.environ.get("CARELINE_LLM_MODEL", "4b")

# By-stakes switch: concerning turns lean on a larger Bonsai; routine turns stay
# on the fast tier. If a tier is unreachable OR returns an empty reply, we fall
# back — a router must never break a live call.
# Live concerning turns: 8B is the largest Bonsai that answers inside a
# conversational beat. Do NOT point this at the 27B -- it reasons for ~26s on
# every call, which stalls the conversation and, under a small max_tokens cap,
# returns an EMPTY reply (all tokens spent thinking).
STRONG_BASE_URL = os.environ.get("CARELINE_LLM_STRONG_BASE_URL", "http://localhost:1234/v1")
STRONG_MODEL = os.environ.get("CARELINE_LLM_STRONG_MODEL", "8b")

# Post-hangup extraction: the 27B ternary model, where thinking is an asset and
# its latency is invisible. LM Studio IGNORES chat_template_kwargs, so thinking
# cannot be switched off there -- the budget must instead be large enough to
# cover reasoning AND the answer, or the reply comes back empty.
EXTRACT_BASE_URL = os.environ.get("CARELINE_LLM_EXTRACT_BASE_URL", "http://localhost:1234/v1")
EXTRACT_MODEL = os.environ.get("CARELINE_LLM_EXTRACT_MODEL", "27b@q1_0")
EXTRACT_MAX_TOKENS = int(os.environ.get("CARELINE_EXTRACT_MAX_TOKENS", "3000"))
# Bonsai 27B is a reasoning model; cap thinking per path (llama-server accepts
# thinking_budget_tokens per request — see Bonsai AGENTS.md). Profiled 2026-08-19:
# a 512 budget added ~30s of silent thinking to every live strong turn at
# ~17 tok/s, so live turns get a small budget and only the post-hangup
# extraction gets room to think. Live turns use 0 (thinking OFF), not a small
# cap: a truncated budget makes the model leak raw reasoning into the spoken
# reply (observed at 64), while 0 cleanly disables it.
TURN_REASONING_BUDGET = int(os.environ.get("CARELINE_REASONING_BUDGET_TURN", "0"))
EXTRACT_REASONING_BUDGET = int(os.environ.get("CARELINE_REASONING_BUDGET_EXTRACT", "512"))


async def chat(
    messages: list[dict],
    temperature: float = 0.6,
    strong: bool = False,
    reasoning_budget: int | None = None,
) -> str:
    if strong:
        # reasoning_budget > 0 marks the post-hangup extraction path, which gets
        # the 27B. Live turns get the 8B: the 27B reasons ~26s on every call.
        extracting = (reasoning_budget or 0) > 0
        if extracting:
            url, model = EXTRACT_BASE_URL, EXTRACT_MODEL
            # Budget must cover reasoning AND the answer. A tight cap returns an
            # empty reply with every token spent thinking (measured: 300 fails,
            # 3000 works). chat_template_kwargs is sent for servers that honour
            # it (the llama.cpp fork); LM Studio ignores it, hence the budget.
            payload = {
                "model": model, "messages": messages, "temperature": temperature,
                "max_tokens": EXTRACT_MAX_TOKENS,
            }
        else:
            url, model = STRONG_BASE_URL, STRONG_MODEL
            payload = {
                "model": model, "messages": messages, "temperature": temperature,
                "chat_template_kwargs": {"enable_thinking": False},
                "max_tokens": int(os.environ.get("CARELINE_STRONG_MAX_TOKENS", "120")),
            }
        try:
            async with httpx.AsyncClient(timeout=300 if extracting else 60) as client:
                resp = await client.post(f"{url}/chat/completions", json=payload)
                resp.raise_for_status()
                msg = resp.json()["choices"][0]["message"]
            content = (msg.get("content") or "").strip()
            if not content:
                # Reasoning models sometimes put the answer only in the reasoning
                # channel. Recover it rather than speaking silence.
                content = (msg.get("reasoning_content") or "").strip()
            if content:
                return content
            # Still empty: fall through to the fast tier. Returning "" here would
            # make the agent silently say nothing, which reads as a dead call.
        except (httpx.HTTPError, KeyError, IndexError):
            pass  # tier down -> fast tier

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{BASE_URL}/chat/completions",
            json={"model": MODEL, "messages": messages, "temperature": temperature},
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def _extract_json(raw: str) -> dict | list:
    """Pull the first JSON object out of a reply, tolerating fences and prose."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1].removeprefix("json").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {}


async def chat_json(messages: list[dict], strong: bool = False) -> dict | list:
    """Chat expecting a JSON reply; tolerates code fences and surrounding prose.

    A failed parse on the strong model retries once on the default model —
    an empty extraction silently drops memory facts, which is never acceptable.
    """
    result = _extract_json(
        await chat(
            messages, temperature=0.1, strong=strong, reasoning_budget=EXTRACT_REASONING_BUDGET
        )
    )
    if not result and strong:
        result = _extract_json(await chat(messages, temperature=0.1, strong=False))
    return result
