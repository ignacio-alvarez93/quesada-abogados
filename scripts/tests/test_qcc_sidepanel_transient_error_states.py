"""
Regresión: el Side Panel pintaba en rojo estados transitorios/neutros
(carga inicial, NO_ACTIVE_SESSION, creación de sesión, cambio de
perfil de navegador, 503 de registry) durante el sondeo habitual.

Solo un fallo genuino de Bridge/red (HTTP distinto de 503, payload
malformado, RESOLUTION_ERROR, excepción inesperada) debe seguir
pintándose como error rojo.

Estas comprobaciones son estáticas sobre el código fuente del Side
Panel (mismo estilo que el resto de ``test_qcc_sidepanel_*``), sin
abrir navegador ni Bridge real.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

JS = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "sidepanel"
    / "sidepanel.js"
)


def _read():
    return JS.read_text(encoding="utf-8")


def _block(js, start_marker, end_marker):
    start = js.index(start_marker)
    end = js.index(end_marker, start)
    return js[start:end]


def test_fetch_json_preserves_http_status_for_callers():
    js = _read()

    block = _block(
        js,
        "async function fetchJson(",
        "async function postJson(",
    )

    assert "httpError.status" in block
    assert "response.status" in block


def test_transient_context_error_helper_classifies_timeouts_and_503():
    """F/E. Timeout de sondeo y 503 de registry son transitorios."""

    js = _read()

    block = _block(
        js,
        "function qccIsTransientContextError(",
        "function setBridgeState(",
    )

    assert '"AbortError"' in block
    assert "err.status === 503" in block


def test_check_context_failure_routes_through_transient_classifier():
    js = _read()

    block = _block(
        js,
        "async function checkContext(",
        "function toggleHiddenElement(",
    )

    assert "qccIsTransientContextError(" in block
    assert "showPresentationUnavailable(" in block
    assert "showPresentationError(" in block


def test_refresh_presentation_context_failure_routes_through_transient_classifier():
    """F/G. Fallo de red en presentation-context distingue
    transitorio (neutral) de genuino (rojo)."""

    js = _read()

    block = _block(
        js,
        "async function refreshPresentationContext(",
        "function hideTeachHumanOnlyPanel(",
    )

    catch_block = block[block.index("} catch (err) {"):]

    assert "qccIsTransientContextError(" in catch_block
    assert "showPresentationUnavailable();" in catch_block
    assert "showPresentationError(" in catch_block


def test_resolution_error_and_malformed_payload_still_render_error():
    """G. RESOLUTION_ERROR/payload inválido siguen pintándose en rojo."""

    js = _read()

    block = _block(
        js,
        "async function refreshPresentationContext(",
        "function hideTeachHumanOnlyPanel(",
    )

    assert "payload.protocol_version !== 1" in block
    assert "showPresentationError(" in block


def test_no_active_session_still_renders_neutral():
    """E. NO_ACTIVE_SESSION sigue siendo neutral, no error."""

    js = _read()

    block = _block(
        js,
        "async function refreshPresentationContext(",
        "function hideTeachHumanOnlyPanel(",
    )

    no_active_index = block.index('"NO_ACTIVE_SESSION"')
    following = block[no_active_index:no_active_index + 200]

    assert "showPresentationUnavailable(" in following
