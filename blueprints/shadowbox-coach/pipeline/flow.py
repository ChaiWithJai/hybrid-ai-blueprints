#!/usr/bin/env python3
"""Recursive self-improvement flow for Shadowbox Coach, documented in MLflow.

Stages (each an MLflow-traced span, per the mlflow tracing skill that ships
with the shared install):

  1. crawl   — fetch the KO Boxing curriculum from boxing.dharmicdata.org
               (both 35-day programs; prerendered Nuxt HTML, cached locally)
  2. parse   — HTML → structured lessons (focus, drills, prescriptions, cues)
  3. coach_kb— distill lessons into app/coach_kb.json so the corner coach
               grounds its cues in the actual curriculum
  4. sft     — emit datasets/bonsai_coach_sft.jsonl (instruction pairs) for
               fine-tuning the Bonsai coach
  5. eval    — run the detector eval suite (node eval.mjs --json) and log
               its metrics into the same MLflow run

Everything logs to the SHARED infra other agents (Codex) use:
  MLflow  http://127.0.0.1:5210          (bonsai-lab tracking server)
  MongoDB mongodb://127.0.0.1:27028      (bonsai-evidence-lab-mongo-1)
so learnings transfer between agents. Run with the bonsai-lab venv:

  /Users/jaibhagat/code/prismml/bonsai-lab/.venv/bin/python pipeline/flow.py
"""

from __future__ import annotations

import html as html_mod
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import mlflow
from mlflow.entities import SpanType

PIPELINE_DIR = Path(__file__).resolve().parent
BLUEPRINT = PIPELINE_DIR.parent
APP = BLUEPRINT / "app"
RAW = PIPELINE_DIR / "raw"
DATASETS = PIPELINE_DIR / "datasets"

BASE = os.environ.get("BOXING_BASE_URL", "https://boxing.dharmicdata.org")
TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://127.0.0.1:5210")
EXPERIMENT = os.environ.get("MLFLOW_EXPERIMENT", "shadowbox-coach")
MONGO_URI = os.environ.get("SHADOWBOX_MONGO_URI", "mongodb://127.0.0.1:27028")
MONGO_DB = os.environ.get("SHADOWBOX_MONGO_DB", "bonsai_evidence_lab")
MONGO_COLLECTION = "shadowbox_flow"

PROGRAMS = {"basic": 5, "competitive": 5}  # program → weeks (7 days each)

CHROME_LINES = {
    "Video", "YouTube", "SOURCE SECTION", "CANONICAL SOURCE", "Training",
    "Programs", "Technique guide", "Course", "KO", "Boxing Training",
    "WORK THE PROGRAM", "Boxing workout", "Inspect source", "Download full plan",
    "Lead video shown above", "Trainer-owned content",
}


def strip_html(raw: str) -> list[str]:
    body = re.sub(r"<script[^>]*>.*?</script>", " ", raw, flags=re.S)
    body = re.sub(r"<style[^>]*>.*?</style>", " ", body, flags=re.S)
    text = html_mod.unescape(re.sub(r"<[^>]+>", "\n", body))
    return [line.strip() for line in text.split("\n") if line.strip()]


@mlflow.trace(span_type=SpanType.RETRIEVER)
def crawl() -> dict[str, str]:
    """Fetch every lesson page (cached in pipeline/raw/)."""
    RAW.mkdir(parents=True, exist_ok=True)
    pages: dict[str, str] = {}
    fetched = 0
    for program, weeks in PROGRAMS.items():
        for week in range(1, weeks + 1):
            for day in range(1, 8):
                key = f"{program}-w{week}-d{day}"
                cache = RAW / f"{key}.html"
                if cache.exists():
                    pages[key] = cache.read_text(encoding="utf-8")
                    continue
                url = f"{BASE}/program/{program}/week/{week}/day/{day}"
                try:
                    with urllib.request.urlopen(url, timeout=20) as resp:
                        content = resp.read().decode("utf-8", errors="replace")
                except Exception as exc:  # a missing day is data, not a crash
                    print(f"  skip {key}: {exc}")
                    continue
                cache.write_text(content, encoding="utf-8")
                pages[key] = content
                fetched += 1
                time.sleep(0.15)
    print(f"crawl: {len(pages)} pages ({fetched} freshly fetched)")
    return pages


