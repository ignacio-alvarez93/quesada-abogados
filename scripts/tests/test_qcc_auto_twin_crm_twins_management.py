from pathlib import Path
import json

from backend.qcc.auto_twin.materialized_revision import (
    AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL,
    build_auto_twin_materialized_revision,
)

from backend.qcc.auto_twin.materialized_revision_store import (
    AutoTwinMaterializedRevisionStore,
)

from backend.services.twin_management_service import (
    TwinManagementService,
)


HASH_A = "a" * 64
HASH_B = "b" * 64


def _install_revision(
    root,
):
    store = (
        AutoTwinMaterializedRevisionStore(
            root=root
        )
    )

    record = (
        build_auto_twin_materialized_revision(
            twin_key="mercurio",

            materialization_mode=(
                AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL
            ),

            source_capture_ids=[
                "capture-1",
            ],

            candidate_refs=[],

            state_manifest=[
                {
                    "state_id":
                        "EX01_PERSONAL",

                    "source_capture_id":
                        "capture-1",

                    "pathname":
                        (
                            "/mercurio/"
                            "nuevaSolicitud-EX01.html"
                        ),

                    "functional_state":
                        "EX01_PERSONAL",
                },
            ],

            artifact_manifest=[
                {
                    "path":
                        (
                            "states/01-EX01_PERSONAL/"
                            "runtime/index.html"
                        ),

                    "kind":
                        "RUNTIME",

                    "sha256":
                        HASH_A,

                    "size_bytes":
                        1,
                },
            ],

            content_sha256=(
                HASH_B
            ),
        )
    )

    saved = store.save(
        record
    )

    revision_dir = (
        Path(root)
        / "mercurio"
        / saved[
            "materialized_revision_id"
        ]
    )

    runtime = (
        revision_dir
        / "runtime"
    )

    runtime.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        runtime
        / "registry.json"
    ).write_text(
        json.dumps({
            "procedure_code":
                "EX01",

            "flow_variant":
                "TITULAR",

            "states": [
                {
                    "state_id":
                        "EX01_PERSONAL",
                }
            ],
        }),
        encoding="utf-8",
    )

    (
        runtime
        / "index.html"
    ).write_text(
        "<html></html>",
        encoding="utf-8",
    )

    return saved


def test_dashboard_projects_materialized_mercurio(
    tmp_path,
):
    saved = _install_revision(
        tmp_path
    )

    service = (
        TwinManagementService(
            materialized_root=tmp_path
        )
    )

    snapshot = (
        service.get_dashboard_snapshot()
    )

    mercurio = snapshot[
        "twins"
    ][0]

    assert (
        mercurio[
            "twin_key"
        ]
        == "mercurio"
    )

    assert (
        mercurio[
            "status"
        ]
        == "MATERIALIZED"
    )

    assert (
        mercurio[
            "revision_id"
        ]
        == saved[
            "materialized_revision_id"
        ]
    )

    assert (
        mercurio[
            "state_count"
        ]
        == 1
    )

    assert (
        mercurio[
            "procedure_code"
        ]
        == "EX01"
    )

    assert (
        mercurio[
            "flow_variant"
        ]
        == "TITULAR"
    )

    assert (
        mercurio[
            "discovery_profile_key"
        ]
        == "twin_discovery"
    )

    assert (
        mercurio[
            "localhost_status"
        ]
        == "STOPPED"
    )


def test_dashboard_distinguishes_enabled_empty_and_future_twins(
    tmp_path,
):
    service = (
        TwinManagementService(
            materialized_root=tmp_path
        )
    )

    twins = (
        service.get_dashboard_snapshot()[
            "twins"
        ]
    )

    assert [
        item[
            "site_code"
        ]
        for item
        in twins
    ] == [
        "MERCURIO",
        "RED_SARA",
        "DEHU",
        "NACIONALIDAD",
    ]

    status_by_site = {
        item[
            "site_code"
        ]:
            item[
                "status"
            ]
        for item
        in twins
    }

    assert status_by_site == {
        "MERCURIO":
            "EMPTY",

        "RED_SARA":
            "EMPTY",

        "DEHU":
            "PLANNED",

        "NACIONALIDAD":
            "PLANNED",
    }


def test_dashboard_summary_is_provider_neutral(
    tmp_path,
):
    _install_revision(
        tmp_path
    )

    summary = (
        TwinManagementService(
            materialized_root=tmp_path
        )
        .get_dashboard_snapshot()[
            "summary"
        ]
    )

    assert (
        summary[
            "total_twins"
        ]
        == 4
    )

    assert (
        summary[
            "materialized_twins"
        ]
        == 1
    )

    assert (
        summary[
            "known_states"
        ]
        == 1
    )


