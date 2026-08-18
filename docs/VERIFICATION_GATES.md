# Prism Vault Verification Gates

## Current demo completion rule

The active goal is the customer demo in
[`DEMO_INFORMATION_ARCHITECTURE.md`](./DEMO_INFORMATION_ARCHITECTURE.md).
Accuracy certification and commercial proof do not gate the current demo.
Sections that describe those programs remain historical controls and must not
be used to report the current demo as incomplete.

The current demo requires a working local room, the three main page views, a
source linked brief, citation navigation, team activity, a stable room link,
responsive layout, keyboard use, and plain error states.

This document turns the postmortem into release controls. A milestone is done
only when its claim is falsifiable, its evidence is reproducible, and its known
boundary is visible in the same interface that presents the result.

## Evidence taxonomy

Every product claim must be labeled as exactly one of:

1. **Researched** — supported by a cited external or internal research source.
2. **Projected** — calculated from stated assumptions, but not measured.
3. **Configured** — credentials/endpoint/artifact are present, but invocation is not proven.
4. **Invoked** — a trace proves which runtime handled a specific request.
5. **Measured** — a versioned benchmark artifact records dataset, runtime, result, and failures.

“Production ready,” “air-gapped,” “zero egress,” and benchmark scores are
prohibited unless a purpose-built acceptance test proves the complete claim.

## The anti-facade rule

An evaluator must consume every input named by its claim. A check cannot report
source grounding if it only inspects the response or expected answer. Exact
string overlap must be labelled as lexical reproduction, and its record must
state that semantic faithfulness and accuracy are unmeasured. A negative
control must repeat a claim in the response while omitting it from the source,
and the check must fail.

An evaluator cannot accept a caller supplied pass count as proof that it
checked an artifact. A table check must read the extracted cells and compare
each registered coordinate and value. The metric must be called a fixture
match unless an independent labeled corpus supports an extraction accuracy
claim. A phrase denylist must be called a denylist check. It cannot be called
hallucination detection.

A calculation case cannot count because its schema contains a formula field.
The evaluator must bind every named input to a reviewed claim, confirm the input
value occurs in that claim, execute only the bounded arithmetic language, and
recompute the registered result within tolerance. The output must show the
inputs, formula, result, and unit together in one calculation block. Missing any one of these is a deterministic
failure. This check proves reproducibility of the registered arithmetic, not
that the economic method is the right one.

A schema gate must reject any assertion keyword that the local validator does
not implement. The required controls change fixed values, cross strict numeric
bounds, omit timestamp offsets, and use `oneOf` to try to bypass a sibling
requirement. Each control must fail. The gate claims only the supported JSON
Schema subset used by the checked in contracts.

Recognizing a keyword is not enough. The schema definition check must also
reject an unsupported dialect, format, type, constraint value form, or local
reference. A schema under `additionalProperties` must validate every undeclared
field. Pattern matching must use JSON Schema search semantics.
JSON value equality must not let `true` satisfy a numeric constant, and
nonfinite Python numbers must fail before bounds are evaluated. Equal numeric
values such as `1` and `1.0` count as duplicates under `uniqueItems`.

A failed verification attempt cannot replace the last known good canonical
record. The failed attempt must remain available under a separate path, and a
later valid run must still validate its exact saved bytes before it can replace
the canonical record. Component tests must use controlled fixtures instead of
assuming that a mutable production evidence file is valid.

A composite record must not hash a mutable report that routine checks overwrite.
The recorder must create a record specific snapshot for each dependent result,
and it must bind that snapshot by hash. A later routine check can update its own
report without invalidating the earlier composite record.

A signed trace checkpoint must bind the exact ledger format, entry count, and
head hash in the signed event payload. The verifier must restore the raw event,
check its NIP-01 identity and BIP-340 signature, signer, channel, and content,
then prove the head exists at the recorded ledger sequence. A later append may
preserve the anchored prefix while making the current head unanchored. A Buzz
relay on the same host is a signed checkpoint, not an external trust domain or
immutable audit service.

A normal local verification passes only when its committed cold restart record
passes. The candidate generated inside the restart recorder may mark that check
as pending because the enclosing record has not been written yet. No other
local report may treat a failed cold restart section as success.

A required field check cannot be called schema compliance. A typed check must
read each value and reject a wrong type. The result must state whether it checks
only top level JSON types or a complete JSON Schema. Empty schemas cannot pass.

Trace state must distinguish a failed check from a check that was never run.
An explicit guard failure is `rejected`. Missing evidence is `unverified`.
Pending human work is `awaiting_review`. A user must not see `Guard rejected`
when the record only says that a property was not measured.

Every acceptance criterion must name four things:

