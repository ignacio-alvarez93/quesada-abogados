"""Selección forense determinista de evidencia bruta EUR-Lex verificada.

Esta capa NO copia ni reescribe bytes crudos. Escribe únicamente un
manifiesto pequeño y versionado que REFERENCIA un
``EurLexEvidenceArtifact`` ya verificado (por ``artifact_id``, SHA-256
de contenido, SHA-256 de identidad, URL/identificador de origen y
rutas del artefacto). Seleccionar un artefacto NUNCA lo promueve a
fixture de test comprometida en el repositorio: el manifiesto vive en
el mismo árbol runtime ignorado por Git que la propia evidencia.

Cargar o verificar un manifiesto reverifica siempre la evidencia
subyacente y falla cerrado ante manipulación del manifiesto,
desaparición del artefacto o desajuste de payload/identidad.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from .evidence import (
    DEFAULT_EUR_LEX_EVIDENCE_ROOT,
    EurLexEvidenceArtifact,
    EurLexEvidenceError,
    load_eurlex_evidence_artifact,
)


EUR_LEX_FORENSIC_SELECTION_SCHEMA_VERSION = 1

DEFAULT_EUR_LEX_FORENSIC_SELECTION_ROOT = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "knowledge_eurlex_forensic_selection"
)

_REQUIRED_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "selection_key",
        "selection_id",
        "artifact_id",
        "requested_identifier",
        "source_url",
        "sha256",
        "identity_sha256",
        "evidence_metadata_path",
        "selected_at",
    }
)


class EurLexForensicSelectionError(RuntimeError):
    """Error controlado de la capa de selección forense EUR-Lex."""


class EurLexForensicSelectionIntegrityError(
    EurLexForensicSelectionError
):
    """El manifiesto persistido no coincide con la evidencia real."""


def _require_non_empty_str(value: object, *, field_name: str) -> str:
    text = str(value or "").strip()

    if not text:
        raise ValueError(
            f"EUR-Lex forensic selection {field_name} no puede "
            "estar vacío"
        )

    return text


def _selection_key(*, artifact_id: str, selection_id: str) -> str:
    return sha256(
        f"{artifact_id}|{selection_id}".encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class EurLexForensicSelection:
    """Manifiesto forense inmutable que referencia evidencia verificada."""

    schema_version: int
    selection_key: str
    selection_id: str
    artifact_id: str
    requested_identifier: str
    canonical_identifier: str | None
    source_url: str
    content_type: str | None
    sha256: str
    identity_sha256: str
    evidence_metadata_path: Path
    evidence_raw_path: Path
    selected_at: datetime
    manifest_path: Path

    def to_manifest_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "selection_key": self.selection_key,
            "selection_id": self.selection_id,
            "artifact_id": self.artifact_id,
            "requested_identifier": self.requested_identifier,
            "canonical_identifier": self.canonical_identifier,
            "source_url": self.source_url,
            "content_type": self.content_type,
            "sha256": self.sha256,
            "identity_sha256": self.identity_sha256,
            "evidence_metadata_path": str(self.evidence_metadata_path),
            "evidence_raw_path": str(self.evidence_raw_path),
            "selected_at": self.selected_at.isoformat(),
        }


def _manifest_from_artifact(
    artifact: EurLexEvidenceArtifact,
    *,
    selection_id: str,
    evidence_metadata_path: Path,
    evidence_raw_path: Path,
    manifest_path: Path,
    selected_at: datetime,
) -> EurLexForensicSelection:
    return EurLexForensicSelection(
        schema_version=EUR_LEX_FORENSIC_SELECTION_SCHEMA_VERSION,
        selection_key=_selection_key(
            artifact_id=artifact.artifact_id,
            selection_id=selection_id,
        ),
        selection_id=selection_id,
        artifact_id=artifact.artifact_id,
        requested_identifier=artifact.requested_identifier,
        canonical_identifier=artifact.canonical_identifier,
        source_url=artifact.source_url,
        content_type=artifact.content_type,
        sha256=artifact.sha256_hex,
        identity_sha256=artifact.identity_sha256_hex,
        evidence_metadata_path=evidence_metadata_path,
        evidence_raw_path=evidence_raw_path,
        selected_at=selected_at,
        manifest_path=manifest_path,
    )


def select_eurlex_forensic_evidence(
    *,
    artifact_id: str,
    selection_id: str,
    evidence_root: Path | str = DEFAULT_EUR_LEX_EVIDENCE_ROOT,
    selection_root: Path | str = (
        DEFAULT_EUR_LEX_FORENSIC_SELECTION_ROOT
    ),
    selected_at: datetime | None = None,
) -> EurLexForensicSelection:
    """Selecciona deliberadamente evidencia ya verificada para forense.

    Idempotente: repetir la misma selección (mismo ``artifact_id`` y
    misma ``selection_id``) nunca duplica ni reescribe el manifiesto;
    simplemente lo reverifica y lo devuelve.
    """

    artifact_id_n = _require_non_empty_str(
        artifact_id, field_name="artifact_id"
    )
    selection_id_n = _require_non_empty_str(
        selection_id, field_name="selection_id"
    )

    evidence_metadata_path = (
        Path(evidence_root) / f"{artifact_id_n}.json"
    )

    if not evidence_metadata_path.is_file():
        raise EurLexForensicSelectionError(
            "No existe evidencia EUR-Lex verificada con artifact_id="
            f"{artifact_id_n}"
        )

    artifact = load_eurlex_evidence_artifact(evidence_metadata_path)

    if artifact.artifact_id != artifact_id_n:
        raise EurLexForensicSelectionIntegrityError(
            "artifact_id recalculado no coincide con el solicitado"
        )

    evidence_raw_path = evidence_metadata_path.with_suffix(".raw")

    selection_root_path = Path(selection_root)
    selection_root_path.mkdir(parents=True, exist_ok=True)

    selection_key = _selection_key(
        artifact_id=artifact_id_n,
        selection_id=selection_id_n,
    )
    manifest_path = selection_root_path / f"{selection_key}.json"

    if manifest_path.is_file():
        return load_eurlex_forensic_selection(manifest_path)

    manifest = _manifest_from_artifact(
        artifact,
        selection_id=selection_id_n,
        evidence_metadata_path=evidence_metadata_path,
        evidence_raw_path=evidence_raw_path,
        manifest_path=manifest_path,
        selected_at=(
            selected_at.astimezone(timezone.utc)
            if selected_at is not None
            else datetime.now(timezone.utc)
        ),
    )

    manifest_path.write_text(
        json.dumps(
            manifest.to_manifest_dict(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )

    return manifest


def load_eurlex_forensic_selection(
    manifest_path: Path | str,
) -> EurLexForensicSelection:
    """Carga un manifiesto forense reverificando la evidencia referida.

    Falla cerrado si el manifiesto fue manipulado, si la evidencia
    referenciada desapareció o si su contenido/identidad reverificados
    ya no coinciden con lo declarado en el manifiesto.
    """

    path = Path(manifest_path)

    if not path.is_file():
        raise EurLexForensicSelectionError(
            f"Manifiesto forense EUR-Lex no encontrado: {path}"
        )

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EurLexForensicSelectionError(
            f"Manifiesto forense EUR-Lex ilegible: {path}"
        ) from exc

    try:
        raw_manifest = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise EurLexForensicSelectionIntegrityError(
            f"Manifiesto forense EUR-Lex no es JSON válido: {path}"
        ) from exc

    if not isinstance(raw_manifest, dict):
        raise EurLexForensicSelectionIntegrityError(
            "Manifiesto forense EUR-Lex con forma inválida"
        )

    missing = _REQUIRED_MANIFEST_KEYS - raw_manifest.keys()

    if missing:
        raise EurLexForensicSelectionIntegrityError(
            "Manifiesto forense EUR-Lex incompleto, faltan campos: "
            f"{sorted(missing)}"
        )

    artifact_id = str(raw_manifest["artifact_id"])
    selection_id = str(raw_manifest["selection_id"])

    expected_key = _selection_key(
        artifact_id=artifact_id,
        selection_id=selection_id,
    )

    if expected_key != str(raw_manifest["selection_key"]):
        raise EurLexForensicSelectionIntegrityError(
            "selection_key del manifiesto forense no coincide con "
            "artifact_id/selection_id declarados"
        )

    if expected_key != path.stem:
        raise EurLexForensicSelectionIntegrityError(
            "selection_key del manifiesto forense no coincide con "
            "el nombre de archivo persistido"
        )

    evidence_metadata_path = Path(
        str(raw_manifest["evidence_metadata_path"])
    )

    try:
        artifact = load_eurlex_evidence_artifact(evidence_metadata_path)
    except EurLexEvidenceError as exc:
        raise EurLexForensicSelectionIntegrityError(
            "La evidencia EUR-Lex referenciada por el manifiesto "
            "forense no reverifica: "
            f"{exc}"
        ) from exc

    if artifact.artifact_id != artifact_id:
        raise EurLexForensicSelectionIntegrityError(
            "artifact_id del manifiesto forense no coincide con la "
            "evidencia reverificada"
        )

    if artifact.sha256_hex != str(raw_manifest["sha256"]):
        raise EurLexForensicSelectionIntegrityError(
            "sha256 del manifiesto forense no coincide con la "
            "evidencia reverificada"
        )

    if artifact.identity_sha256_hex != str(
        raw_manifest["identity_sha256"]
    ):
        raise EurLexForensicSelectionIntegrityError(
            "identity_sha256 del manifiesto forense no coincide con "
            "la evidencia reverificada"
        )

    if artifact.source_url != str(raw_manifest["source_url"]):
        raise EurLexForensicSelectionIntegrityError(
            "source_url del manifiesto forense no coincide con la "
            "evidencia reverificada"
        )

    try:
        selected_at = datetime.fromisoformat(
            str(raw_manifest["selected_at"])
        )
    except ValueError as exc:
        raise EurLexForensicSelectionIntegrityError(
            "selected_at del manifiesto forense ilegible"
        ) from exc

    return EurLexForensicSelection(
        schema_version=int(raw_manifest["schema_version"]),
        selection_key=expected_key,
        selection_id=selection_id,
        artifact_id=artifact.artifact_id,
        requested_identifier=artifact.requested_identifier,
        canonical_identifier=artifact.canonical_identifier,
        source_url=artifact.source_url,
        content_type=artifact.content_type,
        sha256=artifact.sha256_hex,
        identity_sha256=artifact.identity_sha256_hex,
        evidence_metadata_path=evidence_metadata_path,
        evidence_raw_path=evidence_metadata_path.with_suffix(".raw"),
        selected_at=selected_at,
        manifest_path=path,
    )


def verify_eurlex_forensic_selection(
    manifest_path: Path | str,
) -> EurLexForensicSelection:
    """Alias semántico de :func:`load_eurlex_forensic_selection`."""

    return load_eurlex_forensic_selection(manifest_path)
