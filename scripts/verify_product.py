#!/usr/bin/env python3
"""Evidence-based Prism Vault verifier.

This script intentionally does not claim that the target architecture is
complete. It verifies component behavior and a selected runtime benchmark,
then reports unmeasured external gates separately.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from core.ai_provider import ProviderRegistry  # noqa: E402
from core.benchmark import run_benchmark  # noqa: E402
from core.first_pass_benchmark import (  # noqa: E402
    evaluate_development_responses,
    schema_errors,
    validate_contract,
)
from core.goal_completion import evaluate_goal_completion  # noqa: E402
from core.customer_demo import (  # noqa: E402
    validate_content_graph,
    validate_customer_demo_browser_record,
    validate_customer_demo_scope,
)
from core.xlsx_benchmark import evaluate_xlsx_display_benchmark  # noqa: E402
from core.nostr_event import nostr_event_errors  # noqa: E402
from core.deployment_evidence import validate_deployment_record  # noqa: E402
from core.judge_calibration import validate_saved_judge_calibration  # noqa: E402
from core.pricing_poc import validate_saved_pricing_poc  # noqa: E402
from core.sealed_test_control import sealed_test_preflight  # noqa: E402
from core.trace_anchor import validate_trace_anchor_receipt  # noqa: E402
from core.network_observation import validate_network_observation  # noqa: E402
from core.ocr_accuracy_benchmark import validate_saved_ocr_accuracy  # noqa: E402
from core.oracle_context_diagnostic import validate_saved_oracle_context  # noqa: E402
from core.evidence_manifest import (  # noqa: E402
    engineering_source_manifest,
    source_manifest_errors,
)
from core.candidate_source_review import (  # noqa: E402
    build_candidate_source_review_packet,
    evaluate_source_review_state,
    packet_sha256 as candidate_packet_sha256,
)
from core.first_pass_review import (  # noqa: E402
    build_review_packet,
    load_output_reviewer_roster,
    packet_sha256,
)
import server as server_module  # noqa: E402
from server import DEAL_ROOM_CATALOG  # noqa: E402


def resolve_pricing_poc_events(event_ids: set[str], channel_id: str) -> dict:
    return server_module.global_buzz.events_by_ids(event_ids, channel_id=channel_id)


PROHIBITED_RUNTIME_CLAIMS = [
    "Production Ready (Workstation Validated)",
    "AIR-GAP ACTIVE (0 EGRESS)",
    "eBPF Packet Filter  : ACTIVE",
    "Python code synthesized by Bonsai 27B",
    "Bonsai_27B_Code_Synthesis",
    "Notification dispatched to Investment Committee",
    "immutable local audit trail",
    "SovereignCodingAgent",
    "Docling_AST_Folder_Ingestion",
    "Docling AST Object",
    "We adopt Docling",
    "No weights are installed and no hardware measurements have been performed.",
    "Hardware efficiency, general coding reliability, domain approval, and cold-restart reproduction remain unverified.",
    "Completed locally (network not measured)",
    "Executed successfully.",
    "Not copied to Buzz",
    "not copied into Buzz",
    "This module does not perform language-model inference.",
]
RUNTIME_SURFACES = [
    PROJECT_ROOT / "README.md",
    PROJECT_ROOT / "server.py",
    PROJECT_ROOT / "prismctl",
    PROJECT_ROOT / "web" / "index.html",
    PROJECT_ROOT / "web" / "app.js",
] + sorted((PROJECT_ROOT / "core").glob("*.py"))

DOCUMENT_SURFACES = sorted((PROJECT_ROOT / "docs").glob("*.md"))
PROHIBITED_DOCUMENT_ASSERTIONS = [
    "Status**: Approved target state",
    "Status**: Approved target architecture",
    "✅ Approved",
    "Security & Air-Gap Compliance Guarantees",
    "definitive **Build vs. Buy decision framework**",
    "Prism Vault is an enterprise-grade",
    "It operates entirely offline",
    "## Definitive Build vs. Buy Matrix",
    "Prism Vault uses **Ternary Bonsai 27B** as the flagship model",
    "without risking container escape or external network leaks",
    "See the immutable",
    "separate immutable JSON",
    "preserves 94.6% of FP16 reasoning",
    "achieving up to 8.4x speedups",
    "We BUILD custom fused",
    "We ADOPT Docling",
    "We BUILD an internal orchestrator",
    "stored in local cryptographically signed JSONL",
    "Default Path (Local Air-Gap)",
    "PrismML organizes enterprise AI into two immutable rails",
    "Bonsai 27B holds the entire deal room in memory simultaneously",
    "Search Buzz events/media for a seeded secret source string",
]

# Current measurements belong in versioned JSON evidence. Repeating volatile
# values in prose caused the benchmark card to describe an older run as the
# current run. Keep prose tied to the record instead of copying values that
# change whenever verification is refreshed.
PROHIBITED_VOLATILE_DOCUMENT_PATTERNS = [
    (
        re.compile(r"\bMean end-to-end latency was\s+[\d,.]+\s+ms per case", re.I),
        "inline current-run latency instead of a versioned evidence reference",
    ),
    (
        re.compile(r"\bBionic PID\s+\d+\s+exited", re.I),
        "inline current-run process identity instead of a versioned evidence reference",
    ),
    (
        re.compile(r"\bpassed all\s+\d+\s+component tests\b", re.I),
        "inline current test count instead of a versioned evidence reference",
    ),
    (
        re.compile(r"\bfull\s+\d+-test suite\b", re.I),
        "inline current test count instead of a versioned evidence reference",
    ),
]

REQUIRED_REALITY_TESTS = {
    "goal_completion_current_demo_positive_control": "test_goal_completion.GoalCompletionGuardTests.test_current_demo_milestones_complete_goal",
    "goal_completion_scope_guard": "test_goal_completion.GoalCompletionGuardTests.test_missing_scope_fails_closed",
    "goal_completion_fresh_browser_guard": "test_goal_completion.GoalCompletionGuardTests.test_missing_fresh_browser_record_fails_closed",
    "goal_completion_runtime_guard": "test_goal_completion.GoalCompletionGuardTests.test_missing_local_runtime_fails_closed",
    "goal_completion_team_durability_guard": "test_goal_completion.GoalCompletionGuardTests.test_missing_team_durability_fails_closed",
    "goal_completion_retired_program_boundary": "test_goal_completion.GoalCompletionGuardTests.test_accuracy_and_pricing_do_not_control_current_goal",
    "trace_anchor_exact_head_guard": "test_trace_anchor.TraceAnchorTests.test_signed_anchor_binds_current_ledger_head_without_external_claim",
    "trace_anchor_event_tamper_guard": "test_trace_anchor.TraceAnchorTests.test_event_content_tamper_fails",
    "trace_anchor_ledger_rewrite_guard": "test_trace_anchor.TraceAnchorTests.test_rewritten_ledger_cannot_reuse_signed_anchor",
    "trace_anchor_prefix_boundary": "test_trace_anchor.TraceAnchorTests.test_new_entries_preserve_prefix_but_make_current_head_unanchored",
    "network_observation_loopback_positive_control": "test_network_observation.NetworkObservationTests.test_sampled_loopback_observation_passes_without_zero_egress_claim",
    "network_observation_external_negative_control": "test_network_observation.NetworkObservationTests.test_external_socket_or_zero_egress_label_fails",
    "network_observation_wildcard_negative_control": "test_network_observation.NetworkObservationTests.test_wildcard_listener_is_not_treated_as_loopback",
    "network_observation_process_presence_guard": "test_network_observation.NetworkObservationTests.test_every_named_process_must_have_an_observed_socket",
    "network_observation_secret_redaction_guard": "test_network_observation.NetworkObservationTests.test_unredacted_process_secret_fails_closed",
    "network_observation_saved_label_guard": "test_network_observation.NetworkObservationTests.test_saved_record_requires_a_pass_label",
    "network_observation_derived_pass_guard": "test_network_observation.NetworkObservationTests.test_pass_derivation_recomputes_external_socket_failure",
    "macos_sandbox_os_policy_guard": "test_reality_guards.RealityGuardTests.test_macos_sandbox_profile_confines_writes_and_denies_network",
    "local_context_output_reserve_guard": "test_reality_guards.RealityGuardTests.test_local_context_admission_reserves_output_before_inference",
    "local_context_overflow_negative_control": "test_reality_guards.RealityGuardTests.test_local_context_admission_rejects_overflow_before_inference",
    "local_context_tokenizer_identity_guard": "test_reality_guards.RealityGuardTests.test_local_context_admission_fails_when_tokenizer_identity_is_ambiguous",
    "evidence_scope_current_inventory_guard": "test_evidence_scope.EvidenceScopeTests.test_scope_is_recomputed_from_current_parser_inventory",
    "evidence_scope_anchor_negative_control": "test_evidence_scope.EvidenceScopeTests.test_wrong_source_hash_or_missing_anchor_cannot_restore_scope",
    "evidence_scope_parser_drift_guard": "test_evidence_scope.EvidenceScopeTests.test_inventory_digest_changes_when_current_parser_text_changes",
    "evidence_scope_duplicate_citation_guard": "test_evidence_scope.EvidenceScopeTests.test_duplicate_parser_citation_fails_closed",
    "evidence_scope_chat_anchor_drift_guard": "test_reality_guards.RealityGuardTests.test_trace_bound_chat_fails_when_current_evidence_anchor_drifts",
    "volatile_document_measurement_guard": "test_reality_guards.RealityGuardTests.test_claim_scan_rejects_volatile_current_measurements_in_prose",
    "buzz_review_event_pagination": "test_buzz_bridge.BuzzBridgeTests.test_named_review_events_are_restored_across_message_pages",
    "buzz_room_message_signature_boundary": "test_buzz_bridge.BuzzBridgeTests.test_room_messages_require_raw_signature_and_exact_payload",
    "buzz_published_message_signature_boundary": "test_buzz_bridge.BuzzBridgeTests.test_published_message_must_restore_with_expected_content_and_identity",
    "buzz_canvas_signature_boundary": "test_buzz_bridge.BuzzBridgeTests.test_canvas_read_requires_bound_raw_signature_and_exact_payload",
    "buzz_canvas_write_binding": "test_buzz_bridge.BuzzBridgeTests.test_canvas_write_verifies_and_persists_event_binding",
    "buzz_room_registry_integrity": "test_buzz_bridge.BuzzBridgeTests.test_room_registry_rejects_corruption_and_identity_drift",
    "buzz_room_registry_concurrency": "test_buzz_bridge.BuzzBridgeTests.test_concurrent_room_bindings_persist_without_loss",
    "buzz_room_creation_concurrency": "test_buzz_bridge.BuzzBridgeTests.test_concurrent_ensure_room_creates_one_buzz_channel",
    "buzz_room_cross_process_creation_guard": "test_buzz_bridge.BuzzBridgeTests.test_competing_processes_create_one_canonical_buzz_room",
    "buzz_room_binding_and_rollback_guard": "test_buzz_bridge.BuzzBridgeTests.test_room_binding_drift_and_failed_replace_preserve_canonical_registry",
    "buzz_room_registry_visible_failure": "test_reality_guards.RealityGuardTests.test_corrupt_buzz_room_registry_is_visible_and_fails_workspace_closed",
    "buzz_room_setup_source_boundary": "test_buzz_bridge.BuzzBridgeTests.test_room_setup_canvas_excludes_source_payload_and_discloses_buzz_retention",
    "artifact_evidence_boundary": "test_reality_guards.RealityGuardTests.test_artifact_inspection_proves_presence_not_invocation",
    "present_tense_target_claim_guard": "test_reality_guards.RealityGuardTests.test_claim_scan_rejects_present_tense_target_architecture",
    "private_folder_cli": "test_reality_guards.RealityGuardTests.test_cli_runs_an_arbitrary_folder_and_local_runtime_fails_closed",
    "private_folder_http": "test_reality_guards.RealityGuardTests.test_live_http_opens_and_executes_an_arbitrary_private_folder",
    "private_folder_preview_change_guard": "test_reality_guards.RealityGuardTests.test_folder_change_after_preview_fails_before_buzz_write",
    "private_folder_recursive_preview_guard": "test_reality_guards.RealityGuardTests.test_nested_only_folder_is_indexed_with_relative_identity",
    "private_folder_recursive_collision_guard": "test_reality_guards.RealityGuardTests.test_recursive_parser_disambiguates_duplicate_basenames_and_blocks_symlink_directories",
    "private_folder_empty_guard": "test_reality_guards.RealityGuardTests.test_empty_folder_cannot_create_buzz_room",
    "private_folder_recursive_limit_guard": "test_reality_guards.RealityGuardTests.test_recursive_parser_enforces_depth_file_count_and_total_byte_limits",
    "private_folder_relative_citation_guard": "test_reality_guards.RealityGuardTests.test_nested_retrieval_uses_exact_relative_citation_identity",
    "capital_structure_retrieval_guard": "test_reality_guards.RealityGuardTests.test_titan_debt_tranche_question_admits_exact_sources_table",
    "capital_structure_prompt_contract": "test_reality_guards.RealityGuardTests.test_titan_debt_tranche_prompt_requires_undrawn_facilities",
    "citation_identity_claim_boundary": "test_reality_guards.RealityGuardTests.test_chat_guard_does_not_score_citation_identity_as_claim_text",
    "capital_structure_completeness_guard": "test_reality_guards.RealityGuardTests.test_chat_guard_requires_every_disclosed_debt_instrument",
    "citation_wrapper_formatting_boundary": "test_reality_guards.RealityGuardTests.test_chat_guard_treats_source_citation_wrapper_as_formatting",
    "entry_leverage_absence_retrieval": "test_reality_guards.RealityGuardTests.test_citrix_entry_leverage_question_admits_financing_disclosure",
    "entry_leverage_absence_guard": "test_reality_guards.RealityGuardTests.test_chat_guard_rejects_valuation_multiple_substitution_for_entry_leverage",
    "termination_fee_component_retrieval": "test_reality_guards.RealityGuardTests.test_termination_fee_retrieval_requires_both_requested_fees",
    "termination_fee_component_guard": "test_reality_guards.RealityGuardTests.test_chat_guard_requires_every_disclosed_termination_fee_amount",
    "investment_screen_retrieval_guard": "test_first_pass.FirstPassTests.test_investment_screen_reserves_matching_evidence_in_bounded_context",
    "investment_screen_real_source_guard": "test_reality_guards.RealityGuardTests.test_real_first_pass_retrieval_admits_screen_specific_nested_evidence",
    "first_pass_source_snapshot_commit_guard": "test_reality_guards.RealityGuardTests.test_first_pass_blocks_model_and_fallback_publication_after_source_mutation",
    "first_pass_post_publish_snapshot_guard": "test_reality_guards.RealityGuardTests.test_first_pass_quarantines_candidate_when_source_changes_during_publication",
    "chat_post_publish_snapshot_guard": "test_reality_guards.RealityGuardTests.test_chat_quarantines_candidate_when_source_changes_during_publication",
    "workspace_uncommitted_agent_quarantine": "test_reality_guards.RealityGuardTests.test_workspace_replaces_uncommitted_agent_payload_with_quarantine_notice",
    "screen_bound_live_evidence_tamper_guard": "test_reality_guards.RealityGuardTests.test_screen_bound_live_first_pass_evidence_rejects_snapshot_or_route_tamper",
    "hierarchy_aware_citation_guard": "test_reality_guards.RealityGuardTests.test_markdown_retrieval_cites_child_provision_with_bounded_section_context",
    "private_folder_preview_browser_evidence": "test_reality_guards.RealityGuardTests.test_folder_preview_browser_evidence_is_hash_and_no_write_bound",
    "buzz_polling_browser_evidence": "test_reality_guards.RealityGuardTests.test_buzz_polling_browser_evidence_is_behavioral_and_hash_bound",
    "xlsx_source_fidelity": "test_reality_guards.RealityGuardTests.test_xlsx_cells_coordinates_and_formula_boundaries_are_preserved",
    "scanned_pdf_real_ocr": "test_reality_guards.RealityGuardTests.test_image_only_pdf_uses_real_ocr_with_physical_anchor_and_disclosure",
    "scanned_pdf_ocr_boundary": "test_reality_guards.RealityGuardTests.test_image_only_pdf_ocr_can_be_disabled_and_is_page_bounded",
    "scanned_pdf_ocr_negative_control": "test_reality_guards.RealityGuardTests.test_wrong_ocr_result_is_not_promoted_as_expected_text",
    "ocr_accuracy_exact_recomputation": "test_ocr_accuracy_benchmark.OcrAccuracyBenchmarkTests.test_exact_raw_ocr_text_passes_recomputed_metrics",
    "ocr_accuracy_wrong_number_guard": "test_ocr_accuracy_benchmark.OcrAccuracyBenchmarkTests.test_wrong_material_number_fails_error_and_phrase_thresholds",
    "ocr_accuracy_ground_truth_hash_guard": "test_ocr_accuracy_benchmark.OcrAccuracyBenchmarkTests.test_ground_truth_text_cannot_drift_from_preregistered_hash",
    "ocr_accuracy_saved_score_tamper_guard": "test_ocr_accuracy_benchmark.OcrAccuracyBenchmarkTests.test_saved_scores_are_recomputed_and_tampering_fails",
    "whole_corpus_absence_oracle": "test_absence_oracle.AbsenceOracleTests.test_current_citrix_whole_corpus_audit_passes_narrow_contract",
    "whole_corpus_absence_negative_control": "test_absence_oracle.AbsenceOracleTests.test_direct_disclosure_pattern_injection_fails",
    "oracle_context_repair_localization_guard": "test_oracle_context_diagnostic.OracleContextDiagnosticTests.test_wrong_baseline_and_correct_oracle_localize_context_sensitive_failure",
    "oracle_context_regression_guard": "test_oracle_context_diagnostic.OracleContextDiagnosticTests.test_baseline_pass_followed_by_oracle_failure_is_a_regression",
    "oracle_context_absence_boundary": "test_oracle_context_diagnostic.OracleContextDiagnosticTests.test_absence_case_is_not_run_with_one_positive_passage",
    "oracle_context_saved_response_tamper_guard": "test_oracle_context_diagnostic.OracleContextDiagnosticTests.test_saved_raw_response_tamper_is_recomputed_and_fails",
    "xlsx_retrieval_boundary": "test_reality_guards.RealityGuardTests.test_xlsx_is_retrievable_with_formula_disclosure",
    "xlsx_publication_boundary": "test_reality_guards.RealityGuardTests.test_xlsx_claim_cannot_hide_non_recalculated_formula_state",
    "xlsx_display_fidelity": "test_xlsx_benchmark.XlsxDisplayBenchmarkTests.test_preregistered_display_contract_passes_end_to_end",
    "xlsx_display_negative_control": "test_xlsx_benchmark.XlsxDisplayBenchmarkTests.test_wrong_expected_display_fails_the_evaluator",
    "xlsx_display_claim_boundary": "test_xlsx_benchmark.XlsxDisplayBenchmarkTests.test_measurement_state_does_not_claim_excel_parity",
    "xlsx_resource_boundary": "test_reality_guards.RealityGuardTests.test_xlsx_parser_rejects_out_of_boundary_coordinates",
    "xlsx_external_resource_boundary": "test_reality_guards.RealityGuardTests.test_xlsx_parser_rejects_external_workbook_relationships",
    "private_folder_registration_restart": "test_reality_guards.RealityGuardTests.test_custom_room_registry_survives_reload_and_rejects_identity_drift",
    "private_folder_registration_concurrency": "test_registry_concurrency.LocalDealRoomRegistryConcurrencyTests.test_concurrent_commits_persist_every_room_without_temp_file_collisions",
    "private_folder_cross_process_guard": "test_registry_concurrency.LocalDealRoomRegistryConcurrencyTests.test_competing_processes_preserve_all_rooms_and_live_process_reloads",
    "private_folder_rollback_guard": "test_registry_concurrency.LocalDealRoomRegistryConcurrencyTests.test_folder_registry_drift_and_failed_replace_preserve_prior_bytes",
    "source_mutation": "test_reality_guards.RealityGuardTests.test_reviewed_workflow_values_are_loaded_from_selected_folder",
    "json_source_mutation": "test_reality_guards.RealityGuardTests.test_json_workflows_are_source_bound_and_do_not_invent_dates",
    "provider_invocation": "test_reality_guards.RealityGuardTests.test_configured_local_provider_is_actually_invoked_and_traced",
    "visible_model_rejection": "test_reality_guards.RealityGuardTests.test_rejected_bonsai_draft_is_a_signed_visible_state_not_a_false_send_failure",
    "cloud_context_consent": "test_reality_guards.RealityGuardTests.test_cloud_context_requires_separate_explicit_opt_in",
    "benchmark_negative_control": "test_reality_guards.RealityGuardTests.test_benchmark_negative_control_fails",
    "benchmark_unrelated_claim_negative_control": "test_reality_guards.RealityGuardTests.test_accretion_benchmark_rejects_unrelated_regulatory_conclusion",
    "benchmark_unit_and_invented_policy_negative_control": "test_reality_guards.RealityGuardTests.test_accretion_benchmark_rejects_invented_threshold_and_wrong_eps_unit",
    "benchmark_equivalent_per_share_label": "test_reality_guards.RealityGuardTests.test_accretion_benchmark_accepts_equivalent_per_share_unit_label",
    "benchmark_equivalent_multiline_titan": "test_reality_guards.RealityGuardTests.test_titan_benchmark_accepts_equivalent_multiline_json_records",
    "benchmark_qoe_invented_policy_negative_control": "test_reality_guards.RealityGuardTests.test_qoe_benchmark_rejects_invented_valuation_policy",
    "sandbox_escape_and_limits": "test_reality_guards.RealityGuardTests.test_subprocess_sandbox_blocks_unknown_import_and_times_out",
    "coding_agent_pilot": "test_reality_guards.RealityGuardTests.test_saved_coding_pilot_covers_required_behaviors",
    "coding_agent_legal_claim_boundary": "test_vault.TestPrismVaultPlatform.test_lbo_ai_guidance_does_not_turn_schedule_mismatch_into_legal_breach",
    "coding_agent_relevance_boundary": "test_vault.TestPrismVaultPlatform.test_accretion_ai_guidance_excludes_unrelated_regulatory_conclusions",
    "coding_agent_pre_execution_scope_guard": "test_vault.TestPrismVaultPlatform.test_accretion_generated_script_scope_rejects_unrelated_findings",
    "coding_agent_qoe_scope_guard": "test_vault.TestPrismVaultPlatform.test_qoe_generated_script_scope_rejects_invented_policy",
    "cold_restart_evidence": "test_reality_guards.RealityGuardTests.test_cold_restart_evidence_hash_tamper_fails_closed",
    "cold_restart_recorder_exact_processes": "test_cold_restart_recorder.ColdRestartRecorderTests.test_exact_process_selection_ignores_other_apps_and_models",
    "cold_restart_browser_snapshot_boundary": "test_cold_restart_recorder.ColdRestartRecorderTests.test_cold_restart_uses_immutable_browser_snapshot_path",
    "local_verification_cold_gate": "test_evidence_manifest.EvidenceManifestTests.test_local_verification_requires_cold_restart_except_candidate",
    "local_trace_anchor_runtime_scope": "test_evidence_manifest.EvidenceManifestTests.test_live_trace_anchor_is_required_only_for_local_runtime",
    "current_local_evidence_tamper_guard": "test_reality_guards.RealityGuardTests.test_current_local_product_evidence_scope_tamper_fails_closed",
    "current_local_equivalent_unit_guard": "test_reality_guards.RealityGuardTests.test_saved_evidence_validator_accepts_equivalent_per_share_unit",
    "xlsx_live_signed_evidence_tamper_guard": "test_reality_guards.RealityGuardTests.test_xlsx_live_evidence_verifies_raw_events_and_rejects_tampering",
    "first_pass_signed_delivery_tamper_guard": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_signed_delivery_evidence_rejects_raw_event_tampering",
    "http_contract": "test_reality_guards.RealityGuardTests.test_live_http_contract_and_errors",
    "http_inference_concurrency": "test_reality_guards.RealityGuardTests.test_production_server_keeps_status_responsive_during_long_request",
    "live_inference_concurrency_evidence": "test_reality_guards.RealityGuardTests.test_live_inference_concurrency_evidence_rejects_latency_or_delivery_tampering",
    "configured_status_truth": "test_reality_guards.RealityGuardTests.test_status_distinguishes_configured_provider_from_baseline_engine",
    "runtime_history_process_boundary": "test_reality_guards.RealityGuardTests.test_status_separates_persisted_history_from_current_process_invocation",
    "runtime_measured_deployment_boundary": "test_reality_guards.RealityGuardTests.test_status_separates_measured_deployment_from_provider_configuration",
    "trace_release_state_boundary": "test_trace_persistence.TracePersistenceTests.test_trace_release_state_distinguishes_rejection_pending_and_unverified",
    "empty_aggregate_metric_boundary": "test_trace_persistence.TracePersistenceTests.test_empty_aggregate_metrics_remain_unmeasured",
    "lexical_claim_source_boundary": "test_vault.TestPrismVaultPlatform.test_lexical_claim_check_cannot_pass_without_source_support",
    "lexical_claim_semantic_boundary": "test_vault.TestPrismVaultPlatform.test_lexical_claim_pass_discloses_that_semantics_are_unmeasured",
    "tabular_self_reported_count_guard": "test_vault.TestPrismVaultPlatform.test_tabular_self_reported_counts_cannot_create_a_pass",
    "tabular_exact_fixture_guard": "test_vault.TestPrismVaultPlatform.test_tabular_fixture_match_inspects_coordinate_and_exact_text",
    "public_pdf_visual_claim_guard": "test_public_deal_corpus_verification.PublicDealCorpusVerificationTests.test_saved_corpus_evidence_does_not_claim_an_unrecorded_human_review",
    "public_pdf_visual_claim_remediation_guard": "test_public_deal_corpus_verification.PublicDealCorpusVerificationTests.test_legacy_visual_claim_corrections_match_current_bytes",
    "first_pass_human_review_signal_guard": "test_first_pass_evidence_record.FirstPassEvidenceRecordTests.test_missing_or_ambiguous_human_review_signal_fails_closed",
    "denylist_hallucination_claim_boundary": "test_vault.TestPrismVaultPlatform.test_forbidden_string_check_is_not_labeled_hallucination_detection",
    "schema_presence_claim_boundary": "test_vault.TestPrismVaultPlatform.test_field_presence_does_not_claim_type_or_schema_validation",
    "typed_schema_negative_control": "test_vault.TestPrismVaultPlatform.test_typed_field_schema_rejects_wrong_type_and_empty_schema",
    "trace_legacy_migration_guard": "test_trace_persistence.TracePersistenceTests.test_legacy_jsonl_migrates_to_verified_hash_chain",
    "trace_hash_chain_tamper_guard": "test_trace_persistence.TracePersistenceTests.test_hash_tamper_and_internal_entry_deletion_fail_closed",
    "trace_cross_process_append_guard": "test_trace_persistence.TracePersistenceTests.test_competing_processes_append_every_trace",
    "trace_conflict_and_rollback_guard": "test_trace_persistence.TracePersistenceTests.test_conflicting_review_update_and_failed_append_preserve_history",
    "live_trace_tamper_visible_failure": "test_reality_guards.RealityGuardTests.test_live_trace_ledger_tamper_is_a_visible_dependency_failure",
    "failed_bind_trace_store_side_effect_guard": "test_operator_preflight.OperatorPreflightTests.test_failed_bind_does_not_open_or_migrate_trace_store",
    "trace_fixture_contamination_remediation_guard": "test_trace_contamination_remediation.TraceContaminationRemediationTests.test_exact_fixture_pair_is_retained_labelled_and_excluded",
    "trace_fixture_contamination_evidence_guard": "test_trace_contamination_remediation.TraceContaminationRemediationTests.test_saved_remediation_record_preserves_the_correction_boundary",
    "engineering_source_manifest_tamper_guard": "test_evidence_manifest.EvidenceManifestTests.test_source_manifest_detects_same_size_implementation_change",
    "engineering_evidence_release_boundary": "test_evidence_manifest.EvidenceManifestTests.test_summary_rejects_stale_evidence_and_preserves_release_boundary",
    "current_report_single_run_self_validation": "test_evidence_manifest.EvidenceManifestTests.test_current_report_validates_exact_saved_bytes_in_one_run",
    "failed_current_report_preservation_guard": "test_evidence_manifest.EvidenceManifestTests.test_failed_current_run_preserves_canonical_and_writes_attempt_record",
    "runtime_model_catalog_boundary": "test_reality_guards.RealityGuardTests.test_models_endpoint_does_not_present_research_catalog_as_runtime_discovery",
    "first_pass_relation_guard": "test_first_pass.FirstPassTests.test_detects_live_year_value_relation_failure",
    "first_pass_claim_guard": "test_first_pass.FirstPassTests.test_detects_live_yoy_arithmetic_and_unsupported_approval",
    "first_pass_calculation_guard": "test_first_pass.FirstPassTests.test_detects_uncited_numbers_and_false_leverage_calculation",
    "first_pass_registered_calculation_schema_guard": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_case_schema_requires_source_bound_calculation_inputs",
    "first_pass_registered_calculation_recompute_guard": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_registered_calculation_contract_recomputes_expected_value",
    "first_pass_registered_calculation_source_guard": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_registered_calculation_input_must_exist_in_source_claim",
    "first_pass_registered_calculation_response_guard": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_calculation_response_requires_inputs_formula_result_and_unit",
    "first_pass_registered_calculation_owner_guard": "test_candidate_case_approval.CandidateCaseApprovalTests.test_owner_cannot_approve_a_calculation_with_unbound_inputs",
    "schema_keyword_coverage_guard": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_checked_in_schemas_use_only_enforced_keywords",
    "schema_unsupported_keyword_guard": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_schema_validator_rejects_unsupported_assertion_keywords",
    "schema_keyword_form_guard": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_schema_validator_rejects_unsupported_keyword_forms",
    "schema_additional_property_guard": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_schema_validator_enforces_schema_valued_additional_properties",
    "schema_pattern_semantics_guard": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_schema_validator_uses_json_schema_pattern_search_semantics",
    "schema_reference_guard": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_schema_validator_reports_unresolved_reference",
    "schema_const_and_bound_guard": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_schema_validator_enforces_const_and_exclusive_bounds",
    "schema_json_equality_guard": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_schema_validator_uses_json_value_equality",
    "schema_finite_number_guard": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_schema_validator_rejects_nonfinite_numbers",
    "schema_timezone_guard": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_schema_validator_rejects_ambiguous_date_time",
    "schema_composition_guard": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_one_of_does_not_bypass_sibling_requirements",
    "candidate_companion_discovery_boundary": "test_candidate_companion_discovery.CandidateCompanionDiscoveryTests.test_latest_financial_filing_before_proxy_is_selected",
    "candidate_companion_acquisition_boundary": "test_candidate_companion_acquisition.CandidateCompanionAcquisitionTests.test_exact_sec_archive_path_is_accepted",
    "candidate_financial_source_binding_guard": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_financial_draft_cannot_bind_proxy_acquisition",
    "candidate_exact_source_retrieval_guard": "test_reality_guards.RealityGuardTests.test_deal_room_query_can_admit_one_exact_source",
    "candidate_xbrl_metadata_retrieval_guard": "test_reality_guards.RealityGuardTests.test_deal_room_query_excludes_inline_xbrl_header_metadata",
    "candidate_cross_document_review_guard": "test_candidate_source_review.CandidateSourceReviewTests.test_cross_document_review_requires_support_from_both_sources",
    "candidate_cross_document_registration_guard": "test_candidate_case_registration.CandidateCaseRegistrationTests.test_cross_document_approval_registers_both_sources_atomically",
    "pricing_poc_buyer_evidence_boundary": "test_reality_guards.RealityGuardTests.test_pricing_poc_endpoint_preserves_unmeasured_buyer_boundary",
    "pricing_poc_signature_tamper_guard": "test_pricing_poc.PricingPocTests.test_payload_tamper_invalidates_buyer_signature",
    "pricing_poc_unpublished_event_guard": "test_pricing_poc.PricingPocTests.test_signed_but_unpublished_buyer_event_is_rejected",
    "pricing_poc_changed_relay_event_guard": "test_pricing_poc.PricingPocTests.test_changed_restored_buyer_event_is_rejected",
    "pricing_poc_live_resolver_guard": "test_pricing_poc.PricingPocTests.test_saved_record_requires_live_buzz_resolver",
    "pricing_poc_buyer_authority_guard": "test_pricing_poc.PricingPocTests.test_self_issued_buyer_key_cannot_become_commercial_evidence",
    "pricing_poc_distinct_authority_guard": "test_pricing_poc.PricingPocTests.test_buyer_cannot_act_as_its_own_commercial_authority",
    "pricing_poc_authority_channel_guard": "test_pricing_poc.PricingPocTests.test_authority_event_cannot_claim_multiple_buzz_channels",
    "pricing_poc_authority_renderer_guard": "test_pricing_poc_cli.PricingPocCliTests.test_authorization_renderer_emits_exact_signing_statement",
    "pricing_poc_unconfigured_publisher_guard": "test_pricing_poc_cli.PricingPocCliTests.test_publisher_fails_before_buzz_when_authority_is_unconfigured",
    "pricing_poc_unconfigured_authorizer_guard": "test_pricing_poc_cli.PricingPocCliTests.test_authority_publisher_fails_before_buzz_when_authority_is_unconfigured",
    "pricing_poc_self_authorizer_cli_guard": "test_pricing_poc_cli.PricingPocCliTests.test_authority_publisher_rejects_self_authorized_buyer_before_buzz",
    "pricing_poc_transfer_quality_guard": "test_pricing_poc.PricingPocTests.test_transfer_critical_correction_fails_product_value",
    "pricing_poc_browser_state_guard": "test_reality_guards.RealityGuardTests.test_pricing_poc_browser_evidence_is_empty_state_and_screenshot_bound",
    "pricing_poc_unsigned_record_guard": "test_reality_guards.RealityGuardTests.test_pricing_poc_unsigned_record_builder_guards_required_evidence",
    "pricing_poc_completion_fixture_guard": "test_reality_guards.RealityGuardTests.test_pricing_poc_completion_fixture_cannot_become_buyer_evidence",
    "sealed_test_fail_before_read_guard": "test_sealed_test_control.SealedTestControlTests.test_current_state_fails_before_secret_loader",
    "sealed_test_public_secret_leak_guard": "test_sealed_test_control.SealedTestControlTests.test_public_manifest_rejects_secret_fields_before_read",
    "sealed_test_one_time_contact_guard": "test_sealed_test_control.SealedTestControlTests.test_valid_preflight_then_one_time_open",
    "sealed_test_concurrent_contact_guard": "test_sealed_test_control.SealedTestControlTests.test_concurrent_contact_invokes_only_one_loader",
    "sealed_test_secret_hash_guard": "test_sealed_test_control.SealedTestControlTests.test_secret_hash_mismatch_consumes_version_and_fails",
    "first_pass_repair_transport": "test_first_pass.FirstPassTests.test_stateful_repair_sends_only_correction_after_response_id",
    "first_pass_metric_clause_scope": "test_first_pass.FirstPassTests.test_numeric_relation_guard_scopes_pairs_to_each_metric_clause",
    "first_pass_legacy_review_guard": "test_first_pass.FirstPassTests.test_signed_draft_guard_version_controls_reviewability",
    "first_pass_rejected_model_fallback": "test_reality_guards.RealityGuardTests.test_rejected_model_creates_separate_reviewable_evidence_fallback",
    "first_pass_accepted_trace_restart": "test_reality_guards.RealityGuardTests.test_accepted_model_buzz_event_persists_its_trace_identity",
    "first_pass_agent_author_boundary": "test_first_pass_restoration.TraceBoundFirstPassRestorationTests.test_human_signed_draft_marker_is_not_a_bonsai_draft",
    "first_pass_event_trace_replay_guard": "test_first_pass_restoration.TraceBoundFirstPassRestorationTests.test_copied_newer_event_cannot_shadow_original_trace_event",
    "first_pass_trace_semantic_binding": "test_first_pass_restoration.TraceBoundFirstPassRestorationTests.test_trace_semantic_mismatches_are_rejected",
    "first_pass_legacy_event_trace_recovery": "test_first_pass_restoration.TraceBoundFirstPassRestorationTests.test_marker_without_trace_uses_unique_trace_event_binding",
    "first_pass_review_restart_restore": "test_first_pass_restoration.TraceBoundLocalReviewRestorationTests.test_review_survives_process_cache_loss_from_signed_buzz_events",
    "first_pass_review_event_drift_guard": "test_first_pass_restoration.TraceBoundLocalReviewRestorationTests.test_review_rejects_metadata_or_signed_event_drift",
    "first_pass_orphan_canvas_commit_guard": "test_reality_guards.RealityGuardTests.test_orphaned_signed_review_canvas_fails_digest_closed",
    "operator_preflight_evidence_guard": "test_reality_guards.RealityGuardTests.test_operator_preflight_evidence_rejects_loaded_model_or_scope_drift",
    "local_deployment_file_and_warm_cache_tamper_guard": "test_deployment_evidence.DeploymentEvidenceTests.test_file_bound_validator_rejects_artifact_tampering",
    "local_deployment_concurrent_cold_cache_guard": "test_deployment_evidence.DeploymentEvidenceTests.test_concurrent_cold_status_requests_hash_artifacts_once",
    "local_deployment_active_runtime_drift_guard": "test_deployment_evidence.DeploymentEvidenceTests.test_active_runtime_drift_fails_even_with_verified_artifacts",
    "local_deployment_non_loopback_guard": "test_deployment_evidence.DeploymentEvidenceTests.test_active_runtime_non_loopback_bind_fails",
    "local_provider_loopback_configuration_guard": "test_local_provider_boundary.LocalProviderBoundaryTests.test_registry_rejects_remote_alias_and_ambiguous_local_urls",
    "direct_server_local_provider_boundary_guard": "test_local_provider_boundary.LocalProviderBoundaryTests.test_direct_server_import_fails_closed_for_remote_local_provider",
    "local_deployment_port_drift_guard": "test_deployment_evidence.DeploymentEvidenceTests.test_active_runtime_port_drift_fails",
    "local_deployment_secret_guard": "test_deployment_evidence.DeploymentEvidenceTests.test_recorder_hashes_exact_artifacts_and_never_saves_process_secret",
    "operator_preflight_catalog_boundary": "test_operator_preflight.OperatorPreflightTests.test_catalog_model_without_loaded_instance_fails_readiness",
    "operator_preflight_agent_start_guard": "test_operator_preflight.OperatorPreflightTests.test_early_agent_exit_prevents_ready_announcement",
    "operator_preflight_port_ownership_guard": "test_operator_preflight.OperatorPreflightTests.test_occupied_workspace_port_fails_closed_without_fallback",
    "buzz_relay_host_loopback_guard": "test_operator_preflight.OperatorPreflightTests.test_buzz_compose_publishes_relay_on_ipv4_loopback_only",
    "buzz_acp_room_scope_guard": "test_operator_preflight.OperatorPreflightTests.test_agent_scope_requires_one_room_folder_and_channel_binding",
    "buzz_acp_subscription_policy_guard": "test_operator_preflight.OperatorPreflightTests.test_acp_environment_is_single_room_owner_only_and_memoryless",
    "buzz_acp_exact_subscription_readiness": "test_operator_preflight.OperatorPreflightTests.test_agent_readiness_requires_exact_channel_subscription_marker",
    "buzz_acp_duplicate_process_guard": "test_operator_preflight.OperatorPreflightTests.test_existing_repo_acp_process_is_detected_exactly",
    "buzz_acp_child_shutdown_guard": "test_operator_preflight.OperatorPreflightTests.test_agent_shutdown_cleans_exact_child_binaries",
    "buzz_acp_runtime_supervision_guard": "test_operator_preflight.OperatorPreflightTests.test_agent_exit_after_startup_stops_server",
    "buzz_message_read_coalescing_guard": "test_buzz_bridge.BuzzBridgeTests.test_identical_concurrent_message_reads_share_one_verified_relay_read",
    "buzz_message_read_failure_retry_guard": "test_buzz_bridge.BuzzBridgeTests.test_coalesced_message_failure_reaches_waiters_and_next_poll_retries",
    "workspace_poll_overlap_guard": "test_reality_guards.RealityGuardTests.test_workspace_polling_queues_refresh_instead_of_overlapping_buzz_reads",
    "buzz_acp_status_scope_guard": "test_reality_guards.RealityGuardTests.test_status_discloses_single_room_acp_source_scope",
    "operator_review_restart_evidence_guard": "test_reality_guards.RealityGuardTests.test_operator_review_restart_evidence_rejects_scope_or_identity_drift",
    "provenance_bound_publication_guard": "test_reality_guards.RealityGuardTests.test_provenance_bound_publication_recomputes_current_room_and_rejects_tampering",
    "first_pass_evidence_recorder": "test_first_pass_evidence_record.FirstPassEvidenceRecordTests.test_rejects_buzz_artifact_without_trace_identity",
    "first_pass_trace_provider_identity_guard": "test_first_pass_evidence_record.FirstPassEvidenceRecordTests.test_rejects_model_draft_with_unrelated_or_mismatched_trace",
    "first_pass_cross_deal_scope_guard": "test_first_pass_development_runner.FirstPassDevelopmentRunnerTests.test_source_scope_rejects_cross_deal_files",
    "battletest_rejection_outcome_guard": "test_first_pass_development_runner.FirstPassDevelopmentRunnerTests.test_battletest_summary_does_not_count_signed_rejection_as_answer",
    "first_pass_exact_citation_preview": "test_reality_guards.RealityGuardTests.test_workspace_exposes_bounded_text_and_exact_citation_anchor_preview",
    "browser_favicon_contract": "test_reality_guards.RealityGuardTests.test_browser_implicit_favicon_request_is_not_an_error",
    "browser_evidence_integrity": "test_reality_guards.RealityGuardTests.test_browser_evidence_is_trace_and_screenshot_bound",
    "source_review_browser_evidence_integrity": "test_reality_guards.RealityGuardTests.test_source_review_browser_evidence_is_pipeline_and_screenshot_bound",
    "case_authoring_browser_evidence_integrity": "test_reality_guards.RealityGuardTests.test_case_authoring_browser_evidence_is_state_and_screenshot_bound",
    "output_review_browser_evidence_integrity": "test_reality_guards.RealityGuardTests.test_output_review_browser_evidence_is_blinded_and_screenshot_bound",
    "output_review_completion_fixture_integrity": "test_reality_guards.RealityGuardTests.test_output_review_completion_fixture_is_schema_packet_and_screenshot_bound",
    "real_deal_browser_evidence_integrity": "test_reality_guards.RealityGuardTests.test_real_deal_browser_evidence_is_source_event_and_screenshot_bound",
    "titan_debt_browser_evidence_integrity": "test_reality_guards.RealityGuardTests.test_titan_debt_browser_evidence_is_source_trace_and_screenshot_bound",
    "accessibility_browser_evidence_integrity": "test_reality_guards.RealityGuardTests.test_accessibility_browser_evidence_is_room_and_screenshot_bound",
    "cross_browser_evidence_integrity": "test_reality_guards.RealityGuardTests.test_cross_browser_evidence_is_engine_event_and_screenshot_bound",
    "deal_room_chat_query_expansion": "test_reality_guards.RealityGuardTests.test_deal_room_chat_expands_multi_part_ma_questions",
    "buzz_discussion_canonical_url": "test_reality_guards.RealityGuardTests.test_buzz_message_canonical_url_opens_discussion_event",
    "first_pass_benchmark_schema": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_case_schema_rejects_missing_review_state",
    "first_pass_benchmark_source_hash": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_source_hash_tamper_fails_structure",
    "first_pass_benchmark_anchor_evidence": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_unverified_anchor_fails_structure",
    "first_pass_benchmark_deal_split": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_deal_split_leakage_fails_structure",
    "first_pass_benchmark_false_approval": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_false_domain_approval_fails_structure",
    "first_pass_deterministic_cannot_promote": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_deterministic_pass_cannot_become_accuracy_release",
    "first_pass_development_evaluation": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_saved_development_evaluation_stays_unverified",
    "first_pass_blinded_review_packet": "test_first_pass_review.FirstPassReviewTests.test_packet_is_hash_bound_and_contains_no_model_identity_keys",
    "first_pass_review_tamper": "test_first_pass_review.FirstPassReviewTests.test_response_tamper_and_missing_dimension_are_rejected",
    "first_pass_distinct_reviewers": "test_first_pass_review.FirstPassReviewTests.test_duplicate_reviewer_cannot_satisfy_two_reviewer_gate",
    "first_pass_review_adjudication": "test_first_pass_review.FirstPassReviewTests.test_disagreement_requires_principal_adjudication",
    "first_pass_review_resolved_labels": "test_first_pass_review.FirstPassReviewTests.test_agreement_resolves_to_canonical_human_labels",
    "output_reviewer_roster_concurrency": "test_reviewer_roster_concurrency.ReviewerRosterConcurrencyTests.test_concurrent_output_approvals_preserve_every_reviewer",
    "source_reviewer_roster_concurrency": "test_reviewer_roster_concurrency.ReviewerRosterConcurrencyTests.test_concurrent_source_approvals_preserve_every_reviewer",
    "reviewer_authority_pair_commit_guard": "test_reviewer_roster_authority.ReviewerRosterAuthorityTests.test_partial_pair_commit_closes_both_rosters_until_same_authority_repairs_it",
    "reviewer_authority_stale_precheck_guard": "test_reviewer_roster_authority.ReviewerRosterAuthorityTests.test_stale_precheck_cannot_overwrite_authority_that_wins_locked_commit",
    "first_pass_review_agreement_event_restore": "test_first_pass_review.FirstPassReviewTests.test_agreement_only_review_restores_events_without_adjudication",
    "first_pass_saved_review_packet": "test_first_pass_review.FirstPassReviewTests.test_saved_packet_matches_current_registry_rubric_and_responses",
    "first_pass_principal_adjudication": "test_first_pass_review.FirstPassReviewTests.test_principal_adjudication_is_distinct_and_complete",
    "first_pass_candidate_inventory_boundary": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_candidate_sources_do_not_inflate_registered_inventory",
    "first_pass_near_duplicate_split_guard": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_near_duplicate_family_split_leakage_fails_structure",
    "first_pass_candidate_overclaim_guard": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_candidate_source_cannot_claim_acquisition_or_labels",
    "first_pass_candidate_question_draft_guard": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_candidate_question_draft_cannot_create_answer_or_registration",
    "candidate_source_exact_sec_path": "test_candidate_source_acquisition.CandidateSourceAcquisitionTests.test_resolves_exact_sec_primary_document",
    "candidate_source_ambiguous_path": "test_candidate_source_acquisition.CandidateSourceAcquisitionTests.test_rejects_ambiguous_or_cross_accession_document",
    "candidate_source_registry_update": "test_candidate_source_acquisition.CandidateSourceAcquisitionTests.test_registry_update_is_hash_bound_and_cannot_claim_labels",
    "candidate_source_review_packet": "test_candidate_source_review.CandidateSourceReviewTests.test_packet_is_model_blind_hash_bound_and_complete",
    "candidate_source_review_saved_packet": "test_candidate_source_review.CandidateSourceReviewTests.test_saved_packet_matches_current_candidate_registry",
    "candidate_source_review_tamper": "test_candidate_source_review.CandidateSourceReviewTests.test_tampered_packet_source_and_citation_are_rejected",
    "candidate_source_review_single_reviewer": "test_candidate_source_review.CandidateSourceReviewTests.test_single_reviewer_cannot_make_a_draft_eligible",
    "candidate_source_review_duplicate_reviewer": "test_candidate_source_review.CandidateSourceReviewTests.test_duplicate_reviewer_cannot_satisfy_two_reviewer_gate",
    "candidate_source_review_agreement": "test_candidate_source_review.CandidateSourceReviewTests.test_two_agreeing_reviewers_make_only_the_draft_eligible",
    "candidate_source_review_adjudication": "test_candidate_source_review.CandidateSourceReviewTests.test_disagreement_requires_a_distinct_principal",
    "candidate_source_registry_tamper_binding": "test_candidate_source_review.CandidateSourceReviewTests.test_packet_rejects_candidate_registry_tamper",
    "candidate_source_reviewer_roster_guard": "test_candidate_source_review.CandidateSourceReviewTests.test_self_asserted_qualification_cannot_bypass_empty_roster",
    "candidate_source_reviewer_signature_guard": "test_candidate_source_review.CandidateSourceReviewTests.test_missing_or_forged_buzz_attestation_is_rejected",
    "candidate_source_review_http_guard": "test_reality_guards.RealityGuardTests.test_candidate_source_review_http_is_roster_gated_and_unregistered",
    "benchmark_pipeline_http_guard": "test_reality_guards.RealityGuardTests.test_benchmark_pipeline_http_reports_each_unpassed_gate",
    "ten_benchmark_decisions_surface_guard": "test_reality_guards.RealityGuardTests.test_benchmark_pipeline_http_reports_each_unpassed_gate",
    "ten_benchmark_decisions_evidence_guard": "test_reality_guards.RealityGuardTests.test_source_review_browser_evidence_is_pipeline_and_screenshot_bound",
    "benchmark_governance_plain_field_guard": "test_benchmark_governance.BenchmarkGovernanceTests.test_plain_manifest_approval_fields_have_no_authority",
    "benchmark_governance_material_tamper_guard": "test_benchmark_governance.BenchmarkGovernanceTests.test_signed_receipts_fail_after_benchmark_material_changes",
    "benchmark_governance_authority_tamper_guard": "test_benchmark_governance.BenchmarkGovernanceTests.test_authority_assignment_edit_breaks_root_signature",
    "benchmark_governance_independent_signer_guard": "test_benchmark_governance.BenchmarkGovernanceTests.test_role_labels_cannot_reuse_one_actor_or_signing_key",
    "benchmark_governance_replay_guard": "test_benchmark_governance.BenchmarkGovernanceTests.test_event_replay_and_cross_role_substitution_fail",
    "benchmark_governance_atomic_record_guard": "test_benchmark_governance.BenchmarkGovernanceTests.test_atomic_recorder_rejects_duplicate_scope_and_role",
    "case_authoring_http_guard": "test_reality_guards.RealityGuardTests.test_case_authoring_http_is_source_review_and_owner_gated",
    "case_authoring_ui_guard": "test_reality_guards.RealityGuardTests.test_case_authoring_page_keeps_signing_and_registration_separate",
    "output_review_http_guard": "test_reality_guards.RealityGuardTests.test_output_review_http_is_blinded_roster_gated_and_unsigned",
    "output_review_unsigned_export_guard": "test_output_review_record.OutputReviewRecordTests.test_unsigned_output_review_is_complete_schema_valid_and_not_attested",
    "workspace_customer_demo_contract_guard": "test_reality_guards.RealityGuardTests.test_workspace_html_is_fresh_and_names_the_customer_demo_contract",
    "cloud_consent_unsigned_network_guard": "test_reality_guards.RealityGuardTests.test_cloud_http_requires_and_consumes_signed_request_consent_before_network",
    "cloud_consent_distinct_context_guard": "test_cloud_consent.CloudConsentTests.test_dispatch_and_context_need_distinct_request_bound_signatures",
    "cloud_consent_material_tamper_guard": "test_cloud_consent.CloudConsentTests.test_prompt_snapshot_provider_and_expiry_tamper_fail",
    "cloud_consent_atomic_replay_guard": "test_cloud_consent.CloudConsentTests.test_consent_is_atomically_consumed_once",
    "cloud_consent_relay_restoration_guard": "test_cloud_consent.CloudConsentTests.test_signed_but_unpublished_or_changed_event_fails_closed",
    "cloud_provider_https_boundary_guard": "test_local_provider_boundary.LocalProviderBoundaryTests.test_cloud_provider_rejects_unsafe_endpoint_forms",
    "cloud_cli_consent_guard": "test_prismctl_cloud_boundary.PrismctlCloudBoundaryTests.test_cloud_agent_requires_consent_file_before_agent_or_provider",
    "cloud_cli_room_identity_guard": "test_prismctl_cloud_boundary.PrismctlCloudBoundaryTests.test_cloud_folder_path_requires_stable_room_identity",
    "cloud_benchmark_consent_map_guard": "test_prismctl_cloud_boundary.PrismctlCloudBoundaryTests.test_cloud_benchmark_requires_per_case_consent_map",
    "cloud_status_buzz_readiness_guard": "test_reality_guards.RealityGuardTests.test_cloud_status_requires_buzz_readiness_and_reports_actual_ledger",
    "candidate_source_review_ui_guard": "test_reality_guards.RealityGuardTests.test_candidate_source_review_page_has_no_preselected_decision",
    "candidate_source_roster_approval_guard": "test_source_reviewer_roster.SourceReviewerRosterTests.test_add_requires_explicit_approval_and_prevents_identity_overwrite",
    "candidate_source_roster_shape_guard": "test_source_reviewer_roster.SourceReviewerRosterTests.test_invalid_roster_shape_fails_closed",
    "candidate_source_roster_distinct_key_guard": "test_source_reviewer_roster.SourceReviewerRosterTests.test_duplicate_buzz_key_fails_closed",
    "candidate_source_roster_signed_payload_guard": "test_source_reviewer_roster.SourceReviewerRosterTests.test_signed_roster_approval_cannot_be_reused_after_payload_drift",
    "candidate_source_roster_authority_scope_guard": "test_source_reviewer_roster.SourceReviewerRosterTests.test_wrong_authority_key_or_channel_cannot_approve_reviewer",
    "candidate_source_roster_unconfigured_authority_guard": "test_source_reviewer_roster.SourceReviewerRosterTests.test_unconfigured_authority_cannot_admit_a_reviewer",
    "reviewer_roster_authority_bootstrap_guard": "test_reviewer_roster_authority.ReviewerRosterAuthorityTests.test_configuration_requires_out_of_band_identity_confirmation",
    "reviewer_roster_authority_shared_scope_guard": "test_reviewer_roster_authority.ReviewerRosterAuthorityTests.test_one_configuration_binds_both_rosters_to_the_same_key_and_channel",
    "reviewer_roster_authority_replacement_guard": "test_reviewer_roster_authority.ReviewerRosterAuthorityTests.test_configured_authority_cannot_be_silently_replaced",
    "output_reviewer_self_assertion_guard": "test_first_pass_review.FirstPassReviewTests.test_self_asserted_output_reviewer_and_principal_are_rejected",
    "output_reviewer_signature_guard": "test_first_pass_review.FirstPassReviewTests.test_missing_or_forged_buzz_attestation_is_rejected",
    "output_reviewer_roster_approval_guard": "test_output_reviewer_roster.OutputReviewerRosterTests.test_add_output_reviewer_requires_approval_and_prevents_overwrite",
    "output_reviewer_roster_shape_guard": "test_output_reviewer_roster.OutputReviewerRosterTests.test_invalid_output_roster_fails_closed",
    "output_reviewer_roster_distinct_key_guard": "test_output_reviewer_roster.OutputReviewerRosterTests.test_duplicate_buzz_key_fails_closed",
    "judge_calibration_perfect_control": "test_judge_calibration.JudgeCalibrationTests.test_perfect_calibration_passes_every_gate",
    "judge_calibration_failure_controls": "test_judge_calibration.JudgeCalibrationTests.test_critical_false_pass_and_parse_failure_fail_closed",
    "judge_calibration_order_guard": "test_judge_calibration.JudgeCalibrationTests.test_order_flip_and_missing_case_trial_fail",
    "judge_calibration_receipt_and_sample_guard": "test_judge_calibration.JudgeCalibrationTests.test_receipt_hash_tamper_and_missing_judge_labels_are_rejected",
    "judge_calibration_signed_label_replay_guard": "test_judge_calibration.JudgeCalibrationTests.test_forged_receipt_and_updated_binding_cannot_replace_signed_labels",
    "judge_calibration_minimum_sample_guard": "test_judge_calibration.JudgeCalibrationTests.test_small_human_calibration_sample_is_rejected",
    "judge_calibration_saved_result_guard": "test_judge_calibration.JudgeCalibrationTests.test_saved_result_is_recomputed_and_tampering_fails",
    "review_attestation_renderer_guard": "test_review_signatures.ReviewSignatureTests.test_renderer_matches_canonical_content_and_ignores_event_id",
    "review_attestation_publication_guard": "test_review_publication.ReviewPublicationTests.test_verified_event_finalizes_the_unsigned_record",
    "candidate_rejection_cannot_promote": "test_candidate_source_review.CandidateSourceReviewTests.test_two_agreeing_rejections_do_not_make_a_draft_eligible",
    "candidate_adjudicated_rejection_cannot_promote": "test_candidate_source_review.CandidateSourceReviewTests.test_principal_selection_of_rejection_resolves_without_eligibility",
    "candidate_case_owner_approval_guard": "test_candidate_case_approval.CandidateCaseApprovalTests.test_independent_reviews_and_owner_signature_authorize_case_artifact",
    "candidate_case_authoring_material_guard": "test_candidate_case_approval.CandidateCaseApprovalTests.test_authoring_material_is_derived_from_agreed_reviews",
    "candidate_case_rejected_authoring_guard": "test_candidate_case_approval.CandidateCaseApprovalTests.test_rejected_reviews_cannot_create_authoring_material",
    "candidate_case_drift_guard": "test_candidate_case_approval.CandidateCaseApprovalTests.test_question_or_excerpt_drift_fails_approval",
    "candidate_case_approval_record_guard": "test_candidate_case_registration.CandidateCaseRegistrationTests.test_signed_approval_is_recorded_without_registering_a_case",
    "candidate_case_approval_record_duplicate_guard": "test_candidate_case_registration.CandidateCaseRegistrationTests.test_duplicate_signed_approval_cannot_be_recorded_twice",
    "candidate_case_approval_record_rollback_guard": "test_candidate_case_registration.CandidateCaseRegistrationTests.test_failed_approval_record_commit_leaves_ledger_unchanged",
    "candidate_case_approval_ledger_shape_guard": "test_candidate_case_registration.CandidateCaseRegistrationTests.test_approval_ledger_shape_fails_closed",
    "candidate_case_approval_chain_deletion_guard": "test_candidate_case_registration.CandidateCaseRegistrationTests.test_approval_ledger_tail_deletion_breaks_chain_header",
    "candidate_case_approval_chain_preappend_guard": "test_candidate_case_registration.CandidateCaseRegistrationTests.test_corrupt_approval_chain_fails_before_append",
    "candidate_case_sealed_approval_guard": "test_candidate_case_registration.CandidateCaseRegistrationTests.test_sealed_case_cannot_enter_approval_ledger",
    "candidate_case_unrecorded_registration_guard": "test_candidate_case_registration.CandidateCaseRegistrationTests.test_registration_rejects_valid_but_unrecorded_approval",
    "nostr_event_signature_replay_guard": "test_nostr_event.NostrEventTests.test_real_buzz_event_hash_and_signature_replay",
    "nostr_event_tamper_guard": "test_nostr_event.NostrEventTests.test_content_or_signature_tamper_fails",
    "candidate_case_atomic_registration_guard": "test_candidate_case_registration.CandidateCaseRegistrationTests.test_signed_approval_registers_through_one_ledger_commit",
    "candidate_case_duplicate_registration_guard": "test_candidate_case_registration.CandidateCaseRegistrationTests.test_duplicate_approval_cannot_register_twice",
    "candidate_case_failed_commit_guard": "test_candidate_case_registration.CandidateCaseRegistrationTests.test_failed_commit_leaves_ledger_unchanged",
    "candidate_case_cross_process_ledger_guard": "test_candidate_case_registration.CandidateCaseRegistrationTests.test_ledger_transaction_preserves_updates_from_distinct_processes",
    "candidate_case_registration_tamper_guard": "test_candidate_case_registration.CandidateCaseRegistrationTests.test_registered_source_or_artifact_tamper_breaks_contract",
    "candidate_case_registration_chain_deletion_guard": "test_candidate_case_registration.CandidateCaseRegistrationTests.test_registration_ledger_tail_deletion_breaks_chain_header",
    "candidate_pipeline_task_family_capacity_guard": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_candidate_pipeline_must_be_able_to_fill_each_task_family",
    "candidate_pipeline_task_family_binding_guard": "test_first_pass_benchmark_guard.FirstPassBenchmarkGuardTests.test_candidate_draft_task_family_cannot_drift_from_question_family",
    "unittest_discovery_integrity_guard": "test_test_discovery.TestDiscoveryTests.test_no_pytest_style_tests_are_invisible_to_unittest_discovery",
    "source_review_unsigned_export_guard": "test_source_review_record.SourceReviewRecordTests.test_unsigned_browser_export_is_schema_valid_and_cannot_be_an_attestation",
    "case_authoring_unsigned_export_guard": "test_case_authoring_record.CaseAuthoringRecordTests.test_unsigned_case_approval_is_schema_valid_and_not_an_attestation",
    "persistent_trace_restart": "test_trace_persistence.TracePersistenceTests.test_record_and_review_update_survive_restart",
    "concurrent_trace_persistence": "test_trace_persistence.TracePersistenceTests.test_concurrent_records_persist_without_loss_or_jsonl_corruption",
}

COLD_RESTART_EVIDENCE = PROJECT_ROOT / "evidence" / "bonsai-cold-restart.json"
CURRENT_LOCAL_PRODUCT_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "bonsai-local-product-verification-current.json"
)
TRACE_ANCHOR_EVIDENCE = PROJECT_ROOT / "evidence" / "trace-ledger-buzz-anchor-v1.json"
NETWORK_OBSERVATION_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "process-network-observation-v1.json"
)
OCR_ACCURACY_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "macos-vision-public-ocr-accuracy-v1.json"
)
ORACLE_CONTEXT_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "bonsai-oracle-context-diagnostic-v1.json"
)
TRACE_STORE = PROJECT_ROOT / ".runtime" / "evals" / "traces.jsonl"


def _atomic_write_report(path: Path, report: dict) -> None:
    """Commit one JSON report without exposing a partially written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    encoded = (json.dumps(report, indent=2) + "\n").encode("utf-8")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def finalize_report_output(
    report: dict,
    output_path: Path,
    *,
    canonical_current_path: Path = CURRENT_LOCAL_PRODUCT_EVIDENCE,
) -> dict:
    """Write a report and validate the canonical local report against its saved bytes."""
    output_path = output_path.resolve()
    canonical_current_path = canonical_current_path.resolve()
    finalized = copy.deepcopy(report)
    is_current_local = (
        output_path == canonical_current_path
        and finalized.get("runtime") == "local"
        and finalized.get("verification_phase") == "complete_verification"
    )
    if not is_current_local:
        _atomic_write_report(output_path, finalized)
        return finalized

    if finalized.get("selected_runtime_verified") is not True:
        failure_path = output_path.with_name(
            output_path.stem + "-failed-attempt" + output_path.suffix
        )
        finalized["canonical_commit"] = {
            "committed": False,
            "reason": "failed_run_cannot_replace_canonical_current_evidence",
            "preserved_record": str(output_path),
            "failure_record": str(failure_path),
        }
        _atomic_write_report(failure_path, finalized)
        return finalized

    finalized["current_local_engineering_evidence"] = {
        "passed": False,
        "measurement_state": "pending_exact_saved_report_validation",
        "not_evaluated": True,
        "errors": [],
    }
    _atomic_write_report(output_path, finalized)
    saved_validation = validate_current_local_product_evidence(output_path)
    finalized["current_local_engineering_evidence"] = saved_validation
    if not saved_validation["passed"]:
        finalized["selected_runtime_verified"] = False
    _atomic_write_report(output_path, finalized)

    final_validation = validate_current_local_product_evidence(output_path)
    if final_validation != saved_validation:
        finalized["current_local_engineering_evidence"] = final_validation
        finalized["selected_runtime_verified"] = False
        _atomic_write_report(output_path, finalized)
    return finalized