1. **Claim** — one narrow sentence that can be false.
2. **Artifact** — the saved input, output, trace, or measurement.
3. **Adversarial check** — a mutation, negative control, missing dependency, or
   boundary escape that must produce the expected failure.
4. **Decision** — an automatic pass/fail or a named human approver. Ambiguous or
   unavailable evidence is `UNVERIFIED`, never a pass.

Mocks prove an interface contract only. They cannot prove model quality,
hardware performance, network isolation, browser behavior, or domain accuracy.
The evaluator must be independent of the implementation: expected deal values
live in versioned benchmark data, and a deliberately wrong expected value must
make the suite fail.

A restored first pass needs one exact evidence chain. The Buzz event must have
a valid Nostr signature from the configured agent key. Its event ID must match
the draft event ID in one persisted trace. The same trace must match the room,
model, guard version, artifact mode, citation count, and full response text.
It must also match the server-derived room classification, canonical provenance
binding hash, and complete folder snapshot in both the signed marker and trace.
Restoration recomputes the current classification and folder snapshot. A later
source change, public-corpus integrity failure, or copied artifact fails closed.
Prism ignores copied markers, human signed markers, ambiguous trace matches,
and events whose labels match while their payload does not. Older events remain
in Buzz history, but they cannot replace the active draft unless they pass all
of these checks.

A restored artifact must also resolve against the current parser inventory.
The inventory binds each citation to its source hash and includes a digest of
the current searchable text. Duplicate citation identities fail closed. The
surface must show the parsed inventory and the passages admitted to the model.
It must state that this is not a measure of semantic coverage and does not prove
full document review.

The canonical product verifier also emits `goal_completion`. The current
decision covers the customer demo contract. It requires the scope decision,
the ideal page structure, the local Bonsai deal room, the current customer
surface, the source and team path, a defended content graph, and a fresh browser
record. Missing evidence fails closed.

The browser record must load the current asset version. It must verify the
Project Titan decision status, the four primary views, the specific decision
question, four grouped priority files, exact source navigation, the Activity
and Evaluation routes, and the secondary views inside Room details. It must
also check 390, 768, and 1440 pixel widths and record no console, request, or
HTTP errors.

Benchmark accuracy, pricing proof, and production hardening remain separate
programs. Their records stay in the broad product report, but their state does
not raise or lower the current customer demo decision.

The stated investment screen is an operative retrieval input, not prompt-only
decoration. Screen-matched passages reserve bounded context slots even when
generic transaction passages score higher. The first pass also binds the
folder preview hash before inference and checks it again before any model or
fallback draft is published. Prism checks the same binding again after Buzz
restores the signed event. A changed or unavailable source records a failed
trace and returns `source_changed_during_first_pass`. The signed candidate stays
in Buzz history, but it has no accepted trace and cannot restore as a draft.
The discussion view replaces such a candidate with a quarantine notice.

Chat publication uses the same boundary. It snapshots the complete room and
computes its provenance binding before inference, checks both again before the
agent event is signed, and checks both once more after Buzz restores the signed
event. The marker, trace, and API response record the three values. If either
changes during publication, Prism records the candidate as orphaned and
publishes a signed rejection. The discussion view shows the rejection and
quarantines the orphaned candidate. Historical unbound evidence can still be
inspected through raw Buzz evidence, but the workspace does not present it as
an accepted answer.

Chat restoration applies the same current inventory check to every retrieved
anchor in the trace. A missing citation, changed source hash, or duplicate
parser citation prevents acceptance. Browser verification must observe the
scope disclosure on the signed answer.

Failure localization must not infer model quality from a schema placeholder.
For answer cases, the oracle-context diagnostic supplies only the registered
passages, saves the raw prompt and response, and recomputes literal citation and
number checks. A normal pass followed by an oracle failure is recorded as a
regression. A normal failure repaired under oracle context is only a
context-sensitive deterministic result. Neither result proves retrieval fault,
semantic accuracy, or usefulness. An answer-absence case remains ineligible
unless a whole-corpus absence audit exists. The Citrix development case now has a
bounded whole-folder audit. It verifies both registered source files and scans
all 2,401 admitted nodes against three disclosed direct-disclosure patterns.
It also verifies three confusable source anchors. The current audit found zero
direct matches, but the patterns were written after the team inspected the
development corpus. The scan does not prove the absence of an unregistered
synonym or a domain expert's conclusion. Bonsai produced both required absence
phrases under this context but omitted the citation, so the deterministic case
still failed.

