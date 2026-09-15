import json
from urllib.error import HTTPError
from urllib.request import (
    Request,
    urlopen,
)

from backend.qcc.bridge.server import (
    QccBridgeServer,
)
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
)
from backend.qcc.site_architecture import (
    QccSiteArchitectureIngestor,
)


def _capture(
    *,
    pathname="/form",
):
    frame = {
        "schema_version": 1,
        "captured_at":
            "2026-09-02T08:00:00Z",
        "url":
            (
                "https://example.test"
                + pathname
            ),
        "origin":
            "https://example.test",
        "pathname":
            pathname,
        "hostname":
            "example.test",
        "title":
            "Página prueba",
        "ready_state":
            "complete",
        "content_type":
            "text/html",
        "character_set":
            "UTF-8",
        "html":
            "<html><body></body></html>",
        "counts": {
            "elements": 0,
        },
        "elements": [],
        "shadow_roots": [],
    }

    return {
        "ok":
            True,
        "capture_type":
            "QCC_EXTENSION_DOM_CAPTURE",
        "schema_version":
            1,
        "captured_at":
            "2026-09-02T08:00:00Z",
        "tab_id":
            9,
        "captured_frames":
            1,
        "frames": [{
            "frame_id":
                0,
            "document_id":
                "same-document",
            "result":
                frame,
        }],
    }


def _post_observe(
    base,
    capture,
    *,
    baseline_capture_id=None,
):
    payload = {
        "protocol_version":
            QCC_PROTOCOL_VERSION,
        "capture":
            capture,
    }

    if baseline_capture_id is not None:
        payload[
            "baseline_capture_id"
        ] = baseline_capture_id

    body = json.dumps(
        payload
    ).encode(
        "utf-8"
    )

    request = Request(
        (
            base
            + "/qcc/site-architecture/observe"
        ),
        data=body,
        headers={
            "Content-Type":
                "application/json",
        },
        method="POST",
    )

    try:
        response = urlopen(
            request,
            timeout=2,
        )

    except HTTPError as exc:
        return (
            exc.code,
            json.loads(
                exc.read().decode(
                    "utf-8"
                )
            ),
        )

    with response:
        return (
            response.status,
            json.loads(
                response.read().decode(
                    "utf-8"
                )
            ),
        )


def test_observe_candidate_is_memory_only(
    tmp_path,
):
    ingestor = QccSiteArchitectureIngestor(
        output_root=tmp_path,
    )

    result = ingestor.observe_candidate(
        _capture()
    )

    assert len(
        result["fingerprint"]
    ) == 64

    assert (
        result["state_observation"][
            "fingerprint"
        ]
        == result["fingerprint"]
    )

    assert list(
        tmp_path.iterdir()
    ) == []


def test_observe_candidate_has_no_capture_id(
    tmp_path,
):
    ingestor = QccSiteArchitectureIngestor(
        output_root=tmp_path,
    )

    result = ingestor.observe_candidate(
        _capture()
    )

    assert (
        "capture_id"
        not in result
    )


def test_observe_and_ingest_use_same_canonical_fingerprint(
    tmp_path,
):
    ingestor = QccSiteArchitectureIngestor(
        output_root=tmp_path,
    )

    capture = _capture()

    observed = (
        ingestor.observe_candidate(
            capture
        )
    )

    assert list(
        tmp_path.iterdir()
    ) == []

    ingested = ingestor.ingest(
        capture
    )

    assert (
        observed["fingerprint"]
        == ingested[
            "state_observation"
        ][
            "fingerprint"
        ]
    )


def test_observe_gate_detects_canonical_page_change(
    tmp_path,
):
    ingestor = QccSiteArchitectureIngestor(
        output_root=tmp_path,
    )

    before = ingestor.observe_candidate(
        _capture(
            pathname="/form-a"
        )
    )

    after = ingestor.observe_candidate(
        _capture(
            pathname="/form-b"
        )
    )

    assert (
        before["fingerprint"]
        != after["fingerprint"]
    )

    assert list(
        tmp_path.iterdir()
    ) == []


