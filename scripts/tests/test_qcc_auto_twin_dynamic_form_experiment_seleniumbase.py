"""Governed SeleniumBase E2E for UWT-6B2 dynamic form experiments.

Local Twin only. No REAL navigation, no REAL capture, no REAL client
data. Serves a synthetic materialized revision through
``TwinLocalRuntimeService`` and drives it with a real governed
SeleniumBase browser (``SeleniumBaseBrowserSession``), exactly as
production would.

The synthetic Twin page contains genuine client-side JavaScript
dynamic behavior (SELECT dependency, CHECKBOX dependency, RADIO
dependency) — never anything resembling the REAL Mercurio site.

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
from backend.services.twin_dynamic_form_experiment_service import (
    ACTION_CHECKBOX,
    ACTION_RADIO,
    ACTION_SELECT,
    TwinDynamicFormExperimentService,
)
from backend.services.twin_local_runtime_service import (
    TwinLocalRuntimeService,
)


TWIN_KEY = "uwt6b2-synthetic-twin"
REVISION_ID = "matrev-uwt6b2-001"
STATE_ID = "SYNTHETIC_DYNAMIC_FORM_MAIN"

TEST_BEFORE_FINGERPRINT = "a" * 64


_TWIN_HTML = """<!DOCTYPE html>
<html>
<body>
  <form>
    <select id="province" name="province">
      <option value="28" selected>Madrid</option>
      <option value="08">Barcelona</option>
    </select>
    <select id="city" name="city"></select>
    <input id="city_required_notice" name="city_required_notice" type="text">

    <input id="accept" name="accept" type="checkbox" value="yes">
    <input id="details" name="details" type="text" disabled>

    <input id="plan-basic" name="plan" type="radio" value="basic" checked>
    <input id="plan-pro" name="plan" type="radio" value="pro">
    <input id="pro_options" name="pro_options" type="text" disabled>
  </form>
  <script>
    var CITY_OPTIONS = {
      "28": [
        {value: "madrid-centro", text: "Centro"},
        {value: "madrid-norte", text: "Norte"}
      ],
      "08": [
        {value: "bcn-eixample", text: "Eixample"}
      ]
    };

    function renderCityOptions(provinceValue) {
      var citySelect = document.getElementById("city");
      citySelect.innerHTML = "";

      (CITY_OPTIONS[provinceValue] || []).forEach(function (opt) {
        var optionEl = document.createElement("option");
        optionEl.value = opt.value;
        optionEl.textContent = opt.text;
        citySelect.appendChild(optionEl);
      });

      if (citySelect.options.length > 0) {
        citySelect.options[0].selected = true;
      }

      var noticeField = document.getElementById("city_required_notice");

      if (provinceValue === "08") {
        noticeField.setAttribute("required", "");
      } else {
        noticeField.removeAttribute("required");
      }
    }

    document.getElementById("province").addEventListener(
      "change",
      function (e) { renderCityOptions(e.target.value); }
    );

    renderCityOptions(document.getElementById("province").value);

    document.getElementById("accept").addEventListener(
      "change",
      function (e) {
        document.getElementById("details").disabled = !e.target.checked;
      }
    );

    Array.prototype.forEach.call(
      document.querySelectorAll('input[name="plan"]'),
      function (radio) {
        radio.addEventListener("change", function (e) {
          document.getElementById("pro_options").disabled = (
            e.target.value !== "pro" || !e.target.checked
          );
        });
      }
    );
  </script>
