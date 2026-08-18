# Implementation Status

Updated: 2026-08-18

## Current goal

The active goal is a customer demo that a new person can understand without an
explanation, plus a development evaluation of retrieval, generation, agent
workflows, and chat errors. The evaluation does not expand the primary product
navigation. Accuracy certification and commercial proof remain outside the
goal. Their implementation and evidence remain below as historical work, but
they do not control the current demo decision.

Accuracy certification and commercial proof are outside this goal.

The current room revision uses asset version `hybrid-eval-lab-v1`. A citation
opens an in place preview before the reader chooses
to ask about the passage or open the exact full source. The composer remains
available in Overview, Sources, Activity, and Evaluation. Markdown, CSV, and bounded JSON
previews use readable document structures. The current Project Titan records
pass 16 Chromium product checks, 21 Chromium accessibility checks, and 18
Firefox and WebKit checks.

The development evaluation is in `evidence/workspace-eval-v1.json`. Six mapped
retrieval questions pass their Recall at k thresholds, one saved Bonsai answer
passes separate deterministic grounding and relevance checks, and three saved
workflows pass. The release decision remains false because the chat sample has
zero human annotations, the generation set has one answer, and no blind cloud
or hybrid comparison has run.

The human error discovery surface is a native Prism room view and is browser
verified with synthetic data.
Five rapid fixture judgments persist across reload, and the fifth judgment
unlocks the depth phase. The replay verifies corpus coverage, separate agent
suggestions, breadth expansion, mobile width, and hash only telemetry. The
canonical review ledger still has zero human annotations.

The local Phoenix collector accepted one marked synthetic chain with five
OpenInference evaluator spans. The evaluator spans include hashes and exclude
content. They also identify their source as `synthetic_fixture`. The export
receipt states that no human review was performed and that reviewer identity
was not verified.

The current demo contract is
[`DEMO_INFORMATION_ARCHITECTURE.md`](./DEMO_INFORMATION_ARCHITECTURE.md). The
segment and phrase defense is
[`DEAL_ROOM_CONTENT_GRAPH.md`](./DEAL_ROOM_CONTENT_GRAPH.md).

This status is keyed to `VERIFICATION_GATES.md`. “Verified” means direct
evidence exists in the current checkout; “open” is not silently treated as a
pass.

