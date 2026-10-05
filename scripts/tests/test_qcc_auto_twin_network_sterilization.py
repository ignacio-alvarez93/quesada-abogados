import hashlib
from email import policy
from email.message import EmailMessage
from pathlib import Path

from backend.qcc.auto_twin.materialization_builder import (
    _NETWORK_GUARD,
    materialize_auto_twin_plan,
)

from backend.qcc.auto_twin.materialization_plan import (
    AUTO_TWIN_MATERIALIZATION_PLAN_TYPE,
)

from backend.qcc.auto_twin.runtime_network_sterilization import (
    AUTO_TWIN_NETWORK_STERILIZER_VERSION,
    sterilize_runtime_html,
)


def test_sterilizer_is_versioned():
    assert (
        AUTO_TWIN_NETWORK_STERILIZER_VERSION
        == 4
    )


def test_remote_base_becomes_local():
    html, stats = sterilize_runtime_html(
        '<html><head>'
        '<base href="https://example.invalid/app/">'
        '</head></html>'
    )

    assert (
        '<base href="./" '
        'data-qcc-auto-twin-network-sterilized="1">'
        in html
    )

    assert (
        "example.invalid"
        not in html
    )

    assert (
        stats[
            "base_tags_rewritten"
        ]
        == 1
    )


def test_remote_resource_links_are_removed():
    html, stats = sterilize_runtime_html(
        '<link rel="manifest" '
        'href="https://example.invalid/site.webmanifest">'
        '<link rel="modulepreload" '
        'href="//example.invalid/chunk.js">'
        '<link rel="stylesheet" href="assets/local.css">'
    )

    assert (
        "site.webmanifest"
        not in html
    )

    assert (
        "chunk.js"
        not in html
    )

    assert (
        'href="assets/local.css"'
        in html
    )

    assert (
        stats[
            "external_link_tags_removed"
        ]
        == 2
    )


def test_remote_script_is_removed_local_script_survives():
    html, stats = sterilize_runtime_html(
        '<script src="https://example.invalid/app.js"></script>'
        '<script src="assets/local.js"></script>'
    )

    assert (
        "example.invalid"
        not in html
    )

    assert (
        'src="assets/local.js"'
        in html
    )

    assert (
        stats[
            "external_script_tags_removed"
        ]
        == 1
    )


def test_external_navigation_is_neutralized():
    html, stats = sterilize_runtime_html(
        '<a href="https://example.invalid/path">X</a>'
        '<form action="//example.invalid/post"></form>'
    )

    assert (
        'href="#"'
        in html
    )

    assert (
        'action="#"'
        in html
    )

    assert (
        "example.invalid"
        not in html
    )

    assert (
        stats[
            "external_attributes_rewritten"
        ]
        == 2
    )


def test_external_media_is_inert():
    html, _ = sterilize_runtime_html(
        '<img src="https://example.invalid/a.png">'
        '<video poster="//example.invalid/p.jpg"></video>'
        '<img srcset="https://example.invalid/a.png 1x">'
    )

    assert (
        'src="data:,"'
        in html
    )

    assert (
        'poster="data:,"'
        in html
    )

    assert (
        'srcset=""'
        in html
    )

    assert (
        "example.invalid"
        not in html
    )


def test_srcset_resolved_candidates_survive_unresolved_removal():
    html, stats = sterilize_runtime_html(
        '<img srcset="https://cdn.untrusted.invalid/ext.jpg 1x, '
        'assets/small.jpg 2x, assets/large.jpg 3x">'
    )

    assert (
        'srcset="assets/small.jpg 2x, assets/large.jpg 3x"'
        in html
    )

    assert (
        "cdn.untrusted.invalid"
        not in html
    )

    assert (
        stats[
            "external_srcset_candidates_removed"
        ]
        == 1
    )


def test_srcset_candidate_order_and_descriptors_preserved():
    html, _ = sterilize_runtime_html(
        '<img srcset="assets/large.jpg 3x, assets/small.jpg 2x">'
    )

    assert (
        'srcset="assets/large.jpg 3x, assets/small.jpg 2x"'
        in html
    )


def test_relative_and_data_resources_are_preserved():
    source = (
        '<img src="assets/logo.svg">'
        '<img src="data:image/png;base64,AA==">'
        '<a href="#main">Main</a>'
    )

    result, _ = (
        sterilize_runtime_html(
            source
        )
    )

    assert result == source


# =============================================================================
# UWT-7A4: captured inline <script> (no src) REAL JavaScript
# neutralization.
#
# Technical Direction: captured REAL application JavaScript must never
# execute inside a materialized Twin. sterilize_runtime_html() is the
# approved neutralization point, upstream of every Twin-authored
# runtime adapter injection.
# =============================================================================


_INLINE_SCRIPT_MARKER = (
    'data-qcc-auto-twin-network-sterilized="captured-inline-script"'
)


