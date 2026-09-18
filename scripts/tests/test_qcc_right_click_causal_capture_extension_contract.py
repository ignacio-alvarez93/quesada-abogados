import re
from pathlib import Path


SERVICE_WORKER = Path(
    "chrome_extension/qcc/background/service_worker.js"
)


def _source():
    return SERVICE_WORKER.read_text(
        encoding="utf-8"
    )


def _listener_block(source):
    start = source.index(
        "function installQccHumanClickListenerInFrame("
    )

    end = source.index(
        "function qccHumanFrameIdFromPath",
        start,
    )

    return source[start:end]


def _extract_js_regex_literal(block, const_name):
    """Pull the literal /pattern/ assigned to `const const_name` out of
    the shipped JS source, so behavior is verified against the exact
    regex that ships, not a hand-copied guess."""

    marker = (
        "const "
        + const_name
        + " =\n    /"
    )

    start = block.index(marker) + len(marker) - 1

    end = block.index("/;", start + 1)

    return block[start + 1:end]


def _extract_unsafe_onclick_handler_names(block):
    marker = (
        "const ONCLICK_UNSAFE_HANDLER_NAMES =\n"
        "    new Set([\n"
    )

    start = block.index(marker) + len(marker)

    end = block.index("]);", start)

    names = set()

    for line in block[start:end].splitlines():
        line = line.strip().rstrip(",")

        if not line:
            continue

        names.add(line.strip('"'))

    return names


def _onclick_structural_signature(
    raw_value,
    safe_handler_re,
    handler_name_re,
    unsafe_names,
):
    """Mirrors qccOnclickStructuralSignature() exactly, but driven by
    regex objects extracted from the real shipped source."""

    if not safe_handler_re.fullmatch(raw_value):
        return None

    match = handler_name_re.match(raw_value)

    if not match:
        return None

    if match.group(1).lower() in unsafe_names:
        return None

    trailing_semicolon = raw_value.strip().endswith(";")

    return (
        match.group(0)
        + ")"
        + (";" if trailing_semicolon else "")
    )


def _parse_onclick_structural_selector(selector, selector_re):
    match = selector_re.fullmatch(selector)

    if not match:
        return None

    return match.group(1).lower(), match.group(2)


def test_twin_discovery_auto_arm_uses_contextmenu():
    source = _source()

    assert (
        "QCC_RIGHT_CLICK_CAUSAL_CAPTURE_V1"
        in source
    )

    assert (
        'event_mode:\n          "CONTEXTMENU"'
        in source
    )

    assert (
        '=== "CONTEXTMENU"\n      ? "contextmenu"'
        in source
    )

    assert (
        "event.preventDefault();"
        in source
    )

    assert (
        "event.stopPropagation();"
        in source
    )


def test_legacy_human_listener_keeps_pointerdown_default():
    source = _source()

    assert (
        'request?.event_mode\n      || "POINTERDOWN"'
        in source
    )

    assert (
        'eventMode !== "POINTERDOWN"'
        in source
    )

    assert (
        'eventMode !== "CONTEXTMENU"'
        in source
    )

    assert (
        '"QCC_HUMAN_LISTENER_EVENT_MODE_INVALID"'
        in source
    )


def test_exact_document_listener_receives_event_mode():
    source = _source()

    assert (
        "installQccHumanClickListenerInFrame("
        in source
    )

    assert (
        "ttlMs,\n  eventMode\n)"
        in source
    )

    assert (
        "QCC_HUMAN_LISTENER_TTL_MS,\n"
        "            eventMode"
        in source
    )

def test_right_click_forces_fresh_backend_evidence_before_signal():
    source = _source()

    assert (
        "QCC_RIGHT_CLICK_FRESH_EVIDENCE_V1"
        in source
    )

    assert (
        "qccCaptureFreshRightClickCausalEvidence("
        in source
    )

    assert (
        "await inspectSpecificTabDom("
        in source
    )

    assert (
        "await qccSubmitAutomaticDomCapture("
        in source
    )

    assert (
        "human_listener_evidence_id"
        in source
    )

    assert (
        "QCC_RIGHT_CLICK_FRESH_TARGET_NOT_CANONICAL"
        in source
    )

    assert (
        "effectiveEvidenceId"
        in source
    )

    assert (
        "effectiveObservedAt"
        in source
    )