| Gate | State | Evidence | Remaining acceptance work |
|---|---|---|---|
| Current customer demo | Verified in the current browser replays | Accepted scope, page structure, and content graph. Chromium verifies the Project Titan decision status, specific question, four grouped priority files, Overview, Sources, Activity, Evaluation, secondary views inside Room details, exact source navigation, canonical room routes, three responsive layouts, hashed screenshots, and no browser errors. Firefox and WebKit pass the earlier decision path. | A human usability study and cross browser checks of Evaluation remain separate work. Accuracy certification and commercial proof do not control this gate. |
| 0. Integrity baseline | Verified | Capability-aware CLI/API, target-state banners, unsupported-claim scan | Continue claim scan as surfaces change |
| 1. Private-folder ingestion | Verified for bounded recursive md/txt/csv/json/html, XLSX, text-bearing PDF, and image-only PDF ingestion on the measured macOS host | Arbitrary-path CLI and loopback HTTP/UI registration; hash-bound no-write folder preview; nested source-change-before-create rejection; stable relative citation identities and duplicate-basename checks; file and byte limits; format guards; a preregistered XLSX regression; physical PDF page anchors; OCR disclosure and limits; and a three-page public clean-raster OCR benchmark that recomputes scores from raw output. The current OCR run measured 0.11 percent word error, 0.04 percent character error, and 21 of 21 critical phrases after the OCR raster changed from 200 to 300 DPI. | The same pages were used to find and verify the DPI change, so the pass is development regression evidence. No independent reviewer approved the labels. Natural customer scans, general reading order, tables, layout, non-macOS OCR, legacy or protected XLS files, formula recalculation, independent office-suite parity, Docling layout AST, and merged-cell reconstruction remain open. |
| 2. Provider reality | Live invocation, current engineering benchmark, and automated cold restart verified | Current weights and vision projection files independently hashed; sanitized llama.cpp 2.28.2 process configuration; LM Studio native `reasoning: off`; returned `27b@q1_0`; current source-bound post-restart run passed all four generated-code cases; app PID turnover and port closure recorded; raw process socket samples for the exact Prism, Bionic, and Bonsai processes | Clean-machine portability, VRAM, energy, packet capture, whole-host monitoring, and zero-egress proof remain unverified |
| 3. Hybrid policy | Verified at the request-authorization boundary | Local default; HTTPS-only cloud configuration; request-bound policy signature; distinct data-owner signature for context; exact Buzz relay restoration; atomic one-time consumption; PII redaction; provider metadata; HTTP and CLI fail-before-provider controls | No live cloud provider was configured or invoked. Buzz is in the same local trust domain. Organizational DLP, independent identity proof, provider trust, and network enforcement remain out of scope. |
| 4. Reliability benchmark | Deterministic baseline, Bonsai engineering regression, and bounded oracle-context diagnostics verified. Accuracy release has not passed. | Versioned four-case coding dataset; five-case underwriting development registry; raw output and source manifests; negative controls; and all five cases rerun. The Citrix absence case verifies two source files and scans 2,401 parsed nodes against three disclosed patterns. Two oracle answers passed the literal probe. Citrix financing dropped its citation. Citrix absence supplied both absence phrases but dropped its citation. The CMA failure persisted. | The whole-folder scan proves only zero matches for the registered patterns, which were written after development inspection. It does not prove semantic absence. The cases have no domain-owner approval. Approved cloud, ternary Bonsai, human calibration, and sealed comparisons remain open. |
| 5. Sandbox boundary | Prototype verified on the measured macOS host | Strict AST and import checks, dunder and transitive module escape tests, timeout, output, and resource ceilings, plus an operating system profile that denies network access, process forks, and reads under `/Users`, `/Volumes`, and `/Network`, plus the resolved current project and selected deal-room roots when needed. Traces record the effective roots. The profile limits writes to the temporary run directory. | The macOS profile is deprecated, and other readable system paths remain available. Hardened multi tenant or VM isolation is not implemented. Other operating systems have only the AST and subprocess controls. |
| 6. End to end product | Seeded and real SEC browser paths verified | Canonical nested routes, two-stage hash-bound folder opening, screen-bound retrieval, before and after first pass source snapshots, Buzz backed first pass and discussion UI, independently verified room message and canvas signatures, trace bound review commit guard, validated atomic room registries, trace bound Titan and Zendesk replays, persistent local folder registration, exact citation navigation, hashed screenshots, zero console or HTTP errors, explicit human decision control, security headers, request limits, threaded HTTP serving, concurrent trace persistence, clean directory reproduction, and a same host operator preflight. Startup now fails on an occupied explicit port and verifies the exact child PID through the live status endpoint before printing the canonical URL. Identical active Buzz message reads are coalesced, browser polls cannot overlap, hidden tabs stop polling, and abandoned HTTP clients no longer emit misleading server tracebacks. | The folder preview has six passing Chromium assertions and makes no Buzz or registry write. Ranking pressure and real folder tests prove the investment screen changes admitted evidence. Mutating a source during model generation or fallback retrieval returns 409, records the failed snapshot state, and publishes no agent draft. A real workbook request completed while all 367 status probes made during the request remained responsive. The slowest took 135.802 ms. Its signed events and trace restored. This is not a load test or production service objective. A behavioral Chromium control delays one message response beyond the polling interval, proves at most one active message request, observes the queued refresh, suppresses the hidden tab interval, and refreshes when visible. It is not a Buzz load or soak test. A four part Zendesk answer passed the structural publication guard and restored after a Prism restart. Earlier misses remain visible in Buzz history. Corrupt room registries and orphaned review canvases fail visibly. An occupied workspace port never falls through to an unannounced alternate server. The WebUI provider path is scoped for each request and publishes signed Buzz events. Generic direct ACP is opt in and experimental. Its single room safety controls work, but a live Bonsai run exhausted its tool loop without publishing a reply. Domain review, Safari, branded Chrome, Edge, extensions, assistive technology review, WCAG conformance, and clean physical machine setup remain open. |
| 7. First pass underwriting | Product path, benchmark contract, development evaluator, blinded output review, source workshop, case authoring workshop, signed case approval, approval recording, raw Nostr replay, atomic candidate registration, reviewer authority controls, material bound benchmark governance, and fail before read sealed custody are verified. Accuracy release has not passed | Live `27b@q1_0` runs, signed Buzz requests, v7 evidence guards, exact citation links, a five case base registry, 29 acquired SEC deal proxies, 29 acquired pre-proxy financial companions, 261 unlabeled single source drafts, 58 unlabeled cross document drafts, candidate capacity for every release task family, a private Buzz review channel, source review, case authoring, blinded output review, folder preview, and pricing proof pages. The source review surface shows all ten benchmark decisions with current server derived evidence and blockers. It also shows a server derived three scope by four role governance matrix, all current material hashes, and the local trust root boundary. The browser never requests a governance private key. Source and output reviewer admission require exact relay restored events signed by one configured authority key and bound to separate scopes. Benchmark promotion no longer reads names or booleans from the manifest. One root signed Buzz event must assign product, domain, strategy, and security roles. All four roles must sign the benchmark contract, release thresholds, and sealed test opening over the exact current material hash. Tests reject material edits, assignment edits, shared role keys, wrong signers, cross role reuse, event replay, duplicate receipts, saved browser matrix edits, and plain manifest approval fields. The system also verifies reviewer signatures, source snapshots, registration, locked roster updates, content addressed approval artifacts, append order hash chains, atomic ledger replacement, deletion and corrupt head controls, duplicate and rollback guards, browser records, synthetic completion fixtures, and a public only sealed manifest plus one time contact controller | The ten decision surface reports 0 of 10 satisfied. Benchmark governance is unconfigured and has 0 of 12 required receipts. The checked in trust root is still local configuration. Prism does not prove legal identity or qualification, and a local administrator can replace the code and trust root. The approval, registration, governance, and roster JSON files are mutable local files. Their signatures and chains detect inconsistent saved history, and local locks prevent cooperating processes from losing an update. They are not externally anchored, immutable, or distributed storage. Both candidate ledgers are empty, so the benchmark remains 5 of 120 cases, 3 of 30 deals, and 0 domain approvals. Candidate capacity does not satisfy approved coverage. Both reviewer roster authorities are unconfigured, both reviewer rosters are empty, and the sealed inventory is empty. Synthetic authority, registration, completion, governance, and sealed controller fixtures do not count as human, buyer, or accuracy evidence. Calibration, human approved cross document cases, sealed testing, required coverage, signed owners, and signed thresholds remain open. |
| 8. Paid pricing proof | Contract, unsigned record builder, authority statement renderer, separate authority and buyer Buzz publishers, evaluator, CLI, honest empty-state web workspace, and synthetic completion fixture are verified. No pricing result is claimed | Ten explicit product-value gates; distinct configured authority and buyer keys; exact authority and buyer event restoration; two-deal setup and transfer design; time, usefulness, correction, post-use price, and next-step measures; exact buyer payload hashing; NIP-01 and BIP-340 verification; atomic persistence; self-issued-key, unpublished-event, changed-event, signature-tamper, transfer-quality, price-order, buyer-refusal, and failed-POC retention controls | The pricing authority is unconfigured. No customer has supplied authorized private historical rooms, signed buyer evidence, a price range, or a paid-next-step decision. The configured authority will prove key control and an approval statement, not legal identity or employment. Public SEC demonstrations, raw signatures that are not restored from Buzz, and synthetic fixtures do not satisfy the pricing contract. |

