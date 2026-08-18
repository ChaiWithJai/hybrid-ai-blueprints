# Prism Vault v0 Surface Contract

Current scope: customer demo  
Current page contract: [`DEMO_INFORMATION_ARCHITECTURE.md`](./DEMO_INFORMATION_ARCHITECTURE.md)

Accuracy certification and commercial proof are outside the current demo goal.
Their routes and records remain available for historical inspection, but they
do not appear in the main navigation or control completion.

## Product boundary

The v0 surface is a browser workspace backed by a real Buzz community relay.
Buzz is the shared system of record. Prism supplies the deal-room parser,
Bonsai agent persona, domain workflows, evaluation records, and browser view.

The dominant product task is to decide whether to advance, pause, or stop a
deal, and know what must happen next. Sources, Activity, Decision notes, and
Technical details support that task. The current product contract is
[`DEMO_INFORMATION_ARCHITECTURE.md`](./DEMO_INFORMATION_ARCHITECTURE.md).

The mapping is deliberately small:

| Product concept | Buzz primitive | Browser route |
| --- | --- | --- |
| Prism deployment | One Buzz community/relay | `/` |
| Private deal room | One private Buzz stream channel | `/rooms/{room_id}` |
| Team discussion | Signed channel messages and threads | `/rooms/{room_id}/discussion?event={event_id}` |
| Canonical deal digest | Channel canvas, Markdown | `/rooms/{room_id}/digest` |
| Reviewable finding | Root message plus replies | `/rooms/{room_id}/findings/{event_id}` |
| Bonsai 27B | Buzz bot member through `buzz-acp` + `buzz-agent` | Visible model/runtime status |
| Evidence | Prism trace linked from the Buzz event | `/runs/{trace_id}` |
| Benchmark source review | Hash bound draft queue and signed Buzz attestations | `/benchmark/source-review` |
| Benchmark case authoring | Reviewed source contract and unsigned domain owner approval | `/benchmark/case-authoring` |
| Blinded output review | Five development responses, explicit human labels, and one unsigned review export | `/benchmark/output-review` |
| Benchmark promotion status | Server derived review, recorded approval, registration, and release gates | `/api/benchmark/pipeline` |

Prism never serves the selected folder as a public directory, and room setup
does not publish source file bytes. Prism parses the folder locally. Messages,
generated briefs, citations, and reviewed canvases can contain deal facts, and
Buzz stores that published content as signed events on the configured relay.

## Minimum lovable journey

1. **Open a room.** The operator points Prism at an absolute local folder. The
   product previews supported files and warnings before creating the room.
2. **Set the screen.** The operator records the investment screen and chooses
   advance, pause, and stop as the available recommendation states.
3. **Run the first pass.** Bonsai produces the required brief sections, source
   evidence, calculations, risks, and unknowns. The run is stored as a signed
   Buzz event and trace.
4. **Inspect the evidence.** Selecting a material claim opens the cited local
   source anchor or PDF page without changing the room URL.
5. **Review and correct.** A deal professional accepts or edits each finding,
   The configured local operator records critical and major corrections and
   makes the room decision. The Buzz event is bound to the operator key; this
   does not count as independent benchmark domain review.
6. **Discuss with the team.** Humans and `@Bonsai` use the room thread to ask
   follow-up questions. The messages remain signed Buzz events.
7. **Publish the operator review.** An accepted Bonsai draft can become the
   locally reviewed first-pass canvas. A deterministic source-excerpt packet
   can receive an operator review, but the signed message and canvas continue
   to call it a source evidence packet. Review cannot rename it to a brief or
   turn the rejected model run into a pass.
8. **Share a canonical URL.** A room, brief, finding, source, or run URL opens
   the same durable object for another authorized member.

If the Bonsai candidate fails a deterministic evidence guard, Prism keeps that
model trace rejected and builds a separate evidence-safe fallback. The fallback
contains a conservative system `PAUSE`, bounded source excerpts, exact citation
anchors, explicit retrieval limits, and standard review questions. It is
labeled as authored by the deterministic evidence renderer. Operator review of
the fallback updates only its trace and publishes a reviewed source evidence
packet. It cannot convert the failed Bonsai trace into a pass or the packet
into a first-pass underwriting brief.

## Design constraints

- The default view has one dominant task: run or review the first pass brief.
- A failed model run still yields a reviewable evidence surface without
  presenting deterministic excerpts as model output.
