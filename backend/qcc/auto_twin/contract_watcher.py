"""QCC Contract Watcher — deterministic evolution evidence for a Site Contract.

Contract Watcher does not observe REAL sites, does not run a browser and does
not build a second Site Architecture model. It consumes two already-normalized
QCC Site Architecture contracts (the same contract produced by
``backend.automation.site_architecture``) and produces immutable, PII-safe
evidence describing whether the contract evolved between two observations of
the same logical surface.

Two independent dimensions are reported, deliberately not conflated:

``ContractWatchSeverity``
    WHAT kind of change was detected (COSMETIC / NON_BREAKING /
    CONTRACT_CHANGE / BREAKING / UNKNOWN).

``ContractWatchState``
    WHAT the watcher lifecycle should do about it (NO_CHANGE /
    CHANGE_SUSPECTED / CHANGE_CONFIRMED / REBUILD_REQUIRED /
    VALIDATION_REQUIRED).

Element/page structural comparison reuses
``backend.automation.site_architecture.contract_diff.diff_site_architecture``.
Functional identity reuses
``backend.automation.site_architecture.state_fingerprint``. This module adds
only what does not already exist: catalog/option evolution, severity
classification, watch-state lifecycle and deterministic evidence packaging.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json

from backend.automation.site_architecture.contract_diff import (
    ContractChange,
    DEFAULT_GEOMETRY_TOLERANCE_PX,
    GEOMETRY_CHANGED,
    INTERACTION_CHANGED,
    SELECTOR_CHANGED,
    SEMANTICS_CHANGED,
    diff_site_architecture,
)
from backend.automation.site_architecture.models import (
    SiteArchitectureSnapshot,
)
from backend.automation.site_architecture.schema import (
    require_supported_schema_version,
)
from backend.automation.site_architecture.snapshot import (
    build_normalized_snapshot_payload,
)
from backend.automation.site_architecture.state_fingerprint import (
    build_functional_state_fingerprint,
)


CONTRACT_WATCHER_SCHEMA_VERSION = 1

CONTRACT_WATCHER_EVIDENCE_TYPE = "QCC_CONTRACT_WATCHER_EVIDENCE"

CONTRACT_WATCHER_EVIDENCE_ID_PREFIX = "cwev-"


class ContractWatchSeverity(str, Enum):
    COSMETIC = "COSMETIC"
    NON_BREAKING = "NON_BREAKING"
    CONTRACT_CHANGE = "CONTRACT_CHANGE"
    BREAKING = "BREAKING"
    UNKNOWN = "UNKNOWN"


class ContractWatchState(str, Enum):
    NO_CHANGE = "NO_CHANGE"
    CHANGE_SUSPECTED = "CHANGE_SUSPECTED"
    CHANGE_CONFIRMED = "CHANGE_CONFIRMED"
    REBUILD_REQUIRED = "REBUILD_REQUIRED"
    VALIDATION_REQUIRED = "VALIDATION_REQUIRED"


_SEVERITY_ORDER = (
    ContractWatchSeverity.COSMETIC,
    ContractWatchSeverity.NON_BREAKING,
    ContractWatchSeverity.CONTRACT_CHANGE,
    ContractWatchSeverity.BREAKING,
)

# Element-level reasons that do not map 1:1 to ADDED/REMOVED (which are
# already BREAKING/NON_BREAKING by construction) get a severity here.
_ELEMENT_REASON_SEVERITY = {
    GEOMETRY_CHANGED: ContractWatchSeverity.COSMETIC,
    INTERACTION_CHANGED: ContractWatchSeverity.CONTRACT_CHANGE,
    SEMANTICS_CHANGED: ContractWatchSeverity.CONTRACT_CHANGE,
    SELECTOR_CHANGED: ContractWatchSeverity.CONTRACT_CHANGE,
}


def _severity_rank(value):
    return _SEVERITY_ORDER.index(value)


def _text(value):
    value = str(value or "").strip()
    return value or None


def _required_text(value, *, error):
    result = _text(value)

    if not result:
        raise ValueError(error)

    return result


def _utc_timestamp(value=None):
    if value is None:
        return (
            datetime.now(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )

    result = _required_text(
        value,
        error="QCC_CONTRACT_WATCHER_CREATED_AT_INVALID",
    )

    candidate = result

    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(
            "QCC_CONTRACT_WATCHER_CREATED_AT_INVALID"
        ) from exc

    if parsed.tzinfo is None:
        raise ValueError(
            "QCC_CONTRACT_WATCHER_CREATED_AT_TIMEZONE_REQUIRED"
        )

    return result


def _jsonable(value):
    """Recursively converts tuples to lists for stable JSON persistence."""

    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]

    return value


def _require_contract_payload(value, *, error):
    if isinstance(value, SiteArchitectureSnapshot):
        return build_normalized_snapshot_payload(value)

    if not isinstance(value, dict):
        raise ValueError(error)

    require_supported_schema_version(value.get("schema_version"))

    return value


# ---------------------------------------------------------------------------
# Catalog / option evolution.
#
# diff_site_architecture() only compares "elements" and "page" identity. It
# deliberately does not know about catalogs, so a catalog/option contract
# change (a governed capability required by this Work Order) is computed
# here, reusing the same identity conventions already established by
# backend.automation.site_architecture.catalogs (catalog_key, or
# frame_path + selector when catalog_key is absent from the input payload).
# ---------------------------------------------------------------------------


def _catalog_identity(catalog):
    if not isinstance(catalog, dict):
        return None

    key = _text(catalog.get("catalog_key"))

    if key:
        return key

    selector = _text(catalog.get("selector"))

    if not selector:
        return None

    frame_path = _text(catalog.get("frame_path")) or "main"

    return frame_path + "::" + selector


def _option_signature_set(catalog):
    result = set()

    for option in catalog.get("options") or ():
        if not isinstance(option, dict):
            continue

        result.add((
            _text(option.get("value")) or "",
            _text(option.get("label")) or "",
            bool(option.get("disabled")),
        ))

    return result


def _catalog_index(catalogs):
    positions_by_identity = {}
    unmatched = []

    for position, catalog in enumerate(catalogs):
        identity = _catalog_identity(catalog)

        if identity is None:
            unmatched.append(position)
            continue

        positions_by_identity.setdefault(identity, []).append(
            (position, catalog)
        )

    index = {}

    for identity, entries in positions_by_identity.items():
        if len(entries) == 1:
            index[identity] = entries[0][1]
            continue

        # A duplicated identity cannot be trusted for comparison.
        # Fail closed towards "unmatched" for every occurrence instead
        # of silently guessing or dropping one of them.
        unmatched.extend(position for position, _ in entries)

    return index, tuple(sorted(unmatched))


def _diff_catalogs(before_payload, after_payload):
    before_index, before_unmatched = _catalog_index(
        tuple(before_payload.get("catalogs") or ())
    )

    after_index, after_unmatched = _catalog_index(
        tuple(after_payload.get("catalogs") or ())
    )

    before_keys = set(before_index)
    after_keys = set(after_index)

    catalogs_added = tuple(sorted(after_keys - before_keys))
    catalogs_removed = tuple(sorted(before_keys - after_keys))

    option_changes = []

    for key in sorted(before_keys & after_keys):
        before_options = _option_signature_set(before_index[key])
        after_options = _option_signature_set(after_index[key])

        options_added = tuple(sorted(after_options - before_options))
        options_removed = tuple(sorted(before_options - after_options))

        if options_added or options_removed:
            option_changes.append({
                "catalog_key": key,
                "options_added": [list(item) for item in options_added],
                "options_removed": [list(item) for item in options_removed],
            })

    return {
        "catalogs_added": list(catalogs_added),
        "catalogs_removed": list(catalogs_removed),
        "option_changes": option_changes,
        "unmatched_before": list(before_unmatched),
        "unmatched_after": list(after_unmatched),
    }


# ---------------------------------------------------------------------------
# Severity / watch-state classification.
# ---------------------------------------------------------------------------


def _element_change_severity(reasons):
    severity = ContractWatchSeverity.COSMETIC

    for reason in reasons:
        candidate = _ELEMENT_REASON_SEVERITY.get(
            reason,
            ContractWatchSeverity.CONTRACT_CHANGE,
        )

        if _severity_rank(candidate) > _severity_rank(severity):
            severity = candidate

    return severity


def _classify_severity(*, contract_diff, catalog_diff):
    severity = ContractWatchSeverity.COSMETIC
    detected = False

    def _observe(candidate):
        nonlocal severity, detected
        detected = True
        if _severity_rank(candidate) > _severity_rank(severity):
            severity = candidate

    if contract_diff["page"]["changed"]:
        _observe(ContractWatchSeverity.BREAKING)

    for item in contract_diff["elements"]:
        change = item["change"]

        if change == ContractChange.REMOVED.value:
            _observe(ContractWatchSeverity.BREAKING)
        elif change == ContractChange.ADDED.value:
            _observe(ContractWatchSeverity.NON_BREAKING)
        elif change == ContractChange.CHANGED.value:
            _observe(_element_change_severity(item["changes"]))

    if catalog_diff["catalogs_removed"]:
        _observe(ContractWatchSeverity.BREAKING)

    if catalog_diff["catalogs_added"]:
        _observe(ContractWatchSeverity.NON_BREAKING)

    for entry in catalog_diff["option_changes"]:
        if entry["options_removed"]:
            _observe(ContractWatchSeverity.BREAKING)
        if entry["options_added"]:
            _observe(ContractWatchSeverity.NON_BREAKING)

    return severity, detected


def _classify_watch_state(*, inconclusive, detected, fingerprint_changed, severity):
    if inconclusive:
        return ContractWatchState.VALIDATION_REQUIRED

    if not detected and not fingerprint_changed:
        return ContractWatchState.NO_CHANGE

    if severity == ContractWatchSeverity.BREAKING:
        return ContractWatchState.REBUILD_REQUIRED

    if severity in (
        ContractWatchSeverity.CONTRACT_CHANGE,
        ContractWatchSeverity.NON_BREAKING,
    ):
        return ContractWatchState.CHANGE_CONFIRMED

    # COSMETIC-only structural changes, or a functional fingerprint drift
    # that the element/catalog diff could not itself attribute to a
    # concrete addition/removal/change, are reported as suspected rather
    # than confirmed.
    return ContractWatchState.CHANGE_SUSPECTED


def _summarize(
    *,
    watch_state,
    severity,
    counts,
    catalog_diff,
    page_changed,
    inconclusive,
):
    if inconclusive:
        return (
            "Contract comparison inconclusive: element or catalog identity "
            "could not be matched unambiguously; manual validation required."
        )

    options_added = sum(
        len(entry["options_added"]) for entry in catalog_diff["option_changes"]
    )

    options_removed = sum(
        len(entry["options_removed"]) for entry in catalog_diff["option_changes"]
    )

    return (
        "watch_state={watch_state} severity={severity} page_changed={page_changed} "
        "elements[added={added} removed={removed} changed={changed} unchanged={unchanged}] "
        "catalogs[added={catalogs_added} removed={catalogs_removed} "
        "options_added={options_added} options_removed={options_removed}]"
    ).format(
        watch_state=watch_state.value,
        severity=severity.value,
        page_changed=page_changed,
        added=counts.get("ADDED", 0),
        removed=counts.get("REMOVED", 0),
        changed=counts.get("CHANGED", 0),
        unchanged=counts.get("UNCHANGED", 0),
        catalogs_added=len(catalog_diff["catalogs_added"]),
        catalogs_removed=len(catalog_diff["catalogs_removed"]),
        options_added=options_added,
        options_removed=options_removed,
    )


def compare_site_contract_revision(
    before,
    after,
    *,
    geometry_tolerance_px=DEFAULT_GEOMETRY_TOLERANCE_PX,
):
    """Deterministically compares two normalized Site Contract observations.

    Accepts a ``SiteArchitectureSnapshot`` or an already-normalized dict for
    ``before``/``after`` (same contract accepted by ``diff_site_architecture``
    and ``build_functional_state_fingerprint``). Fails closed: malformed
    input or an unsupported/missing schema version raises ``ValueError``
    instead of ever returning ``NO_CHANGE``.
    """

    before_payload = _require_contract_payload(
        before,
        error="QCC_CONTRACT_WATCHER_BEFORE_CONTRACT_INVALID",
    )

    after_payload = _require_contract_payload(
        after,
        error="QCC_CONTRACT_WATCHER_AFTER_CONTRACT_INVALID",
    )

    contract_diff = diff_site_architecture(
        before_payload,
        after_payload,
        geometry_tolerance_px=geometry_tolerance_px,
    )

    catalog_diff = _diff_catalogs(before_payload, after_payload)

    before_fingerprint = build_functional_state_fingerprint(before_payload)
    after_fingerprint = build_functional_state_fingerprint(after_payload)

    fingerprint_changed = before_fingerprint != after_fingerprint

    inconclusive = (
        bool(contract_diff["inconclusive"])
        or bool(catalog_diff["unmatched_before"])
        or bool(catalog_diff["unmatched_after"])
    )

    severity, detected = _classify_severity(
        contract_diff=contract_diff,
        catalog_diff=catalog_diff,
    )

    if inconclusive:
        severity = ContractWatchSeverity.UNKNOWN

    watch_state = _classify_watch_state(
        inconclusive=inconclusive,
        detected=detected,
        fingerprint_changed=fingerprint_changed,
        severity=severity,
    )

    counts = dict(contract_diff["counts"])

    page_changed = bool(contract_diff["page"]["changed"])

    summary = _summarize(
        watch_state=watch_state,
        severity=severity,
        counts=counts,
        catalog_diff=catalog_diff,
        page_changed=page_changed,
        inconclusive=inconclusive,
    )

    return {
        "site_architecture_schema_version": before_payload["schema_version"],
        "geometry_tolerance_px": float(contract_diff["geometry_tolerance_px"]),
        "before_functional_fingerprint": before_fingerprint,
        "after_functional_fingerprint": after_fingerprint,
        "fingerprint_changed": fingerprint_changed,
        "severity": severity.value,
        "watch_state": watch_state.value,
        "inconclusive": inconclusive,
        "page_changed": page_changed,
        "counts": counts,
        "elements": _jsonable(contract_diff["elements"]),
        "unmatched_before": _jsonable(contract_diff["unmatched_before"]),
        "unmatched_after": _jsonable(contract_diff["unmatched_after"]),
        "catalog_diff": catalog_diff,
        "summary": summary,
    }


def _evidence_id(identity_payload):
    encoded = json.dumps(
        identity_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    digest = hashlib.sha256(
        b"QCC_CONTRACT_WATCHER_EVIDENCE_V1\0" + encoded
    ).hexdigest()

    return CONTRACT_WATCHER_EVIDENCE_ID_PREFIX + digest[:24]


def build_contract_watcher_evidence(
    *,
    contract_key,
    before,
    after,
    before_reference=None,
    after_reference=None,
    geometry_tolerance_px=DEFAULT_GEOMETRY_TOLERANCE_PX,
    created_at=None,
):
    """Builds immutable, deterministic Contract Watcher evidence.

    ``contract_key`` is an opaque caller-supplied identity for the watched
    logical contract (for example an existing AUTO TWIN ``state_id`` or
    site-contract key). This module never derives or redefines that
    identity; it only tags evidence with it. ``before_reference``/
    ``after_reference`` are optional opaque references to the existing
    capture/revision evidence that produced ``before``/``after`` (never the
    raw content itself).
    """

    normalized_contract_key = _required_text(
        contract_key,
        error="QCC_CONTRACT_WATCHER_CONTRACT_KEY_REQUIRED",
    )

    comparison = compare_site_contract_revision(
        before,
        after,
        geometry_tolerance_px=geometry_tolerance_px,
    )

    identity_payload = {
        "schema_version": CONTRACT_WATCHER_SCHEMA_VERSION,
        "evidence_type": CONTRACT_WATCHER_EVIDENCE_TYPE,
        "contract_key": normalized_contract_key,
        "before_reference": _text(before_reference),
        "after_reference": _text(after_reference),
    }

    identity_payload.update(comparison)

    evidence_id = _evidence_id(identity_payload)

    record = dict(identity_payload)
    record["evidence_id"] = evidence_id
    record["created_at"] = _utc_timestamp(created_at)

    return record


def validate_contract_watcher_evidence(record):
    """Validates structural integrity and determinism of persisted evidence.

    Recomputes ``evidence_id`` from the record's own persisted content and
    fails closed on any mismatch (tampering, hand-edited fixtures, or a
    non-canonical record). This does not require the original ``before``/
    ``after`` contracts to remain available, so raw page content never needs
    to be retained merely to validate stored evidence.
    """

    if not isinstance(record, dict):
        raise TypeError("QCC_CONTRACT_WATCHER_EVIDENCE_INVALID")

    if record.get("schema_version") != CONTRACT_WATCHER_SCHEMA_VERSION:
        raise ValueError(
            "QCC_CONTRACT_WATCHER_EVIDENCE_SCHEMA_VERSION_INVALID"
        )

    if record.get("evidence_type") != CONTRACT_WATCHER_EVIDENCE_TYPE:
        raise ValueError("QCC_CONTRACT_WATCHER_EVIDENCE_TYPE_INVALID")

    _required_text(
        record.get("contract_key"),
        error="QCC_CONTRACT_WATCHER_EVIDENCE_CONTRACT_KEY_INVALID",
    )

    if record.get("watch_state") not in {item.value for item in ContractWatchState}:
        raise ValueError("QCC_CONTRACT_WATCHER_EVIDENCE_WATCH_STATE_INVALID")

    if record.get("severity") not in {item.value for item in ContractWatchSeverity}:
        raise ValueError("QCC_CONTRACT_WATCHER_EVIDENCE_SEVERITY_INVALID")

    identity_payload = {
        key: value
        for key, value in record.items()
        if key not in ("evidence_id", "created_at")
    }

    expected_evidence_id = _evidence_id(identity_payload)

    if record.get("evidence_id") != expected_evidence_id:
        raise ValueError("QCC_CONTRACT_WATCHER_EVIDENCE_ID_MISMATCH")

    _utc_timestamp(record.get("created_at"))

    return deepcopy(record)
