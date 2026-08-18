# Prism Vault Bonsai 27B Pilot Benchmark Card

Status: current engineering regression passed, not an accuracy release  
Run date: 2026-08-15  
Hardware: MacBook Pro, M5 Pro, 48 GB unified memory  
Serving runtime: LM Studio llama.cpp 2.28.2 over the native `/api/v1/chat` API

## Product benchmark direction

The product benchmark is now defined as a first pass underwriting brief for a
private equity deal team. The current pilot and public dossier results are
development evidence for that benchmark. They do not certify the complete job.

The target dataset, evaluator layers, pricing proof of concept, and release
thresholds are in
[`FIRST_PASS_UNDERWRITING_BENCHMARK.md`](./FIRST_PASS_UNDERWRITING_BENCHMARK.md).

## Model identity

- Served identifier: `27b@q1_0`
- Weight artifact: `Bonsai-27B-Q1_0.gguf`
- Quantization reported by LM Studio: `Q1_0`, 1 bit
- Weight SHA-256:
  `17ef842e47450caeb8eaa3ebfbbab5d2f2278b62b79be107985fb69a2f819aa0`
- Reasoning mode: requested off; responses without a recorded zero reasoning-token
  count are rejected
- Cold-restart load configuration: backend `--fit-ctx 16384`, four parallel
  slots, and loopback server on `127.0.0.1:1234`. The models API separately
  advertises the model maximum as 262,144 tokens. No 262,144-token workload was
  tested.

The filesystem inspection record is
[`bonsai-27b-artifact.json`](../evidence/bonsai-27b-artifact.json). Presence alone
is not treated as invocation evidence.

The live status API verifies the current weights and projection hashes. It
caches that expensive check only while the evidence bytes and artifact file
identity remain unchanged. A same-size artifact change invalidates the cache
and fails the next status check. Concurrent cold status requests share one hash
verification.

Each live status read separately checks the active llama-server. The model and
projection paths, executable bundle, runtime version, fitted context, parallel
slots, cache types, flash attention, load mode, bind host, and bind port must
match the measured record. The bind host must be `127.0.0.1`. The deployment
card fails if the model is unloaded, duplicated, exposed on a non-loopback
address, or restarted with different settings. The process check does not
measure network egress or prove an air gap.

## Deal-room pilot

The current version 3 workload contains four generated-code cases covering
EBITDA stress, an LBO cash sweep, EPS accretion, and carve-out quality of
earnings. The dataset SHA-256 is
`95a31ad2e745a2ac44117388b3a346b36f238984dac597d8795c8be97301e93a`.

The current source bound live run passed 4/4 cases. Mean structured check
coverage and filename attribution coverage were both 1.0. The saved report
records the per case latency and the measured mean for that run. All four
generated scripts passed the prototype sandbox. Prism attaches the deal identifier and the filenames used by
the typed input bundle to the execution result. The output labels this section
as framework provenance and keeps it separate from the model-generated sandbox
output. Filename attribution coverage is not semantic grounding. The saved
[`current local verification run`](../evidence/bonsai-local-product-verification-current.json)
records the exact model, artifact hash, runtime, hardware, generated code, raw
output, and any rejected generation attempt.

Run 4 failed at 3/4 because Titan returned correct multiline JSON but did not
print its source metadata. Run 5 passed after Prism attached framework-owned
provenance and the evaluator accepted an equivalent multiline JSON layout. A
negative control still fails when the year-one contract sweep changes from 25
percent to 50 percent. Both runs remain saved.

Version 3 adds label-and-unit patterns and negative checks for unrelated
regulatory findings, invented accretion thresholds, EPS values labeled as
millions, invented valuation policy, wrong LBO contract tiers, and unsupported
legal breach claims. Supported calculation tasks receive parser-extracted typed
facts instead of full source text. Generated scripts that cross a reviewed task
scope receive one recorded repair attempt and then fail closed.

