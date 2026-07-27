"""
Normalización común de mensajes procedentes de cualquier proveedor.
"""

import hashlib
import html
import re
import unicodedata
from email.utils import parseaddr


WHITESPACE_RE = re.compile(r"[ \t\r\f\v]+")
MULTILINE_RE = re.compile(r"\n{3,}")
HTML_TAG_RE = re.compile(r"<[^>]+>")


def normalize_email_address(value):
    _, address = parseaddr(str(value or ""))
    return address.strip().lower()


def html_to_text(value):
    text = str(value or "")

    if not text:
        return ""

    text = re.sub(
        r"(?i)<br\s*/?>",
        "\n",
        text,
    )
    text = re.sub(
        r"(?i)</p\s*>",
        "\n",
        text,
    )
    text = HTML_TAG_RE.sub(" ", text)
    text = html.unescape(text)

    return normalize_body_text(text)


def normalize_body_text(value):
    text = str(value or "")
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    lines = []

    for line in text.split("\n"):
        line = WHITESPACE_RE.sub(" ", line).strip()
        lines.append(line)

    text = "\n".join(lines)
    text = MULTILINE_RE.sub("\n\n", text)

    return text.strip()


def normalize_search_text(value):
    text = normalize_body_text(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )
    return text.upper()


def sha256_text(value):
    return hashlib.sha256(
        str(value or "").encode("utf-8")
    ).hexdigest()


def build_dedupe_key(message):
    provider = str(
        message.get("provider")
        or "UNKNOWN"
    ).strip().upper()

    account_email = normalize_email_address(
        message.get("account_email")
    )

    provider_message_id = str(
        message.get("provider_message_id")
        or ""
    ).strip()

    internet_message_id = str(
        message.get("internet_message_id")
        or ""
    ).strip().lower()

    if provider_message_id:
        material = (
            f"PROVIDER|{provider}|"
            f"{account_email}|"
            f"{provider_message_id}"
        )
        return sha256_text(material)

    if internet_message_id:
        return sha256_text(
            "INTERNET_MESSAGE_ID|"
            + internet_message_id
        )

    body = normalize_body_text(
        message.get("body_text")
        or html_to_text(
            message.get("body_html")
        )
    )

    material = "|".join(
        [
            "CONTENT",
            normalize_email_address(
                message.get("sender_email")
            ),
            str(
                message.get("received_at")
                or ""
            ).strip(),
            str(
                message.get("subject")
                or ""
            ).strip(),
            body,
        ]
    )

    return sha256_text(material)


def normalize_message(message):
    data = dict(message or {})

    body_text = normalize_body_text(
        data.get("body_text")
    )

    if not body_text and data.get("body_html"):
        body_text = html_to_text(
            data.get("body_html")
        )

    normalized = {
        "account_id":
            data.get("account_id"),
        "provider":
            str(
                data.get("provider")
                or "MANUAL"
            ).strip().upper(),
        "account_email":
            normalize_email_address(
                data.get("account_email")
            ),
        "provider_message_id":
            str(
                data.get("provider_message_id")
                or ""
            ).strip(),
        "provider_thread_id":
            str(
                data.get("provider_thread_id")
                or ""
            ).strip(),
        "internet_message_id":
            str(
                data.get("internet_message_id")
                or ""
            ).strip(),
        "direction":
            str(
                data.get("direction")
                or "INBOUND"
            ).strip().upper(),
        "folder":
            str(
                data.get("folder")
                or "INBOX"
            ).strip(),
        "sender_email":
            normalize_email_address(
                data.get("sender_email")
            ),
        "sender_name":
            str(
                data.get("sender_name")
                or ""
            ).strip(),
        "recipients":
            list(
                data.get("recipients")
                or []
            ),
        "cc":
            list(data.get("cc") or []),
        "bcc":
            list(data.get("bcc") or []),
        "subject":
            str(
                data.get("subject")
                or ""
            ).strip(),
        "received_at":
            str(
                data.get("received_at")
                or ""
            ).strip(),
        "sent_at":
            str(
                data.get("sent_at")
                or ""
            ).strip(),
        "body_text":
            body_text,
        "body_html":
            str(
                data.get("body_html")
                or ""
            ),
        "has_attachments":
            int(
                bool(
                    data.get("has_attachments")
                    or data.get("attachments")
                )
            ),
        "raw_metadata":
            dict(
                data.get("raw_metadata")
                or {}
            ),
    }

    normalized["body_sha256"] = (
        sha256_text(body_text)
    )
    normalized["dedupe_key"] = (
        build_dedupe_key(normalized)
    )

    return normalized
