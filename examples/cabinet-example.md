Invented example. Sara, Max and the class do not exist.

# Cabinets

Written 2027-01-20.

## The rules

- A pigment goes into a cabinet before it goes anywhere else.
- A brush is loaded only for the job at hand, at run time. The pigment is never written to disk beside the work.
- No Essence file holds a pigment. Only which cabinet, and which drawer: the item's name.
- A pigment never passes through the conversation.

## The keys to the cabinets

- One file on Max's laptop holds the agent's access token for the "Class" vault, readable only by the agent's user (Max, 2027-01-20, record). No other secret file is allowed there.

## Cabinet: Max's password manager

- What it is: Max's password manager, read through an agent token named "class-agent". Every read carries a reason and shows in Max's audit log.
- Helper: `class-secret "<reason>" <item> [field]`. It prints one field and logs the reason.
- May open: vault "Class" only.
- Holds: "Store account" (the store account brush) and "Recipe printer" (the printer brush).
- Never holds or used for: Max's own logins, the school's staff system, any parent's details.
- Key: one token file, readable only by the agent's user. It expires 2028-01-20.
- Owner: Max.
- Taken away: Max revokes "class-agent" in the password manager's settings.
