"""End-to-end proof of the CareLine loop, using synthetic personas (no real PHI).

Call 1 (fine): Dorothy shares plans → facts land in memory.
Call 2 (recall): agent should reference the recital from call 1 unprompted.
Call 3 (concerning): scripted decline signals → escalation alert must fire.

Run: uv run python scripts/demo_run.py  (server must be up on :8100)
"""

import sys

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


def run_call(client: httpx.Client, label: str, lines: list[str]) -> tuple[dict, list[dict], str]:
    print(f"\n{'=' * 60}\n{label}\n{'=' * 60}")
    r = client.post(f"{BASE}/api/calls", json={"resident_id": "dorothy-01", "name": "Dorothy"})
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
    with httpx.Client(timeout=180) as client:
        c1, a1, greeting1 = run_call(client, "CALL 1 — baseline (fine)", CALL_1)
        c2, a2, _ = run_call(client, "CALL 2 — cross-session recall test", CALL_2)
        c3, a3, _ = run_call(client, "CALL 3 — decline scenario (must alert)", CALL_3)

        mem = client.get(f"{BASE}/api/residents/dorothy-01/memory").json()

        print(f"\n{'=' * 60}\nVERIFICATION\n{'=' * 60}")
        ok_memory = len(mem["facts"]) > 0
        ok_no_early_alerts = not a1 and not a2
        ok_alert_once = len(a3) == 1
        # first-call greeting must not pretend a shared history (only meaningful on a fresh DB)
        hallucination_terms = [
            "last spoke", "last time", "we spoke", "remember", "as you mentioned",
            "last call", "our last", "since we", "previous call", "again",
        ]
        ok_greeting = not any(t in greeting1.lower() for t in hallucination_terms)
        print(f"memory facts stored: {len(mem['facts'])} {'✅' if ok_memory else '❌'}")
        print(f"no alerts on healthy calls: {'✅' if ok_no_early_alerts else '❌'}")
        print(f"call 3 fired exactly one alert: {len(a3)} {'✅' if ok_alert_once else '❌'}")
        print(f"first-call greeting free of invented history: {'✅' if ok_greeting else '❌'}")
        print(f"call 3 concern score: {c3['concern_score']}")
        return 0 if (ok_memory and ok_no_early_alerts and ok_alert_once and ok_greeting) else 1


if __name__ == "__main__":
    sys.exit(main())
