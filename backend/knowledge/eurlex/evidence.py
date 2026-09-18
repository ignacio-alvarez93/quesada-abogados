"""Evidencia bruta auténtica EUR-Lex y su cadena de provenance.

Esta capa preserva EXACTAMENTE los bytes de una respuesta EUR-Lex
(descargada o importada por un operador) junto con metadata
determinista suficiente para probar identidad y origen.

Separación deliberada de tres conceptos que NO deben confundirse:

- evidencia bruta auténtica (este módulo):
  bytes de respuesta sin modificar más provenance;

- fixture de test:
  contenido sintético o recortado usado para ejercitar el parser;

- snapshot estructural parseado:
  salida de ``full_structure``/``article_structure`` sobre un payload.

Capturar o importar evidencia NUNCA promueve automáticamente ese
payload a fixture de confianza ni cambia el comportamiento del
parser. Esta capa no interpreta HTML/XHTML EUR-Lex.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Protocol

from .parser import EUR_LEX_SOURCE_KEY, normalize_celex


EUR_LEX_EVIDENCE_SCHEMA_VERSION = 1

EUR_LEX_EVIDENCE_PROVIDER = EUR_LEX_SOURCE_KEY

DEFAULT_EUR_LEX_EVIDENCE_ROOT = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "knowledge_eurlex_evidence"
)

_RESERVED_METADATA_KEYS = frozenset(
    {
        "schema_version",
        "provider",
        "requested_identifier",
        "canonical_identifier",
        "source_url",
        "content_type",
        "retrieved_at",
        "byte_length",
        "sha256",
        "identity_sha256",
        "artifact_id",
    }
)

_REQUIRED_METADATA_KEYS = frozenset(
    {
        "schema_version",
        "provider",
        "requested_identifier",
        "source_url",
        "retrieved_at",
        "byte_length",
        "sha256",
        "identity_sha256",
        "artifact_id",
    }
)


class EurLexEvidenceError(RuntimeError):
    """Error controlado de la capa de evidencia EUR-Lex."""


class EurLexEvidenceIntegrityError(EurLexEvidenceError):
    """La evidencia persistida no coincide con su propia metadata."""


def _require_non_empty_str(
    value: object,
    *,
    field_name: str,
) -> str:
    text = str(value or "").strip()

    if not text:
        raise ValueError(
            f"EUR-Lex evidence {field_name} no puede estar vacío"
        )

    return text


def _normalize_optional_str(
    value: object | None,
) -> str | None:
    if value is None:
        return None

    text = str(value).strip()

    return text or None


def _normalize_retrieved_at(
    value: datetime,
) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(
            "EUR-Lex evidence retrieved_at debe ser datetime"
        )

    if value.tzinfo is None:
        raise ValueError(
            "EUR-Lex evidence retrieved_at debe ser timezone-aware"
        )

    return value.astimezone(timezone.utc)


def _normalize_extra_metadata(
    value: Mapping[str, object] | tuple[tuple[str, str], ...] | None,
) -> tuple[tuple[str, str], ...]:
    if not value:
        return ()

    items = (
        value.items()
        if isinstance(value, Mapping)
        else value
    )

    normalized: dict[str, str] = {}

    for key, val in items:
        key_text = str(key or "").strip()

        if not key_text:
            raise ValueError(
                "EUR-Lex evidence extra_metadata no admite claves vacías"
            )

        if key_text in _RESERVED_METADATA_KEYS:
            raise ValueError(
                "EUR-Lex evidence extra_metadata no puede "
                f"sobrescribir el campo reservado: {key_text}"
            )

        normalized[key_text] = str(val)

    return tuple(
        sorted(
            normalized.items()
        )
    )


@dataclass(frozen=True, slots=True)
class EurLexEvidenceArtifact:
    """Evidencia bruta auténtica EUR-Lex con provenance determinista.

    No es un fixture de test confiable ni un snapshot estructural
    parseado: es la materia prima forense sobre la que un parser
    podrá auditarse posteriormente.
    """

    provider: str
    requested_identifier: str
    source_url: str
    body: bytes
    canonical_identifier: str | None = None
    content_type: str | None = None
    retrieved_at: datetime | None = None
    extra_metadata: (
        Mapping[str, object] | tuple[tuple[str, str], ...] | None
    ) = None
    schema_version: int = EUR_LEX_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        provider = _require_non_empty_str(
            self.provider,
            field_name="provider",
        )

        requested_identifier = _require_non_empty_str(
            self.requested_identifier,
            field_name="requested_identifier",
        )

        source_url = _require_non_empty_str(
            self.source_url,
            field_name="source_url",
        )

        canonical_identifier = _normalize_optional_str(
            self.canonical_identifier
        )

        content_type = _normalize_optional_str(
            self.content_type
        )

        retrieved_at = _normalize_retrieved_at(
            self.retrieved_at
            if self.retrieved_at is not None
            else datetime.now(timezone.utc)
        )

        extra_metadata = _normalize_extra_metadata(
            self.extra_metadata
        )

        if not isinstance(self.body, (bytes, bytearray)):
            raise TypeError(
                "EUR-Lex evidence body debe ser bytes"
            )

        body = bytes(self.body)

        if not body:
            raise ValueError(
                "EUR-Lex evidence body no puede estar vacío"
            )

        if (
            not isinstance(self.schema_version, int)
            or isinstance(self.schema_version, bool)
            or self.schema_version <= 0
        ):
            raise ValueError(
                "EUR-Lex evidence schema_version debe ser entero positivo"
            )

        object.__setattr__(self, "provider", provider)
        object.__setattr__(
            self, "requested_identifier", requested_identifier
        )
        object.__setattr__(self, "source_url", source_url)
        object.__setattr__(
            self, "canonical_identifier", canonical_identifier
        )
        object.__setattr__(self, "content_type", content_type)
        object.__setattr__(self, "retrieved_at", retrieved_at)
        object.__setattr__(self, "extra_metadata", extra_metadata)
        object.__setattr__(self, "body", body)

    @property
    def byte_length(self) -> int:
        return len(self.body)

    @property
    def sha256_hex(self) -> str:
        return sha256(self.body).hexdigest()

    @property
    def identity_key(self) -> str:
        """Identidad de origen: NO incluye los bytes."""

        return "|".join(
            (
                self.provider,
                self.requested_identifier,
                self.canonical_identifier or "",
                self.source_url,
            )
        )

    @property
    def identity_sha256_hex(self) -> str:
        return sha256(
            self.identity_key.encode("utf-8")
        ).hexdigest()

    @property
    def artifact_id(self) -> str:
        """Identidad de archivo determinista: origen + contenido.

        Origen y bytes idénticos producen siempre el mismo
        ``artifact_id`` (idempotencia). Si cualquiera de los dos
        cambia genuinamente, el ``artifact_id`` cambia y el
        artefacto anterior se conserva intacto.
        """

        return f"{self.identity_sha256_hex}__{self.sha256_hex}"

    def to_metadata_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "provider": self.provider,
            "requested_identifier": self.requested_identifier,
            "canonical_identifier": self.canonical_identifier,
            "source_url": self.source_url,
            "content_type": self.content_type,
            "retrieved_at": self.retrieved_at.isoformat(),
            "byte_length": self.byte_length,
            "sha256": self.sha256_hex,
            "identity_sha256": self.identity_sha256_hex,
            "artifact_id": self.artifact_id,
            "extra_metadata": dict(self.extra_metadata),
        }


@dataclass(frozen=True, slots=True)
class EurLexEvidenceArtifactPaths:
    """Rutas runtime (ignoradas por Git) de una evidencia persistida."""

    metadata_path: Path
    raw_path: Path


def save_eurlex_evidence_artifact(
    artifact: EurLexEvidenceArtifact,
    *,
    root_dir: Path | str = DEFAULT_EUR_LEX_EVIDENCE_ROOT,
) -> EurLexEvidenceArtifactPaths:
    """Persiste evidencia bruta EUR-Lex bajo el árbol runtime ignorado.

    Origen + bytes idénticos son idempotentes: no se duplica nada en
    disco. Origen o bytes genuinamente distintos producen un
    ``artifact_id`` distinto y por tanto un artefacto separado.
    """

    if not isinstance(artifact, EurLexEvidenceArtifact):
        raise TypeError(
            "save_eurlex_evidence_artifact requiere EurLexEvidenceArtifact"
        )

    root = Path(root_dir)
    root.mkdir(parents=True, exist_ok=True)

    raw_path = root / f"{artifact.artifact_id}.raw"
    metadata_path = root / f"{artifact.artifact_id}.json"

    if raw_path.is_file() and metadata_path.is_file():
        # artifact_id ya combina identidad de origen + SHA-256 del
        # contenido, así que un mismo artifact_id ya persistido es,
        # por construcción, el mismo origen y los mismos bytes.
        # load_eurlex_evidence_artifact sigue verificando que lo
        # persistido en disco no haya sido alterado.
        load_eurlex_evidence_artifact(metadata_path)

        return EurLexEvidenceArtifactPaths(
            metadata_path=metadata_path,
            raw_path=raw_path,
        )

    raw_path.write_bytes(artifact.body)

    metadata_path.write_text(
        json.dumps(
            artifact.to_metadata_dict(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )

    return EurLexEvidenceArtifactPaths(
        metadata_path=metadata_path,
        raw_path=raw_path,
    )


def load_eurlex_evidence_artifact(
    metadata_path: Path | str,
) -> EurLexEvidenceArtifact:
    """Carga una evidencia persistida verificando su propia integridad.

    Falla cerrado si los bytes crudos no coinciden con la metadata
    almacenada (tamaño, SHA-256, identidad o ``artifact_id``).
    """

    path = Path(metadata_path)

    if not path.is_file():
        raise EurLexEvidenceError(
            f"Metadata de evidencia EUR-Lex no encontrada: {path}"
        )

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EurLexEvidenceError(
            f"Metadata de evidencia EUR-Lex ilegible: {path}"
        ) from exc

    try:
        raw_metadata = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise EurLexEvidenceIntegrityError(
            f"Metadata de evidencia EUR-Lex no es JSON válido: {path}"
        ) from exc

    if not isinstance(raw_metadata, dict):
        raise EurLexEvidenceIntegrityError(
            "Metadata de evidencia EUR-Lex con forma inválida"
        )

    missing = _REQUIRED_METADATA_KEYS - raw_metadata.keys()

    if missing:
        raise EurLexEvidenceIntegrityError(
            "Metadata de evidencia EUR-Lex incompleta, faltan campos: "
            f"{sorted(missing)}"
        )

    raw_path = path.with_suffix(".raw")

    if not raw_path.is_file():
        raise EurLexEvidenceError(
            f"Raw body de evidencia EUR-Lex no encontrado: {raw_path}"
        )

    try:
        body = raw_path.read_bytes()
    except OSError as exc:
        raise EurLexEvidenceError(
            f"Raw body de evidencia EUR-Lex ilegible: {raw_path}"
        ) from exc

    if not body:
        raise EurLexEvidenceIntegrityError(
            "Raw body de evidencia EUR-Lex vacío"
        )

    computed_sha256 = sha256(body).hexdigest()

    if computed_sha256 != raw_metadata["sha256"]:
        raise EurLexEvidenceIntegrityError(
            "SHA-256 de evidencia EUR-Lex no coincide con la metadata "
            "almacenada"
        )

    if len(body) != int(raw_metadata["byte_length"]):
        raise EurLexEvidenceIntegrityError(
            "byte_length de evidencia EUR-Lex no coincide con el body real"
        )

    try:
        retrieved_at = datetime.fromisoformat(
            str(raw_metadata["retrieved_at"])
        )
    except ValueError as exc:
        raise EurLexEvidenceIntegrityError(
            "retrieved_at de evidencia EUR-Lex ilegible"
        ) from exc

    artifact = EurLexEvidenceArtifact(
        provider=str(raw_metadata["provider"]),
        requested_identifier=str(raw_metadata["requested_identifier"]),
        source_url=str(raw_metadata["source_url"]),
        body=body,
        canonical_identifier=raw_metadata.get("canonical_identifier"),
        content_type=raw_metadata.get("content_type"),
        retrieved_at=retrieved_at,
        extra_metadata=raw_metadata.get("extra_metadata") or {},
        schema_version=int(raw_metadata["schema_version"]),
    )

    if artifact.identity_sha256_hex != raw_metadata["identity_sha256"]:
        raise EurLexEvidenceIntegrityError(
            "identity_sha256 de evidencia EUR-Lex no coincide con la "
            "identidad de origen recalculada"
        )

    if artifact.artifact_id != raw_metadata["artifact_id"]:
        raise EurLexEvidenceIntegrityError(
            "artifact_id de evidencia EUR-Lex no coincide con la "
            "identidad/contenido recalculados"
        )

    if artifact.artifact_id != path.stem:
        raise EurLexEvidenceIntegrityError(
            "artifact_id de evidencia EUR-Lex no coincide con el "
            "nombre de archivo persistido"
        )

    return artifact


def verify_eurlex_evidence_artifact(
    metadata_path: Path | str,
) -> EurLexEvidenceArtifact:
    """Prueba forense explícita: falla si la evidencia fue alterada.

    Alias semántico de :func:`load_eurlex_evidence_artifact` pensado
    para que un test forense declare intención de verificación, no
    solo de carga.
    """

    return load_eurlex_evidence_artifact(metadata_path)


def import_eurlex_evidence_file(
    *,
    source_path: Path | str,
    requested_identifier: str,
    source_url: str,
    provider: str = EUR_LEX_EVIDENCE_PROVIDER,
    canonical_identifier: str | None = None,
    content_type: str | None = None,
    retrieved_at: datetime | None = None,
    extra_metadata: Mapping[str, object] | None = None,
    root_dir: Path | str = DEFAULT_EUR_LEX_EVIDENCE_ROOT,
) -> EurLexEvidenceArtifactPaths:
    """Importa un payload EUR-Lex ya descargado por el operador.

    Permite ingerir evidencia auténtica incluso sin acceso a red,
    siempre que el operador declare identidad y origen exactos del
    fichero ya descargado. No interpreta ni valida el contenido.
    """

    path = Path(source_path)

    if not path.is_file():
        raise EurLexEvidenceError(
            f"Archivo de evidencia EUR-Lex no encontrado: {path}"
        )

    try:
        body = path.read_bytes()
    except OSError as exc:
        raise EurLexEvidenceError(
            f"Archivo de evidencia EUR-Lex ilegible: {path}"
        ) from exc

    if not body:
        raise EurLexEvidenceError(
            f"Archivo de evidencia EUR-Lex vacío: {path}"
        )

    artifact = EurLexEvidenceArtifact(
        provider=provider,
        requested_identifier=requested_identifier,
        source_url=source_url,
        body=body,
        canonical_identifier=canonical_identifier,
        content_type=content_type,
        retrieved_at=retrieved_at,
        extra_metadata=extra_metadata,
    )

    return save_eurlex_evidence_artifact(
        artifact,
        root_dir=root_dir,
    )


class EurLexEvidenceAcquisitionTransport(Protocol):
    """Puerto mínimo reutilizado de :mod:`transport` para adquisición."""

    def fetch_tree_notice(self, celex: str):
        ...

    def fetch_original_content(self, celex: str):
        ...

    def fetch_consolidated_content(self, consolidated_celex: str):
        ...

    def resolve_latest_consolidated(
        self, original_celex: str
    ):
        ...


def _artifact_from_http_response(
    *,
    requested_identifier: str,
    canonical_identifier: str | None,
    response: object,
) -> EurLexEvidenceArtifact:
    body = getattr(response, "body", None)

    if not isinstance(body, (bytes, bytearray)):
        raise TypeError(
            "Transporte EUR-Lex debe devolver respuesta con body bytes"
        )

    source_url = str(
        getattr(response, "final_url", "")
        or getattr(response, "requested_url", "")
    )

    transport_name = getattr(response, "transport", None)

    extra_metadata: dict[str, object] = {}

    if transport_name:
        extra_metadata["transport"] = str(transport_name)

    return EurLexEvidenceArtifact(
        provider=EUR_LEX_EVIDENCE_PROVIDER,
        requested_identifier=requested_identifier,
        canonical_identifier=canonical_identifier,
        source_url=source_url,
        content_type=getattr(response, "content_type", None),
        body=bytes(body),
        extra_metadata=extra_metadata,
    )


def acquire_eurlex_tree_notice_evidence(
    transport: EurLexEvidenceAcquisitionTransport,
    celex: str,
    *,
    root_dir: Path | str = DEFAULT_EUR_LEX_EVIDENCE_ROOT,
) -> EurLexEvidenceArtifactPaths:
    """Descarga y persiste el tree notice Cellar tal cual se recibe."""

    identifier = normalize_celex(celex)

    response = transport.fetch_tree_notice(identifier)

    artifact = _artifact_from_http_response(
        requested_identifier=identifier,
        canonical_identifier=identifier,
        response=response,
    )

    return save_eurlex_evidence_artifact(artifact, root_dir=root_dir)


def acquire_eurlex_original_evidence(
    transport: EurLexEvidenceAcquisitionTransport,
    original_celex: str,
    *,
    root_dir: Path | str = DEFAULT_EUR_LEX_EVIDENCE_ROOT,
) -> EurLexEvidenceArtifactPaths:
    """Descarga y persiste el acto original tal cual se recibe."""

    identifier = normalize_celex(original_celex)

    response = transport.fetch_original_content(identifier)

    artifact = _artifact_from_http_response(
        requested_identifier=identifier,
        canonical_identifier=identifier,
        response=response,
    )

    return save_eurlex_evidence_artifact(artifact, root_dir=root_dir)


def acquire_eurlex_consolidated_evidence(
    transport: EurLexEvidenceAcquisitionTransport,
    original_celex: str,
    *,
    root_dir: Path | str = DEFAULT_EUR_LEX_EVIDENCE_ROOT,
) -> EurLexEvidenceArtifactPaths:
    """Resuelve, descarga y persiste la última revisión consolidada.

    La identidad canónica registrada es el CELEX consolidado
    realmente resuelto por el transporte, no el original solicitado.
    """

    identifier = normalize_celex(original_celex)

    consolidated_celex, _metadata_response = (
        transport.resolve_latest_consolidated(identifier)
    )

    response = transport.fetch_consolidated_content(
        consolidated_celex
    )

    artifact = _artifact_from_http_response(
        requested_identifier=identifier,
        canonical_identifier=consolidated_celex,
        response=response,
    )

    return save_eurlex_evidence_artifact(artifact, root_dir=root_dir)
