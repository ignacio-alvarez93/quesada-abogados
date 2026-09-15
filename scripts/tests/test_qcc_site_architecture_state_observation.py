import json

from backend.qcc.bridge.server import (
    QccBridgeServer,
)
from backend.qcc.site_architecture import (
    QccSiteArchitectureIngestor,
)
from backend.automation.site_policies.mercurio import (
    MERCURIO_LAB_ORIGIN,
    MERCURIO_REAL_ORIGIN,
)
from tools.mercurio_lab.core.routes import (
    MERCURIO_INICIO_PATH,
)


def _capture(
    *,
    origin,
    pathname,
):
    return {
        "ok":
            True,

        "capture_type":
            "QCC_EXTENSION_DOM_CAPTURE",

        "schema_version":
            1,

        "captured_at":
            "2026-08-26T10:00:00Z",

        "frames": [
            {
                "frame_id":
                    0,

                "document_id":
                    "main",

                "result": {
                    "schema_version":
                        1,

                    "captured_at":
                        "2026-08-26T10:00:00Z",

                    "url":
                        origin
                        + pathname,

                    "origin":
                        origin,

                    "pathname":
                        pathname,

                    "title":
                        "Test",

                    "ready_state":
                        "complete",

                    "content_type":
                        "text/html",

                    "character_set":
                        "UTF-8",

                    "html":
                        "<html></html>",

                    "counts": {
                        "elements":
                            0,
                    },

                    "elements":
                        [],

                    "shadow_roots":
                        [],
                },
            },
        ],
    }


def _post_capture(
    base,
    capture,
):
    import json
    from urllib.request import (
        Request,
        urlopen,
    )

    request = Request(
        (
            base
            + "/qcc/site-architecture/capture"
        ),
        data=json.dumps(
            {
                "protocol_version":
                    1,

                "capture":
                    capture,
            }
        ).encode(
            "utf-8"
        ),
        headers={
            "Content-Type":
                "application/json",
        },
        method="POST",
    )

    with urlopen(
        request,
        timeout=2,
    ) as response:
        return (
            response.status,
            json.loads(
                response.read().decode(
                    "utf-8"
                )
            ),
        )


def test_ingestor_recognizes_mercurio_real(
    tmp_path,
):
    ingestor = (
        QccSiteArchitectureIngestor(
            output_root=tmp_path,
        )
    )

    result = ingestor.ingest(
        _capture(
            origin=(
                MERCURIO_REAL_ORIGIN
            ),
            pathname=(
                MERCURIO_INICIO_PATH
            ),
        )
    )

    assert (
        result["site_code"]
        == "MERCURIO"
    )

    observation = (
        result[
            "state_observation"
        ]
    )

    assert (
        observation[
            "recognition_status"
        ]
        == "RECOGNIZED"
    )

    assert (
        observation["state"]
        == "MERCURIO_INICIO"
    )

    assert (
        len(
            observation[
                "fingerprint"
            ]
        )
        == 64
    )


def test_ingestor_recognizes_same_state_in_lab(
    tmp_path,
):
    ingestor = (
        QccSiteArchitectureIngestor(
            output_root=tmp_path,
        )
    )

    result = ingestor.ingest(
        _capture(
            origin=(
                MERCURIO_LAB_ORIGIN
            ),
            pathname=(
                MERCURIO_INICIO_PATH
            ),
        )
    )

    assert (
        result["site_code"]
        == "MERCURIO"
    )

    assert (
        result[
            "state_observation"
        ][
            "state"
        ]
        == "MERCURIO_INICIO"
    )


def test_unknown_site_still_gets_fingerprint(
    tmp_path,
):
    ingestor = (
        QccSiteArchitectureIngestor(
            output_root=tmp_path,
        )
    )

    result = ingestor.ingest(
        _capture(
            origin=(
                "https://unknown.example"
            ),
            pathname="/profile",
        )
    )

    assert (
        result["site_code"]
        is None
    )

    observation = (
        result[
            "state_observation"
        ]
    )

    assert (
        observation[
            "recognition_status"
        ]
        == "UNRECOGNIZED"
    )

    assert (
        observation["state"]
        is None
    )

    assert (
        len(
            observation[
                "fingerprint"
            ]
        )
        == 64
    )


def test_state_observation_is_persisted_separately(
    tmp_path,
):
    ingestor = (
        QccSiteArchitectureIngestor(
            output_root=tmp_path,
        )
    )

    result = ingestor.ingest(
        _capture(
            origin=(
                MERCURIO_REAL_ORIGIN
            ),
            pathname=(
                MERCURIO_INICIO_PATH
            ),
        )
    )

    capture_dir = (
        tmp_path
        / result[
            "capture_id"
        ]
    )

    path = (
        capture_dir
        / "state_observation.json"
    )

    assert path.exists()

    persisted = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    assert (
        persisted
        == result[
            "state_observation"
        ]
    )

    assert (
        persisted["state"]
        == "MERCURIO_INICIO"
    )


