"""Unit tests for CONTROL_APPEARED fragment extraction/minimization.

Pure coverage of ``backend.qcc.auto_twin.control_appeared_fragment``.
No browser, no REAL site.
"""

from __future__ import annotations

from backend.qcc.auto_twin.control_appeared_fragment import (
    FRAGMENT_STATUS_CAPTURED,
    FRAGMENT_STATUS_UNRESOLVED,
    build_control_appeared_fragment,
)


def _page(body):
    return "<html><body>" + body + "</body></html>"


# ---------------------------------------------------------------------------
# Target-only extraction (no full-page/frame HTML persistence)
# ---------------------------------------------------------------------------


def test_extracts_only_appeared_subtree_not_whole_page():
    after_html = _page(
        '<div id="unrelated-sibling">untouched content here</div>'
        '<div id="new-panel"><span>Appeared</span></div>'
    )

    result = build_control_appeared_fragment(
        after_html=after_html,
        selector="#new-panel",
    )

    assert result["status"] == FRAGMENT_STATUS_CAPTURED
    assert "new-panel" in result["html"]
    assert "unrelated-sibling" not in result["html"]
    assert "<body>" not in result["html"]
    assert "<html>" not in result["html"]


def test_fragment_html_is_the_exact_matched_subtree():
    after_html = _page(
        '<div id="new-panel" class="panel">'
        '<label for="x">Nombre</label>'
        "</div>"
    )

    result = build_control_appeared_fragment(
        after_html=after_html,
        selector="#new-panel",
    )

    assert result["status"] == FRAGMENT_STATUS_CAPTURED
    assert result["html"].startswith('<div id="new-panel"')
    assert "Nombre" in result["html"]


# ---------------------------------------------------------------------------
# Runtime value minimization
# ---------------------------------------------------------------------------


def test_text_input_value_is_removed():
    after_html = _page(
        '<div id="new-panel">'
        '<input id="f" type="text" name="f" value="super-secret-pii">'
        "</div>"
    )

    result = build_control_appeared_fragment(
        after_html=after_html,
        selector="#new-panel",
    )

    assert "super-secret-pii" not in result["html"]
    assert 'id="f"' in result["html"]


def test_textarea_runtime_contents_removed():
    after_html = _page(
        '<div id="new-panel">'
        '<textarea name="notes">typed confidential notes</textarea>'
        "</div>"
    )

    result = build_control_appeared_fragment(
        after_html=after_html,
        selector="#new-panel",
    )

    assert "typed confidential notes" not in result["html"]
    assert "<textarea" in result["html"]


def test_checkbox_checked_state_removed():
    after_html = _page(
        '<div id="new-panel">'
        '<input type="checkbox" name="agree" value="yes" checked>'
        "</div>"
    )

    result = build_control_appeared_fragment(
        after_html=after_html,
        selector="#new-panel",
    )

    assert "checked" not in result["html"]
    # Static option identity (not a runtime literal) is preserved.
    assert 'value="yes"' in result["html"]


def test_radio_checked_state_removed():
    after_html = _page(
        '<div id="new-panel">'
        '<input type="radio" name="opt" value="a" checked>'
        "</div>"
    )

    result = build_control_appeared_fragment(
        after_html=after_html,
        selector="#new-panel",
    )

    assert "checked" not in result["html"]


def test_select_option_selected_state_removed():
    after_html = _page(
        '<div id="new-panel">'
        "<select>"
        '<option value="a" selected>A</option>'
        '<option value="b">B</option>'
        "</select>"
        "</div>"
    )

    result = build_control_appeared_fragment(
        after_html=after_html,
        selector="#new-panel",
    )

    assert "selected" not in result["html"]


def test_contenteditable_runtime_content_removed():
    after_html = _page(
        '<div id="new-panel">'
        '<p contenteditable="true">user typed this live</p>'
        "</div>"
    )

    result = build_control_appeared_fragment(
        after_html=after_html,
        selector="#new-panel",
    )

    assert "user typed this live" not in result["html"]
    assert 'contenteditable="true"' in result["html"]


