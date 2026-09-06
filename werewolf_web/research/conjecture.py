"""Dual-table research records with an append-only, public-only archive.

This is a trusted, in-process data layer, not authentication or an LLM planner.
Each actor's notebook is separately owned. Never pass notebooks to opponents.
Free text may intentionally disclose or fabricate claims: reference validation
prevents access to private records, not semantic information-flow violations.
"""

from dataclasses import asdict, dataclass
from typing import Optional


def _text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")


@dataclass(frozen=True)
class Guess:
    player: str
    roles: tuple[str, ...] = ()
    status: str = "unknown"
    confidence: str = "low"
    evidence: tuple[str, ...] = ()
    rationale: str = ""
    alternatives: str = ""
    faction: str = ""
    faction_status: str = "unknown"
    candidate_roles: tuple[str, ...] = ()

    def __post_init__(self):
        _text(self.player, "player")
        if self.status not in {"unknown", "withheld", "inferred", "claimed", "known"}:
            raise ValueError("invalid knowledge status")
        if self.confidence not in {"low", "medium", "high"}:
            raise ValueError("invalid confidence")
        if self.faction not in {"", "good", "wolf"}:
            raise ValueError("invalid faction")
        if self.faction_status not in {"unknown", "withheld", "inferred", "claimed", "known"}:
            raise ValueError("invalid faction status")
        if bool(self.faction) != (self.faction_status not in {"unknown", "withheld"}):
            raise ValueError("faction and its status must agree")
        for values in (self.roles, self.evidence, self.candidate_roles):
            if type(values) is not tuple or len(set(values)) != len(values):
                raise ValueError("roles and evidence must be unique immutable tuples")
            for value in values:
                _text(value, "role or evidence")
        if self.status in {"unknown", "withheld"} and self.roles:
            raise ValueError("unknown/withheld entries cannot assert roles")
        if self.status not in {"unknown", "withheld"} and not self.roles:
            raise ValueError("a substantive judgment requires a role or faction")
        if not isinstance(self.rationale, str) or not isinstance(self.alternatives, str):
            raise ValueError("explanations must be text")


@dataclass(frozen=True)
class _Table:
    actor: str
    version: int
    phase: str
    as_of: int
    guesses: tuple[Guess, ...]
    revision_reason: str = ""
    proposed_action: str = ""

    def __post_init__(self):
        _text(self.actor, "actor")
        _text(self.phase, "phase")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("version must be a positive integer")
        if type(self.as_of) is not int or self.as_of < 0:
            raise ValueError("as_of must be a nonnegative public sequence")
        if type(self.guesses) is not tuple or not all(type(g) is Guess for g in self.guesses):
            raise ValueError("guesses must be an immutable tuple of Guess records")
        if not isinstance(self.revision_reason, str) or not isinstance(self.proposed_action, str):
            raise ValueError("table explanations must be text")
        if self.version > 1:
            _text(self.revision_reason, "revision reason")


@dataclass(frozen=True)
class PublicTable(_Table):
    """A player's deliberate public account, not certified truth."""


@dataclass(frozen=True)
class PrivateTable(_Table):
    """Explicit decision input, not privileged access to a model's thoughts."""


@dataclass(frozen=True)
class PublicRecord:
    sequence: int
    event_id: str
    kind: str
    actor: Optional[str]
    phase: str
    text: str = ""
    table: Optional[PublicTable] = None


@dataclass(frozen=True)
class RowChange:
    player: str
    before: Guess
    after: Guess


def _roster(players: tuple[str, ...]) -> tuple[str, ...]:
    if type(players) is not tuple or not players or len(set(players)) != len(players):
        raise ValueError("players must be a nonempty unique tuple")
    for player in players:
        _text(player, "player")
    return players


def _coverage(table: _Table, players: tuple[str, ...]) -> None:
    targets = tuple(g.player for g in table.guesses)
    if len(targets) != len(players) or set(targets) != set(players):
        raise ValueError("each table must cover every player exactly once")


