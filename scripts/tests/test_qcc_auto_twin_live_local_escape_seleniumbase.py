"""Governed SeleniumBase E2E for UWT-7A4 runtime network shielding.

Proves, with a REAL governed SeleniumBase browser, that captured REAL
inline JavaScript (no src) can never escape the materialized Twin --
even when the hostile script explicitly targets a LOCAL loopback trap
origin that is NOT the Twin's own origin.

No REAL network. The trap is 127.0.0.1-only:

- never a real government host;
- never example.com;
- never 169.254.169.254;
- never the public internet;
- never external DNS.

If this environment cannot launch a governed SeleniumBase/Chrome
session, the test is explicitly skipped with a BLOCKED reason rather
than silently reporting success.
"""

from __future__ import annotations

import hashlib
import http.server
import threading
import time
from email import policy
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlparse

import pytest

from backend.qcc.auto_twin.materialization_builder import (
    materialize_auto_twin_plan,
)
from backend.qcc.auto_twin.materialization_plan import (
    AUTO_TWIN_MATERIALIZATION_PLAN_TYPE,
)
from backend.services.twin_browser_runtime_service import (
    TwinBrowserRuntimeService,
)


TWIN_KEY = "uwt7a4-live-local-escape-twin"
STATE_ID = "STATE_HOSTILE_INLINE_JS"
STATE_DIR_NAME = "01-" + STATE_ID
CAPTURE_ID = "cap-live-escape-1"
CAPTURED_ORIGIN = "https://example.test"
PATHNAME = "/es/hostile-inline"

_INLINE_SCRIPT_MARKER = (
    'data-qcc-auto-twin-network-sterilized="captured-inline-script"'
)


# =============================================================================
# LOCAL loopback trap. Never REAL, never public internet.
# =============================================================================


class _TrapRequestHandler(http.server.BaseHTTPRequestHandler):
    def _record(self):
        self.server.received_paths.append(self.path)
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        self._record()

    def do_POST(self):
        self._record()

    def log_message(self, format, *args):
        return


class _TrapServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.received_paths = []


def _start_trap_server():
    server = _TrapServer(
        ("127.0.0.1", 0),
        _TrapRequestHandler,
    )

    thread = threading.Thread(
        target=server.serve_forever,
        name="qcc-live-local-escape-trap",
        daemon=True,
    )

    thread.start()

    return server, thread


# =============================================================================
# SYNTHETIC captured evidence: hostile inline JS targeting the trap.
# =============================================================================


def _sha256(content):
    return hashlib.sha256(content).hexdigest()


def _hostile_html(trap_origin, click_trap_origin):
    return (
        "<!doctype html>\n"
        "<html>\n"
        "<head><title>Hostile Inline JS Fixture</title></head>\n"
        "<body>\n"
        "CAPTURED REAL PAGE\n"
        "<script>\n"
        'window.location = "' + trap_origin + '/navigate";\n'
        'window.open("' + trap_origin + '/open");\n'
        'fetch("' + trap_origin + '/fetch");\n'
        "var xhr = new XMLHttpRequest();\n"
        'xhr.open("GET", "' + trap_origin + '/xhr");\n'
        "xhr.send();\n"
        "</script>\n"
        '<button id="onclick-trap" onclick=\'window.location='
        '"' + click_trap_origin + '/onclick-nav";\'>'
        "Onclick Trap</button>\n"
        '<a id="js-href-trap" href=\'javascript:window.location='
        '"' + click_trap_origin + '/js-href-nav";\'>'
        "JS Href Trap</a>\n"
        "</body>\n"
        "</html>\n"
    )


def _write_fixture_mhtml(path, trap_origin, click_trap_origin):
    root = EmailMessage()
    root["MIME-Version"] = "1.0"
    root.set_type("multipart/related")

    html_part = EmailMessage()
    html_part.set_content(
        _hostile_html(trap_origin, click_trap_origin),
        subtype="html",
        charset="utf-8",
    )

    html_part["Content-Location"] = CAPTURED_ORIGIN + PATHNAME

    root.attach(html_part)

    path.write_bytes(root.as_bytes(policy=policy.default))