def test_right_click_fresh_capture_is_exact_document_bound():
    source = _source()

    assert (
        "QCC_RIGHT_CLICK_DOCUMENT_CHANGED"
        in source
    )

    assert (
        "qccAutomaticMainDocumentId("
        in source
    )

    assert (
        "expectedDocumentId"
        in source
    )


def test_pointerdown_legacy_does_not_require_fresh_capture():
    source = _source()

    # Browser arm keeps POINTERDOWN as the compatibility default.
    assert (
        "arm?.event_mode"
        in source
    )

    assert (
        '|| "POINTERDOWN"'
        in source
    )

    # Existing arm evidence is the default effective evidence.
    assert (
        "let effectiveEvidenceId"
        in source
    )

    assert (
        "arm?.evidence_id"
        in source
    )

    # Fresh capture is opt-in exclusively for CONTEXTMENU.
    assert (
        "armEventMode"
        in source
    )

    assert (
        '=== "CONTEXTMENU"'
        in source
    )

    assert (
        "await qccCaptureFreshRightClickCausalEvidence("
        in source
    )

def test_right_click_page_timestamp_stays_physical():
    import re

    source = _source()

    start = source.index(
        "function installQccHumanClickListenerInFrame("
    )

    end = source.index(
        "function qccHumanFrameIdFromPath",
        start,
    )

    block = source[start:end]

    assert re.search(
        r"observed_at:\s*observedAt\b",
        block,
    )

    assert (
        "effectiveObservedAt"
        not in block
    )

def test_fresh_evidence_post_uses_effective_timestamp_and_evidence():
    import re

    source = _source()

    start = source.index(
        "async function forwardQccHumanDomActionSignal("
    )

    end = source.index(
        "function captureDomFrame()",
        start,
    )

    block = source[start:end]

    assert (
        "effectiveEvidenceId"
        in block
    )

    assert (
        "effectiveObservedAt"
        in block
    )

    assert re.search(
        r"evidence_id:\s*effectiveEvidenceId\b",
        block,
    )

    assert re.search(
        r"observed_at:\s*effectiveObservedAt\b",
        block,
    )

def test_right_click_waits_for_bridge_ack_before_left_click():
    source = _source()

    assert (
        "QCC_RIGHT_CLICK_CAUSAL_ACK_V2"
        in source
    )

    assert (
        "QCC_HUMAN_DOM_ACTION_ACK"
        in source
    )

    assert (
        "QCC_HUMAN_DOM_ACTION_ACK_TIMEOUT"
        in source
    )

    assert (
        "waitForAck"
        in source
    )

    assert (
        "AUTO TWIN · acción capturada"
        in source
    )


def test_legacy_pointerdown_remains_fire_and_forget():
    source = _source()

    assert (
        "waitForAck !== true"
        in source
    )

    assert (
        "Legacy POINTERDOWN"
        in source
    )

    assert (
        "queued:"
        in source
    )


def test_structural_onclick_fallback_is_self_contained_in_injected_boundary():
    block = _listener_block(
        _source()
    )

    # installQccHumanClickListenerInFrame is injected through
    # chrome.scripting.executeScript: any helper it needs must be
    # declared inside this same block, or it disappears at injection.
    for token in (
        "const ONCLICK_SAFE_HANDLER_RE",
        "const ONCLICK_HANDLER_NAME_RE",
        "const ONCLICK_UNSAFE_HANDLER_NAMES",
        "const ONCLICK_SELECTOR_RE",
        "function qccOnclickStructuralSignature(",
        "function qccParseOnclickStructuralSelector(",
        "function qccMatchesOnclickStructural(",
    ):
        assert token in block


def test_structural_onclick_fallback_only_runs_after_exact_match_fails():
    block = _listener_block(
        _source()
    )

    exact_index = block.index(
        "target.closest(\n"
    )

    composed_index = block.index(
        "Fallback para composed/shadow paths."
    )

    structural_index = block.index(
        "Fallback estructural ONCLICK."
    )

    # Structural matching is a last-resort fallback, never the
    # primary path: exact CSS matching still runs first.
    assert exact_index < composed_index < structural_index

    structural_guard = block[
        structural_index:
        block.index(
            "qccParseOnclickStructuralSelector(",
            structural_index,
        )
    ]

    assert "if (!found) {" in structural_guard


