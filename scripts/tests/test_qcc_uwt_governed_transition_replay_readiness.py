"""Regression tests for the generic UWT governed replay readiness
contract (R5B): bounded, non-sleeping waits for context/trigger DOM
candidate readiness, used by
``test_qcc_uwt_governed_transition_replay_certification``.

No real browser, no Mercurio: a fake service double stands in for
``TwinBrowserRuntimeService.execute_script`` so these tests are fast
and deterministic.
"""

from __future__ import annotations

import time

import pytest

from test_qcc_uwt_governed_transition_replay_certification import (
    _resolve_trigger_requirement,
    _wait_for_runtime_entry,
    _wait_for_selector_ready,
)


class FakeReadinessService:
    """Returns one entry of ``count_sequence`` per ``execute_script``
    call (last entry repeats once exhausted). Never starts a real
    browser and never re-navigates -- a whole-transition retry would
    show up as an unexpected ``start`` call, which this double does
    not even expose."""

    def __init__(self, count_sequence):
        self.count_sequence = list(count_sequence)
        self.calls = 0

    def execute_script(self, *, twin_key, script, args=None):
        self.calls += 1

        index = min(self.calls - 1, len(self.count_sequence) - 1)

        return self.count_sequence[index]


def _fast(monkeypatch):
    """Collapses the poll interval so bounded-wait tests run in
    milliseconds instead of real seconds."""

    import test_qcc_uwt_governed_transition_replay_certification as mod

    monkeypatch.setattr(mod, "_POLL_INTERVAL_SECONDS", 0.001)


def test_context_selector_already_available_is_immediate_pass(monkeypatch):
    _fast(monkeypatch)

    service = FakeReadinessService([1])

    count = _wait_for_selector_ready(
        service,
        twin_key="t",
        selector="input[name=x]",
        required_count=1,
        timeout=5.0,
    )

    assert count == 1
    assert service.calls == 1


def test_context_selector_appears_after_bounded_delay(monkeypatch):
    _fast(monkeypatch)

    service = FakeReadinessService([0, 0, 1])

    count = _wait_for_selector_ready(
        service,
        twin_key="t",
        selector="input[name=x]",
        required_count=1,
        timeout=5.0,
    )

    assert count == 1
    assert service.calls == 3


def test_context_selector_never_appears_bounded_timeout(monkeypatch):
    _fast(monkeypatch)

    service = FakeReadinessService([0])

    with pytest.raises(AssertionError, match="QCC_UWT_REPLAY_SELECTOR_NOT_READY"):
        _wait_for_selector_ready(
            service,
            twin_key="t",
            selector="input[name=x]",
            required_count=1,
            timeout=0.05,
        )

    # Bounded: polled more than once but did not hang/retry forever.
    assert service.calls > 1


def test_trigger_selector_already_available_is_immediate_pass(monkeypatch):
    _fast(monkeypatch)

    service = FakeReadinessService([1])

    count = _wait_for_selector_ready(
        service,
        twin_key="t",
        selector='a[onclick="continuar();"]',
        required_count=1,
        timeout=5.0,
    )

    assert count == 1
    assert service.calls == 1


def test_trigger_selector_appears_after_bounded_delay(monkeypatch):
    _fast(monkeypatch)

    service = FakeReadinessService([0, 1])

    count = _wait_for_selector_ready(
        service,
        twin_key="t",
        selector='a[onclick="continuar();"]',
        required_count=1,
        timeout=5.0,
    )

    assert count == 1
    assert service.calls == 2


def test_trigger_selector_never_appears_bounded_timeout(monkeypatch):
    _fast(monkeypatch)

    service = FakeReadinessService([0])

    with pytest.raises(AssertionError, match="QCC_UWT_REPLAY_SELECTOR_NOT_READY"):
        _wait_for_selector_ready(
            service,
            twin_key="t",
            selector='a[onclick="continuar();"]',
            required_count=1,
            timeout=0.05,
        )


