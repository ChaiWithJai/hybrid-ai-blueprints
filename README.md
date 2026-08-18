# Prism Vault

Prism Vault is a local deal-room analysis prototype and an integration path for
using **Bonsai 27B as the local model in a hybrid local/cloud coding agent**.
The repository contains real document parsing, policy routing, sandboxed Python
calculation, trace recording, and reproducible benchmark scaffolding. It does
not bundle Bonsai weights, a production inference kernel, or hardened VM
isolation.

## Minimum lovable Buzz workspace

The v0 delivery surface is a browser workspace backed by Block's real Buzz
relay and ACP harness. A private deal room maps to a private Buzz channel;
conversation is stored as signed Buzz events; the deal digest is a Buzz canvas;
and Bonsai 27B can join one selected room as a bot member through `buzz-acp`
and `buzz-agent`. The direct Buzz agent is bound to one room, one channel, and
one source folder. It does not subscribe to every room.
Before displaying a message, Prism restores its raw Nostr event and verifies the
NIP-01 event identity, BIP-340 signature, channel, author, and payload. Message
writes receive the same check before the API reports success.
Prism applies the same checks to the current Buzz canvas. A canvas changed
outside Prism remains unavailable until the operator saves it through the
verified Prism path and records the new event ID.
The local Buzz room registry validates each room, channel, and canvas binding.
Prism reports registry corruption as a workspace dependency error and does not
reinterpret corrupt state as an empty room list.
Room creation, canvas binding, and folder registration commits take local
advisory file locks and replace their registries atomically after rereading
them. This coordinates cooperating Prism processes on one filesystem. The two
local registries and the relay are not one distributed transaction.

With LM Studio serving `27b@q1_0` on port 1234:

```bash
python3 scripts/preflight.py --phase host
python3 scripts/run_v0.py
python3 scripts/preflight.py --phase live --json \
  --output evidence/operator-preflight-current.json
```

To open a previously registered folder room, start the surface with its room ID:

```bash
python3 scripts/run_v0.py --agent-room local_bbfa4e91f7ee
```

The WebUI analysis path is source-scoped to the room selected in each request
and publishes its answer as a signed Buzz event. The generic direct Buzz ACP
responder is not part of the required v0 surface because a live Bonsai run
exhausted its tool loop without publishing a reply. It can be investigated with
`--direct-acp`. When enabled, it listens only to the named room, accepts the
local operator identity, keeps memory disabled, and stops Prism if it exits.
Those controls prove scope safety, not response behavior.

`run_v0.py` performs the Buzz bootstrap and installs the pinned Buzz tools when
they are absent. The first setup therefore needs Docker image access plus Git
and network access to build the pinned Buzz commit. Startup fails before the
site is announced if Docker is unavailable, the requested Bonsai model is only
listed but not loaded, native reasoning-off support is absent, Buzz is not
healthy, or key permissions are unsafe. When experimental direct ACP is
enabled, startup also fails if that agent exits early. The
preflight is a same-host readiness check. It is not clean-machine reproduction,
model-quality evidence, artifact-identity evidence, or an air-gap test.

Open `http://127.0.0.1:8787/rooms/project_titan_lbo/first-pass`. See
[`docs/SURFACE_V0.md`](../../docs/SURFACE_V0.md) for the product boundary, canonical
URL model, anti-facade acceptance criteria, and explicit v0 limits.

Project Titan, AeroFlux, BioVanguard, and Horizon are fabricated engineering
fixtures. The API and workspace label them as synthetic. An acquired filing
room is labeled public only when every visible file matches its checked-in
acquisition path, byte count, and SHA-256. Other folders are labeled as
operator selected, which does not prove customer origin or authorization.

Run the browser check while the local stack is live:

```bash
npm install
npm run setup:browsers
npm run verify:browser
npm run verify:accessibility
npm run verify:cross-browser
```

