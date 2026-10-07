"""Orquestación determinista de la Suite de Validación AUTO TWIN (UWT-10).

Combina, sin ejecutar nada nuevo ni cambiar el lifecycle del candidato,
la evidencia YA producida por los componentes existentes:

    FIDELITY        -> ValidationEvidenceStore (STRUCTURE/GEOMETRY/
                        VISUAL/CATALOGS/BEHAVIOR, vía unified_comparator)

    NAVIGATION      -> AutoTwinNavigationTransitionValidationStore
                        (replay gobernado ya ejecutado en el Twin local)

    NETWORK_SAFETY  -> runtime_network_sterilization (punto fijo sobre
                        el runtime ya materializado en disco)

Este módulo no:
- descubre capturas;
- ejecuta navegador;
- materializa;
- cambia CandidateRevision;
- promociona ACTIVE.

Cuando una sección no tiene evidencia asociada, se declara SKIPPED
explícitamente. Cuando la evidencia existente no se puede aplicar con
seguridad al candidato actual (p. ej. pertenece a otra revisión), se
declara UNRESOLVED en lugar de arriesgar un veredicto. El resultado es
determinista: para el mismo estado observable de los stores y del
runtime materializado en disco, ``run_auto_twin_validation_suite``
produce siempre el mismo ``suite_result_id``.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from backend.services.twin_browser_runtime_service import (
    DEFAULT_MATERIALIZED_ROOT,
)

from .candidate_revision_store import (
    AutoTwinCandidateRevisionStore,
)

from .navigation_transition_validation_store import (
    AUTO_TWIN_NAVIGATION_VALIDATION_STATUS,
    AutoTwinNavigationTransitionValidationStore,
    get_default_navigation_transition_validation_store,
)

from .runtime_network_sterilization import (
    sterilize_runtime_html,
)

from .validation_evidence import (
    AUTO_TWIN_VALIDATION_CHECK_FAIL,
    AUTO_TWIN_VALIDATION_CHECK_PASS,
)

from .validation_evidence_store import (
    AutoTwinValidationEvidenceStore,
)


AUTO_TWIN_VALIDATION_SUITE_SCHEMA_VERSION = 1

AUTO_TWIN_VALIDATION_SUITE_TYPE = (
    "QCC_AUTO_TWIN_VALIDATION_SUITE_RESULT"
)


AUTO_TWIN_VALIDATION_SUITE_SECTION_EVALUATED = "EVALUATED"
AUTO_TWIN_VALIDATION_SUITE_SECTION_SKIPPED = "SKIPPED"
AUTO_TWIN_VALIDATION_SUITE_SECTION_UNRESOLVED = "UNRESOLVED"

AUTO_TWIN_VALIDATION_SUITE_SECTION_STATUSES = frozenset({
    AUTO_TWIN_VALIDATION_SUITE_SECTION_EVALUATED,
    AUTO_TWIN_VALIDATION_SUITE_SECTION_SKIPPED,
    AUTO_TWIN_VALIDATION_SUITE_SECTION_UNRESOLVED,
})


AUTO_TWIN_VALIDATION_SUITE_VERDICT_PASS = "PASS"
AUTO_TWIN_VALIDATION_SUITE_VERDICT_FAIL = "FAIL"
AUTO_TWIN_VALIDATION_SUITE_VERDICT_INCONCLUSIVE = "INCONCLUSIVE"


AUTO_TWIN_VALIDATION_SUITE_SECTION_FIDELITY = "FIDELITY"
AUTO_TWIN_VALIDATION_SUITE_SECTION_NAVIGATION = "NAVIGATION"
AUTO_TWIN_VALIDATION_SUITE_SECTION_NETWORK_SAFETY = "NETWORK_SAFETY"

AUTO_TWIN_VALIDATION_SUITE_SECTIONS = (
    AUTO_TWIN_VALIDATION_SUITE_SECTION_FIDELITY,
    AUTO_TWIN_VALIDATION_SUITE_SECTION_NAVIGATION,
    AUTO_TWIN_VALIDATION_SUITE_SECTION_NETWORK_SAFETY,
)


def _text(
    value,
) -> str:
    return str(
        value
        or ""
    ).strip()


def _section(
    *,
    status,
    reason,
    verdict=None,
    references=None,
    metrics=None,
) -> dict:
    if (
        status
        not in AUTO_TWIN_VALIDATION_SUITE_SECTION_STATUSES
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_VALIDATION_SUITE_SECTION_STATUS_INVALID"
        )

    return {
        "status":
            status,

        "verdict":
            verdict,

        "reason":
            _text(
                reason
            )
            or None,

        "references":
            dict(
                references
                or {}
            ),

        "metrics":
            dict(
                metrics
                or {}
            ),
    }


def _fidelity_section(
    *,
    evidence_store,
    twin_key,
    candidate_id,
    candidate_revision,
) -> dict:
    record = (
        evidence_store.latest_for_candidate(
            twin_key,
            candidate_id,
        )
    )

    if record is None:
        return _section(
            status=(
                AUTO_TWIN_VALIDATION_SUITE_SECTION_SKIPPED
            ),
            reason="NO_FIDELITY_EVIDENCE",
        )

    evidence = (
        record.get(
            "validation_evidence"
        )
        or {}
    )

    if (
        evidence.get(
            "candidate_revision"
        )
        != candidate_revision
    ):
        return _section(
            status=(
                AUTO_TWIN_VALIDATION_SUITE_SECTION_UNRESOLVED
            ),
            reason="FIDELITY_EVIDENCE_REVISION_STALE",
            references={
                "evidence_id":
                    record.get(
                        "evidence_id"
                    ),

                "evidence_candidate_revision":
                    evidence.get(
                        "candidate_revision"
                    ),

                "candidate_revision":
                    candidate_revision,
            },
        )

    capture_pair = (
        evidence.get(
            "capture_pair"
        )
        or {}
    )

    summary = (
        evidence.get(
            "summary"
        )
        or {}
    )

    return _section(
        status=(
            AUTO_TWIN_VALIDATION_SUITE_SECTION_EVALUATED
        ),
        verdict=(
            evidence.get(
                "verdict"
            )
        ),
        reason="FIDELITY_EVIDENCE_APPLIED",
        references={
            "evidence_id":
                record.get(
                    "evidence_id"
                ),

            "recorded_at":
                record.get(
                    "recorded_at"
                ),

            "real_capture_id":
                capture_pair.get(
                    "real_capture_id"
                ),

            "twin_capture_id":
                capture_pair.get(
                    "twin_capture_id"
                ),
        },
        metrics={
            "passed_dimensions":
                list(
                    summary.get(
                        "passed_dimensions"
                    )
                    or ()
                ),

            "failed_dimensions":
                list(
                    summary.get(
                        "failed_dimensions"
                    )
                    or ()
                ),

            "incomplete_dimensions":
                list(
                    summary.get(
                        "incomplete_dimensions"
                    )
                    or ()
                ),
        },
    )


def _navigation_section(
    *,
    navigation_validation_store,
    twin_key,
    candidate_id,
    materialized_revision_id,
) -> dict:
    if not materialized_revision_id:
        return _section(
            status=(
                AUTO_TWIN_VALIDATION_SUITE_SECTION_SKIPPED
            ),
            reason="NO_MATERIALIZED_REVISION_SCOPE",
        )

    record = (
        navigation_validation_store
        .latest_for_revision_candidate(
            twin_key,
            materialized_revision_id,
            candidate_id,
        )
    )

    if record is None:
        return _section(
            status=(
                AUTO_TWIN_VALIDATION_SUITE_SECTION_SKIPPED
            ),
            reason="NO_TWIN_VALIDATED_TRANSITION",
            references={
                "revision_id":
                    materialized_revision_id,
            },
        )

    if (
        record.get(
            "status"
        )
        != AUTO_TWIN_NAVIGATION_VALIDATION_STATUS
    ):
        return _section(
            status=(
                AUTO_TWIN_VALIDATION_SUITE_SECTION_UNRESOLVED
            ),
            reason="NAVIGATION_RECORD_STATUS_INVALID",
            references={
                "evidence_id":
                    record.get(
                        "evidence_id"
                    ),
            },
        )

    return _section(
        status=(
            AUTO_TWIN_VALIDATION_SUITE_SECTION_EVALUATED
        ),
        verdict=(
            AUTO_TWIN_VALIDATION_CHECK_PASS
        ),
        reason="TWIN_VALIDATED_TRANSITION_FOUND",
        references={
            "evidence_id":
                record.get(
                    "evidence_id"
                ),

            "validated_at":
                record.get(
                    "validated_at"
                ),

            "before_state_id":
                record.get(
                    "before_state_id"
                ),

            "after_state_id":
                record.get(
                    "after_state_id"
                ),

            "revision_id":
                materialized_revision_id,
        },
    )


def _network_safety_section(
    *,
    materialized_root,
    twin_key,
    materialized_revision_id,
) -> dict:
    if not materialized_revision_id:
        return _section(
            status=(
                AUTO_TWIN_VALIDATION_SUITE_SECTION_SKIPPED
            ),
            reason="NO_MATERIALIZED_REVISION_SCOPE",
        )

    runtime_root = (
        Path(
            materialized_root
        )
        / twin_key
        / materialized_revision_id
        / "runtime"
    )

    if not runtime_root.is_dir():
        return _section(
            status=(
                AUTO_TWIN_VALIDATION_SUITE_SECTION_SKIPPED
            ),
            reason="NO_MATERIALIZED_RUNTIME",
            references={
                "revision_id":
                    materialized_revision_id,
            },
        )

    html_paths = sorted(
        runtime_root.rglob(
            "*.html"
        )
    )

    if not html_paths:
        return _section(
            status=(
                AUTO_TWIN_VALIDATION_SUITE_SECTION_SKIPPED
            ),
            reason="NO_MATERIALIZED_RUNTIME_HTML",
            references={
                "revision_id":
                    materialized_revision_id,
            },
        )

    # Punto fijo: el runtime materializado ya debió quedar sterilizado
    # en origen. Volver a aplicar el mismo sterilizador debe ser un
    # no-op exacto; cualquier diferencia revela una fuga de red/REAL
    # que sobrevivió a la materialización.
    unsterilized = []

    for html_path in html_paths:
        source = (
            html_path.read_text(
                encoding="utf-8"
            )
        )

        resterilized, _ = (
            sterilize_runtime_html(
                source
            )
        )

        if resterilized != source:
            unsterilized.append(
                str(
                    html_path
                    .relative_to(
                        runtime_root
                    )
                    .as_posix()
                )
            )

    verdict = (
        AUTO_TWIN_VALIDATION_CHECK_FAIL
        if unsterilized
        else AUTO_TWIN_VALIDATION_CHECK_PASS
    )

    return _section(
        status=(
            AUTO_TWIN_VALIDATION_SUITE_SECTION_EVALUATED
        ),
        verdict=verdict,
        reason=(
            "UNSTERILIZED_RUNTIME_ARTIFACT_DETECTED"
            if unsterilized
            else "RUNTIME_NETWORK_STERILE"
        ),
        references={
            "revision_id":
                materialized_revision_id,
        },
        metrics={
            "html_files_scanned":
                len(
                    html_paths
                ),

            "unsterilized_files":
                unsterilized,
        },
    )


def _suite_verdict(
    sections,
) -> str:
    evaluated_verdicts = tuple(
        section[
            "verdict"
        ]
        for section
        in sections.values()
        if section[
            "status"
        ]
        == AUTO_TWIN_VALIDATION_SUITE_SECTION_EVALUATED
    )

    if (
        AUTO_TWIN_VALIDATION_CHECK_FAIL
        in evaluated_verdicts
    ):
        return (
            AUTO_TWIN_VALIDATION_SUITE_VERDICT_FAIL
        )

    has_unresolved = any(
        section[
            "status"
        ]
        == AUTO_TWIN_VALIDATION_SUITE_SECTION_UNRESOLVED
        for section
        in sections.values()
    )

    if has_unresolved:
        return (
            AUTO_TWIN_VALIDATION_SUITE_VERDICT_INCONCLUSIVE
        )

    if (
        evaluated_verdicts
        and all(
            verdict
            == AUTO_TWIN_VALIDATION_CHECK_PASS
            for verdict
            in evaluated_verdicts
        )
    ):
        return (
            AUTO_TWIN_VALIDATION_SUITE_VERDICT_PASS
        )

    return (
        AUTO_TWIN_VALIDATION_SUITE_VERDICT_INCONCLUSIVE
    )


def _canonical_json(
    value,
) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    )


def _suite_result_id(
    result,
) -> str:
    payload = deepcopy(
        result
    )

    payload.pop(
        "suite_result_id",
        None,
    )

    canonical = (
        _canonical_json(
            payload
        )
    )

    return hashlib.sha256(
        canonical.encode(
            "utf-8"
        )
    ).hexdigest()


def run_auto_twin_validation_suite(
    *,
    twin_key,
    candidate_id,
    candidate_store,
    evidence_store,
    navigation_validation_store=None,
    materialized_revision_id=None,
    materialized_root=(
        DEFAULT_MATERIALIZED_ROOT
    ),
) -> dict:
    """Produce un resultado único y determinista para un candidato.

    Lee evidencia YA persistida por los componentes existentes
    (fidelidad REAL↔TWIN, replay de navegación en el Twin local,
    esterilización de red del runtime materializado). No ejecuta
    navegador, no captura nada nuevo y no cambia el estado del
    CandidateRevision: el resultado nunca promociona ACTIVE por sí
    mismo, aunque su veredicto sea PASS.
    """

    if not isinstance(
        candidate_store,
        AutoTwinCandidateRevisionStore,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_VALIDATION_SUITE_CANDIDATE_STORE_INVALID"
        )

    if not isinstance(
        evidence_store,
        AutoTwinValidationEvidenceStore,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_VALIDATION_SUITE_EVIDENCE_STORE_INVALID"
        )

    navigation_validation_store = (
        navigation_validation_store
        or get_default_navigation_transition_validation_store()
    )

    if not isinstance(
        navigation_validation_store,
        AutoTwinNavigationTransitionValidationStore,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_VALIDATION_SUITE_NAVIGATION_STORE_INVALID"
        )

    normalized_twin_key = _text(
        twin_key
    )

    normalized_candidate_id = _text(
        candidate_id
    )

    normalized_revision_id = (
        _text(
            materialized_revision_id
        )
        or None
    )

    if not normalized_twin_key:
        raise ValueError(
            "QCC_AUTO_TWIN_KEY_REQUIRED"
        )

    if not normalized_candidate_id:
        raise ValueError(
            "QCC_AUTO_TWIN_CANDIDATE_ID_REQUIRED"
        )

    candidate = (
        candidate_store.get_candidate(
            normalized_twin_key,
            normalized_candidate_id,
        )
    )

    if candidate is None:
        raise ValueError(
            "QCC_AUTO_TWIN_CANDIDATE_NOT_FOUND"
        )

    try:
        candidate_revision = int(
            candidate.get(
                "candidate_revision"
            )
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "QCC_AUTO_TWIN_VALIDATION_SUITE_"
            "CANDIDATE_REVISION_INVALID"
        ) from exc

    if candidate_revision <= 0:
        raise ValueError(
            "QCC_AUTO_TWIN_VALIDATION_SUITE_"
            "CANDIDATE_REVISION_INVALID"
        )

    sections = {
        AUTO_TWIN_VALIDATION_SUITE_SECTION_FIDELITY:
            _fidelity_section(
                evidence_store=(
                    evidence_store
                ),
                twin_key=(
                    normalized_twin_key
                ),
                candidate_id=(
                    normalized_candidate_id
                ),
                candidate_revision=(
                    candidate_revision
                ),
            ),

        AUTO_TWIN_VALIDATION_SUITE_SECTION_NAVIGATION:
            _navigation_section(
                navigation_validation_store=(
                    navigation_validation_store
                ),
                twin_key=(
                    normalized_twin_key
                ),
                candidate_id=(
                    normalized_candidate_id
                ),
                materialized_revision_id=(
                    normalized_revision_id
                ),
            ),

        AUTO_TWIN_VALIDATION_SUITE_SECTION_NETWORK_SAFETY:
            _network_safety_section(
                materialized_root=(
                    materialized_root
                ),
                twin_key=(
                    normalized_twin_key
                ),
                materialized_revision_id=(
                    normalized_revision_id
                ),
            ),
    }

    verdict = (
        _suite_verdict(
            sections
        )
    )

    evaluated_sections = tuple(
        name
        for name, section
        in sections.items()
        if section[
            "status"
        ]
        == AUTO_TWIN_VALIDATION_SUITE_SECTION_EVALUATED
    )

    skipped_sections = tuple(
        name
        for name, section
        in sections.items()
        if section[
            "status"
        ]
        == AUTO_TWIN_VALIDATION_SUITE_SECTION_SKIPPED
    )

    unresolved_sections = tuple(
        name
        for name, section
        in sections.items()
        if section[
            "status"
        ]
        == AUTO_TWIN_VALIDATION_SUITE_SECTION_UNRESOLVED
    )

    result = {
        "schema_version":
            AUTO_TWIN_VALIDATION_SUITE_SCHEMA_VERSION,

        "result_type":
            AUTO_TWIN_VALIDATION_SUITE_TYPE,

        "twin_key":
            normalized_twin_key,

        "candidate_id":
            normalized_candidate_id,

        "candidate_revision":
            candidate_revision,

        "candidate_status":
            candidate.get(
                "status"
            ),

        "materialized_revision_id":
            normalized_revision_id,

        "sections":
            sections,

        "evaluated_sections":
            evaluated_sections,

        "skipped_sections":
            skipped_sections,

        "unresolved_sections":
            unresolved_sections,

        "verdict":
            verdict,

        # Deliberadamente estricto: solo cuando las tres secciones
        # fueron efectivamente evaluadas (ninguna SKIPPED/UNRESOLVED)
        # y el veredicto es PASS se marca el resultado como apto para
        # una futura certificación. Esto es solo una señal informativa:
        # no cambia por sí mismo el status del CandidateRevision ni lo
        # promociona ACTIVE.
        "certifiable":
            (
                verdict
                == AUTO_TWIN_VALIDATION_SUITE_VERDICT_PASS
                and not unresolved_sections
                and not skipped_sections
            ),
    }

    result[
        "suite_result_id"
    ] = (
        _suite_result_id(
            result
        )
    )

    return result
