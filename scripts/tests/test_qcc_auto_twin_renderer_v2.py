from email import policy
from email.message import EmailMessage
import json

from backend.qcc.auto_twin.automatic_materialization import (
    _renderer_refresh_required,
)

from backend.qcc.auto_twin.materialization_builder import (
    AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    _extract_mhtml_assets,
    _normalize_declarative_shadow_dom,
    _rewrite_text,
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
<link rel="stylesheet" href="styles.css">
</head>
<body>
<x-control>
<template shadowmode="open">
<input class="field" placeholder="Nombre">
<img src="media/logo.svg">
</template>
</x-control>
</body>
</html>
""",
        subtype="html",
        charset="utf-8",
    )

    html_part[
        "Content-Location"
    ] = (
        "https://example.test/es/nuevo-registro"
    )

    root.attach(
        html_part
    )

    css_part = EmailMessage()
    css_part.set_content(
        """
.field {
  border: 1px solid #123456;
  background-image: url(media/logo.svg);
}
""",
        subtype="css",
        charset="utf-8",
    )

    css_part[
        "Content-Location"
    ] = (
        "https://example.test/es/styles.css"
    )

    root.attach(
        css_part
    )

    svg_part = EmailMessage()
    svg_part.set_content(
        (
            b'<svg xmlns="http://www.w3.org/2000/svg" '
            b'width="10" height="10"></svg>'
        ),
        maintype="image",
        subtype="svg+xml",
    )

    svg_part[
        "Content-Location"
    ] = (
        "https://example.test/es/media/logo.svg"
    )

    root.attach(
        svg_part
    )

    path.write_bytes(
        root.as_bytes(
            policy=policy.default
        )
    )


def test_renderer_v2_uses_rendered_mhtml_and_relative_assets(
    tmp_path,
):
    mhtml = (
        tmp_path
        / "page.mhtml"
    )

    runtime = (
        tmp_path
        / "runtime"
    )

    runtime.mkdir()

    _write_fixture_mhtml(
        mhtml
    )

    (
        replacements,
        written,
        rendered_html,
    ) = _extract_mhtml_assets(
        mhtml_path=mhtml,
        runtime_dir=runtime,
    )

    assert rendered_html

    assert (
        "styles.css"
        in replacements
    )

    assert (
        "media/logo.svg"
        in replacements
    )

    assert (
        "/es/styles.css"
        in replacements
    )

    assert (
        "es/styles.css"
        in replacements
    )

    local_html = (
        _normalize_declarative_shadow_dom(
            rendered_html
        )
    )

    local_html = _rewrite_text(
        local_html,
        replacements,
    )

    assert (
        'shadowrootmode="open"'
        in local_html
    )

    assert (
        'shadowmode="open"'
        not in local_html
    )

    assert (
        'href="assets/'
        in local_html
    )

    assert (
        'src="assets/'
        in local_html
    )

    css_items = [
        item
        for item in written
        if (
            item[
                "content_type"
            ]
            == "text/css"
        )
    ]

    assert len(
        css_items
    ) == 1

    css = (
        css_items[0][
            "path"
        ]
        .read_text(
            encoding="utf-8"
        )
    )

    assert (
        "media/logo.svg"
        not in css
    )


def test_renderer_refresh_detects_physical_v1_revision(
    tmp_path,
):
    twin_key = "red_sara"
    revision_id = (
        "matrev-test-renderer"
    )

    revision = {
        "materialized_revision_id":
            revision_id,
    }

    revision_dir = (
        tmp_path
        / twin_key
        / revision_id
    )

    (
        revision_dir
        / "runtime"
    ).mkdir(
        parents=True
    )

    assert (
        _renderer_refresh_required(
            materialized_root=tmp_path,
            twin_key=twin_key,
            revision=revision,
        )
        is True
    )

    marker = (
        revision_dir
        / "runtime"
        / "renderer.json"
    )

    marker.write_text(
        json.dumps({
            "renderer_version":
                AUTO_TWIN_RUNTIME_RENDERER_VERSION,
        }),
        encoding="utf-8",
    )

    assert (
        _renderer_refresh_required(
            materialized_root=tmp_path,
            twin_key=twin_key,
            revision=revision,
        )
        is False
    )


def test_renderer_refresh_ignores_metadata_without_physical_revision(
    tmp_path,
):
    assert (
        _renderer_refresh_required(
            materialized_root=tmp_path,
            twin_key="red_sara",
            revision={
                "materialized_revision_id":
                    "matrev-synthetic",
            },
        )
        is False
    )