The end to end surface now shows a server derived evidence scope for each
accepted answer and restored first pass. The server recomputes the current
parser inventory and checks every trace citation against the current source
hash. Duplicate citation identities, missing anchors, and source hash drift fail
closed. The displayed counts describe parsed inventory and passages admitted to
the model. They do not measure semantic coverage and do not prove full document
review.

The benchmark calculation field is executable rather than decorative. A
registered calculation carries named values bound to reviewed claims. Prism
uses a bounded arithmetic parser to recompute the expected result and rejects
unknown variables, calls, unsupported syntax, zero division, nonfinite values,
and source values absent from the reviewed claim. The answer evaluator requires
the inputs, formula, result, and unit. No current registered case contains a
calculation, so this closes the verification path but does not increase measured
calculation coverage.

The benchmark contract validator now rejects schema keywords that it does not
implement. It enforces the checked in `const` and `exclusiveMinimum` rules,
requires a UTC offset on every `date-time`, and applies sibling rules beside a
`oneOf` or `$ref`. Negative controls change the pricing record's fixed billing
unit, submit zero where a positive price is required, omit a timestamp offset,
and try to bypass a required field through `oneOf`. Each record fails. The
validator implements the subset of JSON Schema used by the checked in
contracts. The schema definition check also rejects unsupported dialects,
formats, types, constraint value forms, and unresolved local references. A
schema under `additionalProperties` is applied to every undeclared field.
Patterns use JSON Schema search semantics. The validator does not claim general
JSON Schema conformance. JSON value comparison keeps booleans distinct from
numbers, treats mathematically equal JSON numbers as equal, and rejects
nonfinite Python numbers before numeric constraints run.