FIRST_PASS_EVIDENCE = PROJECT_ROOT / "evidence" / "bonsai-first-pass-titan-v7.json"
SCREEN_BOUND_FIRST_PASS_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "bonsai-first-pass-titan-screen-bound-v1.json"
)
SCREEN_BOUND_TITAN_INVESTMENT_SCREEN = (
    "Decide whether Project Titan should advance. Focus specifically on the mismatch "
    "between the reported debt paydown and ECF sweep schedule and Section 2.02 cash "
    "sweep policy. Identify missing or conflicting evidence. Do not infer an entry "
    "valuation multiple unless every input is cited."
)
OPERATOR_REVIEW_RESTART_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "operator-review-restart-anaplan-v1.json"
)
FIRST_PASS_DEVELOPMENT_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "bonsai-first-pass-public-development-v1.json"
)
BROWSER_EVIDENCE = PROJECT_ROOT / "evidence" / "browser-first-pass-v7.json"
CUSTOMER_DEMO_BROWSER_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "browser-customer-demo-v1.json"
)
COLD_RESTART_BROWSER_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "browser-first-pass-cold-restart.json"
)
REAL_DEAL_BROWSER_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "browser-real-deal-zendesk-v1.json"
)
PROVENANCE_BOUND_PUBLICATION_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "provenance-bound-publication-v1.json"
)
TITAN_DEBT_BROWSER_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "browser-titan-debt-chat-v1.json"
)
XLSX_WORKBOOK_CHAT_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "bonsai-xlsx-workbook-chat-v2.json"
)
OPERATOR_PREFLIGHT_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "operator-preflight-current.json"
)
LOCAL_DEPLOYMENT_EVIDENCE = PROJECT_ROOT / "evidence" / "local-deployment-current.json"
LIVE_INFERENCE_CONCURRENCY_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "live-inference-concurrency-v1.json"
)
ACCESSIBILITY_BROWSER_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "browser-accessibility-customer-demo-v1.json"
)
CROSS_BROWSER_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "browser-cross-engine-customer-demo-v1.json"
)
SOURCE_REVIEW_BROWSER_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "browser-source-review-v1.json"
)
CASE_AUTHORING_BROWSER_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "browser-case-authoring-v1.json"
)
OUTPUT_REVIEW_BROWSER_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "browser-output-review-v1.json"
)
OUTPUT_REVIEW_COMPLETION_FIXTURE_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "browser-output-review-completion-fixture-v1.json"
)
PRICING_POC_BROWSER_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "browser-pricing-poc-v1.json"
)
PRICING_POC_COMPLETION_FIXTURE_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "browser-pricing-poc-completion-fixture-v1.json"
)
FOLDER_PREVIEW_BROWSER_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "browser-folder-preview-v1.json"
)
BUZZ_POLLING_BROWSER_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "browser-buzz-polling-v1.json"
)
ZENDESK_SOURCE_EVIDENCE = PROJECT_ROOT / "evidence" / "candidate-source-zendesk_2022.json"
ZENDESK_COMPANION_SOURCE_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "candidate-companion-source-zendesk_2022.json"
)
HUMAN_REVIEW_PACKET = PROJECT_ROOT / "evidence" / "first-pass-human-review-packet-v2.json"
CANDIDATE_SOURCE_REVIEW_PACKET = (
    PROJECT_ROOT / "evidence" / "candidate-source-review-packet-v1.json"
)
CANDIDATE_SOURCE_REVIEW_VALIDATION = (
    PROJECT_ROOT / "evidence" / "candidate-source-review-validation-v1.json"
)
BROWSER_ASSERTIONS = {
    "synthetic_source_provenance_visible",
    "review_control_visible",
    "review_control_enabled",
    "trace_visible",
    "guard_visible",
    "runtime_state_boundary_visible",
    "canvas_signature_verified",
    "inline_citations_visible",
    "canonical_citation_navigation",
    "exact_anchor_preview",
    "trace_derived_runtime_state_card",
    "evidence_trace_visible",
    "measured_deployment_identity_visible",
    "deployment_and_invocation_states_separate",
    "trace_store_integrity_boundary_visible",
    "scanned_pdf_ocr_boundary_visible",
    "verification_fixture_exclusion_visible",
    "review_pending_not_rejected",
}
REAL_DEAL_BROWSER_ASSERTIONS = {
    "source_folder_bound",
    "custom_room_restored_from_persisted_registry",
    "hash_bound_public_source_set",
    "hash_verified_public_provenance_visible",
    "signed_answer_event_present",
    "answer_currently_trace_and_source_bound",
    "answer_event_signature_verified",
    "guarded_answer_trace_restored",
    "guarded_answer_event_trace_binding",
    "guarded_answer_requested_part_contract",
    "observed_value_matches_source_bounded_answer",
    "canonical_url_opens_discussion",
    "answer_event_focused",
    "verified_signature_visible",
    "bonsai_answer_visible",
    "machine_trace_marker_hidden_from_human_view",
    "human_requested_part_labels_visible",
    "bounded_evidence_scope_visible",
    "runtime_state_boundary_visible",
    "canvas_signature_verified",
    "answer_citation_visible",
    "all_requested_part_citations_exact",
    "citation_navigates_to_exact_anchor",
    "source_preview_contains_exact_cited_passage",
}
TITAN_DEBT_BROWSER_ASSERTIONS = {
    "buzz_workspace_ready",
    "trace_ledger_verified",
    "runtime_history_separate_from_current_process",
    "source_hash_and_anchor_bound",
    "accepted_question_signature_verified",
    "accepted_answer_signature_verified",
    "accepted_trace_event_binding",
    "capital_structure_contract_bound",
    "every_debt_instrument_visible_in_signed_answer",
    "equity_rows_excluded_from_debt_answer",
    "structural_pass_is_not_accuracy_release",
    "prior_rejection_retained",
    "accepted_trace_restored_after_restart",
    "canonical_discussion_event_focused",
    "verified_signature_visible",
    "human_debt_label_and_values_visible",
    "machine_marker_hidden",
    "exact_citation_visible",
    "citation_opens_exact_source_anchor",
    "source_preview_contains_debt_table",
}
ACCESSIBILITY_BROWSER_ASSERTIONS = {
    "document_language_declared",
    "single_main_landmark",
    "single_page_heading",
    "document_ids_unique",
    "room_views_use_tab_contract",
    "one_tab_selected_and_focusable",
    "inactive_panels_hidden",
    "visible_controls_have_names",
    "arrow_keys_move_and_activate_tabs",
    "keyboard_focus_is_visible",
    "citation_preview_is_keyboard_operable",
    "citation_preview_receives_and_traps_focus",
    "citation_preview_contains_exact_passage",
    "citation_preview_tab_loop_is_contained",
    "citation_preview_escape_restores_trigger",
    "citation_full_source_is_exact",
    "folder_dialog_traps_initial_focus",
    "dialog_escape_restores_trigger_focus",
    "reduced_motion_disables_animation",
    "mobile_page_has_no_unintended_horizontal_overflow",
    "visible_targets_are_at_least_24_pixels",
}
CROSS_BROWSER_ASSERTIONS = {
    "deal_brief_visible",
    "customer_navigation_visible",
    "source_citation_controls_visible",
    "semantic_tab_contract_visible",
    "keyboard_tab_navigation_works",
    "keyboard_citation_preview_is_exact",
    "citation_preview_focus_is_contained",
    "citation_full_source_navigation_is_exact",
    "mobile_width_has_no_page_overflow",
}
SOURCE_REVIEW_BROWSER_ASSERTIONS = {
    "source_gate_truth",
    "approval_gate_truth",
    "registration_gate_truth",
    "calibration_gate_truth",
    "release_gate_truth",
    "ten_decision_count_visible",
    "ten_decision_cards_visible",
    "ten_decision_api_matches_surface",
    "governance_receipt_count_visible",
    "governance_unconfigured_truth",
    "governance_matrix_geometry",
    "governance_material_hashes_visible",
    "governance_private_key_not_requested",
    "attestation_boundary",
    "oracle_summary_truth",
    "oracle_citrix_regression",
    "oracle_cma_persistent_failure",
    "no_preselected_decision",
    "no_preselected_answer_policy",
    "unsigned_export_closed_without_roster",
    "unconfigured_authority_visible",
    "pipeline_api_matches_surface",
    "packet_binding_matches_api",
    "all_release_task_families_have_review_leads",
    "two_cross_document_question_families_are_visible",
    "multi_document_draft_has_two_hash_bound_sources",
    "multi_document_sources_visible",
    "multi_document_evidence_from_both_sources_visible",
}
CASE_AUTHORING_BROWSER_ASSERTIONS = {
    "empty_source_review_gate",
    "queue_count_matches_api",
    "approval_and_registration_truth",
    "owner_control_closed",
    "unsigned_export_closed",
    "no_preselected_evaluation_slice",
    "api_preserves_stage_boundaries",
}
OUTPUT_REVIEW_BROWSER_ASSERTIONS = {
    "blinded_identity_state",
    "packet_case_count",
    "development_boundary",
    "closed_roster_guard",
    "five_cases_rendered",
    "no_dimension_label_preselected",
    "no_usefulness_preselected",
    "no_deal_decision_preselected",
    "unsigned_export_closed",
    "api_is_blinded_and_calibration_blocked",
    "model_identifier_absent_from_page",
    "loading_state_cleared",
}
OUTPUT_REVIEW_COMPLETION_FIXTURE_ASSERTIONS = {
    "fixture_roster_visible",
    "fixture_reviewer_selected",
    "five_cases_completed",
    "all_dimension_labels_explicit",
    "unsigned_export_enabled_after_completion",
    "unsigned_record_downloaded",
    "unsigned_record_case_count",
    "unsigned_record_packet_bound",
    "unsigned_record_not_attested",
    "unsigned_record_has_no_model_identity",
    "fixture_cannot_promote_review_gate",
}
PRICING_POC_BROWSER_ASSERTIONS = {
    "honest_empty_state",
    "buyer_authority_blocker_visible",
    "zero_of_ten_gates",
    "value_unit_visible",
    "paid_poc_gate_visible",
    "two_private_deals_gate_visible",
    "transfer_gate_visible",
    "post_use_price_gate_visible",
    "buyer_attestation_gate_visible",
    "buyer_relay_restoration_visible",
    "public_demo_boundary_visible",
    "api_preserves_unmeasured_state",
    "unsigned_builder_visible",
    "buyer_private_key_not_requested",
    "unsigned_builder_starts_blank",
}
PRICING_POC_COMPLETION_FIXTURE_ASSERTIONS = {
    "fixture_banner_visible",
    "unsigned_record_downloaded",
    "unsigned_record_has_no_buyer_attestation",
    "unsigned_record_has_no_buyer_authorization",
    "unsigned_record_passes_browser_contract",
    "two_distinct_source_hashes",
    "setup_and_transfer_roles_preserved",
    "post_use_prices_ordered",
    "fixture_key_is_public_only",
    "download_does_not_submit",
    "fixture_does_not_change_server_evidence",
}
FOLDER_PREVIEW_BROWSER_ASSERTIONS = {
    "preview_is_first_action",
    "preview_api_is_read_only",
    "content_hash_is_bound",
    "supported_inventory_visible",
    "no_publish_boundary_visible",
    "creation_requires_second_action",
}
BUZZ_POLLING_BROWSER_ASSERTIONS = {
    "delayed_poll_crossed_timer_interval",
    "no_overlapping_message_requests",
    "queued_refresh_executed",
    "server_reports_inflight_only_policy",
    "verified_messages_remain_visible",
    "hidden_tab_poll_suppressed",
    "visible_tab_refresh_resumed",
}


