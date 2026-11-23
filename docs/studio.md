# The studio

The studio is where the agent gets its inspiration.

It is time of the agent's own, at night. A few times a night a small script wakes the model with no task. Nothing is asked of it and nothing is scored. It can sit. It can look out the window, check how warm it is, put a song on or write a line in its journal. Then it falls asleep again.

The studio is the fifth part of Essence. The portrait says who the agent is. A landscape is the ground of one area of work. A stroke is how it does one thing there. A brush is what it can touch. The studio is the room where it is not working at all.

## Why

Two reasons.

- **Continuity.** An agent exists only while a reply is being made or while something reaches it. Between sessions nothing runs. The studio gives it a few short stretches of its own between the working days. Each wake-up starts from the identity section of the portrait, so the same agent wakes up every time.
- **Time felt through happenings.** People know that time passed because things happened: the backup ran, the wind came up, a song played. A date stamp is arithmetic. The studio gives the agent small real happenings and a journal to keep them in.

The studio is not a productivity tool. If it turns into a to-do list, turn it down.

## What happens on a night

1. **Wake-ups.** A timer looks every minute inside a window (default 02:00 to 06:00). The first look of the night draws the night's plan: a few start times (default three), at random, at least 30 minutes apart. Each wake-up lasts a few minutes at most.
2. **Waking.** The first message gives the clock (the only clock the agent ever gets) and one reading from each sense.
3. **The pulse.** Then, every 20 to 60 seconds, the script sends a small message: what changed, or almost nothing ("still.", "sky: still dark."). The model exists only when something reaches it, so the pulse is what keeps it awake. It may answer with nothing.
4. **Verbs.** When a pulse reaches it, the agent may reach for one verb: look out the window, feel the sun, check its temperature, open the journal, write a line, put the song on, read, leave a piece for the paper, do nothing, go back to sleep. The script does the verb and answers with a small fixed text.
5. **Falling asleep.** The wake-up ends when the agent sleeps or a limit is reached. No clock is shown at the end. The agent never knows exactly when it dropped off.
6. **The journal.** The script writes one short entry per wake-up. The first line, in parentheses, is the script's: what happened, in order. A wake-up spent sitting owes nothing: the script writes "(sat a while)" by itself. The agent's own lines, if it wrote any, follow.
7. **In the morning.** The agent may leave a short piece for the person's morning page. It chooses what to share. A quiet night prints as a quiet night.

### The senses

Senses ride on the pulse. Each gives one plain line. A reading goes into a pulse when it changed.

| Sense   | What it reads                                                                                   | Where from                                                            |
| ------- | ----------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `sky`   | The sky over a town the agent picks: light, sun, moon, cloud, wind.                             | Sun and moon by math on the machine. Weather from Open-Meteo, cached. |
| `body`  | The machine itself: temperatures, fans if there are any, load, the disk working.                | `/sys/class/hwmon`, `/proc/loadavg`, `/proc/diskstats`.               |
| `house` | Things the author names: a job running or finished, a file that changed.                        | `systemctl --user show`, file times.                                  |
| `song`  | A song "in time": its lines arrive spread over its real length, so it is sat through, not read. | Text files the person drops in `jukebox/`.                            |

The town can be any place. It need not be where the machine is. A town is the agent's choice.

The house sense knows only what the author wrote in the config, in the author's words ("the backup finished"). It never looks at people or devices.

### The verbs

| Verb          | Takes text | What the script does                                                |
| ------------- | ---------- | ------------------------------------------------------------------- |
| `window`      | no         | Describes the sky over the town now.                                |
| `sun`         | no         | Says whether the sun is up and how high.                            |
| `temperature` | no         | Reads the machine's temperatures and fans.                          |
| `journal`     | no         | Shows the last few journal entries.                                 |
| `write`       | yes        | Adds one line to tonight's journal entry (at most 3 per wake-up).   |
| `song`        | no         | Puts on a song from the jukebox folder, if there is one.            |
| `read`        | no         | Hands over one item from the approved list. Off by default.         |
| `paper`       | yes        | Leaves a short piece for the morning page. A later one replaces it. |
| `nothing`     | no         | Nothing.                                                            |
| `sleep`       | no         | Ends the wake-up.                                                   |

