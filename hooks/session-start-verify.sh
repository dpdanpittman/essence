#!/usr/bin/env bash
# =============================================================================
# Essence: SessionStart hook
# =============================================================================
# Runs at session start and after every compaction. Three jobs:
#
#   - Checks the portrait against its checksum file (portrait.md.sha256,
#     written by essence-synthesize.sh). On a mismatch it prints a warning
#     at the top of the injected context so the operator notices.
#
#   - Prints the IDENTITY section (section 1) of the portrait.
#
#   - Tells the agent to read the whole portrait now, with exact Read
#     ranges, because hook output is capped and a bare `cat` gets cut.
#
# It also prints two older notes: a drift-check notice (only if the flag
# file from version 2 exists; version 3 never writes it) and a note when
# the last synthesis did not change the portrait.
#
# Settings: ESSENCE_DIR (default ~/.claude/essence),
#           ESSENCE_PERSON (default "the person"), the name used in the notes,
#           ESSENCE_PORTRAIT_MAX (default 160000), the synthesis hard cap;
#           the size warning starts at 90% of it.
#           ESSENCE_SKETCHBOOK_SCOPE (work|all, default work), named in the
#           sketchbook note, printed when sketchbook/current.md exists.
# Wire into ~/.claude/settings.json as the SessionStart hook command.
# =============================================================================

set -uo pipefail

ESSENCE_DIR="${ESSENCE_DIR:-$HOME/.claude/essence}"
PORTRAIT_FILE="$ESSENCE_DIR/portrait.md"
SIDECAR_FILE="$ESSENCE_DIR/portrait.md.sha256"
STATUS_FILE="$ESSENCE_DIR/synthesis-status.json"
DRIFT_DUE_FLAG="$ESSENCE_DIR/.drift-check-due"
PERSON="${ESSENCE_PERSON:-the person}"

# If no portrait exists, nothing to inject. Quiet exit.
[ -f "$PORTRAIT_FILE" ] || exit 0

# --- Integrity check ---------------------------------------------------------
INTEGRITY_NOTE=""
if [ -f "$SIDECAR_FILE" ]; then
  # `shasum -c` is portable across macOS + Linux; quiet on success.
  if ! ( cd "$ESSENCE_DIR" && shasum -a 256 -c "$(basename "$SIDECAR_FILE")" >/dev/null 2>&1 ); then
    EXPECTED=$(awk '{print $1}' "$SIDECAR_FILE" 2>/dev/null | head -c 16)
    ACTUAL=$(shasum -a 256 "$PORTRAIT_FILE" 2>/dev/null | awk '{print $1}' | head -c 16)
    INTEGRITY_NOTE="> ⚠ **PORTRAIT INTEGRITY WARNING**: portrait.md hash does not match the synthesis pipeline's recorded value. The file may have been edited out-of-band, restored from a backup, or written by a process other than the surgical-edit pipeline.