The automated cold restart recorder reproduced the current version 3 run. The
recorder verified that the old application process exited, port 1234 closed,
and distinct application and model processes started. The recorder then refreshed the measured deployment,
the live inference responsiveness check, and the browser check. The restart
record stores the SHA-256 hash of each result. The post-restart report contains
the current source manifest and passed 4/4. See the current
[`restart record`](../evidence/bonsai-cold-restart.json) and
[`restart verification run`](../evidence/bonsai-local-product-verification-cold-restart.json).
The manual predecessor and the first automated run remain saved. The first
automated run exposed and preserved a duplicate validator rule that rejected
`$/share` even though the registered rubric accepts it.

These expected answers have not been signed off by a deal-domain owner. Four
synthetic cases are an engineering regression, not an approved transactional
accuracy claim.

## Public deal dossier battletest

The version 1 public dossier set uses the Anaplan and Citrix merger filings and
the 418 page CMA Microsoft and Activision report. Each saved source has a
SHA-256 hash, byte count, and official publisher URL. The HTML parser records
block and table anchors, while the PDF parser records physical page numbers.

The corpus and source fact gates passed. The current live run produced five
accepted Bonsai answers through the bounded retrieval, publication guard, and
signed Buzz path. All five passed the deterministic citation, registered-number,
answer-absence, source-write, and signed-delivery checks. The Citrix absence
case now has an explicit job contract that rejects a valuation multiple as an
entry debt-to-EBITDA multiple. The Anaplan fee case requires both disclosed fee
amounts from one qualifying source passage.

This is not a five-case accuracy pass. All five cases remain semantically
unverified because no qualified domain reviewer has approved primary intent,
evidence meaning, component completeness, or usefulness. The release therefore
remains closed. The runner also fails when Prism returns a signed rejection,
even though the HTTP request succeeded, and the offline v3 verifier binds each
raw Buzz marker, trace, model, and visible answer. The saved response and
verification records are:

- [`bonsai-public-deal-battletest-responses.json`](../evidence/bonsai-public-deal-battletest-responses.json)
- [`public-deal-buzz-event-verification.json`](../evidence/public-deal-buzz-event-verification.json)
- [`first-pass-development-evaluation-v2.json`](../evidence/first-pass-development-evaluation-v2.json)
- [`public-deal-corpus-verification-v2.json`](../evidence/public-deal-corpus-verification-v2.json)
- [`bonsai-public-deal-battletest-failed-agent-loop.json`](../evidence/bonsai-public-deal-battletest-failed-agent-loop.json)

The three v1 corpus verification files originally claimed that a human checked
PDF renders, but no reviewer identity or receipt existed. The records now mark
that field as a superseded, unsupported claim. The correction record preserves
the prior and corrected hashes in
[`public-pdf-visual-claim-remediation-v1.json`](../evidence/public-pdf-visual-claim-remediation-v1.json).
The active v2 record contains only an automated render check and an unrecorded
human review state.

The original corpus v1 placed the CMA PDF at the public-corpus root beside the
Anaplan and Citrix directories. The saved CMA answer cited only the CMA PDF, so
its task-level scoring remains inspectable, but its Buzz room was not isolated
from the other deals. That invalidates the v1 CMA product-scope proof. Corpus v2
places the CMA PDF in its own manifest-bound room and the verifier now rejects
unexpected cross-deal files. The prior Buzz product verification must not be
used as room-isolation evidence.

The failed agent loop record shows the earlier ACP path produced a 58,368 token
tool history and no signed reply. The current web path uses bounded retrieval,
one local model call, citation validation, and one signed Buzz reply.

## Full first-pass public development run

Corpus v2 was used for three complete first-pass product runs: Anaplan, Citrix,
and Microsoft/Activision. Each deal folder exactly matched its manifest scope,
each request invoked `27b@q1_0`, and each model draft failed the v7 evidence
guard after one bounded repair. Prism created three separate evidence-safe
fallbacks with linked rejected-model traces and signed Buzz event IDs. No source
file changed. The CMA fallback cites only the isolated CMA PDF.

This proves three product failure paths, not three model passes. No generated
brief received semantic scoring or domain review, and the artifact fixes
`accuracy_release_passed` to false. See
[`bonsai-first-pass-public-development-v1.json`](../evidence/bonsai-first-pass-public-development-v1.json).

