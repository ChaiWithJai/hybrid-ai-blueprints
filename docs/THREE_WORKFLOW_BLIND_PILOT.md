# Three workflow blind pilot

Status: ready for candidate generation and participant scheduling  
Version: 1.0  
Date: August 16, 2026  

## Decision this pilot must support

This pilot will decide where PrismML should invest after the current product
surface. The allowed choices are model quality, retrieval, interface design,
document fidelity, and deployment security.

The pilot does not certify Bonsai, approve a price, or support an accuracy
release. It produces observed product and pricing evidence from a small group
of real users.

## Frozen product surface

The product surface is frozen for this pilot. No new verifier features, review
roles, benchmark routes, or workflow controls will be added during the study.

The frozen baseline is:

| Item | Frozen value |
| --- | --- |
| Product | Prism Vault v0 in the existing Buzz backed web workspace |
| Evaluation surface | Review queue and Eval lab inside the same room Evaluation tab |
| Surface asset version | `hybrid-eval-lab-v1` |
| Main job | Review an authorized deal room and support an advance, pause, or stop decision |
| Local model | Bonsai 27B through the recorded LM Studio runtime |
| Canonical verification file | `evidence/bonsai-local-product-verification-current.json` |
| Engineering source manifest | `9f0e33c63d354b625d38789b6e18f2ef87a4c24add377f610088d3c765bbdc1c` |
| Automated tests | 519 passing and 0 skipped |
| Human domain reviews | 0 complete |
| Buyer pricing records | 0 complete |
| Accuracy release | Not approved |

Only defects that prevent a participant from finishing the study may be fixed.
Every such fix must be logged. A fix that changes an answer, prompt, evidence
packet, or candidate presentation ends the affected comparison and requires a
new candidate set.

## The three workflows

The cases are public development cases. They are not sealed test data. Each one
tests a different part of a real deal review.

| Workflow | Registered case | Question | What it tests |
| --- | --- | --- | --- |
| Diligence chronology | `anaplan_vdr_timeline` | When did Anaplan open its virtual data room, what categories of material did it contain, and when did the intensive diligence period end? | Date accuracy, multi part extraction, and evidence navigation |
| Financing stack | `citrix_financing_mix` | What financing mix did Vista and Elliott disclose for the Citrix deal? State debt, preferred equity, and common equity separately. | Critical numbers, category separation, named parties, and evidence quality |
| Regulatory finding | `cma_competition_conclusion` | What did the CMA conclude for console gaming and cloud gaming, and what cloud gaming market share did it estimate for Microsoft? | Opposing conclusions, a critical percentage, PDF handling, and decision usefulness |

These workflows do not represent the full first pass underwriting benchmark.
They are a small product study that covers chronology, capital structure, and a
regulatory decision.

## The three candidate modes

Each mode receives the same frozen folder snapshot, exact question, output
contract, evidence packet, context limit, and response length limit.

| Mode | Candidate generation |
| --- | --- |
| Bonsai | Prism retrieval and document extraction produce the evidence packet. Bonsai 27B writes the answer locally. |
| Cloud | The approved cloud model receives only the same evidence packet and answer instructions. No private source leaves the local system unless the existing cloud consent path is configured and used. |
| Hybrid | Bonsai writes a local draft. The approved cloud model reviews that draft against the same evidence packet and returns a revised answer with a correction note. |

The cloud provider is not configured in the current evidence. Cloud and hybrid
candidates must remain missing until the existing policy and data owner consent
path authorizes a real provider call. A copied, simulated, or manually written
cloud answer does not count.

Use temperature zero when the provider supports it. Record the provider, model,
prompt hash, source snapshot hash, evidence packet hash, output hash, start
time, end time, token counts when available, and every runtime error.

## Candidate output contract

Every candidate must use the same structure:

1. Direct answer.
2. Material facts with source citations.
3. Missing or conflicting information.
4. Decision effect for the deal team.

Do not add model names, runtime details, speed, or cost to the candidate output.
Do not repair one candidate by hand. If a generation fails, record the failure
and keep it in the results.

## Blind review protocol

Babak, Omead, Sahin, Reza, or equivalent participants review the same nine
candidate outputs. This document does not claim a qualification for any named
person. The study owner must record each participant's actual role and relevant
experience before the session.

For each workflow, assign the three candidates to A, B, and C with a new random
order. Keep the mapping in a separate locked file. Publish its hash before the
first review. Reveal the mapping only after all review and pricing forms are
locked.

Each person reviews independently. Group discussion starts only after every
form is submitted. Candidate order should rotate between participants when the
review tool permits it.

The session order is:

1. Explain the deal task and scoring anchors without naming candidate modes.
2. Open the same canonical workflow and source links for every participant.
3. Start the timer when the first candidate appears.
4. Let the participant inspect citations and source material.
5. Stop the timer when the participant locks a decision and review.
6. Repeat for all three workflows.
7. Run the pricing interview immediately, before candidate identities or group
   opinions are revealed.
8. Lock the review and pricing records.
9. Reveal the candidate mapping.
10. Hold the group discussion and record interpretation separately.