def test_metadata_references_state_observation_artifact(
    tmp_path,
):
    ingestor = (
        QccSiteArchitectureIngestor(
            output_root=tmp_path,
        )
    )

    result = ingestor.ingest(
        _capture(
            origin=(
                MERCURIO_REAL_ORIGIN
            ),
            pathname=(
                MERCURIO_INICIO_PATH
            ),
        )
    )

    assert (
        result[
            "artifacts"
        ][
            "state_observation"
        ]
        == "state_observation.json"
    )


def test_bridge_returns_safe_state_observation(
    tmp_path,
):
    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            QccSiteArchitectureIngestor(
                output_root=tmp_path,
            )
        ),
    )

    bridge.start()

    try:
        base = (
            f"http://{bridge.host}:"
            f"{bridge.port}"
        )

        status, payload = (
            _post_capture(
                base,
                _capture(
                    origin=(
                        MERCURIO_REAL_ORIGIN
                    ),
                    pathname=(
                        MERCURIO_INICIO_PATH
                    ),
                ),
            )
        )

        assert status == 200

        assert (
            payload[
                "site_code"
            ]
            == "MERCURIO"
        )

        observation = (
            payload[
                "state_observation"
            ]
        )

        assert (
            observation["state"]
            == "MERCURIO_INICIO"
        )

        assert (
            observation[
                "recognition_status"
            ]
            == "RECOGNIZED"
        )

        serialized = json.dumps(
            observation
        ).lower()

        forbidden = (
            "<html",
            "cookie",
            "password",
            "certificate",
            "token",
        )

        for token in forbidden:
            assert token not in serialized

    finally:
        bridge.close()


def test_bridge_projects_matching_capture_into_live_context(
    tmp_path,
):
    from datetime import (
        datetime,
        timezone,
    )

    from backend.qcc.contracts.protocol import (
        QccPresentationSession,
        QccPresentationStatus,
    )

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            QccSiteArchitectureIngestor(
                output_root=tmp_path,
            )
        ),
    )

    bridge.start()

    try:
        bridge.context_store.set_active_session(
            QccPresentationSession(
                session_id="live-merc-1",
                expedient_id=1,
                client_id=1,
                procedure="TEST",
                provider="MERCURIO",
                runtime="TEST_RUNTIME",
                started_at=datetime.now(
                    timezone.utc
                ),
                status=(
                    QccPresentationStatus
                    .AUTOMATING
                ),
                current_step="TEST",
                progress=10,
                requires_user_action=False,
            )
        )

        base = (
            f"http://{bridge.host}:"
            f"{bridge.port}"
        )

        status, payload = (
            _post_capture(
                base,
                _capture(
                    origin=(
                        MERCURIO_REAL_ORIGIN
                    ),
                    pathname=(
                        MERCURIO_INICIO_PATH
                    ),
                ),
            )
        )

        assert status == 200

        assert (
            payload[
                "live_projection"
            ][
                "projected"
            ]
            is True
        )

        context = (
            bridge.context_store
            .snapshot()
        )

        live = (
            context[
                "live_navigation"
            ]
        )

        assert (
            live["session_id"]
            == "live-merc-1"
        )

        assert (
            live["current"]["state"]
            == "MERCURIO_INICIO"
        )

        assert (
            len(
                live[
                    "current"
                ][
                    "fingerprint"
                ]
            )
            == 64
        )

        assert (
            live["next_step"]
            is None
        )

        assert (
            live["governance"]
            is None
        )

    finally:
        bridge.close()


def test_unrelated_site_does_not_inherit_active_session(
    tmp_path,
):
    ingestor = (
        QccSiteArchitectureIngestor(
            output_root=tmp_path,
        )
    )

    result = ingestor.ingest(
        _capture(
            origin="https://youtube.example",
            pathname="/watch",
        ),
        context={
            "active": True,
            "active_session": {
                "session_id":
                    "merc-session-1",
                "provider":
                    "MERCURIO",
                "runtime":
                    "TEST_RUNTIME",
            },
        },
    )

    assert (
        result["context_mode"]
        == "MANUAL"
    )

    assert (
        result["session_id"]
        is None
    )

    assert (
        result["active_session"]
        is None
    )

    assert (
        result["session_bound"]
        is False
    )


def test_matching_site_inherits_active_session(
    tmp_path,
):
    ingestor = (
        QccSiteArchitectureIngestor(
            output_root=tmp_path,
        )
    )

    result = ingestor.ingest(
        _capture(
            origin=(
                MERCURIO_REAL_ORIGIN
            ),
            pathname=(
                MERCURIO_INICIO_PATH
            ),
        ),
        context={
            "active": True,
            "active_session": {
                "session_id":
                    "merc-session-1",
                "provider":
                    "MERCURIO",
                "runtime":
                    "TEST_RUNTIME",
            },
        },
    )

    assert (
        result["context_mode"]
        == "ASSISTED_PRESENTATION"
    )

    assert (
        result["session_id"]
        == "merc-session-1"
    )

    assert (
        result["session_bound"]
        is True
    )
