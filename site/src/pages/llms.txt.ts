// llms.txt in the llmstxt.org format: an H1, one blockquote summary, then sections of links.
// The Markdown copies it links to are written from the built HTML (scripts/markdown.mjs).
import type { APIRoute } from 'astro';
import { abs, repoUrl, version, updated, license, installLine, privacy } from '../lib/project';

export const GET: APIRoute = () => {
  const optional = [
    `- [Changelog](${repoUrl}/blob/main/CHANGELOG.md): every change, newest first`,
    `- [Licence](${license.url}): ${license.name}`,
    `- [Releases feed](${abs('/feed.xml')}): RSS, one item per released version`,
  ];
  if (privacy.mode === 'live') optional.unshift(`- [Privacy](${abs('/privacy/index.md')}): what this site collects`);
  const body = `# Essence

> Essence gives a Claude Code agent a memory of who it is and how to work with its person. It is a set of Claude Code hooks and markdown files that live on the person's own machine. Version ${version}, ${license.name}, last updated ${updated}.

Install from the repository: \`${installLine}\`. The setup guide explains each step and how to undo it.

## Docs

- [Essence, the whole page as Markdown](${abs('/index.md')}): what it is, how a session starts, synthesis, the studio, the sketchbook, limits
- [README](${repoUrl}/blob/main/README.md): the reference, with install and settings
- [Setup guide](${repoUrl}/blob/main/docs/setup.md): from nothing to a working install, with checks and undo
- [AGENTS.md](${repoUrl}/blob/main/AGENTS.md): instructions for coding agents working in the repository

## Source

- [Repository](${repoUrl}): hooks, templates, invented examples, tests and this website

## Optional

${optional.join('\n')}
`;
  return new Response(body, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
};
