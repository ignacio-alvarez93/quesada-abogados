"""QCC_BRANCH_CONTEXT_CAPTURE_V1 core translator regression suite.

Covers backend.qcc.universal_web.branch_context_capture
.build_branch_context_from_resolved_navigation_branch(): the pure
translation from one already-governed CONTEXTUAL_RESOLVED branch
record into a UWT-4 BranchContext. No site/provider-specific literal
is used on purpose (genericity must not depend on any real customer).
"""

from pathlib import Path

from backend.qcc.universal_web.branch_context_capture import (
    build_branch_context_from_resolved_navigation_branch,
)


ROOT = Path(__file__).resolve().parents[2]

CORE_MODULE = (
    ROOT
    / "backend"
    / "qcc"
    / "universal_web"
    / "branch_context_capture.py"
)


def _entry(
    *,
    key="ROUTE",
    kind="RADIO",
    selected_values=("130",),
    frame_path="main",
    selector="input[name=route]",
):
    return {
        "key": key,
        "selector": selector,
        "frame_path": frame_path,
        "kind": kind,
        "selected_values": list(selected_values),
    }


def _branch(entries):
    return {
        "context_signature": "irrelevant-opaque-hash",
        "navigation_context": list(entries),
        "after_fingerprint": "b" * 64,
        "candidate_ids": ["candidate-1"],
        "real_observation_count": 1,
    }


# ---------------------------------------------------------------------------
# 1. raw navigation_context alone cannot create branch authority.
# ---------------------------------------------------------------------------


def test_raw_navigation_context_list_alone_cannot_create_branch_context():
    raw_navigation_context = [_entry()]

    # Handing the translator the bare navigation_context list itself
    # (not a resolved branch record carrying it) must never be
    # interpreted as branch authority.
    assert (
        build_branch_context_from_resolved_navigation_branch(
            raw_navigation_context
        )
        is None
    )


# ---------------------------------------------------------------------------
# 2. translator only consumes explicitly resolved branch input.
# ---------------------------------------------------------------------------


def test_translator_requires_explicit_branch_shape():
    assert (
        build_branch_context_from_resolved_navigation_branch(None)
        is None
    )

    assert (
        build_branch_context_from_resolved_navigation_branch({})
        is None
    )

    assert (
        build_branch_context_from_resolved_navigation_branch(
            {"navigation_context": []}
        )
        is None
    )

    assert (
        build_branch_context_from_resolved_navigation_branch(
            {"navigation_context": "not-a-list"}
        )
        is None
    )


# ---------------------------------------------------------------------------
# 3-5. one discriminator per supported singleton control family.
# ---------------------------------------------------------------------------


def test_select_singleton_yields_deterministic_discriminator():
    branch = _branch([
        _entry(kind="SELECT", selected_values=("EXPRESS",))
    ])

    context = build_branch_context_from_resolved_navigation_branch(
        branch
    )

    assert context is not None
    assert len(context.discriminators) == 1
    assert context.discriminators[0].kind == "SELECT"
    assert context.discriminators[0].active_value == "EXPRESS"


def test_radio_singleton_yields_deterministic_discriminator():
    branch = _branch([
        _entry(kind="RADIO", selected_values=("130",))
    ])

    context = build_branch_context_from_resolved_navigation_branch(
        branch
    )

    assert context is not None
    assert len(context.discriminators) == 1
    assert context.discriminators[0].kind == "RADIO"
    assert context.discriminators[0].active_value == "130"


def test_tab_singleton_yields_deterministic_discriminator():
    branch = _branch([
        _entry(kind="TAB", selected_values=("SECOND",))
    ])

    context = build_branch_context_from_resolved_navigation_branch(
        branch
    )

    assert context is not None
    assert len(context.discriminators) == 1
    assert context.discriminators[0].kind == "TAB"
    assert context.discriminators[0].active_value == "SECOND"


# ---------------------------------------------------------------------------
# 6. unsupported/default DISCRETE kind fails closed.
# ---------------------------------------------------------------------------


def test_unsupported_discrete_kind_fails_closed():
    branch = _branch([
        _entry(kind="DISCRETE", selected_values=("X",))
    ])

    assert (
        build_branch_context_from_resolved_navigation_branch(branch)
        is None
    )

    missing_kind = _branch([
        {
            "key": "ROUTE",
            "selector": None,
            "frame_path": "main",
            "selected_values": ["X"],
        }
    ])

    assert (
        build_branch_context_from_resolved_navigation_branch(
            missing_kind
        )
        is None
    )