A local operator review must also survive a Prism restart. The persisted trace
names the review message and the canvas event. Prism restores both raw events
from Buzz, verifies both signatures, and compares the reviewer key and every
decision field. Prism also compares the draft identity and full canvas text. A
mismatch makes the first pass endpoint unavailable, so Prism does not fall back
to process memory or show the draft as unreviewed.

Review publication spans Buzz message storage, Buzz canvas storage, and the
local trace store. These writes are not a distributed transaction. A signed
review canvas is therefore not a commit by itself. The digest endpoint presents
it only when the exact canvas event, exact review message, and persisted trace
restore as one review chain. An interrupted publication returns an explicit
uncommitted-canvas error instead of showing the orphaned canvas as reviewed.

The saved live restart record is
`evidence/operator-review-restart-anaplan-v1.json`. It uses a public Anaplan
development fallback and keeps usefulness, domain review, and accuracy release
false. The record proves decision durability only.

## Goal-cycle milestone ladder

Milestones are sequential. Later work can be prototyped, but no later milestone
can be presented as achieved while an earlier required gate is open.

### M0 — Truthful baseline and build/buy decision

Exit criteria:

- ADR 0001 is accepted: adopt an existing local serving runtime; build the
  workload, policy, provenance, and evaluation layers.
- Every runtime surface distinguishes target architecture, configured
  capability, invocation, and measurement.
- The prohibited-claim scan and component suite pass from a clean checkout.

### M1 — Reproducible private-folder baseline

Exit criteria:

- A caller can select an arbitrary readable folder without copying it into a
  product-specific catalog.
- The browser shows a hash-bound supported-file inventory and parser warnings
  before room creation. Preview performs no Buzz or registry write. Missing or
  stale preview hashes fail before creation.
- Supported source cells survive ingestion exactly, filenames are cited, and
  symlinks/oversize/unsupported files fail visibly.
- Nested directories are either indexed or explicitly warned. They cannot
  disappear while the surface implies the complete tree was ingested.
- Mutating a source value changes the answer; removing a required source makes
  the reviewed workflow refuse to conclude.
- The versioned baseline benchmark is 100% passing, including a negative
  control that proves the evaluator can fail.

The XLSX portion uses `benchmarks/xlsx_display_fidelity.v1.json`. Expected raw
values, display values, formats, and formula states are preregistered outside
the parser. The harness builds a workbook from inputs only, parses it through
the product path, and compares the result with those expectations. A mutation
of the expected percent display must fail only that case. This establishes the
declared bounded parser contract. It is not an Excel or LibreOffice execution
oracle and does not establish full spreadsheet parity.

### M2 — Real Bonsai 27B invocation

Exit criteria:

- The exact weight artifact, checksum, quantization, serving-runtime version,
  model identifier, hardware, and command/config are saved with the run.
- The standalone deployment record hashes every artifact used by the active
  backend and the verifier recomputes those hashes from the current files.
  Process arguments are reduced to an allowlist so credentials cannot enter the
  evidence record. The allowlist includes the process bind host and port.
- A trace shows the local endpoint actually returned the response; no mock or
  deterministic fallback is allowed in this artifact.
- The model completes every benchmark case without provider or sandbox errors.
- The scorer binds important values to their labels and units. It rejects
  unrelated conclusions, invented policies, unsupported legal claims, and
  wrong source-policy tiers.
- Generated scripts cross a reviewed task boundary only after a recorded repair
  succeeds. A second violation fails closed before execution.
- A cold restart reproduces the exact current dataset hash. Historical restart
  evidence for an older benchmark version does not satisfy this gate. Missing
  weights or endpoint makes this milestone fail closed as `NOT CONFIGURED`.

### M3 — Coding-agent reliability

Exit criteria:

- A versioned coding task set covers generation, edit, test, tool use, unsafe
  code, timeout, and unsupported-request behavior.
- At least one hidden or held-out mutation exists for each critical workflow.

- Syntax success, test pass rate, sandbox pass/fail, grounded-source rate, and
  task success are recorded separately; a composite score cannot hide a zero in
  a critical safety metric.
- No unsafe execution is reported as a successful answer.

### Product responsiveness during inference

The prototype HTTP listener must serve status, files, and collaboration reads
while a local model request is in flight. A real model request and concurrent
status probes must be saved together with the signed question and answer event
IDs and the accepted trace. The registered prototype threshold is 2,000 ms per
status probe. The trace store must also survive twelve concurrent local-process
writers without lost, duplicate, or invalid JSONL records. Creations and review
updates must be hash chained; a content edit, reordered entry, or internal
deletion must fail load; conflicting reviews must fail closed; and a failed
append must preserve prior bytes. The local chain is not signed or externally
anchored, so it is not an immutable audit ledger. This is not a load test or
production SLO.

