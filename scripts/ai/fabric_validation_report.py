"""FCP-8C-02: auditable validation report V1 - a pure, deterministic,
secret-free, NON-AUTHORITATIVE composition of the FCP-8 evaluations, sealed
with a canonical SHA-256 digest that any consumer can re-verify.

Inputs (exclusively; anything else is recorded as a reason code, never raised)
------------------------------------------------------------------------------
* one observation: `ValidationAssessment` (FCP-8A-01), `SingleRunObservation`
  (FCP-8A-02) or `DagRunObservation` (FCP-8B-01). It is classified with the
  FCP-8B-02 rules (`classify_evidence`), reused verbatim - no fact is ever
  re-derived, upgraded or read from provider prose here;
* optionally one `AcceptanceProjection` (FCP-8C-01). It is re-validated
  through its own construction guard (a tampered projection is refused and
  never serialized) and is only bindable to a single-unit source
  (ASSESSMENT / SINGLE_RUN): a DAG projection carries no acceptance.

Report content (schema `fcp8c02-validation-report-v1`)
------------------------------------------------------
* `sources`: each native source by a safe identifier only - its kind, schema
  and the SHA-256 of its own canonical JSON (`SRC-1` observation, `SRC-2`
  acceptance). Never a run/worker id, path or text.
* `classification`: the FCP-8B-02 `EvidenceClassification.to_dict()`.
* `acceptance`: the FCP-8C-01 `AcceptanceProjection.to_dict()` or null.
* `claims`: VERIFIED / UNKNOWN / FAILED claim ids - one per unit dimension
  (`unit.<index>.<dimension>`, DAG workers in native plan order) plus
  `acceptance.passed` when an acceptance projection is bound. UNKNOWN and
  MALFORMED are never VERIFIED.
* `reason_codes`: the classification codes plus the report's own codes, in a
  fixed vocabulary order (bounded by the vocabulary size).
* `verdict`: HUMAN_REVIEW_REQUIRED on any negative, else UNPROVEN on any
  unknown, else VALIDATION_COMPLETE - advisory, never a permit.
* `manifest`: SHA-256 of each section's canonical JSON; `report_sha256`:
  SHA-256 of the canonical JSON of every other field.
* every authority flag (`certified`, `approved`, `merging_allowed`,
  `execution_allowed`, PR / remote CI / human acceptance / push / phase
  closure ...) fixed to False. A report never certifies anything.

Every string in a report is an enumerated token, schema name or hex digest
matching `SAFE_TOKEN`; no raw provider output, stack trace, token, prompt,
Work Order text, local path, e-mail or secret can be represented.

Canonical form: `json.dumps(sort_keys=True, separators=(",", ":"),
ensure_ascii=True)`, no floats, encoded ASCII - byte-identical for identical
input on any platform. `verify_report` re-derives every derived field from
the report's own sections (re-running the FCP-8 construction guards) and
fails closed on any alteration of fields, order, ids, manifest, digest or
authority flags; given the original inputs it also checks source binding.

Stdlib plus the FCP-8 modules only; no I/O, process, Git, network, environment
or clock. Safety, auth/quota, execution, acceptance and permissions remain
Runner's sole authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields
from typing import Optional

try:
    from scripts.ai import fabric_validation_acceptance as va
    from scripts.ai import fabric_validation_contract as vc
    from scripts.ai import fabric_validation_dag as vd
    from scripts.ai import fabric_validation_rules as vr
    from scripts.ai import fabric_validation_single as vs
except ImportError:  # pragma: no cover - direct script execution
    import fabric_validation_acceptance as va  # type: ignore[no-redef]
    import fabric_validation_contract as vc  # type: ignore[no-redef]
    import fabric_validation_dag as vd  # type: ignore[no-redef]
    import fabric_validation_rules as vr  # type: ignore[no-redef]
    import fabric_validation_single as vs  # type: ignore[no-redef]

SCHEMA = "fcp8c02-validation-report-v1"
SCHEMA_VERSION = 1
REPORT_MARKER = "FCP8C02_VALIDATION_REPORT_ADVISORY_ONLY_NOT_CERTIFIED_NOT_AUTHORIZED"

# Limits (verification refuses anything larger before parsing it).
MAX_REPORT_BYTES = 262144
MAX_DEPTH = 6
MAX_TOKEN_LENGTH = 128
SAFE_TOKEN = re.compile(r"[A-Za-z0-9_.:\-]{1,%d}" % MAX_TOKEN_LENGTH)
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")

# Source kinds and their schemas.
KIND_ASSESSMENT = vr.SOURCE_ASSESSMENT
KIND_SINGLE_RUN = vr.SOURCE_SINGLE_RUN
KIND_DAG_RUN = vr.SOURCE_DAG_RUN
KIND_ACCEPTANCE = "ACCEPTANCE"
SOURCE_SCHEMAS = {
    KIND_ASSESSMENT: (vc.SCHEMA, vc.SCHEMA_VERSION), KIND_SINGLE_RUN: (vs.SCHEMA, vs.SCHEMA_VERSION),
    KIND_DAG_RUN: (vd.SCHEMA, vd.SCHEMA_VERSION), KIND_ACCEPTANCE: (va.SCHEMA, va.SCHEMA_VERSION),
}
OBSERVATION_SOURCE_ID = "SRC-1"
ACCEPTANCE_SOURCE_ID = "SRC-2"
_BINDABLE_SOURCES = (KIND_ASSESSMENT, KIND_SINGLE_RUN)

# Claim statuses and ids.
CLAIM_VERIFIED = "VERIFIED"
CLAIM_UNKNOWN = "UNKNOWN"
CLAIM_FAILED = "FAILED"
CLAIM_STATUSES = (CLAIM_VERIFIED, CLAIM_UNKNOWN, CLAIM_FAILED)
ACCEPTANCE_CLAIM_ID = "acceptance.passed"
_CLAIM_OF_STATE = {vc.STATE_TRUE: CLAIM_VERIFIED, vc.STATE_FALSE: CLAIM_FAILED, vc.STATE_UNKNOWN: CLAIM_UNKNOWN,
                   vc.STATE_MALFORMED: CLAIM_UNKNOWN}

# Report codes beyond the FCP-8B-02 classification codes.
ACCEPTANCE_NOT_TYPED = "ACCEPTANCE_NOT_TYPED"
ACCEPTANCE_INPUT_INCONSISTENT = "ACCEPTANCE_INPUT_INCONSISTENT"
ACCEPTANCE_NOT_BINDABLE = "ACCEPTANCE_NOT_BINDABLE"
SOURCE_NOT_SERIALIZABLE = "SOURCE_NOT_SERIALIZABLE"
ACCEPTANCE_UNPROVEN = "ACCEPTANCE_UNPROVEN"
ACCEPTANCE_FAILED = "ACCEPTANCE_FAILED"
ACCEPTANCE_INCONSISTENT = "ACCEPTANCE_INCONSISTENT"
ACCEPTANCE_CONTRADICTS_OBSERVATION = "ACCEPTANCE_CONTRADICTS_OBSERVATION"
# Codes describing the input as supplied (not derivable from the sections).
INPUT_CODES = (ACCEPTANCE_NOT_TYPED, ACCEPTANCE_INPUT_INCONSISTENT, ACCEPTANCE_NOT_BINDABLE, SOURCE_NOT_SERIALIZABLE)
REPORT_CODES = INPUT_CODES + (ACCEPTANCE_UNPROVEN, ACCEPTANCE_FAILED, ACCEPTANCE_INCONSISTENT,
                              ACCEPTANCE_CONTRADICTS_OBSERVATION)
REPORT_NEGATIVE_CODES = (ACCEPTANCE_FAILED, ACCEPTANCE_INCONSISTENT, ACCEPTANCE_CONTRADICTS_OBSERVATION)
REASON_CODES = vr.CODES + REPORT_CODES
NEGATIVE_CODES = vr.NEGATIVE_CODES + REPORT_NEGATIVE_CODES
UNKNOWN_CODES = tuple(c for c in REASON_CODES if c not in NEGATIVE_CODES)
MAX_REASON_CODES = len(REASON_CODES)

VERDICTS = vr.VERDICTS
MANIFEST_SECTIONS = ("sources", "classification", "acceptance", "claims", "reason_codes")

# Every authority flag, fixed to False in every report.
AUTHORITY_FLAGS = (
    "certified", "approved", "authorizes_action", "execution_allowed", "merging_allowed", "promotion_allowed",
    "auto_retry_allowed", "resume_allowed", "push_allowed", "fallback_allowed", "provider_switch_allowed",
    "pr_certified", "remote_ci_certified", "human_acceptance_certified", "phase_closure_certified",
)

# Verification failure codes, in their fixed canonical order.
VERIFY_CODES = (
    "INPUT_NOT_SUPPORTED", "SIZE_LIMIT_EXCEEDED", "NOT_JSON", "NOT_CANONICAL", "UNSAFE_TEXT",
    "SCHEMA_INVALID", "AUTHORITY_FLAG_INVALID", "CLASSIFICATION_INVALID", "ACCEPTANCE_INVALID",
    "SOURCES_INVALID", "REASON_CODES_INVALID", "MANIFEST_MISMATCH", "DIGEST_MISMATCH", "CONTENT_MISMATCH",
    "SOURCE_BINDING_MISMATCH",
)

_TOP_KEYS = frozenset({
    "schema", "schema_version", "verdict", "sources", "classification", "acceptance", "claims", "claim_counts",
    "reason_codes", "manifest", "report_sha256", "marker",
} | set(AUTHORITY_FLAGS))
_SOURCE_KEYS = frozenset({"source_id", "kind", "schema", "schema_version", "sha256"})


def _ordered(codes, vocabulary) -> tuple:
    return tuple(sorted(set(codes), key=vocabulary.index))


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


# ---------------------------------------------------------------------------
# Input re-validation (construction guards of the upstream contracts)
# ---------------------------------------------------------------------------

def _trusted_acceptance(projection) -> Optional[va.AcceptanceProjection]:
    """A fresh `AcceptanceProjection` equal to `projection`, rebuilt through
    its own construction guards, or None when it no longer satisfies them."""
    try:
        commands = projection.commands
        if type(commands) is not tuple or len(commands) > va.MAX_COMMANDS \
                or any(type(c) is not va.CommandEvidence for c in commands):
            return None
        rebuilt_commands = tuple(va.CommandEvidence(**{f.name: getattr(c, f.name)
                                                       for f in fields(va.CommandEvidence)}) for c in commands)
        values = {f.name: getattr(projection, f.name) for f in fields(va.AcceptanceProjection)}
        values["commands"] = rebuilt_commands
        rebuilt = va.AcceptanceProjection(**values)
        if rebuilt != projection:
            return None
        _canonical(va.AcceptanceProjection.to_dict(rebuilt))
    except (TypeError, ValueError, AttributeError, RecursionError):
        return None
    return rebuilt


def _observation_digest(observation, kind: str) -> Optional[str]:
    serializer = {KIND_ASSESSMENT: vc.canonical_json, KIND_SINGLE_RUN: vs.canonical_json,
                  KIND_DAG_RUN: vd.canonical_json}[kind]
    try:
        text = serializer(observation)
        return _sha256(text) if type(text) is str else None
    except (TypeError, ValueError, AttributeError, UnicodeError, RecursionError):
        return None


# ---------------------------------------------------------------------------
# Assembly (the single derivation both `build_report` and `verify_report` use)
# ---------------------------------------------------------------------------

def _acceptance_codes(classification: vr.EvidenceClassification,
                      acceptance: Optional[va.AcceptanceProjection]) -> list:
    if acceptance is None:
        return []
    codes = []
    if acceptance.status == va.STATUS_FAILED:
        codes.append(ACCEPTANCE_FAILED)
    elif acceptance.status == va.STATUS_INCONSISTENT:
        codes.append(ACCEPTANCE_INCONSISTENT)
    elif acceptance.status != va.STATUS_PASSED:
        codes.append(ACCEPTANCE_UNPROVEN)
    proven = acceptance.acceptance_proven
    index = vc.DIMENSIONS.index(vc.ACCEPTANCE_PROVEN)
    for unit in classification.unit_states:
        state = unit[index]
        if proven is not None and state in (vc.STATE_TRUE, vc.STATE_FALSE) and (state == vc.STATE_TRUE) != proven:
            codes.append(ACCEPTANCE_CONTRADICTS_OBSERVATION)
    return codes


def _claims(classification: vr.EvidenceClassification, acceptance: Optional[va.AcceptanceProjection]) -> dict:
    claims = {status: [] for status in CLAIM_STATUSES}
    for index, unit in enumerate(classification.unit_states):
        for dimension, state in zip(vc.DIMENSIONS, unit):
            claims[_CLAIM_OF_STATE[state]].append(f"unit.{index}.{dimension}")
    if acceptance is not None:
        if acceptance.status == va.STATUS_PASSED:
            status = CLAIM_VERIFIED
        elif acceptance.status in (va.STATUS_FAILED, va.STATUS_INCONSISTENT):
            status = CLAIM_FAILED
        else:
            status = CLAIM_UNKNOWN
        claims[status].append(ACCEPTANCE_CLAIM_ID)
    return {status.lower(): ids for status, ids in claims.items()}


def _sources(classification, acceptance, observation_digest: Optional[str]) -> list:
    sources = []
    if observation_digest is not None:
        schema, version = SOURCE_SCHEMAS[classification.source]
        sources.append({"source_id": OBSERVATION_SOURCE_ID, "kind": classification.source, "schema": schema,
                        "schema_version": version, "sha256": observation_digest})
    if acceptance is not None:
        sources.append({"source_id": ACCEPTANCE_SOURCE_ID, "kind": KIND_ACCEPTANCE, "schema": va.SCHEMA,
                        "schema_version": va.SCHEMA_VERSION,
                        "sha256": _sha256(va.canonical_json(acceptance))})
    return sources


def _assemble(classification: vr.EvidenceClassification, acceptance: Optional[va.AcceptanceProjection],
              observation_digest: Optional[str], input_codes) -> str:
    """Canonical report JSON. Raises ValueError when the parts are mutually
    inconsistent (only reachable from a forged report under verification)."""
    if type(classification) is not vr.EvidenceClassification:
        raise ValueError("classification must be an EvidenceClassification")
    if acceptance is not None and type(acceptance) is not va.AcceptanceProjection:
        raise ValueError("acceptance must be an AcceptanceProjection or None")
    input_codes = tuple(input_codes)
    if any(c not in INPUT_CODES for c in input_codes) or len(set(input_codes)) != len(input_codes):
        raise ValueError("unknown input code")
    acceptance_input = [c for c in input_codes if c != SOURCE_NOT_SERIALIZABLE]
    if len(acceptance_input) > 1 or (acceptance_input and acceptance is not None):
        raise ValueError("at most one acceptance input code, and only without acceptance")
    if ACCEPTANCE_NOT_BINDABLE in input_codes and classification.source in _BINDABLE_SOURCES:
        raise ValueError("ACCEPTANCE_NOT_BINDABLE only for a source that cannot bind acceptance")
    if acceptance is not None and classification.source not in _BINDABLE_SOURCES:
        raise ValueError("acceptance is only bindable to a single-unit source")
    unserializable = SOURCE_NOT_SERIALIZABLE in input_codes
    if unserializable and classification.source == vr.SOURCE_INVALID:
        raise ValueError("an invalid source has nothing to serialize")
    if (observation_digest is None) != (classification.source == vr.SOURCE_INVALID or unserializable):
        raise ValueError("observation digest presence must match the source")
    if observation_digest is not None and not (type(observation_digest) is str
                                               and _SHA256_HEX.fullmatch(observation_digest)):
        raise ValueError("observation digest must be a SHA-256 hex digest")

    reason_codes = _ordered(list(classification.codes) + list(input_codes)
                            + _acceptance_codes(classification, acceptance), REASON_CODES)
    if any(c in NEGATIVE_CODES for c in reason_codes):
        verdict = vr.HUMAN_REVIEW_REQUIRED
    elif any(c in UNKNOWN_CODES for c in reason_codes):
        verdict = vr.UNPROVEN
    else:
        verdict = vr.VALIDATION_COMPLETE
    if verdict == vr.VALIDATION_COMPLETE and not classification.validation_complete:
        raise ValueError("VALIDATION_COMPLETE requires a complete classification")  # pragma: no cover

    claims = _claims(classification, acceptance)
    sections = {
        "sources": _sources(classification, acceptance, observation_digest),
        "classification": vr.EvidenceClassification.to_dict(classification),
        "acceptance": None if acceptance is None else va.AcceptanceProjection.to_dict(acceptance),
        "claims": claims,
        "reason_codes": list(reason_codes),
    }
    body = {
        "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "verdict": verdict, **sections,
        "claim_counts": {status: len(ids) for status, ids in claims.items()},
        "manifest": {name: _sha256(_canonical(sections[name])) for name in MANIFEST_SECTIONS},
        "marker": REPORT_MARKER, **dict.fromkeys(AUTHORITY_FLAGS, False),
    }
    body["report_sha256"] = _sha256(_canonical(body))
    text = _canonical(body)
    if len(text) > MAX_REPORT_BYTES or _unsafe(body, 0):
        raise ValueError("report exceeds limits or carries unsafe text")  # pragma: no cover - by construction
    return text


def _unsafe(value, depth: int) -> bool:
    """True when `value` holds anything but safe tokens, ints, bools, None,
    lists and dicts within MAX_DEPTH."""
    if depth > MAX_DEPTH:
        return True
    if value is None or type(value) in (bool, int):
        return False
    if type(value) is str:
        return SAFE_TOKEN.fullmatch(value) is None
    if type(value) is list:
        return any(_unsafe(v, depth + 1) for v in value)
    if type(value) is dict:
        return any(type(k) is not str or SAFE_TOKEN.fullmatch(k) is None or _unsafe(v, depth + 1)
                   for k, v in value.items())
    return True


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

class _NotAuthorized(vr._NotAuthorized):
    """The rules' zero-authority guarantees plus approval, PR / remote CI /
    human acceptance / phase closure certification - fixed, never fields."""

    @property
    def approved(self) -> bool:
        return False

    @property
    def pr_certified(self) -> bool:
        return False

    @property
    def remote_ci_certified(self) -> bool:
        return False

    @property
    def human_acceptance_certified(self) -> bool:
        return False

    @property
    def phase_closure_certified(self) -> bool:
        return False


@dataclass(frozen=True)
class ValidationReport(_NotAuthorized):
    """Immutable, sealed report: the canonical JSON text itself. Construction
    runs `verify_report`, so a hand-made or altered report is refused."""
    canonical: str

    def __post_init__(self):
        if type(self.canonical) is not str:
            raise ValueError("canonical must be the report JSON text")
        verification = verify_report(self.canonical)
        if not verification.valid:
            raise ValueError("invalid validation report: " + ",".join(verification.codes))

    def to_dict(self) -> dict:
        """A fresh copy; mutating it never affects the report."""
        return json.loads(self.canonical)

    def to_bytes(self) -> bytes:
        return self.canonical.encode("ascii")

    @property
    def report_sha256(self) -> str:
        return self.to_dict()["report_sha256"]

    @property
    def verdict(self) -> str:
        return self.to_dict()["verdict"]

    @property
    def reason_codes(self) -> tuple:
        return tuple(self.to_dict()["reason_codes"])

    @property
    def claims(self) -> dict:
        return {status: tuple(ids) for status, ids in self.to_dict()["claims"].items()}


def canonical_json(report: ValidationReport) -> str:
    """The report's canonical text, for the exact contract type only."""
    if type(report) is not ValidationReport:
        raise TypeError("canonical_json accepts only a ValidationReport")
    return report.canonical


