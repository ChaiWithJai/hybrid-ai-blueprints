# First pass human review runbook

Status: packet ready; reviewer roster and signed submissions pending  
Current submissions: 0  
Current cases: 5 development cases  

## Purpose

The review determines whether each saved response is correct, complete, and
useful to a deal professional. The review does not approve the planned 120 case
release benchmark. The five responses are known development data.

## Reviewer requirements

Two qualified deal reviewers must review the same packet independently. They
must not receive the model name, provider, latency, token counts, or prior model
score. Each reviewer must label every required dimension as pass or fail. A
failed label needs a specific critique.

A third principal reviewer must resolve disagreements. The principal reviewer
cannot be either of the first two reviewers.

Reviewer identity is not self-asserted in the JSON. The domain owner must add
two output reviewers and, before adjudication, one principal to
`output_reviewer_roster.v1.json`. Each person must control a distinct Buzz key.
For example:

```bash
python3 scripts/add_output_reviewer.py \
  --reviewer-id REVIEWER_ID \
  --display-name "DISPLAY NAME" \
  --role qualified_deal_output_reviewer \
  --qualification "RECORDED QUALIFICATION" \
  --buzz-pubkey REVIEWER_NOSTR_PUBLIC_KEY \
  --approved-by DOMAIN_OWNER_ID \
  --confirm-domain-owner-approval
```

Use `principal_output_reviewer` for the adjudicator. Roster membership binds a
name to a key, but the domain owner is responsible for verifying the person's
legal identity and key control.

The roster command reads, checks, and replaces the roster while holding one
local process lock. Concurrent approvals on the same machine cannot overwrite
each other. The command also checks the updated roster before it replaces the
current file. Direct JSON edits must satisfy the same ID, text length, role,
and public key rules, but direct edits are not the supported approval path.

## Files

- `evidence/first-pass-human-review-packet-v2.json` is the blinded packet.
- `benchmarks/first_pass/human_review_submission.schema.json` defines one
  completed reviewer submission.
- `benchmarks/first_pass/principal_adjudication.schema.json` defines the
  principal review when the first two reviewers disagree.
- `benchmarks/first_pass/judge_calibration.schema.json` defines one semantic
  judge calibration input after the human labels are complete.

The current packet SHA256 is
`24e7ccb69d5e4efbe94cbf2b45137f1844ddd1cf2575929de980ec31df5c1a6d`.
Regenerate the packet when the registry, rubric, or responses change.

## Process

1. Generate the packet.

   ```bash
   python3 scripts/export_first_pass_review_packet.py
   ```

2. Give the same packet to both reviewers without model identity metadata.

3. Each reviewer creates a JSON submission that follows
   `human_review_submission.schema.json`. The submission must include the
   packet hash, every case response hash, the roster-bound `reviewer_pubkey`,
   and a 64-zero placeholder `buzz_event_id`.

4. Publish with the reviewer's own Buzz private key. The publisher validates
   the unsigned record and roster, sends the canonical payload, restores the
   exact event from Buzz, verifies the signer and content, and only then
   replaces the placeholder in the specified file.

   ```bash
   BUZZ_PRIVATE_KEY=REVIEWER_PRIVATE_KEY \
   python3 scripts/publish_review_attestation.py \
     --kind blinded_output_review \
     --record /approved/path/reviewer-a.json \
     --buzz-channel REVIEW_CHANNEL_ID
   ```

   `render_review_attestation.py` remains available for inspecting the
   canonical payload, but manual event-ID copying is not the supported path.

5. Validate both submissions against exact raw events restored from that
   private Buzz channel. The validator checks the channel tag, recomputes each
   NIP-01 event ID, and verifies its BIP-340 Schnorr signature. Keep this
   channel dedicated to benchmark review attestations.

   ```bash
   python3 scripts/validate_first_pass_reviews.py \
     --submission /approved/path/reviewer-a.json \
     --submission /approved/path/reviewer-b.json \
     --buzz-channel REVIEW_CHANNEL_ID
   ```

6. If the receipt reports disagreements, the principal reviewer creates an
   adjudication file, publishes a `blinded_output_adjudication` attestation,
   and validates the same pair with the added file.

   ```bash
   BUZZ_PRIVATE_KEY=PRINCIPAL_REVIEWER_PRIVATE_KEY \
   python3 scripts/publish_review_attestation.py \
     --kind blinded_output_adjudication \
     --record /approved/path/principal-adjudication.json \
     --buzz-channel REVIEW_CHANNEL_ID

   python3 scripts/validate_first_pass_reviews.py \
     --submission /approved/path/reviewer-a.json \
     --submission /approved/path/reviewer-b.json \
     --adjudication /approved/path/principal-adjudication.json \
     --buzz-channel REVIEW_CHANNEL_ID
   ```

7. Keep the review gate open unless the command returns success and the receipt
   records `review_gate_complete` as true.

8. Use `resolved_labels` from the successful receipt as the human reference.
   The validator records one label for every case and human dimension. Reviewer
   agreement and principal adjudication are recorded as separate resolution
   types. The receipt stores the submissions, adjudication, roster hash, raw
   Buzz events, and a hash of the complete resolved label list. A later
   calibration run verifies the NIP-01 event IDs and BIP-340 signatures again.
   Editing the receipt and updating its file hash cannot replace a signed label.

## Judge calibration

Judge calibration starts after the calibration split contains at least 20
approved cases across at least five deals. The judge input must reference a
successful human review receipt by path and hash. The evaluator independently
replays the receipt from its signed events before using any label. The input
must include one judgment
for every semantic dimension in that receipt and one answer order trial for
every calibration case.

Run the calibration evaluator with:

```bash
python3 scripts/evaluate_judge_calibration.py \
  /approved/path/judge-calibration-input.json
```

The evaluator checks critical false passes, fail recall, fail precision,
Cohen's kappa, parse failures, and answer order changes. It returns a failed
result when the human receipt is missing or changed. It also fails when the
sample is too small or any expected label is missing. A passing calibration
does not authorize the sealed test.

## Acceptance boundary

A completed review pair provides development labels and error analysis. It
does not change the registry to domain approved, authorize sealed test access,
or support a Bonsai accuracy release. The release contract still requires 120
cases across at least 30 deals, approved owners and thresholds, calibration,
and one sealed test run.