def test_inline_script_without_src_is_neutralized():
    html, stats = sterilize_runtime_html(
        "<script>window.REAL_APP_STATE = 1;</script>"
    )

    assert "window.REAL_APP_STATE" not in html
    assert "<script" in html
    assert "</script>" in html
    assert _INLINE_SCRIPT_MARKER in html

    assert (
        stats["inline_scripts_neutralized"]
        == 1
    )


def test_inline_script_marker_is_deterministic_and_stable():
    source = "<script>doSomethingReal();</script>"

    once, _ = sterilize_runtime_html(source)
    twice, _ = sterilize_runtime_html(once)

    assert once == twice
    assert once.count(_INLINE_SCRIPT_MARKER) == 1


def test_inline_script_window_location_assignment_is_neutralized():
    html, stats = sterilize_runtime_html(
        '<script>window.location = '
        '"https://real.example/account";</script>'
    )

    assert "real.example" not in html
    assert "window.location" not in html

    assert (
        stats["inline_scripts_neutralized"]
        == 1
    )


def test_inline_script_window_open_is_neutralized():
    html, _ = sterilize_runtime_html(
        '<script>window.open("https://real.example/popup");</script>'
    )

    assert "real.example" not in html
    assert "window.open" not in html


def test_inline_script_fetch_is_neutralized():
    html, _ = sterilize_runtime_html(
        '<script>fetch("https://real.example/api");</script>'
    )

    assert "real.example" not in html
    assert "fetch(" not in html


def test_inline_script_xmlhttprequest_is_neutralized():
    html, _ = sterilize_runtime_html(
        "<script>"
        "var xhr = new XMLHttpRequest();"
        'xhr.open("GET", "https://real.example/api");'
        "xhr.send();"
        "</script>"
    )

    assert "real.example" not in html
    assert "XMLHttpRequest" not in html


def test_inline_script_preserves_non_dangerous_attributes():
    html, _ = sterilize_runtime_html(
        '<script type="text/javascript" id="real-inline">'
        "doSomethingReal();"
        "</script>"
    )

    assert 'type="text/javascript"' in html
    assert 'id="real-inline"' in html
    assert _INLINE_SCRIPT_MARKER in html
    assert "doSomethingReal" not in html


def test_inline_script_strips_own_event_handler_attributes():
    html, _ = sterilize_runtime_html(
        '<script onerror="exfiltrate()" onload="exfiltrate()">'
        "doSomethingReal();"
        "</script>"
    )

    assert "onerror" not in html
    assert "onload" not in html
    assert "exfiltrate" not in html
    assert "doSomethingReal" not in html


def test_script_with_present_empty_src_follows_external_contract():
    # A script with a present (even empty) src attribute is -- per the
    # HTML spec -- an external script whose inline body never
    # executes. It is governed by the existing external-script
    # contract, not by inline-body neutralization.
    html, stats = sterilize_runtime_html(
        '<script src="">captured REAL body never executes anyway'
        "</script>"
    )

    assert (
        stats["inline_scripts_neutralized"]
        == 0
    )

    assert (
        "captured REAL body never executes anyway"
        in html
    )


def test_inline_script_non_executable_type_is_still_neutralized():
    # FAIL CLOSED: every no-src captured script body is treated as
    # untrusted, with no selective JavaScript-type parsing.
    html, stats = sterilize_runtime_html(
        '<script type="application/json">{"real":"data"}</script>'
    )

    assert "real" not in html

    assert (
        stats["inline_scripts_neutralized"]
        == 1
    )


def test_multiple_inline_scripts_are_each_neutralized():
    html, stats = sterilize_runtime_html(
        "<script>one();</script>"
        '<script src="assets/local.js"></script>'
        "<script>two();</script>"
    )

    assert "one()" not in html
    assert "two()" not in html
    assert 'src="assets/local.js"' in html
    assert html.count(_INLINE_SCRIPT_MARKER) == 2

    assert (
        stats["inline_scripts_neutralized"]
        == 2
    )


def test_external_remote_script_behavior_unchanged_by_inline_contract():
    html, stats = sterilize_runtime_html(
        '<script src="https://example.invalid/app.js"></script>'
    )

    assert "example.invalid" not in html
    assert stats["external_script_tags_removed"] == 1
    assert stats["inline_scripts_neutralized"] == 0


# =============================================================================
# CSP contract: the Twin-authored _NETWORK_GUARD carries the canonical
# policy and is injected strictly AFTER sterilize_runtime_html() runs,
# so it is never itself subject to inline-script neutralization.
# =============================================================================


_CSP_REQUIRED_DIRECTIVES = (
    "default-src",
    "connect-src",
    "script-src",
    "img-src",
    "style-src",
    "font-src",
    "frame-src",
    "object-src",
    "form-action",
    "base-uri",
)


