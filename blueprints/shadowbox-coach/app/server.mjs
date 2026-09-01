// Static server + recording sink. Run: node server.mjs [port]
// POST /save writes labeled landmark recordings into recordings/ so real
// punches become replayable test data (see replay.mjs).
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const REC_DIR = path.join(ROOT, "recordings");
const PORT = Number(process.argv[2] || 4790);
const MIME = {
  ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript",
  ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml",
};

http.createServer((req, res) => {
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
}).listen(PORT, () => console.log(`shadowbox coach on http://localhost:${PORT}`));
