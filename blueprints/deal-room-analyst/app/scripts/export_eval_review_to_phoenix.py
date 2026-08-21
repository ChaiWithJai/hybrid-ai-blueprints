#!/usr/bin/env python3
"""Explicitly export Prism human-review telemetry to Arize Phoenix over OTLP."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent


def _loopback_endpoint(value: str) -> bool:
    host = urllib.parse.urlparse(value).hostname
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def _fetch(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=10) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise RuntimeError("review observability endpoint returned an invalid response")
    return value


def _timestamp_ns(value: str | None) -> int | None:
    if not value:
        return None
    return int(datetime.fromisoformat(value).timestamp() * 1_000_000_000)


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def build_receipt(
    snapshot: dict[str, Any],
    *,
    endpoint: str,
    project: str,
    fixture: bool,
) -> dict[str, Any]:
    """Describe collector acceptance without claiming human review."""
    snapshot_sha256 = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema_version": 1,
        "verification_kind": "explicit_phoenix_otlp_eval_export",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": endpoint,
        "project": project,
        "review_record_count": len(snapshot.get("records", [])),
        "content_policy": snapshot.get("content_policy"),
        "snapshot_sha256": snapshot_sha256,
        "exporter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "transport": "OpenTelemetry OTLP HTTP protobuf",
        "semantics": "OpenInference EVALUATOR spans with prism.eval.* local extensions",
        "record_provenance": (
            "synthetic_fixture"
            if fixture
            else "local_review_ledger_self_asserted_reviewer"
        ),
        "synthetic_fixture": fixture,
        "reviewer_identity_verified": False,
        "human_review_performed_claimed": False,
        "limitations": [
            "A successful OTLP export proves collector acceptance, not reviewer identity or label quality.",
            "Synthetic fixture records do not count as human review.",
            "The local review ledger remains the authoritative annotation record.",
            "Prompt, source, and note content is excluded unless --include-content is explicitly supplied.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-url", default="http://127.0.0.1:8787")
    parser.add_argument("--room", default="project_titan_lbo")
    parser.add_argument("--endpoint", default=os.environ.get("PRISM_PHOENIX_OTLP_ENDPOINT", "http://127.0.0.1:6006/v1/traces"))
    parser.add_argument("--project", default="prism-error-discovery")
    parser.add_argument("--include-content", action="store_true")
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument(
        "--fixture",
        action="store_true",
        help="Mark every exported record as synthetic verification data, not human review.",
    )
    parser.add_argument("--output", default="evidence/phoenix-eval-export-v1.json")
    args = parser.parse_args()

    if not args.allow_remote and not _loopback_endpoint(args.endpoint):
        raise RuntimeError("non-loopback Phoenix export requires --allow-remote")
    query = urllib.parse.urlencode({
        "room": args.room,
        "include_content": "true" if args.include_content else "false",
    })
    snapshot = _fetch(
        f"{args.review_url.rstrip('/')}/api/workspace/evaluation/observability?{query}"
    )

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    except ImportError as exc:
        raise RuntimeError(
            "OpenTelemetry export dependencies are missing. Install "
            "opentelemetry-sdk and opentelemetry-exporter-otlp-proto-http in an isolated environment."
        ) from exc

    resource_attributes = dict(snapshot.get("resource", {}))
    resource_attributes["openinference.project.name"] = args.project
    provider = TracerProvider(resource=Resource.create(resource_attributes))
    exporter = OTLPSpanExporter(
        endpoint=args.endpoint,
        headers={"x-project-name": args.project},
    )
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("prism.error_discovery", "1.0.0")

    with tracer.start_as_current_span("Prism human error discovery") as root_span:
        root_span.set_attribute("openinference.span.kind", "CHAIN")
        root_span.set_attribute("session.id", "prism-milestone-8")
        root_span.set_attribute("prism.eval.reviewed_count", snapshot.get("summary", {}).get("reviewed_count", 0))
        root_span.set_attribute("prism.eval.content.policy", snapshot.get("content_policy", "unknown"))
        root_span.set_attribute("prism.eval.synthetic_fixture", args.fixture)
        for record in snapshot.get("records", []):
            start = _timestamp_ns(record.get("started_at"))
            span = tracer.start_span(record.get("name", "evaluate Prism workspace trace"), start_time=start)
            for key, value in record.get("attributes", {}).items():
                if value is None:
                    continue
                if isinstance(value, list):
                    value = [str(item) for item in value]
                span.set_attribute(key, value)
            span.set_attribute("prism.eval.synthetic_fixture", args.fixture)
            if args.fixture:
                span.set_attribute("prism.eval.feedback.source", "synthetic_fixture")
            span.end(end_time=_timestamp_ns(record.get("ended_at")))
    provider.force_flush()
    provider.shutdown()

    receipt = build_receipt(
        snapshot,
        endpoint=args.endpoint,
        project=args.project,
        fixture=args.fixture,
    )
    _atomic_write((ROOT / args.output).resolve(), receipt)
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
