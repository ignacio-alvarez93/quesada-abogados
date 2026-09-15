"""Análisis canónico de probes causales de catálogo REAL gobernados.

Convierte:

    QCC_GENERIC_CATALOG_CAUSAL_PROBE

en conocimiento causal AUTO TWIN provider-neutral.

Este módulo NO:
- ejecuta navegador;
- interactúa con REAL;
- confía en la autoridad declarada por la extensión;
- escribe MaterializedRevision;
- persiste artefactos;
- modifica lifecycle.

La autoridad efectiva se recibe ya revalidada por backend.
"""

from __future__ import annotations

import hashlib
import json
from urllib.parse import urlparse

from backend.automation.site_architecture.catalog_dynamics import (
    CATALOG_DYNAMIC_OPTIONS_CHANGED,
    build_catalog_causal_relations,
    build_catalog_dynamic_evidence,
)

from .catalog_probe_decision import (
    AUTO_TWIN_CATALOG_PROBE_DECISION_SCHEMA_VERSION,
    AUTO_TWIN_CATALOG_PROBE_DECISION_TYPE,
)


AUTO_TWIN_CATALOG_DEPENDENCY_SCHEMA_VERSION = 1

AUTO_TWIN_CATALOG_DEPENDENCY_TYPE = (
    "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_EVIDENCE"
)

AUTO_TWIN_GOVERNED_CATALOG_PROBE_TYPE = (
    "QCC_GENERIC_CATALOG_CAUSAL_PROBE"
)

AUTO_TWIN_GOVERNED_CATALOG_PROBE_SAFETY_MODE = (
    "GOVERNED_REAL_PROBE"
)

AUTO_TWIN_CATALOG_DEPENDENCY_OPTION_IDENTITY_MODE = (
    "VALUE_OR_LABEL"
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


def _canonical_json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_json(value) -> str:
    return hashlib.sha256(
        _canonical_json(
            value
        ).encode(
            "utf-8"
        )
    ).hexdigest()


def _catalog_key(
    selector,
) -> str:
    return (
        "main::"
        + _required_text(
            selector,
            error=(
                "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_SELECTOR_REQUIRED"
            ),
        )
    )


def _normalized_options(
    value,
    *,
    error,
):
    if not isinstance(
        value,
        list,
    ):
        raise ValueError(
            error
        )

    result = []

    for item in value:
        if not isinstance(
            item,
            dict,
        ):
            raise ValueError(
                error
            )

        option_value = _text(
            item.get(
                "value"
            )
        )

        option_label = _text(
            item.get(
                "label"
            )
        )

        if (
            not option_value
            and not option_label
        ):
            raise ValueError(
                error
            )

        result.append({
            "value":
                option_value,

            "label":
                option_label,

            "disabled":
                bool(
                    item.get(
                        "disabled"
                    )
                ),
        })

    return result


def _catalog_record(
    *,
    catalog_key,
    selected_value,
    selected_label,
    options,
):
    return {
        "catalog_key":
            catalog_key,

        "state": {
            "selected_value":
                _text(
                    selected_value
                ),

            "selected_label":
                _text(
                    selected_label
                ),

            "selected_values":
                (
                    [
                        _text(
                            selected_value
                        )
                    ]
                    if _text(
                        selected_value
                    )
                    else []
                ),

            "selected_index":
                None,
        },

        "options":
            options,
    }


def _validated_authority(
    decision,
):
    if not isinstance(
        decision,
        dict,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_AUTHORITY_INVALID"
        )

    if (
        decision.get(
            "schema_version"
        )
        != AUTO_TWIN_CATALOG_PROBE_DECISION_SCHEMA_VERSION
        or decision.get(
            "decision_type"
        )
        != AUTO_TWIN_CATALOG_PROBE_DECISION_TYPE
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_AUTHORITY_SCHEMA_INVALID"
        )

    if (
        decision.get(
            "allowed"
        )
        is not True
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_AUTHORITY_DENIED"
        )

    profile_policy = (
        decision.get(
            "profile_policy"
        )
        or {}
    )

    if (
        not isinstance(
            profile_policy,
            dict,
        )
        or profile_policy.get(
            "active_discovery"
        )
        is not True
        or profile_policy.get(
            "active_catalog_probe"
        )
        is not True
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_POLICY_DENIED"
        )

    profile_key = _required_text(
        decision.get(
            "browser_profile_key"
        ),
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_PROFILE_REQUIRED"
        ),
    )

    twin_key = _required_text(
        decision.get(
            "twin_key"
        ),
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_TWIN_REQUIRED"
        ),
    )

    site_code = _required_text(
        decision.get(
            "site_code"
        ),
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_SITE_REQUIRED"
        ),
    )

    page_url = _required_text(
        decision.get(
            "url"
        ),
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_URL_REQUIRED"
        ),
    )

    parsed = urlparse(
        page_url
    )

    if (
        parsed.scheme
        not in {
            "http",
            "https",
        }
        or not parsed.netloc
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_URL_INVALID"
        )

    pathname = (
        parsed.path
        or "/"
    )

    route = pathname

    if parsed.query:
        route += (
            "?"
            + parsed.query
        )

    return {
        "browser_profile_key":
            profile_key,

        "twin_key":
            twin_key,

        "site_code":
            site_code,

        "url":
            page_url,

        "origin":
            (
                parsed.scheme
                + "://"
                + parsed.netloc
            ),

        "pathname":
            pathname,

        "route":
            route,

        "reason":
            _text(
                decision.get(
                    "reason"
                )
            ),
    }


