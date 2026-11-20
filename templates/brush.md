<!--
Essence brush template. Copy to ~/.claude/essence/brushes/<name>.md, add a line to brushes/INDEX.md,
and list it in the landscapes whose work uses it.
A brush is one ability: the login, role, token or tool that lets the agent make a mark on the world.
A stroke says how to do a thing. A brush is what can. Permissions belong here, because only a brush touches the world.
A brush makes no mark until it is loaded with its pigment: the secret (a token, a password, a key). The pigment lives in
a cabinet: a password-manager vault. NEVER write a pigment in this file. Write only the drawer (the item name) and the
cabinet (the vault, and the helper that reads it). Write "none" for a brush that needs no pigment, like a local tool.
Mark each fact: checked YYYY-MM-DD (seen with a read-only command) or record (a named record says so).
The synthesis never edits a brush.
A rule that belongs to the ability (for example: read the platform's current docs first) goes in a short
"## Before you use this brush" part right under the Written line. hooks/essence-brush-rules.py keeps it there.
-->
# Brush: NAME

Written YYYY-MM-DD.

## What it is
<!-- The login, role, token or tool, and who it acts as. -->

## Can reach
<!-- The exact scope: which accounts, repos, vaults, machines, verbs. -->

## Cannot
<!-- The limits that matter, including the ones people wrongly assume it has. -->

## Pigment and cabinet
<!-- Two lines. Never the value. -->
- Pigment: ITEM NAME, or none
- Cabinet: VAULT, read with HELPER, or none

## Granted by and when
<!-- Who gave it, the date, and when it expires. -->

## How to check it
<!-- One read-only command that proves it works and shows its scope. It must not print a secret. -->

## How to take it away
<!-- Who removes it, and where. -->

## Used by
<!-- The landscapes and strokes that need it. -->