def build_report(observation, acceptance=None) -> ValidationReport:
    """Compose one FCP-8 observation (and optionally its acceptance
    projection) into a sealed report. Pure and idempotent; never raises on
    bad input; never writes, executes, certifies or authorizes anything."""
    classification = vr.classify_evidence(observation)
    input_codes = []
    digest = None
    if classification.source != vr.SOURCE_INVALID:
        digest = _observation_digest(observation, classification.source)
        if digest is None:
            input_codes.append(SOURCE_NOT_SERIALIZABLE)
    bound = None
    if acceptance is not None:
        if type(acceptance) is not va.AcceptanceProjection:
            input_codes.append(ACCEPTANCE_NOT_TYPED)
        else:
            bound = _trusted_acceptance(acceptance)
            if bound is None:
                input_codes.append(ACCEPTANCE_INPUT_INCONSISTENT)
            elif classification.source not in _BINDABLE_SOURCES:
                input_codes.append(ACCEPTANCE_NOT_BINDABLE)
                bound = None
    return ValidationReport(_assemble(classification, bound, digest, input_codes))


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReportVerification(_NotAuthorized):
    """Outcome of `verify_report`. `valid` only says the report is intact and
    self-consistent - never that the work is approved or certified."""
    valid: bool
    codes: tuple
    report_sha256: Optional[str] = None

    def __post_init__(self):
        if type(self.valid) is not bool:
            raise ValueError("valid must be a bool")
        if not (type(self.codes) is tuple and all(type(c) is str and c in VERIFY_CODES for c in self.codes)
                and self.codes == _ordered(self.codes, VERIFY_CODES)):
            raise ValueError("codes must be ordered verification codes")
        if self.valid != (not self.codes) or self.valid != (self.report_sha256 is not None):
            raise ValueError("valid exactly when no code and a digest")


