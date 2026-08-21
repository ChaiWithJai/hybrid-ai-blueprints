import copy
import json
import multiprocessing
import os
import tempfile
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from core.buzz_bridge import BuzzBridge, BuzzUnavailable, initial_room_canvas
from tests.nostr_signing import sign_event
from tests.test_nostr_event import EVENT


CANVAS_CHANNEL = "canvas-channel"
CANVAS_CONTENT = "# Deal brief\n\nVerified canvas content."
CANVAS_EVENT = sign_event({
    "created_at": 1786788000,
    "kind": 40100,
    "tags": [["h", CANVAS_CHANNEL]],
    "content": CANVAS_CONTENT,
}, "1" * 64)


class PagingBuzz(BuzzBridge):
    def __init__(self, pages):
        super().__init__(Path.cwd())
        self.pages = pages
        self.calls = []

    def messages(self, channel_id, limit=100, *, before=None):
        self.calls.append((channel_id, limit, before))
        return self.pages.get(before, [])


class RawBuzz(BuzzBridge):
    def __init__(self, event):
        super().__init__(Path.cwd())
        self.event = event
        self.run_count = 0

    def _run(self, *args, actor="owner", stdin=None):
        self.run_count += 1
        return json.dumps([self.event])


class VerifiedMessageBuzz(RawBuzz):
    def __init__(self, raw_event, displayed_event=None):
        super().__init__(raw_event)
        self.displayed_event = displayed_event or {
            key: raw_event[key]
            for key in ("id", "pubkey", "created_at", "kind", "content", "tags")
        }

    def messages(self, channel_id, limit=100, *, before=None):
        return [self.displayed_event]


class CanvasBuzz(BuzzBridge):
    def __init__(self, content=CANVAS_CONTENT, bound=True):
        super().__init__(Path.cwd())
        self.content = content
        self.rooms = {
            "room": {
                "room_id": "room",
                "channel_id": CANVAS_CHANNEL,
                **({"canvas_event_id": CANVAS_EVENT["id"]} if bound else {}),
            }
        }

    @property
    def identities(self):
        return {"PRISM_BUZZ_OWNER_PUBLIC_KEY": CANVAS_EVENT["pubkey"]}

    def _room_map(self):
        return self.rooms

    def _save_room_map(self, rooms):
        self.rooms = copy.deepcopy(rooms)

    def canvas(self, channel_id):
        return self.content

    def _run(self, *args, actor="owner", stdin=None):
        if args[:2] == ("canvas", "set"):
            return json.dumps({"accepted": True, "event_id": CANVAS_EVENT["id"]})
        return json.dumps([CANVAS_EVENT])


class ProcessSetupBuzz(BuzzBridge):
    """Filesystem-observable Buzz substitute for the process collision test."""

    @property
    def identities(self):
        return {"PRISM_BUZZ_AGENT_PUBLIC_KEY": "a" * 64}

    def _run(self, *args, actor="owner", stdin=None):
        if args[:2] == ("channels", "create"):
            descriptor = os.open(
                self.root / "channel-creates.log",
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o600,
            )
            with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
                handle.write(f"{os.getpid()}\n")
                handle.flush()
                os.fsync(handle.fileno())
            time.sleep(0.05)
            return json.dumps({"channel_id": str(uuid.UUID(int=991))})
        return json.dumps({})

    def set_canvas(self, channel_id, content, *, persist_binding=True):
        return {"event_id": "c" * 64}


def _ensure_room_process(root, start, results):
    start.wait(timeout=5)
    try:
        record = ProcessSetupBuzz(root).ensure_room(
            {"id": "shared-room", "name": "Shared", "description": "Private"},
            1,
            0,
        )
        results.put({"ok": True, "record": record})
    except Exception as exc:  # pragma: no cover - returned to parent for assertion
        results.put({"ok": False, "error": repr(exc)})