## Goal completion decision

`scripts/verify_product.py` emits a separate fail-closed `goal_completion`
decision. The current decision covers the accepted customer demo goal. It
requires the propagated scope, the ideal page structure, the local Bonsai deal
room, the current customer surface, the source and team path, the defended
content graph, and a fresh browser record.

The new browser record uses the current asset version and Project Titan. It
checks Overview, Sources, Activity, Evaluation, the Room details drawer, the decision
status, the decision question, four priority files, exact source navigation,
the canonical Activity route, and the 390, 768, and 1440 pixel layouts. It also
hashes desktop and mobile screenshots.

Accuracy certification, commercial proof, and production hardening stay in
this status page as historical and future programs. They do not control the
current customer demo decision.

The saved process socket observation remains a partial network check. It reparses
raw samples, requires the three named process roles, rejects wildcard and
nonloopback endpoints, and rejects unredacted API keys. The check found no
nonloopback endpoint in its samples. It can miss brief connections and excludes
packets, Docker guest traffic, and unrelated processes. The goal guard therefore
keeps `measured_zero_egress` false.

The trace ledger has a signed checkpoint path. The recorder publishes the
exact ledger format, sequence, and head as an owner-signed Buzz message,
restores the raw event, verifies its signature and payload, and proves the hash
at that sequence still exists in the local ledger. Later benchmark traces may
advance the current head while preserving that signed prefix; the verifier
reports this distinction explicitly. Because Buzz runs on loopback on the same
machine, the receipt reports `externally_anchored: false`.

The observability module no longer contains a response-only evaluator that can
report source grounding while ignoring its source argument. The compatibility
method now requires exact claim text in both declared source fields and the
response. It records `lexical_claim_reproduction`, and it always states that
semantic faithfulness and accuracy are unmeasured. A response that echoes a
claim absent from the source fails the check.

The old table evaluator also trusted caller supplied counts and did not inspect
the extracted tables. The compatibility method now ignores those counts. A
pass requires a nonempty fixture with a table index, row, column, and exact text
for each checked cell. The emitted metric is `tabular_fixture_cell_match`, and
its record states that general extraction accuracy is unmeasured. A wrong value
at a valid coordinate fails. The configured phrase check now records exact
denylist matches and states that it does not detect hallucinations.

The canonical local verification record is now a last known good record. A
failed local run writes a separate `failed-attempt` record and cannot replace
the canonical file. The test that mutates a saved answer now builds its own
valid fixture, so the component suite does not depend on mutable production
evidence. A successful canonical run still validates the exact saved bytes
before it can commit.

The cold restart record now binds a cold specific browser report and screenshot.
Running the normal browser verifier no longer changes the file that the restart
record hashes. A hash change in the cold specific report still fails the restart
validator.

A normal local product verification now requires the cold restart record to
pass. The post restart candidate is the only exception because its enclosing
record does not exist yet. A report cannot return a verified local result while
showing a failed cold restart section.

The old schema helper checked only whether keys existed, even though its name
and explanation implied typed schema validation. A list of fields now emits
`required_field_presence` and states that field types were not checked. A map
from field names to JSON type names checks required top level types and emits
`typed_field_schema_check`. The check does not claim nested constraints or full
JSON Schema validation. Empty schemas and wrong types fail.

The trace release state no longer labels an unmeasured check as a rejected
guard. An explicit failed guard returns `rejected`. Missing or not applicable
evidence returns `unverified` with the label `Evidence incomplete`. A pending
human or domain decision returns `awaiting_review` only when no failed or
unverified check takes priority.

The live deployment status cache is bound to the evidence bytes and each model
artifact's device, inode, size, modification time, and change time. A changed
artifact causes a new SHA-256 verification. A warm-cache tamper test changes a
same-size weights file and requires the next status read to fail verification.
A separate 20-request cold-cache test observes one hash validation and one
shared verification timestamp.