A failed server bind must occur before the production trace store is opened.
The occupied-port control must leave a configured trace path and its lock file
absent. Verification fixtures may never silently count as product traces. If a
fixture contaminates durable history, it remains in the chain, receives an
explicit correction event, and is excluded from aggregate metrics rather than
being deleted.

The threaded prototype must serialize each local registry transaction.
Concurrent requests for one new room must create one Buzz channel. Concurrent
registrations for distinct folders and channels must persist every record
without temporary file collisions. Both registries must survive twelve
competing local processes by using mode-0600 advisory file locks, rereading
under the lock, and syncing atomic replacements. A live process must reload a
registry replaced by another process. Identity drift or a failed replacement
must preserve the prior canonical bytes. Remote Buzz creation plus both local
registries are not one distributed transaction.

### M4 — Deal-room accuracy and domain review

Exit criteria:

- Dataset cases include expected values, tolerances, required citations,
  forbidden claims, and source-document versions.
- Baseline, Bonsai-local, and approved cloud runs are separate versioned,
  content-hashed JSON artifacts with per-case traces. An editable JSON file is
  never described as immutable.
- A deal-domain owner signs off expected answers and adjudicates failures.
- Two signed human reviews produce one hash bound resolved label set. A
  distinct signed principal adjudication resolves every disagreement.
- Judge calibration covers at least 20 calibration cases across five deals and
  passes every threshold in the versioned rubric. Missing labels, parse
  failures, and answer order changes fail the gate.
- Release thresholds are set before the scored run. For the initial pilot:
  critical numerical accuracy and citation grounding must both be 100%; other
  quality metrics must meet their pre-registered thresholds.

The release benchmark is the first pass underwriting contract in
[`FIRST_PASS_UNDERWRITING_BENCHMARK.md`](./FIRST_PASS_UNDERWRITING_BENCHMARK.md).
Its machine readable manifest, rubric, schemas, and development inventory are
under [`benchmarks/first_pass`](../benchmarks/first_pass). The five current
public dossier cases remain development data because the team has inspected
their failures.

Every saved development answer must also carry the current public room
classification, provenance hash, and complete folder snapshot. The delivery
record must contain the raw signed question and answer events and the persisted
trace. The marker, trace metadata, room, question, visible answer, model, event
IDs, provenance hash, and folder snapshot must agree. An older answer without
these fields cannot pass the current development delivery gate. These checks
prove source identity and delivery history. They do not prove that an answer is
correct or useful.

Before a sourced question can enter that registry, it passes a separate
authoring gate. A reproducible packet hides retrieval rank and model identity,
binds every option to the filing hash, and requires agreement from two distinct
qualified source reviewers on a domain owner managed roster. A qualification
typed into a form does not satisfy this requirement. The roster authority must
first be configured with an identity, Buzz public key, and private channel after
an out of band identity check. Prism records the check but does not prove it.
Every roster entry must match a relay-restored event signed by that configured
authority key. The signed content binds the roster scope and full reviewer
record. A source reviewer approval cannot authorize an output reviewer.
Both roster files must contain the same authority object. An interrupted
configuration that changes only one file closes all roster reads and reviewer
admissions. Repeating the same configuration repairs the pair. A different key
cannot repair or replace it.
The authority replacement check also runs inside the roster lock. A setup
process cannot overwrite a different authority that commits after its initial
read.
Disagreement requires a rostered, distinct principal. Roster entries must use
distinct Buzz public keys, and each review or adjudication must match a
relay-restored event signed by the corresponding key. Passing this gate means
only that a draft is eligible for case authoring; it does not
create a label, split, approval, benchmark case, or accuracy claim.

Case authoring has a second signed boundary. The embedded case must exactly
retain the affirmative reviewed decision and source bindings, and a separately
rostered `domain_case_owner` must sign it through Buzz. Matching or adjudicated
rejections never become eligible. A valid case approval still does not mutate
the benchmark registry. Prism first records the exact signed approval chain in
a hash chained local ledger using one atomic file replacement. Registration then
replays that recorded bundle and makes a separate atomic benchmark membership
commit. An approval cannot
skip the recorded state, and a recorded approval does not count as a registered
case.

Approval and registration writers must take an advisory file lock, reread the
latest ledger under that lock, check duplicates, and sync the replacement before
releasing the lock. A separate process test must preserve every update from 12
competing Python processes. The lock coordinates Prism writers on one local
filesystem. Each append must bind its sequence and prior entry hash, and the
saved count and head must reject deletion or reorder controls. This is not a
distributed lock, an external anchor, or immutable storage. A local
administrator can still rewrite the complete chain.

