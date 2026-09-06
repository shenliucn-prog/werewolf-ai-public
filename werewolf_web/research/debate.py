"""Offline debate coordinator and explicitly hand-labelled observer reactions.

No natural-language classifier or ground-truth judge is implemented here.
Labels are individual observer inputs for controlled fixtures, never a public
host verdict. These trusted-process views are NOT endpoint authentication.
"""

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import math

from .conjecture import Guess, PrivateNotebook, PrivateTable, PublicArchive, PublicTable, _text


CATEGORIES = frozenset({"reasonable_revision", "different_conditions",
                        "strategic_concealment", "unresolved_contradiction",
                        "insufficient_evidence"})
# Only the fixed classic-role fixtures use this mapping. Unknown special roles
# do not acquire an assumed faction; live board integration is out of scope.
FACTIONS = {"werewolf": True, "seer": False, "villager": False, "good": False}


@dataclass(frozen=True)
class Challenge:
    event_id: str
    actor: str
    target: str
    table_version: int
    row_player: str
    evidence: tuple[str, ...]
    response_event: str = ""


@dataclass(frozen=True)
class Opinion:
    suspicion: float
    credibility: float = 1.0
    known_faction: bool | None = None


class DebateSession:
    """One bounded research round, with a static roster and owner-held notebooks.

    All public changes must go through this coordinator while it is active.
    Sealed drafts, private reactions and research frames never enter public views.
    """

    def __init__(self, archive: PublicArchive, notebooks: dict[str, PrivateNotebook],
                 *, phase: str = "D1", max_challenges: int = 2,
                 per_actor_limit: int = 1, sensitivities: dict[str, float] | None = None):
        _text(phase, "phase")
        if set(notebooks) != set(archive.players):
            raise ValueError("one notebook is required per actor")
        if any(n.actor != a or n.archive is not archive for a, n in notebooks.items()):
            raise ValueError("notebook owner/archive mismatch")
        if any(n.history() for n in notebooks.values()) or any(r.table for r in archive.history()):
            raise ValueError("this coordinator starts with fresh tables; public prehistory is allowed")
        for limit in (max_challenges, per_actor_limit):
            if type(limit) is not int or limit < 1:
                raise ValueError("challenge limits must be positive integers")
        sensitivity = dict(sensitivities or {})
        if not set(sensitivity) <= set(archive.players):
            raise ValueError("unknown sensitivity owner")
        for value in sensitivity.values():
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 2:
                raise ValueError("sensitivity must be finite and in (0, 2]")
        self.archive = archive
        self._notebooks = dict(notebooks)
        self.phase = phase
        self.state = "collecting"
        self.max_challenges = max_challenges
        self.per_actor_limit = per_actor_limit
        self._sensitivities = sensitivity
        self._cutoff = archive.sequence
        self._expected_sequence = archive.sequence
        self._drafts: dict[str, tuple[PrivateTable, PublicTable]] = {}
        self._challenges: dict[str, Challenge] = {}
        self._pending = ""
        self._opinion: dict[str, dict[str, Opinion]] = {}
        self._assessments: dict[str, list[dict]] = {a: [] for a in archive.players}
        self._seen: dict[str, set[tuple]] = {a: set() for a in archive.players}
        self._frames: list[dict] = []
        self._actions: set[str] = set()
        self._capture("initial", None)

    def _guard(self, *states: str) -> None:
        if self.archive.sequence != self._expected_sequence:
            raise ValueError("public archive changed outside the coordinator")
        if self.state not in states:
            raise ValueError(f"operation not allowed while {self.state}")

    def _actor(self, actor: str) -> None:
        if actor not in self.archive.players:
            raise ValueError("unknown actor")

    def _capture(self, cause: str, private_actor: str | None) -> None:
        self._expected_sequence = self.archive.sequence
        self._frames.append({
            "cause": cause, "private_actor": private_actor, "state": self.state,
            "public": self.archive.export(),
            "challenges": [asdict(c) for c in self._challenges.values()],
            "owners": {a: self._owner_data(a) for a in self.archive.players},
        })

    def _owner_data(self, actor: str) -> dict:
        return {"notebook": self._notebooks[actor].export_for_owner(),
                "opinions": {p: asdict(o) for p, o in self._opinion.get(actor, {}).items()},
                "assessments": deepcopy(self._assessments[actor])}

    def submit(self, actor: str, private: PrivateTable, public: PublicTable) -> None:
        self._guard("collecting")
        self._actor(actor)
        if actor in self._drafts:
            raise ValueError("actor already submitted")
        if type(private) is not PrivateTable or type(public) is not PublicTable:
            raise ValueError("expected distinct private and public table types")
        if private.actor != actor or public.actor != actor:
            raise ValueError("draft owner mismatch")
        if private.phase != self.phase or public.phase != self.phase:
            raise ValueError("draft phase mismatch")
        self._notebooks[actor].validate(private)
        self.archive._validate_table(public, self._cutoff)
        # Nothing becomes visible or gets saved to a notebook until all drafts
        # have passed validation and the host explicitly opens debate.
        self._drafts[actor] = (private, public)

    def open_debate(self) -> None:
        self._guard("collecting")
        if set(self._drafts) != set(self.archive.players):
            raise ValueError("all actors must submit before release")
        for actor, (private, public) in self._drafts.items():
            self._notebooks[actor].validate(private)
            self.archive._validate_table(public, self._cutoff)
        for actor in self.archive.players:
            private, _ = self._drafts[actor]
            self._notebooks[actor].save(private)
            opinions = {}
            for row in private.guesses:
                known = (FACTIONS.get(row.roles[0])
                         if row.status == "known" and len(row.roles) == 1 else None)
                suspicion = (float(known) if known is not None else
                             0.7 if row.roles == ("werewolf",) else 0.35)
                opinions[row.player] = Opinion(suspicion, known_faction=known)
            self._opinion[actor] = opinions
        self.archive.publish_round(tuple(self._drafts[a][1] for a in self.archive.players))
        self._drafts.clear()
        self.state = "debating"
        self._capture("tables_released", None)

    def challenge(self, actor: str, target: str, version: int, row_player: str,
                  evidence: tuple[str, ...], text: str) -> str:
        self._guard("debating")
        self._actor(actor)
        self._actor(target)
        self._actor(row_player)
        _text(text, "challenge")
        if actor == target or self._pending:
            raise ValueError("self-challenge or another pending response")
        if len(self._challenges) >= self.max_challenges:
            raise ValueError("table challenge budget exhausted")
        if sum(c.actor == actor for c in self._challenges.values()) >= self.per_actor_limit:
            raise ValueError("actor challenge budget exhausted")
        if type(version) is not int:
            raise ValueError("invalid table version")
        self.archive.table(target, version)
        if type(evidence) is not tuple or not evidence or len(set(evidence)) != len(evidence):
            raise ValueError("challenge requires distinct public evidence references")
        for ref in evidence:
            self.archive.lookup(ref)
        record = self.archive.append_statement(actor, f"{self.phase}.challenge", text)
        item = Challenge(record.event_id, actor, target, version, row_player, evidence)
        self._challenges[item.event_id] = item
        self._pending = item.event_id
        self._capture("challenge", None)
        return item.event_id

    def respond(self, actor: str, challenge_id: str, text: str) -> None:
        self._guard("debating")
        self._actor(actor)
        _text(text, "response")
        if not self._pending or self._pending != challenge_id:
            raise ValueError("no matching pending challenge")
        item = self._challenges[challenge_id]
        if item.target != actor:
            raise ValueError("only the challenged actor may respond")
        response = self.archive.append_statement(actor, f"{self.phase}.response", text)
        self._challenges[challenge_id] = replace(item, response_event=response.event_id)
        self._pending = ""
        self._capture("response", None)

    def assess(self, observer: str, challenge_id: str, category: str, reason: str) -> None:
        """Apply one observer's hand-authored classification, not a host verdict.

        Coefficients are explicit experimental scores, not calibrated chances.
        Same-source repeated attacks cannot stack. Later credibility recovery is
        intentionally not modelled by this first one-assessment-per-dispute pass.
        """
        self._guard("debating")
        self._actor(observer)
        _text(reason, "assessment reason")
        if category not in CATEGORIES:
            raise ValueError("unknown assessment category")
        item = self._challenges[challenge_id]
        if not item.response_event:
            raise ValueError("wait for the response window before assessment")
        if observer == item.target:
            raise ValueError("target does not score its own credibility")
        # Excludes the challenger and response ID: repeating an accusation is not
        # independent evidence, even if another actor repeats it later.
        key = (item.target, item.row_player, tuple(sorted(item.evidence)))
        if key in self._seen[observer]:
            raise ValueError("observer already assessed this underlying dispute")
        before = self._opinion[observer][item.target]
        scale = self._sensitivities.get(observer, 1.0)
        severe = category == "unresolved_contradiction"
        after = Opinion(
            min(1.0, before.suspicion + 0.35 * scale)
            if severe and before.known_faction is None else before.suspicion,
            max(0.0, before.credibility - 0.30 * scale) if severe else before.credibility,
            before.known_faction,
        )
        notebook = self._notebooks[observer]
        previous = notebook.history()[-1]
        rows = []
        for row in previous.guesses:
            if row.player != item.target:
                rows.append(row)
                continue
            roles, status, confidence = row.roles, row.status, row.confidence
            if after.suspicion != before.suspicion and row.status != "known":
                roles = ("werewolf",) if after.suspicion >= 0.6 else row.roles
                status = "inferred" if roles else "unknown"
                confidence = "medium" if roles else "low"
            refs = tuple(dict.fromkeys(row.evidence + item.evidence +
                                       (item.event_id, item.response_event)))
            rows.append(replace(row, roles=roles, status=status, confidence=confidence,
                                evidence=refs, rationale=reason))
        revised = replace(previous, version=previous.version + 1,
                          as_of=self.archive.sequence, guesses=tuple(rows), revision_reason=reason)
        notebook.save(revised)
        self._opinion[observer][item.target] = after
        self._seen[observer].add(key)
        self._assessments[observer].append({
            "challenge": challenge_id, "category": category, "reason": reason,
            "source": "hand_authored_observer_annotation", "target": item.target,
            "before": asdict(before), "after": asdict(after),
            "private_version_before": previous.version,
            "private_version_after": revised.version,
            "as_of": self.archive.sequence,
        })
        self._capture("private_assessment", observer)

    def revise(self, actor: str, table: PublicTable) -> None:
        self._guard("debating")
        self._actor(actor)
        if self._pending:
            raise ValueError("respond before revising")
        if type(table) is not PublicTable or table.actor != actor or table.phase != self.phase:
            raise ValueError("public revision owner/phase mismatch")
        self.archive.publish_revision(table)
        self._capture("public_revision", None)

    def close(self, summary: str, *, force: bool = False) -> None:
        self._guard("debating")
        _text(summary, "host summary")
        if self._pending and not force:
            raise ValueError("a response is pending; explicit host closure required")
        if self._pending:
            event = self.archive.append_event(f"{self.phase}.response_window_closed", summary)
            item = self._challenges[self._pending]
            self._challenges[self._pending] = replace(item, response_event=event.event_id)
            self._pending = ""
        else:
            self.archive.append_event(f"{self.phase}.closed", summary)
        self.state = "closed"
        self._capture("host_closure", None)

    def suggested_target(self, actor: str) -> str:
        """Small fixture policy using private scores, not a general game planner."""
        self._guard("debating", "closed")
        self._actor(actor)
        opinions = self._opinion[actor]
        is_wolf = opinions[actor].known_faction is True
        candidates = [p for p in self.archive.players if p != actor and not (
            is_wolf and opinions[p].known_faction is True)]
        if not candidates:
            raise ValueError("no candidate for fixture policy")
        return max(candidates, key=lambda p: opinions[p].suspicion)

    def act(self, actor: str, target: str, explanation: str) -> None:
        """Explicit public choice; may deliberately differ from private suspicion."""
        self._guard("closed")
        self._actor(actor)
        self._actor(target)
        _text(explanation, "action explanation")
        if actor == target or actor in self._actions:
            raise ValueError("self-target or duplicate action")
        notebook = self._notebooks[actor]
        version = notebook.history()[-1].version
        notebook.record_decision(version, f"vote:{target}")
        self.archive.append_statement(actor, f"{self.phase}.action", f"vote:{target}\n{explanation}")
        self._actions.add(actor)
        if len(self._actions) == len(self.archive.players):
            self.state = "complete"
        self._capture("action", None)

    def player_view(self, actor: str) -> dict:
        self._actor(actor)
        return {"state": self.state, "public": self.archive.export(),
                "own": self._owner_data(actor),
                "challenges": [asdict(c) for c in self._challenges.values()]}

    def player_replay(self, actor: str) -> list[dict]:
        self._actor(actor)
        # No global frame indexes/private timestamps: other actors' private
        # updates must not be observable as gaps in an otherwise public replay.
        return deepcopy([{"state": f["state"], "cause": f["cause"],
                          "public": f["public"], "challenges": f["challenges"],
                          "own": f["owners"][actor]}
                         for f in self._frames if f["private_actor"] in (None, actor)])

    def research_replay(self) -> list[dict]:
        """Explicit all-owner export for isolated offline analysis only."""
        return deepcopy(self._frames)
