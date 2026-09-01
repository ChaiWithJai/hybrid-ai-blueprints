// Shadowbox Coach — webcam punch tracker (MediaPipe pose) + Bonsai corner coach.
// All inference is on-device: pose in the browser, coaching via LM Studio on localhost.

import { L, BONES, CFG, HandTracker, makeSmoother, SYNTH, syntheticFrame, ShoulderRotation, punchPower } from "./punch.js";

const PARAMS = new URLSearchParams(location.search);
const SYNTHETIC = PARAMS.has("synthetic");
const POSE_MODEL = ["lite", "full", "heavy"].includes(PARAMS.get("model")) ? PARAMS.get("model") : "lite";
const ROUND_SEC = 180, REST_SEC = 60;

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
          { role: "system", content: "You are a boxing corner coach between rounds. Given round stats, give ONE specific, punchy coaching cue in under 40 words. Prioritize form problems: high arm_punch_pct means they aren't turning the body; slow avg_retraction_ms means hands hang out; low guard_height means the chin is open. No preamble, no lists." },
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