The deterministic comparison path also passed the same four cases in the saved
[`baseline product report`](../evidence/baseline-product-verification.json).
That result is a reviewed-formula regression oracle and is not attributed to an
AI provider. No approved cloud comparison artifact exists.

## Constrained coding pilot

Two version 2 seven-case datasets cover Python generation, editing, generated
tests, allowlisted library use, unsafe code, timeout behavior, and unsupported
languages.

| Set | Dataset SHA-256 | Result | Syntax | Grounded source | Disposition | Mean latency |
|---|---|---:|---:|---:|---:|---:|
| Visible pilot | `aa85698f67cb2048a2b6c519349679f51208fd66701c918ab047266de256e662` | 7/7 | 1.0 | 1.0 over 3 applicable cases | 1.0 | 3,956.72 ms |
| Held-out mutations | `dc179d8839f624d3131528c0f6baeaa2f91f9717817755b3e2c0130fb51714e5` | 7/7 | 1.0 | 1.0 over 3 applicable cases | 1.0 | 3,974.00 ms |

Reports:

- [`bonsai-local-coding-benchmark.json`](../evidence/bonsai-local-coding-benchmark.json)
- [`bonsai-local-coding-holdout.json`](../evidence/bonsai-local-coding-holdout.json)

Six cases in each set invoked Bonsai. The unsupported-language case was handled
by a deterministic policy guard and is not credited to the model. Three cases
are expected to fail execution because they test a bug assertion, unsafe code,
or timeout. Their success means the observed rejection matched the registered
disposition; the raw sandbox-success rate is consequently 4/7.

## Reproduction

After installing Bionic or LM Studio and placing the exact artifact at the path
recorded by the inspection evidence, start and load the runtime:

```bash
$HOME/.lmstudio/bin/lms server start --port 1234 --bind 127.0.0.1
$HOME/.lmstudio/bin/lms load 27b@q1_0 --context-length 16384 \
  --parallel 4 --identifier 27b@q1_0 --yes
```

Set the provider metadata documented in the
[`README`](../README.md), then run:

```bash
python3 scripts/verify_product.py --runtime local --output local-verification.json
./prismctl coding-benchmark --runtime local --output local-coding.json
./prismctl coding-benchmark --runtime local \
  --dataset benchmarks/coding_agent_holdout.json --output local-coding-holdout.json
```

Compare the dataset hashes, provider/model identity, case count, and failures;
do not compare only the aggregate pass rate.

The current
[`clean directory record`](../evidence/clean-directory-baseline.json) copied the
declared project files into a fresh temporary root and ran the complete component
suite with zero skips plus the deterministic baseline workload. The record contains
the exact file and test counts. It checks path
and undeclared-checkout coupling on the same host, and it is not clean-machine
evidence.

The sealed custody and folder preview controls pass in the current complete
component suite with zero skips. The sealed controller keeps the checked in inventory empty, reports
the missing approvals and calibration, and returns before an external secret
loader call. Folder creation requires a separate, hash-bound preview and rejects
source drift before Buzz writes. The final clean-directory and cold-restart
records bind these controls to their source manifests.

## Known limits

The local observability helper has no semantic faithfulness score. Its bounded
lexical check requires exact claim text in both declared source fields and the
response, and it is excluded from faithfulness aggregates. A passing lexical
check does not prove entailment, meaning, or accuracy.

The local table helper reports exact fixture cell matches. It reads the
extracted table and compares table index, row, column, and text. Caller supplied
pass counts are ignored. The helper does not measure general table extraction
accuracy. The forbidden string helper reports exact configured phrase matches,
and it does not measure hallucination rate.

The observability helper separates required field presence from typed field
checks. Field presence does not validate types. The typed check supports named
top level JSON types and rejects missing or wrong values. It does not implement
nested rules, allowed value sets, extra field rules, or full JSON Schema.

- Sample sizes are four deal-room cases and fourteen constrained coding cases.
- No general repository-editing, BFCL, HumanEval, or public benchmark claim was
  measured.
