"""Resolve one direct Buzz ACP process to one room, channel, and source folder."""

from __future__ import annotations

import json
import uuid
from pathlib import Path


def resolve_source_scope(root: Path, room_id: str) -> Path:
    room_id = room_id.strip()
    if not room_id:
        raise RuntimeError("Buzz ACP room ID cannot be empty")
    seeded = (root / "deal_rooms" / room_id).resolve()
    if seeded.is_dir():
        return seeded
    registry_path = root / ".runtime" / "deal_rooms" / "registrations.v1.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot resolve ACP source scope for room {room_id}: {exc}") from exc
    matches = [
        item for item in registry.get("rooms", [])
        if isinstance(item, dict) and item.get("id") == room_id
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("path"), str):
        raise RuntimeError(f"room {room_id} has no unique persisted source folder")
    source = Path(matches[0]["path"]).resolve()
    if not source.is_dir():
        raise RuntimeError(f"ACP source folder is unavailable for room {room_id}: {source}")
    return source


def resolve_agent_scope(root: Path, room_id: str) -> tuple[Path, str]:
    """Resolve one room to one source folder and one Buzz channel, or fail closed."""
    source = resolve_source_scope(root, room_id)
    rooms_path = root / ".runtime" / "buzz" / "rooms.json"
    try:
        rooms = json.loads(rooms_path.read_text(encoding="utf-8"))
        binding = rooms[room_id]
        channel = str(uuid.UUID(str(binding["channel_id"])))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"room {room_id} has no valid Buzz channel binding") from exc
    if binding.get("room_id") != room_id or binding.get("channel_id") != channel:
        raise RuntimeError(f"room {room_id} has a mismatched Buzz channel binding")
    return source, channel
