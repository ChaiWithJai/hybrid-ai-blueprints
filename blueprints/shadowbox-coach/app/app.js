// Shadowbox Coach — webcam punch tracker (MediaPipe pose) + Bonsai corner coach.
// All inference is on-device: pose in the browser, coaching via LM Studio on localhost.

import { L, BONES, CFG, HandTracker, makeSmoother, SYNTH, syntheticFrame, ShoulderRotation, punchPower } from "./punch.js";

const PARAMS = new URLSearchParams(location.search);
const SYNTHETIC = PARAMS.has("synthetic");
const POSE_MODEL = ["lite", "full", "heavy"].includes(PARAMS.get("model")) ? PARAMS.get("model") : "lite";
let ROUND_SEC = 180, REST_SEC = 60; // mutable: a workout day can prescribe its own timer

// ---- DOM ----
const $ = (id) => document.getElementById(id);
const video = $("video"), overlay = $("overlay"), ctx = overlay.getContext("2d");
const stageMsg = $("stage-msg"), flash = $("punch-flash"), debugPanel = $("debug-panel");

// ---- session state ----
const stats = { total: 0, JAB: 0, CROSS: 0, HOOK: 0, UPPERCUT: 0, peakSpeed: 0 };
const punchLog = []; // {t, type, hand, speed} — feeds PPM + the coach
let roundNum = 1, roundLeft = ROUND_SEC, resting = false, ticking = null;

// CompuBox convention: jabs vs power (everything that isn't the lead straight)
const power = (s) => s.CROSS + s.HOOK + s.UPPERCUT;
let roundStart = { ...stats };
const roundHistory = []; // {round, thrown, jabs, power}

function closeRound() {
  const entry = {
    round: roundNum,
    thrown: stats.total - roundStart.total,
    jabs: stats.JAB - roundStart.JAB,
    power: power(stats) - power(roundStart),
  };
  roundHistory.push(entry);
  const panel = $("rounds-panel");
  panel.hidden = false;
  panel.querySelector("tbody").innerHTML = roundHistory
    .map((r) => `<tr><td>${r.round}</td><td>${r.thrown}</td><td>${r.jabs}</td><td>${r.power}</td></tr>`)
    .join("");
  saveRoundToHistory(entry);
  renderTrends();
}

// ---- cross-session trends (localStorage, per-browser, best-effort) ----
const HISTORY_KEY = "shadowbox-history";
function loadHistory() {
  try { return JSON.parse(localStorage.getItem(HISTORY_KEY)) || []; } catch { return []; }
}
function saveRoundToHistory(entry) {
  try {
    const h = loadHistory();
    h.push({ day: new Date().toISOString().slice(0, 10), ...entry,
      avgPower: form.powerN ? Math.round(form.powerSum / form.powerN) : null });
    localStorage.setItem(HISTORY_KEY, JSON.stringify(h.slice(-200)));
  } catch { /* storage unavailable — trends just stay session-local */ }
}
function renderTrends() {
  const h = loadHistory();
  if (h.length < 2) return;
  const el = $("trends-panel");
  el.hidden = false;
  // sparkline of punches thrown per round, last 24 rounds
  const recent = h.slice(-24);
  const max = Math.max(...recent.map((r) => r.thrown), 1);
  const BARS = "▁▂▃▄▅▆▇█";
  const spark = recent.map((r) => BARS[Math.min(7, Math.floor((r.thrown / max) * 7.99))]).join("");
  const best = Math.max(...h.map((r) => r.thrown));
  $("trends-line").textContent = `${spark}  best ${best}/rd · ${h.length} rounds logged`;
}
renderTrends();

// =========================================================================
// Workout mode: the 2-phase guide (workout_guide.json, built by the
// prismml-eng agent civilization from boxing.dharmicdata.org). Each day
// drives the round timer and the coach's curriculum focus.
// =========================================================================
let guide = null, woDays = [], woIdx = 0;
const WO_KEY = "shadowbox-workout";
function woProgress() {
  try { return JSON.parse(localStorage.getItem(WO_KEY)) || { done: [] }; } catch { return { done: [] }; }
}
function woDayKey(d) { return `${d.program}-w${d.week}-d${d.day}`; }

// every training event lands in pipeline/datasets/training_log.jsonl — the
// dataset the error-discovery skill reviews and the MLflow ingester reads
function logEvent(entry) {
  fetch("/log", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ at: new Date().toISOString(), ...entry }),
  }).catch(() => {});
}

fetch("workout_guide.json").then((r) => r.ok ? r.json() : null).then((g) => {
  if (!g) return;
  guide = g;
  woDays = [...g.phase1.days, ...g.phase2.days];
  const prog = woProgress();
  const firstUndone = woDays.findIndex((d) => !prog.done.includes(woDayKey(d)));
  woIdx = firstUndone === -1 ? 0 : firstUndone;
  $("workout-panel").hidden = false;
  $("program-title").textContent = guide.title.toUpperCase();
  buildProgramGrid();
  renderWorkout();
  renderStreak();
  applyDisclosure();
  // first run: three steps and the phase-1 goal, once
  try {
    if (!localStorage.getItem("shadowbox-welcomed")) {
      $("welcome-goal").textContent = `${guide.tagline}`;
      $("welcome").hidden = false;
    }
  } catch { /* storage unavailable */ }
}).catch(() => {});

$("welcome-go").addEventListener("click", () => {
  $("welcome").hidden = true;
  try { localStorage.setItem("shadowbox-welcomed", "1"); } catch { /* fine */ }
  initAudio();
});

// ---- earned disclosure: the cockpit reveals itself as the athlete earns it ----
// day 0: stage + today + coach only · day 1+: program map + streak ·
// day 3+: trends · week 4+ of phase 1 (or phase 2): the gate panel · ▦ shows all
function applyDisclosure() {
  let full = false;
  try { full = localStorage.getItem("shadowbox-full") === "1"; } catch { /* fine */ }
  const done = woProgress().done.length;
  const d = woDays[woIdx];
  document.body.classList.toggle("simple", !full && done < 1);
  $("gate-panel").hidden = !(full || (d && (d.week >= 4 || d.program === guide?.phase2.program)));
  if ($("trends-panel")) $("trends-panel").hidden = $("trends-panel").hidden || (!full && done < 3);
}
$("btn-map").addEventListener("click", () => {
  try {
    const cur = localStorage.getItem("shadowbox-full") === "1";
    localStorage.setItem("shadowbox-full", cur ? "0" : "1");
  } catch { /* fine */ }
  applyDisclosure();
  renderTrends();
});

// ---- program map: all 70 days, one glance ----
function buildProgramGrid() {
  const grid = $("program-grid");
  grid.innerHTML = "";
  let idx = 0;
  for (const [pname, p] of [["PHASE 1 · " + guide.phase1.title, guide.phase1], ["PHASE 2 · " + guide.phase2.title, guide.phase2]]) {
    const head = document.createElement("div");
    head.className = "pg-phase";
    head.textContent = pname.toUpperCase();
    grid.appendChild(head);
    for (let w = 1; w <= 5; w++) {
      const row = document.createElement("div");
      row.className = "pg-week";
      for (const d of p.days.filter((x) => x.week === w)) {
        const cell = document.createElement("button");
        cell.className = "pg-day" + (d.rounds ? "" : " rest");
        cell.textContent = d.day;
        cell.title = `${d.title} — ${d.focus}`;
        const myIdx = idx++;
        cell.dataset.idx = myIdx;
        cell.addEventListener("click", () => { woIdx = myIdx; renderWorkout(); });
        row.appendChild(cell);
      }
      grid.appendChild(row);
    }
  }
}
function paintProgramGrid() {
  const prog = woProgress();
  document.querySelectorAll(".pg-day").forEach((cell) => {
    const d = woDays[Number(cell.dataset.idx)];
    cell.classList.toggle("done", prog.done.includes(woDayKey(d)));
    cell.classList.toggle("current", Number(cell.dataset.idx) === woIdx);
  });
}
$("btn-today").addEventListener("click", () => {
  const prog = woProgress();
  const first = woDays.findIndex((d) => !prog.done.includes(woDayKey(d)));
  woIdx = first === -1 ? woDays.length - 1 : first;
  renderWorkout();
});

