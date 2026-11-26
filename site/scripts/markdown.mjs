#!/usr/bin/env node
// Writes a Markdown copy next to every built page: dist/index.html -> dist/index.md,
// dist/privacy/index.html -> dist/privacy/index.md. It reads the built HTML, so the copy is made
// from the same source as the page and cannot drift from it. Each page links its copy with
// <link rel="alternate" type="text/markdown">.
//
// Only the <main> element is converted. Decorative parts are left out: SVG drawings, anything
// marked aria-hidden="true", hidden elements, buttons, scripts and styles.
// Node standard library only. Usage: node scripts/markdown.mjs [dist]

import { readFileSync, writeFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';

const VOID = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr']);
const SKIP = new Set(['svg', 'script', 'style', 'button', 'noscript', 'template', 'head']);
const BLOCK = new Set([
  'address', 'article', 'aside', 'blockquote', 'dd', 'div', 'dl', 'dt', 'figcaption', 'figure', 'footer', 'h1', 'h2',
  'h3', 'h4', 'h5', 'h6', 'header', 'li', 'main', 'nav', 'ol', 'p', 'pre', 'section', 'table', 'ul', 'tr', 'thead', 'tbody',
]);

const ENT = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', mdash: '—', ndash: '–', hellip: '…', middot: '·', rarr: '→', larr: '←', darr: '↓', uarr: '↑', rsquo: '’', lsquo: '‘', ldquo: '“', rdquo: '”', times: '×', copy: '©' };
function decode(s) {
  return s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) => {
    if (e[0] === '#') {
      const n = e[1] === 'x' || e[1] === 'X' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      return n === 0x2011 ? '-' : String.fromCodePoint(n);
    }
    return ENT[e.toLowerCase()] ?? m;
  });
}

// ---------- a small HTML tree builder ----------