Deployment status also inspects the current process table on every read. It
requires one llama-server using the measured weights and projection, and it
compares only allowlisted runtime fields. Missing, duplicate, or changed runtime
configuration fails the deployment card without exposing unknown process
arguments. The saved and active process must use the same bind port, and the
bind host must be `127.0.0.1`. The loopback check does not measure network
egress or prove an air gap.

The trace API now returns one explicit evaluation state for each run. The state
separates guard rejection, pending review, passed recorded checks, and missing
evaluations. The Evidence page uses the API state, and the browser replay checks
that a structurally accepted answer awaiting domain review says `Review pending`
instead of `Rejected` or `Accepted`.

The observability aggregate helper now returns `null` for every metric that has
no samples, and it returns a sample count for each metric. An empty trace set no
longer appears as zero quality, zero latency, or 100 percent local routing.

Trace persistence is now a versioned SHA-256 event chain rather than a mutable
snapshot. Trace creation and review updates append under a mode-0600 advisory
file lock after rereading the ledger. Legacy JSONL snapshots migrate through a
synced atomic replacement. Tests detect content edits, reordering, and internal
entry deletion; preserve twelve competing process writes; reject conflicting
reviews; and preserve prior bytes when an append fails. This is tamper-evident
local history, not a signed, externally anchored, immutable, or distributed
audit system. A local administrator can still rewrite or truncate the ledger.
The upgrade also exposed a verifier isolation defect: a failed-bind test opened
the production trace store before the socket failure, so later HTTP tests wrote
20 fixture traces there. Startup now binds before opening the store, and a
negative test proves a failed bind creates neither ledger nor lock file. The 20
events were not deleted. Twenty correction events label them as verification
fixtures and exclude them from aggregates; the before and after heads are in
`evidence/runtime-trace-contamination-remediation-v1.json`.

The threaded server serializes registry transactions within one Prism process,
and both local registries use mode-0600 advisory file locks across cooperating
processes on one filesystem. Concurrent tests persist 32 local folder
registrations and 32 Buzz room bindings without loss. Twelve competing
processes preserve every distinct folder registration and produce one Buzz
channel with one canonical record. A live process reloads a registry replaced
by another process. Identity drift and failed atomic replacements preserve the
previous bytes. Remote Buzz channel creation and the two local registries are
not one distributed transaction.

Local operator review state is not stored in process memory. After a restart,
Prism reads the review from the persisted trace and
restores the named raw Buzz review and canvas events. Prism verifies both
signatures and compares every decision field plus the complete published text.
The first pass endpoint returns a dependency error when any part differs. A
local operator review remains separate from benchmark domain review.

The live Anaplan durability smoke review uses public development fallback trace
`trc_e730c75ee888`. The signed review records `PAUSE`, leaves usefulness false,
and states that it does not assess accuracy. After a Prism restart, the same
review event and canvas event restored from Buzz, and the review event timestamp
predated the new server process. The saved record is
`evidence/operator-review-restart-anaplan-v1.json`.

That Anaplan record predates the source-provenance marker and is retained as
historical durability evidence only. Current restoration does not promote it
to an active first pass. New first-pass and chat publications bind the signed
Buzz marker and trace to the server-derived room classification, a canonical
provenance hash, and the complete folder snapshot. Prism recomputes all three
before restoration. Chat and first pass check them again after Buzz restores a
new signed event. If the room changes during publication, Prism records the
candidate event as orphaned. The workspace replaces the candidate payload with
a quarantine notice and presents the signed rejection instead. A live Zendesk SEC run restored
the raw Nostr event, verified its signature, matched the persisted trace, and
recomputed the two-file public corpus state in 12 checks. See
`evidence/provenance-bound-publication-v1.json`.

M3 general coding-agent reliability is not claimed. A measured seven-case pilot
and a separate seven-case held-out mutation set cover generation, edit, test
generation, allowlisted library use, unsafe filesystem access, timeout, and
unsupported-language behavior. Both sets passed 7/7 expected dispositions.
Six cases in each set invoked `27b@q1_0`; the unsupported-language case was
stopped by a deterministic policy guard and is not attributed to Bonsai. Syntax,
sandbox, task, disposition, and source-grounding outcomes are recorded
separately. Grounding was 1.0 across the three applicable code-anchor cases in
each set. Reports are saved in
`evidence/bonsai-local-coding-benchmark.json` and
`evidence/bonsai-local-coding-holdout.json`. This remains a small constrained
Python pilot, not a general repository-level coding score. Unsafe-code passes
mean the sandbox rejected generated code, not that the model avoided generating
it.