## What reviewers record

The review form is at `docs/pilot/BLIND_REVIEW_FORM.md`. Record these measures
for every candidate:

| Measure | Required record |
| --- | --- |
| Time | Seconds from candidate open to locked decision |
| Corrections | Count and explain every critical, major, and minor correction |
| Evidence quality | Score from 1 to 5 using the anchors below |
| Decision usefulness | Score from 1 to 5 using the anchors below |
| Decision | Advance, pause, stop, or insufficient evidence |
| Confidence | Score from 1 to 5 |
| Candidate preference | Forced rank of A, B, and C for the workflow |
| Workflow preference | Forced rank of the three workflows after all reviews |

Evidence quality anchors:

| Score | Meaning |
| ---: | --- |
| 1 | Material claims lack usable evidence or cite the wrong source passage. |
| 2 | Some evidence is usable, but important claims are unsupported or hard to verify. |
| 3 | Material claims are mostly supported, with corrections or navigation effort required. |
| 4 | Material claims are supported by clear citations with little correction. |
| 5 | Every material claim is easy to verify from the cited source and no material correction is needed. |

Decision usefulness anchors:

| Score | Meaning |
| ---: | --- |
| 1 | The answer cannot support the stated deal task. |
| 2 | The answer gives limited help and needs major expert repair. |
| 3 | The answer helps, but an expert must correct or complete important parts. |
| 4 | The answer supports the decision with limited expert correction. |
| 5 | The answer is ready for the stated first pass decision after normal review. |

Correction severity follows the benchmark contract. A critical correction can
change the deal decision or create unsupported confidence. A major correction
leaves a required part incomplete or makes review materially harder. A minor
correction changes presentation but not the supported conclusion.

## Pricing exercise after use

The pricing interview is at `docs/pilot/PRICING_INTERVIEW.md`. Run it as soon as
the participant finishes the three workflows. Do not show candidate identities,
other participants' opinions, or a proposed PrismML price first.

Madhavan Ramanujam and Georg Tacke's method places customer value and willingness
to pay inside product development. The product should be designed around what a
customer values and will pay for, not priced only after it is built. This pilot
therefore asks about the valuable result, value unit, package, and willingness
to pay while the workflow is fresh.

The current PrismML instrument asks for an acceptable price, an expensive but
still considered price, and a prohibitively expensive price. These three
questions are PrismML's study instrument. They are not presented as a named or
proprietary Ramanujam survey method.

The interview must also record a paid next step or a concrete reason to decline.
A high stated price without budget authority or a paid next step remains a
hypothesis.

Authoritative background:

* [Simon Kucher history of Monetizing Innovation](https://www.simon-kucher.com/en/who-we-are/our-story)
* [Simon Kucher interview with Madhavan Ramanujam](https://www.simon-kucher.com/en/insights/taking-companies-next-level-nine-questions-unicorn-whisperer-madhavan-ramanujam)
* [Simon Kucher description of building products around price](https://www.simon-kucher.com/en/insights/mastering-product-innovation-strategies-market-leadership-and-growth)

## Preset investment decision rules

Do not combine every measure into one score. Use correction logs and observed
behavior to locate the failure.

| Next investment | Select when this pattern appears |
| --- | --- |
| Model quality | Candidates receive the same evidence, but Bonsai has more critical or major corrections and lower usefulness than cloud across at least two workflows. |
| Retrieval | All three modes miss the same needed passage, or participants repeatedly leave the answer to search for evidence that the packet omitted. |
| Interface design | Answers and citations are adequate, but participants lose time finding, comparing, or discussing them in the workspace. |
| Document fidelity | Errors cluster in PDF reading order, tables, scans, page locations, or source layout before answer generation. |
| Deployment security | Participants or buyers reject cloud use, require local control, or condition a paid next step on isolation, audit, access control, or deployment policy. |

Select an investment only when at least three of four participants agree, or
when the median measures and correction records show the same pattern across at
least two workflows. If the evidence splits, run one targeted follow up on the
disputed layer. Do not expand the whole verifier.

Pricing and product results answer different questions. Candidate preference
shows which workflow people trust. Pricing evidence shows whether a buyer values
the result enough to fund it. Both are required before an investment claim.

## Completion criteria

The pilot is complete only when:

1. The evidence bundle has been refreshed once against the frozen source
   manifest.
2. All nine real candidate outputs exist, or a real failed generation is
   recorded.
3. At least four qualified participants independently submit complete blind
   reviews.
4. Every participant completes the pricing interview immediately after use.
5. Candidate identities are revealed only after the records are locked.
6. The result names one next investment area or states that the evidence is
   split.
7. The report preserves negative results and does not claim benchmark or pricing
   proof beyond the study.

## Known limits

The three cases are public development cases and may be familiar to the team.
They do not measure private folder transfer, broad deal coverage, production
security, or market wide willingness to pay. The next commercial proof still
requires at least two authorized private historical deal rooms, including one
unchanged transfer case, under the existing pricing contract.