The setup command installs a dedicated Chromium build. The browser check opens
the saved Titan first pass, follows an inline citation to its exact source
passage, checks the trace and model status, and saves a full page screenshot.
The check fails on browser console errors, failed requests, HTTP errors, or a
missing UI assertion. The accessibility smoke checks tab semantics, keyboard
navigation, visible focus, citation focus, dialog focus, reduced motion, target
size, and mobile width. A separate replay runs the same signed answer and exact
citation path in Firefox and WebKit. The checks do not prove deal accuracy,
WCAG conformance, assistive technology behavior, Safari, branded Chrome, Edge,
browser extensions, or clean machine setup.

The current Titan v7 run passed the deterministic evidence guard after one
bounded repair corrected a revenue-growth error. It remains an unreviewed model
draft, not a benchmark or accuracy pass. Buzz retains older rejected drafts and
their separately traced source-excerpt fallbacks; reviewing a fallback cannot
promote its rejected Bonsai trace. Inline citations open canonical file URLs at
the exact parsed source node. A visible artifact is not evidence of model or
benchmark acceptance.

The live surface was also exercised on an acquired Zendesk SEC DEFM14A. The
saved history retains the original retrieval misses. The corrected path detects
four requested parts, retrieves qualifying passages for each part, and rejects
an answer unless each part has a same-line citation. It also rejects numbers and
material words that are absent from the cited passage. Bonsai returned the
`$77.50` consideration, stockholder approval, regulatory approvals, and the lack
of a financing condition in one signed Buzz answer. The answer event is bound to
a persistent trace and four source anchors. After a Prism restart, a 24 assertion
browser replay restored the trace and signed events, hid the machine marker,
rendered human labels, and opened the financing citation at the exact source
block. This is a structural publication pass. It is not domain review or an
accuracy result, and Zendesk is not a registered benchmark case. See
[`evidence/browser-real-deal-zendesk-v1.json`](../../evidence/browser-real-deal-zendesk-v1.json)
and its hashed screenshot.

The workspace shows the evidence scope for each accepted answer and restored
first pass. The server recomputes the current parser inventory and verifies that
every trace bound citation still resolves to the same source hash. The disclosure
states how many passages reached the model and how many searchable nodes the
parser found. These counts do not measure semantic coverage and do not prove a
full document review.

A newer live Zendesk publication also binds the signed event and trace to the
server-derived `public_filing_corpus` classification, a canonical provenance
hash, and the complete two-file folder snapshot. A separate process restored
the raw Nostr event, verified its signature, restored the persisted trace, and
recomputed the current folder state in 12 checks. This is provenance and
durability evidence, not deal accuracy or buyer evidence. See
[`evidence/provenance-bound-publication-v1.json`](../../evidence/provenance-bound-publication-v1.json).

The Titan discussion surface also has a narrower debt-structure reality test.
For the question asking for every disclosed debt tranche and amount, retrieval
must select the Sources of Funds table. The publication guard requires the
revolver, first-lien term loan, second-lien notes, and mezzanine debt, including
the revolver's stated commitment and zero funded amount, while excluding equity
rows. A 20-assertion Chromium replay retains the earlier rejected attempt beside
the accepted signed answer, proves restart restoration, and opens the exact
table citation. This remains a structural check awaiting domain review. See
[`evidence/browser-titan-debt-chat-v1.json`](../../evidence/browser-titan-debt-chat-v1.json)
and its hashed screenshot.

Measured pilot results and limitations are collected in the
[Bonsai 27B benchmark card](../../docs/BENCHMARK_CARD.md).

The product verifier reports local runtime readiness separately from full goal
completion. Inspect `goal_completion` in its JSON output. A live Buzz workspace
does not close domain review, benchmark scale, pricing, clean-machine, security,
network, OCR, or layout gates.

Benchmark calculations are source bound and executable. A registered case must
name each numeric input and its reviewed claim. Prism recomputes the bounded
arithmetic formula before registration, then requires the answer to show the
inputs, formula, result, and unit. The current five registered cases contain no
calculations, so this control does not claim calculation coverage.

The local trace chain can be checkpointed into a signed Buzz event with
`python3 scripts/record_trace_anchor.py`. The receipt verifies the exact ledger
prefix and records whether it was the current head at verification time. Later
trace appends preserve the checkpointed prefix but make the current-head flag
false. The bundled Buzz relay runs on the same host, so this does not satisfy
the independent external-anchor gate.