# ---------------------------------------------------------------------------
# 7. ambiguous multi-value fails closed.
# ---------------------------------------------------------------------------


def test_ambiguous_multi_value_fails_closed():
    branch = _branch([
        _entry(
            kind="RADIO",
            selected_values=("130", "131"),
        )
    ])

    assert (
        build_branch_context_from_resolved_navigation_branch(branch)
        is None
    )

    empty_values = _branch([
        _entry(kind="RADIO", selected_values=())
    ])

    assert (
        build_branch_context_from_resolved_navigation_branch(
            empty_values
        )
        is None
    )


# ---------------------------------------------------------------------------
# 8. order independence.
# ---------------------------------------------------------------------------


def test_order_independence_yields_identical_context_id():
    entry_a = _entry(
        key="ROUTE",
        kind="RADIO",
        selected_values=("130",),
    )

    entry_b = _entry(
        key="ACCEPT",
        kind="CHECKBOX",
        selected_values=("CHECKED",),
    )

    forward = build_branch_context_from_resolved_navigation_branch(
        _branch([entry_a, entry_b])
    )

    backward = build_branch_context_from_resolved_navigation_branch(
        _branch([entry_b, entry_a])
    )

    assert forward is not None
    assert backward is not None
    assert forward.context_id == backward.context_id


# ---------------------------------------------------------------------------
# 9. multiple valid discriminators compose deterministically.
# ---------------------------------------------------------------------------


def test_multiple_valid_discriminators_compose():
    branch = _branch([
        _entry(
            key="ROUTE",
            kind="RADIO",
            selected_values=("130",),
        ),
        _entry(
            key="ACCEPT",
            kind="CHECKBOX",
            selected_values=("CHECKED",),
        ),
    ])

    context = build_branch_context_from_resolved_navigation_branch(
        branch
    )

    assert context is not None
    assert len(context.discriminators) == 2
    assert {
        discriminator.kind
        for discriminator in context.discriminators
    } == {"RADIO", "CHECKBOX"}


# ---------------------------------------------------------------------------
# 10. conflicting discriminator fails closed.
# ---------------------------------------------------------------------------


def test_conflicting_discriminator_fails_closed():
    # Same frame_path + key (hence same control identity) reported
    # with two different kinds/active values: an irreconcilable
    # conflict, never silently resolved by picking one.
    branch = _branch([
        _entry(
            key="ROUTE",
            kind="RADIO",
            selected_values=("130",),
        ),
        _entry(
            key="ROUTE",
            kind="SELECT",
            selected_values=("131",),
        ),
    ])

    assert (
        build_branch_context_from_resolved_navigation_branch(branch)
        is None
    )


# ---------------------------------------------------------------------------
# 11. frame-aware control identity deterministic.
# ---------------------------------------------------------------------------


def test_frame_aware_control_identity_is_deterministic():
    main_frame = build_branch_context_from_resolved_navigation_branch(
        _branch([
            _entry(
                key="ROUTE",
                kind="RADIO",
                selected_values=("130",),
                frame_path="main",
            )
        ])
    )

    iframe = build_branch_context_from_resolved_navigation_branch(
        _branch([
            _entry(
                key="ROUTE",
                kind="RADIO",
                selected_values=("130",),
                frame_path="main>iframe#checkout",
            )
        ])
    )

    repeat_main_frame = (
        build_branch_context_from_resolved_navigation_branch(
            _branch([
                _entry(
                    key="ROUTE",
                    kind="RADIO",
                    selected_values=("130",),
                    frame_path="main",
                )
            ])
        )
    )

    assert main_frame is not None
    assert iframe is not None
    assert repeat_main_frame is not None

    # Same key in a different frame is a different control identity.
    assert main_frame.context_id != iframe.context_id

    # Same frame + key reproduces the exact same identity.
    assert main_frame.context_id == repeat_main_frame.context_id


# ---------------------------------------------------------------------------
# 12. no provider/site-specific strings in core.
# ---------------------------------------------------------------------------


def test_core_translator_source_has_no_provider_specific_literals():
    source = CORE_MODULE.read_text(encoding="utf-8")

    forbidden = (
        "MERCURIO",
        "RED_SARA",
        "QUESADA",
        "TITULAR",
        "EX01",
        "EX02",
    )

    for literal in forbidden:
        assert literal not in source


def test_core_translator_does_not_import_auto_twin():
    source = CORE_MODULE.read_text(encoding="utf-8")

    import_lines = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith(("import ", "from "))
    ]

    assert not any(
        "auto_twin" in line
        for line in import_lines
    )
