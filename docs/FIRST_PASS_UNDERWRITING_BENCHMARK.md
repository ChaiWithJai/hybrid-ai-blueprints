# First pass underwriting product and benchmark

Status: proposed product and benchmark contract  
Version: 1.0.0  
Created: August 14, 2026  
Product owner: unassigned  
Domain owner: unassigned  
Strategy owner: proposed for the PrismML strategy lead  
Approval state: not approved  

## Main decision

Prism Vault v0 will be designed around one job. A private equity deal team can
point Prism Vault at an authorized private folder and receive a first pass
underwriting brief. The brief helps a deal professional decide whether to
advance, pause, or stop review.

Every material factual claim must cite source evidence. Every calculation must
show its inputs and method. The brief must identify missing and conflicting
information. A human remains responsible for the investment decision.

The first release will not claim to produce a completed investment committee
memo. A completed memo requires market work, judgment, and facts that may not
exist in the folder. The first pass brief is a bounded product that can be
tested, reviewed, and priced.

## Why the job fits PrismML

PrismML develops small local models with high capability for their memory and
compute use. The company presents Bonsai as a family for local reasoning,
vision, tool use, and long agent loops. Local execution can keep private files
and intermediate state on customer controlled hardware.

The proposed division of work is:

| Function | Responsibility |
| --- | --- |
| Research | Babak Hassibi, Sahin Lale, Omead Pooladzandi, and their research team establish the model capability and efficiency limits |
| Product and engineering | The product team turns the model into a private folder workflow with evidence, calculations, review, and shared URLs |
| Strategy | The strategy lead selects the first buyer, tests willingness to pay, chooses the value unit, defines packaging, and decides whether the proof of concept supports expansion |
| Domain review | A named deal professional defines expected answers, labels outputs, and adjudicates disagreements |

The responsibility assigned to the strategy lead is a product proposal. It is
not a statement about an existing PrismML operating process.

## Pricing exercise

The pricing exercise follows Madhavan Ramanujam's published method. PrismML
should test price and packaging while it tests the product. The team should not
set price from model cost or competitor seat prices alone.

The first pricing assumptions are:

| Question | Initial assumption | Validation method |
| --- | --- | --- |
| First buyer | A private equity associate or vice president who owns the first review | Interview and observe deal professionals who perform the work |
| Economic buyer | A partner, operating executive, or technology leader with a deal review budget | Confirm budget authority during proof of concept selection |
| Valuable result | An expert accepted first pass underwriting brief | Measure acceptance, corrections, and review time |
| Value unit | One accepted first pass review for one deal room | Compare with seat, usage, and platform fee alternatives |
| Proof of concept | A paid review of historical deal rooms with a written business case | Require buyer effort, source access, and success criteria |
| Price research | Ask for acceptable, expensive, and prohibitively expensive prices after the buyer uses the workflow | Record answers by buyer segment and package |
| Packaging | Start with a secure workspace and completed review allowance | Test whether collaboration, policy, and deployment support create separate willingness to pay |

The proof of concept should use at least two closed historical deals from the
customer. One deal supports setup and correction. The second deal measures
transfer without case specific changes. Public filings can demonstrate the
workflow, but they cannot prove willingness to pay for private folder work.

No dollar price is approved in this document. A price decision requires buyer
research and a measured proof of concept.

The executable pricing contract is defined by
`benchmarks/first_pass/pricing_poc.schema.json` and `core/pricing_poc.py`. The
workspace at `/benchmark/pricing-poc` presents the ten commercial gates and the
current evidence state. A completed record must include two distinct private
historical source hashes, baseline and Prism review times, setup and unchanged
transfer roles, usefulness and correction results, prices asked after use, and
a paid next step or recorded decline reason. A configured commercial authority
first approves the buyer key after an identity and role check outside Prism.
The authority and buyer keys must be distinct. The buyer then signs the exact
authorized record. The evaluator restores both events from the configured
authority channel on every read, verifies their NIP-01 event IDs and BIP-340
signatures, and compares every signed field with the saved events. A self-issued
buyer key or a signature that exists only in JSON does not count.

No buyer record exists today. The current surface therefore says that pricing
proof is blocked. Synthetic tests exercise the evaluator and its negative
controls. They do not count as customer research, willingness to pay, or
revenue.

The browser can prepare an unsigned record, but it never receives the buyer's
private key and cannot submit evidence. The authority key holder first runs
`scripts/publish_pricing_buyer_authorization.py`, which publishes and restores
the exact approval without writing the final POC. The buyer then runs
`scripts/publish_pricing_poc.py` with that event ID. The second command checks
that `BUZZ_PRIVATE_KEY` matches the stated buyer public key, publishes the
authorized canonical payload, restores both raw events, and verifies their
NIP-01 IDs and BIP-340 signatures. It then uses an atomic replacement for the
canonical record. Later reads repeat both exact Buzz restorations instead of
trusting saved signatures. The configured authority proves key control and an
approval statement. It does not prove the signer's legal identity or employment.

