#!/usr/bin/env bash
# essence-now.sh: UserPromptSubmit hook. Puts the real current time in front of the agent on every message
# from the person, so the agent reads the time instead of estimating it.
#
# Why: an agent has no clock. It guesses the time from timestamps it happened to see in tool output, and the
# guess drifts. Asked "when is my appointment?", it said "just after 2:00" at 1:40 and counted 20 minutes too
# few. A rule ("check the time") does not fix that; the fact, in front of it every turn, does.
#
# Prints one line, which Claude Code adds to the prompt as context. No model, no network, no state.
# Set ESSENCE_TZ to the person's time zone (an IANA name such as America/Denver); without it, the machine's
# local time zone is used. UTC is always shown beside it, because tool output and logs use UTC.
set -u
zone="${ESSENCE_TZ:-}"
if [ -n "$zone" ]; then
  local_now=$(TZ="$zone" date '+%a %Y-%m-%d %-I:%M %p %Z')
else
  local_now=$(date '+%a %Y-%m-%d %-I:%M %p %Z')
fi
printf '[Now: %s (%s UTC). Use this, never estimate the time.]\n' "$local_now" "$(date -u '+%H:%M')"
