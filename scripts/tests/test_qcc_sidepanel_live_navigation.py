from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

HTML = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "sidepanel"
    / "index.html"
)

JS = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "sidepanel"
    / "sidepanel.js"
)

CSS = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "sidepanel"
    / "sidepanel.css"
)


def test_navigation_surface_exists():
    html = HTML.read_text(
        encoding="utf-8"
    )

    for element_id in (
        "qcc-live-navigation",
        "navigation-title",
        "navigation-current",
        "navigation-target",
        "navigation-route",
        "navigation-next-step",
        "navigation-decision",
        "navigation-instruction",
    ):
        assert (
            f'id="{element_id}"'
            in html
        )


def test_context_renders_live_navigation():
    js = JS.read_text(
        encoding="utf-8"
    )

    assert (
        "function renderLiveNavigation("
        in js
    )

    assert (
        "payload.live_navigation"
        in js
    )

    assert (
        "payload.active_session.session_id"
        in js
    )


def test_navigation_renderer_is_session_bound():
    js = JS.read_text(
        encoding="utf-8"
    )

    start = js.index(
        "function renderLiveNavigation("
    )

    end = js.index(
        "function renderContext(",
        start,
    )

    block = js[
        start:end
    ]

    assert (
        "navigation.session_id"
        in block
    )

    assert (
        "activeSessionId"
        in block
    )


def test_navigation_renderer_is_provider_agnostic():
    js = JS.read_text(
        encoding="utf-8"
    )

    start = js.index(
        "function renderLiveNavigation("
    )

    end = js.index(
        "function renderContext(",
        start,
    )

    block = js[
        start:end
    ].upper()

    forbidden = (
        "MERCURIO",
        "ICP_PLUS",
        "DEHU",
        "SELENIUMBASE_ASSISTED",
        "DESKTOP_GUI_ASSISTED",
    )

    for literal in forbidden:
        assert literal not in block


def test_navigation_renderer_does_not_execute_actions():
    js = JS.read_text(
        encoding="utf-8"
    )

    start = js.index(
        "function renderLiveNavigation("
    )

    end = js.index(
        "function renderContext(",
        start,
    )

    block = js[
        start:end
    ]

    forbidden = (
        "submitSessionAction(",
        "postJson(",
        ".click(",
        "executeScript",
        "inspectActiveTabDom",
    )

    for literal in forbidden:
        assert literal not in block


def test_governance_states_are_visual_only():
    js = JS.read_text(
        encoding="utf-8"
    )

    for decision in (
        "HUMAN_ONLY",
        "AUTOMATION_ALLOWED",
        "DENY",
        "NO_ACTION_REQUIRED",
        "OBSERVE_ONLY",
    ):
        assert decision in js


def test_navigation_styles_exist():
    css = CSS.read_text(
        encoding="utf-8"
    )

    assert (
        ".qcc-navigation {"
        in css
    )

    assert (
        ".qcc-navigation-decision--human-only"
        in css
    )

    assert (
        ".qcc-navigation-decision--automation-allowed"
        in css
    )

    assert (
        ".qcc-navigation-decision--deny"
        in css
    )
