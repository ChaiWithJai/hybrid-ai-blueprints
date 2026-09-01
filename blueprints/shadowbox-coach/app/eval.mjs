// Verifiable-reward eval harness for the punch detector.
//
// Generates synthetic sparring across body sizes, punch speeds, landmark
// noise, and framerates — plus NEGATIVE scenarios (hanging arms, slow
// reaches, guard jitter) that must score zero calls. The reward is
// F1-shaped: +1 per correct call, penalties for phantom calls, misses,
// and late scoring. Run directly for a report at the current CFG:
//
//   node eval.mjs
//
import { L, CFG, HandTracker, makeSmoother } from "./punch.js";

// ---- seeded rng ----
export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const randn = (rng) => {
  const u = Math.max(rng(), 1e-9), v = rng();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
};

// ---- actor: a parameterized skeleton ----
function makeActor({ sw = 0.24, guardY = 0.30, amplitude = 1.0 }) {
  const S = 0.5;
  const base = {};
  for (const i of Object.values(L)) base[i] = { x: S, y: 0.5, z: 0 };
  Object.assign(base[L.NOSE], { x: S, y: 0.22 });
  Object.assign(base[L.L_SHOULDER], { x: S + sw / 2, y: 0.35 });
  Object.assign(base[L.R_SHOULDER], { x: S - sw / 2, y: 0.35 });
  Object.assign(base[L.L_ELBOW], { x: S + sw / 2 + 0.04, y: 0.48 });
  Object.assign(base[L.R_ELBOW], { x: S - sw / 2 - 0.04, y: 0.48 });
  Object.assign(base[L.L_HIP], { x: S + sw / 3, y: 0.72 });
  Object.assign(base[L.R_HIP], { x: S - sw / 3, y: 0.72 });
  const guard = {
    L: { x: S + sw / 2 - 0.02, y: guardY, z: -0.05 },
    R: { x: S - sw / 2 + 0.02, y: guardY, z: -0.05 },
  };
  // extension deltas at k=1, in shoulder-width multiples; sign flips per hand for x
  const PUNCHES = {
    STRAIGHT: { d: { x: -0.08, y: -0.1, z: -1.55 }, arm: "straight" },
    CROSSING: { d: { x: -0.45, y: -0.1, z: -1.45 }, arm: "straight" }, // cross traveling across the midline
    HOOK: { d: { x: -1.5, y: 0, z: -0.4 }, arm: "bent" },
    UPPERCUT: { d: { x: -0.15, y: -1.45, z: -0.35 }, arm: "bent" },
  };
  return {
    sw, guard, base,
    frame(poses) {
      // poses: {L: {punch, k} | null, R: ...} — null means guard
      const lm = [];
      for (const i of Object.values(L)) lm[i] = { ...base[i] };
      for (const hand of ["L", "R"]) {
        const wi = hand === "L" ? L.L_WRIST : L.R_WRIST;
        const ei = hand === "L" ? L.L_ELBOW : L.R_ELBOW;
        const si = hand === "L" ? L.L_SHOULDER : L.R_SHOULDER;
        const w = lm[wi] = { ...guard[hand] };
        const pose = poses[hand];
        if (pose && pose.custom) { Object.assign(w, pose.custom); continue; }
        if (!pose || pose.k <= 0) continue;
        const { d, arm } = PUNCHES[pose.punch];
        const sign = hand === "L" ? 1 : -1;
        const k = pose.k * amplitude;
        w.x += sign * d.x * sw * k;
        w.y += d.y * sw * k;
        w.z += d.z * sw * k;
        if (arm === "straight") {
          const s = lm[si], e = lm[ei];
          e.x += ((s.x + w.x) / 2 - e.x) * k;
          e.y += ((s.y + w.y) / 2 - e.y) * k;
          e.z += ((s.z + w.z) / 2 - e.z) * k;
        }
      }
      return lm;
    },
  };
}