function parse(html) {
  const root = { tag: '#root', attrs: {}, children: [] };
  const stack = [root];
  const re = /<!--[\s\S]*?-->|<!doctype[^>]*>|<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:\s+[^\s"'>\/=]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?)*)\s*(\/?)>|([^<]+)|</g;
  let m;
  while ((m = re.exec(html))) {
    const top = stack[stack.length - 1];
    if (m[1]) {
      const tag = m[1].toLowerCase();
      for (let i = stack.length - 1; i > 0; i--) {
        if (stack[i].tag === tag) {
          stack.length = i;
          break;
        }
      }
    } else if (m[2]) {
      const tag = m[2].toLowerCase();
      const attrs = {};
      const ar = /([^\s"'>\/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g;
      let a;
      while ((a = ar.exec(m[3] || ''))) attrs[a[1].toLowerCase()] = decode(a[2] ?? a[3] ?? a[4] ?? '');
      const node = { tag, attrs, children: [] };
      top.children.push(node);
      if (!VOID.has(tag) && !m[4]) {
        stack.push(node);
        if (tag === 'script' || tag === 'style') {
          const end = html.indexOf(`</${tag}`, re.lastIndex);
          re.lastIndex = end < 0 ? html.length : end;
        }
      }
    } else if (m[5] !== undefined) {
      top.children.push({ text: decode(m[5]) });
    } else if (m[0] === '<') {
      top.children.push({ text: '<' });
    }
  }
  return root;
}

function find(node, tag) {
  if (node.tag === tag) return node;
  for (const c of node.children || []) {
    const f = find(c, tag);
    if (f) return f;
  }
  return null;
}

function findAll(node, pred, out = []) {
  if (pred(node)) out.push(node);
  for (const c of node.children || []) findAll(c, pred, out);
  return out;
}

// ---------- tree to Markdown ----------

const skipped = (n) =>
  SKIP.has(n.tag) || n.attrs?.['aria-hidden'] === 'true' || 'hidden' in (n.attrs || {}) || /\bskip\b/.test(n.attrs?.class || '');

function inline(node) {
  if (node.text !== undefined) return node.text.replace(/\s+/g, ' ');
  if (skipped(node)) return '';
  const inner = () => node.children.map(inline).join('');
  switch (node.tag) {
    case 'br':
      return '  \n';
    case 'b':
    case 'strong': {
      const t = inner().trim();
      return t ? `**${t}**` : '';
    }
    case 'i':
    case 'em': {
      const t = inner().trim();
      return t ? `_${t}_` : '';
    }
    case 'code': {
      const t = inner();
      return t.includes('`') ? `\`\` ${t} \`\`` : `\`${t}\``;
    }
    case 'a': {
      const t = inner().trim();
      const href = node.attrs.href || '';
      if (!t) return '';
      if (!href || href.startsWith('#')) return t;
      return `[${t}](${href})`;
    }
    case 'img':
      return node.attrs.alt || '';
    default:
      if (BLOCK.has(node.tag)) return ` ${block(node).trim()} `;
      return inner();
  }
}

function clean(s) {
  return s.replace(/[ \t]+/g, ' ').replace(/ *\n */g, '\n').trim();
}

function hasBlockChild(node) {
  return (node.children || []).some((c) => c.tag && BLOCK.has(c.tag) && !skipped(c));
}

function blocks(children, ctx) {
  const out = [];
  let run = [];
  const flush = () => {
    const t = clean(run.map(inline).join(''));
    if (t) out.push(t);
    run = [];
  };
  for (const c of children) {
    if (c.tag && BLOCK.has(c.tag)) {
      flush();
      if (skipped(c)) continue;
      const b = block(c, ctx);
      if (b.trim()) out.push(b.replace(/^\n+|\n+$/g, ''));
    } else if (!(c.tag && skipped(c))) {
      run.push(c);
    }
  }
  flush();
  return out.join('\n\n');
}

function list(node, ordered, ctx) {
  const depth = (ctx?.depth || 0) + 1;
  let n = 0;
  return node.children
    .filter((c) => c.tag === 'li' && !skipped(c))
    .map((li) => {
      n += 1;
      const mark = ordered ? `${n}. ` : '- ';
      const body = blocks(li.children, { depth });
      const pad = ' '.repeat(mark.length);
      return mark + body.split('\n').map((l, i) => (i === 0 || !l ? l : pad + l)).join('\n').replace(/\n\n+/g, '\n');
    })
    .join('\n');
}

function table(node) {
  const rows = findAll(node, (n) => n.tag === 'tr').map((tr) =>
    tr.children.filter((c) => c.tag === 'th' || c.tag === 'td').map((c) => clean(c.children.map(inline).join('')).replace(/\|/g, '\\|')),
  );
  if (!rows.length) return '';
  const width = Math.max(...rows.map((r) => r.length));
  const line = (r) => `| ${Array.from({ length: width }, (_, i) => r[i] || '').join(' | ')} |`;
  return [line(rows[0]), line(rows[0].map(() => '---')), ...rows.slice(1).map(line)].join('\n');
}

function block(node, ctx) {
  if (skipped(node)) return '';
  const t = node.tag;
  if (/^h[1-6]$/.test(t)) return `${'#'.repeat(Number(t[1]))} ${clean(node.children.map(inline).join(''))}`;
  if (t === 'p' || t === 'dt' || t === 'figcaption') {
    const s = clean(node.children.map(inline).join(''));
    if (!s) return '';
    if (t === 'dt') return `**${s}**`;
    if (t === 'figcaption') return `_${s}_`;
    return s;
  }
  if (t === 'ul' || t === 'ol') return list(node, t === 'ol', ctx);
  if (t === 'pre') return '```\n' + node.children.map((c) => (c.text !== undefined ? c.text : textOf(c))).join('').replace(/\n+$/, '') + '\n```';
  if (t === 'blockquote') return blocks(node.children, ctx).split('\n').map((l) => (l ? `> ${l}` : '>')).join('\n');
  if (t === 'table') return table(node);
  if (t === 'li') return blocks(node.children, ctx);
  if (!hasBlockChild(node)) return clean(node.children.map(inline).join(''));
  return blocks(node.children, ctx);
}

function textOf(node) {
  if (node.text !== undefined) return node.text;
  if (skipped(node)) return '';
  return (node.children || []).map(textOf).join('');
}

export function htmlToMarkdown(html) {
  const tree = parse(html);
  const head = find(tree, 'head');
  const title = head ? textOf(find(head, 'title') || { children: [] }).trim() : '';
  const metas = head ? findAll(head, (n) => n.tag === 'meta') : [];
  const links = head ? findAll(head, (n) => n.tag === 'link') : [];
  const description = metas.find((m) => m.attrs.name === 'description')?.attrs.content || '';
  const canonical = links.find((l) => l.attrs.rel === 'canonical')?.attrs.href || '';
  const main = find(tree, 'main');
  if (!main) throw new Error('no <main> element');
  const lines = [`<!-- ${title}. Markdown copy of ${canonical}, made from the HTML at build time. -->`, ''];
  if (description) lines.push(`> ${description}`, '');
  lines.push(blocks(main.children).replace(/\n{3,}/g, '\n\n'));
  return lines.join('\n').trimEnd() + '\n';
}

function pages(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = path.join(dir, name);
    if (statSync(p).isDirectory()) out.push(...pages(p));
    else if (name === 'index.html') out.push(p);
  }
  return out;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const dist = path.resolve(process.argv[2] || 'dist');
  for (const file of pages(dist)) {
    const md = htmlToMarkdown(readFileSync(file, 'utf8'));
    const target = file.replace(/\.html$/, '.md');
    writeFileSync(target, md);
    console.log(`markdown: ${path.relative(dist, target)} (${md.length} bytes)`);
  }
}