DRILL_RE = re.compile(
    r"^[A-Z0-9 #'’:;,.\-()/×xX+&%]{8,110}$"
)
PRESCRIPTION_HINT = re.compile(
    r"\d+\s*(ROUNDS?|MINUTES?|SECONDS?|REPS?|SETS?)|PUSH-?UPS|CLIMBERS|SQUATS|"
    r"BURPEES|JUMPS|CRUNCHES|PLANK|SPRAWLS|SIT-?UPS|SKIP|ROPE"
)


@mlflow.trace(span_type=SpanType.PARSER)
def parse(pages: dict[str, str]) -> list[dict]:
    """Line-oriented extraction from the prerendered lesson HTML."""
    lessons = []
    for key, raw in sorted(pages.items()):
        program, w, d = re.match(r"(\w+)-w(\d+)-d(\d+)", key).groups()
        lines = strip_html(raw)

        def after(marker: str) -> str | None:
            for i, line in enumerate(lines):
                if line == marker and i + 1 < len(lines):
                    return lines[i + 1]
            return None

        meta = next((l for l in lines if re.match(r"^DAY \d+ · WEEK \d+", l)), "")
        title = after(meta) if meta else None
        focus = after("Today’s focus") or after("Today's focus")
        pickup = after("PICKUP")
        dropoff = after("DROPOFF")

        drills: list[dict] = []
        try:
            start = lines.index("SOURCE SECTION")
        except ValueError:
            start = len(lines)
        i = start
        while i < len(lines):
            line = lines[i]
            if (line not in CHROME_LINES and not re.match(r"^#? ?\d{1,3}$", line)
                    and DRILL_RE.match(line) and line == line.upper()
                    and (PRESCRIPTION_HINT.search(line) or "DRILL" in line
                         or "SHADOWBOX" in line or "BAG" in line or "SPARRING" in line)):
                # verbatim trainer-owned wording (typos preserved on purpose)
                if not drills or drills[-1]["text"] != line:
                    drills.append({"text": line})
            i += 1

        lessons.append({
            "program": program, "week": int(w), "day": int(d),
            "meta": meta, "title": title, "focus": focus,
            "pickup": pickup, "dropoff": dropoff,
            "drills": drills,
            "url": f"{BASE}/program/{program}/week/{w}/day/{d}",
        })
    parsed = [l for l in lessons if l["drills"] or l["focus"]]
    print(f"parse: {len(parsed)}/{len(lessons)} lessons with content, "
          f"{sum(len(l['drills']) for l in parsed)} drill lines")
    return parsed


@mlflow.trace(span_type=SpanType.CHAIN)
def build_coach_kb(lessons: list[dict]) -> dict:
    """Group cues + drills by focus theme for the in-app corner coach."""
    kb: dict[str, dict] = {}
    for l in lessons:
        focus = l["focus"] or "General conditioning"
        entry = kb.setdefault(focus, {"cues": [], "drills": []})
        for cue in (l["pickup"], l["dropoff"]):
            if cue and cue not in entry["cues"]:
                entry["cues"].append(cue)
        for drill in l["drills"]:
            if drill["text"] not in entry["drills"]:
                entry["drills"].append(drill["text"])
    for entry in kb.values():
        entry["cues"] = entry["cues"][:6]
        entry["drills"] = entry["drills"][:10]
    out = {
        "source": BASE,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "focuses": kb,
    }
    path = APP / "coach_kb.json"
    path.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"coach_kb: {len(kb)} focus themes → {path.relative_to(BLUEPRINT)}")
    return out