// ---- day streak (calendar days with a completed day) ----
function dayLog() {
  try { return JSON.parse(localStorage.getItem("shadowbox-daylog")) || []; } catch { return []; }
}
function renderStreak() {
  const days = [...new Set(dayLog().map((e) => e.date))].sort();
  const todayKey = new Date().toISOString().slice(0, 10);
  const trainedToday = days.includes(todayKey);
  let streak = 0;
  const today = new Date();
  for (let i = 0; ; i++) {
    const d = new Date(today);
    d.setDate(today.getDate() - i);
    const key = d.toISOString().slice(0, 10);
    if (days.includes(key)) streak++;
    else if (i > 0) break; // today itself may not be trained yet
  }
  const done = woProgress().done.length;
  const el = $("streak-line");
  el.textContent = streak > 0
    ? (trainedToday ? `🔥 ${streak} ✓ · ${done}/${woDays.length || 70}` : `🔥 ${streak} — train today · ${done}/${woDays.length || 70}`)
    : `${done}/${woDays.length || 70} days`;
  el.classList.toggle("at-risk", streak > 0 && !trainedToday);
}
renderStreak(); // streak lives even if the guide fails to load

// day 20 must not look like day 1: seed the coach with last session
{
  const last = dayLog().at?.(-1);
  if (last) {
    const gapDays = Math.round((Date.now() - new Date(last.date).getTime()) / 86400000);
    $("coach-text").textContent = gapDays > 1
      ? `↩ back after ${gapDays} days — pick up where you left off: ${last.title}. Shake the rust off.`
      : `last ▸ ${last.title}: ${last.stats?.total ?? "–"} 👊 · ⚡${last.form?.avg_power ?? "–"} · guard ${last.form?.guard_height_sw ?? "–"} sw`;
  }
}

// ---- phase gate: this session's telemetry vs the promotion targets ----
// live session values, falling back to the LAST logged session so the gates
// show yesterday's evidence instead of dashes before the first punch today
const lastForm = () => dayLog().at?.(-1)?.form || {};
const GATE_CHECKS = {
  arm_punch_pct: { get: () => form.powerPunches ? (100 * form.armPunches / form.powerPunches) : lastForm().arm_punch_pct ?? null, pass: (v) => v <= 25, fmt: (v) => v.toFixed(0) + "%" },
  guard_height_sw: { get: () => form.guardN ? form.guardSum / form.guardN : lastForm().guard_height_sw ?? null, pass: (v) => v >= 0.85, fmt: (v) => v.toFixed(2) + " sw" },
  avg_retraction_ms: { get: () => form.retractN ? form.retractSum / form.retractN : lastForm().avg_retraction_ms ?? null, pass: (v) => v <= 350, fmt: (v) => v.toFixed(0) + " ms" },
  punches_per_round: { get: () => roundHistory.length ? roundHistory[roundHistory.length - 1].thrown : (stats.total || dayLog().at?.(-1)?.stats?.total || null), pass: (v) => v >= 120, fmt: (v) => String(Math.round(v)) },
  avg_power: { get: () => form.powerN ? form.powerSum / form.powerN : lastForm().avg_power ?? null, pass: (v) => v >= 55, fmt: (v) => v.toFixed(0) },
};
function renderGates() {
  if (!guide) return;
  $("gate-list").innerHTML = guide.gates.map((g) => {
    const chk = GATE_CHECKS[g.stat];
    const v = chk ? chk.get() : null;
    const ok = v != null && chk.pass(v);
    return `<li class="${ok ? "gate-pass" : "gate-fail"}">${ok ? "●" : "○"} ${g.stat.replaceAll("_", " ")}: <b>${v == null ? "—" : chk.fmt(v)}</b> <span>(${g.threshold})</span></li>`;
  }).join("");
}

// per-day block check-offs, persisted
function blockChecks() {
  try { return JSON.parse(localStorage.getItem("shadowbox-blockchecks")) || {}; } catch { return {}; }
}
function renderWorkout() {
  const d = woDays[woIdx];
  if (!d) return;
  const phase = d.program === guide.phase1.program ? 1 : 2;
  const prog = woProgress();
  const checks = blockChecks()[woDayKey(d)] || [];
  $("workout-label").textContent = `PHASE ${phase} · WEEK ${d.week} · DAY ${d.day}`;
  $("wo-title").textContent = d.title;
  // the day header describes the day's real shape, block by block — the old
  // day-level "6 × 3:00" lied whenever block 1 prescribed something else
  previewPlan = d.blocks.length ? buildSessionPlan(d) : null;
  if (previewPlan) {
    const estMin = Math.round(previewPlan.steps.reduce((a, s) => a + (s.sec || 60), 0) / 60);
    const timed = previewPlan.steps.filter((s) => s.kind === "work").length;
    $("wo-focus").textContent = `${d.focus.toUpperCase()} — ${d.blocks.length} ▦ · ${timed} ⏱ · ≈${estMin} MIN`;
  } else {
    $("wo-focus").textContent = `${d.focus.toUpperCase()} — ☾ REST / RECOVERY`;
  }
  if (!ticking && !session) renderClock(); // preview block 1's clock immediately
  // goal ladder: today ▸ this week ▸ phase ▸ program — the WHY, always one glance away
  const gl = $("goal-ladder");
  gl.hidden = false;
  $("gl-today").textContent = shortRx(d.summary, 110);
  $("gl-week").textContent = `week ${d.week} · ${d.focus.toLowerCase()}`;
  const phaseObj = phase === 1 ? guide.phase1 : guide.phase2;
  $("gl-phase").textContent = `${phaseObj.title}: ${shortRx(phaseObj.intro, 260)}`;
  $("gl-program").textContent = `${guide.title} — ${guide.tagline}`;
  applyDisclosure();
  $("wo-blocks").innerHTML = d.blocks
    .map((b, i) => `<li class="${checks[i] ? "checked" : ""}"><label><input type="checkbox" data-i="${i}" ${checks[i] ? "checked" : ""}><span><b>${b.name}</b> <span class="rx">— ${b.prescription}</span></span></label></li>`)
    .join("");
  $("wo-blocks").querySelectorAll("input").forEach((box) => {
    box.addEventListener("change", () => {
      try {
        const all = blockChecks();
        const arr = all[woDayKey(d)] || [];
        arr[Number(box.dataset.i)] = box.checked;
        all[woDayKey(d)] = arr;
        localStorage.setItem("shadowbox-blockchecks", JSON.stringify(all));
      } catch { /* storage unavailable */ }
      renderWorkout();
    });
  });
  const allChecked = d.blocks.length > 0 && d.blocks.every((_, i) => checks[i]);
  const isDone = prog.done.includes(woDayKey(d));
  const isRest = !d.rounds || !d.roundSec;
  $("wo-start").disabled = isRest;
  $("wo-start").textContent = isRest ? "☾ REST" : "▶ START DAY";
  $("wo-done").classList.toggle("completed", isDone);
  $("wo-done").classList.toggle("ready", allChecked && !isDone);
  $("wo-done").textContent = isDone ? "↩ UNDO ✓" : "✓ DONE";
  const p1done = guide.phase1.days.filter((x) => prog.done.includes(woDayKey(x))).length;
  $("wo-gate").textContent = phase === 1
    ? `Phase gate (${p1done}/${guide.phase1.days.length} days done): ${guide.gate_text}`
    : guide.coach_guidance;
  paintProgramGrid();
  renderGates();
}
$("wo-prev").addEventListener("click", () => { woIdx = Math.max(0, woIdx - 1); renderWorkout(); });
$("wo-next").addEventListener("click", () => { woIdx = Math.min(woDays.length - 1, woIdx + 1); renderWorkout(); });
$("wo-start").addEventListener("click", () => {
  const d = woDays[woIdx];
  if (!d || !d.rounds || !d.roundSec) return; // rest days: button is disabled
  if (stats.total > 0 && !dayStarted &&
      !confirm(`Start ${d.title}? This resets the ${stats.total}-punch session on the clock.`)) return;
  $("btn-reset").click();
  ROUND_SEC = d.roundSec; REST_SEC = d.restSec || 60; // free-mode fallback values
  workoutFocus = d.coach_focus;
  dayStarted = true;
  session = buildSessionPlan(d);
  const st = session.steps[0];
  resting = st.kind === "rest";
  roundNum = st.global || 1;
  roundLeft = st.sec || 0;
  roundStart = { ...stats };
  $("btn-start").click();
  renderSession();
  $("coach-text").textContent = `▶ ${d.title} — ${d.summary}`;
  $("stage-coach").textContent = "";
});
let woDoneArmed = false, lastDoneClick = 0;
$("wo-done").addEventListener("click", () => {
  const d = woDays[woIdx];
  if (!d) return;
  const nowMs = Date.now();
  if (nowMs - lastDoneClick < 800) return; // glove double-tap guard
  lastDoneClick = nowMs;
  const k = woDayKey(d);
  const prog0 = woProgress();
  if (prog0.done.includes(k)) {
    // undo: the ledger must be repairable
    prog0.done = prog0.done.filter((x) => x !== k);
    try { localStorage.setItem(WO_KEY, JSON.stringify(prog0)); } catch { /* storage unavailable */ }
    renderWorkout(); renderStreak();
    return;
  }
  // soft gate: DONE with zero evidence needs a second, deliberate tap
  const checks = blockChecks()[k] || [];
  const evidence = stats.total > 0 || d.blocks.some((_, i) => checks[i]) || !d.rounds;
  if (!evidence && !woDoneArmed) {
    woDoneArmed = true;
    $("wo-done").textContent = "SURE?";
    setTimeout(() => { woDoneArmed = false; renderWorkout(); }, 3000);
    return;
  }
  woDoneArmed = false;
  const snapshot = {
    type: "day_complete", dayKey: k, title: d.title, focus: d.focus,
    date: new Date().toISOString().slice(0, 10),
    stats: { ...stats, power: power(stats) },
    form: {
      avg_power: form.powerN ? Math.round(form.powerSum / form.powerN) : null,
      arm_punch_pct: form.powerPunches ? Math.round(100 * form.armPunches / form.powerPunches) : null,
      avg_retraction_ms: form.retractN ? Math.round(form.retractSum / form.retractN) : null,
      guard_height_sw: form.guardN ? Number((form.guardSum / form.guardN).toFixed(2)) : null,
    },
    rounds: roundHistory,
  };
  try {
    const prog = woProgress();
    if (!prog.done.includes(k)) prog.done.push(k);
    localStorage.setItem(WO_KEY, JSON.stringify(prog));
    const dl = dayLog();
    dl.push(snapshot);
    localStorage.setItem("shadowbox-daylog", JSON.stringify(dl.slice(-200)));
  } catch { /* storage unavailable */ }
  logEvent(snapshot); // → training_log.jsonl → MLflow ingest
  // no auto-advance: let the green land. Tomorrow is selected on next load.
  renderWorkout();
  renderStreak();
  $("coach-text").textContent = `✓ ${d.title} banked · ${$("streak-line").textContent}`;
});

