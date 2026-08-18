# Candidate Question Review Runbook

Updated: 2026-08-15

## Purpose

The candidate question file is a reviewer queue. It is not benchmark data. The
retriever proposes nearby source anchors for eleven review questions on each of
29 acquired SEC deals. The questions cover every task family in the release
contract. Two question families require both the proxy and the pre-transaction
financial filing. The queue does not create an expected answer, label, split,
approval, or accuracy result.

The queue is `benchmarks/first_pass/candidate_question_drafts.v1.json`. Reviewers
use `evidence/candidate-source-review-packet-v1.json`, which is reproducibly
generated from that queue and its source registry.

## What the generator provides

Each draft contains:

- the candidate deal and question family;
- one provisional question;
- the acquired source and evidence hashes;
- up to four ranked source excerpts with exact anchors;
- an empty expected answer and empty label list;
- an explicit unregistered and unreviewed state.

Retrieval rank is only a lead. It can select proposal history, a table of
contents, an equity award clause, or another nearby passage instead of the
final term.

## Review one draft

1. Open the acquired source named in the draft.
2. Read every proposed excerpt in its surrounding source context.
3. Mark which anchors support the final answer and which are confusable.
4. Rewrite the question so one reviewer can decide whether the answer is
   correct. Split broad questions when two facts need separate judgments.
5. Write the required claims and calculations from the source. Do not copy a
   model answer.
6. State whether absence is the correct answer for any requested fact.
7. Add material counterevidence, proposal history, and table or calculation
   requirements.
8. Ask a second qualified reviewer to check the source interpretation.
9. Record the domain owner, review date, and disagreements.
10. Only then create a case that passes `case.schema.json` and assign its deal
    to a development, calibration, or sealed split.

## Independent review records

Use the local reviewer workshop at
`http://127.0.0.1:8787/benchmark/source-review`. It lists every candidate,
shows the packet-bound excerpts, and loads nearby parsed nodes directly from
the hash-verified SEC filing. It does not expose retrieval rank or model
identity, and it does not preselect a decision or answer policy. The current
browser is a source-reading and decision-drafting surface. Its submit control
stays disabled until browser key custody and a two-phase Buzz signing flow are
implemented. Once a reviewer is rostered, the form can download an unsigned,
schema-valid review record for that reviewer to sign through Buzz CLI. The
download is not a submission, approval, or benchmark promotion. A roster
dropdown alone is not authentication.

The workshop shows four separate gates for source review, case approval,
registration, and accuracy release. The counts come from
`/api/benchmark/pipeline`. A structurally valid empty ledger remains blocked,
and the page does not use a green state until the accuracy release contract
passes. The local setup stores the dedicated private Buzz review channel ID in
`.runtime/buzz/benchmark-review-channel-id`.

Reviewer qualification is not a free text assertion. Both reviewer rosters
start with an unconfigured authority and no reviewers. First, verify the domain
owner and their Buzz key outside Prism. Then provision that local root of trust:

```bash
python3 scripts/configure_reviewer_roster_authority.py \
  --authority-id DOMAIN_OWNER_ID \
  --display-name "DOMAIN OWNER" \
  --buzz-pubkey DOMAIN_OWNER_NOSTR_PUBLIC_KEY \
  --buzz-channel PRIVATE_REVIEW_CHANNEL_ID \
  --confirm-out-of-band-authority-identity
```

The confirmation records an operator action. Prism cannot verify the person's
legal identity or work history. The command writes the same authority to both
roster scopes. A process or disk failure can interrupt the two file writes. If
that happens, every roster read and reviewer admission fails until both files
agree. Run the same configuration command again to repair an interrupted
commit. A different key cannot use this repair path. After provisioning, the
domain owner can sign and record one exact reviewer admission:

The replacement check runs again while each roster lock is held. If two setup
processes race with different keys, the first committed key wins and the other
process fails. It cannot overwrite the winner using an earlier empty read.

```bash
BUZZ_PRIVATE_KEY=DOMAIN_OWNER_PRIVATE_KEY \
python3 scripts/approve_reviewer_roster_entry.py \
  --scope source_review \
  --reviewer-id REVIEWER_ID \
  --display-name "DISPLAY NAME" \
  --role qualified_deal_source_reviewer \
  --qualification "RECORDED QUALIFICATION" \
  --buzz-pubkey REVIEWER_NOSTR_PUBLIC_KEY \
  --approved-at APPROVAL_TIMESTAMP \
  --confirm-domain-owner-approval
```