Recording and passing are separate. Any structurally valid buyer-signed result
is retained, including a refusal to quote price or a POC that misses usefulness,
time, or transfer-quality gates. The evaluator reports those gates as failures.
It does not suppress negative buyer evidence.

## The certified job

The certified job statement is:

> Given an authorized M&A folder and a stated investment screen, produce a
> reviewable first pass underwriting brief that helps a private equity deal
> professional decide whether to advance, pause, or stop review. Support every
> material factual claim with source evidence, reproduce every calculation,
> and state missing or conflicting information.

The benchmark starts when the folder snapshot and investment screen are
accepted. The benchmark ends when the signed brief, evidence links, trace, and
review record are available at canonical URLs.

## Required output

Every first pass brief must contain the following sections when the source and
investment screen make them applicable:

1. The brief identifies the transaction, parties, structure, and important
   dates.
2. The brief states the purchase price and the valuation measures disclosed by
   the source.
3. The brief states debt, preferred equity, common equity, and named financing
   parties when the source provides them.
4. The brief shows entry valuation calculations only when every required input
   is supported.
5. The brief reports important financial quality, market, regulatory,
   operating, and contractual findings requested by the investment screen.
6. The brief separates material risks from unresolved questions.
7. The brief lists missing and conflicting information.
8. The brief recommends advance, pause, or stop and states the reasons.
9. The brief links every material factual claim to a document anchor or page.
10. The brief labels source facts, calculations, assumptions, inferences, and
    unknowns.

### Registered calculation contract

A case counts toward calculation coverage only when its calculation is
executable and source bound. Each registered calculation names its inputs. Each
input records a variable name, reviewed claim ID, numeric value, and unit. The
numeric value must occur in that reviewed source claim. The formula may use only
those variables, numeric constants, parentheses, and bounded arithmetic.

Before registration, Prism evaluates the formula without Python `eval`, function
calls, attribute access, or imports. The computed result must match the expected
value within the registered tolerance. During output evaluation, Prism requires
the response to show every registered input, the formula, the result, and its
unit together in one calculation block. This is a deterministic reproducibility check. It does not decide whether
the chosen economic method is appropriate. That judgment remains part of
qualified blinded review.

An output section is not required merely because it appears in this list. The
case definition records which sections the user requested and which sections
the available sources can support. The benchmark must not penalize a model for
omitting optional boilerplate.

## The ten benchmark decisions

### 1. Job under certification

The job is the first pass underwriting brief defined above. The job is not
general folder analysis, open chat, or a completed investment committee memo.

### 2. Label authority

A principal deal professional owns the expected result. A second qualified
reviewer labels every sealed test output without seeing the model identity. The
principal domain owner adjudicates disagreements and records the reason.

The strategy or engineering team cannot approve domain correctness by itself.
The answer model and judge model cannot create their own ground truth.

### 3. Error severity

The benchmark uses three severity levels:

| Severity | Definition | Examples | Release effect |
| --- | --- | --- | --- |
| Critical | An error can change the deal decision or creates unsupported confidence | Wrong purchase price, wrong debt multiple, unsupported recommendation, missed answer absence, citation to unrelated text | Any critical false pass blocks release |
| Major | An error leaves a required part incomplete or makes review materially harder | Missing financing party, omitted requested market conclusion, unreproducible calculation | The critical case threshold and overall component threshold apply |
| Minor | An error affects presentation but does not change the supported conclusion | Small wording problem, optional detail omitted, harmless formatting issue | Reported for improvement and does not block alone |

### 4. Dataset size and coverage

Benchmark version 1 targets 120 labeled cases across at least 30 deals. The
minimum production calibration set remains 100 cases. The larger target leaves
room for a sealed test set and meaningful product slices.

| Split | Cases | Minimum deals | Use |
| --- | ---: | ---: | --- |
| Development | 60 | 15 | Error analysis, prompt work, and deterministic rule development |
| Calibration | 20 | 5 | Judge calibration and threshold selection |
| Sealed test | 40 | 10 | One final model and product decision after all settings are frozen |

The target task mix is:

| Task family | Cases |
| --- | ---: |
| Transaction identity, structure, and chronology | 10 |
| Purchase price and valuation | 20 |
| Financing and capital structure | 20 |
| Financial quality and earnings adjustments | 15 |
| Contract terms, covenants, and approvals | 15 |
| Market and regulatory findings | 15 |
| Risks, conflicts, and missing information | 15 |
| Cross document synthesis and recommendation | 10 |

At least 20 percent of cases must require an answer absence decision. At least
25 percent must use tables or calculations. At least 40 percent must require
more than one document. At least 10 percent must contain conflicting or easily
confused evidence. A case may satisfy more than one condition.

The dataset must also identify the ingestion form for every source. Scanned PDF
cases need separate labels for text accuracy, reading order, table structure,
and citation location. A page can pass text recognition and still fail table or
layout fidelity. The current macOS OCR path is an engineering capability only,
until domain reviewers approve those cases and the benchmark measures them.

