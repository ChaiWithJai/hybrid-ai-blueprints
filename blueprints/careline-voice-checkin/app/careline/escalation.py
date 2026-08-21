"""Decline detection + escalation gateway.

Baseline is deliberately keyword/threshold on the transcript (per plan —
paralinguistic modeling is a stretch goal, not core). The alert sink is an
OpenClaw stand-in: on the GB10 this POST goes to OpenClaw's messaging
integration (Telegram bot); here it logs and optionally hits a webhook.
"""

import os

import httpx

from . import memory

# concern keywords → weight
CONCERN_TERMS: dict[str, int] = {
    "fell": 3, "fall": 3, "fallen": 3,
    "chest pain": 4, "can't breathe": 4, "cannot breathe": 4,
    "dizzy": 2, "pain": 2, "hurts": 2, "hurt": 2,
    "confused": 2, "forget": 1, "forgot": 1,
    "lonely": 2, "alone": 1, "sad": 1, "crying": 2, "hopeless": 3,
    "not eating": 3, "no appetite": 2, "skipped": 1,
    "can't sleep": 2, "haven't slept": 2,
    "medication": 1, "missed my pills": 3, "out of pills": 3,
}

ALERT_THRESHOLD = int(os.environ.get("CARELINE_ALERT_THRESHOLD", "3"))
WEBHOOK_URL = os.environ.get("CARELINE_ALERT_WEBHOOK", "")


def score_utterance(text: str) -> tuple[int, list[str]]:
    lowered = text.lower()
    hits = [term for term in CONCERN_TERMS if term in lowered]
    return sum(CONCERN_TERMS[t] for t in hits), hits


_SEVERITY_RANK = {None: 0, "medium": 1, "high": 2}


async def check_and_alert(
    resident_id: str, call_id: str, text: str, running_score: int, alerted_severity: str | None
) -> tuple[int, str | None, dict | None]:
    """Returns (new_running_score, alerted_severity, alert_or_none).

    Alerts at most once per severity level per call: a medium alert is followed
    by a high one only if the score keeps climbing, and never re-fires.
    """
    score, hits = score_utterance(text)
    running_score += score
    if score == 0 or running_score < ALERT_THRESHOLD:
        return running_score, alerted_severity, None

    severity = "high" if running_score >= ALERT_THRESHOLD * 2 else "medium"
    if _SEVERITY_RANK[severity] <= _SEVERITY_RANK[alerted_severity]:
        return running_score, alerted_severity, None

    reason = f"Concern signals in check-in: {', '.join(hits)} (score {running_score})"
    memory.save_alert(resident_id, call_id, reason, severity)
    alert = {"resident_id": resident_id, "call_id": call_id, "reason": reason, "severity": severity}

    if WEBHOOK_URL:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(WEBHOOK_URL, json=alert)
        except httpx.HTTPError:
            pass  # alert is already persisted; webhook delivery is best-effort

    return running_score, severity, alert
