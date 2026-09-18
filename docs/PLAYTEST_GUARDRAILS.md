# Playtest-driven observation safeguards

- Chinese human-speech metadata recognizes exact seat numbers and explicit
  current stances within clauses. Quoted, historical and ambiguous text should
  remain unclassified. The player's original text is never rewritten. This is
  intentionally conservative extraction, not general natural-language understanding.
- A public narration publishes the day's main speaking order before speech.
  Model context derives completed/awaiting seats from that schedule and public
  main speeches. Interruptions and election speech do not complete a day turn.
  Awaiting a turn does not establish evasion; neither does a queued question.
- Public facts expose revealed role/side and distinguish night death from
  exile. The source is only the public record, never a hidden role lookup.
  A vote against a player is not proof that the player was exiled. Unknown
  legacy role/timing fields remain unknown. No private night cause is exposed.
- Model badge transfer is its own task: choose a living successor or destroy
  the badge. It uses the same lawful private information as other decisions,
  including the dying seer's latest check. It is not an exile vote or check.

## Compatibility and limits

No snapshot schema, model routing, faction rules or offline strategy changes.
Older records without a public schedule report unknown turn status; resuming
the speech step can publish the schedule without replaying completed speeches.
Existing accepted decisions are not rerolled. Original speech remains intact.

These safeguards improve inputs and remove deterministic extraction errors;
they do not certify model logic, prevent every false statement or forbid a
wolf from deliberately lying. Tests verify real session paths, privacy and
restore behavior. A fresh model playtest is needed to measure behavioral impact.