// ---- visual-reasoning feedback: x key OR the on-stage ✗ WRONG? button ----
// annotations land in training_log.jsonl, the dataset the error-discovery
// skill reviews and clusters into failure modes
function flagLastCall(note) {
  if (!punchLog.length) return;
  const last = punchLog[punchLog.length - 1];
  logEvent({
    type: "call_feedback", verdict: "wrong",
    flagged: { hand: last.hand, type: last.type, speed: +last.speed.toFixed(1), power: last.power },
    actual: (note || "").trim() || "phantom — no punch thrown",
    recent: punchLog.slice(-5).map((p) => p.type),
    rotation_rate: +rotation.rate.toFixed(2),
    day: woDays[woIdx] ? woDayKey(woDays[woIdx]) : null,
    config: { extendAt: CFG.extendAt, minPeakSpeed: CFG.minPeakSpeed, peakDrop: CFG.peakDrop },
  });
  $("btn-flag").hidden = true;
  flash.textContent = "✗ FLAGGED";
  flash.classList.remove("pop");
  void flash.offsetWidth;
  flash.classList.add("pop");
}
document.addEventListener("keydown", (e) => {
  if (e.key !== "x" || !punchLog.length) return;
  const last = punchLog[punchLog.length - 1];
  const note = prompt(`Flag "${last.hand} ${last.type}" as wrong. What actually happened? (blank = phantom)`);
  if (note !== null) flagLastCall(note);
});
$("btn-flag").addEventListener("click", () => flagLastCall("")); // one glove-tap = phantom flag
let flagTimer = null;

const hands = { L: new HandTracker("L"), R: new HandTracker("R") };
const smoother = makeSmoother();
const rotation = new ShoulderRotation();
let fps = 0, lastFrameAt = 0, inferMs = 0;
// form telemetry for the corner coach: guard height, retraction, kinetic chain
const form = { powerSum: 0, powerN: 0, armPunches: 0, powerPunches: 0, retractSum: 0, retractN: 0, guardSum: 0, guardN: 0 };

// ---- session recorder (press r): raw landmarks + fired events → recordings/ ----
let recording = null;
function toggleRecording() {
  if (!recording) {
    recording = { startedAt: new Date().toISOString(), frames: [], events: [] };
    $("rec-dot").hidden = false;
    return;
  }
  const rec = recording;
  recording = null;
  $("rec-dot").hidden = true;
  rec.label = prompt("What did you actually throw? (e.g. 'jab x10')") || "unlabeled";
  fetch("/save", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(rec) })
    .then((r) => r.json())
    .then((j) => alert(`saved ${j.file} — ${rec.frames.length} frames, ${rec.events.length} punches called`))
    .catch(() => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([JSON.stringify(rec)], { type: "application/json" }));
      a.download = `shadowbox-${Date.now()}.json`;
      a.click();
    });
}

// setup assistant + tracking-loss watchdog
let lastPoseAt = 0, framedFrames = 0, framedOnce = false, cameraLive = false, lossShown = false;
const FRAME_HINT = "⌖ 2–3 m back · shoulders + hips in frame";