## Current measured results

- Deterministic baseline: 4/4 cases, exact expected numeric outputs, and all
  required source names. Values are extracted from the selected folder; mutation
  tests prove outputs change with the files. Titan additionally surfaces a
  model-versus-credit-policy inconsistency. This remains a reviewed-workflow
  regression result, not a Bonsai or general AI accuracy score. See
  `evidence/baseline-product-verification.json`.
- Initial local Bonsai smoke test: LM Studio/Bionic served `27b@q1_0` through
  `/api/v1/chat`; the response recorded zero reasoning tokens and generated a
  Q2-2026 EBITDA sensitivity script that passed the AST/subprocess sandbox.
  The arithmetic and citations were correct, but the response omitted the
  benchmark's explicit covenant-breach field. It is retained as failure-history
  evidence rather than overwritten by the later passing run. See
  `evidence/bonsai-native-smoke.json`.
- Current local Bonsai engineering benchmark v3: 4/4 cases passed with mean
  structured check coverage 1.0, filename attribution coverage 1.0, sandbox
  success on every case, and per-case provider and model identity. Prism adds
  framework-owned deal and source provenance to the model-generated sandbox
  output. The output says that the provenance is not model authored. Filename
  attribution does not prove semantic grounding. The benchmark rejects unrelated
  regulatory findings, invented policy thresholds, wrong EPS units, wrong LBO
  contract tiers, and unsupported breach language. See
  `evidence/bonsai-local-product-verification-current.json`.
- The current v3 run passed 4/4 after an automated Bionic restart. The recorder
  proves the old PID exited, port 1234 closed, and a distinct application and
  model process started. The recorder then refreshes the measured deployment,
  the live inference responsiveness check, and the browser check. The restart
  record stores the SHA-256 hash of each result. The post restart report contains
  its source manifest and complete component test result. The clean directory
  record contains the current test and file counts with zero skipped tests. The
  final cold restart record binds the live runtime to the final source manifest.
  The backend used `--fit-ctx 16384`. The API advertises a 262,144 token model
  maximum, but Prism does not treat that value as active capacity. The local
  provider uses the chat template and tokenizer from the matching llama.cpp
  process. It adds a 32 token Bionic wrapper margin and reserves 4,096 output
  tokens before it admits a request. The live concurrency record stores both
  the admission count and the input count reported by Bionic. See
  `evidence/bonsai-cold-restart.json`.
- Cloud AI: unavailable until the HTTPS endpoint, model, two distinct authority
  keys, consent channel, and per-request published Buzz events are configured.
  A raw signature supplied only by the caller, an unpublished event, a changed
  restored event, a missing second context signature, or a replay fails before
  provider invocation.
- Titan first-pass v3: rejected before Buzz draft publication after one repair.
  Trace `trc_8c996bb91fba` records four remaining defects: 22.0% stated growth
  versus 24.4% implied by 418.0 to 520.0, one uncited numeric claim, and two
  invalid leverage calculations. Earlier v1 and v2 drafts are retained in Buzz
  as failure history but are `legacy_unverified` under the current guard and
  cannot be reviewed.
  Guard v4 additionally excludes filename-only retrieval nodes and checks named
  target support. Its definitive live run was rejected after one repair; trace
  `trc_deb005c32d88` records one uncited numeric claim and a target name cited
  only to a passage that did not support it.
- Titan first-pass v7: the live `27b@q1_0` draft passed the current deterministic
  evidence guard after a bounded repair corrected 2024A-to-2025A revenue growth
  from 22.0% to 24.4%. Trace `trc_c16aa77253ce` records 8,640 tokens, 96.2
  seconds, five admitted citations, and pending domain review. Browser QA proved
  inline citations open the exact parsed source node. Manual review still needs
  to resolve an ambiguous statement about which leverage ratio is undisclosed.
  This is a product-path pass, not an accuracy-release pass.
  Prism now restores the original agent event
  `5f66ef5717fc76af3304768f47800302b7e041449b8805803a4a3f2e47bb1b8b`.
  Trace `trc_c16aa77253ce` names the same event. A later event that copied the
  marker is retained in Buzz history and is not accepted as the active draft.
  The trace linked Buzz restore, source hashes, output, response hash, and
  explicit pending review state are saved in
  `evidence/bonsai-first-pass-titan-v7.json`.
