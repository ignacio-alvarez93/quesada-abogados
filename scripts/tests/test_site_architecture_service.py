import json

from backend.automation.site_architecture import (
    persist_site_architecture_from_raw,
)


def _raw_payload():
    return {
        "schema_version": 1,
        "captured_at":
            "2026-08-22T21:00:00",
        "metadata": {
            "url":
                "https://example.test/form",
            "origin":
                "https://example.test",
            "pathname":
                "/form",
            "title":
                "Test form",
            "ready_state":
                "complete",
        },
        "viewport": {},
        "counts": {},
        "documents": [],
        "elements": [],
        "frames": [],
        "shadows": [],
    }


def test_raw_capture_can_be_persisted_as_site_architecture(
    tmp_path,
):
    result = (
        persist_site_architecture_from_raw(
            _raw_payload(),
            tmp_path,
        )
    )

    path = result["snapshot_path"]

    assert path.name == (
        "site_architecture.json"
    )

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    assert payload["schema_version"] == 1
    assert (
        payload["page"]["pathname"]
        == "/form"
    )


def test_capture_pipeline_does_not_expose_raw_payload(
    monkeypatch,
    tmp_path,
):
    from backend.automation.site_architecture import (
        service,
    )

    capture_dir = (
        tmp_path
        / "capture"
    )
    capture_dir.mkdir()

    calls = []

    def fake_capture(
        browser,
        output_root,
        *,
        label,
        timestamp,
        include_payload,
    ):
        calls.append(
            include_payload
        )

        return {
            "capture_dir":
                capture_dir,
            "inventory_path":
                capture_dir
                / "dom_inventory.json",
            "metadata_path":
                capture_dir
                / "metadata.json",
            "page_path":
                capture_dir
                / "page.html",
            "counts":
                {},
            "url":
                "https://example.test/form",
            "title":
                "Test form",
            "raw_payload":
                _raw_payload(),
        }

    monkeypatch.setattr(
        service,
        "capture_dom_snapshot",
        fake_capture,
    )

    result = service.capture_site_architecture(
        object(),
        tmp_path,
    )

    assert calls == [True]
    assert "raw_payload" not in result
    assert result["snapshot_path"].exists()
