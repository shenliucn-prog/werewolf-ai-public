# Own-seat acting context

Model requests include `own_acting_state`: form, valence, arousal, confidence,
stress, momentum and effective abilities from the requesting NPC's existing
Brain. State event logs and other NPC states are excluded. This separate field
does not change factual observations, role visibility, legal actions or rules.
The existing request budget still applies. Existing saves already carry the
underlying state; no new save field or cross-game learning is introduced.

Instructions connect personality to risk, initiative, disclosure and emphasis,
while preserving faction goals. Feelings are explicitly not identity evidence.
No postprocessor forces an emotionally distinctive or strategically bad move.

## Evidence and limits

Five automated tests cover own-state sensitivity, isolation from other NPCs and
private event logs, detached/bounded requests, restore parity and separation of
personality from factual observations.

Four synthetic local Agent requests used gpt-5.6-terra / medium, comparing
direct/cautious personalities with calm/irritated affect under identical facts.
All chose the same target. Cautious replies qualified their suspicions more;
affect differences were weak. Observed call durations: 9.23, 5.30, 5.80, 5.34
seconds. This is a tiny unreplicated smoke test, not a strength, latency or
distinct-character benchmark. No real game save was used. A full player-led
game remains necessary to judge whether the acting is enjoyable.
