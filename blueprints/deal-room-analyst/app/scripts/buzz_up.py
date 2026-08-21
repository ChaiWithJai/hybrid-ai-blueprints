#!/usr/bin/env python3
"""Bootstrap the pinned local Buzz relay without committing secrets.

This script creates local-only operator and agent identities, starts the real
Buzz single-node substrate, and stores runtime material under .runtime/buzz.
It is idempotent: existing identities and Docker volumes are preserved.
"""

from __future__ import annotations

import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime" / "buzz"
ENV_PATH = RUNTIME / ".env"
IDENTITY_PATH = RUNTIME / "identities.env"
COMPOSE_PATH = ROOT / "infra" / "buzz" / "compose.yml"
IMAGE = "ghcr.io/block/buzz:main@sha256:32937a6644ed340560ca4b1e445ecfc13a78bf6046358fdcf52e9018e4fe2afe"


def run(*args: str, capture: bool = False, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=capture,
        env=env,
    )
    return completed.stdout if capture else ""


def generate_key() -> tuple[str, str]:
    output = run(
        "docker", "run", "--rm", "--entrypoint", "buzz-admin", IMAGE,
        "generate-key", capture=True,
    )
    public = re.search(r"Public key:\s+([0-9a-f]{64})", output)
    secret = re.search(r"Secret key:\s+([0-9a-f]{64})", output)
    if not public or not secret:
        raise RuntimeError("buzz-admin did not return a parseable keypair")
    return public.group(1), secret.group(1)


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def write_private(path: Path, values: dict[str, str]) -> None:
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
    path.chmod(0o600)


def ensure_runtime() -> tuple[dict[str, str], dict[str, str]]:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    identities = read_env(IDENTITY_PATH)
    if not identities:
        owner_public, owner_secret = generate_key()
        agent_public, agent_secret = generate_key()
        identities = {
            "PRISM_BUZZ_OWNER_PUBLIC_KEY": owner_public,
            "PRISM_BUZZ_OWNER_PRIVATE_KEY": owner_secret,
            "PRISM_BUZZ_AGENT_PUBLIC_KEY": agent_public,
            "PRISM_BUZZ_AGENT_PRIVATE_KEY": agent_secret,
        }
        write_private(IDENTITY_PATH, identities)

    config = read_env(ENV_PATH)
    if not config:
        config = {
            "BUZZ_HTTP_PORT": "3030",
            "RELAY_URL": "ws://127.0.0.1:3030",
            "BUZZ_MEDIA_BASE_URL": "http://127.0.0.1:3030/media",
            "BUZZ_MEDIA_SERVER_DOMAIN": "127.0.0.1",
            "BUZZ_CORS_ORIGINS": "http://127.0.0.1:8787,http://localhost:8787",
            "BUZZ_REQUIRE_AUTH_TOKEN": "false",
            "BUZZ_REQUIRE_RELAY_MEMBERSHIP": "true",
            "BUZZ_ALLOW_NIP_OA_AUTH": "true",
            "BUZZ_AUTO_MIGRATE": "true",
            "BUZZ_GIT_CONFORMANCE_PROBE": "false",
            "RUST_LOG": "buzz_relay=info,buzz_auth=info",
            "RELAY_OWNER_PUBKEY": identities["PRISM_BUZZ_OWNER_PUBLIC_KEY"],
            "BUZZ_RELAY_PRIVATE_KEY": identities["PRISM_BUZZ_OWNER_PRIVATE_KEY"],
            "BUZZ_GIT_HOOK_HMAC_SECRET": secrets.token_hex(32),
            "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
            "REDIS_PASSWORD": secrets.token_urlsafe(32),
            "BUZZ_S3_ACCESS_KEY": "prism" + secrets.token_hex(8),
            "BUZZ_S3_SECRET_KEY": secrets.token_urlsafe(32),
        }
        write_private(ENV_PATH, config)
    return identities, config


def wait_for_relay(port: str) -> None:
    url = f"http://127.0.0.1:{port}/_liveness"
    for _ in range(60):
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(1)
    raise RuntimeError(f"Buzz relay did not become live at {url}")


def main() -> int:
    identities, config = ensure_runtime()
    compose_env = os.environ.copy()
    compose_env.update(config)
    compose_env["PRISM_BUZZ_ENV_FILE"] = str(ENV_PATH)
    run("docker", "compose", "--env-file", str(ENV_PATH), "-f", str(COMPOSE_PATH), "up", "-d", env=compose_env)
    wait_for_relay(config["BUZZ_HTTP_PORT"])

    # Registration is a signed Buzz membership event. Repeating it is safe and
    # keeps a restored database aligned with the preserved local identities.
    run(
        "docker", "compose", "--env-file", str(ENV_PATH),
        "-f", str(COMPOSE_PATH), "run", "--rm", "--no-deps",
        "--entrypoint", "buzz-admin", "relay", "add-member",
        "--pubkey", identities["PRISM_BUZZ_AGENT_PUBLIC_KEY"],
        env=compose_env,
    )
    print("Buzz relay: http://127.0.0.1:3030")
    print("Runtime identities: .runtime/buzz/identities.env (mode 0600)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"buzz bootstrap failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
