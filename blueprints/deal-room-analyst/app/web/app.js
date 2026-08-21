const DEFAULT_ROOM = "project_titan_lbo";
const DEAL_ROOM_CHAT_GUARD_FAMILY = "deal_room_chat_guard_v";

const state = {
  roomId: roomIdFromPath(),
  workspace: null,
  status: null,
  rooms: [],
  messages: [],
  messageVerification: null,
  digest: "",
  digestVerification: null,
  firstPass: null,
  activeView: viewFromPath(),
  selectedFile: 0,
  selectedAnchor: new URLSearchParams(location.search).get("anchor"),
  polling: null,
  messagesLoading: false,
  messagesRefreshQueued: false,
  folderPreview: null,
  citationPreview: null,
  citationOpener: null,
  composerContext: null,
  evaluation: null,
  evaluationDashboard: null,
  evaluationMode: "review",
  evaluationIndex: 0,
  evaluationUndo: [],
};

let evaluationWriteQueue = Promise.resolve();
let evaluationNoteTimer = null;

document.addEventListener("DOMContentLoaded", init);

async function init() {
  bindEvents();
  switchView(state.activeView);
  await Promise.all([loadStatus(), loadRooms()]);
  await loadWorkspace();
  state.polling = window.setInterval(pollMessagesWhenVisible, 3500);
  document.addEventListener("visibilitychange", pollMessagesWhenVisible);
}

function pollMessagesWhenVisible() {
  if (document.visibilityState === "visible") loadMessages();
}

function roomIdFromPath() {
  const match = location.pathname.match(/^\/rooms\/([^/]+)/);
  return match ? decodeURIComponent(match[1]) : DEFAULT_ROOM;
}

function viewFromPath() {
  const tail = location.pathname.split("/").filter(Boolean).at(-1);
  if (["digest", "files", "evidence", "discussion", "first-pass", "evaluation"].includes(tail)) {
    return tail === "discussion" ? "conversation" : tail;
  }
  return "first-pass";
}

function bindEvents() {
  document.addEventListener("click", (event) => {
    const citation = event.target.closest("[data-source-citation]");
    if (citation) openCitation(citation);
  });
  document.querySelectorAll(".workspace-tab").forEach((button) => {
    button.addEventListener("click", () => {
      switchView(button.dataset.view);
      button.closest("details")?.removeAttribute("open");
    });
    if (button.matches('[role="tab"]')) {
      button.addEventListener("keydown", moveWorkspaceTabFocus);
    }
  });
  document.querySelectorAll("[data-open-view]").forEach((button) => {
    button.addEventListener("click", () => {
      switchView(button.dataset.openView);
      document.getElementById("context-panel").classList.remove("open");
    });
  });
  document.getElementById("message-form").addEventListener("submit", sendMessage);
  document.getElementById("first-pass-form").addEventListener("submit", runFirstPass);
  document.getElementById("review-form").addEventListener("submit", publishReview);
  document.getElementById("message-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      document.getElementById("message-form").requestSubmit();
    }
  });
  document.getElementById("message-input").addEventListener("input", autoSizeComposer);
  document.getElementById("clear-composer-context").addEventListener("click", () => setComposerContext(null));
  document.getElementById("close-citation-preview").addEventListener("click", closeCitationPreview);
  document.getElementById("citation-scrim").addEventListener("click", closeCitationPreview);
  document.getElementById("open-full-source").addEventListener("click", openFullCitationSource);
  document.getElementById("ask-about-citation").addEventListener("click", askAboutCitation);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.citationPreview) {
      event.preventDefault();
      closeCitationPreview();
    }
    if (event.key === "Tab" && state.citationPreview) trapCitationPreviewFocus(event);
  });
  document.getElementById("open-folder-button").addEventListener("click", () => {
    document.getElementById("folder-dialog").showModal();
  });
  document.getElementById("folder-form").addEventListener("submit", openFolder);
  document.getElementById("folder-path").addEventListener("input", resetFolderPreview);
  document.getElementById("copy-room-link").addEventListener("click", copyRoomLink);
  document.getElementById("toggle-context").addEventListener("click", () => {
    document.getElementById("context-panel").classList.toggle("open");
  });
  document.getElementById("show-analysis-controls").addEventListener("click", (event) => {
    const panel = document.getElementById("view-first-pass");
    const editing = panel.classList.toggle("editing-focus");
    event.currentTarget.textContent = editing ? "Hide question" : "Edit question";
    if (editing) document.getElementById("investment-screen").focus();
  });
  document.getElementById("edit-digest-button").addEventListener("click", editDigest);
  document.getElementById("cancel-digest").addEventListener("click", cancelDigest);
  document.getElementById("digest-form").addEventListener("submit", saveDigest);
  document.querySelector(".evaluation-judgment").addEventListener("click", (event) => {
    const button = event.target.closest("[data-evaluation-label]");
    if (button) saveEvaluationAnnotation(button.dataset.evaluationLabel);
  });
  document.getElementById("evaluation-note").addEventListener("input", scheduleEvaluationNoteSave);
  document.getElementById("evaluation-reviewer").addEventListener("change", () => saveEvaluationAnnotation(null, { track: false }));
  document.getElementById("evaluation-previous").addEventListener("click", () => moveEvaluation(-1));
  document.getElementById("evaluation-next").addEventListener("click", () => moveEvaluation(1));
  document.getElementById("evaluation-jump").addEventListener("click", jumpToEvaluationTrace);
  document.getElementById("evaluation-suggestions").addEventListener("click", handleEvaluationSuggestion);
  document.getElementById("evaluation-add-breadth").addEventListener("click", addEvaluationBreadth);
  document.getElementById("evaluation-scan-depth").addEventListener("click", scanEvaluationDepth);
  document.getElementById("evaluation-map").addEventListener("click", openEvaluationMapTrace);
  document.querySelectorAll("[data-evaluation-mode]").forEach((button) => {
    button.addEventListener("click", () => switchEvaluationMode(button.dataset.evaluationMode));
  });
  document.addEventListener("keydown", handleEvaluationKeyboard);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
    ...options,
  });
  let body;
  try { body = await response.json(); } catch { body = { error: "invalid_server_response" }; }
  if (!response.ok) {
    const error = new Error(body.detail || humanize(body.error) || `Request failed (${response.status})`);
    error.status = response.status;
    error.body = body;
    throw error;
  }
  return body;
}

async function loadStatus() {
  try {
    state.status = await api("/api/status");
    renderRuntimeStatus();
  } catch (error) {
    renderDependencyDown("Prism server unavailable", error.message);
  }
}

async function loadRooms() {
  try {
    state.rooms = await api("/api/deal-rooms");
    renderRooms();
  } catch (error) { showToast(error.message, true); }
}

async function loadWorkspace() {
  setWorkspaceLoading(true);
  try {
    state.workspace = await api(`/api/workspace?room=${encodeURIComponent(state.roomId)}`);
    renderWorkspace();
    await Promise.all([loadFirstPass(), loadMessages(), loadDigest(), loadEvidence(), loadEvaluation(), loadEvaluationDashboard()]);
  } catch (error) {
    if (error.status === 409) {
      renderWorkspaceNotBound();
    } else {
      renderDependencyDown("Workspace unavailable", error.message);
    }
  } finally { setWorkspaceLoading(false); }
}

async function loadFirstPass() {
  if (!state.workspace) return;
  try {
    const result = await api(`/api/workspace/first-pass?room=${encodeURIComponent(state.roomId)}`);
    state.firstPass = result.draft;
    const screen = document.getElementById("investment-screen");
    if (!screen.value) screen.value = result.default_investment_screen || "";
    renderFirstPass();
  } catch (error) {
    document.getElementById("first-pass-hint").textContent = `First pass unavailable · ${error.message}`;
  }
}

async function loadMessages() {
  if (!state.workspace) return;
  if (state.messagesLoading) {
    state.messagesRefreshQueued = true;
    return;
  }
  const requestedRoom = state.roomId;
  state.messagesLoading = true;
  try {
    const result = await api(`/api/workspace/messages?room=${encodeURIComponent(requestedRoom)}`);
    if (state.roomId !== requestedRoom) return;
    const changed = JSON.stringify(result.messages.map((m) => m.id)) !== JSON.stringify(state.messages.map((m) => m.id));
    state.messages = result.messages;
    state.messageVerification = result.signature_verification;
    renderMessageVerification();
    if (changed) renderMessages();
  } catch (error) {
    if (state.roomId !== requestedRoom) return;
    state.messageVerification = null;
    renderMessageVerification();
    document.getElementById("composer-hint").textContent = `Buzz unavailable · ${error.message}`;
  } finally {
    state.messagesLoading = false;
    if (state.messagesRefreshQueued) {
      state.messagesRefreshQueued = false;
      window.queueMicrotask(loadMessages);
    }
  }
}

async function loadDigest() {
  if (!state.workspace) return;
  try {
    const result = await api(`/api/workspace/digest?room=${encodeURIComponent(state.roomId)}`);
    state.digest = result.markdown;
    state.digestVerification = result.signature_verification;
    document.getElementById("digest-rendered").innerHTML = renderMarkdown(state.digest);
    renderDigestVerification();
  } catch (error) {
    state.digestVerification = null;
    renderDigestVerification();
    document.getElementById("digest-rendered").innerHTML = errorState("Digest unavailable", error.message);
  }
}

function renderDigestVerification() {
  const verified = state.digestVerification?.state === "verified"
    && state.digestVerification?.scheme === "nip01_event_id_plus_bip340";
  const evidencePacket = state.digest.includes("## Reviewed source evidence packet");
  const firstPassDraft = state.digest.includes("## Reviewed first pass draft");
  const reviewed = evidencePacket || firstPassDraft;
  document.getElementById("digest-title").textContent = evidencePacket
    ? "Decision notes"
    : firstPassDraft ? "Decision notes" : "Decision notes";
  document.getElementById("digest-state").textContent = verified
    ? reviewed ? "Saved team decision" : "Saved room notes"
    : "Room notes unavailable";
}

async function loadEvidence() {
  try {
    const evals = await api("/api/evals");
    renderEvidence(evals);
  } catch (error) {
    document.getElementById("run-list").innerHTML = errorState("Trace list unavailable", error.message);
  }
}

async function loadEvaluation() {
  if (!state.workspace) return;
  try {
    const result = await api(`/api/workspace/evaluation?room=${encodeURIComponent(state.roomId)}`);
    if (result.room !== state.roomId) return;
    state.evaluation = result;
    if (state.evaluationIndex >= result.samples.length) state.evaluationIndex = 0;
    renderEvaluation();
  } catch (error) {
    state.evaluation = null;
    document.getElementById("evaluation-turns").innerHTML = errorState("Evaluation unavailable", error.message);
    document.getElementById("evaluation-count").textContent = "Review unavailable";
  }
}