def test_resolve_trigger_requirement_plain_selector():
    base, required = _resolve_trigger_requirement(
        'a[onclick="continuar();"]'
    )

    assert base == 'a[onclick="continuar();"]'
    assert required == 1


def test_resolve_trigger_requirement_positional_selector():
    base, required = _resolve_trigger_requirement(
        'a[onclick="validarYEnviar()"]:qcc-nth-onclick(5)'
    )

    assert base == 'a[onclick="validarYEnviar()"]'
    assert required == 5


def test_qcc_nth_candidate_population_evolves_1_to_3_to_5(monkeypatch):
    _fast(monkeypatch)

    service = FakeReadinessService([1, 3, 5])

    base, required = _resolve_trigger_requirement(
        'a[onclick="validarYEnviar()"]:qcc-nth-onclick(5)'
    )

    count = _wait_for_selector_ready(
        service,
        twin_key="t",
        selector=base,
        required_count=required,
        timeout=5.0,
    )

    assert count == 5
    assert service.calls == 3


def test_qcc_nth_5_not_ready_below_5_candidates(monkeypatch):
    _fast(monkeypatch)

    # Population only ever reaches 4 -- position 5 can never resolve.
    service = FakeReadinessService([1, 3, 4])

    base, required = _resolve_trigger_requirement(
        'a[onclick="validarYEnviar()"]:qcc-nth-onclick(5)'
    )

    with pytest.raises(AssertionError, match="QCC_UWT_REPLAY_SELECTOR_NOT_READY"):
        _wait_for_selector_ready(
            service,
            twin_key="t",
            selector=base,
            required_count=required,
            timeout=0.05,
        )


class FakeTargetRecognitionService:
    def __init__(self, href_sequence):
        self.href_sequence = list(href_sequence)
        self.calls = 0

    def execute_script(self, *, twin_key, script):
        self.calls += 1

        index = min(self.calls - 1, len(self.href_sequence) - 1)

        return self.href_sequence[index]


def test_target_state_recognition_remains_strict_on_exact_entry(monkeypatch):
    import test_qcc_uwt_governed_transition_replay_certification as mod

    monkeypatch.setattr(mod, "_POLL_INTERVAL_SECONDS", 0.001)

    service = FakeTargetRecognitionService(
        [
            "http://127.0.0.1:1/states/00-OTHER/runtime/index.html",
            "http://127.0.0.1:1/states/01-TARGET/runtime/index.html",
        ]
    )

    landed = _wait_for_runtime_entry(
        service,
        twin_key="t",
        expected_entry="states/01-TARGET/runtime/index.html",
        timeout=5.0,
    )

    assert "states/01-TARGET" in landed


def test_target_state_recognition_bounded_timeout_when_never_reached(monkeypatch):
    import test_qcc_uwt_governed_transition_replay_certification as mod

    monkeypatch.setattr(mod, "_POLL_INTERVAL_SECONDS", 0.001)

    service = FakeTargetRecognitionService(
        ["http://127.0.0.1:1/states/00-OTHER/runtime/index.html"]
    )

    with pytest.raises(AssertionError, match="QCC_UWT_REPLAY_TARGET_NOT_REACHED"):
        _wait_for_runtime_entry(
            service,
            twin_key="t",
            expected_entry="states/01-TARGET/runtime/index.html",
            timeout=0.05,
        )


def test_no_whole_transition_retry_surface_on_readiness_wait(monkeypatch):
    """``_wait_for_selector_ready`` only ever calls ``execute_script``
    (a read-only probe); it has no access to -- and therefore cannot
    call -- ``start``/navigate again. The fake double below does not
    even implement ``start``, so any such call would raise
    AttributeError instead of silently retrying the transition."""

    _fast(monkeypatch)

    service = FakeReadinessService([0, 0, 0, 1])

    count = _wait_for_selector_ready(
        service,
        twin_key="t",
        selector="input[name=x]",
        required_count=1,
        timeout=5.0,
    )

    assert count == 1
    assert service.calls == 4
    assert not hasattr(service, "start")