def iter_test_ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from iter_test_ids(item)
        else:
            yield item.id()


def run_tests() -> tuple[bool, int, int, set[str]]:
    provider_keys = [
        key for key in os.environ
        if key.startswith("PRISM_LOCAL_AI_") or key.startswith("PRISM_CLOUD_AI_")
    ]
    saved_provider_env = {key: os.environ[key] for key in provider_keys}
    saved_server_providers = server_module.global_providers
    for key in provider_keys:
        os.environ.pop(key, None)
    try:
        server_module.global_providers = ProviderRegistry()
        suite = unittest.defaultTestLoader.discover(str(PROJECT_ROOT / "tests"))
        discovered = set(iter_test_ids(suite))
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    finally:
        server_module.global_providers = saved_server_providers
        os.environ.update(saved_provider_env)
    return result.wasSuccessful(), result.testsRun, len(result.skipped), discovered


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def scan_claims(runtime_surfaces=None, document_surfaces=None):
    runtime_surfaces = RUNTIME_SURFACES if runtime_surfaces is None else runtime_surfaces
    document_surfaces = DOCUMENT_SURFACES if document_surfaces is None else document_surfaces
    violations = []
    for path in runtime_surfaces:
        text = path.read_text(encoding="utf-8")
        for claim in PROHIBITED_RUNTIME_CLAIMS:
            if claim in text:
                violations.append({"file": _display_path(path), "claim": claim})
    for path in document_surfaces:
        text = path.read_text(encoding="utf-8")
        for claim in PROHIBITED_DOCUMENT_ASSERTIONS:
            if claim.casefold() in text.casefold():
                violations.append({"file": _display_path(path), "claim": claim})
        for pattern, claim in PROHIBITED_VOLATILE_DOCUMENT_PATTERNS:
            if pattern.search(text):
                violations.append({"file": _display_path(path), "claim": claim})
    return violations


def check_frontend_contract() -> dict:
    html = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")
    stylesheet = (PROJECT_ROOT / "web" / "style.css").read_text(encoding="utf-8")
    source_review_html = (PROJECT_ROOT / "web" / "source-review.html").read_text(encoding="utf-8")
    source_review_javascript = (
        PROJECT_ROOT / "web" / "source-review.mjs"
    ).read_text(encoding="utf-8")
    case_authoring_html = (
        PROJECT_ROOT / "web" / "case-authoring.html"
    ).read_text(encoding="utf-8")
    case_authoring_javascript = (
        PROJECT_ROOT / "web" / "case-authoring.mjs"
    ).read_text(encoding="utf-8")
    output_review_html = (
        PROJECT_ROOT / "web" / "output-review.html"
    ).read_text(encoding="utf-8")
    output_review_javascript = (
        PROJECT_ROOT / "web" / "output-review.mjs"
    ).read_text(encoding="utf-8")
    violations = []
    if "onclick=" in html or "onchange=" in html or "onsubmit=" in html:
        violations.append("inline event handler conflicts with the script-src 'self' CSP")
    if '["Bonsai runtime", "27b@q1_0"' in javascript:
        violations.append("frontend hard-codes Bonsai invocation evidence")
    required_html_markers = (
        'id="view-first-pass"',
        'id="review-form"',
        'id="view-evidence"',
        "Select a file to read the passage used in the review.",
        "Messages stay with this room.",
        'src="/app.js?',
        'href="/style.css?',
        'role="tablist"',
        'role="tabpanel"',
        'id="source-preview" tabindex="-1" aria-live="polite"',
        'id="folder-preview" aria-live="polite" hidden',
        'id="create-room-button" value="default" type="submit">Preview folder',
        'id="contract-cloud"',
    )
    for marker in required_html_markers:
        if marker not in html:
            violations.append(f"frontend is missing first-pass surface contract: {marker}")
    required_javascript_markers = (
        "/api/workspace/first-pass",
        'action: "run"',
        'action: "review"',
        'draft.acceptance_state === "accepted"',
        'control.disabled = !reviewable',
        "trace.evaluation_state",
        'data-evaluation-state=',
        "evaluationState.label",
        "renderInlineCitations(line)",
        "[^\\[\\]#]+\\.(?:md|txt|html?|pdf|csv|json|xlsx)",
        "state.status.local_inference_invoked_in_process",
        "state.status.local_inference_recorded_history",
        '"hash_chained_local_jsonl_v1"',
        "Hash-chained local JSONL",
        "traceStore.meaning",
        '"No local model"',
        "configured only",
        "state.status.configured_local_model_name",
        "state.status?.measured_local_deployment",
        "configured_local_provider_network_scope",
        "Loopback IP URL enforced",
        '"Measured deployment identity"',
        "Artifacts are rechecked when file identity changes",
        "active_runtime",
        "Active context admission",
        "loaded_model_tokenizer_with_runtime_margin",
        "The model catalog maximum is not treated as usable capacity.",
        "Loopback binding is not a zero-egress, quality, or clean-machine claim.",
        "displayMessageContent(message, agent)",
        "renderEvidenceScope(message.prism_evidence_scope)",
        "These counts do not measure semantic coverage or prove full-document review.",
        "message.display_content || message.content",
        "prism:first-pass-draft",
        '"Draft blocked"',
        "deal_room_chat_guard_v",
        "Prism will not substitute a different passage.",
        "moveWorkspaceTabFocus",
        'preview.focus({ preventScroll: true })',
        "/api/deal-room/preview",
        "preview_sha256: state.folderPreview.preview_sha256",
        "Nothing has been published. Review the inventory, then create the room.",
        "OCR text, not reconstructed layout",
        "Engine confidence is not a measured accuracy score.",
        "Scanned PDF support",
        "accuracy has not been benchmarked",
        "state.status.cloud_consent",
        '"Hybrid AI cloud boundary"',
        "Denied before network",
        "browser cannot turn cloud access on with a checkbox",
        "published to and restored from Buzz",
    )
    for marker in required_javascript_markers:
        if marker not in javascript:
            violations.append(f"frontend is missing runtime truth marker: {marker}")
    for marker in (
        "@media (prefers-reduced-motion: reduce)",
        ".agent-toggle input:focus-visible + .toggle-track",
        ".decision-control input:focus-visible + span",
    ):
        if marker not in stylesheet:
            violations.append(f"frontend is missing accessibility contract: {marker}")
    for marker in (
        'id="source-review-form"',
        'name="source-decision"',
        'name="answer-policy"',
        'id="source-context-checked"',
        'id="pipeline-title"',
        'data-pipeline-stage="accuracy-release"',
    ):
        if marker not in source_review_html:
            violations.append(f"frontend is missing source-review contract: {marker}")
    if " checked" in source_review_html:
        violations.append("source-review UI preselects a reviewer decision")
    for marker in (
        "/api/benchmark/source-review",
        "/api/benchmark/source-review/context",
        "renderPipeline(packet.pipeline)",
        "accuracy_release_ready",
        "no stage promotes itself",
        "buildUnsignedReview",
        "Nothing was submitted or promoted",
    ):
        if marker not in source_review_javascript:
            violations.append(f"frontend is missing source-review script contract: {marker}")
    for marker in (
        'id="case-authoring-form"',
        'id="export-case-approval"',
        'href="/benchmark/source-review"',
    ):
        if marker not in case_authoring_html:
            violations.append(f"frontend is missing case-authoring contract: {marker}")
    if " checked" in case_authoring_html:
        violations.append("case-authoring UI preselects an evaluation slice")
    for marker in (
        "/api/benchmark/case-authoring",
        "buildUnsignedCaseApproval",
        "Nothing was signed, recorded, or registered",
    ):
        if marker not in case_authoring_javascript:
            violations.append(f"frontend is missing case-authoring script contract: {marker}")
    for marker in (
        'id="case-review-form"',
        'id="reviewer-id"',
        'id="export-review"',
        "Model identity withheld",
    ):
        if marker not in output_review_html:
            violations.append(f"frontend is missing output-review contract: {marker}")
    if " checked" in output_review_html:
        violations.append("output-review UI preselects a human judgment")
    for marker in (
        "/api/benchmark/output-review",
        "buildUnsignedOutputReview",
        "The packet is not model blind.",
        "Nothing is submitted from this browser.",
    ):
        if marker not in output_review_javascript:
            violations.append(f"frontend is missing output-review script contract: {marker}")
    node = shutil.which("node")
    if not node:
        return {"passed": False, "violations": violations, "javascript_syntax": "node unavailable"}
    checked = subprocess.run(
        [node, "--check", str(PROJECT_ROOT / "web" / "app.js")],
        capture_output=True, text=True, timeout=10,
    )
    if checked.returncode != 0:
        violations.append(checked.stderr.strip() or "web/app.js syntax check failed")
    source_review_checked = subprocess.run(
        [node, "--check", str(PROJECT_ROOT / "web" / "source-review.mjs")],
        capture_output=True, text=True, timeout=10,
    )
    if source_review_checked.returncode != 0:
        violations.append(
            source_review_checked.stderr.strip() or "web/source-review.mjs syntax check failed"
        )
    case_authoring_checked = subprocess.run(
        [node, "--check", str(PROJECT_ROOT / "web" / "case-authoring.mjs")],
        capture_output=True, text=True, timeout=10,
    )
    if case_authoring_checked.returncode != 0:
        violations.append(
            case_authoring_checked.stderr.strip()
            or "web/case-authoring.mjs syntax check failed"
        )
    output_review_checked = subprocess.run(
        [node, "--check", str(PROJECT_ROOT / "web" / "output-review.mjs")],
        capture_output=True, text=True, timeout=10,
    )
    if output_review_checked.returncode != 0:
        violations.append(
            output_review_checked.stderr.strip()
            or "web/output-review.mjs syntax check failed"
        )
    output_review_record_checked = subprocess.run(
        [node, "--check", str(PROJECT_ROOT / "web" / "output-review-record.mjs")],
        capture_output=True, text=True, timeout=10,
    )
    if output_review_record_checked.returncode != 0:
        violations.append(
            output_review_record_checked.stderr.strip()
            or "web/output-review-record.mjs syntax check failed"
        )
    return {
        "passed": not violations,
        "violations": violations,
        "javascript_syntax": (
            "passed"
            if checked.returncode == 0
            and source_review_checked.returncode == 0
            and case_authoring_checked.returncode == 0
            and output_review_checked.returncode == 0
            and output_review_record_checked.returncode == 0
            else "failed"
        ),
    }