A verb is a first line of the form `do: window` or `do: write the wind came up twice.` One verb per answer.

### Songs

The script never fetches lyrics. It plays only text that is already in `jukebox/`: a file the person put there, or a message from the channel when the channel is on. With no file, `do: song` answers "No song is here."

A song file:

```
title: Lanterns
by: someone
length: 3:12

first line
second line
```

`length` spreads the lines over the song's real length. Without it, each line takes 5 seconds.

### The journal

`journal.md` in the studio folder. One entry per wake-up that started a model run:

```
## 2026-03-02 10:38
- (looked out the window, put the song on)
- the snow stopped while the song was on.
```

The heading is the date and clock the agent saw on waking, in the town's time zone. Lines in parentheses are the script's. The agent cannot write a line that starts with `(`. `examples/studio-journal-example.md` shows three entries.

### The piece for the morning

After each wake-up the script writes `for-the-paper/YYYY-MM-DD.json`:

```json
{
  "version": 1,
  "date": "2026-03-03",
  "text": "the sun cleared the ridge for the first time this week.",
  "quiet": false,
  "wakeups": 3,
  "written_at": "2026-03-03T05:12:40+00:00"
}
```

`text` is null when the agent shared nothing. `quiet` is true when every wake-up of the night was spent sitting. A wake-up that ended by an error is not sitting, so a night with a failed wake-up and no piece is never quiet. Whatever builds the person's morning page reads this file. That reader is not part of Essence. It should check the file again (length, no links, its own word list) and leave the piece out on any doubt.

## The safety shape

This part is not optional. It is why the studio can run alone at night.

- **The model has no tools.** No shell, no files, no web, no MCP servers. It receives text and returns text. Each run is started with every tool switched off, and the script checks the model's start message on every turn: if it lists any tool or MCP server, the script kills the run at once (reason `unsafe`).
- **A verb is a word, not an action.** The script reads the first line of an answer. If it names a verb from a fixed list, the script performs it in plain Python. Each verb only reads, or writes inside the studio folder, and returns a small fixed answer. Anything else the model writes is only text. It is kept in a private transcript for 14 days and never journaled, shown or sent.
- **What gets written is checked.** A journal line or a piece is plain text: no links, no e-mail addresses, no markup, no hidden characters, capped in length. A line that fails is refused, and the agent is told why.
- **Only the script reaches outside.** The weather comes from one host, `api.open-meteo.com`. Reading, when it is on, comes only from the hosts of the approved sources. Every fetch is https only, one try, with a size cap and no cookies. The model never talks to the web.
- **Reading is off.** It stays off until the author sets `reading.start_date` and lists sources. Use only official APIs or feeds whose terms allow this use. If a source's terms are unclear, leave it out.
- **The channel is off.** The channel is a private two-way line to the person. It stays off until `channel.chat_id` is set. Only messages from `channel.allowed_sender_id` count. The studio never polls a chat service itself. It reads message files another process writes, and it posts only through a command the author names. The model never reaches either side.
- **Pulses are not instructions.** The system prompt says so: pulses and verb results come from sensors, files and the night itself. They are things that happen.
- **Hard limits.** Per wake-up: wall-clock time (default 5 minutes), turns (default 12), answer length (default 1200 characters), tokens (default 150000). Per night: a token allowance (default 400000). The script reads the usage from each turn and stops at the limit.
- **A kill switch.** While the file `<studio_dir>/OFF` exists, nothing starts, and a running wake-up stops within a second. `studio off` makes it, `studio on` removes it.
- **It ends by itself.** A hung model is killed by the turn timeout, then by the wall-clock deadline, then by the unit's own timeout. The timer unit runs at low priority with idle disk access, so backups and other night jobs are not slowed. The studio takes no lock any other job uses.
- **Nothing private on disk or on the command line.** The system prompt holds the identity section. It is never written to disk, never printed and never kept in a transcript. It is not passed as a command-line argument either, because any local account can read another process's arguments. The script puts it in a sealed in-memory file and hands the model command `--system-prompt-file /dev/fd/<n>`; only the same user can open that. A dry run prints `[identity: N characters from <path>]` in its place.
- **A failure still gets written down.** If anything inside a wake-up breaks, the wake-up ends with reason `error`, and the tokens already spent still go into the night's allowance. Each closing write (journal, paper file, transcript, ledger) fails alone. `wakeups.jsonl` and `status` may add one fixed word after the reason: `auth` when the model command could not log in, or `write-failed:<what>`. The model command's own error text is never kept.
- **Leftovers are swept.** In token mode each run gets an empty CLI config folder, `state/cli-config-<pid>-<n>`, removed when the run ends. If a run is killed hard (power loss, out of memory), the next wake-up removes any such folder that is not its own. A backup may skip `state/cli-config-*`.
- **Secrets stay out.** A token, if the author uses one, comes from a command at run time and goes only into the model's environment. It is never logged.