class PublicArchive:
    """Exact public history. Contains no ground truth or private notebook registry.

    The fixed-scenario roster is static (including eliminated seats). A future
    game adapter must enforce alive actors and legal phase windows separately.
    """

    def __init__(self, players: tuple[str, ...]):
        self._players = _roster(players)
        self._records: list[PublicRecord] = []
        self._by_id: dict[str, PublicRecord] = {}
        self._tables: dict[tuple[str, int], PublicTable] = {}
        self._latest: dict[str, int] = {}

    @property
    def players(self) -> tuple[str, ...]:
        return self._players

    @property
    def sequence(self) -> int:
        return len(self._records)

    def history(self) -> tuple[PublicRecord, ...]:
        return tuple(self._records)

    def lookup(self, event_id: str) -> PublicRecord:
        return self._by_id[event_id]

    def table(self, actor: str, version: int) -> PublicTable:
        return self._tables[(actor, version)]

    def _append(self, kind: str, actor: Optional[str], phase: str,
                text: str = "", table: Optional[PublicTable] = None) -> PublicRecord:
        sequence = self.sequence + 1
        record = PublicRecord(sequence, f"E{sequence:06d}", kind, actor, phase, text, table)
        self._records.append(record)
        self._by_id[record.event_id] = record
        if table is not None:
            self._tables[(table.actor, table.version)] = table
            self._latest[table.actor] = table.version
        return record

    def append_statement(self, actor: str, phase: str, text: str) -> PublicRecord:
        if actor not in self.players:
            raise ValueError("unknown actor")
        _text(phase, "phase")
        _text(text, "statement")
        return self._append("statement", actor, phase, text)

    def append_event(self, phase: str, text: str) -> PublicRecord:
        """Trusted caller supplies only already-public game events."""
        _text(phase, "phase")
        _text(text, "event")
        return self._append("event", None, phase, text)

    def _validate_table(self, table: PublicTable, cutoff: int) -> None:
        if type(table) is not PublicTable:
            raise ValueError("only PublicTable can be published")
        if table.actor not in self.players:
            raise ValueError("unknown actor")
        _coverage(table, self.players)
        if table.as_of != cutoff:
            raise ValueError("table must use the current public cutoff")
        if table.version != self._latest.get(table.actor, 0) + 1:
            raise ValueError("versions must be consecutive and cannot overwrite history")
        for guess in table.guesses:
            if guess.status == "known" or guess.faction_status == "known":
                raise ValueError("public judgments are claims, not certified private knowledge")
            for ref in guess.evidence:
                record = self._by_id.get(ref)
                if record is None or record.sequence > table.as_of:
                    raise ValueError("unavailable public evidence")

    def publish_round(self, tables: tuple[PublicTable, ...]) -> tuple[PublicRecord, ...]:
        """Atomically release a complete set prepared against one public cutoff.

        Draft collection is outside this layer. No table in this batch may cite
        another table in the same batch. Validation precedes every mutation.
        """
        if type(tables) is not tuple or not all(type(t) is PublicTable for t in tables):
            raise ValueError("expected public tables")
        actors = tuple(t.actor for t in tables)
        if len(actors) != len(self.players) or set(actors) != set(self.players):
            raise ValueError("round must contain each player's table exactly once")
        cutoff = self.sequence
        for table in tables:
            self._validate_table(table, cutoff)
        if len({t.phase for t in tables}) != 1:
            raise ValueError("a batch must use one phase")
        by_actor = {t.actor: t for t in tables}
        return tuple(self._append("table", actor, by_actor[actor].phase,
                                  table=by_actor[actor]) for actor in self.players)

    def publish_revision(self, table: PublicTable) -> PublicRecord:
        if type(table) is not PublicTable or table.actor not in self._latest:
            raise ValueError("initial tables must be published as a complete round")
        self._validate_table(table, self.sequence)
        return self._append("table", table.actor, table.phase, table=table)

    def publish_active_round(self, tables: tuple[PublicTable, ...], active: tuple[str, ...]):
        """Game adapter supplies the living roster; dead actors never submit.

        Tables still cover the original full roster, preserving historical claims.
        """
        _roster(active)
        if not set(active) <= set(self.players) or type(tables) is not tuple:
            raise ValueError("invalid active roster")
        if len(tables) != len(active) or {t.actor for t in tables} != set(active):
            raise ValueError("incomplete living-player batch")
        for table in tables:
            self._validate_table(table, self.sequence)
        if len({t.phase for t in tables}) != 1:
            raise ValueError("mixed phases")
        return tuple(self._append("table", t.actor, t.phase, table=t) for t in tables)

    def changes(self, actor: str, before: int, after: int) -> tuple[RowChange, ...]:
        """Mechanical differences, NOT a semantic contradiction verdict."""
        old = {g.player: g for g in self.table(actor, before).guesses}
        new = {g.player: g for g in self.table(actor, after).guesses}
        return tuple(RowChange(p, old[p], new[p]) for p in self.players if old[p] != new[p])

    def export(self) -> dict:
        """Detached public-only snapshot; safe to render in either language."""
        return {"schema_version": 1, "players": list(self.players),
                "records": [asdict(record) for record in self._records]}