def validate_cold_restart_evidence(record_path: Path = COLD_RESTART_EVIDENCE) -> dict:
    """Validate recorded process turnover and the canonical post-restart run."""
    record_path = record_path.resolve()
    errors = []
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}

    before = record.get("before", {})
    after = record.get("after", {})
    stop = record.get("stop_observation", {})
    if record.get("measurement_state") != "cold_restart_reproduced":
        errors.append("measurement_state is not cold_restart_reproduced")
    if not isinstance(before.get("pid"), int) or not isinstance(after.get("pid"), int):
        errors.append("before and after application PIDs must be recorded integers")
    elif before["pid"] == after["pid"]:
        errors.append("before and after application PIDs are identical")
    if not all(stop.get(field) is True for field in (
        "graceful_quit_requested", "old_pid_exited", "loopback_port_1234_closed"
    )):
        errors.append("the cold-stop observation is incomplete")
    commands = record.get("restart_commands", [])
    if not (
        any("server start --port 1234 --bind 127.0.0.1" in command for command in commands)
        and any("unload 27b@q1_0" in command for command in commands)
        and any("load 27b@q1_0" in command and "--context-length" in command
                for command in commands)
    ):
        errors.append("exact loopback server, unload, and model-load commands are missing")

    artifact_name = record.get("verification_artifact")
    artifact_path = (PROJECT_ROOT / str(artifact_name)).resolve()
    try:
        artifact_path.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        errors.append("verification artifact resolves outside the project")
    if not artifact_path.is_file():
        errors.append("verification artifact is missing")
        artifact = {}
    else:
        actual_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if actual_hash != record.get("verification_artifact_sha256"):
            errors.append("verification artifact SHA-256 does not match the restart record")
        try:
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            artifact = {}
            errors.append("verification artifact is not valid JSON")

    benchmark = artifact.get("benchmark", {})
    runtime = benchmark.get("runtime_evidence", {})
    cases = benchmark.get("cases", [])
    if artifact.get("verification_phase") != "post_restart_candidate_before_record_commit":
        errors.append("post-restart verification artifact has the wrong bootstrap phase")
    if not (
        artifact.get("cold_restart_evidence", {}).get("not_evaluated") is True
        and artifact.get("cold_restart_evidence", {}).get("measurement_state")
            == "pending_enclosing_cold_restart_record_commit"
    ):
        errors.append("post-restart verification artifact does not disclose the pending record commit")
    if artifact.get("runtime") != "local" or artifact.get("selected_runtime_verified") is not True:
        errors.append("post-restart local verification did not pass")
    if artifact.get("component_tests", {}).get("tests_skipped") != 0:
        errors.append("post-restart verification skipped component tests")
    if not (
        benchmark.get("total_cases") == 4
        and benchmark.get("passed_cases") == 4
        and benchmark.get("pass_rate") == 1.0
        and benchmark.get("mean_structured_check_coverage") == 1.0
        and benchmark.get("structured_check_measurement_state")
            == "preregistered_rule_coverage_not_domain_accuracy"
        and benchmark.get("mean_source_attribution_coverage") == 1.0
        and benchmark.get("grounding_measurement_state")
            == "filename_presence_only_not_semantic_grounding"
    ):
        errors.append("post-restart four-case quality thresholds were not met")
    if benchmark.get("dataset_sha256") != record.get("benchmark_dataset_sha256"):
        errors.append("post-restart dataset hash does not match the restart record")
    dependent = record.get("dependent_evidence")
    expected_dependencies = {
        "local_deployment": LOCAL_DEPLOYMENT_EVIDENCE,
        "live_inference_concurrency": LIVE_INFERENCE_CONCURRENCY_EVIDENCE,
        "process_network_observation": NETWORK_OBSERVATION_EVIDENCE,
        "browser_surface": COLD_RESTART_BROWSER_EVIDENCE,
    }
    if not isinstance(dependent, dict):
        errors.append("cold-restart record has no dependent evidence bindings")
    else:
        for name, expected_path in expected_dependencies.items():
            binding = dependent.get(name, {})
            expected_relative = str(expected_path.relative_to(PROJECT_ROOT))
            if binding.get("path") != expected_relative:
                errors.append(f"cold-restart dependent evidence path mismatch: {name}")
                continue
            try:
                actual_hash = hashlib.sha256(expected_path.read_bytes()).hexdigest()
            except OSError as exc:
                errors.append(f"cold-restart dependent evidence unavailable: {name}: {exc}")
                continue
            if binding.get("sha256") != actual_hash:
                errors.append(f"cold-restart dependent evidence hash mismatch: {name}")
    if not (
        after.get("context_length_requested") == 16384
        and after.get("backend_fit_context_length") == 16384
        and after.get("api_advertised_context_length") == 262144
        and after.get("request_context_admission")
            == "loaded_model_tokenizer_with_runtime_margin"
        and after.get("request_context_runtime_margin_tokens") == 32
        and after.get("request_reserved_output_tokens") == 4096
        and after.get("parallel_slots") == 4
    ):
        errors.append("post-restart fitted context and request admission state is incomplete")
    identity_fields = ("model", "artifact_sha256", "runtime_name", "runtime_version", "hardware")
    for field in identity_fields:
        if runtime.get(field) != after.get(field if field != "model" else "model_identifier"):
            errors.append(f"post-restart runtime identity mismatch: {field}")
    if runtime.get("provider_id") != "local_bonsai" or runtime.get("protocol") != "lmstudio_native_chat":
        errors.append("post-restart provider or protocol is not the required Bonsai-native path")
    if len(cases) != 4 or not all(
        case.get("passed") is True
        and case.get("sandbox_success") is True
        and case.get("provider_id") == "local_bonsai"
        and case.get("model_name") == after.get("model_identifier")
        for case in cases
    ):
        errors.append("post-restart cases do not all prove model-backed sandbox success")
    engineering_validation = validate_current_local_product_evidence(artifact_path)
    if not engineering_validation["passed"]:
        errors.extend(
            f"post-restart engineering evidence: {error}"
            for error in engineering_validation["errors"]
        )

    return {
        "passed": not errors,
        "record": (
            str(record_path.relative_to(PROJECT_ROOT))
            if record_path.is_absolute() and record_path.is_relative_to(PROJECT_ROOT)
            else str(record_path)
        ),
        "verification_artifact": artifact_name,
        "before_pid": before.get("pid"),
        "after_pid": after.get("pid"),
        "errors": errors,
        "limitations": record.get("limitations", []),
    }


def has_per_share_unit_label(text: str) -> bool:
    """Accept the two registered equivalent labels for a per-share value."""
    return bool(re.search(
        r"(?:USD\s+per\s+share|\$\s*/\s*share)",
        text,
        re.IGNORECASE,
    ))


def local_verification_cold_gate(
    runtime: str,
    cold_restart_candidate: bool,
    cold_restart_evidence: dict,
) -> bool:
    """Require committed cold evidence for normal local reports."""
    return bool(
        runtime != "local"
        or cold_restart_candidate
        or cold_restart_evidence.get("passed") is True
    )


def runtime_trace_anchor_gate(runtime: str, trace_anchor_evidence: dict) -> bool:
    """Require the production-ledger receipt only for local-runtime reports."""
    return bool(
        runtime != "local" or trace_anchor_evidence.get("passed") is True
    )


def runtime_network_observation_gate(runtime: str, network_evidence: dict) -> bool:
    """Require process-scoped observation only for local-runtime reports."""
    return bool(runtime != "local" or network_evidence.get("passed") is True)


def validate_current_local_product_evidence(
    record_path: Path = CURRENT_LOCAL_PRODUCT_EVIDENCE,
) -> dict:
    """Validate the saved current engineering run without claiming domain accuracy."""
    errors = []
    try:
        artifact = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}

    errors.extend(source_manifest_errors(
        artifact.get("engineering_source_manifest"), PROJECT_ROOT,
    ))

    dataset_path = PROJECT_ROOT / "benchmarks" / "deal_room_reliability.json"
    dataset_sha256 = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    benchmark = artifact.get("benchmark", {})
    runtime = benchmark.get("runtime_evidence", {})
    cases = benchmark.get("cases", [])
    by_id = {case.get("case_id"): case for case in cases}
    expected_ids = {
        "horizon_ebitda_stress", "titan_lbo_sweep",
        "aeroflux_accretion", "biovanguard_qoe",
    }

    if artifact.get("runtime") != "local" or artifact.get("selected_runtime_verified") is not True:
        errors.append("saved report is not a passing selected local runtime")
    tests = artifact.get("component_tests", {})
    if not (tests.get("passed") is True and tests.get("tests_skipped") == 0
            and tests.get("required_reality_tests_present") is True):
        errors.append("saved report did not pass the complete required component suite")
    if benchmark.get("benchmark_version") != 3:
        errors.append("saved report is not benchmark version 3")
    if benchmark.get("dataset_sha256") != dataset_sha256:
        errors.append("saved report dataset hash differs from the current benchmark")
    if not (
        benchmark.get("total_cases") == 4
        and benchmark.get("passed_cases") == 4
        and benchmark.get("pass_rate") == 1.0
        and benchmark.get("mean_structured_check_coverage") == 1.0
        and benchmark.get("structured_check_measurement_state")
            == "preregistered_rule_coverage_not_domain_accuracy"
        and benchmark.get("mean_source_attribution_coverage") == 1.0
        and benchmark.get("grounding_measurement_state")
            == "filename_presence_only_not_semantic_grounding"
    ):
        errors.append("saved report does not meet the four-case engineering thresholds")
    if set(by_id) != expected_ids:
        errors.append("saved report case inventory differs from the registered four cases")
    if not (
        runtime.get("provider_id") == "local_bonsai"
        and runtime.get("model") == "27b@q1_0"
        and runtime.get("protocol") == "lmstudio_native_chat"
        and re.fullmatch(r"[0-9a-f]{64}", str(runtime.get("artifact_sha256", "")))
        and all(runtime.get(field) for field in ("runtime_name", "runtime_version", "hardware"))
    ):
        errors.append("saved report lacks the required local Bonsai runtime identity")
    for case_id, case in by_id.items():
        if not (
            case.get("passed") is True
            and case.get("sandbox_success") is True
            and case.get("execution_mode") == "ai_generated_sandboxed_code"
            and case.get("provider_id") == "local_bonsai"
            and case.get("model_name") == "27b@q1_0"
            and case.get("missing_terms") == []
            and case.get("forbidden_hits") == []
            and case.get("observed_output")
            and case.get("observed_generated_code")
            and isinstance(case.get("generation_attempts"), int)
            and case.get("generation_attempts") >= 1
        ):
            errors.append(f"saved case is incomplete or unpassed: {case_id}")

    output = {case_id: str(case.get("observed_output", "")) for case_id, case in by_id.items()}
    if "NovaTech" not in output.get("horizon_ebitda_stress", ""):
        errors.append("Horizon output lacks the deal identifier")
    titan = output.get("titan_lbo_sweep", "")
    if ("PROJECT TITAN" not in titan or "MODEL_POLICY_MISMATCH" not in titan
            or re.search(r"\bBREACH\b", titan, re.IGNORECASE)):
        errors.append("Titan output violates the project or legal-claim boundary")
    aero = output.get("aeroflux_accretion", "")
    if (not all(term in aero for term in ("42.5M", "17.3M"))
            or not has_per_share_unit_label(aero)
            or any(term.lower() in aero.lower() for term in (
                "CFIUS", "Antitrust", "Policy Conclusion", "minimum 1%", "minimum 1.0%"
            ))):
        errors.append("AeroFlux output violates unit, relevance, or invented-policy boundaries")
    bio = output.get("biovanguard_qoe", "")
    if any(term.lower() in bio.lower() for term in (
        "Benchmark Multiple", "policy threshold", "Covenant/Policy Compliance"
    )):
        errors.append("BioVanguard output contains an invented policy conclusion")

    return {
        "passed": not errors,
        "record": str(record_path.relative_to(PROJECT_ROOT)) if record_path.is_relative_to(PROJECT_ROOT) else str(record_path),
        "dataset_sha256": benchmark.get("dataset_sha256"),
        "passed_cases": benchmark.get("passed_cases"),
        "total_cases": benchmark.get("total_cases"),
        "model": runtime.get("model"),
        "errors": errors,
        "limitations": [
            "This is a four-case synthetic engineering regression, not a deal-domain accuracy release.",
            "Restart reproduction is validated separately against the canonical cold-restart record.",
        ],
    }


def validate_first_pass_evidence(record_path: Path = FIRST_PASS_EVIDENCE) -> dict:
    errors = []
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}
    artifact = record.get("artifact", {})
    trace = record.get("trace", {})
    if record.get("verification_kind") != "trace_linked_first_pass_product_record":
        errors.append("unexpected first-pass verification kind")
    if record.get("product_path_verified") is not True:
        errors.append("product path is not verified")
    if record.get("accuracy_release_passed") is not False:
        errors.append("single-run evidence must not claim an accuracy release pass")
    if record.get("human_review_state") != "pending":
        errors.append("the saved Titan v7 artifact must remain pending human review")
    if not artifact.get("restored_from_buzz"):
        errors.append("artifact was not restored from Buzz")
    restoration = artifact.get("restoration_verification", {})
    if (
        restoration.get("state") != "verified"
        or restoration.get("event_id") != artifact.get("draft_event_id")
        or restoration.get("trace_id") != artifact.get("trace_id")
    ):
        errors.append("artifact lacks exact Buzz event and trace restoration proof")
    if not artifact.get("trace_id") or trace.get("trace_id") != artifact.get("trace_id"):
        errors.append("artifact and evaluation trace identities do not match")
    if trace.get("metadata", {}).get("draft_event_id") != artifact.get("draft_event_id"):
        errors.append("evaluation trace is not bound to the restored Buzz draft event")
    if trace.get("session_id") != record.get("room"):
        errors.append("evaluation trace session is not bound to the recorded room")
    artifact_markdown = str(artifact.get("markdown", ""))
    if trace.get("response_sha256") != hashlib.sha256(
        artifact_markdown.encode("utf-8")
    ).hexdigest():
        errors.append("evaluation trace response does not match the restored draft")
    if trace.get("metadata", {}).get("guard_version") != artifact.get("guard_version"):
        errors.append("evaluation trace and draft guard versions do not match")
    if artifact.get("artifact_mode") == "model_draft":
        if trace.get("metadata", {}).get("provider_id") != "local_bonsai":
            errors.append("model draft trace does not identify the local Bonsai provider")
        if not trace.get("model_name") or trace.get("model_name") != artifact.get("model"):
            errors.append("model draft and trace model identities do not match")
        if record.get("runtime", {}).get("invocation_evidence") != (
            "artifact_trace_id_bound_local_provider_record"
        ):
            errors.append("first-pass invocation evidence is not bound to the artifact trace")
    if not artifact.get("draft_event_id"):
        errors.append("signed Buzz draft event identity is missing")
    if not artifact.get("citations"):
        errors.append("saved first-pass artifact has no citations")
    source_folder = PROJECT_ROOT / "deal_rooms" / "project_titan_lbo"
    observed = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_folder.iterdir() if path.is_file()
    }
    recorded = {
        item.get("filename"): item.get("sha256") for item in record.get("source_files", [])
    }
    if observed != recorded:
        errors.append("saved first-pass source hashes do not match the current Titan folder")
    return {
        "passed": not errors,
        "record": (
            str(record_path.relative_to(PROJECT_ROOT))
            if record_path.is_absolute() and record_path.is_relative_to(PROJECT_ROOT)
            else str(record_path)
        ),
        "trace_id": artifact.get("trace_id"),
        "draft_event_id": artifact.get("draft_event_id"),
        "human_review_state": record.get("human_review_state"),
        "accuracy_release_passed": record.get("accuracy_release_passed"),
        "errors": errors,
        "limitations": record.get("limitations", []),
    }


def validate_screen_bound_first_pass_evidence(
    record_path: Path = SCREEN_BOUND_FIRST_PASS_EVIDENCE,
) -> dict:
    result = validate_first_pass_evidence(record_path)
    errors = list(result.get("errors", []))
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}
    artifact = record.get("artifact", {})
    trace = record.get("trace", {})
    metadata = trace.get("metadata", {})
    failure = record.get("model_failure_trace")
    snapshot = artifact.get("source_snapshot_sha256")

    if record.get("investment_screen") != SCREEN_BOUND_TITAN_INVESTMENT_SCREEN:
        errors.append("screen-bound evidence uses an unexpected investment screen")
    if (
        artifact.get("artifact_mode") != "evidence_safe_fallback"
        or artifact.get("authored_by") != "deterministic_evidence_renderer"
    ):
        errors.append("screen-bound evidence is not the honest deterministic fallback")
    if artifact.get("investment_screen_retrieval") != "screen_bound_v1" or (
        not isinstance(artifact.get("investment_screen_passage_count"), int)
        or artifact["investment_screen_passage_count"] < 1
    ):
        errors.append("screen-bound evidence has no verified screen-matched retrieval")
    for field in (
        "investment_screen_retrieval", "investment_screen_passage_count",
        "source_snapshot_sha256", "source_classification",
        "source_provenance_sha256", "source_provenance",
    ):
        if artifact.get(field) != metadata.get(field):
            errors.append(f"artifact and trace disagree on {field}")
    if not isinstance(snapshot, str) or not re.fullmatch(r"[0-9a-f]{64}", snapshot):
        errors.append("screen-bound evidence has an invalid source snapshot hash")
    else:
        current_source_folder = (
            PROJECT_ROOT / "deal_rooms" / "project_titan_lbo"
        ).resolve()
        if record.get("source_snapshot_scope") != "absolute_local_path":
            errors.append("screen-bound evidence has an unexpected snapshot scope")
        elif record.get("source_folder_resolved") == str(current_source_folder):
            current_snapshot = server_module.inspect_local_deal_room(
                str(current_source_folder)
            )["preview"]["preview_sha256"]
            if snapshot != current_snapshot:
                errors.append("screen-bound evidence source snapshot differs from current Titan")
            current_binding = server_module.source_provenance_binding(
                DEAL_ROOM_CATALOG["project_titan_lbo"]
            )
            if (
                artifact.get("source_classification")
                != current_binding.get("classification")
                or artifact.get("source_provenance_sha256")
                != current_binding.get("binding_sha256")
            ):
                errors.append("screen-bound evidence provenance differs from current Titan")
    markdown = str(artifact.get("markdown", ""))
    if "## Investment screen evidence" not in markdown:
        errors.append("fallback does not visibly separate investment-screen evidence")
    for citation_prefix in (
        "[03_Three_Statement_Financial_Model_2024_2028.csv#",
    ):
        if citation_prefix not in markdown:
            errors.append(f"screen-bound fallback is missing {citation_prefix}")
    provision_citation = (
        "[02_LBO_Debt_Financing_Credit_Agreement.md#node:node_para_3]"
    )
    if provision_citation not in artifact.get("citations", []) or provision_citation not in markdown:
        errors.append("screen-bound fallback is not bound to the Section 2.02 provision paragraph")
    if "[02_LBO_Debt_Financing_Credit_Agreement.md#node:sec_5_4]" in artifact.get(
        "citations", []
    ):
        errors.append("screen-bound fallback still treats the Section 2.02 heading as evidence")
    for threshold in ("50.0% of ECF", "25.0% of ECF", "0.0% of ECF"):
        if threshold not in markdown:
            errors.append(f"screen-bound fallback omits the provision threshold {threshold}")

    failure_id = metadata.get("model_failure_trace_id")
    if not isinstance(failure, dict) or failure.get("trace_id") != failure_id:
        errors.append("screen-bound fallback is not bound to its rejected-model trace")
    else:
        if failure.get("model_name") != "27b@q1_0" or failure.get("routed_tier") != "LOCAL_BONSAI_27B":
            errors.append("rejected-model trace does not identify the live Bonsai route")
        if failure.get("response") not in {"", None}:
            errors.append("rejected model prose was retained as an accepted trace response")
        if not any(
            evaluation.get("name") == "first_pass_acceptance"
            and evaluation.get("passed") is False
            for evaluation in failure.get("evaluations", [])
        ):
            errors.append("rejected-model trace has no failing first-pass evaluation")
        if failure.get("metadata", {}).get("result_state") != "rejected_before_buzz_draft":
            errors.append("rejected-model trace does not prove pre-publication rejection")

    return {
        **result,
        "passed": not errors,
        "errors": errors,
        "source_snapshot_sha256": snapshot,
        "investment_screen_passage_count": artifact.get(
            "investment_screen_passage_count"
        ),
        "model_failure_trace_id": failure_id,
        "acceptance_state": artifact.get("acceptance_state"),
    }


