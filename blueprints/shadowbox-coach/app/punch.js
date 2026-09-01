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
  leadHand: "L",       // orthodox: left = jab. Southpaw flips this to "R".
  smoother: "ema",     // "ema" | "oneeuro" — which landmark filter to use
  minCutoff: 1.2,      // one-euro: baseline smoothing (lower = smoother, laggier)
  euroBeta: 0.04,      // one-euro: how fast smoothing relaxes with speed
  // Values below were found by sweep.mjs (random search scored by eval.mjs,
  // validated on held-out seeds): holdout F1 1.000 — every punch scored, zero
  // phantoms, zero misses — at 62 ms mean impact latency (the search traded
  // ~20 ms of latency for never being wrong; still under the 80 ms gate and
  // ~2 camera frames at 30 fps). Don't hand-tweak — re-run the sweep.
  smooth: 0.72,        // EMA alpha for landmarks (higher = snappier)
  zWeight: 0.79,       // how much to trust MediaPipe's relative depth
  extendAt: 1.07,      // reach that arms a punch
  returnAt: 0.97,      // reach that re-enters guard
  peakDrop: 0.145,     // reach falling this far below max = impact just happened
  rearm: 0.14,         // rise off the retraction low that counts as punching again
  minPeakSpeed: 3.17,  // slower than this is a stretch, not a punch
  armSpeed: 0.99,      // outbound speed required to arm — punches leave guard fast
  guardWindowMs: 350,  // a punch must launch from guard this recently (kills phantom counts from hanging arms)
  elbowArm: 151,       // a straight elbow also arms the punch (depth under-reads straights at the camera)
  elbowStraight: 143,  // bent elbow at peak = hook; straighter = jab/cross
  cooldownMs: 98,      // jitter guard only — the re-arm path handles real double counts
  speedAlpha: 0.39,    // EMA on hand speed used for gates — soaks up single-frame noise spikes (the phantom killer)
  armFrames: 1,        // consecutive qualifying frames required to arm
  predVel: 999,        // predictive impact: fire when smoothed reach velocity drops below -predVel
                       // (sw/s) instead of waiting for the reach to fall peakDrop. 999 = off
                       // (finite so it survives JSON round-trips in sweep results).
};

// Rough per-punch power score from hand speed + torso rotation (the kinetic
// chain): an arm-punch moves the hand without turning the shoulders. Yaw is
// read from the shoulders' relative depth, so this is an estimate, not force.
export function punchPower(speed, yawRate) {
  return Math.max(5, Math.min(99, Math.round(55 * speed / 6 + 45 * Math.abs(yawRate) / 4)));
}

export class ShoulderRotation {
  constructor(alpha = 0.4) { this.alpha = alpha; this.prev = null; this.rate = 0; }
  update(ls, rs, now) {
    const yaw = Math.atan2((ls.z - rs.z), (ls.x - rs.x));
    if (this.prev) {
      const dt = Math.max((now - this.prev.t) / 1000, 1e-3);
      let d = yaw - this.prev.yaw;
      if (d > Math.PI) d -= 2 * Math.PI;
      if (d < -Math.PI) d += 2 * Math.PI;
      this.rate += this.alpha * (d / dt - this.rate);
    }
    this.prev = { yaw, t: now };
    return this.rate;
  }
}

export function elbowAngleDeg(shoulder, elbow, wrist) {
  const ax = shoulder.x - elbow.x, ay = shoulder.y - elbow.y, az = (shoulder.z - elbow.z) * CFG.zWeight;
  const bx = wrist.x - elbow.x, by = wrist.y - elbow.y, bz = (wrist.z - elbow.z) * CFG.zWeight;
  const cos = (ax * bx + ay * by + az * bz) /
    (Math.hypot(ax, ay, az) * Math.hypot(bx, by, bz) + 1e-9);
  return Math.acos(Math.min(1, Math.max(-1, cos))) * 180 / Math.PI;
}

