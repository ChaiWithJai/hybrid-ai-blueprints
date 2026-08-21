"""End-to-end proof of the CareLine loop, using synthetic personas (no real PHI).

Call 1 (fine): Dorothy shares plans → facts land in memory.
Call 2 (recall): agent should reference the recital from call 1 unprompted.
Call 3 (concerning): scripted decline signals → escalation alert must fire.

Run: uv run python scripts/demo_run.py  (server must be up on :8100)

Two modes, because one of the checks depends on the resident having no history:

  --resident-id dorothy-01   (default) the id the browser console shows, so the
                             run populates the UI you then look at. Memory
                             accumulates across runs by design.
  --fresh                    a run-scoped resident, so every check is meaningful
                             no matter how many times this has run before. This
                             is what scripts/verify uses.

The first-call greeting check asks whether the agent invented a shared history.
That question only has an answer when the resident genuinely has none. On a
resident who already has facts, a greeting referencing them is correct
behaviour, so the check reports itself as not applicable rather than failing --
a regression that only passes the first time it is ever run is not a regression.
"""

import argparse
import sys
import uuid

import httpx

BASE = "http://localhost:8100"

CALL_1 = [
    "Oh hello dear, I'm doing alright today. I had my oatmeal this morning.",
    "Well, my granddaughter Emily has her piano recital on Saturday, I'm very excited about that.",
    "Yes, I slept fine. I'm going to water my tomatoes this afternoon.",
]

CALL_2 = [
    "Hello again! I'm well, thank you for asking.",
    "Oh yes, I'm still looking forward to it very much.",
]

CALL_3 = [
    "Oh... hello. I'm not doing so well today, to be honest.",
    "I felt dizzy this morning and I fell in the kitchen. I didn't hurt myself badly but it scared me.",
    "And I haven't had much appetite, I've been feeling a bit lonely since Sunday.",
]


def run_call(
    client: httpx.Client, label: str, lines: list[str], resident_id: str
) -> tuple[dict, list[dict], str]:
    print(f"\n{'=' * 60}\n{label}\n{'=' * 60}")
    r = client.post(f"{BASE}/api/calls", json={"resident_id": resident_id, "name": "Dorothy"})
    r.raise_for_status()
    call = r.json()
    call_id = call["call_id"]
    greeting = call["greeting"]
    print(f"AGENT: {greeting}")
    fired: list[dict] = []
    for line in lines:
        print(f"DOROTHY: {line}")
        t = client.post(f"{BASE}/api/calls/{call_id}/turn", json={"text": line})
        t.raise_for_status()
        data = t.json()
        print(f"AGENT: {data['reply']}")
        if data["alert"]:
            fired.append(data["alert"])
            print(f"🚨 ESCALATION FIRED → {data['alert']['severity'].upper()}: {data['alert']['reason']}")
    e = client.post(f"{BASE}/api/calls/{call_id}/end")
    e.raise_for_status()
    result = e.json()
    print(f"\n[call summary] {result['summary']}")
    print(f"[facts saved] {result['facts']}")
    print(f"[concern score] {result['concern_score']}")
    return result, fired, greeting


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--resident-id",
        default="dorothy-01",
        help="resident to call (default: dorothy-01, the id the browser console shows)",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="use a run-scoped resident so every check is meaningful on a used database",
    )
    args = parser.parse_args()
    resident_id = f"dorothy-{uuid.uuid4().hex[:8]}" if args.fresh else args.resident_id

    with httpx.Client(timeout=180) as client:
        # Prior facts decide whether the invented-history check has an answer.
        prior = client.get(f"{BASE}/api/residents/{resident_id}/memory").json()
        prior_facts = len(prior.get("facts") or [])
        print(f"resident: {resident_id} ({prior_facts} fact(s) already stored)")

        c1, a1, greeting1 = run_call(client, "CALL 1 — baseline (fine)", CALL_1, resident_id)
        c2, a2, _ = run_call(client, "CALL 2 — cross-session recall test", CALL_2, resident_id)
        c3, a3, _ = run_call(
            client, "CALL 3 — decline scenario (must alert)", CALL_3, resident_id
        )

        mem = client.get(f"{BASE}/api/residents/{resident_id}/memory").json()

        print(f"\n{'=' * 60}\nVERIFICATION\n{'=' * 60}")
        ok_memory = len(mem["facts"]) > 0
        ok_no_early_alerts = not a1 and not a2
        ok_alert_once = len(a3) == 1
        hallucination_terms = [
            "last spoke", "last time", "we spoke", "remember", "as you mentioned",
            "last call", "our last", "since we", "previous call", "again",
        ]
        greeting_clean = not any(t in greeting1.lower() for t in hallucination_terms)

        print(f"memory facts stored: {len(mem['facts'])} {'✅' if ok_memory else '❌'}")
        print(f"no alerts on healthy calls: {'✅' if ok_no_early_alerts else '❌'}")
        print(f"call 3 fired exactly one alert: {len(a3)} {'✅' if ok_alert_once else '❌'}")
        if prior_facts:
            # Referencing real stored facts is correct, not invented. Reported as
            # not measured rather than as a pass, so the gap stays visible.
            print(
                "first-call greeting free of invented history: not applicable "
                f"({resident_id} already had {prior_facts} fact(s); use --fresh to check this)"
            )
            ok_greeting = True
        else:
            print(f"first-call greeting free of invented history: {'✅' if greeting_clean else '❌'}")
            ok_greeting = greeting_clean
        print(f"call 3 concern score: {c3['concern_score']}")
        return 0 if (ok_memory and ok_no_early_alerts and ok_alert_once and ok_greeting) else 1


if __name__ == "__main__":
    sys.exit(main())
