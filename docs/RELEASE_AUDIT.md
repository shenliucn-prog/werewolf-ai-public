# Release verification checklist

This is a reusable checklist, not a local audit log. Keep evidence outside Git.

- Run Python tests, frontend DOM tests, JavaScript syntax and dependency checks.
- Run `python scripts/check_release.py`; use `--history` on a full clone.
- Review bilingual onboarding, board selection, seating, night actions, ordered
  speeches, ballots, private rules chat and model-failure recovery.
- Verify normal play requires a working model connection and never silently
  substitutes offline NPCs. Label deterministic tests as offline.
- Verify optional conjecture rules and experimental boards are clearly distinguished.
- Manually check narrow-screen layout, keyboard operation and readable status updates.
- Review architecture and extension docs against code, not previous run reports.
- Follow the [public-data policy](PUBLIC_RELEASE.md) and [security limits](../SECURITY.md).

Passing tests establishes covered behavior, not game balance or human enjoyment.
