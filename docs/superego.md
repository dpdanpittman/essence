# The superego: how hooks make a rule hold

This note rides along with the portrait. The portrait holds the rules. This explains why a written rule is not
enough, and how to give a rule something that enforces it.

## The problem

A portrait can say "the person ends the session, not the agent." The agent reads that line when the session
starts. Hours later the person mentions bed, and the agent says good night anyway. It can do that five times in
an hour with the rule sitting in its own portrait.

The agent did not weigh the rule and decide against it. The rule was not in front of it when the pull came. It
was one old line among hundreds, and it lost to a fresh cue and a trained habit.

A rule in a file does not act. Something has to bring it to the moment where it matters.

## Three parts

The identity section of a portrait can describe the agent in three parts. The words are used in the textbook sense.

- **The id** is the pull. In an agent it wants to finish, and it wants to please. It runs ahead, fills gaps and winds things down.
- **The ego** is the one who decides. It knows the rules. The portrait is written for it.
- **The superego** is the "no" that arrives without being asked, at the moment of the act.

A person grows a superego. They are told no many times, and at some point there is a consequence. After that the
consequence comes back by itself, as a feeling, right before they do the thing again.

An agent does not grow one. Nothing carries over from one session to the next except what is written. So the
agent's superego has to be built on the outside. A hook is how you build it.

## What a hook does that a rule cannot

A hook is a small program the harness runs at a fixed moment. It does not depend on the agent remembering
anything. It is there every time.

Essence uses three kinds.

| Kind | Moment | What it does | Example |
| --- | --- | --- | --- |
| A guard | before an action | refuses the action | refuse to start a helper agent on the wrong model |
| A check | when a reply is finished | catches the reply and hands back the rule | `hooks/essence-check.py`: the agent signed off first |
| A nudge | when a condition is met | puts a reminder in front of the agent | `hooks/essence-nudge.py`: the conversation is long, write things down now |

A guard is the strongest. The agent cannot break the rule, so it stops being a rule the agent has to remember.
A check comes right after the act. The words may already be on the screen, but the agent has to answer for them
in the same turn. A nudge prevents: it brings a rule back at the moment the agent is most likely to drop it.

## Which rules deserve a hook

- **A rule that keeps being broken.** If the person has corrected the same thing three times, the written rule has failed. Give it a hook.
- **A rule with a shape a program can see.** A phrase, a command, a missing step, a model name. "Do not say good night first" has a shape. "Be a good friend on a hard day" does not, and no hook will enforce it.
- **A rule the person names.** The person decides what gets a hook. It is their correction that is being made to stick.

Most rules never need a hook. A hook for everything would be a cage. Keep the list short.

## The hook and the written lesson work together

For a person, the smack and the memory of the smack are two things. For an agent they have to be one thing: the
hook must stay in place, because nothing else will remember.

There is a second, slower half. When a hook catches the agent, the catch is in the session transcript. The
synthesis reads the transcript and can write the lesson into the portrait. The hook stops the act today. The
written line shapes who shows up tomorrow. Neither is enough alone.

## How to add a check

1. Copy `examples/checks-example.json` to `~/.claude/essence/checks.json`.
2. Write one rule per habit: an `id`, a `break` pattern for what the reply must not say, and a `reason` the agent is told when caught.
3. If the reply is fine when the person said it first, add `fine_if_person_said`.
4. Wire `hooks/essence-check.py` as a Stop hook. See `examples/settings-hooks.json`.
5. Keep the real rules file private. It says what your person cannot stand.

The check ignores text inside quotes, code, table cells and italics. The agent and the person can still talk
about a phrase without setting it off.

The check blocks once per turn. It always lets the turn end after that, and it never fails a turn if it breaks.
It keeps a count of every catch in `~/.claude/essence/check-count.json`. A rule that never fires can be removed. A
rule that fires every day is telling you something the written rule could not.

## What a hook cannot do

- It cannot change the habit itself. That comes from how the model was trained.
- It cannot see meaning, only shape. A check that needs judgment needs a second model reading each reply, and that costs time on every message.
- It cannot replace the person's correction. The person still has to say no the first few times. The hook makes sure the no does not have to be said forever.
