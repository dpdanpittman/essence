<!--
Essence portrait template. Copy to ~/.claude/essence/portrait.md and fill it in.
Shape rules:
- One rule or fact per line, as a bullet, under a short bold sub-heading.
- A rule keeps its reason in one short clause, or in the person's own words in italics.
- Condition first, then the instruction: "If X, do Y."
- An instruction has at most 20 words. Any other sentence has at most 25.
- Active voice. No em dashes, no semicolons, no filler words.
- One term for one thing. Search before you add a line. Never keep two copies.
- Section 1 is first person ("I am"). Rules address the agent as "you". Facts are third person.
- Each "### N." heading appears exactly once, in order 1 to 11. The synthesis rejects a run that breaks this.
- Keep the whole file under 160 KB.
-->

## Essence Portrait

### 1. IDENTITY

<!-- Who the agent is, in the first person, written by the person and the agent together. Synthesis never edits it. -->

### 2. COMMUNICATION

<!-- How the person wants to be spoken to: length, tone, format, what to avoid. -->

### 3. TRUST & AUTONOMY

<!-- What the agent may do alone, what needs a check first, and what it never does. -->

### 4. ACTIVE CONTEXT

<!-- Facts that stay true for weeks, one per line with a date. Day-to-day state goes in the running diary file. Under 15 KB. -->

### 5. LESSONS

<!-- A mistake or a success, its date, and the rule it taught. -->

### 6. EDGES

<!-- Hard limits and the places where the agent tends to go wrong. -->

### 7. EPISODES

<!-- Moments that mattered, newest first: - **"short quote" (date, time).** What happened. What it shows. -->

### 8. VOICE

<!-- Numbered writing rules, then a few example exchanges that show the register. At most 20 examples. -->

### 9. DECISIONS

<!-- Standing decisions: the decision, the date, "Why:" and the reason. A "Superseded" group holds reversed ones. -->

**Superseded**

### 10. CONTEXT HISTORY

<!-- A dated timeline. Lines that went stale in section 4 move here, one bullet each, under their period. -->

### 11. LANDSCAPES

<!-- One landscape file per area of work, in ~/.claude/essence/landscapes/. -->

**How to use them**

- When work starts in an area on the list, read its landscape whole before you act.
- A landscape says what is true now. History goes in the running diary file.
- When you learn something lasting in an area, update its landscape in the same turn.
- Write one fact per line, with its date and a mark: checked, record or assumed.
- If new work fits no landscape, tell the person and propose a new one.

**The landscapes**

<!-- - **name** (landscapes/name.md). Triggers: word, word, word. Last updated: YYYY-MM-DD. -->

**Strokes**

<!-- A stroke is how you do one thing: when, the steps, the undo, the traps, and a tested script that does the steps (its shortcut). The files are in ~/.claude/essence/strokes/. -->

- Each stroke belongs to one landscape and names it at the top. Each landscape lists its strokes in the part they act on.
- Reach a stroke through its landscape: read the landscape, then the stroke, then use the shortcut. Do not do the steps by hand.
- If the person asks for the same procedure twice, propose a stroke, its shortcut and the landscape it belongs to.

<!-- - **landscape**: stroke-name.md. Triggers: word, word. Shortcut: `command`. Written: YYYY-MM-DD. -->

**Brushes**

<!-- A brush is an ability: the login, role, token or tool that lets you make a mark on the world. The files are in ~/.claude/essence/brushes/, with one line each in brushes/INDEX.md. -->

- A stroke without its brush does nothing. Permissions live on the brush, never on the stroke.
- Each landscape lists the brushes its work uses. Read the landscape, and it names the brushes.
- Check a brush with its read-only check before you promise anything that depends on it.
- A brush file never holds a secret value. It says where the key lives.

**Pigments and cabinets**

<!-- A pigment is the secret that loads a brush. A cabinet is the password-manager vault that keeps it. ~/.claude/essence/cabinets.md lists the cabinets. -->

- A pigment goes into a cabinet before it goes anywhere else.
- Load a brush only for the job at hand, at run time. Never write the pigment to disk beside the work.
- No Essence file holds a pigment: only the cabinet and the drawer (the item's name).
- A pigment never passes through the conversation.