The browser exposes the two boundaries at `/benchmark/source-review` and
`/benchmark/case-authoring`. The authoring page opens only an eligible draft,
locks the reviewed source contract, and exports an unsigned owner record. The
browser cannot sign, record, register, or release a case. Separate rendered
browser checks bind both pages to the current review and benchmark state.

The first public dossier run uses
`benchmarks/public_deal_corpus_manifest.json` and
`benchmarks/public_deal_battletest.json`. The benchmark is registered before
the model run. A changed question, answer, source hash, citation anchor, or
threshold creates a new benchmark version.

The public dossier gate has four decisions:

1. The corpus gate passes only when every downloaded file matches its saved
   SHA-256 hash and byte count.
2. The ingestion gate passes only when the parser admits every file and finds
   every saved HTML anchor or PDF page.
3. The answer gate passes only when every critical number and citation is
   correct. A question whose answer is absent passes only when the model says
   the answer is absent.
4. The product gate passes only when the same run works through the Buzz room
   and the web page without a source folder write. The restored draft must also
   pass the configured agent, event ID, room, model, guard, mode, citation, and
   response checks against one persisted trace.

The files are public deal dossiers. They are not copies of the private virtual
data rooms used by the deal teams. A result must not claim that a public filing
contains private customer files, quality of earnings work, or the original
bank model unless the source contains that material.

### M5 — Hybrid AI policy evidence

Exit criteria:

- Local, cloud, and deterministic execution are identifiable in every trace by
  provider and returned model ID.
- The local provider configuration and provider constructor reject every URL
  except plain HTTP with an IPv4 loopback address or the exact IPv6 `::1`
  address. DNS names, private network addresses, and ambiguous URL forms fail.
- Cloud selection requires an explicit runtime request and a short-lived,
  request-bound policy event restored from the configured Buzz channel.
  Sending folder contents requires a second restored event from a distinct
  data-owner key. Missing, unpublished, changed, expired, or replayed events
  fail before provider invocation.
- PII/redaction tests include positive and negative controls.
- A network/DLP control is required before claiming enforced zero egress. Until
  then the product says only `local-only policy`.

### M6 — Evangelism release

Exit criteria:

- A repeatable browser check opens the saved first pass, follows a citation to
  the exact source passage, and checks the trace, model status, and review
  control.
- The saved browser record includes the browser version and a screenshot hash.
  Browser console errors, failed requests, HTTP errors, and missing assertions
  make the check fail.
- A second browser record uses a parser-verified public filing, opens the signed
  Buzz answer event at its canonical discussion URL, and follows an answer
  citation to the exact local source block. For a multi-part question, every
  detected part needs qualifying retrieved evidence and a same-line citation.
  Claimed numbers and material terms must appear in the cited passage. The
  debt-structure path must admit the Sources of Funds table, include every
  disclosed debt instrument, and keep equity rows out. Citation filenames and
  anchors are formatting metadata and must not be scored as model claims. The
  browser record must prove the trace and answer event binding survives a Prism
  restart, the machine marker stays out of the human view, and Prism independently
  verified the raw event identity, signature, channel, and payload. It must apply
  the same proof to the current shared canvas. These deterministic checks do not
  prove semantic entailment or domain accuracy.
- A separate Titan debt browser record binds the current source hash, exact
  Sources of Funds anchor, accepted question and answer events, prior rejected
  attempt, both traces, and screenshot hash. It must restore after a Prism
  restart and navigate the visible citation to the exact debt table. Its
  accuracy release remains false until domain review and benchmark registration.
- The launcher fails if its explicitly requested loopback port is occupied. It
  does not increment to an alternate port. Before printing the canonical URL,
  `/api/status` must report the exact child process PID and a ready Buzz
  workspace. A response from an older Prism process is a failed startup.
- The Buzz Compose port must publish `3030` only on host IPv4 loopback. A bare
  host port, `0.0.0.0`, or an IPv6 all-interface listener fails the local demo
  boundary. Loopback publication is still not zero-egress or tenant isolation.
- Identical concurrent message reads for one Buzz channel, limit, and cursor
  execute one relay read and one raw-signature verification pass. Every waiter
  receives an independent copy of the verified result. A shared failure reaches
  every waiter, and the next request retries Buzz. Completed message lists are
  never cached. A browser timing control delays one response beyond the polling
  interval and must observe no overlapping message request plus one queued
  follow-up refresh. The same control must prove that a hidden tab suppresses
  its interval poll and becoming visible triggers one refresh.
- An accessibility browser record must use the same signed public filing event.
  It checks semantic tab state, keyboard tab and citation navigation, visible
  focus, dialog focus restoration, reduced motion, target size, and mobile
  width. Failed assertions, browser errors, HTTP errors, or a changed event ID
  make the check fail. The record must say that it is an automated smoke check,
  not WCAG conformance or assistive technology review.
