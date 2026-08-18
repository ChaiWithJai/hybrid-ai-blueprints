# First pass underwriting benchmark

This directory contains the versioned contracts for the first pass
underwriting benchmark. The product and evaluation decisions are documented in
[`docs/FIRST_PASS_UNDERWRITING_BENCHMARK.md`](../../docs/FIRST_PASS_UNDERWRITING_BENCHMARK.md).

The five registered cases are development cases. The team has inspected their
outputs, so they are not sealed test evidence. None has domain approval.

Files:

- `benchmark_manifest.v2.json` records the target, inventory sources, split
  policy, and release approval state. Inventory counts are derived by the
  validator instead of being duplicated here.
- `development_registry.v2.json` contains the five base development cases with
  source snapshot hashes, claim to citation links, and explicit review states.
- `candidate_case_registrations.v1.json` is the sole atomic membership commit
  for later approved public cases. It starts empty. Its entries reference
  immutable content-addressed source, review, approval, roster, and raw Buzz
  event artifacts that the contract validator replays.
- `benchmark_manifest.v1.json` and `development_cases.v1.json` remain unchanged
  because their hashes are inputs to the saved three deal product run.
- `rubric.v1.json` records dimensions, severity levels, and proposed release
  thresholds.
- `case.schema.json` defines a labeled case record.
- `run_record.schema.json` defines a model and product result.
- `judge_calibration.schema.json` defines the semantic judge calibration input.
- `sealed_test_manifest.v1.json` is the public, currently empty sealed inventory.
  Its schema permits case IDs, deal isolation metadata, source snapshot hashes,
  and secret case hashes. It rejects prompts, questions, answers, claims, and
  citations.
- `sealed_test_control.v1.json` binds that inventory and starts explicitly
  unauthorized. It later binds a passing calibration result and one frozen
  product verification artifact before a one-time read is possible.
- `pricing_poc.schema.json` defines the buyer-attested paid proof of concept.
  It measures product value and willingness to pay after use. It does not
  replace benchmark accuracy or security approval.
- `candidate_deal_sources.v1.json` records a separate 29-deal sourcing list.
  All 29 official SEC filings are acquired, parser verified, and bound to
  separate evidence hashes. They remain unregistered and have no labels. The
  one browser-observed Zendesk fact does not change the benchmark inventory.
- `candidate_companion_sources.v1.json` records one public 10-K or 10-Q filed
  before each deal proxy. All 29 companion filings are acquired, parser
  verified, and bound to separate evidence hashes. They are source material,
  not benchmark cases.
- `candidate_question_drafts.v1.json` contains 319 reviewer leads across the 29
  candidates. The eleven question families include 261 single-source drafts
  and 58 two-source drafts. Every release task family has enough candidate plus
  registered capacity to meet its target. Expected answers and labels are empty.
  The review process is in
  `docs/CANDIDATE_QUESTION_REVIEW_RUNBOOK.md`.

Raw private test prompts and expected answers must not be committed here. The
sealed manifest may contain identifiers and hashes after an approved secure
storage process exists.

Validate the current contract with:

```bash
python3 scripts/verify_first_pass_benchmark_contract.py
python3 scripts/evaluate_first_pass_development.py
python3 scripts/export_first_pass_review_packet.py
python3 scripts/evaluate_judge_calibration.py /approved/path/calibration-input.json
python3 scripts/open_sealed_test.py
python3 scripts/evaluate_pricing_poc.py evidence/first-pass-pricing-poc.json
BUZZ_PRIVATE_KEY=<buyer-key> python3 scripts/publish_pricing_poc.py \
  --record evidence/<poc-id>.unsigned.json \
  --buzz-channel <private-channel-id> \
  --confirm-record-buyer-evidence
python3 scripts/draft_candidate_questions.py
```

The command returns success when the registered files are structurally valid.
The JSON report has a separate `release_ready` field. The field remains false
until case counts, deal coverage, slice coverage, domain reviews, and owner
approvals meet the release contract.

The development evaluator checks saved responses for required citations,
registered numeric tokens, answer absence behavior, and source folder writes.
It leaves meaning, completeness, and usefulness unverified until an approved
human review exists. A deterministic pass cannot become an accuracy release.

The sealed test command without a secret path is a read-free preflight. The
current result is blocked and reports the missing inventory, approvals,
calibration, and frozen system binding. The eventual one-time operation also
requires `--confirm-one-time-contact`. It creates a version-consuming contact
receipt before invoking the external secret loader. A bad bundle or hash still
consumes that version and cannot be retried.

The review export removes model and provider identity. A valid review must be
bound to the packet and rubric hashes, cover every case and human dimension,
and explain every failed label. Two distinct qualified reviewers are required.
A principal reviewer must resolve any disagreement.
