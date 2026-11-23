# Set up Essence

This guide takes you from nothing to a working Essence install in one evening. It is written for an engineer who uses Claude Code and has never seen this project. Follow it from the top. Every command runs in a terminal on the machine where you run Claude Code.

There are two ways through the install. `./install.sh` does the mechanical part in one command, and is safe to run twice. The numbered manual steps do the same thing by hand. Read the manual steps either way: they say what each part is for.

## What you get at the end, and what it costs

### What you get

- A portrait at `~/.claude/essence/portrait.md`. At every session start and after every compaction, a hook prints its first section and tells your agent to read the whole file before its first reply.
- A synthesis step. When a session compacts or ends, a script cuts the new part of the transcript down to plain text and starts one `claude -p` run. That run makes small edits to the portrait and the landscapes. A supervisor checks the result and puts the old copy back if the run broke the file.
- A time line on every prompt (`[Now: ...]`), so your agent reads the time instead of guessing it.
- A nudge when a conversation grows long: a reminder to write down what it learned before the context is compacted.
- A check on every finished reply. If the reply breaks a rule in `~/.claude/essence/checks.json`, the turn is blocked once and your agent is told the rule.
- Optional: landscapes, strokes, brushes and a list of cabinets (the four kinds of files in the README), and the brush-rules check.

### What it costs

- **Tokens at every session start.** Your agent reads the whole portrait into its context at every start and after every compaction. The template is 4373 bytes. A portrait grows over months, up to the hard cap of 160000 bytes (`ESSENCE_PORTRAIT_MAX`). A rough rule for English text is 4 bytes per token, so that is about 1,100 tokens for the template and about 40,000 tokens at the cap. This is an estimate. It was not measured.
- **Tokens on every prompt.** The time line is about 25 tokens. The nudge adds about 100 tokens, and only when a conversation has grown past 6 MB, then every 3 MB.
- **A model run at every compaction and every session end.** The synthesis runs `claude -p` with the model `opus` (setting `ESSENCE_MODEL`). It runs only when the new part of the transcript holds at least 3 messages from you (`ESSENCE_MIN_MESSAGES`). Its input is bounded by the code: the transcript slice is at most 600000 bytes, the portrait at most 160000 bytes, and each landscape it opens at most 30000 bytes. It uses several turns with Read and Edit, so it reads some of that more than once. Its token use and its price were not measured. It is billed to the account your `claude` command logs in with.
- **No model for the checks.** The Stop check, the nudge, the time line and the brush-rules check are local scripts. They use no model and no network.
- **Disk.** Each synthesis that changes the portrait keeps two copies of it in `~/.claude/essence/portraits/`. Nothing deletes them. At the cap, that is up to 320 KB per run.

### Limits

- Essence runs on Claude Code hooks and reads Claude Code's transcript format. It does not work with other agents.
- It is tested on Linux. On macOS, the synthesis does not run as it is: it uses GNU `stat -c`, which macOS does not have. The other hooks use only bash, Python, `awk`, `shasum` and `date` options that macOS also has, but that was read from the code, not tested.
- The install gives your agent an empty portrait. The character in a mature portrait comes from months of corrections, one at a time. No install can supply that.

## Before you start

You need each of these. Run the command beside it to check.

| You need                               | Check                                | What you should see                  |
| -------------------------------------- | ------------------------------------ | ------------------------------------ |
| Linux                                  | `uname -s`                           | `Linux`                              |
| Claude Code, logged in                 | `claude --version`                   | a version number and `(Claude Code)` |
| bash                                   | `bash --version`                     | `GNU bash`, version 4 or newer       |
| Python 3.8 or newer (tested with 3.12) | `python3 --version`                  | `Python 3.8` or higher               |
| jq                                     | `jq --version`                       | `jq-1.6` or newer                    |
| shasum                                 | `shasum --version`                   | a version number                     |
| sha256sum                              | `sha256sum --version`                | `sha256sum (GNU coreutils)`          |
| GNU stat                               | `stat --version`                     | `stat (GNU coreutils)`               |
| git                                    | `git --version`                      | a version number                     |
| Claude Code reads `~/.claude`          | `echo "${CLAUDE_CONFIG_DIR:-unset}"` | `unset`                              |

To check all of them at once, run this. It prints one line per missing tool, then `checked`:

```bash
for t in claude bash python3 jq shasum sha256sum git; do command -v "$t" >/dev/null || echo "missing: $t"; done; stat --version 2>/dev/null | grep -q GNU || echo "missing: GNU stat"; echo checked
```

