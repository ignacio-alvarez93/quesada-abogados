from pathlib import Path

import pytest

from backend.knowledge.boe import (
    BoeProvider,
)
from backend.knowledge.ingestion import (
    KnowledgeIngestionService,
)
from backend.knowledge.revisions import (
    KnowledgeRevisionStatus,
)
from backend.knowledge.sqlite_repository import (
    SQLiteKnowledgeRepository,
)


TARGET = "BOE-A-2026-15300"


class _FakeBoeTransport:
    def __init__(self):
        self.text = (
            "Artículo 1. Contenido jurídico "
            "de prueba."
        )
        self.source_revision = (
            "20260720145601"
        )

    def discover(
        self,
        *,
        cursor=None,
    ):
        return {
            "status": {
                "code": "200",
                "text": "ok",
            },
            "data": {
                "sumario": {
                    "metadatos": {
                        "publicacion": "BOE",
                        "fecha_publicacion": (
                            "20260714"
                        ),
                    },
                    "diario": {
                        "seccion": {
                            "departamento": {
                                "item": {
                                    "identificador": (
                                        TARGET
                                    ),
                                    "titulo": (
                                        "Disposición "
                                        "de prueba"
                                    ),
                                    "url_html": (
                                        "https://www.boe.es/"
                                        "diario_boe/txt.php"
                                        f"?id={TARGET}"
                                    ),
                                    "url_xml": (
                                        "https://www.boe.es/"
                                        "diario_boe/xml.php"
                                        f"?id={TARGET}"
                                    ),
                                    "url_pdf": {
                                        "texto": (
                                            "https://www.boe.es/"
                                            "boe/dias/2026/07/14/"
                                            f"pdfs/{TARGET}.pdf"
                                        ),
                                    },
                                }
                            }
                        }
                    },
                }
            },
        }

    def fetch(
        self,
        external_id,
    ):
        assert external_id == TARGET

        return {
            "id": TARGET,
            "title": (
                "Disposición de prueba"
            ),
            "text": self.text,
            "published_on": (
                "2026-07-14"
            ),
            "url": (
                "https://www.boe.es/"
                "eli/es/test/2026/07/14/1"
            ),
            "source_revision": (
                self.source_revision
            ),
            "language": "es",
            "metadata": {
                "rango": "Resolución",
                "url_pdf": (
                    "https://www.boe.es/"
                    "boe/dias/2026/07/14/"
                    f"pdfs/{TARGET}.pdf"
                ),
            },
        }


def _repository(
    tmp_path: Path,
):
    repository = (
        SQLiteKnowledgeRepository(
            tmp_path
            / "knowledge_ingestion.db"
        )
    )

    repository.initialize_schema()

    return repository


def _provider():
    transport = _FakeBoeTransport()

    return (
        BoeProvider(
            transport
        ),
        transport,
    )


def test_first_ingestion_is_new(
    tmp_path,
):
    repository = _repository(
        tmp_path
    )
    provider, _ = _provider()

    service = (
        KnowledgeIngestionService(
            repository
        )
    )

    batch = (
        provider.discover(
            cursor="20260714"
        )
    )

    reference = batch.items[0]

    result = (
        service.ingest_reference(
            provider,
            reference,
        )
    )

    assert (
        result.status
        is KnowledgeRevisionStatus.NEW
    )
    assert result.written is True
    assert result.revision_number == 1

    stored = repository.get_current(
        "BOE",
        TARGET,
    )

    assert stored is not None
    assert (
        stored.source_revision
        == "20260720145601"
    )


def test_second_identical_ingestion_is_unchanged(
    tmp_path,
):
    repository = _repository(
        tmp_path
    )
    provider, _ = _provider()

    service = (
        KnowledgeIngestionService(
            repository
        )
    )

    first = (
        service.discover_and_ingest(
            provider,
            cursor="20260714",
        )
    )

    second = (
        service.discover_and_ingest(
            provider,
            cursor="20260714",
        )
    )

    assert (
        first.results[0].status
        is KnowledgeRevisionStatus.NEW
    )

    assert (
        second.results[0].status
        is KnowledgeRevisionStatus.UNCHANGED
    )

    assert (
        second.results[0].written
        is False
    )

    history = (
        repository.list_revisions(
            "BOE",
            TARGET,
        )
    )

    assert len(history) == 1


