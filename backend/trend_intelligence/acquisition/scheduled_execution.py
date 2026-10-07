"""
Explicit, caller-invoked scheduled batch execution.

Built entirely on top of the existing SourceAcquisitionOrchestrator
registry/runner and whatever deterministic due plan the caller already
built (``AcquisitionReadinessPlan`` from ``acquisition.readiness`` or
``AcquisitionSchedulePlan`` from ``acquisition.scheduling``). This
module adds no new network, parsing, persistence or ingestion logic of
its own: it only consumes a plan's entries and, for every entry marked
due/ready, reuses ``SourceAcquisitionOrchestrator.run_source`` exactly
as a manual/single-source invocation would.

This is NOT a background scheduler: it has no daemon, no timer, no
sleep, no hidden retry loop, and it never calls itself. It executes
exactly once, synchronously, only when an external caller explicitly
invokes ``execute_scheduled_batch``, and only for the sources present
in the supplied plan. A source that is absent from the plan, or
present but not marked due/ready, is never executed: skipping it is
recorded as an explicit outcome, never a silent omission.

Sources are executed in deterministic (sorted source_code) order.
Each source is isolated: one source raising/failing never aborts or
rolls back the outcome already recorded for any other source, so
partial success across the batch is always preserved. Every entry in
the supplied plan produces exactly one outcome in the returned report,
whether it was executed or skipped.

Domain-neutral and provider-neutral: no vertical-specific assumptions,
no UI, no Selenium, no schema mutation.
"""

from dataclasses import dataclass

EXECUTION_EXECUTED = "EXECUTED"
EXECUTION_SKIPPED = "SKIPPED"

VALID_EXECUTION_STATES = frozenset({EXECUTION_EXECUTED, EXECUTION_SKIPPED})

SKIP_REASON_NOT_DUE = "NOT_DUE"
SKIP_REASON_UNRESOLVABLE_PLAN_ENTRY = "UNRESOLVABLE_PLAN_ENTRY"


@dataclass(frozen=True, slots=True)
class SourceExecutionOutcome:
    source_code: str

    execution_state: str
    executed: bool
    ok: bool | None

    plan_reason: str | None
    acquisition_outcome: object | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class ScheduledBatchExecutionReport:
    outcomes: tuple[SourceExecutionOutcome, ...]

    @property
    def executed(self):
        return tuple(
            outcome for outcome in self.outcomes if outcome.execution_state == EXECUTION_EXECUTED
        )

    @property
    def skipped(self):
        return tuple(
            outcome for outcome in self.outcomes if outcome.execution_state == EXECUTION_SKIPPED
        )

    @property
    def succeeded(self):
        return tuple(outcome for outcome in self.executed if outcome.ok)

    @property
    def failed(self):
        return tuple(outcome for outcome in self.executed if not outcome.ok)


def _entry_source_code(entry):
    return str(getattr(entry, "source_code", "") or "").strip().upper()


def _entry_plan_reason(entry):
    return getattr(entry, "reason", None)


def _entry_is_due(entry):
    """Read the due/ready flag off a plan entry without guessing.

    Supports both ``AcquisitionSchedulePlan`` entries (``is_due``) and
    ``AcquisitionReadinessPlan`` entries (``is_ready``): both express
    the same "safe to run now" boolean under a different plan-specific
    name. An entry exposing neither is an unresolvable plan entry, not
    a silent "not due": it is reported explicitly so a malformed or
    unrelated plan object can never be mistaken for one that simply
    has nothing due.
    """
    if hasattr(entry, "is_due"):
        return bool(entry.is_due)
    if hasattr(entry, "is_ready"):
        return bool(entry.is_ready)
    raise ValueError(
        "El entry del plan no expone ni is_due ni is_ready: no es un "
        "plan de ejecución reconocible"
    )


def execute_scheduled_batch(orchestrator, plan):
    """Execute, exactly once, every due/ready entry of ``plan``.

    ``plan`` must be a deterministic due plan already built by the
    caller (e.g. ``build_acquisition_schedule_plan`` or
    ``build_acquisition_readiness_plan``); this function never builds,
    refreshes or re-derives it. It only reads ``plan.entries``, sorts
    them by ``source_code`` for a fully deterministic execution order
    regardless of the order the plan happened to be constructed in,
    and then, for every entry:

    - if the entry is not marked due/ready, records an explicit
      ``SKIPPED`` outcome and never touches the orchestrator for that
      source;
    - if the entry is marked due/ready, calls
      ``orchestrator.run_source(source_code)`` exactly once and
      records an ``EXECUTED`` outcome carrying the orchestrator's own
      ``SourceAcquisitionOutcome`` (success or failure).

    A source raising anything while being resolved or executed -
    including one not actually registered with ``orchestrator`` - is
    isolated to that source's own outcome (``ok=False`` with an
    explicit ``error_message``) and never prevents sibling sources
    from being considered or executed. This is the only acceptable
    retry boundary: there is no implicit re-attempt here, a caller
    that wants a retry must build a fresh plan and invoke this
    function again explicitly.
    """
    if plan is None:
        raise ValueError("plan es obligatorio: no hay planificación implícita")

    entries = sorted(plan.entries, key=_entry_source_code)
    outcomes = []

    for entry in entries:
        code = _entry_source_code(entry)
        plan_reason = _entry_plan_reason(entry)

        try:
            due = _entry_is_due(entry)
        except ValueError as exc:
            outcomes.append(
                SourceExecutionOutcome(
                    source_code=code,
                    execution_state=EXECUTION_SKIPPED,
                    executed=False,
                    ok=None,
                    plan_reason=SKIP_REASON_UNRESOLVABLE_PLAN_ENTRY,
                    error_message=str(exc)[:500],
                )
            )
            continue

        if not due:
            outcomes.append(
                SourceExecutionOutcome(
                    source_code=code,
                    execution_state=EXECUTION_SKIPPED,
                    executed=False,
                    ok=None,
                    plan_reason=plan_reason or SKIP_REASON_NOT_DUE,
                )
            )
            continue

        try:
            acquisition_outcome = orchestrator.run_source(code)
        except Exception as exc:
            # Isolation boundary: a source that is due but cannot even
            # be resolved/run (e.g. missing from the orchestrator
            # registry, or an adapter_factory failure) must never
            # abort sibling sources' execution.
            outcomes.append(
                SourceExecutionOutcome(
                    source_code=code,
                    execution_state=EXECUTION_EXECUTED,
                    executed=True,
                    ok=False,
                    plan_reason=plan_reason,
                    error_message=str(exc)[:500],
                )
            )
            continue

        outcomes.append(
            SourceExecutionOutcome(
                source_code=code,
                execution_state=EXECUTION_EXECUTED,
                executed=True,
                ok=acquisition_outcome.ok,
                plan_reason=plan_reason,
                acquisition_outcome=acquisition_outcome,
            )
        )

    return ScheduledBatchExecutionReport(outcomes=tuple(outcomes))