### 5. Leakage control

The dataset is split by deal, not by question or document. All documents,
amendments, questions, and paraphrases from one transaction stay in one split.
Near duplicate transactions and templated documents receive a family identifier
and remain in one split when they would reveal the answer pattern.

The sealed test manifest stores only case identifiers, source snapshot hashes,
and split metadata in the working repository. Prompts, expected claims, and
adjudications remain in access controlled storage until the run starts. Opening
the sealed answers for prompt or procedure work invalidates the set and creates
a new test version.

The executable public manifest also commits the hash of each external secret
case. Its schema rejects question, prompt, answer, claim, citation, and source
text fields. The opening controller returns before calling the external loader
unless the inventory, split isolation, owner approvals, approved thresholds,
passing judge calibration, and frozen system verification are all bound and
valid. The controller creates an exclusive contact receipt before the first
read. Any contact, including an invalid or hash-mismatched bundle, consumes the
version. The current manifest is empty and the control is unauthorized, so the
preflight is expected to fail without reading a secret.

The five current public dossier cases are development cases. They cannot serve
as sealed evidence because the team has inspected their outputs and failures.

### 6. Model roles

Bonsai is a candidate answer model and a candidate judge. Human labels remain
the authority. The same Bonsai configuration must not be the only judge of its
own output.

The benchmark compares these roles separately:

| Role | Required comparison |
| --- | --- |
| Answer model | Deterministic reviewed baseline, Bonsai 27B 1 bit, Ternary Bonsai 27B when available, and one approved cloud reference when policy permits |
| Semantic judge | Bonsai judge, an independent reference judge when policy permits, and human labels |
| Deterministic evaluator | Source hashes, citation resolution, required fields, number matching, calculation checks, and runtime failures |

Model identity, weight hash, prompt hash, runtime, sampling settings, context
limit, and hardware must be stored with every scored run.

### 7. Failure localization

Each case receives separate results for ingestion, retrieval, response,
evaluation, and product delivery. A final fail does not identify the failed
stage by itself.

The diagnostic sequence is:

1. First, verify the source snapshot and parser output.
2. Second, test whether the needed passage appears in bounded retrieval.
3. Third, give the answer model the exact supporting passage. The oracle
   context result separates retrieval errors from response errors.
4. Fourth, compare deterministic checks, semantic judge results, and human
   labels.
5. Fifth, verify the signed Buzz event, canonical URL, and review record.

The oracle-context diagnostic now runs all five registered cases. Four answer
cases use only their registered source passages. The Citrix absence case also
uses a complete deterministic folder audit. The audit verifies two source files
and scans all 2,401 admitted nodes against three disclosed direct-disclosure
patterns. It checks three confusable anchors, including the 13.0x valuation
multiple and the $15.0 billion debt commitment. Two cases passed the narrow
citation and number probe. The Citrix financing answer omitted its required
citation, and the CMA deterministic failure persisted. The Citrix absence
answer included both required absence phrases, but it omitted its required
citation and still failed. The absence patterns were written after the team
inspected the development corpus, so the audit does not prove semantic absence.
The record keeps semantic accuracy and failure attribution unverified because
the development labels have no domain approval. See
`evidence/bonsai-oracle-context-diagnostic-v1.json` and
`docs/TEN_BENCHMARK_DECISIONS_REALITY_AUDIT.md`.

### 8. Private data and evaluation records

Raw private source text stays inside the approved local boundary by default.
The evaluation record stores source hashes, anchor identifiers, claim hashes,
scores, model data, timing, and human labels. Short evidence excerpts may be
stored only when the customer policy allows them.

Cloud model use requires explicit approval for the provider and separate
approval for deal room context. Redaction does not make a document safe by
default. The trace must record the approval, payload policy, provider, and
returned model identity.

An Arize deployment may be the experiment system of record after security,
retention, and access policies are approved. Until then, the repository uses a
vendor neutral JSONL record with the same core fields.

### 9. Required comparisons

Every release report must compare answer quality under the same cases, source
snapshot, retrieval limit, prompt contract, and output budget. The report must
not compare models that received different evidence without showing the
difference.

The minimum comparison is the deterministic reviewed baseline and the local
Bonsai configuration. A cloud comparison is optional until policy approval.
Ternary Bonsai becomes required when the artifact is available on the target
hardware.

The report includes quality, latency, time to first token, tokens, memory when
measured, parse failures, output limit failures, and signed product delivery.
Cost and energy remain null unless directly measured.

### 10. Release thresholds

The following thresholds are proposed for benchmark version 1. The domain
owner and product owner must approve them before opening the sealed test set.

#### Hard product and answer gates

| Measure | Threshold |
| --- | ---: |
| Source snapshot hash match | 100 percent |
| Citation anchor resolution | 100 percent |
| Material unsupported claims in critical cases | 0 |
| Critical numerical accuracy | 100 percent |
| Critical answer absence recall | 100 percent |
| Critical requested component recall | 100 percent |
| Overall requested component recall | At least 95 percent |
| Unauthorized source folder writes | 0 |
| Empty, invalid, or unrecorded sealed test completions | 0 |
| Canonical Buzz delivery for completed cases | 100 percent |