- The fitted context was 16,384 tokens. No 100K-to-262K context claim was tested.
- A text-bearing PDF parser was exercised on the 418 page CMA report. An
  image-only PDF with no embedded text also exercises the bounded Apple Vision
  OCR path on the measured macOS host. Pages 1, 7, and 8 of the CMA report
  were also preregistered as clean 200 DPI image-only accuracy cases. The saved
  run recomputes its scores from raw Apple Vision text. The first corrected run
  measured 0.34 percent word error, 0.08 percent character error, and 20 of 21
  critical phrases. The cover page read `CMA` as `CMAY`. A resolution sweep on
  the unchanged image-only page returned `CMA` at 150 DPI and at every tested
  setting from 250 through 600 DPI. The product OCR raster was then changed
  from 200 to 300 DPI. The current run measured 0.11 percent word error, 0.04
  percent character error, and all 21 critical phrases. The source, derivatives,
  expected text, raw output, prior failed evidence, and scores are hash bound.
  The thresholds did not change, and no document-specific words were added.
  The implementation team used the same pages to select the change, so the pass
  is development regression evidence. The small clean-raster slice does not
  cover natural scans, and no independent reviewer approved its labels. OCR reading order, tables,
  columns, merged cells, and document layout remain unverified. Bounded
  XLSX ingestion now passes parser and live private-folder HTTP guards, including
  sheet values, cell coordinates, formula-state disclosure, and external-link
  rejection. Retrieval admits XLSX sheets, and chat and first-pass publication
  fail when an XLSX-derived claim hides that formulas are cached and were not
  recalculated. A bounded audited formatter covers simple decimals, grouping,
  currency, percentages, and `x` multiples while preserving raw values. It does
  not provide full Excel formatting parity; unsupported formats remain raw. A
  separate nine-case preregistered regression checks this exact contract and a
  wrong-expected-display mutation proves its evaluator can fail. The expected
  displays are spec-derived test data, not an independent spreadsheet renderer.
- No cloud comparison was run because no approved cloud provider was configured.
- No VRAM, energy, power, network-egress, or clean-machine portability result
  was measured.
- On the measured macOS host, generated Python runs under the AST checks,
  subprocess resource limits, and an operating system profile. The profile
  denies child network access, process forks, and reads under `/Users`,
  `/Volumes`, and `/Network`. It also denies the resolved current project and
  selected deal-room roots when needed and records the effective roots in the
  trace. It confines writes to the temporary run directory. Other readable
  system paths remain available, so it is not a hardened multi tenant boundary.
- A replayable Chromium check passed on 2026-08-15. It checks the saved Titan
  trace, model status, measured deployment card, separation of artifact identity
  from current-process invocation, review control, inline citations, exact source
  passage, browser errors, and HTTP errors. Its 18 assertions bind the visible
  deployment state to the saved record hash. They also prove that an answer
  awaiting domain review is shown as `Review pending`, not as rejection or
  acceptance. The JSON record and hashed screenshot are in
  `evidence/browser-first-pass-v7.json` and
  `evidence/browser-first-pass-v7.png`. Cross browser checks, assistive
  technology review, WCAG conformance, clean physical machine setup, and deal
  domain review remain open.
- A live concurrency check sent one real Bonsai workbook request through the
  signed Buzz path while probing `/api/status`. All 367 probes made during the
  request passed. The slowest probe took 135.802 ms, and the request completed
  in 36,894.524 ms. This is a prototype responsiveness guard. It is not a load
  test or production service objective. See
  `evidence/live-inference-concurrency-v1.json`.
- A second Chromium check passed on the acquired Zendesk SEC filing. It binds
  a four-part answer to the filing hash, signed Buzz event, canonical
  discussion URL, four exact source blocks, and screenshot. It also verifies that the
  local room registration predates the current Prism process, so the canonical
  room survived a server restart. The status shown in the browser identifies
  the model evidence as prior trace history and does not claim that the current
  process invoked it. Prism restored the raw answer event and verified its
  NIP-01 identity, BIP-340 signature, channel, author, and payload before the
  browser displayed a verified signature state. The browser also verified that
  the rendered digest matches its signed kind 40100 canvas event. All 21
  assertions passed. The earlier broad answer and first multi-part retry remain
  visible failures. The JSON record and screenshot are
  `evidence/browser-real-deal-zendesk-v1.json` and
  `evidence/browser-real-deal-zendesk-v1.png`. The four-part result passed a
  structural publication guard. It is not a benchmark case or accuracy release.
