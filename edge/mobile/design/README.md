# The design layer

One design system under every keep-demo app, so the suite reads as one
product family and a new demo inherits the craft for free.

| File | What it is |
| --- | --- |
| [tokens.css](tokens.css) | Color, type, spacing, motion. Warm paper + ink + one marigold accent reserved for the act of speaking. Light + dark. 56px touch floor, 88px for the mic — because the mic *is* the app. |
| [sprites.svg](sprites.svg) | Original characters in the spirit of Pablo Stanley's Open Peeps — thick ink strokes (currentColor, theme-aware), flat fills, warm and human: Amma, the worker, the mother, the kid — plus the eight state icons. |
| [COPY.md](COPY.md) | The UX writing rules. The short version: speak like a neighbor, icon + word for every state, offline is normal not an error, the AI's only mark is "Made on this phone", numbers and names are sacred. |

## The apps

| App | Demo | Port | The critical workflow |
| --- | --- | --- | --- |
| **Awaaz** — family voices, kept close | 01 | 8031 | A voice note arrives → transcript + summary made on the phone → reply by voice, queues offline, sends itself |
| **Dhaaga** — one thread, only your family | 03 | 8033 | Two ends of a family across a border; encrypted envelopes flow as bandwidth allows; "What the relay sees" shows the real ciphertext |
| **Bol** — say it, send it written | 04 | 8034 | Hold to speak → a clean written message → hear it back → send. When unsure, the app asks — it never guesses |

Run any of them: `python3 serve.py` in the demo dir (`fixture` for
deterministic, auto-detects live Bonsai 1.7b otherwise), then open the
printed URL. Everything is stdlib + one HTML file; there is nothing to
install.

## Design principles the tokens encode

1. **Fully offline, structurally.** System font stack, inline sprites, no
   CDN, no external request anywhere. If the page needs the internet, the
   product thesis is already broken.
2. **Low-literacy first.** 18px body floor, one idea per line, every state
   is icon + word, the original voice is always one tap away, and Urdu
   renders RTL in its own script.
3. **The intelligence is furniture, not a character.** No chatbot, no
   avatar for the AI, no "thinking…" theater. Its entire presence is the
   sparkle mark and honest smallness: "Made on this phone", and when
   unsure, "I couldn't catch this — play the voice instead."
4. **Marigold means speak.** The accent appears only on actions that make
   or send voice. Everything else stays paper and ink, so the one thing
   that matters is the one thing in color.

## Extending the suite (the point of all this)

A new app = one namespace bundle + one screen:

1. Copy a keep-demo directory; write your `bundle.json` (fields, client
   actions, sync_mode) — the platform validates it at install.
2. Register your actions in `app.py` against `edgekit.ActionRegistry`;
   every model call goes through the provider seam, so your demo is
   testable with fixtures and honest about live results by construction.
3. Write gates with a negative control that proves your evaluator can
   fail, and run `python3 app.py fixture` until the verdict is keep.
4. Wrap it in `serve.py` (copy Awaaz's — it is 140 lines) and build your
   screen from `tokens.css` + `sprites.svg` + the COPY.md rules.
5. Add nothing to the design system without needing it twice.

The parked demos (`../demos/parked/`) are the counter-examples worth
reading: correct code, killed on live model evidence, waiting on LoRAs —
that is the bar, and the honesty convention, for anything new.
