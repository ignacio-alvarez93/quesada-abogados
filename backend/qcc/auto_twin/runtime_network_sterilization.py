"""Esterilización de referencias externas en AUTO TWIN.

El Twin debe poder ejecutarse desconectado de REAL.

La transformación es provider-neutral:

- <base> pasa a ser local;
- <link href=http(s)> se elimina;
- <script src=http(s)> se elimina;
- <script> capturado sin src (REAL inline) se neutraliza: el cuerpo
  capturado nunca llega a ejecutarse en el Twin;
- navegación href/action/formaction externa se neutraliza;
- src/poster/data externos se convierten en recursos inertes;
- srcset externo se elimina;
- cualquier atributo manejador de evento (on*) se elimina de toda
  etiqueta de apertura capturada;
- esquemas `javascript:` en atributos que portan URL se neutralizan,
  incluso con ofuscación léxica (mayúsculas, espacios, referencias de
  caracteres HTML);
- `data:` ejecutables (text/html, xhtml+xml, javascript, svg+xml) se
  neutralizan en sumideros de navegación y de ejecución, preservando
  recursos de imagen `data:` ordinarios.

La evidencia original permanece intacta fuera del runtime materializado.
"""

from __future__ import annotations

import html
import re


AUTO_TWIN_NETWORK_STERILIZER_SCHEMA_VERSION = 1
AUTO_TWIN_NETWORK_STERILIZER_VERSION = 5

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
    r"(?P<open><script\b[^>]*>)"
    r"(?P<body>.*?)"
    r"(?P<close></script\s*>)",
    re.IGNORECASE | re.DOTALL,
)

# Attribute-presence check (not value extraction): a <script> that
# carries a src attribute -- even an empty one -- is treated by the
# HTML spec as an external script whose inline body is never executed.
# Only the true no-src case is captured REAL inline application logic.
_SRC_ATTR_PRESENT_RE = re.compile(
    r"(?<![\w-])src\s*=",
    re.IGNORECASE,
)

# Generic HTML/SVG event-handler attribute (onclick/onload/onerror/...)
# on ANY captured opening tag -- not just <script> -- is an independent
# captured-REAL execution vector and must not survive neutralization.
# The leading `\s+` requirement means a name is only matched when "on"
# immediately follows attribute-boundary whitespace, which is why
# "data-onclick" (preceded by "-", not whitespace) is left untouched.
_EVENT_HANDLER_ATTR_RE = re.compile(
    r"\s+on[a-zA-Z]+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)",
    re.IGNORECASE,
)

# Any captured HTML/SVG opening tag (never a closing tag or a comment,
# since both start with a non-letter right after "<"). Used to apply
# _EVENT_HANDLER_ATTR_RE uniformly across every element, including
# <svg>, <img>, <body>, <a xlink:href>, etc.
_OPEN_TAG_RE = re.compile(
    r"<[a-zA-Z][^>]*>",
    re.DOTALL,
)

_INLINE_SCRIPT_MARKER_ATTR_RE = re.compile(
    r"\s+data-qcc-auto-twin-network-sterilized\s*=\s*"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s>]+)",
    re.IGNORECASE,
)

_INLINE_SCRIPT_MARKER_VALUE = "captured-inline-script"

_INERT_INLINE_SCRIPT_BODY = (
    "\n/* QCC_AUTO_TWIN_CAPTURED_INLINE_SCRIPT_NEUTRALIZED */\n"
)

_META_TAG_RE = re.compile(
    r"<meta\b[^>]*>",
    re.IGNORECASE | re.DOTALL,
)

# URL-bearing attribute names governed by the sterilizer. `xlink:href`
# is the SVG equivalent of `href` (e.g. <a xlink:href="...">,
# <image xlink:href="...">) and is classified/neutralized identically.
_URL_ATTR_NAME_ALTERNATION = (
    r"(?:xlink:)?href|src|action|formaction|poster|data"
)

_QUOTED_ATTR_RE = re.compile(
    r"\b"
    r"(?P<name>"
    + _URL_ATTR_NAME_ALTERNATION
    + r")"
    r"\s*=\s*"
    r"(?P<quote>[\"'])"
    r"(?P<value>.*?)"
    r"(?P=quote)",
    re.IGNORECASE | re.DOTALL,
)

