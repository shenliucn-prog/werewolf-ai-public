# Playing and developing Werewolf AI

When the user asks to play, read `docs/AGENT_PLAY.md`. Work in their local fork.
Before each new game, ask for the board (or offer confirmed previous settings),
then role/personality/conjecture choices. Never infer these from "next game".
Normal play is provider-neutral: API/local model service or a configured Agent
adapter (Codex is optional). See docs/MODEL_CONNECTIONS.md. All interfaces use
model decisions, not offline rules or legacy rephrasing. Verify preflight before dealing.
Use offline only when the user explicitly selects a rule-flow test, and label
it as such. Never silently substitute local NPCs when model calls fail.
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

If a process is lost, use the recorded game id with `chat_game --resume GAME_ID`.
Do not inspect private checkpoint contents or re-randomize the game. If recovery
fails, report the error and ask before starting over. When the player dies, explain that the current
engine automatically continues the NPC game; retain all public output.

For code changes, preserve existing user work. Keep human onboarding enabled
in both chat and web. Direct research `GameSession` callers skip onboarding by
default; player-adapter tests must cover the ready gate. Run relevant Python
tests and browser DOM checks after changing shared contracts.
