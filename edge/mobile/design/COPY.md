# UX writing rules

The reader may read slowly, read a different script than the sender, or
not read at all. Every word below the app bar earns its place or goes.

## The rules

1. **Speak like a neighbor, not a system.** "Sent. It will arrive when
   Amma's phone wakes up." — never "Message queued for delivery."
2. **One idea per line. Eight words is a long line.**
3. **Never color alone, never icon alone.** Every state = icon + word.
   Queued ✈ "Waiting for network". Delivered ✈✓ "Arrived".
4. **The AI never takes credit and never takes over.** Its one mark is the
   sparkle + "Made on this phone" — a privacy statement, not a brand.
   When it isn't sure, it says so and steps back: "I couldn't catch this
   part. Play the voice instead?" The original voice note is always one
   tap away; the summary is a convenience, never a replacement.
5. **Offline is normal, not an error.** The offline banner is calm, brown,
   and factual: "No internet right now. Everything here still works."
   Red is reserved for real problems the user must act on.
6. **Buttons say what happens.** "Send when connected" — not "OK".
   "Play her voice" — not "Play audio".
7. **Numbers and names are sacred.** Amounts, dates, and names render
   verbatim from source, in the source script, always — the model may
   summarize around them, never restate them.
8. **Every string ships with a `lang` attribute** and renders in its own
   script (Urdu gets `dir="rtl"`). The UI chrome follows the family
   member's language preference, not the sender's.

## Voice of each state

| State | Icon | Copy pattern |
| --- | --- | --- |
| queued | ic-queued | "Waiting for network — will send by itself" |
| delivered | ic-delivered | "Arrived" |
| offline | ic-offline | "No internet right now. Everything here still works." |
| on-device AI | ic-sparkle | "Made on this phone" |
| AI unsure | ic-listen | "I couldn't catch this part. Play the voice instead?" |
| encrypted | ic-lock | "Only your family can read this" |
