#!/usr/bin/env python3
"""Run the local minimum lovable surface and its real Buzz/Bonsai processes."""

from __future__ import annotations

import os
import argparse
import json
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.buzz_agent_scope import resolve_agent_scope  # noqa: E402


RUNTIME = ROOT / ".runtime" / "buzz"


def assert_loopback_port_available(port: int) -> None:
    """Fail before announcing a URL if another process owns the requested port."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Match PrismHTTPServer.allow_reuse_address so a clean restart is not
        # mistaken for a live competing listener while TCP connections drain.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))
    except OSError as exc:
        raise RuntimeError(
            f"Prism will not start: 127.0.0.1:{port} is already in use. "
            "Stop the existing process or choose another explicit --port; no fallback "
            "URL was advertised."
        ) from exc
    finally:
        probe.close()


def verify_server_started(
    server: subprocess.Popen,
    port: int,
    *,
    timeout_seconds: float = 30.0,
    request_timeout_seconds: float = 5.0,
) -> None:
    """Require the status endpoint to identify the exact child before announcement."""
    url = f"http://127.0.0.1:{port}/api/status"
    deadline = time.monotonic() + timeout_seconds
    last_error = "status endpoint did not respond"
    while time.monotonic() < deadline:
        return_code = server.poll()
        if return_code is not None:
            raise RuntimeError(
                f"Prism server exited during startup with code {return_code}; "
                "the workspace URL was not advertised."
            )
        try:
            with urllib.request.urlopen(url, timeout=request_timeout_seconds) as response:
                status = json.load(response)
            if status.get("server_process_pid") != server.pid:
                last_error = (
                    "status endpoint belongs to PID "
                    f"{status.get('server_process_pid')}, expected child PID {server.pid}"
                )
            elif status.get("product_stage") != "local_prototype":
                last_error = "status endpoint did not identify the Prism local prototype"
            elif status.get("buzz", {}).get("workspace_ready") is not True:
                last_error = "Buzz workspace was not ready"
            else:
                return
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(0.1)
    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()
    raise RuntimeError(
        f"Prism server did not prove ownership of {url}; the workspace URL was not "
        f"advertised. Last observation: {last_error}"
    )


def running_acp_pids(binary: Path) -> list[int]:
    """Return exact running instances of this checkout's ACP binary."""
    completed = subprocess.run(
        ["ps", "-axo", "pid=,command="], text=True, capture_output=True, check=True,
    )
    expected = str(binary.resolve())
    observed: list[int] = []
    for line in completed.stdout.splitlines():
        fields = line.strip().split(maxsplit=1)
        if len(fields) != 2 or fields[1] != expected:
            continue
        try:
            observed.append(int(fields[0]))
        except ValueError:
            continue
    return observed


def stop_agent_tree(binaries: list[Path], grace_seconds: float = 2.0) -> None:
    """Stop only exact agent binaries from this checkout, including child groups."""
    targets: set[int] = set()
    for binary in binaries:
        targets.update(running_acp_pids(binary))
    for pid in targets:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + grace_seconds
    remaining = set(targets)
    while remaining and time.monotonic() < deadline:
        remaining = {pid for pid in remaining if _pid_exists(pid)}
        if remaining:
            time.sleep(0.05)
    for pid in remaining:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def verify_agent_started(agent: subprocess.Popen, log_path: Path, wait_seconds: float = 1.0) -> None:
    """Reject an ACP process that exits before Prism announces a ready surface."""
    time.sleep(wait_seconds)
    return_code = agent.poll()
    if return_code is None:
        return
    try:
        detail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
    except OSError:
        detail = "agent log unavailable"
    raise RuntimeError(
        f"Buzz Bonsai agent exited during startup with code {return_code}.\n{detail}"
    )


def verify_agent_subscription(
    agent: subprocess.Popen,
    log_path: Path,
    channel_id: str,
    *,
    start_offset: int,
    timeout_seconds: float = 30.0,
) -> None:
    """Require the pinned harness to confirm the exact channel subscription."""
    marker = f"subscribed to channel {channel_id}"
    deadline = time.monotonic() + timeout_seconds
    detail = ""
    while time.monotonic() < deadline:
        return_code = agent.poll()
        try:
            with log_path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(start_offset)
                detail = handle.read()
        except OSError:
            detail = ""
        if marker in detail:
            return
        if return_code is not None:
            raise RuntimeError(
                f"Buzz Bonsai agent exited before subscribing to {channel_id} "
                f"with code {return_code}.\n{detail[-4000:]}"
            )
        time.sleep(0.1)
    raise RuntimeError(
        f"Buzz Bonsai agent did not confirm subscription to {channel_id}; "
        "Prism was not announced.\n" + detail[-4000:]
    )