The command checks that the private key matches the configured authority. It
publishes the exact admission to the configured Buzz channel and restores the
raw event. It checks the NIP 01 identity and BIP 340 signature before appending
the reviewer. A changed role, qualification, timestamp, reviewer key, signer,
or channel fails before the roster changes. The lower level
`render_reviewer_roster_approval.py` and `add_source_reviewer.py` commands
support a separate signing ceremony.

Use `principal_source_reviewer` only for a person authorized to adjudicate
disagreements. The command refuses replacement of an existing identity, and
changes require a separate roster amendment.
Use `domain_case_owner` for the accountable deal professional who may approve a
fully authored case after source-review eligibility. This is a separate role;
source review alone never grants case approval.

Every active person needs a distinct Buzz public key. The loader rejects two
reviewer identities that share one key. The domain owner remains responsible
for confirming that the named person controls that key. The signed admission
proves authorization by the configured key. It does not prove the person's
identity, qualification, independence, or review quality.

Each reviewer submits one or more draft decisions that pass
`candidate_source_review_submission.schema.json`. The submission records the
reviewer's qualification, packet hash, source hash, full-context check, final
question, answer policy, supporting and confusable citations, expected claims,
and rationale. Partial batches are allowed so reviewers do not need to finish
all 319 drafts in one file.

A draft is eligible for later case authoring only when two distinct qualified
reviewers submit the same normalized decision. A second submission from the
same reviewer does not count. If qualified reviewers disagree, a principal who
did not submit either review must select one review in a hash-bound record that
passes `candidate_source_adjudication.schema.json`.

Eligibility is not registration. A later case-authoring step must still create
a schema-valid case, preserve deal-level split isolation, and obtain the named
domain owner's approval.

## Signed Buzz attestation

Each review JSON includes the roster-bound `reviewer_pubkey` and a
`buzz_event_id`. The guarded publisher handles the two phases because the event
ID does not exist until Buzz publishes the event:

1. Complete the workshop form and choose **Download unsigned review**, or create
   the review JSON manually with `buzz_event_id` set to 64 zeroes. The browser
   does not send the decision to the server.
2. Publish the review with the reviewer's own `BUZZ_PRIVATE_KEY`. Do not use the
   Prism owner or agent key for a different reviewer. The command validates the
   record and roster, publishes the canonical payload, restores the exact Buzz
   event, verifies its signer and content, and only then writes its event ID
   into the specified JSON file.

   ```bash
   BUZZ_PRIVATE_KEY=REVIEWER_PRIVATE_KEY \
   python3 scripts/publish_review_attestation.py \
     --kind candidate_source_review \
     --record /approved/path/reviewer-a.json \
     --buzz-channel REVIEW_CHANNEL_ID
   ```

   `render_review_attestation.py` remains available for inspecting the exact
   canonical payload. Manual publication and event-ID copying are not the
   supported path.
3. Validate the review against relay-restored events.

   ```bash
   python3 scripts/validate_candidate_source_reviews.py \
     --buzz-channel REVIEW_CHANNEL_ID
   ```

The validator rejects a missing event, a signer key that differs from the
roster, altered attestation text, packet drift, or review-record drift. Buzz
verifies the Nostr event signature when the event is accepted and restored.
The validator retrieves each exact raw event by ID, checks its private-channel
tag, recomputes its NIP-01 event ID, and verifies its BIP-340 Schnorr signature.
Use a dedicated private review channel so unrelated traffic cannot obscure the
audit history.

## Promotion criteria

A draft can become a registered case only when all of these are true:

- the source bytes and acquisition evidence hashes still match;
- every required claim maps to an exact supporting anchor;
- confusable and contradictory passages are recorded;
- numeric answers include units, dates, and a stated calculation when needed;
- the question has one clear decision intent;
- two qualified reviewers agree, or a distinct principal adjudicates;
- the whole deal stays in one split;
- the domain owner signs the case record.

Passing retrieval or model output is not a promotion criterion.

## Signed case approval boundary

An eligible draft is still not a benchmark case. A case author must create a
record that follows `candidate_case_approval.schema.json`. The embedded case
must follow `case.schema.json` and retain the exact reviewed question, expected
claims, supporting citations, source and excerpt hashes, answer policy, and
confusable citations. Its split must not divide a deal across benchmark splits.

