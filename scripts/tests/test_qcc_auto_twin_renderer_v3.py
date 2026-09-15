import pytest

from backend.qcc.auto_twin.materialization_builder import (
    AUTO_TWIN_RUNTIME_RENDERER_V3_VERSION,
    AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    _find_declarative_shadow_templates,
    _inject_shadow_adopted_stylesheets,
)


def _payload(
    *,
    roots,
    catalog,
):
    return {
        "frames": [
            {
                "frame_id": 0,
                "result": {
                    "shadow_roots":
                        roots,

                    "shadow_adopted_stylesheets":
                        catalog,
                },
            },
        ],
    }


def test_renderer_v3_version():
    assert (
        AUTO_TWIN_RUNTIME_RENDERER_V3_VERSION
        == 3
    )


def test_renderer_v3_injects_real_css_per_shadow_root():
    html = (
        "<html><body>"
        "<x-one>"
        '<template shadowrootmode="open">'
        "<span>one</span>"
        "</template>"
        "</x-one>"
        "<x-two>"
        '<template shadowrootmode="open">'
        "<button>two</button>"
        "</template>"
        "</x-two>"
        "</body></html>"
    )

    payload = _payload(
        roots=[
            {
                "host_tag":
                    "x-one",

                "adopted_stylesheet_refs":
                    [
                        "shadow-sheet-0001",
                    ],
            },
            {
                "host_tag":
                    "x-two",

                "adopted_stylesheet_refs":
                    [
                        "shadow-sheet-0001",
                        "shadow-sheet-0002",
                    ],
            },
        ],
        catalog=[
            {
                "stylesheet_id":
                    "shadow-sheet-0001",

                "readable":
                    True,

                "css_text":
                    ":host { color: red; }",
            },
            {
                "stylesheet_id":
                    "shadow-sheet-0002",

                "readable":
                    True,

                "css_text":
                    "button { border: 0; }",
            },
        ],
    )

    rendered, stats = (
        _inject_shadow_adopted_stylesheets(
            html,
            payload,
        )
    )

    assert (
        rendered.count(
            'data-qcc-adopted-stylesheet='
        )
        == 3
    )

    assert (
        rendered.count(
            'data-qcc-adopted-stylesheet="shadow-sheet-0001"'
        )
        == 2
    )

    assert (
        rendered.count(
            'data-qcc-adopted-stylesheet="shadow-sheet-0002"'
        )
        == 1
    )

    assert (
        ":host { color: red; }"
        in rendered
    )

    assert (
        "button { border: 0; }"
        in rendered
    )

    assert stats == {
        "evidence_available":
            True,

        "shadow_root_count":
            2,

        "template_count":
            2,

        "styled_shadow_root_count":
            2,

        "stylesheet_ref_count":
            3,

        "unique_stylesheet_count":
            2,

        "css_chars_injected":
            (
                len(
                    ":host { color: red; }"
                )
                * 2
                + len(
                    "button { border: 0; }"
                )
            ),
    }


def test_renderer_v3_preserves_reference_order():
    html = (
        "<x-one>"
        '<template shadowrootmode="open">'
        "<span>x</span>"
        "</template>"
        "</x-one>"
    )

    payload = _payload(
        roots=[
            {
                "host_tag":
                    "x-one",

                "adopted_stylesheet_refs":
                    [
                        "shadow-sheet-0002",
                        "shadow-sheet-0001",
                    ],
            },
        ],
        catalog=[
            {
                "stylesheet_id":
                    "shadow-sheet-0001",

                "readable":
                    True,

                "css_text":
                    ".one{}",
            },
            {
                "stylesheet_id":
                    "shadow-sheet-0002",

                "readable":
                    True,

                "css_text":
                    ".two{}",
            },
        ],
    )

    rendered, _ = (
        _inject_shadow_adopted_stylesheets(
            html,
            payload,
        )
    )

    assert (
        rendered.index(
            "shadow-sheet-0002"
        )
        < rendered.index(
            "shadow-sheet-0001"
        )
    )


