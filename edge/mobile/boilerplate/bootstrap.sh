#!/usr/bin/env bash
# Bootstrap the bonsai_edge toolchain + project skeleton.
#
# Idempotent; each step checks before acting and records what it did.
# Nothing below is considered "done" for documentation purposes until it
# has actually run on a machine — this repo documents evidence, not intent.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$ROOT/boilerplate/bootstrap.log"
say() { echo "[bootstrap] $*" | tee -a "$LOG"; }

# 1. Dart + Flutter (via official channel; brew on macOS)
if ! command -v flutter >/dev/null; then
  say "installing flutter via homebrew cask"
  brew install --cask flutter
else
  say "flutter present: $(flutter --version | head -1)"
fi

# 2. Serverpod CLI
if ! command -v serverpod >/dev/null; then
  say "activating serverpod cli"
  dart pub global activate serverpod_cli
  export PATH="$PATH:$HOME/.pub-cache/bin"
else
  say "serverpod present: $(serverpod version 2>/dev/null || true)"
fi

# 3. Create the pod (SQLite dev profile — no Docker needed for the laptop loop)
if [ ! -d "$ROOT/bonsai_edge_server" ]; then
  say "running serverpod create"
  (cd "$ROOT" && serverpod create bonsai_edge_server)
else
  say "bonsai_edge_server exists — skipping create"
fi

# 4. Flutter shell
if [ ! -d "$ROOT/bonsai_edge_flutter" ]; then
  say "creating flutter shell"
  (cd "$ROOT" && flutter create bonsai_edge_flutter --platforms=android,ios,macos)
else
  say "bonsai_edge_flutter exists — skipping"
fi

say "next: apply core models (see boilerplate/README.md), then 'serverpod generate'"
say "then: ./boilerplate/tmux-dev.sh 01"