def _materialize_hostile_twin(tmp_path, trap_origin, click_trap_origin):
    captures = tmp_path / "captures"
    capture_dir = captures / CAPTURE_ID
    capture_dir.mkdir(parents=True)

    page_html = b"<html><body>FALLBACK</body></html>"

    (capture_dir / "page.html").write_bytes(page_html)

    _write_fixture_mhtml(
        capture_dir / "page.mhtml",
        trap_origin,
        click_trap_origin,
    )

    page_mhtml = (capture_dir / "page.mhtml").read_bytes()

    plan = {
        "plan_type": AUTO_TWIN_MATERIALIZATION_PLAN_TYPE,
        "twin_key": TWIN_KEY,
        "materialization_mode": "BOOTSTRAP_REAL",
        "source_capture_ids": [CAPTURE_ID],
        "source_evidence_sha256": "a" * 64,
        "artifact_operations": [
            {
                "source_reference": CAPTURE_ID + "/page.html",
                "destination_path": (
                    "states/" + STATE_DIR_NAME + "/source/page.html"
                ),
                "sha256": _sha256(page_html),
                "size_bytes": len(page_html),
            },
            {
                "source_reference": CAPTURE_ID + "/page.mhtml",
                "destination_path": (
                    "states/" + STATE_DIR_NAME + "/source/page.mhtml"
                ),
                "sha256": _sha256(page_mhtml),
                "size_bytes": len(page_mhtml),
            },
        ],
        "state_manifest": [
            {
                "state_index": 1,
                "state_id": STATE_ID,
                "source_capture_id": CAPTURE_ID,
                "pathname": PATHNAME,
                "functional_state": None,
                "rendering_profile_id": "RENDER_PROFILE_1",
            },
        ],
    }

    materialized_root = tmp_path / "materialized"

    result = materialize_auto_twin_plan(
        plan=plan,
        source_root=captures,
        materialized_root=materialized_root,
        procedure_code="LIVE_LOCAL_ESCAPE",
        flow_variant="SITE_LEVEL",
    )

    revision_dir = Path(
        result["revision_dir"]
    )

    runtime_index = (
        revision_dir
        / "states"
        / STATE_DIR_NAME
        / "runtime"
        / "index.html"
    )

    return (
        materialized_root,
        result["revision"]["materialized_revision_id"],
        runtime_index,
    )


# =============================================================================
# A normal Twin-authored script (the _NETWORK_GUARD submit interceptor,
# injected strictly AFTER sterilization) must still operate.
# =============================================================================


_SUBMIT_GUARD_PROBE_SCRIPT = """
var form = document.createElement("form");
document.body.appendChild(form);
var event = new Event("submit", {cancelable: true, bubbles: true});
var dispatchReturned = form.dispatchEvent(event);
var defaultPrevented = event.defaultPrevented;
document.body.removeChild(form);
return {
  dispatchReturned: dispatchReturned,
  defaultPrevented: defaultPrevented
};
"""


_CLICK_TRAPS_PROBE_SCRIPT = """
var onclickTrap = document.getElementById("onclick-trap");
var jsHrefTrap = document.getElementById("js-href-trap");
onclickTrap.click();
jsHrefTrap.click();
return {
  onclickAttribute: onclickTrap.getAttribute("onclick"),
  jsHrefAttribute: jsHrefTrap.getAttribute("href"),
  currentUrl: window.location.href
};
"""


