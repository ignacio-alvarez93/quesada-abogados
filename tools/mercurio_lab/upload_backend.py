from __future__ import annotations

import hashlib
import html
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser


@dataclass(frozen=True)
class MercurioLabUpload:
    file_field: str
    filename: str
    size: int
    sha256: str
    document_code: str
    document_description: str
    other_text: str


def _safe_filename(value):
    return (
        str(value or "")
        .replace("\\", "/")
        .rsplit("/", 1)[-1]
        .strip()
    )

def parse_multipart_upload(*, content_type, body):
    content_type = str(content_type or "").strip()

    if "multipart/form-data" not in content_type.lower():
        raise ValueError("MERCURIO_LAB_MULTIPART_REQUIRED")

    crlf = bytes((13, 10))
    envelope = (
        b"Content-Type: "
        + content_type.encode("ascii")
        + crlf
        + b"MIME-Version: 1.0"
        + crlf + crlf
        + bytes(body)
    )
    message = BytesParser(
        policy=policy.default
    ).parsebytes(envelope)

    if not message.is_multipart():
        raise ValueError("MERCURIO_LAB_MULTIPART_INVALID")

    fields = {}
    file_field = ""
    filename = ""
    file_payload = None

    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue

        name = part.get_param(
            "name",
            header="content-disposition",
        ) or ""

        part_filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""

        if part_filename:
            if file_payload is not None:
                raise ValueError("MERCURIO_LAB_MULTIPLE_FILES")

            file_field = str(name)
            filename = _safe_filename(part_filename)
            file_payload = bytes(payload)
            continue

        charset = part.get_content_charset() or "utf-8"
        fields[str(name)] = payload.decode(
            charset,
            errors="replace",
        )

    if file_payload is None or not filename:
        raise ValueError("MERCURIO_LAB_FILE_MISSING")

    code = str(
        fields.get("id_tipo_documento", "")
    ).strip()

    if not code:
        raise ValueError("MERCURIO_LAB_DOCUMENT_CODE_MISSING")

    description = str(
        fields.get("de_documento", "")
    ).strip()

    other_text = str(
        fields.get("texto_otros", "")
    ).strip()

    if code == "999" and not other_text:
        raise ValueError("MERCURIO_LAB_OTHER_TEXT_MISSING")

    return MercurioLabUpload(
        file_field=file_field or "file",
        filename=filename,
        size=len(file_payload),
        sha256=hashlib.sha256(file_payload).hexdigest().upper(),
        document_code=code,
        document_description=description,
        other_text=other_text,
    )

def render_upload_table(uploads):
    rows = []

    for index, upload in enumerate(uploads, start=1):
        description = (
            upload.other_text
            if upload.document_code == "999" and upload.other_text
            else upload.document_description
        )

        rows.append(
            "<tr id=\"lab_upload_" + str(index) + "\">"
            + "<td><a href=\"#\">Eliminar</a></td>"
            + "<td>" + html.escape(upload.filename) + "</td>"
            + "<td>" + html.escape(description) + "</td>"
            + "<td>" + html.escape(upload.sha256) + "</td>"
            + "<td style=\"display:none;\">"
            + html.escape(upload.document_code)
            + "</td></tr>"
        )

    return (
        "<table id=\"tabla_datos_adj\">"
        "<thead><tr>"
        "<th></th><th>Nombre del fichero</th>"
        "<th>Descripción</th><th>HASH</th>"
        "<th style=\"display:none;\"></th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )
