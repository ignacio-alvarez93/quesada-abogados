"""FCP-9A-02: UTC execution windows, deadlines and temporal eligibility -
pure, deterministic, fail-closed, provider-neutral, NON-AUTHORITATIVE.

Answers ONE question: given the `not_before_utc` / `deadline_utc` bounds the
Runner Manifest (or the Fabric DAG Blueprint, or an FCP-9A-01
`ScheduleRequest`) already carries, and an explicit evaluation instant, is
the window READY, WAIT_UNTIL a stated instant, EXPIRED, or INVALID? It never
answers "may I dispatch now?".

Why this is a consultative evaluator, not a clock
-------------------------------------------------
* The bounds are the Runner's own `Manifest.not_before_utc` /
  `Manifest.deadline_utc` (forwarded unchanged by `fabric_dag_blueprint`);
  no other authority clock, calendar or schedule is introduced. The
  Runner's `PipelineRunner` (`_wait_not_before`, `_compute_deadline`) stays
  the only component that waits or stops at execution time.
* Never reads the current time: the instant is the explicit `as_of` value
  or the return value of an injected `clock` callable (called exactly once).
  Supplying neither (or both) is INVALID - there is no wall-clock default.
  No timers, threads, sleeps, polling, daemon, I/O, environment, network or
  mutable global state; stdlib only.
* Semantics mirror the Runner (pinned by tests): the window is open from
  `not_before` inclusive (`now < not_before` waits) and closed at `deadline`
  inclusive (`now >= deadline` stops).

Input (`ExecutionWindow`, frozen; or any source exposing both
`not_before_utc` and `deadline_utc` - Runner `Manifest`, `DagBlueprint`,
`ScheduleRequest` - or a manifest `dict`. Only those two fields are read.)
------------------------------------------------------------------------
* Bounds: `None` (unbounded) or a strict ISO-8601 string, at most 40 ASCII
  chars: `YYYY-MM-DDTHH:MM:SS[.f{1,6}](Z|+HH:MM|-HH:MM)`. The explicit
  offset is mandatory (naive is refused), must be within +-14:00, and the
  RFC 3339 "unknown local offset" `-00:00` is refused. Compact, week-date
  and space-separated forms are refused even where `fromisoformat` accepts
  them. Every accepted string is accepted by the Runner's `_parse_iso` with
  the same instant.
* `as_of`: an aware `datetime` (exact type) or a string as above. A
  `datetime` whose tzinfo maps its wall time to two different offsets
  (DST fold or gap, e.g. Europe/Madrid 02:30 on a transition day) is refused
  as ambiguous instead of being guessed.
* Every instant must fall within `MIN_YEAR..MAX_YEAR` (UTC), so no
  conversion can overflow. A bound later than `as_of + MAX_HORIZON` is an
  absurd horizon and refused.
* `not_before` must strictly precede `deadline` (an empty window is
  contradictory).

Statuses (fixed vocabulary, none of them is a permit)
-----------------------------------------------------
* INVALID: at least one `INVALID_REASONS` code; nothing is echoed.
* EXPIRED: `as_of >= deadline`; never eligible again (`next_eligible_utc`
  is None).
* WAIT_UNTIL: `as_of < not_before`; `next_eligible_utc` is `not_before`.
* READY: inside the window; `next_eligible_utc` is `as_of` itself.
Output (`WindowEvaluation`, schema `fcp9a02-scheduler-window-v1`) holds only
UTC-normalized instants ("...Z"), integer second counts and enumerated codes.
It fixes every zero-authority flag of the FCP-9A-01 contract to False as
read-only properties.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

try:
    from scripts.ai import fabric_scheduler_contract as sc
except ImportError:  # pragma: no cover - direct script execution
    import fabric_scheduler_contract as sc  # type: ignore[no-redef]

SCHEMA = "fcp9a02-scheduler-window-v1"
SCHEMA_VERSION = 1
WINDOW_MARKER = "FCP9A02_WINDOW_ADVISORY_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

MIN_YEAR = 2000
MAX_YEAR = 2199
MAX_HORIZON = timedelta(days=366)
MAX_OFFSET = timedelta(hours=14)
MAX_CANONICAL_JSON_BYTES = 4096

_TIMESTAMP_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(?:Z|([+-])(\d{2}):(\d{2}))"
)
_SECOND = timedelta(seconds=1)

READY = "READY"
WAIT_UNTIL = "WAIT_UNTIL"
EXPIRED = "EXPIRED"
INVALID = "INVALID"
STATUSES = (READY, WAIT_UNTIL, EXPIRED, INVALID)

# Invalid-input codes, in their fixed canonical order.
WINDOW_SOURCE_UNSUPPORTED = "WINDOW_SOURCE_UNSUPPORTED"
AS_OF_MISSING = "AS_OF_MISSING"
AS_OF_SOURCE_AMBIGUOUS = "AS_OF_SOURCE_AMBIGUOUS"
CLOCK_UNAVAILABLE = "CLOCK_UNAVAILABLE"
AS_OF_INVALID = "AS_OF_INVALID"
AS_OF_NAIVE = "AS_OF_NAIVE"
AS_OF_AMBIGUOUS_LOCAL_TIME = "AS_OF_AMBIGUOUS_LOCAL_TIME"
AS_OF_OUT_OF_RANGE = "AS_OF_OUT_OF_RANGE"
NOT_BEFORE_INVALID = "NOT_BEFORE_INVALID"
NOT_BEFORE_NAIVE = "NOT_BEFORE_NAIVE"
NOT_BEFORE_OUT_OF_RANGE = "NOT_BEFORE_OUT_OF_RANGE"
DEADLINE_INVALID = "DEADLINE_INVALID"
DEADLINE_NAIVE = "DEADLINE_NAIVE"
DEADLINE_OUT_OF_RANGE = "DEADLINE_OUT_OF_RANGE"
WINDOW_INVERTED = "WINDOW_INVERTED"
HORIZON_EXCEEDED = "HORIZON_EXCEEDED"
INVALID_REASONS = (
    WINDOW_SOURCE_UNSUPPORTED, AS_OF_MISSING, AS_OF_SOURCE_AMBIGUOUS, CLOCK_UNAVAILABLE, AS_OF_INVALID,
    AS_OF_NAIVE, AS_OF_AMBIGUOUS_LOCAL_TIME, AS_OF_OUT_OF_RANGE, NOT_BEFORE_INVALID, NOT_BEFORE_NAIVE,
    NOT_BEFORE_OUT_OF_RANGE, DEADLINE_INVALID, DEADLINE_NAIVE, DEADLINE_OUT_OF_RANGE, WINDOW_INVERTED,
    HORIZON_EXCEEDED,
)

# Temporal codes (exactly one per non-READY, non-INVALID status).
WINDOW_NOT_OPEN = "WINDOW_NOT_OPEN"
WINDOW_EXPIRED = "WINDOW_EXPIRED"
TEMPORAL_REASONS = (WINDOW_NOT_OPEN, WINDOW_EXPIRED)
REASONS = INVALID_REASONS + TEMPORAL_REASONS

# Parse failures, per field: (invalid, naive, out of range).
_FIELD_CODES = {
    "as_of": (AS_OF_INVALID, AS_OF_NAIVE, AS_OF_OUT_OF_RANGE),
    "not_before": (NOT_BEFORE_INVALID, NOT_BEFORE_NAIVE, NOT_BEFORE_OUT_OF_RANGE),
    "deadline": (DEADLINE_INVALID, DEADLINE_NAIVE, DEADLINE_OUT_OF_RANGE),
}
_OK, _BAD, _NAIVE, _RANGE = 0, 1, 2, 3


def _ordered(codes) -> tuple:
    return tuple(sorted(set(codes), key=REASONS.index))


def _in_range(value: datetime) -> bool:
    return MIN_YEAR <= value.year <= MAX_YEAR


def _parse_text(value) -> tuple:
    """Returns (status, utc datetime or None) for a strict ISO-8601 string."""
    if type(value) is not str or not 0 < len(value) <= sc.MAX_TIMESTAMP_CHARS or not value.isascii():
        return _BAD, None
    match = _TIMESTAMP_RE.fullmatch(value)
    if match is None:
        # A well-formed local timestamp lacking only its offset is "naive".
        if _TIMESTAMP_RE.fullmatch(value + "Z"):
            return _NAIVE, None
        return _BAD, None
    sign, off_h, off_m = match.group(7), match.group(8), match.group(9)
    if sign is not None:
        offset = timedelta(hours=int(off_h), minutes=int(off_m))
        if int(off_m) >= 60 or offset > MAX_OFFSET or (sign == "-" and offset == timedelta(0)):
            return _BAD, None
    if not MIN_YEAR <= int(match.group(1)) <= MAX_YEAR:
        return _RANGE, None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        utc = parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return _BAD, None
    return (_OK, utc) if _in_range(utc) else (_RANGE, None)


def _parse_datetime(value) -> tuple:
    """Returns (status, utc datetime or None, ambiguous) for a datetime."""
    if value.tzinfo is None or value.utcoffset() is None:
        return _NAIVE, None, False
    if not _in_range(value):
        return _RANGE, None, False
    # A wall time that maps to two offsets (DST fold or gap) is ambiguous.
    try:
        ambiguous = value.replace(fold=0).utcoffset() != value.replace(fold=1).utcoffset()
        offset = value.utcoffset()
    except (ValueError, TypeError):
        return _BAD, None, False
    if ambiguous:
        return _BAD, None, True
    if abs(offset) > MAX_OFFSET:
        return _BAD, None, False
    utc = value.astimezone(timezone.utc)
    return (_OK, utc, False) if _in_range(utc) else (_RANGE, None, False)


def parse_utc(value) -> Optional[datetime]:
    """Strict parse of one bound string to an aware UTC datetime, or None."""
    status, parsed = _parse_text(value)
    return parsed if status == _OK else None


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExecutionWindow:
    """The Runner's own window bounds. Validated by `evaluate_window` (fail
    closed), not here."""
    not_before_utc: Optional[str] = None
    deadline_utc: Optional[str] = None


_MISSING = object()


def window_from_source(source) -> Optional[ExecutionWindow]:
    """Reads ONLY `not_before_utc` and `deadline_utc` from a Runner
    `Manifest`, `DagBlueprint`, `ScheduleRequest`, manifest `dict` or an
    `ExecutionWindow`. Returns None for any other source (never guesses)."""
    if type(source) is ExecutionWindow:
        return source
    if type(source) is dict:
        return ExecutionWindow(source.get("not_before_utc"), source.get("deadline_utc"))
    # Instance fields only (`vars`): no property, descriptor or proxy runs.
    try:
        fields = vars(source)
    except TypeError:
        return None
    not_before = fields.get("not_before_utc", _MISSING)
    deadline = fields.get("deadline_utc", _MISSING)
    if not_before is _MISSING or deadline is _MISSING:
        return None
    return ExecutionWindow(not_before, deadline)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _ceil_seconds(delta: timedelta) -> int:
    return -((-delta) // _SECOND)


@dataclass(frozen=True)
class WindowEvaluation(sc._NotAuthorized):
    """Consultative temporal evaluation. Construction re-checks every
    invariant, so a hand-made evaluation cannot claim a status its instants
    do not support."""
    status: str
    reasons: tuple
    as_of_utc: Optional[str]
    not_before_utc: Optional[str]
    deadline_utc: Optional[str]
    next_eligible_utc: Optional[str]
    seconds_until_eligible: Optional[int]
    seconds_until_deadline: Optional[int]

    def __post_init__(self):
        if type(self.status) is not str or self.status not in STATUSES:
            raise ValueError("unknown window status")
        if not (type(self.reasons) is tuple and all(type(r) is str and r in REASONS for r in self.reasons)
                and self.reasons == _ordered(self.reasons)):
            raise ValueError("reasons must be ordered window reason codes")
        fields = (self.as_of_utc, self.not_before_utc, self.deadline_utc, self.next_eligible_utc,
                  self.seconds_until_eligible, self.seconds_until_deadline)
        if self.status == INVALID:
            if not self.reasons or not set(self.reasons) <= set(INVALID_REASONS):
                raise ValueError("an INVALID evaluation carries only invalid reasons")
            if fields != (None,) * len(fields):
                raise ValueError("an INVALID evaluation echoes nothing")
            return
        as_of, not_before, deadline = (_reparse(self.as_of_utc, required=True), _reparse(self.not_before_utc),
                                       _reparse(self.deadline_utc))
        if _window_reasons(as_of, not_before, deadline):
            raise ValueError("a non-INVALID evaluation needs a consistent window within the horizon")
        if self.status != _status_for(as_of, not_before, deadline):
            raise ValueError("status must be exactly the one derived from the instants")
        if (self.reasons, self.next_eligible_utc, self.seconds_until_eligible,
                self.seconds_until_deadline) != _evaluation_fields(as_of, not_before, deadline):
            raise ValueError("reasons, next eligibility and second counts must match the instants")

    @property
    def eligible(self) -> bool:
        """Informational only: inside the window at `as_of`. Not a permit."""
        return self.status == READY

    def to_dict(self) -> dict:
        guarantees = sc._NotAuthorized._guarantees()
        guarantees["marker"] = WINDOW_MARKER
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "status": self.status,
            "reasons": list(self.reasons), "as_of_utc": self.as_of_utc, "not_before_utc": self.not_before_utc,
            "deadline_utc": self.deadline_utc, "next_eligible_utc": self.next_eligible_utc,
            "seconds_until_eligible": self.seconds_until_eligible,
            "seconds_until_deadline": self.seconds_until_deadline, **guarantees,
        }


def _reparse(text, required: bool = False) -> Optional[datetime]:
    if text is None and not required:
        return None
    parsed = parse_utc(text)
    if parsed is None or sc._utc_text(parsed) != text:
        raise ValueError("instants must be UTC-normalized timestamps")
    return parsed


def _window_reasons(as_of: datetime, not_before: Optional[datetime], deadline: Optional[datetime]) -> set:
    reasons = set()
    if not_before is not None and deadline is not None and not_before >= deadline:
        reasons.add(WINDOW_INVERTED)
    if any(bound is not None and bound - as_of > MAX_HORIZON for bound in (not_before, deadline)):
        reasons.add(HORIZON_EXCEEDED)
    return reasons


def _status_for(as_of: datetime, not_before: Optional[datetime], deadline: Optional[datetime]) -> str:
    # Runner order: the deadline stops first; not_before waits (`now < nb`).
    if deadline is not None and as_of >= deadline:
        return EXPIRED
    if not_before is not None and as_of < not_before:
        return WAIT_UNTIL
    return READY


def _evaluation_fields(as_of, not_before, deadline) -> tuple:
    status = _status_for(as_of, not_before, deadline)
    until_deadline = None if deadline is None or status == EXPIRED else _ceil_seconds(deadline - as_of)
    if status == EXPIRED:
        return (WINDOW_EXPIRED,), None, None, None
    if status == WAIT_UNTIL:
        return (WINDOW_NOT_OPEN,), sc._utc_text(not_before), _ceil_seconds(not_before - as_of), until_deadline
    return (), sc._utc_text(as_of), 0, until_deadline


def canonical_json(evaluation: WindowEvaluation) -> str:
    """Stable, sorted, compact, size-bounded serialization of the exact
    contract type (a subclass cannot substitute `to_dict`)."""
    if type(evaluation) is not WindowEvaluation:
        raise TypeError("canonical_json accepts only a WindowEvaluation")
    text = sc._canonical(WindowEvaluation.to_dict(evaluation))
    if len(text) > MAX_CANONICAL_JSON_BYTES:
        raise ValueError("canonical evaluation exceeds MAX_CANONICAL_JSON_BYTES")
    return text


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _invalid(reasons) -> WindowEvaluation:
    return WindowEvaluation(
        status=INVALID, reasons=_ordered(reasons), as_of_utc=None, not_before_utc=None, deadline_utc=None,
        next_eligible_utc=None, seconds_until_eligible=None, seconds_until_deadline=None,
    )


def _resolve_as_of(as_of, clock, reasons: set) -> Optional[datetime]:
    if as_of is None and clock is None:
        reasons.add(AS_OF_MISSING)
        return None
    if as_of is not None and clock is not None:
        reasons.add(AS_OF_SOURCE_AMBIGUOUS)
        return None
    if clock is not None:
        if not callable(clock):
            reasons.add(CLOCK_UNAVAILABLE)
            return None
        try:
            as_of = clock()
        except Exception:  # noqa: BLE001 - an unreadable clock is UNKNOWN: fail closed
            reasons.add(CLOCK_UNAVAILABLE)
            return None
    invalid, naive, out_of_range = _FIELD_CODES["as_of"]
    if type(as_of) is datetime:
        status, parsed, ambiguous = _parse_datetime(as_of)
        if ambiguous:
            reasons.add(AS_OF_AMBIGUOUS_LOCAL_TIME)
            return None
    else:
        status, parsed = _parse_text(as_of)
    if status != _OK:
        reasons.add({_BAD: invalid, _NAIVE: naive, _RANGE: out_of_range}[status])
    return parsed


def _resolve_bound(value, field: str, reasons: set) -> Optional[datetime]:
    if value is None:
        return None
    invalid, naive, out_of_range = _FIELD_CODES[field]
    status, parsed = _parse_text(value)
    if status != _OK:
        reasons.add({_BAD: invalid, _NAIVE: naive, _RANGE: out_of_range}[status])
    return parsed


def evaluate_window(source, *, as_of=None, clock=None) -> WindowEvaluation:
    """Pure, deterministic temporal eligibility advisory. Exactly one of
    `as_of` (aware datetime or strict ISO-8601 string) or `clock` (callable
    returning one, called once) must be given; the wall clock is never read.
    Never raises on bad input and never mutates it. The result never
    authorizes dispatch, execution, retry, resume, merge or a provider
    switch."""
    reasons: set = set()
    window = window_from_source(source)
    if window is None:
        reasons.add(WINDOW_SOURCE_UNSUPPORTED)
        not_before = deadline = None
    else:
        not_before = _resolve_bound(window.not_before_utc, "not_before", reasons)
        deadline = _resolve_bound(window.deadline_utc, "deadline", reasons)
    now = _resolve_as_of(as_of, clock, reasons)
    if not_before is not None and deadline is not None and not_before >= deadline:
        reasons.add(WINDOW_INVERTED)
    if now is not None:
        reasons |= _window_reasons(now, not_before, deadline)
    if reasons:
        return _invalid(reasons)

    status = _status_for(now, not_before, deadline)
    temporal, next_eligible, until_eligible, until_deadline = _evaluation_fields(now, not_before, deadline)
    return WindowEvaluation(
        status=status, reasons=temporal, as_of_utc=sc._utc_text(now), not_before_utc=sc._utc_text(not_before),
        deadline_utc=sc._utc_text(deadline), next_eligible_utc=next_eligible,
        seconds_until_eligible=until_eligible, seconds_until_deadline=until_deadline,
    )
