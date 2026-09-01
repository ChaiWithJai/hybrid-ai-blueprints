// Shadowbox Coach — webcam punch tracker (MediaPipe pose) + Bonsai corner coach.
// All inference is on-device: pose in the browser, coaching via LM Studio on localhost.

import { L, BONES, CFG, HandTracker, LandmarkSmoother, SYNTH, syntheticFrame } from "./punch.js";

const SYNTHETIC = new URLSearchParams(location.search).has("synthetic");
const ROUND_SEC = 180, REST_SEC = 60;

// ---- DOM ----
const $ = (id) => document.getElementById(id);
const video = $("video"), overlay = $("overlay"), ctx = overlay.getContext("2d");
const stageMsg = $("stage-msg"), flash = $("punch-flash"), debugPanel = $("debug-panel");

// ---- session state ----
const stats = { total: 0, JAB: 0, CROSS: 0, HOOK: 0, UPPERCUT: 0, peakSpeed: 0 };
const punchLog = []; // {t, type, hand, speed} — feeds PPM + the coach
let roundNum = 1, roundLeft = ROUND_SEC, resting = false, ticking = null;

const hands = { L: new HandTracker("L"), R: new HandTracker("R") };
const smoother = new LandmarkSmoother();

function onFrame(landmarks, now) {
  const lm = smoother.update(landmarks);
  const ls = lm.get(L.L_SHOULDER), rs = lm.get(L.R_SHOULDER);
  const sw = Math.hypot(ls.x - rs.x, ls.y - rs.y);
  if (sw < 0.02) return; // not actually facing the camera

  for (const [hand, wristIdx, shoulderIdx] of [["L", L.L_WRIST, L.L_SHOULDER], ["R", L.R_WRIST, L.R_SHOULDER]]) {
    const ev = hands[hand].update(lm.get(wristIdx), lm.get(shoulderIdx), sw, now);
    if (ev && !resting) recordPunch(ev, now);
  }
  draw(lm);
  for (const [hand, id] of [["L", "meter-l"], ["R", "meter-r"]]) {
    const el = $(id);
    el.style.width = `${Math.min(100, (hands[hand].reach / 1.6) * 100)}%`;
    el.classList.toggle("armed", hands[hand].reach > CFG.extendAt);
  }
  if (!debugPanel.hidden) {
    debugPanel.textContent =
      `L reach ${hands.L.reach.toFixed(2)}  speed ${hands.L.speed.toFixed(1)}  phase ${hands.L.phase}\n` +
      `R reach ${hands.R.reach.toFixed(2)}  speed ${hands.R.speed.toFixed(1)}  phase ${hands.R.phase}\n` +
      `shoulder-width ${sw.toFixed(3)}  ${SYNTHETIC ? "SYNTHETIC FEED" : "live camera"}`;
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
  $("stat-total").textContent = stats.total;
  $("stat-jab").textContent = stats.JAB;
  $("stat-cross").textContent = stats.CROSS;
  $("stat-hook").textContent = stats.HOOK;
  $("stat-uppercut").textContent = stats.UPPERCUT;
  $("stat-speed").innerHTML = `${stats.peakSpeed.toFixed(1)}<small>sw/s</small>`;
  flash.textContent = ev.type === "JAB" || ev.type === "CROSS" ? ev.type : `${ev.hand} ${ev.type}`;
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
      if (resting) { resting = false; roundNum++; roundLeft = ROUND_SEC; }
      else { resting = true; roundLeft = REST_SEC; askCoach(); }
    }
    renderClock();
  }, 1000);
});
$("btn-reset").addEventListener("click", () => {
  clearInterval(ticking); ticking = null; $("btn-start").textContent = "START";
  roundNum = 1; roundLeft = ROUND_SEC; resting = false;
  renderClock();
});
renderClock();

document.addEventListener("keydown", (e) => {
  if (e.key === "d") debugPanel.hidden = !debugPanel.hidden;
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
    jabs: stats.JAB, crosses: stats.CROSS, hooks: stats.HOOK, uppercuts: stats.UPPERCUT,
    punches_per_min: Number($("stat-ppm").textContent),
    fastest_hand_sw_per_s: Number(stats.peakSpeed.toFixed(1)),
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
          { role: "system", content: "You are a boxing corner coach between rounds. Given round stats, give ONE specific, punchy coaching cue in under 40 words. No preamble, no lists." },
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

async function startLive() {
  const MP = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14";
  const { PoseLandmarker, FilesetResolver } = await import(MP);
  const vision = await FilesetResolver.forVisionTasks(`${MP}/wasm`);
  const landmarker = await PoseLandmarker.createFromOptions(vision, {
    baseOptions: {
      modelAssetPath:
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
      delegate: "GPU",
    },
    runningMode: "VIDEO",
    numPoses: 1,
  });
  stageMsg.textContent = "requesting camera…";
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { width: 960, height: 720, facingMode: "user" },
  });
  video.srcObject = stream;
  await video.play();
  sizeOverlay();
  stageMsg.hidden = true;

  let lastVideoTime = -1;
  const loop = () => {
    if (video.currentTime !== lastVideoTime) {
      lastVideoTime = video.currentTime;
      const now = performance.now();
      const result = landmarker.detectForVideo(video, now);
      if (result.landmarks?.[0]) onFrame(result.landmarks[0], now);
    }
    requestAnimationFrame(loop);
  };
  loop();
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
