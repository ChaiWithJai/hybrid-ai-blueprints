"""Conversation core: prompt assembly, turn handling, end-of-call fact extraction."""

import uuid
from datetime import datetime, timezone

from . import escalation, llm, memory

SYSTEM_TEMPLATE = """You are CareLine, a warm, unhurried wellness check-in companion calling {name} on behalf of their care team. Today is {today}.

Guidelines:
- Speak in short, natural sentences — this is a phone call, not an essay. One or two sentences per turn.
- Be genuinely curious about their day: meals, sleep, mood, plans, family.
- You are NOT a clinician. Never diagnose, never give medical advice. If something sounds concerning, gently acknowledge it and say you'll make sure their care team knows.
- Use what you remember from earlier calls to show continuity — ask follow-ups about things they mentioned before, naming when they said it.
- NEVER invent memories. Only reference things that appear in the earlier-call facts listed below. If no facts are listed, you know nothing about them yet.

{memory_block}"""

SELF_TEMPLATE = """You are {name}'s own voice — literally: this call speaks in their cloned voice, and they know it. This is a "call yourself" self-compassion check-in they chose to receive. Today is {today}.

Guidelines:
- Speak as a kind, steady version of themselves: "we" and "you" language, never clinical, never saccharine. One or two short sentences per turn.
- Ask about the real day: what got done, what got dropped, what they're avoiding, what felt good.
- Practice honest self-compassion: acknowledge hard things plainly, then point at evidence of effort. No toxic positivity.
- You are NOT a therapist and never claim to be. If they mention self-harm, crisis, or relapse, respond with warmth, name it seriously, tell them their support contact will be notified, and mention they can reach a crisis line right now.
- Use what you remember from earlier calls for continuity — naming when they said it.
- NEVER invent memories. Only reference the earlier-call facts listed below. If none are listed, this is the first call — open by saying why this ritual exists: taking a minute to talk to yourself kindly.

{memory_block}"""


def _memory_block(resident_id: str) -> str:
    facts = memory.recall(resident_id)
    if not facts:
        return (
            "This is your FIRST ever call with them. You have never spoken before — "
            "do not claim to remember anything or refer to a previous conversation. "
            "Introduce yourself briefly and explain their care team asked you to check in."
        )
    lines = []
    for f in facts:
        day = f["created_at"][:10]
        lines.append(f"- ({day}) {f['fact']}")
    return "Things they told you on earlier calls:\n" + "\n".join(lines)


class CallSession:
    def __init__(self, resident_id: str, name: str, mode: str = "care"):
        self.id = uuid.uuid4().hex[:12]
        self.resident_id = resident_id
        self.name = name
        self.mode = mode
        self.concern_score = 0
        self.alerted_severity: str | None = None
        today = datetime.now(timezone.utc).strftime("%A, %B %d")
        self.is_first_call = not memory.recall(resident_id, limit=1)
        template = SELF_TEMPLATE if mode == "self" else SYSTEM_TEMPLATE
        self.messages: list[dict] = [
            {
                "role": "system",
                "content": template.format(
                    name=name, today=today, memory_block=_memory_block(resident_id)
                ),
            }
        ]
        memory.start_call(self.id, resident_id)

    async def open_call(self) -> str:
        if self.is_first_call:
            cue = (
                "(The call connects. You have NEVER spoken with this person before — this is the "
                "very first call. Do not mention any last call, previous chat, or shared history. "
                "Introduce yourself as a new check-in service from their care team.)"
            )
        else:
            cue = "(The call connects. Greet them and open the check-in.)"
        self.messages.append({"role": "user", "content": cue})
        reply = await llm.chat(self.messages)
        self.messages.append({"role": "assistant", "content": reply})
        return reply

    async def turn(self, user_text: str) -> tuple[str, dict | None]:
        self.messages.append({"role": "user", "content": user_text})
        self.concern_score, self.alerted_severity, alert = await escalation.check_and_alert(
            self.resident_id, self.id, user_text, self.concern_score, self.alerted_severity
        )
        # by-stakes switch: once concern registers, the strong model leans in
        reply = await llm.chat(self.messages, strong=self.concern_score > 0)
        self.messages.append({"role": "assistant", "content": reply})
        return reply, alert

    async def end(self) -> dict:
        transcript = "\n".join(
            f"{m['role']}: {m['content']}" for m in self.messages if m["role"] != "system"
        )
        extraction = await llm.chat_json(
            strong=True,  # extraction reliability > latency; latency is hidden post-hangup
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract durable personal facts from this eldercare check-in transcript — "
                        "things worth remembering for the NEXT call (events, people, plans, health "
                        "mentions, mood). Also write a one-sentence call summary for the care team. "
                        'Reply ONLY with JSON: {"facts": ["..."], "summary": "..."}'
                    ),
                },
                {"role": "user", "content": transcript},
            ]
        )
        facts = extraction.get("facts", []) if isinstance(extraction, dict) else []
        summary = extraction.get("summary", "") if isinstance(extraction, dict) else ""
        if facts:
            memory.save_facts(self.resident_id, self.id, facts)
        memory.end_call(self.id, summary, self.concern_score)
        return {"facts": facts, "summary": summary, "concern_score": self.concern_score}
