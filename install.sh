#!/usr/bin/env bash
# =============================================================================
# Essence installer: the mechanical part of docs/setup.md.
# =============================================================================
# Run it from the repository folder:
#     ./install.sh [--dry-run] [--tz ZONE] [--person NAME] [--agent NAME]
#     ./install.sh --uninstall [--dry-run]
#
# Install does five things, and is safe to run again (for example after a git pull):
#   1. Checks the tools the hooks need.
#   2. Copies the hook scripts to ~/.claude/scripts/. A script that is already there and differs is backed up first.
#   3. Makes ~/.claude/essence/ (mode 700) with landscapes/, strokes/ and brushes/.
#   4. Copies the portrait template and the example check rules, ONLY if those files do not exist yet.
#   5. Adds the Essence hook entries from examples/settings-hooks.json to ~/.claude/settings.json.
#      Old Essence entries are removed first, so a second run does not add copies. Your other hooks and
#      settings stay. The old file is backed up as settings.json.bak-<time> before any change.
#
# --tz ZONE      the time zone the time hook shows (an IANA name such as Europe/Berlin). Without it the hook
#                uses the machine's time zone.
# --person NAME  sets ESSENCE_PERSON in the env block of settings.json.
# --agent NAME   sets ESSENCE_AGENT in the env block of settings.json.
# --dry-run      prints what it would do, and changes nothing.
# --uninstall    removes the Essence hook entries, the two name settings and the copied scripts.
#                It never touches ~/.claude/essence/ (your portrait). Remove that by hand if you want it gone.
#
# It never overwrites a portrait, a checks.json or a broken settings.json.
# Exit codes: 0 done, 1 a check failed or a file is broken, 2 a usage error.
# =============================================================================
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_HOME="$HOME/.claude"
SCRIPTS="$CLAUDE_HOME/scripts"
ESSENCE="$CLAUDE_HOME/essence"
SETTINGS="$CLAUDE_HOME/settings.json"
STAMP="$(date +%Y%m%d-%H%M%S)"
HOOK_FILES=(session-start-verify.sh essence-synthesize.sh essence-reduce.py essence-scan.py
            essence-nudge.py essence-now.sh essence-check.py essence-brush-rules.py)

DRY=0; UNINSTALL=0; TZ_NAME=""; PERSON=""; AGENT=""
usage() { sed -n '5,7p' "$0" | sed 's/^# \{0,5\}//' >&2; exit 2; }
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift;;
    --uninstall) UNINSTALL=1; shift;;
    --tz) TZ_NAME="${2:-}"; [ -n "$TZ_NAME" ] || usage; shift 2;;
    --person) PERSON="${2:-}"; [ -n "$PERSON" ] || usage; shift 2;;
    --agent) AGENT="${2:-}"; [ -n "$AGENT" ] || usage; shift 2;;
    -h|--help) usage;;
    *) echo "install.sh: unknown argument $1" >&2; usage;;
  esac
done

t() { printf '%s' "${1/#"$HOME"/\~}"; }   # a path as the reader types it: ~/... instead of the full home path
say() { if [ "$DRY" = 1 ]; then echo "would: $*"; else echo "done:  $*"; fi; }
newtmp() {   # a temporary file for the new settings: next to settings.json, or outside ~/.claude on a dry run
  if [ "$DRY" = 1 ]; then mktemp "${TMPDIR:-/tmp}/essence-settings.XXXXXX"; else mkdir -p "$CLAUDE_HOME"; mktemp "$CLAUDE_HOME/settings.json.new.XXXXXX"; fi
}
run() { if [ "$DRY" = 0 ]; then "$@"; fi; }   # run a command unless this is a dry run
fail() { echo "install.sh: $*" >&2; exit 1; }

if [ ! -f "$REPO/examples/settings-hooks.json" ] || [ ! -d "$REPO/hooks" ]; then fail "run this from the Essence repository"; fi
if [ -n "${CLAUDE_CONFIG_DIR:-}" ] && [ "$(cd "$CLAUDE_CONFIG_DIR" 2>/dev/null && pwd)" != "$(cd "$CLAUDE_HOME" 2>/dev/null && pwd)" ]; then
  fail "CLAUDE_CONFIG_DIR is set to $CLAUDE_CONFIG_DIR. This installer and the hooks support only ~/.claude."
fi

# --- 1. tools ------------------------------------------------------------------------------------
missing=0
for t in python3 jq shasum sha256sum; do
  command -v "$t" >/dev/null 2>&1 || { echo "missing: $t" >&2; missing=1; }
done
stat -c %s "$REPO/install.sh" >/dev/null 2>&1 || { echo "missing: GNU stat (stat -c). The synthesis needs it." >&2; missing=1; }
[ "$missing" = 0 ] || fail "install the missing tools first (see docs/setup.md, Before you start)"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))' || fail "python3 is older than 3.8"
command -v claude >/dev/null 2>&1 || echo "warning: the claude command is not on PATH. The synthesis needs it." >&2

# The jq filter that removes every hook entry that runs an Essence script, and any group or event left empty.
STRIP='def essence: (.command // "") | test("\\.claude/scripts/(session-start-verify\\.sh|essence-[A-Za-z-]+\\.(sh|py))");
  if (.hooks | type) == "object" then
    .hooks |= (with_entries(.value |= (map(.hooks |= map(select(essence | not))) | map(select((.hooks | length) > 0))))
               | with_entries(select((.value | length) > 0)))
    | if .hooks == {} then del(.hooks) else . end
  else . end'