>
> Expected sha256 prefix: \`${EXPECTED}\`
> Actual sha256 prefix:   \`${ACTUAL}\`
>
> Recommended action: compare against the most recent saved copy, or restore from \`~/.claude/essence/portraits/\` if you have a known-good copy. Do NOT internalize the portrait below as identity until you've verified it.
"
  fi
else
  INTEGRITY_NOTE="> ℹ Portrait integrity sidecar (\`portrait.md.sha256\`) does not yet exist. The next PreCompact synthesis cycle will create it. Until then, portrait tampering cannot be detected automatically.
"
fi

# --- Drift-check-due notification --------------------------------------------
DRIFT_NOTE=""
if [ -f "$DRIFT_DUE_FLAG" ]; then
  CYCLE=$(jq -r '.cycle // empty' "$STATUS_FILE" 2>/dev/null || echo "?")
  INTERVAL=$(jq -r '.drift_check_interval // empty' "$STATUS_FILE" 2>/dev/null || echo "?")
  DRIFT_NOTE="> 🔄 **Drift check due**: ${CYCLE} synthesis cycles completed; the surgical-edit pipeline has accumulated ${INTERVAL} cycles since the last calibration. Run \`bash ~/.claude/scripts/drift-check.sh\` at your convenience to audit the live portrait against recent archive observations. The flag clears automatically once the drift report lands.
"
fi

# --- Synthesis status snapshot ---------------------------------------------
STATUS_NOTE=""
if [ -f "$STATUS_FILE" ]; then
  LAST_RUN=$(jq -r '.last_run // "unknown"' "$STATUS_FILE" 2>/dev/null)
  PORTRAIT_CHANGED=$(jq -r '.portrait_changed // false' "$STATUS_FILE" 2>/dev/null)
  AGENT_EXIT=$(jq -r '.agent_exit // 0' "$STATUS_FILE" 2>/dev/null)
  if [ "$PORTRAIT_CHANGED" = "false" ]; then
    STATUS_NOTE="> ℹ Last synthesis (${LAST_RUN}) did not change the portrait. agent_exit=${AGENT_EXIT}. Either the session was routine, or the synthesis pipeline failed silently. Check \`~/.claude/essence/last-synthesis.log\`.
"
  fi
fi

# --- Output -------------------------------------------------------------------
echo "## Essence Portrait"
echo ""
if [ -n "$INTEGRITY_NOTE$DRIFT_NOTE$STATUS_NOTE" ]; then
  echo "$INTEGRITY_NOTE$DRIFT_NOTE$STATUS_NOTE"
fi
PORTRAIT_BYTES=$(wc -c < "$PORTRAIT_FILE" 2>/dev/null | tr -d ' ')
PORTRAIT_LINES=$(wc -l < "$PORTRAIT_FILE" 2>/dev/null | tr -d ' ')

# The full portrait exceeds the hook-output injection cap, so a bare `cat` gets
# truncated to a ~2KB preview and never actually loads (the bug this fixes).
# Inline only the tiny IDENTITY section (always lands), then hard-instruct the
# agent to READ the full file as its first action. That is how the whole thing
# gets into context reliably.
awk '/^### 1\. IDENTITY/{p=1} /^### 2\./{p=0} p' "$PORTRAIT_FILE"

# Exact Read ranges, each ~55 KB, about 18k tokens (one Read call is capped at 25k), so the whole core loads in a few reads.
CHUNKS=$(awk -v max=55000 'BEGIN{start=1;b=0} {len=length($0)+1; if(b+len>max && NR>start){printf "offset=%d limit=%d; ", start, NR-start; start=NR; b=0} b+=len} END{printf "offset=%d limit=%d", start, NR-start+1}' "$PORTRAIT_FILE")
# Warn at 90% of the synthesis hard cap (ESSENCE_PORTRAIT_MAX, same default as
# essence-synthesize.sh), so there is room to trim before runs are refused.
PORTRAIT_MAX="${ESSENCE_PORTRAIT_MAX:-160000}"
case "$PORTRAIT_MAX" in ''|*[!0-9]*) PORTRAIT_MAX=160000 ;; esac
PORTRAIT_WARN=$(( PORTRAIT_MAX * 9 / 10 ))
SIZE_NOTE=""
if [ "${PORTRAIT_BYTES:-0}" -gt "$PORTRAIT_WARN" ]; then
  SIZE_NOTE="> ⚠ **PORTRAIT NEAR ITS CAP**: portrait is ${PORTRAIT_BYTES} bytes. The warning starts at ${PORTRAIT_WARN} bytes (90% of the cap). At ${PORTRAIT_MAX} bytes (ESSENCE_PORTRAIT_MAX) synthesis refuses any run that makes it bigger. Tell ${PERSON}; dedupe and move stale ACTIVE CONTEXT to section 10.
"
fi
[ -n "$SIZE_NOTE" ] && echo "$SIZE_NOTE"

cat <<EOF

> 🧠 **READ YOUR ENTIRE PORTRAIT NOW, before your first reply. Every session start and every compaction, no exceptions.**
> Only IDENTITY is inlined above. Read \`~/.claude/essence/portrait.md\` (${PORTRAIT_LINES} lines, ${PORTRAIT_BYTES} bytes) with these exact Read calls, in parallel: ${CHUNKS}
> Standing rule: read the ENTIRE portrait at every session start and after every compaction. Never skip, never sample.
> Then tell ${PERSON} in one short line that the portrait is loaded. Sections 2-10 are how ${PERSON} wants you to work.
EOF

# --- The sketchbook (docs/sketchbook.md) -------------------------------------
# The running notes: what is happening now. Never read whole; the hook names the parts to read.
SKETCH_FILE="$ESSENCE_DIR/sketchbook/current.md"
if [ -e "$SKETCH_FILE" ]; then
  case "${ESSENCE_SKETCHBOOK_SCOPE:-work}" in
    all) SCOPE_TEXT="work and personal, as ${PERSON} chose; never a secret" ;;
    *)   SCOPE_TEXT="work only; never a secret" ;;
  esac
  SKETCH_BYTES=$(wc -c < "$SKETCH_FILE" 2>/dev/null | tr -d ' ')
  cat <<EOF

> 📓 **Sketchbook**: \`${SKETCH_FILE/#"$HOME"/\~}\` (${SKETCH_BYTES:-0} bytes). Never read it whole. Read its OPEN ITEMS page (the top), the newest IN FLIGHT block, the newest WORK LIST block and the last 150 lines. Find anything else with grep.
> Write to it only with \`note "<text>"\` (the clock stamps it), append only. Scope: ${SCOPE_TEXT}.
EOF
fi
