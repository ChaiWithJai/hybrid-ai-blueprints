"""Validation for the current Prism customer demo contract and browser record."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# docs/ is a CATALOG resource and stays at the repository root, four levels
# above this application after the issue #2 migration. The `root` argument
# stays the application root: callers pass a temporary copy of it for tamper
# tests, and those copies contain web/ fixtures, never the catalog docs.
REPO_ROOT = Path(__file__).resolve().parents[4]


EXPECTED_ASSERTIONS = {
    "room_identity_is_clear",
    "strategy_state_is_secondary",
    "primary_navigation_is_plain",
    "retired_programs_are_outside_primary_navigation",
    "decision_status_has_priority",
    "decision_question_is_specific",
    "priority_sources_are_grouped",
    "citation_preview_preserves_current_view",
    "citation_preview_opens_exact_full_source",
    "citation_context_reaches_persistent_composer",
    "supported_source_formats_render_semantically",
    "activity_separates_background_events",
    "composer_is_available_in_all_primary_views",
    "activity_keeps_canonical_room_url",
    "secondary_views_are_in_room_details",
    "required_viewports_have_no_horizontal_overflow",
}


def _read(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"cannot read {path}: {exc}")
        return ""


def validate_content_graph(root: Path) -> dict[str, Any]:
    """Fail when a visible segment or product phrase has no stated job."""

    errors: list[str] = []
    graph_path = root / "web" / "content-graph.json"
    try:
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "errors": [f"cannot read content graph: {exc}"]}
    nodes = graph.get("nodes", []) if isinstance(graph, Mapping) else []
    if not isinstance(nodes, list):
        return {"passed": False, "errors": ["content graph nodes must be a list"]}
    by_id: dict[str, Mapping[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, Mapping) or not isinstance(node.get("id"), str):
            errors.append("content graph contains a node without an id")
            continue
        node_id = str(node["id"])
        if node_id in by_id:
            errors.append(f"duplicate content graph node: {node_id}")
        by_id[node_id] = node
        if not str(node.get("statement") or node.get("defense") or "").strip():
            errors.append(f"content graph node has no statement or defense: {node_id}")

    root_job = graph.get("root_job")
    if root_job not in by_id or by_id[root_job].get("kind") != "job":
        errors.append("content graph root_job must name a job node")

    referenced_copy: set[str] = set()
    for node_id, node in by_id.items():
        if node.get("kind") != "segment":
            continue
        question = node.get("user_question")
        if question not in by_id or by_id[question].get("kind") not in {"job", "user_question"}:
            errors.append(f"segment has no valid user question: {node_id}")
        if not str(node.get("placement", "")).strip() or not str(node.get("defense", "")).strip():
            errors.append(f"segment has no placement or defense: {node_id}")
        for copy_id in node.get("copy", []):
            referenced_copy.add(str(copy_id))
            if copy_id not in by_id or by_id[copy_id].get("kind") != "copy":
                errors.append(f"segment references invalid copy: {node_id} -> {copy_id}")

    for node_id, node in by_id.items():
        if node.get("kind") == "copy":
            if not str(node.get("text", "")).strip() or not str(node.get("defense", "")).strip():
                errors.append(f"copy has no text or defense: {node_id}")
            if node_id not in referenced_copy:
                errors.append(f"copy is not owned by a segment: {node_id}")

    edges = graph.get("edges", [])
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in by_id}
    for edge in edges if isinstance(edges, list) else []:
        if not isinstance(edge, list) or len(edge) != 2 or edge[0] not in by_id or edge[1] not in by_id:
            errors.append(f"content graph contains an invalid edge: {edge}")
            continue
        adjacency[str(edge[0])].add(str(edge[1]))
    reachable: set[str] = set()
    frontier = [str(root_job)] if root_job in by_id else []
    while frontier:
        current = frontier.pop()
        if current in reachable:
            continue
        reachable.add(current)
        frontier.extend(adjacency.get(current, ()))
    for node_id, node in by_id.items():
        if node.get("kind") == "segment" and node_id not in reachable:
            errors.append(f"segment is not connected to the root job: {node_id}")

    html = _read(root / "web" / "index.html", errors)
    javascript = _read(root / "web" / "app.js", errors)
    rendered_source = f"{html}\n{javascript}".casefold()
    for node_id, node in by_id.items():
        if node.get("kind") == "segment" and f'data-content-id="{node_id}"'.casefold() not in rendered_source:
            errors.append(f"segment has no rendered content id: {node_id}")
        if node.get("kind") == "copy" and str(node.get("text", "")).casefold() not in rendered_source:
            errors.append(f"defended copy is absent from the product source: {node_id}")
    for phrase in graph.get("forbidden_primary_copy", []):
        if str(phrase).casefold() in rendered_source:
            errors.append(f"retired primary copy remains in product source: {phrase}")

    return {
        "verification_kind": "deal_room_content_graph.v1",
        "passed": not errors,
        "errors": errors,
        "root_job": root_job,
        "node_count": len(by_id),
        "segment_count": sum(node.get("kind") == "segment" for node in by_id.values()),
        "copy_count": sum(node.get("kind") == "copy" for node in by_id.values()),
    }


def validate_customer_demo_scope(root: Path) -> dict[str, Any]:
    """Check that the accepted demo decision is present from policy to UI."""

    errors: list[str] = []
    documents = {
        "adr": _read(REPO_ROOT / "docs" / "ADR_0002_DEMO_FIRST_SCOPE.md", errors),
        "structure": _read(REPO_ROOT / "docs" / "DEMO_INFORMATION_ARCHITECTURE.md", errors),
        "content_graph": _read(REPO_ROOT / "docs" / "DEAL_ROOM_CONTENT_GRAPH.md", errors),
        "prd": _read(REPO_ROOT / "docs" / "PRD.md", errors),
        "rfc": _read(REPO_ROOT / "docs" / "RFC_0042_VAULT_ARCHITECTURE.md", errors),
        "surface": _read(REPO_ROOT / "docs" / "SURFACE_V0.md", errors),
        "gates": _read(REPO_ROOT / "docs" / "VERIFICATION_GATES.md", errors),
        "status": _read(REPO_ROOT / "docs" / "IMPLEMENTATION_STATUS.md", errors),
    }
    html = _read(root / "web" / "index.html", errors)
    javascript = _read(root / "web" / "app.js", errors)
    stylesheet = _read(root / "web" / "style.css", errors)

    required_document_markers = {
        "adr": (
            "Accuracy certification and commercial proof are outside the current goal.",
            "The main room navigation contains Overview, Sources, Activity, and Evaluation.",
            "The current browser client uses plain HTML, CSS, and JavaScript.",
        ),
        "structure": (
            "Where am I?",
            "What can I do here?",
            "What should I do next?",
            "The main navigation contains no benchmark or pricing work.",
            "The page works at 390, 768, and 1440 pixel widths.",
        ),
        "content_graph": (
            "decide whether to advance, pause, or stop a deal, and know what must happen next.",
            "Every visible segment must",
            "web/content-graph.json",
        ),
        "prd": ("Accuracy certification and", "outside the current goal"),
        "rfc": ("Accuracy certification and commercial proof no longer gate the demo.",),
        "surface": ("Accuracy certification and commercial proof are outside the current demo goal.",),
        "gates": ("Accuracy certification and commercial proof do not gate the current demo.",),
        "status": ("Accuracy certification and commercial proof are outside this goal.",),
    }
    for name, markers in required_document_markers.items():
        normalized_document = " ".join(documents[name].split())
        for marker in markers:
            if marker not in normalized_document:
                errors.append(f"{name} is missing current demo marker: {marker}")

    for marker in (
        '>Overview</button>',
        '>Sources</button>',
        '>Activity</button>',
        '>Evaluation</button>',
        '>Decision notes</button>',
        '>Technical details</button>',
        'id="run-first-pass" type="submit">Review deal room</button>',
        'id="show-analysis-controls" type="button">Edit question</button>',
        'id="copy-room-link"',
        'id="toggle-context"',
        'app.js?v=hybrid-eval-lab-v1',
        'style.css?v=hybrid-eval-lab-v1',
    ):
        if marker not in html:
            errors.append(f"customer demo HTML is missing: {marker}")
    primary_navigation = html.split('<nav class="workspace-tabs"', 1)[-1].split("</nav>", 1)[0]
    for retired_label in (">Benchmark</button>", ">Pricing</button>"):
        if retired_label in primary_navigation:
            errors.append(f"retired program appears in primary navigation: {retired_label}")
    if primary_navigation.count('role="tab"') != 4:
        errors.append("primary navigation must contain exactly four semantic tabs")

    for marker in (
        "friendlyModelName",
        "enhanceBriefDocument",
        "openCitation(citation)",
        "openFullCitationSource()",
        "askAboutCitation()",
        "renderSourceContent(doc, value = \"\")",
        "copyRoomLink()",
        '.slice(-10)',
    ):
        if marker not in javascript:
            errors.append(f"customer demo script is missing: {marker}")
    for marker in ("@media (max-width: 960px)", "@media (max-width: 760px)", ".priority-source"):
        if marker not in stylesheet:
            errors.append(f"customer demo stylesheet is missing: {marker}")

    content_graph = validate_content_graph(root)
    errors.extend(content_graph["errors"])
    return {
        "verification_kind": "customer_demo_scope_contract.v1",
        "passed": not errors,
        "errors": errors,
        "documents": [
            "docs/ADR_0002_DEMO_FIRST_SCOPE.md",
            "docs/DEMO_INFORMATION_ARCHITECTURE.md",
            "docs/DEAL_ROOM_CONTENT_GRAPH.md",
            "docs/PRD.md",
            "docs/RFC_0042_VAULT_ARCHITECTURE.md",
            "docs/SURFACE_V0.md",
            "docs/VERIFICATION_GATES.md",
            "docs/IMPLEMENTATION_STATUS.md",
        ],
        "asset_version": "hybrid-eval-lab-v1",
        "content_graph": content_graph,
    }


def validate_customer_demo_browser_record(root: Path, record_path: Path) -> dict[str, Any]:
    """Validate the saved browser record and its screenshot bytes."""

    errors: list[str] = []
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}
    if not isinstance(record, Mapping):
        return {"passed": False, "record": str(record_path), "errors": ["record is not an object"]}
    if record.get("verification_kind") != "customer_demo_browser_surface.v1":
        errors.append("unexpected customer demo browser verification kind")
    if record.get("semantic_state") != "current_customer_demo_surface":
        errors.append("customer demo browser record has the wrong semantic state")
    if record.get("asset_version") != "hybrid-eval-lab-v1":
        errors.append("customer demo browser record does not match the current asset version")
    if record.get("room") != "project_titan_lbo":
        errors.append("customer demo browser record does not use Project Titan")
    assertions = record.get("assertions", [])
    names = {item.get("name") for item in assertions if isinstance(item, Mapping)}
    missing = sorted(EXPECTED_ASSERTIONS - names)
    if missing:
        errors.append(f"customer demo browser record is missing assertions: {', '.join(missing)}")
    if any(item.get("passed") is not True for item in assertions if isinstance(item, Mapping)):
        errors.append("one or more customer demo browser assertions failed")
    if record.get("assertion_count") != len(assertions):
        errors.append("customer demo assertion count does not match")

    viewports = record.get("viewports", [])
    widths = {item.get("width") for item in viewports if isinstance(item, Mapping)}
    if widths != {390, 768, 1440}:
        errors.append("customer demo record must cover 390, 768, and 1440 pixel widths")
    for viewport in viewports:
        if not isinstance(viewport, Mapping) or viewport.get("scroll_width") != viewport.get("width"):
            errors.append("customer demo record contains horizontal overflow")
            break
    for field in ("console_errors", "failed_requests", "http_errors"):
        if record.get(field):
            errors.append(f"customer demo browser record contains {field}")

    screenshots = record.get("screenshots", [])
    if len(screenshots) != 2:
        errors.append("customer demo record must contain desktop and mobile screenshots")
    for screenshot in screenshots:
        if not isinstance(screenshot, Mapping):
            errors.append("customer demo screenshot record is invalid")
            continue
        path = (root / str(screenshot.get("path", ""))).resolve()
        try:
            path.relative_to(root.resolve())
            data = path.read_bytes()
        except (ValueError, OSError) as exc:
            errors.append(f"customer demo screenshot is unavailable: {exc}")
            continue
        if screenshot.get("bytes") != len(data):
            errors.append("customer demo screenshot byte count does not match")
        if screenshot.get("sha256") != hashlib.sha256(data).hexdigest():
            errors.append("customer demo screenshot hash does not match")
    if record.get("passed") is not True:
        errors.append("customer demo browser run did not pass")
    limitations = record.get("limitations", [])
    if not any("human usability study" in str(item) for item in limitations):
        errors.append("customer demo record does not preserve its human study boundary")

    try:
        display_path = str(record_path.relative_to(root))
    except ValueError:
        display_path = str(record_path)
    return {
        "passed": not errors,
        "record": display_path,
        "room": record.get("room"),
        "asset_version": record.get("asset_version"),
        "assertion_count": len(assertions),
        "viewports": viewports,
        "screenshots": screenshots,
        "errors": errors,
        "limitations": limitations,
    }