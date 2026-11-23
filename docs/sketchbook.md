# The sketchbook

The sketchbook is the agent's running notes: what happened today, what is in flight, what waits on the person, what was just decided. Dated, quick, informal. It is working memory.

The sketchbook is the sixth part of Essence. The portrait says who the agent is. A landscape is the ground of one area of work. A stroke is how it does one thing there. A brush is what it can touch. The studio is its own time. None of them says what is happening right now. After a compaction or a new session, the portrait gives the agent back its character. The sketchbook lets it pick the thread back up.

A painter keeps a sketchbook every day. Most of it is never shown. What keeps coming back gets painted properly. The same holds here: a pattern that keeps showing up in the sketches becomes a rule in the portrait, a fact in a landscape, or a stroke.

The folder is the **sketchbook**. Each entry in it is a **sketch**.

## Why

An agent that works for weeks with one person builds up a lot of state that is true only for a day or two: a job running, a question waiting, a list of what to do next. That state does not belong in the portrait (it holds what stays true for weeks) or in a landscape (it holds what is true now, without history). It needs its own place.

A single running notes file works at first and then outgrows itself. Past a few hundred kilobytes it can only be read with grep, never whole, and every program that reads it gets slower. The sketchbook keeps the habit of one running file and adds two things: one file per month, and a stable pointer to the current month.

## The format

A sketchbook is a folder, one file per month:

```
~/.claude/essence/sketchbook/
  2027-01.md       a past month, never changed
  2027-02.md       the current month
  current.md       a symlink to the current month
  .lock            taken by note and sketchbook-rotate
  .size-warning    present only when the current month is over the size mark
```

Every reader and writer uses `current.md`, so no program needs to know about months.

There are three kinds of entry. All are appended at the end, newest at the bottom, never edited in place.

1. **A sketch.** One line, stamped by the clock, never by the agent. Written with `note "<text>"`:

   ```
   - 2027-02-03 15:10 CET Max decided the bread lesson moves to Friday ("Friday, the oven man comes Thursday").
   ```

2. **The In flight block.** What waits on the person, what runs, what just finished. The newest block wins. A block older than 18 hours counts as absent.

   ```
   - 2027-02-03 15:12 CET IN FLIGHT (current):
     W. what only the person can do
     R. 14:50 what is running, with its start time
     F. 15:05 what just finished
   ```

   The header starts at column 0. Each item is indented and starts with `W.`, `R.` or `F.`. The block ends at the first blank or unindented line. To change it, append a whole new block; never edit the old one.

3. **The work list block.** The person's ordered list of work. The newest block wins.

   ```
   - 2027-02-03 09:00 CET WORK LIST (current; replaces the 2027-01-27 list):
     1. [P1] the bread lesson: moved to Friday.
     2. [P2] sewing unit plan: draft ready, waits on Max.
   ```

An open list is optional: a block whose header is `OPEN LIST`, `<WORD> OPEN LIST` (for example `PERSONAL OPEN LIST`) or `OPEN:`, either as a dated line with indented items or as a `## ` heading with plain lines under it.

`templates/sketchbook-month.md` is an empty month. `examples/sketchbook-example.md` is an invented month.

## Rules

- **Append only.** Nothing is rewritten. A correction is a new sketch that says what it corrects.
- **The clock stamps every entry.** The agent never types a time. `note` reads it from the clock in `ESSENCE_TZ`.
- **Never a secret.** Key names and vault item names only, never a value.
- **The person decides what else stays out.** `ESSENCE_SKETCHBOOK_SCOPE` holds the choice, made at setup:
  - `work` (the default): work only. Health, money and family stay out.
  - `all`: anything the person brings up, if the sketchbook stays on the machine. Programs that copy parts of it elsewhere (a morning page, a chat message, a status screen) still screen those out themselves.
- **The person's words go in quotes, exactly as said**, typos included.
- **Record a guess as a guess** and an inference as an inference ("my reading", "not checked").
- **Never read the whole sketchbook.** At session start and after a compaction, read the open items page, the newest In flight block, the newest work list and the last 150 lines. Find everything else with grep. The session-start hook says so when `current.md` exists.

## Rotation

`scripts/sketchbook-rotate` runs once a day from a timer and does nothing unless the month changed. On the first run of a new month it:

1. takes the lock (`.lock`; `note` takes the same lock for its append);
2. reads the old month and never changes it;
3. writes `YYYY-MM.md` starting with an **open items page**, "OPEN ITEMS (carried from YYYY-MM)": copies of the newest In flight block, the newest work list block and the newest block of each open list, re-stamped with the clock and marked carried. An In flight block that was already stale keeps its old stamp, so it stays absent. With scope `work`, a block whose header says PERSONAL is not carried;
4. points `current.md` at the new month (a temporary symlink, then a rename, so a reader never sees it missing);
5. copies to the new month any lines that a writer without the lock appended to the old month during steps 2 to 4. They also stay in the old month.