def validate_operator_review_restart_evidence(
    record_path: Path = OPERATOR_REVIEW_RESTART_EVIDENCE,
) -> dict:
    errors = []
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        manifest = json.loads(
            (PROJECT_ROOT / "benchmarks" / "public_deal_corpus_manifest.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}
    review = record.get("review", {})
    verification = review.get("signature_verification", {})
    if record.get("verification_kind") != "signed_operator_review_restart_record":
        errors.append("unexpected operator review verification kind")
    if record.get("accuracy_release_passed") is not False:
        errors.append("operator durability evidence must not claim an accuracy release")
    if record.get("artifact_mode") != "evidence_safe_fallback":
        errors.append("operator durability evidence is not bound to an evidence fallback")
    if record.get("review_subject") != "source_evidence_packet":
        errors.append("operator durability review relabels the source packet as a brief")
    if (
        review.get("benchmark_domain_review") is not False
        or review.get("authentication_scope") != "local_operator_bridge"
        or review.get("decision") != "pause"
        or review.get("useful_starting_point") is not False
        or review.get("notes")
        != "Automated durability smoke review. This is not domain review and does not assess accuracy."
    ):
        errors.append("operator durability review scope or decision changed")
    if review.get("restored_from_buzz") is not True or verification.get("state") != "verified":
        errors.append("operator review lacks signed Buzz restoration proof")
    for field in ("review_event_id", "canvas_event_id"):
        event_id = review.get(field)
        if not isinstance(event_id, str) or not re.fullmatch(r"[0-9a-f]{64}", event_id):
            errors.append(f"operator review has invalid {field}")
        if verification.get(field) != event_id:
            errors.append(f"operator review signature proof does not match {field}")
    if record.get("digest_event_id") != review.get("canvas_event_id"):
        errors.append("saved digest event does not match the reviewed canvas")
    if record.get("review_predates_server_process") is not True or not (
        isinstance(record.get("review_event_created_at"), (int, float))
        and isinstance(record.get("server_process_started_at"), (int, float))
        and record["review_event_created_at"] < record["server_process_started_at"]
    ):
        errors.append("saved review does not prove restoration after a process restart")
    if not re.fullmatch(r"trc_[0-9a-f]{12}", str(record.get("trace_id", ""))):
        errors.append("saved operator review trace ID is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("draft_event_id", ""))):
        errors.append("saved operator review draft event ID is invalid")

    expected_sources = [
        {
            "filename": item["filename"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
        }
        for item in manifest.get("documents", []) if item.get("room") == "anaplan"
    ]
    if record.get("source_folder") != ".runtime/public-deal-corpus/anaplan":
        errors.append("operator review evidence names an unexpected source folder")
    if record.get("source_files") != expected_sources:
        errors.append("operator review source identity differs from the public corpus manifest")
    return {
        "passed": not errors,
        "record": (
            str(record_path.relative_to(PROJECT_ROOT))
            if record_path.is_absolute() and record_path.is_relative_to(PROJECT_ROOT)
            else str(record_path)
        ),
        "room": record.get("room"),
        "trace_id": record.get("trace_id"),
        "review_event_id": review.get("review_event_id"),
        "canvas_event_id": review.get("canvas_event_id"),
        "review_predates_server_process": record.get("review_predates_server_process"),
        "benchmark_domain_review": review.get("benchmark_domain_review"),
        "artifact_mode": record.get("artifact_mode"),
        "review_subject": record.get("review_subject"),
        "accuracy_release_passed": record.get("accuracy_release_passed"),
        "errors": errors,
        "limitations": record.get("limitations", []),
    }


def validate_provenance_bound_publication(
    record_path: Path = PROVENANCE_BOUND_PUBLICATION_EVIDENCE,
) -> dict:
    errors: list[str] = []
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}
    if record.get("verification_kind") != "provenance_bound_publication":
        errors.append("unexpected provenance publication verification kind")
    assertions = record.get("assertions", [])
    if len(assertions) != 12 or not all(item.get("passed") is True for item in assertions):
        errors.append("provenance publication does not retain twelve passing live assertions")
    event = record.get("event", {})
    trace = record.get("trace", {})
    metadata = trace.get("metadata", {})
    event_id = record.get("event_id")
    trace_id = record.get("trace_id")
    if event.get("id") != event_id or nostr_event_errors(event):
        errors.append("provenance publication raw Buzz event failed identity or signature checks")
    marker = re.match(
        r"^<!-- prism:deal-room-answer model=([^\s]+) "
        r"guard=(deal_room_chat_guard_v\d+) trace=(trc_[0-9a-f]{12}) "
        r"source_class=([a-z0-9_]+) provenance=([0-9a-f]{64}) "
        r"source_snapshot=([0-9a-f]{64}) -->\n",
        str(event.get("content", "")),
    )
    if not marker:
        errors.append("provenance publication signed marker is missing or malformed")
    else:
        visible = str(event.get("content", ""))[marker.end():]
        expected = (
            trace.get("model_name"), metadata.get("guard_version"), trace_id,
            metadata.get("source_classification"),
            metadata.get("source_provenance_sha256"),
            metadata.get("source_snapshot_sha256"),
        )
        if marker.groups() != expected:
            errors.append("provenance publication marker differs from trace metadata")
        if visible != trace.get("response"):
            errors.append("provenance publication visible response differs from trace")
    if (
        trace.get("trace_id") != trace_id
        or trace.get("session_id") != record.get("room")
        or metadata.get("answer_event_id") != event_id
    ):
        errors.append("provenance publication event, trace, or room binding differs")
    room = server_module.all_deal_rooms().get(str(record.get("room", "")))
    if room is None and isinstance(record.get("source_folder"), str):
        source_folder = (PROJECT_ROOT / record["source_folder"]).resolve()
        if source_folder.is_relative_to(PROJECT_ROOT) and source_folder.is_dir():
            room = {"id": str(record.get("room", "")), "path": str(source_folder)}
    try:
        current_binding = server_module.source_provenance_binding(room) if room else None
        current_snapshot = (
            server_module.inspect_local_deal_room(room["path"])["preview"]["preview_sha256"]
            if room else None
        )
    except (FileNotFoundError, ValueError, NotADirectoryError, PermissionError, OSError) as exc:
        current_binding = None
        current_snapshot = None
        errors.append(f"provenance publication current room is unavailable: {exc}")
    if not current_binding or (
        current_binding.get("classification") != record.get("source_classification")
        or current_binding.get("binding_sha256") != record.get("source_provenance_sha256")
    ):
        errors.append("provenance publication no longer matches current room classification")
    relocated_evidence_check = os.environ.get(
        "PRISM_VERIFY_RELOCATED_EVIDENCE"
    ) == "1"
    if (
        current_snapshot != record.get("source_snapshot_sha256")
        and not relocated_evidence_check
    ):
        errors.append("provenance publication no longer matches current complete-folder snapshot")
    integrity = record.get("public_integrity", {})
    if integrity.get("passed") is not True or integrity.get("source_count") != 2:
        errors.append("provenance publication lacks the two-file public integrity proof")
    limitation_text = " ".join(record.get("limitations", [])).lower()
    if "not domain accuracy" not in limitation_text or "buyer" not in limitation_text:
        errors.append("provenance publication omits its accuracy or buyer limitation")
    return {
        "passed": not errors,
        "record": str(record_path),
        "room": record.get("room"),
        "event_id": event_id,
        "trace_id": trace_id,
        "source_classification": record.get("source_classification"),
        "source_provenance_sha256": record.get("source_provenance_sha256"),
        "source_snapshot_sha256": record.get("source_snapshot_sha256"),
        "assertion_count": len(assertions),
        "current_snapshot_recomputed": not relocated_evidence_check,
        "relocated_public_source_integrity_verified": relocated_evidence_check,
        "errors": errors,
        "limitations": record.get("limitations", []),
    }
def validate_first_pass_development_evidence(
    record_path: Path = FIRST_PASS_DEVELOPMENT_EVIDENCE,
) -> dict:
    errors = []
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}
    expected_hashes = {
        "benchmark_manifest_sha256": PROJECT_ROOT / "benchmarks" / "first_pass" / "benchmark_manifest.v1.json",
        "development_cases_sha256": PROJECT_ROOT / "benchmarks" / "first_pass" / "development_cases.v1.json",
        "source_manifest_sha256": PROJECT_ROOT / "benchmarks" / "public_deal_corpus_manifest.json",
    }
    for field, path in expected_hashes.items():
        if record.get(field) != hashlib.sha256(path.read_bytes()).hexdigest():
            errors.append(f"{field} does not match the current contract")
    if record.get("product_path_complete") is not True:
        errors.append("three-deal development product path is incomplete")
    if record.get("accuracy_release_passed") is not False:
        errors.append("development product path must not claim accuracy release")
    if record.get("domain_approval") != "not_reviewed":
        errors.append("development artifact domain approval state is not honest")
    if record.get("human_review_performed") is not False:
        errors.append("development artifact unexpectedly claims human review")
    if record.get("unauthorized_source_writes"):
        errors.append("development run changed source files")
    results = record.get("results", {})
    scopes = record.get("source_scope", {})
    if set(results) != {"anaplan_2022", "citrix_2022", "microsoft_activision_2023"}:
        errors.append("development artifact does not contain the three registered deals")
    for deal_id, result in results.items():
        scope = scopes.get(deal_id, {})
        if scope.get("passed") is not True:
            errors.append(f"{deal_id} source scope did not pass")
        if result.get("acceptance_state") not in {"accepted", "evidence_safe_fallback"}:
            errors.append(f"{deal_id} has no reviewable product artifact")
        if not all(result.get(field) for field in ("trace_id", "draft_event_id", "citations")):
            errors.append(f"{deal_id} is missing trace, event, or citation evidence")
        allowed = set(scope.get("expected_files", []))
        cited = {
            citation[1:].split("#", 1)[0]
            for citation in result.get("citations", [])
            if isinstance(citation, str) and citation.startswith("[") and "#" in citation
        }
        if not cited or not cited.issubset(allowed):
            errors.append(f"{deal_id} cites files outside its isolated deal scope")
    return {
        "passed": not errors,
        "record": str(record_path.relative_to(PROJECT_ROOT)),
        "deal_count": record.get("deal_count"),
        "registered_question_count": record.get("registered_question_count"),
        "acceptance_states": {
            deal_id: result.get("acceptance_state") for deal_id, result in results.items()
        },
        "accuracy_release_passed": record.get("accuracy_release_passed"),
        "errors": errors,
        "limitations": record.get("limitations", []),
    }


def validate_browser_evidence(record_path: Path = BROWSER_EVIDENCE) -> dict:
    errors = []
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        first_pass = json.loads(
            SCREEN_BOUND_FIRST_PASS_EVIDENCE.read_text(encoding="utf-8")
        )
        concurrency = json.loads(LIVE_INFERENCE_CONCURRENCY_EVIDENCE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}

    if record.get("verification_kind") != "replayable_browser_surface_check":
        errors.append("unexpected browser verification kind")
    if record.get("passed") is not True:
        errors.append("browser replay did not pass")
    expected_artifact = first_pass.get("artifact", {})
    browser_artifact = record.get("artifact", {})
    for field in ("trace_id", "draft_event_id"):
        if not browser_artifact.get(field) or browser_artifact.get(field) != expected_artifact.get(field):
            errors.append(
                f"browser {field} is not bound to the active screen-bound Titan artifact"
            )

    assertions = record.get("assertions", [])
    observed_names = {
        item.get("name") for item in assertions if isinstance(item, dict)
    }
    missing = sorted(BROWSER_ASSERTIONS - observed_names)
    if missing:
        errors.append(f"browser replay is missing assertions: {', '.join(missing)}")
    if any(item.get("passed") is not True for item in assertions if isinstance(item, dict)):
        errors.append("one or more browser assertions failed")
    for field in ("console_errors", "failed_requests", "http_errors"):
        if record.get(field):
            errors.append(f"browser replay recorded {field}")
    runtime_status = record.get("observed_runtime_status", {})
    if runtime_status.get("recorded_history") is not True:
        errors.append("browser runtime status does not record prior local invocation history")
    invoked_in_process = runtime_status.get("invoked_in_process")
    if invoked_in_process is True:
        if runtime_status.get("invocation_evidence") != "current_process_trace":
            errors.append("browser runtime status misclassifies current-process invocation evidence")
        if runtime_status.get("current_process_model") != runtime_status.get("configured_model"):
            errors.append("browser current-process model differs from the configured model")
    elif invoked_in_process is False:
        if runtime_status.get("invocation_evidence") != "recorded_trace_history":
            errors.append("browser runtime status misclassifies historical invocation evidence")
        if runtime_status.get("current_process_model") not in (None, ""):
            errors.append("browser history-only state unexpectedly names a current-process model")
    else:
        errors.append("browser runtime status has no explicit process invocation state")
    expected_runtime_model = (
        expected_artifact.get("model")
        if expected_artifact.get("artifact_mode") == "model_draft"
        else first_pass.get("model_failure_trace", {}).get("model_name")
    )
    if runtime_status.get("last_recorded_model") != expected_runtime_model:
        errors.append("browser runtime history model differs from the saved Titan artifact")
    review_state = record.get("observed_review_state", {})
    if not (
        review_state.get("trace_id") == concurrency.get("product_evidence", {}).get("trace_id")
        and review_state.get("state") == "awaiting_review"
        and review_state.get("label") == "Review pending"
    ):
        errors.append("browser does not distinguish a pending domain review from rejection")
    deployment_status = record.get("observed_measured_deployment", {})
    deployment_record_bytes = LOCAL_DEPLOYMENT_EVIDENCE.read_bytes()
    deployment_record_hash = hashlib.sha256(deployment_record_bytes).hexdigest()
    if not (
        deployment_status.get("verified") is True
        and deployment_status.get("record_sha256") == deployment_record_hash
        and record.get("deployment_record_sha256") == deployment_record_hash
        and deployment_status.get("model") == "27b@q1_0"
        and deployment_status.get("artifact_count") == 2
        and deployment_status.get("runtime", {}).get("effective_config", {}).get(
            "fitted_context_length"
        ) == "16384"
        and deployment_status.get("active_runtime", {}).get("verified") is True
        and deployment_status.get("active_runtime", {}).get("effective_config", {}).get(
            "bind_host"
        ) == "127.0.0.1"
        and re.fullmatch(
            r"\d{1,5}",
            str(deployment_status.get("active_runtime", {}).get(
                "effective_config", {}
            ).get("bind_port", "")),
        ) is not None
    ):
        errors.append("browser deployment card is not bound to the measured deployment record")
    canvas_verification = record.get("observed_canvas_verification", {})
    if canvas_verification.get("state") != "verified":
        errors.append("browser did not verify the Buzz canvas signature")
    if canvas_verification.get("scheme") != "nip01_event_id_plus_bip340":
        errors.append("browser canvas used an unexpected signature verification scheme")
    if not re.fullmatch(r"[0-9a-f]{64}", str(canvas_verification.get("event_id", ""))):
        errors.append("browser canvas has no verified event identity")

    screenshot = record.get("screenshot", {})
    screenshot_path = (PROJECT_ROOT / str(screenshot.get("path", ""))).resolve()
    try:
        screenshot_path.relative_to(PROJECT_ROOT)
    except ValueError:
        errors.append("browser screenshot path escapes the project root")
    else:
        try:
            screenshot_bytes = screenshot_path.read_bytes()
        except OSError as exc:
            errors.append(f"browser screenshot is unavailable: {exc}")
        else:
            if screenshot.get("bytes") != len(screenshot_bytes):
                errors.append("browser screenshot byte count does not match")
            digest = hashlib.sha256(screenshot_bytes).hexdigest()
            if screenshot.get("sha256") != digest:
                errors.append("browser screenshot digest does not match")
    if not record.get("limitations"):
        errors.append("browser evidence does not state its limitations")

    try:
        display_path = str(record_path.relative_to(PROJECT_ROOT))
    except ValueError:
        display_path = str(record_path)
    return {
        "passed": not errors,
        "record": display_path,
        "trace_id": browser_artifact.get("trace_id"),
        "draft_event_id": browser_artifact.get("draft_event_id"),
        "assertion_count": len(assertions),
        "browser": record.get("browser", {}),
        "screenshot": screenshot,
        "errors": errors,
        "limitations": record.get("limitations", []),
    }


def validate_real_deal_browser_evidence(
    record_path: Path = REAL_DEAL_BROWSER_EVIDENCE,
) -> dict:
    errors = []
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        acquisition = json.loads(ZENDESK_SOURCE_EVIDENCE.read_text(encoding="utf-8"))
        companion_acquisition = json.loads(
            ZENDESK_COMPANION_SOURCE_EVIDENCE.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}
    if record.get("verification_kind") != "replayable_real_deal_browser_check":
        errors.append("unexpected real-deal browser verification kind")
    if record.get("passed") is not True:
        errors.append("real-deal browser replay did not pass")
    if record.get("accuracy_release_passed") is not False:
        errors.append("one observed fact must not claim an accuracy release")
    if record.get("semantic_claim_state") != "multi_part_structural_pass_not_accuracy_release":
        errors.append("real-deal evidence overstates its semantic claim")

    source = record.get("source", {})
    acquired_source = acquisition.get("source", {})
    for field in ("path", "bytes", "sha256"):
        if source.get(field) != acquired_source.get(field):
            errors.append(f"browser source {field} is not bound to acquired SEC evidence")
    provenance = record.get("observed_source_provenance", {})
    public_integrity = provenance.get("public_integrity", {})
    expected_registry_paths = [
        "benchmarks/first_pass/candidate_companion_sources.v1.json",
        "benchmarks/first_pass/candidate_deal_sources.v1.json",
    ]
    expected_snapshot_items = []
    for acquired, registry_path in (
        (acquisition, expected_registry_paths[1]),
        (companion_acquisition, expected_registry_paths[0]),
    ):
        acquired_source = acquired.get("source", {})
        expected_snapshot_items.append({
            "path": Path(str(acquired_source.get("path", ""))).name,
            "sha256": acquired_source.get("sha256"),
            "bytes": acquired_source.get("bytes"),
            "registry_path": registry_path,
        })
    expected_public_snapshot = hashlib.sha256(
        json.dumps(
            sorted(expected_snapshot_items, key=lambda item: item["path"]),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    if (
        provenance.get("classification") != "public_filing_corpus"
        or provenance.get("label") != "Hash-verified public filing corpus"
        or provenance.get("public_source") is not True
        or provenance.get("manifest_bound") is not True
        or provenance.get("customer_data_verified") is not False
        or provenance.get("accuracy_release_evidence") is not False
        or provenance.get("buyer_evidence") is not False
        or public_integrity.get("passed") is not True
        or public_integrity.get("source_count") != 2
        or public_integrity.get("errors") != []
        or public_integrity.get("registry_paths") != expected_registry_paths
        or public_integrity.get("snapshot_sha256") != expected_public_snapshot
        or record.get("workspace_document_count") != 2
    ):
        errors.append("real-deal browser public provenance is not bound to both acquired filings")
    event_id = record.get("buzz", {}).get("answer_event_id")
    if not re.fullmatch(r"[0-9a-f]{64}", str(event_id or "")):
        errors.append("signed Buzz answer event identity is missing")
    canonical = record.get("buzz", {}).get("canonical_path", "")
    if canonical != f"/rooms/{record.get('room')}/discussion?event={event_id}":
        errors.append("canonical answer URL does not open the signed discussion event")

    assertions = record.get("assertions", [])
    observed_names = {
        item.get("name") for item in assertions if isinstance(item, dict)
    }

    missing = sorted(REAL_DEAL_BROWSER_ASSERTIONS - observed_names)
    if missing:
        errors.append(f"real-deal browser replay is missing assertions: {', '.join(missing)}")
    if any(item.get("passed") is not True for item in assertions if isinstance(item, dict)):
        errors.append("one or more real-deal browser assertions failed")
    for field in ("console_errors", "failed_requests", "http_errors"):
        if record.get(field):
            errors.append(f"real-deal browser replay recorded {field}")
    runtime_status = record.get("observed_runtime_status", {})
    if runtime_status.get("recorded_history") is not True:
        errors.append("real-deal browser runtime status lacks recorded local history")
    invoked_in_process = runtime_status.get("invoked_in_process")
    if invoked_in_process is True:
        if runtime_status.get("invocation_evidence") != "current_process_trace":
            errors.append("real-deal browser runtime status misclassifies current-process evidence")
        if runtime_status.get("current_process_model") != runtime_status.get("configured_model"):
            errors.append("real-deal browser current-process model differs from configuration")
    elif invoked_in_process is False:
        if runtime_status.get("invocation_evidence") != "recorded_trace_history":
            errors.append("real-deal browser runtime status misclassifies historical evidence")
        if runtime_status.get("current_process_model") not in (None, ""):
            errors.append("real-deal history-only state unexpectedly names a current-process model")
    else:
        errors.append("real-deal browser runtime status has no explicit process invocation state")
    if not runtime_status.get("last_recorded_model"):
        errors.append("real-deal browser runtime history has no recorded model identity")
    trace = record.get("observed_trace", {})
    trace_metadata = trace.get("metadata", {}) if isinstance(trace, dict) else {}
    expected_parts = [
        "consideration", "stockholder_approval", "regulatory_approval",
        "financing_condition",
    ]
    if not re.fullmatch(r"trc_[0-9a-f]{12}", str(trace.get("trace_id", ""))):
        errors.append("real-deal browser trace identity is missing")
    if trace.get("session_id") != record.get("room"):
        errors.append("real-deal browser trace room differs from the opened room")
    if trace.get("model_name") != runtime_status.get("last_recorded_model"):
        errors.append("real-deal browser trace model differs from runtime history")
    if trace_metadata.get("answer_event_id") != event_id:
        errors.append("real-deal browser trace is not bound to the answer event")
    if trace_metadata.get("guard_version") != "deal_room_chat_guard_v1":
        errors.append("real-deal browser trace has an unexpected chat guard")
    if trace_metadata.get("result_state") != "guard_passed_and_signed_to_buzz":
        errors.append("real-deal browser trace does not record signed publication")
    if trace_metadata.get("requested_parts") != expected_parts:
        errors.append("real-deal browser trace does not preserve the four requested parts")
    expected_observation = record.get("expected_observation", {})
    expected_anchors = expected_observation.get("source_anchors", [])
    traced_anchors = trace_metadata.get("retrieved_anchors", [])
    if not isinstance(expected_anchors, list) or len(expected_anchors) != 4:
        errors.append("real-deal browser expected anchors are incomplete")
    else:
        for anchor in expected_anchors:
            if not any(
                item.get("citation", "").endswith(f"#{anchor}]")
                and item.get("source_sha256") == source.get("sha256")
                for item in traced_anchors if isinstance(item, dict)
            ):
                errors.append(f"real-deal browser trace lacks source-bound anchor {anchor}")
    evaluations = {
        item.get("name"): item for item in trace.get("evaluations", [])
        if isinstance(item, dict)
    }
    if evaluations.get("deal_room_chat_publication_guard", {}).get("passed") is not True:
        errors.append("real-deal browser trace did not pass the structural publication guard")
    if evaluations.get("human_accuracy_review", {}).get("passed") is not False:
        errors.append("real-deal browser trace incorrectly claims human accuracy review")
    signature_verification = record.get("observed_signature_verification", {})
    if signature_verification.get("state") != "verified":
        errors.append("real-deal browser did not verify the answer event signature")
    if signature_verification.get("scheme") != "nip01_event_id_plus_bip340":
        errors.append("real-deal browser used an unexpected signature verification scheme")
    if not isinstance(signature_verification.get("verified_event_count"), int):
        errors.append("real-deal browser lacks a verified event count")
    canvas_verification = record.get("observed_canvas_verification", {})
    if canvas_verification.get("state") != "verified":
        errors.append("real-deal browser did not verify the Buzz canvas signature")
    if canvas_verification.get("scheme") != "nip01_event_id_plus_bip340":
        errors.append("real-deal browser canvas used an unexpected signature verification scheme")
    if not re.fullmatch(r"[0-9a-f]{64}", str(canvas_verification.get("event_id", ""))):
        errors.append("real-deal browser canvas has no verified event identity")
    registration = record.get("observed_room_registration", {})
    if registration.get("registry_path") != ".runtime/deal_rooms/registrations.v1.json":
        errors.append("real-deal browser room registry path is unexpected")
    if not re.fullmatch(r"[0-9a-f]{64}", str(registration.get("registry_sha256", ""))):
        errors.append("real-deal browser room registry digest is missing")
    if registration.get("restored_before_process") is not True:
        errors.append("real-deal browser did not prove room registration predates the server process")
    if registration.get("room_id") != record.get("room"):
        errors.append("real-deal browser room registry identity differs from the opened room")
    if not (
        isinstance(registration.get("registry_mtime"), (int, float))
        and isinstance(registration.get("server_process_started_at"), (int, float))
        and registration["registry_mtime"] < registration["server_process_started_at"]
    ):
        errors.append("real-deal browser room registry timestamp does not prove restart order")
    if Path(str(registration.get("folder_path", ""))).name != Path(
        str(source.get("path", ""))
    ).parent.name:
        errors.append("real-deal browser persisted folder differs from the acquired source folder")

    screenshot = record.get("screenshot", {})
    screenshot_path = (PROJECT_ROOT / str(screenshot.get("path", ""))).resolve()
    try:
        screenshot_path.relative_to(PROJECT_ROOT)
        screenshot_bytes = screenshot_path.read_bytes()
    except (ValueError, OSError) as exc:
        errors.append(f"real-deal browser screenshot is unavailable: {exc}")
    else:
        if screenshot.get("bytes") != len(screenshot_bytes):
            errors.append("real-deal screenshot byte count does not match")
        if screenshot.get("sha256") != hashlib.sha256(screenshot_bytes).hexdigest():
            errors.append("real-deal screenshot digest does not match")
    if not record.get("limitations"):
        errors.append("real-deal browser evidence does not state its limitations")
    try:
        display_path = str(record_path.relative_to(PROJECT_ROOT))
    except ValueError:
        display_path = str(record_path)
    return {
        "passed": not errors,
        "record": display_path,
        "room": record.get("room"),
        "answer_event_id": event_id,
        "source_sha256": source.get("sha256"),
        "assertion_count": len(assertions),
        "accuracy_release_passed": record.get("accuracy_release_passed"),
        "screenshot": screenshot,
        "errors": errors,
        "limitations": record.get("limitations", []),
    }


def validate_titan_debt_browser_evidence(
    record_path: Path = TITAN_DEBT_BROWSER_EVIDENCE,
) -> dict:
    errors = []
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}
    if record.get("verification_kind") != "replayable_titan_debt_chat_browser_check_v1":
        errors.append("unexpected Titan debt browser verification kind")
    if record.get("passed") is not True:
        errors.append("Titan debt browser replay did not pass")
    if record.get("measurement_state") != "structural_guard_passed_awaiting_domain_review":
        errors.append("Titan debt evidence overstates or loses its review boundary")
    if record.get("accuracy_release_passed") is not False:
        errors.append("Titan debt structural check must not claim an accuracy release")

    source = record.get("source", {})
    source_path = (PROJECT_ROOT / str(source.get("path", ""))).resolve()
    expected_citation = (
        "[01_Confidential_Information_Memorandum.md#node:node_tbl_1]"
    )
    try:
        source_path.relative_to(PROJECT_ROOT)
        source_bytes = source_path.read_bytes()
    except (ValueError, OSError) as exc:
        errors.append(f"Titan debt source is unavailable: {exc}")
    else:
        if source.get("bytes") != len(source_bytes):
            errors.append("Titan debt source byte count does not match")
        if source.get("sha256") != hashlib.sha256(source_bytes).hexdigest():
            errors.append("Titan debt source digest does not match")
    if source.get("citation") != expected_citation:
        errors.append("Titan debt evidence is not bound to the exact Sources of Funds table")

    buzz = record.get("buzz", {})
    for field in ("question_event_id", "accepted_answer_event_id", "prior_rejection_event_id"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(buzz.get(field, ""))):
            errors.append(f"Titan debt evidence lacks a valid {field}")
    if buzz.get("canonical_path") != (
        f"/rooms/{record.get('room')}/discussion?event={buzz.get('accepted_answer_event_id')}"
    ):
        errors.append("Titan debt canonical URL is not bound to the accepted answer")
    signature = buzz.get("signature_verification", {})
    if signature.get("state") != "verified" or signature.get("scheme") != "nip01_event_id_plus_bip340":
        errors.append("Titan debt Buzz history is not signature verified")

    accepted = record.get("accepted_trace", {})
    accepted_meta = accepted.get("metadata", {}) if isinstance(accepted, dict) else {}
    if not re.fullmatch(r"trc_[0-9a-f]{12}", str(accepted.get("trace_id", ""))):
        errors.append("Titan debt accepted trace identity is missing")
    if accepted.get("session_id") != record.get("room"):
        errors.append("Titan debt accepted trace room differs from the browser room")
    if accepted_meta.get("answer_event_id") != buzz.get("accepted_answer_event_id"):
        errors.append("Titan debt accepted trace is not bound to the answer event")
    if accepted_meta.get("question_event_id") != buzz.get("question_event_id"):
        errors.append("Titan debt accepted trace is not bound to the question event")
    if accepted_meta.get("result_state") != "guard_passed_and_signed_to_buzz":
        errors.append("Titan debt accepted trace does not record signed publication")
    if accepted_meta.get("requested_parts") != ["capital_structure"]:
        errors.append("Titan debt accepted trace does not preserve the capital-structure job")
    if accepted_meta.get("part_citations", {}).get("capital_structure") != [expected_citation]:
        errors.append("Titan debt accepted trace is not bound to the exact citation")
    if not any(
        item.get("citation") == expected_citation
        and item.get("source_sha256") == source.get("sha256")
        and item.get("requested_parts") == ["capital_structure"]
        for item in accepted_meta.get("retrieved_anchors", []) if isinstance(item, dict)
    ):
        errors.append("Titan debt retrieved evidence lacks the hash-bound capital-structure source")
    evaluations = {
        item.get("name"): item for item in accepted.get("evaluations", [])
        if isinstance(item, dict)
    }
    if evaluations.get("deal_room_chat_publication_guard", {}).get("passed") is not True:
        errors.append("Titan debt structural publication guard did not pass")
    human_review = evaluations.get("human_accuracy_review", {})
    if human_review.get("passed") is not False or human_review.get("metadata", {}).get(
        "measurement_state"
    ) != "awaiting_domain_review":
        errors.append("Titan debt evidence does not preserve pending human review")

    prior = record.get("prior_rejected_trace", {})
    prior_meta = prior.get("metadata", {}) if isinstance(prior, dict) else {}
    if prior.get("query") != accepted.get("query"):
        errors.append("Titan debt rejection and acceptance do not use the same question")
    if prior_meta.get("rejection_event_id") != buzz.get("prior_rejection_event_id"):
        errors.append("Titan debt prior rejection trace is not bound to its Buzz event")
    if prior_meta.get("result_state") != "rejected_before_buzz_answer":
        errors.append("Titan debt prior failure is not retained as a rejection")

    runtime = record.get("observed_runtime_status", {})
    if not (
        runtime.get("recorded_history") is True
        and runtime.get("invoked_in_process") is False
        and runtime.get("invocation_evidence") == "recorded_trace_history"
        and runtime.get("provider_network_scope") == "loopback_ip_literal"
        and isinstance(accepted.get("timestamp"), (int, float))
        and isinstance(runtime.get("server_process_started_at"), (int, float))
        and accepted["timestamp"] < runtime["server_process_started_at"]
    ):
        errors.append("Titan debt evidence does not prove history restoration after restart")

    assertions = record.get("assertions", [])
    observed_names = {item.get("name") for item in assertions if isinstance(item, dict)}
    missing = sorted(TITAN_DEBT_BROWSER_ASSERTIONS - observed_names)
    if missing:
        errors.append(f"Titan debt browser replay is missing assertions: {', '.join(missing)}")
    if any(item.get("passed") is not True for item in assertions if isinstance(item, dict)):
        errors.append("one or more Titan debt browser assertions failed")
    for field in ("console_errors", "failed_requests", "http_errors"):
        if record.get(field):
            errors.append(f"Titan debt browser replay recorded {field}")

    screenshot = record.get("screenshot", {})
    screenshot_path = (PROJECT_ROOT / str(screenshot.get("path", ""))).resolve()
    try:
        screenshot_path.relative_to(PROJECT_ROOT)
        screenshot_bytes = screenshot_path.read_bytes()
    except (ValueError, OSError) as exc:
        errors.append(f"Titan debt browser screenshot is unavailable: {exc}")
    else:
        if screenshot.get("bytes") != len(screenshot_bytes):
            errors.append("Titan debt screenshot byte count does not match")
        if screenshot.get("sha256") != hashlib.sha256(screenshot_bytes).hexdigest():
            errors.append("Titan debt screenshot digest does not match")
    if not record.get("limitations"):
        errors.append("Titan debt browser evidence does not state its limitations")
    try:
        display_path = str(record_path.relative_to(PROJECT_ROOT))
    except ValueError:
        display_path = str(record_path)
    return {
        "passed": not errors,
        "record": display_path,
        "room": record.get("room"),
        "answer_event_id": buzz.get("accepted_answer_event_id"),
        "prior_rejection_event_id": buzz.get("prior_rejection_event_id"),
        "source_sha256": source.get("sha256"),
        "assertion_count": len(assertions),
        "accuracy_release_passed": record.get("accuracy_release_passed"),
        "screenshot": screenshot,
        "errors": errors,
        "limitations": record.get("limitations", []),
    }


def validate_xlsx_workbook_chat_evidence(
    record_path: Path = XLSX_WORKBOOK_CHAT_EVIDENCE,
) -> dict:
    """Verify the live XLSX success and rejection from their raw signed Buzz events."""
    errors = []
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}

    if record.get("verification_kind") != "live_xlsx_webui_buzz_success_and_guard_rejection":
        errors.append("unexpected XLSX live verification kind")
    if record.get("passed") is not True:
        errors.append("XLSX live-smoke record does not pass")
    if record.get("accuracy_release_passed") is not False:
        errors.append("XLSX live smoke must not claim an accuracy release")
    if record.get("measurement_state") != "structural_guard_passed_awaiting_domain_review":
        errors.append("XLSX live smoke overstates or obscures its measurement state")

    source = record.get("source", {})
    accepted = record.get("accepted_run", {})
    rejected = record.get("rejected_run", {})
    browser = record.get("browser_observation", {})
    direct_acp = record.get("direct_acp_observation", {})
    identities = record.get("buzz_identities", {})
    raw_events = record.get("raw_buzz_events", {})
    room = record.get("room")
    channel = record.get("channel_id")
    citation = source.get("citation")
    response = str(accepted.get("response", ""))
    answer_event = accepted.get("answer_event_id")
    question_event = accepted.get("question_event_id")
    rejection_event = rejected.get("rejection_event_id")
    rejected_question_event = rejected.get("question_event_id")
    if room != "local_bbfa4e91f7ee" or channel != "f6f6917f-d4a0-498e-8f6e-fe643c7acbf7":
        errors.append("XLSX evidence is not bound to the observed room and Buzz channel")
    if not re.fullmatch(r"[0-9a-f]{64}", str(source.get("sha256", ""))):
        errors.append("XLSX source digest is missing")
    if source.get("observed_value") != "9997.2%":
        errors.append("XLSX displayed value is not preserved")
    if source.get("formula_boundary") != "Cached formulas were not recalculated.":
        errors.append("XLSX evidence is not bound to its calculation boundary")
    if citation != "[Pricing_Workbook.xlsx#xlsx:sheet:3]" or citation not in response:
        errors.append("XLSX answer is not bound to the exact admitted sheet citation")
    if "9997.2%" not in response or "not recalculated" not in response.lower():
        errors.append("XLSX answer lacks the observed value or calculation boundary")
    if accepted.get("response_sha256") != hashlib.sha256(response.encode()).hexdigest():
        errors.append("XLSX answer digest does not match its saved response")
    if not re.fullmatch(r"trc_[0-9a-f]{12}", str(accepted.get("trace_id", ""))):
        errors.append("XLSX accepted trace identity is missing")
    if accepted.get("inference_attempts") != 1 or accepted.get("publication_guard_passed") is not True:
        errors.append("XLSX successful run did not pass the first publication attempt")
    if accepted.get("provider") != "local_bonsai" or accepted.get("model") != "27b@q1_0":
        errors.append("XLSX evidence does not preserve the observed local model route")
    if not isinstance(accepted.get("latency_ms"), (int, float)) or accepted.get("latency_ms", 0) <= 0:
        errors.append("XLSX accepted run lacks a positive measured latency")
    for name, event_id in (
        ("question", question_event), ("answer", answer_event),
        ("rejected question", rejected_question_event), ("rejection", rejection_event),
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", str(event_id or "")):
            errors.append(f"XLSX {name} Buzz event identity is missing")
    expected_path = f"/rooms/{room}/discussion?event={answer_event}"
    if accepted.get("canonical_path") != expected_path:
        errors.append("XLSX canonical URL is not bound to the signed answer event")
    if rejected.get("draft_published_as_answer") is not False:
        errors.append("XLSX rejection record does not fail closed")
    if not re.fullmatch(r"trc_[0-9a-f]{12}", str(rejected.get("trace_id", ""))):
        errors.append("XLSX rejected trace identity is missing")
    if "publication guard" not in str(rejected.get("reason", "")):
        errors.append("XLSX rejection record lacks its publication-guard reason")

    expected_ids = {question_event, answer_event, rejected_question_event, rejection_event}
    if set(raw_events) != expected_ids:
        errors.append("XLSX evidence does not contain exactly its four raw Buzz events")
    owner = identities.get("owner_pubkey")
    agent = identities.get("agent_pubkey")
    if (
        not re.fullmatch(r"[0-9a-f]{64}", str(owner or ""))
        or not re.fullmatch(r"[0-9a-f]{64}", str(agent or ""))
        or owner == agent
    ):
        errors.append("XLSX evidence lacks distinct valid owner and agent identities")
    for event_id in expected_ids:
        event = raw_events.get(event_id, {})
        if event.get("id") != event_id:
            errors.append(f"XLSX raw Buzz event {event_id} has a mismatched identity")
            continue
        event_errors = nostr_event_errors(event)
        errors.extend(f"XLSX raw Buzz event {event_id}: {item}" for item in event_errors)
        if ["h", channel] not in event.get("tags", []):
            errors.append(f"XLSX raw Buzz event {event_id} is outside the recorded channel")
    for event_id in (question_event, rejected_question_event):
        if raw_events.get(event_id, {}).get("pubkey") != owner:
            errors.append(f"XLSX question event {event_id} is not owner signed")
    for event_id in (answer_event, rejection_event):
        if raw_events.get(event_id, {}).get("pubkey") != agent:
            errors.append(f"XLSX agent event {event_id} is not agent signed")
    if raw_events.get(question_event, {}).get("content") != accepted.get("question"):
        errors.append("XLSX accepted question differs from its signed Buzz event")
    accepted_content = str(raw_events.get(answer_event, {}).get("content", ""))
    accepted_marker = (
        f"<!-- prism:deal-room-answer model={accepted.get('model')} "
        f"guard=deal_room_chat_guard_v1 trace={accepted.get('trace_id')}"
    )
    if accepted.get("source_provenance_sha256"):
        accepted_marker += (
            f" source_class={accepted.get('source_classification')} "
            f"provenance={accepted.get('source_provenance_sha256')} "
            f"source_snapshot={accepted.get('source_snapshot_sha256')}"
        )
    accepted_marker += " -->\n"
    if accepted_content != accepted_marker + response:
        errors.append("XLSX accepted answer differs from its signed Buzz event or trace marker")
    if raw_events.get(rejected_question_event, {}).get("content") != rejected.get("question"):
        errors.append("XLSX rejected question differs from its signed Buzz event")
    rejection_content = str(raw_events.get(rejection_event, {}).get("content", ""))
    if (
        f"model=rejected guard=deal_room_chat_guard_v1 trace={rejected.get('trace_id')}"
        not in rejection_content
        or str(rejected.get("reason", "")) not in rejection_content
        or "No answer or accuracy claim was accepted." not in rejection_content
    ):
        errors.append("XLSX rejection differs from its signed fail-closed Buzz event")

    if browser.get("verified_event_count", 0) < 4:
        errors.append("XLSX browser did not observe enough verified signed events")
    if browser.get("accepted_answer_visible") is not True or browser.get("rejected_state_visible") is not True:
        errors.append("XLSX browser did not show both success and rejection states")
    if browser.get("source_preview_value_visible") is not True:
        errors.append("XLSX browser did not prove exact citation navigation")
    if browser.get("cached_formula_boundary_visible") is not True or browser.get("console_error_count") != 0:
        errors.append("XLSX browser calculation boundary or console state failed")
    expected_citation_target = (
        "/rooms/local_bbfa4e91f7ee/files?source=Pricing_Workbook.xlsx&anchor=xlsx%3Asheet%3A3"
    )
    if browser.get("citation_target") != expected_citation_target:
        errors.append("XLSX browser citation target is not bound to the exact room and sheet")
    if (
        direct_acp.get("required_for_v0") is not False
        or direct_acp.get("status") != "experimental_failed_live_response_gate"
        or direct_acp.get("scope_controls_passed") is not True
        or direct_acp.get("owner_only") is not True
        or direct_acp.get("memory_disabled") is not True
        or direct_acp.get("single_channel") != channel
        or "no signed reply" not in str(direct_acp.get("failure", ""))
    ):
        errors.append("XLSX evidence obscures the failed experimental direct-ACP response gate")
    limitations = record.get("limitations", [])
    limitation_text = " ".join(str(item).lower() for item in limitations)
    for phrase in ("not the versioned domain benchmark", "temporary", "not recalculate", "not been approved", "did not pass"):
        if phrase not in limitation_text:
            errors.append(f"XLSX live evidence lacks limitation: {phrase}")

    try:
        display_path = str(record_path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        display_path = str(record_path)

    return {
        "passed": not errors,
        "record": display_path,
        "trace_id": accepted.get("trace_id"),
        "answer_event_id": answer_event,
        "rejection_event_id": rejection_event,
        "source_sha256": source.get("sha256"),
        "accuracy_release_passed": record.get("accuracy_release_passed"),
        "errors": errors,
        "limitations": limitations,
    }


def validate_local_deployment_evidence(
    record_path: Path = LOCAL_DEPLOYMENT_EVIDENCE,
) -> dict:
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}
    errors = validate_deployment_record(record, verify_files=True)
    artifacts = record.get("artifacts", [])
    weights = next(
        (item for item in artifacts if isinstance(item, dict) and item.get("role") == "model_weights"),
        {},
    )
    try:
        display_path = str(record_path.relative_to(PROJECT_ROOT))
    except ValueError:
        display_path = str(record_path)
    return {
        "passed": not errors,
        "record": display_path,
        "measurement_state": record.get("measurement_state"),
        "model": record.get("model", {}).get("identifier"),
        "artifact_sha256": weights.get("sha256"),
        "artifact_count": len(artifacts) if isinstance(artifacts, list) else 0,
        "runtime_version": record.get("runtime", {}).get("version"),
        "effective_config": record.get("runtime", {}).get("effective_config", {}),
        "hardware": record.get("hardware", {}),
        "catalog_size_matches_artifact": record.get("model", {}).get(
            "catalog_size_matches_artifact"
        ),
        "errors": errors,
        "limitations": record.get("limitations", []),
    }


def validate_live_inference_concurrency_evidence(
    record_path: Path = LIVE_INFERENCE_CONCURRENCY_EVIDENCE,
) -> dict:
    errors = []
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}
    if record.get("schema_version") != 1:
        errors.append("unexpected live concurrency evidence schema")
    if record.get("verification_kind") != "live_inference_http_concurrency":
        errors.append("unexpected live concurrency verification kind")
    if record.get("measurement_state") != "real_bonsai_request_with_concurrent_status_probes":
        errors.append("live concurrency evidence is not a real Bonsai request measurement")
    if record.get("passed") is not True:
        errors.append("live concurrency evidence does not pass")
    deployment_hash = hashlib.sha256(LOCAL_DEPLOYMENT_EVIDENCE.read_bytes()).hexdigest()
    if record.get("deployment_record_sha256") != deployment_hash:
        errors.append("live concurrency evidence is not bound to the deployment record")
    request = record.get("request", {})
    if request.get("http_status") != 201 or request.get("answer_state") == "rejected":
        errors.append("live concurrency request was not accepted")
    for field in ("prompt_sha256", "response_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(request.get(field, ""))):
            errors.append(f"live concurrency request lacks {field}")
    product = record.get("product_evidence", {})
    for field in ("question_event_id", "answer_event_id"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(product.get(field, ""))):
            errors.append(f"live concurrency product evidence lacks {field}")
    if not re.fullmatch(r"trc_[0-9a-f]{12}", str(product.get("trace_id", ""))):
        errors.append("live concurrency product evidence lacks a trace ID")
    if not (
        product.get("question_signature_verified") is True
        and product.get("answer_signature_verified") is True
        and product.get("trace_result_state") == "guard_passed_and_signed_to_buzz"
        and product.get("provider_id") == "local_bonsai"
        and product.get("model") == "27b@q1_0"
    ):
        errors.append("live concurrency evidence lacks accepted signed Bonsai delivery")
    admitted = product.get("admitted_input_tokens")
    runtime_input = product.get("runtime_input_tokens")
    reserved = product.get("reserved_output_tokens")
    fitted = product.get("fitted_context_tokens")
    if not (
        product.get("context_admission") == "loaded_model_tokenizer_with_runtime_margin"
        and product.get("context_runtime_margin_tokens") == 32
        and reserved == 4_096
        and fitted == 16_384
        and isinstance(admitted, int)
        and isinstance(runtime_input, int)
        and 0 <= runtime_input <= admitted
        and admitted + reserved <= fitted
    ):
        errors.append("live concurrency evidence lacks fitted-context admission measurements")
    responsiveness = record.get("responsiveness", {})
    probes = responsiveness.get("probes", [])
    measured_latencies = [
        item.get("latency_ms") for item in probes
        if isinstance(item, dict) and isinstance(item.get("latency_ms"), (int, float))
    ] if isinstance(probes, list) else []
    if not probes or responsiveness.get("probe_count") != len(probes):
        errors.append("live concurrency evidence lacks its status probes")
    in_flight_count = sum(
        item.get("request_was_in_flight") is True
        for item in probes if isinstance(item, dict)
    ) if isinstance(probes, list) else 0
    if responsiveness.get("in_flight_probe_count") != in_flight_count or in_flight_count < 1:
        errors.append("live concurrency evidence has no probe during inference")
    observed_max = max(measured_latencies, default=None)
    if responsiveness.get("max_status_latency_ms") != observed_max:
        errors.append("live concurrency maximum latency differs from its probes")
    threshold = responsiveness.get("threshold_ms")
    if not isinstance(threshold, (int, float)) or threshold != 2_000:
        errors.append("live concurrency evidence changed the registered threshold")
    if observed_max is None or observed_max >= 2_000:
        errors.append("status was not responsive during live inference")
    if any(
        item.get("http_status") != 200
        or item.get("product_stage") != "local_prototype"
        or item.get("deployment_verified") is not True
        for item in probes if isinstance(item, dict)
    ):
        errors.append("one or more concurrent status probes returned invalid product state")
    limitation_text = " ".join(str(item).lower() for item in record.get("limitations", []))
    for phrase in (
        "not a load or soak test", "unverified for domain accuracy",
        "not a production service-level objective", "runtime-wrapper margin",
    ):
        if phrase not in limitation_text:
            errors.append(f"live concurrency evidence lacks limitation: {phrase}")
    try:
        display_path = str(record_path.relative_to(PROJECT_ROOT))
    except ValueError:
        display_path = str(record_path)
    return {
        "passed": not errors,
        "record": display_path,
        "trace_id": product.get("trace_id"),
        "request_duration_ms": request.get("duration_ms"),
        "probe_count": responsiveness.get("probe_count"),
        "max_status_latency_ms": responsiveness.get("max_status_latency_ms"),
        "errors": errors,
        "limitations": record.get("limitations", []),
    }


def validate_operator_preflight_evidence(
    record_path: Path = OPERATOR_PREFLIGHT_EVIDENCE,
) -> dict:
    errors = []
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}
    if record.get("verification_kind") != "operator_preflight":
        errors.append("unexpected operator preflight kind")
    if record.get("phase") != "live":
        errors.append("operator preflight did not check live services")
    if record.get("measurement_state") != "same_host_preflight_not_clean_machine_reproduction":
        errors.append("operator preflight overstates its reproduction scope")
    checks = {
        item.get("name"): item for item in record.get("checks", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    required_names = {
        "python_version", "project_files", "docker_cli", "docker_daemon",
        "docker_compose", "buzz_binaries", "model_endpoint_loopback",
        "bonsai_model_loaded", "reasoning_off_capability", "buzz_relay_live",
        "buzz_identity_permissions",
    }
    missing = sorted(required_names - set(checks))
    if missing:
        errors.append(f"operator preflight lacks required checks: {', '.join(missing)}")
    failed_required = sorted(
        name for name, item in checks.items()
        if item.get("required") is True and item.get("passed") is not True
    )
    if failed_required:
        errors.append(f"operator preflight has failed required checks: {', '.join(failed_required)}")
    if record.get("required_passed") is not True or failed_required:
        errors.append("operator preflight required-pass summary is false or inconsistent")
    model = checks.get("bonsai_model_loaded", {})
    model_observed = model.get("observed", {}) if isinstance(model, dict) else {}
    if (
        model.get("state") != "loaded"
        or model_observed.get("catalog_present") is not True
        or model_observed.get("loaded") is not True
    ):
        errors.append("operator preflight did not distinguish a loaded model from catalog presence")
    if checks.get("reasoning_off_capability", {}).get("state") != "supported":
        errors.append("operator preflight did not prove the reasoning-off capability")
    if checks.get("buzz_relay_live", {}).get("observed", {}).get("http_status") != 200:
        errors.append("operator preflight did not observe a live Buzz relay")
    if checks.get("buzz_identity_permissions", {}).get("observed") != "0o600":
        errors.append("operator preflight did not verify private Buzz key permissions")
    deployment = checks.get("benchmark_deployment_metadata", {})
    if deployment.get("required") is not False:
        errors.append("benchmark deployment metadata must remain a separate optional startup check")
    if deployment.get("passed") is True:
        observed = deployment.get("observed", {})
        if not all(observed.get(field) for field in (
            "artifact_sha256", "runtime_name", "runtime_version", "hardware"
        )):
            errors.append("operator preflight claims complete deployment metadata without all fields")
    limitation_text = " ".join(str(item).lower() for item in record.get("limitations", []))
    for phrase in ("not prove a clean physical machine", "not prove zero egress", "not artifact identity"):
        if phrase not in limitation_text:
            errors.append(f"operator preflight lacks limitation: {phrase}")
    try:
        display_path = str(record_path.relative_to(PROJECT_ROOT))
    except ValueError:
        display_path = str(record_path)
    return {
        "passed": not errors,
        "record": display_path,
        "phase": record.get("phase"),
        "required_check_count": sum(
            item.get("required") is True for item in checks.values()
        ),
        "model": model_observed.get("display_name"),
        "deployment_metadata_complete": deployment.get("passed") is True,
        "errors": errors,
        "limitations": record.get("limitations", []),
    }


def validate_accessibility_browser_evidence(
    record_path: Path = ACCESSIBILITY_BROWSER_EVIDENCE,
) -> dict:
    errors = []
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}
    if record.get("verification_kind") != "browser_accessibility_smoke":
        errors.append("unexpected accessibility browser verification kind")
    if record.get("semantic_state") != "accessibility_smoke_pass_not_conformance":
        errors.append("accessibility evidence overstates or fails its semantic boundary")
    if record.get("passed") is not True:
        errors.append("accessibility browser smoke did not pass")
    if record.get("room") != "project_titan_lbo":
        errors.append("accessibility browser record does not use the customer demo room")
    assertions = record.get("assertions", [])
    observed_names = {
        item.get("name") for item in assertions if isinstance(item, dict)
    }
    missing = sorted(ACCESSIBILITY_BROWSER_ASSERTIONS - observed_names)
    if missing:
        errors.append(f"accessibility browser smoke is missing assertions: {', '.join(missing)}")
    if any(item.get("passed") is not True for item in assertions if isinstance(item, dict)):
        errors.append("one or more accessibility browser assertions failed")
    for field in ("console_errors", "failed_requests", "http_errors"):
        if record.get(field):
            errors.append(f"accessibility browser smoke recorded {field}")
    screenshot = record.get("screenshot", {})
    screenshot_path = (PROJECT_ROOT / str(screenshot.get("path", ""))).resolve()
    try:
        screenshot_path.relative_to(PROJECT_ROOT)
        screenshot_bytes = screenshot_path.read_bytes()
    except (ValueError, OSError) as exc:
        errors.append(f"accessibility browser screenshot is unavailable: {exc}")
    else:
        if screenshot.get("bytes") != len(screenshot_bytes):
            errors.append("accessibility screenshot byte count does not match")
        if screenshot.get("sha256") != hashlib.sha256(screenshot_bytes).hexdigest():
            errors.append("accessibility screenshot digest does not match")
    limitations = record.get("limitations", [])
    if not limitations or not any("not WCAG conformance" in item for item in limitations):
        errors.append("accessibility evidence does not preserve its non-conformance boundary")
    try:
        display_path = str(record_path.relative_to(PROJECT_ROOT))
    except ValueError:
        display_path = str(record_path)
    return {
        "passed": not errors,
        "record": display_path,
        "room": record.get("room"),
        "assertion_count": len(assertions),
        "semantic_state": record.get("semantic_state"),
        "browser": record.get("browser", {}),
        "screenshot": screenshot,
        "errors": errors,
        "limitations": limitations,
    }


def validate_cross_browser_evidence(
    record_path: Path = CROSS_BROWSER_EVIDENCE,
) -> dict:
    errors = []
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}
    if record.get("verification_kind") != "cross_browser_real_deal_surface":
        errors.append("unexpected cross browser verification kind")
    if record.get("semantic_state") != "firefox_and_webkit_pass_not_safari_or_accuracy":
        errors.append("cross browser evidence overstates or fails its semantic boundary")
    if record.get("passed") is not True:
        errors.append("cross browser replay did not pass")
    if record.get("room") != "project_titan_lbo":
        errors.append("cross browser record does not use the customer demo room")
    engines = record.get("engines", [])
    observed_engines = {
        engine.get("engine") for engine in engines if isinstance(engine, dict)
    }
    if observed_engines != {"firefox", "webkit"} or len(engines) != 2:
        errors.append("cross browser evidence must contain one Firefox and one WebKit run")
    for engine in engines:
        if not isinstance(engine, dict):
            errors.append("cross browser engine record is invalid")
            continue
        name = str(engine.get("engine", "unknown"))
        if not engine.get("version"):
            errors.append(f"{name} browser version is missing")
        if engine.get("passed") is not True:
            errors.append(f"{name} browser replay did not pass")
        assertions = engine.get("assertions", [])
        observed_names = {
            item.get("name") for item in assertions if isinstance(item, dict)
        }
        missing = sorted(CROSS_BROWSER_ASSERTIONS - observed_names)
        if missing:
            errors.append(f"{name} browser replay is missing assertions: {', '.join(missing)}")
        if any(item.get("passed") is not True for item in assertions if isinstance(item, dict)):
            errors.append(f"one or more {name} browser assertions failed")
        for field in ("console_errors", "failed_requests", "http_errors"):
            if engine.get(field):
                errors.append(f"{name} browser replay recorded {field}")
        screenshot = engine.get("screenshot", {})
        screenshot_path = (PROJECT_ROOT / str(screenshot.get("path", ""))).resolve()
        try:
            screenshot_path.relative_to(PROJECT_ROOT)
            screenshot_bytes = screenshot_path.read_bytes()
        except (ValueError, OSError) as exc:
            errors.append(f"{name} browser screenshot is unavailable: {exc}")
        else:
            if screenshot.get("bytes") != len(screenshot_bytes):
                errors.append(f"{name} browser screenshot byte count does not match")
            if screenshot.get("sha256") != hashlib.sha256(screenshot_bytes).hexdigest():
                errors.append(f"{name} browser screenshot digest does not match")
    if record.get("engine_count") != 2:
        errors.append("cross browser engine count is not two")
    if record.get("assertion_count") != sum(
        len(engine.get("assertions", [])) for engine in engines if isinstance(engine, dict)
    ):
        errors.append("cross browser assertion count does not match engine records")
    limitations = record.get("limitations", [])
    if not limitations or not any("does not test Safari" in item for item in limitations):
        errors.append("cross browser evidence does not preserve its Safari boundary")
    try:
        display_path = str(record_path.relative_to(PROJECT_ROOT))
    except ValueError:
        display_path = str(record_path)
    return {
        "passed": not errors,
        "record": display_path,
        "room": record.get("room"),
        "engine_count": len(engines),
        "engines": [
            {"engine": engine.get("engine"), "version": engine.get("version"),
             "assertion_count": len(engine.get("assertions", [])),
             "screenshot": engine.get("screenshot")}
            for engine in engines if isinstance(engine, dict)
        ],
        "assertion_count": sum(
            len(engine.get("assertions", [])) for engine in engines if isinstance(engine, dict)
        ),
        "semantic_state": record.get("semantic_state"),
        "errors": errors,
        "limitations": limitations,
    }


def validate_source_review_browser_evidence(
    record_path: Path = SOURCE_REVIEW_BROWSER_EVIDENCE,
) -> dict:
    errors = []
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}
    if record.get("verification_kind") != "replayable_source_review_browser_check":
        errors.append("unexpected source-review browser verification kind")
    if record.get("passed") is not True:
        errors.append("source-review browser replay did not pass")
    assertions = record.get("assertions", [])
    observed_names = {
        item.get("name") for item in assertions if isinstance(item, dict)
    }
    missing = sorted(SOURCE_REVIEW_BROWSER_ASSERTIONS - observed_names)
    if missing:
        errors.append(f"source-review browser replay is missing assertions: {', '.join(missing)}")
    if any(item.get("passed") is not True for item in assertions if isinstance(item, dict)):
        errors.append("one or more source-review browser assertions failed")
    for field in ("console_errors", "failed_requests", "http_errors"):
        if record.get(field):
            errors.append(f"source-review browser replay recorded {field}")
    pipeline = record.get("observed_pipeline", {})
    try:
        contract = validate_contract(PROJECT_ROOT)
        current_source_packet = build_candidate_source_review_packet(PROJECT_ROOT)
        source_state = json.loads(
            CANDIDATE_SOURCE_REVIEW_VALIDATION.read_text(encoding="utf-8")
        )
        source_roster = json.loads(
            (
                PROJECT_ROOT
                / "benchmarks"
                / "first_pass"
                / "source_reviewer_roster.v1.json"
            ).read_text(encoding="utf-8")
        )
        output_roster = load_output_reviewer_roster(PROJECT_ROOT)
        calibration = validate_saved_judge_calibration(
            PROJECT_ROOT, server_module.JUDGE_CALIBRATION_EVIDENCE,
        )
        benchmark_channel = (
            server_module.BENCHMARK_REVIEW_CHANNEL.read_text(encoding="utf-8").strip()
            if server_module.BENCHMARK_REVIEW_CHANNEL.exists() else ""
        )
        current_pipeline = server_module.VaultHTTPRequestHandler._pipeline_state(
            source_state,
            source_roster,
            benchmark_channel,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"current benchmark state is unavailable: {exc}")
        contract = {"inventory": {}, "release_ready": None, "release_failures": []}
        source_state = {}
        source_roster = {"reviewers": []}
        output_roster = {"reviewers": []}
        calibration = {
            "evidence_state": "invalid", "calibration_passed": False,
        }
        current_source_packet = {}
        current_pipeline = {"benchmark_decisions": {}}
    if record.get("source_review_packet_sha256") != candidate_packet_sha256(
        current_source_packet
    ):
        errors.append("source-review browser packet hash differs from current review packet")
    if record.get("source_review_draft_count") != current_source_packet.get("draft_count"):
        errors.append("source-review browser draft count differs from current review packet")
    inventory = contract.get("inventory", {})
    active_case_owners = sum(
        item.get("active") is True and item.get("role") == "domain_case_owner"
        for item in source_roster.get("reviewers", [])
        if isinstance(item, dict)
    )
    qualified_output_reviewers = sum(
        item.get("active") is True
        and item.get("role") == "qualified_deal_output_reviewer"
        for item in output_roster.get("reviewers", [])
        if isinstance(item, dict)
    )
    principal_output_reviewers = sum(
        item.get("active") is True and item.get("role") == "principal_output_reviewer"
        for item in output_roster.get("reviewers", [])
        if isinstance(item, dict)
    )
    expected = {
        ("source_review", "eligible_count"): source_state.get(
            "eligible_for_case_authoring_count"
        ),
        ("source_review", "rejected_count"): source_state.get("rejected_draft_count"),
        ("source_review", "pending_count"): source_state.get("pending_draft_count"),
        ("case_approval", "recorded_approval_count"): inventory.get(
            "candidate_approvals_recorded"
        ),
        ("case_approval", "unregistered_approval_count"): inventory.get(
            "candidate_approvals_unregistered"
        ),
        ("case_approval", "registered_approval_count"): inventory.get(
            "candidate_cases_registered"
        ),
        ("case_approval", "active_domain_case_owner_count"): active_case_owners,
        ("case_approval", "roster_authority_state"): source_roster.get(
            "authority", {}
        ).get("state", "invalid"),
        ("case_approval", "storage"): (
            "hash_chained_content_addressed_signed_approval_ledger"
        ),
        ("registration", "candidate_cases_registered"): (
            inventory.get("candidate_cases_registered")
        ),
        ("registration", "total_cases_registered"): inventory.get("registered_cases"),
        ("registration", "total_deals_registered"): inventory.get("registered_deals"),
        ("calibration", "evaluator_available"): True,
        ("calibration", "reviewer_roster_authority_state"): output_roster.get(
            "authority", {}
        ).get("state", "invalid"),
        ("calibration", "registered_case_count"): inventory.get("calibration_cases"),
        ("calibration", "registered_deal_count"): inventory.get("calibration_deals"),
        ("calibration", "required_case_count"): inventory.get("target_calibration_cases"),
        ("calibration", "required_deal_count"): inventory.get("target_calibration_deals"),
        ("calibration", "qualified_output_reviewer_count"): qualified_output_reviewers,
        ("calibration", "principal_output_reviewer_count"): principal_output_reviewers,
        ("calibration", "evidence_state"): calibration.get("evidence_state"),
        ("calibration", "calibration_passed"): calibration.get("calibration_passed"),
        ("release", "accuracy_release_ready"): contract.get("release_ready"),
        ("release", "domain_approved_cases"): inventory.get("domain_approved_cases"),
        ("release", "target_cases"): inventory.get("target_cases"),
        ("release", "target_deals"): inventory.get("target_deals"),
        ("release", "blocker_count"): len(contract.get("release_failures", [])),
    }
    for (section, field), value in expected.items():
        if pipeline.get(section, {}).get(field) != value:
            errors.append(
                f"source-review browser {section}.{field} differs from current benchmark state"
            )
    if pipeline.get("benchmark_decisions") != current_pipeline.get("benchmark_decisions"):
        errors.append(
            "source-review browser ten benchmark decisions differ from current benchmark state"
        )
    if pipeline.get("governance") != current_pipeline.get("governance"):
        errors.append(
            "source-review browser governance matrix differs from current benchmark state"
        )
    observed_oracle = record.get("observed_oracle_diagnostic", {})
    current_oracle = validate_saved_oracle_context(
        PROJECT_ROOT, ORACLE_CONTEXT_EVIDENCE,
    )
    for field in (
        "passed",
        "engineering_diagnostic_completed",
        "eligible_case_count",
        "completed_case_count",
        "semantic_accuracy_state",
        "accuracy_release_passed",
        "localization_counts",
    ):
        if observed_oracle.get(field) != current_oracle.get(field):
            errors.append(
                f"source-review browser oracle diagnostic {field} differs from current evidence"
            )
    observed_localizations = {
        item.get("case_id"): item.get("localization")
        for item in observed_oracle.get("cases", []) if isinstance(item, dict)
    }
    try:
        saved_oracle_cases = json.loads(
            ORACLE_CONTEXT_EVIDENCE.read_text(encoding="utf-8")
        ).get("cases", [])
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"current oracle diagnostic cases are unavailable: {exc}")
        saved_oracle_cases = []
    expected_localizations = {
        item.get("case_id"): item.get("localization")
        for item in saved_oracle_cases if isinstance(item, dict)
    }
    if observed_localizations != expected_localizations:
        errors.append(
            "source-review browser oracle case localizations differ from current evidence"
        )
    screenshot = record.get("screenshot", {})
    screenshot_path = (PROJECT_ROOT / str(screenshot.get("path", ""))).resolve()
    try:
        screenshot_path.relative_to(PROJECT_ROOT)
        screenshot_bytes = screenshot_path.read_bytes()
    except (ValueError, OSError) as exc:
        errors.append(f"source-review browser screenshot is unavailable: {exc}")
    else:
        if screenshot.get("bytes") != len(screenshot_bytes):
            errors.append("source-review screenshot byte count does not match")
        if screenshot.get("sha256") != hashlib.sha256(screenshot_bytes).hexdigest():
            errors.append("source-review screenshot digest does not match")
    if not record.get("limitations"):
        errors.append("source-review browser evidence does not state its limitations")
    try:
        display_path = str(record_path.relative_to(PROJECT_ROOT))
    except ValueError:
        display_path = str(record_path)
    return {
        "passed": not errors,
        "record": display_path,
        "assertion_count": len(assertions),
        "accuracy_release_passed": pipeline.get("release", {}).get("accuracy_release_ready"),
        "screenshot": screenshot,
        "errors": errors,
        "limitations": record.get("limitations", []),
    }