- Navigation names objects people recognize: Rooms, Digest, Files, Evidence.
- Progressive disclosure keeps model internals and traces out of the main chat.
- Every action has a visible state and a reversible result where possible.
- The layout uses a restrained material palette, generous negative space,
  rounded continuous surfaces, and few controls. Decoration does not compete
  with deal evidence.
- No surface says air-gapped, measured, invoked, or shared unless the matching
  evidence exists at runtime.

## v0 acceptance criteria

Each item follows the postmortem anti-facade rule: claim, artifact, adversarial
check, and decision.

| Claim | Artifact | Adversarial check | Decision |
| --- | --- | --- | --- |
| A room is Buzz-backed | Channel ID and independently verified raw Nostr events in a saved run | Alter the displayed payload or raw signature, and require the room message request to fail | Automated |
| The optional direct Buzz ACP cannot cross room boundaries | With `--direct-acp`, require an exact room/channel/folder scope, exact subscription confirmation, one process, owner-only input, and disabled memory | Change the room binding, subscribe globally, leave an older ACP process running, send from a non-owner identity, or stop the process; startup must fail or Prism must stop | Automated scope guard only; response behavior remains experimental |
| The announced surface has its real dependencies | Same-host preflight record covering Docker, Compose, Buzz tools and relay, private key permissions, exact loaded Bonsai instance, and reasoning-off capability | Leave the model in the LM Studio catalog but unload every matching instance, or make the ACP agent exit during startup | Automated |
| Deployment identity is visible without implying invocation | Evidence tab shows current file-bound artifact identity separately from configured provider and current-process trace state | Tamper with an artifact or deployment-record hash, or report verified artifacts as a current model call; the verifier must fail | Automated and replayed in Chromium |
| A restored first pass came from Bonsai and the claimed room | Verified agent event plus one persisted trace with the same event ID, room, model, guard, mode, citation count, response, server-derived room classification, provenance binding, and full folder snapshot | Publish a valid human signed marker, copy an agent marker, alter any provenance field, or change the current folder; Prism must ignore it | Automated |
| The investment screen changes the evidence set | Screen-matched passages carry an explicit retrieval reason and reserve space in the bounded context | Fill generic topics with higher-scoring passages and place the requested issue only in a nested source; the requested source must still reach the model and evidence fallback | Automated against a real folder plus ranking-pressure unit control |
| A first pass is bound to one folder snapshot | The trace and response record the exact preview hash observed before inference | Mutate a nested source during model generation or fallback retrieval; Prism must publish no agent draft and record a rejected source-snapshot trace | Automated HTTP mutation guard |
| A URL is canonical | Reloaded room, discussion event, finding, or digest resolves from Buzz state | Register a local folder, restart Prism, clear browser storage, and reopen the URL | Automated |
| Room setup does not upload source files | The initial signed canvas contains room metadata, supported file count, and the data boundary notice | Seed a source file with a sentinel and prove that room setup never receives or publishes its payload | Automated |
| A fixture cannot look like customer data | The room API and visible header classify built-in rooms as synthetic. An acquired room is public only when its complete visible file set matches checked-in paths, byte counts, and SHA-256 values. Other folders are operator selected | Rename a fixture, add an unregistered file under a public path, or alter registered bytes. The classification must stay synthetic or become an integrity failure, never customer or public evidence | Automated plus Chromium replay |
| Folder preview is a real gate | Hash-bound supported-file inventory, parser warnings, and a visible second confirmation; preview records `buzz_write_performed: false` | Omit the preview hash or change a supported source after preview; room creation and Buzz writes must fail | Automated plus Chromium replay |
| Published analysis has a visible retention boundary | Files page and initial room canvas state that Buzz retains messages, generated briefs, citations, and reviewed canvases | Remove the disclosure from either public surface and fail the static contract | Automated |
| Citations are grounded | Trace maps every cited filename to the indexed folder snapshot | Delete or rename a cited source and rerun | Automated |
| A multi-part chat answer covers the request and one unchanged room | Detected parts, qualifying passages, same-line citations, source hashes, room classification, provenance binding, full folder snapshot, and signed answer event are stored in one trace | Omit a part, cite an unrelated passage, add an unsupported number, alter the event binding, or mutate the folder during inference; Prism must reject publication | Automated |
| Team history is durable | Second identity reads the signed events from the relay | Restart web server and clear its memory | Automated |
| An operator decision is durable | Persisted trace plus the exact signed review message and canvas event | Clear process memory or change any review field, signer, event ID, or canvas text | Automated |
| The digest is shared markup | Verified Buzz kind 40100 canvas event and matching rendered Markdown | Change the canvas outside Prism without recording the event ID, and require the browser read to fail | Automated |
| A reviewed digest is committed, not merely written | Exact canvas event, review message, and persisted trace restore as one review chain | Interrupt publication after the canvas write and require an explicit `uncommitted_review_canvas` response | Automated |
| Room bindings are durable | Validated room, channel, and canvas event records in the local Buzz registry | Corrupt JSON or change a room identity, and require status plus workspace requests to report the registry failure | Automated |
| Failure is honest | UI shows relay/model/folder failure at the point of action | Kill each dependency independently | Automated |
| Long inference does not freeze the workspace | A real Bonsai request runs while status probes return within the registered prototype threshold, and concurrent traces persist without corruption | Hold one request open, probe status, and race multiple trace writes | Automated plus live measurement |

