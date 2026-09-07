# Playing and developing Werewolf AI

When the user asks to play, read `docs/AGENT_PLAY.md`. Work in their local fork.
Use `python -m werewolf_web.setup` for first-time setup, or the documented chat
command when their choices are already known. Keep one persistent interactive
process (PTY when required) across turns. Never launch a second game merely
because the user asks a rules question or says “continue”.

At onboarding, show the named host, exact board/rules and full public seating
map. Wait for the user's ready confirmation before night one. Do not invent NPC
acknowledgements. Relay every public statement verbatim with seat and name;
summaries are optional additions, never replacements. Preserve uncertainty:
“I checked them last night” does not establish a second check or its result.
Do not invent human statements or submit a decision when the user only asks
about rules. The engine alone resolves actions. Do not inspect hidden roles or
NPC private memory to answer player questions.

If a process is lost, report it; recovery/transfer is not implemented. Ask before
restarting and re-randomizing. When the player dies, explain that the current
engine automatically continues the NPC game; retain all public output.

For code changes, preserve existing user work. Keep human onboarding enabled
in both chat and web. Direct research `GameSession` callers skip onboarding by
default; player-adapter tests must cover the ready gate. Run relevant Python
tests and browser DOM checks after changing shared contracts.
