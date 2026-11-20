# AGENTS.md

Instructions for AI coding agents working in this repository. Humans should start with `README.md`.

## What this project is

Essence gives a Claude Code agent a memory of who it is and how to work with its person. It is Claude Code hooks and four kinds of markdown files: one portrait (eleven sections), one landscape per area of work (six parts), one stroke per procedure (five parts, plus a tested script, its shortcut), and one brush per ability (eight parts: a login, role, token or tool, and its permissions). A brush is loaded by its pigment (a secret) kept in a cabinet (a password-manager vault); `cabinets.md` lists the cabinets, never their contents. The files live on the owner's machine in `~/.claude/essence/`. This repository holds the hooks, the templates, invented examples, tests and the project website. It was called `session-essence` before. License: AGPL-3.0-or-later.

## Layout

- `hooks/session-start-verify.sh`: SessionStart hook. Checks the checksum, prints section 1, tells the agent to read the whole portrait.
- `hooks/essence-reduce.py`: cuts the unread part of a transcript down to a plain-text slice. Lines are marked PERSON and AGENT.
- `hooks/essence-synthesize.sh`: PreCompact and SessionEnd hook. Lock, reduce, save copies, one `claude -p` run with Read and Edit only, supervisor checks and rollback, checksum. The synthesis prompt is inside this file.
- `hooks/essence-nudge.py`: UserPromptSubmit hook. Reminds the agent to update landscapes when the transcript has grown long since the last compaction.
- `hooks/essence-now.sh`: UserPromptSubmit hook. Prints the current time (`ESSENCE_TZ`, plus UTC) so the agent never estimates it.
- `hooks/essence-check.py`: Stop hook. Reads the finished reply and blocks the turn when it breaks a rule from the private file `~/.claude/essence/checks.json`. The script holds no rules.
- `hooks/essence-scan.py`: called by the synthesis supervisor. Scans the lines a run added. Exit 1 means a finding.
- `templates/portrait.md`, `templates/landscape.md`, `templates/stroke.md`, `templates/brush.md`, `templates/cabinet.md`: empty skeletons.
- `examples/settings-hooks.json`: the hooks block for `~/.claude/settings.json`.
- `examples/checks-example.json`: example rules for the check. A real rules file is private and must never be committed.
- `docs/superego.md`: why a written rule is not enough and how hooks make it hold.
- `examples/portrait-example.md`, `examples/landscape-example.md`, `examples/stroke-example.md`, `examples/brush-example.md`, `examples/cabinet-example.md`: invented, filled-in files (Sara, Max, a home economics class).
- `tests/test_essence.py`: offline tests with a fake `claude` on PATH.
- `docs/history/`: design notes of the retired version 1 and 2. Do not update them.
- `site/`: the Astro + Tailwind website, with its own `package.json`, Dockerfile, nginx config and deploy files.

## Commands

```bash
# Tests (offline, standard library only)
python3 -m unittest discover -s tests -v

# Syntax and lint checks for the hooks
bash -n hooks/essence-synthesize.sh hooks/session-start-verify.sh hooks/essence-now.sh
python3 -m py_compile hooks/essence-reduce.py hooks/essence-nudge.py hooks/essence-check.py hooks/essence-scan.py
shellcheck -S warning hooks/*.sh

# Site
cd site && npm install && npm run build     # also: npm run dev, npm run preview
```

## Rules for agents

- Ask before large changes. Explain the problem and the proposed fix first. Keep diffs small.
- Keep the hooks runnable with bash, Python 3 standard library, `jq`, `shasum` and `sha256sum`. A new dependency needs a written argument.
- Config is environment variables only. A new variable gets a default in the script and a row in the README settings table.
- Run the tests and the checks above before you say a change is done. Say plainly what you did not run.
- A change to the supervisor checks, the shape rules or the prompt needs a test.
- Keep the two names as settings (`ESSENCE_PERSON`, `ESSENCE_AGENT`). The prompt uses `@PERSON@`, `@AGENT@`, `@DIR@` and `@SLICE@` placeholders.
- The synthesis agent gets Read and Edit only. Never give it Bash, Write or network tools.
- Prose follows the writing rules in the README: short sentences, active voice, no em dashes, no filler words.
- Do not change deployment files (`site/Dockerfile`, `site/deploy.sh`, `site/k8s/`, `site/nginx.conf`) unless that is the task. An agent does not deploy.
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
