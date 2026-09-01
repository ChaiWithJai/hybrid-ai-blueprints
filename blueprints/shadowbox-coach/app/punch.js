// Punch detection core — no DOM, no MediaPipe. Runs in the browser and in Node,
// so the counting logic is unit-testable without a camera.

// MediaPipe pose landmark indices
export const L = {
  NOSE: 0,
  L_SHOULDER: 11, R_SHOULDER: 12,
  L_ELBOW: 13, R_ELBOW: 14,
  L_WRIST: 15, R_WRIST: 16,
  L_HIP: 23, R_HIP: 24,
};
export const BONES = [
  [11, 12], [11, 13], [13, 15], [12, 14], [14, 16],
  [11, 23], [12, 24], [23, 24],
];

// tunables (distances in shoulder-widths, speeds in shoulder-widths/sec)
export const CFG = {
  smooth: 0.55,        // EMA alpha for landmarks (higher = snappier)
  zWeight: 0.7,        // how much to trust MediaPipe's relative depth
  extendAt: 1.15,      // reach that arms a punch
  returnAt: 0.95,      // reach that re-enters guard
  peakDrop: 0.08,      // reach falling this far below max = impact just happened
  rearm: 0.2,          // rise off the retraction low that counts as punching again
  minPeakSpeed: 2.2,   // slower than this is a stretch, not a punch
  cooldownMs: 120,     // jitter guard only — the re-arm path handles real double counts
};

export class LandmarkSmoother {
  constructor(alpha = CFG.smooth) {
    this.alpha = alpha;
    this.pts = new Map();
  }
  update(landmarks) {
    for (const i of Object.values(L)) {
      const cur = landmarks[i], prev = this.pts.get(i);
      if (!prev) { this.pts.set(i, { ...cur }); continue; }
      prev.x += this.alpha * (cur.x - prev.x);
      prev.y += this.alpha * (cur.y - prev.y);
      prev.z += this.alpha * (cur.z - prev.z);
    }
    return this.pts;
  }
}

// One small state machine per hand. reach = 3D wrist-to-shoulder distance in
// shoulder-width units, so it is scale-invariant; z (relative depth) is what
// catches straights thrown at the camera, which barely move in 2D.
export class HandTracker {
  constructor(hand) {
    this.hand = hand; // "L" | "R"
    this.phase = "guard";
    this.prev = null;
    this.guardPos = null;
    this.peak = null;
    this.lastCountAt = -Infinity;
    this.reach = 0;
    this.speed = 0;
  }

  update(wrist, shoulder, sw, now) {
    const dx = wrist.x - shoulder.x, dy = wrist.y - shoulder.y;
    const dz = (wrist.z - shoulder.z) * CFG.zWeight;
    this.reach = Math.hypot(dx, dy, dz) / sw;

    if (this.prev) {
      const dt = (now - this.prev.t) / 1000;
      if (dt > 0) {
        this.speed = Math.hypot(
          wrist.x - this.prev.x, wrist.y - this.prev.y,
          (wrist.z - this.prev.z) * CFG.zWeight,
        ) / sw / dt;
      }
    }
    this.prev = { ...wrist, t: now };

    // Scored at impact, CompuBox-style: the event fires the moment the reach
    // curve turns over (peak extension), not after the hand returns to guard.
    // "retracting" exists only to prevent double counts — and to re-arm on a
    // half-retracted double jab, which never gets back to guard at all.
    let event = null;
    if (this.phase === "guard") {
      if (this.reach < CFG.returnAt) this.guardPos = { ...wrist };
      if (this.reach > CFG.extendAt && this.guardPos) {
        this.phase = "extended";
        this.peak = { reach: this.reach, speed: this.speed, pos: { ...wrist } };
      }
    } else if (this.phase === "extended") {
      if (this.reach >= this.peak.reach) {
        this.peak.reach = this.reach;
        this.peak.pos = { ...wrist };
      }
      this.peak.speed = Math.max(this.peak.speed, this.speed);
      if (this.reach < this.peak.reach - CFG.peakDrop) {
        this.phase = "retracting";
        this.localMin = this.reach;
        if (this.peak.speed >= CFG.minPeakSpeed && now - this.lastCountAt > CFG.cooldownMs) {
          this.lastCountAt = now;
          event = { hand: this.hand, type: this.classify(sw), speed: this.peak.speed };
        }
      }
    } else { // retracting
      this.localMin = Math.min(this.localMin, this.reach);
      if (this.reach < CFG.returnAt) {
        this.phase = "guard";
        this.guardPos = { ...wrist };
      } else if (this.reach > this.localMin + CFG.rearm && this.speed >= CFG.minPeakSpeed * 0.6) {
        // thrown again without returning to guard — double jab
        this.phase = "extended";
        this.peak = { reach: this.reach, speed: this.speed, pos: { ...wrist } };
      }
    }
    return event;
  }