def supervise(server: subprocess.Popen, agent: subprocess.Popen, log_path: Path) -> int:
    """Keep the surface honest if either long-running process exits."""
    while True:
        server_code = server.poll()
        if server_code is not None:
            return server_code
        agent_code = agent.poll()
        if agent_code is not None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
            try:
                detail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            except OSError:
                detail = "agent log unavailable"
            raise RuntimeError(
                f"Buzz Bonsai agent exited after startup with code {agent_code}; "
                f"Prism was stopped instead of advertising a partial surface.\n{detail}"
            )
        time.sleep(0.5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--direct-acp",
        action="store_true",
        help=(
            "Start the experimental direct Buzz mention responder. The proven v0 "
            "WebUI path publishes signed answers to Buzz without this process."
        ),
    )
    parser.add_argument(
        "--agent-room",
        default=os.environ.get("PRISM_BUZZ_ACP_ROOM_ID", "project_titan_lbo"),
        help=(
            "Room opened by the launcher and, with --direct-acp, the only room whose "
            "mentions may access its selected source folder."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8787,
        help="Exact loopback port for the Prism workspace. Occupied ports fail closed.",
    )
    args = parser.parse_args()
    env = os.environ.copy()
    env.setdefault("PRISM_LOCAL_AI_URL", "http://127.0.0.1:1234")
    env.setdefault("PRISM_LOCAL_AI_MODEL", "27b@q1_0")
    env.setdefault("PRISM_LOCAL_AI_PROTOCOL", "lmstudio-native")
    env.setdefault("PRISM_LOCAL_AI_KEY", "lm-studio")
    env.setdefault("PRISM_LOCAL_AI_PROMPT_SUFFIX", "/no_think")
    subprocess.run(
        [sys.executable, "scripts/preflight.py", "--phase", "host"],
        cwd=ROOT, env=env, check=True,
    )
    subprocess.run([sys.executable, "scripts/buzz_up.py"], cwd=ROOT, check=True)
    if not (RUNTIME / "bin" / "buzz").exists():
        subprocess.run([sys.executable, "scripts/buzz_install_tools.py"], cwd=ROOT, check=True)
    subprocess.run(
        [sys.executable, "scripts/preflight.py", "--phase", "live"],
        cwd=ROOT, env=env, check=True,
    )
    assert_loopback_port_available(args.port)
    if not args.direct_acp:
        print(
            "Direct Buzz ACP: not launched (experimental). "
            "WebUI answers remain source-scoped and are published as signed Buzz events."
        )
        server = subprocess.Popen(
            [sys.executable, "server.py", "--port", str(args.port)], cwd=ROOT, env=env,
        )
        verify_server_started(server, args.port)
        print(f"Prism Vault v0: http://127.0.0.1:{args.port}/rooms/{args.agent_room}")
        return server.wait()

    source_scope, channel_id = resolve_agent_scope(ROOT, args.agent_room)
    existing_agents = running_acp_pids(RUNTIME / "bin" / "buzz-acp")
    if existing_agents:
        raise RuntimeError(
            "A Buzz ACP process from this checkout is already running "
            f"(PID(s): {', '.join(map(str, existing_agents))}). Stop it before changing "
            "the room source scope; Prism will not run duplicate responders."
        )
    env.update({
        "PRISM_BUZZ_ACP_ROOM_ID": args.agent_room,
        "PRISM_BUZZ_ACP_CHANNEL_ID": channel_id,
        "PRISM_BUZZ_ACP_SOURCE_SCOPE": str(source_scope),
        "PRISM_BUZZ_ACP_EXPERIMENTAL": "true",
    })

    logs = RUNTIME / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    agent_log_path = logs / "bonsai-agent.log"
    agent_log = agent_log_path.open("a")
    agent_log_start = agent_log_path.stat().st_size
    agent = subprocess.Popen(
        [
            sys.executable,
            "scripts/buzz_agent.py",
            "--room-id", args.agent_room,
            "--deal-room", str(source_scope),
            "--channel", channel_id,
        ],
        cwd=ROOT,
        stdout=agent_log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        verify_agent_started(agent, agent_log_path)
        verify_agent_subscription(
            agent, agent_log_path, channel_id, start_offset=agent_log_start,
        )
        print(
            f"Experimental direct Buzz ACP scope: room={args.agent_room} channel={channel_id} "
            f"source={source_scope}"
        )
        server = subprocess.Popen(
            [sys.executable, "server.py", "--port", str(args.port)], cwd=ROOT, env=env,
        )
        verify_server_started(server, args.port)
        print(f"Prism Vault v0: http://127.0.0.1:{args.port}/rooms/{args.agent_room}")
        return supervise(server, agent, agent_log_path)
    finally:
        stop_agent_tree([
            RUNTIME / "bin" / "buzz-acp",
            RUNTIME / "bin" / "buzz-agent",
            RUNTIME / "bin" / "buzz-dev-mcp",
        ])
        agent_log.close()


if __name__ == "__main__":
    raise SystemExit(main())
