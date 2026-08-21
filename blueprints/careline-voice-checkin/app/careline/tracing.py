"""OpenTelemetry tracing for the CareLine voice loop, in OpenInference format.

Why this exists: the blueprint's central claim is a by-stakes router across the
Bonsai family, and that claim is invisible without traces. A span per turn shows
WHICH tier answered, how long it took, and what the decline scorer decided --
which is the difference between asserting local AI and demonstrating it.

Design constraints:

  * NEVER fatal. A voice call must not fail because a collector is down. Every
    entry point degrades to a no-op span, and export errors are swallowed.
  * OpenInference semantic conventions, so Phoenix/Arize render LLM spans with
    model, prompts, completions and token counts instead of opaque timings.
  * Off unless configured. Tracing turns on when CARELINE_TRACE_ENDPOINT is set
    (or CARELINE_TRACE=1 for the local Phoenix default), so the blueprint runs
    unchanged with no observability stack present.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

_TRACER = None
_ENABLED = False


def init() -> bool:
    """Configure the exporter once. Returns whether tracing is live."""
    global _TRACER, _ENABLED
    if _TRACER is not None:
        return _ENABLED

    endpoint = os.environ.get("CARELINE_TRACE_ENDPOINT")
    if not endpoint and os.environ.get("CARELINE_TRACE", "").lower() in ("1", "true", "yes"):
        endpoint = "http://localhost:6006/v1/traces"   # Phoenix default
    if not endpoint:
        _TRACER, _ENABLED = _NoopTracer(), False
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(
            resource=Resource.create({
                "service.name": os.environ.get("CARELINE_TRACE_SERVICE", "careline"),
                "openinference.project.name": os.environ.get(
                    "CARELINE_TRACE_PROJECT", "careline-voice-checkin"),
            })
        )
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        _TRACER, _ENABLED = trace.get_tracer("careline"), True
        return True
    except Exception:
        # Misconfigured or missing deps must not take the call down.
        _TRACER, _ENABLED = _NoopTracer(), False
        return False


class _NoopSpan:
    def set_attribute(self, *a, **k): pass
    def set_attributes(self, *a, **k): pass
    def record_exception(self, *a, **k): pass
    def set_status(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _NoopTracer:
    @contextmanager
    def start_as_current_span(self, *a, **k):
        yield _NoopSpan()


def _tracer():
    if _TRACER is None:
        init()
    return _TRACER


@contextmanager
def span(name: str, kind: str = "CHAIN", **attrs):
    """Generic span. `kind` is an OpenInference span kind name."""
    try:
        from openinference.semconv.trace import SpanAttributes
        base = {SpanAttributes.OPENINFERENCE_SPAN_KIND: kind}
    except Exception:
        base = {}
    with _tracer().start_as_current_span(name) as sp:
        try:
            sp.set_attributes({**base, **{k: v for k, v in attrs.items() if v is not None}})
        except Exception:
            pass
        yield sp


@contextmanager
def llm_span(name: str, *, model: str, endpoint: str, tier: str, messages=None):
    """LLM span carrying the attributes Phoenix/Arize need to render a call.

    `tier` is the blueprint-specific bit: it records WHICH by-stakes tier served
    the turn, which is what makes the router legible in a trace.
    """
    try:
        from openinference.semconv.trace import SpanAttributes as S
        attrs = {
            S.OPENINFERENCE_SPAN_KIND: "LLM",
            S.LLM_MODEL_NAME: model,
            S.LLM_PROVIDER: "local",
            S.LLM_SYSTEM: "openai",
        }
        in_key, out_key, tok_in, tok_out, tok_all = (
            S.INPUT_VALUE, S.OUTPUT_VALUE,
            S.LLM_TOKEN_COUNT_PROMPT, S.LLM_TOKEN_COUNT_COMPLETION, S.LLM_TOKEN_COUNT_TOTAL,
        )
    except Exception:
        attrs, in_key, out_key = {}, "input.value", "output.value"
        tok_in, tok_out, tok_all = (
            "llm.token_count.prompt", "llm.token_count.completion", "llm.token_count.total")

    attrs.update({"careline.tier": tier, "careline.endpoint": endpoint})
    if messages:
        try:
            last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
            attrs[in_key] = str(last)[:2000]
        except Exception:
            pass

    with _tracer().start_as_current_span(name) as sp:
        try:
            sp.set_attributes(attrs)
        except Exception:
            pass

        def finish(output: str = "", usage: dict | None = None, fell_back: bool = False):
            try:
                if output:
                    sp.set_attribute(out_key, str(output)[:2000])
                if usage:
                    for key, attr in (("prompt_tokens", tok_in),
                                      ("completion_tokens", tok_out),
                                      ("total_tokens", tok_all)):
                        if usage.get(key) is not None:
                            sp.set_attribute(attr, int(usage[key]))
                # Fallbacks are the interesting failure mode: a tier that is down
                # or returns an empty reply is invisible without this flag.
                sp.set_attribute("careline.fell_back", bool(fell_back))
            except Exception:
                pass

        sp.finish_llm = finish  # type: ignore[attr-defined]
        yield sp