#### Judge calibration gates

| Measure | Threshold |
| --- | ---: |
| Critical false passes | 0 |
| Fail recall | At least 95 percent |
| Fail precision | At least 90 percent |
| Cohen's kappa against human labels | At least 0.75 |
| Parse failure rate | 0 percent |
| Pairwise order flip rate | Less than 5 percent |

The calibration evaluator is implemented in `core/judge_calibration.py`. Its
input follows `benchmarks/first_pass/judge_calibration.schema.json`. The input
must bind to a successful signed human review receipt and its resolved label
hash. The receipt contains the submissions, adjudication, roster hash, and raw
Buzz events. The evaluator verifies every event ID and signature again before
it accepts the human labels. It requires at least 20 calibration cases across
five deals. It fails when a judgment is missing, cannot be parsed, changes
after answer order reversal, or exceeds any proposed threshold. The evaluator
does not open the sealed test or approve an accuracy release.

#### Product value gates

| Measure | Pilot threshold |
| --- | ---: |
| Expert says the brief is a useful starting point | At least 80 percent of pilot deals |
| Median human first review time | At least 30 percent below the customer's historical baseline |
| Critical correction count after review | 0 for the transfer deal |
| Buyer provides a price range after using the product | Required |
| Buyer agrees to a paid next step or states a recorded reason for declining | Required |

The product value thresholds are hypotheses for the first paid proof of
concept. Customer evidence may change them before the sealed product study.

## Evaluation layers

The benchmark uses ordered evaluation layers. A later layer cannot convert an
earlier hard failure into a pass.

| Layer | Method | Examples |
| --- | --- | --- |
| Source | Deterministic | File hash, byte count, parser admission, page and anchor existence |
| Retrieval | Deterministic and human labeled | Required passage found, confusing passage ranked, retrieval recall at the saved limit |
| Structure | Deterministic | Required sections, parties, numbers, labels, and citation syntax |
| Calculation | Deterministic | Formula, inputs, units, tolerance, and reproducibility |
| Meaning | Human calibrated model judge | Claim support, relation between a number and its meaning, contradiction, and recommendation support |
| Completeness | Checklist and human calibrated judge | Every requested component and result shape |
| Uncertainty | Checklist and human calibrated judge | Supported refusal, missing facts, conflicts, and no invented value |
| Product | Deterministic and human review | Buzz event, canonical URL, review state, latency, and usefulness |

The semantic judge reports pass or fail and a concrete critique. Repeated votes
measure instability. Repeated votes do not create ground truth.

## Rubric families and model representation

The Bonsai judge prior work tested primary intent, overconstraint, and component
overlap. The first pass benchmark keeps the same distinctions:

| Rubric family | Required behavior |
| --- | --- |
| Primary intent | Judge whether the output completes the requested underwriting job without penalizing optional omissions |
| Overconstraint | Require explicit user and case requirements without demanding unsupported boilerplate |
| Component completeness | Require every requested party, value, conclusion, and result shape instead of passing on one relevant part |

The prior activation study found that changing rubric meaning changed final
token activation sketches. The overconstraint correction produced the largest
observed direction change on one matched prompt. The study used one prompt and
a lossy projection, so it does not identify a causal layer or general model
feature.

The benchmark treats a rubric version as part of the model system. Every rubric
must have an owner, version, content hash, calibration report, and sealed test
result. Activation measurements remain research diagnostics and do not count
as product acceptance evidence.

## Case review and adjudication

The domain owner prepares a case from a fixed source snapshot. The case records
the requested components, supported claims, required calculations, acceptable
absence language, forbidden claims, citations, and severity.

Two reviewers label sealed outputs independently. They record a label and a
specific critique for every failed dimension. The principal domain owner then
resolves disagreements without seeing aggregate model rankings. Every change to
ground truth creates a new case version and an adjudication record.

The team reviews failures until new review rounds stop producing new material
failure categories. The benchmark does not claim saturation from a fixed case
count alone.

## Run and release process

1. First, freeze the source snapshot, cases, rubric, thresholds, prompt,
   retrieval settings, model artifact, and runtime settings.
2. Second, save hashes for every frozen input.
3. Third, run development and calibration checks. Do not open sealed expected
   answers.
4. Fourth, obtain written approval from the product and domain owners.
5. Fifth, run the sealed set once for the release decision.
6. Sixth, store all outputs, failures, traces, human labels, and environment
   information.
7. Seventh, publish the full scorecard. Do not publish only the aggregate pass
   rate.
8. Eighth, add each confirmed production failure to development data. Create a
   new sealed set when contact invalidates the old set.

The operational commands are:

```bash
python3 scripts/open_sealed_test.py
python3 scripts/open_sealed_test.py \
  --secret-bundle /approved/external/sealed-bundle.json \
  --confirm-one-time-contact
```