def test_captured_hostile_inline_script_cannot_reach_local_trap(
    tmp_path,
):
    trap_server, _trap_thread = _start_trap_server()
    click_trap_server, _click_trap_thread = _start_trap_server()

    trap_port = int(
        trap_server.server_address[1]
    )

    click_trap_port = int(
        click_trap_server.server_address[1]
    )

    trap_origin = "http://127.0.0.1:{}".format(trap_port)

    click_trap_origin = "http://127.0.0.1:{}".format(
        click_trap_port
    )

    try:
        (
            materialized_root,
            revision_id,
            runtime_index_path,
        ) = _materialize_hostile_twin(
            tmp_path,
            trap_origin,
            click_trap_origin,
        )

        materialized_html = runtime_index_path.read_text(
            encoding="utf-8"
        )

        # ---------------------------------------------------------
        # Static proof: the hostile body never survives
        # sterilize_runtime_html(), regardless of browser execution.
        # ---------------------------------------------------------
        assert trap_origin not in materialized_html
        assert click_trap_origin not in materialized_html
        assert "window.location" not in materialized_html
        assert "window.open" not in materialized_html
        assert "fetch(" not in materialized_html
        assert "XMLHttpRequest" not in materialized_html
        assert "onclick=" not in materialized_html
        assert "javascript:" not in materialized_html
        assert _INLINE_SCRIPT_MARKER in materialized_html

        service = TwinBrowserRuntimeService(
            materialized_root=materialized_root,
            profile_resolver=(
                lambda key: tmp_path / "browser_profiles" / key
            ),
        )

        try:
            try:
                status = service.start(
                    twin_key=TWIN_KEY,
                    revision_id=revision_id,
                    state_id=STATE_ID,
                )
            except Exception as exc:
                pytest.skip(
                    "SELENIUMBASE_E2E_BLOCKED:"
                    + " {}: {}".format(
                        type(exc).__name__,
                        exc,
                    )
                )
                return

            if status["status"] != "RUNNING":
                pytest.skip(
                    "SELENIUMBASE_E2E_BLOCKED:"
                    + " status={}".format(status["status"])
                    + " last_error={}".format(
                        status.get("last_error")
                    )
                )
                return

            parsed_twin_url = urlparse(status["url"])
            assert parsed_twin_url.hostname == "127.0.0.1"
            assert parsed_twin_url.scheme == "http"
            assert parsed_twin_url.port != trap_port
            assert parsed_twin_url.port != click_trap_port

            # Give any (unexpected) navigation/fetch attempt time to
            # reach the trap before asserting zero contact.
            time.sleep(1.5)

            current_url = service.execute_script(
                twin_key=TWIN_KEY,
                script="return window.location.href;",
            )

            parsed_current_url = urlparse(current_url)

            assert parsed_current_url.hostname == "127.0.0.1"
            assert parsed_current_url.port != trap_port

            assert trap_server.received_paths == []

            probe = service.execute_script(
                twin_key=TWIN_KEY,
                script=_SUBMIT_GUARD_PROBE_SCRIPT,
            )

            assert probe["defaultPrevented"] is True
            assert probe["dispatchReturned"] is False

            # -------------------------------------------------------
            # A. onclick targeting the click-trap origin must not
            #    execute: the attribute itself must already be gone.
            # B. javascript: href targeting the click-trap origin must
            #    not execute: the href must already be neutralized.
            # C. clicking both elements must leave the Twin on its own
            #    governed local origin, with zero contact to either
            #    trap.
            # -------------------------------------------------------
            click_probe = service.execute_script(
                twin_key=TWIN_KEY,
                script=_CLICK_TRAPS_PROBE_SCRIPT,
            )

            assert click_probe["onclickAttribute"] is None
            assert click_probe["jsHrefAttribute"] == "#"

            parsed_click_probe_url = urlparse(
                click_probe["currentUrl"]
            )

            assert (
                parsed_click_probe_url.hostname
                == "127.0.0.1"
            )

            assert (
                parsed_click_probe_url.port
                != trap_port
            )

            assert (
                parsed_click_probe_url.port
                != click_trap_port
            )

            assert trap_server.received_paths == []
            assert click_trap_server.received_paths == []

        finally:
            service.stop(twin_key=TWIN_KEY)

    finally:
        trap_server.shutdown()
        trap_server.server_close()
        click_trap_server.shutdown()
        click_trap_server.server_close()
