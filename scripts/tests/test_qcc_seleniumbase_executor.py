import pytest

from backend.automation.site_architecture.seleniumbase_executor import (
    DEFAULT_TRANSIENT_ERROR_CLASS_NAMES,
    build_seleniumbase_executor,
    default_transient_error_classifier,
)


class _FakeBrowser:
    """Duck-typed CDP-style browser: exposes ``evaluate`` only."""

    def __init__(self, *, click_result=True, evaluate_result=True):
        self.calls = []
        self._click_result = click_result
        self._evaluate_result = evaluate_result

    def evaluate(self, script):
        self.calls.append(script)

        if "querySelector" in script and ".click()" in script:
            return self._click_result

        return self._evaluate_result


def test_click_kind_dispatches_to_click_js():
    browser = _FakeBrowser(click_result=True)
    executor = build_seleniumbase_executor(browser)

    executor(action_kind="BUTTON", selector="#go", frame_path="main")

    assert len(browser.calls) == 1
    assert ".click()" in browser.calls[0]


def test_click_kind_raises_when_element_not_found():
    browser = _FakeBrowser(click_result=False)
    executor = build_seleniumbase_executor(browser)

    with pytest.raises(RuntimeError):
        executor(action_kind="BUTTON", selector="#missing")


def test_input_value_kind_dispatches_to_generic_js_writer():
    browser = _FakeBrowser(evaluate_result=True)
    executor = build_seleniumbase_executor(browser)

    executor(
        action_kind="INPUT_VALUE",
        selector="#dni",
        value="12345678Z",
    )

    assert len(browser.calls) == 1
    assert "12345678Z" in browser.calls[0]
    assert "querySelector" in browser.calls[0]


def test_checkbox_kind_dispatches_to_checkbox_writer():
    browser = _FakeBrowser(evaluate_result=True)
    executor = build_seleniumbase_executor(browser)

    executor(action_kind="CHECKBOX", selector="#accept", value=True)

    assert len(browser.calls) == 1
    assert ".checked" in browser.calls[0]


def test_unsupported_action_kind_is_rejected():
    browser = _FakeBrowser()
    executor = build_seleniumbase_executor(browser)

    with pytest.raises(ValueError):
        executor(action_kind="UNKNOWN_KIND", selector="#x")


def test_missing_selector_is_rejected_before_touching_browser():
    browser = _FakeBrowser()
    executor = build_seleniumbase_executor(browser)

    with pytest.raises(ValueError):
        executor(action_kind="BUTTON", selector="")

    assert browser.calls == []


def test_default_transient_classifier_matches_known_conditions():
    class StaleElementReferenceException(Exception):
        pass

    class SomeUnrelatedError(Exception):
        pass

    assert default_transient_error_classifier(
        StaleElementReferenceException("stale")
    )
    assert not default_transient_error_classifier(
        SomeUnrelatedError("boom")
    )


def test_default_transient_class_names_are_a_fixed_documented_set():
    assert "StaleElementReferenceException" in (
        DEFAULT_TRANSIENT_ERROR_CLASS_NAMES
    )
    assert "TimeoutException" in DEFAULT_TRANSIENT_ERROR_CLASS_NAMES