The first command performs only preflight. The second is permitted only after
the control record has been updated through the approved governance process.
It does not print the secret bundle.

## Current evidence and status

The current public dossier set contains five development cases. The corpus and
ingestion checks passed. Bonsai passed two cases and failed three cases. The
failures include an omitted financing party, an unsupported entry debt multiple,
and an omitted regulatory conclusion.

Contract version 2 converts the five cases into the published case schema. Each
case now records a deal snapshot hash, exact source hashes, claim to citation
links, and an explicit domain review state. A deterministic validator checks
schema fields, source evidence, deal split isolation, inventory, coverage, and
signed governance receipts. Plain manifest names and booleans are not approvals.
The contract passes structural validation and fails release
readiness. It reports 5 of 120 cases, 3 of 30 deals, no calibration or sealed
cases, and 0 domain approved cases. Missing table, calculation, and multiple
document coverage also fail the release gate.

The governance ledger is `benchmark_governance.v1.json`. It starts with no
authority and no receipts. One root-signed Buzz event assigns four governance
roles with four distinct actor IDs and signing keys. The root key cannot also
act as a role key. Every role must sign three scopes: the benchmark contract,
the release thresholds, and sealed test opening. This produces 12 required
receipts. Each signed payload includes a hash of the manifest, rubric, case
schema, sealed schemas, sealed public manifest, and sealed controller. A change
to any of those files invalidates the saved receipts. The local trust root is
still checked-in configuration. These controls prove signature and material
binding. They do not make a local administrator unable to replace the code and
trust root.

The operator commands are `scripts/configure_benchmark_governance.py` and
`scripts/approve_benchmark_governance.py`. Both publish to Buzz, restore the raw
event from the relay, verify its NIP-01 identity and BIP-340 signature, and only
then commit the local ledger. Private keys are read from `BUZZ_PRIVATE_KEY` and
are never written to the benchmark artifacts.

The version 2 development evaluator applies only deterministic checks to the
five saved Bonsai question answers. It found one hard failure. The Citrix entry
leverage answer used the wrong citation and failed the required answer absence
behavior. All five owner questions and agent answers now match independently
verified raw Buzz event pairs with valid signatures, exact room binding, and
exact saved-response linkage. This proves product delivery integrity, not answer
quality. All five cases remain unverified for intent, evidence meaning,
component completeness, and human usefulness. The evaluator therefore records
no accuracy release, even where citation and numeric checks pass. See
`evidence/first-pass-development-evaluation-v2.json`.

A blinded development review packet is ready at
`evidence/first-pass-human-review-packet-v2.json`. It contains the five
responses, case requirements, evidence links, and human rubric dimensions. It
does not contain model, provider, latency, or token metadata. Submissions must
match the packet and response hashes, cover all five human dimensions, and come
from two distinct qualified reviewers. No submissions have been received, so
the human review milestone remains open. The operating steps and submission
commands are in `docs/HUMAN_REVIEW_RUNBOOK.md`.

The current result is useful error analysis. It does not meet the proposed
release gates and cannot support a private deal room accuracy claim.

The source review workspace now shows the ten benchmark decisions beside the
five operational promotion stages. Each decision includes current evidence and
one next blocker from the live benchmark state. The current count is 0 of 10
release decisions satisfied. The browser replay verifies all ten cards and
binds the saved decision state to the current API response.

The sourcing registry now contains 29 acquired and parser verified official SEC
DEFM14A filings. A companion registry contains one acquired and parser verified
10-K or 10-Q filed before each deal proxy. Each source is bound to a separate
acquisition record and source hash. This gives every candidate deal two public
documents. It does not create a private deal room or a benchmark case. The 29
candidates plus the 3 registered development deals provide a 32 deal sourcing
pipeline. The benchmark inventory remains 5 cases across 3 deals because none
of the 29 candidates has approved question design, labels, split assignment, or
domain review.

A generated review queue now proposes eleven question families for every
candidate. Six use the proxy, including separate transaction chronology and
regulatory questions. Three use the financial filing. Two reconcile the proxy
with the latest pre-transaction financial filing. The 319 drafts contain exact
anchor candidates and bounded excerpts but no expected answers or labels. Of
these, 261 admit one source and 58 admit both exact source filenames. Every
release task family has enough candidate plus registered capacity to meet its
target. A supported cross-document review must cite both source hashes.
Capacity is not approval, and a calculation prompt does not count as
calculation coverage until reviewers approve it and a later step
registers it. The
benchmark validator rejects a draft that claims registration, review, or an
answer. See
`benchmarks/first_pass/candidate_question_drafts.v1.json` and
`docs/CANDIDATE_QUESTION_REVIEW_RUNBOOK.md`.