// ---- script segments -> frames + expected events ----
// segment kinds:
//  {kind:"punch", hand, punch, outMs, backMs}          → one expected event at t+outMs
//  {kind:"doublejab", hand, ...}                        → two expected events
//  {kind:"idle", ms}
//  {kind:"handsDown", ms}   {kind:"slowReach", hand}    → expected: nothing
function expandScript(script, actor, rng) {
  const timeline = []; // {t, poses}
  const expected = []; // {t, type}
  let t = 0;
  const typeOf = (hand, punch) =>
    punch === "HOOK" ? "HOOK" : punch === "UPPERCUT" ? "UPPERCUT"
      : hand === CFG.leadHand ? "JAB" : "CROSS";
  for (const seg of script) {
    if (seg.kind === "punch") {
      const { hand, punch, outMs, backMs } = seg;
      expected.push({ t: t + outMs, type: typeOf(hand, punch) });
      timeline.push({ dur: outMs + backMs, poses: (tl) => ({
        [hand]: { punch, k: tl < outMs ? tl / outMs : 1 - (tl - outMs) / backMs },
      }) });
    } else if (seg.kind === "doublejab") {
      const { hand } = seg;
      const [o1, hb, o2, b2] = [150, 130, 110, 220];
      expected.push({ t: t + o1, type: typeOf(hand, "STRAIGHT") });
      expected.push({ t: t + o1 + hb + o2, type: typeOf(hand, "STRAIGHT") });
      timeline.push({ dur: o1 + hb + o2 + b2, poses: (tl) => {
        let k;
        if (tl < o1) k = tl / o1;
        else if (tl < o1 + hb) k = 1 - 0.3 * ((tl - o1) / hb);
        else if (tl < o1 + hb + o2) k = 0.7 + 0.3 * ((tl - o1 - hb) / o2);
        else k = 1 - (tl - o1 - hb - o2) / b2;
        return { [hand]: { punch: "STRAIGHT", k } };
      } });
    } else if (seg.kind === "handsDown") {
      // arms hanging by the hips, body swaying while walking — must not score
      timeline.push({ dur: seg.ms, poses: (tl) => {
        const sway = 0.05 * Math.sin(2 * Math.PI * 1.2 * tl / 1000) +
                     0.03 * Math.sin(2 * Math.PI * 3.1 * tl / 1000);
        const bob = 0.02 * Math.sin(2 * Math.PI * 2.3 * tl / 1000);
        return {
          L: { custom: { x: actor.base[L.L_HIP].x + 0.02 + sway, y: 0.80 + bob, z: 0 } },
          R: { custom: { x: actor.base[L.R_HIP].x - 0.02 + sway, y: 0.80 + bob, z: 0 } },
        };
      } });
    } else if (seg.kind === "slowReach") {
      // reaching for something over 1.6s — extended, but far too slow to be a punch
      const { hand } = seg;
      timeline.push({ dur: 1600, poses: (tl) => ({
        [hand]: { punch: "STRAIGHT", k: tl < 800 ? tl / 800 : 1 - (tl - 800) / 800 },
      }) });
    } else { // idle
      timeline.push({ dur: seg.ms, poses: () => ({}) });
    }
    t += timeline[timeline.length - 1].dur;
  }
  return { timeline, expected, totalMs: t };
}

export function runScenario(scn, seed) {
  const rng = mulberry32(seed * 7919 + scn.id * 104729);
  const actor = makeActor(scn.actor || {});
  const { timeline, expected, totalMs } = expandScript(scn.script, actor, rng);
  const noise = scn.noise ?? 0.003;
  const fps = scn.fps ?? 30;
  const hands = { L: new HandTracker("L"), R: new HandTracker("R") };
  const smoother = makeSmoother();
  const events = [];

  for (let t = 0; t <= totalMs; t += 1000 / fps) {
    // locate segment
    let acc = 0, poses = {};
    for (const seg of timeline) {
      if (t < acc + seg.dur) { poses = seg.poses(t - acc); break; }
      acc += seg.dur;
    }
    const lm = actor.frame(poses);
    for (const i of Object.values(L)) {
      lm[i].x += noise * randn(rng);
      lm[i].y += noise * randn(rng);
      lm[i].z += noise * 2.5 * randn(rng);
    }
    const sm = smoother.update(lm, t);
    const ls = sm.get(L.L_SHOULDER), rs = sm.get(L.R_SHOULDER);
    const swNow = Math.hypot(ls.x - rs.x, ls.y - rs.y);
    if (swNow < 0.02) continue;
    const ctx = { sw: swNow, hipY: (sm.get(L.L_HIP).y + sm.get(L.R_HIP).y) / 2 };
    for (const [hand, wi, ei, si] of [["L", L.L_WRIST, L.L_ELBOW, L.L_SHOULDER], ["R", L.R_WRIST, L.R_ELBOW, L.R_SHOULDER]]) {
      const ev = hands[hand].update(sm.get(wi), sm.get(ei), sm.get(si), ctx, t);
      if (ev) events.push({ t, ...ev });
    }
  }
  return { expected, events };
}

