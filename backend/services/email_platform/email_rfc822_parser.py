"""
Conversión de mensajes RFC822/EML al formato común de la plataforma.
"""

from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
from email.utils import parsedate_to_datetime

from backend.services.email_platform import (
    email_normalization_service,
)


def _decode_header_value(value):
    return str(value or "").strip()


def _addresses(header_values):
    values = []

    if isinstance(header_values, str):
        header_values = [header_values]

    for _, address in getaddresses(
        list(header_values or [])
    ):
        normalized = (
            email_normalization_service
            .normalize_email_address(address)
        )

        if normalized:
            values.append(normalized)

    return values


def _extract_text_parts(message):
    plain_parts = []
    html_parts = []
    attachments = []

    if message.is_multipart():
        parts = message.walk()
    else:
        parts = [message]

    for part in parts:
        if part.is_multipart():
            continue

        disposition = str(
            part.get_content_disposition()
            or ""
        ).lower()

        filename = part.get_filename()
        content_type = part.get_content_type()

        payload = part.get_payload(
            decode=True
        ) or b""

        if disposition == "attachment" or filename:
            attachments.append(
                {
                    "filename":
                        str(filename or "").strip(),
                    "mime_type":
                        content_type,
                    "size_bytes":
                        len(payload),
                    "content_id":
                        str(
                            part.get(
                                "Content-ID"
                            )
                            or ""
                        ).strip(),
                }
            )
            continue

        try:
            content = part.get_content()
        except Exception:
            charset = (
                part.get_content_charset()
                or "utf-8"
            )

            content = payload.decode(
                charset,
                errors="replace",
            )

        if content_type == "text/plain":
            plain_parts.append(str(content))
        elif content_type == "text/html":
            html_parts.append(str(content))

    body_text = "\n\n".join(
        plain_parts
    ).strip()

    body_html = "\n\n".join(
        html_parts
    ).strip()

    if not body_text and body_html:
        body_text = (
            email_normalization_service
            .html_to_text(body_html)
        )

    return body_text, body_html, attachments


def parse_rfc822_message(
    raw_bytes,
    *,
    provider,
    account_email,
    provider_message_id,
    folder="INBOX",
):
    message = BytesParser(
        policy=policy.default
    ).parsebytes(raw_bytes)

    sender_name = ""
    sender_email = ""

    from_header = message.get("From")
    from_addresses = getattr(
        from_header,
        "addresses",
        None,
    )

    if from_addresses:
        sender_address = from_addresses[0]

        sender_name = str(
            getattr(
                sender_address,
                "display_name",
                "",
            )
            or ""
        ).strip()

        sender_email = str(
            getattr(
                sender_address,
                "addr_spec",
                "",
            )
            or ""
        ).strip()

    elif from_header:
        parsed_addresses = getaddresses(
            [str(from_header)]
        )

        if parsed_addresses:
            sender_name = str(
                parsed_addresses[0][0]
                or ""
            ).strip()

            sender_email = str(
                parsed_addresses[0][1]
                or ""
            ).strip()

    received_at = ""

    raw_date = message.get("Date")

    if raw_date:
        try:
            received_at = (
                parsedate_to_datetime(
                    str(raw_date)
                ).isoformat()
            )
        except Exception:
            received_at = str(raw_date)

    body_text, body_html, attachments = (
        _extract_text_parts(message)
    )

    return {
        "provider": provider,
        "account_email": account_email,
        "provider_message_id":
            str(provider_message_id),
        "provider_thread_id": "",
        "internet_message_id":
            str(
                message.get("Message-ID")
                or ""
            ).strip(),
        "direction": "INBOUND",
        "folder": folder,
        "sender_email":
            str(sender_email or "").strip(),
        "sender_name":
            str(sender_name or "").strip(),
        "recipients":
            _addresses(
                message.get_all("To", [])
            ),
        "cc":
            _addresses(
                message.get_all("Cc", [])
            ),
        "bcc": [],
        "subject":
            _decode_header_value(
                message.get("Subject")
            ),
        "received_at": received_at,
        "body_text": body_text,
        "body_html": body_html,
        "attachments": attachments,
        "has_attachments":
            bool(attachments),
        "raw_metadata": {
            "return_path":
                str(
                    message.get(
                        "Return-Path"
                    )
                    or ""
                ).strip(),
            "reply_to":
                str(
                    message.get(
                        "Reply-To"
                    )
                    or ""
                ).strip(),
        },
    }