def test_frontend_twins_view_does_not_scan_auto_twin_filesystem():
    source = Path(
        "frontend/views/twins_view.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "data/qcc"
        not in source
    )

    assert (
        "AutoTwinMaterializedRevisionStore"
        not in source
    )

    assert (
        "Path("
        not in source
    )


def test_sidebar_renames_legacy_mercurio_selenium_surface():
    source = Path(
        "frontend/layouts/sidebar.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        '("Twins", "🧬")'
        in source
    )

    assert (
        '("Mercurio / Selenium", "🤖")'
        not in source
    )

    active_section = source[
        source.index(
            "KNOWN_ACTIVE_VIEWS"
        ):
        source.index(
            "def sidebar_menu"
        )
    ]

    assert (
        '"Twins"'
        in active_section
    )


def test_app_main_routes_twins_view():
    source = Path(
        "app/main.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "from frontend.views.twins_view "
        "import twins_view"
        in source
    )

    assert (
        '== "Twins"'
        in source
    )

    assert (
        "content = twins_view(page)"
        in source
    )



class FakeTwinBrowserRuntime:
    def __init__(self):
        self.starts = []
        self.stops = []

    def get_status(
        self,
        *,
        twin_key,
    ):
        return {
            "twin_key": twin_key,
            "status": "STOPPED",
            "revision_id": None,
            "pathname": None,
            "url": None,
            "profile_key":
                "twin_runtime_" + twin_key,
            "profile_dir":
                "/tmp/twin_runtime_" + twin_key,
            "browser_session_mode":
                "PERSISTENT",
            "qcc_registered":
                False,
            "owner_thread_alive":
                False,
            "last_error":
                None,
        }

    def start(
        self,
        *,
        twin_key,
        revision_id,
        pathname=None,
    ):
        self.starts.append({
            "twin_key":
                twin_key,
            "revision_id":
                revision_id,
            "pathname":
                pathname,
        })

        return {
            "twin_key":
                twin_key,
            "status":
                "RUNNING",
            "revision_id":
                revision_id,
            "pathname":
                pathname,
            "url":
                "http://127.0.0.1:45678/",
            "profile_key":
                "twin_runtime_" + twin_key,
            "profile_dir":
                "/tmp/twin_runtime_" + twin_key,
            "browser_session_mode":
                "PERSISTENT",
            "qcc_registered":
                True,
            "owner_thread_alive":
                True,
            "last_error":
                None,
        }

    def stop(
        self,
        *,
        twin_key,
    ):
        self.stops.append(
            twin_key
        )

        return {
            "twin_key":
                twin_key,
            "status":
                "STOPPED",
            "profile_key":
                "twin_runtime_" + twin_key,
            "browser_session_mode":
                "PERSISTENT",
            "qcc_registered":
                False,
            "owner_thread_alive":
                False,
        }


def test_management_opens_twin_through_governed_browser_runtime(
    tmp_path,
):
    saved = _install_revision(
        tmp_path
    )

    browser = FakeTwinBrowserRuntime()

    service = TwinManagementService(
        materialized_root=tmp_path,
        browser_runtime_service=browser,
    )

    result = service.start_twin_browser(
        "mercurio"
    )

    assert result[
        "status"
    ] == "RUNNING"

    assert result[
        "profile_key"
    ] == "twin_runtime_mercurio"

    assert browser.starts == [
        {
            "twin_key":
                "mercurio",
            "revision_id":
                saved[
                    "materialized_revision_id"
                ],
            "pathname":
                None,
        }
    ]


def test_management_stops_governed_twin_browser(
    tmp_path,
):
    _install_revision(
        tmp_path
    )

    browser = FakeTwinBrowserRuntime()

    service = TwinManagementService(
        materialized_root=tmp_path,
        browser_runtime_service=browser,
    )

    service.stop_twin_browser(
        "mercurio"
    )

    assert browser.stops == [
        "mercurio"
    ]


def test_frontend_never_opens_twin_in_normal_browser():
    source = Path(
        "frontend/views/twins_view.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "ft.UrlLauncher"
        not in source
    )

    assert (
        ".launch_url("
        not in source
    )

    assert (
        "service.start_twin_browser("
        in source
    )

    assert (
        "service.stop_twin_browser("
        in source
    )

    assert (
        "Abrir Twin SeleniumBase"
        in source
    )