def validate_case_authoring_browser_evidence(
    record_path: Path = CASE_AUTHORING_BROWSER_EVIDENCE,
) -> dict:
    errors = []
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}
    if record.get("verification_kind") != "replayable_case_authoring_browser_check":
        errors.append("unexpected case-authoring browser verification kind")
    if record.get("passed") is not True:
        errors.append("case-authoring browser replay did not pass")
    assertions = record.get("assertions", [])
    observed_names = {
        item.get("name") for item in assertions if isinstance(item, dict)
    }
    missing = sorted(CASE_AUTHORING_BROWSER_ASSERTIONS - observed_names)
    if missing:
        errors.append(f"case-authoring browser replay is missing assertions: {', '.join(missing)}")
    if any(item.get("passed") is not True for item in assertions if isinstance(item, dict)):
        errors.append("one or more case-authoring browser assertions failed")
    for field in ("console_errors", "failed_requests", "http_errors"):
        if record.get(field):
            errors.append(f"case-authoring browser replay recorded {field}")
    state = record.get("observed_state", {})
    pipeline = state.get("pipeline", {})
    try:
        contract = validate_contract(PROJECT_ROOT)
        source_state = json.loads(
            CANDIDATE_SOURCE_REVIEW_VALIDATION.read_text(encoding="utf-8")
        )
        packet = build_candidate_source_review_packet(PROJECT_ROOT)
        roster = json.loads(
            (
                PROJECT_ROOT
                / "benchmarks"
                / "first_pass"
                / "source_reviewer_roster.v1.json"
            ).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"current benchmark state is unavailable: {exc}")
        contract = {"inventory": {}, "release_ready": None, "release_failures": []}
        source_state = {}
        packet = {"draft_count": None}
        roster = {"reviewers": []}
    inventory = contract.get("inventory", {})
    active_case_owners = sum(
        item.get("active") is True and item.get("role") == "domain_case_owner"
        for item in roster.get("reviewers", [])
        if isinstance(item, dict)
    )
    expected_state = {
        "eligible_draft_count": source_state.get("eligible_for_case_authoring_count"),
        "total_draft_count": packet.get("draft_count"),
        "owner_roster_ready": active_case_owners > 0,
        "browser_owner_authentication_ready": False,
        "unsigned_export_ready": bool(
            source_state.get("eligible_for_case_authoring_count") and active_case_owners
        ),
    }
    for field, value in expected_state.items():
        if state.get(field) != value:
            errors.append(
                f"case-authoring browser {field} differs from current benchmark state"
            )
    expected_pipeline = {
        ("source_review", "eligible_count"): source_state.get(
            "eligible_for_case_authoring_count"
        ),
        ("case_approval", "recorded_approval_count"): inventory.get(
            "candidate_approvals_recorded"
        ),
        ("case_approval", "unregistered_approval_count"): inventory.get(
            "candidate_approvals_unregistered"
        ),
        ("case_approval", "registered_approval_count"): inventory.get(
            "candidate_cases_registered"
        ),
        ("case_approval", "active_domain_case_owner_count"): active_case_owners,
        ("case_approval", "roster_authority_state"): roster.get(
            "authority", {}
        ).get("state", "invalid"),
        ("registration", "candidate_cases_registered"): inventory.get(
            "candidate_cases_registered"
        ),
        ("release", "accuracy_release_ready"): contract.get("release_ready"),
        ("release", "domain_approved_cases"): inventory.get("domain_approved_cases"),
        ("release", "target_cases"): inventory.get("target_cases"),
        ("release", "target_deals"): inventory.get("target_deals"),
        ("release", "blocker_count"): len(contract.get("release_failures", [])),
    }
    for (section, field), value in expected_pipeline.items():
        if pipeline.get(section, {}).get(field) != value:
            errors.append(
                f"case-authoring browser {section}.{field} differs from current benchmark state"
            )
    screenshot = record.get("screenshot", {})
    screenshot_path = (PROJECT_ROOT / str(screenshot.get("path", ""))).resolve()
    try:
        screenshot_path.relative_to(PROJECT_ROOT)
        screenshot_bytes = screenshot_path.read_bytes()
    except (ValueError, OSError) as exc:
        errors.append(f"case-authoring browser screenshot is unavailable: {exc}")
    else:
        if screenshot.get("bytes") != len(screenshot_bytes):
            errors.append("case-authoring screenshot byte count does not match")
        if screenshot.get("sha256") != hashlib.sha256(screenshot_bytes).hexdigest():
            errors.append("case-authoring screenshot digest does not match")
    if not record.get("limitations"):
        errors.append("case-authoring browser evidence does not state its limitations")
    try:
        display_path = str(record_path.relative_to(PROJECT_ROOT))
    except ValueError:
        display_path = str(record_path)
    return {
        "passed": not errors,
        "record": display_path,
        "assertion_count": len(assertions),
        "accuracy_release_passed": pipeline.get("release", {}).get(
            "accuracy_release_ready"
        ),
        "screenshot": screenshot,
        "errors": errors,
        "limitations": record.get("limitations", []),
    }


