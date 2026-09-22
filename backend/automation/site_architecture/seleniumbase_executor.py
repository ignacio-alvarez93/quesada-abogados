"""SeleniumBase-wired snapshot provider and executor (V1).

QCC_STATE_AWARE_SELENIUMBASE_EXECUTOR_V1

The only module in this mission that actually touches a live browser.
Both collaborators required by
``state_aware_execution.execute_state_aware_action`` are built here on
top of the SAME real primitives already used across the codebase
(``backend.automation.browser_actions`` and
``backend.automation.dom_inspector``): this is not a second,
parallel execution architecture, it is the concrete adapter that
plugs the governed chain into real SeleniumBase/CDP.

Provider-neutral: nothing here references Mercurio, Red SARA, DEHu or
any other specific site.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from backend.automation import browser_actions
from backend.automation.dom_inspector import (
    capture_dom_payload,
)
from backend.automation.site_architecture.normalizer import (
    normalize_dom_capture,
)

from .state_aware_execution import (
    CapturedSnapshot,
)


# Conservative, name-based allow-list of well-known SeleniumBase/CDP
# timing conditions. Matched on ``type(exc).__name__`` only, so this
# module never hard-imports selenium/seleniumbase: it stays usable
# even in environments where those packages are not installed (e.g.
# unit tests). Deliberately narrow: anything not on this list is
# treated as a non-transient error and is never retried.
DEFAULT_TRANSIENT_ERROR_CLASS_NAMES = frozenset({
    "StaleElementReferenceException",
    "ElementNotInteractableException",
    "ElementClickInterceptedException",
    "NoSuchElementException",
    "NoSuchFrameException",
    "TimeoutException",
    "JavascriptException",
})

_CLICK_KINDS = frozenset({
    "BUTTON",
    "SUBMIT",
    "LINK",
    "TAB",
})

_CHECKBOX_KINDS = frozenset({
    "CHECKBOX",
})

_VALUE_KINDS = frozenset({
    "INPUT_VALUE",
    "SELECT",
    "RADIO",
})


def default_transient_error_classifier(exc: Exception) -> bool:
    """Conservative, name-based transient-condition classification."""

    return (
        type(exc).__name__
        in DEFAULT_TRANSIENT_ERROR_CLASS_NAMES
    )


def build_seleniumbase_snapshot_provider(browser):
    """Returns a ``snapshot_provider`` callable for the governed chain.

    Captures the live DOM via CDP/execute_script, normalizes it into
    the certified Site Architecture snapshot shape, and stamps the
    capture time for evidence-freshness checks. Never writes to disk.

    State recognition itself is applied later by the orchestrator
    (``StateAwareExecutionRequest.state_recognizer``), not here: this
    provider only ever returns the raw normalized snapshot.
    """

    def _provider():
        raw_capture = capture_dom_payload(browser)
        normalized = normalize_dom_capture(raw_capture)

        return CapturedSnapshot(
            # ``normalize_dom_capture`` returns a
            # ``SiteArchitectureSnapshot`` dataclass; the governed
            # chain (and ``observe_site_state``) work against its
            # plain-dict public representation.
            snapshot=normalized.to_dict(),
            captured_at=datetime.now(timezone.utc),
        )

    return _provider


def _click(browser, selector):
    if not browser_actions.click_js(browser, selector):
        raise RuntimeError(
            "QCC_SELENIUMBASE_EXECUTOR_ELEMENT_NOT_FOUND"
        )


def _set_value(browser, selector, value):
    script = f"""
    (function(){{
        const el = document.querySelector({json.dumps(selector)});
        if (!el) return false;
        el.value = {json.dumps("" if value is None else str(value))};
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        return true;
    }})();
    """

    if not browser_actions.js(browser, script):
        raise RuntimeError(
            "QCC_SELENIUMBASE_EXECUTOR_ELEMENT_NOT_FOUND"
        )


def _set_checkbox(browser, selector, value):
    script = f"""
    (function(){{
        const el = document.querySelector({json.dumps(selector)});
        if (!el) return false;
        el.checked = {json.dumps(bool(value))};
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        return true;
    }})();
    """

    if not browser_actions.js(browser, script):
        raise RuntimeError(
            "QCC_SELENIUMBASE_EXECUTOR_ELEMENT_NOT_FOUND"
        )


def build_seleniumbase_executor(browser):
    """Returns an ``executor`` callable for the governed chain.

    Dispatches by canonical action kind onto the same DOM-primitive
    functions (``browser_actions.click_js`` / ``browser_actions.js``)
    already used throughout the existing SeleniumBase execution paths.
    Raises on any structural failure (element not found); it never
    swallows an error and never itself decides whether that failure is
    safe to retry, that is the orchestrator's job.
    """

    def _executor(*, action_kind, selector, frame_path="main", value=None):
        if not selector:
            raise ValueError(
                "QCC_SELENIUMBASE_EXECUTOR_SELECTOR_REQUIRED"
            )

        kind = str(action_kind or "").strip().upper()

        if kind in _CLICK_KINDS:
            _click(browser, selector)
            return

        if kind in _CHECKBOX_KINDS:
            _set_checkbox(browser, selector, value)
            return

        if kind in _VALUE_KINDS:
            _set_value(browser, selector, value)
            return

        raise ValueError(
            "QCC_SELENIUMBASE_EXECUTOR_UNSUPPORTED_ACTION_KIND"
        )

    return _executor
