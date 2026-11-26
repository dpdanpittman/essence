#!/usr/bin/env node
// Draws the social card, public/og.png (1200 x 630), from the built page: the masthead, the title
// and the pigment key, in the site's own stylesheet and fonts. Run it after `npm run build`, by hand,
// when the first screen changes. It needs a Chromium or Chrome on PATH (CHROME=/path/to/chrome).
// The PNG is committed, so a normal build does not need a browser.

import http from 'node:http';
import { readFileSync, existsSync } from 'node:fs';
import { execFile } from 'node:child_process';
import path from 'node:path';

const dist = path.resolve('dist');
const out = path.resolve('public/og.png');
const home = readFileSync(path.join(dist, 'index.html'), 'utf8');
const css = home.match(/<link rel="stylesheet" href="([^"]+)"/)?.[1];
const defs = home.match(/<svg class="defs"[\s\S]*?<\/svg>/)?.[0];
const key = home.match(/<ul class="key"[\s\S]*?<\/ul>/)?.[0];
if (!css || !defs || !key) throw new Error('og-image: build the site first (npm run build)');

const card = `<!doctype html><html lang="en"><head><meta charset="utf-8"><link rel="stylesheet" href="${css}">
<style>
  html { font-size: 20px; } body { margin: 0; width: 1200px; height: 630px; overflow: hidden; }
  .card { box-sizing: border-box; width: 1200px; height: 630px; padding: 56px 72px; display: flex; flex-direction: column; }
  .card .mast { margin-bottom: 40px; font-size: 1.6rem; }
  .card h1 { font-size: 5.2rem; line-height: 0.98; letter-spacing: -0.02em; max-width: 11em; margin: 0 0 auto; }
  .card .key { margin: 0; grid-template-columns: repeat(4, minmax(0, 1fr)); font-size: 1rem; }
  .card .key .swatch { width: 100%; height: auto; }
</style></head><body>${defs}<div class="card"><p class="mast">Essence</p><h1>An AI that remembers who it is.</h1>${key}</div></body></html>`;

const types = { '.css': 'text/css', '.woff2': 'font/woff2', '.html': 'text/html' };
const server = http.createServer((req, res) => {
  const url = decodeURIComponent(req.url.split('?')[0]);
  if (url === '/__og.html') return res.end(card);
  const file = path.join(dist, path.normalize(url));
  if (!file.startsWith(dist) || !existsSync(file)) return res.writeHead(404).end();
  res.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream' });
  res.end(readFileSync(file));
});

server.listen(0, '127.0.0.1', () => {
  const { port } = server.address();
  const chrome = process.env.CHROME || 'chromium';
  // Async, so this process keeps serving the page while the browser loads it.
  execFile(chrome, [
    '--headless', '--disable-gpu', '--hide-scrollbars', '--force-device-scale-factor=1',
    '--window-size=1200,630', '--virtual-time-budget=3000', `--screenshot=${out}`,
    `http://127.0.0.1:${port}/__og.html`,
  ], { timeout: 60000 }, (err) => {
    server.close();
    if (err) {
      console.error(`og-image: ${chrome} failed: ${err.message}`);
      process.exit(1);
    }
    console.log(`og-image: wrote ${path.relative(process.cwd(), out)}`);
  });
});
