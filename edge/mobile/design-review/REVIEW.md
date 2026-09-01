# Design review — round 1 findings, fixes, round 2 verification

Method adapted from
[ChaiWithJai/aplus-video tools/design-review](https://github.com/ChaiWithJai/aplus-video/tree/main/tools/design-review):
capture a screenshot atlas of every app state at mobile (430×900) and
desktop (1200×850), annotate defects as rectangles with plain notes,
cluster them by failure mode, fix each cluster at its root, and prove
closure by recapture. `capture.sh` drives every state through the apps'
real APIs, so the atlas shows the actual pipeline output. Raw atlases are
gitignored; [annotations.json](annotations.json) holds the full round-1
record; [proof/](proof/) holds the four round-2 shots that close the
critical findings.

## Round 1 — 13 findings, 7 clusters

| Cluster | Count | Worst | Root cause → fix |
| --- | --- | --- | --- |
| layout-scroll-hijack | 3 | **critical** | `window.scrollTo(0, scrollHeight)` on render threw Dhaaga's header (and its E2EE trust chip) off-screen, blanked the entire desktop first paint, and hid the offline banner + queued bubble — the product thesis invisible in the app built to prove it. → Thread scrolls its own overflow container; sticky header; `thread.scrollTop`, never the window. |
| state-leakage | 2 | high | Author display rules (`.chip`/`.honest { display:flex }`) silently defeat the `hidden` attribute — UA `[hidden]{display:none}` loses to any author `display`. Awaaz showed "Waiting to hear back" on the user's own outgoing card (server state was correct: `needsReply=false`); Bol showed the "I couldn't tidy this" fallback note on successful model cleans. → `[hidden]{display:none !important}` in tokens.css — the bug class is dead platform-wide. |
| dev-chrome-collision | 3 | medium | Each app hand-placed demo controls top-right over product chrome. → One convention: fixed bottom-left (raised above Dhaaga's full-width dock), translucent. |
| robustness | 1 | high | A malformed JSON body crashed the serving thread (empty reply) in all three servers. → try/except → HTTP 400, all three. |
| rig-defect | 1 | medium | bash `"${3:-{}}"` brace-default appended a stray `}` to every explicit JSON body — which is what exposed the robustness bug. → explicit default + `curl -f`. |
| semantic-color-drift | 1 | low | Needs-reply chip wore clay red; COPY.md reserves red for real problems. → wait palette. |
| redundancy | 2 | low | Duration rendered twice per card; "Made on this phone" rendered twice per screen. → one each. |

Also fixed en route: headless capture stalls (Chromium profile-singleton
contention with the running BrowserOS instance → isolated
`--user-data-dir` + 60s hard cap per shot).

## Round 2 — closure

All 14 states recaptured after the fixes. Verified in [proof/](proof/):

- **awaaz-offline-queued-mobile** — phantom chip gone; offline banner,
  pill, and queued state read in one screen; dev controls out of the way.
- **dhaaga-offline-mobile** — the thesis shot: sticky header with the
  lock chip, offline banner, the queued Urdu envelope ("Waiting for
  network — will send by itself"), an Arrived bubble, and the ciphertext
  drawer link, all visible at once. Round 1 showed a blank page here.
- **dhaaga-thread-mobile / -desktop** — header never leaves the screen;
  desktop first paint went from 4.7KB of blank paper to a full thread.
- **bol-clarify-mobile** — the clarify card (highlighted uncertain span,
  "Say that part again", no model call) beside a model-clean card wearing
  only its sparkle mark; the contradiction is gone.

Every fix landed at the root (token layer, scroll ownership, shared
convention) rather than per-symptom, so the clusters cannot silently
reopen one screen at a time.

## Rerun

```bash
./capture.sh              # round N atlas into shots/ (gitignored)
./capture.sh shots-rN     # or a named round
```