The old month stays searchable with grep. A second run in the same month does nothing. A run that stopped half way is finished by the next one.

**The size mark.** Past 400 KB in one month (`ESSENCE_SKETCHBOOK_WARN_KB`), the rotation prints one line and writes it to `.size-warning`, and the nudge hook adds a sentence to its reminder. Then rotate early: `sketchbook-rotate --early` starts `YYYY-MM-DD.md` the same way. The next month starts as usual.

**Old readers.** A program that finds the running notes by the newest file name in some folder keeps working with `--compat-link-glob`, for example `--compat-link-glob "~/notes/notes-*.md"`. Each rotation then adds one symlink, `notes-YYYY-MM-01.md`, pointing at the new month. It never changes an older link. Point new readers at `current.md` instead.

Options: `--dry-run` (says what it would do, writes nothing), `--early`, `--init` (starts an empty sketchbook if there is none; the installer runs it), `--now "YYYY-MM-DD HH:MM"` (tests), `--dir`.

Exit codes: 0 done (rotated, nothing to do, or a dry run); 1 an unexpected error; 2 refused, nothing changed (for example `current.md` missing, or a name it would create is taken); 3 the lock is busy.

## How it connects to the rest of Essence

- **To the portrait.** The portrait keeps what holds for weeks. The sketchbook keeps the day. A lesson or a decision that keeps coming back in the sketches is a candidate for a portrait rule.
- **To landscapes.** When a thread changes state, a sketch records the moment and the landscape gets rewritten to say what is true now. A landscape holds no history; the sketchbook keeps it.
- **To strokes.** A procedure that shows up in the sketches twice becomes a stroke.
- **To the studio.** None. The studio's journal is the agent's own and stays separate.
- **To the hooks.** The session-start hook names the sketchbook and the parts to read, with the scope. The nudge hook asks the agent to bring the sketchbook up to date and warns past the size mark. A Stop check (`hooks/essence-check.py`) can read the In flight block from `current.md`.

## Setup

The installer does it: it copies `note` and `sketchbook-rotate` to `~/.claude/scripts/`, makes `~/.claude/essence/sketchbook/` (mode 700) and starts the first month. `--sketchbook-scope work|all` sets the scope in `~/.claude/settings.json`.

By hand:

```bash
mkdir -p ~/.claude/scripts
cp scripts/note scripts/sketchbook-rotate ~/.claude/scripts/
chmod 700 ~/.claude/scripts/note ~/.claude/scripts/sketchbook-rotate
ESSENCE_TZ=Europe/Berlin python3 ~/.claude/scripts/sketchbook-rotate --init
```

Put `note` on your PATH so the agent can call it by name, for example `ln -s ~/.claude/scripts/note ~/.local/bin/note`. Then set `ESSENCE_TZ` and, if you want it, `ESSENCE_SKETCHBOOK_SCOPE=all` in the `env` block of `~/.claude/settings.json`.

The daily timer, as systemd user units:

```ini
# ~/.config/systemd/user/sketchbook-rotate.service
[Unit]
Description=Sketchbook: start a new month when the month changed

[Service]
Type=oneshot
Environment=ESSENCE_TZ=Europe/Berlin
ExecStart=/usr/bin/python3 %h/.claude/scripts/sketchbook-rotate
```

```ini
# ~/.config/systemd/user/sketchbook-rotate.timer
[Unit]
Description=Sketchbook rotation check, every day just after midnight

[Timer]
OnCalendar=*-*-* 00:05:00 Europe/Berlin
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now sketchbook-rotate.timer
```

Back up the sketchbook folder with the rest of `~/.claude/essence/`. The month files are the only copy.

## Undo

```bash
systemctl --user disable --now sketchbook-rotate.timer
rm ~/.config/systemd/user/sketchbook-rotate.service ~/.config/systemd/user/sketchbook-rotate.timer
rm ~/.claude/scripts/note ~/.claude/scripts/sketchbook-rotate
```

The month files stay. Remove `~/.claude/essence/sketchbook/` by hand only if you want them gone.

## Tests

`tests/test_sketchbook.py` runs offline in temporary folders: rotation at a month change, the carried blocks, the scope, idempotence, the compatibility link, old months untouched, a dry run writes nothing, the lock, late lines, the size mark, `note`, the installer, and the impersonal check over the sketchbook files.
