// Pose inference off the main thread: MediaPipe runs here so HUD work and
// animations on the main thread can never delay a detection frame.
const MP = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14";
let landmarker = null;

self.onmessage = async (e) => {
  const msg = e.data;
  if (msg.type === "init") {
    try {
      const { PoseLandmarker, FilesetResolver } = await import(MP);
      const vision = await FilesetResolver.forVisionTasks(`${MP}/wasm`);
      landmarker = await PoseLandmarker.createFromOptions(vision, {
        baseOptions: { modelAssetPath: msg.modelPath, delegate: "GPU" },
        runningMode: "VIDEO",
        numPoses: 1,
      });
      postMessage({ type: "ready" });
    } catch (err) {
      postMessage({ type: "init-error", message: String(err?.message || err) });
    }
    return;
  }
  if (msg.type === "frame" && landmarker) {
    const t0 = performance.now();
    let landmarks = null;
    try {
      const result = landmarker.detectForVideo(msg.bitmap, msg.t);
      landmarks = result.landmarks?.[0] ?? null;
    } finally {
      msg.bitmap.close();
    }
    postMessage({ type: "landmarks", t: msg.t, landmarks, inferMs: performance.now() - t0 });
  }
};