Run `python3 scripts/record_network_observation.py` to sample sockets for the
exact Prism, Bionic, and Bonsai processes during one local Bonsai request. The
recorder saves the raw `lsof` fields, and product verification reparses them.
The check fails if it sees a wildcard, invalid, or nonloopback address. It also
redacts the runtime API key and writes the record with mode `0600`. Socket
sampling can miss brief connections, and it does not inspect packets, Docker
guest traffic, or unrelated processes. The record does not prove zero egress,
an air gap, firewall enforcement, DLP, or production network isolation.

The current version 3 local engineering run passed all four synthetic
calculation cases with label, unit, source, relevance, legal-language, and
policy-tier guards. The result is saved in
[`evidence/bonsai-local-product-verification-current.json`](../../evidence/bonsai-local-product-verification-current.json).
It is not a domain-accuracy release. The current dataset has not yet been
independently reviewed by deal-domain owners. It has been reproduced after a
fresh Bionic process restart on the same workstation. This does not prove
clean-machine portability.

## First pass underwriting product

The product goal is now a first pass underwriting brief for a private equity
deal team. The user supplies an authorized M&A folder and an investment screen.
Prism Vault produces a reviewable advance, pause, or stop recommendation with
source evidence, reproducible calculations, and explicit unknowns.

The complete product definition, pricing assumptions, ten benchmark decisions,
dataset plan, evaluator design, and release gates are in the
[first pass underwriting benchmark](../../docs/FIRST_PASS_UNDERWRITING_BENCHMARK.md).
The versioned machine readable contracts are under
[`benchmarks/first_pass`](../../benchmarks/first_pass).

The measured macOS prototype can read image-only PDF pages with Apple Vision
OCR when a page has no usable embedded text. The Files view identifies OCR
pages and states that text and reading order may be wrong. Prism does not
reconstruct tables or layout from OCR. A preregistered engineering check on
three clean 200 DPI image-only pages from the public CMA Microsoft and
Activision report now passes its engineering thresholds after the OCR raster
was increased from 200 to 300 DPI. It measured 0.11 percent word error, 0.04
percent character error, and all 21 critical phrases. The change fixed a prior
`CMA` to `CMAY` error without adding document-specific words. The same pages
were used to find and verify the change, so the result is a development
regression check. It is not evidence for natural customer scans or a human
approved OCR release.

Check the benchmark inventory and approval gate with:

```bash
python3 scripts/verify_first_pass_benchmark_contract.py
python3 scripts/evaluate_first_pass_development.py
python3 scripts/export_first_pass_review_packet.py
python3 scripts/draft_candidate_questions.py
python3 scripts/export_candidate_source_review_packet.py
python3 scripts/validate_candidate_source_reviews.py
python3 scripts/evaluate_pricing_poc.py evidence/first-pass-pricing-poc.json
```

The current registry is structurally valid but is not ready for an accuracy
release. It contains 5 of 120 cases across 3 of 30 required deals, and none of
the cases has domain approval.

All 29 official SEC deal proxies are acquired and parser verified. Each deal
also has one acquired and parser verified public 10-K or 10-Q filed before the
proxy. A separate 319-question review queue contains 261 single-source leads
and 58 native cross-document leads, but no expected answers, labels, splits, or
approvals. See the
[candidate review runbook](../../docs/CANDIDATE_QUESTION_REVIEW_RUNBOOK.md).
Its model-blind reviewer packet is hash bound to the complete queue. The current
validation truthfully records 0 submissions, 0 drafts eligible for case
authoring, and 0 registered cases.

