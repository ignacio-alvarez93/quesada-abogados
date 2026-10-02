"""Governed SeleniumBase E2E for UWT-6A2 form runtime hydration.

Local Twin only. No REAL navigation, no REAL capture. Serves a
synthetic materialized revision through ``TwinLocalRuntimeService``
and drives it with a real governed SeleniumBase browser
(``SeleniumBaseBrowserSession``), exactly as production would.

If this environment cannot launch a governed SeleniumBase/Chrome
session, the test is explicitly skipped with a BLOCKED reason rather
than silently reporting success.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.automation.browser_contracts import (
    BrowserSessionConfig,
    BrowserSessionMode,
    BrowserShutdownMode,
)
from backend.automation.seleniumbase_browser_session import (
    SeleniumBaseBrowserSession,
)
from backend.services.twin_form_runtime_service import (
    TwinFormRuntimeService,
)
from backend.services.twin_local_runtime_service import (
    TwinLocalRuntimeService,
)


TWIN_KEY = "uwt6a2-synthetic-twin"
REVISION_ID = "matrev-uwt6a2-001"
STATE_ID = "SYNTHETIC_FORM_MAIN"
SOURCE_CAPTURE_ID = "cap-uwt6a2-001"


_TWIN_HTML = """<!DOCTYPE html>
<html>
<body>
  <form>
    <input id="full_name" name="full_name" type="text">
    <input id="csrf" name="csrf" type="hidden" value="LIVE_TOKEN_1">
    <select id="province" name="province">
      <option value="28">Madrid</option>
      <option value="08" selected>Barcelona</option>
    </select>
    <input id="accept" name="accept" type="checkbox" value="yes">
    <input name="choice" type="radio" value="A">
    <input name="choice" type="radio" value="B">
    <input id="attachment" name="attachment" type="file">
    <button id="continue_button" type="button"
            onclick="document.getElementById('result').textContent='DONE';">
      Continue
    </button>
    <div id="result"></div>
  </form>
