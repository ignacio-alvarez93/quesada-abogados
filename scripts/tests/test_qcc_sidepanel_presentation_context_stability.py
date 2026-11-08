"""
QCC_CONTEXT_STABILITY_V5.

Regresion: Presentation Context a veces desaparecia en el Side Panel
aunque la sesion activa seguia siendo AVAILABLE en el Bridge. La causa
real era que un fallo TRANSITORIO de sondeo (AbortError, timeout, 503,
una peticion solapada/cancelada) se trataba como si la sesion
autoritativa hubiese terminado: los tres catch implicados
(``checkBridgeHealth``, ``checkContext``, ``refreshPresentationContext``)
limpiaban session ids y repintaban el panel en estado neutral/error
antes de devolver el control.

Estas comprobaciones son estaticas sobre el codigo fuente del Side
Panel (mismo estilo que el resto de ``test_qcc_sidepanel_*``), sin
abrir navegador ni Bridge real: no existe en este repositorio un
arnes de ejecucion de JS, asi que la propiedad "un error transitorio
nunca limpia el contexto ya pintado" se verifica comprobando que la
rama transitoria de cada catch retorna ANTES de tocar cualquier
estado o funcion de render, y que la rama genuina (tras ese retorno
acotado) sigue limpiando/pintando como antes.
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


def _catch_branches(block):
    """Splits a function body's ``catch`` into (transient, genuine)
    source text, assuming the transient branch ends with the first
    bounded ``return;`` after the catch opens."""

    catch_block = block[block.index("} catch"):]
    transient = catch_block[: catch_block.index("return;")]
    genuine = catch_block[catch_block.index("return;"):]
    return transient, genuine


# AVAILABLE -> AbortError / transient 503 -> AVAILABLE (health poll).
def test_check_bridge_health_transient_failure_preserves_context():
    js = _read()

    block = _block(
        js,
        "async function checkBridgeHealth(",
        "async function handleDocumentsStart(",
    )

    assert "qccIsTransientContextError(" in block

    transient, genuine = _catch_branches(block)

    assert "qccOwnSessionId" not in transient
    assert "qccViewedSessionId" not in transient
    assert "setBridgeState(" not in transient
    assert "showEmptyContext(" not in transient
    assert "showPresentationUnavailable(" not in transient

    # The genuine (non-transient) branch still clears/paints as before.
    assert "qccOwnSessionId" in genuine
    assert "qccViewedSessionId" in genuine
    assert "showPresentationUnavailable(" in genuine


# AVAILABLE -> AbortError / transient 503 -> AVAILABLE (context poll).
def test_check_context_transient_failure_preserves_context():
    js = _read()

    block = _block(
        js,
        "async function checkContext(",
        "function toggleHiddenElement(",
    )

    assert "qccIsTransientContextError(" in block

    transient, genuine = _catch_branches(block)

    assert "qccOwnSessionId" not in transient
    assert "qccViewedSessionId" not in transient
    assert "showEmptyContext(" not in transient
    assert "showPresentationError(" not in transient
    assert "showPresentationUnavailable(" not in transient

    assert "showPresentationError(" in genuine


# AVAILABLE -> AbortError / transient 503 / overlapping-cancelled
# refresh -> AVAILABLE (presentation-context poll itself).
def test_refresh_presentation_context_transient_failure_preserves_context():
    js = _read()

    block = _block(
        js,
        "async function refreshPresentationContext(",
        "function hideTeachHumanOnlyPanel(",
    )

    assert "qccIsTransientContextError(" in block

    transient, genuine = _catch_branches(block)

    assert "showPresentationUnavailable(" not in transient
    assert "showPresentationError(" not in transient

    assert "showPresentationError(" in genuine


# AVAILABLE -> authoritative session end -> clears.
def test_authoritative_no_active_session_still_clears_presentation_context():
    js = _read()

    block = _block(
        js,
        "async function refreshPresentationContext(",
        "function hideTeachHumanOnlyPanel(",
    )

    no_active_index = block.index('"NO_ACTIVE_SESSION"')
    following = block[no_active_index:no_active_index + 200]

    assert "showPresentationUnavailable(" in following


def test_authoritative_inactive_general_context_still_clears():
    js = _read()

    block = _block(
        js,
        "function renderContext(",
        "async function checkContext(",
    )

    assert "!payload.active" in block or "!payload.active_session" in block
    assert "showEmptyContext(" in block


# Session/profile A -> authoritative B switches correctly: explicit
# switches stay untouched by the transient-error fix, they still
# reset the viewed/own session before re-resolving against the
# Bridge.
def test_explicit_profile_switch_resets_viewed_session_before_recheck():
    js = _read()

    block = _block(
        js,
        "async function handleBrowserProfileSelection(",
        "async function handleBrowserProfileBind(",
    )

    assert "qccViewedSessionId" in block
    assert "null;" in block
    assert "checkContext()" in block


def test_explicit_profile_bind_resets_own_and_viewed_session_before_recheck():
    js = _read()

    block = _block(
        js,
        "async function handleBrowserProfileBind(",
        "async function checkContext(",
    )

    assert "qccOwnSessionId" in block
    assert "qccViewedSessionId" in block
    assert "checkContext()" in block
