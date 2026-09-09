"""Match-scoped identities, independent of display names and transports.

R1 shell only: memory, pending actions and budgets remain in their existing
checkpoint owners. Do not create a second mutable copy of those fields here.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Participant:
    match_id: str
    participant_id: str
    seat: int | None
    controller: str
    adapter: str | None = None

    @classmethod
    def from_seat(cls, match_id, seat, driver, adapter=None):
        return cls(match_id, seat.player_id, seat.pos,
                   "human" if seat.is_player else driver,
                   adapter if not seat.is_player and driver == "agent" else None)


def participant_roster(match_id, seats, driver, adapter=None):
    """Rebuild from durable engine identity + driver, including the human."""
    roster = {}
    for seat in seats:
        if not isinstance(seat.player_id, str) or not seat.player_id or seat.player_id in roster:
            raise ValueError("Participant roster requires unique non-empty player IDs")
        roster[seat.player_id] = Participant.from_seat(match_id, seat, driver, adapter)
    return roster