function onFrame(landmarks, now) {
  lastPoseAt = now;
  if (lossShown) { stageMsg.hidden = true; lossShown = false; }
  if (cameraLive && !framedOnce) {
    const hipVis = Math.min(landmarks[L.L_HIP]?.visibility ?? 1, landmarks[L.R_HIP]?.visibility ?? 1);
    const ls0 = landmarks[L.L_SHOULDER], rs0 = landmarks[L.R_SHOULDER];
    const swRaw = Math.hypot(ls0.x - rs0.x, ls0.y - rs0.y);
    const good = hipVis > 0.5 && swRaw > 0.08 && swRaw < 0.45;
    framedFrames = good ? framedFrames + 1 : 0;
    if (framedFrames >= 30) {
      framedOnce = true;
      stageMsg.classList.add("ok");
      stageMsg.textContent = "✓ in frame — hit ▶";
      setTimeout(() => { stageMsg.hidden = true; stageMsg.classList.remove("ok"); }, 1800);
    } else if (!good) {
      stageMsg.hidden = false;
      stageMsg.textContent = hipVis <= 0.5 ? "⌖ step back / tilt camera ↓ — hips out of frame"
        : swRaw >= 0.45 ? "⌖ too close — step back" : FRAME_HINT;
    }
  }
  if (recording) {
    const snap = {};
    for (const i of Object.values(L)) {
      const p = landmarks[i];
      snap[i] = { x: +p.x.toFixed(4), y: +p.y.toFixed(4), z: +p.z.toFixed(4) };
    }
    recording.frames.push({ t: +now.toFixed(1), lm: snap });
  }
  if (lastFrameAt) fps += ((1000 / (now - lastFrameAt)) - fps) * 0.1;
  lastFrameAt = now;
  const lm = smoother.update(landmarks, now);
  const ls = lm.get(L.L_SHOULDER), rs = lm.get(L.R_SHOULDER);
  const sw = Math.hypot(ls.x - rs.x, ls.y - rs.y);
  if (sw < 0.02) return; // not actually facing the camera
  const ctx2 = { sw, hipY: (lm.get(L.L_HIP).y + lm.get(L.R_HIP).y) / 2 };
  rotation.update(ls, rs, now);

  const mode = scoringMode(); // the block's tracking contract governs the camera
  for (const [hand, wi, ei, si] of [["L", L.L_WRIST, L.L_ELBOW, L.L_SHOULDER], ["R", L.R_WRIST, L.R_ELBOW, L.R_SHOULDER]]) {
    const tracker = hands[hand];
    const ev = tracker.update(lm.get(wi), lm.get(ei), lm.get(si), ctx2, now);
    if (ev && mode === "punch") {
      ev.power = punchPower(ev.speed, rotation.rate);
      recordPunch(ev, now);
    } else if (ev && mode === "rest") {
      // punches during rest are seen, said, and not counted
      $("stage-rest").textContent = "REST ✗";
      setTimeout(() => { $("stage-rest").textContent = "REST"; }, 600);
    } // defense/movement: form only · conditioning: a push-up is not a punch
    if (tracker.phase === "guard" && mode !== "conditioning" && mode !== "rest") {
      if (tracker.lastRetractMs != null && tracker.lastRetractMs < 2000) {
        form.retractSum += tracker.lastRetractMs; form.retractN++;
        recentRetracts.push(tracker.lastRetractMs);
        if (recentRetracts.length > 6) recentRetracts.shift();
        tracker.lastRetractMs = null;
      }
      // guard height: how far the wrist sits above the shoulder line, in sw
      const gh = (lm.get(si).y - lm.get(wi).y) / sw;
      form.guardSum += gh; form.guardN++;
      guardNow += 0.1 * (gh - guardNow);
    } else if (tracker.lastRetractMs != null) tracker.lastRetractMs = null;
  }
  draw(lm);
  for (const [hand, id] of [["L", "meter-l"], ["R", "meter-r"]]) {
    const el = $(id);
    el.style.width = `${Math.min(100, (hands[hand].reach / 1.6) * 100)}%`;
    el.classList.toggle("armed", hands[hand].reach > CFG.extendAt);
  }
  if (!debugPanel.hidden) {
    debugPanel.textContent =
      `L reach ${hands.L.reach.toFixed(2)}  speed ${hands.L.speed.toFixed(1)}  elbow ${hands.L.elbowAngle.toFixed(0)}°  phase ${hands.L.phase}\n` +
      `R reach ${hands.R.reach.toFixed(2)}  speed ${hands.R.speed.toFixed(1)}  elbow ${hands.R.elbowAngle.toFixed(0)}°  phase ${hands.R.phase}\n` +
      `shoulder-width ${sw.toFixed(3)}  ${fps.toFixed(0)} fps  pose ${inferMs.toFixed(1)}ms (${POSE_MODEL})  rot ${rotation.rate.toFixed(1)}r/s  ${CFG.smoother}  ${SYNTHETIC ? "SYNTHETIC FEED" : "live camera"}  ${recording ? "REC " + recording.frames.length : ""}`;
  }
}

// ---- punch sound: a synthesized thump, no audio assets ----
let audio = null;
function initAudio() {
  if (!audio) audio = new (window.AudioContext || window.webkitAudioContext)();
}
document.addEventListener("pointerdown", initAudio, { once: true });
document.addEventListener("keydown", initAudio, { once: true });
function thump(speed) {
  if (!audio || audio.state !== "running") return;
  const t = audio.currentTime;
  const gain = audio.createGain();
  gain.gain.setValueAtTime(Math.min(0.5, 0.15 + speed * 0.04), t);
  gain.gain.exponentialRampToValueAtTime(0.001, t + 0.15);
  gain.connect(audio.destination);
  const osc = audio.createOscillator();
  osc.frequency.setValueAtTime(160, t);
  osc.frequency.exponentialRampToValueAtTime(50, t + 0.12);
  osc.connect(gain);
  osc.start(t);
  osc.stop(t + 0.15);
}

// ---- real-time coach, tier 0+1: spoken cues while you work --------------
// tier 0 = reflexes: rule-based cues from live telemetry, 0 ms, no model
// tier 1 = cadence: one 8-word Bonsai cue mid-round via /coach (sub-second
//          with a 2B loaded; silently skipped if the model is slow/absent)
// tier 2 = the existing between-rounds analysis
let voiceOn = (() => { try { return localStorage.getItem("shadowbox-voice") !== "off"; } catch { return true; } })();
function speak(text) {
  if (!voiceOn || !("speechSynthesis" in window)) return;
  try {
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(String(text).replace(/[📼🗣▸✗▦⏱☾🔥●○·]/g, " "));
    u.rate = 1.08;
    speechSynthesis.speak(u);
  } catch { /* no voice — visuals still carry the cue */ }
}
$("btn-voice").textContent = voiceOn ? "🔊" : "🔇";
$("btn-voice").addEventListener("click", () => {
  voiceOn = !voiceOn;
  if (!voiceOn) try { speechSynthesis.cancel(); } catch { /* fine */ }
  $("btn-voice").textContent = voiceOn ? "🔊" : "🔇";
  try { localStorage.setItem("shadowbox-voice", voiceOn ? "on" : "off"); } catch { /* fine */ }
});

