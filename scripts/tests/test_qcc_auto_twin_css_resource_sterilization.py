"""UWT-7A3: CSS nested resource sterilization.

An unresolved external resource reference inside an inline <style> block
or a materialized text/css asset must never retain a browser-fetchable
REAL URL, while captured/resolved local references and safe non-external
forms (fragment-only, relative, data:) must survive untouched.
"""

from email import policy
from email.message import EmailMessage
import hashlib
from pathlib import Path

from backend.qcc.auto_twin.materialization_builder import (
    materialize_auto_twin_plan,
)

from backend.qcc.auto_twin.materialization_plan import (
    AUTO_TWIN_MATERIALIZATION_PLAN_TYPE,
)

from backend.qcc.auto_twin.runtime_network_sterilization import (
    sterilize_runtime_css,
    sterilize_runtime_html,
)


# =============================================================================
# Direct sterilize_runtime_css() coverage of every required CSS surface.
# =============================================================================


def test_unresolved_https_url_is_sterilized():
    css, stats = sterilize_runtime_css(
        "div{background:url(https://example.invalid/a.png)}"
    )

    assert "example.invalid" not in css
    assert "url(data:,)" in css
    assert stats["css_url_references_rewritten"] == 1


def test_unresolved_http_url_is_sterilized():
    css, _ = sterilize_runtime_css(
        "div{background:url(http://example.invalid/a.png)}"
    )

    assert "example.invalid" not in css
    assert "url(data:,)" in css


def test_protocol_relative_url_is_sterilized():
    css, _ = sterilize_runtime_css(
        "div{background:url(//example.invalid/a.png)}"
    )

    assert "example.invalid" not in css
    assert "url(data:,)" in css


def test_double_quoted_url_is_sterilized():
    css, _ = sterilize_runtime_css(
        'div{background:url("https://example.invalid/a.png")}'
    )

    assert "example.invalid" not in css
    assert 'url("data:,")' in css


def test_single_quoted_url_is_sterilized():
    css, _ = sterilize_runtime_css(
        "div{background:url('https://example.invalid/a.png')}"
    )

    assert "example.invalid" not in css
    assert "url('data:,')" in css


def test_unquoted_url_is_sterilized():
    css, _ = sterilize_runtime_css(
        "div{background:url(https://example.invalid/a.png)}"
    )

    assert "example.invalid" not in css
    assert "url(data:,)" in css


def test_unresolved_import_is_sterilized():
    css, stats = sterilize_runtime_css(
        '@import url("https://example.invalid/theme.css");'
    )

    assert "example.invalid" not in css
    assert stats["css_url_references_rewritten"] == 1

    css, stats = sterilize_runtime_css(
        '@import "https://example.invalid/theme.css";'
    )

    assert "example.invalid" not in css
    assert stats["css_import_references_rewritten"] == 1


def test_unresolved_font_face_src_is_sterilized():
    css, _ = sterilize_runtime_css(
        "@font-face{font-family:X;"
        "src:url(https://example.invalid/font.woff2) format('woff2')}"
    )

    assert "example.invalid" not in css
    assert "url(data:,)" in css


def test_unresolved_background_image_is_sterilized():
    css, _ = sterilize_runtime_css(
        ".x{background-image:url(https://example.invalid/bg.png)}"
    )

    assert "example.invalid" not in css


def test_unresolved_list_style_image_is_sterilized():
    css, _ = sterilize_runtime_css(
        "li{list-style-image:url(https://example.invalid/bullet.png)}"
    )

    assert "example.invalid" not in css


def test_unresolved_cursor_is_sterilized():
    css, _ = sterilize_runtime_css(
        ".x{cursor:url(https://example.invalid/cursor.png),pointer}"
    )

    assert "example.invalid" not in css
    assert "url(data:,),pointer" in css


