"""Governed functional validation of materialized AUTO TWIN transitions.

A trusted REAL causal transition already materialized as TWIN_ELIGIBLE
may be replayed exclusively inside the local governed Twin.

This module:
- never opens REAL;
- starts the exact before_state_id;
- executes the learned selector inside SeleniumBase;
- requires navigation to the exact local target_runtime_entry;
- fails closed if the browser leaves the loopback origin;
- does not grant REAL automation authority;
- does not persist evidence yet.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from backend.services.twin_browser_runtime_service import (
    DEFAULT_MATERIALIZED_ROOT,
    get_default_twin_browser_runtime_service,
)


AUTO_TWIN_NAVIGATION_VALIDATION_SCHEMA_VERSION = 1

AUTO_TWIN_NAVIGATION_VALIDATION_TYPE = (
    "QCC_AUTO_TWIN_NAVIGATION_VALIDATION"
)

AUTO_TWIN_NAVIGATION_VALIDATION_TWIN_VALIDATED = (
    "TWIN_VALIDATED"
)

AUTO_TWIN_NAVIGATION_VALIDATION_FAILED = (
    "FAILED"
)


def _text(
    value,
):
    return str(
        value
        or ""
    ).strip()


def _segment(
    value,
    *,
    error,
):
    value = _text(
        value
    )

    if (
        not value
        or "/" in value
        or "\\" in value
        or value in {".", ".."}
    ):
        raise ValueError(
            error
        )

    return value


def _loopback_origin(
    url,
):
    parsed = urlsplit(
        _text(
            url
        )
    )

    hostname = (
        parsed.hostname
        or ""
    ).lower()

    if (
        parsed.scheme != "http"
        or hostname
        not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }
    ):
        raise RuntimeError(
            "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_"
            "NON_LOCAL_RUNTIME"
        )

    return (
        parsed.scheme
        + "://"
        + parsed.netloc
    )


def _load_transition(
    *,
    materialized_root,
    twin_key,
    revision_id,
    candidate_id,
):
    twin_key = _segment(
        twin_key,
        error=(
            "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_"
            "TWIN_KEY_INVALID"
        ),
    )

    revision_id = _segment(
        revision_id,
        error=(
            "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_"
            "REVISION_ID_INVALID"
        ),
    )

    candidate_id = _text(
        candidate_id
    )

    if not candidate_id:
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_"
            "CANDIDATE_ID_REQUIRED"
        )

    path = (
        Path(
            materialized_root
        )
        / twin_key
        / revision_id
        / "runtime"
        / "navigation_transitions.json"
    )

    if not path.is_file():
        raise FileNotFoundError(
            "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_"
            "RUNTIME_TRANSITIONS_NOT_FOUND:"
            + revision_id
        )

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    transitions = payload.get(
        "transitions"
    )

    if not isinstance(
        transitions,
        list,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_"
            "TRANSITIONS_INVALID"
        )

    matches = [
        transition
        for transition in transitions
        if (
            isinstance(
                transition,
                dict,
            )
            and _text(
                transition.get(
                    "candidate_id"
                )
            )
            == candidate_id
        )
    ]

    if not matches:
        raise KeyError(
            "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_"
            "CANDIDATE_NOT_FOUND:"
            + candidate_id
        )

    if len(
        matches
    ) != 1:
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_"
            "CANDIDATE_AMBIGUOUS:"
            + candidate_id
        )

    transition = matches[0]

    if (
        _text(
            transition.get(
                "eligibility"
            )
        )
        != "TWIN_ELIGIBLE"
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_"
            "NOT_TWIN_ELIGIBLE"
        )

    before_state_id = _text(
        transition.get(
            "before_state_id"
        )
    )

    after_state_id = _text(
        transition.get(
            "after_state_id"
        )
    )

    target_runtime_entry = _text(
        transition.get(
            "target_runtime_entry"
        )
    )

    action = (
        transition.get(
            "action"
        )
        or {}
    )

    selector = _text(
        action.get(
            "selector"
        )
    )

    frame_path = (
        _text(
            action.get(
                "frame_path"
            )
        )
        or "main"
    )

    if (
        not before_state_id
        or not after_state_id
        or not selector
        or not target_runtime_entry
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_"
            "TRANSITION_IDENTITY_INVALID"
        )

    if frame_path != "main":
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_"
            "FRAME_UNSUPPORTED:"
            + frame_path
        )

    if (
        target_runtime_entry.startswith(
            "/"
        )
        or "://" in target_runtime_entry
        or ".." in target_runtime_entry.split(
            "/"
        )
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_"
            "TARGET_RUNTIME_ENTRY_INVALID"
        )

    return transition


def validate_materialized_navigation_transition(
    *,
    twin_key,
    revision_id,
    candidate_id,
    browser_runtime_service=None,
    materialized_root=DEFAULT_MATERIALIZED_ROOT,
    timeout_seconds=8.0,
    poll_interval_seconds=0.10,
):
    """Replay one exact materialized causal transition in the Twin."""

    timeout_seconds = float(
        timeout_seconds
    )

    poll_interval_seconds = float(
        poll_interval_seconds
    )

    if timeout_seconds <= 0:
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_"
            "TIMEOUT_INVALID"
        )

    if poll_interval_seconds <= 0:
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_"
            "POLL_INTERVAL_INVALID"
        )

    transition = _load_transition(
        materialized_root=(
            materialized_root
        ),
        twin_key=twin_key,
        revision_id=revision_id,
        candidate_id=candidate_id,
    )

    before_state_id = transition[
        "before_state_id"
    ]

    after_state_id = transition[
        "after_state_id"
    ]

    target_runtime_entry = transition[
        "target_runtime_entry"
    ]

    action = transition[
        "action"
    ]

    selector = action[
        "selector"
    ]

    service = (
        browser_runtime_service
        or get_default_twin_browser_runtime_service()
    )

    expected_pathname = (
        "/"
        + target_runtime_entry.lstrip(
            "/"
        )
    )

    base_result = {
        "schema_version":
            AUTO_TWIN_NAVIGATION_VALIDATION_SCHEMA_VERSION,

        "validation_type":
            AUTO_TWIN_NAVIGATION_VALIDATION_TYPE,

        "twin_key":
            twin_key,

        "revision_id":
            revision_id,

        "candidate_id":
            candidate_id,

        "before_state_id":
            before_state_id,

        "after_state_id":
            after_state_id,

        "selector":
            selector,

        "expected_runtime_entry":
            target_runtime_entry,

        "expected_pathname":
            expected_pathname,
    }

    started = False

    try:
        start_result = service.start(
            twin_key=twin_key,
            revision_id=revision_id,
            state_id=before_state_id,
        )

        started = True

        if (
            _text(
                start_result.get(
                    "status"
                )
            )
            != "RUNNING"
        ):
            return {
                **base_result,
                "status":
                    AUTO_TWIN_NAVIGATION_VALIDATION_FAILED,

                "reason":
                    "TWIN_BROWSER_NOT_RUNNING",

                "location":
                    None,
            }

        runtime_origin = _loopback_origin(
            start_result.get(
                "url"
            )
        )

        click_result = service.execute_script(
            twin_key=twin_key,
            script=r"""