def test_renderer_v3_old_capture_without_catalog_is_noop():
    html = (
        "<x-one>"
        '<template shadowrootmode="open">'
        "<span>x</span>"
        "</template>"
        "</x-one>"
    )

    payload = _payload(
        roots=[
            {
                "host_tag":
                    "x-one",
            },
        ],
        catalog=[],
    )

    rendered, stats = (
        _inject_shadow_adopted_stylesheets(
            html,
            payload,
        )
    )

    assert rendered == html
    assert (
        stats[
            "evidence_available"
        ]
        is False
    )


def test_renderer_v3_rejects_shadow_root_count_mismatch():
    html = (
        "<x-one>"
        '<template shadowrootmode="open">'
        "</template>"
        "</x-one>"
    )

    payload = _payload(
        roots=[
            {
                "host_tag":
                    "x-one",

                "adopted_stylesheet_refs":
                    [
                        "shadow-sheet-0001",
                    ],
            },
            {
                "host_tag":
                    "x-two",

                "adopted_stylesheet_refs":
                    [
                        "shadow-sheet-0001",
                    ],
            },
        ],
        catalog=[
            {
                "stylesheet_id":
                    "shadow-sheet-0001",

                "readable":
                    True,

                "css_text":
                    ":host{}",
            },
        ],
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_SHADOW_ROOT_COUNT_MISMATCH"
        ),
    ):
        _inject_shadow_adopted_stylesheets(
            html,
            payload,
        )


def test_renderer_v3_rejects_shadow_root_order_mismatch():
    html = (
        "<x-one>"
        '<template shadowrootmode="open">'
        "</template>"
        "</x-one>"
    )

    payload = _payload(
        roots=[
            {
                "host_tag":
                    "x-different",

                "adopted_stylesheet_refs":
                    [
                        "shadow-sheet-0001",
                    ],
            },
        ],
        catalog=[
            {
                "stylesheet_id":
                    "shadow-sheet-0001",

                "readable":
                    True,

                "css_text":
                    ":host{}",
            },
        ],
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_SHADOW_ROOT_ORDER_MISMATCH"
        ),
    ):
        _inject_shadow_adopted_stylesheets(
            html,
            payload,
        )


def test_renderer_v3_rejects_unknown_stylesheet_ref():
    html = (
        "<x-one>"
        '<template shadowrootmode="open">'
        "</template>"
        "</x-one>"
    )

    payload = _payload(
        roots=[
            {
                "host_tag":
                    "x-one",

                "adopted_stylesheet_refs":
                    [
                        "shadow-sheet-9999",
                    ],
            },
        ],
        catalog=[
            {
                "stylesheet_id":
                    "shadow-sheet-0001",

                "readable":
                    True,

                "css_text":
                    ":host{}",
            },
        ],
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_SHADOW_STYLESHEET_REF_INVALID"
        ),
    ):
        _inject_shadow_adopted_stylesheets(
            html,
            payload,
        )


def test_renderer_v3_skips_unreadable_or_empty_stylesheets():
    html = (
        "<x-one>"
        '<template shadowrootmode="open">'
        "</template>"
        "</x-one>"
    )

    payload = _payload(
        roots=[
            {
                "host_tag":
                    "x-one",

                "adopted_stylesheet_refs":
                    [
                        "shadow-sheet-0001",
                        "shadow-sheet-0002",
                    ],
            },
        ],
        catalog=[
            {
                "stylesheet_id":
                    "shadow-sheet-0001",

                "readable":
                    False,

                "css_text":
                    ".forbidden{}",
            },
            {
                "stylesheet_id":
                    "shadow-sheet-0002",

                "readable":
                    True,

                "css_text":
                    "",
            },
        ],
    )

    rendered, stats = (
        _inject_shadow_adopted_stylesheets(
            html,
            payload,
        )
    )

    assert (
        "data-qcc-adopted-stylesheet"
        not in rendered
    )

    assert (
        stats[
            "stylesheet_ref_count"
        ]
        == 2
    )

    assert (
        stats[
            "styled_shadow_root_count"
        ]
        == 0
    )