def test_structural_onclick_fallback_never_sends_raw_literal_to_backend():
    block = _listener_block(
        _source()
    )

    signal_match = re.search(
        r'type:\s*"QCC_HUMAN_DOM_ACTION_SIGNAL"',
        block,
    )

    assert signal_match

    end_match = re.search(
        r"waitForAck\s*\);",
        block[signal_match.start():],
    )

    assert end_match

    signal_block = block[
        signal_match.start():
        signal_match.start() + end_match.end()
    ]

    # Only the already-sanitized canonical selector travels to the
    # backend. Nothing derived from the physical onclick attribute
    # (rawOnclick / nameMatch / signature) ever enters this payload.
    for forbidden in (
        "rawOnclick",
        "nameMatch",
        "getAttribute",
    ):
        assert forbidden not in signal_block

    assert re.search(
        r"selector:\s*selector\b",
        signal_block,
    )


def test_structural_onclick_fallback_matches_physical_child_target_without_pii():
    block = _listener_block(
        _source()
    )

    safe_handler_re = re.compile(
        _extract_js_regex_literal(
            block,
            "ONCLICK_SAFE_HANDLER_RE",
        )
    )

    handler_name_re = re.compile(
        _extract_js_regex_literal(
            block,
            "ONCLICK_HANDLER_NAME_RE",
        )
    )

    selector_re = re.compile(
        _extract_js_regex_literal(
            block,
            "ONCLICK_SELECTOR_RE",
        )
    )

    unsafe_names = _extract_unsafe_onclick_handler_names(
        block
    )

    # Canonical durable target, exactly as Site Architecture
    # sanitizes it for Mercurio's CONTINUAR link.
    canonical_selector = 'a[onclick="continuar();"]'

    parsed = _parse_onclick_structural_selector(
        canonical_selector,
        selector_re,
    )

    assert parsed is not None

    tag, signature = parsed

    assert tag == "a"
    assert signature == "continuar();"

    # The real physical DOM node under Mercurio's <a>: a right click
    # on a nested <span> lands here with the safe literal 'INI'
    # still present in the raw attribute.
    physical_onclick = "continuar('INI');"

    computed_signature = _onclick_structural_signature(
        physical_onclick,
        safe_handler_re,
        handler_name_re,
        unsafe_names,
    )

    assert computed_signature == signature

    # The literal must never surface anywhere in the canonical
    # identity used for matching.
    assert "INI" not in signature
    assert "INI" not in computed_signature


def test_structural_onclick_fallback_rejects_handler_mismatch():
    block = _listener_block(
        _source()
    )

    safe_handler_re = re.compile(
        _extract_js_regex_literal(
            block,
            "ONCLICK_SAFE_HANDLER_RE",
        )
    )

    handler_name_re = re.compile(
        _extract_js_regex_literal(
            block,
            "ONCLICK_HANDLER_NAME_RE",
        )
    )

    unsafe_names = _extract_unsafe_onclick_handler_names(
        block
    )

    canonical_signature = "continuar();"

    other_signature = _onclick_structural_signature(
        "registrar('INI');",
        safe_handler_re,
        handler_name_re,
        unsafe_names,
    )

    assert other_signature == "registrar();"
    assert other_signature != canonical_signature


def test_structural_onclick_fallback_rejects_unsafe_dynamic_expressions():
    block = _listener_block(
        _source()
    )

    safe_handler_re = re.compile(
        _extract_js_regex_literal(
            block,
            "ONCLICK_SAFE_HANDLER_RE",
        )
    )

    handler_name_re = re.compile(
        _extract_js_regex_literal(
            block,
            "ONCLICK_HANDLER_NAME_RE",
        )
    )

    unsafe_names = _extract_unsafe_onclick_handler_names(
        block
    )

    dynamic_values = (
        "continuar(getTipo())",
        "continuar(window.tipo)",
        "continuar('INI' + suffix)",
        "continuar(document.cookie)",
        "alert('hi')",
    )

    for value in dynamic_values:
        assert (
            _onclick_structural_signature(
                value,
                safe_handler_re,
                handler_name_re,
                unsafe_names,
            )
            is None
        )


def test_structural_onclick_fallback_never_exposes_pii_like_literal():
    block = _listener_block(
        _source()
    )

    safe_handler_re = re.compile(
        _extract_js_regex_literal(
            block,
            "ONCLICK_SAFE_HANDLER_RE",
        )
    )

    handler_name_re = re.compile(
        _extract_js_regex_literal(
            block,
            "ONCLICK_HANDLER_NAME_RE",
        )
    )

    unsafe_names = _extract_unsafe_onclick_handler_names(
        block
    )

    signature = _onclick_structural_signature(
        "verDetalle('NIE-X1234567');",
        safe_handler_re,
        handler_name_re,
        unsafe_names,
    )

    assert signature == "verDetalle();"
    assert "X1234567" not in signature
    assert "NIE" not in signature