def test_bridge_observe_is_non_persistent(
    tmp_path,
):
    ingestor = QccSiteArchitectureIngestor(
        output_root=tmp_path,
    )

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            ingestor
        ),
    )

    bridge.start()

    try:
        base = (
            f"http://{bridge.host}:"
            f"{bridge.port}"
        )

        status, payload = (
            _post_observe(
                base,
                _capture(),
            )
        )

        assert status == 200
        assert payload["ok"] is True

        assert (
            payload["persisted"]
            is False
        )

        assert len(
            payload["fingerprint"]
        ) == 64

        assert (
            "capture_id"
            not in payload
        )

        assert list(
            tmp_path.iterdir()
        ) == []

    finally:
        bridge.close()


def test_bridge_observe_fingerprint_matches_ingest(
    tmp_path,
):
    ingestor = QccSiteArchitectureIngestor(
        output_root=tmp_path,
    )

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            ingestor
        ),
    )

    bridge.start()

    try:
        base = (
            f"http://{bridge.host}:"
            f"{bridge.port}"
        )

        capture = _capture()

        status, payload = (
            _post_observe(
                base,
                capture,
            )
        )

        assert status == 200

        assert list(
            tmp_path.iterdir()
        ) == []

        ingested = ingestor.ingest(
            capture
        )

        assert (
            payload["fingerprint"]
            == ingested[
                "state_observation"
            ][
                "fingerprint"
            ]
        )

    finally:
        bridge.close()



def test_bridge_observe_backend_dedupes_against_persisted_capture(
    tmp_path,
):
    ingestor = QccSiteArchitectureIngestor(
        output_root=tmp_path,
    )

    baseline_capture = _capture()

    baseline = ingestor.ingest(
        baseline_capture
    )

    baseline_id = (
        baseline["capture_id"]
    )

    baseline_count = len(
        list(
            tmp_path.iterdir()
        )
    )

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            ingestor
        ),
    )

    bridge.start()

    try:
        base = (
            f"http://{bridge.host}:"
            f"{bridge.port}"
        )

        status, payload = (
            _post_observe(
                base,
                _capture(),
                baseline_capture_id=(
                    baseline_id
                ),
            )
        )

        assert status == 200
        assert payload["ok"] is True

        assert (
            payload[
                "baseline_capture_id"
            ]
            == baseline_id
        )

        assert (
            payload[
                "baseline_fingerprint"
            ]
            == baseline[
                "state_observation"
            ][
                "fingerprint"
            ]
        )

        assert (
            payload["changed"]
            is False
        )

        assert len(
            list(
                tmp_path.iterdir()
            )
        ) == baseline_count

    finally:
        bridge.close()


def test_bridge_observe_backend_detects_changed_persisted_state(
    tmp_path,
):
    ingestor = QccSiteArchitectureIngestor(
        output_root=tmp_path,
    )

    baseline = ingestor.ingest(
        _capture(
            pathname="/form-a"
        )
    )

    baseline_id = (
        baseline["capture_id"]
    )

    baseline_count = len(
        list(
            tmp_path.iterdir()
        )
    )

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            ingestor
        ),
    )

    bridge.start()

    try:
        base = (
            f"http://{bridge.host}:"
            f"{bridge.port}"
        )

        status, payload = (
            _post_observe(
                base,
                _capture(
                    pathname="/form-b"
                ),
                baseline_capture_id=(
                    baseline_id
                ),
            )
        )

        assert status == 200

        assert (
            payload["changed"]
            is True
        )

        assert (
            payload["fingerprint"]
            != payload[
                "baseline_fingerprint"
            ]
        )

        # /observe sigue siendo memory-only.
        assert len(
            list(
                tmp_path.iterdir()
            )
        ) == baseline_count

    finally:
        bridge.close()