To install a missing tool on Debian or Ubuntu, use `sudo apt install jq` (or the tool's package). `shasum` comes with Perl. On Fedora, `shasum` is in the package `perl-Digest-SHA`.

Essence uses `~/.claude` for its scripts and files. If `CLAUDE_CONFIG_DIR` is set, Claude Code reads its settings from another folder, and this guide does not cover that.

## Install

### The short path: the installer

The installer does steps 2, 3, 4, 6 and 7 below. It never overwrites a portrait, a `checks.json` or a broken `settings.json`. It backs up `settings.json` and any script it replaces. Do step 1 first, then look at what it would do:

```bash
./install.sh --dry-run --tz Europe/Berlin --person Alex --agent Robin
```

Use your own time zone (an IANA name), your name and the name of your agent. Each option is optional. The dry run prints `would:` lines and the change to `settings.json` as a diff. It changes nothing.

Then run it:

```bash
./install.sh --tz Europe/Berlin --person Alex --agent Robin
```

You should see `done:` lines, one per action, and at the end `Next: write section 1 of ~/.claude/essence/portrait.md`. A second run prints `same:` and `kept:` lines and changes nothing. To undo it, run `./install.sh --uninstall` (see Uninstall).

After the installer, go to step 5, then step 8. Step 9 is optional. To update the hooks after a `git pull`, run `./install.sh` again: it replaces only the scripts that changed, and keeps a backup of each.

### The manual path

Run every command from the repository folder unless a step says otherwise.

#### 1. Get the repository

This gets the hooks, the templates and the examples.

```bash
git clone https://github.com/dpdanpittman/essence.git
cd essence
```

You should see these folders, among others:

```bash
ls
```

```
AGENTS.md  CHANGELOG.md  CLAUDE.md  docs  examples  hooks  install.sh  LICENSE  README.md  site  studio  templates  tests
```

Undo: `cd ..` and `rm -rf essence`.

#### 2. Copy the hook scripts to where they run from

Claude Code runs the hooks from `~/.claude/scripts/`. Nothing runs from the clone, so a `git pull` changes nothing until you copy again. `essence-synthesize.sh` finds `essence-reduce.py` and `essence-scan.py` in its own folder, so keep the eight files together.

```bash
mkdir -p ~/.claude/scripts
cp hooks/session-start-verify.sh hooks/essence-synthesize.sh hooks/essence-reduce.py hooks/essence-scan.py hooks/essence-nudge.py hooks/essence-now.sh hooks/essence-check.py hooks/essence-brush-rules.py ~/.claude/scripts/
chmod 700 ~/.claude/scripts/session-start-verify.sh ~/.claude/scripts/essence-*
```

You should see eight files, each with mode `-rwx------`:

```bash
ls -l ~/.claude/scripts/
```

Undo:

```bash
rm ~/.claude/scripts/session-start-verify.sh ~/.claude/scripts/essence-synthesize.sh ~/.claude/scripts/essence-reduce.py ~/.claude/scripts/essence-scan.py ~/.claude/scripts/essence-nudge.py ~/.claude/scripts/essence-now.sh ~/.claude/scripts/essence-check.py ~/.claude/scripts/essence-brush-rules.py
```

#### 3. Make the Essence folder

This folder holds the portrait and everything that grows from it. It is private, so only your user may open it.

```bash
mkdir -p ~/.claude/essence/landscapes ~/.claude/essence/strokes ~/.claude/essence/brushes
chmod 700 ~/.claude/essence
```

You should see `drwx------`:

```bash
ls -ld ~/.claude/essence
```

Undo, only while the folder is still empty: `rm -r ~/.claude/essence`.

#### 4. Start the portrait from the template

This copies the empty portrait, with its eleven `### N.` headings. The first command copies only if no portrait exists yet, so it never overwrites one.

```bash
[ -e ~/.claude/essence/portrait.md ] || cp templates/portrait.md ~/.claude/essence/portrait.md
chmod 600 ~/.claude/essence/portrait.md
```

You should see `11`, the number of section headings:

```bash
grep -c '^### ' ~/.claude/essence/portrait.md
```

Keep the headings exactly as they are. The session-start hook looks for `### 1. IDENTITY`, and the synthesis rejects any run that leaves a heading missing, repeated or out of order.

Undo, only before you have written into it: `rm ~/.claude/essence/portrait.md`.

#### 5. Write section 1, the identity

Section 1 is who your agent is, in the first person. The session-start hook prints it at every start, and the synthesis never edits it. Open the portrait in your editor:

```bash
"${EDITOR:-nano}" ~/.claude/essence/portrait.md
```

Under `### 1. IDENTITY`, write three to six short lines. For example:

```
### 1. IDENTITY

- I am Robin, the coding agent of Alex.
- I work in Alex's repositories and say plainly when I do not know something.
- I ask before I change anything outside the task.
```

You can also leave it empty now and write it with your agent in the first session. `examples/portrait-example.md` shows a whole portrait filled in for an invented agent.

You should see your lines:

```bash
sed -n '/^### 1\. /,/^### 2\. /p' ~/.claude/essence/portrait.md
```

Undo: delete the lines in your editor.

#### 6. Copy the rules for the Stop check

The Stop check reads its rules from `~/.claude/essence/checks.json`. Without the file it has no rules and does nothing. The example has two rules: do not sign off before the person does, and do not write a recap.

```bash
[ -e ~/.claude/essence/checks.json ] || cp examples/checks-example.json ~/.claude/essence/checks.json
chmod 600 ~/.claude/essence/checks.json
```

You should see `sign-off` and `no-recap`:

```bash
jq -r '.rules[].id' ~/.claude/essence/checks.json
```

Undo: `rm ~/.claude/essence/checks.json`.

#### 7. Add the hook entries to settings.json

Claude Code starts a hook when its event happens, if `~/.claude/settings.json` names it. These are the entries to add, from `examples/settings-hooks.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|compact",
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claude/scripts/session-start-verify.sh"
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claude/scripts/essence-synthesize.sh || true"
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claude/scripts/essence-synthesize.sh || true"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/scripts/essence-nudge.py",
            "timeout": 10
          },
          {
            "type": "command",
            "command": "ESSENCE_TZ=YOUR_TIME_ZONE bash ~/.claude/scripts/essence-now.sh",
            "timeout": 5
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/scripts/essence-check.py",
            "timeout": 15
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/scripts/essence-brush-rules.py --hook",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

Your `settings.json` may already hold other settings and hooks. The commands below add these entries next to yours and keep everything else.

First, make sure the file exists. This writes an empty object only if there is no file:

```bash
[ -e ~/.claude/settings.json ] || echo '{}' > ~/.claude/settings.json
```

Check that the file is valid JSON before you change it. You should see `valid`:

```bash
jq empty ~/.claude/settings.json && echo valid
```

If you see a parse error instead, fix the file first. Troubleshooting has the steps.

Back up the file:

```bash
cp ~/.claude/settings.json ~/.claude/settings.json.bak-essence
```

Add the entries. Run this once:

```bash
jq --slurpfile block examples/settings-hooks.json '.hooks = (reduce ($block[0].hooks | keys[]) as $k ((.hooks // {}); .[$k] = ((.[$k] // []) + $block[0].hooks[$k])))' ~/.claude/settings.json.bak-essence > ~/.claude/settings.json
```

Set your time zone in the time hook. Replace `Europe/Berlin` with your IANA time zone name:

```bash
sed -i 's|ESSENCE_TZ=YOUR_TIME_ZONE |ESSENCE_TZ=Europe/Berlin |' ~/.claude/settings.json
```

To use the machine's time zone instead, replace it with nothing: `sed -i 's|ESSENCE_TZ=YOUR_TIME_ZONE ||' ~/.claude/settings.json`. If you leave the placeholder, the time line shows UTC under the wrong name `YOUR`.

Set the two names. The synthesis prompt and the session-start notes use them. Without them the text says "the person" and "the agent":

```bash
jq '.env.ESSENCE_PERSON = "Alex" | .env.ESSENCE_AGENT = "Robin"' ~/.claude/settings.json > ~/.claude/settings.json.new && mv ~/.claude/settings.json.new ~/.claude/settings.json
```

You should see `valid`, then `2`, then your time zone and your names:

```bash
jq empty ~/.claude/settings.json && echo valid
grep -c 'essence-synthesize.sh' ~/.claude/settings.json
grep -o 'ESSENCE_TZ=[^ ]*' ~/.claude/settings.json
jq -c '.env' ~/.claude/settings.json
```

If the count is `4`, the entries were added twice. Restore the backup and run the add command once.

Undo: `cp ~/.claude/settings.json.bak-essence ~/.claude/settings.json`.

#### 8. Check the files and their permissions

This step is for review. It changes nothing. Run it after the manual steps or after the installer.

```bash
stat -c '%A %n' ~/.claude/essence ~/.claude/essence/portrait.md ~/.claude/essence/checks.json ~/.claude/scripts/*
```

You should see:

```
drwx------ ~/.claude/essence
-rw------- ~/.claude/essence/portrait.md
-rw------- ~/.claude/essence/checks.json
-rwx------ ~/.claude/scripts/essence-brush-rules.py
-rwx------ ~/.claude/scripts/essence-check.py
-rwx------ ~/.claude/scripts/essence-now.sh
-rwx------ ~/.claude/scripts/essence-nudge.py
-rwx------ ~/.claude/scripts/essence-reduce.py
-rwx------ ~/.claude/scripts/essence-scan.py
-rwx------ ~/.claude/scripts/essence-synthesize.sh
-rwx------ ~/.claude/scripts/session-start-verify.sh
```

`stat` prints the full path of your home folder where this shows `~`. Other scripts you keep in `~/.claude/scripts/` show up too.

Now run the session-start hook by hand. It is the same command Claude Code runs:

```bash
echo '{"source":"startup"}' | bash ~/.claude/scripts/session-start-verify.sh
```

You should see `## Essence Portrait`, a note that `portrait.md.sha256` does not exist yet, your section 1, and a block that starts with `READ YOUR ENTIRE PORTRAIT NOW` and gives Read ranges such as `offset=1 limit=101`. The note about the checksum is expected until the first synthesis that changes the portrait.

#### 9. Optional: keep a local history

If `~/.claude/essence` is a git repository, each synthesis makes two commits: what changed by hand or in the session before the run, and what the run changed. That makes it easy to see and undo any change.

```bash
git -C ~/.claude/essence init
```

You should see `Initialized empty Git repository in .../.claude/essence/.git/`. Git may print a few `hint:` lines about the branch name first. They do no harm. Keep this history local. A real portrait holds private things, so never push it to a public remote.

Undo: `rm -rf ~/.claude/essence/.git`.

## Your first session

Start Claude Code in any project folder:

```bash
claude
```

Send a first message, such as `hello`. Before it replies, your agent should call Read on `~/.claude/essence/portrait.md` (one call per range the hook gave) and then say in one short line that the portrait is loaded. That line is the proof that the hook ran and the agent read the file. It may also mention the checksum note.

Two more checks:

- Ask `What does section 1 of your portrait say?`. It should quote the lines you wrote.
- Ask `What time is it?`. It should answer from the `[Now: ...]` line, in your time zone.

The hook runs on a new session and after a compaction. It does not run when you resume a session (`claude --continue`, `claude --resume`) or after `/clear`, because the matcher in step 7 is `startup|compact`. Add `|resume|clear` to the matcher if you want it there too.

If the agent did not read the portrait:

1. Type `/hooks` in Claude Code. You should see the Essence hooks listed under SessionStart, PreCompact, SessionEnd, UserPromptSubmit, Stop and PostToolUse. If they are missing, Claude Code did not load your `settings.json`. Check it with `jq empty ~/.claude/settings.json`.
2. Run the hook by hand, as in step 8. If it prints an error, the error says what is wrong.
3. Start Claude Code with a hook log, then read the log after one message:

   ```bash
   claude --debug=hooks --debug-file /tmp/claude-hooks.log
   ```

   ```bash
   grep -i -A3 'SessionStart' /tmp/claude-hooks.log
   ```

4. See Troubleshooting below.

Session transcripts are in `~/.claude/projects/<folder>/<session-id>.jsonl`. The newest one is:

```bash
ls -t ~/.claude/projects/*/*.jsonl | head -1
```

## Your first synthesis

### When it runs

The synthesis runs by itself at a compaction (automatic, or when you type `/compact`) and when a session ends. The hook returns at once, and the work runs in the background. It skips the run when the new part of the transcript has fewer than 3 messages from you. A session of three or more real exchanges is enough for a first run.

What it does, in order:

1. It takes a lock, so only one synthesis runs at a time.
2. It cuts the part of the transcript that no earlier run has read down to a plain-text slice.
3. It saves a copy of the portrait in `~/.claude/essence/portraits/<time>-before.md`, and copies of the landscapes, strokes and brushes.
4. It starts one `claude -p` run with only the Read and Edit tools, in `~/.claude/essence`, without your other hooks.
5. It checks the result. It puts the saved copies back if a `### N.` heading is missing, repeated or out of order, if the portrait shrank by more than 20 percent, if it grew past `ESSENCE_PORTRAIT_MAX`, if section 1 changed, or if an added line looks planted (an instruction, a secret, an unknown web address, hidden characters).
6. If the run passed and changed the portrait, it saves `<time>-after.md` and writes the checksum file `portrait.md.sha256`.

### Run it once by hand

This lets you watch a run instead of waiting for a session to end. Pick the transcript of a session with at least 3 messages from you:

```bash
T=$(ls -t ~/.claude/projects/*/*.jsonl | head -1); echo "$T"
```

When you run the script by hand, the two names from `settings.json` are not set. Set them in your shell first:

```bash
export ESSENCE_PERSON=Alex ESSENCE_AGENT=Robin
```

First, a dry run. It runs the real model on a copy of the Essence folder in `/tmp`, prints the log, and changes nothing real:

```bash
bash ~/.claude/scripts/essence-synthesize.sh --transcript "$T" --dry
```

You should see, on the error stream:

```
Essence: DRY RUN on a copy in /tmp/essence-dry.XXXXXX (the real portrait is not touched)
Essence v3: run <time>, transcript <session>.jsonl bytes 0..<size>, {"end": ..., "person": 5, ...}, model opus, DRY RUN
<the model's summary: one line per edit, or "routine, no edits">
Essence: portrait changed; checksum updated; copies <time>-before.md and <time>-after.md
Essence: finished <time> (agent exit 0, verdict: ok)
```

The copy stays in `/tmp/essence-dry.XXXXXX`. Compare it with the real file, then remove it:

```bash
diff ~/.claude/essence/portrait.md /tmp/essence-dry.XXXXXX/portrait.md
rm -r /tmp/essence-dry.XXXXXX
```

Replace `XXXXXX` with the name the run printed.

Then the real run. `--wait` keeps it in the foreground and prints the log at the end:

```bash
bash ~/.claude/scripts/essence-synthesize.sh --transcript "$T" --wait
```

You should see the same lines without `DRY RUN`. A second run on the same transcript prints `Essence: only 0 new messages from Alex since the last run, skipping (need 3).` and exits with code 2, because the script remembers how far it read each transcript.

The real run is not free. See What it costs.

### What changes

After a run that changed the portrait:

- `portrait.md` has a few edited or added lines. Most runs add zero to three lines across sections 2, 3, 5 and 6.
- `portraits/<time>-before.md` and `portraits/<time>-after.md` are the copies from before and after.
- `portrait.md.sha256` holds the new checksum.
- `synthesis-status.json` says how the run ended.
- `synth-state.json` records how far each transcript was read.
- `last-synthesis.log` is the log of the last run.
- Landscapes whose subject came up in the slice may have changed.

After a run that changed nothing, the `before` copy is removed, and the log says `portrait not changed`.

### See what it did

```bash
cat ~/.claude/essence/last-synthesis.log
jq . ~/.claude/essence/synthesis-status.json
ls -t ~/.claude/essence/portraits/ | head -2
diff ~/.claude/essence/portraits/<time>-before.md ~/.claude/essence/portrait.md
```

`verdict` is `ok` for a run that passed. Any other verdict names the reason it was rolled back, such as `bad headings (1 2 3 4 5 6 8 9 10 11 )` or `section 1 was changed`. If you set up the local history in step 9, `git -C ~/.claude/essence log --stat` shows each run as a commit.

### Roll back to the previous copy

Put the `before` copy back, then write the checksum for it. Without the second command, the next session start shows an integrity warning:

```bash
cp ~/.claude/essence/portraits/<time>-before.md ~/.claude/essence/portrait.md
(cd ~/.claude/essence && sha256sum portrait.md > portrait.md.sha256)
```

With the local history, you can instead restore the file from the commit before the run. Git writes the file with your default mode, so set it back to 600, then write the checksum:

```bash
git -C ~/.claude/essence checkout HEAD~1 -- portrait.md
chmod 600 ~/.claude/essence/portrait.md
(cd ~/.claude/essence && sha256sum portrait.md > portrait.md.sha256)
```

### After you edit the portrait yourself

The checksum file changes only when a synthesis changes the portrait. If you or your agent edit the portrait in any other way, the next session start shows `PORTRAIT INTEGRITY WARNING` and tells the agent not to trust the portrait. After every edit you meant to make, write the checksum again:

```bash
(cd ~/.claude/essence && sha256sum portrait.md > portrait.md.sha256)
```

## Growing it

Each step below takes about five minutes. Each new file starts from a template. For each one there is an invented example in `examples/`.

### Add a landscape

A landscape is one area of work: what is true there now. The rule: one fact per line, in the form `- fact (date, checked|record|assumed)`. When a fact stops being true, the line goes.

Copy the template. Use a short name for the area:

```bash
cp templates/landscape.md ~/.claude/essence/landscapes/billing-service.md
```

Fill in the six parts. Then list it in section 11 of the portrait, under `**The landscapes**`, with the words that should make your agent read it:

```
- **billing-service** (landscapes/billing-service.md). Triggers: billing, invoice, payments. Last updated: 2027-01-20.
```

Write the checksum again (see above). You should see your landscape when you run `ls ~/.claude/essence/landscapes/`. To test it, start a new session and ask ten questions about the area. Your agent should answer from the landscape alone.

### Add a stroke

A stroke is one procedure: when to do it, the steps, the undo and the traps. The rule: write a stroke when you ask for the same procedure a second time. It names one landscape and one brush, and the synthesis never edits it.

```bash
cp templates/stroke.md ~/.claude/essence/strokes/deploy-staging.md
```

Fill in the parts. Write `none yet` under Shortcut until a tested script exists. Add a `- Stroke: deploy-staging (strokes/deploy-staging.md). Shortcut: none yet.` line to its landscape, and a line under `**Strokes**` in section 11. `examples/stroke-example.md` shows one filled in.

### Add a brush

A brush is one ability: a login, a role, a token or a tool. The rule: a brush says what it can reach and what it cannot, and it never holds a secret value. It names only the vault (the cabinet) and the item (the drawer) where the secret lives.

```bash
cp templates/brush.md ~/.claude/essence/brushes/github-cli.md
```

Fill in the eight parts. Its check is one read-only command that proves the brush works and prints no secret, such as `gh auth status`. Add a line for it to `~/.claude/essence/brushes/INDEX.md`:

```bash
echo '- github-cli: the gh login, read and write on the team repositories. brushes/github-cli.md' >> ~/.claude/essence/brushes/INDEX.md
```

Then list it in each landscape that uses it, with a line such as `- Brush: github-cli (brushes/github-cli.md). Read and write on the team repositories.`. The synthesis never edits a brush.

### Add a cabinets entry

`cabinets.md` lists every password-manager vault your agent may open, never its contents. The rule: a secret goes into a cabinet before it goes anywhere else, and it never passes through the conversation.

```bash
[ -e ~/.claude/essence/cabinets.md ] || cp templates/cabinet.md ~/.claude/essence/cabinets.md
```

Fill in one `## Cabinet: NAME` section per vault: the helper command that reads one item, the vaults it may open, what it must never hold, where its own access token sits, and how you take the access away. `examples/cabinet-example.md` shows one filled in.

### Turn a rule that keeps failing into a check

A rule written in the portrait does not act at the moment it matters. If you have corrected the same thing three times, and it has a shape a program can see (a phrase, a command), give it a check. `docs/superego.md` explains the idea.

The repository's example is the rule "the person ends the session, not the agent". In `~/.claude/essence/checks.json` it is the rule `sign-off`:

- `break` is a regular expression for what a reply must not say, such as `sleep well`.
- `fine_if_person_said` is a regular expression for your own last message. If it matches (you said goodnight first), the reply is fine.
- `reason` is what your agent is told when it is caught. `{hit}` becomes the words that broke the rule.

Text inside quotes, code, tables and italics does not count, so your agent can still talk about a phrase.

To add your own rule, add one object to the `rules` list, with an `id`, a `break` pattern and a `reason`. Check that the file is still valid:

```bash
jq -r '.rules[].id' ~/.claude/essence/checks.json
```

Test the rule by hand. This feeds the Stop hook the same JSON Claude Code sends: the finished reply and the path of a transcript whose last message from you is `thanks`:

```bash
printf '%s\n' '{"type":"user","message":{"content":"thanks"}}' > /tmp/essence-check-test.jsonl
echo '{"last_assistant_message":"All done. Sleep well.","transcript_path":"/tmp/essence-check-test.jsonl"}' | python3 ~/.claude/scripts/essence-check.py
```

You should see:

```
{"decision": "block", "reason": "[Essence check: sign-off] You signed off ('Sleep well') and the person did not say goodbye. The person ends the session. Say in one short line that the check caught you, and stay: answer what they said."}
```

In a session, Claude Code shows that reason to your agent and does not let the turn end. Your agent has to answer for it in the same turn. The check blocks at most once per turn and never blocks when it fails. Each catch is counted in `~/.claude/essence/check-count.json`. A rule that never fires can go. Remove the test file with `rm /tmp/essence-check-test.jsonl`.

### Optional: rules that ride on a brush

`hooks/essence-brush-rules.py` checks that a landscape which mentions a platform lists one of that platform's brushes. It does nothing until `~/.claude/essence/brush-rules.json` exists. `examples/brush-rules-example.json` describes an invented platform. Do not copy it as it is: write your own rule for a real platform first.

Once the rules file exists, every landscape needs a Brushes line, or the check reports it. A landscape that uses no brush can say so:

```
- Brushes (~/.claude/essence/brushes/): none
```

To check everything at once:

```bash
python3 ~/.claude/scripts/essence-brush-rules.py --all
```

Exit code 0 and no output means clean. Each problem prints one line, and the exit code is 1. Without a rules file, it prints `broken rules file: rules file .../brush-rules.json does not exist` and exits with code 2. The hook stays silent in that case.

## Optional: the studio

The studio wakes the model a few times a night with no task. It is a separate script with its own timer, not a hook, and it is off until you install it. It needs Python 3.12. [docs/studio.md](studio.md) has the full explanation, the safety shape and every config key.

The first three commands, after you write the config file that docs/studio.md describes:

```bash
cp -r studio ~/.claude/scripts/studio
PYTHONPATH=~/.claude/scripts python3 -P -m studio config check
PYTHONPATH=~/.claude/scripts python3 -P -m studio wake --dry-run
```

The dry run uses no model, writes nothing and fetches nothing. The studio runs a real model at night when the timer is on, three short wake-ups by default, every night. Run `studio measure` first (it runs the real model a few times) and set the token limits from what it prints, before you turn the timer on.

## Troubleshooting

### A hook does not fire

Symptom: the agent does not mention the portrait, or there is no `[Now: ...]` line.

Check:

1. Type `/hooks` in Claude Code. The Essence hooks should be listed.
2. Print the command Claude Code runs for the session start, then run it the same way:

   ```bash
   jq -r '.hooks.SessionStart[].hooks[].command' ~/.claude/settings.json
   echo '{"source":"startup"}' | bash -c "$(jq -r '.hooks.SessionStart[].hooks[].command' ~/.claude/settings.json)"
   ```

   If a script is missing, you see `bash: .../.claude/scripts/session-start-verify.sh: No such file or directory` and exit code 127.

3. Check that the portrait exists: `ls -l ~/.claude/essence/portrait.md`. Without a portrait, the session-start hook prints nothing on purpose.

Fix: copy the scripts again (install step 2, or run `./install.sh`). If `/hooks` lists nothing, check `settings.json` (below). Restart Claude Code after you change `settings.json`.

### The portrait is too large for one read

Symptom: the session start shows `PORTRAIT NEAR ITS CAP`, or the agent says the file is too large to read, or it reads only part of it.

Check:

```bash
wc -c ~/.claude/essence/portrait.md
echo '{"source":"startup"}' | bash ~/.claude/scripts/session-start-verify.sh | grep 'Read calls'
```

The hook splits the portrait into ranges of about 55 KB each, because one Read call is capped. A portrait of 161 KB gives three ranges, such as `offset=1 limit=739; offset=740 limit=700; offset=1440 limit=666`. The agent must make every one of those calls.

Fix: if the agent read only one range, tell it to read all of them. The warning starts at 90 percent of `ESSENCE_PORTRAIT_MAX` (144000 bytes). Trim before you reach the cap: remove duplicate lines, and move stale lines from section 4 to section 10. At the cap, the synthesis refuses every run that makes the portrait bigger. Keep one fact per line. A very long single line can still be too large for one read.

### The synthesis leaves the portrait unchanged

Symptom: the portrait does not change after a session, or the session start says `Last synthesis (unknown) did not change the portrait`. The word `unknown` there is expected: the note reads a field that the current version no longer writes.

Check the log and the status:

```bash
cat ~/.claude/essence/last-synthesis.log
jq . ~/.claude/essence/synthesis-status.json
```

Then match what you see:

| What you see                                     | Cause                                                              | Fix                                                                                                         |
| ------------------------------------------------ | ------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------- |
| `only N new messages from ... skipping (need 3)` | Fewer than 3 new messages from you since the last run.             | Nothing to fix. The next long session triggers a run. Lower `ESSENCE_MIN_MESSAGES` to change the threshold. |
| `claude: command not found` and `agent exit 127` | The hook could not find the `claude` command on its PATH.          | Make sure `command -v claude` works in the shell you start Claude Code from.                                |
| `agent exit` other than 0                        | The model run failed, for example a login or quota error.          | Run `claude -p "say ok"` by hand to see the error.                                                          |
| `RUN REJECTED (...)`                             | The supervisor rolled the run back. The reason is in the brackets. | Nothing was lost. Read the reason. If it was `section 1 was changed`, nothing needs fixing.                 |
| `a synthesis is already running, skipping.`      | Another run holds the lock.                                        | Wait for it. A lock whose process has ended is removed by the next run.                                     |
| `portrait not changed` and `agent exit 0`        | The model found nothing that should change the next session.       | Nothing to fix. A routine session makes no edits.                                                           |
| `no transcript to read`                          | The hook got no transcript path.                                   | Run it by hand with `--transcript` (see Your first synthesis).                                              |

A run that stopped in the middle can leave files in `~/.claude/essence/run/` and a lock file, `~/.claude/essence/.synthesis-running`. The files in `run/` hold parts of your conversation. This command removes both, but only when the process named in the lock has ended. Otherwise it prints `a synthesis is running; wait for it`:

```bash
if kill -0 "$(cat ~/.claude/essence/.synthesis-running 2>/dev/null)" 2>/dev/null; then echo "a synthesis is running; wait for it"; else rm -f ~/.claude/essence/.synthesis-running; rm -rf ~/.claude/essence/run/*; echo cleaned; fi
```

### PORTRAIT INTEGRITY WARNING at session start

Symptom: the session start shows `PORTRAIT INTEGRITY WARNING`, and the agent hesitates to use the portrait.

Check: did you, or your agent, edit the portrait since the last synthesis that changed it? Compare with the newest saved copy:

```bash
diff "$(ls -t ~/.claude/essence/portraits/*-after.md | head -1)" ~/.claude/essence/portrait.md
```

Fix: if every difference is one you meant, write the checksum again:

```bash
(cd ~/.claude/essence && sha256sum portrait.md > portrait.md.sha256)
```

If a difference is not yours, restore a saved copy (see Roll back to the previous copy).

### A broken settings.json

Symptom: Claude Code reports a problem with your settings when it starts, and no Essence hook runs. `./install.sh` stops with `settings.json is not valid JSON` and changes nothing.

Check: `jq empty ~/.claude/settings.json` prints the line and column of the first error, such as `jq: parse error: Expected value before ',' at line 46, column 14`.

Fix: open the file and fix the error at the line `jq` names. A common cause is a comma after the last item of a list or an object, or a comma before the first one. Run `jq empty ~/.claude/settings.json` again until it prints nothing.

If you would rather go back, list the backups, newest first:

```bash
ls -t ~/.claude/settings.json.bak*
```

`settings.json.bak-essence` is the copy from before step 7, and the installer's copies are named `settings.json.bak-<time>`. A backup from before the install has no Essence entries. After you restore it, do step 7 again, or run `./install.sh`:

```bash
cp ~/.claude/settings.json.bak-essence ~/.claude/settings.json
```

### A missing tool

Symptom and fix, per tool:

- **jq missing.** `./install.sh` stops with `missing: jq`. The manual merge in step 7 prints `jq: command not found`. The hooks still run, but without jq the session start skips its status notes. Install jq.
- **sha256sum missing.** The synthesis stops after the model run, at the checksum. The model's edit stays in the portrait, the log ends without a `finished` line, `portrait.md.sha256` is left empty, and every session start shows `PORTRAIT INTEGRITY WARNING`. Install GNU coreutils. Then check the edit with `diff`, write the checksum by hand (above), and remove the leftovers with the cleanup command above.
- **GNU stat missing** (macOS). The synthesis prints `stat: illegal option -- c` and stops before the model run, right after it saved the `before` copy. The portrait does not change. The slice stays in `run/`: remove it with the cleanup command above. Essence's synthesis does not run on macOS as it is.
- **python3 missing.** Every Python hook fails with `python3: command not found` (exit code 127), and the synthesis cannot cut the transcript. The hook log from Your first session shows the error. Install Python 3.
- **claude missing from the hook's PATH.** See the synthesis table above.

The check in Before you start finds all of these at once.

## Uninstall

This removes the hooks and the scripts and leaves your own files in `~/.claude/essence/` in place.

### The short path

From the repository folder:

```bash
./install.sh --uninstall --dry-run
./install.sh --uninstall
```

You should see a backup line for `settings.json`, `done:  wrote ~/.claude/settings.json`, one `removed` line per script, and `kept:  ~/.claude/essence`. Your other hooks and settings stay.

### The manual path

1. Back up `settings.json`:

   ```bash
   cp ~/.claude/settings.json ~/.claude/settings.json.bak-uninstall
   ```

2. Remove every hook entry that runs an Essence script, and the two name settings. Your other hooks stay:

   ```bash
   jq 'def essence: (.command // "") | test("\\.claude/scripts/(session-start-verify\\.sh|essence-[A-Za-z-]+\\.(sh|py))"); if .hooks then .hooks |= (with_entries(.value |= (map(.hooks |= map(select(essence | not))) | map(select((.hooks | length) > 0)))) | with_entries(select((.value | length) > 0))) else . end | if .hooks == {} then del(.hooks) else . end | if .env then .env |= del(.ESSENCE_PERSON, .ESSENCE_AGENT) else . end | if .env == {} then del(.env) else . end' ~/.claude/settings.json.bak-uninstall > ~/.claude/settings.json
   ```

3. Check that no Essence entry is left. You should see `0`:

   ```bash
   grep -c 'essence' ~/.claude/settings.json
   ```

4. Remove the scripts:

   ```bash
   rm ~/.claude/scripts/session-start-verify.sh ~/.claude/scripts/essence-synthesize.sh ~/.claude/scripts/essence-reduce.py ~/.claude/scripts/essence-scan.py ~/.claude/scripts/essence-nudge.py ~/.claude/scripts/essence-now.sh ~/.claude/scripts/essence-check.py ~/.claude/scripts/essence-brush-rules.py
   ```

5. If you installed the studio, follow Undo in [docs/studio.md](studio.md).

6. If `~/.claude/scripts/` is now empty, remove it: `rmdir ~/.claude/scripts`. `rmdir` refuses a folder that still holds files.

Restart Claude Code. `/hooks` should list no Essence hooks.

### What is left, and how to remove it

`~/.claude/essence/` stays: the portrait, the landscapes, the strokes, the brushes, `checks.json`, the saved copies and the logs. The backups `settings.json.bak-*` stay in `~/.claude/`.

To remove your Essence files too, make an archive first, then delete the folder:

```bash
tar -czf ~/essence-backup.tar.gz -C ~/.claude essence
rm -rf ~/.claude/essence
```

This cannot be undone without the archive.