export class LandmarkSmoother {
  constructor(alpha = CFG.smooth) {
    this.alpha = alpha;
    this.pts = new Map();
  }
  update(landmarks, _tMs) {
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

// One Euro filter (Casiez et al.): smooth when slow, snappy when fast —
// a better lag/jitter trade for punch-speed motion than a fixed EMA.
class OneEuroAxis {
  constructor(minCutoff, beta, dCutoff = 1) {
    this.minCutoff = minCutoff; this.beta = beta; this.dCutoff = dCutoff;
    this.prev = null;
  }
  static alpha(cutoff, dt) {
    const tau = 1 / (2 * Math.PI * cutoff);
    return 1 / (1 + tau / dt);
  }
  filter(x, tMs) {
    if (!this.prev) { this.prev = { x, dx: 0, t: tMs }; return x; }
    const dt = Math.max((tMs - this.prev.t) / 1000, 1e-3);
    const aD = OneEuroAxis.alpha(this.dCutoff, dt);
    const dx = aD * ((x - this.prev.x) / dt) + (1 - aD) * this.prev.dx;
    const a = OneEuroAxis.alpha(this.minCutoff + this.beta * Math.abs(dx), dt);
    const xf = a * x + (1 - a) * this.prev.x;
    this.prev = { x: xf, dx, t: tMs };
    return xf;
  }
}

export class OneEuroSmoother {
  constructor(minCutoff = CFG.minCutoff, beta = CFG.euroBeta) {
    this.minCutoff = minCutoff; this.beta = beta;
    this.filters = new Map();
    this.pts = new Map();
  }
  update(landmarks, tMs) {
    for (const i of Object.values(L)) {
      let f = this.filters.get(i);
      if (!f) {
        f = {
          x: new OneEuroAxis(this.minCutoff, this.beta),
          y: new OneEuroAxis(this.minCutoff, this.beta),
          z: new OneEuroAxis(this.minCutoff, this.beta),
        };
        this.filters.set(i, f);
        this.pts.set(i, { x: 0, y: 0, z: 0 });
      }
      const p = this.pts.get(i), cur = landmarks[i];
      p.x = f.x.filter(cur.x, tMs);
      p.y = f.y.filter(cur.y, tMs);
      p.z = f.z.filter(cur.z, tMs);
    }
    return this.pts;
  }
}

export function makeSmoother() {
  return CFG.smoother === "oneeuro" ? new OneEuroSmoother() : new LandmarkSmoother();
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
    this.lastGuardAt = -Infinity;
    this.reach = 0;
    this.reachVel = 0; // smoothed d(reach)/dt — its zero-crossing IS the impact
    this.speed = 0;
    this.speedSm = 0;
    this.armStreak = 0;
    this.elbowAngle = 0;
    this.lastRetractMs = null; // impact → back-in-guard time of the last punch
  }

  // ctx: { sw (shoulder width), hipY (avg hip height, image coords) }
  update(wrist, elbow, shoulder, ctx, now) {
    const sw = ctx.sw;
    const dx = wrist.x - shoulder.x, dy = wrist.y - shoulder.y;
    const dz = (wrist.z - shoulder.z) * CFG.zWeight;
    const prevReach = this.reach;
    this.reach = Math.hypot(dx, dy, dz) / sw;
    if (this.prev) {
      const dtv = Math.max((now - this.prev.t) / 1000, 1e-3);
      this.reachVel += 0.5 * ((this.reach - prevReach) / dtv - this.reachVel);
    }
    this.elbowAngle = elbowAngleDeg(shoulder, elbow, wrist);

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
    this.speedSm += CFG.speedAlpha * (this.speed - this.speedSm);

    // Scored at impact, CompuBox-style: the event fires the moment the reach
    // curve turns over (peak extension), not after the hand returns to guard.
    // "retracting" exists only to prevent double counts — and to re-arm on a
    // half-retracted double jab, which never gets back to guard at all.
    let event = null;
    if (this.phase === "guard") {
      if (this.reach < CFG.returnAt) { this.guardPos = { ...wrist }; this.lastGuardAt = now; }
      // Arm on reach — or on a straight elbow, since depth under-reads straights
      // thrown at the camera. Either way the punch must have LEFT GUARD recently
      // and be moving fast: hanging arms and camera drift never arm.
      const extended = this.reach > CFG.extendAt ||
        (this.elbowAngle > CFG.elbowArm && this.reach > 0.8);
      if (extended && this.guardPos &&
          now - this.lastGuardAt < CFG.guardWindowMs && this.speedSm > CFG.armSpeed) {
        this.armStreak++;
        if (this.armStreak >= CFG.armFrames) {
          this.phase = "extended";
          this.peak = { reach: this.reach, speed: this.speedSm, pos: { ...wrist }, elbowAngle: this.elbowAngle };
        }
      } else this.armStreak = 0;
    } else if (this.phase === "extended") {
      if (this.reach >= this.peak.reach) {
        this.peak.reach = this.reach;
        this.peak.pos = { ...wrist };
        this.peak.elbowAngle = this.elbowAngle;
      }
      this.peak.speed = Math.max(this.peak.speed, this.speedSm);
      // impact = the reach curve turning over: either it has fallen peakDrop
      // below max, or (predictive) its velocity has swung hard negative
      if (this.reach < this.peak.reach - CFG.peakDrop || this.reachVel < -CFG.predVel) {
        this.phase = "retracting";
        this.localMin = this.reach;
        const aboveHips = this.peak.pos.y < ctx.hipY; // image y grows downward
        if (aboveHips && this.peak.speed >= CFG.minPeakSpeed && now - this.lastCountAt > CFG.cooldownMs) {
          this.lastCountAt = now;
          event = { hand: this.hand, type: this.classify(sw), speed: this.peak.speed };
        }
      }
    } else { // retracting
      this.localMin = Math.min(this.localMin, this.reach);
      if (this.reach < CFG.returnAt) {
        this.phase = "guard";
        this.guardPos = { ...wrist };
        this.lastGuardAt = now;
        this.lastRetractMs = now - this.lastCountAt;
      } else if (this.reach > this.localMin + CFG.rearm && this.speedSm >= CFG.minPeakSpeed * 0.6) {
        // thrown again without returning to guard — double jab
        this.phase = "extended";
        this.peak = { reach: this.reach, speed: this.speed, pos: { ...wrist }, elbowAngle: this.elbowAngle };
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
    // A hook is a bent-elbow punch; direction alone misreads crosses that
    // travel across the midline. Elbow geometry at peak is the honest signal.
    if (this.peak.elbowAngle < CFG.elbowStraight) return "HOOK";
    return this.hand === CFG.leadHand ? "JAB" : "CROSS";
  }
}

// ---- synthetic sparring partner ------------------------------------------
// A scripted skeleton throwing jab, cross, lead hook, rear uppercut on a
// loop. Used by ?synthetic=1 in the app and by the Node unit test.

export const SYNTH = {
  combo: [
    { hand: "L", type: "JAB", d: { x: 0, y: -0.1, z: -1.6 }, arm: "straight" },
    { hand: "R", type: "CROSS", d: { x: 0, y: -0.1, z: -1.6 }, arm: "straight" },
    { hand: "L", type: "HOOK", d: { x: -1.5, y: 0, z: -0.4 }, arm: "bent" },
    { hand: "R", type: "UPPERCUT", d: { x: 0.2, y: -1.5, z: -0.3 }, arm: "bent" },
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
  const { hand, d, arm } = combo[idx];
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
  // a straight punch straightens the arm: elbow tracks the shoulder–wrist
  // midpoint at full extension; hooks and uppercuts keep the elbow bent
  if (arm === "straight" && k > 0) {
    const s = lm[hand === "L" ? L.L_SHOULDER : L.R_SHOULDER];
    const e = lm[hand === "L" ? L.L_ELBOW : L.R_ELBOW];
    const mid = { x: (s.x + w.x) / 2, y: (s.y + w.y) / 2, z: (s.z + w.z) / 2 };
    e.x += (mid.x - e.x) * k;
    e.y += (mid.y - e.y) * k;
    e.z += (mid.z - e.z) * k;
  }
  return lm;
}
