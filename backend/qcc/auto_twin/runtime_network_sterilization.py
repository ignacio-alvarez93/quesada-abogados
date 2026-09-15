"""Esterilización de referencias externas en AUTO TWIN.

El Twin debe poder ejecutarse desconectado de REAL.

La transformación es provider-neutral:

- <base> pasa a ser local;
- <link href=http(s)> se elimina;
- <script src=http(s)> se elimina;
- navegación href/action/formaction externa se neutraliza;
- src/poster/data externos se convierten en recursos inertes;
- srcset externo se elimina.

La evidencia original permanece intacta fuera del runtime materializado.
"""

from __future__ import annotations

import re


AUTO_TWIN_NETWORK_STERILIZER_SCHEMA_VERSION = 1
AUTO_TWIN_NETWORK_STERILIZER_VERSION = 1

AUTO_TWIN_NETWORK_STERILIZER_TYPE = (
    "QCC_AUTO_TWIN_NETWORK_STERILIZATION"
)


_BASE_TAG_RE = re.compile(
    r"<base\b[^>]*>",
    re.IGNORECASE | re.DOTALL,
)

_LINK_TAG_RE = re.compile(
    r"<link\b[^>]*>",
    re.IGNORECASE | re.DOTALL,
)

_SCRIPT_TAG_RE = re.compile(
    r"<script\b[^>]*>.*?</script\s*>",
    re.IGNORECASE | re.DOTALL,
)

_META_TAG_RE = re.compile(
    r"<meta\b[^>]*>",
    re.IGNORECASE | re.DOTALL,
)

_QUOTED_ATTR_RE = re.compile(
    r"\b"
    r"(?P<name>"
    r"href|src|action|formaction|poster|data|srcset"
    r")"
    r"\s*=\s*"
    r"(?P<quote>[\"'])"
    r"(?P<value>.*?)"
    r"(?P=quote)",
    re.IGNORECASE | re.DOTALL,
)

_UNQUOTED_EXTERNAL_ATTR_RE = re.compile(
    r"\b"
    r"(?P<name>"
    r"href|src|action|formaction|poster|data|srcset"
    r")"
    r"\s*=\s*"
    r"(?P<value>(?:https?:)?//[^\s>]+)",
    re.IGNORECASE,
)


def _is_external_url(
    value,
):
    value = str(
        value
        or ""
    ).strip().lower()

    return (
        value.startswith(
            "http://"
        )
        or value.startswith(
            "https://"
        )
        or value.startswith(
            "//"
        )
    )


def _attribute_value(
    tag,
    name,
):
    pattern = re.compile(
        r"\b"
        + re.escape(
            name
        )
        + r"\s*=\s*"
        + r"(?:"
        + r"(?P<q>[\"'])(?P<quoted>.*?)(?P=q)"
        + r"|"
        + r"(?P<bare>[^\s>]+)"
        + r")",
        re.IGNORECASE | re.DOTALL,
    )

    match = pattern.search(
        tag
    )

    if match is None:
        return ""

    return (
        match.group(
            "quoted"
        )
        if match.group(
            "quoted"
        )
        is not None
        else match.group(
            "bare"
        )
        or ""
    )


def _safe_attribute_value(
    name,
):
    name = str(
        name
        or ""
    ).lower()

    if name in {
        "href",
        "action",
        "formaction",
    }:
        return "#"

    if name == "srcset":
        return ""

    return "data:,"


def sterilize_runtime_html(
    source_html,
):
    if not isinstance(
        source_html,
        str,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_NETWORK_STERILIZER_HTML_INVALID"
        )

    stats = {
        "schema_version":
            AUTO_TWIN_NETWORK_STERILIZER_SCHEMA_VERSION,

        "record_type":
            AUTO_TWIN_NETWORK_STERILIZER_TYPE,

        "sterilizer_version":
            AUTO_TWIN_NETWORK_STERILIZER_VERSION,

        "base_tags_rewritten":
            0,

        "external_link_tags_removed":
            0,

        "external_script_tags_removed":
            0,

        "meta_refresh_tags_removed":
            0,

        "external_attributes_rewritten":
            0,
    }


    def replace_base(
        match,
    ):
        stats[
            "base_tags_rewritten"
        ] += 1

        return (
            '<base href="./" '
            'data-qcc-auto-twin-network-sterilized="1">'
        )


    source_html = (
        _BASE_TAG_RE.sub(
            replace_base,
            source_html,
        )
    )


    def replace_link(
        match,
    ):
        tag = match.group(
            0
        )

        href = _attribute_value(
            tag,
            "href",
        )

        if _is_external_url(
            href
        ):
            stats[
                "external_link_tags_removed"
            ] += 1

            return ""

        return tag


    source_html = (
        _LINK_TAG_RE.sub(
            replace_link,
            source_html,
        )
    )


    def replace_script(
        match,
    ):
        tag = match.group(
            0
        )

        src = _attribute_value(
            tag,
            "src",
        )

        if _is_external_url(
            src
        ):
            stats[
                "external_script_tags_removed"
            ] += 1

            return ""

        return tag


    source_html = (
        _SCRIPT_TAG_RE.sub(
            replace_script,
            source_html,
        )
    )


    def replace_meta(
        match,
    ):
        tag = match.group(
            0
        )

        http_equiv = (
            _attribute_value(
                tag,
                "http-equiv",
            )
            .strip()
            .lower()
        )

        content = _attribute_value(
            tag,
            "content",
        )

        if (
            http_equiv
            == "refresh"
            and (
                "http://"
                in content.lower()
                or "https://"
                in content.lower()
                or "url=//"
                in content.lower()
            )
        ):
            stats[
                "meta_refresh_tags_removed"
            ] += 1

            return ""

        return tag


    source_html = (
        _META_TAG_RE.sub(
            replace_meta,
            source_html,
        )
    )


    def replace_quoted_attr(
        match,
    ):
        name = (
            match.group(
                "name"
            )
            .lower()
        )

        value = match.group(
            "value"
        )

        if not _is_external_url(
            value
        ):
            return match.group(
                0
            )

        stats[
            "external_attributes_rewritten"
        ] += 1

        safe = _safe_attribute_value(
            name
        )

        return (
            name
            + '="'
            + safe
            + '"'
        )


    source_html = (
        _QUOTED_ATTR_RE.sub(
            replace_quoted_attr,
            source_html,
        )
    )


    def replace_unquoted_attr(
        match,
    ):
        name = (
            match.group(
                "name"
            )
            .lower()
        )

        stats[
            "external_attributes_rewritten"
        ] += 1

        return (
            name
            + '="'
            + _safe_attribute_value(
                name
            )
            + '"'
        )


    source_html = (
        _UNQUOTED_EXTERNAL_ATTR_RE.sub(
            replace_unquoted_attr,
            source_html,
        )
    )


    return (
        source_html,
        stats,
    )