async function loadEvaluationDashboard() {
  if (!state.workspace) return;
  try {
    const result = await api(`/api/workspace/evaluation/dashboard?room=${encodeURIComponent(state.roomId)}`);
    if (result.scope?.room !== state.roomId) return;
    state.evaluationDashboard = result;
    renderEvaluationDashboard();
  } catch (error) {
    state.evaluationDashboard = null;
    document.getElementById("eval-lab-decision-title").textContent = "Evaluation unavailable";
    document.getElementById("eval-lab-decision-reason").textContent = error.message;
  }
}

function switchEvaluationMode(mode) {
  state.evaluationMode = mode === "lab" ? "lab" : "review";
  document.querySelectorAll("[data-evaluation-mode]").forEach((button) => {
    const active = button.dataset.evaluationMode === state.evaluationMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll(".evaluation-mode-pane").forEach((pane) => {
    const active = pane.id === `evaluation-${state.evaluationMode}-pane`;
    pane.classList.toggle("active", active);
    pane.hidden = !active;
  });
  renderEvaluationHeader();
}

function renderEvaluationHeader() {
  if (state.evaluationMode === "lab") {
    const dashboard = state.evaluationDashboard;
    document.getElementById("evaluation-count").textContent = dashboard
      ? `${dashboard.experiments?.length || 0} experiments · ${dashboard.evaluators?.length || 0} evaluators`
      : "Loading eval lab";
    document.getElementById("evaluation-phase").textContent = dashboard
      ? humanize(dashboard.decision?.state || "not_enough_evidence")
      : "Room scope";
    document.getElementById("evaluation-next-action").textContent = dashboard?.decision?.next_action
      || "Compare evidence, review failures, and let buyer value determine the next investment.";
    return;
  }
  const session = state.evaluation?.session || {};
  document.getElementById("evaluation-count").textContent = `${session.reviewed_count || 0} reviewed · ${session.remaining_count || 0} remaining`;
  document.getElementById("evaluation-phase").textContent = `${titleCase(session.phase || "breadth")} phase, saturation not claimed`;
  document.getElementById("evaluation-next-action").textContent = session.next_action || "Review the selected room traces.";
}

function evalStateClass(value = "") {
  const stateName = String(value);
  if (/pass|active|ready_for_pilot|measured/.test(stateName) && !/unverified|not_measured/.test(stateName)) return "positive";
  if (/blocked|fail|unverified|not_started|not_configured/.test(stateName)) return "blocked";
  return "pending";
}

function formatEvalValue(item = {}) {
  if (item.state === "not_measured" || item.value === null || item.value === undefined) return "Not measured";
  if (typeof item.value === "number") {
    if (/rate|recall|mrr|success|reduction|quality|usefulness/.test(item.id || "")) return `${Math.round(item.value * 100)}%`;
    return String(item.value);
  }
  return humanize(String(item.value));
}

function renderEvaluationDashboard() {
  const dashboard = state.evaluationDashboard;
  if (!dashboard) return;
  const decision = dashboard.decision || {};
  document.getElementById("eval-lab-decision-title").textContent = decision.next_investment
    ? `Invest in ${humanize(decision.next_investment)}`
    : "Not enough evidence";
  document.getElementById("eval-lab-decision-reason").textContent = decision.reason || "The investment decision is not ready.";
  document.getElementById("eval-lab-next-action").textContent = decision.next_action || "Collect representative evidence.";

  document.getElementById("eval-lab-routes").innerHTML = (dashboard.route_experiments || []).map((route) => `
    <article class="eval-lab-route ${evalStateClass(route.state)}">
      <div><span class="eval-state-dot" aria-hidden="true"></span><strong>${escapeHtml(route.label)}</strong><span class="eval-state-chip">${escapeHtml(humanize(route.state))}</span></div>
      <p>${route.model ? escapeHtml(route.model) : "No model run recorded"}</p>
      <dl><div><dt>Cases</dt><dd>${Number(route.case_count || 0)}</dd></div><div><dt>Human reviewed</dt><dd>${Number(route.human_reviewed_cases || 0)}</dd></div><div><dt>Privacy</dt><dd>${escapeHtml(humanize(route.privacy || "not_measured"))}</dd></div></dl>
    </article>`).join("");

  document.getElementById("eval-lab-gates").innerHTML = (dashboard.release_gates || []).map((gate) => `
    <article class="eval-lab-list-row">
      <span class="eval-state-dot ${evalStateClass(gate.state)}" aria-hidden="true"></span>
      <div><strong>${escapeHtml(gate.label)}</strong><p>${escapeHtml(gate.evidence || "No evidence recorded.")}</p></div>
      <span class="eval-state-chip ${evalStateClass(gate.state)}">${escapeHtml(humanize(gate.state))}</span>
    </article>`).join("");

  const calibration = dashboard.judge_validation || {};
  const labels = Number(calibration.labels_available || 0);
  const target = Number(calibration.minimum_labels_per_failure_mode || 0);
  const progress = target > 0 ? Math.min(100, Math.round((labels / target) * 100)) : 0;
  document.getElementById("eval-lab-judge-state").textContent = calibration.trusted_for_release ? "Trusted" : "Not trusted";
  document.getElementById("eval-lab-calibration").innerHTML = `
    <div class="eval-lab-judge-progress"><div><strong>${labels} of ${target}</strong><span>balanced domain labels</span></div><div class="eval-progress-track" aria-label="Judge label progress" aria-valuemin="0" aria-valuemax="${target}" aria-valuenow="${labels}" role="progressbar"><span style="width:${progress}%"></span></div></div>
    <dl class="eval-lab-judge-contract">
      <div><dt>Candidate</dt><dd>${escapeHtml(calibration.candidate_judge || "Not selected")}</dd></div>
      <div><dt>Split</dt><dd>${Math.round(Number(calibration.splits?.train || 0) * 100)} / ${Math.round(Number(calibration.splits?.dev || 0) * 100)} / ${Math.round(Number(calibration.splits?.test || 0) * 100)}</dd></div>
      <div><dt>TPR target</dt><dd>${Math.round(Number(calibration.target_tpr || 0) * 100)}%</dd></div>
      <div><dt>TNR target</dt><dd>${Math.round(Number(calibration.target_tnr || 0) * 100)}%</dd></div>
    </dl>
    <p>One narrow binary criterion at a time. Any criterion, prompt, model, quantization, or retrieval change requires recalibration.</p>`;

  document.getElementById("eval-lab-experiments").innerHTML = (dashboard.experiments || []).map((experiment) => `
    <tr>
      <td><strong>${escapeHtml(experiment.name)}</strong><small>${experiment.baseline ? "Named baseline" : escapeHtml(experiment.dataset || "Dataset missing")}</small></td>
      <td>${escapeHtml(titleCase(experiment.route_mode || "unknown"))}</td>
      <td>${Number(experiment.case_count || 0)}</td>
      <td><div class="eval-measure-list">${(experiment.measures || []).map((measure) => `<span><small>${escapeHtml(humanize(measure.id))}</small><strong>${escapeHtml(formatEvalValue(measure))}</strong></span>`).join("")}</div></td>
      <td><span class="eval-state-chip ${experiment.release ? "positive" : "blocked"}">${experiment.release ? "Released" : "Not released"}</span></td>
    </tr>`).join("");

  document.getElementById("eval-lab-evaluators").innerHTML = (dashboard.evaluators || []).map((evaluator) => `
    <article class="eval-lab-evaluator">
      <div><span class="eval-state-dot ${evaluator.trusted_for_release ? "positive" : evalStateClass(evaluator.status)}" aria-hidden="true"></span><strong>${escapeHtml(humanize(evaluator.id))}</strong></div>
      <p>${escapeHtml(evaluator.criterion || humanize(evaluator.kind || "evaluator"))}</p>
      <div><span>${escapeHtml(humanize(evaluator.kind || "unknown"))}</span><span class="eval-state-chip ${evaluator.trusted_for_release ? "positive" : evalStateClass(evaluator.status)}">${evaluator.trusted_for_release ? "Trusted" : escapeHtml(humanize(evaluator.status || "not_trusted"))}</span></div>
    </article>`).join("");

  document.getElementById("eval-lab-layers").innerHTML = (dashboard.layers || []).map((layer, index) => `
    <article><span>${String(index + 1).padStart(2, "0")}</span><div><strong>${escapeHtml(humanize(layer.id))}</strong><p>${escapeHtml(layer.question)}</p></div></article>`).join("");

  const measuredBusiness = (dashboard.business_measures || []).filter((item) => item.state === "measured").length;
  document.getElementById("eval-lab-business-state").textContent = measuredBusiness ? `${measuredBusiness} measured` : "Not measured";
  document.getElementById("eval-lab-business").innerHTML = (dashboard.business_measures || []).map((measure) => `
    <div><span>${escapeHtml(humanize(measure.id))}</span><strong>${escapeHtml(formatEvalValue(measure))}</strong></div>`).join("");

  document.getElementById("eval-lab-boundaries").innerHTML = (dashboard.boundaries || []).map((boundary) => `<li>${escapeHtml(boundary)}</li>`).join("");
  renderEvaluationHeader();
}

function currentEvaluationSample(recordId = null) {
  const samples = state.evaluation?.samples || [];
  if (recordId) return samples.find((sample) => sample.id === recordId);
  return samples[state.evaluationIndex];
}

function renderEvaluation() {
  const evaluation = state.evaluation;
  if (!evaluation) return;
  renderEvaluationSession();
  renderEvaluationTrace();
  renderEvaluationCoverage();
  renderEvaluationLearning();
  renderEvaluationObservability();
}

function renderEvaluationSession() {
  renderEvaluationHeader();
}

function renderEvaluationTrace() {
  const sample = currentEvaluationSample();
  if (!sample) {
    document.getElementById("evaluation-turns").innerHTML = errorState("No room traces", "Add activity to this room before starting error discovery.");
    return;
  }
  document.getElementById("evaluation-stratum").textContent = humanize(sample.stratum || "trace");
  document.getElementById("evaluation-trace-title").textContent = `Trace ${sample.id.slice(0, 10)}`;
  const recorded = new Date(Number(sample.created_at || 0) * 1000);
  document.getElementById("evaluation-trace-meta").textContent = `${humanize(sample.acceptance_state || "recorded")} · ${recorded.toLocaleString()}`;
  document.getElementById("evaluation-counter").textContent = `${state.evaluationIndex + 1} of ${state.evaluation.samples.length}`;
  const turns = sample.turns?.length ? sample.turns : [sample];
  document.getElementById("evaluation-turns").innerHTML = turns.map((turn) => {
    const focus = turn.id === sample.focus_turn_id;
    const content = String(turn.content || "").replace(/^<!-- prism:[^\n]+-->\n?/, "");
    return `<section class="evaluation-turn ${escapeHtml(turn.role || "other")}${focus ? " focus" : ""}">
      <div><strong>${escapeHtml(titleCase(turn.role || "event"))}</strong><span>${focus ? "Review target" : "Context"}</span></div>
      <article>${renderMarkdown(content)}</article>
    </section>`;
  }).join("");
  document.getElementById("evaluation-machine").textContent = JSON.stringify(sample.metadata || {}, null, 2);
  const saved = state.evaluation.annotations?.[sample.id] || {};
  document.getElementById("evaluation-note").value = saved.note || "";
  document.getElementById("evaluation-reviewer").value = saved.reviewer || "local reviewer";
  document.querySelectorAll("[data-evaluation-label]").forEach((button) => {
    button.classList.toggle("selected", button.dataset.evaluationLabel === saved.label);
  });
  renderEvaluationSuggestions();
}

function renderEvaluationSuggestions() {
  const sample = currentEvaluationSample();
  if (!sample || !state.evaluation) return;
  const suggestions = state.evaluation.suggestions.filter((item) => item.record_id === sample.id && item.state === "pending");
  document.getElementById("evaluation-suggestions").innerHTML = suggestions.length ? suggestions.map((item) => `
    <article class="evaluation-suggestion" data-evaluation-suggestion="${escapeHtml(item.id)}">
      <strong>${escapeHtml(humanize(item.mode))}</strong><p>${escapeHtml(item.reason)}</p>
      <div><button class="text-button" data-suggestion-state="accepted" type="button">Accept</button><button class="text-button" data-suggestion-state="dismissed" type="button">Dismiss</button></div>
    </article>`).join("") : `<p class="muted">No pending suggestions for this trace.</p>`;
}

function scheduleEvaluationNoteSave() {
  clearTimeout(evaluationNoteTimer);
  const sample = currentEvaluationSample();
  if (!sample) return;
  const note = document.getElementById("evaluation-note").value;
  const reviewer = document.getElementById("evaluation-reviewer").value;
  evaluationNoteTimer = window.setTimeout(() => {
    saveEvaluationAnnotation(null, { track: false, recordId: sample.id, note, reviewer });
  }, 700);
}

function saveEvaluationAnnotation(label = null, { track = true, recordId = null, note = null, reviewer = null } = {}) {
  const sample = currentEvaluationSample(recordId);
  if (!sample || !state.evaluation) return Promise.resolve();
  const previous = state.evaluation.annotations?.[sample.id] || null;
  const currentNote = note === null ? document.getElementById("evaluation-note").value.trim() : String(note).trim();
  const currentReviewer = (reviewer === null ? document.getElementById("evaluation-reviewer").value : reviewer).trim() || "local reviewer";
  if (track) state.evaluationUndo.push({ recordId: sample.id, previous });
  const annotation = {
    ...(previous || {}),
    label: label || previous?.label || "defer",
    note: currentNote,
    reviewer: currentReviewer,
    confirmed_modes: previous?.confirmed_modes || [],
  };
  state.evaluation.annotations = { ...(state.evaluation.annotations || {}), [sample.id]: annotation };
  renderEvaluationTrace();
  const payload = { room: state.roomId, record_id: sample.id, ...annotation };
  const operation = evaluationWriteQueue.catch(() => {}).then(() => api("/api/workspace/evaluation/annotation", {
    method: "POST",
    body: JSON.stringify(payload),
  })).then((result) => {
    if (result.annotation) state.evaluation.annotations[sample.id] = result.annotation;
    state.evaluation.session = result.session;
    renderEvaluationSession();
    renderEvaluationLearning();
    renderEvaluationCoverage();
    return result;
  });
  evaluationWriteQueue = operation.catch((error) => showToast(`Review not saved: ${error.message}`, true));
  return operation;
}

async function moveEvaluation(delta) {
  clearTimeout(evaluationNoteTimer);
  const sample = currentEvaluationSample();
  const previous = sample ? state.evaluation?.annotations?.[sample.id] : null;
  const note = document.getElementById("evaluation-note").value.trim();
  if (sample && (note || previous)) {
    await saveEvaluationAnnotation(null, { track: false, recordId: sample.id, note });
  }
  await evaluationWriteQueue.catch(() => {});
  const length = state.evaluation?.samples?.length || 0;
  if (!length) return;
  state.evaluationIndex = (state.evaluationIndex + delta + length) % length;
  renderEvaluationTrace();
}

function jumpToEvaluationTrace() {
  const value = document.getElementById("evaluation-jump-id").value.trim();
  const index = state.evaluation?.samples?.findIndex((sample) => sample.id.startsWith(value)) ?? -1;
  if (index < 0) return showToast("Trace is not in the current review sample", true);
  state.evaluationIndex = index;
  renderEvaluationTrace();
}

async function handleEvaluationSuggestion(event) {
  const button = event.target.closest("[data-suggestion-state]");
  const root = event.target.closest("[data-evaluation-suggestion]");
  if (!button || !root) return;
  const suggestion = state.evaluation.suggestions.find((item) => item.id === root.dataset.evaluationSuggestion);
  if (!suggestion) return;
  if (button.dataset.suggestionState === "accepted") {
    const sample = currentEvaluationSample(suggestion.record_id);
    const saved = state.evaluation.annotations?.[sample.id] || {};
    document.getElementById("evaluation-note").value = [saved.note, `Confirmed: ${humanize(suggestion.mode)}. ${suggestion.reason}`].filter(Boolean).join("\n");
    saved.confirmed_modes = [...new Set([...(saved.confirmed_modes || []), suggestion.mode])];
    state.evaluation.annotations[sample.id] = saved;
    await saveEvaluationAnnotation("fail", { track: true, recordId: sample.id });
  }
  await api("/api/workspace/evaluation/suggestion", {
    method: "POST",
    body: JSON.stringify({ room: state.roomId, suggestion_id: suggestion.id, state: button.dataset.suggestionState }),
  });
  await loadEvaluation();
  showToast(button.dataset.suggestionState === "accepted" ? "Suggestion confirmed as human feedback" : "Suggestion dismissed");
}

function renderEvaluationCoverage() {
  const evaluation = state.evaluation;
  if (!evaluation) return;
  const clusters = [...new Set(evaluation.graph.map((item) => item.cluster))];
  const colors = ["#315f48", "#a45f47", "#416982", "#74568d", "#a58134", "#62806d", "#765348", "#4f6d78"];
  const palette = Object.fromEntries(clusters.map((name, index) => [name, colors[index % colors.length]]));
  document.getElementById("evaluation-map").innerHTML = evaluation.graph.map((item) => {
    const annotated = Boolean(evaluation.annotations?.[item.id]);
    const common = `class="evaluation-node ${item.sampled ? "sampled" : "unsampled"} ${annotated ? "annotated" : ""}" data-evaluation-node="${item.sampled ? escapeHtml(item.id) : ""}" fill="${palette[item.cluster]}"`;
    return item.role === "user"
      ? `<rect ${common} x="${item.x - 7}" y="${item.y - 7}" width="14" height="14"><title>${escapeHtml(humanize(item.cluster))}</title></rect>`
      : `<circle ${common} cx="${item.x}" cy="${item.y}" r="${item.sampled ? 9 : 6}"><title>${escapeHtml(humanize(item.cluster))}</title></circle>`;
  }).join("");
  document.getElementById("evaluation-legend").innerHTML = clusters.map((name) => `<span style="--legend-color:${palette[name]}">${escapeHtml(humanize(name))}</span>`).join("");
  const annotated = evaluation.graph.filter((item) => evaluation.annotations?.[item.id]).length;
  const sampled = evaluation.graph.filter((item) => item.sampled).length;
  document.getElementById("evaluation-coverage-summary").textContent = `${annotated} reviewed of ${sampled} sampled`;
}

function openEvaluationMapTrace(event) {
  const id = event.target.dataset.evaluationNode;
  if (!id) return;
  const index = state.evaluation.samples.findIndex((sample) => sample.id === id);
  if (index < 0) return;
  state.evaluationIndex = index;
  renderEvaluationTrace();
  document.querySelector(".evaluation-trace-card").scrollIntoView({ block: "start" });
}

function renderEvaluationLearning() {
  const evaluation = state.evaluation;
  if (!evaluation) return;
  const session = evaluation.session || {};
  document.getElementById("evaluation-reviewed").textContent = session.reviewed_count || 0;
  document.getElementById("evaluation-failures").textContent = session.labels?.fail || 0;
  document.getElementById("evaluation-pending").textContent = session.suggestions?.pending || 0;
  document.getElementById("evaluation-corpus").textContent = session.corpus_count || 0;
  document.getElementById("evaluation-scan-depth").disabled = !session.depth_scan_ready;
  document.getElementById("evaluation-learning-summary").textContent = `${session.reviewed_count || 0} of ${session.sample_count || 0} sampled traces reviewed. Human labels and agent suggestions remain separate.`;
  document.getElementById("evaluation-saturation").textContent = "Saturation not claimed";
  document.getElementById("evaluation-patterns").innerHTML = evaluation.patterns.length ? evaluation.patterns.map((item) => `
    <article><strong>${escapeHtml(humanize(item.name))}</strong><span>${item.confirmed || 0} confirmed · ${item.suggested || 0} suggested</span><p>${escapeHtml(item.description)}</p></article>`).join("") : `<p class="muted">No human confirmed failure modes yet.</p>`;
}

async function addEvaluationBreadth() {
  const result = await api("/api/workspace/evaluation/next-samples", { method: "POST", body: JSON.stringify({ room: state.roomId }) });
  await loadEvaluation();
  showToast(result.added.length ? `Added ${result.added.length} diverse room traces` : "No unsampled room traces remain");
}

async function scanEvaluationDepth() {
  try {
    const result = await api("/api/workspace/evaluation/scan", { method: "POST", body: JSON.stringify({ room: state.roomId }) });
    await loadEvaluation();
    showToast(`Corpus scan added ${result.added} suggestions`);
  } catch (error) {
    showToast(error.message, true);
  }
}

function renderEvaluationObservability() {
  const evaluation = state.evaluation;
  if (!evaluation) return;
  const phoenix = evaluation.phoenix || {};
  document.getElementById("evaluation-phoenix-state").textContent = phoenix.live ? "Phoenix live" : phoenix.configured ? "Phoenix unavailable" : "Phoenix not configured";
  document.getElementById("evaluation-phoenix-copy").textContent = phoenix.live ? "Local collector ready. Export remains explicit." : "The local review ledger remains authoritative.";
  document.getElementById("evaluation-otel-records").textContent = evaluation.observability?.records?.length || 0;
  document.getElementById("evaluation-otel-content").textContent = evaluation.observability?.content_policy === "hashes_only" ? "Hashes" : "Included";
  document.getElementById("evaluation-phoenix-link").href = phoenix.endpoint || "http://127.0.0.1:6006";
}

function handleEvaluationKeyboard(event) {
  if (state.activeView !== "evaluation" || event.target.matches("textarea,input")) return;
  if (event.key === "ArrowRight") moveEvaluation(1);
  if (event.key === "ArrowLeft") moveEvaluation(-1);
  if (event.key === "1") saveEvaluationAnnotation("pass");
  if (event.key === "2") saveEvaluationAnnotation("fail");
  if (event.key.toLowerCase() === "d") saveEvaluationAnnotation("defer");
  if (event.key.toLowerCase() === "u") undoEvaluationAnnotation();
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    saveEvaluationAnnotation();
  }
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    event.preventDefault();
    saveEvaluationAnnotation().then(() => moveEvaluation(1));
  }
}

