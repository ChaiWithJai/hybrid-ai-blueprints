// Static server + recording sink + training log + coach proxy.
//   node server.mjs [port]
// Serves http://localhost:<port> and, when openssl is available,
// https://<lan-ip>:<port+1> for phones (getUserMedia needs a secure context
// off localhost; accept the self-signed cert once on the phone).
// /coach/* proxies LM Studio (localhost:1234) so the browser talks same-origin
// — no CORS setup, and it works from a phone where localhost isn't the Mac.
import http from "node:http";
import https from "node:https";
import os from "node:os";
import fs from "node:fs";
import path from "node:path";
import { execSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const REC_DIR = path.join(ROOT, "recordings");
const PORT = Number(process.argv[2] || 4790);
const LMSTUDIO = "http://127.0.0.1:1234/v1";
const MIME = {
  ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript",
  ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml",
};

const LOG_PATH = path.join(ROOT, "..", "pipeline", "datasets", "training_log.jsonl");

async function proxyCoach(req, res) {
  try {
    if (req.method === "GET" && req.url === "/coach/models") {
      const r = await fetch(`${LMSTUDIO}/models`, { signal: AbortSignal.timeout(2000) });
      res.writeHead(r.status, { "Content-Type": "application/json" });
      res.end(await r.text());
      return true;
    }
    if (req.method === "POST" && req.url === "/coach/chat") {
      let body = "";
      req.on("data", (c) => { body += c; if (body.length > 1e6) req.destroy(); });
      await new Promise((ok) => req.on("end", ok));
      const r = await fetch(`${LMSTUDIO}/chat/completions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        signal: AbortSignal.timeout(45000),
      });
      res.writeHead(r.status, { "Content-Type": "application/json" });
      res.end(await r.text());
      return true;
    }
  } catch (e) {
    res.writeHead(502, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: `LM Studio unreachable: ${e.message}` }));
    return true;
  }
  return false;
}

const handler = (req, res) => {
  if (req.url.startsWith("/coach/")) { proxyCoach(req, res); return; }
  if (req.method === "POST" && req.url === "/log") {
    // training + feedback events → the JSONL dataset that the error-discovery
    // skill reviews and pipeline/ingest_training_log.py pushes to MLflow
    let body = "";
    req.on("data", (c) => { body += c; if (body.length > 1e6) req.destroy(); });
    req.on("end", () => {
      try {
        const entry = JSON.parse(body);
        fs.mkdirSync(path.dirname(LOG_PATH), { recursive: true });
        fs.appendFileSync(LOG_PATH, JSON.stringify(entry) + "\n");
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ok: true }));
        console.log(`log: ${entry.type} (${entry.dayKey ?? entry.actual ?? ""})`);
      } catch (e) {
        res.writeHead(400);
        res.end(JSON.stringify({ error: e.message }));
      }
    });
    return;
  }
  if (req.method === "POST" && req.url === "/save") {
    let body = "";
    req.on("data", (c) => { body += c; if (body.length > 50e6) req.destroy(); });
    req.on("end", () => {
      try {
        const rec = JSON.parse(body);
        const label = String(rec.label || "unlabeled").toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40);
        fs.mkdirSync(REC_DIR, { recursive: true });
        const file = `${new Date().toISOString().replace(/[:.]/g, "-")}-${label}.json`;
        fs.writeFileSync(path.join(REC_DIR, file), JSON.stringify(rec));
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ file: `recordings/${file}` }));
        console.log(`saved ${file} (${rec.frames?.length ?? 0} frames, label: ${rec.label})`);
      } catch (e) {
        res.writeHead(400);
        res.end(JSON.stringify({ error: e.message }));
      }
    });
    return;
  }
  const url = new URL(req.url, "http://x").pathname;
  const file = path.join(ROOT, url === "/" ? "index.html" : url);
  if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    res.writeHead(404);
    res.end("not found");
    return;
  }
  res.writeHead(200, { "Content-Type": MIME[path.extname(file)] || "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
};

http.createServer(handler).listen(PORT, "0.0.0.0", () =>
  console.log(`shadowbox coach on http://localhost:${PORT}`));

// HTTPS for phones: self-signed cert, generated once with openssl
function lanIPs() {
  return Object.values(os.networkInterfaces()).flat()
    .filter((i) => i && i.family === "IPv4" && !i.internal)
    .map((i) => i.address);
}
try {
  const certDir = path.join(ROOT, ".certs");
  const keyPath = path.join(certDir, "key.pem"), certPath = path.join(certDir, "cert.pem");
  if (!fs.existsSync(keyPath) || !fs.existsSync(certPath)) {
    fs.mkdirSync(certDir, { recursive: true });
    execSync(`openssl req -x509 -newkey rsa:2048 -keyout "${keyPath}" -out "${certPath}" -days 825 -nodes -subj "/CN=shadowbox-coach"`, { stdio: "ignore" });
  }
  https.createServer({ key: fs.readFileSync(keyPath), cert: fs.readFileSync(certPath) }, handler)
    .listen(PORT + 1, "0.0.0.0", () => {
      for (const ip of lanIPs()) console.log(`phone → https://${ip}:${PORT + 1}  (accept the self-signed cert once)`);
    });
} catch (e) {
  console.log(`https disabled (${e.message}) — phone camera needs https; install openssl to enable`);
}