const recentCalls = [];    // last 12 punches: {t, type, arm}
const recentRetracts = []; // last 6 retraction times, ms
let guardNow = 0.3;        // EMA of live guard height, sw
let stageCoachTimer = null;
const reflexCool = {};
function sayCue(text) {
  speak(text);
  $("coach-text").textContent = text;
  const scEl = $("stage-coach");
  scEl.textContent = text;
  clearTimeout(stageCoachTimer);
  stageCoachTimer = setTimeout(() => { if (!resting) scEl.textContent = ""; }, 3500);
}
function coachReflexes(now) {
  const fire = (key, text) => {
    if (now - (reflexCool[key] || 0) < 25000) return false;
    reflexCool[key] = now;
    sayCue(text);
    return true;
  };
  const power5 = recentCalls.slice(-5).filter((c) => c.type !== "JAB");
  if (power5.length >= 3 && power5.filter((c) => c.arm).length / power5.length >= 0.7 &&
      fire("arm", "Turn the hip — punch from the ground!")) return;
  if (guardNow < 0.05 && fire("guard", "Hands up!")) return;
  if (recentRetracts.length >= 4 &&
      recentRetracts.reduce((a, b) => a + b, 0) / recentRetracts.length > 550 &&
      fire("retract", "Snap it back!")) return;
  const st = session?.steps[session.idx];
  if (st?.kind === "work" && roundHistory.length) {
    const elapsed = st.sec - roundLeft;
    const thrown = stats.total - roundStart.total;
    const best = Math.max(...roundHistory.map((r) => r.thrown));
    if (elapsed > 40 && best >= 20 && thrown < 0.5 * best * (elapsed / st.sec)) {
      fire("pace", "Pick up the pace!");
    }
  }
}
async function liveCue(st) {
  try {
    const models = await fetch(`${COACH_API}/models`, { signal: AbortSignal.timeout(1500) }).then((r) => r.json());
    const model = models.data?.[0]?.id;
    if (!model) return;
    const res = await fetch(`${COACH_API}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: AbortSignal.timeout(4000), // a slow cue is a dead cue
      body: JSON.stringify({
        model, max_tokens: 24, temperature: 0.7,
        messages: [
          { role: "system", content: "Mid-round boxing corner coach. Shout ONE imperative cue, max 8 words. No preamble." + dayBrief() },
          { role: "user", content: JSON.stringify({
            current_block: `${st.name} (${st.rx})`,
            seconds_left: roundLeft,
            thrown_this_round: stats.total - roundStart.total,
            recent_arm_punch: recentCalls.slice(-5).filter((c) => c.arm).length,
            guard_height_sw: +guardNow.toFixed(2),
            focus: workoutFocus,
          }) },
        ],
      }),
    }).then((r) => r.json());
    const text = res.choices?.[0]?.message?.content?.trim();
    if (text && ticking && !resting) sayCue(text);
  } catch { /* reflexes still cover the round */ }
}

// ---- combo caller: name the trailing sequence when it lands inside 2s ----
const COMBOS = [
  [["JAB", "CROSS", "HOOK"], "1-2-3!"],
  [["JAB", "CROSS", "UPPERCUT"], "1-2-6!"],
  [["JAB", "CROSS"], "1-2!"],
  [["JAB", "JAB"], "DOUBLE JAB"],
  [["HOOK", "HOOK"], "HOOK HOOK!"],
];
function comboName(now) {
  const recent = punchLog.filter((p) => now - p.t < 2000).map((p) => p.type);
  for (const [seq, name] of COMBOS) {
    if (recent.length >= seq.length &&
        seq.every((t, i) => recent[recent.length - seq.length + i] === t)) return name;
  }
  return null;
}

function recordPunch(ev, now) {
  stats.total++;
  stats[ev.type]++;
  stats.peakSpeed = Math.max(stats.peakSpeed, ev.speed);
  punchLog.push({ t: now, ...ev });
  if (recording) recording.events.push({ t: +now.toFixed(1), ...ev });
  form.powerSum += ev.power; form.powerN++;
  if (ev.type !== "JAB") {
    form.powerPunches++;
    if (Math.abs(rotation.rate) < 1.0) form.armPunches++; // power punch thrown without turning the body
  }
  recentCalls.push({ t: now, type: ev.type, arm: ev.type !== "JAB" && Math.abs(rotation.rate) < 1.0 });
  if (recentCalls.length > 12) recentCalls.shift();
  $("stat-total").textContent = stats.total;
  $("stat-jab").textContent = stats.JAB;
  $("stat-cross").textContent = stats.CROSS;
  $("stat-hook").textContent = stats.HOOK;
  $("stat-uppercut").textContent = stats.UPPERCUT;
  $("stat-power").textContent = power(stats);
  $("stat-speed").innerHTML = `${stats.peakSpeed.toFixed(1)}<small>sw/s</small>`;
  const label = ev.type === "JAB" || ev.type === "CROSS" ? ev.type : `${ev.hand} ${ev.type}`;
  flash.textContent = `${label} ${ev.power}`;
  flash.classList.remove("pop");
  void flash.offsetWidth; // restart the animation
  flash.classList.add("pop");
  thump(ev.speed);
  // touch parity for the feedback loop: ✗ WRONG? shows for 4s after each call
  $("btn-flag").hidden = false;
  clearTimeout(flagTimer);
  flagTimer = setTimeout(() => { $("btn-flag").hidden = true; }, 4000);
  const combo = comboName(now);
  if (combo) {
    const cf = $("combo-flash");
    cf.textContent = combo;
    cf.classList.remove("pop");
    void cf.offsetWidth;
    cf.classList.add("pop");
  }
}

setInterval(() => {
  const now = performance.now();
  const recent = punchLog.filter((p) => now - p.t < 60000).length;
  $("stat-ppm").textContent = recent;
  if (guide) renderGates(); // live gate readout in the left rail
  if (ticking && !resting && scoringMode() === "punch" && stats.total - roundStart.total >= 4) coachReflexes(performance.now());
  // tracking loss: if the pose stream goes quiet, say so instead of freezing
  if (cameraLive && framedOnce && performance.now() - lastPoseAt > 1500 && stageMsg.hidden) {
    ctx.clearRect(0, 0, overlay.width, overlay.height);
    $("meter-l").style.width = "0%";
    $("meter-r").style.width = "0%";
    stageMsg.hidden = false;
    stageMsg.textContent = "⌖ can't see you — " + FRAME_HINT.slice(2);
    lossShown = true;
  }
}, 1000);

// ---- skeleton overlay ----
function draw(lm) {
  const w = overlay.width, h = overlay.height;
  ctx.clearRect(0, 0, w, h);
  ctx.lineWidth = 3;
  ctx.strokeStyle = "rgba(255,59,59,.9)";
  for (const [a, b] of BONES) {
    const pa = lm.get(a), pb = lm.get(b);
    ctx.beginPath();
    ctx.moveTo(pa.x * w, pa.y * h);
    ctx.lineTo(pb.x * w, pb.y * h);
    ctx.stroke();
  }
  for (const i of Object.values(L)) {
    const p = lm.get(i);
    const isWrist = i === L.L_WRIST || i === L.R_WRIST;
    ctx.fillStyle = isWrist ? "#ffc24b" : "#ff3b3b";
    ctx.beginPath();
    ctx.arc(p.x * w, p.y * h, isWrist ? 8 : 5, 0, Math.PI * 2);
    ctx.fill();
  }
}

// ---- round timer: deadline-driven (throttled tabs can't drift the clock),
// with a finish line — the day ENDS after its prescribed rounds ----
function fmt(s) { return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }
let dayStarted = false, deadline = 0, wakeLock = null;
let session = null;     // the block-driven session player: {steps, idx, nBlocks, day}
let previewPlan = null; // the selected day's compiled plan, shown before ▶ (display-only)
const shortRx = (s, n = 64) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

// tracking contract per block: what should the camera score right now?
//   punch 🥊 full scoring · defense 🛡 / movement 🦶 form only · conditioning 💪 paused
// modes are baked into workout_guide.json by pipeline/annotate_guide.py;
// this JS mirror covers guides built before that pass
const MODE_GLYPH = { punch: "🥊", defense: "🛡", movement: "🦶", conditioning: "💪" };
const MODE_RULES = [
  ["punch", /bag|shadow ?box|freestyle|sparring|pad work|punch|jab|cross\b|hook|uppercut|combo|combination|fight|tennis ball|counter|supplemental|timed round|opening round|partner work|interval/i],
  ["defense", /slip|roll|head movement|duck|parry|defen/i],
  ["movement", /stance|movement|footwork|agility|shuffle|pendulum|pivot|shift|step drill|balance/i],
  ["conditioning", /push-?up|squat|climber|burpee|plank|jump|crunch|sit-?up|pull-?up|med ?ball|dumbbell|barbell|lift|sets? of|reps|circuit|endurance|mobility|stretch|rope|sprawl|raises|jacks|tucks|sprint|conditioning|weighted stick|hip bridge|wall sit|juggling/i],
];
function blockMode(b) {
  if (b.mode) return b.mode;
  const t = `${b.name} ${b.prescription} ${b.source_drill || ""}`;
  for (const [m, re] of MODE_RULES) if (re.test(t)) return m;
  return "punch";
}
// what the camera should score during the current step
function scoringMode() {
  if (!session || !ticking) return "punch"; // free sessions: full scoring
  const st = session.steps[session.idx];
  if (st.kind === "rest") return "rest";
  return st.mode || "punch";
}

// Parse a block's prescription into a timed scheme. Handles the curriculum's
// real shapes ("4 ROUNDS OF 2 MINUTES WITH 30 SECONDS OF REST", "9 rounds x
// 1 min", "1ROUND OF 3MINUTES") — anything rep-based becomes self-paced.
function parseScheme(text) {
  const t = text.toLowerCase().replace(/[,;]/g, " ");
  const round = t.match(/(\d+)\s*rounds?\s*(?:of|x|×)?\s*(\d+(?:\.\d+)?)\s*(min|sec|s\b|m\b)/);
  const rest = t.match(/(\d+)\s*(min|sec|s)\w*\s*(?:of\s*)?rest/) || t.match(/rest[^0-9]{0,12}(\d+)\s*(min|sec|s)/);
  if (round) {
    const workSec = Math.round(parseFloat(round[2]) * (round[3].startsWith("m") ? 60 : 1));
    let restSec = workSec >= 150 ? 60 : 30;
    if (rest) restSec = Math.round(parseFloat(rest[1]) * (rest[2].startsWith("m") ? 60 : 1));
    return { kind: "rounds", rounds: +round[1], workSec, restSec };
  }
  return { kind: "reps" }; // self-paced: NEXT advances when the reps are done
}

function buildSessionPlan(d) {
  const steps = [];
  let global = 0;
  d.blocks.forEach((b, bi) => {
    const s = parseScheme(`${b.prescription} ${b.source_drill || ""}`);
    const mode = blockMode(b);
    if (s.kind === "rounds") {
      for (let r = 1; r <= s.rounds; r++) {
        global++;
        steps.push({ kind: "work", sec: s.workSec, blockIdx: bi, name: b.name, rx: b.prescription, round: r, of: s.rounds, global, mode });
        if (r < s.rounds) steps.push({ kind: "rest", sec: s.restSec, blockIdx: bi, name: b.name, rx: `breathe — ${s.restSec}s` });
      }
      if (bi < d.blocks.length - 1) {
        steps.push({ kind: "rest", sec: 45, blockIdx: bi, name: "switch", rx: "set up the next block" });
      }
    } else {
      global++;
      steps.push({ kind: "selfpaced", sec: 0, blockIdx: bi, name: b.name, rx: b.prescription, global, mode });
    }
  });
  return { steps, idx: 0, nBlocks: d.blocks.length, day: d };
}

function checkBlockDone(bi) {
  try {
    const d = session?.day || woDays[woIdx];
    if (!d) return;
    const all = blockChecks();
    const arr = all[woDayKey(d)] || [];
    arr[bi] = true;
    all[woDayKey(d)] = arr;
    localStorage.setItem("shadowbox-blockchecks", JSON.stringify(all));
  } catch { /* storage unavailable */ }
}

function renderSession() {
  const card = $("wo-now");
  if (!session) {
    card.hidden = true;
    $("wo-all").open = true;
    $("stage-block").hidden = true;
    $("btn-next").hidden = true;
    return;
  }
  const st = session.steps[session.idx];
  card.hidden = false;
  $("wo-all").open = false; // progressive disclosure: the full list folds away mid-session
  $("wo-now-tag").textContent = `NOW · BLOCK ${st.blockIdx + 1}/${session.nBlocks}` + (st.round ? ` · ROUND ${st.round}/${st.of}` : "");
  $("wo-now-name").textContent = st.kind === "rest" ? "REST" : `${MODE_GLYPH[st.mode] || ""} ${st.name}`;
  $("wo-now-rx").textContent = st.rx;
  $("wo-progress").innerHTML = session.day.blocks
    .map((_, i) => `<span class="${i < st.blockIdx ? "done" : i === st.blockIdx ? "current" : ""}"></span>`)
    .join("");
  const nxt = session.steps.slice(session.idx + 1).find((s) => s.kind !== "rest");
  $("wo-next-line").textContent = nxt ? `next ▸ ${nxt.name}` : "🏁 last block — finish strong";
}

function advanceStep() {
  if (!session) return;
  const st = session.steps[session.idx];
  if (st.kind === "work") { bell(2); closeRound(); }
  else if (st.kind === "selfpaced") bell(1);
  // leaving a block? bank its check-off
  const nx0 = session.steps[session.idx + 1];
  if (st.kind !== "rest" && (!nx0 || nx0.blockIdx !== st.blockIdx)) {
    checkBlockDone(st.blockIdx);
    renderWorkout();
  }
  session.idx++;
  if (session.idx >= session.steps.length) {
    session.day.blocks.forEach((_, i) => checkBlockDone(i));
    session = null;
    renderSession();
    renderWorkout();
    dayComplete();
    return;
  }
  const nx = session.steps[session.idx];
  resting = nx.kind === "rest";
  if (nx.kind !== "rest") { roundNum = nx.global; roundStart = { ...stats }; $("stage-coach").textContent = ""; }
  roundLeft = nx.sec || 0;
  deadline = Date.now() + roundLeft * 1000;
  if (resting && nx.sec >= 45) askCoach();
  renderSession();
  renderClock();
}

$("btn-next").addEventListener("click", () => {
  if (!session || !ticking) return;
  advanceStep(); // finish a self-paced block, or skip the rest early
});

function bell(times = 1) {
  if (!audio || audio.state !== "running") return;
  for (let i = 0; i < times; i++) {
    const t = audio.currentTime + i * 0.35;
    const gain = audio.createGain();
    gain.gain.setValueAtTime(0.3, t);
    gain.gain.exponentialRampToValueAtTime(0.001, t + 0.3);
    gain.connect(audio.destination);
    const osc = audio.createOscillator();
    osc.frequency.setValueAtTime(880, t);
    osc.connect(gain);
    osc.start(t);
    osc.stop(t + 0.3);
  }
}

function renderClock() {
  const live = session?.steps[session.idx];
  // idle with a day selected → PREVIEW block 1's real scheme, not a stale 3:00
  const prev = (!ticking && !session && previewPlan) ? previewPlan.steps[0] : null;
  const st = live || prev;
  const selfPaced = st?.kind === "selfpaced";
  const shown = live ? Math.max(0, roundLeft) : (prev ? prev.sec : Math.max(0, roundLeft));
  $("round-clock").textContent = selfPaced ? "▸▸" : fmt(shown);
  $("round-clock").classList.toggle("rest", resting);
  $("round-label").textContent = st
    ? (st.kind === "rest" ? "REST" : `B${st.blockIdx + 1}${st.round ? ` R${st.round}/${st.of}` : ""}`)
    : (resting ? "REST" : `R${roundNum}`);
  const sc = $("stage-clock");
  sc.hidden = !ticking;
  sc.textContent = selfPaced ? "▸▸" : fmt(shown);
  sc.classList.toggle("warn", !!live && !resting && !selfPaced && roundLeft <= 10 && roundLeft > 0);
  document.body.classList.toggle("resting", resting && !!ticking);
  $("stage-rest").hidden = !(resting && ticking);
  // on-stage assist: what move am I on (or about to start), and what does it ask
  const sb = $("stage-block");
  if (live && ticking) {
    sb.hidden = false;
    const tag = live.mode === "conditioning" ? " · scoring ⏸" : (live.mode === "movement" || live.mode === "defense") ? " · form only" : "";
    sb.textContent = live.kind === "rest"
      ? `next ▸ ${session.steps.slice(session.idx + 1).find((s) => s.kind !== "rest")?.name ?? "finish"}`
      : `${MODE_GLYPH[live.mode] || ""} ${live.name}${live.round ? ` · R${live.round}/${live.of}` : ""}${tag} — ${shortRx(live.rx)}`;
  } else if (prev) {
    sb.hidden = false;
    sb.textContent = `up first ▸ ${MODE_GLYPH[prev.mode] || ""} ${prev.name} — ${shortRx(prev.rx)}`;
  } else sb.hidden = true;
  document.body.classList.toggle("scoring-paused", !!live && ticking && live.mode === "conditioning");
  const bn = $("btn-next");
  bn.hidden = !(live && ticking && (selfPaced || live.kind === "rest"));
  bn.textContent = selfPaced ? "DONE ▸ NEXT" : "SKIP REST ▸";
}

async function grabWakeLock() {
  try { wakeLock = await navigator.wakeLock?.request("screen"); } catch { /* not fatal */ }
}
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && ticking) grabWakeLock();
});

function stopTimer(label = "▶") {
  clearInterval(ticking); ticking = null;
  $("btn-start").textContent = label;
  try { wakeLock?.release(); } catch { /* already gone */ }
  renderClock();
}

function dayComplete() {
  stopTimer();
  bell(2);
  const cf = $("combo-flash");
  cf.textContent = "DAY ✓";
  cf.classList.remove("pop"); void cf.offsetWidth; cf.classList.add("pop");
  $("stage-coach").textContent = "DAY COMPLETE — hit ✓ DONE";
  $("wo-done").classList.add("ready");
  askCoach();
}

$("btn-start").addEventListener("click", () => {
  // with a program loaded, the header ▶ starts TODAY (one ritual, one button)
  if (!ticking && guide && !dayStarted && woDays[woIdx] &&
      !woProgress().done.includes(woDayKey(woDays[woIdx])) && woDays[woIdx].rounds) {
    $("wo-start").click();
    return;
  }
  if (ticking) { stopTimer(); return; }
  $("btn-start").textContent = "⏸";
  deadline = Date.now() + roundLeft * 1000;
  grabWakeLock();
  ticking = setInterval(() => {
    if (session) {
      const st = session.steps[session.idx];
      if (st.kind === "selfpaced") return; // clock idles; NEXT advances
      const left = Math.ceil((deadline - Date.now()) / 1000);
      if (left === roundLeft) return;
      roundLeft = left;
      if (st.kind === "work" && roundLeft === 10) bell(1);
      // tier-1 cadence: one Bonsai cue at the midpoint of long PUNCH rounds
      // (a hip cue mid-push-ups would be nonsense — contract-gated)
      if (st.kind === "work" && st.mode === "punch" && st.sec >= 90 && !st.cueFired && roundLeft <= st.sec / 2) {
        st.cueFired = true;
        liveCue(st);
      }
      if (roundLeft <= 0) { advanceStep(); return; }
      renderClock();
      return;
    }
    // free session (no program day started): classic 3:00 / 1:00 loop
    const left = Math.ceil((deadline - Date.now()) / 1000);
    if (left === roundLeft) return;
    roundLeft = left;
    if (!resting && roundLeft === 10) bell(1);
    if (roundLeft <= 0) {
      if (resting) {
        resting = false; roundNum++; roundLeft = ROUND_SEC;
        roundStart = { ...stats };
        $("stage-coach").textContent = "";
        bell(1);
      } else {
        bell(2);
        closeRound();
        resting = true; roundLeft = REST_SEC;
        askCoach();
      }
      deadline = Date.now() + roundLeft * 1000;
    }
    renderClock();
  }, 250);
  renderClock();
});
$("btn-reset").addEventListener("click", () => {
  stopTimer();
  roundNum = 1; roundLeft = ROUND_SEC; resting = false;
  dayStarted = false; session = null;
  renderSession();
  Object.assign(stats, { total: 0, JAB: 0, CROSS: 0, HOOK: 0, UPPERCUT: 0, peakSpeed: 0 });
  punchLog.length = 0;
  roundHistory.length = 0;
  roundStart = { ...stats };
  $("rounds-panel").hidden = true;
  $("stage-coach").textContent = "";
  for (const id of ["stat-total", "stat-jab", "stat-cross", "stat-hook", "stat-uppercut", "stat-power", "stat-ppm"]) $(id).textContent = "0";
  $("stat-speed").innerHTML = `0<small>sw/s</small>`;
  renderClock();
});
renderClock();

$("btn-stance").addEventListener("click", () => {
  CFG.leadHand = CFG.leadHand === "L" ? "R" : "L";
  $("btn-stance").textContent = CFG.leadHand === "L" ? "ORTHODOX" : "SOUTHPAW";
});

document.addEventListener("keydown", (e) => {
  if (e.key === "d") debugPanel.hidden = !debugPanel.hidden;
  if (e.key === "r") toggleRecording();
});

// =========================================================================
// Corner coach — Bonsai on LM Studio (OpenAI-compatible, localhost:1234).
// Falls back to canned corner talk when no local model is reachable.
// =========================================================================
// The coach talks to LM Studio through OUR server's /coach proxy — same-origin
// (no CORS setup) and it works from a phone, where localhost isn't the Mac.
const COACH_API = "/coach";

// Curriculum grounding: coach_kb.json is distilled from boxing.dharmicdata.org
// by pipeline/flow.py. The coach picks the focus theme matching the round's
// weakest form stat and grounds its cue in real curriculum lines.
let coachKB = null;
fetch("coach_kb.json").then((r) => r.ok ? r.json() : null).then((kb) => { coachKB = kb; }).catch(() => {});

let workoutFocus = null; // set by START DAY: today's curriculum focus overrides the heuristic
// the coach is THE program's coach: every call carries where the athlete is
// in the 70-day arc and what today's blocks actually are
function dayBrief() {
  if (!guide) return "";
  const d = woDays[woIdx];
  if (!d) return "";
  const phase = d.program === guide.phase1.program ? 1 : 2;
  const pos = woDays.indexOf(d) + 1;
  return ` PROGRAM: '${guide.title}', day ${pos}/70 (phase ${phase}, week ${d.week}, day ${d.day}). ` +
    `TODAY: ${d.title}, focus ${d.focus} — ${shortRx(d.summary, 150)} ` +
    `BLOCKS: ${d.blocks.map((b) => `${b.name}[${blockMode(b)}]`).join(", ").slice(0, 280)}.`;
}

function pickFocusTheme() {
  if (!coachKB) return null;
  if (workoutFocus && coachKB.focuses[workoutFocus]) {
    return { name: workoutFocus, ...coachKB.focuses[workoutFocus] };
  }
  const names = Object.keys(coachKB.focuses);
  const find = (frag) => names.find((n) => n.toLowerCase().includes(frag));
  const armPct = form.powerPunches ? form.armPunches / form.powerPunches : 0;
  const guardH = form.guardN ? form.guardSum / form.guardN : 1;
  const retract = form.retractN ? form.retractSum / form.retractN : 0;
  let name = null;
  if (armPct > 0.4) name = find("pivot") || find("combination");
  else if (guardH < 0.1) name = find("defense");
  else if (retract > 700) name = find("stance") || find("movement");
  if (!name) name = names[(roundNum - 1) % names.length];
  return name ? { name, ...coachKB.focuses[name] } : null;
}
const CANNED = [
  "Snap the jab back to your chin — same speed out and in.",
  "You're arm-punching the cross. Turn the rear hip through it.",
  "Double up the jab before the cross. Make the first one honest.",
  "Breathe out on every punch. Quiet exhale, sharp hands.",
  "Bend the knees on the uppercut — lift from the legs, not the elbow.",
];
let cannedIdx = 0;

function roundSummary() {
  const last = punchLog.slice(-80);
  return {
    round: roundNum,
    total: stats.total,
    jabs: stats.JAB, power_punches: power(stats),
    crosses: stats.CROSS, hooks: stats.HOOK, uppercuts: stats.UPPERCUT,
    punches_per_min: Number($("stat-ppm").textContent),
    fastest_hand_sw_per_s: Number(stats.peakSpeed.toFixed(1)),
    // form telemetry — pre-digested stats only, never raw traces, so the
    // small judge model can't drift off into re-scoring punches itself
    avg_power_score_0_to_99: form.powerN ? Math.round(form.powerSum / form.powerN) : null,
    arm_punch_pct: form.powerPunches ? Math.round(100 * form.armPunches / form.powerPunches) : null,
    avg_retraction_ms: form.retractN ? Math.round(form.retractSum / form.retractN) : null,
    guard_height_above_shoulders_sw: form.guardN ? Number((form.guardSum / form.guardN).toFixed(2)) : null,
    rounds: roundHistory,
    last_sequence: last.map((p) => p.type).join(" "),
  };
}

let coachReq = 0; // stale responses must never clobber newer ones
async function askCoach() {
  const id = ++coachReq;
  const el = $("coach-text"), src = $("coach-source"), btn = $("btn-coach");
  btn.disabled = true;
  btn.textContent = "🗣 …";
  el.textContent = "…coach is thinking";
  try {
    const models = await fetch(`${COACH_API}/models`, { signal: AbortSignal.timeout(3000) }).then((r) => r.json());
    const model = models.data?.[0]?.id;
    if (!model) throw new Error("no model loaded");
    const res = await fetch(`${COACH_API}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: AbortSignal.timeout(12000), // later than 12 s and the rest is over anyway
      body: JSON.stringify({
        model,
        max_tokens: 120,
        temperature: 0.7,
        messages: [
          {
            role: "system",
            content: "You are the dedicated corner coach of this 70-day program, between rounds. Given round stats, give ONE specific, punchy coaching cue in under 40 words, tied to today's focus. Prioritize form problems: high arm_punch_pct means they aren't turning the body; slow avg_retraction_ms means hands hang out; low guard_height means the chin is open. No preamble, no lists." + dayBrief() +
              (() => {
                const theme = pickFocusTheme();
                if (!theme) return "";
                return ` Ground your cue in this curriculum focus ("${theme.name}"): cues: ${theme.cues.slice(0, 3).join(" | ")}. drills: ${theme.drills.slice(0, 2).join(" | ")}.`;
              })(),
          },
          { role: "user", content: JSON.stringify(roundSummary()) },
        ],
      }),
    }).then((r) => r.json());
    const text = res.choices?.[0]?.message?.content?.trim();
    if (!text) throw new Error("empty response");
    if (id !== coachReq) return; // superseded
    el.textContent = text;
    speak(text); // the athlete is 3 m away — the coach talks
    if (resting) $("stage-coach").textContent = text; // cue lands where the athlete is
    src.textContent = `live · ${model}`;
    src.classList.add("live");
  } catch {
    if (id !== coachReq) return;
    el.textContent = "📼 " + CANNED[cannedIdx++ % CANNED.length];
    if (resting) $("stage-coach").textContent = "📼 " + CANNED[(cannedIdx - 1) % CANNED.length];
    src.textContent = "canned (load a model in LM Studio)";
    src.classList.remove("live");
  } finally {
    if (id === coachReq) { btn.disabled = false; btn.textContent = "🗣 COACH"; }
  }
}
$("btn-coach").addEventListener("click", askCoach);