- A cross browser record must replay the same signed answer and exact citation
  in Firefox and WebKit. Each engine must save its version, screenshot hash,
  assertions, browser errors, request failures, and HTTP errors. WebKit does
  not count as a Safari application test. Branded Chrome, Edge, and browser
  extensions remain separate checks.
- A local operator review can be restored after clearing process memory. The
  restored state must match its signed Buzz review message, signed canvas, and
  persisted trace. A changed event or trace field must fail the review read.
- The demo, PRD, RFC, README, and benchmark card all link to the same saved
  artifacts and use the evidence taxonomy consistently.
- Every performance or quality statement identifies the exact Bonsai artifact,
  workload version, hardware, run date, sample count, and limitations.
- The live deployment card must rehash the model artifacts after their device,
  inode, size, modification time, or change time differs. A warm cache must not
  keep reporting a changed artifact as verified. Concurrent cold status reads
  must share one hash verification instead of hashing the artifact set in
  parallel.
- The deployment card must also find exactly one active llama-server using the
  measured weights and projection. Its executable bundle, runtime version,
  fitted context, parallel slots, cache types, flash attention, and load mode
  must match the saved record. The bind host must be `127.0.0.1`, and the current
  bind port must match the saved record. Missing, duplicate, exposed, or drifted
  processes fail the deployment identity even when file hashes pass. A matching
  loopback address does not prove zero egress or an air gap.
- The Evidence page must classify each trace from its recorded evaluations.
  A failed publication guard is `Guard rejected`. A passed structural guard
  with an unfinished human or domain review is `Review pending`. A missing
  evaluation is `No evaluations`. The browser must prove that pending review
  is not shown as rejection or acceptance.
- Aggregate evaluation fields must be `null` when they have no measured
  samples. The trace summary must include a sample count for each aggregate.
  An empty trace set must not report zero quality or 100 percent local routing.
- A clean-machine operator can reproduce the demo using documented commands.
- A skeptical reviewer can trigger one expected failure (missing provider,
  wrong benchmark value, unsafe code, or denied cloud context) and see it fail
  visibly.

The current same-host preflight is evidence toward, but not completion of, the
clean-machine criterion. It requires Docker, Compose, installed Buzz tools, a
live Buzz relay, private identity-file permissions, the exact requested model
as a loaded LM Studio instance, and native reasoning-off support. Catalog
presence alone fails. It also rejects an ACP agent that exits before startup.
The record is `evidence/operator-preflight-current.json`; its measurement state
explicitly denies clean-machine reproduction, artifact identity, quality, and
zero-egress claims.

The local verifier also reads
`evidence/process-network-observation-v1.json`. The recorder samples the exact
Prism, Bionic, and Bonsai process trees during one bounded native Bonsai
request. The recorder first derives the result from an unlabeled record. It
then writes the derived label. The saved record fails validation if the label
is missing or differs from the parsed facts. The validator reparses the raw
`lsof` output. A wildcard listener, an invalid host, an external address, a
missing named process, or an unredacted API key makes the check fail. The
passing record found no nonloopback endpoint in the saved samples. Sampling can
miss brief connections and does not cover packets, DNS, Docker guest traffic,
or unrelated processes, so the zero egress and air gap completion gates remain
open.

## Gate 0 — Integrity baseline

Claim: every public surface tells the same truth about installed capabilities.

Acceptance criteria:

- `/api/status`, `prismctl status`, the web UI, and README distinguish the
  deterministic baseline from configured AI providers.
- Missing model weights never appear as a loaded or invoked model.
- Mathematical VRAM values are labeled projections.
- Unsupported security boundaries are named explicitly.
- A repository scan finds no present-tense claims for absent megakernels,
  Firecracker/gVisor/eBPF enforcement, or measured Bonsai benchmarks.

## Gate 1 — Private-folder ingestion

Claim: an operator can point Prism Vault at a readable private folder.

Acceptance criteria:

- CLI accepts an arbitrary folder path and fails clearly for missing folders.
- Supported files are parsed with filename provenance and deterministic counts.
- Nested sources keep stable relative identities through preview, retrieval,
  citation, and source-change checks. Duplicate basenames cannot collapse.
- Recursion, file count, per-file size, aggregate admitted bytes, and symlink
  traversal have explicit fail-visible bounds shared by preview and retrieval.
- Table tests compare every extracted cell with the source CSV, not merely table dimensions.
- Unsupported/binary files are reported rather than presented as successfully parsed text.

## Gate 2 — Provider reality