def test_static_button_value_label_preserved():
    after_html = _page(
        '<div id="new-panel">'
        '<input type="submit" value="Enviar">'
        "</div>"
    )

    result = build_control_appeared_fragment(
        after_html=after_html,
        selector="#new-panel",
    )

    assert 'value="Enviar"' in result["html"]


# ---------------------------------------------------------------------------
# Executable/network authority sterilization (reused, not duplicated)
# ---------------------------------------------------------------------------


def test_inline_script_neutralized():
    after_html = _page(
        '<div id="new-panel">'
        "<script>stealSessionCookies();</script>"
        "</div>"
    )

    result = build_control_appeared_fragment(
        after_html=after_html,
        selector="#new-panel",
    )

    assert "stealSessionCookies" not in result["html"]


def test_event_handler_attribute_removed():
    after_html = _page(
        '<div id="new-panel">'
        '<img src="/local.png" onerror="evil()">'
        "</div>"
    )

    result = build_control_appeared_fragment(
        after_html=after_html,
        selector="#new-panel",
    )

    assert "onerror" not in result["html"]


def test_external_resource_reference_neutralized():
    after_html = _page(
        '<div id="new-panel">'
        '<img src="https://real.example.test/x.png">'
        "</div>"
    )

    result = build_control_appeared_fragment(
        after_html=after_html,
        selector="#new-panel",
    )

    assert "https://real.example.test" not in result["html"]


def test_javascript_url_neutralized():
    after_html = _page(
        '<div id="new-panel">'
        '<a href="javascript:doEvil()">Click</a>'
        "</div>"
    )

    result = build_control_appeared_fragment(
        after_html=after_html,
        selector="#new-panel",
    )

    assert "javascript:" not in result["html"]


# ---------------------------------------------------------------------------
# Fail-closed resolution
# ---------------------------------------------------------------------------


def test_unresolved_when_selector_not_found():
    after_html = _page('<div id="other"></div>')

    result = build_control_appeared_fragment(
        after_html=after_html,
        selector="#new-panel",
    )

    assert result == {
        "status": FRAGMENT_STATUS_UNRESOLVED,
        "html": None,
    }


def test_unresolved_when_selector_is_ambiguous():
    after_html = _page(
        '<div class="dup">A</div><div class="dup">B</div>'
    )

    result = build_control_appeared_fragment(
        after_html=after_html,
        selector=".dup",
    )

    assert result["status"] == FRAGMENT_STATUS_UNRESOLVED


def test_unresolved_on_unsupported_selector_syntax():
    after_html = _page('<div id="new-panel"></div>')

    result = build_control_appeared_fragment(
        after_html=after_html,
        selector='div[onclick="f()"]:qcc-nth-onclick(1)',
    )

    assert result["status"] == FRAGMENT_STATUS_UNRESOLVED


def test_unresolved_on_empty_after_html():
    result = build_control_appeared_fragment(
        after_html="",
        selector="#new-panel",
    )

    assert result["status"] == FRAGMENT_STATUS_UNRESOLVED


def test_unresolved_on_empty_selector():
    result = build_control_appeared_fragment(
        after_html=_page('<div id="new-panel"></div>'),
        selector="",
    )

    assert result["status"] == FRAGMENT_STATUS_UNRESOLVED


def test_unresolved_on_non_string_after_html():
    result = build_control_appeared_fragment(
        after_html=None,
        selector="#new-panel",
    )

    assert result["status"] == FRAGMENT_STATUS_UNRESOLVED


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_result_is_deterministic_across_calls():
    after_html = _page(
        '<div id="new-panel">'
        '<input type="text" value="x">'
        "</div>"
    )

    first = build_control_appeared_fragment(
        after_html=after_html,
        selector="#new-panel",
    )

    second = build_control_appeared_fragment(
        after_html=after_html,
        selector="#new-panel",
    )

    assert first == second