async function undoEvaluationAnnotation() {
  const action = state.evaluationUndo.pop();
  if (!action) return showToast("Nothing to undo");
  const body = action.previous
    ? { room: state.roomId, record_id: action.recordId, ...action.previous }
    : { room: state.roomId, record_id: action.recordId, delete: true };
  const result = await api("/api/workspace/evaluation/annotation", { method: "POST", body: JSON.stringify(body) });
  if (action.previous) state.evaluation.annotations[action.recordId] = result.annotation;
  else delete state.evaluation.annotations[action.recordId];
  state.evaluation.session = result.session;
  renderEvaluation();
  showToast("Last review change undone");
}

function renderRooms() {
  const list = document.getElementById("room-list");
  const currentRoom = state.rooms.find((room) => room.id === state.roomId);
  list.innerHTML = (currentRoom ? [currentRoom] : []).map((room) => {
    const name = room.name.replace(/^Project\s+/i, "").split(":")[0];
    const active = room.id === state.roomId ? " active" : "";
    const provenance = room.source_provenance || {};
    return `<a class="room-link${active}" href="/rooms/${encodeURIComponent(room.id)}" data-source-class="${escapeHtml(provenance.classification || "unverified")}" title="${escapeHtml(provenance.label || "Source provenance unverified")}"><span class="room-monogram">${escapeHtml(name[0] || "D")}</span><span>${escapeHtml(name)}</span></a>`;
  }).join("");
}

