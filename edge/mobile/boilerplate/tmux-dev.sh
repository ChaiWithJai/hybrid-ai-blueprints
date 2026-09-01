#!/usr/bin/env bash
# tmux dev cockpit for bonsai_edge demos.
#
# One session, one window per concern, panes arranged for a laptop screen.
# Usage:
#   ./tmux-dev.sh [demo]        # demo = 01|02|03|04|05|06 (default: 01)
#   tmux attach -t bonsai-edge  # reattach
#
# Panes assume: LM Studio CLI (`lms`) on PATH, serverpod project created by
# bootstrap.sh at ../bonsai_edge_server, Flutter shell at
# ../bonsai_edge_flutter. Each pane fails loudly if its tool is missing —
# nothing here fakes a running system.

set -euo pipefail

SESSION="bonsai-edge"
DEMO="${1:-01}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVER_DIR="$ROOT/bonsai_edge_server/bonsai_edge_server"
FLUTTER_DIR="$ROOT/bonsai_edge_flutter"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "session '$SESSION' exists — attaching"; exec tmux attach -t "$SESSION"
fi

# Window 1: models — the intelligence layer
tmux new-session -d -s "$SESSION" -n models -x 220 -y 50
tmux send-keys -t "$SESSION:models" \
  "lms server start --port 1234 --bind 127.0.0.1 && lms load 1.7b --context-length 4096 --identifier 1.7b --yes || echo 'lms missing: install LM Studio CLI'" C-m
tmux split-window -t "$SESSION:models" -h
tmux send-keys -t "$SESSION:models.1" \
  "echo 'whisper.cpp + kokoro pane — run demo ASR/TTS harness here'" C-m

# Window 2: pod — two server processes + redis, the multi-process reality
tmux new-window -t "$SESSION" -n pod
tmux send-keys -t "$SESSION:pod" \
  "cd '$SERVER_DIR' 2>/dev/null && dart bin/main.dart --port 8080 || echo 'run bootstrap.sh first'" C-m
tmux split-window -t "$SESSION:pod" -h
tmux send-keys -t "$SESSION:pod.1" \
  "cd '$SERVER_DIR' 2>/dev/null && dart bin/main.dart --port 8081 || echo 'second pod process (message-central via redis)'" C-m
tmux split-window -t "$SESSION:pod.1" -v
tmux send-keys -t "$SESSION:pod.2" \
  "redis-server --port 6379 2>/dev/null || echo 'redis optional in dev; required for 2-process fan-out test'" C-m

# Window 3: app — the Flutter shell running the selected demo
tmux new-window -t "$SESSION" -n app
tmux send-keys -t "$SESSION:app" \
  "cd '$FLUTTER_DIR' 2>/dev/null && flutter run --dart-define=DEMO=$DEMO || echo 'flutter missing or shell not created'" C-m
tmux split-window -t "$SESSION:app" -h -p 35
tmux send-keys -t "$SESSION:app.1" \
  "echo 'chaos pane: toggle network to prove offline-first'; echo 'macOS: networksetup -setairportpower en0 off|on'" C-m

# Window 4: watch — codegen drift + evals
tmux new-window -t "$SESSION" -n watch
tmux send-keys -t "$SESSION:watch" \
  "cd '$SERVER_DIR' 2>/dev/null && serverpod generate --watch || echo 'serverpod cli missing'" C-m
tmux split-window -t "$SESSION:watch" -h
tmux send-keys -t "$SESSION:watch.1" \
  "cd '$ROOT/demos/$DEMO'* 2>/dev/null && echo 'eval harness pane for demo $DEMO — see DESIGN.md eval gates' || true" C-m

tmux select-window -t "$SESSION:app"
exec tmux attach -t "$SESSION"