def _parse_onclick_structural_selector_full(selector, selector_re):
    match = selector_re.fullmatch(selector)

    if not match:
        return None

    position = (
        int(match.group(3))
        if match.group(3) is not None
        else None
    )

    return match.group(1).lower(), match.group(2), position


def test_structural_onclick_fallback_self_contained_includes_positional_helper():
    block = _listener_block(
        _source()
    )

    for token in (
        "function qccOnclickStructuralPosition(",
        "parsed.position",
        ":qcc-nth-onclick",
    ):
        assert token in block


def test_structural_onclick_selector_parses_positional_disambiguation_suffix():
    block = _listener_block(
        _source()
    )

    selector_re = re.compile(
        _extract_js_regex_literal(
            block,
            "ONCLICK_SELECTOR_RE",
        )
    )

    parsed = _parse_onclick_structural_selector_full(
        'a[onclick="validarYEnviar()"]:qcc-nth-onclick(1)',
        selector_re,
    )

    assert parsed == ("a", "validarYEnviar()", 1)

    # Backward compatible: the canonical form without the positional
    # suffix keeps parsing exactly as before.
    canonical = _parse_onclick_structural_selector_full(
        'a[onclick="continuar();"]',
        selector_re,
    )

    assert canonical == ("a", "continuar();", None)


def test_structural_onclick_selector_rejects_malformed_positional_suffix():
    block = _listener_block(
        _source()
    )

    selector_re = re.compile(
        _extract_js_regex_literal(
            block,
            "ONCLICK_SELECTOR_RE",
        )
    )

    malformed = (
        'a[onclick="validarYEnviar()"]:qcc-nth-onclick()',
        'a[onclick="validarYEnviar()"]:qcc-nth-onclick(AB)',
        'a[onclick="validarYEnviar()"]:qcc-nth-onclick(1',
        'a[onclick="validarYEnviar()"]:qcc-nth-onclick(-1)',
        'a[onclick="validarYEnviar()"]extra',
    )

    for selector in malformed:
        assert selector_re.fullmatch(selector) is None


def test_structural_onclick_fallback_positional_selector_matches_abogacia_signature():
    """CONTINUAR ABOGACÍA collapses to the same structural signature as
    its siblings (validarYEnviar('IN'), ('RC'), ...); the positional
    suffix is what makes it individually addressable, without ever
    carrying the literal branch code 'AB'."""

    block = _listener_block(
        _source()
    )

    safe_handler_re = re.compile(
        _extract_js_regex_literal(
            block,
            "ONCLICK_SAFE_HANDLER_RE",
        )
    )

    handler_name_re = re.compile(
        _extract_js_regex_literal(
            block,
            "ONCLICK_HANDLER_NAME_RE",
        )
    )

    selector_re = re.compile(
        _extract_js_regex_literal(
            block,
            "ONCLICK_SELECTOR_RE",
        )
    )

    unsafe_names = _extract_unsafe_onclick_handler_names(
        block
    )

    canonical_selector = (
        'a[onclick="validarYEnviar()"]'
        ":qcc-nth-onclick(5)"
    )

    parsed = _parse_onclick_structural_selector_full(
        canonical_selector,
        selector_re,
    )

    assert parsed is not None

    tag, signature, position = parsed

    assert tag == "a"
    assert position == 5

    physical_onclick = "validarYEnviar('AB')"

    computed_signature = _onclick_structural_signature(
        physical_onclick,
        safe_handler_re,
        handler_name_re,
        unsafe_names,
    )

    assert computed_signature == signature
    assert "AB" not in signature
    assert "AB" not in computed_signature


def test_ordinary_exact_selectors_are_not_parsed_as_onclick_structural():
    block = _listener_block(
        _source()
    )

    selector_re = re.compile(
        _extract_js_regex_literal(
            block,
            "ONCLICK_SELECTOR_RE",
        )
    )

    ordinary_selectors = (
        "#continueButton",
        '[data-testid="continuar"]',
        '[aria-label="Continuar"]',
        "button",
    )

    for selector in ordinary_selectors:
        assert (
            _parse_onclick_structural_selector(
                selector,
                selector_re,
            )
            is None
        )
