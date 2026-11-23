# AGENTS.md

Instructions for AI coding agents working in this repository. Humans should start with `README.md`.

## What this project is

Essence gives a Claude Code agent a memory of who it is and how to work with its person. It is Claude Code hooks and four kinds of markdown files: one portrait (eleven sections), one landscape per area of work (six parts), one stroke per procedure (five parts, plus a tested script, its shortcut), and one brush per ability (eight parts: a login, role, token or tool, and its permissions). A brush is loaded by its pigment (a secret) kept in a cabinet (a password-manager vault); `cabinets.md` lists the cabinets, never their contents. The files live on the owner's machine in `~/.claude/essence/`. Beside them is the studio: a few short night wake-ups with no task, where the agent has time of its own (`docs/studio.md`). This repository holds the hooks, the studio engine, the templates, invented examples, tests and the project website. It was called `session-essence` before. License: AGPL-3.0-or-later.

## Layout

- `hooks/session-start-verify.sh`: SessionStart hook. Checks the checksum, prints section 1, tells the agent to read the whole portrait.
- `hooks/essence-reduce.py`: cuts the unread part of a transcript down to a plain-text slice. Lines are marked PERSON and AGENT.
- `hooks/essence-synthesize.sh`: PreCompact and SessionEnd hook. Lock, reduce, save copies, one `claude -p` run with Read and Edit only, supervisor checks and rollback, checksum. The synthesis prompt is inside this file.
- `hooks/essence-nudge.py`: UserPromptSubmit hook. Reminds the agent to update landscapes when the transcript has grown long since the last compaction.
- `hooks/essence-now.sh`: UserPromptSubmit hook. Prints the current time (`ESSENCE_TZ`, plus UTC) so the agent never estimates it.
- `hooks/essence-check.py`: Stop hook. Reads the finished reply and blocks the turn when it breaks a rule from the private file `~/.claude/essence/checks.json`. The script holds no rules.
- `hooks/essence-brush-rules.py`: PostToolUse hook and command. A landscape that involves a platform must list that platform's brush, and the brush must keep its "Before you use this brush" rule. Rules in the private file `~/.claude/essence/brush-rules.json`. Fails open.
- `hooks/essence-scan.py`: called by the synthesis supervisor. Scans the lines a run added. Exit 1 means a finding.
- `studio/`: the studio engine, a Python 3.12 standard-library package run as `python3 -P -m studio`. `cli.py` (commands), `config.py` (the one JSON config), `wake.py` (the wake-up loop), `model.py` (the tool-less stream-json model run), `wire.py` (system prompt and answer parser), `pulse.py`, `limits.py`, `journal.py`, `schedule.py`, `folder.py`, `types.py`. Senses and sense verbs: `sky.py`, `body.py`, `house.py`, `song.py`, `reading.py`, `channel.py`, `senses.py`. `fetch.py` is the only module that touches the network.
- `docs/setup.md`: the setup guide for a first-time user. Follow it in a clean home folder after a change to the install.
- `install.sh`: the mechanical part of the install. Safe to run twice, backs up what it changes, `--dry-run` and `--uninstall`.
- `docs/studio.md`: what the studio is, its safety shape, every config key, the commands, install and undo.
- `templates/studio-config.json`: every studio key with its default. `examples/studio-config-example.json`: filled in for an invented town. `examples/studio-journal-example.md`: three invented journal entries.
- `tests/test_studio_engine.py`, `tests/test_studio_senses.py`, `tests/fake_claude_stream.py`, `tests/fixtures/studio/`: offline studio tests with a fake `claude` that speaks stream-json. `tests/test_studio_public.py`: the studio files hold nothing personal.
- `templates/portrait.md`, `templates/landscape.md`, `templates/stroke.md`, `templates/brush.md`, `templates/cabinet.md`: empty skeletons.
- `examples/settings-hooks.json`: the hooks block for `~/.claude/settings.json`.
- `examples/brush-rules-example.json`: an invented platform rule for the brush-rules check.
- `examples/checks-example.json`: example rules for the check. A real rules file is private and must never be committed.
- `docs/superego.md`: why a written rule is not enough and how hooks make it hold.
- `examples/portrait-example.md`, `examples/landscape-example.md`, `examples/stroke-example.md`, `examples/brush-example.md`, `examples/cabinet-example.md`: invented, filled-in files (Sara, Max, a home economics class).
- `tests/test_essence.py`: offline tests with a fake `claude` on PATH.
- `docs/history/`: design notes of the retired version 1 and 2. Do not update them.
- `site/`: the Astro website, with its own `package.json`. Plain CSS in `site/src/styles/site.css`, no Tailwind. One component per section in `site/src/components/`. The pigment colours are defined once, in that stylesheet; `site/src/lib/pigments.ts` says which kind of file each pigment marks, and `site/src/lib/rough.ts` draws the painted edges from a seed. Keep a pigment for its kind of file only. `npm run build` writes static files to `site/dist/`.

