"""UWT-7A2: AUTO TWIN favicon fidelity and deterministic resource fallback.

End-to-end proof, through the REAL materialize_auto_twin_plan() pipeline
(MHTML extraction + resource aliases + rewrite_text + network
sterilization -- no second renderer/materializer/resource-resolution
engine), that:

- captured favicon-like <link> resources (icon, shortcut icon,
  apple-touch-icon), relative or absolute, resolve to local
  materialized assets with byte-faithful content;
- unresolved and protocol-relative favicon references can never
  retain a REAL/escaping URL, and sterilize deterministically;
- a missing favicon declaration never introduces a REAL
  /favicon.ico dependency;
- repeated materialization of the same source is deterministic;
- ordinary governed navigation hrefs are left untouched by the
  static-resource fallback machinery;
- pre-existing UWT-7A1 resource fidelity (srcset order/descriptors,
  download byte-fidelity) is preserved.
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


DOCUMENT_LOCATION = "https://example.test/es/documento"

ICON_BYTES = b"\x00\x00\x01\x00 FAKE ICO FIXTURE BYTES"
SHORTCUT_ICON_BYTES = b"\x00\x00\x01\x00 FAKE SHORTCUT ICO BYTES"
APPLE_TOUCH_ICON_BYTES = b"\x89PNG FAKE APPLE TOUCH ICON BYTES"
RELATIVE_ICON_BYTES = b"\x00\x00\x01\x00 FAKE RELATIVE ICO BYTES"
NESTED_ICON_BYTES = b"\x89PNG FAKE NESTED ICON BYTES"
PROTOCOL_RELATIVE_ICON_BYTES = b"\x89PNG FAKE PROTOCOL RELATIVE BYTES"
PDF_BYTES = b"%PDF-1.4 FAKE INFORME FIXTURE BYTES\n"
SMALL_JPEG_BYTES = b"\xff\xd8\xff\xe0 SMALL JPEG FIXTURE BYTES"
LARGE_JPEG_BYTES = b"\xff\xd8\xff\xe0 LARGE JPEG FIXTURE BYTES"

CAPTURE_ID = "cap-favicon-1"
STATE_ID = "STATE_FAVICON"
STATE_DIR_NAME = "01-" + STATE_ID
TWIN_KEY = "favicon_resource_fallback"


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
    *,
    html_body,
    parts,
    document_location=DOCUMENT_LOCATION,
):
    root = EmailMessage()
    root["MIME-Version"] = "1.0"
    root.set_type(
        "multipart/related"
    )

    html_part = EmailMessage()
    html_part.set_content(
        html_body,
        subtype="html",
        charset="utf-8",
    )

    html_part[
        "Content-Location"
    ] = document_location

    root.attach(
        html_part
    )

    for part in parts:
        asset_part = EmailMessage()

        asset_part.set_content(
            part["content"],
            maintype=part["maintype"],
            subtype=part["subtype"],
        )

        asset_part[
            "Content-Location"
        ] = part["location"]

        root.attach(
            asset_part
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
    *,
    html_body,
    parts=(),
    document_location=DOCUMENT_LOCATION,
    pathname="/es/documento",
    materialized_root=None,
    twin_key=TWIN_KEY,
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
        parents=True,
        exist_ok=True,
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
        / "page.mhtml",
        html_body=html_body,
        parts=parts,
        document_location=document_location,
    )

    page_mhtml = (
        capture_dir
        / "page.mhtml"
    ).read_bytes()

    plan = {
        "plan_type":
            AUTO_TWIN_MATERIALIZATION_PLAN_TYPE,

        "twin_key":
            twin_key,

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
                    pathname,

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
            materialized_root
            or (
                tmp_path
                / "materialized"
            )
        ),
        procedure_code="FAVICON_FALLBACK",
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


def test_captured_rel_icon_resolves_locally(
    tmp_path,
):
    runtime_dir, html = _materialize(
        tmp_path,
        html_body=(
            '<html><head>'
            '<link rel="icon" '
            'href="https://example.test/favicon.ico">'
            '</head><body></body></html>'
        ),
        parts=[{
            "location":
                "https://example.test/favicon.ico",

            "content":
                ICON_BYTES,

            "maintype":
                "image",

            "subtype":
                "x-icon",
        }],
    )

    filename = _asset_filename(
        ICON_BYTES,
        ".ico",
    )

    assert (
        'rel="icon" href="assets/'
        + filename
        + '"'
        in html
    )

    assert (
        "example.test"
        not in html
    )

    assert (
        (
            runtime_dir
            / "assets"
            / filename
        ).read_bytes()
        == ICON_BYTES
    )


def test_captured_shortcut_icon_resolves_locally(
    tmp_path,
):
    runtime_dir, html = _materialize(
        tmp_path,
        html_body=(
            '<html><head>'
            '<link rel="shortcut icon" '
            'href="https://example.test/favicon-shortcut.ico">'
            '</head><body></body></html>'
        ),
        parts=[{
            "location":
                "https://example.test/favicon-shortcut.ico",

            "content":
                SHORTCUT_ICON_BYTES,

            "maintype":
                "image",

            "subtype":
                "x-icon",
        }],
    )

    filename = _asset_filename(
        SHORTCUT_ICON_BYTES,
        ".ico",
    )

    assert (
        'rel="shortcut icon" href="assets/'
        + filename
        + '"'
        in html
    )

    assert (
        (
            runtime_dir
            / "assets"
            / filename
        ).read_bytes()
        == SHORTCUT_ICON_BYTES
    )


def test_captured_apple_touch_icon_resolves_locally(
    tmp_path,
):
    runtime_dir, html = _materialize(
        tmp_path,
        html_body=(
            '<html><head>'
            '<link rel="apple-touch-icon" '
            'href="https://example.test/apple-touch-icon.png">'
            '</head><body></body></html>'
        ),
        parts=[{
            "location":
                "https://example.test/apple-touch-icon.png",

            "content":
                APPLE_TOUCH_ICON_BYTES,

            "maintype":
                "image",

            "subtype":
                "png",
        }],
    )

    filename = _asset_filename(
        APPLE_TOUCH_ICON_BYTES,
        ".png",
    )

    assert (
        'rel="apple-touch-icon" href="assets/'
        + filename
        + '"'
        in html
    )

    assert (
        (
            runtime_dir
            / "assets"
            / filename
        ).read_bytes()
        == APPLE_TOUCH_ICON_BYTES
    )


def test_relative_captured_favicon_resolves_locally(
    tmp_path,
):
    runtime_dir, html = _materialize(
        tmp_path,
        html_body=(
            '<html><head>'
            '<link rel="icon" href="favicon.ico">'
            '</head><body></body></html>'
        ),
        parts=[{
            "location":
                "https://example.test/es/favicon.ico",

            "content":
                RELATIVE_ICON_BYTES,

            "maintype":
                "image",

            "subtype":
                "x-icon",
        }],
        document_location=(
            "https://example.test/es/documento"
        ),
    )

    filename = _asset_filename(
        RELATIVE_ICON_BYTES,
        ".ico",
    )

    assert (
        'rel="icon" href="assets/'
        + filename
        + '"'
        in html
    )

    assert (
        (
            runtime_dir
            / "assets"
            / filename
        ).read_bytes()
        == RELATIVE_ICON_BYTES
    )


def test_absolute_real_favicon_resolves_locally_when_captured(
    tmp_path,
):
    runtime_dir, html = _materialize(
        tmp_path,
        html_body=(
            '<html><head>'
            '<link rel="icon" '
            'href="https://example.test/icons/favicon-32.png">'
            '</head><body></body></html>'
        ),
        parts=[{
            "location":
                "https://example.test/icons/favicon-32.png",

            "content":
                NESTED_ICON_BYTES,

            "maintype":
                "image",

            "subtype":
                "png",
        }],
    )

    filename = _asset_filename(
        NESTED_ICON_BYTES,
        ".png",
    )

    assert (
        'rel="icon" href="assets/'
        + filename
        + '"'
        in html
    )

    assert (
        "example.test"
        not in html
    )

    assert (
        (
            runtime_dir
            / "assets"
            / filename
        ).read_bytes()
        == NESTED_ICON_BYTES
    )


def test_protocol_relative_favicon_cannot_escape_real(
    tmp_path,
):
    _, html = _materialize(
        tmp_path,
        html_body=(
            '<html><head>'
            '<link rel="icon" '
            'href="//cdn.untrusted.invalid/favicon.ico">'
            '</head><body></body></html>'
        ),
    )

    assert (
        "cdn.untrusted.invalid"
        not in html
    )

    assert (
        "rel=\"icon\""
        not in html
    )


def test_protocol_relative_favicon_resolves_locally_when_captured(
    tmp_path,
):
    runtime_dir, html = _materialize(
        tmp_path,
        html_body=(
            '<html><head>'
            '<link rel="icon" '
            'href="//example.test/favicon-protocol-relative.png">'
            '</head><body></body></html>'
        ),
        parts=[{
            "location":
                "https://example.test/"
                "favicon-protocol-relative.png",

            "content":
                PROTOCOL_RELATIVE_ICON_BYTES,

            "maintype":
                "image",

            "subtype":
                "png",
        }],
    )

    filename = _asset_filename(
        PROTOCOL_RELATIVE_ICON_BYTES,
        ".png",
    )

    assert (
        'rel="icon" href="assets/'
        + filename
        + '"'
        in html
    )

    assert (
        "example.test"
        not in html
    )

    assert (
        (
            runtime_dir
            / "assets"
            / filename
        ).read_bytes()
        == PROTOCOL_RELATIVE_ICON_BYTES
    )


def test_unresolved_favicon_has_deterministic_sterile_fallback(
    tmp_path,
):
    html_body = (
        '<html><head>'
        '<link rel="icon" '
        'href="https://cdn.untrusted.invalid/favicon.ico">'
        '</head><body></body></html>'
    )

    _, first_html = _materialize(
        tmp_path / "run1",
        html_body=html_body,
    )

    _, second_html = _materialize(
        tmp_path / "run2",
        html_body=html_body,
    )

    assert (
        "cdn.untrusted.invalid"
        not in first_html
    )

    assert first_html == second_html


def test_missing_favicon_does_not_depend_on_real_favicon_ico(
    tmp_path,
):
    _, html = _materialize(
        tmp_path,
        html_body=(
            '<html><head>'
            '<title>No favicon</title>'
            '</head><body></body></html>'
        ),
    )

    assert (
        "favicon.ico"
        not in html
    )

    assert (
        "example.test"
        not in html
    )

    assert (
        'connect-src \'none\''
        in html
    )


def test_repeated_materialization_is_deterministic(
    tmp_path,
):
    html_body = (
        '<html><head>'
        '<link rel="icon" '
        'href="https://example.test/favicon.ico">'
        '<link rel="apple-touch-icon" '
        'href="https://cdn.untrusted.invalid/apple.png">'
        '</head><body></body></html>'
    )

    parts = [{
        "location":
            "https://example.test/favicon.ico",

        "content":
            ICON_BYTES,

        "maintype":
            "image",

        "subtype":
            "x-icon",
    }]

    _, first_html = _materialize(
        tmp_path / "run1",
        html_body=html_body,
        parts=parts,
    )

    _, second_html = _materialize(
        tmp_path / "run2",
        html_body=html_body,
        parts=parts,
    )

    assert first_html == second_html


def test_ordinary_navigation_href_is_not_treated_as_static_resource(
    tmp_path,
):
    _, html = _materialize(
        tmp_path,
        html_body=(
            '<html><body>'
            '<a href="/es/otra-pagina">Siguiente</a>'
            '</body></html>'
        ),
    )

    assert (
        'href="/es/otra-pagina"'
        in html
    )


def test_external_unresolved_static_resource_cannot_retain_real_url(
    tmp_path,
):
    _, html = _materialize(
        tmp_path,
        html_body=(
            '<html><body>'
            '<img src="https://cdn.untrusted.invalid/x.png">'
            '</body></html>'
        ),
    )

    assert (
        "cdn.untrusted.invalid"
        not in html
    )

    assert (
        'src="data:,"'
        in html
    )


def test_existing_srcset_descriptors_order_unchanged(
    tmp_path,
):
    runtime_dir, html = _materialize(
        tmp_path,
        html_body=(
            '<html><body>'
            '<img srcset="https://cdn.untrusted.invalid/ext.jpg 1x, '
            'https://example.test/media/small.jpg 2x, '
            'https://example.test/media/large.jpg 3x">'
            '</body></html>'
        ),
        parts=[
            {
                "location":
                    "https://example.test/media/small.jpg",

                "content":
                    SMALL_JPEG_BYTES,

                "maintype":
                    "image",

                "subtype":
                    "jpeg",
            },
            {
                "location":
                    "https://example.test/media/large.jpg",

                "content":
                    LARGE_JPEG_BYTES,

                "maintype":
                    "image",

                "subtype":
                    "jpeg",
            },
        ],
    )

    small_filename = _asset_filename(
        SMALL_JPEG_BYTES,
        ".jpg",
    )

    large_filename = _asset_filename(
        LARGE_JPEG_BYTES,
        ".jpg",
    )

    assert (
        'srcset="assets/'
        + small_filename
        + " 2x, assets/"
        + large_filename
        + ' 3x"'
        in html
    )

    assert (
        "cdn.untrusted.invalid"
        not in html
    )

    assert (
        (
            runtime_dir
            / "assets"
            / small_filename
        ).read_bytes()
        == SMALL_JPEG_BYTES
    )

    assert (
        (
            runtime_dir
            / "assets"
            / large_filename
        ).read_bytes()
        == LARGE_JPEG_BYTES
    )


def test_existing_captured_download_resource_remains_byte_faithful(
    tmp_path,
):
    runtime_dir, html = _materialize(
        tmp_path,
        html_body=(
            '<html><body>'
            '<a href="https://example.test/files/informe.pdf" '
            'download="reporte-descarga.pdf">Descargar</a>'
            '</body></html>'
        ),
        parts=[{
            "location":
                "https://example.test/files/informe.pdf",

            "content":
                PDF_BYTES,

            "maintype":
                "application",

            "subtype":
                "pdf",
        }],
    )

    pdf_filename = _asset_filename(
        PDF_BYTES,
        ".pdf",
    )

    assert (
        'href="assets/'
        + pdf_filename
        + '"'
        in html
    )

    assert (
        'download="reporte-descarga.pdf"'
        in html
    )

    assert (
        (
            runtime_dir
            / "assets"
            / pdf_filename
        ).read_bytes()
        == PDF_BYTES
    )