</body>
</html>
"""


def _raw_qcc_capture():
    return {
        "capture_type": "QCC_EXTENSION_DOM_CAPTURE",
        "schema_version": 1,
        "captured_at": "2026-10-02T10:00:00.000Z",
        "frames": [
            {
                "frame_id": 0,
                "document_id": "doc-main",
                "result": {
                    "schema_version": 1,
                    "url": "https://example.test/synthetic-form",
                    "title": "Synthetic Form",
                    "ready_state": "complete",
                    "content_type": "text/html",
                    "character_set": "UTF-8",
                    "viewport": {
                        "inner_width": 1280,
                        "inner_height": 800,
                        "device_pixel_ratio": 1,
                        "scroll_x": 0,
                        "scroll_y": 0,
                    },
                    "counts": {},
                    "elements": [
                        {
                            "index": 0,
                            "frame_path": "main",
                            "tag": "input",
                            "id": "full_name",
                            "name": "full_name",
                            "type": "text",
                            "role": "",
                            "attributes": {
                                "id": "full_name",
                                "name": "full_name",
                                "type": "text",
                                "required": "",
                            },
                            "form_signals": {
                                "has_value": True,
                            },
                            "visible": True,
                            "disabled": False,
                        },
                        {
                            "index": 1,
                            "frame_path": "main",
                            "tag": "input",
                            "id": "csrf",
                            "name": "csrf",
                            "type": "hidden",
                            "attributes": {
                                "id": "csrf",
                                "name": "csrf",
                                "type": "hidden",
                            },
                            "form_signals": {
                                "has_value": True,
                            },
                        },
                        {
                            "index": 2,
                            "frame_path": "main",
                            "tag": "select",
                            "id": "province",
                            "name": "province",
                            "type": "",
                            "attributes": {
                                "id": "province",
                                "name": "province",
                            },
                            "options": [
                                {
                                    "value": "28",
                                    "text": "Madrid",
                                    "selected": True,
                                },
                                {
                                    "value": "08",
                                    "text": "Barcelona",
                                    "selected": False,
                                },
                            ],
                        },
                        {
                            "index": 3,
                            "frame_path": "main",
                            "tag": "input",
                            "id": "accept",
                            "name": "accept",
                            "type": "checkbox",
                            "attributes": {
                                "id": "accept",
                                "name": "accept",
                                "type": "checkbox",
                                "value": "yes",
                            },
                            "checked": True,
                        },
                        {
                            "index": 4,
                            "frame_path": "main",
                            "tag": "input",
                            "id": "",
                            "name": "choice",
                            "type": "radio",
                            "attributes": {
                                "name": "choice",
                                "type": "radio",
                                "value": "A",
                            },
                            "checked": False,
                        },
                        {
                            "index": 5,
                            "frame_path": "main",
                            "tag": "input",
                            "id": "",
                            "name": "choice",
                            "type": "radio",
                            "attributes": {
                                "name": "choice",
                                "type": "radio",
                                "value": "B",
                            },
                            "checked": True,
                        },
                        {
                            "index": 6,
                            "frame_path": "main",
                            "tag": "input",
                            "id": "attachment",
                            "name": "attachment",
                            "type": "file",
                            "attributes": {
                                "id": "attachment",
                                "name": "attachment",
                                "type": "file",
                            },
                            "form_signals": {
                                "file_selected": True,
                            },
                        },
                    ],
                },
            }
        ],
    }


def _materialize_synthetic_twin(*, materialized_root, site_architecture_root):
    revision_dir = (
        Path(materialized_root)
        / TWIN_KEY
        / REVISION_ID
    )

    state_runtime_dir = (
        revision_dir
        / "states"
        / ("01-" + STATE_ID)
        / "runtime"
    )

    state_runtime_dir.mkdir(parents=True)

    twin_html_path = (
        state_runtime_dir
        / "index.html"
    )

    twin_html_path.write_text(
        _TWIN_HTML,
        encoding="utf-8",
    )

    runtime_dir = (
        revision_dir
        / "runtime"
    )

    runtime_dir.mkdir(parents=True)

    (
        runtime_dir
        / "index.html"
    ).write_text(
        "<html><body>entry</body></html>",
        encoding="utf-8",
    )

    registry = {
        "schema_version": 1,
        "twin_key": TWIN_KEY,
        "states": [
            {
                "state_id": STATE_ID,
                "source_capture_id": SOURCE_CAPTURE_ID,
                "pathname": "/synthetic-form",
                "functional_state": "SYNTHETIC_FORM",
                "runtime_entry": (
                    "states/"
                    + "01-"
                    + STATE_ID
                    + "/runtime/index.html"
                ),
            }
        ],
    }

    (
        runtime_dir
        / "registry.json"
    ).write_text(
        json.dumps(registry),
        encoding="utf-8",
    )

    capture_dir = (
        Path(site_architecture_root)
        / SOURCE_CAPTURE_ID
    )

    capture_dir.mkdir(parents=True)

    (
        capture_dir
        / "qcc_capture.json"
    ).write_text(
        json.dumps(_raw_qcc_capture()),
        encoding="utf-8",
    )

    return twin_html_path


def test_governed_form_runtime_hydration_e2e(tmp_path):
    materialized_root = tmp_path / "materialized"
    site_architecture_root = tmp_path / "site_architecture"

    twin_html_path = _materialize_synthetic_twin(
        materialized_root=materialized_root,
        site_architecture_root=site_architecture_root,
    )

    original_html_bytes = (
        twin_html_path.read_bytes()
    )

    local_runtime = TwinLocalRuntimeService(
        materialized_root=materialized_root
    )

    service = TwinFormRuntimeService(
        materialized_root=materialized_root,
        site_architecture_root=site_architecture_root,
    )

    plan = service.load_hydration_plan(
        twin_key=TWIN_KEY,
        revision_id=REVISION_ID,
        state_id=STATE_ID,
    )

    assert plan["frame_scope"] == "MAIN"
    assert plan["operation_count"] == 7
    assert plan["unsupported_frame_control_count"] == 0

    for operation in plan["operations"]:
        assert operation["addressable"] is True

    text_control_key = next(
        operation["control_key"]
        for operation in plan["operations"]
        if operation["kind"] == "TEXT"
    )

    file_control_key = next(
        operation["control_key"]
        for operation in plan["operations"]
        if operation["kind"] == "FILE"
    )

    synthetic_file = tmp_path / "synthetic_attachment.txt"
    synthetic_file.write_text(
        "synthetic content",
        encoding="utf-8",
    )

    runtime_status = local_runtime.start(
        twin_key=TWIN_KEY,
        revision_id=REVISION_ID,
    )

    state_url = (
        runtime_status["base_url"]
        + "/states/"
        + "01-"
        + STATE_ID
        + "/runtime/index.html"
    )

    config = BrowserSessionConfig(
        consumer="qcc_uwt6a2_form_runtime_e2e",
        mode=BrowserSessionMode.EPHEMERAL,
        headless=True,
    )

    session = SeleniumBaseBrowserSession(config=config)

    try:
        browser = session.start()

    except Exception as exc:
        local_runtime.stop_all()

        pytest.skip(
            "SELENIUMBASE_E2E_BLOCKED:"
            + f" {type(exc).__name__}: {exc}"
        )

        return

    try:
        browser.get(state_url)

        result = service.apply_hydration_plan(
            browser=browser,
            plan=plan,
            runtime_values={
                text_control_key: "Maria Lopez",
                file_control_key: str(synthetic_file),
            },
            state_id=STATE_ID,
        )

        assert result["operations_total"] == 7
        assert result["errors"] == ()
        assert result["unresolved"] == ()

        # full_name(TEXT) + province(SELECT) + accept(CHECKBOX)
        # + choice=B(RADIO) + attachment(FILE) are actually acted
        # upon. csrf(HIDDEN, no override supplied) and choice=A
        # (RADIO, captured unchecked) correctly receive no action.
        assert result["operations_applied"] == 5
        assert result["captured_state_restored"] == 3
        assert result["runtime_values_applied"] == 2

        # No secret/runtime literal ever appears in structured evidence.
        serialized_result = json.dumps(result, default=str)
        assert "Maria Lopez" not in serialized_result
        assert str(synthetic_file) not in serialized_result

        # SELENIUM_TEXT
        assert (
            browser.get_attribute("#full_name", "value")
            == "Maria Lopez"
        )

        # FORM_CONSTRAINT_AUDIT: constraint lost by the Twin render
        # is restored generically (no provider-specific JS).
        assert (
            browser.get_attribute("#full_name", "required")
        )

        # SELENIUM_SELECT / CAPTURED_SELECTION_RESTORED
        assert (
            browser.evaluate(
                "document.querySelector('#province').value"
            )
            == "28"
        )

        # SELENIUM_CHECKBOX / CAPTURED_CHECKED_RESTORED
        assert browser.is_checked("#accept") is True

        # SELENIUM_RADIO / CAPTURED_CHECKED_RESTORED
        assert (
            browser.is_checked(
                '[name="choice"][value="B"]'
            )
            is True
        )
        assert (
            browser.is_checked(
                '[name="choice"][value="A"]'
            )
            is False
        )

        # HIDDEN input preserved (no runtime override supplied).
        assert (
            browser.get_attribute("#csrf", "value")
            == "LIVE_TOKEN_1"
        )

        # SELENIUM_FILE_INTERFACE
        assert (
            browser.evaluate(
                "document.querySelector('#attachment')"
                ".files.length"
            )
            == 1
        )
        assert (
            browser.evaluate(
                "document.querySelector('#attachment')"
                ".files[0].name"
            )
            == synthetic_file.name
        )

        # RUNTIME_VALUES_PERSISTED=NO: the served materialized file
        # on disk is untouched by hydration; only the live browser
        # DOM was mutated.
        assert (
            twin_html_path.read_bytes()
            == original_html_bytes
        )

        # CONTINUE_EXPLICIT_ACTION / RESULTING_SURFACE: hydration never
        # clicks Continue itself; the caller does, explicitly.
        assert (
            browser.evaluate(
                "document.getElementById('result').textContent"
            )
            == ""
        )

        browser.click("#continue_button")

        assert (
            browser.evaluate(
                "document.getElementById('result').textContent"
            )
            == "DONE"
        )

    finally:
        session.shutdown(BrowserShutdownMode.CLOSE)
        local_runtime.stop_all()
