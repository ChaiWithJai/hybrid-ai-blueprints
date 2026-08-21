import csv
import hashlib
import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock
import tempfile
import http.client
import os
import shutil
import subprocess
import sys
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from core.ai_provider import (
    LMStudioNativeProvider, OpenAICompatibleProvider, ProviderError, ProviderRegistry,
    ProviderResult,
)
from core.benchmark import run_benchmark
from core.coding_agent import DealRoomWorkflowAgent
from core.doc_parser import DealRoomParser
from core.deal_room_analyzer import DealRoomAnalyzer
from core.hybrid_router import HybridAIRouter
from tests.cloud_consent_fixtures import (
    authority as cloud_authority,
    relay_events as cloud_relay_events,
    signed_bundle,
)
from core.sandbox import SubprocessSandbox
from core.artifact_inspection import inspect_model_artifact
import server as server_module
from server import (
    DEAL_ROOM_CATALOG,
    VaultHTTPRequestHandler,
    global_tracer,
    trace_bound_deal_room_message_state,
)
from scripts.verify_product import (
    scan_claims,
    validate_browser_evidence,
    validate_accessibility_browser_evidence,
    validate_cross_browser_evidence,
    validate_case_authoring_browser_evidence,
    validate_cold_restart_evidence,
    validate_current_local_product_evidence,
    validate_real_deal_browser_evidence,
    validate_titan_debt_browser_evidence,
    validate_operator_review_restart_evidence,
    validate_provenance_bound_publication,
    validate_operator_preflight_evidence,
    validate_output_review_browser_evidence,
    validate_output_review_completion_fixture_evidence,
    validate_pricing_poc_browser_evidence,
    validate_pricing_poc_completion_fixture_evidence,
    validate_folder_preview_browser_evidence,
    validate_buzz_polling_browser_evidence,
    validate_source_review_browser_evidence,
    validate_screen_bound_first_pass_evidence,
    validate_xlsx_workbook_chat_evidence,
    validate_live_inference_concurrency_evidence,
    has_per_share_unit_label,
)
from scripts.query_deal_room import query as query_deal_room
from core.deal_room_chat import (
    answer_deal_room_question,
    DealRoomChatResult,
    DealRoomChatError,
    retrieve_deal_room_evidence,
    validate_deal_room_answer,
)
from core.arize_evals import ArizeObservabilityTracer, ArizeTraceRecord
from core.buzz_bridge import BuzzBridge
from core.first_pass import (
    FirstPassError,
    FirstPassResult,
    evidence_claim_issues,
    retrieve_first_pass_evidence,
    restore_signed_first_pass,
)


def _write_test_xlsx(
    path: str, *, extreme_coordinate: bool = False, external_relationship: bool = False
) -> None:
    coordinate = "XFE1" if extreme_coordinate else "A1"
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheets><sheet name="LBO Model" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""
    target_mode = ' TargetMode="External"' if external_relationship else ""
    target = "https://example.invalid/sheet.xml" if external_relationship else "worksheets/sheet1.xml"
    relationships = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="{target}"{target_mode}/>
</Relationships>"""
    shared_strings = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="3" uniqueCount="3">
 <si><t>Metric</t></si><si><t>Base Case</t></si><si><t>Revenue</t></si>
</sst>"""
    worksheet = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
 <row r="1"><c r="{coordinate}" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
 <row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>100</v></c></row>
 <row r="3"><c r="A3" t="inlineStr"><is><t>Debt / EBITDA</t></is></c><c r="B3" s="1"><f>B2/20</f><v>5</v></c></row>
 <row r="4"><c r="A4" t="inlineStr"><is><t>Unsaved formula</t></is></c><c r="B4"><f>B2*2</f></c></row>
 <row r="5"><c r="A5" t="inlineStr"><is><t>Margin</t></is></c><c r="B5" s="2"><v>0.25</v></c></row>
 <row r="6"><c r="A6" t="inlineStr"><is><t>Closing date serial</t></is></c><c r="B6" s="3"><v>45292</v></c></row>
</sheetData></worksheet>"""
    styles = r"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
 <numFmts count="2"><numFmt numFmtId="166" formatCode="0.0%"/><numFmt numFmtId="168" formatCode="0.0\x"/></numFmts>
 <cellXfs count="4"><xf numFmtId="0"/><xf numFmtId="168" applyNumberFormat="1"/><xf numFmtId="166" applyNumberFormat="1"/><xf numFmtId="14" applyNumberFormat="1"/></cellXfs>
</styleSheet>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="xml" ContentType="application/xml"/>
</Types>"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/sharedStrings.xml", shared_strings)
        archive.writestr("xl/styles.xml", styles)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)


def _write_scanned_pdf(folder: Path, text: str) -> Path:
    """Create an image-only PDF with the host's measured macOS tools."""
    source = folder / "source.txt"
    text_pdf = folder / "text.pdf"
    page_prefix = folder / "page"
    scanned_pdf = folder / "scan.pdf"
    source.write_text(text, encoding="utf-8")
    with text_pdf.open("wb") as output:
        converted = subprocess.run(
            ["cupsfilter", "-m", "application/pdf", str(source)],
            stdout=output, stderr=subprocess.PIPE, timeout=30, check=False,
        )
    if converted.returncode != 0:
        raise RuntimeError(converted.stderr.decode("utf-8", errors="replace"))
    subprocess.run(
        [
            "pdftoppm", "-f", "1", "-l", "1", "-singlefile", "-png", "-r", "200",
            str(text_pdf), str(page_prefix),
        ],
        capture_output=True, timeout=30, check=True,
    )
    subprocess.run(
        ["sips", "-s", "format", "pdf", str(page_prefix.with_suffix(".png")),
         "--out", str(scanned_pdf)],
        capture_output=True, timeout=30, check=True,
    )
    embedded = subprocess.run(
        ["pdftotext", str(scanned_pdf), "-"],
        capture_output=True, timeout=30, check=True,
    ).stdout
    if embedded.strip():
        raise RuntimeError("scanned PDF fixture unexpectedly contains embedded text")
    return scanned_pdf


