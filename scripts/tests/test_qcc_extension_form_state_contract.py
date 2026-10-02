from pathlib import Path


ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

SERVICE_WORKER = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "background"
    / "service_worker.js"
)

DOM_INSPECTOR = (
    ROOT
    / "backend"
    / "automation"
    / "dom_inspector.py"
)


def _service_worker_source():
    return SERVICE_WORKER.read_text(
        encoding="utf-8"
    )


def _dom_inspector_source():
    return DOM_INSPECTOR.read_text(
        encoding="utf-8"
    )


def _block(text, start, end):
    begin = text.index(start)
    finish = text.index(end, begin)

    return text[begin:finish]


# ---------------------------------------------------------------------------
# PRODUCTION_CAPTURE_FORM_STATE
# ---------------------------------------------------------------------------

def test_service_worker_defines_form_signals_helper():
    source = _service_worker_source()

    assert "function formSignalsOf(" in source

    helper = _block(
        source,
        "function formSignalsOf(",
        "function catalogSelectorOf(",
    )

    for token in (
        "has_value",
        "checked",
        "file_selected",
        "file_count",
        "required",
        "readonly",
        "multiple",
    ):
        assert token in helper


def test_service_worker_attaches_form_signals_to_element_record():
    source = _service_worker_source()

    record_block = _block(
        source,
        "const record = {",
        "return record;",
    )

    assert "form_signals:" in record_block
    assert "formSignalsOf(" in record_block


# ---------------------------------------------------------------------------
# DOM_INSPECTOR_FORM_STATE
# ---------------------------------------------------------------------------

def test_dom_inspector_defines_form_signals_helper():
    source = _dom_inspector_source()

    assert "function formSignalsOf(" in source

    helper = _block(
        source,
        "function formSignalsOf(",
        "function elementRecord(",
    )

    for token in (
        "has_value",
        "checked",
        "file_selected",
        "file_count",
        "required",
        "readonly",
        "multiple",
    ):
        assert token in helper


def test_dom_inspector_attaches_form_signals_to_element_record():
    source = _dom_inspector_source()

    record_block = _block(
        source,
        "const record = {",
        "return record;",
    )

    assert "form_signals:" in record_block
    assert "formSignalsOf(" in record_block


# ---------------------------------------------------------------------------
# CAPTURE_PARITY
# ---------------------------------------------------------------------------

def test_extension_and_dom_inspector_form_signals_share_semantic_fields():
    worker_helper = _block(
        _service_worker_source(),
        "function formSignalsOf(",
        "function catalogSelectorOf(",
    )

    inspector_helper = _block(
        _dom_inspector_source(),
        "function formSignalsOf(",
        "function elementRecord(",
    )

    required_tokens = (
        'tag === "select"',
        'tag === "textarea"',
        'type === "checkbox"',
        'type === "radio"',
        'type === "file"',
        'type === "hidden"',
        "element.required",
        "element.readOnly",
        "element.multiple",
        "element.checked",
        "element.value",
        "element.files",
    )

    for token in required_tokens:
        assert token in worker_helper
        assert token in inspector_helper


# ---------------------------------------------------------------------------
# FILE_STATE_SAFE
# ---------------------------------------------------------------------------

def test_form_signals_never_captures_file_path_or_name():
    for helper in (
        _block(
            _service_worker_source(),
            "function formSignalsOf(",
            "function catalogSelectorOf(",
        ),
        _block(
            _dom_inspector_source(),
            "function formSignalsOf(",
            "function elementRecord(",
        ),
    ):
        forbidden = (
            ".name",
            "webkitRelativePath",
            "fakepath",
            "path",
        )

        for token in forbidden:
            assert token not in helper


# ---------------------------------------------------------------------------
# READ-ONLY SAFETY
# ---------------------------------------------------------------------------

def test_form_signals_helper_is_read_only():
    for helper in (
        _block(
            _service_worker_source(),
            "function formSignalsOf(",
            "function catalogSelectorOf(",
        ),
        _block(
            _dom_inspector_source(),
            "function formSignalsOf(",
            "function elementRecord(",
        ),
    ):
        forbidden = (
            ".value =",
            ".checked =",
            "setAttribute(",
            "removeAttribute(",
            "dispatchEvent(",
        )

        for token in forbidden:
            assert token not in helper


# ---------------------------------------------------------------------------
# SITE_NEUTRALITY
# ---------------------------------------------------------------------------

def test_form_signals_helper_has_no_site_specific_tokens():
    forbidden = (
        "mercurio",
        "ex01",
        "datosforaut",
        "gsup",
        "province",
        "nationality",
    )

    for helper in (
        _block(
            _service_worker_source(),
            "function formSignalsOf(",
            "function catalogSelectorOf(",
        ).lower(),
        _block(
            _dom_inspector_source(),
            "function formSignalsOf(",
            "function elementRecord(",
        ).lower(),
    ):
        for token in forbidden:
            assert token not in helper