# Unquoted URL-bearing attribute values. Unlike the V1 contract (which
# only recognised the external http(s)/protocol-relative shape here),
# this now classifies every unquoted value the same way as the quoted
# path so an unquoted `javascript:`/unsafe `data:` value cannot bypass
# neutralization merely by omitting quotes.
_UNQUOTED_ATTR_RE = re.compile(
    r"\b"
    r"(?P<name>"
    + _URL_ATTR_NAME_ALTERNATION
    + r")"
    r"\s*=\s*"
    r"(?P<value>[^\s>\"']+)",
    re.IGNORECASE,
)

# srcset carries a comma-separated list of independent
# "<url> [descriptor]" candidates. Unlike every other attribute above,
# a single srcset value may legitimately mix candidates that resolved
# to local runtime assets with candidates that remained unresolved
# external references -- so it must be sterilized candidate-by-
# candidate rather than as one all-or-nothing value.
_SRCSET_ATTR_RE = re.compile(
    r"\bsrcset\s*=\s*"
    r"(?P<quote>[\"'])"
    r"(?P<value>.*?)"
    r"(?P=quote)",
    re.IGNORECASE | re.DOTALL,
)

_STYLE_TAG_RE = re.compile(
    r"(?P<open><style\b[^>]*>)"
    r"(?P<body>.*?)"
    r"(?P<close></style\s*>)",
    re.IGNORECASE | re.DOTALL,
)

# CSS url(...) is the single syntax underlying every covered property
# (background-image, list-style-image, cursor, @font-face src, @import,
# generated content, ...) -- sterilizing this one construct covers all
# of them without per-property logic.
_CSS_URL_RE = re.compile(
    r"url\(\s*"
    r"(?:"
    r"(?P<q>[\"'])(?P<qval>.*?)(?P=q)"
    r"|"
    r"(?P<uval>[^)\"']*)"
    r")"
    r"\s*\)",
    re.IGNORECASE | re.DOTALL,
)

# @import also accepts a bare quoted string instead of url(...).
_CSS_IMPORT_STRING_RE = re.compile(
    r"(?P<prefix>@import\s+)"
    r"(?P<q>[\"'])(?P<value>.*?)(?P=q)",
    re.IGNORECASE | re.DOTALL,
)

_CSS_INERT_URL_VALUE = "data:,"


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


# ASCII tab/newline/CR are stripped anywhere in a URL by browsers
# before scheme classification (WHATWG URL parsing), and HTML character
# references (e.g. "&#x73;" -> "s", "&#58;" -> ":") are decoded before
# the browser ever sees a scheme -- so both must be undone before this
# sterilizer classifies a captured attribute value as safe or unsafe.
_URL_CONTROL_CHAR_RE = re.compile(
    r"[\t\r\n]"
)


def _canonical_url_scheme_candidate(
    value,
):
    decoded = html.unescape(
        str(
            value
            or ""
        )
    )

    decoded = (
        _URL_CONTROL_CHAR_RE.sub(
            "",
            decoded,
        )
    )

    return (
        decoded
        .strip()
        .lower()
    )


def _is_javascript_url(
    value,
):
    return (
        _canonical_url_scheme_candidate(
            value
        ).startswith(
            "javascript:"
        )
    )


# `data:` document/script MIME types capable of causing browser
# document or script execution. Ordinary resource MIME types (e.g.
# image/png, image/jpeg, font/woff2) are deliberately NOT listed here
# so legitimate non-navigation resource usage keeps working.
_UNSAFE_DATA_MIME_RE = re.compile(
    r"^data:\s*(?:"
    r"text/html"
    r"|application/xhtml\+xml"
    r"|text/javascript"
    r"|application/javascript"
    r"|application/x-javascript"
    r"|image/svg\+xml"
    r")\b"
)


def _is_executable_data_url(
    value,
):
    candidate = (
        _canonical_url_scheme_candidate(
            value
        )
    )

    return bool(
        _UNSAFE_DATA_MIME_RE.match(
            candidate
        )
    )


