#!/usr/bin/env bash
# Screenshot atlas for the three keep apps — the capture half of the
# design-review method (adapted from ChaiWithJai/aplus-video
# tools/design-review: capture surfaces at two widths, annotate rectangles,
# cluster failure modes, fix, recapture).
#
# States are driven through each app's REAL API before every shot, so the
# atlas shows the pipeline's actual output, not staged HTML.
#
#   ./capture.sh [shots_dir]     # default: ./shots (gitignored)

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEMOS="$HERE/../demos"
SHOTS="${1:-$HERE/shots}"
BROWSER="/Applications/BrowserOS neo.app/Contents/MacOS/BrowserOS neo"
[ -x "$BROWSER" ] || BROWSER="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
mkdir -p "$SHOTS"

PROFILE="$(mktemp -d)"   # isolated profile: never contend with a running
                         # BrowserOS instance's singleton lock

shot() {  # shot <name> <url> — hard 60s cap per viewport so a wedged
          # browser launch can never stall the whole atlas
  for view in mobile:430,900 desktop:1200,850; do
    label="${view%%:*}"; size="${view##*:}"
    "$BROWSER" --headless=new --disable-gpu --hide-scrollbars \
      --user-data-dir="$PROFILE" --no-first-run \
      --virtual-time-budget=5000 --window-size="$size" \
      --screenshot="$SHOTS/$1-$label.png" "$2" >/dev/null 2>&1 &
    BPID=$!
    for _ in $(seq 1 60); do kill -0 $BPID 2>/dev/null || break; sleep 1; done
    kill -9 $BPID 2>/dev/null || true
    wait $BPID 2>/dev/null || true
  done
  echo "shot: $1"
}

api() {  # api <port> <path> [json-body]
  local body="${3:-}"; [ -z "$body" ] && body='{}'
  curl -sf -X POST "http://127.0.0.1:$1$2" -d "$body" >/dev/null
}

PIDS=()
cleanup() { for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT

(cd "$DEMOS/01-voice-note-intelligence" && exec python3 serve.py fixture) & PIDS+=($!)
(cd "$DEMOS/03-family-line"            && exec python3 serve.py fixture) & PIDS+=($!)
(cd "$DEMOS/04-dictation-compose"      && exec python3 serve.py fixture) & PIDS+=($!)
sleep 2

# ---- Awaaz (8031) ----
api 8031 /api/receive; api 8031 /api/receive; api 8031 /api/receive
shot awaaz-inbox        "http://127.0.0.1:8031/"
api 8031 /api/network '{"online": false}'
api 8031 /api/reply
shot awaaz-offline-queued "http://127.0.0.1:8031/"
api 8031 /api/network '{"online": true}'
shot awaaz-delivered    "http://127.0.0.1:8031/"

# ---- Dhaaga (8033) ----
api 8033 /api/send '{"who": "worker"}'
api 8033 /api/send '{"who": "home"}'
api 8033 /api/send '{"who": "worker"}'
shot dhaaga-thread      "http://127.0.0.1:8033/"
api 8033 /api/network '{"online": false}'
api 8033 /api/send '{"who": "home"}'
shot dhaaga-offline     "http://127.0.0.1:8033/"
api 8033 /api/network '{"online": true}'

# ---- Bol (8034) ----
api 8034 /api/dictate
shot bol-draft          "http://127.0.0.1:8034/"
for i in 1 2 3 4 5; do api 8034 /api/dictate; done   # rotation reaches the low-confidence fixture
shot bol-clarify        "http://127.0.0.1:8034/"

echo "atlas in $SHOTS"
