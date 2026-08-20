# Wellness check-in calls

A recurring voice call checks in on a person, remembers what they said in
earlier calls, and escalates decline signals to a human care contact. The
caller talks; the system listens, responds, and decides one thing per call:
escalate or do not escalate.

## Who it serves

The primary user is a care coordinator who cannot call every person every day.
The buyer is a care operations leader at a home health agency, senior living
operator, or recovery program. Verticals with the same call shape:

1. **Elder care** — daily wellness calls, fall and appetite signals.
2. **Substance abuse recovery** — routine contact, relapse-adjacent signals.
3. **Mental health** — continuity of contact between clinical sessions,
   including a consented **self-voice mode** ("call yourself") where the call
   speaks in the member's own cloned voice as a self-compassion ritual.

## Why hybrid

Voice, health signals, and personal memory are the strongest possible case for
edge inference: the audio and the memory never leave the device. The same
blueprint routes to cloud endpoints where an operator prefers managed
infrastructure. Escalation delivery is a webhook either way, so the human
contact is reachable from both routes.

## Boundaries

This use case is wellness check-ins and escalation triage. It is not clinical
monitoring, diagnosis, or treatment, and its blueprints must not claim
otherwise. Any cloned voice other than the user's own requires documented
consent and disclosure to the listener.

Task contracts: [cross-session continuity](tasks/cross-session-continuity.yaml)
and [decline escalation](tasks/decline-escalation.yaml).
Blueprint: [CareLine voice check-in](../../blueprints/careline-voice-checkin/README.md).