function renderRuntimeStatus() {
  const buzz = state.status?.buzz || {};
  const workspaceReady = Boolean(buzz.workspace_ready);
  const relayDot = document.getElementById("relay-dot");
  relayDot.className = `status-dot ${workspaceReady ? "live" : "down"}`;
  document.getElementById("relay-label").textContent = workspaceReady
    ? "Activity available"
    : buzz.room_registry_state === "corrupt" ? "Room history unavailable" : "Team activity offline";
  document.getElementById("relay-detail").textContent = workspaceReady ? "Checking room history" : "Messages and sharing are unavailable";
  document.getElementById("truth-history").textContent = workspaceReady ? "Checking" : "Unavailable";
  document.getElementById("contract-buzz").textContent = workspaceReady ? "Live · verifying room events" : "Unavailable · runs are blocked";

  const configured = Boolean(state.status.local_inference_configured);
  const invokedThisProcess = Boolean(state.status.local_inference_invoked_in_process);
  const recordedHistory = Boolean(state.status.local_inference_recorded_history);
  const configuredModel = state.status.configured_local_model_name;
  const currentModel = state.status.current_process_local_model;
  const invokedModel = state.status.last_invoked_local_model;
  document.getElementById("model-name").textContent = friendlyModelName(currentModel || configuredModel || invokedModel);
  document.getElementById("contract-model").textContent = configured
    ? `${friendlyModelName(configuredModel)} is ready on this Mac`
    : "Bonsai is not available";
  const cloudConsent = state.status.cloud_consent || {};
  document.getElementById("contract-cloud").textContent = cloudConsent.dispatch_ready_for_signed_request
    ? "Cloud use requires a signed room approval"
    : "Cloud sharing is off";
  const modelState = document.getElementById("model-state");
  modelState.textContent = invokedThisProcess
    ? "Active"
    : configured && recordedHistory
      ? "Ready"
      : configured ? "Ready" : "Offline";
  modelState.classList.toggle("down", !configured);
}

function renderMessageVerification() {
  const verification = state.messageVerification;
  const verified = verification?.state === "verified"
    && verification?.scheme === "nip01_event_id_plus_bip340";
  document.getElementById("relay-detail").textContent = verified
    ? `${verification.verified_event_count} room events checked`
    : "Room history could not be checked";
  document.getElementById("truth-history").textContent = verified
    ? "Checked"
    : "Unverified";
  document.getElementById("contract-buzz").textContent = verified
    ? "Buzz is saving team activity"
    : "Team activity is unavailable";
}

function renderFirstPass() {
  const draft = state.firstPass;
  const panel = document.getElementById("view-first-pass");
  panel.classList.toggle("has-deal-brief", Boolean(draft));
  if (!draft) panel.classList.remove("editing-focus");
  document.getElementById("draft-section").hidden = !draft;
  document.getElementById("first-pass-empty").hidden = Boolean(draft);
  if (!draft) {
    document.getElementById("brief-status").textContent = "Not started";
    return;
  }
  const reviewed = Boolean(draft.review);
  const fallback = draft.acceptance_state === "evidence_safe_fallback";
  const reviewable = draft.acceptance_state === "accepted" || fallback;
  document.getElementById("brief-status").textContent = reviewed
    ? `Decision saved: ${titleCase(draft.review.decision)}`
    : reviewable ? "Ready for team review" : "Run again";
  document.getElementById("draft-kind").textContent = "Decision status";
  document.getElementById("first-pass-draft").innerHTML = fallback
    ? renderFallbackReview(draft)
    : renderMarkdown(draft.markdown) + renderEvidenceScope(draft.evidence_scope);
  if (!fallback) enhanceBriefDocument();
  document.getElementById("draft-recommendation").textContent = fallback
    ? "Not ready to advance"
    : titleCase(humanize(draft.recommendation));
  const citedFiles = new Set((draft.citations || []).map((citation) => parseCitation(citation)?.source).filter(Boolean));
  const bits = [
    citedFiles.size ? `${citedFiles.size} priority file${citedFiles.size === 1 ? "" : "s"}` : null,
  ].filter(Boolean);
  document.getElementById("draft-meta").innerHTML = bits.map((item) => `<span>${escapeHtml(item)}</span>`).join("");
  document.querySelectorAll('input[name="review-decision"]').forEach((input) => {
    input.checked = Boolean(draft.review) && input.value === draft.review.decision;
  });
  document.getElementById("critical-corrections").value = draft.review?.critical_corrections ?? 0;
  document.getElementById("major-corrections").value = draft.review?.major_corrections ?? 0;
  document.getElementById("useful-starting-point").checked = draft.review?.useful_starting_point ?? false;
  document.getElementById("review-notes").value = draft.review?.notes ?? "";
  document.querySelectorAll("#review-form input, #review-form textarea, #publish-review").forEach((control) => {
    control.disabled = !reviewable;
  });
  document.getElementById("publish-review").textContent = "Save decision";
  document.getElementById("review-hint").innerHTML = !reviewable
    ? "This draft predates the current deterministic evidence guard. Run a new accepted first pass before review."
    : reviewed
    ? fallback
      ? `Open <button class="inline-link" type="button" data-open-reviewed>decision notes</button>.`
      : `Open <button class="inline-link" type="button" data-open-reviewed>decision notes</button>.`
    : fallback
    ? "Review the priority files before saving the team decision."
    : "Save the decision when the team is ready.";
  document.querySelector("[data-open-reviewed]")?.addEventListener("click", () => switchView("digest"));
}

async function runFirstPass(event) {
  event.preventDefault();
  const button = document.getElementById("run-first-pass");
  const hint = document.getElementById("first-pass-hint");
  button.disabled = true;
  hint.textContent = "Reviewing the room. The review can take about a minute.";
  try {
    state.firstPass = await api("/api/workspace/first-pass", {
      method: "POST",
      body: JSON.stringify({ room: state.roomId, action: "run", investment_screen: document.getElementById("investment-screen").value.trim() }),
    });
    await Promise.all([loadFirstPass(), loadMessages(), loadEvidence()]);
    hint.textContent = state.firstPass.acceptance_state === "evidence_safe_fallback"
      ? "The source review is ready. Check the priority files before deciding."
      : "The deal review is ready and saved to this room.";
    document.getElementById("draft-section").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    hint.textContent = `Analysis could not finish. ${error.message}`;
    showToast(`Analysis could not finish. ${error.message}`, true);
  } finally { button.disabled = false; }
}

async function publishReview(event) {
  event.preventDefault();
  const button = document.getElementById("publish-review");
  const decision = new FormData(event.currentTarget).get("review-decision");
  button.disabled = true;
  try {
    const review = await api("/api/workspace/first-pass", {
      method: "POST",
      body: JSON.stringify({
        room: state.roomId,
        action: "review",
        decision,
        critical_corrections: Number(document.getElementById("critical-corrections").value),
        major_corrections: Number(document.getElementById("major-corrections").value),
        useful_starting_point: document.getElementById("useful-starting-point").checked,
        notes: document.getElementById("review-notes").value.trim(),
      }),
    });
    state.firstPass.review = review;
    renderFirstPass();
    await Promise.all([loadDigest(), loadMessages()]);
    showToast("Decision saved to reviewed notes");
  } catch (error) {
    showToast(`Review not published: ${error.message}`, true);
  } finally { button.disabled = false; }
}

function renderWorkspace() {
  const room = state.workspace;
  const provenance = room.source_provenance || {};
  const requestedSource = new URLSearchParams(location.search).get("source");
  const requestedIndex = room.documents.findIndex((document) => document.filename === requestedSource);
  if (requestedIndex >= 0) state.selectedFile = requestedIndex;
  document.title = `${room.room_name} — Prism Vault`;
  document.getElementById("room-name").textContent = room.room_name;
  const provenanceLabel = document.getElementById("room-provenance");
  const provenanceClass = [
    "synthetic_engineering_fixture",
    "public_filing_corpus",
    "operator_selected_local_folder",
  ].includes(provenance.classification) ? provenance.classification : "unverified";
  provenanceLabel.textContent = {
    synthetic_engineering_fixture: "Demo files",
    public_filing_corpus: "Public filings",
    operator_selected_local_folder: "Private folder",
  }[provenanceClass] || "File source unverified";
  provenanceLabel.className = `provenance-label ${provenanceClass}`;
  provenanceLabel.title = provenance.meaning || "Prism did not return a source provenance boundary.";
  document.getElementById("truth-source-provenance").textContent = provenance.label || "Unverified";
  document.getElementById("document-count").textContent = `${room.total_documents} file${room.total_documents === 1 ? "" : "s"}`;
  const roomDescription = state.roomId === "project_titan_lbo"
    ? "LBO model with debt terms, cash sweep assumptions, and sponsor returns."
    : room.description;
  document.getElementById("room-description").textContent = roomDescription;
  document.getElementById("room-description-header").textContent = roomDescription;
  renderSources();
}