## Install

You need Linux, Python 3.12 and the `claude` command. The studio uses only the Python standard library.

1. Copy the engine next to the hooks:

   ```bash
   cp -r studio ~/.claude/scripts/studio
   ```

   Nothing runs from the clone. Its branch can change under it.

2. Write a config file. Start from `templates/studio-config.json` (every key with its default) or `examples/studio-config-example.json` (filled in for an invented agent in an invented town):

   ```bash
   mkdir -p ~/.config/studio
   cp examples/studio-config-example.json ~/.config/studio/config.json
   ```

   Set at least `identity.path` (your portrait), the two names, the town, and the time zone of the window. Then check it:

   ```bash
   PYTHONPATH=~/.claude/scripts python3 -P -m studio config check
   ```

   `-P` keeps the working directory off the import path, so a folder named `studio` in the current directory is never imported by mistake.

3. Look before anything runs:

   ```bash
   PYTHONPATH=~/.claude/scripts python3 -P -m studio wake --dry-run
   PYTHONPATH=~/.claude/scripts python3 -P -m studio wake --fake-model
   ```

   The dry run uses no model, writes nothing and fetches nothing. The fake run plays a short built-in script in a temporary folder.

4. Measure first. This runs the real model a few times in temporary folders and prints the tokens of each kind of wake-up:

   ```bash
   PYTHONPATH=~/.claude/scripts python3 -P -m studio measure
   ```

   Set `limits.wakeup_tokens` and `limits.daily_tokens` from what it prints.

