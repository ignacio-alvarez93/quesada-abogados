import json

from backend.qcc.auto_twin.automatic_materialization import (
    _navigation_runtime_refresh_required,
    _physical_renderer_refresh_required,
    _renderer_refresh_required,
)

from backend.qcc.auto_twin.materialization_builder import (
    AUTO_TWIN_RUNTIME_RENDERER_VERSION,
)

from backend.qcc.auto_twin.navigation_transition_runtime import (
    AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION,
    AUTO_TWIN_NAVIGATION_RUNTIME_FILENAME,
)


def _revision():
    return {
        "materialized_revision_id":
            "matrev-test",
    }


def _runtime(
    tmp_path,
    *,
    renderer_version,
    navigation_version,
):
    runtime = (
        tmp_path
        / "mercurio"
        / "matrev-test"
        / "runtime"
    )

    runtime.mkdir(
        parents=True,
    )

    (
        runtime
        / "renderer.json"
    ).write_text(
        json.dumps({
            "renderer_version":
                renderer_version,
        }),
        encoding="utf-8",
    )

    (
        runtime
        / AUTO_TWIN_NAVIGATION_RUNTIME_FILENAME
    ).write_text(
        json.dumps({
            "adapter_version":
                navigation_version,
        }),
        encoding="utf-8",
    )


def test_current_renderer_and_navigation_need_no_refresh(
    tmp_path,
):
    _runtime(
        tmp_path,
        renderer_version=(
            AUTO_TWIN_RUNTIME_RENDERER_VERSION
        ),
        navigation_version=(
            AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION
        ),
    )

    revision = _revision()

    assert not _physical_renderer_refresh_required(
        materialized_root=tmp_path,
        twin_key="mercurio",
        revision=revision,
    )

    assert not _navigation_runtime_refresh_required(
        materialized_root=tmp_path,
        twin_key="mercurio",
        revision=revision,
    )

    assert not _renderer_refresh_required(
        materialized_root=tmp_path,
        twin_key="mercurio",
        revision=revision,
    )


def test_stale_navigation_does_not_make_renderer_physical_stale(
    tmp_path,
):
    _runtime(
        tmp_path,
        renderer_version=(
            AUTO_TWIN_RUNTIME_RENDERER_VERSION
        ),
        navigation_version=(
            AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION
            - 1
        ),
    )

    revision = _revision()

    assert not _physical_renderer_refresh_required(
        materialized_root=tmp_path,
        twin_key="mercurio",
        revision=revision,
    )

    assert _navigation_runtime_refresh_required(
        materialized_root=tmp_path,
        twin_key="mercurio",
        revision=revision,
    )

    assert _renderer_refresh_required(
        materialized_root=tmp_path,
        twin_key="mercurio",
        revision=revision,
    )


def test_stale_renderer_remains_physical_refresh(
    tmp_path,
):
    _runtime(
        tmp_path,
        renderer_version=(
            AUTO_TWIN_RUNTIME_RENDERER_VERSION
            - 1
        ),
        navigation_version=(
            AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION
        ),
    )

    revision = _revision()

    assert _physical_renderer_refresh_required(
        materialized_root=tmp_path,
        twin_key="mercurio",
        revision=revision,
    )

    assert not _navigation_runtime_refresh_required(
        materialized_root=tmp_path,
        twin_key="mercurio",
        revision=revision,
    )

    assert _renderer_refresh_required(
        materialized_root=tmp_path,
        twin_key="mercurio",
        revision=revision,
    )