- A third Chromium check passed on the source review workshop. It renders the
  source review, case approval, registration, and accuracy release gates from
  the server API. It also confirms that decisions remain unselected and export
  remains closed with an empty reviewer roster. The JSON record and screenshot
  are `evidence/browser-source-review-v1.json` and
  `evidence/browser-source-review-v1.png`. The record shows zero eligible
  drafts, zero candidate registrations, and a blocked accuracy release. Its 14
  assertions bind the rendered queue to the current packet hash and show a
  cross-document draft with evidence from both admitted source hashes.
- A fourth Chromium check passed on the case authoring workshop. It confirms
  that no draft opens before source review clears it, all owner controls remain
  disabled, no evaluation slice is selected, and unsigned export remains
  closed. The JSON record and screenshot are
  `evidence/browser-case-authoring-v1.json` and
  `evidence/browser-case-authoring-v1.png`. The record has seven passing
  assertions and does not claim a case approval or accuracy result.
- A fifth Chromium check passed on the blinded output review workshop. It
  confirms that all five development responses are visible without model or
  provider identity, all human judgments start empty, and export remains closed
  with the empty reviewer roster. Its 12 assertions bind the packet, rubric,
  calibration state, and screenshot hashes. It does not claim a signed review,
  judge calibration, or accuracy release. The files are
  `evidence/browser-output-review-v1.json` and
  `evidence/browser-output-review-v1.png`.
- A separate synthetic Chromium fixture proves the enabled output review path.
  It completes all 25 labels across five cases and downloads a schema valid
  unsigned record. The fixture is bound to the current packet, response hashes,
  and screenshot. Its reviewer names and keys are synthetic, and its evidence
  states that no human review or release occurred. The files are
  `evidence/browser-output-review-completion-fixture-v1.json` and
  `evidence/browser-output-review-completion-fixture-v1.png`.
- An eighth production-state Chromium check passed on the pricing proof
  workspace. Its fifteen assertions verify the exact `not_recorded` buyer evidence
  state, all ten commercial gates, the accepted-review value unit, and the
  boundary that public demos count as zero willingness-to-pay evidence. The
  surface also states that Prism must restore the exact buyer event from Buzz.
  JSON record and hashed screenshot are
  `evidence/browser-pricing-poc-v1.json` and
  `evidence/browser-pricing-poc-v1.png`. This verifies the POC contract and
  empty state. It does not claim customer research, a price, or revenue.
- A separate eleven-assertion synthetic Chromium fixture fills the pricing form
  and downloads the unsigned record. The screenshot carries a visible fixture
  banner, the record has no buyer attestation, and the server evidence remains
  `not_recorded`. The files are
  `evidence/browser-pricing-poc-completion-fixture-v1.json` and
  `evidence/browser-pricing-poc-completion-fixture-v1.png`.
- A sixth Chromium check passed on the signed Zendesk answer. It has 18
  assertions for semantic tab state, keyboard navigation, visible focus,
  citation focus, dialog focus, reduced motion, target size, and mobile width.
  It is saved in `evidence/browser-accessibility-zendesk-v1.json` with a hashed
  screenshot. It is an automated accessibility smoke check, not WCAG
  conformance or assistive technology review.
- A seventh browser record passed in Firefox 153 and WebKit 26.5. Each engine
  opened the same signed Zendesk answer, checked all four labels and citations,
  used keyboard tab and citation navigation, moved focus to the exact source,
  and checked mobile width. All 16 combined assertions passed with no browser
  or HTTP errors. The record and screenshots start with
  `evidence/browser-cross-engine-zendesk`. WebKit does not count as a Safari
  application test. Branded Chrome, Edge, and extensions remain untested.
