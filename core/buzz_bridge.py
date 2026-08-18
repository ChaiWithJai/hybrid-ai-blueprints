"""Thin, fail-closed bridge from the Prism browser surface to Buzz CLI.

Buzz remains the durable event system. This module never mirrors messages into
application memory. If the relay or CLI is unavailable, workspace actions fail
instead of appearing to succeed locally.
"""

from __future__ import annotations

import copy
import fcntl
import json
import os
import re
import subprocess
import tempfile
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from core.nostr_event import nostr_event_errors


_ROOM_REGISTRY_THREAD_LOCK = threading.RLock()


class BuzzUnavailable(RuntimeError):
    """Raised when the real Buzz boundary cannot complete an operation."""


class _InflightVerifiedRead:
    """One exact relay read shared only while it is still in flight."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.result: list[dict[str, Any]] | None = None
        self.error: str | None = None


def initial_room_canvas(room: dict[str, Any], document_count: int, warnings: int) -> str:
    """Build room metadata without receiving or publishing source file content."""
    return (
        f"# {room['name']}\n\n"
        "## Deal brief\n\n"
        f"{room.get('description', 'Private deal room')}\n\n"
        "## Source boundary\n\n"
        f"{document_count} supported files indexed locally; {warnings} parser warnings. "
        "Source files stay in the selected folder. Prism does not publish file bytes "
        "during room setup. Messages, generated briefs, citations, and reviewed canvases "
        "are stored as signed events on this Buzz relay.\n\n"
        "## Open questions\n\n- Add the first human-reviewed question.\n"
    )


class BuzzBridge:
    def __init__(self, project_root: str | Path):
        self.root = Path(project_root).resolve()
        self.runtime = self.root / ".runtime" / "buzz"
        self.binary = self.runtime / "bin" / "buzz"
        self.identities_path = self.runtime / "identities.env"
        self.rooms_path = self.runtime / "rooms.json"
        self.relay_url = os.environ.get("PRISM_BUZZ_RELAY_URL", "ws://127.0.0.1:3030")
        self.relay_http_url = self.relay_url.replace("ws://", "http://", 1).replace(
            "wss://", "https://", 1
        )
        self._registry_lock = _ROOM_REGISTRY_THREAD_LOCK
        self._verified_event_cache: dict[str, dict[str, Any]] = {}
        self._message_read_lock = threading.Lock()
        self._inflight_message_reads: dict[
            tuple[str, int, int | None], _InflightVerifiedRead
        ] = {}
        self._message_read_leaders = 0
        self._message_read_followers = 0
        self._message_read_failures = 0

    @staticmethod
    def _read_env(path: Path) -> dict[str, str]:
        values: dict[str, str] = {}
        if not path.exists():
            return values
        for line in path.read_text().splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
        return values

    @property
    def identities(self) -> dict[str, str]:
        return self._read_env(self.identities_path)

    @property
    def configured(self) -> bool:
        identities = self.identities
        return (
            self.binary.is_file()
            and os.access(self.binary, os.X_OK)
            and len(identities.get("PRISM_BUZZ_OWNER_PRIVATE_KEY", "")) == 64
            and len(identities.get("PRISM_BUZZ_AGENT_PUBLIC_KEY", "")) == 64
        )

    def relay_live(self) -> bool:
        try:
            with urlopen(f"{self.relay_http_url}/_liveness", timeout=1.5) as response:
                return response.status == 200 and response.read(16).strip() == b"ok"
        except OSError:
            return False

    def status(self) -> dict[str, Any]:
        identities = self.identities
        try:
            room_count = len(self._room_map())
            registry_state = "verified"
            registry_error = None
        except BuzzUnavailable as exc:
            room_count = None
            registry_state = "corrupt"
            registry_error = str(exc)
        relay_live = self.relay_live() if self.configured else False
        with self._message_read_lock:
            message_reads = {
                "policy": "coalesce_exact_inflight_no_stale_message_cache",
                "active": len(self._inflight_message_reads),
                "leader_reads": self._message_read_leaders,
                "joined_followers": self._message_read_followers,
                "failed_reads": self._message_read_failures,
            }
        return {
            "configured": self.configured,
            "relay_live": relay_live,
            "relay_url": self.relay_url,
            "agent_pubkey": identities.get("PRISM_BUZZ_AGENT_PUBLIC_KEY"),
            "operator_pubkey": identities.get("PRISM_BUZZ_OWNER_PUBLIC_KEY"),
            "persistence": "buzz_signed_event_log" if self.configured else "unavailable",
            "browser_signing": "local_operator_bridge",
            "room_registry_state": registry_state,
            "room_registry_error": registry_error,
            "room_count": room_count,
            "room_registry_commit": "advisory_file_lock_atomic_replace_and_fsync",
            "workspace_ready": bool(self.configured and relay_live and registry_state == "verified"),
            "message_reads": message_reads,
        }

    def _env(self, actor: str = "owner") -> dict[str, str]:
        if not self.configured:
            raise BuzzUnavailable("Buzz CLI or local identities are not configured")
        identities = self.identities
        key_name = (
            "PRISM_BUZZ_AGENT_PRIVATE_KEY" if actor == "agent"
            else "PRISM_BUZZ_OWNER_PRIVATE_KEY"
        )
        env = os.environ.copy()
        env["BUZZ_PRIVATE_KEY"] = identities[key_name]
        env["BUZZ_RELAY_URL"] = self.relay_url
        return env

    def _run(self, *args: str, actor: str = "owner", stdin: str | None = None) -> str:
        if not self.relay_live():
            raise BuzzUnavailable(f"Buzz relay is unavailable at {self.relay_url}")
        try:
            completed = subprocess.run(
                [str(self.binary), *args],
                cwd=self.root,
                env=self._env(actor),
                input=stdin,
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BuzzUnavailable(f"Buzz command failed: {exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "unknown Buzz error"
            raise BuzzUnavailable(detail)
        return completed.stdout.strip()

    @staticmethod
    def _validated_room_map(value: Any) -> dict[str, dict[str, str]]:
        if not isinstance(value, dict):
            raise BuzzUnavailable("Buzz room registry must be a JSON object")
        validated: dict[str, dict[str, str]] = {}
        channel_ids: set[str] = set()
        for room_id, item in value.items():
            if not isinstance(room_id, str) or not re.fullmatch(
                r"[A-Za-z0-9_.-]{1,128}", room_id
            ):
                raise BuzzUnavailable("Buzz room registry contains an invalid room ID")
            if not isinstance(item, dict):
                raise BuzzUnavailable(f"Buzz room registry entry {room_id} is not an object")
            if set(item) - {"room_id", "channel_id", "canvas_event_id"}:
                raise BuzzUnavailable(f"Buzz room registry entry {room_id} has unknown fields")
            if item.get("room_id") != room_id:
                raise BuzzUnavailable(f"Buzz room registry identity differs for {room_id}")
            channel_id = item.get("channel_id")
            try:
                canonical_channel = str(uuid.UUID(str(channel_id)))
            except (ValueError, AttributeError, TypeError) as exc:
                raise BuzzUnavailable(
                    f"Buzz room registry entry {room_id} has an invalid channel ID"
                ) from exc
            if str(channel_id) != canonical_channel:
                raise BuzzUnavailable(
                    f"Buzz room registry entry {room_id} has a noncanonical channel ID"
                )
            if canonical_channel in channel_ids:
                raise BuzzUnavailable("Buzz room registry assigns one channel to multiple rooms")
            channel_ids.add(canonical_channel)
            record = {"room_id": room_id, "channel_id": canonical_channel}
            canvas_event_id = item.get("canvas_event_id")
            if canvas_event_id is not None:
                if not isinstance(canvas_event_id, str) or not re.fullmatch(
                    r"[0-9a-f]{64}", canvas_event_id
                ):
                    raise BuzzUnavailable(
                        f"Buzz room registry entry {room_id} has an invalid canvas event ID"
                    )
                record["canvas_event_id"] = canvas_event_id
            validated[room_id] = record
        return validated

    def _room_map(self) -> dict[str, dict[str, str]]:
        with self._registry_lock:
            if not self.rooms_path.exists():
                return {}
            try:
                value = json.loads(self.rooms_path.read_text())
            except OSError as exc:
                raise BuzzUnavailable(f"Buzz room registry is unreadable: {exc}") from exc
            except json.JSONDecodeError as exc:
                raise BuzzUnavailable("Buzz room registry contains invalid JSON") from exc
            return self._validated_room_map(value)

    @contextmanager
    def _room_registry_transaction(self):
        """Serialize a registry reread and commit across local processes."""
        self.rooms_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.rooms_path.with_name(f".{self.rooms_path.name}.lock")
        with self._registry_lock:
            descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            with os.fdopen(descriptor, "a+b") as handle:
                os.chmod(lock_path, 0o600)
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _save_room_map(self, rooms: dict[str, dict[str, str]]) -> None:
        with self._registry_lock:
            validated = self._validated_room_map(rooms)
            self.rooms_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix="rooms.", suffix=".tmp", dir=self.rooms_path.parent
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(validated, handle, indent=2, sort_keys=True)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, self.rooms_path)
                directory_fd = os.open(self.rooms_path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                if temporary.exists():
                    temporary.unlink()

    def ensure_room(self, room: dict[str, Any], document_count: int, warnings: int) -> dict[str, str]:
        with self._room_registry_transaction():
            rooms = self._room_map()
            existing = rooms.get(room["id"])
            if existing:
                return existing

            created = json.loads(
                self._run(
                    "channels", "create",
                    "--name", str(room["name"])[:80],
                    "--type", "stream",
                    "--visibility", "private",
                    "--description", str(room.get("description", "Private deal room"))[:240],
                )
            )
            channel_id = created["channel_id"]
            agent_pubkey = self.identities["PRISM_BUZZ_AGENT_PUBLIC_KEY"]
            self._run(
                "channels", "add-member", "--channel", channel_id,
                "--pubkey", agent_pubkey, "--role", "bot",
            )
            canvas = initial_room_canvas(room, document_count, warnings)
            canvas_event = self.set_canvas(channel_id, canvas, persist_binding=False)
            record = {
                "channel_id": channel_id,
                "room_id": room["id"],
                "canvas_event_id": canvas_event["event_id"],
            }
            rooms[room["id"]] = record
            self._save_room_map(rooms)
            return record

    def bind_existing_room(self, room_id: str, channel_id: str) -> None:
        with self._room_registry_transaction():
            rooms = self._room_map()
            existing = rooms.get(room_id)
            if existing and existing.get("channel_id") != channel_id:
                raise BuzzUnavailable(
                    f"Buzz room {room_id} is already bound to a different channel"
                )
            if existing:
                return
            rooms[room_id] = {
                "room_id": room_id,
                "channel_id": channel_id,
            }
            self._save_room_map(rooms)

    def room(self, room_id: str) -> dict[str, str] | None:
        return self._room_map().get(room_id)

    def messages(
        self,
        channel_id: str,
        limit: int = 100,
        *,
        before: int | None = None,
    ) -> list[dict[str, Any]]:
        args = [
            "messages", "get", "--channel", channel_id,
            "--limit", str(min(limit, 200)),
        ]
        if before is not None:
            args.extend(["--before", str(before)])
        output = self._run(*args)
        value = json.loads(output or "[]")
        if not isinstance(value, list):
            raise BuzzUnavailable("Buzz messages response was not an array")
        return value

    def verified_messages(
        self,
        channel_id: str,
        limit: int = 100,
        *,
        before: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return verified relay messages, coalescing only identical in-flight reads.

        Completed message lists are not cached. Every later request returns to
        Buzz, while concurrent browser polls for the same page share one relay
        read and one signature-verification pass.
        """
        normalized_limit = min(limit, 200)
        key = (channel_id, normalized_limit, before)
        with self._message_read_lock:
            inflight = self._inflight_message_reads.get(key)
            leader = inflight is None
            if leader:
                inflight = _InflightVerifiedRead()
                self._inflight_message_reads[key] = inflight
                self._message_read_leaders += 1
            else:
                self._message_read_followers += 1

        assert inflight is not None
        if not leader:
            if not inflight.done.wait(timeout=25):
                raise BuzzUnavailable(
                    "Timed out waiting for the active verified Buzz message read"
                )
            if inflight.error is not None:
                raise BuzzUnavailable(inflight.error)
            return copy.deepcopy(inflight.result or [])

        try:
            result = self._verified_messages_from_relay(
                channel_id, limit=normalized_limit, before=before
            )
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            with self._message_read_lock:
                self._message_read_failures += 1
                inflight.error = message
                inflight.done.set()
                self._inflight_message_reads.pop(key, None)
            if isinstance(exc, BuzzUnavailable):
                raise
            raise BuzzUnavailable(f"Buzz verified message read failed: {message}") from exc
        else:
            with self._message_read_lock:
                inflight.result = copy.deepcopy(result)
                inflight.done.set()
                self._inflight_message_reads.pop(key, None)
            return result

    def _verified_messages_from_relay(
        self,
        channel_id: str,
        limit: int = 100,
        *,
        before: int | None = None,
    ) -> list[dict[str, Any]]:
        """Perform one relay read and its complete raw-event verification."""
        messages = self.messages(channel_id, limit=limit, before=before)
        event_ids = [str(message.get("id", "")) for message in messages]
        if len(event_ids) != len(set(event_ids)):
            raise BuzzUnavailable("Buzz messages response contains a duplicate event ID")
        if any(len(event_id) != 64 for event_id in event_ids):
            raise BuzzUnavailable("Buzz messages response contains an invalid event ID")
        raw_events = self.events_by_ids(set(event_ids), channel_id=channel_id)
        if set(raw_events) != set(event_ids):
            raise BuzzUnavailable("Buzz raw event verification did not restore every message")

        verified: list[dict[str, Any]] = []
        compared_fields = ("id", "pubkey", "created_at", "kind", "content", "tags")
        for message in messages:
            raw = raw_events[str(message["id"])]
            if any(message.get(field) != raw.get(field) for field in compared_fields):
                raise BuzzUnavailable(
                    f"Buzz message {message['id']} differs from its verified raw event"
                )
            verified.append({
                **message,
                "signature_verified": True,
                "signature_scheme": "nip01_event_id_plus_bip340",
            })
        return verified

    def messages_by_ids(
        self,
        channel_id: str,
        event_ids: set[str],
        *,
        page_size: int = 200,
        max_pages: int = 1_000,
    ) -> dict[str, dict[str, Any]]:
        """Restore named events while paging backward through a Buzz channel."""
        remaining = {str(item) for item in event_ids if item}
        found: dict[str, dict[str, Any]] = {}
        before: int | None = None
        for _ in range(max_pages):
            if not remaining:
                break
            page = self.messages(channel_id, limit=page_size, before=before)
            if not page:
                break
            for event in page:
                event_id = str(event.get("id", ""))
                if event_id in remaining:
                    found[event_id] = event
                    remaining.remove(event_id)
            if len(page) < page_size:
                break
            timestamps = [
                item.get("created_at") for item in page
                if isinstance(item.get("created_at"), int)
            ]
            if len(timestamps) != len(page):
                raise BuzzUnavailable("Buzz pagination needs an integer created_at on every event")
            # Buzz treats --before as inclusive. Step behind the oldest second
            # or the boundary event is returned again and pagination stalls.
            next_before = min(timestamps) - 1
            if before is not None and next_before >= before:
                raise BuzzUnavailable("Buzz pagination did not move to an older event page")
            before = next_before
        if remaining and max_pages <= 0:
            raise BuzzUnavailable("Buzz review-event pagination is disabled")
        return found

    def events_by_ids(
        self,
        event_ids: set[str],
        *,
        channel_id: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Restore exact raw events and independently verify hash and signature."""
        found: dict[str, dict[str, Any]] = {}
        for expected_id in sorted({str(item) for item in event_ids if item}):
            cached = self._verified_event_cache.get(expected_id)
            if cached is not None:
                if channel_id is not None and ["h", channel_id] not in cached.get("tags", []):
                    raise BuzzUnavailable(f"Buzz raw event {expected_id} is not in channel {channel_id}")
                found[expected_id] = cached
                continue
            output = self._run("social", "event", "--event", expected_id)
            values = json.loads(output or "[]")
            if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
                raise BuzzUnavailable(f"Buzz did not return exactly one raw event for {expected_id}")
            event = values[0]
            if event.get("id") != expected_id:
                raise BuzzUnavailable(f"Buzz returned the wrong raw event for {expected_id}")
            errors = nostr_event_errors(event)
            if errors:
                raise BuzzUnavailable(f"Buzz raw event {expected_id} failed verification: {'; '.join(errors)}")
            if channel_id is not None and ["h", channel_id] not in event.get("tags", []):
                raise BuzzUnavailable(f"Buzz raw event {expected_id} is not in channel {channel_id}")
            self._verified_event_cache[expected_id] = event
            found[expected_id] = event
        return found

    def canvas(self, channel_id: str) -> str:
        return self._run("canvas", "get", "--channel", channel_id)

    def verified_canvas(self, channel_id: str) -> dict[str, Any]:
        """Return the canvas only when it matches its verified raw event."""
        room_records = [
            record for record in self._room_map().values()
            if record.get("channel_id") == channel_id
        ]
        event_ids = {
            str(record.get("canvas_event_id"))
            for record in room_records if record.get("canvas_event_id")
        }
        if len(event_ids) != 1:
            raise BuzzUnavailable(
                "Buzz canvas has no single verified event binding; save the canvas again"
            )
        event_id = next(iter(event_ids))
        content = self.canvas(channel_id)
        event = self.events_by_ids({event_id}, channel_id=channel_id)[event_id]
        self._validate_canvas_event(
            event,
            content=content,
            expected_pubkey=self.identities["PRISM_BUZZ_OWNER_PUBLIC_KEY"],
        )
        return {
            "markdown": content,
            "event_id": event_id,
            "signature_verification": {
                "state": "verified",
                "scheme": "nip01_event_id_plus_bip340",
                "event_id": event_id,
                "author_pubkey": event["pubkey"],
            },
        }

    def send(self, channel_id: str, content: str, ask_bonsai: bool = False) -> dict[str, Any]:
        args = ["messages", "send", "--channel", channel_id, "--content", content]
        if ask_bonsai:
            args.extend(["--mention", self.identities["PRISM_BUZZ_AGENT_PUBLIC_KEY"]])
        result = json.loads(self._run(*args))
        self._verify_published_message(
            result,
            channel_id=channel_id,
            content=content,
            expected_pubkey=self.identities["PRISM_BUZZ_OWNER_PUBLIC_KEY"],
        )
        return result

    def send_as_agent(self, channel_id: str, content: str) -> dict[str, Any]:
        """Publish a model answer with the configured Buzz agent identity."""
        result = json.loads(self._run(
            "messages", "send", "--channel", channel_id, "--content", content,
            actor="agent",
        ))
        self._verify_published_message(
            result,
            channel_id=channel_id,
            content=content,
            expected_pubkey=self.identities["PRISM_BUZZ_AGENT_PUBLIC_KEY"],
        )
        return result

    def _verify_published_message(
        self,
        result: dict[str, Any],
        *,
        channel_id: str,
        content: str,
        expected_pubkey: str,
    ) -> None:
        event_id = str(result.get("event_id", ""))
        if len(event_id) != 64:
            raise BuzzUnavailable("Buzz send did not return a valid event ID")
        event = self.events_by_ids({event_id}, channel_id=channel_id).get(event_id)
        if event is None:
            raise BuzzUnavailable("Buzz send event could not be restored")
        if event.get("content") != content:
            raise BuzzUnavailable("Buzz send event content differs from the submitted message")
        if event.get("pubkey") != expected_pubkey:
            raise BuzzUnavailable("Buzz send event was signed by an unexpected identity")

    def set_canvas(
        self,
        channel_id: str,
        content: str,
        *,
        persist_binding: bool = True,
    ) -> dict[str, Any]:
        result = json.loads(
            self._run("canvas", "set", "--channel", channel_id, "--content", "-", stdin=content)
        )
        event_id = str(result.get("event_id", ""))
        if len(event_id) != 64:
            raise BuzzUnavailable("Buzz canvas write did not return a valid event ID")
        event = self.events_by_ids({event_id}, channel_id=channel_id)[event_id]
        self._validate_canvas_event(
            event,
            content=content,
            expected_pubkey=self.identities["PRISM_BUZZ_OWNER_PUBLIC_KEY"],
        )
        if persist_binding:
            with self._room_registry_transaction():
                rooms = self._room_map()
                changed = False
                for room in rooms.values():
                    if room.get("channel_id") == channel_id:
                        room["canvas_event_id"] = event_id
                        changed = True
                if changed:
                    self._save_room_map(rooms)
        result["signature_verified"] = True
        result["signature_scheme"] = "nip01_event_id_plus_bip340"
        return result

    @staticmethod
    def _validate_canvas_event(
        event: dict[str, Any],
        *,
        content: str,
        expected_pubkey: str,
    ) -> None:
        if event.get("kind") != 40100:
            raise BuzzUnavailable("Buzz canvas event has an unexpected kind")
        if event.get("content") != content:
            raise BuzzUnavailable("Buzz canvas content differs from its verified raw event")
        if event.get("pubkey") != expected_pubkey:
            raise BuzzUnavailable("Buzz canvas event was signed by an unexpected identity")
