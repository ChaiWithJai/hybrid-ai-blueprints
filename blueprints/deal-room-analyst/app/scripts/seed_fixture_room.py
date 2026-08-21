#!/usr/bin/env python3
"""Bind a catalog fixture room to its own Buzz channel.

A fixture room listed in DEAL_ROOM_CATALOG appears in the room list, but its
workspace is empty until a Buzz channel is bound to it. Until then the browser
sits on "Opening workspace" and /api/workspace returns workspace_not_bound.

Opening a folder in the browser does not fix this: that path registers a room
keyed by the folder's absolute path (local_<sha256[:12]>), which is a different
room id from the fixture's catalog id.

This script calls the same BuzzBridge.ensure_room the application uses, so the
channel is created private, the agent identity is added as a bot member, and the
initial canvas is written and recorded. It is idempotent: a fixture that is
already bound is reported and left alone.

Run from the application directory:

    python3 scripts/seed_fixture_room.py project_titan_lbo
    python3 scripts/seed_fixture_room.py --all

Verify with the workspace API, not with the page. A GET on /rooms/<id> returns
the single-page shell and answers 200 even when nothing is bound:

    curl -s 'http://127.0.0.1:8787/api/workspace?room=project_titan_lbo'
"""

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from core.buzz_bridge import BuzzBridge, BuzzUnavailable  # noqa: E402


def seed(bridge: BuzzBridge, room_id: str) -> int:
    room = server.DEAL_ROOM_CATALOG.get(room_id)
    if room is None:
        known = ", ".join(sorted(server.DEAL_ROOM_CATALOG))
        print(f"unknown fixture room {room_id!r}; known rooms: {known}")
        return 2

    existing = bridge.room(room_id)
    if existing:
        print(f"{room_id}: already bound to channel {existing['channel_id']}")
        return 0

    folder = ROOT / room["path"]
    if not folder.is_dir():
        print(f"{room_id}: fixture folder missing at {room['path']}")
        return 1
    documents = [p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")]

    try:
        record = bridge.ensure_room(room, document_count=len(documents), warnings=0)
    except BuzzUnavailable as error:
        # The registry allows one channel per room. Reusing a channel that
        # already belongs to another room fails here rather than silently
        # producing two rooms that share a conversation.
        print(f"{room_id}: {error}")
        return 1

    print(f"{room_id}: bound to channel {record['channel_id']} with {len(documents)} documents")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("room", nargs="?", help="fixture room id, for example project_titan_lbo")
    parser.add_argument("--all", action="store_true", help="seed every fixture room in the catalog")
    parser.add_argument("--list", action="store_true", help="list fixture rooms and their bindings")
    args = parser.parse_args()

    bridge = BuzzBridge(ROOT)

    if args.list:
        for room_id in sorted(server.DEAL_ROOM_CATALOG):
            bound = bridge.room(room_id)
            state = f"channel {bound['channel_id']}" if bound else "not bound"
            print(f"{room_id}: {state}")
        return 0

    if args.all:
        return max(seed(bridge, room_id) for room_id in sorted(server.DEAL_ROOM_CATALOG))

    if not args.room:
        parser.print_help()
        return 2
    return seed(bridge, args.room)


if __name__ == "__main__":
    sys.exit(main())