  classify(sw) {
    const g = this.guardPos, p = this.peak.pos;
    const lateral = Math.abs(p.x - g.x) / sw;
    const up = (g.y - p.y) / sw;                             // image y grows downward
    const fwd = Math.max(0, (g.z - p.z) * CFG.zWeight) / sw; // toward camera
    if (up > 0.35 && up >= lateral && up >= fwd) return "UPPERCUT";
    if (lateral > fwd * 1.15 && lateral > 0.5) return "HOOK";
    return this.hand === "L" ? "JAB" : "CROSS";
  }
}

// ---- synthetic sparring partner ------------------------------------------
// A scripted skeleton throwing jab, cross, lead hook, rear uppercut on a
// loop. Used by ?synthetic=1 in the app and by the Node unit test.

export const SYNTH = {
  combo: [
    { hand: "L", type: "JAB", d: { x: 0, y: -0.1, z: -1.6 } },
    { hand: "R", type: "CROSS", d: { x: 0, y: -0.1, z: -1.6 } },
    { hand: "L", type: "HOOK", d: { x: -1.5, y: 0, z: -0.4 } },
    { hand: "R", type: "UPPERCUT", d: { x: 0.2, y: -1.5, z: -0.3 } },
  ],
  punchMs: 500,
  gapMs: 300,
  sw: 0.24,
  cycleMs: 4 * 800,
};

const SYNTH_BASE = (() => {
  const base = {};
  for (const i of Object.values(L)) base[i] = { x: 0.5, y: 0.5, z: 0 };
  Object.assign(base[L.NOSE], { x: 0.5, y: 0.22 });
  Object.assign(base[L.L_SHOULDER], { x: 0.62, y: 0.35 });
  Object.assign(base[L.R_SHOULDER], { x: 0.38, y: 0.35 });
  Object.assign(base[L.L_ELBOW], { x: 0.66, y: 0.48 });
  Object.assign(base[L.R_ELBOW], { x: 0.34, y: 0.48 });
  Object.assign(base[L.L_HIP], { x: 0.58, y: 0.72 });
  Object.assign(base[L.R_HIP], { x: 0.42, y: 0.72 });
  return base;
})();
const SYNTH_GUARD = {
  L: { x: 0.60, y: 0.30, z: -0.05 },
  R: { x: 0.40, y: 0.30, z: -0.05 },
};

export function syntheticFrame(tMs) {
  const { combo, punchMs, gapMs, sw, cycleMs } = SYNTH;
  const tIn = tMs % cycleMs;
  const idx = Math.floor(tIn / (punchMs + gapMs));
  const tPunch = tIn - idx * (punchMs + gapMs);
  const { hand, d } = combo[idx];
  // triangle wave: out for the first half of the punch window, back for the second
  let k = 0;
  if (tPunch < punchMs) k = tPunch < punchMs / 2 ? tPunch / (punchMs / 2) : 2 - tPunch / (punchMs / 2);

  const lm = [];
  for (const i of Object.values(L)) lm[i] = { ...SYNTH_BASE[i] };
  lm[L.L_WRIST] = { ...SYNTH_GUARD.L };
  lm[L.R_WRIST] = { ...SYNTH_GUARD.R };
  const w = hand === "L" ? lm[L.L_WRIST] : lm[L.R_WRIST];
  w.x += d.x * sw * k;
  w.y += d.y * sw * k;
  w.z += d.z * sw * k;
  return lm;
}
