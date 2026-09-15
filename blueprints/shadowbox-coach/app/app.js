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
  $("gate-panel").hidden = false;
  $("program-title").textContent = guide.title.toUpperCase();
  buildProgramGrid();
  renderWorkout();
  renderStreak();
}).catch(() => {});

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
  $("streak-line").textContent =
    `${streak > 0 ? "🔥 " + streak + "-day streak · " : ""}${done}/${woDays.length || 70} days complete`;
}

// ---- phase gate: this session's telemetry vs the promotion targets ----
const GATE_CHECKS = {
  arm_punch_pct: { get: () => form.powerPunches ? (100 * form.armPunches / form.powerPunches) : null, pass: (v) => v <= 25, fmt: (v) => v.toFixed(0) + "%" },
  guard_height_sw: { get: () => form.guardN ? form.guardSum / form.guardN : null, pass: (v) => v >= 0.85, fmt: (v) => v.toFixed(2) + " sw" },
  avg_retraction_ms: { get: () => form.retractN ? form.retractSum / form.retractN : null, pass: (v) => v <= 350, fmt: (v) => v.toFixed(0) + " ms" },
  punches_per_round: { get: () => roundHistory.length ? roundHistory[roundHistory.length - 1].thrown : (stats.total || null), pass: (v) => v >= 120, fmt: (v) => String(Math.round(v)) },
  avg_power: { get: () => form.powerN ? form.powerSum / form.powerN : null, pass: (v) => v >= 55, fmt: (v) => v.toFixed(0) },
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
  $("wo-focus").textContent = d.rounds
    ? `${d.focus.toUpperCase()} — ${d.rounds} × ${fmt(d.roundSec)} / ${fmt(d.restSec)} rest`
    : `${d.focus.toUpperCase()} — REST / RECOVERY`;
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
  $("wo-done").classList.toggle("completed", prog.done.includes(woDayKey(d)));
  $("wo-done").classList.toggle("ready", allChecked && !prog.done.includes(woDayKey(d)));
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
  if (!d) return;
  if (!d.rounds || !d.roundSec) {
    // rest / recovery day — never start a zero-length timer (Sahin's sign-off, issue 1)
    $("coach-text").textContent = `${d.title}: rest day. ${d.summary} No rounds to score — recover, and mark it ✓ DONE.`;
    return;
  }
  ROUND_SEC = d.roundSec; REST_SEC = d.restSec;
  workoutFocus = d.coach_focus;
  $("btn-reset").click();
  $("btn-start").click();
  $("coach-text").textContent = `Today: ${d.title} — ${d.summary}`;
});
$("wo-done").addEventListener("click", () => {
  const d = woDays[woIdx];
  if (!d) return;
  const k = woDayKey(d);
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
  if (woIdx < woDays.length - 1) woIdx++;
  renderWorkout();
  renderStreak();
});

// ---- visual-reasoning feedback: press x to flag the last call as wrong ----
// annotations land in training_log.jsonl, the dataset the error-discovery
// skill reviews and clusters into failure modes
document.addEventListener("keydown", (e) => {
  if (e.key !== "x" || !punchLog.length) return;
  const last = punchLog[punchLog.length - 1];
  const note = prompt(`Flag call "${last.hand} ${last.type}" as wrong. What actually happened? (blank = phantom)`);
  if (note === null) return;
  logEvent({
    type: "call_feedback", verdict: "wrong",
    flagged: { hand: last.hand, type: last.type, speed: +last.speed.toFixed(1), power: last.power },
    actual: note.trim() || "phantom — no punch thrown",
    recent: punchLog.slice(-5).map((p) => p.type),
    rotation_rate: +rotation.rate.toFixed(2),
    day: woDays[woIdx] ? woDayKey(woDays[woIdx]) : null,
    config: { extendAt: CFG.extendAt, minPeakSpeed: CFG.minPeakSpeed, peakDrop: CFG.peakDrop },
  });
  flash.textContent = "FLAGGED";
  flash.classList.remove("pop");
  void flash.offsetWidth;
  flash.classList.add("pop");
});

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