Claim: Bonsai-local and cloud AI are real, separate provider paths.

Acceptance criteria:

- No endpoint means `NOT CONFIGURED`, never a simulated AI response.
- Mock tests prove both the OpenAI-compatible path and LM Studio native path.
- The native path uses the documented `system_prompt`, sets `store: false`,
  requests `reasoning: off`, and rejects responses without zero-reasoning stats.
- A configured local fitted context requires the exact model artifact path.
  Prism must find one matching llama.cpp process on loopback. Prism applies that
  process's chat template and tokenizer before inference, adds the registered
  runtime margin, reserves the output budget, and rejects an overflow before it
  sends a generation request.
- The live record must show that Bionic's reported input count did not exceed
  the admitted count. The admitted input and reserved output must fit within
  the measured 16,384 token context.
- A cloud provider double proves the separate adapter only after the HTTP or CLI
  path restores the exact request-bound approval events from Buzz. Negative
  controls prove unsigned, unpublished, changed, expired, and replayed events
  never reach the provider double.
- Provider ID, returned model ID, latency, usage, and error are recorded without secrets.
- AI-generated code must pass AST validation and subprocess execution or the task fails visibly.

## Gate 3 — Hybrid policy and recording

Claim: confidential deal-room work defaults local and cloud use is auditable.

Acceptance criteria:

- Confidential/default requests select local AI when configured, otherwise the honestly named baseline.
- Cloud is selected only when the caller explicitly requests it, the configured
  authority signs the exact request, and Prism restores that exact event from
  Buzz before atomic one-time consumption. Full context requires the distinct
  data-owner event.
- Redaction tests include PII matches and non-matches.
- Each trace records decision, provider, model, execution mode, and sandbox outcome.
- “Local” does not imply certified air-gap or measured zero egress.

Optional direct Buzz ACP has a separate source-boundary gate. One process may subscribe
to one exact room and channel only. Its source folder must resolve from the same
room binding. The local operator is the only accepted author and ACP memory is
disabled. If the agent exits while Prism is running, the launcher stops Prism
instead of leaving a workspace that appears agent-ready. Startup also rejects
an existing ACP process from the same checkout. These controls certify scope,
not response behavior. The generic responder remains experimental until a live
signed-reply test passes. Two responders with different folder scopes must
never share the same agent identity.
Stopping the experimental launcher must also remove its exact `buzz-acp`,
`buzz-agent`, and `buzz-dev-mcp` processes. A surviving child process fails the
lifecycle gate.

## Gate 4 — Reliability and accuracy benchmark

Claim: runtime quality can be compared on a stable deal-room workload.

Acceptance criteria:

- Benchmark cases are versioned data, separate from evaluator code.
- Expected and forbidden outputs are visible and reviewable.
- Report includes every case, failures, accuracy, pass rate, latency, runtime, and provider.
- Baseline, local Bonsai, and cloud runs produce separate artifacts.
- A model score is never shown without its saved artifact and exact model identifier.
- Adding a deliberately wrong answer makes at least one case fail (negative-control test).
- A real image-only PDF must contain no embedded text before parsing. The parser
  must preserve its physical page anchor, identify the OCR engine, and show the
  OCR limits in retrieval and the WebUI.
- Disabling OCR or exceeding the page limit must fail before OCR runs. A
  deliberately wrong OCR result must remain wrong, so the test cannot pass by
  reading a hidden expected answer.
- OCR engine confidence must never be reported as measured accuracy. The public
  engineering slice fixes the source bytes, page numbers, normalized expected
  text, 200 DPI image-only derivative contract, critical phrases, and thresholds
  before a run. The evaluator recomputes word error, character error, and exact
  phrase recall from raw OCR output. A wrong material number, expected-text
  drift, saved-score edit, or raw-output edit must fail.
- A ground-truth correction must preserve its prior benchmark and failed-record
  hashes, visual evidence, and whether thresholds changed. The current correction
  added visible logo text omitted from the PDF text layer and did not change a
  threshold. A later implementation record preserves the failed evidence and
  prior code hashes. The OCR raster changed from 200 to 300 DPI without adding
  document-specific words. The same pages were used to choose the change, so a
  passing rerun is development evidence and not an independent test.
- This three-page clean-raster result does not establish accuracy for natural
  customer scans, reading order, table extraction, or layout fidelity. Those
  need separate domain-labeled benchmark slices and independent approval before
  release claims.
- The first pass release requires all hard gates in
  `benchmarks/first_pass/rubric.v1.json`. A composite average cannot offset a
  critical unsupported claim, wrong number, failed answer absence case, or
  missing signed product result.

## Gate 5 — Sandbox boundary