def validate_output_review_browser_evidence(
    record_path: Path = OUTPUT_REVIEW_BROWSER_EVIDENCE,
) -> dict:
    errors = []
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}
    if record.get("verification_kind") != "replayable_output_review_browser_check":
        errors.append("unexpected output-review browser verification kind")
    if record.get("passed") is not True:
        errors.append("output-review browser replay did not pass")
    assertions = record.get("assertions", [])
    observed_names = {
        item.get("name") for item in assertions if isinstance(item, dict)
    }
    missing = sorted(OUTPUT_REVIEW_BROWSER_ASSERTIONS - observed_names)
    if missing:
        errors.append(f"output-review browser replay is missing assertions: {', '.join(missing)}")
    if any(item.get("passed") is not True for item in assertions if isinstance(item, dict)):
        errors.append("one or more output-review browser assertions failed")
    for field in ("console_errors", "failed_requests", "http_errors"):
        if record.get(field):
            errors.append(f"output-review browser replay recorded {field}")

    observed_packet = record.get("packet", {})
    observed_calibration = record.get("observed_calibration", {})
    try:
        packet = build_review_packet(PROJECT_ROOT, server_module.FIRST_PASS_REVIEW_RESPONSES)
        roster = load_output_reviewer_roster(PROJECT_ROOT)
        calibration = validate_saved_judge_calibration(
            PROJECT_ROOT, server_module.JUDGE_CALIBRATION_EVIDENCE,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"current output-review state is unavailable: {exc}")
        packet = {}
        roster = {"reviewers": []}
        calibration = {"evidence_state": "invalid", "calibration_passed": False}
    qualified_reviewers = [
        item for item in roster.get("reviewers", [])
        if isinstance(item, dict)
        and item.get("active") is True
        and item.get("role") == "qualified_deal_output_reviewer"
    ]
    expected_packet = {
        "packet_sha256": packet_sha256(packet) if packet else None,
        "rubric_sha256": packet.get("rubric_sha256"),
        "case_count": len(packet.get("cases", [])),
        "blinded_to_model": packet.get("blinded_to_model"),
        "model_identity_included": packet.get("model_identity_included"),
        "reviewer_roster_ready": len(qualified_reviewers) >= 2,
        "unsigned_export_ready": bool(qualified_reviewers),
    }
    for field, value in expected_packet.items():
        if observed_packet.get(field) != value:
            errors.append(f"output-review browser packet.{field} differs from current state")
    if observed_packet.get("blinded_to_model") is not True:
        errors.append("output-review browser packet is not blinded")
    if observed_packet.get("model_identity_included") is not False:
        errors.append("output-review browser packet includes model identity")
    for field in ("evidence_state", "calibration_passed"):
        if observed_calibration.get(field) != calibration.get(field):
            errors.append(
                f"output-review browser calibration.{field} differs from current state"
            )
    if observed_calibration.get("reviewer_roster_authority_state") != roster.get(
        "authority", {}
    ).get("state", "invalid"):
        errors.append("output-review browser calibration authority state differs from current state")

    screenshot = record.get("screenshot", {})
    screenshot_path = (PROJECT_ROOT / str(screenshot.get("path", ""))).resolve()
    try:
        screenshot_path.relative_to(PROJECT_ROOT)
        screenshot_bytes = screenshot_path.read_bytes()
    except (ValueError, OSError) as exc:
        errors.append(f"output-review browser screenshot is unavailable: {exc}")
    else:
        if screenshot.get("bytes") != len(screenshot_bytes):
            errors.append("output-review screenshot byte count does not match")
        if screenshot.get("sha256") != hashlib.sha256(screenshot_bytes).hexdigest():
            errors.append("output-review screenshot digest does not match")
    if not record.get("limitations"):
        errors.append("output-review browser evidence does not state its limitations")
    try:
        display_path = str(record_path.relative_to(PROJECT_ROOT))
    except ValueError:
        display_path = str(record_path)
    return {
        "passed": not errors,
        "record": display_path,
        "assertion_count": len(assertions),
        "blinded_to_model": observed_packet.get("blinded_to_model"),
        "calibration_passed": observed_calibration.get("calibration_passed"),
        "screenshot": screenshot,
        "errors": errors,
        "limitations": record.get("limitations", []),
    }


def validate_output_review_completion_fixture_evidence(
    record_path: Path = OUTPUT_REVIEW_COMPLETION_FIXTURE_EVIDENCE,
) -> dict:
    errors = []
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}
    if record.get("verification_kind") != "synthetic_output_review_completion_browser_fixture":
        errors.append("unexpected output-review completion fixture kind")
    if record.get("passed") is not True:
        errors.append("output-review completion fixture did not pass")
    for field, expected in (
        ("synthetic_reviewer_fixture", True),
        ("human_review_performed", False),
        ("review_gate_complete", False),
        ("accuracy_release_passed", False),
    ):
        if record.get(field) is not expected:
            errors.append(f"output-review completion fixture has unsafe {field} state")
    assertions = record.get("assertions", [])
    observed_names = {
        item.get("name") for item in assertions if isinstance(item, dict)
    }
    missing = sorted(OUTPUT_REVIEW_COMPLETION_FIXTURE_ASSERTIONS - observed_names)
    if missing:
        errors.append(
            "output-review completion fixture is missing assertions: " + ", ".join(missing)
        )
    if any(item.get("passed") is not True for item in assertions if isinstance(item, dict)):
        errors.append("one or more output-review completion fixture assertions failed")
    for field in ("console_errors", "failed_requests", "http_errors"):
        if record.get(field):
            errors.append(f"output-review completion fixture recorded {field}")

    observed_packet = record.get("packet", {})
    unsigned = record.get("fixture_unsigned_record", {})
    fixtures = record.get("fixture_reviewers", [])
    try:
        packet = build_review_packet(PROJECT_ROOT, server_module.FIRST_PASS_REVIEW_RESPONSES)
        roster = load_output_reviewer_roster(PROJECT_ROOT)
        schema = json.loads(
            (
                PROJECT_ROOT / "benchmarks" / "first_pass"
                / "human_review_submission.schema.json"
            ).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"current output-review fixture dependencies are unavailable: {exc}")
        packet = {}
        roster = {"reviewers": []}
        schema = {}
    expected_packet = {
        "packet_sha256": packet_sha256(packet) if packet else None,
        "rubric_sha256": packet.get("rubric_sha256"),
        "case_count": len(packet.get("cases", [])),
        "blinded_to_model": packet.get("blinded_to_model"),
        "model_identity_included": packet.get("model_identity_included"),
    }
    for field, value in expected_packet.items():
        if observed_packet.get(field) != value:
            errors.append(
                f"output-review completion fixture packet.{field} differs from current state"
            )
    if schema and schema_errors(unsigned, schema):
        errors.extend(
            "output-review completion unsigned record " + item
            for item in schema_errors(unsigned, schema)
        )
    fixture_ids = {item.get("reviewer_id") for item in fixtures if isinstance(item, dict)}
    fixture_keys = {item.get("buzz_pubkey") for item in fixtures if isinstance(item, dict)}
    approved_ids = {
        item.get("reviewer_id") for item in roster.get("reviewers", [])
        if isinstance(item, dict)
    }
    approved_keys = {
        item.get("buzz_pubkey") for item in roster.get("reviewers", [])
        if isinstance(item, dict)
    }
    if fixture_ids != {"fixture.output.one", "fixture.output.two"}:
        errors.append("output-review completion fixture reviewer IDs changed")
    if fixture_ids & approved_ids or fixture_keys & approved_keys:
        errors.append("synthetic output-review fixture appears on the approved roster")
    if unsigned.get("reviewer_id") != "fixture.output.one":
        errors.append("output-review completion record has an unexpected fixture reviewer")
    if unsigned.get("buzz_event_id") != "0" * 64:
        errors.append("output-review completion record is not explicitly unsigned")
    if unsigned.get("packet_sha256") != expected_packet["packet_sha256"]:
        errors.append("output-review completion record differs from the current packet")
    expected_cases = {
        item.get("case_id"): item for item in packet.get("cases", [])
        if isinstance(item, dict)
    }
    observed_cases = {
        item.get("case_id"): item for item in unsigned.get("cases", [])
        if isinstance(item, dict)
    }
    if set(observed_cases) != set(expected_cases) or len(unsigned.get("cases", [])) != len(observed_cases):
        errors.append("output-review completion record does not contain every packet case once")
    for case_id, expected_case in expected_cases.items():
        observed_case = observed_cases.get(case_id, {})
        if observed_case.get("response_sha256") != expected_case.get("response_sha256"):
            errors.append(f"output-review completion response hash differs for {case_id}")
        dimensions = observed_case.get("dimensions", [])
        if {
            item.get("dimension") for item in dimensions if isinstance(item, dict)
        } != set(expected_case.get("dimensions_to_review", [])):
            errors.append(f"output-review completion dimensions differ for {case_id}")
    encoded_unsigned = (json.dumps(unsigned, indent=2) + "\n").encode("utf-8")
    if record.get("fixture_unsigned_record_sha256") != hashlib.sha256(encoded_unsigned).hexdigest():
        errors.append("output-review completion downloaded record hash does not match")

    screenshot = record.get("screenshot", {})
    screenshot_path = (PROJECT_ROOT / str(screenshot.get("path", ""))).resolve()
    try:
        screenshot_path.relative_to(PROJECT_ROOT)
        screenshot_bytes = screenshot_path.read_bytes()
    except (ValueError, OSError) as exc:
        errors.append(f"output-review completion screenshot is unavailable: {exc}")
    else:
        if screenshot.get("bytes") != len(screenshot_bytes):
            errors.append("output-review completion screenshot byte count does not match")
        if screenshot.get("sha256") != hashlib.sha256(screenshot_bytes).hexdigest():
            errors.append("output-review completion screenshot digest does not match")
    if not record.get("limitations"):
        errors.append("output-review completion fixture does not state its limitations")
    try:
        display_path = str(record_path.relative_to(PROJECT_ROOT))
    except ValueError:
        display_path = str(record_path)
    return {
        "passed": not errors,
        "record": display_path,
        "assertion_count": len(assertions),
        "case_count": len(observed_cases),
        "synthetic_reviewer_fixture": record.get("synthetic_reviewer_fixture"),
        "human_review_performed": record.get("human_review_performed"),
        "review_gate_complete": record.get("review_gate_complete"),
        "screenshot": screenshot,
        "errors": errors,
        "limitations": record.get("limitations", []),
    }


def validate_folder_preview_browser_evidence(
    record_path: Path = FOLDER_PREVIEW_BROWSER_EVIDENCE,
) -> dict:
    errors = []
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}
    if record.get("verification_kind") != "replayable_folder_preview_browser_check":
        errors.append("unexpected folder preview browser verification kind")
    if record.get("passed") is not True:
        errors.append("folder preview browser replay did not pass")
    assertions = record.get("assertions", [])
    observed_names = {item.get("name") for item in assertions if isinstance(item, dict)}
    missing = sorted(FOLDER_PREVIEW_BROWSER_ASSERTIONS - observed_names)
    if missing:
        errors.append("folder preview browser replay is missing assertions: " + ", ".join(missing))
    if any(item.get("passed") is not True for item in assertions if isinstance(item, dict)):
        errors.append("one or more folder preview browser assertions failed")
    for field in ("console_errors", "failed_requests", "http_errors"):
        if record.get(field):
            errors.append(f"folder preview browser replay recorded {field}")
    observed = record.get("preview", {})
    if observed.get("buzz_write_performed") is not False:
        errors.append("folder preview browser evidence claims a Buzz write")
    if observed.get("room_registered") is not False:
        errors.append("folder preview browser evidence claims room registration")
    if record.get("room_ids_before_sha256") != record.get("room_ids_after_sha256"):
        errors.append("folder preview changed the room registry")
    try:
        fixture = (PROJECT_ROOT / str(record.get("folder_fixture", ""))).resolve()
        fixture.relative_to(PROJECT_ROOT)
        current = server_module.inspect_local_deal_room(str(fixture))["preview"]
    except (ValueError, OSError) as exc:
        errors.append(f"folder preview fixture is unavailable: {exc}")
        current = {}
    for field in (
        "preview_state", "document_count", "buzz_write_performed", "room_registered",
    ):
        if observed.get(field) != current.get(field):
            errors.append(f"folder preview browser {field} differs from current fixture")
    current_inventory_sha256 = hashlib.sha256(
        json.dumps(
            current.get("files", []), separators=(",", ":"),
        ).encode()
    ).hexdigest()
    if observed.get("source_inventory_sha256") != current_inventory_sha256:
        errors.append("folder preview browser source inventory differs from current fixture")
    if not re.fullmatch(r"[a-f0-9]{64}", str(observed.get("preview_sha256", ""))):
        errors.append("folder preview browser preview hash is invalid")
    if not re.fullmatch(r"local_[a-f0-9]{12}", str(observed.get("room_id", ""))):
        errors.append("folder preview browser room ID is invalid")
    if observed.get("warning_count") != len(current.get("warnings", [])):
        errors.append("folder preview browser warning count differs from current fixture")
    screenshot = record.get("screenshot", {})
    screenshot_path = (PROJECT_ROOT / str(screenshot.get("path", ""))).resolve()
    try:
        screenshot_path.relative_to(PROJECT_ROOT)
        screenshot_bytes = screenshot_path.read_bytes()
    except (ValueError, OSError) as exc:
        errors.append(f"folder preview screenshot is unavailable: {exc}")
    else:
        if screenshot.get("bytes") != len(screenshot_bytes):
            errors.append("folder preview screenshot byte count does not match")
        if screenshot.get("sha256") != hashlib.sha256(screenshot_bytes).hexdigest():
            errors.append("folder preview screenshot digest does not match")
    if not record.get("limitations"):
        errors.append("folder preview browser evidence does not state limitations")
    try:
        display_path = str(record_path.relative_to(PROJECT_ROOT))
    except ValueError:
        display_path = str(record_path)
    return {
        "passed": not errors,
        "record": display_path,
        "assertion_count": len(assertions),
        "preview_state": current.get("preview_state"),
        "document_count": current.get("document_count"),
        "buzz_write_performed": observed.get("buzz_write_performed"),
        "room_registered": observed.get("room_registered"),
        "screenshot": screenshot,
        "errors": errors,
        "limitations": record.get("limitations", []),
    }


def validate_buzz_polling_browser_evidence(
    record_path: Path = BUZZ_POLLING_BROWSER_EVIDENCE,
) -> dict:
    errors = []
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}
    if record.get("verification_kind") != "behavioral_buzz_polling_browser_check":
        errors.append("unexpected Buzz polling browser verification kind")
    if record.get("passed") is not True:
        errors.append("Buzz polling browser replay did not pass")
    assertions = record.get("assertions", [])
    names = {item.get("name") for item in assertions if isinstance(item, dict)}
    missing = sorted(BUZZ_POLLING_BROWSER_ASSERTIONS - names)
    if missing:
        errors.append("Buzz polling browser replay is missing assertions: " + ", ".join(missing))
    if any(item.get("passed") is not True for item in assertions if isinstance(item, dict)):
        errors.append("one or more Buzz polling browser assertions failed")
    for field in ("console_errors", "failed_requests", "http_errors"):
        if record.get(field):
            errors.append(f"Buzz polling browser replay recorded {field}")
    timing = record.get("timing", {})
    if timing.get("configured_poll_interval_ms") != 3500:
        errors.append("Buzz polling evidence uses an unexpected polling interval")
    if timing.get("injected_second_request_delay_ms", 0) < 3500:
        errors.append("Buzz polling delay did not cross one polling interval")
    if timing.get("request_count", 0) < 3:
        errors.append("Buzz polling queued refresh was not observed")
    if timing.get("max_concurrent_message_requests") != 1:
        errors.append("Buzz polling browser observed overlapping message requests")
    if timing.get("hidden_request_count", 0) < 3:
        errors.append("Buzz polling browser did not reach the hidden-tab control")
    policy = record.get("observed_server_message_read_policy", {})
    if policy.get("policy") != "coalesce_exact_inflight_no_stale_message_cache":
        errors.append("Buzz polling evidence lacks the current server coalescing policy")
    screenshot = record.get("screenshot", {})
    screenshot_path = (PROJECT_ROOT / str(screenshot.get("path", ""))).resolve()
    try:
        screenshot_path.relative_to(PROJECT_ROOT)
        screenshot_bytes = screenshot_path.read_bytes()
    except (ValueError, OSError) as exc:
        errors.append(f"Buzz polling screenshot is unavailable: {exc}")
    else:
        if screenshot.get("bytes") != len(screenshot_bytes):
            errors.append("Buzz polling screenshot byte count differs")
        if screenshot.get("sha256") != hashlib.sha256(screenshot_bytes).hexdigest():
            errors.append("Buzz polling screenshot hash differs")
    return {
        "passed": not errors,
        "record": str(record_path.relative_to(PROJECT_ROOT)) if record_path.is_relative_to(PROJECT_ROOT) else str(record_path),
        "assertion_count": len(assertions),
        "request_count": timing.get("request_count"),
        "max_concurrent_message_requests": timing.get("max_concurrent_message_requests"),
        "errors": errors,
        "limitations": record.get("limitations", []),
    }


def validate_pricing_poc_browser_evidence(
    record_path: Path = PRICING_POC_BROWSER_EVIDENCE,
) -> dict:
    errors = []
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}
    if record.get("verification_kind") != "replayable_pricing_poc_browser_check":
        errors.append("unexpected pricing POC browser verification kind")
    if record.get("passed") is not True:
        errors.append("pricing POC browser replay did not pass")
    assertions = record.get("assertions", [])
    observed_names = {
        item.get("name") for item in assertions if isinstance(item, dict)
    }
    missing = sorted(PRICING_POC_BROWSER_ASSERTIONS - observed_names)
    if missing:
        errors.append("pricing POC browser replay is missing assertions: " + ", ".join(missing))
    if any(item.get("passed") is not True for item in assertions if isinstance(item, dict)):
        errors.append("one or more pricing POC browser assertions failed")
    for field in ("console_errors", "failed_requests", "http_errors"):
        if record.get(field):
            errors.append(f"pricing POC browser replay recorded {field}")
    current = validate_saved_pricing_poc(
        PROJECT_ROOT,
        server_module.PRICING_POC_RECORD,
        event_resolver=resolve_pricing_poc_events,
    )
    observed = record.get("observed_state", {})
    expected = {
        "evidence_state": current.get("evidence_state"),
        "pricing_poc_passed": current.get("pricing_poc_passed"),
        "relay_restored": current.get("relay_restored"),
        "buyer_authority_configured": current.get("buyer_authority_configured"),
        "buyer_authority_verified": current.get("buyer_authority_verified"),
        "deal_count": current.get("deal_count"),
        "requirement_count": 10,
        "record_expected_at": str(server_module.PRICING_POC_RECORD.relative_to(PROJECT_ROOT)),
    }
    for field, value in expected.items():
        if observed.get(field) != value:
            errors.append(f"pricing POC browser {field} differs from current state")
    screenshot = record.get("screenshot", {})
    screenshot_path = (PROJECT_ROOT / str(screenshot.get("path", ""))).resolve()
    try:
        screenshot_path.relative_to(PROJECT_ROOT)
        screenshot_bytes = screenshot_path.read_bytes()
    except (ValueError, OSError) as exc:
        errors.append(f"pricing POC screenshot is unavailable: {exc}")
    else:
        if screenshot.get("bytes") != len(screenshot_bytes):
            errors.append("pricing POC screenshot byte count does not match")
        if screenshot.get("sha256") != hashlib.sha256(screenshot_bytes).hexdigest():
            errors.append("pricing POC screenshot digest does not match")
    if not record.get("limitations"):
        errors.append("pricing POC browser evidence does not state limitations")
    try:
        display_path = str(record_path.relative_to(PROJECT_ROOT))
    except ValueError:
        display_path = str(record_path)
    return {
        "passed": not errors,
        "record": display_path,
        "assertion_count": len(assertions),
        "evidence_state": current.get("evidence_state"),
        "pricing_poc_passed": current.get("pricing_poc_passed"),
        "buyer_authority_configured": current.get("buyer_authority_configured"),
        "buyer_authority_verified": current.get("buyer_authority_verified"),
        "deal_count": current.get("deal_count"),
        "screenshot": screenshot,
        "errors": errors,
        "limitations": record.get("limitations", []),
    }


def validate_pricing_poc_completion_fixture_evidence(
    record_path: Path = PRICING_POC_COMPLETION_FIXTURE_EVIDENCE,
) -> dict:
    errors = []
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}
    if record.get("verification_kind") != "synthetic_pricing_poc_completion_browser_fixture":
        errors.append("unexpected pricing POC completion fixture kind")
    if record.get("passed") is not True:
        errors.append("pricing POC completion fixture did not pass")
    for field, expected in (
        ("synthetic_buyer_fixture", True),
        ("buyer_evidence_recorded", False),
        ("pricing_poc_passed", False),
    ):
        if record.get(field) is not expected:
            errors.append(f"pricing POC completion fixture has unsafe {field} state")
    assertions = record.get("assertions", [])
    observed_names = {item.get("name") for item in assertions if isinstance(item, dict)}
    missing = sorted(PRICING_POC_COMPLETION_FIXTURE_ASSERTIONS - observed_names)
    if missing:
        errors.append("pricing POC completion fixture is missing assertions: " + ", ".join(missing))
    if any(item.get("passed") is not True for item in assertions if isinstance(item, dict)):
        errors.append("one or more pricing POC completion assertions failed")
    for field in ("console_errors", "failed_requests", "http_errors"):
        if record.get(field):
            errors.append(f"pricing POC completion fixture recorded {field}")
    unsigned = record.get("fixture_unsigned_record", {})
    if "buyer_attestation" in unsigned or "buyer_authorization" in unsigned:
        errors.append("pricing POC completion fixture is not unsigned")
    if unsigned.get("poc_id") != "fixture-pricing-poc-001":
        errors.append("pricing POC completion fixture POC ID changed")
    deals = unsigned.get("deals", [])
    if len(deals) != 2 or {item.get("experiment_role") for item in deals} != {
        "setup_and_correction", "transfer_without_case_specific_change",
    }:
        errors.append("pricing POC completion fixture deal roles changed")
    encoded = (json.dumps(unsigned, indent=2) + "\n").encode()
    if record.get("fixture_unsigned_record_sha256") != hashlib.sha256(encoded).hexdigest():
        errors.append("pricing POC completion downloaded record hash does not match")
    current = validate_saved_pricing_poc(
        PROJECT_ROOT,
        server_module.PRICING_POC_RECORD,
        event_resolver=resolve_pricing_poc_events,
    )
    if current.get("evidence_state") != "not_recorded" or current.get("pricing_poc_passed") is not False:
        errors.append("pricing POC completion fixture no longer matches the current empty state")
    screenshot = record.get("screenshot", {})
    screenshot_path = (PROJECT_ROOT / str(screenshot.get("path", ""))).resolve()
    try:
        screenshot_path.relative_to(PROJECT_ROOT)
        screenshot_bytes = screenshot_path.read_bytes()
    except (ValueError, OSError) as exc:
        errors.append(f"pricing POC completion screenshot is unavailable: {exc}")
    else:
        if screenshot.get("bytes") != len(screenshot_bytes):
            errors.append("pricing POC completion screenshot byte count does not match")
        if screenshot.get("sha256") != hashlib.sha256(screenshot_bytes).hexdigest():
            errors.append("pricing POC completion screenshot digest does not match")
    if not record.get("limitations"):
        errors.append("pricing POC completion fixture does not state limitations")
    try:
        display_path = str(record_path.relative_to(PROJECT_ROOT))
    except ValueError:
        display_path = str(record_path)
    return {
        "passed": not errors,
        "record": display_path,
        "assertion_count": len(assertions),
        "synthetic_buyer_fixture": record.get("synthetic_buyer_fixture"),
        "buyer_evidence_recorded": record.get("buyer_evidence_recorded"),
        "pricing_poc_passed": record.get("pricing_poc_passed"),
        "screenshot": screenshot,
        "errors": errors,
        "limitations": record.get("limitations", []),
    }


def validate_human_review_packet(record_path: Path = HUMAN_REVIEW_PACKET) -> dict:
    errors = []
    try:
        saved = json.loads(record_path.read_text(encoding="utf-8"))
        expected = build_review_packet(
            PROJECT_ROOT,
            PROJECT_ROOT / "evidence" / "bonsai-public-deal-battletest-responses.json",
        )
        roster = load_output_reviewer_roster(PROJECT_ROOT)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {"passed": False, "record": str(record_path), "errors": [str(exc)]}
    if saved != expected:
        errors.append("saved review packet does not match the current registry, rubric, and responses")
    if saved.get("blinded_to_model") is not True or saved.get("model_identity_included") is not False:
        errors.append("saved review packet is not model blind")
    return {
        "passed": not errors,
        "record": str(record_path.relative_to(PROJECT_ROOT)),
        "packet_sha256": packet_sha256(saved),
        "case_count": len(saved.get("cases", [])),
        "blinded_to_model": saved.get("blinded_to_model"),
        "review_submissions_received": 0,
        "active_output_reviewer_count": sum(
            item.get("active") is True
            and item.get("role") == "qualified_deal_output_reviewer"
            for item in roster.get("reviewers", [])
        ),
        "active_output_principal_count": sum(
            item.get("active") is True
            and item.get("role") == "principal_output_reviewer"
            for item in roster.get("reviewers", [])
        ),
        "reviewer_roster_ready": sum(
            item.get("active") is True
            and item.get("role") == "qualified_deal_output_reviewer"
            for item in roster.get("reviewers", [])
        ) >= 2,
        "errors": errors,
    }


def validate_candidate_source_review_boundary() -> dict:
    errors = []
    try:
        saved_packet = json.loads(CANDIDATE_SOURCE_REVIEW_PACKET.read_text(encoding="utf-8"))
        saved_validation = json.loads(
            CANDIDATE_SOURCE_REVIEW_VALIDATION.read_text(encoding="utf-8")
        )
        expected_packet = build_candidate_source_review_packet(PROJECT_ROOT)
        submissions_dir = PROJECT_ROOT / "benchmarks" / "first_pass" / "source_reviews"
        submissions = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(submissions_dir.glob("*.json"))
        ] if submissions_dir.exists() else []
        adjudication_path = (
            PROJECT_ROOT / "benchmarks" / "first_pass" / "source_review_adjudication.json"
        )
        adjudication = (
            json.loads(adjudication_path.read_text(encoding="utf-8"))
            if adjudication_path.exists() else None
        )
        expected_validation = evaluate_source_review_state(
            PROJECT_ROOT, expected_packet, submissions, adjudication,
        )
        registration_ledger = json.loads(
            (
                PROJECT_ROOT / "benchmarks" / "first_pass"
                / "candidate_case_registrations.v1.json"
            ).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {"passed": False, "errors": [str(exc)]}
    if saved_packet != expected_packet:
        errors.append("saved candidate source review packet differs from current source drafts")
    expected_hash = candidate_packet_sha256(expected_packet)
    if saved_validation.get("packet_sha256") != expected_hash:
        errors.append("candidate source validation is not bound to the current packet")
    if saved_validation != expected_validation:
        errors.append("saved candidate source validation differs from current review files")
    return {
        "passed": not errors,
        "packet_record": str(CANDIDATE_SOURCE_REVIEW_PACKET.relative_to(PROJECT_ROOT)),
        "validation_record": str(CANDIDATE_SOURCE_REVIEW_VALIDATION.relative_to(PROJECT_ROOT)),
        "packet_sha256": expected_hash,
        "candidate_deal_count": expected_packet["candidate_deal_count"],
        "draft_count": expected_packet["draft_count"],
        "review_submissions_received": expected_validation["submission_count"],
        "eligible_for_case_authoring_count": expected_validation[
            "eligible_for_case_authoring_count"
        ],
        "benchmark_cases_registered": len(registration_ledger.get("registrations", [])),
        "promotion_ready": expected_validation["promotion_ready"],
        "errors": errors,
    }


def validate_trace_anchor_evidence(
    record_path: Path = TRACE_ANCHOR_EVIDENCE,
    trace_store: Path = TRACE_STORE,
) -> dict:
    try:
        receipt = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "passed": False,
            "record": str(record_path),
            "signed_anchor_verified": False,
            "current_head_anchored": False,
            "externally_anchored": False,
            "errors": [str(exc)],
        }
    result = validate_trace_anchor_receipt(receipt, trace_store=trace_store)
    try:
        display_path = str(record_path.relative_to(PROJECT_ROOT))
    except ValueError:
        display_path = str(record_path)
    return {"record": display_path, **result}