class BuzzBridgeTests(unittest.TestCase):
    def test_competing_processes_create_one_canonical_buzz_room(self):
        context = multiprocessing.get_context("fork")
        with tempfile.TemporaryDirectory() as folder:
            start = context.Event()
            results = context.Queue()
            processes = [
                context.Process(target=_ensure_room_process, args=(folder, start, results))
                for _ in range(12)
            ]
            for process in processes:
                process.start()
            start.set()
            for process in processes:
                process.join(timeout=10)
                self.assertEqual(process.exitcode, 0)
            observed = [results.get(timeout=2) for _ in processes]

            self.assertTrue(all(item["ok"] for item in observed), observed)
            self.assertEqual(
                len({json.dumps(item["record"], sort_keys=True) for item in observed}),
                1,
            )
            creates = (Path(folder) / "channel-creates.log").read_text().splitlines()
            self.assertEqual(len(creates), 1)
            bridge = BuzzBridge(folder)
            self.assertEqual(set(bridge._room_map()), {"shared-room"})
            lock_path = bridge.rooms_path.with_name(f".{bridge.rooms_path.name}.lock")
            self.assertEqual(lock_path.stat().st_mode & 0o777, 0o600)

    def test_room_binding_drift_and_failed_replace_preserve_canonical_registry(self):
        first_channel = str(uuid.UUID(int=21))
        second_channel = str(uuid.UUID(int=22))
        with tempfile.TemporaryDirectory() as folder:
            bridge = BuzzBridge(folder)
            bridge.bind_existing_room("room", first_channel)
            before = bridge.rooms_path.read_bytes()
            with self.assertRaisesRegex(BuzzUnavailable, "different channel"):
                bridge.bind_existing_room("room", second_channel)
            self.assertEqual(bridge.rooms_path.read_bytes(), before)

            with mock.patch("core.buzz_bridge.os.replace", side_effect=OSError("commit failed")):
                with self.assertRaisesRegex(OSError, "commit failed"):
                    bridge.bind_existing_room("other", second_channel)
            self.assertEqual(bridge.rooms_path.read_bytes(), before)
            self.assertEqual(bridge._room_map()["room"]["channel_id"], first_channel)

    def test_identical_concurrent_message_reads_share_one_verified_relay_read(self):
        class CoalescingBuzz(BuzzBridge):
            def __init__(self):
                super().__init__(Path.cwd())
                self.entered = threading.Event()
                self.release = threading.Event()
                self.message_calls = 0

            def messages(self, channel_id, limit=100, *, before=None):
                self.message_calls += 1
                self.entered.set()
                self.release.wait(timeout=2)
                return [{
                    key: EVENT[key]
                    for key in ("id", "pubkey", "created_at", "kind", "content", "tags")
                }]

            def events_by_ids(self, event_ids, *, channel_id=None):
                return {EVENT["id"]: copy.deepcopy(EVENT)}

        bridge = CoalescingBuzz()
        channel = EVENT["tags"][0][1]
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = [pool.submit(bridge.verified_messages, channel) for _ in range(12)]
            self.assertTrue(bridge.entered.wait(timeout=1))
            time.sleep(0.05)
            bridge.release.set()
            results = [future.result(timeout=2) for future in futures]

        self.assertEqual(bridge.message_calls, 1)
        self.assertEqual(bridge._message_read_leaders, 1)
        self.assertEqual(bridge._message_read_followers, 11)
        self.assertTrue(all(result[0]["signature_verified"] for result in results))
        results[0][0]["content"] = "caller-local mutation"
        self.assertEqual(results[1][0]["content"], EVENT["content"])
        self.assertEqual(bridge._inflight_message_reads, {})

        # Completed lists are deliberately not cached; the next poll returns
        # to the relay and can observe a newly published event.
        bridge.verified_messages(channel)
        self.assertEqual(bridge.message_calls, 2)

    def test_coalesced_message_failure_reaches_waiters_and_next_poll_retries(self):
        class FailOnceBuzz(BuzzBridge):
            def __init__(self):
                super().__init__(Path.cwd())
                self.entered = threading.Event()
                self.release = threading.Event()
                self.message_calls = 0

            def messages(self, channel_id, limit=100, *, before=None):
                self.message_calls += 1
                if self.message_calls == 1:
                    self.entered.set()
                    self.release.wait(timeout=2)
                    raise BuzzUnavailable("relay read failed deliberately")
                return []

            def events_by_ids(self, event_ids, *, channel_id=None):
                return {}

        bridge = FailOnceBuzz()
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(bridge.verified_messages, "channel") for _ in range(8)]
            self.assertTrue(bridge.entered.wait(timeout=1))
            time.sleep(0.05)
            bridge.release.set()
            for future in futures:
                with self.assertRaisesRegex(BuzzUnavailable, "failed deliberately"):
                    future.result(timeout=2)

        self.assertEqual(bridge.message_calls, 1)
        self.assertEqual(bridge._message_read_failures, 1)
        self.assertEqual(bridge._inflight_message_reads, {})
        self.assertEqual(bridge.verified_messages("channel"), [])
        self.assertEqual(bridge.message_calls, 2)

    def test_concurrent_room_bindings_persist_without_loss(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge = BuzzBridge(folder)
            expected = {
                f"room_{index}": str(uuid.UUID(int=index + 1))
                for index in range(32)
            }
            with ThreadPoolExecutor(max_workers=12) as pool:
                list(pool.map(lambda item: bridge.bind_existing_room(*item), expected.items()))

            restored = bridge._room_map()
            self.assertEqual(set(restored), set(expected))
            self.assertEqual(
                {room_id: item["channel_id"] for room_id, item in restored.items()},
                expected,
            )
            self.assertEqual(os.stat(bridge.rooms_path).st_mode & 0o777, 0o600)

    def test_concurrent_ensure_room_creates_one_buzz_channel(self):
        class SetupBuzz(BuzzBridge):
            def __init__(self, root):
                super().__init__(root)
                self.create_count = 0

            @property
            def identities(self):
                return {"PRISM_BUZZ_AGENT_PUBLIC_KEY": "a" * 64}

            def _run(self, *args, actor="owner", stdin=None):
                if args[:2] == ("channels", "create"):
                    self.create_count += 1
                    time.sleep(0.02)
                    return json.dumps({"channel_id": str(uuid.UUID(int=99))})
                return json.dumps({})

            def set_canvas(self, channel_id, content, *, persist_binding=True):
                return {"event_id": "c" * 64}

        room = {"id": "room", "name": "Room", "description": "Private"}
        with tempfile.TemporaryDirectory() as folder:
            bridge = SetupBuzz(folder)
            with ThreadPoolExecutor(max_workers=10) as pool:
                records = list(pool.map(
                    lambda _: bridge.ensure_room(room, 1, 0),
                    range(20),
                ))
            self.assertEqual(bridge.create_count, 1)
            self.assertTrue(all(record == records[0] for record in records))
            self.assertEqual(bridge._room_map()["room"], records[0])

    def test_room_setup_canvas_excludes_source_payload_and_discloses_buzz_retention(self):
        secret_source_text = "CONFIDENTIAL_SENTINEL_7f92"
        canvas = initial_room_canvas(
            {"name": "Project Cedar", "description": "Operator-selected local folder"},
            document_count=4,
            warnings=1,
        )
        self.assertNotIn(secret_source_text, canvas)
        self.assertIn("does not publish file bytes during room setup", canvas)
        self.assertIn("generated briefs, citations, and reviewed canvases", canvas)
        self.assertIn("stored as signed events on this Buzz relay", canvas)

    def test_named_review_events_are_restored_across_message_pages(self):
        target = "a" * 64
        bridge = PagingBuzz({
            None: [
                {"id": "new-one", "created_at": 10},
                {"id": "new-two", "created_at": 9},
            ],
            8: [
                {"id": target, "created_at": 8, "pubkey": "b" * 64},
            ],
        })
        restored = bridge.messages_by_ids("review-room", {target}, page_size=2)
        self.assertEqual(set(restored), {target})
        self.assertEqual(
            bridge.calls,
            [("review-room", 2, None), ("review-room", 2, 8)],
        )

    def test_pagination_without_event_timestamps_fails_closed(self):
        bridge = PagingBuzz({
            None: [{"id": "one"}, {"id": "two", "created_at": 9}],
        })
        with self.assertRaisesRegex(BuzzUnavailable, "integer created_at"):
            bridge.messages_by_ids("review-room", {"missing"}, page_size=2)

    def test_raw_event_restore_verifies_signature_and_channel(self):
        channel = EVENT["tags"][0][1]
        bridge = RawBuzz(EVENT)
        restored = bridge.events_by_ids({EVENT["id"]}, channel_id=channel)
        self.assertEqual(restored[EVENT["id"]]["sig"], EVENT["sig"])
        bridge.events_by_ids({EVENT["id"]}, channel_id=channel)
        self.assertEqual(bridge.run_count, 1)
        with self.assertRaisesRegex(BuzzUnavailable, "is not in channel"):
            RawBuzz(EVENT).events_by_ids({EVENT["id"]}, channel_id="wrong-channel")

    def test_raw_event_restore_rejects_signature_tamper(self):
        tampered = copy.deepcopy(EVENT)
        tampered["sig"] = "0" * 128
        with self.assertRaisesRegex(BuzzUnavailable, "failed verification"):
            RawBuzz(tampered).events_by_ids({EVENT["id"]})

    def test_room_messages_require_raw_signature_and_exact_payload(self):
        channel = EVENT["tags"][0][1]
        bridge = VerifiedMessageBuzz(EVENT)
        messages = bridge.verified_messages(channel)
        self.assertTrue(messages[0]["signature_verified"])
        self.assertEqual(
            messages[0]["signature_scheme"],
            "nip01_event_id_plus_bip340",
        )

        altered = copy.deepcopy(bridge.displayed_event)
        altered["content"] = "relay transformed the signed content"
        with self.assertRaisesRegex(BuzzUnavailable, "differs from its verified raw event"):
            VerifiedMessageBuzz(EVENT, altered).verified_messages(channel)

    def test_published_message_must_restore_with_expected_content_and_identity(self):
        channel = EVENT["tags"][0][1]
        bridge = RawBuzz(EVENT)
        bridge._verify_published_message(
            {"event_id": EVENT["id"]},
            channel_id=channel,
            content=EVENT["content"],
            expected_pubkey=EVENT["pubkey"],
        )
        with self.assertRaisesRegex(BuzzUnavailable, "content differs"):
            bridge._verify_published_message(
                {"event_id": EVENT["id"]},
                channel_id=channel,
                content="different content",
                expected_pubkey=EVENT["pubkey"],
            )
        with self.assertRaisesRegex(BuzzUnavailable, "unexpected identity"):
            bridge._verify_published_message(
                {"event_id": EVENT["id"]},
                channel_id=channel,
                content=EVENT["content"],
                expected_pubkey="f" * 64,
            )

    def test_canvas_read_requires_bound_raw_signature_and_exact_payload(self):
        bridge = CanvasBuzz()
        result = bridge.verified_canvas(CANVAS_CHANNEL)
        self.assertEqual(result["markdown"], CANVAS_CONTENT)
        self.assertEqual(result["event_id"], CANVAS_EVENT["id"])
        self.assertEqual(result["signature_verification"]["state"], "verified")

        with self.assertRaisesRegex(BuzzUnavailable, "content differs"):
            CanvasBuzz(content="changed after signing").verified_canvas(CANVAS_CHANNEL)
        with self.assertRaisesRegex(BuzzUnavailable, "no single verified event binding"):
            CanvasBuzz(bound=False).verified_canvas(CANVAS_CHANNEL)

    def test_canvas_write_verifies_and_persists_event_binding(self):
        bridge = CanvasBuzz(bound=False)
        result = bridge.set_canvas(CANVAS_CHANNEL, CANVAS_CONTENT)
        self.assertTrue(result["signature_verified"])
        self.assertEqual(
            bridge.rooms["room"]["canvas_event_id"],
            CANVAS_EVENT["id"],
        )

    def test_room_registry_rejects_corruption_and_identity_drift(self):
        channel = "8797b0be-9305-437f-84c6-8ed95385dd64"
        valid = {"room": {"room_id": "room", "channel_id": channel}}
        with tempfile.TemporaryDirectory() as folder:
            bridge = BuzzBridge(folder)
            bridge.rooms_path.parent.mkdir(parents=True)
            bridge.rooms_path.write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(BuzzUnavailable, "invalid JSON"):
                bridge._room_map()

            for invalid, message in (
                ({"room": {"room_id": "other", "channel_id": channel}}, "identity differs"),
                ({"room": {"room_id": "room", "channel_id": "not-a-uuid"}}, "invalid channel ID"),
                ({"room": {"room_id": "room", "channel_id": channel, "extra": True}}, "unknown fields"),
                ({
                    "room": {"room_id": "room", "channel_id": channel},
                    "other": {"room_id": "other", "channel_id": channel},
                }, "one channel to multiple rooms"),
            ):
                with self.assertRaisesRegex(BuzzUnavailable, message):
                    bridge._validated_room_map(invalid)

            bridge._save_room_map(valid)
            before = bridge.rooms_path.read_bytes()
            self.assertEqual(bridge._room_map(), valid)
            self.assertEqual(os.stat(bridge.rooms_path).st_mode & 0o777, 0o600)
            with self.assertRaises(BuzzUnavailable):
                bridge._save_room_map({"room": {"room_id": "drift", "channel_id": channel}})
            self.assertEqual(bridge.rooms_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