def _fail(*codes) -> ReportVerification:
    return ReportVerification(valid=False, codes=_ordered(codes, VERIFY_CODES))


def _no_duplicates(pairs):
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate key")
    return dict(pairs)


def _reject(_value):
    raise ValueError("non-integer number")


def _parse(text: str):
    return json.loads(text, object_pairs_hook=_no_duplicates, parse_float=_reject, parse_constant=_reject)


def _rebuild_classification(data) -> vr.EvidenceClassification:
    outcomes = data["outcomes"]
    if type(outcomes) is not dict or set(outcomes) != set(vr.OUTCOMES):
        raise ValueError("outcomes")
    units = data["units"]
    if type(units) is not list or len(units) > vd.MAX_WORKERS:
        raise ValueError("units")
    unit_states = []
    for unit in units:
        if type(unit) is not dict or set(unit) != set(vc.DIMENSIONS):
            raise ValueError("unit")
        unit_states.append(tuple(unit[d] for d in vc.DIMENSIONS))
    codes = data["codes"]
    if type(codes) is not list:
        raise ValueError("codes")
    rebuilt = vr.EvidenceClassification(
        source=data["source"], verdict=data["verdict"], work_success=outcomes[vr.WORK_SUCCESS],
        evidence_complete=outcomes[vr.EVIDENCE_COMPLETE], validation_complete=outcomes[vr.VALIDATION_COMPLETE],
        human_review_required=outcomes[vr.HUMAN_REVIEW_REQUIRED], unproven=outcomes[vr.UNPROVEN],
        unit_states=tuple(unit_states), codes=tuple(codes),
    )
    if _canonical(vr.EvidenceClassification.to_dict(rebuilt)) != _canonical(data):
        raise ValueError("classification")
    return rebuilt


