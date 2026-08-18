#!/usr/bin/env python3
"""Run Bonsai 27B as a real Buzz ACP room member."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.buzz_agent_scope import resolve_agent_scope  # noqa: E402


RUNTIME = ROOT / ".runtime" / "buzz"
BIN = RUNTIME / "bin"


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def build_acp_environment(
    base: dict[str, str],
    identities: dict[str, str],
    *,
    model: str,
    base_url: str,
    deal_room: Path,
    channel: str,
) -> dict[str, str]:
    """Build a single-room ACP policy. The agent must never subscribe globally."""
    env = dict(base)
    env.update({
        "PATH": f"{BIN}:{ROOT / 'scripts'}:{env.get('PATH', '')}",
        "BUZZ_PRIVATE_KEY": identities["PRISM_BUZZ_AGENT_PRIVATE_KEY"],
        "BUZZ_RELAY_URL": env.get("PRISM_BUZZ_RELAY_URL", "ws://127.0.0.1:3030"),
        "BUZZ_ACP_AGENT_COMMAND": str(BIN / "buzz-agent"),
        "BUZZ_ACP_MCP_COMMAND": str(BIN / "buzz-dev-mcp"),
        "BUZZ_ACP_SYSTEM_PROMPT_FILE": str(ROOT / "docs" / "BONSAI_DEAL_ROOM_PROMPT.md"),
        "BUZZ_ACP_SUBSCRIBE": "mentions",
        "BUZZ_ACP_CHANNELS": channel,
        "BUZZ_ACP_AGENT_OWNER": identities["PRISM_BUZZ_OWNER_PUBLIC_KEY"],
        "BUZZ_ACP_RESPOND_TO": "owner-only",
        "BUZZ_ACP_ALLOWED_RESPOND_TO": "owner-only",
        "BUZZ_ACP_NO_MEMORY": "true",
        "RUST_LOG": "buzz_acp=info",
        "BUZZ_AGENT_PROVIDER": "openai",
        "OPENAI_COMPAT_API_KEY": env.get("OPENAI_COMPAT_API_KEY", "lm-studio"),
        "OPENAI_COMPAT_MODEL": model,
        "OPENAI_COMPAT_BASE_URL": base_url,
        "OPENAI_COMPAT_API": "chat",
        "BUZZ_AGENT_MAX_CONTEXT_TOKENS": env.get("BUZZ_AGENT_MAX_CONTEXT_TOKENS", "16384"),
        "BUZZ_AGENT_MAX_OUTPUT_TOKENS": env.get("BUZZ_AGENT_MAX_OUTPUT_TOKENS", "4096"),
        "BUZZ_AGENT_MAX_ROUNDS": env.get("BUZZ_AGENT_MAX_ROUNDS", "12"),
        "BUZZ_AGENT_TOOL_TIMEOUT_SECS": env.get("BUZZ_AGENT_TOOL_TIMEOUT_SECS", "90"),
        "BUZZ_AGENT_REQUIRE_REPLY": "1",
        "BUZZ_AGENT_NO_HINTS": "1",
        "PRISM_DEAL_ROOM_SOURCE": str(deal_room),
    })
    return env


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--room-id", required=True)
    parser.add_argument("--deal-room", default="deal_rooms/project_titan_lbo")
    parser.add_argument("--channel", required=True)
    parser.add_argument("--model", default="27b@q1_0")
    parser.add_argument("--base-url", default="http://127.0.0.1:1234/v1")
    args = parser.parse_args()

    deal_room = (ROOT / args.deal_room).resolve() if not Path(args.deal_room).is_absolute() else Path(args.deal_room).resolve()
    if not deal_room.is_dir():
        parser.error(f"deal-room folder does not exist: {deal_room}")
    try:
        channel = str(uuid.UUID(args.channel))
    except ValueError:
        parser.error("--channel must be a canonical UUID")
    if channel != args.channel:
        parser.error("--channel must be a canonical UUID")
    try:
        expected_source, expected_channel = resolve_agent_scope(ROOT, args.room_id)
    except RuntimeError as exc:
        parser.error(str(exc))
    if expected_source != deal_room or expected_channel != channel:
        parser.error("room, source scope, and Buzz channel are not one verified binding")
    required = [BIN / name for name in ("buzz", "buzz-agent", "buzz-acp", "buzz-dev-mcp")]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        parser.error("Buzz tools are missing; run scripts/buzz_install_tools.py")

    with urlopen(f"{args.base_url.rstrip('/')}/models", timeout=3) as response:
        models = json.load(response)
    model_ids = {model.get("id") for model in models.get("data", [])}
    if args.model not in model_ids:
        parser.error(f"model {args.model!r} is not listed by {args.base_url}")

    identities = read_env(RUNTIME / "identities.env")
    required_identities = {
        "PRISM_BUZZ_AGENT_PRIVATE_KEY",
        "PRISM_BUZZ_OWNER_PUBLIC_KEY",
    }
    if any(len(identities.get(key, "")) != 64 for key in required_identities):
        parser.error("Buzz agent and owner identities are missing or invalid")
    env = build_acp_environment(
        os.environ.copy(), identities, model=args.model, base_url=args.base_url,
        deal_room=deal_room, channel=channel,
    )
    workspace_id = hashlib.sha256(str(deal_room).encode("utf-8")).hexdigest()[:16]
    query_workspace = RUNTIME / "query-workspaces" / workspace_id
    query_workspace.mkdir(parents=True, exist_ok=True)
    query_workspace.chmod(0o555)
    print(
        f"Starting Buzz agent model={args.model} room={args.room_id} channel={channel} "
        f"source_scope={deal_room} respond_to=owner-only subscription=mentions "
        f"memory=disabled query_workspace={query_workspace}", file=sys.stderr,
    )
    os.chdir(query_workspace)
    os.execve(str(BIN / "buzz-acp"), [str(BIN / "buzz-acp")], env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