def test_source_revision_change_is_persisted(
    tmp_path,
):
    repository = _repository(
        tmp_path
    )
    provider, transport = _provider()

    service = (
        KnowledgeIngestionService(
            repository
        )
    )

    service.discover_and_ingest(
        provider,
        cursor="20260714",
    )

    transport.source_revision = (
        "20260721101010"
    )

    result = (
        service.discover_and_ingest(
            provider,
            cursor="20260714",
        )
    )

    assert (
        result.results[0].status
        is KnowledgeRevisionStatus.METADATA_REVISED
    )

    assert (
        result.results[0].revision_number
        == 2
    )

    history = (
        repository.list_revisions(
            "BOE",
            TARGET,
        )
    )

    assert len(history) == 2


def test_content_change_is_persisted(
    tmp_path,
):
    repository = _repository(
        tmp_path
    )
    provider, transport = _provider()

    service = (
        KnowledgeIngestionService(
            repository
        )
    )

    service.discover_and_ingest(
        provider,
        cursor="20260714",
    )

    transport.text = (
        "Artículo 1. "
        "Contenido jurídicamente modificado."
    )

    transport.source_revision = (
        "20260722121212"
    )

    result = (
        service.discover_and_ingest(
            provider,
            cursor="20260714",
        )
    )

    assert (
        result.results[0].status
        is KnowledgeRevisionStatus.CONTENT_REVISED
    )

    assert (
        result.results[0].revision_number
        == 2
    )


def test_batch_result_reports_counts(
    tmp_path,
):
    repository = _repository(
        tmp_path
    )
    provider, _ = _provider()

    service = (
        KnowledgeIngestionService(
            repository
        )
    )

    result = (
        service.discover_and_ingest(
            provider,
            cursor="20260714",
        )
    )

    assert result.source_key == "BOE"
    assert result.discovered_count == 1
    assert result.attempted_count == 1
    assert result.written_count == 1
    assert result.unchanged_count == 0
    assert len(result.results) == 1


def test_batch_limit_is_respected(
    tmp_path,
):
    repository = _repository(
        tmp_path
    )
    provider, _ = _provider()

    service = (
        KnowledgeIngestionService(
            repository
        )
    )

    result = (
        service.discover_and_ingest(
            provider,
            cursor="20260714",
            limit=1,
        )
    )

    assert result.discovered_count == 1
    assert result.attempted_count == 1


@pytest.mark.parametrize(
    "limit",
    [
        0,
        -1,
        True,
        1.5,
    ],
)
def test_invalid_batch_limit_is_rejected(
    tmp_path,
    limit,
):
    repository = _repository(
        tmp_path
    )
    provider, _ = _provider()

    service = (
        KnowledgeIngestionService(
            repository
        )
    )

    with pytest.raises(
        ValueError,
        match="entero positivo",
    ):
        service.discover_and_ingest(
            provider,
            cursor="20260714",
            limit=limit,
        )


def test_preview_new_item_does_not_persist(
    tmp_path,
):
    repository = _repository(
        tmp_path
    )
    provider, _ = _provider()

    service = (
        KnowledgeIngestionService(
            repository
        )
    )

    batch = provider.discover(
        cursor="20260714"
    )

    preview = service.preview_reference(
        provider,
        batch.items[0],
    )

    assert (
        preview.status
        is KnowledgeRevisionStatus.NEW
    )

    assert repository.get_current(
        "BOE",
        TARGET,
    ) is None

    assert repository.list_revisions(
        "BOE",
        TARGET,
    ) == ()


def test_preview_existing_item_detects_change_without_writing(
    tmp_path,
):
    repository = _repository(
        tmp_path
    )
    provider, transport = _provider()

    service = (
        KnowledgeIngestionService(
            repository
        )
    )

    service.discover_and_ingest(
        provider,
        cursor="20260714",
    )

    transport.source_revision = (
        "20260721101010"
    )

    batch = provider.discover(
        cursor="20260714"
    )

    preview = service.preview_reference(
        provider,
        batch.items[0],
    )

    assert (
        preview.status
        is KnowledgeRevisionStatus.METADATA_REVISED
    )

    stored = repository.get_current(
        "BOE",
        TARGET,
    )

    assert stored is not None
    assert (
        stored.source_revision
        == "20260720145601"
    )

    history = repository.list_revisions(
        "BOE",
        TARGET,
    )

    assert len(history) == 1