// QCC_AUTO_TWIN_NAVIGATION_VALIDATION_CLICK_V1
const selector = arguments[0];

let element = null;

try {
    element = document.querySelector(selector);
} catch (error) {
    return {
        found: false,
        selector_error: String(error),
        href: window.location.href
    };
}

if (!element) {
    return {
        found: false,
        selector_error: null,
        href: window.location.href
    };
}

const href = window.location.href;

window.setTimeout(
    () => element.click(),
    0
);

return {
    found: true,
    selector_error: null,
    href: href
};
""",
            args=[
                selector,
            ],
        )

        if (
            not isinstance(
                click_result,
                dict,
            )
            or click_result.get(
                "found"
            )
            is not True
        ):
            return {
                **base_result,
                "status":
                    AUTO_TWIN_NAVIGATION_VALIDATION_FAILED,

                "reason":
                    "ACTION_TARGET_NOT_FOUND",

                "location":
                    (
                        click_result
                        if isinstance(
                            click_result,
                            dict,
                        )
                        else None
                    ),
            }

        deadline = (
            time.monotonic()
            + timeout_seconds
        )

        last_location = None

        while True:
            location = service.execute_script(
                twin_key=twin_key,
                script=r"""
// QCC_AUTO_TWIN_NAVIGATION_VALIDATION_LOCATION_V1
return {
    href: window.location.href,
    origin: window.location.origin,
    pathname: window.location.pathname
};
""",
            )

            if isinstance(
                location,
                dict,
            ):
                last_location = location

                current_origin = _text(
                    location.get(
                        "origin"
                    )
                )

                current_href = _text(
                    location.get(
                        "href"
                    )
                )

                current_pathname = _text(
                    location.get(
                        "pathname"
                    )
                )

                if current_href:
                    _loopback_origin(
                        current_href
                    )

                if (
                    current_origin
                    != runtime_origin
                ):
                    raise RuntimeError(
                        "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_"
                        "ORIGIN_ESCAPE"
                    )

                if (
                    current_pathname
                    == expected_pathname
                ):
                    return {
                        **base_result,

                        "status":
                            AUTO_TWIN_NAVIGATION_VALIDATION_TWIN_VALIDATED,

                        "reason":
                            "EXACT_LOCAL_TARGET_REACHED",

                        "location":
                            location,
                    }

            if (
                time.monotonic()
                >= deadline
            ):
                break

            time.sleep(
                poll_interval_seconds
            )

        return {
            **base_result,

            "status":
                AUTO_TWIN_NAVIGATION_VALIDATION_FAILED,

            "reason":
                "TARGET_RUNTIME_TIMEOUT",

            "location":
                last_location,
        }

    finally:
        if started:
            service.stop(
                twin_key=twin_key
            )


def validate_and_record_materialized_navigation_transition(
    *,
    twin_key,
    revision_id,
    candidate_id,
    browser_runtime_service=None,
    validation_store=None,
    materialized_root=DEFAULT_MATERIALIZED_ROOT,
    timeout_seconds=8.0,
    poll_interval_seconds=0.10,
):
    """Replay one transition and persist only successful Twin validation."""

    from .navigation_transition_validation_store import (
        get_default_navigation_transition_validation_store,
    )

    validation = (
        validate_materialized_navigation_transition(
            twin_key=twin_key,
            revision_id=revision_id,
            candidate_id=candidate_id,
            browser_runtime_service=(
                browser_runtime_service
            ),
            materialized_root=(
                materialized_root
            ),
            timeout_seconds=(
                timeout_seconds
            ),
            poll_interval_seconds=(
                poll_interval_seconds
            ),
        )
    )

    if (
        validation.get(
            "status"
        )
        != AUTO_TWIN_NAVIGATION_VALIDATION_TWIN_VALIDATED
    ):
        return {
            "status":
                validation.get(
                    "status"
                ),

            "recorded":
                False,

            "validation":
                validation,

            "persistence":
                None,
        }

    store = (
        validation_store
        or get_default_navigation_transition_validation_store()
    )

    persistence = (
        store.record_twin_validated(
            validation
        )
    )

    return {
        "status":
            AUTO_TWIN_NAVIGATION_VALIDATION_TWIN_VALIDATED,

        "recorded":
            True,

        "validation":
            validation,

        "persistence":
            persistence,
    }