</body>
</html>
"""


def _materialize_synthetic_twin(*, materialized_root):
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

    twin_html_path = state_runtime_dir / "index.html"

    twin_html_path.write_text(_TWIN_HTML, encoding="utf-8")

    runtime_dir = revision_dir / "runtime"

    runtime_dir.mkdir(parents=True)

    (runtime_dir / "index.html").write_text(
        "<html><body>entry</body></html>",
        encoding="utf-8",
    )

    registry = {
        "schema_version": 1,
        "twin_key": TWIN_KEY,
        "states": [
            {
                "state_id": STATE_ID,
                "source_capture_id": "cap-uwt6b2-001",
                "pathname": "/synthetic-dynamic-form",
                "functional_state": "SYNTHETIC_DYNAMIC_FORM",
                "runtime_entry": (
                    "states/01-" + STATE_ID + "/runtime/index.html"
                ),
            }
        ],
    }

    (runtime_dir / "registry.json").write_text(
        json.dumps(registry),
        encoding="utf-8",
    )

    return twin_html_path


def test_governed_dynamic_form_experiments_e2e(tmp_path):
    materialized_root = tmp_path / "materialized"

    twin_html_path = _materialize_synthetic_twin(
        materialized_root=materialized_root
    )

    original_html_bytes = twin_html_path.read_bytes()

    local_runtime = TwinLocalRuntimeService(
        materialized_root=materialized_root
    )

    service = TwinDynamicFormExperimentService()

    runtime_status = local_runtime.start(
        twin_key=TWIN_KEY,
        revision_id=REVISION_ID,
    )

    state_url = (
        runtime_status["base_url"]
        + "/states/01-"
        + STATE_ID
        + "/runtime/index.html"
    )

    config = BrowserSessionConfig(
        consumer="qcc_uwt6b2_dynamic_form_experiment_e2e",
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
        # -----------------------------------------------------
        # SELECT dependency: province -> city option set
        # + city_required_notice REQUIRED change.
        # -----------------------------------------------------

        browser.get(state_url)

        select_result = service.run_experiment(
            browser=browser,
            action={
                "kind": ACTION_SELECT,
                "selector": "#province",
                "frame_path": "main",
            },
            mutation={"selected_value": "08"},
            before_fingerprint=TEST_BEFORE_FINGERPRINT,
        )

        assert select_result["status"] == "SUCCESS"

        assert select_result["mutation_identity"] == {
            "kind": ACTION_SELECT,
            "selected_index": 1,
        }

        select_effect_kinds = {
            effect["kind"]
            for effect in select_result["effects"]
        }

        assert "SELECTION_CHANGED" in select_effect_kinds
        assert "REQUIRED_CHANGED" in select_effect_kinds

        assert select_result["restoration"]["exact"] is True
        assert select_result["restoration"]["effect_count"] == 0
        assert select_result["restoration"]["catalogs_exact"] is True

        assert (
            browser.evaluate(
                "document.querySelector('#province').value"
            )
            == "28"
        )

        assert (
            browser.evaluate(
                "document.querySelector('#city').value"
            )
            == "madrid-centro"
        )

        assert not browser.get_attribute(
            "#city_required_notice",
            "required",
        )

        # -----------------------------------------------------
        # CHECKBOX dependency: accept -> details enabled.
        # -----------------------------------------------------

        browser.get(state_url)

        checkbox_result = service.run_experiment(
            browser=browser,
            action={
                "kind": ACTION_CHECKBOX,
                "selector": "#accept",
                "frame_path": "main",
            },
            mutation={"checked": True},
            before_fingerprint=TEST_BEFORE_FINGERPRINT,
        )

        assert checkbox_result["status"] == "SUCCESS"

        assert checkbox_result["mutation_identity"] == {
            "kind": ACTION_CHECKBOX,
            "checked": True,
        }

        checkbox_effect_kinds = {
            effect["kind"]
            for effect in checkbox_result["effects"]
        }

        assert "CHECKED_CHANGED" in checkbox_effect_kinds
        assert "DISABLED_CHANGED" in checkbox_effect_kinds

        assert checkbox_result["restoration"]["exact"] is True
        assert checkbox_result["restoration"]["effect_count"] == 0

        assert browser.is_checked("#accept") is False

        assert (
            browser.evaluate(
                "document.querySelector('#details').disabled"
            )
            is True
        )

        # -----------------------------------------------------
        # RADIO dependency: plan-pro -> pro_options enabled.
        # -----------------------------------------------------

        browser.get(state_url)

        radio_result = service.run_experiment(
            browser=browser,
            action={
                "kind": ACTION_RADIO,
                "selector": "#plan-pro",
                "frame_path": "main",
            },
            mutation={"checked": True},
            before_fingerprint=TEST_BEFORE_FINGERPRINT,
        )

        assert radio_result["status"] == "SUCCESS"

        assert radio_result["mutation_identity"] == {
            "kind": ACTION_RADIO,
            "checked": True,
        }

        radio_effect_kinds = {
            effect["kind"]
            for effect in radio_result["effects"]
        }

        assert "CHECKED_CHANGED" in radio_effect_kinds
        assert "DISABLED_CHANGED" in radio_effect_kinds

        assert radio_result["restoration"]["exact"] is True
        assert radio_result["restoration"]["effect_count"] == 0

        assert browser.is_checked("#plan-basic") is True
        assert browser.is_checked("#plan-pro") is False

        assert (
            browser.evaluate(
                "document.querySelector('#pro_options').disabled"
            )
            is True
        )

        # -----------------------------------------------------
        # No raw/secret literal leaks and no on-disk mutation.
        # -----------------------------------------------------

        for result in (
            select_result,
            checkbox_result,
            radio_result,
        ):
            serialized = json.dumps(result, default=str)

            assert "html" not in result
            assert "<html" not in serialized.lower()
            assert '"selected_value"' not in serialized
            assert "mutation" not in result

        assert (
            twin_html_path.read_bytes()
            == original_html_bytes
        )

    finally:
        session.shutdown(BrowserShutdownMode.CLOSE)
        local_runtime.stop_all()