def test_fragment_only_reference_is_preserved():
    source = ".x{filter:url(#mask)}"

    css, stats = sterilize_runtime_css(
        source
    )

    assert css == source
    assert stats["css_url_references_rewritten"] == 0


def test_local_relative_asset_is_preserved():
    source = ".x{background:url(assets/bg.png)}"

    css, _ = sterilize_runtime_css(
        source
    )

    assert css == source


def test_data_uri_is_preserved():
    source = (
        ".x{background:url(data:image/png;base64,AA==)}"
    )

    css, _ = sterilize_runtime_css(
        source
    )

    assert css == source


def test_repeated_sterilization_is_idempotent():
    source = (
        "div{background:url(https://example.invalid/a.png)}"
        "li{list-style-image:url('//example.invalid/b.png')}"
    )

    once, _ = sterilize_runtime_css(
        source
    )

    twice, _ = sterilize_runtime_css(
        once
    )

    assert once == twice


# =============================================================================
# Inline <style> coverage through sterilize_runtime_html().
# =============================================================================


def test_inline_style_cannot_retain_real_external_url():
    html, stats = sterilize_runtime_html(
        "<html><head><style>"
        "body{background:url(https://example.invalid/a.png)}"
        "</style></head>"
        "<body></body></html>"
    )

    assert "example.invalid" not in html
    assert "url(data:,)" in html
    assert stats["css_url_references_rewritten"] == 1


def test_inline_style_local_reference_survives():
    source = (
        "<style>body{background:url(assets/bg.png)}</style>"
    )

    html, _ = sterilize_runtime_html(
        source
    )

    assert html == source


# =============================================================================
# End-to-end through materialize_auto_twin_plan(): captured CSS resources
# preserved local, unresolved CSS references blocked in both inline
# <style> and materialized text/css assets.
# =============================================================================


LOGO_BYTES = b"\x89PNG FAKE LOGO FIXTURE BYTES"

STATE_ID = "STATE_CSS"
STATE_DIR_NAME = "01-" + STATE_ID
CAPTURE_ID = "cap-css-1"


def _sha256(content):
    return hashlib.sha256(
        content
    ).hexdigest()


def _asset_filename(
    content,
    extension,
):
    return (
        _sha256(content)[:24]
        + extension
    )


def _write_fixture_mhtml(
    path,
):
    root = EmailMessage()
    root["MIME-Version"] = "1.0"
    root.set_type(
        "multipart/related"
    )

    html_part = EmailMessage()
    html_part.set_content(
        """<!doctype html>
<html>
<head>
<style>
body {
  background: url(https://example.test/media/logo.png);
}
.blocked {
  background: url(https://cdn.untrusted.invalid/ghost.png);
}
</style>
<link rel="stylesheet" href="https://example.test/css/theme.css">
</head>
<body>CSS FIXTURE</body>
</html>
""",
        subtype="html",
        charset="utf-8",
    )

    html_part[
        "Content-Location"
    ] = (
        "https://example.test/es/estilos"
    )

    root.attach(
        html_part
    )

    logo_part = EmailMessage()
    logo_part.set_content(
        LOGO_BYTES,
        maintype="image",
        subtype="png",
    )

    logo_part[
        "Content-Location"
    ] = (
        "https://example.test/media/logo.png"
    )

    root.attach(
        logo_part
    )

    css_part = EmailMessage()
    css_part.set_content(
        "@font-face{font-family:X;"
        "src:url(https://example.test/media/logo.png)}"
        ".ghost{background:url(https://cdn.untrusted.invalid/ghost.png)}",
        subtype="css",
    )

    css_part[
        "Content-Location"
    ] = (
        "https://example.test/css/theme.css"
    )

    root.attach(
        css_part
    )

    path.write_bytes(
        root.as_bytes(
            policy=policy.default
        )
    )


