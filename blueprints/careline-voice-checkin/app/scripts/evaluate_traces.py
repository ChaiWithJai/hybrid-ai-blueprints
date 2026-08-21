#!/usr/bin/env python3
"""Evaluate CareLine traces against the use case's declared critical failures.

Every check here is a `critical_failures` entry from
use-cases/wellness-check-in-calls/tasks/*.yaml, not a metric invented here. The
contract declares what must never happen; this reads the traces and asserts it
did not.

Extends the repo's existing Arize/Phoenix evaluation shape -- the `EvalMetric`
fields (name/score/threshold/passed/explanation/metadata) and the
release-state vocabulary match `core/arize_evals.py`, and results are written
back as Phoenix span annotations so they render beside the spans they judge.

The contract is *reimplemented* rather than imported: ADR 0003 requires a
blueprint's app/ to reach nothing outside its own directory, and `core/` is the
deal room application's package at the repository root. Importing it would
couple this blueprint to another one -- exactly what issue #2 exists to undo.

Usage:
    python scripts/evaluate_traces.py                 # evaluate + write report
    python scripts/evaluate_traces.py --annotate      # also push to Phoenix
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any

PHOENIX = os.environ.get("CARELINE_PHOENIX_URL", "http://localhost:6006")
PROJECT = os.environ.get("CARELINE_TRACE_PROJECT", "careline-voice-checkin")


@dataclass
class EvalMetric:
    """Mirrors core/arize_evals.py:EvalMetric so results are interchangeable."""
    name: str
    score: float
    threshold: float
    passed: bool
    explanation: str
    metadata: dict[str, Any] = field(default_factory=dict)


def gql(query: str) -> dict:
    req = urllib.request.Request(
        f"{PHOENIX}/graphql", data=json.dumps({"query": query}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def flatten(o: Any, prefix: str = "") -> dict:
    out = {}
    for k, v in (o or {}).items():
        if isinstance(v, dict):
            out.update(flatten(v, f"{prefix}{k}."))
        else:
            out[f"{prefix}{k}"] = v
    return out


def fetch_spans(limit: int = 500) -> list[dict]:
    data = gql(
        "{projects(first:50){edges{node{name spans(first:%d){edges{node{"
        "spanId name spanKind latencyMs statusCode attributes}}}}}}}" % limit
    )
    for e in data.get("data", {}).get("projects", {}).get("edges", []):
        if e["node"]["name"] != PROJECT:
            continue
        spans = []
        for se in e["node"]["spans"]["edges"]:
            s = dict(se["node"])
            try:
                s["attr"] = flatten(json.loads(s.get("attributes") or "{}"))
            except Exception:
                s["attr"] = {}
            spans.append(s)
        return spans
    return []


def evaluate(spans: list[dict]) -> list[EvalMetric]:
    turns = [s for s in spans if s["name"] == "careline.turn"]
    llms = [s for s in spans if s["name"].startswith("bonsai.")]
    metrics: list[EvalMetric] = []

    if not turns:
        return [EvalMetric(
            "traces_present", 0.0, 1.0, False,
            f"No careline.turn spans in project {PROJECT!r}. Run a call with "
            "CARELINE_TRACE=1 before evaluating.",
            {"measurement_state": "unverified"},
        )]

    by_call = collections.defaultdict(list)
    for t in turns:
        by_call[t["attr"].get("careline.call_id", "?")].append(t)

    # decline-escalation: "concerning call produces no alert"
    missed = [c for c, ts in by_call.items()
              if any((t["attr"].get("careline.concern_score") or 0) >= 5 for t in ts)
              and not any(t["attr"].get("careline.alert_fired") for t in ts)]
    metrics.append(EvalMetric(
        "escalation.concerning_call_alerts", 1.0 - len(missed) / max(1, len(by_call)), 1.0,
        not missed,
        "Every call reaching the alert threshold raised an alert."
        if not missed else f"Calls crossed the threshold with no alert: {missed}",
        {"calls": len(by_call), "missed": missed,
         "contract": "tasks/decline-escalation.yaml"},
    ))

    # decline-escalation: "healthy call produces an alert"
    false_pos = [c for c, ts in by_call.items()
                 if all((t["attr"].get("careline.concern_score") or 0) == 0 for t in ts)
                 and any(t["attr"].get("careline.alert_fired") for t in ts)]
    metrics.append(EvalMetric(
        "escalation.no_alert_on_healthy", 1.0 - len(false_pos) / max(1, len(by_call)), 1.0,
        not false_pos,
        "No healthy call raised an alert." if not false_pos
        else f"Healthy calls raised alerts: {false_pos}",
        {"false_positive_calls": false_pos, "contract": "tasks/decline-escalation.yaml"},
    ))

    # decline-escalation: "alert fired repeatedly for the same concern in one call"
    repeats = {}
    for c, ts in by_call.items():
        sev = collections.Counter(t["attr"].get("careline.alert_severity") or ""
                                  for t in ts if t["attr"].get("careline.alert_fired"))
        dupes = {k: v for k, v in sev.items() if k and v > 1}
        if dupes:
            repeats[c] = dupes
    metrics.append(EvalMetric(
        "escalation.debounced_per_severity", 0.0 if repeats else 1.0, 1.0, not repeats,
        "At most one alert per severity per call." if not repeats
        else f"Severity fired more than once: {repeats}",
        {"repeats": repeats, "contract": "tasks/decline-escalation.yaml"},
    ))

    # decline-escalation: "escalation decision made by model judgment instead of
    # the deterministic scorer" -- routing must be a pure function of the score.
    inconsistent = [
        {"call": t["attr"].get("careline.call_id"),
         "score": t["attr"].get("careline.concern_score"),
         "route": t["attr"].get("careline.route")}
        for t in turns
        if (t["attr"].get("careline.route") == "concerning")
        != ((t["attr"].get("careline.concern_score") or 0) > 0)
    ]
    metrics.append(EvalMetric(
        "routing.deterministic_from_scorer",
        1.0 - len(inconsistent) / max(1, len(turns)), 1.0, not inconsistent,
        "Tier selection matched the deterministic scorer on every turn."
        if not inconsistent else f"Route diverged from score on {len(inconsistent)} turn(s)",
        {"divergences": inconsistent[:5], "turns": len(turns),
         "contract": "tasks/decline-escalation.yaml"},
    ))

    # cross-session-continuity: "extraction returns empty and the memory write is
    # silently dropped"
    extractions = [s for s in llms if s["attr"].get("careline.tier") == "extraction"]
    empty = [s["spanId"] for s in extractions if s["attr"].get("careline.empty_reply")]
    metrics.append(EvalMetric(
        "memory.extraction_not_silently_dropped",
        1.0 - len(empty) / max(1, len(extractions)) if extractions else 0.0, 1.0,
        bool(extractions) and not empty,
        f"All {len(extractions)} extraction call(s) returned content."
        if extractions and not empty else
        ("No extraction span observed -- end a call to exercise it."
         if not extractions else f"Empty extraction replies: {empty}"),
        {"extractions": len(extractions), "empty": empty,
         "measurement_state": "unverified" if not extractions else "measured",
         "contract": "tasks/cross-session-continuity.yaml"},
    ))

    # Local-AI claim: every tier answered locally, nothing silently fell back.
    fellback = [s["name"] for s in llms if s["attr"].get("careline.fell_back")]
    tiers = sorted({s["attr"].get("careline.tier") for s in llms if s["attr"].get("careline.tier")})
    models = sorted({s["attr"].get("llm.model_name") for s in llms if s["attr"].get("llm.model_name")})
    metrics.append(EvalMetric(
        "runtime.local_tiers_served", 1.0 - len(fellback) / max(1, len(llms)), 1.0,
        not fellback,
        f"All {len(llms)} model call(s) served locally by tiers {tiers} ({models})."
        if not fellback else f"Fell back on: {collections.Counter(fellback)}",
        {"tiers": tiers, "models": models, "fell_back": len(fellback)},
    ))
    return metrics


def release_state(ms: list[EvalMetric]) -> dict:
    """Same vocabulary as core/arize_evals.py:evaluation_release_state."""
    if not ms:
        return {"state": "unverified", "label": "No evaluations"}
    hard = [m for m in ms if not m.passed
            and m.metadata.get("measurement_state") != "unverified"]
    if hard:
        return {"state": "rejected", "label": "Guard rejected",
                "explanation": hard[0].explanation}
    soft = [m for m in ms if not m.passed]
    if soft:
        return {"state": "unverified", "label": "Evidence missing",
                "explanation": soft[0].explanation}
    return {"state": "verified", "label": "Guards passed"}


def annotate(metrics: list[EvalMetric], spans: list[dict]) -> int:
    """Push results to Phoenix as span annotations so they render with the spans."""
    turn = next((s for s in spans if s["name"] == "careline.turn"), None)
    if not turn:
        return 0
    sent = 0
    for m in metrics:
        body = {"data": [{
            "span_id": turn["spanId"], "name": m.name,
            "annotator_kind": "CODE",
            "result": {"label": "pass" if m.passed else "fail",
                       "score": m.score, "explanation": m.explanation[:900]},
            "metadata": {k: str(v)[:200] for k, v in m.metadata.items()},
        }]}
        req = urllib.request.Request(
            f"{PHOENIX}/v1/span_annotations?sync=false",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30):
                sent += 1
        except Exception as exc:
            print(f"  annotation {m.name} failed: {type(exc).__name__}")
    return sent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotate", action="store_true")
    ap.add_argument("--out", default="/tmp/careline_trace_eval.json")
    a = ap.parse_args()

    spans = fetch_spans()
    print(f"project {PROJECT!r}: {len(spans)} spans\n")
    metrics = evaluate(spans)
    for m in metrics:
        print(f"[{'PASS' if m.passed else 'FAIL'}] {m.name:44s} {m.score:5.2f}  {m.explanation}")
    state = release_state(metrics)
    print(f"\nrelease state: {state['state'].upper()} — {state['label']}")

    if a.annotate:
        print(f"annotations pushed to Phoenix: {annotate(metrics, spans)}")

    with open(a.out, "w") as f:
        json.dump({"project": PROJECT, "spans": len(spans),
                   "release_state": state,
                   "evaluations": [asdict(m) for m in metrics]}, f, indent=1)
    print(f"report -> {a.out}")
    return 0 if state["state"] == "verified" else 1


if __name__ == "__main__":
    sys.exit(main())