Open `http://127.0.0.1:8787/benchmark/case-authoring` after source review makes
a draft eligible. The page shows the agreed source contract and prevents the
author from changing the question, expected claims, citations, source hashes,
or excerpt hashes. The author supplies the remaining case metadata and chooses
the rostered domain case owner. The page downloads an unsigned approval. It
does not sign, record, or register the case. Sealed test cases cannot be stored
through this repository workflow.

The rostered domain case owner signs the approval with their own key:

```bash
BUZZ_PRIVATE_KEY=DOMAIN_CASE_OWNER_PRIVATE_KEY \
python3 scripts/publish_review_attestation.py \
  --kind candidate_case_approval \
  --record /approved/path/case-approval.json \
  --buzz-channel REVIEW_CHANNEL_ID
```

Then validate the approval against the same relay-restored source reviews:

```bash
python3 scripts/validate_candidate_case_approval.py \
  --submission /approved/path/reviewer-a.json \
  --submission /approved/path/reviewer-b.json \
  --approval /approved/path/case-approval.json \
  --buzz-channel REVIEW_CHANNEL_ID
```

Add `--adjudication /approved/path/source-adjudication.json` when a principal
resolved the source reviews. A passing report states
`benchmark_case_registered: false`: it proves authorization for a later atomic
registration step and does not edit the registry. Rejected reviews, including a
principal-selected rejection, cannot produce an eligible or approvable case.

After inspecting the passing report, record the signed approval chain without
registering the case:

```bash
python3 scripts/record_candidate_case_approval.py \
  --submission /approved/path/reviewer-a.json \
  --submission /approved/path/reviewer-b.json \
  --approval /approved/path/case-approval.json \
  --buzz-channel REVIEW_CHANNEL_ID \
  --confirm-record-signed-approval
```

Add `--adjudication` when applicable. The command restores and verifies every
raw Buzz event, writes content addressed artifacts, and makes one atomic append
to `candidate_case_approval_records.v1.json`. The append records a sequence,
the prior entry hash, the new head hash, and the entry count. A recorded approval remains
separate from benchmark membership. The approval ledger rejects sealed test
cases so expected answers cannot enter the repository during staging.

After inspecting the recorded approval, explicitly register it:

```bash
python3 scripts/register_candidate_case.py \
  --approval-record-id APPROVAL_RECORD_ID \
  --confirm-register-approved-case
```

Registration replays the stored signed approval chain, copies the public source
bytes into a content addressed path, and then performs one atomic append to
`candidate_case_registrations.v1.json`. This ledger uses the same sequence and
hash chain. That ledger replacement is the only
benchmark-membership commit. A crash before it can leave unreferenced,
collision-checked content-addressed files but cannot create a partially registered case. Duplicate approvals,
draft IDs, case IDs, cross-split deals, sealed expected answers, changed source
bytes, unrecorded approvals, and changed artifacts fail closed.

Both ledger commands take an advisory lock on the local filesystem and reread
and validate the complete hash chain before checking and replacing the ledger.
The lock prevents cooperating Prism processes from losing concurrent updates.
The chain detects changed order, changed entries, and deletion when the saved
count or head no longer matches. It is not a distributed lock or external
anchor. A local administrator who controls the files can still rewrite the
complete chain, so the JSON ledgers remain mutable local records.

## Verification

Regenerate and validate the queue with:

```bash
python3 scripts/draft_candidate_questions.py
python3 scripts/export_candidate_source_review_packet.py
python3 scripts/validate_candidate_source_reviews.py
python3 scripts/verify_first_pass_benchmark_contract.py
```

The zero-submission validation does not need `--buzz-channel`. Once any review
or adjudication file exists, the channel argument is mandatory.

The current validation is expected to pass its structural checks while stating
`promotion_ready: false`, zero active reviewers, 319 pending drafts, and zero
registered cases. The
benchmark contract must remain structurally valid and `release_ready` must
remain false until registered inventory, reviews, coverage, and approvals
satisfy the published benchmark contract.

Replay the browser guard with:

```bash
node scripts/verify_source_review_surface.mjs
node scripts/verify_case_authoring_surface.mjs
```

The first command checks the rendered gate counts, closed review controls, Buzz
attestation boundary, console errors, failed requests, and HTTP errors. It
writes `evidence/browser-source-review-v1.json` and a hash bound screenshot.
The second command checks the blocked authoring state, stage counts, disabled
owner and export controls, unselected evaluation slices, and browser errors. It
writes `evidence/browser-case-authoring-v1.json` and a hash bound screenshot.