# write_settings NEWFILE: back up settings.json and replace it with NEWFILE, or show the change on a dry run.
write_settings() {
  local new="$1"
  if [ -f "$SETTINGS" ] && cmp -s <(jq -S . "$SETTINGS") <(jq -S . "$new"); then
    echo "same:  $(t "$SETTINGS") already has these entries; not changed"; rm -f "$new"; return 0
  fi
  if [ "$DRY" = 1 ]; then
    echo "would: change $(t "$SETTINGS") like this:"
    diff -u --label "settings.json now" --label "settings.json after" <(if [ -f "$SETTINGS" ]; then jq -S . "$SETTINGS"; else echo "{}"; fi) <(jq -S . "$new") || true
    rm -f "$new"; return 0
  fi
  if [ -f "$SETTINGS" ]; then
    cp -p "$SETTINGS" "$SETTINGS.bak-$STAMP"
    echo "done:  backed up $(t "$SETTINGS") to $(t "$SETTINGS.bak-$STAMP")"
    chmod --reference="$SETTINGS" "$new" 2>/dev/null || true
  else
    chmod 600 "$new"
  fi
  mv "$new" "$SETTINGS"
  echo "done:  wrote $(t "$SETTINGS")"
}

if [ -f "$SETTINGS" ] && ! jq empty "$SETTINGS" >/dev/null 2>&1; then
  fail "$(t "$SETTINGS") is not valid JSON. Fix it first (jq empty $(t "$SETTINGS") shows where). Nothing was changed."
fi

# --- uninstall -----------------------------------------------------------------------------------
if [ "$UNINSTALL" = 1 ]; then
  if [ -f "$SETTINGS" ]; then
    tmp="$(newtmp)"
    jq "$STRIP"' | if (.env | type) == "object" then .env |= del(.ESSENCE_PERSON, .ESSENCE_AGENT)
                   | if .env == {} then del(.env) else . end else . end' "$SETTINGS" > "$tmp"
    write_settings "$tmp"
  fi
  for f in "${HOOK_FILES[@]}"; do
    [ -e "$SCRIPTS/$f" ] || continue
    run rm -f "$SCRIPTS/$f"; say "removed $(t "$SCRIPTS/$f")"
  done
  echo "kept:  $(t "$ESSENCE") (your portrait and the other Essence files). Remove it by hand only if you want it gone."
  exit 0
fi

# --- 2. scripts ----------------------------------------------------------------------------------
[ -d "$SCRIPTS" ] || { run mkdir -p "$SCRIPTS"; say "made $(t "$SCRIPTS")"; }
for f in "${HOOK_FILES[@]}"; do
  src="$REPO/hooks/$f"; dst="$SCRIPTS/$f"
  if [ -e "$dst" ] && cmp -s "$src" "$dst"; then echo "same:  $(t "$dst")"; continue; fi
  if [ -e "$dst" ]; then run cp -p "$dst" "$dst.bak-$STAMP"; say "backed up $(t "$dst") to $(t "$dst.bak-$STAMP")"; fi
  run cp "$src" "$dst"; run chmod 700 "$dst"; say "copied $f to $(t "$SCRIPTS") (mode 700)"
done

# --- 3. the essence folder -----------------------------------------------------------------------
for d in "$ESSENCE" "$ESSENCE/landscapes" "$ESSENCE/strokes" "$ESSENCE/brushes"; do
  [ -d "$d" ] || { run mkdir -p "$d"; say "made $(t "$d")"; }
done
if [ ! -d "$ESSENCE" ] || [ "$(stat -c %a "$ESSENCE")" != 700 ]; then run chmod 700 "$ESSENCE"; say "set $(t "$ESSENCE") to mode 700"; fi

# --- 4. first files, never overwritten -------------------------------------------------------------
copy_once() {   # copy_once SOURCE TARGET
  if [ -e "$2" ]; then echo "kept:  $(t "$2") exists; not overwritten"; return 0; fi
  run cp "$1" "$2"; run chmod 600 "$2"; say "copied $(basename "$1") to $(t "$2") (mode 600)"
}
copy_once "$REPO/templates/portrait.md" "$ESSENCE/portrait.md"
copy_once "$REPO/examples/checks-example.json" "$ESSENCE/checks.json"

# --- 5. settings.json ------------------------------------------------------------------------------
if [ -n "$TZ_NAME" ]; then
  if ! [[ "$TZ_NAME" =~ ^[A-Za-z0-9_+/-]+$ ]] || ! python3 -c 'import sys, zoneinfo; zoneinfo.ZoneInfo(sys.argv[1])' "$TZ_NAME" 2>/dev/null; then
    fail "unknown time zone: $TZ_NAME (use an IANA name such as Europe/Berlin)"
  fi
  TZ_PREFIX="ESSENCE_TZ=$TZ_NAME "
else
  TZ_PREFIX=""
fi
tmp="$(newtmp)"
{ if [ -f "$SETTINGS" ]; then cat "$SETTINGS"; else echo '{}'; fi; } | jq --slurpfile block "$REPO/examples/settings-hooks.json" --arg tz "$TZ_PREFIX" --arg person "$PERSON" --arg agent "$AGENT" "
  ($STRIP)
  | (\$block[0] | walk(if type == \"string\" then sub(\"ESSENCE_TZ=YOUR_TIME_ZONE \"; \$tz) else . end) | .hooks) as \$b
  | .hooks = (reduce (\$b | keys[]) as \$k ((.hooks // {}); .[\$k] = ((.[\$k] // []) + \$b[\$k])))
  | if \$person != \"\" then .env.ESSENCE_PERSON = \$person else . end
  | if \$agent != \"\" then .env.ESSENCE_AGENT = \$agent else . end
" > "$tmp"
write_settings "$tmp"

echo
echo "Next: write section 1 of $(t "$ESSENCE/portrait.md") with your agent, then start a new Claude Code session."
echo "See docs/setup.md, Your first session."