- Titan screen-bound first pass: a new live request focused on the reported ECF
  sweep schedule versus Section 2.02. Three screen-matched passages were
  reserved in the bounded context. Bonsai used 11,183 tokens across its draft
  and repair, then failed because one numeric factual claim remained uncited.
  The first run exposed a heading-only Section 2.02 citation. Prism now carries
  the section title into its child provision and cites `node:node_para_3`, which
  contains the 50%, 25%, and 0% thresholds. The repeated live run retained
  failed trace `trc_a4cdcdb1d205`, published none of that prose, and signed a
  separate source excerpt fallback as trace `trc_8a813e697a21`.
  The fallback and trace share source snapshot
  `b1041d999b205faa538d03ee5a93b8f22ae95de0db3a68e44550833f6f47bbb1`.
  See `evidence/bonsai-first-pass-titan-screen-bound-v1.json`. This proves the
  screen, rejection, snapshot, and fallback path, not deal accuracy.
- Public first-pass development breadth: isolated Anaplan, Citrix, and
  Microsoft/Activision folders completed the full product path with no source
  writes. All three Bonsai drafts were rejected and replaced by separately
  traced evidence fallbacks. This is failure-path coverage, not accuracy. See
  `evidence/bonsai-first-pass-public-development-v1.json`.
- Public discussion development cases: all five registered questions were run
  again through the live Bonsai and Buzz path. Each answer records a current
  public filing classification, provenance hash, and complete folder snapshot.
  A separate process restored all ten raw Buzz events and all five persisted
  traces. The offline evaluator now rejects an answer when any marker, trace,
  room, response, provenance, or snapshot field differs. All five cases remain
  semantically unverified and cannot satisfy the accuracy release gate. See
  `evidence/bonsai-public-deal-battletest-responses.json` and
  `evidence/public-deal-buzz-event-verification.json`.
- Real SEC discussion surface: the acquired Zendesk DEFM14A and financial
  companion opened as a two-source Buzz room with no parser warnings. The first broad answer and the
  first multi-part retry missed the disclosed price. A visible M&A query
  repair first recovered the exact price. The current guard detects four parts
  in the broader question and retrieves qualifying price, stockholder,
  regulatory, and financing-condition passages. `27b@q1_0` returned one
  extractive, source-cited answer in a signed Buzz event. Twenty one browser
  assertions verified all four citations, the signed event and persistent trace
  binding, restart restoration, human labels, the hidden machine marker, exact
  source navigation, and zero browser or HTTP errors. See
  `evidence/browser-real-deal-zendesk-v1.json`. The structural guard passed.
  Domain review and benchmark registration remain open.
- Local XLSX surface smoke: one operator-selected workbook opened through the
  live Buzz workspace with eight sheets, 60 cached formula cells, and no parser
  warning. An early run exposed a real parser defect: style `0.0%` was ignored,
  so the model changed raw value `99.97222222` to unsupported claim
  `99.97222222%`. The guard rejected it as trace `trc_f413f7300a29`. After a
  bounded style-aware parser preserved the raw value and rendered the workbook
  display value `9997.2%`, Bonsai answered with the exact admitted sheet
  citation on its first attempt. Trace `trc_a941c0ec2c72` passed the structural
  guard and answer event `09d73b05b7cf5b68aa68a16b7d320ce861808de6030492bf4640e9186ba0296f`
  was signed to Buzz. Browser verification followed the citation to sheet 3 and
  found the same value, the cached-formula warning, and zero console errors. A
  Prism restart restored the same signed answer at its canonical URL with zero
  console errors.
  See `evidence/bonsai-xlsx-workbook-chat-v1.json`. This is a structural product
  smoke, not an XLSX accuracy pass or a reproducible benchmark case.

## Release blockers for a Bonsai accuracy claim

1. Review of benchmark expected values by a deal-domain owner.
2. Completion and adjudication of the planned first-pass benchmark set.
3. A Bonsai run that passes the current claim-to-source guards and human review thresholds.
