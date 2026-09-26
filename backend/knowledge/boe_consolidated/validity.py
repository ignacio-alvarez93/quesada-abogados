"""Resolución de validez documental para BOE Legislación Consolidada.

BOE Consolidado expone banderas oficiales estructuradas en los
metadatos ya canonicalizados por ``parser.py``:

- ``estatus_derogacion``: "S"/"N";
- ``estatus_anulacion``: "S"/"N";
- ``vigencia_agotada``: "S"/"N";
- ``fecha_vigencia``: AAAAMMDD, fecha oficial asociada al estado
  de vigencia vigente en el momento de la consulta a la fuente;
- ``legal_relations_json``: relaciones jurídicas posteriores, entre
  ellas la relación oficial código 210 ("SE DEROGA"), que identifica
  la norma derogante cuando existe.

Nunca se infiere derogación de la mera existencia de estas relaciones;
solo se usan como identificación complementaria de la norma derogante
cuando las banderas oficiales ya confirman derogación.

No realiza HTTP, persistencia, UI ni IA.
"""

from __future__ import annotations

from datetime import date
import json

from ..items import KnowledgeItem
from ..validity import (
    KnowledgeDocumentValidity,
    KnowledgeValidityEvidence,
    KnowledgeValidityStatus,
)
from .parser import SOURCE_KEY


_REPEAL_RELATION_CODE = "210"
_REPEAL_RELATION_DIRECTION = "posteriores"


def _flag(
    raw: object,
) -> bool | None:
    value = str(
        raw or ""
    ).strip().upper()

    if value == "S":
        return True

    if value == "N":
        return False

    return None


def _optional_yyyymmdd(
    raw: object,
) -> date | None:
    value = str(
        raw or ""
    ).strip()

    if not value:
        return None

    if (
        len(value) != 8
        or not value.isdigit()
    ):
        raise ValueError(
            "fecha_vigencia BOE Consolidado "
            "debe usar AAAAMMDD"
        )

    try:
        return date(
            int(value[:4]),
            int(value[4:6]),
            int(value[6:8]),
        )
    except ValueError as exc:
        raise ValueError(
            "fecha_vigencia BOE Consolidado "
            "no es fecha válida"
        ) from exc


def _repealed_by(
    raw_relations_json: str,
) -> str:
    if not raw_relations_json:
        return ""

    try:
        relations = json.loads(
            raw_relations_json
        )
    except (
        ValueError,
        TypeError,
    ):
        return ""

    if not isinstance(
        relations,
        list,
    ):
        return ""

    for relation in relations:
        if not isinstance(
            relation,
            dict,
        ):
            continue

        if (
            relation.get(
                "direction"
            )
            != _REPEAL_RELATION_DIRECTION
        ):
            continue

        if (
            str(
                relation.get(
                    "relation_code"
                )
                or ""
            )
            != _REPEAL_RELATION_CODE
        ):
            continue

        target = str(
            relation.get(
                "target_id"
            )
            or ""
        ).strip()

        if target:
            return target

    return ""


