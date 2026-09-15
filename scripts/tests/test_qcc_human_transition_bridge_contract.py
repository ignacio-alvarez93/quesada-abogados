from pathlib import Path


def test_bridge_correlates_b_without_knowledge_write():
    text = Path(
        "backend/qcc/bridge/server.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "correlate_observed_human_transition"
        in text
    )

    assert (
        '"human_transition_evidence"'
        in text
    )

    join_start = text.index(
        "# HUMAN CAUSAL JOIN"
    )

    join_end = text.index(
        "# CANONICAL LIVE ACTION EVIDENCE",
        join_start,
    )

    block = text[
        join_start:
        join_end
    ]

    assert (
        "record_transition("
        not in block
    )

    assert (
        "NavigationKnowledge"
        in block
    )

    assert (
        "click("
        not in block
    )


def test_context_store_keeps_transition_runtime_only():
    text = Path(
        "backend/qcc/context/store.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "_observed_human_transition"
        in text
    )

    snapshot_start = text.index(
        "    def snapshot("
    )

    snapshot = text[
        snapshot_start:
    ]

    assert (
        '"observed_human_transition"'
        not in snapshot
    )