function renderSources() {
  const documents = state.workspace?.documents || [];
  document.getElementById("compact-sources").innerHTML = documents.slice(0, 5).map(sourceCompact).join("") || `<p class="muted">No supported files.</p>`;
  document.getElementById("source-list").innerHTML = documents.map((doc, index) => `
    <button class="source-button${index === state.selectedFile ? " active" : ""}" type="button" data-file-index="${index}"${index === state.selectedFile ? ' aria-current="true"' : ""}>
      <span class="file-shape">${escapeHtml(fileLabel(doc.file_type))}</span>
      <span><strong>${escapeHtml(doc.filename)}</strong><small>${escapeHtml(fileLabel(doc.file_type))}, ${formatBytes(doc.raw_size_bytes)}</small></span>
      <small>›</small>
    </button>`).join("");
  document.querySelectorAll("[data-file-index]").forEach((button) => button.addEventListener("click", () => {
    state.selectedFile = Number(button.dataset.fileIndex);
    state.selectedAnchor = null;
    renderSources();
    renderSourcePreview();
  }));
  renderSourcePreview();
}

function sourceCompact(doc) {
  return `<div class="compact-source"><span class="file-shape">${escapeHtml(fileLabel(doc.file_type))}</span><span><strong>${escapeHtml(doc.filename)}</strong><small>${formatBytes(doc.raw_size_bytes)}</small></span></div>`;
}

function renderSourcePreview() {
  const doc = state.workspace?.documents?.[state.selectedFile];
  if (!doc) return;
  const citedPassage = state.selectedAnchor ? doc.anchors?.[state.selectedAnchor] : null;
  const missingCitation = Boolean(state.selectedAnchor && !citedPassage);
  const label = citedPassage
    ? `Cited passage · ${state.selectedAnchor}`
    : missingCitation
    ? `Citation unavailable · ${state.selectedAnchor}`
    : `Parsed preview · ${doc.file_type}`;
  const preview = missingCitation
    ? "The cited anchor was not returned by the workspace API. Prism will not substitute a different passage."
    : citedPassage || doc.preview_text || "No text preview available.";
  const spreadsheetBoundary = doc.file_type === "xlsx" ? `
    <div class="source-boundary" role="note">
      <strong>Stored workbook values only</strong>
      <span>Prism did not recalculate formulas. It applied a bounded set of audited number formats and left unsupported formats raw. ${Number(doc.parser_facts?.cached_formula_cell_count || 0).toLocaleString()} formula value(s) came from the file cache; ${Number(doc.parser_facts?.unevaluated_formula_cell_count || 0).toLocaleString()} had no cached value; ${Number(doc.parser_facts?.unsupported_number_format_cell_count || 0).toLocaleString()} numeric cell(s) used unsupported formats.</span>
    </div>` : "";
  const ocrBoundary = doc.parser_facts?.ocr_applied ? `
    <div class="source-boundary" role="note">
      <strong>OCR text, not reconstructed layout</strong>
      <span>Apple Vision OCR was used on ${Number(doc.parser_facts?.ocr_page_numbers?.length || 0).toLocaleString()} page(s). OCR text and reading order may be wrong. Tables, columns, merged cells, and document layout were not reconstructed. Engine confidence is not a measured accuracy score.</span>
    </div>` : "";
  const [sourceLabel, sourceDetail] = sourceDecisionLabel(doc.filename);
  document.getElementById("source-preview").innerHTML = `
    <div class="source-preview-heading">
      <div><span class="eyebrow">${escapeHtml(label)}</span><h3>${escapeHtml(sourceLabel)}</h3><p>${escapeHtml(doc.filename)} · ${escapeHtml(sourceDetail)}</p></div>
      <button class="secondary-button" type="button" data-ask-file="${escapeHtml(doc.filename)}">Ask about this file</button>
    </div>
    ${spreadsheetBoundary}${ocrBoundary}
    <div class="source-render source-render-${escapeHtml(doc.file_type)}">${renderSourceContent(doc, preview)}</div>`;
  document.querySelector("[data-ask-file]")?.addEventListener("click", () => {
    setComposerContext({ source: doc.filename, anchor: state.selectedAnchor, label: sourceLabel });
    document.getElementById("message-input").focus();
  });
  syncComposerForView();
}

function openCitation(citation) {
  const filename = citation.dataset.source;
  const anchor = citation.dataset.anchor;
  const documents = state.workspace?.documents || [];
  const index = documents.findIndex((document) => document.filename === filename);
  if (index < 0) {
    showToast(`Source is not in this room: ${filename}`, true);
    return;
  }
  state.selectedFile = index;
  state.selectedAnchor = anchor;
  state.citationOpener = citation;
  state.citationPreview = { filename, anchor, returnView: state.activeView };
  const doc = documents[index];
  const passage = doc.anchors?.[anchor];
  const [label, detail] = sourceDecisionLabel(filename);
  document.getElementById("citation-preview-title").textContent = label;
  document.getElementById("citation-preview-meta").textContent = `${detail} · ${humanizeAnchor(anchor)} · ${filename}`;
  document.getElementById("citation-preview-content").innerHTML = passage
    ? renderSourceContent(doc, passage)
    : `<div class="source-missing"><strong>Passage unavailable</strong><p>Prism will not substitute a different passage.</p></div>`;
  const panel = document.getElementById("citation-preview-panel");
  panel.inert = false;
  panel.classList.add("open");
  panel.setAttribute("aria-hidden", "false");
  document.getElementById("citation-scrim").hidden = false;
  document.getElementById("close-citation-preview").focus({ preventScroll: true });
}

function closeCitationPreview({ restoreFocus = true } = {}) {
  const opener = state.citationOpener;
  state.citationPreview = null;
  state.citationOpener = null;
  const panel = document.getElementById("citation-preview-panel");
  panel.classList.remove("open");
  panel.setAttribute("aria-hidden", "true");
  panel.inert = true;
  document.getElementById("citation-scrim").hidden = true;
  if (restoreFocus && opener?.isConnected) opener.focus({ preventScroll: true });
}

function trapCitationPreviewFocus(event) {
  const panel = document.getElementById("citation-preview-panel");
  const controls = [...panel.querySelectorAll('button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])')]
    .filter((element) => !element.hidden);
  if (!controls.length) return;
  const first = controls[0];
  const last = controls.at(-1);
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function openFullCitationSource() {
  const citation = state.citationPreview;
  if (!citation) return;
  closeCitationPreview({ restoreFocus: false });
  renderSources();
  switchView("files");
  const query = new URLSearchParams({ source: citation.filename, anchor: citation.anchor });
  history.replaceState({}, "", `/rooms/${encodeURIComponent(state.roomId)}/files?${query}`);
  const preview = document.getElementById("source-preview");
  preview.scrollIntoView({ block: "start" });
  preview.focus({ preventScroll: true });
}

function askAboutCitation() {
  const citation = state.citationPreview;
  if (!citation) return;
  const [label] = sourceDecisionLabel(citation.filename);
  setComposerContext({ source: citation.filename, anchor: citation.anchor, label });
  closeCitationPreview({ restoreFocus: false });
  document.getElementById("message-input").focus();
}

function setComposerContext(context) {
  state.composerContext = context;
  const root = document.getElementById("composer-context");
  root.hidden = !context;
  document.getElementById("composer-context-label").textContent = context
    ? `${context.label}${context.anchor ? ` · ${humanizeAnchor(context.anchor)}` : ""}`
    : "";
  syncComposerForView();
}

function renderSourceContent(doc, value = "") {
  const text = normalizeSourceText(value, doc.filename);
  if (doc.file_type === "csv" && !/\|\s*---/.test(text)) return renderDelimitedTable(text);
  if (doc.file_type === "json") {
    return doc.structured_preview !== null && doc.structured_preview !== undefined
      ? `<div class="json-document">${renderJsonValue(doc.structured_preview)}</div>`
      : renderJsonDocument(text);
  }
  return renderMarkdown(text);
}

function normalizeSourceText(value, filename) {
  const lines = String(value || "").replaceAll("\r\n", "\n").split("\n");
  const cleaned = [];
  for (const line of lines) {
    const current = line.trim();
    if (!cleaned.length && current === filename) continue;
    const previous = cleaned.at(-1)?.trim();
    if (current && previous === current) continue;
    cleaned.push(line);
  }
  return cleaned.join("\n").replace(/\s+\|\s+\|\s+/g, " |\n| ").trim();
}

function renderDelimitedTable(value) {
  const rows = parseCsv(value).slice(0, 60);
  if (!rows.length) return `<p class="source-empty">No table rows were returned.</p>`;
  const width = Math.max(...rows.map((row) => row.length));
  const normalized = rows.map((row) => [...row, ...Array(Math.max(0, width - row.length)).fill("")]);
  const head = normalized[0];
  const body = normalized.slice(1);
  return `<div class="source-table-wrap"><table class="source-table"><thead><tr>${head.map((cell) => `<th>${escapeHtml(cell)}</th>`).join("")}</tr></thead><tbody>${body.map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>${rows.length >= 60 ? '<p class="source-limit">Showing the first 60 rows.</p>' : ""}`;
}

function parseCsv(value) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  const input = String(value || "");
  for (let index = 0; index < input.length; index += 1) {
    const character = input[index];
    if (character === '"' && quoted && input[index + 1] === '"') {
      cell += '"';
      index += 1;
    } else if (character === '"') quoted = !quoted;
    else if (character === "," && !quoted) { row.push(cell.trim()); cell = ""; }
    else if (character === "\n" && !quoted) { row.push(cell.trim()); rows.push(row); row = []; cell = ""; }
    else cell += character;
  }
  if (cell || row.length) { row.push(cell.trim()); rows.push(row); }
  return rows.filter((item) => item.some(Boolean));
}

function renderJsonDocument(value) {
  try {
    return `<div class="json-document">${renderJsonValue(JSON.parse(value))}</div>`;
  } catch {
    return renderMarkdown(value);
  }
}

function renderJsonValue(value, depth = 0) {
  if (depth > 5) return `<span class="json-scalar">${escapeHtml(JSON.stringify(value))}</span>`;
  if (Array.isArray(value)) {
    return `<ol class="json-list">${value.slice(0, 40).map((item) => `<li>${renderJsonValue(item, depth + 1)}</li>`).join("")}</ol>`;
  }
  if (value && typeof value === "object") {
    return `<dl class="json-object">${Object.entries(value).map(([key, item]) => `<div><dt>${escapeHtml(humanize(key))}</dt><dd>${renderJsonValue(item, depth + 1)}</dd></div>`).join("")}</dl>`;
  }
  return `<span class="json-scalar">${escapeHtml(value === null ? "null" : value)}</span>`;
}

