"""Local-only, privacy-safe performance instrumentation (onboarding baseline).

This module is deliberately thin.  A :class:`Recorder` is an opt-in sink: the
game runs byte-identically with or without it (it only observes wall-clock time
and a few non-secret counters).  Records are written to a JSONL file under
``werewolf_web/data/perf/`` — a directory excluded from the release export —
and never leave the machine.

Privacy rules (hard):

- ``actor``/``seat`` is a **seat position only**.  A player's name, role, request
  body, private decision, command argv and credential are never recorded.
- Timing is on ``time.monotonic``.  Only *observable* durations are recorded: a
  subprocess child's wall time is not split into "spawn vs inference", and a
  non-streaming HTTP call has no "first byte" — those fields are simply absent
  (unmeasurable), never guessed.
- Intervals are reported as separate, non-overlapping categories (``decision``,
  ``model_call``, ``step``, ``checkpoint``, ``human_idle``) with a monotonic
  timestamp; there is no "total busy" figure that could double-count nested
  intervals.  ``human_idle`` is the time a step spends waiting on the human, so
  it is never counted as system work.
"""
from __future__ import annotations

import json
import os
import time

from . import config

PERF_DIR = os.path.join(config.DATA_DIR, "perf")

# Flush to disk when the in-memory buffer reaches this many records, to bound
# memory on long games without turning every event into a syscall.
FLUSH_EVERY = 256


def now() -> float:
    return time.monotonic()


def elapsed_ms(start: float) -> float:
    """Milliseconds since ``start`` (monotonic), rounded to microseconds."""
    return round((time.monotonic() - start) * 1000.0, 3)


class Recorder:
    """Append-only, privacy-safe perf recorder.  A ``None`` path is a no-op."""

    def __init__(self, path: str | None = None):
        self.path = path
        self._records: list[dict] = []

    @property
    def enabled(self) -> bool:
        return bool(self.path)

    def _emit(self, cat: str, **fields) -> None:
        if not self.path:
            return
        record = {"cat": cat, "t": round(now(), 6)}
        record.update(fields)
        self._records.append(record)
        if len(self._records) >= FLUSH_EVERY:
            self.flush()

    # -- categories ---------------------------------------------------------
    def decision(self, **fields) -> None:
        """One NPC decision's wall time + metadata (seat pos, never identity)."""
        self._emit("decision", **fields)

    def model_call(self, **fields) -> None:
        """The external model/agent call itself: duration + serialized request size."""
        self._emit("model_call", **fields)

    def step(self, **fields) -> None:
        self._emit("step", **fields)

    def checkpoint(self, **fields) -> None:
        self._emit("checkpoint", **fields)

    def human_idle(self, **fields) -> None:
        self._emit("human_idle", **fields)

    # -- persistence --------------------------------------------------------
    def flush(self) -> None:
        """Append buffered records; a write failure disables the sink silently.

        Perf logging must never affect the game: an unreadable/unwritable target
        (or any OSError) is swallowed, the buffered records are dropped, and the
        recorder turns itself off instead of raising into the decision path.
        """
        if not self.path or not self._records:
            return
        try:
            directory = os.path.dirname(os.path.abspath(self.path))
            os.makedirs(directory, exist_ok=True)
            os.chmod(directory, 0o700)
            with open(self.path, "a", encoding="utf-8") as handle:
                for record in self._records:
                    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        except (OSError, ValueError, TypeError):
            self._records = []
            self.path = None
        else:
            self._records = []