// longest common subsequence on type strings → aligned (TP) count + latencies
function align(expected, got) {
  const n = expected.length, m = got.length;
  const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = 1; i <= n; i++) for (let j = 1; j <= m; j++) {
    dp[i][j] = expected[i - 1].type === got[j - 1].type
      ? dp[i - 1][j - 1] + 1
      : Math.max(dp[i - 1][j], dp[i][j - 1]);
  }
  // backtrack for latencies of matched pairs
  const lats = [];
  let i = n, j = m;
  while (i > 0 && j > 0) {
    if (expected[i - 1].type === got[j - 1].type && dp[i][j] === dp[i - 1][j - 1] + 1) {
      lats.push(got[j - 1].t - expected[i - 1].t);
      i--; j--;
    } else if (dp[i - 1][j] >= dp[i][j - 1]) i--;
    else j--;
  }
  return { tp: dp[n][m], lats };
}

// ---- the suite ----
const COMBO = (speed) => {
  const [o, b, g] = speed === "fast" ? [130, 150, 70] : speed === "slow" ? [260, 320, 350] : [180, 220, 220];
  const P = (hand, punch) => ({ kind: "punch", hand, punch, outMs: o, backMs: b });
  const I = { kind: "idle", ms: g };
  return [
    P("L", "STRAIGHT"), I, P("R", "CROSSING"), I, P("L", "HOOK"), I,
    P("R", "UPPERCUT"), I, P("L", "STRAIGHT"), I, P("R", "CROSSING"), I,
    P("R", "HOOK"), I, P("L", "UPPERCUT"),
  ];
};

export function makeScenarios() {
  let id = 0;
  const scns = [];
  const add = (name, script, opts = {}) => scns.push({ id: id++, name, script, ...opts });

  for (const fps of [30, 60]) {
    add(`combo-medium@${fps}`, COMBO("medium"), { fps });
    add(`combo-fast@${fps}`, COMBO("fast"), { fps, noise: 0.004 });
    add(`combo-slow-sloppy@${fps}`, COMBO("slow"), { fps, actor: { amplitude: 0.85 } });
    add(`combo-noisy@${fps}`, COMBO("medium"), { fps, noise: 0.006 });
    add(`combo-small-far@${fps}`, COMBO("medium"), { fps, actor: { sw: 0.15 } });
    add(`combo-big-close@${fps}`, COMBO("medium"), { fps, actor: { sw: 0.32 } });
    add(`double-jab@${fps}`, [
      { kind: "doublejab", hand: "L" }, { kind: "idle", ms: 400 },
      { kind: "doublejab", hand: "L" },
    ], { fps });
    add(`neg-hang-walk@${fps}`, [
      { kind: "idle", ms: 500 }, { kind: "handsDown", ms: 4000 }, { kind: "idle", ms: 500 },
    ], { fps });
    add(`neg-slow-reach@${fps}`, [
      { kind: "idle", ms: 400 }, { kind: "slowReach", hand: "L" },
      { kind: "idle", ms: 400 }, { kind: "slowReach", hand: "R" },
    ], { fps });
    add(`neg-guard-jitter@${fps}`, [{ kind: "idle", ms: 3000 }], { fps, noise: 0.008 });
  }
  return scns;
}

export function runSuite(seeds) {
  const scns = makeScenarios();
  let tp = 0, fp = 0, fn = 0;
  const lats = [];
  const perScenario = {};
  for (const seed of seeds) {
    for (const scn of scns) {
      const { expected, events } = runScenario(scn, seed);
      const { tp: t, lats: l } = align(expected, events);
      const f = events.length - t, miss = expected.length - t;
      tp += t; fp += f; fn += miss;
      lats.push(...l);
      const k = scn.name;
      perScenario[k] = perScenario[k] || { tp: 0, fp: 0, fn: 0 };
      perScenario[k].tp += t; perScenario[k].fp += f; perScenario[k].fn += miss;
    }
  }
  const meanLat = lats.length ? lats.reduce((a, b) => a + b, 0) / lats.length : 0;
  const f1 = tp ? (2 * tp) / (2 * tp + fp + fn) : 0;
  const reward = tp - 1.25 * fp - fn - Math.min(2, Math.abs(meanLat) / 200) * 0.5 * tp / 10;
  return { reward, f1, tp, fp, fn, meanLat, perScenario };
}

// ---- CLI report ----
if (import.meta.url === `file://${process.argv[1]}`) {
  const res = runSuite([1, 2, 3]);
  console.log(`reward ${res.reward.toFixed(1)}  F1 ${res.f1.toFixed(3)}  TP ${res.tp}  FP ${res.fp}  FN ${res.fn}  meanLat ${res.meanLat.toFixed(0)}ms`);
  const rows = Object.entries(res.perScenario)
    .filter(([, v]) => v.fp || v.fn)
    .map(([k, v]) => `  ${k}: tp=${v.tp} fp=${v.fp} fn=${v.fn}`);
  console.log(rows.length ? "trouble spots:\n" + rows.join("\n") : "all scenarios clean");
}
