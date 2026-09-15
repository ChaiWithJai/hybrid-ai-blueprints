#!/usr/bin/env python3
"""Coherence pass: give every workout block a TRACKING CONTRACT, audit the
alignment between MediaPipe scoring and workout content, and ground the coach.

1. Classify all 450 blocks into tracking modes:
     punch        — detector fully hot: count, classify, feed gates
     defense      — slips/rolls/head movement: pose form only, no punch counting
     movement     — stance/footwork: pose form only
     conditioning — push-ups/squats/lifts: scoring PAUSED (a push-up is a
                    fast arm extension from a horizontal torso — phantom city)
   Modes are written INTO app/workout_guide.json so the session player pauses
   and resumes scoring per block.
2. Audit coherence: coverage, phantom-risk exposure, coach_focus validity,
   days whose gate stats would have been polluted — scored and logged to the
   shared MLflow + Mongo.
3. Ground the coach: datasets/bonsai_program_sft.jsonl — program-expert
   instruction pairs (day plans, arc, gates) for fine-tuning Bonsai into THE
   coach of this program.

  /Users/jaibhagat/code/prismml/bonsai-lab/.venv/bin/python pipeline/annotate_guide.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import mlflow

sys.path.insert(0, str(Path(__file__).resolve().parent))
from flow import APP, DATASETS, EXPERIMENT, MONGO_COLLECTION, MONGO_DB, TRACKING_URI, write_mongo

GUIDE_PATH = APP / "workout_guide.json"
KB_PATH = APP / "coach_kb.json"

# priority order matters: "slip + punch" counter-punches → punch;
# "freestyle work with 3s sprints" → punch, not conditioning
MODE_RULES = [
    ("punch", re.compile(r"bag|shadow ?box|freestyle|sparring|pad work|punch|jab|cross\b|hook|uppercut|combo|combination|fight|tennis ball|counter", re.I)),
    ("defense", re.compile(r"slip|roll|head movement|duck|parry|defensive|defence|defense", re.I)),
    ("movement", re.compile(r"stance|movement|footwork|agility|shuffle|pendulum|pivot|shift|step drill|balance", re.I)),
    ("conditioning", re.compile(r"push-?up|squat|climber|burpee|plank|jump|crunch|sit-?up|pull-?up|med ?ball|dumbbell|barbell|lift|sets? of|reps|circuit|endurance|mobility|stretch|rope|sprawl|raises|jacks|tucks|sprint|conditioning|weighted stick|hip bridge|wall sit|juggling", re.I)),
    # source-vague blocks that are camera-visible boxing rounds ("supplemental
    # rounds", "timed round", "opening round", "partner work", "interval drill")
    ("punch", re.compile(r"supplemental|timed round|opening round|partner work|interval", re.I)),
]


def block_mode(b: dict) -> str:
    text = f"{b.get('name','')} {b.get('prescription','')} {b.get('source_drill','')}"
    for mode, rx in MODE_RULES:
        if rx.search(text):
            return mode
    return "unknown"


def main() -> None:
    guide = json.loads(GUIDE_PATH.read_text())
    kb_themes = set(json.loads(KB_PATH.read_text())["focuses"].keys())

    total = classified = phantom_risk = focus_bad = 0
    mode_counts: dict[str, int] = {}
    incoherent_days = []
    for pkey in ("phase1", "phase2"):
        for d in guide[pkey]["days"]:
            day_ok = True
            if d["coach_focus"] not in kb_themes:
                focus_bad += 1
                day_ok = False
            for b in d["blocks"]:
                total += 1
                mode = block_mode(b)
                b["mode"] = mode if mode != "unknown" else "punch"  # safe default: keep scoring
                mode_counts[b["mode"]] = mode_counts.get(b["mode"], 0) + 1
                if mode == "unknown":
                    day_ok = False
                else:
                    classified += 1
                if mode == "conditioning":
                    phantom_risk += 1  # was scored before this pass — now paused
            if not day_ok:
                incoherent_days.append(f"{d['program']} w{d['week']}d{d['day']}")

    days_total = 70
    coherence = (days_total - len(incoherent_days)) / days_total
    GUIDE_PATH.write_text(json.dumps(guide, indent=1) + "\n")

    # ---- program-expert SFT: the coach that KNOWS this program ----
    SYSTEM = ("You are the dedicated corner coach for the 70-day program "
              f"'{guide['title']}'. You know every day, every block, the weekly "
              "focus arc, and the phase gates. Be specific and punchy.")
    rows = []
    all_days = [(1, d) for d in guide["phase1"]["days"]] + [(2, d) for d in guide["phase2"]["days"]]
    for i, (phase, d) in enumerate(all_days):
        blocks_line = "; ".join(f"{b['name']} [{b['mode']}] — {b['prescription']}" for b in d["blocks"])[:700]
        rows.append({"messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"I'm on phase {phase}, week {d['week']}, day {d['day']}. What's today and why?"},
            {"role": "assistant", "content": f"{d['title']} — focus: {d['focus']}. {d['summary']} Blocks: {blocks_line or 'rest — recover fully.'}"},
        ]})
        if i + 1 < len(all_days):
            np_, nd = all_days[i + 1]
            rows.append({"messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"What comes after {d['title']} (phase {phase} w{d['week']}d{d['day']})?"},
                {"role": "assistant", "content": f"Phase {np_} week {nd['week']} day {nd['day']}: {nd['title']} — {nd['focus']}. {nd['summary']}"},
            ]})
    for g in guide["gates"]:
        rows.append({"messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Why does the phase gate require {g['stat']} {g['threshold']}?"},
            {"role": "assistant", "content": g["why"]},
        ]})
    rows.append({"messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "How do I graduate from phase 1?"},
        {"role": "assistant", "content": guide["gate_text"]},
    ]})
    sft_path = DATASETS / "bonsai_program_sft.jsonl"
    with sft_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    report = {
        "blocks_total": total,
        "blocks_classified": classified,
        "coverage": classified / total,
        "mode_counts": mode_counts,
        "phantom_risk_blocks_now_paused": phantom_risk,
        "coach_focus_invalid_days": focus_bad,
        "incoherent_days": incoherent_days,
        "coherence_score": coherence,
        "program_sft_pairs": len(rows),
    }
    (DATASETS / "coherence_report.json").write_text(json.dumps(report, indent=1) + "\n")

    mlflow.set_tracking_uri(TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run(run_name=f"coherence-{datetime.now():%Y%m%d-%H%M}") as run:
        mlflow.log_params({"flow": "coherence-annotate", "modes": ",".join(mode_counts)})
        mlflow.log_metrics({
            "coherence_score": coherence,
            "block_coverage": classified / total,
            "phantom_risk_blocks": phantom_risk,
            "focus_invalid_days": focus_bad,
            "program_sft_pairs": len(rows),
        })
        mlflow.log_artifact(str(DATASETS / "coherence_report.json"))
        mlflow.log_artifact(str(sft_path))
        learnings = [
            f"Coherence {coherence:.2f}: {classified}/{total} blocks under a tracking contract "
            f"({', '.join(f'{k}:{v}' for k, v in sorted(mode_counts.items()))}).",
            f"{phantom_risk} conditioning blocks were feeding phantom punches into gate stats — now paused per contract.",
            f"{len(rows)} program-expert SFT pairs ground the coach in the full 70-day arc.",
        ]
        write_mongo({
            "agent": "claude-code", "flow": "coherence-annotate",
            "mlflow_run_id": run.info.run_id, "mlflow_tracking_uri": TRACKING_URI,
            "experiment": EXPERIMENT, "at": datetime.now(timezone.utc).isoformat(),
            "metrics": report, "learnings": learnings,
        })
        print(f"mlflow run {run.info.run_id}")
        for line in learnings:
            print(f"  · {line}")
        if incoherent_days:
            print("  ! incoherent days:", ", ".join(incoherent_days[:10]))


if __name__ == "__main__":
    main()