function onFrame(landmarks, now) {
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

  for (const [hand, wi, ei, si] of [["L", L.L_WRIST, L.L_ELBOW, L.L_SHOULDER], ["R", L.R_WRIST, L.R_ELBOW, L.R_SHOULDER]]) {
    const tracker = hands[hand];
    const ev = tracker.update(lm.get(wi), lm.get(ei), lm.get(si), ctx2, now);
    if (ev && !resting) {
      ev.power = punchPower(ev.speed, rotation.rate);
      recordPunch(ev, now);
    }
    if (tracker.phase === "guard") {
      if (tracker.lastRetractMs != null && tracker.lastRetractMs < 2000) {
        form.retractSum += tracker.lastRetractMs; form.retractN++;
        tracker.lastRetractMs = null;
      }
      // guard height: how far the wrist sits above the shoulder line, in sw
      form.guardSum += (lm.get(si).y - lm.get(wi).y) / sw; form.guardN++;
    }
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

// ---- round timer ----
function fmt(s) { return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }
function renderClock() {
  $("round-clock").textContent = fmt(roundLeft);
  $("round-clock").classList.toggle("rest", resting);
  $("round-label").textContent = resting ? "REST" : `ROUND ${roundNum}`;
}
$("btn-start").addEventListener("click", () => {
  if (ticking) { clearInterval(ticking); ticking = null; $("btn-start").textContent = "START"; return; }
  $("btn-start").textContent = "PAUSE";
  ticking = setInterval(() => {
    roundLeft--;
    if (roundLeft <= 0) {
      if (resting) { resting = false; roundNum++; roundLeft = ROUND_SEC; roundStart = { ...stats }; }
      else { resting = true; roundLeft = REST_SEC; closeRound(); askCoach(); }
    }
    renderClock();
  }, 1000);
});
$("btn-reset").addEventListener("click", () => {
  clearInterval(ticking); ticking = null; $("btn-start").textContent = "START";
  roundNum = 1; roundLeft = ROUND_SEC; resting = false;
  Object.assign(stats, { total: 0, JAB: 0, CROSS: 0, HOOK: 0, UPPERCUT: 0, peakSpeed: 0 });
  punchLog.length = 0;
  roundHistory.length = 0;
  roundStart = { ...stats };
  $("rounds-panel").hidden = true;
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
const LMSTUDIO = "http://localhost:1234/v1";

// Curriculum grounding: coach_kb.json is distilled from boxing.dharmicdata.org
// by pipeline/flow.py. The coach picks the focus theme matching the round's
// weakest form stat and grounds its cue in real curriculum lines.
let coachKB = null;
fetch("coach_kb.json").then((r) => r.ok ? r.json() : null).then((kb) => { coachKB = kb; }).catch(() => {});

let workoutFocus = null; // set by START DAY: today's curriculum focus overrides the heuristic
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

async function askCoach() {
  const el = $("coach-text"), src = $("coach-source");
  el.textContent = "…coach is thinking";
  try {
    const models = await fetch(`${LMSTUDIO}/models`, { signal: AbortSignal.timeout(1500) }).then((r) => r.json());
    const model = models.data?.[0]?.id;
    if (!model) throw new Error("no model loaded");
    const res = await fetch(`${LMSTUDIO}/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: AbortSignal.timeout(30000),
      body: JSON.stringify({
        model,
        max_tokens: 120,
        temperature: 0.7,
        messages: [
          {
            role: "system",
            content: "You are a boxing corner coach between rounds. Given round stats, give ONE specific, punchy coaching cue in under 40 words. Prioritize form problems: high arm_punch_pct means they aren't turning the body; slow avg_retraction_ms means hands hang out; low guard_height means the chin is open. No preamble, no lists." +
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
    el.textContent = text;
    src.textContent = `live · ${model}`;
    src.classList.add("live");
  } catch {
    el.textContent = CANNED[cannedIdx++ % CANNED.length];
    src.textContent = "canned tips (start LM Studio + enable CORS for live coaching)";
    src.classList.remove("live");
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
  stageMsg.textContent = "requesting camera…";
  const stream = await navigator.mediaDevices.getUserMedia({
    // 60 fps halves the sampling interval: tighter peaks, ~16 ms less latency
    video: { width: 960, height: 720, facingMode: "user", frameRate: { ideal: 60 } },
  });
  video.srcObject = stream;
  await video.play();
  sizeOverlay();
  stageMsg.hidden = true;
}

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
        try { await openCamera(); } catch (err) { bail(err.message); return; }
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
    console.warn(`pose worker unavailable (${err.message}); falling back to main thread`);
    await startLiveInline();
  }
}

function startSynthetic() {
  sizeOverlay();
  stageMsg.hidden = true;
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
    stageMsg.textContent = `Could not start: ${err.message}. Allow camera access and reload — or add ?synthetic=1 to watch the built-in sparring partner.`;
  }
})();