@dataclass(frozen=True)
class PrivateObservation:
    event_id: str
    text: str


@dataclass(frozen=True)
class DecisionUse:
    table_version: int
    as_of: int
    action: str


class PrivateNotebook:
    """Owner-held state; the trusted orchestrator provisions lawful observations.

    No actor can select another actor's notebook through PublicArchive. This
    object is not an authorization layer; do not expose it in a shared endpoint.
    """

    def __init__(self, actor: str, archive: PublicArchive):
        if actor not in archive.players:
            raise ValueError("unknown actor")
        self._actor = actor
        self._archive = archive
        self._observations: dict[str, PrivateObservation] = {}
        self._tables: list[PrivateTable] = []
        self._decisions: list[DecisionUse] = []

    def observe(self, text: str) -> PrivateObservation:
        _text(text, "observation")
        event_id = f"P:{self._actor}:{len(self._observations) + 1}"
        event = PrivateObservation(event_id, text)
        self._observations[event_id] = event
        return event

    @property
    def actor(self) -> str:
        return self._actor

    @property
    def archive(self) -> PublicArchive:
        return self._archive

    def validate(self, table: PrivateTable) -> None:
        """Validate without mutation, for coordinated draft submission."""
        if type(table) is not PrivateTable or table.actor != self._actor:
            raise ValueError("only the owner's private table is accepted")
        _coverage(table, self._archive.players)
        if table.version != len(self._tables) + 1:
            raise ValueError("private versions must be consecutive")
        if table.as_of != self._archive.sequence:
            raise ValueError("private table must use the current public cutoff")
        for guess in table.guesses:
            if guess.status in {"claimed", "withheld"} or guess.faction_status in {"claimed", "withheld"}:
                raise ValueError("private beliefs must not use public presentation states")
            if (guess.status == "known" or guess.faction_status == "known") and not guess.evidence:
                raise ValueError("known judgments require lawful evidence references")
            for ref in guess.evidence:
                if ref in self._observations:
                    continue
                try:
                    record = self._archive.lookup(ref)
                except KeyError:
                    raise ValueError("unavailable evidence") from None
                if record.sequence > table.as_of:
                    raise ValueError("unavailable evidence")

    def save(self, table: PrivateTable) -> None:
        self.validate(table)
        self._tables.append(table)

    def history(self) -> tuple[PrivateTable, ...]:
        return tuple(self._tables)

    def record_decision(self, table_version: int, action: str) -> DecisionUse:
        """Record which existing snapshot the caller used, never backfill one.

        This records an assertion of use; causal use by a future planner must be
        verified by that adapter. A data container cannot prove model cognition.
        """
        if type(table_version) is not int or not self._tables or table_version != len(self._tables):
            raise ValueError("decision must reference the latest existing private table")
        _text(action, "action")
        decision = DecisionUse(table_version, self._archive.sequence, action)
        self._decisions.append(decision)
        return decision

    def export_for_owner(self) -> dict:
        return {"actor": self._actor,
                "observations": [asdict(o) for o in self._observations.values()],
                "tables": [asdict(t) for t in self._tables],
                "decisions": [asdict(d) for d in self._decisions]}
