"""FCP-8C-01: structured acceptance / test-run evidence projection - a pure,
read-only, fail-closed, NON-AUTHORITATIVE reading of ONE Director run's
Runner-owned acceptance record that keeps four questions apart:

* acceptance CONFIGURED: the caller-declared completion contract is
  `completion_policy=runner_acceptance` with at least one command;
* acceptance REPORTED: the run's own `DirectorRunEvidence.acceptance` record
  exists with a string `decision`;
* acceptance PASSED: that record proves, structurally and attributably, that
  every configured command ran under Runner supervision, exited 0 and had its
  process confirmed stopped;
* acceptance UNPROVEN: anything short of PASSED. UNKNOWN is never PASSED.

Sources (the only authority of the projection)
----------------------------------------------
`project_acceptance(evidence, run_id, *, completion_policy=None,
acceptance_commands=None)` reads exactly one `fabric_director.
DirectorRunEvidence` value the caller already holds, plus the completion
contract the caller declared when it submitted the Work Order (the
`DirectorWorkOrderSpec.completion_policy` / `acceptance_commands` fields,
verbatim; None = not declared = UNKNOWN). `DirectorRunEvidence` does not
expose the worker's completion contract, and the only Director reader of it
(`_prior_completion_contract`) is private and performs file I/O, so this
module never calls it, never reads `pipeline.json` and never opens any file.

The acceptance record is `runner_pipeline.PipelineRunner._apply_acceptance`'s
own structured output: a record-level `decision` (PASSED, FAILED,
PROCESS_UNRESOLVED, INTERRUPTED) and, per command, `command`, `argv`,
`exit_code`, `timed_out`, `interrupted`, `process_attached`, `confirmed_dead`,
`process_confirmed_stopped` and the failure flags `error`,
`termination_unresolved`, `keyboard_interrupt`. `stdout_tail`, `stderr_tail`,
`reason`, `normalized_result` and every other provider/terminal text are
NEVER read: no test result is ever parsed from prose, ANSI output or a
provider message.

Known limitation (documented, not worked around)
------------------------------------------------
Runner's acceptance record carries no structured test count or skip count;
those exist only inside `stdout_tail`, which is prose. Every projected
command therefore reports `test_count`/`skip_count` as UNKNOWN and the code
TEST_COUNTS_NOT_IN_RUNNER_CONTRACT is emitted; a key with such a name
inside a command entry is not part of Runner's contract, is not attributable
and is ignored (NON_CONTRACT_FIELD_IGNORED). Proposed future extension (NOT
implemented here; Runner/Director are unchanged): Runner could add an
optional structured per-command `test_summary` (tests_run, skipped, failures)
produced by a Runner-owned reporter, which Director would project verbatim.

PASSED requires, all at once
----------------------------
identity bound (`evidence.run_id == run_id`, pipeline/worker ids present);
configuration CONFIGURED; record decision exactly PASSED; one entry per
declared command, in order, each with `command` equal to the declared
command and `argv` equal to its POSIX `shlex.split` (pure tokenization,
nothing is executed); every entry with integer `exit_code == 0`,
`timed_out`/`interrupted` False, `process_attached`/`confirmed_dead`/
`process_confirmed_stopped` True and no failure flag; `work_status_source ==
RUNNER_ACCEPTANCE`, `work_status == SUCCESS` and `evidence_complete is True`.

Incongruences (status INCONSISTENT, never PASSED)
-------------------------------------------------
a provider_verdict contract with a RUNNER_ACCEPTANCE work status source or
with an acceptance record; a RUNNER_ACCEPTANCE source without a PASSED
record; a PASSED record with a PROVIDER source, without commands, with fewer
commands than declared or contradicted by any of its own command entries;
a command (or argv) that is not the declared one. FAILED, PROCESS_UNRESOLVED
and INTERRUPTED records are FAILED (a negative, preserved).

Output (`AcceptanceProjection`, schema `fcp8c01-acceptance-evidence-v1`)
holds only enumerated codes/states, booleans, command indexes and integer
exit codes - never command text, argv, paths, ids or provider text - and
fixes every authority flag to False. Stdlib (`json`, `shlex`) plus the
FCP-8 contract and Director dataclasses only; no I/O, process, Git, network
or environment. Safety, auth/quota, execution, acceptance and permissions
remain Runner's sole authority.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from typing import Optional

try:
    from scripts.ai import fabric_director as fd
    from scripts.ai import fabric_validation_contract as vc
except ImportError:  # pragma: no cover - direct script execution
    import fabric_director as fd  # type: ignore[no-redef]
    import fabric_validation_contract as vc  # type: ignore[no-redef]

SCHEMA = "fcp8c01-acceptance-evidence-v1"
SCHEMA_VERSION = 1
ACCEPTANCE_MARKER = "FCP8C01_ACCEPTANCE_EVIDENCE_ADVISORY_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

POLICY_RUNNER_ACCEPTANCE = fd.claude_runner.COMPLETION_POLICY_RUNNER_ACCEPTANCE
POLICY_PROVIDER_VERDICT = fd.claude_runner.COMPLETION_POLICY_PROVIDER_VERDICT
SOURCE_RUNNER_ACCEPTANCE = fd.claude_runner.WORK_STATUS_SOURCE_RUNNER_ACCEPTANCE
SOURCE_PROVIDER = fd.claude_runner.WORK_STATUS_SOURCE_PROVIDER

# Limits: anything larger is not projected (fail closed).
MAX_COMMANDS = 64
EXIT_CODE_MIN = -(2 ** 31)
EXIT_CODE_MAX = 2 ** 32 - 1

# Runner `_apply_acceptance` record decisions.
DECISION_PASSED = "PASSED"
FAILED_DECISIONS = frozenset({"FAILED", "PROCESS_UNRESOLVED", "INTERRUPTED"})
RECORD_DECISIONS = frozenset({DECISION_PASSED}) | FAILED_DECISIONS
UNRECOGNIZED = "UNRECOGNIZED"

# Keys Runner's `_apply_acceptance` writes into one command entry.
COMMAND_ENTRY_KEYS = frozenset({
    "command", "argv", "exit_code", "timed_out", "interrupted", "duration_seconds", "stdout_tail", "stderr_tail",
    "process_evidence_path", "process_attached", "confirmed_dead", "process_confirmed_stopped",
    "termination_unresolved", "keyboard_interrupt", "keyboard_interrupt_raised", "error",
})
_FAILURE_FLAGS = ("termination_unresolved", "keyboard_interrupt", "keyboard_interrupt_raised")

# Configuration / report states.
CONFIGURED = "CONFIGURED"
NOT_CONFIGURED = "NOT_CONFIGURED"
CONFIG_UNKNOWN = "UNKNOWN"
CONFIG_MALFORMED = "MALFORMED"
CONFIGURATION_STATES = (CONFIGURED, NOT_CONFIGURED, CONFIG_UNKNOWN, CONFIG_MALFORMED)
REPORTED = "REPORTED"
REPORT_ABSENT = "ABSENT"
REPORT_MALFORMED = "MALFORMED"
REPORT_NOT_ATTRIBUTABLE = "NOT_ATTRIBUTABLE"
REPORT_STATES = (REPORTED, REPORT_ABSENT, REPORT_MALFORMED, REPORT_NOT_ATTRIBUTABLE)

# Per-command tri-states (`vc` vocabulary) and exit code states.
TRI_STATES = vc.STATES
EXIT_ZERO = "ZERO"
EXIT_NONZERO = "NONZERO"
EXIT_UNKNOWN = "UNKNOWN"
EXIT_MALFORMED = "MALFORMED"
EXIT_STATES = (EXIT_ZERO, EXIT_NONZERO, EXIT_UNKNOWN, EXIT_MALFORMED)
TEST_COUNT_UNKNOWN = "UNKNOWN"

# Acceptance status.
STATUS_PASSED = "PASSED"
STATUS_FAILED = "FAILED"
STATUS_INCONSISTENT = "INCONSISTENT"
STATUS_UNPROVEN = "UNPROVEN"
STATUS_NOT_CONFIGURED = "NOT_CONFIGURED"
STATUS_INVALID_INPUT = "INVALID_INPUT"
STATUSES = (STATUS_PASSED, STATUS_FAILED, STATUS_INCONSISTENT, STATUS_UNPROVEN, STATUS_NOT_CONFIGURED,
            STATUS_INVALID_INPUT)

# Codes, in their fixed canonical order.
INCONSISTENCY_CODES = (
    "POLICY_SOURCE_INCONGRUENT", "RECORD_WITHOUT_CONFIGURATION", "SOURCE_WITHOUT_PASSED_RECORD",
    "PASSED_WITHOUT_RUNNER_SOURCE", "PASSED_WITHOUT_COMMANDS", "PASSED_COMMANDS_INCOMPLETE",
    "PASSED_RECORD_CONTRADICTED", "UNAUTHORIZED_COMMAND_REFERENCE", "COMMAND_ARGV_DIVERGES",
)
CODES = (
    "EVIDENCE_NOT_TYPED", "RUN_ID_INVALID", "RUN_ID_MISMATCH", "IDENTITY_MALFORMED", "PIPELINE_ID_MISSING",
    "WORKER_ID_MISSING",
    "CONFIGURATION_UNKNOWN", "CONFIGURATION_MALFORMED",
    "RECORD_ABSENT", "RECORD_MALFORMED", "CONFIGURED_NOT_REPORTED", "DECISION_UNRECOGNIZED", "RECORD_NOT_PASSED",
    "RECORD_PROCESS_UNRESOLVED", "RECORD_INTERRUPTED",
    "COMMANDS_MALFORMED", "COMMANDS_LIMIT_EXCEEDED", "COMMAND_ENTRY_MALFORMED",
    "COMMAND_AUTHORIZATION_UNKNOWN",
    "EXIT_CODE_UNKNOWN", "EXIT_CODE_MALFORMED", "EXIT_CODE_NONZERO", "EXIT_ZERO_WITHOUT_PROCESS_PROOF",
    "COMMAND_TIMED_OUT", "COMMAND_INTERRUPTED", "COMMAND_ERROR", "COMMAND_FLAG_UNKNOWN", "COMMAND_FLAG_MALFORMED",
    "PROCESS_NOT_ATTACHED", "PROCESS_ATTACHMENT_UNKNOWN", "PROCESS_NOT_CONFIRMED_STOPPED",
    "PROCESS_STOP_UNKNOWN",
    "NON_CONTRACT_FIELD_IGNORED", "TEST_COUNTS_NOT_IN_RUNNER_CONTRACT",
    "WORK_STATUS_SOURCE_MISSING", "WORK_STATUS_SOURCE_UNRECOGNIZED", "WORK_STATUS_NOT_SUCCESS",
    "EVIDENCE_NOT_COMPLETE",
) + INCONSISTENCY_CODES


def _ordered(codes) -> tuple:
    return tuple(sorted(set(codes), key=CODES.index))


def _is_id(value) -> bool:
    return type(value) is str and bool(value)


def _tri(value) -> str:
    if value is None:
        return vc.STATE_UNKNOWN
    if type(value) is bool:
        return vc.STATE_TRUE if value else vc.STATE_FALSE
    return vc.STATE_MALFORMED


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CommandEvidence:
    """Projection of one Runner acceptance command entry. Never carries the
    command text, argv, output or paths; `exit_code` is kept only when it is
    a bounded integer (never a bool)."""
    index: int
    authorized: str
    exit_code: Optional[int]
    exit_code_state: str
    timed_out: str
    interrupted: str
    process_attached: str
    confirmed_dead: str
    process_confirmed_stopped: str
    failure_flagged: bool

    def __post_init__(self):
        if type(self.index) is not int or self.index < 1:
            raise ValueError("index must be a positive int")
        for name in ("authorized", "timed_out", "interrupted", "process_attached", "confirmed_dead",
                     "process_confirmed_stopped"):
            if getattr(self, name) not in TRI_STATES:
                raise ValueError(f"{name} must be a tri-state")
        if self.exit_code_state not in EXIT_STATES or type(self.failure_flagged) is not bool:
            raise ValueError("malformed command evidence")
        if self.exit_code is None:
            consistent = self.exit_code_state in (EXIT_UNKNOWN, EXIT_MALFORMED)
        else:
            consistent = (type(self.exit_code) is int and EXIT_CODE_MIN <= self.exit_code <= EXIT_CODE_MAX
                          and self.exit_code_state == (EXIT_ZERO if self.exit_code == 0 else EXIT_NONZERO))
        if not consistent:
            raise ValueError("exit_code_state must match exit_code")

    @property
    def clean(self) -> bool:
        """Structural proof this command passed under Runner supervision."""
        return (self.authorized == vc.STATE_TRUE and self.exit_code_state == EXIT_ZERO
                and self.timed_out == vc.STATE_FALSE and self.interrupted == vc.STATE_FALSE
                and self.process_attached == vc.STATE_TRUE and self.confirmed_dead == vc.STATE_TRUE
                and self.process_confirmed_stopped == vc.STATE_TRUE and not self.failure_flagged)

    @property
    def contradicts_pass(self) -> bool:
        """A definitive negative fact a PASSED record cannot carry."""
        return (self.exit_code_state == EXIT_NONZERO or self.timed_out == vc.STATE_TRUE
                or self.interrupted == vc.STATE_TRUE or self.process_attached == vc.STATE_FALSE
                or self.confirmed_dead == vc.STATE_FALSE or self.process_confirmed_stopped == vc.STATE_FALSE
                or self.failure_flagged)

    def to_dict(self) -> dict:
        return {
            "index": self.index, "authorized": self.authorized, "exit_code": self.exit_code,
            "exit_code_state": self.exit_code_state, "timed_out": self.timed_out, "interrupted": self.interrupted,
            "process_attached": self.process_attached, "confirmed_dead": self.confirmed_dead,
            "process_confirmed_stopped": self.process_confirmed_stopped, "failure_flagged": self.failure_flagged,
            "clean": self.clean, "test_count": TEST_COUNT_UNKNOWN, "skip_count": TEST_COUNT_UNKNOWN,
        }


@dataclass(frozen=True)
class AcceptanceProjection(vc._NotAuthorized):
    """Advisory acceptance evidence for one run. A hand-made PASSED that its
    own configuration, record and commands do not prove is refused."""
    status: str
    configuration: str
    report: str
    record_decision: Optional[str]
    commands: tuple
    codes: tuple

    def __post_init__(self):
        if self.status not in STATUSES or self.configuration not in CONFIGURATION_STATES \
                or self.report not in REPORT_STATES:
            raise ValueError("unknown acceptance status/configuration/report")
        if self.record_decision is not None and self.record_decision not in RECORD_DECISIONS | {UNRECOGNIZED}:
            raise ValueError("unknown record decision")
        if not (type(self.commands) is tuple and all(type(c) is CommandEvidence for c in self.commands)
                and tuple(c.index for c in self.commands) == tuple(range(1, len(self.commands) + 1))):
            raise ValueError("commands must be ordered CommandEvidence")
        if not (type(self.codes) is tuple and all(type(c) is str and c in CODES for c in self.codes)
                and self.codes == _ordered(self.codes)):
            raise ValueError("codes must be ordered acceptance codes")
        has_inconsistency = any(c in INCONSISTENCY_CODES for c in self.codes)
        if (self.status == STATUS_INCONSISTENT) != has_inconsistency:
            raise ValueError("INCONSISTENT exactly when an inconsistency code is present")
        if self.status == STATUS_PASSED and not (
                self.configuration == CONFIGURED and self.report == REPORTED
                and self.record_decision == DECISION_PASSED and self.commands
                and all(c.clean for c in self.commands)
                and set(self.codes) <= {"TEST_COUNTS_NOT_IN_RUNNER_CONTRACT", "NON_CONTRACT_FIELD_IGNORED"}):
            raise ValueError("PASSED must be proven by its own configuration, record and commands")
        if self.status == STATUS_FAILED and self.record_decision not in FAILED_DECISIONS:
            raise ValueError("FAILED requires a failed Runner record")

    @property
    def acceptance_configured(self) -> bool:
        return self.configuration == CONFIGURED

    @property
    def acceptance_reported(self) -> bool:
        return self.report == REPORTED

    @property
    def acceptance_passed(self) -> bool:
        return self.status == STATUS_PASSED

    @property
    def acceptance_unproven(self) -> bool:
        return self.status != STATUS_PASSED

    @property
    def acceptance_proven(self) -> Optional[bool]:
        """The `ValidationFacts.acceptance_proven` tri-state this projection
        supports: True only PASSED, False only FAILED, otherwise UNKNOWN."""
        if self.status == STATUS_PASSED:
            return True
        if self.status == STATUS_FAILED:
            return False
        return None

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "status": self.status,
            "configuration": self.configuration, "report": self.report, "record_decision": self.record_decision,
            "acceptance_configured": self.acceptance_configured, "acceptance_reported": self.acceptance_reported,
            "acceptance_passed": self.acceptance_passed, "acceptance_unproven": self.acceptance_unproven,
            "commands": [c.to_dict() for c in self.commands], "codes": list(self.codes),
            "marker": ACCEPTANCE_MARKER, "certified": False, "authorizes_action": False, "execution_allowed": False,
            "merging_allowed": False, "promotion_allowed": False, "auto_retry_allowed": False,
            "resume_allowed": False,
        }


def canonical_json(projection: AcceptanceProjection) -> str:
    """Stable, sorted, compact serialization of the exact contract type."""
    if type(projection) is not AcceptanceProjection:
        raise TypeError("canonical_json accepts only an AcceptanceProjection")
    return json.dumps(AcceptanceProjection.to_dict(projection), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


def _unproven(codes, configuration=CONFIG_UNKNOWN, report=REPORT_NOT_ATTRIBUTABLE,
              status=STATUS_UNPROVEN) -> AcceptanceProjection:
    return AcceptanceProjection(status=status, configuration=configuration, report=report, record_decision=None,
                                commands=(), codes=_ordered(codes))


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

def _configuration(completion_policy, acceptance_commands) -> tuple:
    """(state, declared commands tuple or None)."""
    if completion_policy is None and acceptance_commands is None:
        return CONFIG_UNKNOWN, None
    if type(acceptance_commands) not in (list, tuple, type(None)):
        return CONFIG_MALFORMED, None
    commands = tuple(acceptance_commands or ())
    if len(commands) > MAX_COMMANDS or any(type(c) is not str or not c.strip() for c in commands):
        return CONFIG_MALFORMED, None
    if type(completion_policy) is str and completion_policy == POLICY_RUNNER_ACCEPTANCE and commands:
        return CONFIGURED, commands
    if type(completion_policy) is str and completion_policy == POLICY_PROVIDER_VERDICT and not commands:
        return NOT_CONFIGURED, ()
    return CONFIG_MALFORMED, None


def _authorized(entry: dict, index: int, declared: Optional[tuple], codes: list) -> str:
    command, argv = entry.get("command"), entry.get("argv")
    if type(command) is not str:
        codes.append("COMMAND_ENTRY_MALFORMED")
        return vc.STATE_MALFORMED
    try:
        expected_argv = shlex.split(command, posix=True)
    except ValueError:
        expected_argv = None
    if type(argv) is not list or not all(type(a) is str for a in argv) or argv != expected_argv:
        codes.append("COMMAND_ARGV_DIVERGES")
        return vc.STATE_FALSE
    if declared is None:
        codes.append("COMMAND_AUTHORIZATION_UNKNOWN")
        return vc.STATE_UNKNOWN
    if index > len(declared) or declared[index - 1] != command:
        codes.append("UNAUTHORIZED_COMMAND_REFERENCE")
        return vc.STATE_FALSE
    return vc.STATE_TRUE


def _command(entry, index: int, declared: Optional[tuple], codes: list) -> Optional[CommandEvidence]:
    if type(entry) is not dict or not all(type(k) is str for k in entry):
        codes.append("COMMAND_ENTRY_MALFORMED")
        return None
    if set(entry) - COMMAND_ENTRY_KEYS:
        codes.append("NON_CONTRACT_FIELD_IGNORED")
    authorized = _authorized(entry, index, declared, codes)

    raw_exit = entry.get("exit_code")
    exit_code = None
    if raw_exit is None:
        exit_state = EXIT_UNKNOWN
        codes.append("EXIT_CODE_UNKNOWN")
    elif type(raw_exit) is not int or not EXIT_CODE_MIN <= raw_exit <= EXIT_CODE_MAX:
        exit_state = EXIT_MALFORMED
        codes.append("EXIT_CODE_MALFORMED")
    else:
        exit_code = raw_exit
        exit_state = EXIT_ZERO if raw_exit == 0 else EXIT_NONZERO
        if raw_exit != 0:
            codes.append("EXIT_CODE_NONZERO")

    states = {name: _tri(entry.get(name)) for name in (
        "timed_out", "interrupted", "process_attached", "confirmed_dead", "process_confirmed_stopped")}
    if any(s == vc.STATE_MALFORMED for s in states.values()):
        codes.append("COMMAND_FLAG_MALFORMED")
    for name, true_code in (("timed_out", "COMMAND_TIMED_OUT"), ("interrupted", "COMMAND_INTERRUPTED")):
        if states[name] == vc.STATE_TRUE:
            codes.append(true_code)
        elif states[name] == vc.STATE_UNKNOWN:
            codes.append("COMMAND_FLAG_UNKNOWN")
    if states["process_attached"] == vc.STATE_FALSE:
        codes.append("PROCESS_NOT_ATTACHED")
    elif states["process_attached"] != vc.STATE_TRUE:
        codes.append("PROCESS_ATTACHMENT_UNKNOWN")
    stops = (states["confirmed_dead"], states["process_confirmed_stopped"])
    if vc.STATE_FALSE in stops:
        codes.append("PROCESS_NOT_CONFIRMED_STOPPED")
    elif any(s != vc.STATE_TRUE for s in stops):
        codes.append("PROCESS_STOP_UNKNOWN")
    if exit_state == EXIT_ZERO and (states["process_attached"] != vc.STATE_TRUE
                                    or any(s != vc.STATE_TRUE for s in stops)):
        codes.append("EXIT_ZERO_WITHOUT_PROCESS_PROOF")

    failure_flagged = entry.get("error") is not None or any(entry.get(f) is not None and entry.get(f) is not False
                                                            for f in _FAILURE_FLAGS)
    if entry.get("error") is not None:
        codes.append("COMMAND_ERROR")
    return CommandEvidence(
        index=index, authorized=authorized, exit_code=exit_code, exit_code_state=exit_state,
        failure_flagged=failure_flagged, **states,
    )


def project_acceptance(evidence, run_id, *, completion_policy=None, acceptance_commands=None
                       ) -> AcceptanceProjection:
    """Project one `DirectorRunEvidence` acceptance record. Never raises on bad
    input; never reads prose, opens a file, runs a command, certifies or
    authorizes anything."""
    if type(evidence) is not fd.DirectorRunEvidence:
        return _unproven(("EVIDENCE_NOT_TYPED",), status=STATUS_INVALID_INPUT)
    if not _is_id(run_id):
        return _unproven(("RUN_ID_INVALID",), status=STATUS_INVALID_INPUT)
    configuration, declared = _configuration(completion_policy, acceptance_commands)
    identity = (evidence.run_id, evidence.pipeline_id, evidence.worker_id)
    if not all(v is None or type(v) is str for v in identity):
        return _unproven(("IDENTITY_MALFORMED",), configuration)
    if evidence.run_id != run_id:
        return _unproven(("RUN_ID_MISMATCH",), configuration)
    missing = [code for value, code in ((evidence.pipeline_id, "PIPELINE_ID_MISSING"),
                                        (evidence.worker_id, "WORKER_ID_MISSING")) if not _is_id(value)]
    if missing:
        return _unproven(missing, configuration)

    codes: list = []
    if configuration == CONFIG_UNKNOWN:
        codes.append("CONFIGURATION_UNKNOWN")
    elif configuration == CONFIG_MALFORMED:
        codes.append("CONFIGURATION_MALFORMED")

    source = evidence.work_status_source
    if source is None:
        codes.append("WORK_STATUS_SOURCE_MISSING")
    elif type(source) is not str or source not in fd.claude_runner.WORK_STATUS_SOURCES:
        codes.append("WORK_STATUS_SOURCE_UNRECOGNIZED")
    runner_sourced = type(source) is str and source == SOURCE_RUNNER_ACCEPTANCE

    record = evidence.acceptance
    decision = None
    commands: list = []
    if record is None:
        report = REPORT_ABSENT
        codes.append("RECORD_ABSENT")
        if configuration == CONFIGURED:
            codes.append("CONFIGURED_NOT_REPORTED")
    elif type(record) is not dict or type(record.get("decision")) is not str:
        report = REPORT_MALFORMED
        codes.append("RECORD_MALFORMED")
    else:
        report = REPORTED
        raw = record["decision"]
        decision = raw if raw in RECORD_DECISIONS else UNRECOGNIZED
        if decision == UNRECOGNIZED:
            codes.append("DECISION_UNRECOGNIZED")
        elif decision in FAILED_DECISIONS:
            codes.append("RECORD_NOT_PASSED")
            if decision == "PROCESS_UNRESOLVED":
                codes.append("RECORD_PROCESS_UNRESOLVED")
            elif decision == "INTERRUPTED":
                codes.append("RECORD_INTERRUPTED")
        if record.get("termination_unresolved") is not None and record.get("termination_unresolved") is not False:
            codes.append("PROCESS_NOT_CONFIRMED_STOPPED")
        entries = record.get("commands")
        if type(entries) is not list:
            codes.append("COMMANDS_MALFORMED")
        elif len(entries) > MAX_COMMANDS:
            codes.append("COMMANDS_LIMIT_EXCEEDED")
        else:
            projected = [_command(e, i, declared, codes) for i, e in enumerate(entries, start=1)]
            if any(c is None for c in projected):
                codes.append("COMMANDS_MALFORMED")
            else:
                commands = projected
        codes.append("TEST_COUNTS_NOT_IN_RUNNER_CONTRACT")

    # Incongruences between the declared contract, the work status source and
    # the record. None of these executes or re-checks anything.
    if configuration == NOT_CONFIGURED and runner_sourced:
        codes.append("POLICY_SOURCE_INCONGRUENT")
    if configuration == NOT_CONFIGURED and record is not None:
        codes.append("RECORD_WITHOUT_CONFIGURATION")
    if runner_sourced and decision != DECISION_PASSED:
        codes.append("SOURCE_WITHOUT_PASSED_RECORD")
    if decision == DECISION_PASSED:
        if type(source) is str and source == SOURCE_PROVIDER:
            codes.append("PASSED_WITHOUT_RUNNER_SOURCE")
        if type(record.get("commands")) is list and not record["commands"]:
            codes.append("PASSED_WITHOUT_COMMANDS")
        if declared and commands and len(commands) < len(declared):
            codes.append("PASSED_COMMANDS_INCOMPLETE")
        if any(c.contradicts_pass for c in commands) or "PROCESS_NOT_CONFIRMED_STOPPED" in codes:
            codes.append("PASSED_RECORD_CONTRADICTED")
        if type(evidence.work_status) is not str or evidence.work_status != "SUCCESS":
            codes.append("WORK_STATUS_NOT_SUCCESS")
        if evidence.evidence_complete is not True:
            codes.append("EVIDENCE_NOT_COMPLETE")

    codes = _ordered(codes)
    benign = {"TEST_COUNTS_NOT_IN_RUNNER_CONTRACT", "NON_CONTRACT_FIELD_IGNORED"}
    if any(c in INCONSISTENCY_CODES for c in codes):
        status = STATUS_INCONSISTENT
    elif decision in FAILED_DECISIONS:
        status = STATUS_FAILED
    elif (decision == DECISION_PASSED and configuration == CONFIGURED and commands
          and len(commands) == len(declared) and all(c.clean for c in commands) and set(codes) <= benign):
        status = STATUS_PASSED
    elif configuration == NOT_CONFIGURED and record is None and not runner_sourced:
        status = STATUS_NOT_CONFIGURED
    else:
        status = STATUS_UNPROVEN
    return AcceptanceProjection(status=status, configuration=configuration, report=report,
                                record_decision=decision, commands=tuple(commands), codes=codes)
