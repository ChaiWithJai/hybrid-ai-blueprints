# Ten benchmark decisions reality audit

Updated: August 16, 2026

This audit reconciles the ten decisions in
`FIRST_PASS_UNDERWRITING_BENCHMARK.md` with executable evidence. A written
contract is not counted as a completed gate. Human, buyer, cloud, and sealed
test evidence stay open until the named outside party supplies it.

The same ten decisions are now returned by `/api/benchmark/pipeline` and shown
in the source review workspace. The server derives the current counts, roster
states, calibration state, sealed controller state, oracle diagnostic state,
pricing evidence state, and cryptographic governance receipts from the current files. The
browser record binds all ten cards to that API response. Editing a saved card
or its release state makes evidence validation fail.

Owner names and approval booleans in the benchmark manifest have no authority.
They were removed. The governance ledger starts unconfigured and contains zero
receipts. A governance root must assign the product, domain, strategy, and
security roles with four distinct actor IDs and four distinct keys in one
root-signed Buzz event. The root key cannot also act as a role key. Each
assigned role must then sign
the benchmark contract, release thresholds, and sealed test opening scopes.
Every receipt contains the exact benchmark material hash. Changes to the
manifest, rubric, schemas, sealed public inventory, or sealed controller make
the receipts invalid. The current state is 0 of 12 required receipts.

The source review workspace now shows the same governance state as a three by
four matrix. Each row is a signed scope and each column is an independently
assigned role. The page shows all three current material hashes and the local
trust root limitation. It has no private key input and cannot create an
approval. The browser record binds the matrix to the current server result.

| Decision | Executable evidence now | Current state | Work still required |
| --- | --- | --- | --- |
| 1. Job under certification | The private-folder and Buzz workspace produce a bounded first-pass brief with a stated investment screen, citations, trace, and review state. The product and domain approvals must be signed and bound to the benchmark material. | Product path verified. Governance is unconfigured and job approval is open. | The assigned product owner and domain owner must sign the exact contract scope. |
| 2. Label authority | Reviewer rosters, signed Buzz admissions, blinded submissions, principal adjudication, and case registration fail closed. | Control path verified. Zero qualified reviewers or submissions recorded. | Configure a real authority, admit qualified reviewers, and receive independent labels. |
| 3. Error severity | The case schema and rubric keep critical, major, and minor errors separate. Critical gates cannot be averaged away. | Contract verified. Domain assignments unapproved. | Domain reviewers must confirm severity for each case and correction. |
| 4. Dataset size and coverage | The manifest counts registered cases and deals separately from the 319 candidate drafts across 29 acquired deals. Task-family capacity checks fail if any target family cannot be filled. | 5 of 120 cases, 3 of 30 deals, and 0 domain approvals. | Review, approve, and register enough cases. Meet absence, calculation, cross-document, conflict, and ingestion-form slices. |
| 5. Leakage control | Deal and near-duplicate family split guards are executable. The sealed controller fails before reading a secret and consumes a contacted version. | Public development controls verified. Sealed inventory empty. | Custodian approval, sealed cases, frozen system hashes, and one authorized opening are required. |
| 6. Model roles | Saved records distinguish answer model, deterministic evaluator, human-required dimensions, and signed delivery. The local runtime stores exact Bonsai identity. | Bonsai and deterministic development evidence exist. Human, independent judge, cloud, and ternary comparisons are absent. | Calibrate a judge against qualified human labels. Add approved cloud and ternary comparisons when allowed and available. |
| 7. Failure localization | `core/oracle_context_diagnostic.py` reruns four answer cases with their registered passages. The Citrix absence case also uses a complete two-file audit across 2,401 parsed nodes and three disclosed direct-disclosure patterns. Raw responses and deterministic checks are recomputed. | All five cases completed. Two passed the narrow probe. The Citrix financing answer dropped its citation. The Citrix absence answer supplied both absence phrases but dropped its citation. The CMA failure persisted. Semantic localization remains unverified. | Domain reviewers must approve the absence decision and pattern coverage. Add approved semantic labels before assigning retrieval or generation fault for meaning and completeness errors. |
| 8. Private data and evaluation records | The local JSONL trace store records hashes, model identity, timing, evaluations, review states, and a verified hash chain. Cloud context requires separate consent. | Local vendor-neutral record verified. | Approve retention and access policy before adopting an external Arize deployment. Prove customer data handling with an authorized private pilot. |
| 9. Required comparisons | The same synthetic engineering cases run against the deterministic baseline and local Bonsai configuration. Runtime metadata and source manifests are stored. | Narrow engineering comparison verified. Release comparison incomplete. | Run the approved labeled set with frozen evidence and budgets. Add cloud and ternary models only under the stated policy and availability conditions. |
| 10. Release thresholds | The verifier preserves hard gates, reports missing inventory, and blocks sealed opening and release. The release threshold scope requires four role signatures over the current material hash. Judge calibration and pricing evaluators have negative controls. | Proposed thresholds are executable as blockers. Zero signed governance receipts and no release result exist. | Product, domain, strategy, and security owners must sign the threshold scope. Human calibration, sealed testing, and buyer value evidence must then pass without changing it. |

## Oracle-context finding

The current live oracle-context run completed all five registered cases. The
entry leverage case scans both registered Citrix files. The scan covers 2,401
parsed nodes and three direct-disclosure patterns. It also keeps three
confusable anchors visible. The patterns were written after the team inspected
the development corpus, so zero matches do not prove semantic absence.

The Anaplan timeline and termination-fee answers passed the literal citation
and number probe. The Citrix answer contained the three registered amounts and
named Elliott, but it omitted the required citation. This was worse than its
normal saved response under the narrow deterministic contract.

The Citrix entry leverage answer included both required absence phrases, but
it omitted the required citation. The deterministic probe therefore failed.
The saved audit proves that every registered file and parsed node was checked
against the disclosed patterns. It does not prove that the pattern set covers
every equivalent disclosure.

The CMA answer omitted its citation and did not reproduce the registered
`60 to 70 percent` form. More importantly for later human review, the raw answer
said the opposite of the supplied page about which gaming market had the
substantial-lessening-of-competition finding. This observation is preserved as
development failure evidence. It is not promoted to an approved semantic score
because the current development labels have no domain approval.

The saved record is
`evidence/bonsai-oracle-context-diagnostic-v1.json`. Its validator recomputes
the prompt hash, passage hashes, response hash, probes, and localization from
the raw record. Editing a raw response or a saved score makes validation fail.

## Decision

The ten-question design is coherent, but it is not a completed benchmark. The
live surface reports 0 of 10 release decisions satisfied. Decisions 1 through
10 now have either an executable boundary or an explicit outside evidence
requirement. The remaining work cannot be replaced by more synthetic
signatures, self-review, or implementation-selected labels.