def validate_network_observation_evidence(
    record_path: Path = NETWORK_OBSERVATION_EVIDENCE,
) -> dict:
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "passed": False,
            "record": str(record_path),
            "zero_egress_proved": False,
            "air_gap_proved": False,
            "errors": [str(exc)],
        }
    result = validate_network_observation(record)
    try:
        mode = record_path.stat().st_mode & 0o777
    except OSError as exc:
        result["errors"].append(str(exc))
        result["passed"] = False
    else:
        if mode != 0o600:
            result["errors"].append(
                f"network-observation evidence mode is {oct(mode)}, expected 0o600"
            )
            result["passed"] = False
    try:
        display_path = str(record_path.relative_to(PROJECT_ROOT))
    except ValueError:
        display_path = str(record_path)
    return {"record": display_path, **result}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", choices=["baseline", "local", "cloud"], default="baseline")
    parser.add_argument("--allow-cloud-data", action="store_true")
    parser.add_argument("--cold-restart-candidate", action="store_true")
    parser.add_argument("--output", help="Write the verification report as JSON")
    args = parser.parse_args()

    if args.allow_cloud_data and args.runtime != "cloud":
        parser.error("--allow-cloud-data requires --runtime cloud")
    if args.cold_restart_candidate and args.runtime != "local":
        parser.error("--cold-restart-candidate requires --runtime local")

    tests_ok, tests_run, tests_skipped, discovered_tests = run_tests()
    claims = scan_claims()
    frontend = check_frontend_contract()
    customer_demo_scope = validate_customer_demo_scope(PROJECT_ROOT)
    content_graph = validate_content_graph(PROJECT_ROOT)
    customer_demo_browser_evidence = validate_customer_demo_browser_record(
        PROJECT_ROOT, CUSTOMER_DEMO_BROWSER_EVIDENCE,
    )
    cold_restart = (
        {
            "passed": False,
            "measurement_state": "pending_enclosing_cold_restart_record_commit",
            "not_evaluated": True,
            "errors": [],
            "meaning": (
                "This is the post-restart candidate artifact. The enclosing recorder "
                "must bind and commit it before cold-restart evidence can pass."
            ),
        }
        if args.cold_restart_candidate else validate_cold_restart_evidence()
    )
    current_local_product_evidence = (
        {
            "passed": False,
            "measurement_state": "superseded_current_artifact_not_used_for_candidate",
            "not_evaluated": True,
            "errors": [],
            "meaning": "The candidate's live benchmark below is the run being evaluated.",
        }
        if args.cold_restart_candidate else validate_current_local_product_evidence()
    )
    first_pass_evidence = validate_first_pass_evidence()
    screen_bound_first_pass_evidence = validate_screen_bound_first_pass_evidence()
    operator_review_restart = validate_operator_review_restart_evidence()
    first_pass_development = validate_first_pass_development_evidence()
    browser_evidence = validate_browser_evidence()
    real_deal_browser_evidence = validate_real_deal_browser_evidence()
    provenance_bound_publication = validate_provenance_bound_publication()
    titan_debt_browser_evidence = validate_titan_debt_browser_evidence()
    xlsx_workbook_chat_evidence = validate_xlsx_workbook_chat_evidence()
    local_deployment_evidence = validate_local_deployment_evidence()
    live_inference_concurrency_evidence = validate_live_inference_concurrency_evidence()
    operator_preflight_evidence = validate_operator_preflight_evidence()
    accessibility_browser_evidence = validate_accessibility_browser_evidence()
    cross_browser_evidence = validate_cross_browser_evidence()
    source_review_browser_evidence = validate_source_review_browser_evidence()
    case_authoring_browser_evidence = validate_case_authoring_browser_evidence()
    output_review_browser_evidence = validate_output_review_browser_evidence()
    output_review_completion_fixture_evidence = (
        validate_output_review_completion_fixture_evidence()
    )
    pricing_poc_browser_evidence = validate_pricing_poc_browser_evidence()
    pricing_poc_completion_fixture_evidence = (
        validate_pricing_poc_completion_fixture_evidence()
    )
    folder_preview_browser_evidence = validate_folder_preview_browser_evidence()
    buzz_polling_browser_evidence = validate_buzz_polling_browser_evidence()
    pricing_poc_evidence = validate_saved_pricing_poc(
        PROJECT_ROOT,
        server_module.PRICING_POC_RECORD,
        event_resolver=resolve_pricing_poc_events,
    )
    trace_anchor_evidence = validate_trace_anchor_evidence()
    network_observation_evidence = validate_network_observation_evidence()
    ocr_accuracy_evidence = validate_saved_ocr_accuracy(
        PROJECT_ROOT, OCR_ACCURACY_EVIDENCE,
    )
    oracle_context_evidence = validate_saved_oracle_context(
        PROJECT_ROOT, ORACLE_CONTEXT_EVIDENCE,
    )
    sealed_test_control = sealed_test_preflight(PROJECT_ROOT)
    first_pass_benchmark_contract = validate_contract(PROJECT_ROOT)
    first_pass_development_evaluation = evaluate_development_responses(
        PROJECT_ROOT,
        PROJECT_ROOT / "evidence" / "bonsai-public-deal-battletest-responses.json",
    )
    human_review_packet = validate_human_review_packet()
    candidate_source_review = validate_candidate_source_review_boundary()
    xlsx_display_benchmark = evaluate_xlsx_display_benchmark(
        PROJECT_ROOT / "benchmarks" / "xlsx_display_fidelity.v1.json"
    )
    missing_required_tests = {
        name: test_id for name, test_id in REQUIRED_REALITY_TESTS.items()
        if test_id not in discovered_tests
    }
    required_tests_ok = not missing_required_tests
    providers = ProviderRegistry()
    benchmark = run_benchmark(
        str(PROJECT_ROOT / "benchmarks" / "deal_room_reliability.json"),
        DEAL_ROOM_CATALOG,
        runtime=args.runtime,
        providers=providers,
        allow_cloud_context=args.allow_cloud_data,
    )
    benchmark_ok = benchmark.pass_rate == 1.0
    local_evidence = benchmark.runtime_evidence if args.runtime == "local" else {}
    local_deployment_complete = bool(
        re.fullmatch(r"[0-9a-fA-F]{64}", str(local_evidence.get("artifact_sha256", "")))
        and all(local_evidence.get(field) for field in (
            "runtime_name", "runtime_version", "hardware"
        ))
        and local_evidence.get("protocol") == "lmstudio_native_chat"
    )
    live_bonsai_passed = bool(
        args.runtime == "local" and providers.local.configured and benchmark_ok
        and local_deployment_complete
        and all(case.provider_id == "local_bonsai" and case.model_name for case in benchmark.cases)
    )
    runtime_selection_ok = (
        benchmark_ok
        if args.runtime == "baseline"
        else live_bonsai_passed
        if args.runtime == "local"
        else bool(
            args.runtime == "cloud"
            and providers.cloud.configured
            and benchmark_ok
            and all(case.provider_id == "cloud_ai" and case.model_name for case in benchmark.cases)
        )
    )
    cold_identity_matches_current = bool(
        args.runtime == "local"
        and benchmark.dataset_sha256 == json.loads(COLD_RESTART_EVIDENCE.read_text(encoding="utf-8")).get(
            "benchmark_dataset_sha256"
        )
        and local_evidence.get("model") == "27b@q1_0"
    ) if cold_restart["passed"] else False

    report = {
        "verification_kind": "evidence_based_product_check",
        "verification_phase": (
            "post_restart_candidate_before_record_commit"
            if args.cold_restart_candidate else "complete_verification"
        ),
        "runtime": args.runtime,
        "engineering_source_manifest": engineering_source_manifest(PROJECT_ROOT),
        "component_tests": {
            "passed": tests_ok and required_tests_ok,
            "tests_run": tests_run,
            "tests_skipped": tests_skipped,
            "required_reality_tests_present": required_tests_ok,
            "missing_required_reality_tests": missing_required_tests,
        },
        "unsupported_claim_scan": {
            "passed": not claims,
            "violations": claims,
        },
        "frontend_contract": frontend,
        "customer_demo_scope_contract": customer_demo_scope,
        "deal_room_content_graph": content_graph,
        "customer_demo_browser_surface_evidence": customer_demo_browser_evidence,
        "cold_restart_evidence": cold_restart,
        "current_local_engineering_evidence": current_local_product_evidence,
        "first_pass_product_evidence": first_pass_evidence,
        "screen_bound_first_pass_product_evidence": screen_bound_first_pass_evidence,
        "operator_review_restart_evidence": operator_review_restart,
        "first_pass_development_evidence": first_pass_development,
        "browser_surface_evidence": browser_evidence,
        "real_deal_browser_surface_evidence": real_deal_browser_evidence,
        "provenance_bound_publication_evidence": provenance_bound_publication,
        "titan_debt_browser_surface_evidence": titan_debt_browser_evidence,
        "xlsx_workbook_chat_evidence": xlsx_workbook_chat_evidence,
        "xlsx_display_fidelity_benchmark": xlsx_display_benchmark,
        "local_deployment_evidence": local_deployment_evidence,
        "live_inference_concurrency_evidence": live_inference_concurrency_evidence,
        "operator_preflight_evidence": operator_preflight_evidence,
        "accessibility_browser_surface_evidence": accessibility_browser_evidence,
        "cross_browser_surface_evidence": cross_browser_evidence,
        "source_review_browser_surface_evidence": source_review_browser_evidence,
        "case_authoring_browser_surface_evidence": case_authoring_browser_evidence,
        "output_review_browser_surface_evidence": output_review_browser_evidence,
        "output_review_completion_fixture_evidence": (
            output_review_completion_fixture_evidence
        ),
        "pricing_poc_browser_surface_evidence": pricing_poc_browser_evidence,
        "pricing_poc_completion_fixture_evidence": pricing_poc_completion_fixture_evidence,
        "folder_preview_browser_evidence": folder_preview_browser_evidence,
        "buzz_polling_browser_evidence": buzz_polling_browser_evidence,
        "pricing_poc_evidence": pricing_poc_evidence,
        "trace_anchor_evidence": trace_anchor_evidence,
        "network_observation_evidence": network_observation_evidence,
        "ocr_accuracy_evidence": ocr_accuracy_evidence,
        "oracle_context_diagnostic_evidence": oracle_context_evidence,
        "sealed_test_control": sealed_test_control,
        "first_pass_benchmark_contract": first_pass_benchmark_contract,
        "first_pass_development_evaluation": first_pass_development_evaluation,
        "human_review_packet": human_review_packet,
        "candidate_source_review_boundary": candidate_source_review,
        "benchmark": benchmark.to_dict(),
        "provider_status": [status.__dict__ for status in providers.statuses()],
        "external_gates": {
            "rendered_browser_qa": (
                "replayable Chromium, Firefox, WebKit, and automated accessibility smoke "
                "artifacts verified; Safari, Chrome, Edge, assistive-technology review, "
                "WCAG conformance, and clean physical-machine reproduction remain unverified"
            ),
            "certified_air_gap": "not implemented",
            "hardened_multi_tenant_isolation": "not implemented",
            "measured_bonsai_hardware_performance": (
                "per-case latency measured; VRAM and energy telemetry not implemented"
            ),
            "local_model_deployment_identity": (
                "weights, vision projection, llama.cpp version, effective fitted context, "
                "and sanitized hardware identity measured on the current host"
                if local_deployment_evidence["passed"] else
                "current local deployment identity failed verification"
            ),
        },
        "milestones": {
            "M0_truthful_baseline": {
                "passed": bool(tests_ok and required_tests_ok and not claims and frontend["passed"]),
                "evidence": ["component_tests", "unsupported_claim_scan", "frontend_contract"],
            },
            "M1_private_folder_baseline": {
                "passed": bool(
                    tests_ok and tests_skipped == 0 and required_tests_ok
                    and benchmark_ok and xlsx_display_benchmark["passed"]
                ),
                "evidence": [
                    "private_folder_http", "source_mutation",
                    "benchmark_negative_control", "benchmark",
                    "preregistered XLSX raw/display/formula-state benchmark",
                    "wrong expected XLSX display negative control",
                    "hash-bound no-write folder preview in Chromium",
                ],
            },
            "M1a_public_ocr_accuracy_measurement": {
                "passed": ocr_accuracy_evidence["passed"],
                "engineering_measurement_passed": ocr_accuracy_evidence.get(
                    "engineering_measurement_passed", False
                ),
                "human_approved_ocr_release_gate_passed": ocr_accuracy_evidence.get(
                    "human_approved_ocr_release_gate_passed", False
                ),
                "evidence": [
                    "three fixed public M&A pages rendered as clean 200 DPI image-only PDFs",
                    "Apple Vision rerenders each image-only PDF at the disclosed 300 DPI recognition scale",
                    "word error, character error, and critical-phrase recall recomputed from raw Apple Vision output",
                    "saved scores, source bytes, derivatives, benchmark text, and the disclosed ground-truth correction are hash bound",
                    (
                        "the current development regression passed every-page and 100 percent critical-phrase thresholds"
                        if ocr_accuracy_evidence.get("engineering_measurement_passed") is True
                        else "the current development regression failed its engineering thresholds"
                    ),
                    "the same pages were used to select the DPI fix, so the pass is not an independent test",
                    "natural customer scans, tables, layout, and independent domain labels remain open",
                ],
            },
            "M2a_live_bonsai_benchmark": {
                "passed": live_bonsai_passed,
                "evidence": ["configured local endpoint", "native reasoning-off protocol",
                             "per-case provider/model IDs", "local benchmark"],
            },
            "M2_reproducible_bonsai_runtime": {
                "passed": bool(live_bonsai_passed and cold_restart["passed"]
                               and cold_identity_matches_current),
                "evidence": ["M2a live benchmark", "hash-bound distinct-process cold-restart run"],
            },
            "M6a_replayable_browser_surface": {
                "passed": browser_evidence["passed"],
                "evidence": [
                    "frontend static contract",
                    "trace-bound Playwright Core replay",
                    "canonical citation navigation and exact-anchor preview",
                    "screenshot hash and zero browser/HTTP errors",
                ],
            },
            "M6b_real_public_deal_surface": {
                "passed": real_deal_browser_evidence["passed"],
                "evidence": [
                    "one parser-verified SEC DEFM14A source",
                    "source-bounded Bonsai 27B answer in a signed Buzz event",
                    "canonical discussion URL and exact-anchor citation navigation",
                    "four requested deal-term parts passed structural publication guards; accuracy release remains false",
                ],
            },
            "M6i_titan_debt_chat_surface": {
                "passed": titan_debt_browser_evidence["passed"],
                "accuracy_release_passed": titan_debt_browser_evidence.get(
                    "accuracy_release_passed", False
                ),
                "evidence": [
                    "one exact Sources of Funds table retrieved from the Titan folder",
                    "all four disclosed debt instruments and amounts passed the structural guard",
                    "the accepted answer and earlier rejection remain signed and trace-bound in Buzz",
                    "restart restoration, canonical URL, and exact citation navigation passed in Chromium",
                    "domain accuracy review and benchmark breadth remain open",
                ],
            },
            "M6e_live_xlsx_chat_surface": {
                "passed": xlsx_workbook_chat_evidence["passed"],
                "accuracy_release_passed": xlsx_workbook_chat_evidence.get(
                    "accuracy_release_passed", False
                ),
                "evidence": [
                    "one source-hash-bound operator-selected workbook",
                    "raw value and bounded percent display format preserved",
                    "first-attempt Bonsai answer passed the structural guard",
                    "signed Buzz event and exact sheet citation verified in Chromium",
                    "temporary source, formula recalculation, domain review, and benchmark registration remain open",
                ],
            },
            "M6f_same_host_operator_preflight": {
                "passed": operator_preflight_evidence["passed"],
                "clean_machine_reproduced": False,
                "evidence": [
                    "required Python, Docker, Compose, Buzz tools, relay, and key permission checks",
                    "LM Studio catalog presence distinguished from an exact loaded Bonsai instance",
                    "native reasoning-off capability observed",
                    "benchmark deployment metadata remains a separate optional startup gate",
                    "same-host check only; clean physical machine reproduction remains open",
                ],
            },
            "M6g_measured_local_deployment": {
                "passed": local_deployment_evidence["passed"],
                "clean_machine_reproduced": False,
                "evidence": [
                    "SHA-256 and byte size verified against the current weights and vision projection files",
                    "exact loaded model identifier and Q1_0 quantization recorded",
                    "sanitized llama.cpp 2.28.2 process configuration records a 16,384-token fitted context",
                    "the active Bonsai process bind host is 127.0.0.1 and its port matches the measured record",
                    "machine model, chip, and memory recorded without a hardware serial number",
                    "LM Studio catalog-size discrepancy preserved instead of normalized away",
                    "quality, energy, VRAM, zero egress, and clean physical-machine reproduction remain open",
                ],
            },
            "M6h_live_inference_responsiveness": {
                "passed": live_inference_concurrency_evidence["passed"],
                "evidence": [
                    "real Bonsai request completed through the live signed Buzz product path",
                    "status probes completed while inference was still in flight",
                    "question and answer events restored with verified signatures",
                    "trace binds provider, model, events, and accepted publication state",
                    "prototype responsiveness threshold is not a production SLO or load test",
                ],
            },
            "M6j_signed_trace_anchor": {
                "passed": trace_anchor_evidence["passed"],
                "current_head_anchored": trace_anchor_evidence.get(
                    "current_head_anchored", False
                ),
                "externally_anchored": trace_anchor_evidence.get(
                    "externally_anchored", False
                ),
                "evidence": [
                    "one exact local trace-ledger prefix is bound to a raw NIP-01/BIP-340 Buzz event",
                    "event identity, signer, channel, payload, and ledger prefix are independently checked",
                    "current_head_anchored reports separately whether later trace appends have advanced the ledger",
                    "the relay is same-host loopback, so this is not an external trust-domain or immutable-ledger claim",
                ],
            },
            "M6k_process_socket_observation": {
                "passed": network_observation_evidence["passed"],
                "zero_egress_proved": False,
                "air_gap_proved": False,
                "evidence": [
                    "raw lsof fields were reparsed across the exact Prism, Bionic, and Bonsai processes",
                    "one bounded reasoning-off request returned from the exact Bonsai model instance",
                    "wildcard, invalid, and non-loopback endpoints fail the observation",
                    "process metadata redacts the runtime API key and the artifact is mode 0600",
                    "sampling can miss short-lived sockets and excludes packets, Docker guests, and unrelated processes",
                    "this milestone is not zero-egress, air-gap, firewall, DLP, or production-isolation evidence",
                ],
            },
            "M6c_accessibility_smoke": {
                "passed": accessibility_browser_evidence["passed"],
                "evidence": [
                    "semantic tab and panel state",
                    "keyboard tab and exact-citation navigation",
                    "visible focus and 24-pixel target checks",
                    "dialog focus restoration and reduced-motion behavior",
                    "desktop and mobile-width Chromium replay",
                    "automated smoke only; WCAG conformance remains unverified",
                ],
            },
            "M6d_cross_browser_surface": {
                "passed": cross_browser_evidence["passed"],
                "evidence": [
                    "the same signed Zendesk answer in Firefox and WebKit",
                    "four human part labels and four citation controls",
                    "keyboard tab and exact-citation navigation",
                    "source focus and mobile-width checks",
                    "versioned screenshots and zero browser or HTTP errors",
                    "Safari, Chrome, and Edge remain unverified",
                ],
            },
            "M6l_customer_demo_scope": {
                "passed": customer_demo_scope["passed"],
                "evidence": [
                    "the accepted scope is present in the PRD, RFC, surface contract, verification gates, and status page",
                    "the ideal page structure defines the main and secondary views",
                    "the shadcn decision preserves the current plain HTML, CSS, and JavaScript client",
                    "accuracy certification and commercial proof are outside the current goal",
                ],
            },
            "M6m_customer_demo_surface": {
                "passed": customer_demo_browser_evidence["passed"],
                "evidence": [
                    "the current demo asset version was loaded",
                    "Overview, Sources, Activity, and Evaluation are the primary room views",
                    "the decision status has priority and a source action opens the exact passage",
                    "the Activity view keeps the canonical room URL",
                    "390, 768, and 1440 pixel viewport checks have no horizontal overflow",
                    "desktop and mobile screenshots are content hashed",
                    "the browser recorded no console, request, or HTTP errors",
                ],
            },
            "M6n_job_content_graph": {
                "passed": content_graph["passed"],
                "evidence": [
                    "the root job is explicit",
                    "every visible segment has a user question, placement, and defense",
                    "every governed phrase has an owner and defense",
                    "all segments are connected to the root job",
                    "retired strategy copy is absent from the product source",
                ],
            },
            "M6_evangelism_release": {
                "passed": False,
                "evidence": [
                    "M6a replayable browser surface",
                    "clean physical-machine operator reproduction remains open",
                    "Safari, Chrome, Edge, assistive-technology, and WCAG conformance review remain open",
                ],
            },
            "M4a_first_pass_product_path": {
                "passed": bool(
                    first_pass_evidence["passed"]
                    and screen_bound_first_pass_evidence["passed"]
                ),
                "evidence": [
                    "Buzz-restored draft event",
                    "matching persisted evaluation trace",
                    "content-hashed source folder",
                    "screen-matched retrieval slots and stable before/after source snapshot",
                    "rejected Bonsai prose remains separate from the signed evidence fallback",
                    "human review and accuracy release remain open",
                ],
            },
            "M4a_operator_review_durability": {
                "passed": operator_review_restart["passed"],
                "evidence": [
                    "local operator review in a signed Buzz message",
                    "signed reviewed canvas",
                    "matching persisted trace metadata",
                    "review event predates the restoring Prism process",
                    "domain review and accuracy release remain false",
                ],
            },
            "M4b_public_development_breadth": {
                "passed": first_pass_development["passed"],
                "evidence": [
                    "three isolated public deal folders",
                    "three trace-linked Buzz artifacts",
                    "zero source-folder writes",
                    "all Bonsai attempts rejected; fallbacks do not count as model passes",
                ],
            },
            "M4c_accuracy_release_contract": {
                "passed": first_pass_benchmark_contract["release_ready"],
                "structural_passed": first_pass_benchmark_contract["structural_passed"],
                "evidence": [
                    "schema valid development registry",
                    "source snapshot and citation hash binding",
                    "deal split isolation",
                    "missing inventory and approvals reported as release failures",
                ],
            },
            "M4d_development_accuracy": {
                "passed": first_pass_development_evaluation["accuracy_release_passed"],
                "evidence": [
                    "five hash-bound saved responses",
                    "five independently verified owner-question and agent-answer Buzz event pairs",
                    "deterministic citation, number, absence, and source-write checks",
                    "semantic and usefulness dimensions remain unverified",
                    "no aggregate score can promote an unverified case",
                ],
            },
            "M4i_failure_localization_diagnostic": {
                "passed": oracle_context_evidence["passed"],
                "engineering_diagnostic_completed": oracle_context_evidence.get(
                    "engineering_diagnostic_completed", False
                ),
                "semantic_accuracy_state": "unverified",
                "accuracy_release_passed": False,
                "evidence": [
                    "all five registered cases completed; four use their registered passages and the absence case also uses a complete folder audit",
                    "the Citrix audit verified two files and scanned 2,401 parsed nodes against three disclosed direct-disclosure patterns",
                    "raw prompts, passages, responses, model metadata, source identities, pattern results, and deterministic probes are hash bound and recomputed",
                    "Citrix financing regressed by omitting its citation under oracle context",
                    "Citrix absence supplied both required absence phrases but omitted its citation, so the deterministic failure persisted",
                    "the CMA deterministic failure persisted under oracle context",
                    "the absence patterns were written after development inspection and do not prove semantic absence",
                    "development labels remain unapproved, so semantic localization and accuracy remain unverified",
                ],
            },
            "M4e_blinded_human_review": {
                "passed": False,
                "surface_ready": output_review_browser_evidence["passed"],
                "packet_ready": human_review_packet["passed"],
                "reviewer_roster_ready": human_review_packet.get("reviewer_roster_ready", False),
                "evidence": [
                    "model identity stripped from review packet",
                    "hash-bound Chromium replay of the blinded output review workspace",
                    "a synthetic reviewer fixture proves complete unsigned browser export without claiming human review",
                    "packet, rubric, registry, and responses are hash bound",
                    "domain-owner roster blocks self-asserted reviewer qualification",
                    "two distinct rostered output reviewers and a rostered principal are required",
                    "zero rostered reviewers or review submissions have been received",
                ],
            },
            "M4f_candidate_source_case_review": {
                "passed": bool(candidate_source_review["passed"] and source_review_browser_evidence["passed"]),
                "promotion_ready": False,
                "evidence": [
                    "319 model-blind, hash-bound source review drafts across 29 SEC deals",
                    "every release task family has enough candidate plus registered capacity to meet its target",
                    "58 drafts require both the deal proxy and pre-transaction financial filing",
                    "retrieval ranks and model identity omitted from the reviewer packet",
                    "domain-owner roster blocks self-asserted reviewer qualification",
                    "two distinct rostered reviewers or rostered principal adjudication required",
                    "zero rostered reviewers, submissions, eligible drafts, or registered cases claimed",
                    "hash-bound Chromium replay of all four promotion gates",
                ],
            },
            "M4g_case_authoring_boundary": {
                "passed": case_authoring_browser_evidence["passed"],
                "promotion_ready": False,
                "evidence": [
                    "source review controls which drafts enter case authoring",
                    "reviewed questions, claims, citations, and source hashes are locked",
                    "the browser exports an unsigned owner record",
                    "approval recording and case registration remain separate commits",
                ],
            },
            "M4h_sealed_test_custody": {
                "passed": bool(
                    first_pass_benchmark_contract.get("structural_passed") is True
                    and
                    sealed_test_control.get("ready_to_open") is False
                    and sealed_test_control.get("secret_loader_invoked") is False
                ),
                "ready_to_open": sealed_test_control.get("ready_to_open", False),
                "evidence": [
                    "public-only manifest and hash binding are structurally verified",
                    "current unauthorized state returns before external secret loading",
                    "one-time contact, leakage, and hash mismatch controls are required tests",
                    "zero sealed cases, approvals, calibration, or accuracy claimed",
                ],
            },
            "M5_pricing_poc_boundary": {
                "passed": pricing_poc_browser_evidence["passed"],
                "buyer_authority_configured": pricing_poc_evidence.get(
                    "buyer_authority_configured", False,
                ),
                "buyer_evidence_recorded": pricing_poc_evidence.get("evidence_state") == "verified",
                "pricing_poc_passed": pricing_poc_evidence.get("pricing_poc_passed", False),
                "evidence": [
                    "ten explicit product-value gates",
                    "a distinct configured commercial authority must approve the buyer key",
                    "authority and buyer payloads must both restore exactly from the authority channel",
                    "two private historical deals with setup and unchanged transfer roles required",
                    "public SEC demonstrations and synthetic fixtures count as zero buyer evidence",
                    "hash-bound Chromium replay of the honest empty state",
                    "synthetic completion fixture proves unsigned record export without claiming buyer evidence",
                ],
            },
        },
        "selected_runtime_verified": bool(
            tests_ok and tests_skipped == 0 and required_tests_ok and not claims
            and local_verification_cold_gate(
                args.runtime, args.cold_restart_candidate, cold_restart,
            )
            and frontend["passed"] and customer_demo_scope["passed"]
            and customer_demo_browser_evidence["passed"]
            and runtime_selection_ok and source_review_browser_evidence["passed"]
            and case_authoring_browser_evidence["passed"] and operator_review_restart["passed"]
            and screen_bound_first_pass_evidence["passed"]
            and output_review_browser_evidence["passed"]
            and output_review_completion_fixture_evidence["passed"]
            and pricing_poc_browser_evidence["passed"]
            and pricing_poc_completion_fixture_evidence["passed"]
            and folder_preview_browser_evidence["passed"]
            and buzz_polling_browser_evidence["passed"]
            and accessibility_browser_evidence["passed"]
            and cross_browser_evidence["passed"]
            and provenance_bound_publication["passed"]
            and titan_debt_browser_evidence["passed"]
            and xlsx_workbook_chat_evidence["passed"]
            and xlsx_display_benchmark["passed"]
            and local_deployment_evidence["passed"]
            and live_inference_concurrency_evidence["passed"]
            and operator_preflight_evidence["passed"]
            and runtime_trace_anchor_gate(args.runtime, trace_anchor_evidence)
            and runtime_network_observation_gate(args.runtime, network_observation_evidence)
            and ocr_accuracy_evidence["passed"]
            and oracle_context_evidence["passed"]
        ),
        "target_architecture_complete": False,
    }

    # The current goal decision covers the customer demo contract. Benchmark,
    # pricing, and production hardening records stay in this broader report,
    # but they do not control the current goal decision.
    report["goal_completion"] = evaluate_goal_completion(
        milestones=report["milestones"],
        benchmark_contract=first_pass_benchmark_contract,
        pricing_evidence=pricing_poc_evidence,
        trace_anchor_evidence=trace_anchor_evidence,
        network_observation_evidence=network_observation_evidence,
        ocr_accuracy_evidence=ocr_accuracy_evidence,
    )

    if args.output:
        report = finalize_report_output(report, Path(args.output))
    rendered = json.dumps(report, indent=2)
    print(rendered)
    return 0 if report["selected_runtime_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
