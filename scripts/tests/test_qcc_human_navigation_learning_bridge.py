from pathlib import Path

from backend.qcc.bridge.server import (
    QccBridgeServer,
)

from backend.qcc.navigation_learning import (
    HumanNavigationCandidateStore,
)


ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

SERVER = (
    ROOT
    / "backend"
    / "qcc"
    / "bridge"
    / "server.py"
)


def test_bridge_owns_injected_human_candidate_store(
    tmp_path,
):
    candidates = (
        HumanNavigationCandidateStore(
            root=tmp_path
        )
    )

    bridge = QccBridgeServer(
        port=0,
        human_navigation_candidate_store=(
            candidates
        ),
    )

    try:
        assert (
            bridge
            .human_navigation_candidate_store
            is candidates
        )

    finally:
        bridge.close()


def test_bridge_wires_learning_after_human_causal_join():
    source = SERVER.read_text(
        encoding="utf-8"
    )

    causal = source.index(
        "correlate_observed_human_transition("
    )

    learning = source.index(
        "process_observed_human_navigation_learning("
    )

    planning = source.index(
        "refresh_live_navigation_plan(",
        learning,
    )

    assert (
        causal
        < learning
        < planning
    )


def test_bridge_learning_failure_is_capture_fail_open():
    source = SERVER.read_text(
        encoding="utf-8"
    )

    learning = source.index(
        "process_observed_human_navigation_learning("
    )

    tail = source[
        learning:
        learning + 3500
    ]

    assert (
        "LEARNING_FAIL_CLOSED"
        in tail
    )

    assert (
        "OSError"
        in tail
    )

    assert (
        "ValueError"
        in tail
    )


def test_bridge_runtime_learning_never_grants_automation():
    source = SERVER.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "# TRUSTED HUMAN NAVIGATION LEARNING"
    )

    end = source.index(
        "human_listener_plan = None",
        start,
    )

    block = source[
        start:end
    ]

    assert (
        "AUTOMATION_ALLOWED"
        not in block
    )

    assert (
        ".click("
        not in block
    )

    assert (
        "click_js("
        not in block
    )