def _rebuild_acceptance(data) -> Optional[va.AcceptanceProjection]:
    if data is None:
        return None
    entries = data["commands"]
    if type(entries) is not list or len(entries) > va.MAX_COMMANDS:
        raise ValueError("commands")
    names = [f.name for f in fields(va.CommandEvidence)]
    commands = []
    for entry in entries:
        if type(entry) is not dict:
            raise ValueError("command")
        commands.append(va.CommandEvidence(**{name: entry[name] for name in names}))
    codes = data["codes"]
    if type(codes) is not list:
        raise ValueError("codes")
    rebuilt = va.AcceptanceProjection(
        status=data["status"], configuration=data["configuration"], report=data["report"],
        record_decision=data["record_decision"], commands=tuple(commands), codes=tuple(codes),
    )
    if _canonical(va.AcceptanceProjection.to_dict(rebuilt)) != _canonical(data):
        raise ValueError("acceptance")
    return rebuilt


def _observation_source(sources, classification) -> tuple:
    """(observation digest or None, sources well formed)."""
    if type(sources) is not list or len(sources) > 2:
        return None, False
    for source in sources:
        if type(source) is not dict or set(source) != _SOURCE_KEYS:
            return None, False
        kind = source["kind"]
        if type(kind) is not str or kind not in SOURCE_SCHEMAS \
                or (source["schema"], source["schema_version"]) != SOURCE_SCHEMAS[kind] \
                or type(source["schema_version"]) is not int \
                or type(source["sha256"]) is not str or not _SHA256_HEX.fullmatch(source["sha256"]):
            return None, False
    observation = [s for s in sources if s["kind"] != KIND_ACCEPTANCE]
    if len(observation) > 1 or (observation and observation[0]["kind"] != classification.source):
        return None, False
    return (observation[0]["sha256"] if observation else None), True


