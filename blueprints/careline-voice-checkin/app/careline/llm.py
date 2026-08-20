"""Ollama client via its OpenAI-compatible endpoint.

The blueprint's swap table allows "any OpenAI-compatible" LLM, so on the GB10
this module points at the Nemotron NIM instead — only OLLAMA_BASE_URL and
MODEL change, no code.
"""

import json
import os

import httpx

BASE_URL = os.environ.get("CARELINE_LLM_BASE_URL", "http://localhost:11434/v1")
MODEL = os.environ.get("CARELINE_LLM_MODEL", "qwen2.5:7b")

# By-stakes switch: the strong model (Ternary-Bonsai-27B via the PrismML
# llama.cpp fork's llama-server) handles concerning calls and end-of-call
# extraction; routine turns stay on the fast default. If the strong endpoint
# is down, we silently fall back — a router must never break a live call.
# 8081, not 8080: another llama-server (unrelated project) owns 8080 on this
# machine — see start_llama_server.sh's BONSAI_PORT patch in ~/projects/bonsai-demo.
STRONG_BASE_URL = os.environ.get("CARELINE_LLM_STRONG_BASE_URL", "http://localhost:8081/v1")
STRONG_MODEL = os.environ.get("CARELINE_LLM_STRONG_MODEL", "bonsai-27b")
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
        payload = {
            "model": STRONG_MODEL,
            "messages": messages,
            "temperature": temperature,
        }
        # llama-server treats thinking_budget_tokens=0 as unset (falls back to
        # the server default), so thinking-off is enforced by launching the
        # server with --reasoning-budget 0 and OMITTING the field here; only a
        # positive budget (extraction) is sent as an explicit override.
        budget = TURN_REASONING_BUDGET if reasoning_budget is None else reasoning_budget
        if budget > 0:
            # extraction path: allow bounded thinking + room for the JSON
            payload["thinking_budget_tokens"] = budget
            payload["max_tokens"] = 500
        else:
            # live turns: disable thinking at the template level — the only
            # mechanism that actually works on this model (server-side
            # --reasoning-budget 0 and thinking_budget_tokens:0 both leave the
            # model thinking into reasoning_content; profiled 2026-08-19).
            # max_tokens bounds Bonsai's long-form drift; 120 ≈ two sentences.
            payload["chat_template_kwargs"] = {"enable_thinking": False}
            payload["max_tokens"] = int(os.environ.get("CARELINE_STRONG_MAX_TOKENS", "120"))
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(f"{STRONG_BASE_URL}/chat/completions", json=payload)
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError):
            pass  # fall through to the default backend

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
