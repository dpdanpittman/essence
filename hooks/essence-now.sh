#!/usr/bin/env bash
# essence-now.sh: UserPromptSubmit hook. Puts the real current time in front of the agent on every message
# from the person, so the agent reads the time instead of estimating it, and how much time has passed.
#
# Why: an agent has no clock. It guesses the time from timestamps it happened to see in tool output, and the
# guess drifts. Asked for the time, it said "just after 2:00" at 1:40 and counted 20 minutes too
# few. A rule ("check the time") does not fix that; the fact, in front of it every turn, does.
# The same goes for durations: without them the agent cannot tell a quick reply from a person who was away for
# an hour, or a job that took two minutes from one that took forty. So the line also says how long it has been
# since the person's last message and since the session's first one.
#
# Prints one line, which Claude Code adds to the prompt as context. No model, no network.
# State: one small file per session under ${XDG_STATE_HOME:-~/.local/state}/essence-now/ holding two epoch
# seconds (first message, last message); files older than 7 days are removed. Any problem with the state only
# drops the duration part; the time is always printed.
# Set ESSENCE_TZ to the person's time zone (an IANA name such as America/Denver); without it, the machine's
# local time zone is used. UTC is always shown beside it, because tool output and logs use UTC.
set -u
zone="${ESSENCE_TZ:-}"
if [ -n "$zone" ]; then
  local_now=$(TZ="$zone" date '+%a %Y-%m-%d %-I:%M %p %Z')
else
  local_now=$(date '+%a %Y-%m-%d %-I:%M %p %Z')
fi
utc_now=$(date -u '+%H:%M')

human() { # seconds -> "under a minute" | "N min" | "H h M min" | "N days"
  local s=$1
  if [ "$s" -lt 60 ]; then printf 'under a minute'
  elif [ "$s" -lt 3600 ]; then printf '%d min' $(( s / 60 ))
  elif [ "$s" -lt 172800 ]; then printf '%d h %d min' $(( s / 3600 )) $(( s % 3600 / 60 ))
  else printf '%d days' $(( s / 86400 ))
  fi
}

since=""
input=$(cat 2>/dev/null || true)
sid=""
if command -v jq >/dev/null 2>&1; then
  sid=$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null || true)
fi
sid=$(printf '%s' "$sid" | tr -cd 'A-Za-z0-9_-' | cut -c1-80)
if [ -n "$sid" ]; then
  dir="${XDG_STATE_HOME:-$HOME/.local/state}/essence-now"
  if mkdir -p "$dir" 2>/dev/null && chmod 700 "$dir" 2>/dev/null; then
    f="$dir/$sid"
    now=$(date +%s)
    first=""; last=""
    if [ -f "$f" ]; then read -r first last < "$f" 2>/dev/null || true; fi
    case "$first" in ''|*[!0-9]*) first="";; esac
    case "$last" in ''|*[!0-9]*) last="";; esac
    if [ -n "$first" ] && [ -n "$last" ] && [ "$last" -le "$now" ] && [ "$first" -le "$last" ]; then
      since=" Since the last message: $(human $(( now - last ))). Session so far: $(human $(( now - first )))."
    else
      first=$now
      since=" First message of this session."
    fi
    printf '%s %s\n' "$first" "$now" > "$f.tmp" 2>/dev/null && mv -f "$f.tmp" "$f" 2>/dev/null || since=""
    find "$dir" -type f -mtime +7 -delete 2>/dev/null || true
  fi
fi

printf '[Now: %s (%s UTC).%s Use this, never estimate the time.]\n' "$local_now" "$utc_now" "$since"
