#!/usr/bin/env node
// Fails the build when a built page would make the browser contact another host.
//
// It reads every .html and .css file in dist/ and looks at everything a browser loads by itself:
// script, link (stylesheet, preload, preconnect, icon...), img, source, video, audio, iframe,
// embed, object, form actions, srcset, CSS url() and @import, the social card image, and any
// URL inside an inline script. Plain <a> links are not loads, so they are allowed, and so are
// <link rel="me">, <link rel="canonical"> and <link rel="alternate">, which a browser does not fetch.
//
// It also checks that every same-origin file a page loads exists in dist/. Paths served by the
// web server rather than the build are listed in SERVER_PATHS.
//
// Node standard library only. Usage: node scripts/check-hosts.mjs [dist]   (exit 1 on a finding)

import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import path from 'node:path';

// Served by the web server in front of the site, not by the build: the self-hosted Umami tracker.
const SERVER_PATHS = new Set(['/u/m.js']);

const dist = path.resolve(process.argv[2] || 'dist');
const siteUrl = (process.env.ESSENCE_SITE_URL || '').replace(/\/+$/, '');
let ownHost = siteUrl ? new URL(siteUrl).host : '';

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = path.join(dir, name);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else out.push(p);
  }
  return out;
}

const files = walk(dist);
const findings = [];

// The site's own host: from ESSENCE_SITE_URL, else from the canonical link of the home page.
if (!ownHost) {
  const home = readFileSync(path.join(dist, 'index.html'), 'utf8');
  const m = home.match(/<link[^>]+rel="canonical"[^>]+href="([^"]+)"/) || home.match(/<link[^>]+href="([^"]+)"[^>]+rel="canonical"/);
  if (!m) {
    console.error('check-hosts: no canonical link on the home page, and ESSENCE_SITE_URL is not set');
    process.exit(1);
  }
  ownHost = new URL(m[1]).host;
}

function check(file, url, what) {
  url = url.trim();
  if (!url || url.startsWith('data:') || url.startsWith('#') || url.startsWith('about:')) return;
  let u;
  try {
    u = new URL(url, `https://${ownHost}/${path.relative(dist, file)}`);
  } catch {
    findings.push(`${path.relative(dist, file)}: cannot parse ${what} "${url}"`);
    return;
  }
  if (u.host !== ownHost) {
    findings.push(`${path.relative(dist, file)}: ${what} loads from ${u.host} (${url})`);
    return;
  }
  const local = decodeURIComponent(u.pathname);
  if (SERVER_PATHS.has(local)) return;
  const target = path.join(dist, local.endsWith('/') ? `${local}index.html` : local);
  if (!existsSync(target)) findings.push(`${path.relative(dist, file)}: ${what} "${url}" is not in the build`);
}

function cssUrls(file, css, where) {
  for (const m of css.matchAll(/url\(\s*(['"]?)([^'")]+)\1\s*\)/g)) check(file, m[2], `${where} url()`);
  for (const m of css.matchAll(/@import\s+(['"])([^'"]+)\1/g)) check(file, m[2], `${where} @import`);
}

const attr = (tag, name) => {
  const m = tag.match(new RegExp(`\\s${name}\\s*=\\s*("([^"]*)"|'([^']*)'|([^\\s>]+))`, 'i'));
  return m ? (m[2] ?? m[3] ?? m[4] ?? '') : null;
};

for (const file of files) {
  if (file.endsWith('.css')) {
    cssUrls(file, readFileSync(file, 'utf8'), 'stylesheet');
    continue;
  }
  if (!file.endsWith('.html')) continue;
  const html = readFileSync(file, 'utf8');

  for (const m of html.matchAll(/<([a-zA-Z][\w-]*)(\s[^>]*)?>/g)) {
    const name = m[1].toLowerCase();
    const tag = m[0];
    if (name === 'a') continue;
    if (name === 'link') {
      const rel = (attr(tag, 'rel') || '').toLowerCase().split(/\s+/);
      if (rel.some((r) => r === 'me' || r === 'canonical' || r === 'alternate')) continue;
    }
    if (name === 'meta') {
      const prop = attr(tag, 'property') || attr(tag, 'name') || '';
      if (/^(og:image|og:image:url|og:image:secure_url|og:video|og:audio|twitter:image)$/i.test(prop)) {
        check(file, attr(tag, 'content') || '', prop);
      }
      continue;
    }
    for (const a of ['src', 'href', 'poster', 'data', 'action', 'formaction', 'background']) {
      const v = attr(tag, a);
      if (v !== null) check(file, v, `<${name} ${a}>`);
    }
    for (const a of ['srcset', 'imagesrcset']) {
      const v = attr(tag, a);
      if (v) for (const part of v.split(',')) check(file, part.trim().split(/\s+/)[0], `<${name} ${a}>`);
    }
    const style = attr(tag, 'style');
    if (style) cssUrls(file, style, `<${name} style>`);
  }

  for (const m of html.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/gi)) cssUrls(file, m[1], '<style>');
  for (const m of html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/gi)) {
    if (/type\s*=\s*["']?application\/ld\+json/i.test(m[1])) continue;
    for (const u of m[2].matchAll(/(?:https?:)?\/\/[a-z0-9.-]+\.[a-z]{2,}[^\s'"`)]*/gi)) check(file, u[0], 'inline script');
  }
}

const pages = files.filter((f) => f.endsWith('.html')).length;
if (findings.length) {
  console.error(`check-hosts: ${findings.length} finding(s) in ${dist}`);
  for (const f of findings) console.error(`  ${f}`);
  process.exit(1);
}
console.log(`check-hosts: ${pages} page(s), no load from a host other than ${ownHost}, every local file present`);