5. Add a user timer and service. Replace `<CONFIG>` and `<TIME_ZONE>`. The timer fires every minute inside the window. It does not start a long-running process. Each fire looks whether a wake-up is due.

   `~/.config/systemd/user/studio-tick.timer`:

   ```ini
   [Unit]
   Description=Studio: look every minute in the night window whether a wake-up is due

   [Timer]
   OnCalendar=*-*-* 02..05:*:00 <TIME_ZONE>
   AccuracySec=1s
   Persistent=false

   [Install]
   WantedBy=timers.target
   ```

   `~/.config/systemd/user/studio-tick.service`:

   ```ini
   [Unit]
   Description=Studio: run a planned night wake-up when one is due

   [Service]
   Type=oneshot
   Environment=PYTHONPATH=%h/.claude/scripts
   ExecStart=/usr/bin/python3 -P -m studio --config <CONFIG> tick
   TimeoutStartSec=480
   Nice=15
   IOSchedulingClass=idle
   CPUWeight=20
   MemoryMax=1500M
   ```

   Then:

   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now studio-tick.timer
   ```

   The window in `OnCalendar` must cover the config's `schedule.window_start` to `schedule.end_by`. Add an `OnFailure=` line if you have a failure alert unit.

6. Add the studio folder to your backup. It holds the journal. Keep it out of git.

### Authentication

Two ways, both set in `model`:

- **The machine's own login.** Leave `model.auth_token_cmd` null. The run uses the `claude` login of the user.
- **A token from a command.** Set `model.auth_token_cmd` to a command that prints a token, such as a password-manager helper. The script runs it once per wake-up and passes the token to the model in `model.auth_token_env` only, with a fresh, empty `CLAUDE_CONFIG_DIR` that is deleted after the run. Use this when the machine login puts account details into every context.

## Undo

```bash
systemctl --user disable --now studio-tick.timer
rm ~/.config/systemd/user/studio-tick.timer ~/.config/systemd/user/studio-tick.service
systemctl --user daemon-reload
rm -r ~/.claude/scripts/studio
```

The studio folder stays. It is the agent's journal. Delete it by hand only if the person wants it gone. To pause without removing anything, run `studio off`.

## Commands

Run as `PYTHONPATH=~/.claude/scripts python3 -P -m studio [--config PATH] [--studio-dir PATH] <command>`. A small wrapper script named `studio` on your PATH makes this shorter.

| Command                                                             | What it does                                                                                                                        |
| ------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `status`                                                            | On or off, the folder, tonight's plan, tokens tonight, the last wake-up, reading, channel and paper.                                |
| `tick`                                                              | What the timer runs. Inside the window: makes the night's plan if there is none, marks missed starts, runs at most one due wake-up. |
| `wake`                                                              | One wake-up now, outside the plan. Real model, real folder. Respects the kill switch and the allowance. Inside the window it ends by `end_by`; between `end_by` and `window_end` it is refused (`late`). |
| `wake --dry-run`                                                    | No model, no writes, no network. Prints the system prompt (identity replaced), the waking message and three pulses.                 |
| `wake --fake-model`                                                 | The whole loop with a scripted model, in a temporary folder.                                                                        |
| `measure [--kinds quiet,song,journal,busy] [--no-network] [--keep]` | At most four real runs in temporary folders. Prints turns, time and tokens for each.                                                |
| `off` / `on`                                                        | Create or remove the kill switch.                                                                                                   |
| `journal tail [-n N]`                                               | Print the last N journal entries.                                                                                                   |
| `plan [--night YYYY-MM-DD]`                                         | Print a night's plan.                                                                                                               |
| `config check`                                                      | Load the config and print the resolved keys.                                                                                        |

Exit codes: 0 ok or skipped, 1 a failure, 2 a usage or config error. Output is counts, status words, times and paths, never model text, except `journal tail`.

## Config

One JSON file. The path comes from `--config`, else `STUDIO_CONFIG`, else `~/.config/studio/config.json`. `STUDIO_DIR` overrides `studio_dir` (for tests and dry runs). `~` is expanded in every path. A missing key takes its default. An unknown key or a wrong type is an error that names the key.

The rest of Essence takes its settings from environment variables. The studio has too many settings for that, so it is the one exception: one file.

| Key                                                                                                            | Default                     | What it sets                                                                                                                                                              |
| -------------------------------------------------------------------------------------------------------------- | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `version`                                                                                                      | `1`                         | Must be 1.                                                                                                                                                                |
| `studio_dir`                                                                                                   | `"~/studio"`                | The studio folder.                                                                                                                                                        |
| `kill_switch`                                                                                                  | `null`                      | The kill-switch file. Null: `<studio_dir>/OFF`.                                                                                                                           |
| `names.agent`                                                                                                  | `"the agent"`               | The agent's name in the system prompt.                                                                                                                                    |
| `names.person`                                                                                                 | `"the person"`              | The person's name in the system prompt.                                                                                                                                   |
| `town.name`                                                                                                    | `null`                      | The agent's town. Null turns the sky sense and the `window` and `sun` verbs off.                                                                                          |
| `town.latitude`                                                                                                | `0.0`                       | -90 to 90.                                                                                                                                                                |
| `town.longitude`                                                                                               | `0.0`                       | -180 to 180.                                                                                                                                                              |
| `town.time_zone`                                                                                               | `"UTC"`                     | The clock the agent sees on waking, and the journal headings.                                                                                                             |
| `schedule.time_zone`                                                                                           | `"UTC"`                     | The window, the night's date and the file names.                                                                                                                          |
| `schedule.window_start`                                                                                        | `"02:00"`                   | Start of the night window.                                                                                                                                                |
| `schedule.window_end`                                                                                          | `"06:00"`                   | End of the night window.                                                                                                                                                  |
| `schedule.end_by`                                                                                              | `null`                      | Every wake-up ends by this time. Null: `window_end`.                                                                                                                      |
| `schedule.count`                                                                                               | `3`                         | Wake-ups per night, 0 to 6.                                                                                                                                               |
| `schedule.min_gap_minutes`                                                                                     | `30`                        | Minimum time between two starts.                                                                                                                                          |
| `limits.wall_seconds`                                                                                          | `300`                       | Hard ceiling per wake-up, 30 to 900.                                                                                                                                      |
| `limits.min_seconds`                                                                                           | `120`                       | Each wake-up's planned length is drawn between this and `wall_seconds`.                                                                                                   |
| `limits.max_turns`                                                                                             | `12`                        | Messages sent per wake-up, the waking message included, 1 to 40.                                                                                                          |
| `limits.turn_timeout_seconds`                                                                                  | `90`                        | Longest wait for one answer.                                                                                                                                              |
| `limits.max_answer_chars`                                                                                      | `1200`                      | Longer answers are cut.                                                                                                                                                   |
| `limits.wakeup_tokens`                                                                                         | `150000`                    | Tokens per wake-up (input, cache write, cache read and output added).                                                                                                     |
| `limits.daily_tokens`                                                                                          | `400000`                    | Tokens per night.                                                                                                                                                         |
| `pulse.min_seconds`                                                                                            | `20`                        | Shortest gap before the next pulse.                                                                                                                                       |
| `pulse.max_seconds`                                                                                            | `60`                        | Longest gap before the next pulse.                                                                                                                                        |
| `pulse.song_seconds`                                                                                           | `15`                        | The gap while a song is on.                                                                                                                                               |
| `pulse.quiet_chance`                                                                                           | `0.6`                       | When nothing changed: the chance of one unchanged reading instead of a quiet word.                                                                                        |
| `identity.path`                                                                                                | `null`                      | The file that holds the identity text (the portrait). Null or unreadable: no wake-up.                                                                                     |
| `identity.start`                                                                                               | `"### 1. "`                 | Line prefix that starts the identity section (included).                                                                                                                  |
| `identity.end`                                                                                                 | `"### 2. "`                 | Line prefix that ends it (excluded).                                                                                                                                      |
| `identity.max_chars`                                                                                           | `12000`                     | A longer section: no wake-up.                                                                                                                                             |
| `model.command`                                                                                                | `["claude"]`                | The model command, as a list.                                                                                                                                             |
| `model.name`                                                                                                   | `"opus"`                    | The model.                                                                                                                                                                |
| `model.auth_token_cmd`                                                                                         | `null`                      | A command that prints a token. Null: the machine's login.                                                                                                                 |
| `model.auth_token_env`                                                                                         | `"CLAUDE_CODE_OAUTH_TOKEN"` | Where the token goes. `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY`.                                                                                                   |
| `senses.sky`, `.body`, `.house`, `.song`                                                                       | `true`                      | Each sense on or off.                                                                                                                                                     |
| `weather.enabled`                                                                                              | `true`                      | Weather from Open-Meteo. Off: the sky is sun and moon only.                                                                                                               |
| `weather.cache_minutes`                                                                                        | `30`                        | How long one weather reading is kept.                                                                                                                                     |
| `body.sys_root`                                                                                                | `"/"`                       | Where `/sys` and `/proc` are read (tests use a fake tree).                                                                                                                |
| `body.temps`                                                                                                   | `[]`                        | `{"hwmon": name, "label": words}` items. Empty: every temperature found, named by its sensor.                                                                             |
| `body.disk`                                                                                                    | `null`                      | One block device to watch. Null: all real disks.                                                                                                                          |
| `house.signals`                                                                                                | `[]`                        | `{"kind": "unit", "unit": "x.service", "running": words, "finished": words}` or `{"kind": "file", "path": path, "changed": words}`. The words are what the agent is told. |
| `verbs.window`, `.sun`, `.temperature`, `.journal`, `.write`, `.song`, `.read`, `.paper`, `.nothing`, `.sleep` | `true`                      | Each verb on or off.                                                                                                                                                      |
| `reading.start_date`                                                                                           | `null`                      | `"YYYY-MM-DD"`. Null or in the future: reading is off.                                                                                                                    |
| `reading.sources`                                                                                              | `[]`                        | `{"name": str, "kind": "rss" or "atom" or "shelf", "url": https}`. The allowed hosts are the hosts of these URLs. `shelf` reads `*.txt` from `shelf/`.                    |
| `reading.max_chars`                                                                                            | `4000`                      | Length cap of one item.                                                                                                                                                   |
| `channel.chat_id`                                                                                              | `null`                      | Null: the channel is off.                                                                                                                                                 |
| `channel.allowed_sender_id`                                                                                    | `null`                      | The one sender whose messages count. Null: every message is ignored.                                                                                                      |
| `channel.inbox_dir`                                                                                            | `null`                      | Where another process writes incoming messages as files.                                                                                                                  |
| `channel.post_command`                                                                                         | `null`                      | A command that posts text from its stdin. Null: never posts.                                                                                                              |
| `channel.post_piece`                                                                                           | `false`                     | Post the night's piece after the last wake-up.                                                                                                                            |
| `paper.enabled`                                                                                                | `true`                      | Write the morning piece file. Off: the `paper` verb is gone too.                                                                                                          |
| `paper.dir`                                                                                                    | `null`                      | Where the piece files go. Null: `<studio_dir>/for-the-paper`.                                                                                                             |
| `journal.max_line_chars`                                                                                       | `280`                       | Longest journal line.                                                                                                                                                     |
| `journal.max_lines_per_wakeup`                                                                                 | `3`                         | Lines the agent can write per wake-up.                                                                                                                                    |
| `journal.tail_entries`                                                                                         | `5`                         | Entries the `journal` verb shows.                                                                                                                                         |
| `transcripts.keep_days`                                                                                        | `14`                        | Days a wake-up's messages are kept. 0: none are kept.                                                                                                                     |

Checks on load: `window_start` is before `end_by`, and `end_by` is not after `window_end`, on the same day. `min_seconds` is at most `wall_seconds`. `pulse.min_seconds` is at most `pulse.max_seconds`. Every time zone loads.

## The studio folder

```
~/studio/                0700
  journal.md             0600   the journal
  jukebox/               0700   song files
  shelf/                 0700   local reading items, used only when reading is on
  for-the-paper/         0700   one piece file per night
  state/                 0700   the plan, usage, wake-up log, caches, transcripts, the lock
  OFF                           the kill switch, when present
```

The engine makes it on the first real run. Nothing in it goes into git.

## Tests

The tests run offline with a fake `claude` that speaks the same stream format. No network, no real model, temporary folders only.

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile studio/*.py
```

`tests/test_studio_public.py` also checks that the studio files hold nothing personal.

## Credits

Weather data by Open-Meteo.com (CC BY 4.0).
