import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const RUNS_DIR = process.env.RUNS_DIR || '/data/runs';
const DIST = path.join(__dirname, 'dist');

const MIME = {
  '.html': 'text/html',
  '.js': 'application/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
};

const server = http.createServer((req, res) => {
  const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);

  // ── API: list runs ─────────────────────────────────────────
  if (url.pathname === '/api/runs/') {
    fs.readdir(RUNS_DIR, { withFileTypes: true }, (err, entries) => {
      if (err) {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end('[]');
        return;
      }
      const dirs = entries.filter((e) => e.isDirectory()).map((e) => e.name);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(dirs));
    });
    return;
  }

  // ── API: load gini_timeseries.json for a run ───────────────
  const match = url.pathname.match(/^\/api\/runs\/([^/]+)\/gini_timeseries\.json$/);
  if (match) {
    const runId = match[1];
    const file = path.resolve(RUNS_DIR, runId, 'gini_timeseries.json');
    if (!file.startsWith(path.resolve(RUNS_DIR))) {
      res.writeHead(403);
      res.end('Forbidden');
      return;
    }
    fs.readFile(file, (err, data) => {
      if (err) {
        res.writeHead(404, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'not found' }));
        return;
      }
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(data);
    });
    return;
  }

  // ── serve static files ─────────────────────────────────────
  let filePath = path.join(DIST, url.pathname === '/' ? 'index.html' : url.pathname);
  fs.readFile(filePath, (err, data) => {
    if (err) {
      // SPA fallback: serve index.html
      fs.readFile(path.join(DIST, 'index.html'), (_e2, d2) => {
        if (_e2) {
          res.writeHead(404);
          res.end('Not found');
          return;
        }
        res.writeHead(200, { 'Content-Type': 'text/html' });
        res.end(d2);
      });
      return;
    }
    const ext = path.extname(filePath).toLowerCase();
    res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' });
    res.end(data);
  });
});

server.listen(80, () => {
  console.log(`[ui] http://0.0.0.0:80  RUNS_DIR=${RUNS_DIR}`);
});