def _operation(
    *,
    filename,
    content,
):
    return {
        "source_reference":
            CAPTURE_ID
            + "/"
            + filename,

        "destination_path":
            "states/"
            + STATE_DIR_NAME
            + "/source/"
            + filename,

        "sha256":
            _sha256(
                content
            ),

        "size_bytes":
            len(
                content
            ),
    }


def _materialize(
    tmp_path,
):
    captures = (
        tmp_path
        / "captures"
    )

    capture_dir = (
        captures
        / CAPTURE_ID
    )

    capture_dir.mkdir(
        parents=True
    )

    page_html = (
        b"<html><body>FALLBACK</body></html>"
    )

    (
        capture_dir
        / "page.html"
    ).write_bytes(
        page_html
    )

    _write_fixture_mhtml(
        capture_dir
        / "page.mhtml"
    )

    page_mhtml = (
        capture_dir
        / "page.mhtml"
    ).read_bytes()

    plan = {
        "plan_type":
            AUTO_TWIN_MATERIALIZATION_PLAN_TYPE,

        "twin_key":
            "css_sterilization",

        "materialization_mode":
            "BOOTSTRAP_REAL",

        "source_capture_ids": [
            CAPTURE_ID,
        ],

        "source_evidence_sha256":
            "a" * 64,

        "artifact_operations": [
            _operation(
                filename="page.html",
                content=page_html,
            ),

            _operation(
                filename="page.mhtml",
                content=page_mhtml,
            ),
        ],

        "state_manifest": [
            {
                "state_index":
                    1,

                "state_id":
                    STATE_ID,

                "source_capture_id":
                    CAPTURE_ID,

                "pathname":
                    "/es/estilos",

                "functional_state":
                    None,

                "rendering_profile_id":
                    "RENDER_PROFILE_1",
            },
        ],
    }

    result = materialize_auto_twin_plan(
        plan=plan,
        source_root=captures,
        materialized_root=(
            tmp_path
            / "materialized"
        ),
        procedure_code="CSS_STERILIZATION",
        flow_variant="SITE_LEVEL",
    )

    runtime_dir = (
        Path(
            result[
                "revision_dir"
            ]
        )
        / "states"
        / STATE_DIR_NAME
        / "runtime"
    )

    html = (
        runtime_dir
        / "index.html"
    ).read_text(
        encoding="utf-8"
    )

    return runtime_dir, html


def test_captured_css_resource_continues_to_point_local(
    tmp_path,
):
    runtime_dir, html = _materialize(
        tmp_path
    )

    logo_filename = _asset_filename(
        LOGO_BYTES,
        ".png",
    )

    assert (
        "url(assets/"
        + logo_filename
        + ")"
        in html
    )

    assert (
        (
            runtime_dir
            / "assets"
            / logo_filename
        ).read_bytes()
        == LOGO_BYTES
    )


def test_inline_style_in_materialized_html_has_no_real_url(
    tmp_path,
):
    _, html = _materialize(
        tmp_path
    )

    assert "cdn.untrusted.invalid" not in html
    assert "example.test" not in html


def test_external_materialized_css_asset_has_no_real_url(
    tmp_path,
):
    runtime_dir, _ = _materialize(
        tmp_path
    )

    css_filename = _asset_filename(
        (
            "@font-face{font-family:X;"
            "src:url(https://example.test/media/logo.png)}"
            ".ghost{background:url(https://cdn.untrusted.invalid/"
            "ghost.png)}"
            "\n"
        ).encode("utf-8"),
        ".css",
    )

    css_path = (
        runtime_dir
        / "assets"
        / css_filename
    )

    assert css_path.is_file()

    css_text = css_path.read_text(
        encoding="utf-8"
    )

    assert "cdn.untrusted.invalid" not in css_text

    logo_filename = _asset_filename(
        LOGO_BYTES,
        ".png",
    )

    # Sibling assets inside assets/ reference each other by bare
    # filename, not by an "assets/"-prefixed path.
    assert (
        "url("
        + logo_filename
        + ")"
        in css_text
    )