// =========================================================================
// Feeds: real webcam + MediaPipe, or the synthetic sparring partner
// (?synthetic=1) from punch.js — same detection pipeline, no camera needed.
// =========================================================================
function sizeOverlay() {
  overlay.width = video.videoWidth || 960;
  overlay.height = video.videoHeight || 720;
}

// A/B the pose model with ?model=lite|full|heavy (record clips under each
// and judge them with replay.mjs — same reward function, different model)
const MODEL_PATH =
  `https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_${POSE_MODEL}/float16/1/pose_landmarker_${POSE_MODEL}.task`;

async function openCamera() {
  stageMsg.textContent = "📷 punches are tracked on-device — video never leaves this machine. Allow the camera.";
  const stream = await navigator.mediaDevices.getUserMedia({
    // 60 fps halves the sampling interval: tighter peaks, ~16 ms less latency
    video: { width: 960, height: 720, facingMode: "user", frameRate: { ideal: 60 } },
  });
  video.srcObject = stream;
  await video.play();
  sizeOverlay();
  cameraLive = true;
  stageMsg.textContent = FRAME_HINT; // setup assistant takes it from here
}
const CAMERA_ERRORS = /NotAllowed|NotFound|NotReadable|Permission|Security/i;

// Preferred path: inference in a Web Worker so main-thread HUD work can
// never delay a detection frame. Falls back to inline inference below.
function startLiveWorker() {
  return new Promise((resolve, reject) => {
    let worker;
    try { worker = new Worker("pose-worker.js", { type: "module" }); }
    catch (err) { reject(err); return; }
    let busy = false; // at most one frame in flight — stale frames are skipped, not queued
    const bail = (why) => { worker.terminate(); reject(new Error(why)); };
    const timer = setTimeout(() => bail("pose worker init timed out"), 20000);

    worker.onerror = (e) => { clearTimeout(timer); bail(e.message || "pose worker failed"); };
    worker.onmessage = async (e) => {
      const msg = e.data;
      if (msg.type === "init-error") { clearTimeout(timer); bail(msg.message); return; }
      if (msg.type === "landmarks") {
        busy = false;
        inferMs += (msg.inferMs - inferMs) * 0.1;
        if (msg.landmarks) onFrame(msg.landmarks, msg.t);
        return;
      }
      if (msg.type === "ready") {
        clearTimeout(timer);
        try { await openCamera(); }
        catch (err) { clearTimeout(timer); worker.terminate(); reject(err); return; } // keep err.name for the camera branch
        let lastVideoTime = -1;
        const loop = () => {
          if (!busy && video.currentTime !== lastVideoTime && video.videoWidth) {
            lastVideoTime = video.currentTime;
            busy = true;
            createImageBitmap(video).then((bitmap) => {
              worker.postMessage({ type: "frame", bitmap, t: performance.now() }, [bitmap]);
            }).catch(() => { busy = false; });
          }
          requestAnimationFrame(loop);
        };
        loop();
        resolve();
      }
    };
    worker.postMessage({ type: "init", modelPath: MODEL_PATH });
  });
}

