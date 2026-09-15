#!/usr/bin/env python3
"""Runner: log a workout-guide civilization run to the shared MLflow + MongoDB.

Reads app/workout_guide.json and pipeline/datasets/civilization_report.json
(the prismml-eng agent run: judge scores, verifier repairs, QA verdict) and
records the run where every agent can see it.

  /Users/jaibhagat/code/prismml/bonsai-lab/.venv/bin/python pipeline/log_workout_run.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import mlflow

sys.path.insert(0, str(Path(__file__).resolve().parent))
from flow import APP, DATASETS, EXPERIMENT, MONGO_COLLECTION, MONGO_DB, TRACKING_URI, write_mongo

GUIDE = APP / "workout_guide.json"
REPORT = DATASETS / "civilization_report.json"


def main() -> None:
    guide = json.loads(GUIDE.read_text())
    report = json.loads(REPORT.read_text())
    mlflow.set_tracking_uri(TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run(run_name=f"workout-guide-{datetime.now():%Y%m%d-%H%M}") as run:
        mlflow.log_params({
            "flow": "prismml-workout-civilization",
            "workflow_run_id": report.get("workflow_run_id", ""),
            "agents": report.get("agents", 13),
            "roles": "architect(omead), builders(prismml-eng x4), verifiers(reza x4), "
                     "judges(babak panel x2), qa, senior-manager(sahin)",
        })
        j1, j2 = report["judge1"], report["judge2"]
        metrics = {
            "phase1_days": len(guide["phase1"]["days"]),
            "phase2_days": len(guide["phase2"]["days"]),
            "total_blocks": sum(len(d["blocks"]) for p in ("phase1", "phase2") for d in guide[p]["days"]),
            "verifier_repairs": len(report["verifierIssues"]),
            "contract_issues": len(report["contractIssues"]),
            "qa_pass": 1 if report["qa"]["pass"] else 0,
            "judge1_overall": j1["overall"], "judge1_fidelity": j1["fidelity"],
            "judge2_overall": j2["overall"], "judge2_fidelity": j2["fidelity"],
        }
        mlflow.log_metrics(metrics)
        mlflow.log_artifact(str(GUIDE))
        mlflow.log_artifact(str(REPORT))

        learnings = [
            f"Judges scored phase1 {j1['overall']}/10, phase2 {j2['overall']}/10; QA {'passed' if report['qa']['pass'] else 'FAILED'}.",
            f"Verifiers repaired {len(report['verifierIssues'])} builder deviations from the canonical drills.",
            "Sign-off notes: " + guide.get("signoff_notes", "")[:300],
        ]
        mongo_id = write_mongo({
            "agent": "claude-code",
            "flow": "prismml-workout-civilization",
            "mlflow_run_id": run.info.run_id,
            "mlflow_tracking_uri": TRACKING_URI,
            "experiment": EXPERIMENT,
            "at": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics,
            "artifacts": ["app/workout_guide.json", "pipeline/datasets/civilization_report.json"],
            "learnings": learnings,
        })
        print(f"mlflow run {run.info.run_id} @ {TRACKING_URI}")
        print(f"mongo doc {mongo_id} @ {MONGO_DB}.{MONGO_COLLECTION}")
        for line in learnings:
            print(f"  · {line}")


if __name__ == "__main__":
    main()
