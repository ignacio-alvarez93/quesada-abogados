"""Durable governed evidence store for AUTO TWIN Form Effect Runtime.

Layout:

    data/qcc/auto_twin/form_effect_evidence/
        <safe_twin_key>.json

This store is PERSISTENCE ONLY. It never captures DOM, never runs a
browser, never computes a fingerprint and never builds a
MaterializationPlan. Every recorded observation is routed through
``backend.qcc.auto_twin.form_effect_runtime``'s existing
privacy-safe normalization before it is ever written to disk --
there is no second effect taxonomy, no second mutation validator and
no second runtime engine here.

Physical identity of one evidence record is:

    (twin_key, pathname, functional_state, branch_context_id,
     before_fingerprint)

``before_fingerprint`` is an opaque caller-supplied registry
fingerprint authority (never computed here). Recording identical
evidence again is idempotent (same ``evidence_id``, no duplicate
record). Recording a DIFFERENT normalized result for the SAME
physical identity + structural trigger fails closed rather than
silently overwriting.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path

from .form_effect_runtime import (
    FormEffectRuntimeError,
    normalize_form_effect_evidence_record,
)


AUTO_TWIN_FORM_EFFECT_EVIDENCE_SCHEMA_VERSION = 1

AUTO_TWIN_FORM_EFFECT_EVIDENCE_RECORD_TYPE = (
    "QCC_AUTO_TWIN_FORM_EFFECT_EVIDENCE"
)

DEFAULT_AUTO_TWIN_FORM_EFFECT_EVIDENCE_ROOT = (
    Path("data")
    / "qcc"
    / "auto_twin"
    / "form_effect_evidence"
)

_SAFE_TWIN_KEY_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
)

_FINGERPRINT_RE = re.compile(
    r"^[0-9a-f]{64}$"
)


class AutoTwinFormEffectEvidenceStoreError(ValueError):
    """Fallo gobernado y determinista del Form Effect Evidence Store."""


def _text(value) -> str:
    return str(
        value
        or ""
    ).strip()


def _safe_twin_key(value) -> str:
    result = _text(value)

    if not _SAFE_TWIN_KEY_RE.fullmatch(result):
        raise AutoTwinFormEffectEvidenceStoreError(
            "QCC_AUTO_TWIN_FORM_EFFECT_EVIDENCE_TWIN_KEY_INVALID"
        )

    return result


def _required_pathname(value) -> str:
    result = _text(value)

    if not result.startswith("/"):
        raise AutoTwinFormEffectEvidenceStoreError(
            "QCC_AUTO_TWIN_FORM_EFFECT_EVIDENCE_PATHNAME_INVALID"
        )

    return result


def _optional_functional_state(value):
    result = _text(value)

    return result or None


def _optional_branch_context_id(value):
    result = _text(value)

    if not result:
        return None

    if not _FINGERPRINT_RE.fullmatch(result):
        raise AutoTwinFormEffectEvidenceStoreError(
            "QCC_AUTO_TWIN_FORM_EFFECT_EVIDENCE_BRANCH_CONTEXT_ID_INVALID"
        )

    return result


def _required_fingerprint(value) -> str:
    result = _text(value)

    if not _FINGERPRINT_RE.fullmatch(result):
        raise AutoTwinFormEffectEvidenceStoreError(
            "QCC_AUTO_TWIN_FORM_EFFECT_EVIDENCE_BEFORE_FINGERPRINT_INVALID"
        )

    return result


def _canonical_json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_json(value) -> str:
    return hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _mutation_identity_tuple(mutation_identity):
    if mutation_identity["kind"] == "SELECT":
        return (
            mutation_identity["kind"],
            mutation_identity["selected_index"],
        )

    return (
        mutation_identity["kind"],
        mutation_identity["checked"],
    )


def _trigger_key(physical_identity, normalized_route):
    action = normalized_route["action"]

    return (
        physical_identity["twin_key"],
        physical_identity["pathname"],
        physical_identity["functional_state"],
        physical_identity["branch_context_id"],
        physical_identity["before_fingerprint"],
        action["kind"],
        action["selector"],
        action["frame_path"],
        _mutation_identity_tuple(
            normalized_route["mutation_identity"]
        ),
    )


class AutoTwinFormEffectEvidenceStore:
    """Persistence-only durable bridge to ``MaterializationPlan``.

    One JSON file per ``twin_key``. Never trusts raw ``effects``:
    every recorded observation is routed through
    ``normalize_form_effect_evidence_record`` before being persisted.
    """

    def __init__(
        self,
        *,
        root=DEFAULT_AUTO_TWIN_FORM_EFFECT_EVIDENCE_ROOT,
    ):
        self._root = Path(root)
        self._lock = threading.RLock()

    def _path(self, safe_twin_key):
        return self._root / f"{safe_twin_key}.json"

    def _empty(self, safe_twin_key):
        return {
            "schema_version":
                AUTO_TWIN_FORM_EFFECT_EVIDENCE_SCHEMA_VERSION,

            "record_type":
                AUTO_TWIN_FORM_EFFECT_EVIDENCE_RECORD_TYPE,

            "twin_key":
                safe_twin_key,

            "revision":
                0,

            "evidence_count":
                0,

            "evidence":
                [],
        }

    def _load(self, safe_twin_key):
        path = self._path(safe_twin_key)

        if not path.is_file():
            return self._empty(safe_twin_key)

        try:
            payload = json.loads(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise AutoTwinFormEffectEvidenceStoreError(
                "QCC_AUTO_TWIN_FORM_EFFECT_EVIDENCE_PAYLOAD_INVALID"
            ) from exc

        if not isinstance(payload, dict):
            raise AutoTwinFormEffectEvidenceStoreError(
                "QCC_AUTO_TWIN_FORM_EFFECT_EVIDENCE_PAYLOAD_INVALID"
            )

        if (
            payload.get("schema_version")
            != AUTO_TWIN_FORM_EFFECT_EVIDENCE_SCHEMA_VERSION
        ):
            raise AutoTwinFormEffectEvidenceStoreError(
                "QCC_AUTO_TWIN_FORM_EFFECT_EVIDENCE_SCHEMA_INVALID"
            )

        if (
            payload.get("record_type")
            != AUTO_TWIN_FORM_EFFECT_EVIDENCE_RECORD_TYPE
        ):
            raise AutoTwinFormEffectEvidenceStoreError(
                "QCC_AUTO_TWIN_FORM_EFFECT_EVIDENCE_TYPE_INVALID"
            )

        if payload.get("twin_key") != safe_twin_key:
            raise AutoTwinFormEffectEvidenceStoreError(
                "QCC_AUTO_TWIN_FORM_EFFECT_EVIDENCE_TWIN_KEY_MISMATCH"
            )

        if not isinstance(payload.get("evidence"), list):
            raise AutoTwinFormEffectEvidenceStoreError(
                "QCC_AUTO_TWIN_FORM_EFFECT_EVIDENCE_LIST_INVALID"
            )

        return payload

    def _write(self, safe_twin_key, payload):
        self._root.mkdir(parents=True, exist_ok=True)

        path = self._path(safe_twin_key)

        temporary = path.with_suffix(".json.tmp")

        temporary.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        temporary.replace(path)

    # ------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------

    def record(
        self,
        *,
        twin_key,
        experiment_result,
        functional_state=None,
        branch_context_id=None,
    ) -> dict:
        """Persists ONE normalized B2/B3-1A evidence observation.

        ``experiment_result`` supplies ``pathname``,
        ``before_fingerprint``, ``action``, ``mutation_identity`` and
        ``effects`` -- exactly the shape produced by
        ``TwinDynamicFormExperimentService.run_experiment``. Raw
        ``effects`` are NEVER trusted directly: they are always
        routed through
        ``form_effect_runtime.normalize_form_effect_evidence_record``
        first.
        """

        if not isinstance(experiment_result, dict):
            raise AutoTwinFormEffectEvidenceStoreError(
                "QCC_AUTO_TWIN_FORM_EFFECT_EVIDENCE_RESULT_INVALID"
            )

        safe_twin_key = _safe_twin_key(twin_key)

        physical_identity = {
            "twin_key":
                safe_twin_key,

            "pathname":
                _required_pathname(
                    experiment_result.get("pathname")
                ),

            "functional_state":
                _optional_functional_state(
                    functional_state
                ),

            "branch_context_id":
                _optional_branch_context_id(
                    branch_context_id
                ),

            "before_fingerprint":
                _required_fingerprint(
                    experiment_result.get("before_fingerprint")
                ),
        }

        try:
            normalized_route = (
                normalize_form_effect_evidence_record(
                    action=experiment_result.get("action"),
                    mutation_identity=(
                        experiment_result.get("mutation_identity")
                    ),
                    effects=experiment_result.get("effects"),
                )
            )
        except FormEffectRuntimeError as exc:
            raise AutoTwinFormEffectEvidenceStoreError(
                "QCC_AUTO_TWIN_FORM_EFFECT_EVIDENCE_NORMALIZATION_FAILED:"
                + str(exc)
            ) from exc

        evidence_id = _sha256_json({
            "physical_identity": physical_identity,
            "normalized_route": normalized_route,
        })

        trigger_key = _trigger_key(
            physical_identity,
            normalized_route,
        )

        with self._lock:
            payload = self._load(safe_twin_key)

            existing_evidence_by_id = {
                item["evidence_id"]: item
                for item in payload["evidence"]
            }

            if evidence_id in existing_evidence_by_id:
                return json.loads(
                    json.dumps(
                        existing_evidence_by_id[evidence_id]
                    )
                )

            for item in payload["evidence"]:
                if (
                    _trigger_key(
                        {
                            "twin_key": item["twin_key"],
                            "pathname": item["pathname"],
                            "functional_state": item["functional_state"],
                            "branch_context_id": item["branch_context_id"],
                            "before_fingerprint": item["before_fingerprint"],
                        },
                        {
                            "action": item["action"],
                            "mutation_identity": item["mutation_identity"],
                        },
                    )
                    == trigger_key
                ):
                    raise AutoTwinFormEffectEvidenceStoreError(
                        "QCC_AUTO_TWIN_FORM_EFFECT_EVIDENCE_CONFLICTING_TRIGGER"
                    )

            record = {
                "evidence_id":
                    evidence_id,

                **physical_identity,

                **normalized_route,
            }

            payload["evidence"].append(record)

            payload["evidence"] = sorted(
                payload["evidence"],
                key=lambda item: item["evidence_id"],
            )

            payload["evidence_count"] = len(
                payload["evidence"]
            )

            payload["revision"] = (
                int(payload.get("revision", 0) or 0)
                + 1
            )

            self._write(safe_twin_key, payload)

            return json.loads(json.dumps(record))

    def get(self, twin_key, evidence_id) -> dict | None:
        safe_twin_key = _safe_twin_key(twin_key)

        normalized_evidence_id = _text(evidence_id).lower()

        with self._lock:
            payload = self._load(safe_twin_key)

        for item in payload["evidence"]:
            if item["evidence_id"] == normalized_evidence_id:
                return json.loads(json.dumps(item))

        return None

    def list_for_state(
        self,
        twin_key,
        *,
        pathname,
        functional_state=None,
        branch_context_id=None,
        before_fingerprint=None,
    ) -> tuple[dict, ...]:
        safe_twin_key = _safe_twin_key(twin_key)

        normalized_pathname = _required_pathname(pathname)
        normalized_functional_state = (
            _optional_functional_state(functional_state)
        )
        normalized_branch_context_id = (
            _optional_branch_context_id(branch_context_id)
        )
        normalized_before_fingerprint = (
            _required_fingerprint(before_fingerprint)
            if before_fingerprint is not None
            else None
        )

        with self._lock:
            payload = self._load(safe_twin_key)

        matches = [
            item
            for item in payload["evidence"]
            if (
                item["pathname"] == normalized_pathname
                and item["functional_state"]
                == normalized_functional_state
                and item["branch_context_id"]
                == normalized_branch_context_id
                and (
                    normalized_before_fingerprint is None
                    or item["before_fingerprint"]
                    == normalized_before_fingerprint
                )
            )
        ]

        matches.sort(key=lambda item: item["evidence_id"])

        return tuple(
            json.loads(json.dumps(item))
            for item in matches
        )