def test_renderer_v3_escapes_literal_style_close():
    html = (
        "<x-one>"
        '<template shadowrootmode="open">'
        "</template>"
        "</x-one>"
    )

    payload = _payload(
        roots=[
            {
                "host_tag":
                    "x-one",

                "adopted_stylesheet_refs":
                    [
                        "shadow-sheet-0001",
                    ],
            },
        ],
        catalog=[
            {
                "stylesheet_id":
                    "shadow-sheet-0001",

                "readable":
                    True,

                "css_text":
                    'a::after{content:"</style>";}',
            },
        ],
    )

    rendered, _ = (
        _inject_shadow_adopted_stylesheets(
            html,
            payload,
        )
    )

    assert (
        'content:"<\\/style>";'
        in rendered
    )



def test_renderer_v3_many_shadow_roots_preserve_order():
    root_count = 100

    html = (
        "<html><body>"
        + "".join(
            (
                f"<x-item-{index}>"
                '<template shadowrootmode="open">'
                f"<span>{index}</span>"
                "</template>"
                f"</x-item-{index}>"
            )
            for index in range(
                root_count
            )
        )
        + "</body></html>"
    )

    roots = []
    catalog = []

    for index in range(
        root_count
    ):
        stylesheet_id = (
            f"shadow-sheet-{index:04d}"
        )

        roots.append({
            "host_tag":
                f"x-item-{index}",

            "adopted_stylesheet_refs":
                [
                    stylesheet_id,
                ],
        })

        catalog.append({
            "stylesheet_id":
                stylesheet_id,

            "readable":
                True,

            "css_text":
                (
                    f":host{{--qcc-index:{index};}}"
                ),
        })

    rendered, stats = (
        _inject_shadow_adopted_stylesheets(
            html,
            _payload(
                roots=roots,
                catalog=catalog,
            ),
        )
    )

    assert (
        stats[
            "shadow_root_count"
        ]
        == root_count
    )

    assert (
        stats[
            "template_count"
        ]
        == root_count
    )

    assert (
        stats[
            "stylesheet_ref_count"
        ]
        == root_count
    )

    assert (
        rendered.count(
            "data-qcc-adopted-stylesheet="
        )
        == root_count
    )

    positions = [
        rendered.index(
            f'data-qcc-adopted-stylesheet="shadow-sheet-{index:04d}"'
        )
        for index in range(
            root_count
        )
    ]

    assert positions == sorted(
        positions
    )



def test_renderer_v3_linear_dsd_scanner():
    html = (
        "<html><body>"
        "<x-one data-value='a'>"
        '<template shadowrootmode="open">'
        "<span>one</span>"
        "</template>"
        "</x-one>"
        "<x-two>"
        "   <!-- hydration marker -->   "
        "<template data-x='1' shadowrootmode='open'>"
        "<span>two</span>"
        "</template>"
        "</x-two>"
        "<template id='ordinary-template'>x</template>"
        "</body></html>"
    )

    matches = (
        _find_declarative_shadow_templates(
            html
        )
    )

    assert len(
        matches
    ) == 2

    assert [
        item[
            "host"
        ]
        for item in matches
    ] == [
        "x-one",
        "x-two",
    ]

    for item in matches:
        assert (
            html[
                item[
                    "template_start"
                ]:
                item[
                    "template_end"
                ]
            ]
            .lower()
            .startswith(
                "<template"
            )
        )


def test_renderer_v3_linear_dsd_scanner_handles_many_roots():
    count = 1000

    html = (
        "<body>"
        + "".join(
            (
                f"<x-{index}>"
                '<template shadowrootmode="open">'
                f"<span>{index}</span>"
                "</template>"
                f"</x-{index}>"
            )
            for index in range(
                count
            )
        )
        + "</body>"
    )

    matches = (
        _find_declarative_shadow_templates(
            html
        )
    )

    assert len(
        matches
    ) == count

    assert (
        matches[
            0
        ][
            "host"
        ]
        == "x-0"
    )

    assert (
        matches[
            -1
        ][
            "host"
        ]
        == "x-999"
    )
