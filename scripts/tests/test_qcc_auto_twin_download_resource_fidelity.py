"""UWT-7A1-FIX2: AUTO TWIN resource fidelity for download/srcset assets.

End-to-end proof, through the REAL materialize_auto_twin_plan() pipeline
(MHTML extraction + resource aliases + rewrite_text + network
sterilization -- no second download/materializer/resource-store), that:

- a captured static/download resource href resolves to a local asset,
  with its bytes physically materialized on disk;
- captured srcset candidates resolve to local assets, preserving
  candidate order and descriptors;
- an unresolved genuine external reference (srcset candidate or plain
  navigation href) is blocked;
- no live REAL origin remains in the materialized runtime HTML.
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


PDF_BYTES = b"%PDF-1.4 FAKE INFORME FIXTURE BYTES\n"
SMALL_JPEG_BYTES = b"\xff\xd8\xff\xe0 SMALL JPEG FIXTURE BYTES"
LARGE_JPEG_BYTES = b"\xff\xd8\xff\xe0 LARGE JPEG FIXTURE BYTES"

STATE_ID = "STATE_DOWNLOAD"
STATE_DIR_NAME = "01-" + STATE_ID
CAPTURE_ID = "cap-download-1"


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
<body>
<a href="https://example.test/files/informe.pdf"
   download="reporte-descarga.pdf">Descargar informe</a>
<img
  src="https://example.test/media/small.jpg"
  srcset="https://cdn.untrusted.invalid/ext.jpg 1x,
          https://example.test/media/small.jpg 2x,
          https://example.test/media/large.jpg 3x">
<a href="https://cdn.untrusted.invalid/other-page">External</a>
</body>
</html>
""",
        subtype="html",
        charset="utf-8",
    )

    html_part[
        "Content-Location"
    ] = (
        "https://example.test/es/documento"
    )

    root.attach(
        html_part
    )

    pdf_part = EmailMessage()
    pdf_part.set_content(
        PDF_BYTES,
        maintype="application",
        subtype="pdf",
    )

    pdf_part[
        "Content-Location"
    ] = (
        "https://example.test/files/informe.pdf"
    )

    root.attach(
        pdf_part
    )

    small_part = EmailMessage()
    small_part.set_content(
        SMALL_JPEG_BYTES,
        maintype="image",
        subtype="jpeg",
    )

    small_part[
        "Content-Location"
    ] = (
        "https://example.test/media/small.jpg"
    )

    root.attach(
        small_part
    )

    large_part = EmailMessage()
    large_part.set_content(
        LARGE_JPEG_BYTES,
        maintype="image",
        subtype="jpeg",
    )

    large_part[
        "Content-Location"
    ] = (
        "https://example.test/media/large.jpg"
    )

    root.attach(
        large_part
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
            "download_fidelity",

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
                    "/es/documento",

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
        procedure_code="DOWNLOAD_FIDELITY",
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


def test_captured_download_resource_resolves_local_and_materializes_bytes(
    tmp_path,
):
    runtime_dir, html = _materialize(
        tmp_path
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


def test_srcset_candidates_resolve_local_with_order_and_descriptors(
    tmp_path,
):
    runtime_dir, html = _materialize(
        tmp_path
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


def test_unresolved_external_reference_is_blocked(
    tmp_path,
):
    _, html = _materialize(
        tmp_path
    )

    assert (
        "cdn.untrusted.invalid"
        not in html
    )

    assert (
        'href="#"'
        in html
    )


def test_no_live_real_origin_remains(
    tmp_path,
):
    _, html = _materialize(
        tmp_path
    )

    assert (
        "example.test"
        not in html
    )

    assert (
        "cdn.untrusted.invalid"
        not in html
    )