@mlflow.trace(span_type=SpanType.CHAIN)
def build_sft(lessons: list[dict]) -> Path:
    """Instruction pairs for fine-tuning the Bonsai corner coach."""
    SYSTEM = ("You are a boxing corner coach. Ground every cue in the KO Boxing "
              "curriculum. Be specific and punchy; under 40 words; no lists.")
    rows = []
    for l in lessons:
        ref = f"{l['program']} program, week {l['week']} day {l['day']}"
        if l["focus"] and l["dropoff"]:
            rows.append({"messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content":
                    f"My round stats are weak on {l['focus'].lower()}. What should I work on?"},
                {"role": "assistant", "content":
                    f"{l['dropoff']} Work the {ref}: today's focus is {l['focus'].lower()}."},
            ]})
        if l["focus"] and l["pickup"]:
            rows.append({"messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content":
                    f"How should I start a {l['focus'].lower()} session?"},
                {"role": "assistant", "content": l["pickup"]},
            ]})
        for drill in l["drills"][:6]:
            rows.append({"messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content":
                    f"Give me one drill for {(l['focus'] or 'boxing conditioning').lower()}."},
                {"role": "assistant", "content":
                    f"{drill['text'].title()} — from the {ref} ({l['focus'] or 'conditioning'})."},
            ]})
    DATASETS.mkdir(parents=True, exist_ok=True)
    path = DATASETS / "bonsai_coach_sft.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"sft: {len(rows)} pairs → {path.relative_to(BLUEPRINT)}")
    return path


@mlflow.trace(span_type=SpanType.TOOL)
def run_detector_eval() -> dict:
    """The detector's own eval suite, folded into the same MLflow run."""
    out = subprocess.run(
        ["node", "eval.mjs", "--json"], cwd=APP, capture_output=True, text=True, timeout=300,
    )
    if out.returncode != 0:
        raise RuntimeError(f"eval.mjs failed: {out.stderr[-500:]}")
    return json.loads(out.stdout.strip().splitlines()[-1])


def write_mongo(doc: dict) -> str | None:
    try:
        from pymongo import MongoClient
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=4000)
        coll = client[MONGO_DB][MONGO_COLLECTION]
        inserted = coll.insert_one(doc)
        return str(inserted.inserted_id)
    except Exception as exc:
        print(f"mongo write skipped: {exc}", file=sys.stderr)
        return None


def main() -> None:
    mlflow.set_tracking_uri(TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run(run_name=f"boxing-curriculum-{datetime.now():%Y%m%d-%H%M}") as run:
        mlflow.log_params({
            "source": BASE, "programs": ",".join(PROGRAMS),
            "mongo": f"{MONGO_URI}/{MONGO_DB}.{MONGO_COLLECTION}",
        })

        pages = crawl()
        lessons = parse(pages)
        kb = build_coach_kb(lessons)
        sft_path = build_sft(lessons)
        eval_res = run_detector_eval()

        metrics = {
            "pages_crawled": len(pages),
            "lessons_parsed": len(lessons),
            "drill_lines": sum(len(l["drills"]) for l in lessons),
            "kb_focus_themes": len(kb["focuses"]),
            "sft_pairs": sum(1 for _ in sft_path.open()),
            "detector_f1": eval_res["f1"],
            "detector_tp": eval_res["tp"],
            "detector_fp": eval_res["fp"],
            "detector_fn": eval_res["fn"],
            "detector_mean_latency_ms": eval_res["meanLat"],
        }
        mlflow.log_metrics(metrics)
        mlflow.log_artifact(str(APP / "coach_kb.json"))
        mlflow.log_artifact(str(sft_path))

        learnings = [
            "Curriculum wording is trainer-owned and preserved verbatim (incl. typos).",
            "Focus themes map 1:1 to the app's form telemetry: rotation→pivots/combinations, "
            "guard height→defense, retraction→stance and movement.",
            f"Detector at config parity: F1 {eval_res['f1']:.3f}, "
            f"{eval_res['fp']} phantoms / {eval_res['fn']} misses.",
        ]
        mongo_id = write_mongo({
            "agent": "claude-code",
            "flow": "shadowbox-boxing-curriculum",
            "mlflow_run_id": run.info.run_id,
            "mlflow_tracking_uri": TRACKING_URI,
            "experiment": EXPERIMENT,
            "at": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics,
            "artifacts": ["app/coach_kb.json", "pipeline/datasets/bonsai_coach_sft.jsonl"],
            "learnings": learnings,
        })
        print(f"\nmlflow run {run.info.run_id} @ {TRACKING_URI} (experiment: {EXPERIMENT})")
        print(f"mongo doc {mongo_id} @ {MONGO_DB}.{MONGO_COLLECTION}")
        for line in learnings:
            print(f"  · {line}")


if __name__ == "__main__":
    main()