function humanizeAnchor(anchor = "") {
  const value = String(anchor).replace(/^node:/, "");
  const paragraph = value.match(/^node_para_(\d+)$/);
  if (paragraph) return `Paragraph ${paragraph[1]}`;
  const table = value.match(/^node_(?:tbl|csv_table)(?:_(\d+))?$/);
  if (table) return table[1] ? `Table ${table[1]}` : "Table";
  return titleCase(value.replace(/^sec_/, "").replaceAll("_", " "));
}

function syncComposerForView() {
  const input = document.getElementById("message-input");
  if (!input) return;
  if (state.composerContext) {
    input.placeholder = `Ask about ${state.composerContext.label}`;
    return;
  }
  if (state.activeView === "files") {
    const doc = state.workspace?.documents?.[state.selectedFile];
    input.placeholder = doc ? `Ask about ${sourceDecisionLabel(doc.filename)[0]}` : "Ask about a source";
  } else if (state.activeView === "conversation") {
    input.placeholder = "Ask Bonsai or leave a team note";
  } else {
    input.placeholder = "Ask about this deal or leave a team note";
  }
}

function renderMessages() {
  const container = document.getElementById("conversation");
  if (!state.messages.length) return;
  const agentKey = state.workspace?.buzz?.agent_pubkey || state.status?.buzz?.agent_pubkey;
  const operatorKey = state.workspace?.buzz?.operator_pubkey || state.status?.buzz?.operator_pubkey;
  const focusId = new URLSearchParams(location.search).get("event");
  const workflowEvents = state.messages.filter(isWorkflowEvent);
  const seenMessages = new Set();
  const duplicateEvents = [];
  const conversationMessages = state.messages.filter((message) => !isWorkflowEvent(message)).reverse().filter((message) => {
    const key = `${message.pubkey}:${String(message.display_content || message.content || "").trim()}`;
    if (seenMessages.has(key)) { duplicateEvents.push(message); return false; }
    seenMessages.add(key);
    return true;
  }).reverse();
  const backgroundEvents = [...workflowEvents, ...duplicateEvents];
  const workflow = backgroundEvents.length ? `
    <details class="activity-history">
      <summary><span><strong>${backgroundEvents.length} background events</strong><small>Reviews, repeated prompts, blocked drafts, and setup records</small></span><span>Show history</span></summary>
      <div>${backgroundEvents.slice(-12).reverse().map((message) => renderWorkflowEvent(message, duplicateEvents.includes(message))).join("")}</div>
    </details>` : "";
  container.innerHTML = `${workflow}<div class="message-stream">${conversationMessages.map((message) => {
    const agent = message.pubkey === agentKey;
    const operator = message.pubkey === operatorKey;
    const name = agent ? "Bonsai" : operator ? "Jai" : `Member ${String(message.pubkey || "").slice(0, 6)}`;
    const time = new Date(message.created_at * 1000);
    const currentSourceGuard = message.prism_acceptance_state === "accepted"
      && String(message.prism_guard_version || "").startsWith(DEAL_ROOM_CHAT_GUARD_FAMILY);
    const signatureLabel = message.prism_acceptance_state === "quarantined_uncommitted"
      ? "Draft blocked"
      : message.signature_verified
        ? currentSourceGuard ? "Sources checked" : "Signed"
        : "Not verified";
    return `<article class="message${agent ? " agent" : ""}${operator ? " operator" : ""}${message.id === focusId ? " message-focus" : ""}" id="event-${message.id}">
      <span class="avatar">${agent ? "B" : escapeHtml(name[0])}</span>
      <div class="message-content"><div class="message-meta"><strong>${escapeHtml(name)}</strong><span>${escapeHtml(signatureLabel)}</span><time datetime="${time.toISOString()}">${formatTime(time)}</time></div><div class="message-body">${renderMarkdown(displayMessageContent(message, agent))}</div>${renderEvidenceScope(message.prism_evidence_scope)}</div>
    </article>`;
  }).join("")}</div>`;
  if (focusId) document.getElementById(`event-${focusId}`)?.scrollIntoView({ block: "center" });
  else container.scrollTop = container.scrollHeight;
}

function isWorkflowEvent(message) {
  const content = String(message.content || message.display_content || "");
  return message.prism_acceptance_state === "quarantined_uncommitted"
    || /^<!-- prism:first-pass/i.test(content)
    || /^<!-- prism:review/i.test(content)
    || /^#+\s*(First pass requested|Source evidence packet reviewed)/i.test(content)
    || /Confirm the local model you are using|your configured model identity|mounted deal-room folder/i.test(content);
}

function renderWorkflowEvent(message, duplicate = false) {
  const content = String(message.content || message.display_content || "");
  const time = new Date(message.created_at * 1000);
  let label = "Analysis event";
  let detail = "Saved with this room";
  if (duplicate) {
    label = "Repeated message";
    detail = "A matching message already appears in the conversation.";
  } else if (message.prism_acceptance_state === "quarantined_uncommitted") {
    label = "Draft blocked";
    detail = "The answer did not have a current source record.";
  } else if (/review/i.test(content)) {
    label = "Team decision saved";
    detail = "A review record was added to the room.";
  } else if (/request/i.test(content)) {
    label = "Decision review requested";
    detail = "The deal question was sent for analysis.";
  } else if (/draft|fallback/i.test(content)) {
    label = "Decision review produced";
    detail = "The result is available on Overview.";
  }
  return `<div class="workflow-event"><span></span><div><strong>${escapeHtml(label)}</strong><small>${escapeHtml(detail)}</small></div><time datetime="${time.toISOString()}">${formatTime(time)}</time></div>`;
}

function renderEvidenceScope(scope) {
  if (!scope || scope.measurement_state !== "current_parser_inventory_and_trace_bound_passage_selection") return "";
  const admitted = Number(scope.admitted_passage_count || 0);
  const searchable = Number(scope.corpus_searchable_node_count || 0);
  const parsed = Number(scope.corpus_parsed_node_count || 0);
  const documents = Number(scope.corpus_document_count || 0);
  return `<details class="evidence-scope"><summary>Evidence scope: ${admitted.toLocaleString()} passages selected from ${searchable.toLocaleString()} searchable nodes</summary><p>The current parser found ${parsed.toLocaleString()} nodes across ${documents.toLocaleString()} supported ${documents === 1 ? "file" : "files"}. The model received only the selected passages. These counts do not measure semantic coverage or prove full-document review.</p></details>`;
}

async function sendMessage(event) {
  event.preventDefault();
  const input = document.getElementById("message-input");
  const content = input.value.trim();
  if (!content) return;
  const button = document.getElementById("send-button");
  button.disabled = true;
  try {
    const result = await api("/api/workspace/messages", {
      method: "POST",
      body: JSON.stringify({ room: state.roomId, content: maybePrefixBonsai(withComposerContext(content)), ask_bonsai: document.getElementById("ask-bonsai").checked }),
    });
    input.value = "";
    setComposerContext(null);
    autoSizeComposer();
    document.getElementById("composer-hint").textContent = result.agent_reply?.answer_state === "rejected"
      ? `Saved to Buzz · Bonsai draft rejected · ${result.agent_reply.trace_id}`
      : document.getElementById("ask-bonsai").checked
        ? "Sent to Buzz · guarded Bonsai answer published"
        : "Saved to the shared room";
    await loadMessages();
  } catch (error) {
    document.getElementById("composer-hint").textContent = `Not sent · ${error.message}`;
    showToast(`Message not sent: ${error.message}`, true);
  } finally { button.disabled = false; input.focus(); }
}

function maybePrefixBonsai(content) {
  // Do NOT inject a literal "@Bonsai" into the message body. buzz-cli parses
  // @handle mentions out of the content and resolves them against channel
  // members -- and members are added by pubkey only (`channels add-member`
  // takes --pubkey/--role, with no name or handle option), so "@Bonsai" can
  // never resolve and the send fails with:
  //   mention '@bonsai' does not match a current channel member
  // The ask-bonsai checkbox already routes through the server, which passes
  // `--mention <agent_pubkey>` -- the mechanism that actually works. The text
  // prefix was redundant and broke every send.
  return content;
}

function withComposerContext(content) {
  const context = state.composerContext;
  if (!context) return content;
  const citation = context.anchor ? `[${context.source}#${context.anchor}]` : context.source;
  return `About ${citation}\n\n${content}`;
}

function editDigest() {
  document.getElementById("digest-input").value = state.digest;
  document.getElementById("digest-rendered").hidden = true;
  document.getElementById("digest-form").hidden = false;
  document.getElementById("edit-digest-button").hidden = true;
}

function cancelDigest() {
  document.getElementById("digest-rendered").hidden = false;
  document.getElementById("digest-form").hidden = true;
  document.getElementById("edit-digest-button").hidden = false;
}

async function saveDigest(event) {
  event.preventDefault();
  const content = document.getElementById("digest-input").value.trim();
  try {
    const result = await api("/api/workspace/digest", { method: "POST", body: JSON.stringify({ room: state.roomId, content }) });
    state.digest = content;
    state.digestVerification = result.signature_verified ? {
      state: "verified",
      scheme: result.signature_scheme,
      event_id: result.event_id,
    } : null;
    document.getElementById("digest-rendered").innerHTML = renderMarkdown(content);
    renderDigestVerification();
    cancelDigest();
    showToast("Digest saved to the Buzz canvas");
  } catch (error) { showToast(`Digest not saved: ${error.message}`, true); }
}

async function openFolder(event) {
  event.preventDefault();
  const path = document.getElementById("folder-path").value.trim();
  const status = document.getElementById("folder-status");
  const button = document.getElementById("create-room-button");
  const previewMatches = state.folderPreview?.folder_path === path;
  status.textContent = previewMatches
    ? "Verifying the preview and creating the private Buzz room"
    : "Inspecting supported files locally. Buzz will not be changed";
  button.disabled = true;
  try {
    if (!previewMatches) {
      const preview = await api("/api/deal-room/preview", {
        method: "POST",
        body: JSON.stringify({ folder_path: path }),
      });
      renderFolderPreview(preview);
      if (preview.preview_state !== "ready") {
        status.textContent = "No supported files are ready to index.";
        button.disabled = true;
        return;
      }
      status.textContent = "Nothing has been published. Review the inventory, then create the room.";
      button.textContent = "Create private room";
      button.disabled = false;
      return;
    }
    const room = await api("/api/deal-room/open", {
      method: "POST",
      body: JSON.stringify({
        folder_path: path,
        preview_sha256: state.folderPreview.preview_sha256,
      }),
    });
    location.assign(room.canonical_path);
  } catch (error) {
    if (error.body?.preview) renderFolderPreview(error.body.preview);
    status.textContent = error.message;
    button.disabled = false;
  }
}

