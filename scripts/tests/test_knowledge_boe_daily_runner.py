from pathlib import Path

import pytest

from backend.knowledge.boe import (
    BoeProvider,
)
from backend.knowledge.boe.daily_runner import (
    BoeDailyIngestionRunner,
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


IDS = (
    "BOE-A-2026-15300",
    "BOE-A-2026-15301",
    "BOE-A-2026-15302",
)


class _FakeTransport:
    def __init__(self):
        self.source_revisions = {
            external_id: "20260720145601"
            for external_id in IDS
        }

        self.texts = {
            external_id: (
                f"Artículo 1. "
                f"Contenido {external_id}."
            )
            for external_id in IDS
        }

        self.fail_ids = set()

    def discover(
        self,
        *,
        cursor=None,
    ):
        items = []

        for external_id in IDS:
            items.append(
                {
                    "identificador": external_id,
                    "titulo": (
                        f"Disposición "
                        f"{external_id}"
                    ),
                    "url_html": (
                        "https://www.boe.es/"
                        "diario_boe/txt.php"
                        f"?id={external_id}"
                    ),
                    "url_xml": (
                        "https://www.boe.es/"
                        "diario_boe/xml.php"
                        f"?id={external_id}"
                    ),
                    "url_pdf": {
                        "texto": (
                            "https://www.boe.es/"
                            "pdf/"
                            f"{external_id}.pdf"
                        ),
                    },
                }
            )

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
                                "item": items,
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
        if external_id in self.fail_ids:
            raise RuntimeError(
                "fallo sintético de fetch"
            )

        return {
            "id": external_id,
            "title": (
                f"Disposición {external_id}"
            ),
            "text": self.texts[
                external_id
            ],
            "published_on": (
                "2026-07-14"
            ),
            "url": (
                "https://www.boe.es/"
                f"eli/test/{external_id}"
            ),
            "source_revision": (
                self.source_revisions[
                    external_id
                ]
            ),
            "language": "es",
            "metadata": {
                "rango": "Resolución",
            },
        }


def _runtime(
    tmp_path: Path,
):
    repository = (
        SQLiteKnowledgeRepository(
            tmp_path
            / "boe_daily.db"
        )
    )
    repository.initialize_schema()

    transport = _FakeTransport()
    provider = BoeProvider(
        transport
    )

    service = (
        KnowledgeIngestionService(
            repository
        )
    )

    runner = (
        BoeDailyIngestionRunner(
            provider=provider,
            service=service,
        )
    )

    return (
        repository,
        transport,
        runner,
    )


def test_dry_run_discovers_but_writes_nothing(
    tmp_path,
):
    repository, _, runner = (
        _runtime(tmp_path)
    )

    result = runner.run(
        publication_date="20260714",
        dry_run=True,
    )

    assert result.discovered_count == 3
    assert result.attempted_count == 3
    assert result.new_count == 3
    assert result.written_count == 0
    assert result.failed_count == 0

    for external_id in IDS:
        assert repository.get_current(
            "BOE",
            external_id,
        ) is None


def test_apply_persists_all_new_items(
    tmp_path,
):
    repository, _, runner = (
        _runtime(tmp_path)
    )

    result = runner.run(
        publication_date="20260714",
        dry_run=False,
    )

    assert result.new_count == 3
    assert result.written_count == 3
    assert result.failed_count == 0

    for external_id in IDS:
        assert repository.get_current(
            "BOE",
            external_id,
        ) is not None


def test_second_apply_is_idempotent(
    tmp_path,
):
    repository, _, runner = (
        _runtime(tmp_path)
    )

    runner.run(
        publication_date="20260714",
        dry_run=False,
    )

    result = runner.run(
        publication_date="20260714",
        dry_run=False,
    )

    assert result.new_count == 0
    assert result.unchanged_count == 3
    assert result.written_count == 0

    for external_id in IDS:
        history = (
            repository.list_revisions(
                "BOE",
                external_id,
            )
        )
        assert len(history) == 1


def test_dry_run_detects_revision_without_persisting(
    tmp_path,
):
    repository, transport, runner = (
        _runtime(tmp_path)
    )

    runner.run(
        publication_date="20260714",
        dry_run=False,
    )

    target = IDS[0]

    transport.source_revisions[
        target
    ] = "20260721101010"

    result = runner.run(
        publication_date="20260714",
        dry_run=True,
    )

    assert (
        result.metadata_revised_count
        == 1
    )
    assert result.unchanged_count == 2
    assert result.written_count == 0

    stored = repository.get_current(
        "BOE",
        target,
    )

    assert stored is not None
    assert (
        stored.source_revision
        == "20260720145601"
    )

    assert len(
        repository.list_revisions(
            "BOE",
            target,
        )
    ) == 1


def test_item_failure_does_not_abort_batch(
    tmp_path,
):
    repository, transport, runner = (
        _runtime(tmp_path)
    )

    transport.fail_ids.add(
        IDS[1]
    )

    result = runner.run(
        publication_date="20260714",
        dry_run=False,
    )

    assert result.attempted_count == 3
    assert result.new_count == 2
    assert result.written_count == 2
    assert result.failed_count == 1

    assert result.results[1].status is None
    assert (
        "fallo sintético"
        in result.results[1].error
    )

    assert repository.get_current(
        "BOE",
        IDS[0],
    ) is not None

    assert repository.get_current(
        "BOE",
        IDS[1],
    ) is None

    assert repository.get_current(
        "BOE",
        IDS[2],
    ) is not None


def test_limit_caps_attempted_references(
    tmp_path,
):
    repository, _, runner = (
        _runtime(tmp_path)
    )

    result = runner.run(
        publication_date="20260714",
        dry_run=False,
        limit=2,
    )

    assert result.discovered_count == 3
    assert result.attempted_count == 2
    assert result.written_count == 2

    assert repository.get_current(
        "BOE",
        IDS[2],
    ) is None


@pytest.mark.parametrize(
    "publication_date",
    [
        "",
        "202607",
        "20260231",
        "abcdefgh",
    ],
)
def test_invalid_publication_date_is_rejected(
    tmp_path,
    publication_date,
):
    _, _, runner = _runtime(
        tmp_path
    )

    with pytest.raises(
        ValueError,
    ):
        runner.run(
            publication_date=(
                publication_date
            )
        )


@pytest.mark.parametrize(
    "limit",
    [
        0,
        -1,
        True,
        1.5,
    ],
)
def test_invalid_limit_is_rejected(
    tmp_path,
    limit,
):
    _, _, runner = _runtime(
        tmp_path
    )

    with pytest.raises(
        ValueError,
        match="entero positivo",
    ):
        runner.run(
            publication_date="20260714",
            limit=limit,
        )


def test_dry_run_must_be_bool(
    tmp_path,
):
    _, _, runner = _runtime(
        tmp_path
    )

    with pytest.raises(
        TypeError,
        match="dry_run debe ser bool",
    ):
        runner.run(
            publication_date="20260714",
            dry_run="yes",
        )