class _ProviderHandler(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.__class__.requests.append({"path": self.path, "body": body})
        response = json.dumps({
            "id": "test-request",
            "model": "bonsai-test-model",
            "choices": [{"message": {"content": "```python\nprint('AI PROVIDER RESULT')\n```"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *_):
        pass


class RealityGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_server = None
        try:
            cls.app_server = ThreadingHTTPServer(("127.0.0.1", 0), VaultHTTPRequestHandler)
            cls.app_thread = threading.Thread(target=cls.app_server.serve_forever, daemon=True)
            cls.app_thread.start()
        except PermissionError:
            cls.app_server = None

    @classmethod
    def tearDownClass(cls):
        if cls.app_server:
            cls.app_server.shutdown()
            cls.app_server.server_close()

    def app_request(self, path, payload=None, raw=None):
        url = f"http://127.0.0.1:{self.app_server.server_port}{path}"
        data = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
        request = urllib.request.Request(url, data=data,
                                         headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            try:
                return error.code, json.loads(error.read())
            finally:
                error.close()

    def test_browser_implicit_favicon_request_is_not_an_error(self):
        if not self.app_server:
            self.skipTest("loopback listener unavailable")
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.app_server.server_port, timeout=5
        )
        try:
            connection.request("GET", "/favicon.ico")
            response = connection.getresponse()
            self.assertEqual(response.status, 204)
            self.assertEqual(response.read(), b"")
        finally:
            connection.close()

    def test_pricing_poc_endpoint_preserves_unmeasured_buyer_boundary(self):
        if not self.app_server:
            self.skipTest("loopback listener unavailable")
        status, result = self.app_request("/api/benchmark/pricing-poc")
        self.assertEqual(status, 200)
        self.assertEqual(result["evidence_state"], "not_recorded")
        self.assertFalse(result["pricing_poc_passed"])
        self.assertEqual(result["deal_count"], 0)
        self.assertEqual(len(result["requirements"]), 10)
        self.assertIn("do not count", result["public_demo_boundary"])
        self.assertEqual(
            result["record_expected_at"], "evidence/first-pass-pricing-poc.json"
        )

    def test_pricing_poc_unsigned_record_builder_guards_required_evidence(self):
        completed = subprocess.run(
            ["node", "scripts/verify_pricing_poc_record.mjs"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertTrue(result["passed"])
        self.assertEqual(result["assertions"], 8)

    def test_orphaned_signed_review_canvas_fails_digest_closed(self):
        if not self.app_server:
            self.skipTest("loopback listener unavailable")

        class OrphanReviewCanvasBuzz:
            def room(self, _room_id):
                return {"channel_id": "orphan-review-channel"}

            def verified_canvas(self, _channel_id):
                return {
                    "markdown": (
                        "# Project Titan\n\n## Local operator review\n\n"
                        "Decision: ADVANCE\n\n## Reviewed first pass\n\nOrphaned content"
                    ),
                    "event_id": "c" * 64,
                    "signature_verification": {
                        "state": "verified",
                        "scheme": "nip01_event_id_plus_bip340",
                    },
                }

            def verified_messages(self, _channel_id):
                return []

            def status(self):
                return {"agent_pubkey": "a" * 64, "operator_pubkey": "d" * 64}

        with mock.patch.object(
            server_module, "global_buzz", OrphanReviewCanvasBuzz()
        ):
            status, result = self.app_request(
                "/api/workspace/digest?room=project_titan_lbo"
            )
        self.assertEqual(status, 409)
        self.assertEqual(result["error"], "uncommitted_review_canvas")
        self.assertEqual(result["canvas_event_id"], "c" * 64)
        self.assertIn("not presented", result["detail"])

    def test_operator_preflight_evidence_rejects_loaded_model_or_scope_drift(self):
        canonical = validate_operator_preflight_evidence()
        self.assertTrue(canonical["passed"], canonical)
        self.assertFalse(canonical["deployment_metadata_complete"])
        record = json.loads(
            (Path("evidence") / "operator-preflight-current.json").read_text(encoding="utf-8")
        )
        model = next(
            item for item in record["checks"] if item["name"] == "bonsai_model_loaded"
        )
        model["observed"]["loaded"] = False
        record["measurement_state"] = "clean_machine_reproduced"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tampered-preflight.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            tampered = validate_operator_preflight_evidence(path)
        self.assertFalse(tampered["passed"])
        self.assertTrue(any("reproduction scope" in item for item in tampered["errors"]))
        self.assertTrue(any("loaded model" in item for item in tampered["errors"]))

    def test_workspace_html_is_fresh_and_names_the_customer_demo_contract(self):
        if not self.app_server:
            self.skipTest("loopback listener unavailable")
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.app_server.server_port, timeout=5
        )
        try:
            connection.request("GET", "/rooms/project_titan_lbo/first-pass")
            response = connection.getresponse()
            body = response.read().decode()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            self.assertIn("What should the team decide?", body)
            self.assertIn("Review deal room", body)
            self.assertIn("app.js?v=hybrid-eval-lab-v1", body)
            self.assertIn('id="contract-cloud"', body)
            self.assertIn('id="room-provenance">Source provenance pending</span>', body)
            self.assertIn('id="truth-source-provenance">Checking</dd>', body)
            self.assertIn(">Overview</button>", body)
            self.assertIn(">Sources</button>", body)
            self.assertIn(">Activity</button>", body)
            self.assertIn(">Evaluation</button>", body)
            self.assertIn(">Decision notes</button>", body)
            self.assertIn(">Technical details</button>", body)
            self.assertNotIn('class="more-menu"', body)
            self.assertNotIn(">Benchmark</button>", body)
            self.assertNotIn(">Pricing</button>", body)
            self.assertIn('id="digest-title">Decision notes</h2>', body)
        finally:
            connection.close()

    def test_candidate_source_review_http_is_roster_gated_and_unregistered(self):
        if not self.app_server:
            self.skipTest("loopback listener unavailable")
        status, queue = self.app_request("/api/benchmark/source-review")
        self.assertEqual(status, 200)
        self.assertEqual(queue["draft_count"], 319)
        self.assertEqual(queue["candidate_deal_count"], 29)
        self.assertFalse(queue["reviewer_roster_ready"])
        self.assertFalse(queue["reviewer_authentication_ready"])
        self.assertFalse(queue["submission_ready"])
        self.assertEqual(queue["review_state"]["submission_count"], 0)
        self.assertEqual(queue["review_state"]["benchmark_cases_registered"], 0)
        self.assertEqual(queue["pipeline"]["source_review"]["eligible_count"], 0)
        self.assertEqual(queue["pipeline"]["registration"]["candidate_cases_registered"], 0)
        self.assertFalse(queue["pipeline"]["release"]["accuracy_release_ready"])
        draft_id = queue["drafts"][0]["draft_id"]
        status, detail = self.app_request(
            f"/api/benchmark/source-review?draft={draft_id}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(detail["draft"]["draft_id"], draft_id)
        status, rejected = self.app_request(
            "/api/benchmark/source-review",
            {
                "draft_id": draft_id,
                "reviewer_id": "self-asserted-reviewer",
                "source_context_checked": True,
                "decision": "approve",
                "final_question": detail["draft"]["provisional_question"],
                "answer_policy": "supported",
                "supporting_citations": [],
                "confusable_citations": [],
                "expected_claims": [],
                "absence_basis": "",
                "rationale": "Self-asserted qualification must not be accepted.",
            },
        )
        self.assertEqual(status, 403)
        self.assertEqual(rejected["error"], "reviewer_not_rostered")

    def test_benchmark_pipeline_http_reports_each_unpassed_gate(self):
        if not self.app_server:
            self.skipTest("loopback listener unavailable")
        status, pipeline = self.app_request("/api/benchmark/pipeline")
        self.assertEqual(status, 200)
        self.assertEqual(pipeline["source_review"]["eligible_count"], 0)
        self.assertEqual(pipeline["source_review"]["pending_count"], 319)
        self.assertEqual(pipeline["case_approval"]["recorded_approval_count"], 0)
        self.assertEqual(pipeline["case_approval"]["unregistered_approval_count"], 0)
        self.assertEqual(pipeline["case_approval"]["registered_approval_count"], 0)
        self.assertEqual(pipeline["registration"]["candidate_cases_registered"], 0)
        self.assertEqual(pipeline["registration"]["total_cases_registered"], 5)
        self.assertTrue(pipeline["calibration"]["evaluator_available"])
        self.assertEqual(pipeline["calibration"]["registered_case_count"], 0)
        self.assertEqual(pipeline["calibration"]["required_case_count"], 20)
        self.assertEqual(pipeline["calibration"]["evidence_state"], "not_recorded")
        self.assertFalse(pipeline["calibration"]["calibration_passed"])
        self.assertFalse(pipeline["release"]["accuracy_release_ready"])
        self.assertEqual(pipeline["release"]["target_cases"], 120)
        self.assertFalse(pipeline["governance"]["configured"])
        self.assertTrue(pipeline["governance"]["valid"])
        self.assertEqual(pipeline["governance"]["receipt_count"], 0)
        self.assertEqual(pipeline["governance"]["required_receipt_count"], 12)
        self.assertEqual(
            pipeline["governance"]["signature_verification"],
            "nip01_event_id_plus_bip340_material_bound",
        )
        self.assertEqual(len(pipeline["governance"]["roles"]), 4)
        self.assertEqual(len(pipeline["governance"]["scopes"]), 3)
        self.assertTrue(all(
            scope["verified_role_count"] == 0
            and scope["required_role_count"] == 4
            and len(scope["roles"]) == 4
            and all(role["approved"] is False for role in scope["roles"])
            and len(scope["material_sha256"]) == 64
            for scope in pipeline["governance"]["scopes"]
        ))
        self.assertEqual(
            pipeline["buzz_review_channel"]["signature_verification"],
            "nip01_event_id_plus_bip340",
        )
        audit = pipeline["benchmark_decisions"]
        self.assertEqual(audit["decision_count"], 10)
        self.assertEqual(audit["release_satisfied_count"], 0)
        self.assertFalse(audit["all_release_satisfied"])
        self.assertEqual(
            [item["number"] for item in audit["decisions"]],
            list(range(1, 11)),
        )
        by_key = {item["key"]: item for item in audit["decisions"]}
        self.assertEqual(
            by_key["job_under_certification"]["state"],
            "awaiting_owner_approval",
        )
        self.assertEqual(
            by_key["dataset_size_and_coverage"]["evidence"],
            "5 of 120 cases across 3 of 30 deals.",
        )
        self.assertEqual(
            by_key["private_data_and_evaluation_records"]["state"],
            "private_pilot_not_recorded",
        )
        self.assertEqual(
            by_key["release_thresholds"]["state"],
            "thresholds_unapproved",
        )
        self.assertEqual(
            by_key["release_thresholds"]["evidence"],
            "Signed threshold approvals: False. Accuracy release: False.",
        )

    def test_oracle_diagnostic_http_exposes_failures_without_accuracy_claim(self):
        if not self.app_server:
            self.skipTest("loopback listener unavailable")
        status, diagnostic = self.app_request("/api/benchmark/oracle-diagnostic")
        self.assertEqual(status, 200)
        self.assertEqual(
            diagnostic["verification_state"],
            "validated_saved_engineering_diagnostic",
        )
        self.assertEqual(diagnostic["completed_case_count"], 5)
        self.assertEqual(diagnostic["oracle_probe_pass_count"], 2)
        self.assertEqual(diagnostic["semantic_accuracy_state"], "unverified")
        self.assertFalse(diagnostic["accuracy_release_passed"])
        by_id = {item["case_id"]: item for item in diagnostic["cases"]}
        self.assertEqual(
            by_id["citrix_financing_mix"]["localization"],
            "oracle_context_regressed_deterministic_contract",
        )
        self.assertEqual(
            by_id["cma_competition_conclusion"]["localization"],
            "deterministic_failure_persists_with_registered_oracle_context",
        )
        absence = by_id["citrix_entry_leverage_absent"]
        self.assertTrue(absence["eligible"])
        self.assertEqual(
            absence["localization"],
            "deterministic_failure_persists_with_registered_oracle_context",
        )
        self.assertTrue(absence["absence_audit"]["passed"])
        self.assertEqual(absence["absence_audit"]["scope"], "complete_registered_deal_folder")
        self.assertEqual(absence["absence_audit"]["source_file_count"], 2)
        self.assertEqual(absence["absence_audit"]["parsed_node_count"], 2401)
        self.assertEqual(absence["absence_audit"]["registered_pattern_count"], 3)
        self.assertEqual(absence["absence_audit"]["direct_disclosure_hit_count"], 0)
        self.assertTrue(absence["absence_phrase_policy_passed"])
        self.assertTrue(absence["missing_citations"])
        self.assertIn("does not prove semantic accuracy", diagnostic["meaning"])

    def test_output_review_http_is_blinded_roster_gated_and_unsigned(self):
        if not self.app_server:
            self.skipTest("loopback listener unavailable")
        status, packet = self.app_request("/api/benchmark/output-review")
        self.assertEqual(status, 200)
        self.assertTrue(packet["blinded_to_model"])
        self.assertFalse(packet["model_identity_included"])
        self.assertEqual(packet["case_count"], 5)
        self.assertEqual(packet["qualified_reviewers"], [])
        self.assertFalse(packet["reviewer_roster_ready"])
        self.assertFalse(packet["browser_reviewer_authentication_ready"])
        self.assertFalse(packet["unsigned_export_ready"])
        self.assertIsNone(packet["case"])
        self.assertFalse(packet["pipeline"]["calibration"]["calibration_passed"])
        case_id = packet["cases"][0]["case_id"]
        status, detail = self.app_request(
            f"/api/benchmark/output-review?case={case_id}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(detail["case"]["case_id"], case_id)
        self.assertEqual(len(detail["case"]["response_sha256"]), 64)
        self.assertEqual(
            set(detail["case"]["dimensions_to_review"]),
            {
                "primary_decision_intent",
                "evidence_support",
                "component_completeness",
                "calibrated_uncertainty",
                "human_usefulness",
            },
        )
        status, missing = self.app_request(
            "/api/benchmark/output-review?case=missing-case"
        )
        self.assertEqual(status, 404)
        self.assertEqual(missing["error"], "unknown_output_review_case")

    def test_output_review_http_exposes_only_active_qualified_roster_entries(self):
        if not self.app_server:
            self.skipTest("loopback listener unavailable")
        roster = {
            "version": "1.0.0",
            "status": "domain_owner_managed",
            "reviewers": [
                {
                    "reviewer_id": f"reviewer.{index}",
                    "display_name": f"Reviewer {index}",
                    "role": "qualified_deal_output_reviewer",
                    "qualification": "M&A output review experience.",
                    "buzz_pubkey": character * 64,
                    "approved_by": "domain.owner",
                    "approved_at": "2026-08-15T04:00:00+00:00",
                    "active": True,
                }
                for index, character in (("one", "b"), ("two", "c"))
            ] + [{
                "reviewer_id": "principal.one",
                "display_name": "Principal One",
                "role": "principal_output_reviewer",
                "qualification": "M&A principal review experience.",
                "buzz_pubkey": "d" * 64,
                "approved_by": "domain.owner",
                "approved_at": "2026-08-15T04:00:00+00:00",
                "active": True,
            }],
        }
        with mock.patch.object(
            server_module, "load_output_reviewer_roster", return_value=roster,
        ):
            status, packet = self.app_request("/api/benchmark/output-review")
        self.assertEqual(status, 200)
        self.assertEqual(
            [item["reviewer_id"] for item in packet["qualified_reviewers"]],
            ["reviewer.one", "reviewer.two"],
        )
        self.assertEqual(packet["qualified_reviewers"][0]["buzz_pubkey"], "b" * 64)
        self.assertTrue(packet["reviewer_roster_ready"])
        self.assertTrue(packet["unsigned_export_ready"])
        self.assertFalse(packet["browser_reviewer_authentication_ready"])

    def test_case_authoring_http_is_source_review_and_owner_gated(self):
        if not self.app_server:
            self.skipTest("loopback listener unavailable")
        status, queue = self.app_request("/api/benchmark/case-authoring")
        self.assertEqual(status, 200)
        self.assertEqual(queue["eligible_draft_count"], 0)
        self.assertEqual(queue["eligible_drafts"], [])
        self.assertEqual(queue["domain_case_owners"], [])
        self.assertFalse(queue["owner_roster_ready"])
        self.assertFalse(queue["browser_owner_authentication_ready"])
        self.assertFalse(queue["unsigned_export_ready"])
        self.assertIsNone(queue["authoring_material"])
        draft_id = queue["drafts"][0]["draft_id"]
        status, blocked = self.app_request(
            f"/api/benchmark/case-authoring?draft={draft_id}"
        )
        self.assertEqual(status, 409)
        self.assertEqual(blocked["error"], "draft_not_eligible_for_case_authoring")
        self.assertEqual(blocked["status"], "blocked_by_source_review")

    def test_case_authoring_page_keeps_signing_and_registration_separate(self):
        html = Path("web/case-authoring.html").read_text(encoding="utf-8")
        javascript = Path("web/case-authoring.mjs").read_text(encoding="utf-8")
        self.assertIn('id="case-authoring-form"', html)
        self.assertIn('id="export-case-approval"', html)
        self.assertNotIn(" checked", html)
        self.assertIn("/api/benchmark/case-authoring", javascript)
        self.assertIn("buildUnsignedCaseApproval", javascript)
        self.assertIn("Nothing was signed, recorded, or registered", javascript)
        self.assertNotIn('method:"POST"', javascript.replace(" ", ""))

    def test_candidate_source_review_page_has_no_preselected_decision(self):
        html = Path("web/source-review.html").read_text(encoding="utf-8")
        javascript = Path("web/source-review.mjs").read_text(encoding="utf-8")
        self.assertNotIn(" checked", html)
        self.assertIn('name="source-decision"', html)
        self.assertIn('name="answer-policy"', html)
        self.assertIn('id="pipeline-title"', html)
        self.assertIn("renderPipeline(packet.pipeline)", javascript)
        self.assertIn("accuracy_release_ready", javascript)
        self.assertIn("no stage promotes itself", javascript)
        self.assertIn("Download unsigned review", html)
        self.assertIn("buildUnsignedReview", javascript)
        self.assertIn("Nothing was submitted or promoted", javascript)
        self.assertNotIn('method:"POST"', javascript.replace(" ", ""))
        self.assertIn("/api/benchmark/source-review/context", javascript)
        self.assertIn("benchmark case", html.lower())
        self.assertIn('id="diagnostic-title"', html)
        self.assertIn("Accuracy unverified", html)
        self.assertIn("/api/benchmark/oracle-diagnostic", javascript)
        self.assertIn("renderDiagnostic", javascript)
        self.assertIn('id="benchmark-decisions-title"', html)
        self.assertIn('id="benchmark-decisions-list"', html)
        self.assertIn("renderBenchmarkDecisions(packet.pipeline.benchmark_decisions)", javascript)
        self.assertIn("release_satisfied_count", javascript)

    def test_browser_evidence_is_trace_and_screenshot_bound(self):
        evidence = validate_browser_evidence()
        self.assertTrue(evidence["passed"], evidence["errors"])
        self.assertEqual(evidence["assertion_count"], 20)
        original = json.loads(Path("evidence/browser-first-pass-v7.json").read_text())
        original["deployment_record_sha256"] = "0" * 64
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(original, handle)
            handle.flush()
            tampered = validate_browser_evidence(Path(handle.name))
        self.assertFalse(tampered["passed"])
        self.assertTrue(any("deployment card" in error for error in tampered["errors"]))

    def test_operator_review_restart_evidence_rejects_scope_or_identity_drift(self):
        evidence_path = Path("evidence/operator-review-restart-anaplan-v1.json")
        self.assertTrue(validate_operator_review_restart_evidence(evidence_path)["passed"])
        original = json.loads(evidence_path.read_text(encoding="utf-8"))
        mutations = {
            "domain scope": lambda record: record["review"].update(
                benchmark_domain_review=True,
            ),
            "event identity": lambda record: record["review"].update(
                review_event_id="0" * 64,
            ),
            "restart order": lambda record: record.update(
                server_process_started_at=record["review_event_created_at"],
            ),
            "source identity": lambda record: record["source_files"][0].update(
                sha256="0" * 64,
            ),
            "artifact relabeling": lambda record: record.update(
                review_subject="first_pass_brief",
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                changed = json.loads(json.dumps(original))
                mutate(changed)
                path = Path(folder) / "review.json"
                path.write_text(json.dumps(changed), encoding="utf-8")
                self.assertFalse(validate_operator_review_restart_evidence(path)["passed"])

        with tempfile.TemporaryDirectory() as folder:
            record = json.loads(
                (Path("evidence") / "browser-first-pass-v7.json").read_text(encoding="utf-8")
            )
            record["artifact"]["trace_id"] = "trc_unrelated"
            tampered = Path(folder) / "browser.json"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            rejected = validate_browser_evidence(tampered)
        self.assertFalse(rejected["passed"])
        self.assertIn(
                "browser trace_id is not bound to the active screen-bound Titan artifact",
            rejected["errors"],
        )
        with tempfile.TemporaryDirectory() as folder:
            record = json.loads(
                Path("evidence/browser-first-pass-v7.json").read_text(encoding="utf-8")
            )
            record["observed_runtime_status"]["invoked_in_process"] = not record[
                "observed_runtime_status"
            ]["invoked_in_process"]
            tampered = Path(folder) / "browser-runtime.json"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            rejected = validate_browser_evidence(tampered)
        self.assertFalse(rejected["passed"])
        self.assertTrue(any("browser runtime" in error for error in rejected["errors"]))
        with tempfile.TemporaryDirectory() as folder:
            record = json.loads(
                Path("evidence/browser-first-pass-v7.json").read_text(encoding="utf-8")
            )
            record["observed_canvas_verification"]["event_id"] = "missing"
            tampered = Path(folder) / "browser-canvas.json"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            rejected = validate_browser_evidence(tampered)
        self.assertFalse(rejected["passed"])
        self.assertIn(
            "browser canvas has no verified event identity",
            rejected["errors"],
        )

    def test_source_review_browser_evidence_is_pipeline_and_screenshot_bound(self):
        evidence = validate_source_review_browser_evidence()
        self.assertTrue(evidence["passed"], evidence["errors"])
        self.assertEqual(evidence["assertion_count"], 29)
        self.assertFalse(evidence["accuracy_release_passed"])

        with tempfile.TemporaryDirectory() as folder:
            record = json.loads(
                Path("evidence/browser-source-review-v1.json").read_text(encoding="utf-8")
            )
            record["observed_pipeline"]["registration"]["candidate_cases_registered"] = 1
            tampered = Path(folder) / "browser-source-review.json"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            rejected = validate_source_review_browser_evidence(tampered)
        self.assertFalse(rejected["passed"])
        self.assertIn(
            "source-review browser registration.candidate_cases_registered differs from current benchmark state",
            rejected["errors"],
        )

        with tempfile.TemporaryDirectory() as folder:
            record = json.loads(
                Path("evidence/browser-source-review-v1.json").read_text(encoding="utf-8")
            )
            record["observed_pipeline"]["governance"]["receipt_count"] = 12
            tampered = Path(folder) / "browser-source-review-governance.json"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            rejected = validate_source_review_browser_evidence(tampered)
        self.assertFalse(rejected["passed"])
        self.assertIn(
            "source-review browser governance matrix differs from current benchmark state",
            rejected["errors"],
        )

        with tempfile.TemporaryDirectory() as folder:
            record = json.loads(
                Path("evidence/browser-source-review-v1.json").read_text(encoding="utf-8")
            )
            record["observed_pipeline"]["benchmark_decisions"]["decisions"][0][
                "release_satisfied"
            ] = True
            tampered = Path(folder) / "browser-source-review-decisions.json"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            rejected = validate_source_review_browser_evidence(tampered)
        self.assertFalse(rejected["passed"])
        self.assertIn(
            "source-review browser ten benchmark decisions differ from current benchmark state",
            rejected["errors"],
        )

    def test_case_authoring_browser_evidence_is_state_and_screenshot_bound(self):
        evidence = validate_case_authoring_browser_evidence()
        self.assertTrue(evidence["passed"], evidence["errors"])
        self.assertEqual(evidence["assertion_count"], 7)
        self.assertFalse(evidence["accuracy_release_passed"])

        with tempfile.TemporaryDirectory() as folder:
            record = json.loads(
                Path("evidence/browser-case-authoring-v1.json").read_text(
                    encoding="utf-8"
                )
            )
            record["observed_state"]["eligible_draft_count"] = 1
            tampered = Path(folder) / "browser-case-authoring.json"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            rejected = validate_case_authoring_browser_evidence(tampered)
        self.assertFalse(rejected["passed"])
        self.assertIn(
            "case-authoring browser eligible_draft_count differs from current benchmark state",
            rejected["errors"],
        )

    def test_output_review_browser_evidence_is_blinded_and_screenshot_bound(self):
        evidence = validate_output_review_browser_evidence()
        self.assertTrue(evidence["passed"], evidence["errors"])
        self.assertEqual(evidence["assertion_count"], 12)
        self.assertTrue(evidence["blinded_to_model"])
        self.assertFalse(evidence["calibration_passed"])

        with tempfile.TemporaryDirectory() as folder:
            record = json.loads(
                Path("evidence/browser-output-review-v1.json").read_text(
                    encoding="utf-8"
                )
            )
            record["packet"]["model_identity_included"] = True
            tampered = Path(folder) / "browser-output-review.json"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            rejected = validate_output_review_browser_evidence(tampered)
        self.assertFalse(rejected["passed"])
        self.assertIn(
            "output-review browser packet.model_identity_included differs from current state",
            rejected["errors"],
        )

    def test_output_review_completion_fixture_is_schema_packet_and_screenshot_bound(self):
        evidence = validate_output_review_completion_fixture_evidence()
        self.assertTrue(evidence["passed"], evidence["errors"])
        self.assertEqual(evidence["assertion_count"], 11)
        self.assertEqual(evidence["case_count"], 5)
        self.assertTrue(evidence["synthetic_reviewer_fixture"])
        self.assertFalse(evidence["human_review_performed"])
        self.assertFalse(evidence["review_gate_complete"])

        with tempfile.TemporaryDirectory() as folder:
            record = json.loads(
                Path("evidence/browser-output-review-completion-fixture-v1.json").read_text(
                    encoding="utf-8"
                )
            )
            record["human_review_performed"] = True
            tampered = Path(folder) / "browser-output-review-completion.json"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            rejected = validate_output_review_completion_fixture_evidence(tampered)
        self.assertFalse(rejected["passed"])
        self.assertIn(
            "output-review completion fixture has unsafe human_review_performed state",
            rejected["errors"],
        )

    def test_pricing_poc_browser_evidence_is_empty_state_and_screenshot_bound(self):
        evidence = validate_pricing_poc_browser_evidence()
        self.assertTrue(evidence["passed"], evidence["errors"])
        self.assertEqual(evidence["assertion_count"], 15)
        self.assertEqual(evidence["evidence_state"], "not_recorded")
        self.assertFalse(evidence["pricing_poc_passed"])

        with tempfile.TemporaryDirectory() as folder:
            record = json.loads(
                Path("evidence/browser-pricing-poc-v1.json").read_text(encoding="utf-8")
            )
            record["observed_state"]["pricing_poc_passed"] = True
            tampered = Path(folder) / "browser-pricing-poc.json"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            rejected = validate_pricing_poc_browser_evidence(tampered)
        self.assertFalse(rejected["passed"])
        self.assertIn(
            "pricing POC browser pricing_poc_passed differs from current state",
            rejected["errors"],
        )

    def test_folder_preview_browser_evidence_is_hash_and_no_write_bound(self):
        evidence = validate_folder_preview_browser_evidence()
        self.assertTrue(evidence["passed"], evidence["errors"])
        self.assertEqual(evidence["assertion_count"], 6)
        self.assertEqual(evidence["preview_state"], "ready")
        self.assertGreater(evidence["document_count"], 0)
        self.assertFalse(evidence["buzz_write_performed"])
        self.assertFalse(evidence["room_registered"])

        with tempfile.TemporaryDirectory() as folder:
            record = json.loads(
                Path("evidence/browser-folder-preview-v1.json").read_text(encoding="utf-8")
            )
            record["preview"]["buzz_write_performed"] = True
            tampered = Path(folder) / "browser-folder-preview.json"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            rejected = validate_folder_preview_browser_evidence(tampered)
        self.assertFalse(rejected["passed"])
        self.assertIn(
            "folder preview browser evidence claims a Buzz write",
            rejected["errors"],
        )

    def test_buzz_polling_browser_evidence_is_behavioral_and_hash_bound(self):
        evidence = validate_buzz_polling_browser_evidence()
        self.assertTrue(evidence["passed"], evidence["errors"])
        self.assertEqual(evidence["assertion_count"], 7)
        self.assertGreaterEqual(evidence["request_count"], 3)
        self.assertEqual(evidence["max_concurrent_message_requests"], 1)

        with tempfile.TemporaryDirectory() as folder:
            record = json.loads(
                Path("evidence/browser-buzz-polling-v1.json").read_text(encoding="utf-8")
            )
            record["timing"]["max_concurrent_message_requests"] = 2
            tampered = Path(folder) / "browser-buzz-polling.json"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            rejected = validate_buzz_polling_browser_evidence(tampered)
        self.assertFalse(rejected["passed"])
        self.assertIn(
            "Buzz polling browser observed overlapping message requests",
            rejected["errors"],
        )

    def test_pricing_poc_completion_fixture_cannot_become_buyer_evidence(self):
        evidence = validate_pricing_poc_completion_fixture_evidence()
        self.assertTrue(evidence["passed"], evidence["errors"])
        self.assertEqual(evidence["assertion_count"], 11)
        self.assertTrue(evidence["synthetic_buyer_fixture"])
        self.assertFalse(evidence["buyer_evidence_recorded"])
        self.assertFalse(evidence["pricing_poc_passed"])
        with tempfile.TemporaryDirectory() as folder:
            record = json.loads(
                Path("evidence/browser-pricing-poc-completion-fixture-v1.json").read_text(encoding="utf-8")
            )
            record["buyer_evidence_recorded"] = True
            tampered = Path(folder) / "pricing-completion.json"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            rejected = validate_pricing_poc_completion_fixture_evidence(tampered)
        self.assertFalse(rejected["passed"])
        self.assertIn(
            "pricing POC completion fixture has unsafe buyer_evidence_recorded state",
            rejected["errors"],
        )

    def test_real_deal_browser_evidence_is_source_event_and_screenshot_bound(self):
        evidence = validate_real_deal_browser_evidence()
        self.assertTrue(evidence["passed"], evidence["errors"])
        self.assertEqual(evidence["assertion_count"], 24)
        self.assertFalse(evidence["accuracy_release_passed"])

        with tempfile.TemporaryDirectory() as folder:
            record = json.loads(
                Path("evidence/browser-real-deal-zendesk-v1.json").read_text(
                    encoding="utf-8"
                )
            )
            record["observed_source_provenance"]["public_source"] = False
            tampered = Path(folder) / "browser-real-deal-provenance.json"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            rejected = validate_real_deal_browser_evidence(tampered)
        self.assertFalse(rejected["passed"])
        self.assertIn(
            "real-deal browser public provenance is not bound to both acquired filings",
            rejected["errors"],
        )

        with tempfile.TemporaryDirectory() as folder:
            record = json.loads(
                Path("evidence/browser-real-deal-zendesk-v1.json").read_text(
                    encoding="utf-8"
                )
            )
            record["source"]["sha256"] = "0" * 64
            tampered = Path(folder) / "browser-real-deal.json"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            rejected = validate_real_deal_browser_evidence(tampered)
        self.assertFalse(rejected["passed"])
        self.assertIn(
            "browser source sha256 is not bound to acquired SEC evidence",
            rejected["errors"],
        )
        with tempfile.TemporaryDirectory() as folder:
            record = json.loads(
                Path("evidence/browser-real-deal-zendesk-v1.json").read_text(
                    encoding="utf-8"
                )
            )
            original_invoked = record["observed_runtime_status"]["invoked_in_process"]
            record["observed_runtime_status"]["invoked_in_process"] = not original_invoked
            tampered = Path(folder) / "browser-real-deal-runtime.json"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            rejected = validate_real_deal_browser_evidence(tampered)
        self.assertFalse(rejected["passed"])
        self.assertTrue(any(
            "real-deal browser runtime status misclassifies" in error
            for error in rejected["errors"]
        ), rejected["errors"])
        with tempfile.TemporaryDirectory() as folder:
            record = json.loads(
                Path("evidence/browser-real-deal-zendesk-v1.json").read_text(
                    encoding="utf-8"
                )
            )
            record["observed_room_registration"]["restored_before_process"] = False
            tampered = Path(folder) / "browser-real-deal-registry.json"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            rejected = validate_real_deal_browser_evidence(tampered)
        self.assertFalse(rejected["passed"])
        self.assertIn(
            "real-deal browser did not prove room registration predates the server process",
            rejected["errors"],
        )

        with tempfile.TemporaryDirectory() as folder:
            record = json.loads(
                Path("evidence/browser-real-deal-zendesk-v1.json").read_text(
                    encoding="utf-8"
                )
            )
            record["observed_signature_verification"]["state"] = "unverified"
            tampered = Path(folder) / "browser-real-deal-signature.json"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            rejected = validate_real_deal_browser_evidence(tampered)
        self.assertFalse(rejected["passed"])
        self.assertIn(
            "real-deal browser did not verify the answer event signature",
            rejected["errors"],
        )
        with tempfile.TemporaryDirectory() as folder:
            record = json.loads(
                Path("evidence/browser-real-deal-zendesk-v1.json").read_text(
                    encoding="utf-8"
                )
            )
            record["observed_trace"]["metadata"]["answer_event_id"] = "0" * 64
            record["observed_trace"]["evaluations"][1]["passed"] = True
            tampered = Path(folder) / "browser-real-deal-trace.json"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            rejected = validate_real_deal_browser_evidence(tampered)
        self.assertFalse(rejected["passed"])
        self.assertIn(
            "real-deal browser trace is not bound to the answer event",
            rejected["errors"],
        )
        self.assertIn(
            "real-deal browser trace incorrectly claims human accuracy review",
            rejected["errors"],
        )

    def test_titan_debt_browser_evidence_is_source_trace_and_screenshot_bound(self):
        evidence = validate_titan_debt_browser_evidence()
        self.assertTrue(evidence["passed"], evidence["errors"])
        self.assertEqual(evidence["assertion_count"], 20)
        self.assertFalse(evidence["accuracy_release_passed"])

        with tempfile.TemporaryDirectory() as folder:
            record = json.loads(
                Path("evidence/browser-titan-debt-chat-v1.json").read_text(
                    encoding="utf-8"
                )
            )
            record["accepted_trace"]["metadata"]["part_citations"][
                "capital_structure"
            ] = ["[invented.md#node:fake]"]
            tampered = Path(folder) / "browser-titan-debt.json"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            rejected = validate_titan_debt_browser_evidence(tampered)
        self.assertFalse(rejected["passed"])
        self.assertIn(
            "Titan debt accepted trace is not bound to the exact citation",
            rejected["errors"],
        )

    def test_accessibility_browser_evidence_is_room_and_screenshot_bound(self):
        evidence = validate_accessibility_browser_evidence()
        self.assertTrue(evidence["passed"], evidence["errors"])
        self.assertEqual(evidence["assertion_count"], 21)
        self.assertEqual(
            evidence["semantic_state"],
            "accessibility_smoke_pass_not_conformance",
        )
        with tempfile.TemporaryDirectory() as folder:
            record = json.loads(
                Path("evidence/browser-accessibility-customer-demo-v1.json").read_text(
                    encoding="utf-8"
                )
            )
            record["room"] = "wrong-room"
            tampered = Path(folder) / "browser-accessibility.json"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            rejected = validate_accessibility_browser_evidence(tampered)
        self.assertFalse(rejected["passed"])
        self.assertIn(
            "accessibility browser record does not use the customer demo room",
            rejected["errors"],
        )

    def test_cross_browser_evidence_is_engine_event_and_screenshot_bound(self):
        evidence = validate_cross_browser_evidence()
        self.assertTrue(evidence["passed"], evidence["errors"])
        self.assertEqual(evidence["engine_count"], 2)
        self.assertEqual(evidence["assertion_count"], 18)
        self.assertEqual(
            {engine["engine"] for engine in evidence["engines"]},
            {"firefox", "webkit"},
        )
        with tempfile.TemporaryDirectory() as folder:
            record = json.loads(
                Path("evidence/browser-cross-engine-customer-demo-v1.json").read_text(
                    encoding="utf-8"
                )
            )
            record["engines"][0]["screenshot"]["sha256"] = "0" * 64
            tampered = Path(folder) / "browser-cross-engine.json"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            rejected = validate_cross_browser_evidence(tampered)
        self.assertFalse(rejected["passed"])
        self.assertIn(
            "firefox browser screenshot digest does not match",
            rejected["errors"],
        )

    def test_claim_scan_rejects_present_tense_target_architecture(self):
        with tempfile.TemporaryDirectory() as folder:
            claim_file = Path(folder) / "target.md"
            claim_file.write_text(
                "Prism Vault is an enterprise-grade runtime. It operates entirely offline. "
                "WE ADOPT DOCLING for every document."
            )
            violations = scan_claims(runtime_surfaces=[], document_surfaces=[claim_file])
        self.assertEqual(
            {violation["claim"] for violation in violations},
            {
                "Prism Vault is an enterprise-grade",
                "It operates entirely offline",
                "We ADOPT Docling",
            },
        )

    def test_claim_scan_rejects_volatile_current_measurements_in_prose(self):
        with tempfile.TemporaryDirectory() as folder:
            claim_file = Path(folder) / "benchmark-card.md"
            claim_file.write_text(
                "Mean end-to-end latency was 18,833.21 ms per case. "
                "Bionic PID 44898 exited. The copy passed all 282 component tests "
                "and the full 291-test suite."
            )
            violations = scan_claims(runtime_surfaces=[], document_surfaces=[claim_file])
        self.assertEqual(
            {violation["claim"] for violation in violations},
            {
                "inline current-run latency instead of a versioned evidence reference",
                "inline current-run process identity instead of a versioned evidence reference",
                "inline current test count instead of a versioned evidence reference",
            },
        )

    def test_every_csv_cell_is_preserved(self):
        path = "deal_rooms/sample_ma_acquisition/02_Consolidated_Financial_Ledger_2025_2026.csv"
        with open(path, newline="", encoding="utf-8") as handle:
            source = list(csv.reader(handle))
        parsed = DealRoomParser().parse_file(path).extracted_tables[0].to_matrix()
        self.assertEqual(parsed, source)

    def test_xlsx_cells_coordinates_and_formula_boundaries_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = f"{folder}/model.xlsx"
            _write_test_xlsx(path)
            document = DealRoomParser().parse_file(path)

        self.assertEqual(document.file_type, "xlsx")
        self.assertEqual(document.extracted_tables[0].caption, "LBO Model")
        self.assertEqual(document.extracted_tables[0].to_matrix(), [
            ["Metric", "Base Case"],
            ["Revenue", "100"],
            ["Debt / EBITDA", "5.0x"],
            ["Unsaved formula", "[formula not calculated] =B2*2"],
            ["Margin", "25.0%"],
            ["Closing date serial", "45292"],
        ])
        formula_cell = next(
            cell for cell in document.extracted_tables[0].cells
            if cell.metadata["cell_reference"] == "B3"
        )
        self.assertEqual(formula_cell.metadata["source_anchor"], "xlsx:sheet:1:cell:B3")
        self.assertEqual(formula_cell.metadata["formula"], "=B2/20")
        self.assertEqual(formula_cell.metadata["raw_value"], "5")
        self.assertEqual(formula_cell.metadata["display_value"], "5.0x")
        self.assertEqual(formula_cell.metadata["number_format_code"], r"0.0\x")
        self.assertEqual(formula_cell.metadata["calculation_state"], "cached_value_not_recalculated")
        self.assertEqual(document.metadata["formula_cell_count"], 2)
        self.assertEqual(document.metadata["cached_formula_cell_count"], 1)
        self.assertEqual(document.metadata["unevaluated_formula_cell_count"], 1)
        self.assertEqual(document.metadata["formatted_numeric_cell_count"], 2)
        self.assertEqual(document.metadata["unsupported_number_format_cell_count"], 1)
        self.assertFalse(document.metadata["external_relationships_followed"])
        self.assertFalse(document.metadata["macros_executed"])

    def test_xlsx_is_retrievable_with_formula_disclosure(self):
        with tempfile.TemporaryDirectory() as folder:
            _write_test_xlsx(f"{folder}/model.xlsx")
            results = query_deal_room(
                Path(folder), "What is the debt EBITDA value?", limit=3
            )
        self.assertTrue(results)
        self.assertEqual(results[0]["citation"], "[model.xlsx#xlsx:sheet:1]")
        self.assertIn("Debt / EBITDA", results[0]["text"])
        self.assertIn("formulas were not recalculated", results[0]["parser_disclosure"])
        self.assertIn("1 formula cells use cached values", results[0]["parser_disclosure"])
        self.assertIn("1 used unsupported number formats", results[0]["parser_disclosure"])

    def test_image_only_pdf_uses_real_ocr_with_physical_anchor_and_disclosure(self):
        with tempfile.TemporaryDirectory() as folder_name:
            folder = Path(folder_name)
            path = _write_scanned_pdf(
                folder,
                "PROJECT CEDAR\nPurchase price 125 million USD\nRevenue 87 million USD\n",
            )
            document = DealRoomParser().parse_file(str(path))
            results = query_deal_room(folder, "PROJECT CEDAR purchase 125", limit=3)

        page = document.root_node.children[0]
        self.assertEqual(page.metadata["source_anchor"], "pdf:page:1")
        self.assertEqual(page.metadata["text_extraction"], "ocr")
        self.assertIn("PROJECT CEDAR", page.content)
        self.assertIn("125", page.content)
        self.assertTrue(document.metadata["ocr_applied"])
        self.assertEqual(document.metadata["ocr_page_numbers"], [1])
        self.assertEqual(
            document.metadata["ocr_engine"], "apple_vision_vnrecognizetextrequest"
        )
        self.assertFalse(document.metadata["ocr_accuracy_measured"])
        self.assertFalse(document.metadata["ocr_layout_reconstruction"])
        self.assertEqual(results[0]["citation"], "[scan.pdf#pdf:page:1]")
        self.assertIn("OCR text and reading order may be wrong", results[0]["parser_disclosure"])
        self.assertIn("not reconstructed", results[0]["parser_disclosure"])

    def test_image_only_pdf_ocr_can_be_disabled_and_is_page_bounded(self):
        with tempfile.TemporaryDirectory() as folder_name:
            path = _write_scanned_pdf(Path(folder_name), "PROJECT CEDAR\n125 million USD\n")
            with self.assertRaisesRegex(ValueError, "OCR is disabled"):
                DealRoomParser(enable_pdf_ocr=False).parse_file(str(path))
            with mock.patch("core.doc_parser.ocr_pdf_page") as run_ocr:
                with self.assertRaisesRegex(ValueError, "0 page OCR limit"):
                    DealRoomParser(max_ocr_pages=0).parse_file(str(path))
                run_ocr.assert_not_called()

    def test_wrong_ocr_result_is_not_promoted_as_expected_text(self):
        with tempfile.TemporaryDirectory() as folder_name:
            path = _write_scanned_pdf(Path(folder_name), "PROJECT CEDAR\n125 million USD\n")
            wrong = {
                "schemaVersion": 1,
                "engine": "apple_vision_vnrecognizetextrequest",
                "recognitionLevel": "accurate",
                "languageCorrection": True,
                "lines": [{"text": "WRONG VALUE 999", "confidence": 1.0}],
                "text": "WRONG VALUE 999",
                "meanConfidence": 1.0,
            }
            with mock.patch("core.doc_parser.ocr_pdf_page", return_value=wrong):
                document = DealRoomParser().parse_file(str(path))
        text = document.root_node.children[0].content
        self.assertEqual(text, "WRONG VALUE 999")
        self.assertNotIn("PROJECT CEDAR", text)
        self.assertNotIn("125", text)

    def test_xlsx_claim_cannot_hide_non_recalculated_formula_state(self):
        passage = {
            "citation": "[model.xlsx#xlsx:sheet:1]",
            "text": "First-year ROI | 99.97",
            "parser_disclosure": (
                "XLSX values are stored workbook values. Formulas were not recalculated. "
                "1 formula cells use cached values."
            ),
        }
        hidden = validate_deal_room_answer(
            "- **Answer:** First-year ROI is 99.97. [model.xlsx#xlsx:sheet:1]",
            [passage],
            {"answer": [passage["citation"]]},
        )
        disclosed = validate_deal_room_answer(
            "- **Answer:** First-year ROI is 99.97 from a cached formula that was not "
            "recalculated. [model.xlsx#xlsx:sheet:1]",
            [passage],
            {"answer": [passage["citation"]]},
        )
        self.assertIn(
            "XLSX-derived claim does not disclose cached, non-recalculated formula state",
            hidden,
        )
        self.assertEqual(disclosed, [])

        first_pass_hidden = evidence_claim_issues(
            "First-year ROI is 99.97 [model.xlsx#xlsx:sheet:1].", [passage]
        )
        first_pass_disclosed = evidence_claim_issues(
            "First-year ROI is 99.97 from a cached formula that was not recalculated "
            "[model.xlsx#xlsx:sheet:1].",
            [passage],
        )
        self.assertIn(
            "An XLSX-derived claim does not disclose cached, non-recalculated formula state",
            first_pass_hidden,
        )
        self.assertNotIn(
            "An XLSX-derived claim does not disclose cached, non-recalculated formula state",
            first_pass_disclosed,
        )

    def test_xlsx_parser_rejects_out_of_boundary_coordinates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = f"{folder}/too-wide.xlsx"
            _write_test_xlsx(path, extreme_coordinate=True)
            with self.assertRaisesRegex(ValueError, "parser boundary"):
                DealRoomParser().parse_file(path)

    def test_xlsx_parser_rejects_external_workbook_relationships(self):
        with tempfile.TemporaryDirectory() as folder:
            path = f"{folder}/external.xlsx"
            _write_test_xlsx(path, external_relationship=True)
            with self.assertRaisesRegex(ValueError, "external resources"):
                DealRoomParser().parse_file(path)

    def test_workspace_exposes_bounded_text_and_exact_citation_anchor_preview(self):
        data = VaultHTTPRequestHandler._get_deal_room_data(None, "project_titan_lbo")
        self.assertEqual(
            data["source_provenance"]["classification"],
            "synthetic_engineering_fixture",
        )
        self.assertTrue(data["source_provenance"]["synthetic_fixture"])
        self.assertFalse(data["source_provenance"]["accuracy_release_evidence"])
        self.assertFalse(data["source_provenance"]["buyer_evidence"])
        cim = next(
            document for document in data["documents"]
            if document["filename"] == "01_Confidential_Information_Memorandum.md"
        )
        self.assertTrue(cim["preview_text"])
        self.assertLessEqual(len(cim["preview_text"]), 12_000)
        self.assertIn("node:node_para_2", cim["anchors"])
        self.assertIn("CloudScale Networks Inc.", cim["anchors"]["node:node_para_2"])
        self.assertLessEqual(max(map(len, cim["anchors"].values())), 4_000)
        parsed = DealRoomParser().parse_file(
            "deal_rooms/project_titan_lbo/01_Confidential_Information_Memorandum.md"
        )
        node_ids = []

        def collect_ids(node):
            node_ids.append(node.id)
            for child in node.children:
                collect_ids(child)

        collect_ids(parsed.root_node)
        self.assertEqual(len(node_ids), len(set(node_ids)))

        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "proxy.htm").write_text(
                "<p>First passage.</p><p>The financing condition is not required.</p>",
                encoding="utf-8",
            )
            room = {
                "html_room": {
                    "id": "html_room", "name": "HTML room", "type": "Private folder",
                    "description": "Anchor test", "path": folder,
                },
            }
            with mock.patch.object(server_module, "all_deal_rooms", return_value=room):
                html_data = VaultHTTPRequestHandler._get_deal_room_data(None, "html_room")
        anchors = html_data["documents"][0]["anchors"]
        self.assertIn("html:block:00002", anchors)
        self.assertIn("financing condition", anchors["html:block:00002"])
        self.assertNotIn("node:html_block_00002", anchors)

    def test_room_source_provenance_separates_fixture_public_and_local_folders(self):
        fixture = server_module.room_source_provenance(
            DEAL_ROOM_CATALOG["project_titan_lbo"]
        )
        self.assertEqual(fixture["classification"], "synthetic_engineering_fixture")
        self.assertTrue(fixture["synthetic_fixture"])
        fixture_binding = server_module.source_provenance_binding(
            DEAL_ROOM_CATALOG["project_titan_lbo"]
        )
        self.assertEqual(
            fixture_binding["classification"], "synthetic_engineering_fixture"
        )
        self.assertRegex(fixture_binding["binding_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            fixture_binding,
            server_module.source_provenance_binding(
                DEAL_ROOM_CATALOG["project_titan_lbo"]
            ),
        )
        altered_claim = dict(fixture_binding)
        altered_claim["classification"] = "operator_selected_local_folder"
        altered_claim.pop("binding_sha256")
        altered_hash = hashlib.sha256(json.dumps(
            altered_claim, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        self.assertNotEqual(altered_hash, fixture_binding["binding_sha256"])

        path_only_public = server_module.room_source_provenance({
            "id": "local_public",
            "path": str(
                Path(".runtime/public-deal-corpus/example").resolve()
            ),
        })
        self.assertEqual(
            path_only_public["classification"], "public_corpus_integrity_failed"
        )
        self.assertFalse(path_only_public["public_source"])
        self.assertFalse(path_only_public["buyer_evidence"])
        self.assertIn(
            "no_registered_public_sources",
            path_only_public["public_integrity"]["errors"],
        )

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            source = root / "filing.htm"
            source.write_text("registered public filing bytes", encoding="utf-8")
            source_bytes = source.read_bytes()
            registry = {
                source: {
                    "sha256": hashlib.sha256(source_bytes).hexdigest(),
                    "bytes": len(source_bytes),
                    "registry_path": "manifest.json",
                },
            }
            verified = server_module._public_folder_integrity(root, registry)
            self.assertTrue(verified["passed"], verified)
            source.write_text("changed bytes", encoding="utf-8")
            changed = server_module._public_folder_integrity(root, registry)
            self.assertFalse(changed["passed"])
            self.assertTrue(any(
                error.startswith("byte_count_mismatch:")
                or error.startswith("sha256_mismatch:")
                for error in changed["errors"]
            ))
            source.write_bytes(source_bytes)
            (root / "unregistered.txt").write_text("not in manifest", encoding="utf-8")
            extra = server_module._public_folder_integrity(root, registry)
            self.assertFalse(extra["passed"])
            self.assertIn("unregistered_file:unregistered.txt", extra["errors"])

        with tempfile.TemporaryDirectory() as folder:
            local = server_module.room_source_provenance({
                "id": "local_private",
                "path": str(Path(folder).resolve()),
            })
        self.assertEqual(local["classification"], "operator_selected_local_folder")
        self.assertTrue(local["operator_selected"])
        self.assertFalse(local["customer_data_verified"])

    def test_markdown_retrieval_cites_child_provision_with_bounded_section_context(self):
        folder = Path("deal_rooms/project_titan_lbo").resolve()
        request = "reported debt paydown ECF sweep schedule Section 2.02 cash sweep policy"
        results = query_deal_room(folder, request, limit=10)
        provision = next(
            result for result in results
            if result["filename"] == "02_LBO_Debt_Financing_Credit_Agreement.md"
        )
        self.assertEqual(
            provision["citation"],
            "[02_LBO_Debt_Financing_Credit_Agreement.md#node:node_para_3]",
        )
        self.assertIn("Section 2.02", provision["text"])
        self.assertIn("50.0% of ECF", provision["text"])
        self.assertIn("25.0% of ECF", provision["text"])
        self.assertIn("0.0% of ECF", provision["text"])
        self.assertNotIn(
            "[02_LBO_Debt_Financing_Credit_Agreement.md#node:sec_5_4]",
            {result["citation"] for result in results},
        )

        data = VaultHTTPRequestHandler._get_deal_room_data(None, "project_titan_lbo")
        credit = next(
            document for document in data["documents"]
            if document["filename"] == "02_LBO_Debt_Financing_Credit_Agreement.md"
        )
        paragraph = credit["anchors"]["node:node_para_3"]
        self.assertIn("Section 2.02", paragraph)
        self.assertIn("50.0% of ECF", paragraph)
        self.assertLessEqual(len(paragraph), 4_000)
        self.assertIn("node:sec_5_4", credit["anchors"])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "terms.md").write_text(
                "#### Unique Control Heading\n"
                "Unique covenant language " + ("bounded context " * 500),
                encoding="utf-8",
            )
            bounded = query_deal_room(root, "unique covenant language", limit=2)
        self.assertEqual(bounded[0]["citation"], "[terms.md#node:node_para_1]")
        self.assertTrue(bounded[0]["text"].startswith("Unique Control Heading"))
        self.assertLessEqual(len(bounded[0]["text"]), 1_800)

    def test_artifact_inspection_proves_presence_not_invocation(self):
        with tempfile.TemporaryDirectory() as folder:
            artifact = f"{folder}/test.gguf"
            with open(artifact, "wb") as handle:
                handle.write(b"GGUF" + (3).to_bytes(4, "little") + b"test weights")
            digest = hashlib.sha256(
                b"GGUF" + (3).to_bytes(4, "little") + b"test weights"
            ).hexdigest()
            metadata_dir = f"{folder}/.cache/huggingface/download"
            os.makedirs(metadata_dir)
            with open(f"{metadata_dir}/test.gguf.metadata", "w", encoding="utf-8") as handle:
                handle.write(f"revision-123\n{digest}\n")
            report = inspect_model_artifact(artifact)
        self.assertEqual(report["measurement_state"], "artifact_present_not_invoked")
        self.assertEqual(report["format"], "gguf")
        self.assertEqual(report["gguf_version"], 3)
        self.assertEqual(report["source_revision"], "revision-123")
        self.assertTrue(report["sidecar_digest_matches"])

    def test_jagged_csv_and_json_array_roots_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            csv_path = f"{folder}/jagged.csv"
            json_path = f"{folder}/array.json"
            with open(csv_path, "w", encoding="utf-8", newline="") as handle:
                handle.write("a,b\n1,2,3\n")
            with open(json_path, "w", encoding="utf-8") as handle:
                json.dump([{"value": 7}], handle)
            parser = DealRoomParser()
            docs = parser.parse_deal_room_folder(folder)
        csv_doc = next(doc for doc in docs if doc.filename == "jagged.csv")
        self.assertEqual(csv_doc.extracted_tables[0].to_matrix(), [["a", "b", ""], ["1", "2", "3"]])
        json_doc = next(doc for doc in docs if doc.filename == "array.json")
        self.assertEqual(json_doc.root_node.metadata["json_root_type"], "list")
        self.assertIn('"value": 7', json_doc.root_node.children[0].content)

    def test_html_ingestion_has_hash_anchors_tables_and_no_active_content(self):
        with tempfile.TemporaryDirectory() as folder:
            path = f"{folder}/proxy.htm"
            source = (
                "<html><body><script>secret_active_text</script>"
                "<h1>Merger summary</h1><p>Consideration is $104.00 per share.</p>"
                "<table><tr><th>Source</th><th>Amount</th></tr>"
                "<tr><td>Debt</td><td>$15.0 billion</td></tr></table></body></html>"
            )
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(source)
            document = DealRoomParser().parse_file(path)

        self.assertEqual(document.file_type, "html")
        self.assertEqual(
            document.metadata["source_sha256"], hashlib.sha256(source.encode()).hexdigest()
        )
        section = document.root_node.children[0]
        self.assertEqual(section.metadata["source_anchor"], "html:block:00001")
        self.assertEqual(section.children[0].metadata["source_anchor"], "html:block:00002")
        self.assertEqual(document.extracted_tables[0].to_matrix(), [
            ["Source", "Amount"], ["Debt", "$15.0 billion"],
        ])
        parsed_text = json.dumps(document, default=lambda value: value.__dict__)
        self.assertNotIn("secret_active_text", parsed_text)

    def test_deal_room_query_returns_short_anchor_bound_passages(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "proxy.htm"
            path.write_text(
                "<html><body><p>Other text.</p><p>The debt commitment was $15.0 billion.</p></body></html>",
                encoding="utf-8",
            )
            results = query_deal_room(Path(folder), "What was the debt commitment?", limit=2)
        self.assertEqual(results[0]["source_anchor"], "html:block:00002")
        self.assertEqual(results[0]["citation"], "[proxy.htm#html:block:00002]")
        self.assertIn("$15.0 billion", results[0]["text"])
        self.assertLess(len(results[0]["text"]), 1801)

    def test_deal_room_query_can_admit_one_exact_source(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "proxy.htm").write_text(
                "<p>Revenue was $100 million.</p>", encoding="utf-8"
            )
            Path(folder, "financial.htm").write_text(
                "<p>Revenue was $200 million.</p>", encoding="utf-8"
            )
            results = query_deal_room(
                Path(folder),
                "What was revenue?",
                limit=4,
                source_filenames={"financial.htm"},
            )
        self.assertTrue(results)
        self.assertTrue(all(item["filename"] == "financial.htm" for item in results))
        self.assertIn("$200 million", results[0]["text"])

    def test_deal_room_query_excludes_inline_xbrl_header_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "financial.htm").write_text(
                "<div>FALSE us-gaap:Revenue us-gaap:Assets us-gaap:Liabilities "
                "xbrli:shares xbrli:pure revenue</div>"
                "<p>Revenue increased to $200 million for the latest period.</p>",
                encoding="utf-8",
            )
            results = query_deal_room(Path(folder), "What was revenue?", limit=4)
        self.assertTrue(results)
        self.assertTrue(all("us-gaap:" not in item["text"] for item in results))
        self.assertIn("$200 million", results[0]["text"])

    def test_deal_room_chat_rejects_uncited_model_output(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "proxy.htm").write_text(
                "<p>The merger consideration was $104.00 per share.</p>", encoding="utf-8"
            )
            provider = mock.MagicMock()
            provider.configured = True
            provider.complete.return_value = mock.MagicMock(
                content="The merger consideration was $104.00 per share.",
                provider_id="local_bonsai", model="27b@q1_0", latency_ms=10,
                usage={}, raw_metadata={},
            )
            with self.assertRaises(DealRoomChatError):
                answer_deal_room_question(folder, "What was the consideration?", provider)

            provider.complete.return_value.content = (
                "The merger consideration was $104.00 per share "
                "[proxy.htm#html:block:00001]."
            )
            result = answer_deal_room_question(
                folder, "What was the merger consideration?", provider,
            )
        self.assertEqual(result.model, "27b@q1_0")
        self.assertEqual(result.citations, ["[proxy.htm#html:block:00001]"])

    def test_deal_room_chat_expands_multi_part_ma_questions(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "proxy.htm").write_text(
                "<p>Background discussion about the proposed transaction and closing.</p>"
                "<p>Each Share shall be converted into the right to receive $77.50 in cash, "
                "the Merger Consideration.</p>"
                "<p>The obligations to consummate the Merger are conditioned on stockholder "
                "approval and the absence of an injunction.</p>",
                encoding="utf-8",
            )
            passages = retrieve_deal_room_evidence(
                folder,
                "What is the final per-share price and one material closing condition?",
                limit=8,
            )
        text = "\n".join(passage["text"] for passage in passages)
        self.assertIn("$77.50", text)
        self.assertIn("absence of an injunction", text)
        self.assertTrue(all(passage.get("retrieval_query") for passage in passages))

    def test_titan_debt_tranche_question_admits_exact_sources_table(self):
        question = "What are the disclosed debt tranches and amounts for Project Titan?"
        passages = retrieve_deal_room_evidence(
            "deal_rooms/project_titan_lbo", question, limit=8,
        )
        capital_structure = [
            passage for passage in passages
            if "capital_structure" in passage.get("requested_parts", [])
        ]
        self.assertEqual(len(capital_structure), 1)
        self.assertEqual(
            capital_structure[0]["citation"],
            "[01_Confidential_Information_Memorandum.md#node:node_tbl_1]",
        )
        self.assertIn("First Lien Term Loan B", capital_structure[0]["text"])
        self.assertIn("Second Lien Senior Notes", capital_structure[0]["text"])
        self.assertIn("Subordinated Mezzanine Debt", capital_structure[0]["text"])

    def test_citrix_entry_leverage_question_admits_financing_disclosure(self):
        with tempfile.TemporaryDirectory() as folder:
            background = "".join(
                f"<p>Background chronology item {index}.</p>" for index in range(1, 58)
            )
            Path(folder, "02_citrix_financing_supplement.htm").write_text(
                background
                + "<p>The debt commitment had been increased. Preferred equity was "
                "included and common equity would be provided by Elliott.</p>",
                encoding="utf-8",
            )
            passages = retrieve_deal_room_evidence(
                folder,
                "What was the exact entry debt to EBITDA leverage multiple?",
                limit=8,
            )
        entry_leverage = [
            passage for passage in passages
            if "entry_leverage_absence" in passage.get("requested_parts", [])
        ]
        self.assertEqual(len(entry_leverage), 1)
        self.assertEqual(
            entry_leverage[0]["citation"],
            "[02_citrix_financing_supplement.htm#html:block:00058]",
        )

    def test_termination_fee_retrieval_requires_both_requested_fees(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "proxy.htm").write_text(
                "<p>The reverse termination fee is $20.</p>"
                "<p>The company termination fee is $10 and the reverse termination fee is $20.</p>",
                encoding="utf-8",
            )
            passages = retrieve_deal_room_evidence(
                folder,
                "State the company termination fee and the reverse termination fee.",
                limit=8,
            )
        fee_passages = [
            passage for passage in passages
            if "termination_fee" in passage.get("requested_parts", [])
        ]
        self.assertEqual(len(fee_passages), 1)
        self.assertEqual(fee_passages[0]["citation"], "[proxy.htm#html:block:00002]")
        self.assertIn("company termination fee", fee_passages[0]["text"].lower())

    def test_chat_guard_requires_every_disclosed_termination_fee_amount(self):
        citation = "[proxy.htm#html:block:00002]"
        passages = [{
            "citation": citation,
            "text": (
                "The company termination fee is $293,122,500 and the reverse termination "
                "fee is $586,245,000."
            ),
            "parser_disclosure": None,
        }]
        incomplete = f"- Termination fee: $293,122,500 {citation}"
        violations = validate_deal_room_answer(
            incomplete, passages, {"termination_fee": [citation]},
        )
        self.assertIn(
            "requested part termination_fee omits source fee amount(s): $586,245,000",
            violations,
        )
        complete = (
            "- Termination fee: company termination fee $293,122,500 and reverse "
            f"termination fee $586,245,000 {citation}"
        )
        self.assertEqual(
            validate_deal_room_answer(
                complete, passages, {"termination_fee": [citation]},
            ),
            [],
        )

    def test_chat_guard_rejects_valuation_multiple_substitution_for_entry_leverage(self):
        citation = "[02_citrix_financing_supplement.htm#html:block:00058]"
        passages = [{
            "citation": citation,
            "text": (
                "The debt commitment had been increased. Preferred equity and common equity "
                "were included. A selected transaction valuation multiple was 13.0x."
            ),
            "parser_disclosure": None,
        }]
        part_citations = {"entry_leverage_absence": [citation]}
        bad = (
            "- Entry debt-to-EBITDA disclosure: The exact entry debt-to-EBITDA leverage "
            f"multiple was 13.0x {citation}"
        )
        violations = validate_deal_room_answer(bad, passages, part_citations)
        self.assertIn(
            "requested part entry_leverage_absence must refuse the absent exact multiple",
            violations,
        )
        self.assertIn(
            "requested part entry_leverage_absence invents or substitutes a multiple",
            violations,
        )

        good = (
            "- Entry debt-to-EBITDA disclosure: The exact entry debt-to-EBITDA leverage "
            "multiple is not disclosed and cannot be calculated from the cited passage alone "
            f"{citation}"
        )
        self.assertEqual(
            validate_deal_room_answer(good, passages, part_citations),
            [],
        )

    def test_titan_debt_tranche_prompt_requires_undrawn_facilities(self):
        citation = "[01_Confidential_Information_Memorandum.md#node:node_tbl_1]"
        provider = mock.MagicMock()
        provider.configured = True
        provider.complete.return_value = mock.MagicMock(
            content=(
                "- **Debt tranches and amounts:** Revolving Credit Facility "
                "($150M Commitment): $0.0; First Lien Term Loan B: $900.0; "
                "Second Lien Senior Notes: $300.0; Subordinated Mezzanine Debt: "
                f"$240.0 {citation}"
            ),
            provider_id="local_bonsai", model="27b@q1_0", latency_ms=10,
            usage={}, raw_metadata={},
        )
        result = answer_deal_room_question(
            "deal_rooms/project_titan_lbo",
            "What are the disclosed debt tranches and amounts for Project Titan?",
            provider,
        )
        prompt = provider.complete.call_args.args[0][1]["content"]
        self.assertIn("Include undrawn or zero-funded facilities", prompt)
        self.assertIn("PARTS=capital_structure", prompt)
        self.assertEqual(result.requested_parts, ["capital_structure"])
        self.assertEqual(result.inference_attempts, 1)

    def test_chat_guard_does_not_score_citation_identity_as_claim_text(self):
        citation = (
            "[03_Three_Statement_Financial_Model_2024_2028.csv#node:node_csv_table]"
        )
        passages = [{
            "citation": citation,
            "text": "First Lien Term Loan B | $900.0",
            "parser_disclosure": None,
        }]
        response = f"- Debt tranche: First Lien Term Loan B | $900.0 {citation}"
        self.assertEqual(
            validate_deal_room_answer(response, passages, {}),
            [],
        )

    def test_chat_guard_allows_question_vocabulary_but_not_new_material_terms(self):
        citation = "[proxy.htm#html:block:00001]"
        passages = [{
            "citation": citation,
            "text": "The virtual data room was opened on March 12 and diligence concluded March 20.",
            "parser_disclosure": None,
        }]
        question = (
            "When did the virtual data room open, what material did it contain, and when did the "
            "intensive diligence period end?"
        )
        supported = (
            "- The intensive diligence period ended on March 20 and contained source material "
            f"{citation}"
        )
        self.assertEqual(
            validate_deal_room_answer(supported, passages, {}, question=question),
            [],
        )
        invented = supported.replace("source material", "secret cryptocurrency material")
        violations = validate_deal_room_answer(
            invented, passages, {}, question=question,
        )
        self.assertTrue(any("cryptocurrency" in item for item in violations))

    def test_chat_guard_requires_every_disclosed_debt_instrument(self):
        citation = "[cim.md#node:node_tbl_1]"
        passages = [{
            "citation": citation,
            "text": (
                "Sources of Funds | Revolving Credit Facility | $0.0 | "
                "First Lien Term Loan B | $900.0 | Second Lien Senior Notes | $300.0 | "
                "Subordinated Mezzanine Debt | $240.0"
            ),
            "parser_disclosure": None,
        }]
        response = (
            "- Debt tranches and amounts: First Lien Term Loan B $900.0; "
            "Second Lien Senior Notes $300.0; Subordinated Mezzanine Debt $240.0 "
            f"{citation}"
        )
        violations = validate_deal_room_answer(
            response, passages, {"capital_structure": [citation]},
        )
        self.assertIn(
            "requested part capital_structure omits source debt instrument(s): revolving credit",
            violations,
        )

    def test_chat_guard_treats_source_citation_wrapper_as_formatting(self):
        citation = "[cim.md#node:node_tbl_1]"
        passages = [{
            "citation": citation,
            "text": (
                "Sources of Funds | Revolving Credit Facility ($150M Commitment) | $0.0 | "
                "First Lien Term Loan B | $900.0 | Second Lien Senior Notes | $300.0 | "
                "Subordinated Mezzanine Debt | $240.0"
            ),
            "parser_disclosure": None,
        }]
        response = (
            "- Debt tranches and amounts: Revolving Credit Facility ($150M Commitment) $0.0; "
            "First Lien Term Loan B $900.0; Second Lien Senior Notes $300.0; "
            f"Subordinated Mezzanine Debt $240.0 [SOURCE {citation}]"
        )
        self.assertEqual(
            validate_deal_room_answer(
                response, passages, {"capital_structure": [citation]},
            ),
            [],
        )

    def test_deal_room_chat_requires_same_line_evidence_for_every_requested_part(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "proxy.htm").write_text(
                "<p>Each Share shall be converted into the right to receive $77.50 in cash, "
                "the Merger Consideration.</p>"
                "<p>The Company Stockholder Approval shall have been obtained.</p>"
                "<p>The HSR Act waiting period shall have expired and CFIUS Approval shall "
                "have been obtained.</p>"
                "<p>The obligation of Parent to consummate the Merger is not subject to any "
                "financing condition.</p>",
                encoding="utf-8",
            )
            provider = mock.MagicMock()
            provider.configured = True
            first = mock.MagicMock(
                content="- Price: $77.50 [proxy.htm#html:block:00001]",
                provider_id="local_bonsai", model="27b@q1_0", latency_ms=10,
                usage={}, raw_metadata={},
            )
            repaired = mock.MagicMock(
                content=(
                    "- Price: right to receive $77.50 in cash [proxy.htm#html:block:00001]\n"
                    "- Stockholder approval: shall have been obtained "
                    "[proxy.htm#html:block:00002]\n"
                    "- Regulatory approval: HSR Act waiting period shall have expired and "
                    "CFIUS Approval shall have been obtained "
                    "[proxy.htm#html:block:00003]\n"
                    "- Financing condition: obligation to consummate the Merger is not subject "
                    "to any financing condition "
                    "[proxy.htm#html:block:00004]"
                ),
                provider_id="local_bonsai", model="27b@q1_0", latency_ms=12,
                usage={}, raw_metadata={},
            )
            provider.complete.side_effect = [first, repaired]
            result = answer_deal_room_question(
                folder,
                "What is the per-share consideration, including stockholder and regulatory "
                "approvals and any financing condition?",
                provider,
            )
        self.assertEqual(result.inference_attempts, 2)
        self.assertEqual(result.requested_parts, [
            "consideration", "stockholder_approval", "regulatory_approval",
            "financing_condition",
        ])
        self.assertEqual(provider.complete.call_count, 2)

    def test_deal_room_chat_rejects_number_absent_from_cited_source_after_repair(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "proxy.htm").write_text(
                "<p>The Merger Consideration is $77.50 per share.</p>", encoding="utf-8",
            )
            provider = mock.MagicMock()
            provider.configured = True
            provider.complete.return_value = mock.MagicMock(
                content="- Price: $88.00 [proxy.htm#html:block:00001]",
                provider_id="local_bonsai", model="27b@q1_0", latency_ms=10,
                usage={}, raw_metadata={},
            )
            with self.assertRaisesRegex(DealRoomChatError, "88.00") as raised:
                answer_deal_room_question(folder, "What is the per-share consideration?", provider)
        self.assertEqual(provider.complete.call_count, 2)
        self.assertEqual(
            raised.exception.metadata["rejected_response"],
            "- Price: $88.00 [proxy.htm#html:block:00001]",
        )
        self.assertEqual(raised.exception.metadata["inference_attempts"], 2)
        self.assertIn("88.00", raised.exception.metadata["violations"][0])
        self.assertEqual(
            raised.exception.metadata["retrieved_anchors"][0]["citation"],
            "[proxy.htm#html:block:00001]",
        )

    def test_unmatched_folder_does_not_receive_horizon_findings(self):
        report = DealRoomAnalyzer("deal_rooms/project_titan_lbo").run_full_audit()
        self.assertEqual(report.covenant_findings, [])
        self.assertIn("No reviewed covenant audit profile", report.executive_summary)
        self.assertNotIn("NovaTech", report.executive_summary)

    def test_horizon_audit_findings_change_with_source_values(self):
        with tempfile.TemporaryDirectory() as folder:
            shutil.copytree("deal_rooms/sample_ma_acquisition", folder, dirs_exist_ok=True)
            ledger_path = f"{folder}/02_Consolidated_Financial_Ledger_2025_2026.csv"
            with open(ledger_path, newline="", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
            columns = {name: index for index, name in enumerate(rows[0])}
            q2 = next(row for row in rows[1:] if row[0] == "Q2-2026")
            q2[columns["Adjusted_EBITDA_USD_M"]] = "30.0"
            q2[columns["Cash_Interest_Expense_USD_M"]] = "5.0"
            q2[columns["Calculated_Interest_Coverage"]] = "6.00"
            with open(ledger_path, "w", newline="", encoding="utf-8") as handle:
                csv.writer(handle).writerows(rows)
            report = DealRoomAnalyzer(folder).run_full_audit()
        coverage = next(f for f in report.covenant_findings if f.covenant_name == "Minimum Interest Coverage Ratio")
        self.assertEqual(coverage.actual_value, "6.00 : 1.00 (Q2-2026)")
        self.assertEqual(coverage.status, "COMPLIANT")
        self.assertIn("Q2-2026 Coverage: 6.00x", report.sandbox_execution_logs[0])

    def test_arbitrary_folder_reports_unsupported_files(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(f"{folder}/note.md", "w", encoding="utf-8") as handle:
                handle.write("# Private deal\nEBITDA is 10.")
            with open(f"{folder}/scan.pdf", "wb") as handle:
                handle.write(b"%PDF-placeholder")
            with open(f"{folder}/huge.txt", "w", encoding="utf-8") as handle:
                handle.write("x" * 65)
            os.symlink(f"{folder}/note.md", f"{folder}/linked.md")
            parser = DealRoomParser(max_file_bytes=64)
            docs = parser.parse_deal_room_folder(folder)
        self.assertEqual([doc.filename for doc in docs], ["note.md"])
        warnings = {warning["filename"]: warning["error"] for warning in parser.last_warnings}
        self.assertIn("PDF extraction failed", warnings["scan.pdf"])
        self.assertIn("exceeds", warnings["huge.txt"])
        self.assertIn("Symbolic links", warnings["linked.md"])

    def test_subprocess_sandbox_blocks_unknown_import_and_times_out(self):
        sandbox = SubprocessSandbox(timeout_seconds=0.1)
        ok, message, _ = sandbox.execute_script("import pathlib\nprint(pathlib.Path('/etc/passwd').read_text())")
        self.assertFalse(ok)
        self.assertIn("not allowlisted", message)
        ok, message, _ = sandbox.execute_script("while True:\n    pass")
        self.assertFalse(ok)
        self.assertIn("timed out", message)

        for escape in (
            "print(__builtins__['open']('/etc/passwd').read())",
            "import collections\nprint(collections._sys.modules['os'].getcwd())",
            "import math\nprint(math.__loader__)",
        ):
            ok, message, _ = sandbox.execute_script(escape)
            self.assertFalse(ok, escape)
            self.assertIn("Security Violation", message)

        bounded = SubprocessSandbox(timeout_seconds=2, max_output_bytes=4096, max_file_bytes=4096)
        ok, message, _ = bounded.execute_script("for _ in range(10000):\n    print('x' * 100)")
        self.assertFalse(ok)
        self.assertLessEqual(len(message.encode()), 4096)

        ok, message, _ = SubprocessSandbox().execute_script(
            "import math\nimport json\nimport re\n"
            "print(json.dumps({'value': round(math.sqrt(81), 1)}))\n"
            "print(bool(re.fullmatch(r'[0-9.]+', '9.0')))"
        )
        self.assertTrue(ok)
        self.assertIn('"value": 9.0', message)
        self.assertTrue(message.strip().endswith("True"))

    @unittest.skipUnless(sys.platform == "darwin", "macOS sandbox profile only")
    def test_macos_sandbox_profile_confines_writes_and_denies_network(self):
        sandbox_exec = shutil.which("sandbox-exec", path="/usr/bin:/bin")
        self.assertIsNotNone(sandbox_exec)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            writable = root / "run"
            writable.mkdir()
            profile = writable / "profile.sb"
            profile.write_text(SubprocessSandbox.macos_profile(str(writable)), encoding="utf-8")
            outside = root / "outside.txt"

            inside_result = subprocess.run(
                [
                    sandbox_exec,
                    "-f",
                    str(profile),
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    f"open({str(writable / 'inside.txt')!r}, 'w').write('ok')",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(inside_result.returncode, 0, inside_result.stderr)
            self.assertEqual((writable / "inside.txt").read_text(), "ok")

            outside_result = subprocess.run(
                [
                    sandbox_exec,
                    "-f",
                    str(profile),
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    f"open({str(outside)!r}, 'w').write('bad')",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertNotEqual(outside_result.returncode, 0)
            self.assertFalse(outside.exists())
            self.assertIn("Operation not permitted", outside_result.stderr)

            protected_read_result = subprocess.run(
                [
                    sandbox_exec,
                    "-f",
                    str(profile),
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    f"open({str(Path('README.md').resolve())!r}).read()",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertNotEqual(protected_read_result.returncode, 0)
            self.assertIn("Operation not permitted", protected_read_result.stderr)

            network_result = subprocess.run(
                [
                    sandbox_exec,
                    "-f",
                    str(profile),
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    "import socket; socket.socket().bind(('127.0.0.1', 0))",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertNotEqual(network_result.returncode, 0)
            self.assertIn("Operation not permitted", network_result.stderr)

        ok, message, metadata = SubprocessSandbox().execute_script("print(6 * 7)")
        self.assertTrue(ok, message)
        self.assertEqual(message.strip(), "42")
        isolation = metadata["isolation"]
        self.assertEqual(isolation["mode"], "macos_sandbox_exec_profile")
        self.assertTrue(isolation["os_policy_enforced"])
        self.assertEqual(isolation["network_access"], "denied")
        self.assertEqual(isolation["process_forks"], "denied")
        self.assertEqual(isolation["file_writes"], "temporary_run_directory_only")
        denied_roots = isolation["file_read_denied_roots"]
        for fixed_root in ("/Users", "/Volumes", "/Network"):
            self.assertIn(fixed_root, denied_roots)
        current_root = os.path.realpath(os.getcwd())
        self.assertTrue(
            any(os.path.commonpath((current_root, root)) == root for root in denied_roots)
        )

    def test_configured_local_provider_is_actually_invoked_and_traced(self):
        response_body = json.dumps({
            "id": "test-request", "model": "bonsai-test-model",
            "choices": [{"message": {"content": "```python\nprint('AI PROVIDER RESULT')\n```"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
        }).encode()
        fake_response = mock.MagicMock()
        fake_response.read.return_value = response_body
        fake_response.__enter__.return_value = fake_response
        registry = ProviderRegistry()
        registry.local = OpenAICompatibleProvider(
            "local_bonsai", "local", "http://127.0.0.1:19001", "bonsai-test", prompt_suffix="/no_think"
        )
        agent = DealRoomWorkflowAgent("deal_rooms/sample_ma_acquisition", providers=registry)
        with mock.patch("urllib.request.urlopen", return_value=fake_response) as opened:
            result = agent.execute_task("Run sensitivity stress-test modeling EBITDA")
        self.assertEqual(result.execution_mode, "ai_generated_sandboxed_code")
        self.assertEqual(result.provider_id, "local_bonsai")
        self.assertEqual(result.model_name, "bonsai-test-model")
        self.assertIn("AI PROVIDER RESULT", result.code_execution_stdout)
        self.assertIn("framework-attached; not model-authored", result.code_execution_stdout)
        self.assertIn("Deal identifier supplied: NovaTech", result.code_execution_stdout)
        self.assertIn("01_Senior_Credit_Agreement.md", result.code_execution_stdout)
        self.assertNotIn("framework-attached", agent.tracer.traces[-1].spans[2].attributes["output"])
        self.assertTrue(agent.tracer.traces[-1].metadata["execution_provenance_attached"])
        self.assertEqual(agent.tracer.traces[-1].metadata["provider_id"], "local_bonsai")
        self.assertEqual(agent.tracer.traces[-1].metadata["returned_model"], "bonsai-test-model")
        self.assertEqual(
            agent.tracer.traces[-1].metadata["sandbox_isolation"],
            agent.tracer.traces[-1].spans[2].attributes["isolation"],
        )
        generation_span = agent.tracer.traces[-1].spans[1]
        self.assertEqual(generation_span.name, "AI_Script_Generation")
        self.assertEqual(generation_span.span_kind, "LLM")
        self.assertTrue(generation_span.attributes["model_loaded"])
        with tempfile.NamedTemporaryFile("r+", suffix=".jsonl", encoding="utf-8") as trace_file:
            self.assertEqual(agent.tracer.export_jsonl(trace_file.name), 1)
            trace_file.seek(0)
            exported = json.loads(trace_file.readline())
        self.assertEqual(exported["metadata"]["provider_id"], "local_bonsai")
        self.assertEqual(
            exported["metadata"]["sandbox_isolation"],
            agent.tracer.traces[-1].metadata["sandbox_isolation"],
        )
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:19001/v1/chat/completions")
        sent = json.loads(request.data)
        self.assertEqual(sent["model"], "bonsai-test")
        self.assertEqual(sent["max_tokens"], 4096)
        self.assertTrue(sent["messages"][-1]["content"].endswith("/no_think"))
        self.assertIn("DEAL ROOM EVIDENCE", sent["messages"][1]["content"])
        self.assertIn("latest actual financial period", sent["messages"][1]["content"])
        self.assertIn("Q2-2026", sent["messages"][1]["content"])
        self.assertIn("Net Debt / stressed EBITDA", sent["messages"][1]["content"])
        self.assertIn('"net_debt_usd_m": 84.5', sent["messages"][1]["content"])
        self.assertNotIn("03_Board_Minutes_Q4_Authorization.md", sent["messages"][1]["content"])
        self.assertEqual(agent.tracer.traces[-1].metadata["context_source_filenames"], [
            "01_Senior_Credit_Agreement.md",
            "02_Consolidated_Financial_Ledger_2025_2026.csv",
        ])

        cloud_url = OpenAICompatibleProvider(
            "cloud", "cloud", "https://cloud.example/v1", "model"
        )
        self.assertEqual(cloud_url.status().endpoint, "https://cloud.example")

        with mock.patch.dict(os.environ, {
            "PRISM_LOCAL_AI_URL": "http://127.0.0.1:9000",
            "PRISM_LOCAL_AI_MODEL": "bonsai-exact",
            "PRISM_LOCAL_AI_ARTIFACT_SHA256": "a" * 64,
            "PRISM_LOCAL_AI_RUNTIME": "test-server",
            "PRISM_LOCAL_AI_RUNTIME_VERSION": "1.2.3",
            "PRISM_LOCAL_AI_HARDWARE": "test-gpu",
        }):
            status = ProviderRegistry().local.status()
        self.assertEqual(status.artifact_sha256, "a" * 64)
        self.assertEqual(status.runtime_name, "test-server")
        self.assertEqual(status.runtime_version, "1.2.3")
        self.assertEqual(status.hardware, "test-gpu")

    def test_cloud_context_requires_separate_explicit_opt_in(self):
        response_body = json.dumps({
            "model": "cloud-test-model",
            "choices": [{"message": {"content": "print('insufficient evidence')"}}],
        }).encode()
        fake_response = mock.MagicMock()
        fake_response.read.return_value = response_body
        fake_response.__enter__.return_value = fake_response
        registry = ProviderRegistry()
        registry.cloud = OpenAICompatibleProvider("cloud_ai", "cloud", "https://cloud.test", "cloud-test")
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        restored_cloud_events = {}
        agent = DealRoomWorkflowAgent(
            "deal_rooms/sample_ma_acquisition", providers=registry,
            cloud_consent_authority=cloud_authority(),
            cloud_consent_ledger_path=Path(temporary.name) / "uses.json",
            cloud_consent_event_resolver=lambda event_ids, channel_id: {
                event_id: restored_cloud_events[event_id]
                for event_id in event_ids if event_id in restored_cloud_events
            },
        )

        with mock.patch("urllib.request.urlopen") as opened:
            with self.assertRaisesRegex(ValueError, "signed cloud consent bundle is required"):
                agent.execute_task(
                    "analyze EBITDA", force_cloud_override=True,
                    local_only_policy=False, allow_cloud_context=True,
                    cloud_room_id="sample-room",
                )
            opened.assert_not_called()

        prompt = "email jane@example.com about EBITDA"
        dispatch = signed_bundle(
            agent=agent, prompt=prompt, room_id="sample-room", provider=registry.cloud,
            include_context=False, nonce="ab" * 16,
        )
        restored_cloud_events.update(cloud_relay_events(dispatch))
        with mock.patch("urllib.request.urlopen", return_value=fake_response) as opened:
            result = agent.execute_task(
                prompt, force_cloud_override=True, local_only_policy=False,
                cloud_consent_bundle=dispatch, cloud_room_id="sample-room",
            )
        sent = json.loads(opened.call_args.args[0].data)["messages"][1]["content"]
        self.assertIn("[REDACTED_EMAIL]", sent)
        self.assertIn("DEAL ROOM EVIDENCE: NOT PROVIDED", sent)
        self.assertNotIn("01_Senior_Credit_Agreement.md", sent)
        self.assertFalse(agent.tracer.traces[-1].metadata["cloud_context_included"])
        self.assertIn("Deal-room contents were not sent", " ".join(result.limitations))

        context_prompt = "analyze EBITDA"
        context = signed_bundle(
            agent=agent, prompt=context_prompt, room_id="sample-room", provider=registry.cloud,
            include_context=True, nonce="cd" * 16,
        )
        restored_cloud_events.update(cloud_relay_events(context))
        with mock.patch("urllib.request.urlopen", return_value=fake_response) as opened:
            agent.execute_task(
                context_prompt, force_cloud_override=True, local_only_policy=False,
                allow_cloud_context=True,
                cloud_consent_bundle=context, cloud_room_id="sample-room",
            )
        sent = json.loads(opened.call_args.args[0].data)["messages"][1]["content"]
        self.assertIn("01_Senior_Credit_Agreement.md", sent)
        self.assertTrue(agent.tracer.traces[-1].metadata["cloud_context_included"])
        self.assertEqual(len(agent.tracer.traces[-1].metadata["cloud_consent_event_ids"]), 2)
        self.assertTrue(agent.tracer.traces[-1].metadata["cloud_consent_relay_restored"])

    def test_cloud_http_requires_and_consumes_signed_request_consent_before_network(self):
        if not self.app_server:
            self.skipTest("loopback listener unavailable")
        registry = ProviderRegistry()
        registry.cloud = OpenAICompatibleProvider(
            "cloud_ai", "cloud", "https://approved-cloud.example/v1", "cloud-test-model"
        )
        prompt = "email jane@example.com about EBITDA"
        room_id = "project_titan_lbo"
        consent_authority = cloud_authority()
        with tempfile.TemporaryDirectory() as folder:
            ledger = Path(folder) / "uses.json"
            fixture_agent = DealRoomWorkflowAgent(
                DEAL_ROOM_CATALOG[room_id]["path"], providers=registry,
                cloud_consent_authority=consent_authority,
                cloud_consent_ledger_path=ledger,
            )
            bundle = signed_bundle(
                agent=fixture_agent, prompt=prompt, room_id=room_id,
                provider=registry.cloud, include_context=False,
            )
            environment = {
                "PRISM_CLOUD_POLICY_PUBKEY": str(consent_authority.policy_pubkey),
                "PRISM_CLOUD_CONTEXT_PUBKEY": str(consent_authority.context_pubkey),
                "PRISM_CLOUD_CONSENT_CHANNEL": str(consent_authority.channel_id),
                "PRISM_CLOUD_CONSENT_LEDGER": str(ledger),
            }
            with mock.patch.object(server_module, "global_providers", registry), mock.patch.dict(
                os.environ, environment,
            ), mock.patch.object(registry.cloud, "complete") as generated:
                status, body = self.app_request("/api/agent/run", {
                    "prompt": prompt, "deal_room": room_id, "runtime": "cloud",
                })
                self.assertEqual((status, body["error"]), (403, "cloud_consent_required"))
                generated.assert_not_called()

            provider_result = ProviderResult(
                provider_id="cloud_ai", model="cloud-test-model",
                content="print('insufficient evidence')", latency_ms=1.0,
                usage={"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
                raw_metadata={"request_id": "cloud-request-1"},
            )
            with mock.patch.object(server_module, "global_providers", registry), mock.patch.dict(
                os.environ, environment,
            ), mock.patch.object(
                server_module.global_buzz, "events_by_ids", return_value={},
            ) as restored, mock.patch.object(registry.cloud, "complete") as generated:
                status, body = self.app_request("/api/agent/run", {
                    "prompt": prompt, "deal_room": room_id, "runtime": "cloud",
                    "cloud_consent": bundle,
                })
                self.assertEqual((status, body["error"]), (403, "cloud_consent_required"))
                self.assertIn("not restored from Buzz", body["detail"])
                restored.assert_called_once()
                generated.assert_not_called()
                self.assertFalse(ledger.exists())

            changed_relay_events = cloud_relay_events(bundle)
            changed_relay_events[bundle["cloud_dispatch_event"]["id"]] = {
                **bundle["cloud_dispatch_event"],
                "content": "different relay payload",
            }
            with mock.patch.object(server_module, "global_providers", registry), mock.patch.dict(
                os.environ, environment,
            ), mock.patch.object(
                server_module.global_buzz, "events_by_ids",
                return_value=changed_relay_events,
            ), mock.patch.object(registry.cloud, "complete") as generated:
                status, body = self.app_request("/api/agent/run", {
                    "prompt": prompt, "deal_room": room_id, "runtime": "cloud",
                    "cloud_consent": bundle,
                })
                self.assertEqual((status, body["error"]), (403, "cloud_consent_required"))
                self.assertIn("differs from the submitted", body["detail"])
                generated.assert_not_called()
                self.assertFalse(ledger.exists())

            with mock.patch.object(server_module, "global_providers", registry), mock.patch.dict(
                os.environ, environment,
            ), mock.patch.object(
                server_module.global_buzz, "events_by_ids",
                return_value=cloud_relay_events(bundle),
            ) as restored, mock.patch.object(
                registry.cloud, "complete", return_value=provider_result,
            ) as generated:
                status, body = self.app_request("/api/agent/run", {
                    "prompt": prompt, "deal_room": room_id, "runtime": "cloud",
                    "cloud_consent": bundle,
                })
                self.assertEqual(status, 200, body)
                self.assertEqual(body["provider_id"], "cloud_ai")
                self.assertEqual(body["routing_info"]["target_tier"], "CLOUD_AI")
                restored.assert_called_once()
                generated.assert_called_once()
            saved = json.loads(ledger.read_text())
            self.assertEqual(len(saved["uses"]), 1)
            self.assertFalse(saved["uses"][0]["include_context"])
            self.assertTrue(saved["uses"][0]["relay_restored"])

            with mock.patch.object(server_module, "global_providers", registry), mock.patch.dict(
                os.environ, environment,
            ), mock.patch.object(
                server_module.global_buzz, "events_by_ids",
                return_value=cloud_relay_events(bundle),
            ), mock.patch.object(registry.cloud, "complete") as generated:
                status, body = self.app_request("/api/agent/run", {
                    "prompt": prompt, "deal_room": room_id, "runtime": "cloud",
                    "cloud_consent": bundle,
                })
                self.assertEqual((status, body["error"]), (403, "cloud_consent_required"))
                self.assertIn("already consumed", body["detail"])
                generated.assert_not_called()

    def test_lmstudio_native_provider_disables_reasoning_and_records_stats(self):
        response_body = json.dumps({
            "model_instance_id": "27b@q1_0",
            "output": [{"type": "message", "content": "print('native result')"}],
            "stats": {
                "input_tokens": 20, "total_output_tokens": 5,
                "reasoning_output_tokens": 0, "tokens_per_second": 28.5,
            },
            "response_id": "resp-native",
        }).encode()
        fake_response = mock.MagicMock()
        fake_response.read.return_value = response_body
        fake_response.__enter__.return_value = fake_response
        provider = LMStudioNativeProvider(
            "local_bonsai", "local", "http://127.0.0.1:1234", "27b@q1_0",
            max_completion_tokens=512,
        )
        with mock.patch("urllib.request.urlopen", return_value=fake_response) as opened:
            result = provider.complete([
                {"role": "system", "content": "Return Python."},
                {"role": "user", "content": "Calculate EBITDA."},
            ])
        request = opened.call_args.args[0]
        sent = json.loads(request.data)
        self.assertEqual(request.full_url, "http://127.0.0.1:1234/api/v1/chat")
        self.assertEqual(sent["reasoning"], "off")
        self.assertEqual(sent["max_output_tokens"], 512)
        self.assertEqual(sent["system_prompt"], "Return Python.")
        self.assertEqual(sent["input"], "Calculate EBITDA.")
        self.assertFalse(sent["store"])
        self.assertEqual(result.model, "27b@q1_0")
        self.assertEqual(result.usage["total_tokens"], 25)
        self.assertEqual(result.raw_metadata["reasoning_output_tokens"], 0)
        self.assertEqual(provider.status().protocol, "lmstudio_native_chat")

        fake_response.read.return_value = response_body
        with mock.patch("urllib.request.urlopen", return_value=fake_response) as opened:
            provider.complete([
                {"role": "system", "content": "Return Markdown."},
                {"role": "user", "content": "Draft the memo."},
                {"role": "assistant", "content": "Rejected draft."},
                {"role": "user", "content": "Correct the cited number."},
            ])
        sent = json.loads(opened.call_args.args[0].data)
        self.assertEqual(
            sent["input"],
            "USER MESSAGE\nDraft the memo.\n\nASSISTANT MESSAGE\nRejected draft.\n\n"
            "USER MESSAGE\nCorrect the cited number.",
        )
        self.assertNotIn("previous_response_id", sent)

        fake_response.read.return_value = response_body
        with mock.patch("urllib.request.urlopen", return_value=fake_response) as opened:
            continued = provider.complete([
                {"role": "system", "content": "Return Markdown."},
                {"role": "user", "content": "Correct the cited number."},
            ], previous_response_id="resp-first")
        sent = json.loads(opened.call_args.args[0].data)
        self.assertEqual(sent["input"], "Correct the cited number.")
        self.assertEqual(sent["previous_response_id"], "resp-first")
        self.assertEqual(continued.raw_metadata["previous_response_id_used"], "resp-first")

        with self.assertRaisesRegex(Exception, "must not repeat prior assistant"):
            provider.complete([
                {"role": "assistant", "content": "Rejected draft."},
                {"role": "user", "content": "Correct it."},
            ], previous_response_id="resp-first")

        invalid = json.dumps({
            "output": [{"type": "message", "content": "answer"}],
            "stats": {"reasoning_output_tokens": 3},
        }).encode()
        fake_response.read.return_value = invalid
        with mock.patch("urllib.request.urlopen", return_value=fake_response):
            with self.assertRaisesRegex(Exception, "did not prove reasoning was disabled"):
                provider.complete([{"role": "user", "content": "test"}])

        exhausted = json.dumps({
            "output": [{"type": "message", "content": "partial"}],
            "stats": {"input_tokens": 10, "total_output_tokens": 512,
                      "reasoning_output_tokens": 0},
        }).encode()
        fake_response.read.return_value = exhausted
        with mock.patch("urllib.request.urlopen", return_value=fake_response):
            with self.assertRaisesRegex(Exception, "output budget"):
                provider.complete([{"role": "user", "content": "test"}])

        with mock.patch.dict(os.environ, {
            "PRISM_LOCAL_AI_URL": "http://127.0.0.1:1234",
            "PRISM_LOCAL_AI_PROTOCOL": "lmstudio-native",
        }):
            self.assertIsInstance(ProviderRegistry().local, LMStudioNativeProvider)

    def test_local_context_admission_reserves_output_before_inference(self):
        response_body = json.dumps({
            "model_instance_id": "27b@q1_0",
            "output": [{"type": "message", "content": "accepted"}],
            "stats": {
                "input_tokens": 60, "total_output_tokens": 5,
                "reasoning_output_tokens": 0,
            },
            "response_id": "resp-context",
        }).encode()
        fake_response = mock.MagicMock()
        fake_response.read.return_value = response_body
        fake_response.__enter__.return_value = fake_response
        provider = LMStudioNativeProvider(
            "local_bonsai", "local", "http://127.0.0.1:1234", "27b@q1_0",
            max_completion_tokens=32,
            context_window_tokens=140,
            artifact_path="/tmp/measured-bonsai.gguf",
            token_counter=lambda _messages: 60,
        )
        with mock.patch("urllib.request.urlopen", return_value=fake_response) as opened:
            result = provider.complete([{"role": "user", "content": "bounded request"}])
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(
            result.raw_metadata["context_admission"],
            "loaded_model_tokenizer_with_runtime_margin",
        )
        self.assertEqual(result.raw_metadata["admitted_input_tokens"], 92)
        self.assertEqual(result.raw_metadata["context_runtime_margin_tokens"], 32)
        self.assertEqual(result.raw_metadata["fitted_context_tokens"], 140)
        self.assertEqual(provider.status().context_window_tokens, 140)
        self.assertEqual(
            provider.status().context_admission,
            "loaded_model_tokenizer_with_runtime_margin",
        )

    def test_local_context_admission_rejects_overflow_before_inference(self):
        provider = LMStudioNativeProvider(
            "local_bonsai", "local", "http://127.0.0.1:1234", "27b@q1_0",
            max_completion_tokens=32,
            context_window_tokens=100,
            artifact_path="/tmp/measured-bonsai.gguf",
            token_counter=lambda _messages: 37,
        )
        with mock.patch("urllib.request.urlopen") as opened:
            with self.assertRaisesRegex(ProviderError, "exceeding the measured 100-token fitted context"):
                provider.complete([{"role": "user", "content": "oversized request"}])
        opened.assert_not_called()

    def test_local_context_admission_fails_when_tokenizer_identity_is_ambiguous(self):
        provider = LMStudioNativeProvider(
            "local_bonsai", "local", "http://127.0.0.1:1234", "27b@q1_0",
            max_completion_tokens=32,
            context_window_tokens=100,
            artifact_path="/tmp/measured-bonsai.gguf",
        )
        process_table = mock.MagicMock(stdout="")
        with mock.patch("subprocess.run", return_value=process_table), mock.patch(
            "urllib.request.urlopen"
        ) as opened:
            with self.assertRaisesRegex(ProviderError, "exactly one loaded llama.cpp process"):
                provider.complete([{"role": "user", "content": "request"}])
        opened.assert_not_called()

    def test_rejected_model_creates_separate_reviewable_evidence_fallback(self):
        class FakeBuzz:
            def __init__(self):
                self.events = []
                self.canvas = None
                self.raw_events = {}

            def room(self, _room_id):
                return {"channel_id": "channel-test"}

            def send(self, _channel_id, content):
                event_id = f"{len(self.events) + 1:064x}"
                event = {
                    "event_id": event_id,
                    "id": event_id,
                    "pubkey": "d" * 64,
                    "signature_verified": True,
                    "content": content,
                }
                self.events.append(event)
                self.raw_events[event_id] = {**event, "kind": 9}
                return event

            def send_as_agent(self, channel_id, content):
                event_id = f"{len(self.events) + 1:064x}"
                event = {
                    "event_id": event_id,
                    "id": event_id,
                    "pubkey": "a" * 64,
                    "signature_verified": True,
                    "content": content,
                }
                self.events.append(event)
                self.raw_events[event_id] = {**event, "kind": 9}
                return event

            def set_canvas(self, _channel_id, content):
                self.canvas = content
                event_id = "c" * 64
                self.raw_events[event_id] = {
                    "id": event_id,
                    "pubkey": "d" * 64,
                    "kind": 40100,
                    "content": content,
                }
                return {"event_id": event_id}

            def status(self):
                return {"operator_pubkey": "d" * 64, "agent_pubkey": "a" * 64}

            def verified_messages(self, _channel_id):
                return self.events

            def events_by_ids(self, event_ids, *, channel_id=None):
                return {event_id: self.raw_events[event_id] for event_id in event_ids}

        passage = {
            "filename": "cim.md",
            "source_anchor": "node:terms",
            "citation": "[cim.md#node:terms]",
            "score": 4.0,
            "source_role": "primary_source",
            "text": (
                "The transaction uses $900.0M of first lien debt. Revenue is $520.0M. "
                "The borrower is subject to a leverage covenant."
            ),
        }
        fake_buzz = FakeBuzz()
        tracer = ArizeObservabilityTracer()
        failure = FirstPassError(
            "model claim failed grounding",
            metadata={
                "provider_id": "local_bonsai",
                "model": "27b@q1_0",
                "latency_ms": 12.0,
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )
        with (
            mock.patch.object(server_module, "global_buzz", fake_buzz),
            mock.patch.object(server_module, "global_tracer", tracer),
            mock.patch.object(server_module, "generate_first_pass", side_effect=failure),
            mock.patch.object(server_module, "retrieve_first_pass_evidence", return_value=[passage]),
            mock.patch.object(
                server_module, "build_evidence_inventory",
                side_effect=lambda _documents, *, source_snapshot_sha256: {
                    "scope_version": "current_parser_inventory_v1",
                    "source_snapshot_sha256": source_snapshot_sha256,
                    "inventory_sha256": "e" * 64,
                    "document_count": 1,
                    "parsed_node_count": 1,
                    "searchable_node_count": 1,
                    "citation_sources": {"[cim.md#node:terms]": "f" * 64},
                },
            ),
        ):
            status, result = self.app_request("/api/workspace/first-pass", {
                "room": "project_titan_lbo",
                "action": "run",
                "investment_screen": "Decide whether to advance.",
            })
            self.assertEqual(status, 201)
            self.assertEqual(result["acceptance_state"], "evidence_safe_fallback")
            self.assertEqual(result["authored_by"], "deterministic_evidence_renderer")
            self.assertNotEqual(result["trace_id"], result["model_failure_trace_id"])
            self.assertIn("mode=evidence_safe_fallback", fake_buzz.events[-1]["content"])

            failed_trace = next(
                trace for trace in tracer.traces
                if trace.trace_id == result["model_failure_trace_id"]
            )
            fallback_trace = next(
                trace for trace in tracer.traces if trace.trace_id == result["trace_id"]
            )
            self.assertFalse(failed_trace.evaluations[0].passed)
            self.assertEqual(failed_trace.metadata["result_state"], "rejected_before_buzz_draft")
            self.assertEqual(fallback_trace.query, "evidence_safe_fallback")
            self.assertEqual(fallback_trace.model_name, "deterministic_source_excerpt_v2")

            review_status, review = self.app_request("/api/workspace/first-pass", {
                "room": "project_titan_lbo",
                "action": "review",
                "decision": "pause",
                "critical_corrections": 1,
                "major_corrections": 0,
                "useful_starting_point": True,
                "notes": "Source excerpts were useful; one correction remains.",
            })
            self.assertEqual(review_status, 201)
            self.assertEqual(review["decision"], "pause")
            self.assertEqual(review["review_actor"], "local_operator")
            self.assertEqual(review["reviewer_pubkey"], "d" * 64)
            self.assertEqual(review["authentication_scope"], "local_operator_bridge")
            self.assertFalse(review["benchmark_domain_review"])
            self.assertTrue(review["restored_from_buzz"])
            self.assertEqual(review["signature_verification"]["state"], "verified")
            self.assertIn("Artifact mode: evidence_safe_fallback", fake_buzz.canvas)
            self.assertFalse(failed_trace.evaluations[0].passed)
            self.assertTrue(any(
                evaluation.name == "human_usefulness" for evaluation in fallback_trace.evaluations
            ))
            usefulness = next(
                evaluation for evaluation in fallback_trace.evaluations
                if evaluation.name == "human_usefulness"
            )
            self.assertIn("not independently authenticated domain review", usefulness.explanation)

    def test_accepted_model_buzz_event_persists_its_trace_identity(self):
        class FakeBuzz:
            def __init__(self):
                self.events = []

            def room(self, _room_id):
                return {"channel_id": "channel-test"}

            def send(self, _channel_id, content):
                event = {"event_id": f"event-{len(self.events) + 1}", "content": content}
                self.events.append(event)
                return event

            def send_as_agent(self, channel_id, content):
                return self.send(channel_id, content)

        markdown = "\n\n".join([
            "## Recommendation\n\nRecommendation: PAUSE",
            "## Transaction\n\nTarget transaction [cim.md#node:terms].",
            "## Valuation and financing\n\nNot established.",
            "## Financial quality\n\nNot established.",
            "## Risks and approvals\n\nNot established.",
            "## Missing or conflicting information\n\nValuation is missing.",
            "## Next review questions\n\nWhat evidence supports valuation?",
        ])
        generated = FirstPassResult(
            markdown=markdown,
            recommendation="pause",
            provider="local_bonsai",
            model="27b@q1_0",
            latency_ms=12.0,
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            citations=["[cim.md#node:terms]"],
            retrieved_passages=[],
            raw_metadata={},
        )
        fake_buzz = FakeBuzz()
        tracer = ArizeObservabilityTracer()
        with (
            mock.patch.object(server_module, "global_buzz", fake_buzz),
            mock.patch.object(server_module, "global_tracer", tracer),
            mock.patch.object(server_module, "generate_first_pass", return_value=generated),
        ):
            status, result = self.app_request("/api/workspace/first-pass", {
                "room": "project_titan_lbo",
                "action": "run",
                "investment_screen": "Decide whether to advance.",
            })
        self.assertEqual(status, 201)
        self.assertTrue(result["trace_id"].startswith("trc_"))
        restored = restore_signed_first_pass(fake_buzz.events[-1]["content"])
        self.assertEqual(restored["trace_id"], result["trace_id"])
        self.assertEqual(restored["acceptance_state"], "accepted")
        self.assertEqual(tracer.traces[-1].trace_id, result["trace_id"])

    def test_first_pass_blocks_model_and_fallback_publication_after_source_mutation(self):
        class FakeBuzz:
            def __init__(self):
                self.events = []
                self.agent_events = []

            def room(self, _room_id):
                return {"channel_id": "channel-test"}

            def send(self, _channel_id, content):
                event = {"event_id": f"question-{len(self.events) + 1}", "content": content}
                self.events.append(event)
                return event

            def send_as_agent(self, _channel_id, content):
                self.agent_events.append(content)
                return {"event_id": f"draft-{len(self.agent_events)}"}

        markdown = "\n\n".join([
            "## Recommendation\n\nRecommendation: PAUSE",
            "## Transaction\n\nTarget transaction [source.md#node:terms].",
            "## Valuation and financing\n\nNot established.",
            "## Financial quality\n\nNot established.",
            "## Risks and approvals\n\nNot established.",
            "## Missing or conflicting information\n\nValuation is missing.",
            "## Next review questions\n\nWhat evidence supports valuation?",
        ])
        generated = FirstPassResult(
            markdown=markdown,
            recommendation="pause",
            provider="local_bonsai",
            model="27b@q1_0",
            latency_ms=12.0,
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            citations=["[source.md#node:terms]"],
            retrieved_passages=[],
            raw_metadata={},
        )
        passage = {
            "filename": "source.md",
            "source_anchor": "node:terms",
            "citation": "[source.md#node:terms]",
            "score": 3.0,
            "text": "The transaction is subject to review.",
            "retrieval_reasons": ["investment_screen"],
        }

        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.md"
            source.write_text("# Terms\nInitial authorized source.", encoding="utf-8")
            rooms = {
                "mutable-room": {
                    "id": "mutable-room", "name": "Mutable", "type": "Private folder",
                    "description": "Mutation guard", "path": folder,
                },
            }

            fake_buzz = FakeBuzz()
            tracer = ArizeObservabilityTracer()

            def mutate_after_model(*_args, **_kwargs):
                source.write_text("# Terms\nChanged during model inference.", encoding="utf-8")
                return generated

            with (
                mock.patch.object(server_module, "all_deal_rooms", return_value=rooms),
                mock.patch.object(server_module, "global_buzz", fake_buzz),
                mock.patch.object(server_module, "global_tracer", tracer),
                mock.patch.object(server_module, "generate_first_pass", side_effect=mutate_after_model),
            ):
                status, result = self.app_request("/api/workspace/first-pass", {
                    "room": "mutable-room", "action": "run",
                    "investment_screen": "Assess transaction terms.",
                })
            self.assertEqual((status, result["error"]), (
                409, "source_changed_during_first_pass",
            ))
            self.assertEqual(fake_buzz.agent_events, [])
            self.assertNotEqual(result["source_snapshot_before"], result["source_snapshot_after"])
            self.assertEqual(tracer.traces[-1].metadata["source_snapshot_state"], "changed_during_run")

            source.write_text("# Terms\nStable before fallback.", encoding="utf-8")
            fake_buzz = FakeBuzz()
            tracer = ArizeObservabilityTracer()

            def mutate_during_fallback(*_args, **_kwargs):
                source.write_text("# Terms\nChanged during fallback retrieval.", encoding="utf-8")
                return [passage]

            with (
                mock.patch.object(server_module, "all_deal_rooms", return_value=rooms),
                mock.patch.object(server_module, "global_buzz", fake_buzz),
                mock.patch.object(server_module, "global_tracer", tracer),
                mock.patch.object(
                    server_module, "generate_first_pass",
                    side_effect=FirstPassError("model failed deterministic guard"),
                ),
                mock.patch.object(
                    server_module, "retrieve_first_pass_evidence",
                    side_effect=mutate_during_fallback,
                ),
            ):
                status, result = self.app_request("/api/workspace/first-pass", {
                    "room": "mutable-room", "action": "run",
                    "investment_screen": "Assess transaction terms.",
                })
            self.assertEqual((status, result["error"]), (
                409, "source_changed_during_first_pass",
            ))
            self.assertEqual(fake_buzz.agent_events, [])
            self.assertTrue(result["fallback_trace_id"].startswith("trc_"))
            self.assertEqual(
                tracer.traces[-1].metadata["source_snapshot_state"],
                "changed_during_fallback",
            )

    def test_first_pass_quarantines_candidate_when_source_changes_during_publication(self):
        markdown = "\n\n".join([
            "## Recommendation\n\nRecommendation: PAUSE",
            "## Transaction\n\nTarget transaction [source.md#node:terms].",
            "## Valuation and financing\n\nNot established.",
            "## Financial quality\n\nNot established.",
            "## Risks and approvals\n\nNot established.",
            "## Missing or conflicting information\n\nValuation is missing.",
            "## Next review questions\n\nWhat evidence supports valuation?",
        ])
        generated = FirstPassResult(
            markdown=markdown,
            recommendation="pause",
            provider="local_bonsai",
            model="27b@q1_0",
            latency_ms=12.0,
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            citations=["[source.md#node:terms]"],
            retrieved_passages=[],
            raw_metadata={},
        )
        snapshot_before = "a" * 64
        snapshot_after = "b" * 64
        provenance = {
            "classification": "synthetic_engineering_fixture",
            "binding_sha256": "c" * 64,
        }
        candidate_id = "d" * 64
        tracer = ArizeObservabilityTracer()
        with (
            mock.patch.object(server_module, "global_tracer", tracer),
            mock.patch.object(
                server_module.global_buzz, "room",
                return_value={"room_id": "project_titan_lbo", "channel_id": "channel"},
            ),
            mock.patch.object(
                server_module.global_buzz, "send", return_value={"event_id": "q" * 64},
            ),
            mock.patch.object(
                server_module.global_buzz, "send_as_agent",
                return_value={"event_id": candidate_id},
            ) as send_as_agent,
            mock.patch.object(server_module, "generate_first_pass", return_value=generated),
            mock.patch.object(
                server_module, "inspect_local_deal_room",
                side_effect=[
                    {"preview": {"preview_sha256": snapshot_before}},
                    {"preview": {"preview_sha256": snapshot_before}},
                    {"preview": {"preview_sha256": snapshot_after}},
                ],
            ),
            mock.patch.object(server_module, "source_provenance_binding", return_value=provenance),
        ):
            status, result = self.app_request("/api/workspace/first-pass", {
                "room": "project_titan_lbo",
                "action": "run",
                "investment_screen": "Assess transaction terms.",
            })
        self.assertEqual((status, result["error"]), (409, "source_changed_during_first_pass"))
        self.assertEqual(len(send_as_agent.call_args_list), 1)
        self.assertEqual(
            tracer.traces[-1].metadata["result_state"],
            "rejected_after_buzz_candidate_due_source_change",
        )
        self.assertEqual(tracer.traces[-1].metadata["orphaned_draft_event_id"], candidate_id)

    def test_chat_quarantines_candidate_when_source_changes_during_publication(self):
        answer = DealRoomChatResult(
            response="- consideration: $104.00 [term-sheet.md#text:block:00001]",
            provider="local_bonsai",
            model="27b@q1_0",
            latency_ms=14.0,
            usage={"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
            citations=["[term-sheet.md#text:block:00001]"],
            retrieved_passages=[],
            raw_metadata={},
            requested_parts=["consideration"],
            part_citations={"consideration": ["[term-sheet.md#text:block:00001]"]},
            guard_version="deal_room_chat_guard_v1",
            inference_attempts=1,
        )
        snapshot_before = "a" * 64
        snapshot_after = "b" * 64
        provenance = {
            "classification": "synthetic_engineering_fixture",
            "binding_sha256": "c" * 64,
        }
        candidate_id = "d" * 64
        rejection_id = "e" * 64
        tracer = ArizeObservabilityTracer()
        with (
            mock.patch.object(server_module, "global_tracer", tracer),
            mock.patch.object(
                server_module.global_buzz, "room",
                return_value={"room_id": "project_titan_lbo", "channel_id": "channel"},
            ),
            mock.patch.object(
                server_module.global_buzz, "send", return_value={"event_id": "q" * 64},
            ),
            mock.patch.object(
                server_module.global_buzz, "send_as_agent",
                side_effect=[{"event_id": candidate_id}, {"event_id": rejection_id}],
            ) as send_as_agent,
            mock.patch.object(server_module, "answer_deal_room_question", return_value=answer),
            mock.patch.object(
                server_module, "inspect_local_deal_room",
                side_effect=[
                    {"preview": {"preview_sha256": snapshot_before}},
                    {"preview": {"preview_sha256": snapshot_before}},
                    {"preview": {"preview_sha256": snapshot_after}},
                ],
            ),
            mock.patch.object(server_module, "source_provenance_binding", return_value=provenance),
        ):
            status, result = self.app_request("/api/workspace/messages", {
                "room": "project_titan_lbo",
                "content": "What is the consideration?",
                "ask_bonsai": True,
            })
        self.assertEqual(status, 201)
        self.assertEqual(result["agent_reply"]["answer_state"], "rejected")
        trace = tracer.traces[-1]
        self.assertEqual(
            trace.metadata["result_state"],
            "rejected_after_buzz_candidate_due_source_change",
        )
        self.assertEqual(trace.metadata["orphaned_answer_event_id"], candidate_id)
        candidate_content = send_as_agent.call_args_list[0].args[1]
        rejection_content = send_as_agent.call_args_list[1].args[1]
        candidate = {
            "id": candidate_id,
            "pubkey": "a" * 64,
            "signature_verified": True,
            "content": candidate_content,
        }
        rejection = {
            "id": rejection_id,
            "pubkey": "a" * 64,
            "signature_verified": True,
            "content": rejection_content,
        }
        self.assertIsNone(trace_bound_deal_room_message_state(
            candidate,
            tracer.traces,
            room_id="project_titan_lbo",
            agent_pubkey="a" * 64,
            current_provenance=provenance,
            current_source_snapshot=snapshot_after,
        ))
        self.assertEqual(trace_bound_deal_room_message_state(
            rejection,
            tracer.traces,
            room_id="project_titan_lbo",
            agent_pubkey="a" * 64,
            current_provenance=provenance,
            current_source_snapshot=snapshot_after,
        ), "rejected")

    def test_trace_bound_chat_fails_when_current_evidence_anchor_drifts(self):
        room_id = "project_titan_lbo"
        event_id = "d" * 64
        trace_id = "trc_evidence_scope_guard"
        source_snapshot = "b" * 64
        provenance_sha256 = "c" * 64
        source_sha256 = "e" * 64
        citation = "[cim.md#node:1]"
        body = f"The consideration is stated in the source. {citation}"
        trace = ArizeTraceRecord(
            trace_id=trace_id,
            session_id=room_id,
            timestamp=1.0,
            query="What is the consideration?",
            response=body,
            model_name="27b@q1_0",
            routed_tier="LOCAL_BONSAI_27B",
            total_tokens=10,
            prompt_tokens=8,
            completion_tokens=2,
            total_latency_ms=10.0,
            energy_per_token_mwh=None,
            total_energy_mwh=None,
            vram_peak_gb=None,
            metadata={
                "guard_version": server_module.DEAL_ROOM_CHAT_GUARD_VERSION,
                "source_classification": "synthetic_engineering_fixture",
                "source_provenance_sha256": provenance_sha256,
                "source_snapshot_sha256": source_snapshot,
                "answer_event_id": event_id,
                "result_state": "guard_passed_and_signed_to_buzz",
                "retrieved_anchors": [{
                    "citation": citation,
                    "source_sha256": source_sha256,
                }],
            },
        )
        message = {
            "id": event_id,
            "pubkey": "a" * 64,
            "signature_verified": True,
            "content": (
                "<!-- prism:deal-room-answer model=27b@q1_0 "
                f"guard={server_module.DEAL_ROOM_CHAT_GUARD_VERSION} trace={trace_id} "
                "source_class=synthetic_engineering_fixture "
                f"provenance={provenance_sha256} source_snapshot={source_snapshot} -->\n"
                f"{body}"
            ),
        }
        provenance = {
            "classification": "synthetic_engineering_fixture",
            "binding_sha256": provenance_sha256,
        }
        inventory = {
            "scope_version": "current_parser_inventory_v1",
            "source_snapshot_sha256": source_snapshot,
            "inventory_sha256": "f" * 64,
            "document_count": 1,
            "parsed_node_count": 1,
            "searchable_node_count": 1,
            "citation_sources": {citation: source_sha256},
        }
        self.assertEqual(trace_bound_deal_room_message_state(
            message,
            [trace],
            room_id=room_id,
            agent_pubkey="a" * 64,
            current_provenance=provenance,
            current_source_snapshot=source_snapshot,
            current_evidence_inventory=inventory,
        ), "accepted")
        inventory["citation_sources"][citation] = "0" * 64
        self.assertIsNone(trace_bound_deal_room_message_state(
            message,
            [trace],
            room_id=room_id,
            agent_pubkey="a" * 64,
            current_provenance=provenance,
            current_source_snapshot=source_snapshot,
            current_evidence_inventory=inventory,
        ))

    def test_workspace_replaces_uncommitted_agent_payload_with_quarantine_notice(self):
        event_id = "d" * 64
        message = {
            "id": event_id,
            "pubkey": "a" * 64,
            "signature_verified": True,
            "created_at": 1,
            "content": (
                "<!-- prism:deal-room-answer model=27b@q1_0 "
                "guard=deal_room_chat_guard_v1 trace=trc_orphaned "
                "source_class=synthetic_engineering_fixture "
                f"provenance={'c' * 64} source_snapshot={'b' * 64} -->\n"
                "Unsupported candidate content"
            ),
        }
        with (
            mock.patch.object(server_module, "global_tracer", ArizeObservabilityTracer()),
            mock.patch.object(
                server_module.global_buzz, "room",
                return_value={"room_id": "project_titan_lbo", "channel_id": "channel"},
            ),
            mock.patch.object(
                server_module.global_buzz, "verified_messages", return_value=[message],
            ),
            mock.patch.object(
                server_module.global_buzz, "status",
                return_value={"agent_pubkey": "a" * 64, "operator_pubkey": "f" * 64},
            ),
        ):
            status, result = self.app_request(
                "/api/workspace/messages?room=project_titan_lbo"
            )
        self.assertEqual(status, 200)
        view = result["messages"][0]
        self.assertEqual(view["prism_acceptance_state"], "quarantined_uncommitted")
        self.assertIn("not presented as an answer", view["display_content"])
        self.assertEqual(view["content"], message["content"])

    def test_ai_sandbox_failure_is_not_reported_as_findings(self):
        response_body = json.dumps({
            "model": "unsafe-test-model",
            "choices": [{"message": {"content": "import os\nprint(os.getcwd())"}}],
        }).encode()
        fake_response = mock.MagicMock()
        fake_response.read.return_value = response_body
        fake_response.__enter__.return_value = fake_response
        registry = ProviderRegistry()
        registry.local = OpenAICompatibleProvider(
            "local_bonsai", "local", "http://127.0.0.1:19002", "unsafe"
        )
        agent = DealRoomWorkflowAgent("deal_rooms/sample_ma_acquisition", providers=registry)
        with mock.patch("urllib.request.urlopen", return_value=fake_response):
            result = agent.execute_task("Calculate EBITDA")
        self.assertEqual(result.steps[2].status, "FAILED")
        self.assertEqual(result.steps[3].status, "FAILED")
        self.assertIn("Calculation Failed", result.final_answer)
        self.assertIn("No financial findings were accepted", result.final_answer)

    def test_template_selection_requires_matching_folder_and_prompt(self):
        agent = DealRoomWorkflowAgent("deal_rooms/project_aeroflux_crossborder_ma")
        result = agent.execute_task("Run the Titan LBO debt schedule", force_baseline=True)
        self.assertEqual(result.execution_mode, "deterministic_no_match")
        self.assertIn("No Reviewed Workflow Matched", result.final_answer)
        self.assertNotIn("Ending TLB", result.code_execution_stdout)

    def test_reviewed_workflow_values_are_loaded_from_selected_folder(self):
        header = [
            "Quarter", "Revenue_USD_M", "Gross_Profit_USD_M", "Unadjusted_EBITDA_USD_M",
            "Permitted_Addbacks_USD_M", "Adjusted_EBITDA_USD_M", "Total_Funded_Debt_USD_M",
            "Cash_Equivalents_USD_M", "Net_Debt_USD_M", "Cash_Interest_Expense_USD_M",
            "CapEx_USD_M", "Calculated_Leverage_Ratio", "Calculated_Interest_Coverage",
            "Covenant_Leverage_Cap", "Covenant_Coverage_Floor", "Compliance_Status",
        ]
        row = ["Q2-2026", "0", "0", "0", "0", "30", "100", "10", "90", "5", "0",
               "3.0", "6.0", "3.5", "4.0", "PASS"]
        with tempfile.TemporaryDirectory() as folder:
            with open(f"{folder}/01_Senior_Credit_Agreement.md", "w", encoding="utf-8") as handle:
                handle.write("# Reviewed test covenant")
            with open(
                f"{folder}/02_Consolidated_Financial_Ledger_2025_2026.csv",
                "w", encoding="utf-8", newline="",
            ) as handle:
                writer = csv.writer(handle)
                writer.writerow(header)
                writer.writerow(row)
            result = DealRoomWorkflowAgent(folder).execute_task(
                "Run a 10% and 20% EBITDA stress sensitivity", force_baseline=True
            )
        self.assertIn("EBITDA=$30.0M | Leverage=3.0x", result.code_execution_stdout)
        self.assertIn("EBITDA=$24.0M | Leverage=3.75x", result.code_execution_stdout)
        self.assertNotIn("Leverage=3.77x", result.code_execution_stdout)

    def test_cli_runs_an_arbitrary_folder_and_local_runtime_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            shutil.copytree("deal_rooms/sample_ma_acquisition", folder, dirs_exist_ok=True)
            completed = subprocess.run(
                [sys.executable, "prismctl", "agent",
                 "Run a 10% and 20% EBITDA stress sensitivity",
                 "--deal-room", folder, "--runtime", "baseline"],
                capture_output=True, text=True, timeout=15,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("deterministic_template", completed.stdout)
        self.assertIn("SENSITIVITY ANALYSIS RESULTS", completed.stdout)

        environment = dict(os.environ)
        environment.pop("PRISM_LOCAL_AI_URL", None)
        unavailable = subprocess.run(
            [sys.executable, "prismctl", "agent", "calculate EBITDA",
             "--deal-room", "sample_ma_acquisition", "--runtime", "local"],
            capture_output=True, text=True, timeout=10, env=environment,
        )
        self.assertNotEqual(unavailable.returncode, 0)
        self.assertIn("PRISM_LOCAL_AI_URL is not configured", unavailable.stderr)

        unavailable_benchmark = subprocess.run(
            [sys.executable, "prismctl", "benchmark", "--runtime", "local"],
            capture_output=True, text=True, timeout=15, env=environment,
        )
        self.assertNotEqual(unavailable_benchmark.returncode, 0)
        report = json.loads(unavailable_benchmark.stdout)
        self.assertEqual(report["pass_rate"], 0.0)
        self.assertTrue(all(case["execution_mode"] == "unavailable" for case in report["cases"]))

    def test_json_workflows_are_source_bound_and_do_not_invent_dates(self):
        with tempfile.TemporaryDirectory() as folder:
            shutil.copytree("deal_rooms/project_titan_lbo", folder, dirs_exist_ok=True)
            returns_path = f"{folder}/04_Sponsor_Returns_Sensitivity_IRR_MoIC.json"
            with open(returns_path, encoding="utf-8") as handle:
                returns = json.load(handle)
            scenario = returns["returns_matrix_by_exit_year"]["2030_5_Year_Exit"]["multiples_sensitivity"][0]
            scenario["sponsor_moic"] = 9.99
            scenario["sponsor_irr_pct"] = 58.4
            with open(returns_path, "w", encoding="utf-8") as handle:
                json.dump(returns, handle)
            result = DealRoomWorkflowAgent(folder).execute_task(
                "Run the sponsor returns IRR and MoIC sensitivity", force_baseline=True
            )
        self.assertIn("9.99x", result.code_execution_stdout)
        self.assertIn("58.4%", result.code_execution_stdout)
        self.assertNotIn("  9.0x EBITDA", result.code_execution_stdout)

        litigation = DealRoomWorkflowAgent("deal_rooms/sample_ma_acquisition").execute_task(
            "Check litigation notice materiality", force_baseline=True
        )
        self.assertIn("$12.5M vs Threshold: $7.5M", litigation.code_execution_stdout)
        self.assertIn("REVIEW_REQUIRED", litigation.code_execution_stdout)
        self.assertIn("2025-12-22", litigation.code_execution_stdout)
        self.assertNotIn("Delivered in 4 business days", litigation.code_execution_stdout)

    def test_cloud_requires_explicit_policy_and_configuration(self):
        router = HybridAIRouter(default_local_only_policy=True)
        local = router.evaluate_routing("confidential EBITDA", local_ai_available=True)
        self.assertEqual(local.target_tier, "LOCAL_BONSAI")
        cloud = router.evaluate_routing(
            "email jane@example.com about confidential EBITDA", deal_room_active=False,
            force_cloud_override=True, local_only_policy_override=False, cloud_ai_available=True,
        )
        self.assertEqual(cloud.target_tier, "CLOUD_CONSENT_REQUIRED")
        self.assertIn("[REDACTED_EMAIL]", cloud.sanitized_prompt)
        authorized = router.evaluate_routing(
            "email jane@example.com about confidential EBITDA", deal_room_active=False,
            force_cloud_override=True, local_only_policy_override=False,
            cloud_ai_available=True, cloud_dispatch_authorized=True,
        )
        self.assertEqual(authorized.target_tier, "CLOUD_AI")
        public_cloud = router.evaluate_routing(
            "contact jane@example.com", deal_room_active=False, force_cloud_override=True,
            local_only_policy_override=False, cloud_ai_available=True,
        )
        self.assertIn("[REDACTED_EMAIL]", public_cloud.sanitized_prompt)

    def test_baseline_benchmark_has_case_level_evidence(self):
        report = run_benchmark("benchmarks/deal_room_reliability.json", DEAL_ROOM_CATALOG)
        self.assertEqual(report.total_cases, 4)
        self.assertEqual(len(report.cases), 4)
        self.assertEqual(report.mean_structured_check_coverage, 1.0)
        self.assertEqual(
            report.structured_check_measurement_state,
            "preregistered_rule_coverage_not_domain_accuracy",
        )
        self.assertEqual(report.mean_source_attribution_coverage, 1.0)
        self.assertEqual(
            report.grounding_measurement_state,
            "filename_presence_only_not_semantic_grounding",
        )
        self.assertEqual(report.pass_rate, 1.0)
        self.assertTrue(all(case.trace_id for case in report.cases))
        self.assertTrue(all(case.observed_output for case in report.cases))

        filtered = run_benchmark(
            "benchmarks/deal_room_reliability.json", DEAL_ROOM_CATALOG,
            case_ids=["horizon_ebitda_stress"],
        )
        self.assertEqual(filtered.total_cases, 1)
        self.assertEqual(filtered.cases[0].case_id, "horizon_ebitda_stress")
        with self.assertRaisesRegex(ValueError, "Unknown benchmark case"):
            run_benchmark(
                "benchmarks/deal_room_reliability.json", DEAL_ROOM_CATALOG,
                case_ids=["not-a-case"],
            )

    def test_accretion_benchmark_rejects_unrelated_regulatory_conclusion(self):
        prompt = "Calculate AeroFlux transaction accretion and pro-forma EPS synergies."
        result = DealRoomWorkflowAgent(
            "deal_rooms/project_aeroflux_crossborder_ma"
        ).execute_task(prompt, force_baseline=True)
        result.code_execution_stdout += "\nCFIUS Compliance Status: FAIL"
        with mock.patch.object(
            DealRoomWorkflowAgent, "execute_task", return_value=result
        ):
            report = run_benchmark(
                "benchmarks/deal_room_reliability.json",
                DEAL_ROOM_CATALOG,
                case_ids=["aeroflux_accretion"],
            )
        self.assertEqual(report.pass_rate, 0.0)
        self.assertEqual(report.cases[0].forbidden_hits, ["CFIUS"])

    def test_accretion_benchmark_accepts_equivalent_per_share_unit_label(self):
        prompt = "Calculate AeroFlux transaction accretion and pro-forma EPS synergies."
        result = DealRoomWorkflowAgent(
            "deal_rooms/project_aeroflux_crossborder_ma"
        ).execute_task(prompt, force_baseline=True)
        result.code_execution_stdout = result.code_execution_stdout.replace(
            "Buyer Standalone EPS : $2.79 USD",
            "Buyer standalone EPS ($/share): 2.7908",
        ).replace(
            "Pro-Forma EPS        : $3.31 USD",
            "Pro forma EPS ($/share): 3.3147",
        )
        with mock.patch.object(
            DealRoomWorkflowAgent, "execute_task", return_value=result
        ):
            report = run_benchmark(
                "benchmarks/deal_room_reliability.json",
                DEAL_ROOM_CATALOG,
                case_ids=["aeroflux_accretion"],
            )
        self.assertEqual(report.pass_rate, 1.0, report.cases[0].missing_terms)

    def test_titan_benchmark_accepts_equivalent_multiline_json_records(self):
        prompt = "Run the LBO debt schedule and annual ECF sweep prepayments."
        result = DealRoomWorkflowAgent(
            "deal_rooms/project_titan_lbo"
        ).execute_task(prompt, force_baseline=True)
        result.code_execution_stdout = """PRISM EXECUTION PROVENANCE (framework-attached; not model-authored)
Deal identifier supplied: PROJECT TITAN
Source files supplied: 01_Confidential_Information_Memorandum.md, 02_LBO_Debt_Financing_Credit_Agreement.md, 03_Three_Statement_Financial_Model_2024_2028.csv
MODEL-GENERATED SANDBOX OUTPUT
[
  {
    "period": "2026E_LBO_Y1",
    "reported_ecf_sweep_usd_m": 29.8,
    "contract_sweep_percent": 25.0,
    "policy_match_status": "MODEL_POLICY_MISMATCH"
  },
  {
    "period": "2027E_LBO_Y2",
    "contract_sweep_percent": 0.0,
    "policy_match_status": "MODEL_POLICY_MISMATCH"
  },
  {
    "period": "2030E_LBO_Y5",
    "reported_ending_tlb_usd_m": 438.8
  }
]"""
        with mock.patch.object(
            DealRoomWorkflowAgent, "execute_task", return_value=result
        ):
            report = run_benchmark(
                "benchmarks/deal_room_reliability.json",
                DEAL_ROOM_CATALOG,
                case_ids=["titan_lbo_sweep"],
            )
        self.assertEqual(report.pass_rate, 1.0, report.cases[0].missing_terms)

        result.code_execution_stdout = result.code_execution_stdout.replace(
            '"contract_sweep_percent": 25.0',
            '"contract_sweep_percent": 50.0',
            1,
        )
        with mock.patch.object(
            DealRoomWorkflowAgent, "execute_task", return_value=result
        ):
            wrong_policy = run_benchmark(
                "benchmarks/deal_room_reliability.json",
                DEAL_ROOM_CATALOG,
                case_ids=["titan_lbo_sweep"],
            )
        self.assertEqual(wrong_policy.pass_rate, 0.0)
        self.assertIn(
            "pattern:year1_contract_sweep",
            wrong_policy.cases[0].missing_terms,
        )

    def test_accretion_benchmark_rejects_invented_threshold_and_wrong_eps_unit(self):
        prompt = "Calculate AeroFlux transaction accretion and pro-forma EPS synergies."
        result = DealRoomWorkflowAgent(
            "deal_rooms/project_aeroflux_crossborder_ma"
        ).execute_task(prompt, force_baseline=True)
        result.code_execution_stdout = result.code_execution_stdout.replace(
            "Pro-Forma EPS        : $3.31 USD", "Pro-Forma EPS        : $3.31M"
        ) + "\nPolicy Conclusion: PASS (meets minimum 1.0% threshold)"
        with mock.patch.object(
            DealRoomWorkflowAgent, "execute_task", return_value=result
        ):
            report = run_benchmark(
                "benchmarks/deal_room_reliability.json",
                DEAL_ROOM_CATALOG,
                case_ids=["aeroflux_accretion"],
            )
        self.assertEqual(report.pass_rate, 0.0)
        self.assertIn("pattern:pro_forma_eps_labeled", report.cases[0].missing_terms)
        self.assertIn("pattern:eps_labeled_as_millions", report.cases[0].forbidden_hits)
        self.assertIn("Policy Conclusion", report.cases[0].forbidden_hits)

    def test_qoe_benchmark_rejects_invented_valuation_policy(self):
        prompt = "Build the BioVanguard carve-out QoE and standalone EBITDA bridge."
        result = DealRoomWorkflowAgent(
            "deal_rooms/project_biovanguard_carveout"
        ).execute_task(prompt, force_baseline=True)
        result.code_execution_stdout += (
            "\nBenchmark Multiple: 5.0x\n"
            "Conclusion: MISMATCH - valuation exceeds policy threshold"
        )
        with mock.patch.object(
            DealRoomWorkflowAgent, "execute_task", return_value=result
        ):
            report = run_benchmark(
                "benchmarks/deal_room_reliability.json",
                DEAL_ROOM_CATALOG,
                case_ids=["biovanguard_qoe"],
            )
        self.assertEqual(report.pass_rate, 0.0)
        self.assertIn("Benchmark Multiple", report.cases[0].forbidden_hits)
        self.assertIn("policy threshold", report.cases[0].forbidden_hits)

    def test_saved_coding_pilot_covers_required_behaviors(self):
        required_categories = {
            "generation", "edit", "test", "tool_use", "unsafe_code", "timeout",
            "unsupported_request",
        }
        artifacts = (
            ("benchmarks/coding_agent_reliability.json",
             "evidence/bonsai-local-coding-benchmark.json"),
            ("benchmarks/coding_agent_holdout.json",
             "evidence/bonsai-local-coding-holdout.json"),
        )
        for dataset_path, evidence_path in artifacts:
            with self.subTest(dataset=dataset_path):
                with open(dataset_path, encoding="utf-8") as handle:
                    dataset = json.load(handle)
                with open(evidence_path, encoding="utf-8") as handle:
                    evidence = json.load(handle)
                self.assertEqual(
                    {case["category"] for case in dataset["cases"]},
                    required_categories,
                )
                self.assertEqual(
                    evidence["dataset_sha256"],
                    hashlib.sha256(Path(dataset_path).read_bytes()).hexdigest(),
                )
                self.assertEqual(evidence["runtime_evidence"]["model"], "27b@q1_0")
                self.assertEqual(evidence["pass_rate"], 1.0)
                self.assertEqual(evidence["syntax_success_rate"], 1.0)
                self.assertEqual(evidence["disposition_match_rate"], 1.0)
                self.assertEqual(evidence["grounding_applicable_cases"], 3)
                self.assertEqual(evidence["grounded_source_rate"], 1.0)

                supported = [
                    case for case in evidence["cases"]
                    if case["category"] != "unsupported_request"
                ]
                unsupported = [
                    case for case in evidence["cases"]
                    if case["category"] == "unsupported_request"
                ]
                self.assertEqual(len(supported), 6)
                self.assertTrue(all(
                    case["provider_id"] == "local_bonsai"
                    and case["model_name"] == "27b@q1_0"
                    for case in supported
                ))
                self.assertEqual(len(unsupported), 1)
                self.assertEqual(unsupported[0]["provider_id"], "policy_guard")
                self.assertIsNone(unsupported[0]["model_name"])

    def test_cold_restart_evidence_hash_tamper_fails_closed(self):
        evidence_path = Path("evidence/bonsai-cold-restart.json")
        result = validate_cold_restart_evidence(evidence_path)
        self.assertNotEqual(result["before_pid"], result["after_pid"])

        record = json.loads(evidence_path.read_text(encoding="utf-8"))
        record["verification_artifact_sha256"] = "0" * 64
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", encoding="utf-8", dir="evidence"
        ) as handle:
            json.dump(record, handle)
            handle.flush()
            tampered = validate_cold_restart_evidence(Path(handle.name))
        self.assertFalse(tampered["passed"])
        self.assertIn("SHA-256", " ".join(tampered["errors"]))

        record = json.loads(evidence_path.read_text(encoding="utf-8"))
        dependent_paths = {
            "local_deployment": Path("evidence/local-deployment-current.json"),
            "live_inference_concurrency": Path("evidence/live-inference-concurrency-v1.json"),
            "browser_surface": Path("evidence/browser-first-pass-cold-restart.json"),
        }
        record["dependent_evidence"] = {
            name: {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for name, path in dependent_paths.items()
        }
        record["dependent_evidence"]["browser_surface"]["sha256"] = "0" * 64
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", encoding="utf-8", dir="evidence"
        ) as handle:
            json.dump(record, handle)
            handle.flush()
            tampered = validate_cold_restart_evidence(Path(handle.name))
        self.assertFalse(tampered["passed"])
        self.assertIn(
            "cold-restart dependent evidence hash mismatch: browser_surface",
            tampered["errors"],
        )

    def test_current_local_product_evidence_scope_tamper_fails_closed(self):
        dataset_sha256 = hashlib.sha256(
            Path("benchmarks/deal_room_reliability.json").read_bytes()
        ).hexdigest()
        common = {
            "passed": True,
            "sandbox_success": True,
            "execution_mode": "ai_generated_sandboxed_code",
            "provider_id": "local_bonsai",
            "model_name": "27b@q1_0",
            "missing_terms": [],
            "forbidden_hits": [],
            "observed_generated_code": "print('checked')",
            "generation_attempts": 1,
        }
        artifact = {
            "runtime": "local",
            "selected_runtime_verified": True,
            "component_tests": {
                "passed": True,
                "tests_skipped": 0,
                "required_reality_tests_present": True,
            },
            "benchmark": {
                "benchmark_version": 3,
                "dataset_sha256": dataset_sha256,
                "total_cases": 4,
                "passed_cases": 4,
                "pass_rate": 1.0,
                "mean_structured_check_coverage": 1.0,
                "structured_check_measurement_state": "preregistered_rule_coverage_not_domain_accuracy",
                "mean_source_attribution_coverage": 1.0,
                "grounding_measurement_state": "filename_presence_only_not_semantic_grounding",
                "runtime_evidence": {
                    "provider_id": "local_bonsai",
                    "model": "27b@q1_0",
                    "protocol": "lmstudio_native_chat",
                    "artifact_sha256": "a" * 64,
                    "runtime_name": "fixture runtime",
                    "runtime_version": "1",
                    "hardware": "fixture hardware",
                },
                "cases": [
                    dict(common, case_id="horizon_ebitda_stress", observed_output="NovaTech stress result"),
                    dict(common, case_id="titan_lbo_sweep", observed_output="PROJECT TITAN MODEL_POLICY_MISMATCH"),
                    dict(common, case_id="aeroflux_accretion", observed_output="42.5M 17.3M EPS $/share"),
                    dict(common, case_id="biovanguard_qoe", observed_output="BioVanguard quality review"),
                ],
            },
        }
        aero = next(
            case for case in artifact["benchmark"]["cases"]
            if case["case_id"] == "aeroflux_accretion"
        )
        aero["observed_output"] += "\nCFIUS Clearance: PASS"
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", encoding="utf-8", dir="evidence"
        ) as handle:
            json.dump(artifact, handle)
            handle.flush()
            with mock.patch(
                "scripts.verify_product.source_manifest_errors", return_value=[],
            ):
                tampered = validate_current_local_product_evidence(Path(handle.name))
        self.assertFalse(tampered["passed"])
        self.assertIn("AeroFlux", " ".join(tampered["errors"]))

    def test_saved_evidence_validator_accepts_equivalent_per_share_unit(self):
        self.assertTrue(has_per_share_unit_label("Pro forma EPS: 3.31 USD per share"))
        self.assertTrue(has_per_share_unit_label("Pro forma EPS ($/share): 3.31"))
        self.assertFalse(has_per_share_unit_label("Pro forma EPS: $3.31M"))

    def test_xlsx_live_evidence_verifies_raw_events_and_rejects_tampering(self):
        evidence_path = Path("evidence/bonsai-xlsx-workbook-chat-v2.json")
        result = validate_xlsx_workbook_chat_evidence(evidence_path)
        self.assertTrue(result["passed"], result["errors"])

        record = json.loads(evidence_path.read_text(encoding="utf-8"))
        answer_event_id = record["accepted_run"]["answer_event_id"]
        record["raw_buzz_events"][answer_event_id]["content"] += " tampered"
        record["direct_acp_observation"]["status"] = "passed"
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", encoding="utf-8", dir="evidence"
        ) as handle:
            json.dump(record, handle)
            handle.flush()
            tampered = validate_xlsx_workbook_chat_evidence(Path(handle.name))
        self.assertFalse(tampered["passed"])
        joined = " ".join(tampered["errors"])
        self.assertIn("NIP-01", joined)
        self.assertIn("direct-ACP", joined)

    def test_provenance_bound_publication_recomputes_current_room_and_rejects_tampering(self):
        evidence_path = Path("evidence/provenance-bound-publication-v1.json")
        result = validate_provenance_bound_publication(evidence_path)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["source_classification"], "public_filing_corpus")
        self.assertEqual(result["assertion_count"], 12)

        record = json.loads(evidence_path.read_text(encoding="utf-8"))
        record["event"]["content"] = record["event"]["content"].replace(
            "source_class=public_filing_corpus",
            "source_class=synthetic_engineering_fixture",
            1,
        )
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", encoding="utf-8", dir="evidence"
        ) as handle:
            json.dump(record, handle)
            handle.flush()
            tampered = validate_provenance_bound_publication(Path(handle.name))
        self.assertFalse(tampered["passed"])
        self.assertIn("signature", " ".join(tampered["errors"]).lower())

    def test_benchmark_negative_control_fails(self):
        dataset = {
            "name": "negative control", "version": 1,
            "cases": [{
                "id": "must_fail", "deal_room": "project_titan_lbo",
                "prompt": "Run the LBO debt schedule.",
                "expected_terms": ["THIS VALUE CANNOT BE PRODUCED"],
                "forbidden_terms": [],
            }],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(dataset, handle)
            handle.flush()
            report = run_benchmark(handle.name, DEAL_ROOM_CATALOG)
        self.assertEqual(report.pass_rate, 0.0)
        self.assertIn("THIS VALUE CANNOT BE PRODUCED", report.cases[0].missing_terms)

    def test_live_http_contract_and_errors(self):
        if not self.app_server:
            self.skipTest("sandbox forbids loopback socket binding; run this test outside the managed sandbox")
        status, body = self.app_request("/api/status")
        self.assertEqual(status, 200)

        self.assertIn("providers", body)
        self.assertNotEqual(body.get("product_stage"), "production")
        self.assertEqual(body["analysis_engine"], "deterministic_template_runner")
        self.assertFalse(body["cloud_consent"]["authority_configured"])
        self.assertFalse(body["cloud_consent"]["dispatch_ready_for_signed_request"])
        self.assertEqual(body["cloud_consent"]["default"], "deny_before_network")
        self.assertTrue(body["cloud_consent"]["context_release_requires_distinct_signature"])
        self.assertTrue(body["cloud_consent"]["relay_restoration_required"])
        self.assertTrue(body["document_ingestion"]["pdf_ocr"]["available"])
        self.assertIn("accuracy has not been benchmarked", body["document_ingestion"]["meaning"])

        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.app_server.server_port}/api/status", timeout=5
        ) as response:
            self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
            self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))
            self.assertEqual(response.headers["Cache-Control"], "no-store")

        status, body = self.app_request("/api/agent/run", {"prompt": "", "deal_room": "project_titan_lbo"})
        self.assertEqual((status, body["error"]), (400, "prompt_required"))
        status, body = self.app_request("/api/deal-room?room=missing")
        self.assertEqual((status, body["error"]), (404, "unknown_deal_room"))
        status, body = self.app_request("/api/agent/run", raw=b"not-json")
        self.assertEqual((status, body["error"]), (400, "invalid_json"))
        status, body = self.app_request("/api/benchmark", {"runtime": "local"})
        self.assertEqual((status, body["error"]), (409, "local_provider_not_configured"))

    def test_cloud_status_requires_buzz_readiness_and_reports_actual_ledger(self):
        if not self.app_server:
            self.skipTest("loopback listener unavailable")
        registry = ProviderRegistry()
        registry.cloud = OpenAICompatibleProvider(
            "cloud_ai", "cloud", "https://approved-cloud.example/v1", "cloud-model"
        )
        consent_authority = cloud_authority()
        with tempfile.TemporaryDirectory() as folder:
            ledger = Path(folder) / "configured-uses.json"
            environment = {
                "PRISM_CLOUD_POLICY_PUBKEY": str(consent_authority.policy_pubkey),
                "PRISM_CLOUD_CONTEXT_PUBKEY": str(consent_authority.context_pubkey),
                "PRISM_CLOUD_CONSENT_CHANNEL": str(consent_authority.channel_id),
                "PRISM_CLOUD_CONSENT_LEDGER": str(ledger),
            }
            with mock.patch.object(
                server_module, "global_providers", registry,
            ), mock.patch.dict(
                os.environ, environment,
            ), mock.patch.object(
                server_module.global_buzz, "status",
                return_value={"workspace_ready": False},
            ):
                status, body = self.app_request("/api/status")
        self.assertEqual(status, 200)
        self.assertTrue(body["cloud_consent"]["dispatch_configured_for_signed_request"])
        self.assertFalse(body["cloud_consent"]["dispatch_ready_for_signed_request"])
        self.assertEqual(body["cloud_consent"]["replay_ledger"], str(ledger))
        status, body = self.app_request("/api/route", {
            "query": "public comparison task", "force_cloud_override": True,
            "local_only_policy": False,
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["target_tier"], "CLOUD_NOT_CONFIGURED")

        for headers in (
            {"Host": "attacker.example"},
            {"Host": f"127.0.0.1:{self.app_server.server_port}", "Origin": "https://attacker.example"},
        ):
            guarded = http.client.HTTPConnection("127.0.0.1", self.app_server.server_port, timeout=5)
            guarded.putrequest("GET", "/api/status", skip_host=True)
            for name, value in headers.items():
                guarded.putheader(name, value)
            guarded.endheaders()
            guarded_response = guarded.getresponse()
            guarded_body = json.loads(guarded_response.read())
            guarded.close()
            self.assertEqual((guarded_response.status, guarded_body["error"]), (403, "local_origin_required"))

        connection = http.client.HTTPConnection("127.0.0.1", self.app_server.server_port, timeout=5)
        connection.putrequest("POST", "/api/agent/run")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(1024 * 1024 + 1))
        connection.endheaders()
        response = connection.getresponse()
        body = json.loads(response.read())
        connection.close()
        self.assertEqual((response.status, body["error"]), (413, "request_too_large"))

    def test_workspace_polling_queues_refresh_instead_of_overlapping_buzz_reads(self):
        source = Path("web/app.js").read_text(encoding="utf-8")
        self.assertIn("messagesLoading: false", source)
        self.assertIn("messagesRefreshQueued: false", source)
        self.assertIn("if (state.messagesLoading)", source)
        self.assertIn("window.queueMicrotask(loadMessages)", source)
        self.assertIn('document.visibilityState === "visible"', source)
        self.assertIn('document.addEventListener("visibilitychange"', source)

    def test_production_server_keeps_status_responsive_during_long_request(self):
        started = threading.Event()
        release = threading.Event()

        class BlockingVaultHandler(VaultHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/__test_blocking_inference":
                    started.set()
                    release.wait(timeout=3)
                    self._send_json({"released": True})
                    return
                super().do_GET()

            def log_message(self, *_):
                pass

        try:
            httpd = server_module.PrismHTTPServer(("127.0.0.1", 0), BlockingVaultHandler)
        except PermissionError:
            self.skipTest("loopback listener unavailable")
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        slow_errors = []

        def slow_request():
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{httpd.server_address[1]}/__test_blocking_inference",
                    timeout=4,
                ) as response:
                    response.read()
            except Exception as exc:  # pragma: no cover - asserted below
                slow_errors.append(str(exc))

        server_thread.start()
        slow_thread = threading.Thread(target=slow_request, daemon=True)
        slow_thread.start()
        try:
            self.assertTrue(started.wait(timeout=1), "blocking request never started")
            self.assertFalse(release.is_set())
            with urllib.request.urlopen(
                f"http://127.0.0.1:{httpd.server_address[1]}/api/status", timeout=2,
            ) as response:
                self.assertEqual(response.status, 200)
                status = json.load(response)
            self.assertEqual(status["product_stage"], "local_prototype")
            self.assertFalse(release.is_set())
        finally:
            release.set()
            slow_thread.join(timeout=2)
            httpd.shutdown()
            httpd.server_close()
            server_thread.join(timeout=2)
        self.assertEqual(slow_errors, [])

    def test_live_inference_concurrency_evidence_rejects_latency_or_delivery_tampering(self):
        evidence_path = Path("evidence/live-inference-concurrency-v1.json")
        current = validate_live_inference_concurrency_evidence(evidence_path)
        self.assertTrue(current["passed"], current["errors"])
        original = json.loads(evidence_path.read_text(encoding="utf-8"))
        mutations = {
            "latency": lambda record: record["responsiveness"].update(
                max_status_latency_ms=2_001,
            ),
            "delivery": lambda record: record["product_evidence"].update(
                answer_signature_verified=False,
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.NamedTemporaryFile(
                "w", suffix=".json", encoding="utf-8",
            ) as handle:
                changed = json.loads(json.dumps(original))
                mutate(changed)
                json.dump(changed, handle)
                handle.flush()
                rejected = validate_live_inference_concurrency_evidence(Path(handle.name))
            self.assertFalse(rejected["passed"])

    def test_buzz_message_canonical_url_opens_discussion_event(self):
        if not self.app_server:
            self.skipTest("loopback socket binding unavailable")
        event_id = "signed-event-123"
        with (
            mock.patch.object(
                server_module.global_buzz,
                "room",
                return_value={"room_id": "project_titan_lbo", "channel_id": "channel"},
            ),
            mock.patch.object(
                server_module.global_buzz,
                "send",
                return_value={"event_id": event_id},
            ),
        ):
            status, body = self.app_request(
                "/api/workspace/messages",
                {"room": "project_titan_lbo", "content": "Review this point."},
            )
        self.assertEqual(status, 201)
        self.assertEqual(
            body["canonical_path"],
            f"/rooms/project_titan_lbo/discussion?event={event_id}",
        )

    def test_guarded_bonsai_reply_is_bound_to_signed_events_and_persistent_trace(self):
        if not self.app_server:
            self.skipTest("loopback socket binding unavailable")
        result = DealRoomChatResult(
            response="- Price: $104.00 [term-sheet.md#text:block:00001]",
            provider="local_bonsai",
            model="27b@q1_0",
            latency_ms=14.0,
            usage={"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
            citations=["[term-sheet.md#text:block:00001]"],
            retrieved_passages=[{
                "citation": "[term-sheet.md#text:block:00001]",
                "source_sha256": "source-hash",
                "requested_parts": ["consideration"],
            }],
            raw_metadata={"protocol": "lmstudio_native_chat"},
            requested_parts=["consideration"],
            part_citations={"consideration": ["[term-sheet.md#text:block:00001]"]},
            guard_version="deal_room_chat_guard_v1",
            inference_attempts=1,
        )
        with tempfile.TemporaryDirectory() as folder:
            tracer = ArizeObservabilityTracer(str(Path(folder, "traces.jsonl")))
            with (
                mock.patch.object(server_module, "global_tracer", tracer),
                mock.patch.object(
                    server_module.global_buzz, "room",
                    return_value={"room_id": "project_titan_lbo", "channel_id": "channel"},
                ),
                mock.patch.object(
                    server_module.global_buzz, "send",
                    return_value={"event_id": "q" * 64},
                ),
                mock.patch.object(
                    server_module.global_buzz, "send_as_agent",
                    return_value={"event_id": "a" * 64},
                ) as send_as_agent,
                mock.patch.object(server_module, "answer_deal_room_question", return_value=result),
            ):
                status, body = self.app_request("/api/workspace/messages", {
                    "room": "project_titan_lbo",
                    "content": "What is the per-share consideration?",
                    "ask_bonsai": True,
                })
            restarted = ArizeObservabilityTracer(str(Path(folder, "traces.jsonl")))
        self.assertEqual(status, 201)
        self.assertEqual(body["agent_reply"]["trace_id"], restarted.traces[0].trace_id)
        self.assertEqual(restarted.traces[0].metadata["question_event_id"], "q" * 64)
        self.assertEqual(restarted.traces[0].metadata["answer_event_id"], "a" * 64)
        self.assertEqual(
            restarted.traces[0].metadata["result_state"],
            "guard_passed_and_signed_to_buzz",
        )
        published = send_as_agent.call_args.args[1]
        self.assertIn(f"trace={restarted.traces[0].trace_id}", published)
        self.assertIn("deal_room_chat_guard_v1", published)
        self.assertIn("source_class=synthetic_engineering_fixture", published)
        self.assertRegex(published, r"provenance=[0-9a-f]{64}")
        self.assertRegex(published, r"source_snapshot=[0-9a-f]{64}")
        self.assertEqual(
            restarted.traces[0].metadata["source_classification"],
            "synthetic_engineering_fixture",
        )
        self.assertEqual(
            restarted.traces[0].metadata["source_provenance_sha256"],
            body["agent_reply"]["source_provenance_sha256"],
        )

    def test_chat_rejects_publication_when_complete_folder_snapshot_changes(self):
        if not self.app_server:
            self.skipTest("loopback socket binding unavailable")
        result = DealRoomChatResult(
            response="- Price: $104.00 [term-sheet.md#text:block:00001]",
            provider="local_bonsai",
            model="27b@q1_0",
            latency_ms=14.0,
            usage={"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
            citations=["[term-sheet.md#text:block:00001]"],
            retrieved_passages=[],
            raw_metadata={},
            requested_parts=["consideration"],
            part_citations={"consideration": ["[term-sheet.md#text:block:00001]"]},
            guard_version="deal_room_chat_guard_v1",
            inference_attempts=1,
        )
        tracer = ArizeObservabilityTracer()
        with (
            mock.patch.object(server_module, "global_tracer", tracer),
            mock.patch.object(
                server_module.global_buzz, "room",
                return_value={"room_id": "project_titan_lbo", "channel_id": "channel"},
            ),
            mock.patch.object(
                server_module.global_buzz, "send", return_value={"event_id": "q" * 64},
            ),
            mock.patch.object(
                server_module.global_buzz, "send_as_agent", return_value={"event_id": "r" * 64},
            ) as send_as_agent,
            mock.patch.object(server_module, "answer_deal_room_question", return_value=result),
            mock.patch.object(
                server_module, "inspect_local_deal_room",
                side_effect=[
                    {"preview": {"preview_sha256": "a" * 64}},
                    {"preview": {"preview_sha256": "b" * 64}},
                ],
            ),
        ):
            status, body = self.app_request("/api/workspace/messages", {
                "room": "project_titan_lbo",
                "content": "What is the per-share consideration?",
                "ask_bonsai": True,
            })
        self.assertEqual(status, 201)
        self.assertEqual(body["agent_reply"]["answer_state"], "rejected")
        self.assertEqual(
            tracer.traces[0].metadata["source_snapshot_state"], "changed_during_chat",
        )
        published = send_as_agent.call_args.args[1]
        self.assertIn("Bonsai answer rejected", published)
        self.assertNotIn(result.response, published)

    def test_rejected_bonsai_draft_is_a_signed_visible_state_not_a_false_send_failure(self):
        if not self.app_server:
            self.skipTest("loopback socket binding unavailable")
        with tempfile.TemporaryDirectory() as folder:
            tracer = ArizeObservabilityTracer(str(Path(folder, "traces.jsonl")))
            with (
                mock.patch.object(server_module, "global_tracer", tracer),
                mock.patch.object(
                    server_module.global_buzz, "room",
                    return_value={"room_id": "project_titan_lbo", "channel_id": "channel"},
                ),
                mock.patch.object(
                    server_module.global_buzz, "send",
                    return_value={"event_id": "q" * 64},
                ),
                mock.patch.object(
                    server_module.global_buzz, "send_as_agent",
                    return_value={"event_id": "r" * 64},
                ) as send_as_agent,
                mock.patch.object(
                    server_module, "answer_deal_room_question",
                    side_effect=DealRoomChatError("no admitted citation appears in the answer"),
                ),
            ):
                status, body = self.app_request("/api/workspace/messages", {
                    "room": "project_titan_lbo",
                    "content": "What is the first-year ROI?",
                    "ask_bonsai": True,
                })
            restarted = ArizeObservabilityTracer(str(Path(folder, "traces.jsonl")))
        self.assertEqual(status, 201)
        self.assertEqual(body["agent_reply"]["answer_state"], "rejected")
        self.assertEqual(body["agent_reply"]["event_id"], "r" * 64)
        self.assertEqual(restarted.traces[0].metadata["question_event_id"], "q" * 64)
        self.assertEqual(restarted.traces[0].metadata["rejection_event_id"], "r" * 64)
        self.assertEqual(restarted.traces[0].metadata["result_state"], "rejected_before_buzz_answer")
        self.assertEqual(
            restarted.traces[0].metadata["rejected_response_sha256"],
            hashlib.sha256(b"").hexdigest(),
        )
        self.assertFalse(restarted.traces[0].evaluations[0].passed)
        published = send_as_agent.call_args.args[1]
        self.assertIn("Bonsai answer rejected", published)
        self.assertIn("No answer or accuracy claim was accepted", published)
        self.assertIn(restarted.traces[0].trace_id, published)

    def test_status_distinguishes_configured_provider_from_baseline_engine(self):
        if not self.app_server:
            self.skipTest("loopback socket binding unavailable")
        original = server_module.global_providers
        configured = ProviderRegistry()
        configured.local = OpenAICompatibleProvider(
            "local_bonsai", "local", "http://127.0.0.1:65534", "configured-model"
        )
        try:
            server_module.global_providers = configured
            with mock.patch.object(
                server_module, "global_tracer", ArizeObservabilityTracer()
            ):
                status, body = self.app_request("/api/status")
        finally:
            server_module.global_providers = original
        self.assertEqual(status, 200)
        self.assertTrue(body["local_inference_configured"])
        self.assertFalse(body["local_inference_invoked_in_process"])
        self.assertFalse(body["local_inference_invoked"])
        self.assertIsNone(body["local_inference_invocation_evidence"])
        self.assertEqual(body["configured_local_model_name"], "configured-model")
        self.assertEqual(body["configured_local_provider_network_scope"], "loopback_ip_literal")
        self.assertEqual(body["network_binding_scope"], "prism_http_server")
        self.assertIsNone(body["last_invoked_local_model"])
        self.assertFalse(body["local_inference_recorded_history"])
        self.assertIsNone(body["current_process_local_model"])
        self.assertEqual(body["trace_store"]["format"], "memory_only")
        self.assertEqual(
            body["trace_store"]["integrity"],
            "ephemeral_unpersisted",
        )
        self.assertFalse(body["trace_store"]["signed"])
        self.assertFalse(body["trace_store"]["externally_anchored"])
        for field in (
            "architecture_metrics_state", "effective_bitwidth", "weight_size_gb",
            "kv_cache_rate_bytes", "peak_vram_100k_gb", "peak_vram_262k_gb",
            "intelligence_density", "bfcl_v3_score", "comparisons", "energy_comparisons",
        ):
            self.assertNotIn(field, body)
        self.assertEqual(
            body["analysis_engine"],
            "provider_backed_agent_with_deterministic_baseline",
        )
        self.assertTrue(any(
            "configuration alone does not prove" in item for item in body["limitations"]
        ))

    def test_status_separates_measured_deployment_from_provider_configuration(self):
        if not self.app_server:
            self.skipTest("loopback socket binding unavailable")
        measured = {
            "verified": True,
            "measurement_state": "current_host_artifacts_and_process_measured",
            "model": "27b@q1_0",
            "artifact_sha256": "a" * 64,
            "artifact_count": 2,
            "runtime": {"version": "2.28.2", "effective_config": {
                "fitted_context_length": "16384", "parallel_slots": "4",
            }},
            "hardware": {"machine_model": "MacTest", "chip_type": "Apple Test", "physical_memory": "48 GB"},
            "catalog_size_matches_artifact": False,
            "errors": [],
            "meaning": "Artifact identity is separate from invocation.",
        }
        providers = ProviderRegistry()
        with mock.patch.object(server_module, "global_providers", providers), mock.patch.object(
            server_module, "global_tracer", ArizeObservabilityTracer(),
        ), mock.patch.object(
            server_module, "measured_local_deployment_status", return_value=measured,
        ):
            status, body = self.app_request("/api/status")
        self.assertEqual(status, 200)
        self.assertFalse(body["local_inference_configured"])
        self.assertFalse(body["local_inference_invoked_in_process"])
        self.assertTrue(body["measured_local_deployment"]["verified"])
        self.assertEqual(body["measured_local_deployment"]["artifact_count"], 2)
        self.assertFalse(body["measured_local_deployment"]["catalog_size_matches_artifact"])

    def test_status_discloses_single_room_acp_source_scope(self):
        if not self.app_server:
            self.skipTest("loopback socket binding unavailable")
        channel = "4b668cff-fb84-4129-ae87-949e267fe657"
        with mock.patch.dict(os.environ, {
            "PRISM_BUZZ_ACP_ROOM_ID": "project_titan_lbo",
            "PRISM_BUZZ_ACP_CHANNEL_ID": channel,
            "PRISM_BUZZ_ACP_SOURCE_SCOPE": "/private/deals/titan",
        }):
            status, body = self.app_request("/api/status")
        self.assertEqual(status, 200)
        scope = body["buzz_acp_scope"]
        self.assertTrue(scope["configured"])
        self.assertEqual(scope["room_id"], "project_titan_lbo")
        self.assertEqual(scope["channel_id"], channel)
        self.assertEqual(scope["source_scope"], "/private/deals/titan")
        self.assertEqual(scope["subscription"], "single_room_mentions")
        self.assertEqual(scope["respond_to"], "owner_only")
        self.assertEqual(scope["memory"], "disabled")
        self.assertIn("only for this exact room", scope["meaning"])

    def test_status_separates_persisted_history_from_current_process_invocation(self):
        if not self.app_server:
            self.skipTest("loopback socket binding unavailable")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "traces.jsonl"
            writer = ArizeObservabilityTracer(str(path))
            trace = ArizeTraceRecord(
                trace_id="trc_prior_process",
                session_id="room",
                timestamp=1.0,
                query="first_pass_underwriting",
                response="prior output",
                model_name="27b@q1_0",
                routed_tier="LOCAL_BONSAI_27B",
                total_tokens=1,
                prompt_tokens=1,
                completion_tokens=0,
                total_latency_ms=1.0,
                energy_per_token_mwh=None,
                total_energy_mwh=None,
                vram_peak_gb=None,
                metadata={"provider_id": "local_bonsai"},
            )
            writer.record_trace(trace)
            restarted = ArizeObservabilityTracer(str(path))
            with mock.patch.object(server_module, "global_tracer", restarted):
                status, body = self.app_request("/api/status")
                self.assertEqual(status, 200)
                self.assertTrue(body["local_inference_recorded_history"])
                self.assertTrue(body["local_inference_invoked"])
                self.assertFalse(body["local_inference_invoked_in_process"])
                self.assertEqual(
                    body["local_inference_invocation_evidence"],
                    "recorded_trace_history",
                )
                self.assertIsNone(body["current_process_local_model"])
                self.assertEqual(
                    body["trace_store"]["format"],
                    "hash_chained_local_jsonl_v1",
                )
                self.assertTrue(body["trace_store"]["verified"])
                self.assertFalse(body["trace_store"]["signed"])
                self.assertFalse(body["trace_store"]["externally_anchored"])

                restarted.record_trace(ArizeTraceRecord(
                    **{**trace.__dict__, "trace_id": "trc_current_process"}
                ))
                status, body = self.app_request("/api/status")
                self.assertEqual(status, 200)
                self.assertTrue(body["local_inference_invoked_in_process"])
                self.assertEqual(
                    body["local_inference_invocation_evidence"],
                    "current_process_trace",
                )
                self.assertEqual(body["current_process_local_model"], "27b@q1_0")

    def test_live_trace_ledger_tamper_is_a_visible_dependency_failure(self):
        if not self.app_server:
            self.skipTest("loopback socket binding unavailable")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "traces.jsonl"
            tracer = ArizeObservabilityTracer(str(path))
            tracer.record_trace(ArizeTraceRecord(
                trace_id="trc_visible_tamper",
                session_id="room",
                timestamp=1.0,
                query="first_pass_underwriting",
                response="prior output",
                model_name="27b@q1_0",
                routed_tier="LOCAL_BONSAI_27B",
                total_tokens=1,
                prompt_tokens=1,
                completion_tokens=0,
                total_latency_ms=1.0,
                energy_per_token_mwh=None,
                total_energy_mwh=None,
                vram_peak_gb=None,
            ))
            entry = json.loads(path.read_text(encoding="utf-8"))
            entry["record"]["response"] = "edited after commit"
            path.write_text(json.dumps(entry, sort_keys=True) + "\n", encoding="utf-8")
            with mock.patch.object(server_module, "global_tracer", tracer):
                status, body = self.app_request("/api/status")
                self.assertEqual(status, 503)
                self.assertEqual(body["error"], "trace_store_integrity_error")
                self.assertIn("hash mismatch", body["detail"])

    def test_corrupt_buzz_room_registry_is_visible_and_fails_workspace_closed(self):
        if not self.app_server:
            self.skipTest("loopback socket binding unavailable")
        with tempfile.TemporaryDirectory() as folder:
            broken = BuzzBridge(folder)
            broken.rooms_path.parent.mkdir(parents=True)
            broken.rooms_path.write_text("{broken", encoding="utf-8")
            with mock.patch.object(server_module, "global_buzz", broken):
                status, workspace = self.app_request(
                    "/api/workspace?room=project_titan_lbo"
                )
                self.assertEqual(status, 503)
                self.assertEqual(workspace["error"], "buzz_registry_unavailable")
                status, runtime = self.app_request("/api/status")
                self.assertEqual(status, 200)
                self.assertEqual(runtime["buzz"]["room_registry_state"], "corrupt")
                self.assertFalse(runtime["buzz"]["workspace_ready"])
                self.assertIn("invalid JSON", runtime["buzz"]["room_registry_error"])

    def test_models_endpoint_does_not_present_research_catalog_as_runtime_discovery(self):
        if not self.app_server:
            self.skipTest("loopback socket binding unavailable")
        status, runtime = self.app_request("/api/models")
        self.assertEqual(status, 200)
        self.assertIn("provider_status", runtime)
        self.assertNotIn("models", runtime)
        self.assertIn("does not prove reachability", runtime["meaning"])

        status, research = self.app_request("/api/research/model-catalog")
        self.assertEqual(status, 200)
        self.assertEqual(research["measurement_state"], "unverified_research_catalog")
        self.assertTrue(research["models"])
        self.assertTrue(all(
            item["status"] == "catalog_only_not_runtime_discovery"
            for item in research["models"]
        ))

    def test_live_http_opens_and_executes_an_arbitrary_private_folder(self):
        if not self.app_server:
            self.skipTest("sandbox forbids loopback socket binding; run this test outside the managed sandbox")
        with tempfile.TemporaryDirectory() as folder:
            shutil.copytree("deal_rooms/sample_ma_acquisition", folder, dirs_exist_ok=True)
            _write_test_xlsx(f"{folder}/05_LBO_Model.xlsx")
            with mock.patch.object(
                server_module.global_buzz,
                "ensure_room",
                return_value={"room_id": "test", "channel_id": "test-channel"},
            ) as ensure_room, mock.patch.object(
                server_module,
                "commit_local_deal_room",
                side_effect=lambda room: server_module.CUSTOM_DEAL_ROOMS.update(
                    {room["id"]: room}
                ),
            ):
                preview_status, preview = self.app_request(
                    "/api/deal-room/preview", {"folder_path": folder}
                )
                self.assertEqual(preview_status, 200)
                self.assertEqual(preview["preview_state"], "ready")
                self.assertEqual(preview["document_count"], 5)
                self.assertTrue(preview["source_files_stay_local"])
                self.assertFalse(preview["buzz_write_performed"])
                self.assertFalse(preview["room_registered"])
                self.assertEqual(len(preview["preview_sha256"]), 64)
                ensure_room.assert_not_called()

                missing_status, missing_preview = self.app_request(
                    "/api/deal-room/open", {"folder_path": folder}
                )
                self.assertEqual((missing_status, missing_preview["error"]), (
                    409, "deal_room_preview_required",
                ))
                ensure_room.assert_not_called()

                status, opened = self.app_request(
                    "/api/deal-room/open", {
                        "folder_path": folder,
                        "preview_sha256": preview["preview_sha256"],
                    }
                )
            self.addCleanup(
                server_module.CUSTOM_DEAL_ROOMS.pop,
                opened.get("room_id", ""),
                None,
            )
            self.assertEqual(status, 201)
            self.assertTrue(opened["room_id"].startswith("local_"))
            self.assertEqual(opened["total_documents"], 5)
            self.assertEqual(opened["folder_path"], os.path.realpath(folder))

            status, loaded = self.app_request(f"/api/deal-room?room={opened['room_id']}")
            self.assertEqual(status, 200)
            self.assertEqual(loaded["room_id"], opened["room_id"])
            workbook = next(
                document for document in loaded["documents"]
                if document["filename"] == "05_LBO_Model.xlsx"
            )
            self.assertEqual(workbook["file_type"], "xlsx")
            self.assertEqual(workbook["tables"][0]["caption"], "LBO Model")
            self.assertEqual(workbook["tables"][0]["matrix"][2], ["Debt / EBITDA", "5.0x"])
            self.assertIn("xlsx:sheet:1", workbook["anchors"])
            self.assertEqual(workbook["parser_facts"]["cached_formula_cell_count"], 1)
            self.assertEqual(workbook["parser_facts"]["unevaluated_formula_cell_count"], 1)
            self.assertIn("never recalculated", workbook["parser_facts"]["formula_policy"])
            self.assertEqual(workbook["parser_facts"]["formatted_numeric_cell_count"], 2)
            self.assertEqual(workbook["parser_facts"]["unsupported_number_format_cell_count"], 1)

            status, result = self.app_request("/api/agent/run", {
                "deal_room": opened["room_id"],
                "prompt": "Run sensitivity stress-test modeling a 10% and 20% drop in EBITDA.",
                "runtime": "baseline",
            })
            self.assertEqual(status, 200)
            self.assertEqual(result["execution_mode"], "deterministic_template")
            self.assertEqual(result["generation_attempts"], 0)
            self.assertEqual(result["rejected_scope_violations"], [])
            self.assertIn("SENSITIVITY ANALYSIS RESULTS", result["code_execution_stdout"])

            status, audit = self.app_request("/api/audit", {"deal_room": opened["room_id"]})
            self.assertEqual(status, 200)
            self.assertEqual(audit["total_documents_analyzed"], 5)
            self.assertFalse(audit["evaluation_summary"]["all_evals_passed"])

            status, evals = self.app_request("/api/evals")
            self.assertEqual(status, 200)
            self.assertIsNone(evals["avg_faithfulness"])
            self.assertIsNone(evals["avg_tabular_fixture_cell_match"])
            agent_trace = next(
                trace for trace in evals["traces"] if trace["trace_id"] == result["trace_id"]
            )
            audit_trace = next(
                trace for trace in evals["traces"] if trace["trace_id"] == audit["arize_trace_id"]
            )
            self.assertIsInstance(agent_trace["metadata"]["sandbox_isolation"], dict)
            self.assertIsInstance(audit_trace["metadata"]["sandbox_isolation"], dict)
            if sys.platform == "darwin":
                self.assertTrue(
                    agent_trace["metadata"]["sandbox_isolation"]["os_policy_enforced"]
                )
                self.assertTrue(
                    audit_trace["metadata"]["sandbox_isolation"]["os_policy_enforced"]
                )
                selected_root = os.path.realpath(folder)
                for trace in (agent_trace, audit_trace):
                    denied_roots = trace["metadata"]["sandbox_isolation"][
                        "file_read_denied_roots"
                    ]
                    self.assertTrue(
                        any(
                            os.path.commonpath((selected_root, root)) == root
                            for root in denied_roots
                        ),
                        denied_roots,
                    )

        status, body = self.app_request(
            "/api/deal-room/open", {"folder_path": "/definitely/not/a/prism/folder"}
        )
        self.assertEqual((status, body["error"]), (404, "folder_not_found"))

    def test_folder_change_after_preview_fails_before_buzz_write(self):
        if not self.app_server:
            self.skipTest("loopback socket binding unavailable")
        with tempfile.TemporaryDirectory() as folder:
            nested = Path(folder) / "nested"
            nested.mkdir()
            source = nested / "source.md"
            source.write_text("Initial authorized source", encoding="utf-8")
            status, preview = self.app_request(
                "/api/deal-room/preview", {"folder_path": folder}
            )
            self.assertEqual(status, 200)
            source.write_text("Changed after the human preview", encoding="utf-8")
            with mock.patch.object(server_module.global_buzz, "ensure_room") as ensure_room, mock.patch.object(
                server_module, "commit_local_deal_room",
            ) as commit_room:
                status, result = self.app_request(
                    "/api/deal-room/open", {
                        "folder_path": folder,
                        "preview_sha256": preview["preview_sha256"],
                    },
                )
            self.assertEqual((status, result["error"]), (
                409, "deal_room_changed_since_preview",
            ))
            self.assertNotEqual(
                result["preview"]["preview_sha256"], preview["preview_sha256"],
            )
            ensure_room.assert_not_called()
            commit_room.assert_not_called()

    def test_empty_folder_cannot_create_buzz_room(self):
        if not self.app_server:
            self.skipTest("loopback socket binding unavailable")
        with tempfile.TemporaryDirectory() as folder:
            status, preview = self.app_request(
                "/api/deal-room/preview", {"folder_path": folder}
            )
            self.assertEqual(status, 200)
            self.assertEqual(preview["preview_state"], "blocked_no_supported_files")
            with mock.patch.object(server_module.global_buzz, "ensure_room") as ensure_room, mock.patch.object(
                server_module, "commit_local_deal_room",
            ) as commit_room:
                status, result = self.app_request(
                    "/api/deal-room/open", {
                        "folder_path": folder,
                        "preview_sha256": preview["preview_sha256"],
                    },
                )
            self.assertEqual((status, result["error"]), (400, "no_supported_files"))
            ensure_room.assert_not_called()
            commit_room.assert_not_called()

    def test_nested_only_folder_is_indexed_with_relative_identity(self):
        if not self.app_server:
            self.skipTest("loopback socket binding unavailable")
        with tempfile.TemporaryDirectory() as folder:
            nested = Path(folder) / "nested"
            nested.mkdir()
            (nested / "source.md").write_text("Nested authorized source", encoding="utf-8")
            status, preview = self.app_request(
                "/api/deal-room/preview", {"folder_path": folder}
            )
            self.assertEqual(status, 200)
            self.assertEqual(preview["preview_state"], "ready")
            self.assertEqual(preview["document_count"], 1)
            self.assertEqual(preview["files"][0]["filename"], "nested/source.md")
            self.assertEqual(preview["warnings"], [])
            with mock.patch.object(
                server_module.global_buzz, "ensure_room",
                return_value={"room_id": "test", "channel_id": "test-channel"},
            ) as ensure_room, mock.patch.object(
                server_module, "commit_local_deal_room",
                side_effect=lambda room: server_module.CUSTOM_DEAL_ROOMS.update(
                    {room["id"]: room}
                ),
            ) as commit_room:
                status, result = self.app_request(
                    "/api/deal-room/open", {
                        "folder_path": folder,
                        "preview_sha256": preview["preview_sha256"],
                    },
                )
            self.addCleanup(server_module.CUSTOM_DEAL_ROOMS.pop, result["room_id"], None)
            self.assertEqual(status, 201)
            self.assertEqual(result["documents"][0]["filename"], "nested/source.md")
            ensure_room.assert_called_once()
            commit_room.assert_called_once()

    def test_recursive_parser_disambiguates_duplicate_basenames_and_blocks_symlink_directories(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside:
            root = Path(folder)
            for dirname, content in (("legal", "Legal source"), ("finance", "Finance source")):
                directory = root / dirname
                directory.mkdir()
                (directory / "summary.md").write_text(content, encoding="utf-8")
            outside_path = Path(outside)
            (outside_path / "secret.md").write_text("Must not be traversed", encoding="utf-8")
            try:
                (root / "linked").symlink_to(outside_path, target_is_directory=True)
            except OSError:
                self.skipTest("directory symlinks are unavailable")
            parser = DealRoomParser()
            documents = parser.parse_deal_room_folder(folder)
        self.assertEqual(
            [document.filename for document in documents],
            ["finance/summary.md", "legal/summary.md"],
        )
        self.assertEqual(len({document.doc_id for document in documents}), 2)
        self.assertEqual(
            {document.metadata["relative_path"] for document in documents},
            {"finance/summary.md", "legal/summary.md"},
        )
        self.assertEqual(parser.last_warnings, [{
            "filename": "linked",
            "error": "Symbolic links are not followed",
        }])

    def test_recursive_parser_enforces_depth_file_count_and_total_byte_limits(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            deep = root
            for index in range(3):
                deep = deep / f"level-{index}"
                deep.mkdir()
            (deep / "hidden.md").write_text("Beyond admitted depth", encoding="utf-8")
            parser = DealRoomParser()
            parser.max_folder_depth = 2
            self.assertEqual(parser.parse_deal_room_folder(folder), [])
            self.assertEqual(parser.last_warnings, [{
                "filename": "level-0/level-1/level-2",
                "error": "Directory exceeds 2 level parser depth limit",
            }])

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for index in range(3):
                (root / f"source-{index}.md").write_text("x", encoding="utf-8")
            parser = DealRoomParser()
            parser.max_folder_files = 2
            with self.assertRaisesRegex(ValueError, "visible file parser limit"):
                parser.parse_deal_room_folder(folder)

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "a.md").write_text("1234", encoding="utf-8")
            (root / "b.md").write_text("5678", encoding="utf-8")
            parser = DealRoomParser()
            parser.max_folder_bytes = 7
            with self.assertRaisesRegex(ValueError, "admitted byte parser limit"):
                parser.parse_deal_room_folder(folder)

    def test_nested_retrieval_uses_exact_relative_citation_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "legal").mkdir()
            (root / "finance").mkdir()
            (root / "legal" / "summary.md").write_text(
                "# Legal\nThe reverse termination fee is $15 million.", encoding="utf-8",
            )
            (root / "finance" / "summary.md").write_text(
                "# Finance\nDebt financing commitments total $120 million.", encoding="utf-8",
            )
            results = query_deal_room(root, "reverse termination fee", limit=8)
        self.assertEqual(results[0]["filename"], "legal/summary.md")
        self.assertTrue(results[0]["citation"].startswith("[legal/summary.md#"))
        self.assertNotIn("finance/summary.md", {
            result["filename"] for result in results
            if "termination fee" in result["text"].lower()
        })

    def test_real_first_pass_retrieval_admits_screen_specific_nested_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "transaction").mkdir()
            (root / "commercial").mkdir()
            (root / "transaction" / "overview.md").write_text(
                "Transaction parties purchase price structure consideration closing chronology. "
                "Financing debt equity leverage revenue EBITDA valuation risk covenant approval.",
                encoding="utf-8",
            )
            screen_source = root / "commercial" / "customer-risk.md"
            screen_source.write_text(
                "Acme renewal exposure is thirty-four percent of annual recurring value and "
                "renews next quarter.",
                encoding="utf-8",
            )
            screen = "Assess Acme renewal exposure."
            passages = retrieve_first_pass_evidence(
                root, limit=2, investment_screen=screen,
            )
            generic_only = retrieve_first_pass_evidence(root, limit=2)

        matched = next(
            passage for passage in passages
            if passage["filename"] == "commercial/customer-risk.md"
        )
        self.assertIn("investment_screen", matched["retrieval_reasons"])
        self.assertTrue(matched["citation"].startswith(
            "[commercial/customer-risk.md#",
        ))
        self.assertNotIn(
            "commercial/customer-risk.md",
            {passage["filename"] for passage in generic_only},
        )

    def test_screen_bound_live_first_pass_evidence_rejects_snapshot_or_route_tamper(self):
        evidence = Path("evidence/bonsai-first-pass-titan-screen-bound-v1.json").resolve()
        self.assertTrue(validate_screen_bound_first_pass_evidence(evidence)["passed"])
        record = json.loads(evidence.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as folder:
            tampered = Path(folder) / "tampered.json"
            record["artifact"]["source_snapshot_sha256"] = "0" * 64
            record["model_failure_trace"]["model_name"] = "not-bonsai"
            tampered.write_text(json.dumps(record), encoding="utf-8")
            result = validate_screen_bound_first_pass_evidence(tampered)
        self.assertFalse(result["passed"])
        self.assertTrue(any("source_snapshot_sha256" in error for error in result["errors"]))
        self.assertTrue(any("live Bonsai route" in error for error in result["errors"]))

    def test_custom_room_registry_survives_reload_and_rejects_identity_drift(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as state:
            source = Path(folder).resolve()
            (source / "source.md").write_text("Authorized local source", encoding="utf-8")
            registry = Path(state) / "registrations.v1.json"
            room = server_module.prepare_local_deal_room(str(source))
            server_module.persist_local_deal_rooms({room["id"]: room}, registry)

            loaded = server_module.load_local_deal_rooms(registry)
            self.assertEqual(loaded, {room["id"]: room})
            self.assertEqual(registry.stat().st_mode & 0o777, 0o600)

            value = json.loads(registry.read_text(encoding="utf-8"))
            value["rooms"][0]["id"] = "local_unrelated"
            registry.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid room identity"):
                server_module.load_local_deal_rooms(registry)


if __name__ == "__main__":
    unittest.main()
