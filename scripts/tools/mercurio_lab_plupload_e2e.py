from __future__ import annotations

import hashlib
import tempfile
import threading
import time
from pathlib import Path

from app.run_presentacion_asistida import (
    get_mercurio_document_upload_baseline,
    wait_for_mercurio_document_upload,
)
from backend.automation.browser_contracts import (
    BrowserSessionConfig,
    BrowserShutdownMode,
)
from backend.automation.mercurio_document_dom_reader import (
    read_mercurio_document_state,
)
from backend.automation.seleniumbase_browser_session import (
    SeleniumBaseBrowserSession,
)
from backend.automation.browser_actions import open_url
from tools.mercurio_lab.server import (
    MercurioLabHandler,
    MercurioLabServer,
)

LAB_PATH = "/mercurio/presentacionTelematicaDocumentacion.html"

def run_e2e():
    server = MercurioLabServer(
        ("127.0.0.1", 0),
        MercurioLabHandler,
    )
    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )
    thread.start()

    session = SeleniumBaseBrowserSession(
        config=BrowserSessionConfig(
            consumer="mercurio-lab-plupload-e2e",
            mode="ephemeral",
            headless=False,
        )
    )

    temp_dir = tempfile.TemporaryDirectory()
    pdf_path = Path(temp_dir.name) / "seguro_lab_e2e.pdf"
    pdf_bytes = b"%PDF-1.4 MERCURIO LAB PLUPLOAD E2E"
    pdf_path.write_bytes(pdf_bytes)

    base = "http://127.0.0.1:" + str(server.server_port)
    url = base + LAB_PATH + "?fixture=empty"

    print("LAB_URL =", url)
    print("PDF_PATH =", pdf_path)
    print("PDF_SHA256 =", hashlib.sha256(pdf_bytes).hexdigest().upper())

    browser = None

    try:
        if not url.startswith("http://127.0.0.1:"):
            raise RuntimeError("LAB_LOCALHOST_GUARD_FAILED")

        browser = session.start()
        open_url(browser, url)
        time.sleep(1)

        if browser.evaluate("typeof window.plupload") != "object":
            raise RuntimeError("PLUPLOAD_RUNTIME_MISSING")

        if not browser.evaluate(
            "!!document.getElementById('addDou')"
        ):
            raise RuntimeError("LAB_BROWSE_BUTTON_MISSING")

        print("PLUPLOAD_RUNTIME_OK = True")

        input_element = browser.find_element(
            ".moxie-shim input[type=file]",
            timeout=20,
        )

        browser.select_option_by_value(
            "#docAdjuntarAdjuntos",
            "47",
        )

        send_file = getattr(input_element, "send_file", None)
        if not callable(send_file):
            raise RuntimeError("PLUPLOAD_INPUT_SEND_FILE_UNAVAILABLE")

        send_file(str(pdf_path.resolve()))

        deadline = time.time() + 15
        while time.time() < deadline:
            mirror = browser.evaluate(
                'document.getElementById("fileDocumentoAdjuntos").value'
            )
            if str(mirror or "").endswith(pdf_path.name):
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("PLUPLOAD_FILES_ADDED_NOT_OBSERVED")

        print("FILES_ADDED_OK = True")
        print("MIRROR =", mirror)

        baseline = get_mercurio_document_upload_baseline(
            browser,
            filename=pdf_path.name,
            code="47",
        )
        print("BASELINE =", baseline)

        browser.find_element(
            "#btnOpeAdjuntar",
            timeout=10,
        ).click()

        wait_for_mercurio_document_upload(
            browser,
            filename=pdf_path.name,
            code="47",
            baseline_count=baseline,
            timeout=20,
            poll_interval=0.2,
        )

        state = read_mercurio_document_state(browser)
        confirmed = state.is_uploaded(
            filename=pdf_path.name,
            code="47",
            require_hash=True,
        )

        print("D2_PAGE_DETECTED =", state.page_detected)
        print("D2_CONTRACT_COMPATIBLE =", state.contract_compatible)
        print("D2_UPLOAD_CONFIRMED =", confirmed)
        print("D2_UPLOADED_REQUIRED =", state.uploaded_required_count)

        if not confirmed:
            raise RuntimeError("D2_UPLOAD_NOT_CONFIRMED")

        current_url = str(browser.evaluate("window.location.href") or "")
        if not current_url.startswith(base):
            raise RuntimeError("LAB_NAVIGATION_ESCAPE_DETECTED")

        print("LOCALHOST_GUARD_OK = True")
        print("E2E_OK = True")

    finally:
        if browser is not None:
            result = session.shutdown(BrowserShutdownMode.CLOSE)
            print("SHUTDOWN_CLOSED =", result.browser_closed)
            print("CONTROL_RELEASED =", result.control_released)

        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        temp_dir.cleanup()


if __name__ == "__main__":
    run_e2e()
