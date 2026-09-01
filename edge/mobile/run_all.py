"""The portfolio sweep — run every demo like a Bending Spoons review.

For each demo: unit tests (deterministic, no model), the fixture scorecard,
and — when the local model server is up — the live scorecard against
Bonsai 1.7b. Prints one portfolio table and exits nonzero if any demo's
required run fails. Evidence lands in edge/mobile/evidence/.

Usage: python3 run_all.py [--fixture-only]
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEMOS_DIR = os.path.join(HERE, "demos")
sys.path.insert(0, HERE)

from edgekit.provider import BonsaiProvider  # noqa: E402


def sh(args, cwd):
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          timeout=1800)
    return proc.returncode, proc.stdout + proc.stderr


def run_demo(demo_dir, live):
    name = os.path.basename(demo_dir)
    row = {"demo": name, "unit": None, "fixture": None, "live": None}

    code, out = sh([sys.executable, "-m", "unittest", "-q"], demo_dir)
    row["unit"] = "pass" if code == 0 else "FAIL"
    row["unit_detail"] = out.strip().splitlines()[-1] if out.strip() else ""

    for mode, enabled in (("fixture", True), ("live", live)):
        if not enabled:
            row[mode] = "skipped" if mode == "live" else None
            continue
        arg = "fixture" if mode == "fixture" else "auto"
        code, out = sh([sys.executable, "app.py", arg], demo_dir)
        verdict = "keep" if code == 0 else "kill"
        # pull per-gate summary out of the scorecard the app printed
        gates = ""
        try:
            card = json.loads(out.rsplit("evidence:", 1)[0])
            gates = ", ".join(
                f"{g['gate']}={'P' if g['passed'] else 'F'}"
                for g in card["gates"])
        except (ValueError, KeyError):
            gates = out.strip()[-200:]
        row[mode] = verdict
        row[f"{mode}_gates"] = gates
    return row


def main():
    fixture_only = "--fixture-only" in sys.argv
    live = (not fixture_only) and BonsaiProvider.available()

    print(f"model server: "
          f"{'up — live runs on 1.7b' if live else 'down or skipped'}\n")

    # platform first: a broken platform invalidates every demo
    code, out = sh([sys.executable, "-m", "unittest", "-q"],
                   os.path.join(HERE, "edgekit"))
    print(f"edgekit platform tests: {'pass' if code == 0 else 'FAIL'}")
    if code != 0:
        print(out)
        return 1

    rows = []
    for entry in sorted(os.listdir(DEMOS_DIR)):
        demo_dir = os.path.join(DEMOS_DIR, entry)
        if os.path.isfile(os.path.join(demo_dir, "app.py")):
            rows.append(run_demo(demo_dir, live))

    print(f"\n{'demo':38s} {'unit':6s} {'fixture':8s} {'live':8s}")
    failures = 0
    for r in rows:
        live_cell = r["live"] or "-"
        print(f"{r['demo']:38s} {r['unit']:6s} {str(r['fixture']):8s} "
              f"{live_cell:8s}")
        if r["unit"] != "pass" or r["fixture"] != "keep":
            failures += 1
    print(f"\n{len(rows)} demos; required failures: {failures}"
          f" (live verdicts are recorded findings, not required gates)")
    for r in rows:
        if r.get("live") == "kill":
            print(f"  live-kill detail {r['demo']}: {r.get('live_gates','')}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
