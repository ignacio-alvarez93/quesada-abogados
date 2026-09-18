"""Catálogo determinista de evidencia bruta EUR-Lex ya verificada.

Esta capa NO descarga ni interpreta contenido EUR-Lex. Únicamente
escanea el árbol runtime que sigue la convención de artefactos
``EurLexEvidenceArtifact`` (``evidence.py``), reverifica cada par
metadata/raw candidato con el loader de integridad existente y expone
registros inmutables de solo-metadata en orden determinista.

Ningún par corrupto, incompleto, huérfano o con metadata/raw
desalineados aparece jamás como evidencia válida: se expone
explícitamente en el resultado ``rejected`` del catálogo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .evidence import (
    DEFAULT_EUR_LEX_EVIDENCE_ROOT,
    EurLexEvidenceArtifact,
    EurLexEvidenceError,
    load_eurlex_evidence_artifact,
)


@dataclass(frozen=True, slots=True)
class EurLexEvidenceCatalogEntry:
    """Registro inmutable de solo-metadata de evidencia verificada."""

    artifact_id: str
    provider: str
    requested_identifier: str
    canonical_identifier: str | None
    source_url: str
    content_type: str | None
    retrieved_at: datetime
    byte_length: int
    sha256: str
    identity_sha256: str
    metadata_path: Path
    raw_path: Path

    @staticmethod
    def from_artifact(
        artifact: EurLexEvidenceArtifact,
        *,
        metadata_path: Path,
        raw_path: Path,
    ) -> "EurLexEvidenceCatalogEntry":
        return EurLexEvidenceCatalogEntry(
            artifact_id=artifact.artifact_id,
            provider=artifact.provider,
            requested_identifier=artifact.requested_identifier,
            canonical_identifier=artifact.canonical_identifier,
            source_url=artifact.source_url,
            content_type=artifact.content_type,
            retrieved_at=artifact.retrieved_at,
            byte_length=artifact.byte_length,
            sha256=artifact.sha256_hex,
            identity_sha256=artifact.identity_sha256_hex,
            metadata_path=metadata_path,
            raw_path=raw_path,
        )


@dataclass(frozen=True, slots=True)
class EurLexEvidenceCatalogRejection:
    """Candidato descartado: nunca se expone como evidencia válida."""

    stem: str
    reason: str
    metadata_path: Path | None
    raw_path: Path | None


@dataclass(frozen=True, slots=True)
class EurLexEvidenceCatalog:
    """Resultado determinista de escanear el árbol runtime de evidencia."""

    verified: tuple[EurLexEvidenceCatalogEntry, ...]
    rejected: tuple[EurLexEvidenceCatalogRejection, ...]


def build_eurlex_evidence_catalog(
    root_dir: Path | str = DEFAULT_EUR_LEX_EVIDENCE_ROOT,
    *,
    requested_identifier: str | None = None,
    canonical_identifier: str | None = None,
    artifact_id: str | None = None,
) -> EurLexEvidenceCatalog:
    """Escanea, reverifica y filtra evidencia EUR-Lex ya persistida.

    Solo reconoce la convención de artefactos de ``evidence.py``
    (``<artifact_id>.json`` + ``<artifact_id>.raw``). Cualquier par
    incompleto, huérfano o cuya integridad no reverifique se reporta
    en ``rejected`` y jamás en ``verified``.
    """

    root = Path(root_dir)

    if not root.is_dir():
        return EurLexEvidenceCatalog(verified=(), rejected=())

    json_paths = {path.stem: path for path in root.glob("*.json")}
    raw_paths = {path.stem: path for path in root.glob("*.raw")}

    stems = sorted(set(json_paths) | set(raw_paths))

    verified: list[EurLexEvidenceCatalogEntry] = []
    rejected: list[EurLexEvidenceCatalogRejection] = []

    for stem in stems:
        metadata_path = json_paths.get(stem)
        raw_path = raw_paths.get(stem)

        if metadata_path is None:
            rejected.append(
                EurLexEvidenceCatalogRejection(
                    stem=stem,
                    reason=(
                        "Raw evidence sin metadata asociada (huérfano)"
                    ),
                    metadata_path=None,
                    raw_path=raw_path,
                )
            )
            continue

        try:
            artifact = load_eurlex_evidence_artifact(metadata_path)
        except EurLexEvidenceError as exc:
            rejected.append(
                EurLexEvidenceCatalogRejection(
                    stem=stem,
                    reason=str(exc),
                    metadata_path=metadata_path,
                    raw_path=raw_path,
                )
            )
            continue

        verified.append(
            EurLexEvidenceCatalogEntry.from_artifact(
                artifact,
                metadata_path=metadata_path,
                raw_path=metadata_path.with_suffix(".raw"),
            )
        )

    if requested_identifier is not None:
        wanted = str(requested_identifier).strip()
        verified = [
            entry
            for entry in verified
            if entry.requested_identifier == wanted
        ]

    if canonical_identifier is not None:
        wanted = str(canonical_identifier).strip()
        verified = [
            entry
            for entry in verified
            if entry.canonical_identifier == wanted
        ]

    if artifact_id is not None:
        wanted = str(artifact_id).strip()
        verified = [
            entry
            for entry in verified
            if entry.artifact_id == wanted
        ]

    verified.sort(key=lambda entry: entry.artifact_id)
    rejected.sort(key=lambda entry: entry.stem)

    return EurLexEvidenceCatalog(
        verified=tuple(verified),
        rejected=tuple(rejected),
    )