Claim: generated calculations receive prototype process isolation.

Acceptance criteria:

- Tests reject filesystem, process, network, dynamic import, and dunder escape attempts.
- Infinite loops time out; memory/file-descriptor/file-size ceilings are exercised where portable.
- Successful calculations run in a child process.
- On the measured macOS host, a real operating system profile allows a write in
  the temporary run directory and rejects both a write outside that directory
  and a loopback socket bind. The profile also rejects a read from the project
  after the project is copied outside `/Users`, and each workflow trace shows a
  denied root that contains its selected deal room. Startup fails if the required
  profile runner is unavailable.
- Product surfaces say this is not a hardened multi-tenant boundary.

## Gate 6 — End-to-end product

Claim: the folder-to-result loop works across real boundaries.

Acceptance criteria:

- A live ephemeral HTTP server passes status, folder metadata, workflow, invalid JSON,
  missing prompt, unknown room, trace, and benchmark endpoint tests.
- Browser UI renders unavailable/configured/invoked states and backend errors.
- Browser UI labels room events as verified only after raw event signature and
  payload verification succeeds.
- Corrupt room registry state produces a visible dependency error and never
  becomes an empty or newly initialized registry.
- A clean checkout can reproduce tests and the baseline benchmark from documented commands.

## Gate 7 — Human benchmark governance

Claim: reviewed source material can become a benchmark case without an
engineering or model-generated label silently becoming ground truth.

Acceptance criteria:

- Source review, case approval, registration, output review, calibration, and
  sealed evaluation remain separate commits.
- Two rostered reviewers or a distinct principal adjudicator bind each source
  decision to raw signed Buzz events.
- Multi-document cases cite and register every admitted source hash.
- The browser cannot sign, approve, register, calibrate, or release a case.
- Synthetic fixtures are labeled as fixtures and never increase human approval
  or release inventory.

## Gate 8 — Paid pricing proof

Claim: the team can decide whether a buyer values and will pay for the certified
job without inferring demand from a public demo.

Acceptance criteria:

- The proof of concept is paid and has an identified workflow owner, economic
  buyer, budget authority, buyer effort, authorized access, and agreed success
  criteria.
- It uses two distinct authorized closed private deal rooms. The first permits
  setup and correction. The second measures transfer without case-specific
  changes.
- At least 80 percent of pilot deals are useful starting points, median first
  review time falls at least 30 percent, and the transfer deal has zero critical
  corrections and an accepted review.
- The buyer gives acceptable, expensive, and prohibitively expensive prices
  after use for one accepted first pass review.
- A paid next step or a concrete decline reason is recorded.
- A separately configured commercial authority must approve the buyer key after
  an out-of-band identity check. The authority and buyer keys must be distinct.
- Prism must restore the exact authority and buyer events from the configured
  Buzz channel every time it evaluates the POC. Independent NIP-01 and BIP-340
  verification must pass, and every signed event field must match the record.
- A configured authority proves control of its approval key. Prism does not
  prove the authority's or buyer's legal identity or employment.
- A signed event supplied only in JSON, a missing relay event, a changed relay
  event, a self-issued buyer key, or an event from another channel counts as
  zero buyer evidence.
- A structurally valid signed failure is recorded as a failure. Recording must
  not require the value gates to pass.
- Public filings, evaluator fixtures, and unsigned forms count as zero buyer
  evidence.
- The pricing record rejects a changed currency or value unit, a zero value
  where the contract requires a positive number, and a timestamp without a UTC
  offset.

## Gate 9 — Sealed test custody

Claim: sealed prompts and expected answers remain external until one approved,
frozen evaluation is ready to start.

Acceptance criteria:

- The checked in public inventory contains only identifiers, split metadata,
  snapshot hashes, slices, and secret case hashes. Secret-bearing fields fail
  schema and recursive leakage checks.
- Development, calibration, and near-duplicate deal families do not overlap the
  sealed inventory.
- Missing owner approvals, threshold approval, judge calibration, frozen-system
  evidence, or any changed binding returns before the secret loader is called.
- The first allowed contact creates an exclusive audit receipt before reading.
  Concurrent or repeated contact cannot invoke the loader again.
- A malformed or hash-mismatched external bundle is recorded as invalid and
  consumes that benchmark version. It cannot be repaired into a passing run.
- A controller unit test or synthetic bundle proves mechanics only. It never
  counts as sealed inventory, customer evidence, or model accuracy.

## Milestone rule

A gate can be marked complete only when all criteria have direct evidence. Passing
unit tests alone is insufficient for browser, network, hardware, model-quality, or
security claims. If a criterion cannot be tested in the current environment, its
state remains unverified and the product must display that limitation.