def analyze_auto_twin_governed_catalog_probe(
    artifact,
    *,
    authoritative_decision,
):
    """Construye evidencia causal versionable desde un probe REAL."""

    if not isinstance(
        artifact,
        dict,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_PROBE_INVALID"
        )

    if (
        artifact.get(
            "schema_version"
        )
        != 1
        or artifact.get(
            "artifact_type"
        )
        != AUTO_TWIN_GOVERNED_CATALOG_PROBE_TYPE
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_PROBE_SCHEMA_INVALID"
        )

    if (
        artifact.get(
            "safety_mode"
        )
        != AUTO_TWIN_GOVERNED_CATALOG_PROBE_SAFETY_MODE
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_SAFETY_INVALID"
        )

    if not isinstance(
        artifact.get(
            "authority"
        ),
        dict,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_WORKER_AUTHORITY_MISSING"
        )

    authority = _validated_authority(
        authoritative_decision
    )

    verification = (
        artifact.get(
            "restoration_verification"
        )
        or {}
    )

    if (
        not isinstance(
            verification,
            dict,
        )
        or verification.get(
            "exact"
        )
        is not True
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RESTORATION_REQUIRED"
        )

    source_selector = _required_text(
        artifact.get(
            "source_selector"
        ),
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_SOURCE_REQUIRED"
        ),
    )

    target_selector = _required_text(
        artifact.get(
            "target_selector"
        ),
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_TARGET_REQUIRED"
        ),
    )

    if (
        source_selector
        == target_selector
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_ENDPOINTS_SAME"
        )

    before = (
        artifact.get(
            "before"
        )
        or {}
    )

    observation = (
        artifact.get(
            "observation"
        )
        or {}
    )

    if (
        not isinstance(
            before,
            dict,
        )
        or not isinstance(
            observation,
            dict,
        )
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_OBSERVATION_INVALID"
        )

    stabilization = (
        observation.get(
            "stabilization"
        )
        or {}
    )

    if (
        not isinstance(
            stabilization,
            dict,
        )
        or stabilization.get(
            "stable"
        )
        is not True
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_NOT_STABLE"
        )

    observed_source = (
        observation.get(
            "source"
        )
        or {}
    )

    observed_target = (
        observation.get(
            "target"
        )
        or {}
    )

    if (
        not isinstance(
            observed_source,
            dict,
        )
        or not isinstance(
            observed_target,
            dict,
        )
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_ENDPOINT_OBSERVATION_INVALID"
        )

    if (
        _text(
            observed_source.get(
                "selector"
            )
        )
        != source_selector
        or _text(
            observed_target.get(
                "selector"
            )
        )
        != target_selector
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_SELECTOR_MISMATCH"
        )

    before_value = _text(
        before.get(
            "source_value"
        )
    )

    before_label = _text(
        before.get(
            "source_label"
        )
    )

    after_value = _text(
        observed_source.get(
            "selected_value"
        )
    )

    after_label = _text(
        observed_source.get(
            "selected_label"
        )
    )

    if (
        not after_value
        and not after_label
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_TRIGGER_IDENTITY_REQUIRED"
        )

    if (
        (
            before_value,
            before_label,
        )
        == (
            after_value,
            after_label,
        )
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_SOURCE_UNCHANGED"
        )

    requested_value = _text(
        artifact.get(
            "requested_value"
        )
    )

    requested_label = _text(
        artifact.get(
            "requested_label"
        )
    )

    if (
        requested_value
        and requested_value
        != after_value
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_REQUEST_VALUE_MISMATCH"
        )

    if (
        requested_label
        and requested_label
        != after_label
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_REQUEST_LABEL_MISMATCH"
        )

    before_options = _normalized_options(
        before.get(
            "target_options"
        ),
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_BEFORE_OPTIONS_INVALID"
        ),
    )

    after_options = _normalized_options(
        observed_target.get(
            "options"
        ),
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_AFTER_OPTIONS_INVALID"
        ),
    )

    if (
        before_options
        == after_options
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_TARGET_UNCHANGED"
        )

    declared_count = observed_target.get(
        "options_count"
    )

    if (
        isinstance(
            declared_count,
            bool,
        )
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_OPTION_COUNT_INVALID"
        )

    try:
        declared_count = int(
            declared_count
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_OPTION_COUNT_INVALID"
        ) from exc

    if (
        declared_count
        != len(
            after_options
        )
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_OPTION_COUNT_MISMATCH"
        )

    source_key = _catalog_key(
        source_selector
    )

    target_key = _catalog_key(
        target_selector
    )

    before_catalogs = [
        _catalog_record(
            catalog_key=source_key,
            selected_value=before_value,
            selected_label=before_label,
            options=[],
        ),
        _catalog_record(
            catalog_key=target_key,
            selected_value="",
            selected_label="",
            options=before_options,
        ),
    ]

    after_catalogs = [
        _catalog_record(
            catalog_key=source_key,
            selected_value=after_value,
            selected_label=after_label,
            options=[],
        ),
        _catalog_record(
            catalog_key=target_key,
            selected_value="",
            selected_label="",
            options=after_options,
        ),
    ]

    evidence = (
        build_catalog_dynamic_evidence(
            before_catalogs,
            after_catalogs,
            source_catalog_key=(
                source_key
            ),
        )
    )

    target_changes = [
        item
        for item in evidence
        if (
            isinstance(
                item,
                dict,
            )
            and item.get(
                "kind"
            )
            == CATALOG_DYNAMIC_OPTIONS_CHANGED
            and item.get(
                "source"
            )
            == source_key
            and item.get(
                "target"
            )
            == target_key
        )
    ]

    if len(
        target_changes
    ) != 1:
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_CAUSAL_CHANGE_REQUIRED"
        )

    causal_relations = (
        build_catalog_causal_relations(
            evidence
        )
    )

    relation_signatures = {
        (
            _text(
                relation.get(
                    "relation"
                )
            ),
            _text(
                relation.get(
                    "source"
                )
            ),
            _text(
                relation.get(
                    "target"
                )
            ),
        )
        for relation
        in causal_relations
        if isinstance(
            relation,
            dict,
        )
    }

    expected_relations = {
        (
            "INFLUENCES",
            source_key,
            target_key,
        ),
        (
            "DEPENDS_ON",
            target_key,
            source_key,
        ),
    }

    if (
        relation_signatures
        != expected_relations
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RELATIONS_INVALID"
        )

    target_change = (
        target_changes[0]
    )

    dependency_identity = {
        "option_identity_mode":
            AUTO_TWIN_CATALOG_DEPENDENCY_OPTION_IDENTITY_MODE,

        "twin_key":
            authority[
                "twin_key"
            ],

        "route":
            authority[
                "route"
            ],

        "source": {
            "catalog_key":
                source_key,

            "selector":
                source_selector,
        },

        "trigger": {
            "value":
                after_value,

            "label":
                after_label,
        },

        "target": {
            "catalog_key":
                target_key,

            "selector":
                target_selector,

            "options":
                after_options,
        },
    }

    dependency_fingerprint = (
        _sha256_json(
            dependency_identity
        )
    )

    hard_restore = (
        (
            artifact.get(
                "restoration"
            )
            or {}
        ).get(
            "hard_document_restore"
        )
        or {}
    )

    return {
        "schema_version":
            AUTO_TWIN_CATALOG_DEPENDENCY_SCHEMA_VERSION,

        "record_type":
            AUTO_TWIN_CATALOG_DEPENDENCY_TYPE,

        "dependency_fingerprint":
            dependency_fingerprint,

        "option_identity_mode":
            AUTO_TWIN_CATALOG_DEPENDENCY_OPTION_IDENTITY_MODE,

        "twin_key":
            authority[
                "twin_key"
            ],

        "site_code":
            authority[
                "site_code"
            ],

        "origin":
            authority[
                "origin"
            ],

        "pathname":
            authority[
                "pathname"
            ],

        "route":
            authority[
                "route"
            ],

        "source": {
            "catalog_key":
                source_key,

            "selector":
                source_selector,
        },

        "trigger": {
            "before_value":
                before_value,

            "before_label":
                before_label,

            "value":
                after_value,

            "label":
                after_label,
        },

        "target": {
            "catalog_key":
                target_key,

            "selector":
                target_selector,

            "before_options_count":
                len(
                    before_options
                ),

            "options_count":
                len(
                    after_options
                ),

            "before_options_signature":
                target_change.get(
                    "before_options_signature"
                ),

            "options_signature":
                target_change.get(
                    "after_options_signature"
                ),

            "options":
                after_options,
        },

        "evidence":
            list(
                evidence
            ),

        "causal_relations":
            list(
                causal_relations
            ),

        "causal_relation_count":
            len(
                causal_relations
            ),

        "restoration_exact":
            True,

        "provenance": {
            "source":
                AUTO_TWIN_GOVERNED_CATALOG_PROBE_SAFETY_MODE,

            "browser_profile_key":
                authority[
                    "browser_profile_key"
                ],

            "authority_reason":
                authority[
                    "reason"
                ],

            "hard_document_restore":
                bool(
                    isinstance(
                        hard_restore,
                        dict,
                    )
                    and hard_restore.get(
                        "completed"
                    )
                    is True
                ),
        },
    }
