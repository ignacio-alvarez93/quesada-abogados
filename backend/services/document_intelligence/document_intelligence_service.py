"""
Servicio principal reutilizable de inteligencia documental.

Coordina:
- extracción nativa;
- recuperación de caché;
- OCR selectivo;
- persistencia del resultado.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from .document_image_renderer import (
    PdfPageRenderer,
)
from .document_ocr_service import (
    complete_document_ocr,
)
from .document_text_policy import (
    DEFAULT_TEXT_POLICY,
    DocumentTextPolicy,
)
from .document_text_service import (
    calculate_sha256,
    extract_document_text,
)
from .ocr_engine import OcrEngine
from . import document_ocr_repository


PIPELINE_VERSION = "DOCUMENT_INTELLIGENCE_V1"
NATIVE_EXTRACTOR = "PYPDF"


def policy_fingerprint(
    policy: DocumentTextPolicy,
) -> str:
    payload = {
        "minimum_characters": (
            policy.minimum_characters
        ),
        "minimum_alphanumeric_characters": (
            policy
            .minimum_alphanumeric_characters
        ),
        "minimum_words": (
            policy.minimum_words
        ),
    }

    encoded = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")

    return hashlib.sha256(
        encoded
    ).hexdigest()


def process_document(
    source_path: str | Path,
    *,
    engine: OcrEngine,
    language: str = "eng",
    render_dpi: int = 220,
    policy: DocumentTextPolicy = (
        DEFAULT_TEXT_POLICY
    ),
    db_path=None,
    force_reprocess: bool = False,
):
    path = Path(source_path)

    if not path.exists():
        raise FileNotFoundError(
            f"No existe el archivo: {path}"
        )

    source_sha256 = calculate_sha256(
        path
    )

    engine_version = (
        engine.get_version()
        if engine.is_available()
        else ""
    )

    fingerprint = policy_fingerprint(
        policy
    )

    repository_kwargs = {}

    if db_path is not None:
        repository_kwargs["db_path"] = (
            db_path
        )

    if not force_reprocess:
        cached = (
            document_ocr_repository
            .get_cached_result(
                source_sha256=source_sha256,
                pipeline_version=(
                    PIPELINE_VERSION
                ),
                native_extractor=(
                    NATIVE_EXTRACTOR
                ),
                ocr_engine=engine.engine_code,
                ocr_engine_version=(
                    engine_version
                ),
                ocr_language=language,
                render_dpi=render_dpi,
                policy_fingerprint=(
                    fingerprint
                ),
                **repository_kwargs,
            )
        )

        if cached:
            return cached

    native_result = extract_document_text(
        path,
        policy=policy,
    )

    result = native_result

    if native_result.requires_ocr:
        with tempfile.TemporaryDirectory(
            prefix="quesada_ocr_pipeline_"
        ) as temporary_directory:
            result = complete_document_ocr(
                native_result,
                engine=engine,
                renderer=PdfPageRenderer(
                    dpi=render_dpi,
                    output_directory=(
                        temporary_directory
                    ),
                ),
                language=language,
                policy=policy,
            )

    result.metadata = {
        **result.metadata,
        "cache": {
            "cache_hit": False,
            "pipeline_version": (
                PIPELINE_VERSION
            ),
            "policy_fingerprint": (
                fingerprint
            ),
            "render_dpi": render_dpi,
        },
    }

    persisted = (
        document_ocr_repository
        .persist_result(
            result,
            pipeline_version=(
                PIPELINE_VERSION
            ),
            native_extractor=(
                NATIVE_EXTRACTOR
            ),
            ocr_engine=engine.engine_code,
            ocr_engine_version=(
                engine_version
            ),
            ocr_language=language,
            render_dpi=render_dpi,
            policy_fingerprint=(
                fingerprint
            ),
            **repository_kwargs,
        )
    )

    persisted.metadata = {
        **persisted.metadata,
        "cache": {
            **persisted.metadata.get(
                "cache",
                {},
            ),
            "cache_hit": False,
        },
    }

    return persisted
