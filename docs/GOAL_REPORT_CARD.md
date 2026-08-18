# Goal report card

Date: August 18, 2026

## Goal

Point Prism at a deal room and give the team one thoughtful web workspace for
reading sources, checking citations, discussing the deal, and asking Bonsai a
source bound question. Measure retrieval, generation, agent workflows, and chat
failures without turning development checks into an accuracy claim.

## Overall grade

The current v0 surface is A minus. The evaluation framework and review
instrument are B plus. The full product and commercial goal is C because human
error discovery, a blind cloud and hybrid comparison, and the pricing exercise
remain open.

## Foundations

| Foundation | Grade | Evidence | Open work |
| --- | --- | --- | --- |
| Product job | A | The root job is to decide Advance, Pause, or Stop and name the next action. Sixteen segments and at least 50 phrases have owners and written defenses. | Test the job and words with deal professionals. |
| Deal room surface | A minus | Overview, Sources, Activity, and Evaluation support one stable room URL. The composer remains available in all four views. | Observe the path with people who have reviewed deal rooms. |
| Source rendering | A minus | Markdown uses headings and tables. CSV renders 31 rows as a table. The Project Titan JSON renders 55 structured fields and two lists. | Test natural PDFs, spreadsheets, scans, and large JSON files. |
| Citation journey | A minus | A citation opens an in place dialog on the exact passage. The reader can ask about the passage or open the exact full source. Keyboard focus, Escape restoration, and mobile layout pass. | Run assistive technology and human usability review. |
| Activity and chat | A minus | Four human conversation messages remain in the main stream. Thirty four workflow events are grouped behind **Show history**. Raw citation wrappers are hidden. | Human review of message density, labels, and long conversations. |
| Verification | A minus | The full Python suite passes 519 tests. The live room switches between Review queue and Eval lab on the same URL with no browser errors. The Eval lab has no horizontal overflow at 390 pixels. | The full historical product verifier still needs a final run against all saved evidence. Automated checks are not human review. |
| RAG evaluation | B | Six mapped questions report Recall at k 1.0 and mean reciprocal rank 1.0. The two document case retrieves both passages. One saved Bonsai answer passes separate grounding and relevance checks. Both negative controls fail as expected. | Add private and public deal rooms, more natural questions, generation cases, and domain labels. |
| Agent workflow evaluation | B | Three recorded workflows pass end to end and at each named transition. | Add unknown tasks, tool errors, longer sessions, and efficiency measures. |
| Chat error discovery | B | Evaluation is part of the Prism room and reads the same 38 Buzz events as Activity. Ten diverse traces load with context, saved Pass, Fail, or Defer judgments, free text notes, a coverage map, breadth sampling, a depth gate, and separate agent suggestions. An isolated browser run verified five rapid saves across reload. | Zero canonical human annotations exist. Run free text review and update the failure taxonomy. |
| Evaluation observability | B | Local Phoenix accepted one marked synthetic chain with five OpenInference evaluator spans from the room API. The spans preserve hashes, exclude content, and identify their source as `synthetic_fixture`. | Export genuine review spans only after people review the traces. Decide retention and access policy before any remote collector is allowed. |
| Hybrid evaluation lab | B plus | The room Evaluation view now shows local, cloud, and hybrid route states, release gates, experiment history, evaluator trust, Bonsai judge calibration, seven evidence layers, buyer measures, and explicit truth boundaries. Missing evidence is shown as Not measured. An append only hash chained ledger records experiment definitions and paired runs. | Generate the real cloud and hybrid candidates after consent. Populate the ledger with the three frozen workflows. |
| Semantic judge science | B | Four narrow versioned Bonsai judge criteria have strict JSON output, hidden route identity, classifier metrics, dangerous false pass counts, parse failure reporting, bias correction, and bootstrap intervals. General trace labels cannot be reused as criterion calibration labels. | Collect balanced criterion specific labels and validate each judge on its held out test split. Bonsai remains untrusted for release. |
| Commercial proof | F | The pricing contract and empty state exist. | Run Madhavan's exercise after blinded product use. |

## Milestones

| Milestone | State | Exit rule |
| --- | --- | --- |
| 1. Freeze the v0 information architecture | Complete | Overview, Sources, Activity, and Evaluation are the primary room views. Evaluation is not a separate application. |
| 2. Render supported sources | Complete for the Project Titan fixture | Markdown, CSV, and JSON render in readable native forms without raw preformatted blobs. |
| 3. Complete the citation journey | Complete for the tested path | Preview stays in context, chat inherits the citation, and full source opens the exact anchor. |
| 4. Polish Activity and chat | Complete for the tested path | Human messages remain prominent, workflow events are grouped, and the composer is present in every primary view. |
| 5. Refresh surface evidence | Complete | Current Chromium, accessibility, Firefox, WebKit, mobile width, focus, and browser error checks pass. |
| 6. Build the three track benchmark | Complete as development evidence | RAG, agent workflow, and chat error discovery artifacts run from versioned inputs with negative controls. |
| 7. Build the human review surface | Complete for the local pilot | The native room Evaluation view loads ten full traces with Pass, Fail, Defer, free text notes, suggestions, a coverage map, saved progress, and serialized record updates. The browser run uses isolated synthetic labels and does not count as human review. |
| 7A. Connect evaluation observability | Complete for the local pilot | Phoenix displays one chain and five marked fixture evaluator spans. Content remains excluded, and the receipt makes no human review claim. |
| 7B. Add the native hybrid Eval lab | Complete for the frozen surface | The existing room Evaluation tab compares truthful local, cloud, and hybrid states, tracks experiments, shows judge calibration and buyer evidence, and never creates a second user-facing application. |
| 8. Run human error discovery | Not started | Reviewers label the sample, identify first failures, revisit earlier traces, and reach failure mode saturation. |
| 9. Run blinded domain review | Not started | The same Bonsai, cloud, and hybrid outputs receive blind review from the named domain roles or approved equivalents. |
| 10. Run the pricing exercise | Not started | Run Madhavan's pricing questions immediately after use and record buyer authority, range, conditions, and paid next step. |
| 11. Make the investment decision | Not started | Use the results to choose model quality, retrieval, interface design, document fidelity, or deployment security. |

## Current decision

Keep the four view room surface frozen. The evaluation framework is now visible
inside that room, so the next useful evidence comes from human review of the ten
traces and blinded use of the three deal workflows. Do not expand the verifier
until the review shows which failures deserve more cases.

The benchmark method is documented in
[`WORKSPACE_EVAL_DESIGN.md`](./WORKSPACE_EVAL_DESIGN.md). The implementation
learning record is
[`EVAL_AWAKENING_JOURNAL.md`](./EVAL_AWAKENING_JOURNAL.md).
