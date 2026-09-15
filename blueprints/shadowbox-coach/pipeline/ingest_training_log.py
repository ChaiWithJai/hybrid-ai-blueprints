#!/usr/bin/env python3
"""Runner: ingest training_log.jsonl into the shared MLflow + MongoDB.

The app writes two event types into pipeline/datasets/training_log.jsonl:
  day_complete   — a finished workout day with its stats/form snapshot
  call_feedback  — the athlete flagged a punch call as wrong (press `x`),
                   i.e. visual-reasoning feedback on the detector

This script logs training progress as MLflow metrics and open-codes the
feedback annotations into failure-mode clusters (error-discovery style:
axial coding over flagged-call type × what-actually-happened). For a full
interactive review session, run the ai-evals-course error-discovery skill
over the same JSONL — this dataset is shaped for it on purpose.

  /Users/jaibhagat/code/prismml/bonsai-lab/.venv/bin/python pipeline/ingest_training_log.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import mlflow

sys.path.insert(0, str(Path(__file__).resolve().parent))
from flow import DATASETS, EXPERIMENT, MONGO_COLLECTION, MONGO_DB, TRACKING_URI, write_mongo

LOG = DATASETS / "training_log.jsonl"


def open_code(fb: dict) -> str:
    """Axial-coding-lite: bucket a wrong-call annotation into a failure mode."""
    actual = str(fb.get("actual", "")).lower()
    called = fb.get("flagged", {}).get("type", "?")
    if "phantom" in actual or not actual.strip():
        return f"phantom:{called}"
    for t in ("jab", "cross", "hook", "uppercut"):
        if t in actual:
            return f"misclass:{called}->{t.upper()}"
    if re.search(r"miss|didn'?t count|not counted|dropped", actual):
        return "missed-punch"
    return f"other:{actual[:40]}"


def main() -> None:
    if not LOG.exists():
        print("no training_log.jsonl yet — train a day in the app first")
        return
    entries = [json.loads(line) for line in LOG.read_text().splitlines() if line.strip()]
    days = [e for e in entries if e.get("type") == "day_complete"]
    feedback = [e for e in entries if e.get("type") == "call_feedback"]

    clusters: dict[str, list[dict]] = defaultdict(list)
    for fb in feedback:
        clusters[open_code(fb)].append(fb)
    cluster_counts = Counter({k: len(v) for k, v in clusters.items()})

    mlflow.set_tracking_uri(TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run(run_name=f"training-log-{datetime.now():%Y%m%d-%H%M}") as run:
        mlflow.log_params({
            "flow": "training-log-ingest",
            "log_file": str(LOG.relative_to(DATASETS.parent.parent)),
            "top_failure_modes": "; ".join(f"{k}×{n}" for k, n in cluster_counts.most_common(5)) or "none",
        })
        metrics = {
            "days_completed": len(days),
            "feedback_annotations": len(feedback),
            "failure_mode_clusters": len(clusters),
        }
        # per-day training curve: step = day index, so MLflow charts the trend
        for i, d in enumerate(days):
            s, f = d.get("stats", {}), d.get("form", {})
            for key, val in [("thrown", s.get("total")), ("avg_power", f.get("avg_power")),
                             ("arm_punch_pct", f.get("arm_punch_pct")),
                             ("avg_retraction_ms", f.get("avg_retraction_ms")),
                             ("guard_height_sw", f.get("guard_height_sw"))]:
                if val is not None:
                    mlflow.log_metric(f"day_{key}", val, step=i)
        mlflow.log_metrics(metrics)
        mlflow.log_artifact(str(LOG))

        clusters_path = DATASETS / "feedback_clusters.json"
        clusters_path.write_text(json.dumps(
            {k: v for k, v in sorted(clusters.items(), key=lambda kv: -len(kv[1]))}, indent=1) + "\n")
        mlflow.log_artifact(str(clusters_path))

        learnings = [
            f"{len(days)} training days logged; {len(feedback)} wrong-call flags in {len(clusters)} failure modes.",
            "Top failure modes: " + (", ".join(f"{k} ({n})" for k, n in cluster_counts.most_common(3)) or "none yet"),
            "Each phantom/misclass cluster is a sweep scenario or recorded-clip request; "
            "run the error-discovery skill on training_log.jsonl for the full review session.",
        ]
        mongo_id = write_mongo({
            "agent": "claude-code",
            "flow": "training-log-ingest",
            "mlflow_run_id": run.info.run_id,
            "mlflow_tracking_uri": TRACKING_URI,
            "experiment": EXPERIMENT,
            "at": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics,
            "failure_modes": dict(cluster_counts),
            "learnings": learnings,
        })
        print(f"mlflow run {run.info.run_id} @ {TRACKING_URI}")
        print(f"mongo doc {mongo_id} @ {MONGO_DB}.{MONGO_COLLECTION}")
        for line in learnings:
            print(f"  · {line}")


if __name__ == "__main__":
    main()