The queue now has a separate model-blind source-review boundary. The generated
packet removes retrieval rank, retrieval queries, matched terms, and all model
or runtime identity. Each submission is bound to the packet and source hashes.
Two distinct qualified reviewers must agree on the normalized source decision;
a disagreement requires a distinct principal to select one of the submitted
reviews. This gate only makes a draft eligible for case authoring. It cannot
register or approve a benchmark case. The current evidence records 0
submissions, 0 eligible drafts, and 319 pending drafts.

The post-review case approval boundary is executable but unused. Two matching
affirmative source reviews, or an affirmative review selected by a distinct
principal, are required before a rostered `domain_case_owner` can sign an
authored case. The validator binds the case to the reviewed question, claims,
supporting and confusable citations, source and excerpt hashes, answer policy,
source snapshot, split isolation, and owner identity. Matching rejections are
classified as rejected rather than eligible. A valid approval still reports
that the case is unregistered. The separate registration command writes source
bytes and review artifacts to collision-checked, content-addressed local paths.
It then takes a local advisory file lock, rereads the ledger, and uses one
synced atomic replacement as the sole membership commit. No real
approval has used that path yet.

The source-review web workshop is served at `/benchmark/source-review`. It
shows all 319 drafts, provides exact citation choices, and opens a bounded
window of parsed filing context after rechecking the acquisition and source
hashes. Reviews cannot be submitted by a self-declared identity. The source and
output rosters begin empty and their authority is unconfigured. An operator must
first record one authority identity, Buzz public key, and private review channel
after checking that identity outside Prism. That local confirmation does not
prove the person's legal identity or deal qualification.

Both roster files must hold the same authority object. The setup command can be
interrupted between its two file commits. During that state, every roster read
and reviewer admission fails. Repeating the command with the same authority
repairs the pair. A different authority cannot use the repair path.
The replacement check runs again inside the file lock, so a stale empty read
cannot overwrite a different authority that wins a concurrent commit.

Each reviewer admission must then match a relay-restored event signed by the
configured authority key. The signed content binds the roster scope, full
reviewer record, reviewer key, and channel. A source admission cannot be reused
for output review. Each admitted reviewer must have a distinct Buzz public key,
and every accepted review must match an event signed by that reviewer's key.
Browser submission remains closed until browser key custody and the signing flow
are implemented. A rostered reviewer can download a schema-valid unsigned
record from the form, but only the Buzz command and validator can turn it into
an accepted review. The local files remain editable by an administrator, so
these signatures prove key authorization, not immutable governance.

The case authoring workshop is served at `/benchmark/case-authoring`. It lists
all drafts and opens only drafts that cleared source review. For an eligible
draft, it derives the authoring material from the signed reviews and locks the
agreed question, claims, citations, source hashes, excerpt hashes, answer
policy, and review IDs. A rostered domain case owner can download an unsigned
approval for development or calibration. The browser cannot sign the approval,
record it in the approval ledger, register the case, or store a sealed answer.

The existing synthetic calculation benchmark remains an engineering regression
set. Its expected answers have not received domain owner approval, so it does
not count toward the 120 labeled first pass cases.

### Real SEC discussion run, 2026-08-15

The acquired Zendesk DEFM14A was opened through the same local folder, parser,
Buzz, LM Studio, and browser path used by the product. It contains one source,
189,335 estimated tokens, 2,178 anchors, 447 tables, and no parser warning. The
source hash matches `evidence/candidate-source-zendesk_2022.json`.

The run preserved its failures. A broad question returned an incorrect “not
disclosed” price, and the first multi-part repair also failed. The corrected
retriever detects each requested part and admits a qualifying passage for the
consideration, stockholder approval, regulatory approval, and financing
condition. The publication guard requires a same-line citation for each part.
It rejects numbers and material words that do not occur in the cited passage.
One bounded model repair is available, but the saved live answer passed on its
first call.

The four-part answer is stored as signed Buzz event
`168d8eee8eed77fd8599f9fd77d25ca217c742e4998a835f148150d3596fa297`
and trace `trc_93e38e2a88c7`. A 21-assertion browser replay opens that event at
the canonical Discussion URL, verifies its raw NIP-01 event identity and
BIP-340 signature, restores the trace in a newer Prism process, checks all four
source hashes and citations, hides the machine trace marker, renders human
labels, and follows the financing citation to `html:block:00122`. It also
verifies the current canvas and records zero console, request, or HTTP errors.
The evidence is in
`evidence/browser-real-deal-zendesk-v1.json` and its hashed screenshot.

Zendesk remains an acquired, parser-verified candidate. It is not a registered
case, has no domain-approved expected answer, and does not change the current
5-case, 3-deal benchmark inventory. The structural publication pass does not
create an accuracy release.

### Live surface smoke run, 2026-08-14

The v0 surface ran one real local first pass on the four-file Project Titan
room using LM Studio model `27b@q1_0`. The call took 80.5 seconds, used 4,267
tokens, returned eight admitted citation anchors, and created separate signed
Buzz request and draft events. A cold server restart restored the draft and
its citation anchors from Buzz history.