def verify_report(report, *, observation=None, acceptance=None) -> ReportVerification:
    """Verify a report given as canonical text (str/bytes, which must be
    byte-identical to its canonical form), a parsed dict or a
    `ValidationReport`. Re-derives every derived field; when `observation`
    (and optionally `acceptance`) is given, also checks that the report is
    exactly `build_report(observation, acceptance)`. Never raises."""
    if type(report) is ValidationReport:
        report = object.__getattribute__(report, "canonical")
    if type(report) is bytes:
        if len(report) > MAX_REPORT_BYTES:
            return _fail("SIZE_LIMIT_EXCEEDED")
        try:
            report = report.decode("ascii")
        except UnicodeDecodeError:
            return _fail("NOT_JSON")
    if type(report) is str:
        if len(report) > MAX_REPORT_BYTES:
            return _fail("SIZE_LIMIT_EXCEEDED")
        text = report
        try:
            data = _parse(text)
        except (ValueError, RecursionError):
            return _fail("NOT_JSON")
        try:
            if _canonical(data) != text:
                return _fail("NOT_CANONICAL")
        except (TypeError, ValueError, RecursionError):  # pragma: no cover - parsed JSON always serializes
            return _fail("NOT_JSON")
    elif type(report) is dict:
        try:
            text = _canonical(report)
            if len(text) > MAX_REPORT_BYTES:
                return _fail("SIZE_LIMIT_EXCEEDED")
            data = _parse(text)
        except (TypeError, ValueError, RecursionError):
            return _fail("NOT_JSON")
    else:
        return _fail("INPUT_NOT_SUPPORTED")

    if type(data) is not dict or _unsafe(data, 0):
        return _fail("UNSAFE_TEXT" if type(data) is dict else "SCHEMA_INVALID")
    if set(data) != _TOP_KEYS or data["schema"] != SCHEMA or data["schema_version"] != SCHEMA_VERSION \
            or type(data["schema_version"]) is not int or data["marker"] != REPORT_MARKER:
        return _fail("SCHEMA_INVALID")
    if any(data[flag] is not False for flag in AUTHORITY_FLAGS):
        return _fail("AUTHORITY_FLAG_INVALID")

    codes = []
    try:
        classification = _rebuild_classification(data["classification"])
    except (KeyError, TypeError, ValueError):
        return _fail("CLASSIFICATION_INVALID")
    try:
        bound = _rebuild_acceptance(data["acceptance"])
    except (KeyError, TypeError, ValueError):
        return _fail("ACCEPTANCE_INVALID")
    digest, sources_ok = _observation_source(data["sources"], classification)
    if not sources_ok:
        return _fail("SOURCES_INVALID")
    reason_codes = data["reason_codes"]
    if not (type(reason_codes) is list and len(reason_codes) <= MAX_REASON_CODES
            and all(type(c) is str and c in REASON_CODES for c in reason_codes)
            and tuple(reason_codes) == _ordered(reason_codes, REASON_CODES)):
        return _fail("REASON_CODES_INVALID")

    manifest = data["manifest"]
    if not (type(manifest) is dict and set(manifest) == set(MANIFEST_SECTIONS)
            and all(manifest[name] == _sha256(_canonical(data[name])) for name in MANIFEST_SECTIONS)):
        codes.append("MANIFEST_MISMATCH")
    body = {k: v for k, v in data.items() if k != "report_sha256"}
    if data["report_sha256"] != _sha256(_canonical(body)):
        codes.append("DIGEST_MISMATCH")
    try:
        expected = _assemble(classification, bound, digest, [c for c in reason_codes if c in INPUT_CODES])
    except ValueError:
        expected = None
    if expected != text:
        codes.append("CONTENT_MISMATCH")
    if not codes and observation is not None:
        try:
            if build_report(observation, acceptance).canonical != text:
                codes.append("SOURCE_BINDING_MISMATCH")
        except ValueError:  # pragma: no cover - build_report never raises on bad input
            codes.append("SOURCE_BINDING_MISMATCH")
    if codes:
        return _fail(*codes)
    return ReportVerification(valid=True, codes=(), report_sha256=data["report_sha256"])
