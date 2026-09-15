#!/usr/bin/env python3
"""Scutworker: assemble app/workout_guide.json + civilization_report.json
from a prismml-workout-civilization workflow result file.

  python3 pipeline/assemble_guide.py <workflow-output-file> <workflow-run-id>
"""
import json
import sys
from pathlib import Path

BLUEPRINT = Path(__file__).resolve().parent.parent
raw = Path(sys.argv[1]).read_text()
run_id = sys.argv[2]
outer = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
res = outer.get("result", outer)
res["totalTokens"] = outer.get("totalTokens", res.get("totalTokens"))
ed, arch = res["editorial"], res["arch"]

guide = {
    "title": ed["title"], "tagline": ed["tagline"],
    "source": "https://boxing.dharmicdata.org (owner: Jai Bhagat)",
    "built_by": f"prismml-eng agent civilization (workflow {run_id})",
    "gate_text": ed["gate_text"], "coach_guidance": ed["coach_guidance"],
    "signoff_notes": ed["signoff_notes"], "gates": arch["gate_criteria"],
    "phase1": {"program": "basic", "title": arch["phase1_title"],
               "intro": ed["phase1_intro"], "days": res["phase1Days"]},
    "phase2": {"program": "competitive", "title": arch["phase2_title"],
               "intro": ed["phase2_intro"], "days": res["phase2Days"]},
}
(BLUEPRINT / "app" / "workout_guide.json").write_text(json.dumps(guide, indent=1) + "\n")

report = {
    "workflow_run_id": run_id, "agents": 13,
    "total_tokens": res.get("totalTokens"),
    "judge1": res["judge1"], "judge2": res["judge2"], "qa": res["qa"],
    "verifierIssues": res["verifierIssues"], "contractIssues": res["contractIssues"],
    "arch": arch, "editorial": ed,
}
(BLUEPRINT / "pipeline" / "datasets" / "civilization_report.json").write_text(
    json.dumps(report, indent=1) + "\n")

p1, p2 = len(guide["phase1"]["days"]), len(guide["phase2"]["days"])
blocks = sum(len(d["blocks"]) for p in ("phase1", "phase2") for d in guide[p]["days"])
print(f"guide: {p1}+{p2} days, {blocks} blocks | judges {res['judge1']['overall']}/"
      f"{res['judge2']['overall']} | qa pass={res['qa']['pass']} | "
      f"verifier issues {len(res['verifierIssues'])} | contract {len(res['contractIssues'])}")