# Navigation-bearing attributes: a top-level/frame navigation sink
# where any `data:` value is treated as unsafe generically (FAIL
# CLOSED) rather than attempting to prove an arbitrary data payload is
# harmless. `xlink:href` is normalized to "href" before this lookup.
_NAV_ATTR_NAMES = {
    "href",
    "action",
    "formaction",
}


def _is_unsafe_url_value(
    name_key,
    value,
):
    if _is_javascript_url(
        value
    ):
        return True

    candidate = (
        _canonical_url_scheme_candidate(
            value
        )
    )

    if not candidate.startswith(
        "data:"
    ):
        return False

    if name_key in _NAV_ATTR_NAMES:
        return True

    return _is_executable_data_url(
        value
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


def _sterilize_srcset_value(
    value,
):
    kept = []
    removed = 0

    for raw_candidate in value.split(","):
        candidate = raw_candidate.strip()

        if not candidate:
            continue

        url = candidate.split(
            None,
            1,
        )[0]

        if _is_external_url(url):
            removed += 1
            continue

        kept.append(candidate)

    return (
        ", ".join(kept),
        removed,
    )


def _safe_attribute_value(
    name,
):
    name = str(
        name
        or ""
    ).lower()

    name = name.rsplit(
        ":",
        1,
    )[-1]

    if name in _NAV_ATTR_NAMES:
        return "#"

    return "data:,"


def _neutralized_inline_script_open_tag(
    open_tag,
):
    # The <script> element's own event-handler attributes
    # (onload/onerror/...) are stripped uniformly by the generic
    # _OPEN_TAG_RE / _EVENT_HANDLER_ATTR_RE pass that runs later over
    # the whole document, so only marker bookkeeping happens here.
    without_marker = (
        _INLINE_SCRIPT_MARKER_ATTR_RE.sub(
            "",
            open_tag,
        )
    )

    body_prefix = without_marker[:-1].rstrip()

    return (
        body_prefix
        + ' data-qcc-auto-twin-network-sterilized="'
        + _INLINE_SCRIPT_MARKER_VALUE
        + '">'
    )


def sterilize_runtime_css(
    source_css,
):
    if not isinstance(
        source_css,
        str,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_NETWORK_STERILIZER_CSS_INVALID"
        )

    stats = {
        "css_url_references_rewritten":
            0,

        "css_import_references_rewritten":
            0,
    }


    def replace_url(
        match,
    ):
        quote = match.group(
            "q"
        )

        value = (
            match.group(
                "qval"
            )
            if quote is not None
            else match.group(
                "uval"
            )
        ) or ""

        if not _is_external_url(
            value.strip()
        ):
            return match.group(
                0
            )

        stats[
            "css_url_references_rewritten"
        ] += 1

        if quote:
            return (
                "url("
                + quote
                + _CSS_INERT_URL_VALUE
                + quote
                + ")"
            )

        return (
            "url("
            + _CSS_INERT_URL_VALUE
            + ")"
        )


    source_css = (
        _CSS_URL_RE.sub(
            replace_url,
            source_css,
        )
    )


    def replace_import_string(
        match,
    ):
        value = match.group(
            "value"
        )

        if not _is_external_url(
            value.strip()
        ):
            return match.group(
                0
            )

        stats[
            "css_import_references_rewritten"
        ] += 1

        quote = match.group(
            "q"
        )

        return (
            match.group(
                "prefix"
            )
            + quote
            + _CSS_INERT_URL_VALUE
            + quote
        )


    source_css = (
        _CSS_IMPORT_STRING_RE.sub(
            replace_import_string,
            source_css,
        )
    )


    return (
        source_css,
        stats,
    )


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

        "inline_scripts_neutralized":
            0,

        "meta_refresh_tags_removed":
            0,

        "external_attributes_rewritten":
            0,

        "external_srcset_candidates_removed":
            0,

        "css_url_references_rewritten":
            0,

        "css_import_references_rewritten":
            0,

        "event_handler_attributes_removed":
            0,

        "unsafe_executable_urls_neutralized":
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
        open_tag = match.group(
            "open"
        )

        body = match.group(
            "body"
        )

        close_tag = match.group(
            "close"
        )

        if _SRC_ATTR_PRESENT_RE.search(
            open_tag
        ):
            src = _attribute_value(
                open_tag,
                "src",
            )

            if _is_external_url(
                src
            ):
                stats[
                    "external_script_tags_removed"
                ] += 1

                return ""

            return (
                open_tag
                + body
                + close_tag
            )

        # QCC_AUTO_TWIN_CAPTURED_INLINE_SCRIPT_NEUTRALIZATION
        #
        # A captured <script> with no src attribute carries REAL
        # application JavaScript verbatim. It must never execute
        # inside the Twin: the element is preserved for local
        # auditability, but its body is replaced with deterministic
        # inert content before any Twin-authored script is injected.
        stats[
            "inline_scripts_neutralized"
        ] += 1

        return (
            _neutralized_inline_script_open_tag(
                open_tag
            )
            + _INERT_INLINE_SCRIPT_BODY
            + close_tag
        )


    source_html = (
        _SCRIPT_TAG_RE.sub(
            replace_script,
            source_html,
        )
    )


    # QCC_AUTO_TWIN_EVENT_HANDLER_ATTRIBUTE_NEUTRALIZATION
    #
    # Any captured opening tag -- <button onclick>, <body onload>,
    # <svg onload>, <img onerror>, ... -- can carry REAL JavaScript via
    # a generic on* attribute, independent of the <script> element.
    # This runs over every opening tag in the document, including the
    # just-neutralized <script> element's own open tag.
    def replace_open_tag(
        match,
    ):
        tag = match.group(
            0
        )

        new_tag, removed = (
            _EVENT_HANDLER_ATTR_RE.subn(
                "",
                tag,
            )
        )

        if removed:
            stats[
                "event_handler_attributes_removed"
            ] += removed

        return new_tag


    source_html = (
        _OPEN_TAG_RE.sub(
            replace_open_tag,
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


    def replace_style(
        match,
    ):
        (
            new_body,
            css_stats,
        ) = sterilize_runtime_css(
            match.group(
                "body"
            )
        )

        stats[
            "css_url_references_rewritten"
        ] += css_stats[
            "css_url_references_rewritten"
        ]

        stats[
            "css_import_references_rewritten"
        ] += css_stats[
            "css_import_references_rewritten"
        ]

        return (
            match.group(
                "open"
            )
            + new_body
            + match.group(
                "close"
            )
        )


    source_html = (
        _STYLE_TAG_RE.sub(
            replace_style,
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

        name_key = name.rsplit(
            ":",
            1,
        )[-1]

        value = match.group(
            "value"
        )

        if _is_external_url(
            value
        ):
            stats[
                "external_attributes_rewritten"
            ] += 1

        elif _is_unsafe_url_value(
            name_key,
            value,
        ):
            stats[
                "unsafe_executable_urls_neutralized"
            ] += 1

        else:
            return match.group(
                0
            )

        safe = _safe_attribute_value(
            name_key
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


    def replace_srcset(
        match,
    ):
        quote = match.group(
            "quote"
        )

        value = match.group(
            "value"
        )

        new_value, removed = (
            _sterilize_srcset_value(
                value
            )
        )

        if removed:
            stats[
                "external_srcset_candidates_removed"
            ] += removed

        return (
            "srcset="
            + quote
            + new_value
            + quote
        )


    source_html = (
        _SRCSET_ATTR_RE.sub(
            replace_srcset,
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

        name_key = name.rsplit(
            ":",
            1,
        )[-1]

        value = match.group(
            "value"
        )

        if _is_external_url(
            value
        ):
            stats[
                "external_attributes_rewritten"
            ] += 1

        elif _is_unsafe_url_value(
            name_key,
            value,
        ):
            stats[
                "unsafe_executable_urls_neutralized"
            ] += 1

        else:
            return match.group(
                0
            )

        return (
            name
            + '="'
            + _safe_attribute_value(
                name_key
            )
            + '"'
        )


    source_html = (
        _UNQUOTED_ATTR_RE.sub(
            replace_unquoted_attr,
            source_html,
        )
    )


    return (
        source_html,
        stats,
    )
