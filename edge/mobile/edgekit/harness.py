"""The portfolio scorecard harness.

Every demo runs the same shape of acceptance: a list of named gates, each
a callable returning (passed: bool, detail: str). The scorecard records
which provider mode served the run — a fixture pass and a live pass are
different facts and are never conflated — and ends in a keep/kill verdict:
keep only if every required gate passed. Evidence files land in
edge/mobile/evidence/, following the repository's record-what-ran
conventions.
"""

import json
import os
import time
from dataclasses import dataclass, field


@dataclass
class Gate:
    name: str
    fn: object          # () -> (bool, str)
    required: bool = True
    result: dict = field(default_factory=dict)


def run_gates(demo, gates, mode, model):
    results = []
    for gate in gates:
        started = time.monotonic()
        try:
            passed, detail = gate.fn()
        except Exception as exc:  # a crashing gate is a failing gate
            passed, detail = False, f"exception: {exc!r}"
        results.append({
            "gate": gate.name,
            "required": gate.required,
            "passed": bool(passed),
            "detail": str(detail)[:500],
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
        })
    verdict = "keep" if all(r["passed"] for r in results if r["required"]) \
        else "kill"
    return {
        "demo": demo,
        "mode": mode,
        "model": model,
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "gates": results,
        "verdict": verdict,
    }


def write_evidence(scorecard, evidence_dir):
    os.makedirs(evidence_dir, exist_ok=True)
    path = os.path.join(
        evidence_dir, f"{scorecard['demo']}-{scorecard['mode']}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(scorecard, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return path