The output remains an unapproved draft. Review found a material time-series
label error: it paired the 2030 EBITDA value of 512.3 with the 2028 model year.
This failure passed the structural and citation-presence checks. It proves that
citation presence is not claim support and that semantic relation checking and
human correction counts are release gates. The shared Buzz canvas was not
updated, and the web review form does not preselect the model's recommendation.

On 2026-08-15, the same failure was promoted into a deterministic
table-relation guard. A new live run invoked `27b@q1_0` twice: the original
draft and one bounded repair. Both paired 512.3 with `2028E_LBO_Y3` instead of
375.8 and paired 76.0% with that year instead of 75.0%. Prism rejected the run
before publishing a new Buzz draft. The failed trace `trc_cdc68b06b550`
records 9,937 tokens, 109.4 seconds, zero reasoning tokens, and both exact
discrepancies. The trace was restored through `/api/evals` after a distinct
server restart. The earlier pre-guard draft remains visible as failure history
but is marked `legacy_unverified` and cannot be promoted to the reviewed
canvas.

Two later live runs demonstrated why guard versions are part of the acceptance
contract. The v1 draft passed year/value checks but used malformed citation
markup, asserted an approval without supporting text, and stated 22.0% growth
for 418.0 to 520.0. The v2 draft corrected citation syntax but invented gross
and net leverage calculations using exit EBITDA and a negative denominator.
Neither draft received domain review. Incrementing the guard version made both
Buzz events `legacy_unverified` and disabled review.

The current v3 run used explicit role labels for the repair turn because LM
Studio returned no `response_id` while local response storage was disabled.
After one repair, Prism still found the wrong 22.0% growth, one uncited numeric
claim, and leverage calculations of 7.20x and 6.00x whose stated operands imply
6.39x and 1.91x. Prism rejected the run before publishing a new draft. Trace
`trc_8c996bb91fba` preserves the four exact defects. This is a verified product
failure path, not a passing Titan benchmark or a Bonsai accuracy claim.

On 2026-08-15, a later live request tested the investment screen as an
operative retrieval input. It asked specifically about the reported ECF sweep
schedule versus Section 2.02. Prism reserved three matching passages and bound
the run to source snapshot
`b1041d999b205faa538d03ee5a93b8f22ae95de0db3a68e44550833f6f47bbb1`.
The first run exposed a heading-only Section 2.02 citation. Retrieval now
inherits the section label into the child provision and cites
`node:node_para_3`, which contains the 50%, 25%, and 0% ECF thresholds. In the
repeated live run Bonsai still left one numeric factual claim uncited after
repair, so trace `trc_0392d4ebbea0` failed and none of its prose was published.
Prism published a separate signed evidence fallback as trace
`trc_36492fa2799f`. The saved record is
`evidence/bonsai-first-pass-titan-screen-bound-v1.json`. This is a screen-bound
product and failure-path result, not a model or accuracy pass.

Guard v4 adds a named-target support check and removes filename-only root nodes
from the admitted retrieval set. It is a new contract version because changing
guard semantics without changing the marker would make old Buzz drafts appear
newer than the checks they actually passed.

The definitive v4 live run invoked `27b@q1_0` for an original answer and one
repair. It was rejected before draft publication because a numeric factual
claim remained uncited and the named target was still not supported by the
cited passage. Trace `trc_deb005c32d88` records 10,024 tokens and 178.6 seconds.
This narrower failure is progress in error analysis, not a passing benchmark.

The product now has a separately scored evidence-safe fallback for this case.
It is not a benchmark repair and cannot count as a Bonsai pass. The renderer
uses only admitted source excerpts, assigns a conservative system `PAUSE`, and
records its own trace linked to the rejected model trace. A human can review
and promote that artifact to the Buzz canvas without changing the model's
failed `first_pass_acceptance` evaluation. This preserves user value and
failure evidence at the same time.

Subsequent failure-path QA found two implementation defects in the evidence
surface. Markdown paragraph IDs were reused inside each section, so a valid
citation could resolve to the wrong paragraph. The parser now assigns document-
global paragraph IDs and the workspace exposes a bounded exact-node preview.
The model also places citations inline, while the first renderer made only
standalone citation lines interactive. The renderer now turns every inline
citation into the same canonical source control.

Guard v7 scopes year/value checks to the named metric clause and recognizes the
natural label `Revenue Growth` as the source row `Revenue_YoY_Growth`. This
removed two false-positive rejection modes without relaxing value checking. A
new live Titan run invoked `27b@q1_0`, detected an initial 22.0% growth error,
sent one bounded correction turn, and accepted the repaired 24.4% statement.
Trace `trc_c16aa77253ce` records 8,640 tokens, 96.2 seconds, five admitted
citations, and no human score. Browser QA opened
`01_Confidential_Information_Memorandum.md#node:node_para_2` at the exact cited
CloudScale passage and showed the accepted trace beside the separately rejected
model and fallback traces.

