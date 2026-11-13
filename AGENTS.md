# AGENTS.md

Instructions for AI coding agents working in this repository. Humans should start with `README.md`.

## What this project is

Session Essence is an MCP (Model Context Protocol) server that turns logged interactions into a "portrait": a second-person narrative ("You are...") that an AI assistant reads at session start so it continues rather than starts over. It is a Node.js ESM project (Node 20+), runs over stdio by default, or over HTTP inside Docker through supergateway. Synthesis uses the Claude API by default or a local Ollama model (`SYNTHESIS_BACKEND=ollama`). The repo is public and active: current version 2.1.1 (see `CHANGELOG.md`), license AGPL-3.0-or-later. It also holds a small Astro marketing site in `site/`.

Read `docs/design.md` before changing synthesis logic, prompts or portrait structure. Those changes have an outsized effect and should not be made on instinct.

## Layout

- `index.js`: the whole MCP server. Three tools (`synthesize_essence`, `format_observation`, `analyze_portrait`), the two-backend chat dispatcher, stdio transport. One file by design.
- `prompts.template.js`: committed prompt template (PSYCHOLOGIST, SOCIOLOGIST, MERGE, COMPARE) with a placeholder name. Prompt changes go here.
- `prompts.js`: gitignored, personal copy of the template with the operator's name. Never commit it.
- `examples/`: reference hook scripts the operator installs by hand: `synthesize-essence.sh` (PreCompact surgical edit), `session-start-verify.sh` (SessionStart integrity check), `drift-check.sh` (manual drift audit).
- `docs/design.md`: the reasons behind the architecture, plus the threat model.
- `Dockerfile`: wraps the stdio server in supergateway for HTTP. Builds `prompts.js` from the template; operators mount their own read-only.
- `site/`: Astro + Tailwind landing page, its own `package.json`, Dockerfile, nginx config, k8s manifests and `deploy.sh`.
- `.tribunal/`: records of a past multi-agent audit. The finding ids (F-SEC-004 and so on) are referenced in `CHANGELOG.md` and code comments. Do not edit.

## Commands

```bash
# Install (no build step: plain ESM, no transpile)
npm install

# Required before first run: prompts.js is gitignored
cp prompts.template.js prompts.js

# Run the MCP server over stdio
npm start            # same as: node index.js

# Syntax check (verified; this is the only check that exists)
node --check index.js && node --check prompts.template.js

# HTTP via Docker, bound to localhost (from README)
docker build -t session-essence .
docker run -d --name session-essence -p 127.0.0.1:3250:3250 \
  --add-host=host.docker.internal:host-gateway \
  -e ANTHROPIC_API_KEY=... -e PORT=3250 \
  -v "$(pwd)/prompts.js:/app/prompts.js:ro" session-essence

# Site
cd site && npm install && npm run dev     # also: npm run build, npm run preview
```

There is no test suite, no linter and no type check. `npm test` is not configured. If you want to add tests, propose the framework to the owner first; do not add a test harness unannounced. Not verified here: `npm install`, the Docker build and the site build.

## Deployment

The MCP server is not deployed from this repo. Operators run it themselves (stdio or the Docker recipe above). The owner also runs it as a container in a homelab; changes to Docker build behavior, port binding or HTTP semantics land there first, so call them out in the PR description.

The site is deployed by the owner with `site/deploy.sh` to the homelab Kubernetes cluster behind a reverse proxy. Agents do not run it.

## Rules for agents

- Ask before large changes. Explain the problem and the proposed fix first. Keep diffs small and surgical.
- Never commit secrets: API keys, tokens, passwords, `.env` files. Secrets live in a password manager and are read at run time through env vars.
- Never delete this repository or rewrite published history.
- Do not change deployment, CI or infrastructure files (`Dockerfile`, `site/Dockerfile`, `site/deploy.sh`, `site/k8s/`, `site/nginx.conf`) unless that is the task.
- An agent does not deploy. A change to a running system is a reviewed script the owner runs.
- Before saying a change is done, run `node --check` on changed JS files and say plainly what was not run (there are no tests).
- Commit messages: short, imperative, say what changed.
- ESM only: `import`/`export`, never `require`.
- MCP tool input schemas use zod `z.object({...})`. Match the existing pattern.
- Config is env vars only, no config files. A new env var gets a default in `index.js` and a row in the README environment table.
- The server is stateless: `index.js` does no file I/O. The calling assistant reads observations and writes the portrait. Do not add `fs` calls to `index.js`; re-read `docs/design.md` "Why stateless" if tempted.
- Keep `index.js` as one file. Do not split it into modules without a real reason.
- Keep the three existing tools' names and schemas stable. New tools are fine; renames or schema changes need owner approval.
- Dependencies are kept to a minimum (`@anthropic-ai/sdk`, `@modelcontextprotocol/sdk`, `supergateway`, `zod`). A new dependency needs a written argument.

## Traps

- `prompts.js` must exist before `index.js` will start (it imports from it). Copy the template; in CI generate it the same way the Dockerfile does.
- Hooks read JSON from stdin (`INPUT=$(cat); echo "$INPUT" | jq ...`). The old `$CLAUDE_USER_PROMPT` env-var style is dead in current Claude Code and silently produces empty observations. Do not "simplify" back to it.
- The two synthesis paths differ on purpose. The MCP `synthesize_essence` tool regenerates a 6-section portrait in three passes. `examples/synthesize-essence.sh` makes a surgical edit with a detached `claude -p` and grows sections 7 to 9 (Episodes, Voice, Decisions). They are not redundant; see `docs/design.md` "Why surgical edits, not regeneration".
- Minimum-observation guards live in code, not in the zod schema: `index.js` needs 10 observations, the PreCompact script needs 15. They check runtime state, not input shape.
- `@anthropic-ai/sdk` is a hard dependency even for Ollama-only use. Removing it needs a dynamic import; left for later.
- The portrait integrity sidecar (`portrait.md.sha256`) and drift-check files are written by the example scripts. Changing the portrait write path means updating the sidecar logic too.
- The repo may be symlinked into a larger local MCP server stack. Do not add hard-coded absolute paths that assume a directory layout.

## Never commit or make public

- `prompts.js` or any file containing the operator's real name.
- API keys, tokens, `.env` files, the bearer token used by a reverse proxy.
- Portrait files, observation logs (`observations.jsonl`), archives or drift reports. They contain private conversation content.
- New internal hostnames, IP addresses, machine usernames or home-directory paths. This is a public repo; describe infrastructure generically.
