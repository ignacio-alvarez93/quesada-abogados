from pathlib import Path
from urllib.request import urlopen

import pytest

from backend.services.twin_local_runtime_service import (
    TwinLocalRuntimeService,
)


def _revision(
    root,
    twin_key="mercurio",
    revision_id="matrev-test001",
):
    revision = (
        Path(root)
        / twin_key
        / revision_id
    )

    runtime = (
        revision
        / "runtime"
    )

    state = (
        revision
        / "states"
        / "01-EX01_PERSONAL"
        / "runtime"
    )

    runtime.mkdir(
        parents=True
    )

    state.mkdir(
        parents=True
    )

    (
        runtime
        / "index.html"
    ).write_text(
        (
            '<html><body>'
            '<a href="../states/'
            '01-EX01_PERSONAL/'
            'runtime/index.html">'
            'EX01_PERSONAL'
            '</a>'
            '</body></html>'
        ),
        encoding="utf-8",
    )

    (
        state
        / "index.html"
    ).write_text(
        "<html>PERSONAL</html>",
        encoding="utf-8",
    )

    return revision


def test_runtime_serves_exact_materialized_revision(
    tmp_path,
):
    _revision(
        tmp_path
    )

    service = (
        TwinLocalRuntimeService(
            materialized_root=tmp_path
        )
    )

    runtime = service.start(
        twin_key="mercurio",
        revision_id="matrev-test001",
    )

    try:
        assert (
            runtime[
                "status"
            ]
            == "RUNNING"
        )

        assert (
            runtime[
                "host"
            ]
            == "127.0.0.1"
        )

        with urlopen(
            runtime[
                "url"
            ],
            timeout=2,
        ) as response:
            content = response.read()

        assert (
            b"EX01_PERSONAL"
            in content
        )

        state_url = (
            runtime[
                "base_url"
            ]
            + "/states/"
            + "01-EX01_PERSONAL/"
            + "runtime/index.html"
        )

        with urlopen(
            state_url,
            timeout=2,
        ) as response:
            content = response.read()

        assert (
            b"PERSONAL"
            in content
        )

    finally:
        service.stop_all()


def test_start_is_idempotent_for_same_revision(
    tmp_path,
):
    _revision(
        tmp_path
    )

    service = (
        TwinLocalRuntimeService(
            materialized_root=tmp_path
        )
    )

    try:
        first = service.start(
            twin_key="mercurio",
            revision_id="matrev-test001",
        )

        second = service.start(
            twin_key="mercurio",
            revision_id="matrev-test001",
        )

        assert (
            first[
                "port"
            ]
            == second[
                "port"
            ]
        )

    finally:
        service.stop_all()


def test_stop_closes_runtime_state(
    tmp_path,
):
    _revision(
        tmp_path
    )

    service = (
        TwinLocalRuntimeService(
            materialized_root=tmp_path
        )
    )

    service.start(
        twin_key="mercurio",
        revision_id="matrev-test001",
    )

    result = service.stop(
        twin_key="mercurio"
    )

    assert (
        result[
            "status"
        ]
        == "STOPPED"
    )

    assert (
        service.get_status(
            twin_key="mercurio"
        )[
            "status"
        ]
        == "STOPPED"
    )


@pytest.mark.parametrize(
    "value",
    (
        "../mercurio",
        "..",
        "/absolute",
        "mercurio/other",
    ),
)
def test_runtime_rejects_unsafe_identity(
    tmp_path,
    value,
):
    service = (
        TwinLocalRuntimeService(
            materialized_root=tmp_path
        )
    )

    with pytest.raises(
        ValueError
    ):
        service.get_status(
            twin_key=value
        )


def test_runtime_rejects_non_loopback_binding(
    tmp_path,
):
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_LOCAL_RUNTIME_HOST_REJECTED"
        ),
    ):
        TwinLocalRuntimeService(
            materialized_root=tmp_path,
            host="0.0.0.0",
        )