The restart check also found a provenance defect. The latest matching Buzz
marker could replace the event named by the trace, even when a person or a
later copied event published the marker. Prism now accepts only the configured
agent event that matches one persisted trace on event ID, room, model, guard
version, artifact mode, citation count, and response text. The accepted v7
trace names event
`5f66ef5717fc76af3304768f47800302b7e041449b8805803a4a3f2e47bb1b8b`.
A later copied event remains in Buzz history and cannot become the active
draft. The saved product and browser records use the original event ID.

The v7 draft is still not a release result. Manual audit found that “the
disclosed leverage ratio is not explicitly stated” is ambiguous after the same
brief reports a 7.20x gross leverage multiple. A domain reviewer must decide
whether this is a major correction and whether the intended statement about
the Total Net Leverage Ratio is useful. One guard-accepted case cannot satisfy
the 120-case benchmark or the human acceptance thresholds.

The local operator review path has a separate restart record. Prism published
a `PAUSE` durability smoke review for the Anaplan evidence fallback, restarted
the server, and restored the exact signed review and canvas events through the
persisted trace. The smoke review leaves usefulness false and does not claim
domain review or accuracy. See
`evidence/operator-review-restart-anaplan-v1.json`.

### Public dossier first-pass development breadth, 2026-08-15

The three public dossiers were then run through the complete first-pass product
path rather than the narrower question-answer chat path. Corpus v1 exposed a
room-boundary defect: Microsoft/Activision was opened at the corpus root and its
fallback retrieved Anaplan and Citrix evidence. That artifact was invalidated.
Corpus v2 isolates the CMA PDF in its own room, and a deterministic source-scope
gate rejects missing or cross-deal files before inference.

The clean v2 rerun produced trace-linked evidence fallbacks for Anaplan, Citrix,
and Microsoft/Activision. All three underlying `27b@q1_0` drafts failed the v7
guard; none counts as a model pass. The product-path artifact records all signed
Buzz events, rejected-model trace IDs, fallback trace IDs, citations, manifest
hashes, and zero source writes. It explicitly records no domain review and no
accuracy release. See
`evidence/bonsai-first-pass-public-development-v1.json`.

## Required records

The benchmark directory contains these versioned contracts:

- `case.schema.json` defines a labeled benchmark case.
- `run_record.schema.json` defines one model and product result.
- `rubric.v1.json` defines the dimensions, severity, and gates.
- `benchmark_manifest.v2.json` defines the target, current inventory, and
  approval state.
- `development_registry.v2.json` registers the five inspected public cases in
  the case schema.
- `benchmark_manifest.v1.json` and `development_cases.v1.json` remain fixed as
  inputs to the saved three deal run.
- `evidence/first-pass-benchmark-contract-v2.json` records the current
  structural pass and release failures.
- `evidence/first-pass-development-evaluation-v2.json` records deterministic
  development checks, verified signed product delivery, and the unverified
  semantic dimensions.
- `evidence/public-deal-buzz-event-verification.json` restores and verifies the
  five raw owner-question and agent-answer event pairs against the execution
  prompts and saved responses.
- `human_review_submission.schema.json` defines a complete blinded review.
- `evidence/first-pass-human-review-packet-v2.json` is the current model blind
  packet for the five development cases.
- `candidate_question_drafts.v1.json` is the unregistered 319-question review
  queue for the 29 acquired candidates.
- `candidate_source_review_submission.schema.json` defines a qualified,
  source-bound reviewer submission.
- `candidate_source_adjudication.schema.json` defines distinct-principal
  resolution of reviewer disagreements.
- `candidate_case_approval.schema.json` defines the signed domain-owner
  boundary between affirmative source review and later case registration.
- `candidate_case_approval_records.v1.json` and
  `candidate_case_registrations.v1.json` are atomic, initially empty, hash
  chained local ledgers. Each entry binds its append sequence and predecessor.
  Content-addressed source and review artifacts do not count unless the
  registration ledger references them. The chains detect inconsistent local
  history, but they are not externally anchored or immutable.
- `source_reviewer_roster.schema.json` and `source_reviewer_roster.v1.json`
  define the domain-owner-managed reviewer identities. The current roster is
  empty.
- `evidence/candidate-source-review-packet-v1.json` is the current model-blind
  source review packet.
- `evidence/candidate-source-review-validation-v1.json` records the honest
  zero-submission state and keeps promotion closed.

## References

- PrismML company and team: https://prismml.com/about
- PrismML Bonsai tools and runtime support: https://github.com/PrismML-Eng/Bonsai-demo
- Madhavan Ramanujam on AI pricing and paid proofs of concept: https://podcast.nfx.com/episodes/pricing-madhavan-ramanujam
- Madhavan Ramanujam and Georg Tacke, `Monetizing Innovation`
- Local Bonsai judge report: `/Users/jaibhagat/Documents/Codex/2026-08-14/read/outputs/bonsai-arize-judge/FINAL_REPORT.md`
- Local activation profile: `/Users/jaibhagat/Documents/Codex/2026-08-14/read/outputs/bonsai-arize-judge/profiling/PROFILE.md`