function resetFolderPreview() {
  state.folderPreview = null;
  document.getElementById("folder-preview").hidden = true;
  document.getElementById("folder-status").textContent = "";
  const button = document.getElementById("create-room-button");
  button.textContent = "Preview folder";
  button.disabled = false;
}

function renderFolderPreview(preview) {
  state.folderPreview = preview;
  const panel = document.getElementById("folder-preview");
  panel.hidden = false;
  document.getElementById("folder-preview-summary").textContent =
    `${preview.document_count} supported ${preview.document_count === 1 ? "file" : "files"}`;
  document.getElementById("folder-preview-size").textContent =
    `${formatBytes(preview.total_size_bytes)} · about ${Number(preview.estimated_tokens).toLocaleString()} tokens`;
  const provenance = preview.source_provenance || {};
  const provenanceElement = document.getElementById("folder-preview-provenance");
  provenanceElement.textContent = `${provenance.label || "Operator-selected local folder"}. ${provenance.meaning || "Customer origin and authorization are not independently verified."}`;
  document.getElementById("folder-preview-files").innerHTML = preview.files.map((file) =>
    `<li><span>${escapeHtml(file.filename)}</span><small>${escapeHtml(file.file_type.toUpperCase())} · ${formatBytes(file.raw_size_bytes)}</small></li>`
  ).join("") || "<li><span>No supported files</span></li>";
  const warnings = document.getElementById("folder-preview-warnings");
  warnings.hidden = preview.warnings.length === 0;
  warnings.innerHTML = preview.warnings.length
    ? `<strong>${preview.warnings.length} ${preview.warnings.length === 1 ? "warning" : "warnings"}</strong>${preview.warnings.map((warning) => `<p>${escapeHtml(warning.filename)} · ${escapeHtml(warning.error)}</p>`).join("")}`
    : "";
}

function renderEvidence(evals) {
  const buzz = state.status?.buzz || {};
  const acp = state.status?.buzz_acp_scope || {};
  const workspaceReady = Boolean(buzz.workspace_ready);
  const configured = Boolean(state.status?.local_inference_configured);
  const localProvider = state.status?.providers?.find((provider) => provider.provider_id === "local_bonsai") || {};
  const localProviderScope = state.status?.configured_local_provider_network_scope;
  const invokedThisProcess = Boolean(state.status?.local_inference_invoked_in_process);
  const recordedHistory = Boolean(state.status?.local_inference_recorded_history);
  const deployment = state.status?.measured_local_deployment || {};
  const traceStore = state.status?.trace_store || {};
  const pdfOcr = state.status?.document_ingestion?.pdf_ocr || {};
  const cloudConsent = state.status?.cloud_consent || {};
  const model = state.status?.current_process_local_model
    || state.status?.configured_local_model_name
    || state.status?.last_invoked_local_model;
  const runtimeValue = invokedThisProcess
    ? `${model || "Unnamed local model"} · invoked this process`
    : configured && recordedHistory
      ? `${model || "Unnamed local model"} · configured · prior trace recorded`
      : configured ? `${model || "Unnamed local model"} · configured only` : "Not configured";
  const runtimeNote = invokedThisProcess
    ? "A trace created by this server process identifies the returned local model."
    : configured && recordedHistory
      ? "The endpoint is configured and prior trace history exists, but this server process has not invoked it."
      : configured
        ? `The endpoint is configured with scope ${localProviderScope || "unverified"}, but no local invocation trace is available.`
        : "No local provider is configured; model-backed runs fail closed.";
  const cards = [
    ["Workspace substrate", workspaceReady ? "Buzz workspace ready" : "Unavailable", workspaceReady ? "Room messages and the current canvas are shown as signed only after raw event verification." : "Workspace writes fail closed."],
    ["Direct Buzz agent (experimental)", acp.configured ? (acp.room_id === state.roomId ? "Enabled for this room" : `Scoped to ${acp.room_id}`) : "Not launched", acp.configured ? `Experimental ACP listens only to ${acp.channel_id} with owner-only input and memory disabled. This scope proof is not a response-quality proof.` : "The proven WebUI path remains separately source-scoped and publishes its answers as signed Buzz events."],
    ["Local model runtime", runtimeValue, runtimeNote],
    [
      "Active context admission",
      localProvider.context_admission === "loaded_model_tokenizer_with_runtime_margin"
        ? `${Number(localProvider.context_window_tokens || 0).toLocaleString()} fitted tokens`
        : "Not enforced",
      localProvider.context_admission === "loaded_model_tokenizer_with_runtime_margin"
        ? "Before inference, Prism applies the active llama.cpp chat template, counts with the loaded model tokenizer, adds an explicit runtime-wrapper margin, reserves the configured output budget, and rejects requests that exceed the measured fitted context. The model catalog maximum is not treated as usable capacity."
        : "No exact loaded-model token admission is configured. Catalog context metadata is not an operational capacity claim.",
    ],
    [
      "Local provider network scope",
      configured ? (localProviderScope === "loopback_ip_literal" ? "Loopback IP URL enforced" : "Unverified") : "Not configured",
      configured
        ? "Prism accepts the local provider only when its URL uses plain HTTP and a loopback IP literal. This URL check does not prove zero egress or process isolation."
        : "No local provider URL is configured.",
    ],
    [
      "Hybrid AI cloud boundary",
      cloudConsent.dispatch_ready_for_signed_request
        ? "Ready for signed requests"
        : "Denied before network",
      cloudConsent.dispatch_ready_for_signed_request
        ? "Each cloud request needs a short-lived policy signature bound to the prompt, room snapshot, provider, model, nonce, and expiry. Sending deal-room context needs a second signature from a distinct data-owner key. Prism restores each exact event from Buzz before consuming it once. Signing keys are not entered in this browser."
        : `Cloud dispatch is blocked. Provider configured: ${cloudConsent.provider_configured ? "yes" : "no"}. Consent authority configured: ${cloudConsent.authority_configured ? "yes" : "no"}. Buzz ready: ${workspaceReady ? "yes" : "no"}. Signed approvals must be published to and restored from Buzz. The browser cannot turn cloud access on with a checkbox.`,
    ],
    [
      "Measured deployment identity",
      deployment.verified ? `${deployment.model || "Local model"} · artifacts and runtime verified` : "Not verified",
      deployment.verified
        ? `${deployment.artifact_count} current artifact(s) match the saved hashes · active llama.cpp ${deployment.active_runtime?.runtime_version || "version unavailable"} · active fitted context ${Number(deployment.active_runtime?.effective_config?.fitted_context_length || 0).toLocaleString()} tokens · process bind ${deployment.active_runtime?.effective_config?.bind_host || "host unavailable"}:${deployment.active_runtime?.effective_config?.bind_port || "port unavailable"}. Catalog/file size match: ${deployment.catalog_size_matches_artifact ? "yes" : "no, discrepancy preserved"}. Artifact hashes verified ${deployment.verified_at ? new Date(deployment.verified_at).toLocaleString() : "time unavailable"}; active runtime checked ${deployment.active_runtime?.checked_at ? new Date(deployment.active_runtime.checked_at).toLocaleString() : "time unavailable"}. Artifacts are rechecked when file identity changes. Loopback binding is not a zero-egress, quality, or clean-machine claim.`
        : deployment.artifact_files_verified
          ? `Artifact hashes match, but the active llama-server does not match the measured runtime. ${deployment.active_runtime?.errors?.join(" ") || "Current runtime verification failed."}`
          : "No current file-bound deployment identity is available. Provider configuration or invocation does not substitute for it.",
    ],
    [
      "Trace store",
      traceStore.format === "hash_chained_local_jsonl_v1"
        ? `Hash-chained local JSONL · ${Number(traceStore.entry_count || 0).toLocaleString()} events`
        : traceStore.format === "memory_only" ? "Memory only" : "Unavailable",
      traceStore.meaning || "No trace-store integrity statement is available.",
    ],
    ["Source boundary", "Local folder", "Prism publishes citations and derived markup, not raw source files."],
    [
      "Scanned PDF support",
      pdfOcr.available ? "Apple Vision OCR available" : "OCR unavailable",
      pdfOcr.available
        ? "Pages without usable embedded text can be read on this macOS host. Reading order can be wrong, tables and layout are not reconstructed, and accuracy has not been benchmarked."
        : "Image-only PDF pages cannot be admitted on this host. Text-bearing PDF parsing remains separate.",
    ],
  ];
  document.getElementById("evidence-grid").innerHTML = cards.map(([label, value, note]) => `<div class="evidence-card"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong><p>${escapeHtml(note)}</p></div>`).join("");
  const traces = evals.traces || [];
  document.getElementById("run-list").innerHTML = `<span class="eyebrow">Ten most recent runs</span>${traces.length ? traces.slice(-10).reverse().map((trace) => {
    const evaluationState = trace.evaluation_state || { state: "unverified", label: "No evaluations", explanation: "No evaluation state was returned." };
    const stateClass = evaluationState.state === "rejected" ? "failed" : ["awaiting_review", "unverified", "excluded"].includes(evaluationState.state) ? "pending" : "passed";
    return `<div class="run-row" data-trace-id="${escapeHtml(trace.trace_id)}" data-evaluation-state="${escapeHtml(evaluationState.state)}"><code>${escapeHtml(trace.trace_id)}</code><span><strong>${escapeHtml(trace.query)}</strong><small>${escapeHtml(evaluationState.explanation)}</small></span><span class="run-state ${stateClass}">${escapeHtml(evaluationState.label)}</span></div>`;
  }).join("") : `<p class="muted">No persisted Prism analysis traces yet. A configured endpoint alone is not invocation evidence.</p>`}`;
}

function renderWorkspaceNotBound() {
  document.getElementById("room-name").textContent = "This room is not bound to Buzz";
  document.getElementById("conversation").innerHTML = errorState("No canonical workspace yet", "Open the folder again while the Buzz relay is live. Prism will create a private channel and shared canvas.");
}

function renderDependencyDown(title, detail) {
  document.getElementById("conversation").innerHTML = errorState(title, detail);
  document.getElementById("relay-dot").className = "status-dot down";
  document.getElementById("relay-label").textContent = "Dependency offline";
}

function errorState(title, detail) {
  return `<div class="empty-conversation"><span class="sculpture"></span><h2>${escapeHtml(title)}</h2><p>${escapeHtml(detail)}</p></div>`;
}