def resolve_boe_consolidated_validity(
    item: KnowledgeItem,
) -> KnowledgeDocumentValidity:
    """Interpreta las banderas oficiales de vigencia de BOE Consolidado."""

    if not isinstance(
        item,
        KnowledgeItem,
    ):
        raise TypeError(
            "item debe ser KnowledgeItem"
        )

    if item.source_key != SOURCE_KEY:
        raise ValueError(
            "resolve_boe_consolidated_validity "
            "solo acepta KnowledgeItem "
            "BOE_CONSOLIDATED"
        )

    metadata = dict(
        item.metadata
    )

    raw_derogacion = metadata.get(
        "estatus_derogacion",
        "",
    )
    raw_anulacion = metadata.get(
        "estatus_anulacion",
        "",
    )
    raw_agotada = metadata.get(
        "vigencia_agotada",
        "",
    )
    raw_fecha_vigencia = str(
        metadata.get(
            "fecha_vigencia",
            "",
        )
        or ""
    ).strip()

    derogada = _flag(
        raw_derogacion
    )
    anulada = _flag(
        raw_anulacion
    )
    agotada = _flag(
        raw_agotada
    )

    end_date = _optional_yyyymmdd(
        raw_fecha_vigencia
    )

    evidence = []

    if str(raw_derogacion or "").strip():
        evidence.append(
            KnowledgeValidityEvidence(
                "estatus_derogacion",
                str(raw_derogacion),
            )
        )

    if str(raw_anulacion or "").strip():
        evidence.append(
            KnowledgeValidityEvidence(
                "estatus_anulacion",
                str(raw_anulacion),
            )
        )

    if str(raw_agotada or "").strip():
        evidence.append(
            KnowledgeValidityEvidence(
                "vigencia_agotada",
                str(raw_agotada),
            )
        )

    if raw_fecha_vigencia:
        evidence.append(
            KnowledgeValidityEvidence(
                "fecha_vigencia",
                raw_fecha_vigencia,
            )
        )

    evidence = tuple(
        evidence
    )

    if (
        derogada is None
        and anulada is None
        and agotada is None
    ):
        return KnowledgeDocumentValidity(
            source_key=item.source_key,
            external_id=item.external_id,
            status=(
                KnowledgeValidityStatus.UNKNOWN
            ),
            evidence=evidence,
            reason=(
                "BOE Consolidado no expuso "
                "banderas de vigencia "
                "estructuradas para esta norma."
            ),
        )

    if derogada:
        return KnowledgeDocumentValidity(
            source_key=item.source_key,
            external_id=item.external_id,
            status=(
                KnowledgeValidityStatus.REPEALED
            ),
            end_date=end_date,
            repealed_by_external_id=(
                _repealed_by(
                    str(
                        metadata.get(
                            "legal_relations_json",
                            "",
                        )
                        or ""
                    )
                )
            ),
            evidence=evidence,
            reason=(
                "BOE Consolidado declara "
                "estatus_derogacion=S para "
                "esta norma."
            ),
        )

    if anulada:
        return KnowledgeDocumentValidity(
            source_key=item.source_key,
            external_id=item.external_id,
            status=(
                KnowledgeValidityStatus.REPEALED
            ),
            end_date=end_date,
            repealed_by_external_id=(
                _repealed_by(
                    str(
                        metadata.get(
                            "legal_relations_json",
                            "",
                        )
                        or ""
                    )
                )
            ),
            evidence=evidence,
            reason=(
                "BOE Consolidado declara "
                "estatus_anulacion=S para "
                "esta norma."
            ),
        )

    if agotada:
        return KnowledgeDocumentValidity(
            source_key=item.source_key,
            external_id=item.external_id,
            status=(
                KnowledgeValidityStatus.EXPLICIT_END_OF_VALIDITY
            ),
            end_date=end_date,
            evidence=evidence,
            reason=(
                "BOE Consolidado declara "
                "vigencia_agotada=S sin "
                "derogación/anulación explícita."
            ),
        )

    if (
        derogada is False
        and anulada is False
        and agotada is False
    ):
        return KnowledgeDocumentValidity(
            source_key=item.source_key,
            external_id=item.external_id,
            status=(
                KnowledgeValidityStatus.IN_FORCE
            ),
            evidence=evidence,
            reason=(
                "BOE Consolidado confirma "
                "estatus_derogacion=N, "
                "estatus_anulacion=N y "
                "vigencia_agotada=N."
            ),
        )

    # Al menos una bandera es "S"/"N" y ninguna es "S", pero otra
    # bandera falta o no es reconocible: evidencia parcial. Fallar
    # cerrado hacia UNKNOWN en lugar de afirmar vigencia sin
    # confirmación completa.
    return KnowledgeDocumentValidity(
        source_key=item.source_key,
        external_id=item.external_id,
        status=(
            KnowledgeValidityStatus.UNKNOWN
        ),
        evidence=evidence,
        reason=(
            "BOE Consolidado no confirmó "
            "de forma completa las tres "
            "banderas oficiales de vigencia "
            "para esta norma."
        ),
    )