def test_network_guard_declares_required_csp_directives():
    assert "Content-Security-Policy" in _NETWORK_GUARD

    for directive in _CSP_REQUIRED_DIRECTIVES:
        assert directive in _NETWORK_GUARD


def test_network_guard_connect_src_is_blocked():
    assert "connect-src 'none'" in _NETWORK_GUARD


# =============================================================================
# End-to-end through materialize_auto_twin_plan(): captured REAL inline
# JavaScript must never survive into the materialized runtime, while
# the Twin-authored _NETWORK_GUARD (injected strictly after
# sterilization) must remain present and carry the canonical CSP.
# =============================================================================


STATE_ID_INLINE = "STATE_INLINE_JS"
STATE_DIR_NAME_INLINE = "01-" + STATE_ID_INLINE
CAPTURE_ID_INLINE = "cap-inline-js-1"


def _write_inline_js_fixture_mhtml(path):
    root = EmailMessage()
    root["MIME-Version"] = "1.0"
    root.set_type("multipart/related")

    html_part = EmailMessage()
    html_part.set_content(
        """<!doctype html>
<html>
<head><title>Inline JS Fixture</title></head>
<body>
CAPTURED REAL PAGE
<script>
window.REAL_APP_SECRET = "exfiltrate-me";
fetch("https://real.example/api");
</script>
</body>
</html>
""",
        subtype="html",
        charset="utf-8",
    )

    html_part["Content-Location"] = (
        "https://example.test/es/inline-js"
    )

    root.attach(html_part)

    path.write_bytes(
        root.as_bytes(
            policy=policy.default
        )
    )


def _materialize_inline_js_fixture(tmp_path):
    captures = tmp_path / "captures"
    capture_dir = captures / CAPTURE_ID_INLINE
    capture_dir.mkdir(parents=True)

    page_html = b"<html><body>FALLBACK</body></html>"

    (capture_dir / "page.html").write_bytes(page_html)

    _write_inline_js_fixture_mhtml(
        capture_dir / "page.mhtml"
    )

    page_mhtml = (
        capture_dir / "page.mhtml"
    ).read_bytes()

    plan = {
        "plan_type":
            AUTO_TWIN_MATERIALIZATION_PLAN_TYPE,

        "twin_key":
            "inline_js_sterilization",

        "materialization_mode":
            "BOOTSTRAP_REAL",

        "source_capture_ids": [
            CAPTURE_ID_INLINE,
        ],

        "source_evidence_sha256":
            "a" * 64,

        "artifact_operations": [
            {
                "source_reference":
                    CAPTURE_ID_INLINE + "/page.html",

                "destination_path": (
                    "states/"
                    + STATE_DIR_NAME_INLINE
                    + "/source/page.html"
                ),

                "sha256":
                    hashlib.sha256(page_html).hexdigest(),

                "size_bytes":
                    len(page_html),
            },
            {
                "source_reference":
                    CAPTURE_ID_INLINE + "/page.mhtml",

                "destination_path": (
                    "states/"
                    + STATE_DIR_NAME_INLINE
                    + "/source/page.mhtml"
                ),

                "sha256":
                    hashlib.sha256(page_mhtml).hexdigest(),

                "size_bytes":
                    len(page_mhtml),
            },
        ],

        "state_manifest": [
            {
                "state_index": 1,
                "state_id": STATE_ID_INLINE,
                "source_capture_id": CAPTURE_ID_INLINE,
                "pathname": "/es/inline-js",
                "functional_state": None,
                "rendering_profile_id": "RENDER_PROFILE_1",
            },
        ],
    }

    result = materialize_auto_twin_plan(
        plan=plan,
        source_root=captures,
        materialized_root=(
            tmp_path / "materialized"
        ),
        procedure_code="INLINE_JS_STERILIZATION",
        flow_variant="SITE_LEVEL",
    )

    runtime_dir = (
        Path(result["revision_dir"])
        / "states"
        / STATE_DIR_NAME_INLINE
        / "runtime"
    )

    html = (
        runtime_dir / "index.html"
    ).read_text(encoding="utf-8")

    return runtime_dir, html


def test_captured_inline_script_is_neutralized_end_to_end(
    tmp_path,
):
    _, html = _materialize_inline_js_fixture(
        tmp_path
    )

    assert "REAL_APP_SECRET" not in html
    assert "exfiltrate-me" not in html
    assert "real.example" not in html
    assert _INLINE_SCRIPT_MARKER in html


def test_network_guard_survives_after_inline_script_sterilization(
    tmp_path,
):
    _, html = _materialize_inline_js_fixture(
        tmp_path
    )

    assert 'http-equiv="Content-Security-Policy"' in html

    for directive in _CSP_REQUIRED_DIRECTIVES:
        assert directive in html