// Fallback: inference inline on the main thread (original path)
async function startLiveInline() {
  const MP = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14";
  const { PoseLandmarker, FilesetResolver } = await import(MP);
  const vision = await FilesetResolver.forVisionTasks(`${MP}/wasm`);
  const landmarker = await PoseLandmarker.createFromOptions(vision, {
    baseOptions: { modelAssetPath: MODEL_PATH, delegate: "GPU" },
    runningMode: "VIDEO",
    numPoses: 1,
  });
  await openCamera();
  let lastVideoTime = -1;
  const loop = () => {
    if (video.currentTime !== lastVideoTime) {
      lastVideoTime = video.currentTime;
      const now = performance.now();
      const result = landmarker.detectForVideo(video, now);
      inferMs += (performance.now() - now - inferMs) * 0.1;
      if (result.landmarks?.[0]) onFrame(result.landmarks[0], now);
    }
    requestAnimationFrame(loop);
  };
  loop();
}

async function startLive() {
  try {
    await startLiveWorker();
    console.info("pose inference: worker thread");
  } catch (err) {
    // a camera denial fails identically inline — don't re-download the model for it
    if (CAMERA_ERRORS.test((err.name || "") + (err.message || ""))) throw err;
    console.warn(`pose worker unavailable (${err.message}); falling back to main thread`);
    stageMsg.textContent = "retrying without worker…";
    await startLiveInline();
  }
}

function startSynthetic() {
  sizeOverlay();
  stageMsg.hidden = true;
  framedOnce = true; // no setup assistant for the scripted skeleton
  debugPanel.hidden = false;
  const start = performance.now();
  const step = () => {
    const now = performance.now();
    onFrame(syntheticFrame(now - start), now);
    requestAnimationFrame(step);
  };
  step();
}

(async () => {
  try {
    if (SYNTHETIC) startSynthetic();
    else await startLive();
  } catch (err) {
    stageMsg.hidden = false;
    stageMsg.classList.add("error");
    stageMsg.textContent = err.name === "NotAllowedError"
      ? "⚠ camera blocked — tap the 📷 icon in the address bar, allow, reload"
      : err.name === "NotFoundError"
        ? "⚠ no camera found — plug one in, or add ?synthetic=1 for the demo feed"
        : `⚠ ${err.message} — add ?synthetic=1 for the demo feed`;
  }
})();
