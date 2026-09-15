"""Memoria persistente de dependencias catalogales AUTO TWIN.

Responsabilidad:

    CatalogDependencyEvidence
        -> conocimiento causal persistente

No:
- ejecuta navegador;
- modifica MaterializedRevision;
- modifica CandidateRevision;
- valida fidelidad;
- promociona ACTIVE.

Identidad semántica:
    dependency_fingerprint

Un mismo fingerprint observado repetidamente es idempotente.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import threading

from .catalog_dependency_probe import (
    AUTO_TWIN_CATALOG_DEPENDENCY_OPTION_IDENTITY_MODE,
    AUTO_TWIN_CATALOG_DEPENDENCY_SCHEMA_VERSION,
    AUTO_TWIN_CATALOG_DEPENDENCY_TYPE,
)


AUTO_TWIN_CATALOG_DEPENDENCY_STORE_SCHEMA_VERSION = 1

AUTO_TWIN_CATALOG_DEPENDENCY_STORE_TYPE = (
    "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE"
)

DEFAULT_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_PATH = (
    Path("data")
    / "qcc"
    / "auto_twin"
    / "catalog_dependencies.json"
)


_SHA256_RE = re.compile(
    r"^[0-9a-f]{64}$"
)


def _text(value) -> str:
    return str(
        value
        or ""
    ).strip()


def _required_text(
    value,
    *,
    error,
) -> str:
    result = _text(
        value
    )

    if not result:
        raise ValueError(
            error
        )

    return result


def _json_value(
    value,
):
    return json.loads(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def _canonical_json(
    value,
) -> str:
    return json.dumps(
        _json_value(
            value
        ),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_json(
    value,
) -> str:
    return hashlib.sha256(
        _canonical_json(
            value
        ).encode(
            "utf-8"
        )
    ).hexdigest()


def _normalize_options(
    value,
):
    if not isinstance(
        value,
        list,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_OPTIONS_INVALID"
        )

    result = []

    for option in value:
        if not isinstance(
            option,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_OPTION_INVALID"
            )

        raw_value = _text(
            option.get(
                "value"
            )
        )

        label = _text(
            option.get(
                "label"
            )
        )

        if (
            not raw_value
            and not label
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_OPTION_IDENTITY_INVALID"
            )

        result.append({
            "value":
                raw_value,

            "label":
                label,

            "disabled":
                bool(
                    option.get(
                        "disabled"
                    )
                ),
        })

    return result


def _normalize_dependency(
    value,
) -> dict:
    if not isinstance(
        value,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_EVIDENCE_INVALID"
        )

    if (
        value.get(
            "schema_version"
        )
        != AUTO_TWIN_CATALOG_DEPENDENCY_SCHEMA_VERSION
        or value.get(
            "record_type"
        )
        != AUTO_TWIN_CATALOG_DEPENDENCY_TYPE
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_EVIDENCE_SCHEMA_INVALID"
        )

    if (
        value.get(
            "option_identity_mode"
        )
        != AUTO_TWIN_CATALOG_DEPENDENCY_OPTION_IDENTITY_MODE
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_IDENTITY_MODE_INVALID"
        )

    twin_key = _required_text(
        value.get(
            "twin_key"
        ),
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_TWIN_REQUIRED"
        ),
    )

    route = _required_text(
        value.get(
            "route"
        ),
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_ROUTE_REQUIRED"
        ),
    )

    source = value.get(
        "source"
    )

    trigger = value.get(
        "trigger"
    )

    target = value.get(
        "target"
    )

    if (
        not isinstance(
            source,
            dict,
        )
        or not isinstance(
            trigger,
            dict,
        )
        or not isinstance(
            target,
            dict,
        )
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_ENDPOINTS_INVALID"
        )

    source_key = _required_text(
        source.get(
            "catalog_key"
        ),
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_SOURCE_KEY_REQUIRED"
        ),
    )

    source_selector = _required_text(
        source.get(
            "selector"
        ),
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_SOURCE_SELECTOR_REQUIRED"
        ),
    )

    target_key = _required_text(
        target.get(
            "catalog_key"
        ),
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_TARGET_KEY_REQUIRED"
        ),
    )

    target_selector = _required_text(
        target.get(
            "selector"
        ),
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_TARGET_SELECTOR_REQUIRED"
        ),
    )

    if (
        source_key
        == target_key
        or source_selector
        == target_selector
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_ENDPOINTS_SAME"
        )

    trigger_value = _text(
        trigger.get(
            "value"
        )
    )

    trigger_label = _text(
        trigger.get(
            "label"
        )
    )

    if (
        not trigger_value
        and not trigger_label
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_TRIGGER_REQUIRED"
        )

    options = _normalize_options(
        target.get(
            "options"
        )
    )

    try:
        options_count = int(
            target.get(
                "options_count"
            )
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_OPTION_COUNT_INVALID"
        ) from exc

    if (
        options_count < 0
        or options_count
        != len(
            options
        )
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_OPTION_COUNT_MISMATCH"
        )

    fingerprint = _required_text(
        value.get(
            "dependency_fingerprint"
        ),
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_FINGERPRINT_REQUIRED"
        ),
    )

    if not _SHA256_RE.fullmatch(
        fingerprint
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_FINGERPRINT_INVALID"
        )

    identity = {
        "option_identity_mode":
            AUTO_TWIN_CATALOG_DEPENDENCY_OPTION_IDENTITY_MODE,

        "twin_key":
            twin_key,

        "route":
            route,

        "source": {
            "catalog_key":
                source_key,

            "selector":
                source_selector,
        },

        "trigger": {
            "value":
                trigger_value,

            "label":
                trigger_label,
        },

        "target": {
            "catalog_key":
                target_key,

            "selector":
                target_selector,

            "options":
                options,
        },
    }

    expected_fingerprint = (
        _sha256_json(
            identity
        )
    )

    if (
        fingerprint
        != expected_fingerprint
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_FINGERPRINT_MISMATCH"
        )

    if (
        value.get(
            "restoration_exact"
        )
        is not True
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_RESTORATION_REQUIRED"
        )

    result = _json_value(
        value
    )

    # Canonicaliza los campos que forman identidad.
    result[
        "twin_key"
    ] = twin_key

    result[
        "route"
    ] = route

    result[
        "source"
    ][
        "catalog_key"
    ] = source_key

    result[
        "source"
    ][
        "selector"
    ] = source_selector

    result[
        "trigger"
    ][
        "value"
    ] = trigger_value

    result[
        "trigger"
    ][
        "label"
    ] = trigger_label

    result[
        "target"
    ][
        "catalog_key"
    ] = target_key

    result[
        "target"
    ][
        "selector"
    ] = target_selector

    result[
        "target"
    ][
        "options"
    ] = options

    result[
        "target"
    ][
        "options_count"
    ] = len(
        options
    )

    return result


class AutoTwinCatalogDependencyStore:
    """Memoria causal persistente, thread-safe e idempotente."""

    def __init__(
        self,
        *,
        path=(
            DEFAULT_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_PATH
        ),
    ) -> None:
        self._path = Path(
            path
        )

        self._lock = (
            threading.RLock()
        )

        self._revision = 0

        self._twins: dict[
            str,
            dict[
                str,
                dict,
            ],
        ] = {}

        self._load()

    @property
    def path(
        self,
    ) -> Path:
        return self._path

    @property
    def revision(
        self,
    ) -> int:
        with self._lock:
            return self._revision

    def _counts(
        self,
        twins,
    ):
        dependency_count = sum(
            len(
                dependencies
            )
            for dependencies
            in twins.values()
        )

        return (
            len(
                twins
            ),
            dependency_count,
        )

    def _payload(
        self,
        *,
        twins=None,
        revision=None,
    ) -> dict:
        effective_twins = (
            self._twins
            if twins is None
            else twins
        )

        effective_revision = (
            self._revision
            if revision is None
            else revision
        )

        (
            twin_count,
            dependency_count,
        ) = self._counts(
            effective_twins
        )

        return {
            "schema_version":
                AUTO_TWIN_CATALOG_DEPENDENCY_STORE_SCHEMA_VERSION,

            "store_type":
                AUTO_TWIN_CATALOG_DEPENDENCY_STORE_TYPE,

            "revision":
                int(
                    effective_revision
                ),

            "twin_count":
                twin_count,

            "dependency_count":
                dependency_count,

            "twins":
                deepcopy(
                    effective_twins
                ),
        }

    def _load(
        self,
    ) -> None:
        if not self._path.is_file():
            return

        try:
            payload = json.loads(
                self._path.read_text(
                    encoding="utf-8"
                )
            )

        except (
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError(
                "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_READ_INVALID"
            ) from exc

        if not isinstance(
            payload,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_INVALID"
            )

        if (
            payload.get(
                "schema_version"
            )
            != AUTO_TWIN_CATALOG_DEPENDENCY_STORE_SCHEMA_VERSION
            or payload.get(
                "store_type"
            )
            != AUTO_TWIN_CATALOG_DEPENDENCY_STORE_TYPE
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_SCHEMA_INVALID"
            )

        revision = payload.get(
            "revision"
        )

        twins = payload.get(
            "twins"
        )

        if (
            isinstance(
                revision,
                bool,
            )
            or not isinstance(
                revision,
                int,
            )
            or revision < 0
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_REVISION_INVALID"
            )

        if not isinstance(
            twins,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_TWINS_INVALID"
            )

        normalized_twins = {}

        for (
            raw_twin_key,
            dependencies,
        ) in twins.items():
            twin_key = _required_text(
                raw_twin_key,
                error=(
                    "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_TWIN_KEY_INVALID"
                ),
            )

            if not isinstance(
                dependencies,
                dict,
            ):
                raise ValueError(
                    "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_DEPENDENCIES_INVALID"
                )

            normalized_dependencies = {}

            for (
                raw_fingerprint,
                evidence,
            ) in dependencies.items():
                fingerprint = _required_text(
                    raw_fingerprint,
                    error=(
                        "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_FINGERPRINT_INVALID"
                    ),
                )

                normalized = (
                    _normalize_dependency(
                        evidence
                    )
                )

                if (
                    normalized[
                        "twin_key"
                    ]
                    != twin_key
                    or normalized[
                        "dependency_fingerprint"
                    ]
                    != fingerprint
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_INDEX_MISMATCH"
                    )

                normalized_dependencies[
                    fingerprint
                ] = normalized

            normalized_twins[
                twin_key
            ] = normalized_dependencies

        (
            twin_count,
            dependency_count,
        ) = self._counts(
            normalized_twins
        )

        if (
            payload.get(
                "twin_count"
            )
            != twin_count
            or payload.get(
                "dependency_count"
            )
            != dependency_count
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_COUNTS_INVALID"
            )

        self._revision = revision

        self._twins = (
            normalized_twins
        )

    def _persist(
        self,
        *,
        twins,
        revision,
    ) -> None:
        self._path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary = (
            self._path.with_suffix(
                self._path.suffix
                + ".tmp"
            )
        )

        temporary.write_text(
            json.dumps(
                self._payload(
                    twins=twins,
                    revision=revision,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        temporary.replace(
            self._path
        )

    def record_dependency(
        self,
        evidence,
    ) -> dict:
        normalized = (
            _normalize_dependency(
                evidence
            )
        )

        twin_key = normalized[
            "twin_key"
        ]

        fingerprint = normalized[
            "dependency_fingerprint"
        ]

        with self._lock:
            existing = (
                self._twins.get(
                    twin_key,
                    {}
                ).get(
                    fingerprint
                )
            )

            if existing is not None:
                return {
                    "created":
                        False,

                    "revision":
                        self._revision,

                    "twin_key":
                        twin_key,

                    "dependency_fingerprint":
                        fingerprint,

                    "evidence":
                        deepcopy(
                            existing
                        ),
                }

            next_twins = deepcopy(
                self._twins
            )

            next_twins.setdefault(
                twin_key,
                {},
            )[
                fingerprint
            ] = normalized

            next_revision = (
                self._revision
                + 1
            )

            self._persist(
                twins=next_twins,
                revision=next_revision,
            )

            self._twins = (
                next_twins
            )

            self._revision = (
                next_revision
            )

            return {
                "created":
                    True,

                "revision":
                    self._revision,

                "twin_key":
                    twin_key,

                "dependency_fingerprint":
                    fingerprint,

                "evidence":
                    deepcopy(
                        normalized
                    ),
            }

    def get_dependency(
        self,
        twin_key,
        dependency_fingerprint,
    ):
        twin_key = _text(
            twin_key
        )

        fingerprint = _text(
            dependency_fingerprint
        )

        with self._lock:
            value = (
                self._twins.get(
                    twin_key,
                    {}
                ).get(
                    fingerprint
                )
            )

            return (
                deepcopy(
                    value
                )
                if value is not None
                else None
            )

    def list_dependencies(
        self,
        *,
        twin_key=None,
    ):
        with self._lock:
            if twin_key is not None:
                normalized_twin = _text(
                    twin_key
                )

                return tuple(
                    deepcopy(
                        self._twins.get(
                            normalized_twin,
                            {},
                        )[key]
                    )
                    for key
                    in sorted(
                        self._twins.get(
                            normalized_twin,
                            {},
                        )
                    )
                )

            result = []

            for current_twin in sorted(
                self._twins
            ):
                for fingerprint in sorted(
                    self._twins[
                        current_twin
                    ]
                ):
                    result.append(
                        deepcopy(
                            self._twins[
                                current_twin
                            ][
                                fingerprint
                            ]
                        )
                    )

            return tuple(
                result
            )

    def snapshot(
        self,
    ) -> dict:
        with self._lock:
            return self._payload()