function switchView(view) {
  state.activeView = view;
  document.querySelectorAll(".workspace-tab").forEach((tab) => {
    const selected = tab.dataset.view === view;
    tab.classList.toggle("active", selected);
    if (tab.matches('[role="tab"]')) {
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
    } else {
      tab.toggleAttribute("aria-current", selected);
    }
  });
  document.querySelectorAll(".view-panel").forEach((panel) => {
    const selected = panel.id === `view-${view}`;
    panel.classList.toggle("active", selected);
    panel.hidden = !selected;
  });
  const suffix = { "first-pass": "first-pass", conversation: "discussion", digest: "digest", files: "files", evidence: "evidence", evaluation: "evaluation" }[view];
  const desiredPath = `/rooms/${encodeURIComponent(state.roomId)}/${suffix}`;
  if (suffix && location.pathname !== desiredPath) history.replaceState({}, "", desiredPath);
  syncComposerForView();
}

function moveWorkspaceTabFocus(event) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const tabs = [...document.querySelectorAll('.workspace-tab[role="tab"]')];
  const current = tabs.indexOf(event.currentTarget);
  const next = event.key === "Home"
    ? 0
    : event.key === "End"
    ? tabs.length - 1
    : (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
  tabs[next].focus();
  switchView(tabs[next].dataset.view);
}

function copyRoomLink() {
  navigator.clipboard.writeText(`${location.origin}/rooms/${encodeURIComponent(state.roomId)}`).then(() => showToast("Canonical room link copied"));
}

function renderMarkdown(markdown = "") {
  const normalizedMarkdown = normalizeReadableMath(
    String(markdown).replace(/\[SOURCE\s+(\[[^\]]+\])\]/gi, "$1"),
  );
  const escaped = escapeHtml(normalizedMarkdown).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  const lines = escaped.split("\n");
  let html = "";
  let listType = null;
  const closeList = () => {
    if (listType) html += `</${listType}>`;
    listType = null;
  };
  const tableCells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const next = lines[index + 1] || "";
    if (line.includes("|") && /^\s*\|?\s*:?-{3,}/.test(next)) {
      closeList();
      const headings = tableCells(line);
      const rows = [];
      index += 2;
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        rows.push(tableCells(lines[index]));
        index += 1;
      }
      index -= 1;
      html += `<div class="source-table-wrap"><table class="source-table"><thead><tr>${headings.map((cell) => `<th>${renderInlineCitations(cell)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${renderInlineCitations(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
      continue;
    }
    if (/^[-*] /.test(line)) {
      if (listType !== "ul") { closeList(); html += "<ul>"; listType = "ul"; }
      html += `<li>${renderInlineCitations(line.slice(2))}</li>`;
      continue;
    }
    if (/^\d+\.\s+[A-Z][A-Z &amp;()]+$/.test(line)) {
      closeList();
      html += `<h2>${renderInlineCitations(line.replace(/^\d+\.\s+/, ""))}</h2>`;
      continue;
    }
    if (/^\d+\. /.test(line)) {
      if (listType !== "ol") { closeList(); html += "<ol>"; listType = "ol"; }
      html += `<li>${renderInlineCitations(line.replace(/^\d+\. /, ""))}</li>`;
      continue;
    }
    closeList();
    if (line.startsWith("### ")) html += `<h3>${renderInlineCitations(line.slice(4))}</h3>`;
    else if (line.startsWith("## ")) html += `<h2>${renderInlineCitations(line.slice(3))}</h2>`;
    else if (line.startsWith("# ")) html += `<h1>${renderInlineCitations(line.slice(2))}</h1>`;
    else if (line.startsWith("&gt; ")) html += `<blockquote>${renderInlineCitations(line.slice(5))}</blockquote>`;
    else if (/^\s*---+\s*$/.test(line)) html += "<hr>";
    else if (/^\[[^\[\]#]+\.(?:md|txt|html?|pdf|csv|json|xlsx)#[^\[\]]+\]$/i.test(line)) {
      html += renderInlineCitations(line);
    }
    else if (line.trim()) html += `<p>${renderInlineCitations(line)}</p>`;
  }
  closeList();
  return html;
}

function normalizeReadableMath(value = "") {
  return String(value)
    .replace(/\$([^$\n]+)\$/g, "$1")
    .replace(/\\times\b/g, "×")
    .replace(/\\%/g, "%")
    .replace(/\\leq?\b/g, "≤")
    .replace(/\\geq?\b/g, "≥");
}

function parseCitation(value = "") {
  const match = String(value).match(/^\[([^#\]]+)#([^\]]+)\]$/);
  return match ? { source: match[1], anchor: match[2] } : null;
}

function sourceDecisionLabel(source = "") {
  const value = String(source);
  if (/credit_agreement/i.test(value)) return ["Debt terms", "Credit agreement"];
  if (/financial_model/i.test(value)) return ["Financial model", "Cash flow and debt paydown"];
  if (/returns_sensitivity/i.test(value)) return ["Sponsor returns", "IRR and MoIC sensitivity"];
  if (/information_memorandum/i.test(value)) return ["Deal overview", "Transaction and capital structure"];
  const label = value.replace(/^\d+_/, "").replace(/\.[^.]+$/, "").replaceAll("_", " ");
  return [titleCase(label), "Deal room file"];
}

function renderFallbackReview(draft) {
  const priority = { "Debt terms": 0, "Financial model": 1, "Sponsor returns": 2, "Deal overview": 3 };
  const files = new Map();
  for (const value of draft.citations || []) {
    const citation = parseCitation(value);
    if (!citation) continue;
    const existing = files.get(citation.source);
    const cashSweepPassage = /credit_agreement/i.test(citation.source) && /para_3$/i.test(citation.anchor);
    if (!existing || cashSweepPassage) files.set(citation.source, citation);
  }
  const sourceButtons = [...files.values()].sort((left, right) => {
    const leftLabel = sourceDecisionLabel(left.source)[0];
    const rightLabel = sourceDecisionLabel(right.source)[0];
    return (priority[leftLabel] ?? 99) - (priority[rightLabel] ?? 99);
  }).map(({ source, anchor }) => {
    const [label, detail] = sourceDecisionLabel(source);
    return `<button class="priority-source" type="button" data-source-citation data-source="${escapeHtml(source)}" data-anchor="${escapeHtml(anchor)}"><span><strong>${escapeHtml(label)}</strong><small>${escapeHtml(detail)}</small></span><span aria-hidden="true">Preview</span></button>`;
  }).join("");
  return `
    <section class="decision-block" data-content-id="segment.pause_reason">
      <h2>Why the review is paused</h2>
      <p>The automated review did not meet the source rules. Check the priority files before the team advances.</p>
    </section>
    <section class="decision-block" data-content-id="segment.decision_question_result">
      <h2>Decision question</h2>
      <p class="decision-question-copy">${escapeHtml(decisionQuestionSummary(draft.investment_screen))}</p>
    </section>
    <section class="decision-block" data-content-id="segment.priority_sources">
      <h2>Review next</h2>
      <div class="priority-source-list">${sourceButtons || "<p>No priority file was linked to the review.</p>"}</div>
    </section>`;
}

function decisionQuestionSummary(value = "") {
  if (state.roomId === "project_titan_lbo") {
    return "Should Project Titan advance despite the mismatch between debt paydown and the Section 2.02 cash sweep terms?";
  }
  const question = String(value || "No decision question was saved for this review.").trim();
  return question.length <= 240 ? question : `${question.slice(0, 237).trimEnd()}...`;
}

function enhanceBriefDocument() {
  const root = document.getElementById("first-pass-draft");
  root.querySelectorAll("h3").forEach((heading) => {
    if (!/source excerpt|screen-matched source excerpt/i.test(heading.textContent || "")) return;
    const details = document.createElement("details");
    details.className = "source-disclosure";
    const summary = document.createElement("summary");
    summary.textContent = "Source passage";
    heading.before(details);
    details.append(summary);
    let node = heading;
    while (node) {
      const next = node.nextSibling;
      if (node !== heading && node.nodeType === Node.ELEMENT_NODE && ["H2", "H3"].includes(node.tagName)) break;
      details.append(node);
      node = next;
    }
    heading.hidden = true;
    const citation = details.querySelector("[data-source-citation]");
    if (citation) {
      const source = citation.dataset.source || "source";
      citation.textContent = `Open ${source}`;
      citation.classList.add("brief-source-link");
      details.before(citation);
    }
  });
}

function displayMessageContent(message, agent) {
  const content = String(message.display_content || message.content || "");
  if (!agent || !message.signature_verified) return content;
  const marker = /^<!-- prism:deal-room-answer [^>]+ -->\n/;
  const firstPassMarker = /^<!-- prism:first-pass-draft [^>]+ -->\n/;
  if (!marker.test(content)) return content.replace(firstPassMarker, "");
  const labels = {
    consideration: "Per-share consideration",
    closing_conditions: "Closing conditions",
    stockholder_approval: "Stockholder approval",
    regulatory_approval: "Regulatory approval",
    financing_condition: "Financing condition",
    termination_fee: "Termination fee",
    financing: "Financing",
    capital_structure: "Debt tranches and amounts",
    entry_leverage_absence: "Entry debt-to-EBITDA disclosure",
  };
  return content.replace(marker, "").split("\n").map((line) => line.replace(
    /^[-*]\s+([a-z_]+):\s*/,
    (_full, key) => `- **${labels[key] || humanize(key)}:** `,
  )).join("\n");
}

function renderInlineCitations(html = "") {
  return html.replace(/\[([^\[\]#]+\.(?:md|txt|html?|pdf|csv|json|xlsx))#([^\[\]]+)\]/gi, (_full, source, anchor) => {
    const label = sourceDecisionLabel(source)[0];
    return `<button class="citation-link" type="button" data-source-citation data-source="${source}" data-anchor="${anchor}" title="${source} · ${anchor}"><span>${escapeHtml(label)}</span><small>${escapeHtml(humanizeAnchor(anchor))}</small></button>`;
  });
}

function autoSizeComposer() {
  const input = document.getElementById("message-input");
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 170)}px`;
}

function setWorkspaceLoading(loading) {
  document.body.classList.toggle("loading", loading);
}

function showToast(message, error = false) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.style.background = error ? "#7b3f34" : "";
  toast.classList.add("visible");
  window.setTimeout(() => toast.classList.remove("visible"), 2800);
}

function formatTime(date) {
  return new Intl.DateTimeFormat([], { hour: "numeric", minute: "2-digit" }).format(date);
}
function formatBytes(value = 0) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
function fileLabel(type = "file") { return type.replace(/^\./, "").slice(0, 4).toUpperCase() || "FILE"; }
function humanize(value = "") { return String(value).replaceAll("_", " "); }
function friendlyModelName(value = "") { return String(value || "").startsWith("27b") ? "Bonsai 27B" : String(value || "No local model"); }
function titleCase(value = "") { return String(value).replace(/\b\w/g, (character) => character.toUpperCase()); }
function escapeHtml(value = "") { return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[char]); }