The real-deal browser check covers a four-part discussion on one acquired
Zendesk SEC filing. It opens the exact signed answer event and verifies the
price, stockholder approval, regulatory approval, and financing-condition
citations. It follows the financing citation to the exact local source block
and binds the record to the filing, trace, Buzz events, and screenshot hashes.
The check also proves that the folder and trace predate the current Prism server
process. It records this as restored history, not as a current-process model
call. The UI hides the machine trace marker and shows human-readable part labels.
The record has 21 passing assertions. It is a structural publication pass, not
domain review or an accuracy release. See
`evidence/browser-real-deal-zendesk-v1.json`.

The folder-opening dialog has a separate six-assertion Chromium replay. It
shows the exact supported recursive inventory, stable relative names, sizes, estimated tokens, and
parser warnings before room creation. The preview API records no Buzz write or
room registration, and the room registry hash is unchanged before and after
preview. Creation is a separate action bound to the preview hash. The replay
uses a repository engineering fixture and deliberately stops before room
creation; it is not customer or model-quality evidence. See
`evidence/browser-folder-preview-v1.json`.

The accessibility smoke reuses the same signed Zendesk answer. It checks
semantic tab state, keyboard tab and citation navigation, visible focus,
dialog focus restoration, reduced motion, target size, and a 390 pixel mobile
width. The record has 18 passing assertions and no browser or HTTP errors. It
is saved in `evidence/browser-accessibility-zendesk-v1.json` with a hashed
screenshot. The record is not WCAG conformance or assistive technology review.

The cross browser replay uses the same signed answer in Firefox 153 and WebKit
26.5. Each engine checks the four labels, four citation controls, tab semantics,
keyboard tab navigation, exact financing citation, source focus, and mobile
width. All 16 combined assertions pass with no browser or HTTP errors. The
record is `evidence/browser-cross-engine-zendesk-v1.json`. WebKit is not a
Safari application test, and branded Chrome, Edge, and extensions remain
untested.

The benchmark workshop has a separate browser check. It confirms that all five
promotion gates render from the server state, including the blocked judge
calibration gate. It also confirms that no review
decision or answer policy is selected by default, and that unsigned export is
closed while the reviewer authority is unconfigured and the roster is empty.
The current record has 17 passing assertions and no browser or HTTP errors. It
is saved in
`evidence/browser-source-review-v1.json` with a hashed screenshot.

The case authoring workshop has its own browser check. It confirms that a draft
cannot enter authoring before source review clears it. It also confirms that
owner controls and unsigned export remain closed in the current empty state,
and that no evaluation slice is selected by default. The current record has
seven passing assertions and no browser or HTTP errors. It is saved in
`evidence/browser-case-authoring-v1.json` with a hashed screenshot.

The blinded output review workshop has two browser checks. The first check uses
the current unconfigured authority and empty roster. It confirms that all
labels start empty and export is closed. The second check uses named synthetic
reviewer fixtures. It completes
all 25 dimension labels, saves all five cases, downloads the unsigned record,
and checks the record against the packet and production schema. The fixture
record says that no human review occurred, and the verifier rejects any edit
that tries to turn the fixture into review or release evidence. The records are
`evidence/browser-output-review-v1.json` and
`evidence/browser-output-review-completion-fixture-v1.json`.

## Explicit v0 limits

- Buzz currently provides its full collaboration client through the desktop
  app. Prism's browser client uses the same relay and event objects, but it is a
  separate presentation surface.
- Browser-held multi-user signing is not part of the first slice. The local web
  bridge signs as the configured operator. Multi-human identity is verified
  through Buzz Desktop/CLI until browser key custody is designed and reviewed.
- A hosted web shell cannot read a person's local folder or reach their
  loopback LM Studio endpoint without an explicit private tunnel/bridge. The
  first live deployment is therefore private and is not described as a public,
  fully local-processing product.