The reviewer workshop is live at
[`/benchmark/source-review`](http://127.0.0.1:8787/benchmark/source-review). It
shows the 319-question queue and opens hash-verified SEC context around each
candidate anchor. Submission remains disabled because selecting a rostered name
does not prove identity. Both reviewer rosters currently have no configured
authority and no members. An operator must record an authority key only after an
out of band identity check. Every reviewer admission must then match a
relay-restored Buzz event signed by that authority key and bound to the exact
roster scope and reviewer record. The form can export a schema-valid unsigned
review only for an admitted reviewer. A second signed Buzz event from the
reviewer's own key is required for acceptance.

The case authoring workshop is live at
[`/benchmark/case-authoring`](http://127.0.0.1:8787/benchmark/case-authoring).
It stays closed until a draft has two matching signed source reviews, or a
valid principal adjudication. For an eligible draft, the page locks the agreed
question, claims, citations, and hashes, and it can only download an unsigned
domain owner approval. Buzz signing, approval recording, and registration are
separate commands.

The blinded output review workshop is live at
[`/benchmark/output-review`](http://127.0.0.1:8787/benchmark/output-review).
It presents the five development responses without model or provider identity.
No judgment is selected by default. The browser can prepare one complete
unsigned review only for an approved reviewer and only after every case is
finished. The unconfigured output roster authority keeps export closed. A
source reviewer admission cannot be reused here. This development review does
not count as judge calibration or an accuracy release.

The pricing proof workspace is live at
[`/benchmark/pricing-poc`](http://127.0.0.1:8787/benchmark/pricing-poc). It
shows the paid pilot contract and its current evidence state. No customer proof
has been recorded. The evaluator requires two authorized closed private deal
rooms, a setup deal, an unchanged transfer deal, measured review time, a
post-use price range, a commercial next step or decline reason, a separate
commercial-authority approval, and a buyer event. The authority and buyer keys
must be distinct. Prism restores both events from the configured authority
channel and compares every signed field on each evaluation. A self-issued buyer
key or a valid raw signature in a local JSON file does not count. Public SEC
dossiers cannot satisfy those gates. The authority proves control of an
approval key. It does not prove legal identity or employment, so the operator
must complete the identity check outside Prism.
The browser downloads an unsigned record and never requests a private key. To
prepare the authority approval text, publish it with the configured authority
key, and retain the returned event ID. Then publish, restore, verify, and
atomically record both events:

```bash
export PRISM_PRICING_AUTHORITY_PUBKEY=<commercial-authority-public-key>
export PRISM_PRICING_AUTHORITY_CHANNEL=<private-channel-id>

python3 scripts/render_pricing_buyer_authorization.py \
  evidence/<poc-id>.unsigned.json

BUZZ_PRIVATE_KEY=<commercial-authority-private-key> \
  python3 scripts/publish_pricing_buyer_authorization.py \
  --record evidence/<poc-id>.unsigned.json \
  --buzz-channel <private-channel-id> \
  --confirm-authorize-buyer

BUZZ_PRIVATE_KEY=<buyer-key> python3 scripts/publish_pricing_poc.py \
  --record evidence/<poc-id>.unsigned.json \
  --buzz-channel <private-channel-id> \
  --buyer-authorization-event <authority-event-id> \
  --confirm-record-buyer-evidence
```

A structurally valid signed POC is retained even when value gates fail. The
recording command does not discard an unpaid refusal, missing price range, or
correction-heavy transfer deal to make the pilot look successful.

To check for hidden dependence on the current checkout directory, run:

```bash
python3 scripts/verify_clean_directory.py
```

This relocates an explicit project manifest into a temporary directory and
runs the baseline verifier. It does not provision or prove a clean machine.

The saved same-host dependency and live-service record is
[`evidence/operator-preflight-current.json`](../../evidence/operator-preflight-current.json).
It keeps optional benchmark deployment metadata separate from required startup
readiness, so a loaded model cannot silently become a benchmark claim.

The deployment recorder measures the loaded model separately from startup:

```bash
python3 scripts/record_local_deployment.py
```

The saved record hashes both the GGUF weights and the vision projection file,
captures the sanitized llama.cpp version and effective configuration, and
records the machine model, chip, and memory without the serial number. The main
verifier rehashes the current files. This proves current-host artifact identity,
not model quality, energy use, network isolation, or clean-machine portability.

## What is implemented

- Parse private folders containing Markdown/text, CSV, JSON, HTML, text-bearing
  PDF, and bounded XLSX files with source hashes and stable anchors. XLSX reads
  stored values and cell coordinates. It applies a bounded, audited subset of
  number formats while preserving raw values. It does not recalculate formulas,
  and unsupported formats remain raw. A nine-case preregistered XLSX display
  regression checks raw values, displayed values, formats, and formula state;
  its wrong-expected-value control must fail. This is not Excel parity. The
  parser recursively indexes supported files under stable relative names. It
  stops at eight directory levels, 512 visible files, 100 MiB of admitted
  source bytes, and 10 MiB per file. Symlinks are never followed, and excluded
  paths or limit failures are shown rather than described as ingested.
- Run reviewed deterministic M&A calculation templates as a no-model baseline.
- Call Bonsai through LM Studio's native reasoning-off API, or another local
  model through an explicitly configured OpenAI-compatible endpoint.
- Call a separately configured cloud provider only through an explicit cloud path.
- Record the actual route, provider, model response ID, sandbox outcome, latency,
  token usage, and evaluations in Arize-style traces. The web server persists
  them atomically under `.runtime/evals`; CLI traces remain in memory unless
  `--trace-output` is supplied.
- Review room traces and inspect the hybrid Eval lab inside the same Evaluation
  tab. The lab shows local, cloud, and hybrid states, versioned experiments,
  evaluator trust, Bonsai judge calibration, buyer value, and release gates.
  Its append only experiment ledger supports paired comparisons and does not
  turn missing evidence into a zero, a pass, or a composite score. See
  [`docs/EVALUATION_FRAMEWORK.md`](../../docs/EVALUATION_FRAMEWORK.md).
- Benchmark baseline/local/cloud runtimes against a versioned deal-room dataset.
- Run a separate constrained coding-agent pilot covering generation, edits,
  generated tests, allowlisted library use, unsafe code, timeouts, and refusal.
- Execute generated Python after AST allowlist checks in a resource limited child
  process. On the measured macOS host, an operating system profile also denies
  child network access, process forks, and reads under `/Users`, `/Volumes`, and
  `/Network`. It also denies the resolved current project and selected deal-room
  roots when those paths are outside the fixed roots. The trace records the
  effective denied roots. It confines writes to the temporary run directory.
  Other readable system paths remain available, so the result is not a hardened
  multi tenant boundary.

## Capability states

The product distinguishes research, configuration, recorded history, current
process invocation, and measurement. The live status API does not publish
hypothetical architecture, VRAM, energy, or benchmark values. A Bonsai
performance or accuracy claim is not a measured product result until a saved
benchmark report identifies the exact served model, dataset hash, weight
checksum, serving runtime/version, and hardware.

Inspect the current machine honestly:

```bash
./prismctl status
./prismctl models
```

## Point it at a private folder

```bash
./prismctl audit --deal-room /absolute/path/to/private/folder
./prismctl agent --deal-room /absolute/path/to/private/folder \
  --trace-output run-traces.jsonl \
  "Calculate leverage and identify the source files used"
```

Without an AI provider, `agent` runs the explicitly labeled deterministic
baseline. Supported source types are `.md`, `.txt`, `.csv`, `.json`, `.html`,
`.htm`, and text bearing `.pdf` files.

Prism does not publish source file bytes when it creates a Buzz room. Published
messages, generated briefs, citations, and reviewed canvases can contain deal
facts, and the configured Buzz relay retains that content as signed events.
Users should apply the relay access and retention policy required for the deal.
The included Compose file publishes the prototype relay only on
`127.0.0.1:3030`. This limits host access to IPv4 loopback. It is not an air gap
or a hardened tenant boundary.
The browser first previews the exact supported-file inventory and warnings
without writing to Buzz. Room creation requires that preview hash and fails if
a supported source changes before the operator confirms creation.

## Configure Bonsai as the local coding model

First, record filesystem evidence without loading the model:

```bash
./prismctl inspect-artifact \
  --path /path/to/Bonsai-27B-Q1_0.gguf \
  --backend-manifest /path/to/backend-manifest.json \
  --output bonsai-artifact.json
```

This produces `artifact_present_not_invoked` evidence. It is not a model run.

Serve Bonsai with LM Studio's native chat API (recommended) or an
OpenAI-compatible chat-completions endpoint, then set:

```bash
export PRISM_LOCAL_AI_URL=http://127.0.0.1:8000
export PRISM_LOCAL_AI_MODEL=bonsai-27b
# Optional, when the local server requires authentication:
export PRISM_LOCAL_AI_KEY=...

# Required before the verifier will accept a real Bonsai milestone:
export PRISM_LOCAL_AI_ARTIFACT_SHA256=<sha256-of-exact-weight-artifact>
export PRISM_LOCAL_AI_RUNTIME=<serving-runtime-name>
export PRISM_LOCAL_AI_RUNTIME_VERSION=<exact-version>
export PRISM_LOCAL_AI_HARDWARE=<machine-and-accelerator-description>
# Optional generation controls (defaults shown):
export PRISM_LOCAL_AI_TIMEOUT_SECONDS=300
export PRISM_LOCAL_AI_MAX_TOKENS=4096
export PRISM_LOCAL_AI_PROTOCOL=lmstudio-native
# Required for fitted context admission with the active llama.cpp tokenizer:
export PRISM_LOCAL_AI_CONTEXT_TOKENS=16384
export PRISM_LOCAL_AI_ARTIFACT_PATH=/absolute/path/to/Bonsai-27B-Q1_0.gguf
# Optional model-specific control; for the current Bonsai/Qwen runtime:
export PRISM_LOCAL_AI_PROMPT_SUFFIX=/no_think

./prismctl agent --runtime local --deal-room /absolute/path/to/folder "..."
./prismctl coding-benchmark --runtime local \
  --output evidence/bonsai-local-coding-benchmark.json
./prismctl coding-benchmark --runtime local \
  --dataset benchmarks/coding_agent_holdout.json \
  --output evidence/bonsai-local-coding-holdout.json
```

The verified Bionic cold-restart configuration used:

```bash
$HOME/.lmstudio/bin/lms server start --port 1234 --bind 127.0.0.1
$HOME/.lmstudio/bin/lms unload 27b@q1_0  # remove any auto-restored instance
$HOME/.lmstudio/bin/lms load 27b@q1_0 --context-length 16384 \
  --parallel 4 --identifier 27b@q1_0 --yes
```

The observed llama-server process used `--fit-ctx 16384`. The models API also
reported the model maximum as 262,144 tokens. Prism does not use the catalog
maximum as request capacity. Before each local request, Prism applies the chat
template from the active llama.cpp process and counts the prompt with the loaded
model tokenizer. Prism adds a 32 token margin for the Bionic wrapper and reserves
the configured output budget. Prism rejects the request before generation when
the total exceeds 16,384 tokens. The benchmark did not exercise a 262,144 token
prompt.

The saved pilot and held-out set each contain seven constrained tasks. They are
verification scaffolding, not a general coding benchmark. Unsupported-language
requests are handled by a deterministic policy guard and are not credited to
the model; unsafe-code cases pass only when the sandbox rejects execution.

The LM Studio native adapter sends `reasoning: off` and rejects a response
unless its runtime stats prove zero reasoning tokens. Prism accepts a local
provider URL only when it uses plain HTTP and a loopback IP literal, such as
`127.0.0.1` or `::1`. Hostnames, private network addresses, user information,
queries, and fragments fail during configuration. Prism then sends deal-room
evidence to the provider, requests a self-contained calculation script,
validates the returned code, and executes it in the child-process sandbox. The
trace names the provider and the model ID returned by the server. The URL check
does not prove zero egress or that the configured model is loaded.

## Configure an approved cloud path

```bash
export PRISM_CLOUD_AI_URL=https://approved-provider.example
export PRISM_CLOUD_AI_MODEL=approved-model-id
export PRISM_CLOUD_AI_KEY=...
export PRISM_CLOUD_POLICY_PUBKEY=<64-hex-policy-key>
export PRISM_CLOUD_CONTEXT_PUBKEY=<different-64-hex-data-owner-key>
export PRISM_CLOUD_CONSENT_CHANNEL=<buzz-channel-id>

./prismctl agent --runtime cloud \
  --deal-room /absolute/path/to/folder \
  --cloud-room-id approved-room-id \
  --cloud-consent /path/to/request-consent.json \
  "..."
```

The consent file is not a boolean approval. It contains the request nonce,
expiry, and raw policy event. The event must already be published to the
configured Buzz channel. Prism restores the exact event, verifies its NIP-01
identity, BIP-340 signature, signer, channel, prompt hash, room snapshot,
provider, model, nonce, and expiry, then consumes it once before calling the
provider. A request that includes `--allow-cloud-data` also needs a distinct
data-owner event in the bundle. A signed event supplied only in the file, but
not restored from Buzz, fails closed. The CLI does not collect private signing
keys.

Without `--allow-cloud-data`, cloud execution sends only the pattern-redacted
task and keeps parsed deal-room contents local. Pattern redaction is not a DLP
guarantee. Do not configure or use this path without organizational approval
and a consent publisher that creates the exact request-bound events.

## Reliability and accuracy benchmark

The first pass benchmark is the planned product release benchmark. The older
calculation and public dossier sets remain engineering and development data.
They do not certify a completed first pass underwriting brief.

The five public dossier questions now have new live Bonsai answers. Each saved
answer is bound to a public room classification, provenance hash, complete
folder snapshot, raw signed Buzz events, and a persisted trace. The offline
verifier requires all of these records to agree. The five results still have no
qualified domain labels, so their semantic accuracy and usefulness remain
unverified.

The cases live in
[`benchmarks/deal_room_reliability.json`](../../benchmarks/deal_room_reliability.json).
Run each runtime separately and save the artifact:

```bash
./prismctl benchmark --runtime baseline --output baseline-report.json
./prismctl benchmark --runtime local --output bonsai-report.json
./prismctl benchmark --runtime cloud --allow-cloud-data \
  --cloud-consents /path/to/per-case-consents.json \
  --output cloud-report.json
```

The baseline score is a regression check for reviewed templates, not an AI
quality score. Local/cloud reports are meaningful only when their cases show an
AI provider ID and returned model ID. The cloud consent file must be a JSON
object keyed by case ID. Each case needs its own nonce and published,
request-bound Buzz events; one approval cannot authorize a batch. See
[`docs/VERIFICATION_GATES.md`](../../docs/VERIFICATION_GATES.md) for milestones,
acceptance criteria, negative controls, and prohibited claims.
The current integration boundary is recorded in
[`docs/ADR_0001_BUILD_VS_BUY.md`](../../docs/ADR_0001_BUILD_VS_BUY.md).

## Run the product and tests

```bash
./prismctl serve --port 8080
# Open http://127.0.0.1:8080

python3 -m unittest discover -s tests -v
python3 scripts/verify_product.py --runtime baseline
```

The managed development sandbox may forbid loopback socket binding; the live
HTTP test reports a skip in that environment and must be run outside it before
the end-to-end HTTP gate can be accepted.

## Research and architecture

- [`docs/PRD.md`](../../docs/PRD.md) describes the product goal.
- [`docs/RFC_0042_VAULT_ARCHITECTURE.md`](../../docs/RFC_0042_VAULT_ARCHITECTURE.md)
  describes the proposed Bonsai/hybrid architecture.
- [`docs/ARCHITECTURE_REALITY_MATRIX.md`](../../docs/ARCHITECTURE_REALITY_MATRIX.md)
  maps every named layer to current executable evidence and explicit gaps.
- [`docs/BUILD_VS_BUY_GUIDE.md`](../../docs/BUILD_VS_BUY_GUIDE.md) captures the research
  position for evangelizing Bonsai as a model family.

These documents contain target-state proposals. They are not proof that the
corresponding weights, kernels, benchmarks, or isolation layers are installed.

Evaluation history is stored as a mode-0600, SHA-256-chained local JSONL event
ledger. Prism verifies the chain on load and serializes cooperating writers on
one filesystem. The ledger is not signed, externally anchored, immutable, or a
distributed audit system; a local administrator can rewrite or truncate it.
Verification uses in-memory or temporary trace stores. A failed port bind occurs
before Prism opens the configured production ledger. Historical verification
fixtures discovered before that guard were retained and explicitly excluded by
chained correction events rather than erased.