## Commands

```bash
# Tests (offline, standard library only)
python3 -m unittest discover -s tests -v

# Syntax and lint checks for the hooks
bash -n hooks/essence-synthesize.sh hooks/session-start-verify.sh hooks/essence-now.sh
python3 -m py_compile hooks/essence-reduce.py hooks/essence-nudge.py hooks/essence-check.py hooks/essence-scan.py hooks/essence-brush-rules.py
python3 -m py_compile studio/*.py
shellcheck -S warning hooks/*.sh install.sh

# Site
cd site && npm install && npm run build     # also: npm run dev, npm run preview
```

## Rules for agents

- Ask before large changes. Explain the problem and the proposed fix first. Keep diffs small.
- Keep the hooks runnable with bash, Python 3 standard library, `jq`, `shasum` and `sha256sum`. A new dependency needs a written argument.
- Config is environment variables only. A new variable gets a default in the script and a row in the README settings table. One exception: the studio reads one JSON file (`--config`, else `STUDIO_CONFIG`, else `~/.config/studio/config.json`). A new studio key gets a default in `studio/config.py`, a line in `templates/studio-config.json` and a row in `docs/studio.md`.
- Run the tests and the checks above before you say a change is done. Say plainly what you did not run.
- A change to the supervisor checks, the shape rules or the prompt needs a test.
- Keep the two names as settings (`ESSENCE_PERSON`, `ESSENCE_AGENT`). The prompt uses `@PERSON@`, `@AGENT@`, `@DIR@` and `@SLICE@` placeholders.
- The synthesis agent gets Read and Edit only. Never give it Bash, Write or network tools.
- The studio model run has no tools, ever: no Bash, no Read, no Write, no web, no MCP servers. A verb is a word the script recognises from a fixed list and does in plain Python. A verb only reads, or writes inside the studio folder. Only `studio/fetch.py` touches the network, and only hosts in an allowlist. Reading and the channel stay off by default.
- Studio files are impersonal: "the agent", "the person", "the author". A town appears only as an invented example. `tests/test_studio_public.py` enforces it.
- Prose follows the writing rules in the README: short sentences, active voice, no em dashes, no filler words.
- An agent does not deploy the site. The repository holds no deployment files.
- Commit messages: short, imperative, say what changed. Never rewrite published history. Never delete this repository.

## Traps

- Hooks read their JSON from stdin. Do not switch to environment variables.
- The section 1 check and the heading check depend on the exact form `### N. NAME`. Renaming the headings breaks both, and the session-start hook looks for `### 1. IDENTITY`.
- `essence-synthesize.sh` finds `essence-reduce.py` in its own folder. Install them together.
- `essence-synthesize.sh` uses GNU `stat -c`. It does not run on macOS as it is.
- The session-start hook prints `~/.claude/essence/portrait.md` in its read instruction, even when `ESSENCE_DIR` is set.
- The session-start hook still carries two notes from version 2: a drift-check notice that fires only if `.drift-check-due` exists, and a status note that reads a `last_run` field version 3 no longer writes.
- The site build output (`site/dist/`) is not committed.

## Never commit or make public

- A real portrait or a real landscape. Examples must be invented.
- Session transcripts, slices, synthesis logs or saved copies from `~/.claude/essence/`.
- Secrets: API keys, tokens, passwords, `.env` files. A brush or cabinet file, real or example, names the cabinet and the drawer (item name) and never holds a pigment (the secret value).
- Real names other than the owner credit, host names, IP addresses, user names, home-directory paths, employer, client or colleague details. This is a public repository.
