"""Materialización física gobernada de un MaterializationPlan.

Responsabilidades:

- consume exclusivamente operaciones explícitas del plan;
- verifica SHA256 y tamaño antes de copiar;
- construye primero en staging;
- conserva toda la evidencia fuente;
- extrae recursos archivados en MHTML;
- genera una representación local segura por estado;
- genera un registro de flows/states;
- calcula un manifest completo;
- crea una MaterializedRevision inmutable;
- publica la revisión mediante rename atómico.

No:

- ejecuta navegador;
- toca Mercurio REAL;
- usa Golden;
- modifica candidates;
- valida fidelidad;
- introduce ACTIVE;
- promociona.
"""

from __future__ import annotations

from backend.qcc.auto_twin.catalog_materialization import (
    materialize_catalog_runtime_artifact,
)

from copy import deepcopy
from email import policy
from email.parser import BytesParser
import hashlib
import html
import json
import mimetypes
import os
import posixpath
from pathlib import Path, PurePosixPath
import re
import shutil
import uuid
from urllib.parse import urlparse

from .materialized_storage_dedupe import (
    dedupe_staged_revision,
)
from .runtime_network_sterilization import (
    AUTO_TWIN_NETWORK_STERILIZER_VERSION,
    sterilize_runtime_html,
)

from .catalog_runtime_adapter import (
    AUTO_TWIN_CATALOG_RUNTIME_ADAPTER_FILENAME,
    AUTO_TWIN_CATALOG_RUNTIME_ADAPTER_VERSION,
    catalog_runtime_adapter_source,
    inject_catalog_runtime_adapter,
)

from .materialization_plan import (
    AUTO_TWIN_MATERIALIZATION_PLAN_TYPE,
    AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD,
)

from .navigation_transition_runtime import (
        restore_navigation_action_identity,
AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION,
    AUTO_TWIN_NAVIGATION_RUNTIME_FILENAME,
    build_navigation_runtime_payload,
    inject_navigation_runtime_adapter,
    outgoing_navigation_transitions,
)


from .materialized_revision import (
    build_auto_twin_materialized_revision,
)

from .materialized_revision_store import (
    AutoTwinMaterializedRevisionStore,
)


AUTO_TWIN_PHYSICAL_MATERIALIZATION_SCHEMA_VERSION = 1

AUTO_TWIN_PHYSICAL_MATERIALIZATION_TYPE = (
    "QCC_AUTO_TWIN_PHYSICAL_MATERIALIZATION"
)


AUTO_TWIN_RUNTIME_RENDERER_SCHEMA_VERSION = 1

AUTO_TWIN_RUNTIME_RENDERER_TYPE = (
    "QCC_AUTO_TWIN_RUNTIME_RENDERER"
)

AUTO_TWIN_RUNTIME_RENDERER_V3_VERSION = 3
AUTO_TWIN_RUNTIME_RENDERER_V4_VERSION = 4
AUTO_TWIN_RUNTIME_RENDERER_V5_VERSION = 5

AUTO_TWIN_RUNTIME_RENDERER_VERSION = 7


_SAFE_SEGMENT = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
)


_NETWORK_GUARD = """<meta
  http-equiv="Content-Security-Policy"
  content="default-src 'self' data: blob:;
           img-src 'self' data: blob:;
           style-src 'self' 'unsafe-inline';
           script-src 'self' 'unsafe-inline';
           font-src 'self' data: blob:;
           connect-src 'none';
           frame-src 'none';
           object-src 'none';
           form-action 'none';
           base-uri 'none';">
<script>
(() => {
  const block = (event) => {
    const anchor = event.target.closest?.("a[href]");
    if (!anchor) return;

    const href = anchor.getAttribute("href") || "";

    if (
      href.startsWith("http:") ||
      href.startsWith("https:") ||
      href.startsWith("/")
    ) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  };

  document.addEventListener("click", block, true);

  document.addEventListener(
    "submit",
    (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
    },
    true
  );
})();
</script>
"""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(
        value
    ).hexdigest()


def _canonical_bytes(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _safe_segment(
    value,
    *,
    error,
):
    result = str(
        value
        or ""
    ).strip()

    if not _SAFE_SEGMENT.fullmatch(
        result
    ):
        raise ValueError(error)

    return result


def _safe_relative_path(
    value,
    *,
    error,
):
    raw = str(
        value
        or ""
    ).strip().replace("\\", "/")

    path = PurePosixPath(raw)

    if (
        not raw
        or path.is_absolute()
        or ".." in path.parts
    ):
        raise ValueError(error)

    return path.as_posix()


def _extension(
    content_type,
    content_location,
):
    parsed = urlparse(
        content_location or ""
    )

    suffix = Path(
        parsed.path
    ).suffix

    if (
        suffix
        and len(suffix) <= 10
        and re.fullmatch(
            r"\.[A-Za-z0-9]+",
            suffix,
        )
    ):
        return suffix.lower()

    guessed = mimetypes.guess_extension(
        content_type
        or ""
    )

    return (
        guessed
        or ".bin"
    )


def _inject_guard(
    source_html,
):
    lower = source_html.lower()

    position = lower.find(
        "<head"
    )

    if position >= 0:
        close = source_html.find(
            ">",
            position,
        )

        if close >= 0:
            return (
                source_html[:close + 1]
                + "\n"
                + _NETWORK_GUARD
                + "\n"
                + source_html[close + 1:]
            )

    return (
        _NETWORK_GUARD
        + "\n"
        + source_html
    )


def _rewrite_text(
    text,
    replacements,
):
    # Longer URLs first to avoid partial replacement collisions.
    ordered = sorted(
        replacements.items(),
        key=lambda item: len(
            item[0]
        ),
        reverse=True,
    )

    for source, target in ordered:
        if not source:
            continue

        text = text.replace(
            source,
            target,
        )

        escaped = html.escape(
            source,
            quote=True,
        )

        if escaped != source:
            text = text.replace(
                escaped,
                target,
            )

    return text


def _decode_mhtml_text_part(
    part,
    payload,
):
    charset = str(
        part.get_content_charset()
        or "utf-8"
    ).strip()

    candidates = []

    if charset:
        candidates.append(
            charset
        )

    candidates.extend([
        "utf-8",
        "latin-1",
    ])

    seen = set()

    for encoding in candidates:
        normalized = encoding.lower()

        if normalized in seen:
            continue

        seen.add(
            normalized
        )

        try:
            return payload.decode(
                encoding
            )

        except (
            LookupError,
            UnicodeDecodeError,
        ):
            continue

    return payload.decode(
        "utf-8",
        errors="replace",
    )


def _resource_aliases(
    location,
    *,
    document_location=None,
):
    location = str(
        location
        or ""
    ).strip()

    if not location:
        return ()

    result = []


    def add(
        value,
    ):
        value = str(
            value
            or ""
        ).strip()

        if (
            value
            and value not in result
        ):
            result.append(
                value
            )


    add(
        location
    )

    parsed = urlparse(
        location
    )

    path = (
        parsed.path
        or ""
    )

    query = (
        (
            "?"
            + parsed.query
        )
        if parsed.query
        else ""
    )

    if path:
        add(
            path
            + query
        )

        add(
            path.lstrip("/")
            + query
        )

        name = PurePosixPath(
            path
        ).name

        if name:
            add(
                name
                + query
            )

        document_location = str(
            document_location
            or ""
        ).strip()

        if document_location:
            document_path = (
                urlparse(
                    document_location
                ).path
                or "/"
            )

            document_dir = (
                posixpath.dirname(
                    document_path
                )
                or "/"
            )

            relative = posixpath.relpath(
                path,
                start=document_dir,
            )

            if (
                relative
                and relative != "."
                and not relative.startswith(
                    "../"
                )
            ):
                add(
                    relative
                    + query
                )

    return tuple(
        result
    )


def _register_replacement(
    mapping,
    source,
    target,
):
    source = str(
        source
        or ""
    ).strip()

    if not source:
        return

    current = mapping.get(
        source
    )

    if (
        current is None
        or current == target
    ):
        mapping[
            source
        ] = target



# ============================================================
# QCC AUTO TWIN RENDERER V3
# ShadowRoot adoptedStyleSheets restoration
# ============================================================

_AUTO_TWIN_DSD_HOST_TEMPLATE_RE = re.compile(
    r"""
    <
    (?P<host>[A-Za-z][A-Za-z0-9:_-]*)
    \b
    [^>]*
    >
    (?P<between>
        (?:
            \s
            |
            <!--.*?-->
        )*
    )
    (?P<template>
        <template
        \b
        [^>]*
        \bshadowrootmode
        \s*=\s*
        ["']open["']
        [^>]*
        >
    )
    """,
    re.IGNORECASE
    | re.DOTALL
    | re.VERBOSE,
)


def _main_qcc_frame_result(
    payload,
):
    """Devuelve result del frame principal de una captura QCC."""

    if not isinstance(
        payload,
        dict,
    ):
        return {}

    frames = payload.get(
        "frames"
    )

    if not isinstance(
        frames,
        list,
    ):
        return {}

    # Contrato preferente.
    for frame in frames:
        if not isinstance(
            frame,
            dict,
        ):
            continue

        if frame.get(
            "frame_id"
        ) not in (
            0,
            "0",
        ):
            continue

        result = frame.get(
            "result"
        )

        if isinstance(
            result,
            dict,
        ):
            return result

    # Compatibilidad defensiva.
    for frame in frames:
        if not isinstance(
            frame,
            dict,
        ):
            continue

        result = frame.get(
            "result"
        )

        if isinstance(
            result,
            dict,
        ):
            return result

    return {}


def _shadow_style_evidence(
    payload,
):
    result = _main_qcc_frame_result(
        payload
    )

    roots = result.get(
        "shadow_roots"
    )

    catalog = result.get(
        "shadow_adopted_stylesheets"
    )

    return (
        roots
        if isinstance(
            roots,
            list,
        )
        else [],
        catalog
        if isinstance(
            catalog,
            list,
        )
        else [],
    )


def _escape_style_raw_text(
    css_text,
):
    # Un </style literal dentro de CSS cerraría el elemento
    # HTML durante el parseo del snapshot local.
    return re.sub(
        r"</style",
        r"<\/style",
        str(
            css_text
            or ""
        ),
        flags=re.IGNORECASE,
    )


def _find_declarative_shadow_templates(
    source_html,
):
    """Localiza DSD abierto sin regex global sobre todo el documento.

    Devuelve, en orden documental:

        {
            "host": <tag name>,
            "template_start": <offset>,
            "template_end": <offset después de >,
        }

    El scanner usa str.find/rfind sobre posiciones monotónicas.
    Sólo usa regex sobre tags individuales y pequeños.
    """

    source_html = str(
        source_html
        or ""
    )

    lower_html = source_html.lower()

    needle = "<template"

    cursor = 0

    result = []

    length = len(
        source_html
    )

    while cursor < length:
        template_start = lower_html.find(
            needle,
            cursor,
        )

        if template_start < 0:
            break

        after_name = (
            template_start
            + len(
                needle
            )
        )

        # Evitar falsos positivos tipo <template-foo>.
        if (
            after_name < length
            and (
                lower_html[
                    after_name
                ].isalnum()
                or lower_html[
                    after_name
                ]
                in "_:-"
            )
        ):
            cursor = after_name
            continue

        template_close = source_html.find(
            ">",
            after_name,
        )

        if template_close < 0:
            raise ValueError(
                "QCC_AUTO_TWIN_SHADOW_TEMPLATE_TAG_UNCLOSED"
            )

        template_tag = source_html[
            template_start:
            template_close + 1
        ]

        template_tag_lower = (
            template_tag.lower()
        )

        # Renderer V2 normaliza el snapshot a
        # shadowrootmode="open". Admitimos comillas simples,
        # dobles y espacios alrededor de '='.
        shadow_mode_match = re.search(
            r"""
            \bshadowrootmode
            \s*=\s*
            (?:
                "open"
                |
                'open'
                |
                open
            )
            (?=
                \s
                |
                /
                |
                >
            )
            """,
            template_tag_lower,
            flags=re.VERBOSE,
        )

        if not shadow_mode_match:
            cursor = (
                template_close
                + 1
            )
            continue

        # ----------------------------------------------------
        # El template DSD debe ser hijo directo inicial del host.
        # Permitimos únicamente whitespace y comentarios HTML
        # entre apertura del host y apertura del template.
        # ----------------------------------------------------

        before = template_start

        while True:
            while (
                before > 0
                and source_html[
                    before - 1
                ].isspace()
            ):
                before -= 1

            if (
                before >= 3
                and source_html[
                    before - 3:
                    before
                ]
                == "-->"
            ):
                comment_start = source_html.rfind(
                    "<!--",
                    0,
                    before - 3,
                )

                if comment_start < 0:
                    raise ValueError(
                        "QCC_AUTO_TWIN_SHADOW_TEMPLATE_COMMENT_INVALID"
                    )

                before = comment_start
                continue

            break

        if (
            before <= 0
            or source_html[
                before - 1
            ]
            != ">"
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_SHADOW_TEMPLATE_HOST_BOUNDARY_INVALID"
            )

        host_tag_end = before

        host_tag_start = source_html.rfind(
            "<",
            0,
            host_tag_end,
        )

        if host_tag_start < 0:
            raise ValueError(
                "QCC_AUTO_TWIN_SHADOW_TEMPLATE_HOST_NOT_FOUND"
            )

        host_opening_tag = source_html[
            host_tag_start:
            host_tag_end
        ]

        if host_opening_tag.startswith(
            (
                "</",
                "<!",
                "<?",
            )
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_SHADOW_TEMPLATE_HOST_INVALID"
            )

        host_match = re.match(
            r"""
            <
            \s*
            (?P<host>
                [A-Za-z]
                [A-Za-z0-9:_-]*
            )
            \b
            """,
            host_opening_tag,
            flags=re.VERBOSE,
        )

        if not host_match:
            raise ValueError(
                "QCC_AUTO_TWIN_SHADOW_TEMPLATE_HOST_TAG_INVALID"
            )

        result.append({
            "host":
                host_match.group(
                    "host"
                ),

            "template_start":
                template_start,

            "template_end":
                template_close
                + 1,
        })

        cursor = (
            template_close
            + 1
        )

    return result


def _inject_shadow_adopted_stylesheets(
    source_html,
    qcc_capture_payload,
):
    """Restaura constructable stylesheets como <style> por ShadowRoot.

    La captura QCC conserva:

        shadow_roots[]
            adopted_stylesheet_refs[]

        shadow_adopted_stylesheets[]
            stylesheet_id
            css_text

    MHTML conserva el Shadow DOM serializado mediante Declarative
    Shadow DOM. Renderer V3 materializa cada hoja REAL dentro del
    template correspondiente.

    La asociación se valida estrictamente por:

        1. cantidad de ShadowRoots;
        2. orden persistido;
        3. host_tag.

    Capturas anteriores que no tengan catálogo adoptedStyleSheets
    siguen siendo válidas y producen un no-op.
    """

    source_html = str(
        source_html
        or ""
    )

    roots, catalog = (
        _shadow_style_evidence(
            qcc_capture_payload
        )
    )

    empty_stats = {
        "evidence_available":
            False,

        "shadow_root_count":
            len(
                roots
            ),

        "template_count":
            0,

        "styled_shadow_root_count":
            0,

        "stylesheet_ref_count":
            0,

        "unique_stylesheet_count":
            0,

        "css_chars_injected":
            0,
    }

    # Backward compatibility:
    # capturas V1/V2 no llevaban adoptedStyleSheets.
    if not catalog:
        return (
            source_html,
            empty_stats,
        )

    catalog_by_id = {}

    for item in catalog:
        if not isinstance(
            item,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_SHADOW_STYLESHEET_CATALOG_INVALID"
            )

        stylesheet_id = str(
            item.get(
                "stylesheet_id"
            )
            or ""
        ).strip()

        if (
            not stylesheet_id
            or not re.fullmatch(
                r"[A-Za-z0-9._:-]+",
                stylesheet_id,
            )
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_SHADOW_STYLESHEET_ID_INVALID"
            )

        if (
            stylesheet_id
            in catalog_by_id
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_SHADOW_STYLESHEET_ID_DUPLICATE"
            )

        catalog_by_id[
            stylesheet_id
        ] = item

    matches = (
        _find_declarative_shadow_templates(
            source_html
        )
    )

    if len(
        matches
    ) != len(
        roots
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_SHADOW_ROOT_COUNT_MISMATCH"
        )

    injections = []

    styled_root_count = 0
    stylesheet_ref_count = 0
    css_chars_injected = 0
    unique_injected = set()

    for index, (
        root,
        match,
    ) in enumerate(
        zip(
            roots,
            matches,
        )
    ):
        if not isinstance(
            root,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_SHADOW_ROOT_EVIDENCE_INVALID"
            )

        captured_host = str(
            root.get(
                "host_tag"
            )
            or ""
        ).strip().lower()

        rendered_host = str(
            match[
                "host"
            ]
            or ""
        ).strip().lower()

        if (
            not captured_host
            or captured_host
            != rendered_host
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_SHADOW_ROOT_ORDER_MISMATCH"
                f": index={index}"
                f" captured={captured_host!r}"
                f" rendered={rendered_host!r}"
            )

        refs = root.get(
            "adopted_stylesheet_refs"
        )

        if refs is None:
            refs = []

        if not isinstance(
            refs,
            list,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_SHADOW_STYLESHEET_REFS_INVALID"
            )

        style_blocks = []

        for raw_ref in refs:
            stylesheet_id = str(
                raw_ref
                or ""
            ).strip()

            stylesheet = (
                catalog_by_id.get(
                    stylesheet_id
                )
            )

            if stylesheet is None:
                raise ValueError(
                    "QCC_AUTO_TWIN_SHADOW_STYLESHEET_REF_INVALID"
                    f": {stylesheet_id!r}"
                )

            stylesheet_ref_count += 1

            if not bool(
                stylesheet.get(
                    "readable"
                )
            ):
                continue

            css_text = str(
                stylesheet.get(
                    "css_text"
                )
                or ""
            )

            if not css_text.strip():
                continue

            safe_css = (
                _escape_style_raw_text(
                    css_text
                )
            )

            style_blocks.append(
                "\n"
                '<style data-qcc-adopted-stylesheet="'
                + stylesheet_id
                + '">\n'
                + safe_css
                + "\n</style>"
            )

            css_chars_injected += len(
                css_text
            )

            unique_injected.add(
                stylesheet_id
            )

        if style_blocks:
            styled_root_count += 1

            injections.append(
                (
                    match[
                        "template_end"
                    ],
                    "".join(
                        style_blocks
                    ),
                )
            )

    # Construcción lineal.
    #
    # `injections` ya está en el mismo orden que los matches
    # sobre source_html. No debemos concatenar la cadena
    # completa una vez por ShadowRoot: con cientos de roots
    # y CSS constructable grande eso degenera a O(N²).
    #
    # Se emite source_html exactamente una vez y cada bloque
    # de estilos exactamente una vez.
    rendered_parts = []
    cursor = 0

    for position, block in injections:
        if position < cursor:
            raise ValueError(
                "QCC_AUTO_TWIN_SHADOW_STYLE_INJECTION_ORDER_INVALID"
            )

        rendered_parts.append(
            source_html[
                cursor:position
            ]
        )

        rendered_parts.append(
            block
        )

        cursor = position

    rendered_parts.append(
        source_html[
            cursor:
        ]
    )

    rendered = "".join(
        rendered_parts
    )

    stats = {
        "evidence_available":
            True,

        "shadow_root_count":
            len(
                roots
            ),

        "template_count":
            len(
                matches
            ),

        "styled_shadow_root_count":
            styled_root_count,

        "stylesheet_ref_count":
            stylesheet_ref_count,

        "unique_stylesheet_count":
            len(
                unique_injected
            ),

        "css_chars_injected":
            css_chars_injected,
    }

    return (
        rendered,
        stats,
    )


def _normalize_declarative_shadow_dom(
    source_html,
):
    """Normaliza la serialización MHTML de Chrome.

    Chrome/MHTML puede serializar Shadow DOM abierto como:

        <template shadowmode="open">

    El runtime HTML local necesita la forma declarativa estándar:

        <template shadowrootmode="open">
    """

    return re.sub(
        r"\bshadowmode(?=\s*=)",
        "shadowrootmode",
        source_html,
        flags=re.IGNORECASE,
    )


def _extract_mhtml_assets(
    *,
    mhtml_path,
    runtime_dir,
):
    message = BytesParser(
        policy=policy.default
    ).parsebytes(
        mhtml_path.read_bytes()
    )

    leaf_parts = []

    for part in message.walk():
        if part.is_multipart():
            continue

        payload = part.get_payload(
            decode=True
        )

        if payload is None:
            continue

        content_type = str(
            part.get_content_type()
            or ""
        ).lower()

        location = str(
            part.get(
                "Content-Location"
            )
            or ""
        ).strip()

        content_id = str(
            part.get(
                "Content-ID"
            )
            or ""
        ).strip().strip("<>")

        leaf_parts.append({
            "part":
                part,

            "payload":
                payload,

            "content_type":
                content_type,

            "content_location":
                location,

            "content_id":
                content_id,
        })

    rendered_html = None
    document_location = ""

    for item in leaf_parts:
        if (
            item[
                "content_type"
            ]
            != "text/html"
        ):
            continue

        if rendered_html is not None:
            continue

        rendered_html = (
            _decode_mhtml_text_part(
                item["part"],
                item["payload"],
            )
        )

        document_location = item[
            "content_location"
        ]

    parts = []

    for item in leaf_parts:
        content_type = item[
            "content_type"
        ]

        if content_type == "text/html":
            continue

        payload = item[
            "payload"
        ]

        location = item[
            "content_location"
        ]

        digest = _sha256_bytes(
            payload
        )

        extension = _extension(
            content_type,
            location,
        )

        filename = (
            digest[:24]
            + extension
        )

        parts.append({
            **item,

            "sha256":
                digest,

            "filename":
                filename,
        })

    assets_dir = (
        runtime_dir
        / "assets"
    )

    assets_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Mapping used from runtime HTML.
    html_replacements = {}

    # Mapping used from peer assets such as CSS.
    peer_replacements = {}

    for item in parts:
        filename = item[
            "filename"
        ]

        location = item[
            "content_location"
        ]

        for alias in _resource_aliases(
            location,
            document_location=(
                document_location
            ),
        ):
            _register_replacement(
                html_replacements,
                alias,
                (
                    "assets/"
                    + filename
                ),
            )

            _register_replacement(
                peer_replacements,
                alias,
                filename,
            )

        content_id = item[
            "content_id"
        ]

        if content_id:
            cid = (
                "cid:"
                + content_id
            )

            _register_replacement(
                html_replacements,
                cid,
                (
                    "assets/"
                    + filename
                ),
            )

            _register_replacement(
                peer_replacements,
                cid,
                filename,
            )

    written = []

    for item in parts:
        payload = item[
            "payload"
        ]

        content_type = item[
            "content_type"
        ]

        if (
            content_type.startswith(
                "text/"
            )
            or "javascript"
            in content_type
            or "json"
            in content_type
        ):
            decoded = (
                _decode_mhtml_text_part(
                    item["part"],
                    payload,
                )
            )

            decoded = _rewrite_text(
                decoded,
                peer_replacements,
            )

            payload = decoded.encode(
                "utf-8"
            )

        target = (
            assets_dir
            / item[
                "filename"
            ]
        )

        if not target.exists():
            target.write_bytes(
                payload
            )

        written.append({
            "path":
                target,

            "content_type":
                content_type,

            "content_location":
                item[
                    "content_location"
                ],
        })

    return (
        html_replacements,
        written,
        rendered_html,
    )

def _artifact_record(
    *,
    root,
    path,
    kind,
):
    content = path.read_bytes()

    return {
        "path":
            path.relative_to(
                root
            ).as_posix(),

        "kind":
            kind,

        "sha256":
            _sha256_bytes(
                content
            ),

        "size_bytes":
            len(content),
    }


# QCC_AUTO_TWIN_CARRY_FORWARD_CANONICAL_PATH_IDENTITY_V1
#
# El pathname forma parte de la identidad física del estado,
# pero parámetros de sesión servlet como ;jsessionid son
# volátiles y no pueden invalidar un carry-forward.
#
# No se eliminan otros path parameters.
_VOLATILE_PATH_SESSION_PARAMETER = re.compile(
    r";jsessionid=[^/?#;]*",
    re.IGNORECASE,
)


def _canonical_carry_forward_pathname(
    pathname,
):
    value = str(
        pathname
        or ""
    )

    return (
        _VOLATILE_PATH_SESSION_PARAMETER.sub(
            "",
            value,
        )
    )


def materialize_auto_twin_plan(
    *,
    plan,
    source_root,
    materialized_root,
    procedure_code,
    flow_variant,
):
    if not isinstance(
        plan,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_INVALID"
        )

    if (
        plan.get(
            "plan_type"
        )
        != AUTO_TWIN_MATERIALIZATION_PLAN_TYPE
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_TYPE_INVALID"
        )

    twin_key = _safe_segment(
        plan.get(
            "twin_key"
        ),
        error=(
            "QCC_AUTO_TWIN_MATERIALIZATION_TWIN_KEY_INVALID"
        ),
    )

    procedure = _safe_segment(
        procedure_code,
        error=(
            "QCC_AUTO_TWIN_MATERIALIZATION_PROCEDURE_INVALID"
        ),
    )

    variant = _safe_segment(
        flow_variant,
        error=(
            "QCC_AUTO_TWIN_MATERIALIZATION_VARIANT_INVALID"
        ),
    )

    source_root = Path(
        source_root
    )

    materialized_root = Path(
        materialized_root
    )

    twin_root = (
        materialized_root
        / twin_key
    )

    twin_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    staging = (
        twin_root
        / (
            ".staging-"
            + uuid.uuid4().hex
        )
    )

    staging.mkdir()

    try:
        # ----------------------------------------------------
        # Materialized carry-forward
        # ----------------------------------------------------
        #
        # Una revisión materializada es autosuficiente.
        # Si Site Architecture ya podó el capture histórico,
        # un estado no modificado puede heredarse byte-for-byte
        # desde la revisión materializada previa.
        #
        # Nunca se usa esta vía para adoptar evidencia REAL CHANGED.
        # Esa decisión pertenece al reconciler/candidate pipeline.

        carry_forward_states = [
            state
            for state in (
                plan.get(
                    "state_manifest"
                )
                or ()
            )
            if (
                isinstance(
                    state,
                    dict,
                )
                and state.get(
                    "source_mode"
                )
                == (
                    AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD
                )
            )
        ]

        if carry_forward_states:
            base_revision_id = _safe_segment(
                plan.get(
                    "base_materialized_revision_id"
                ),
                error=(
                    "QCC_AUTO_TWIN_CARRY_FORWARD_BASE_REVISION_INVALID"
                ),
            )

            base_revision_dir = (
                materialized_root
                / twin_key
                / base_revision_id
            )

            if not base_revision_dir.is_dir():
                raise ValueError(
                    "QCC_AUTO_TWIN_CARRY_FORWARD_BASE_REVISION_MISSING:"
                    + base_revision_id
                )

            renderer_marker = (
                base_revision_dir
                / "runtime"
                / "renderer.json"
            )

            if not renderer_marker.is_file():
                raise ValueError(
                    "QCC_AUTO_TWIN_CARRY_FORWARD_RENDERER_MARKER_MISSING"
                )

            try:
                renderer_payload = json.loads(
                    renderer_marker.read_text(
                        encoding="utf-8"
                    )
                )

                base_renderer_version = int(
                    renderer_payload.get(
                        "renderer_version"
                    )
                )

            except Exception as exc:
                raise ValueError(
                    "QCC_AUTO_TWIN_CARRY_FORWARD_RENDERER_INVALID"
                ) from exc

            if (
                base_renderer_version
                != AUTO_TWIN_RUNTIME_RENDERER_VERSION
            ):
                raise ValueError(
                    "QCC_AUTO_TWIN_CARRY_FORWARD_RENDERER_MISMATCH"
                )

            base_states_root = (
                base_revision_dir
                / "states"
            )

            for state in carry_forward_states:
                state_index = int(
                    state[
                        "state_index"
                    ]
                )

                state_id = _safe_segment(
                    state[
                        "state_id"
                    ],
                    error=(
                        "QCC_AUTO_TWIN_CARRY_FORWARD_STATE_ID_INVALID"
                    ),
                )

                matches = [
                    path
                    for path in (
                        base_states_root.glob(
                            "*-" + state_id
                        )
                    )
                    if path.is_dir()
                ]

                if len(matches) != 1:
                    raise ValueError(
                        "QCC_AUTO_TWIN_CARRY_FORWARD_STATE_AMBIGUOUS:"
                        + state_id
                    )

                source_state_dir = matches[0]

                state_metadata_path = (
                    source_state_dir
                    / "runtime"
                    / "state.json"
                )

                if not state_metadata_path.is_file():
                    raise ValueError(
                        "QCC_AUTO_TWIN_CARRY_FORWARD_STATE_METADATA_MISSING:"
                        + state_id
                    )

                try:
                    carried_metadata = json.loads(
                        state_metadata_path.read_text(
                            encoding="utf-8"
                        )
                    )

                except Exception as exc:
                    raise ValueError(
                        "QCC_AUTO_TWIN_CARRY_FORWARD_STATE_METADATA_INVALID:"
                        + state_id
                    ) from exc

                expected_functional_state = (
                    str(
                        state.get(
                            "functional_state"
                        )
                        or ""
                    ).strip()
                    or None
                )

                actual_functional_state = (
                    str(
                        carried_metadata.get(
                            "functional_state"
                        )
                        or ""
                    ).strip()
                    or None
                )

                if (
                    str(
                        carried_metadata.get(
                            "state_id"
                        )
                        or ""
                    )
                    != state_id
                    or str(
                        carried_metadata.get(
                            "source_capture_id"
                        )
                        or ""
                    )
                    != str(
                        state.get(
                            "source_capture_id"
                        )
                        or ""
                    )
                    or _canonical_carry_forward_pathname(
                        carried_metadata.get(
                            "pathname"
                        )
                    )
                    != _canonical_carry_forward_pathname(
                        state.get(
                            "pathname"
                        )
                    )
                    or actual_functional_state
                    != expected_functional_state
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_CARRY_FORWARD_STATE_IDENTITY_MISMATCH:"
                        + state_id
                    )

                destination_state_dir = (
                    staging
                    / "states"
                    / (
                        f"{state_index:02d}-"
                        + state_id
                    )
                )

                shutil.copytree(
                    source_state_dir,
                    destination_state_dir,
                )

        # ----------------------------------------------------
        # Exact REAL source copy
        # ----------------------------------------------------

        for operation in plan.get(
            "artifact_operations",
            (),
        ):
            source_reference = _safe_relative_path(
                operation.get(
                    "source_reference"
                ),
                error=(
                    "QCC_AUTO_TWIN_MATERIALIZATION_SOURCE_REFERENCE_INVALID"
                ),
            )

            destination_path = _safe_relative_path(
                operation.get(
                    "destination_path"
                ),
                error=(
                    "QCC_AUTO_TWIN_MATERIALIZATION_DESTINATION_INVALID"
                ),
            )

            source = (
                source_root
                / Path(
                    source_reference
                )
            )

            if not source.is_file():
                raise ValueError(
                    "QCC_AUTO_TWIN_MATERIALIZATION_SOURCE_MISSING:"
                    + source_reference
                )

            content = source.read_bytes()

            if (
                len(content)
                != operation.get(
                    "size_bytes"
                )
            ):
                raise ValueError(
                    "QCC_AUTO_TWIN_MATERIALIZATION_SOURCE_SIZE_MISMATCH:"
                    + source_reference
                )

            if (
                _sha256_bytes(
                    content
                )
                != operation.get(
                    "sha256"
                )
            ):
                raise ValueError(
                    "QCC_AUTO_TWIN_MATERIALIZATION_SOURCE_HASH_MISMATCH:"
                    + source_reference
                )

            destination = (
                staging
                / Path(
                    destination_path
                )
            )

            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            destination.write_bytes(
                content
            )

        # ----------------------------------------------------
        # Runtime per state
        # ----------------------------------------------------

        runtime_registry = {
            "schema_version":
                AUTO_TWIN_PHYSICAL_MATERIALIZATION_SCHEMA_VERSION,

            "record_type":
                AUTO_TWIN_PHYSICAL_MATERIALIZATION_TYPE,

            "runtime_renderer_version":
                AUTO_TWIN_RUNTIME_RENDERER_VERSION,

            "twin_key":
                twin_key,

            "procedure_code":
                procedure,

            "flow_variant":
                variant,

            "plan_id":
                plan.get(
                    "plan_id"
                ),

            "source_evidence_sha256":
                plan.get(
                    "source_evidence_sha256"
                ),

            "states": [],
        }

        revision_state_manifest = []

        for state in plan.get(
            "state_manifest",
            (),
        ):
            state_index = int(
                state[
                    "state_index"
                ]
            )

            state_id = _safe_segment(
                state[
                    "state_id"
                ],
                error=(
                    "QCC_AUTO_TWIN_MATERIALIZATION_STATE_ID_INVALID"
                ),
            )

            state_root = (
                staging
                / "states"
                / (
                    f"{state_index:02d}-"
                    + state_id
                )
            )

            if (
                state.get(
                    "source_mode"
                )
                == (
                    AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD
                )
            ):
                state_json_path = (
                    state_root
                    / "runtime"
                    / "state.json"
                )

                if not state_json_path.is_file():
                    raise ValueError(
                        "QCC_AUTO_TWIN_CARRY_FORWARD_RUNTIME_STATE_MISSING:"
                        + state_id
                    )

                try:
                    state_metadata = json.loads(
                        state_json_path.read_text(
                            encoding="utf-8"
                        )
                    )

                except Exception as exc:
                    raise ValueError(
                        "QCC_AUTO_TWIN_CARRY_FORWARD_RUNTIME_STATE_INVALID:"
                        + state_id
                    ) from exc

                runtime_registry[
                    "states"
                ].append({
                    **deepcopy(
                        state_metadata
                    ),

                    "runtime_entry":
                        (
                            "states/"
                            + f"{state_index:02d}-"
                            + state_id
                            + "/runtime/index.html"
                        ),
                })

                revision_state_manifest.append({
                    "state_id":
                        state_id,

                    "source_capture_id":
                        state[
                            "source_capture_id"
                        ],

                    "pathname":
                        state[
                            "pathname"
                        ],

                    "functional_state":
                        state[
                            "functional_state"
                        ],
                })

                continue

            source_html_path = (
                state_root
                / "source"
                / "page.html"
            )

            source_mhtml_path = (
                state_root
                / "source"
                / "page.mhtml"
            )

            if not source_html_path.is_file():
                raise ValueError(
                    "QCC_AUTO_TWIN_MATERIALIZATION_PAGE_HTML_MISSING"
                )

            if not source_mhtml_path.is_file():
                raise ValueError(
                    "QCC_AUTO_TWIN_MATERIALIZATION_PAGE_MHTML_MISSING"
                )

            runtime_dir = (
                state_root
                / "runtime"
            )

            runtime_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

            (
                replacements,
                _assets,
                rendered_html,
            ) = _extract_mhtml_assets(
                mhtml_path=(
                    source_mhtml_path
                ),
                runtime_dir=(
                    runtime_dir
                ),
            )

            if rendered_html is None:
                source_html = (
                    source_html_path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )
                )

                runtime_html_source = (
                    "PAGE_HTML_FALLBACK"
                )

            else:
                source_html = (
                    rendered_html
                )

                runtime_html_source = (
                    "MHTML_RENDERED_HTML"
                )

            local_html = (
                _normalize_declarative_shadow_dom(
                    source_html
                )
            )

            # QCC_AUTO_TWIN_RENDERER_V3_SHADOW_STYLES
            #
            # La evidencia se copia previamente dentro del estado
            # materializado. Renderer V3 NO vuelve a consultar REAL:
            # solo consume el qcc_capture inmutable de este source state.
            qcc_capture_path = (
                state_root
                / "evidence"
                / "qcc_capture.json"
            )

            qcc_capture_payload = {}

            if qcc_capture_path.is_file():
                try:
                    qcc_capture_payload = json.loads(
                        qcc_capture_path.read_text(
                            encoding="utf-8"
                        )
                    )

                except (
                    OSError,
                    TypeError,
                    ValueError,
                    json.JSONDecodeError,
                ) as exc:
                    raise ValueError(
                        "QCC_AUTO_TWIN_SHADOW_STYLE_EVIDENCE_INVALID"
                    ) from exc

            (
                local_html,
                shadow_style_stats,
            ) = _inject_shadow_adopted_stylesheets(
                local_html,
                qcc_capture_payload,
            )

            (
                runtime_dir
                / "shadow_styles.json"
            ).write_text(
                json.dumps(
                    shadow_style_stats,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )

            # QCC_AUTO_TWIN_SUPPLEMENTAL_CATALOG_EVIDENCE
            #
            # La procedencia visual permanece en source_capture_id.
            # El catálogo puede proceder de una captura REAL posterior
            # de la MISMA identidad/path, expresamente validada por el plan.
            catalog_runtime_payload = None

            catalog_source_capture_id = str(
                state.get(
                    "catalog_source_capture_id"
                )
                or ""
            ).strip()

            if catalog_source_capture_id:
                catalog_result = (
                    materialize_catalog_runtime_artifact(
                        qcc_capture_path=(
                            Path(
                                source_root
                            )
                            / catalog_source_capture_id
                            / "qcc_capture.json"
                        ),
                        runtime_dir=(
                            runtime_dir
                        ),
                        source_capture_id=(
                            catalog_source_capture_id
                        ),
                        expected_pathname=(
                            state[
                                "pathname"
                            ]
                        ),
                        required_profile_key=(
                            plan[
                                "required_profile_key"
                            ]
                        ),
                    )
                )

                catalog_runtime_payload = (
                    catalog_result[
                        "payload"
                    ]
                )

                expected_catalog_fingerprint = str(
                    state.get(
                        "catalog_fingerprint"
                    )
                    or ""
                )

                actual_catalog_fingerprint = str(
                    catalog_runtime_payload.get(
                        "catalog_fingerprint"
                    )
                    or ""
                )

                if (
                    expected_catalog_fingerprint
                    != actual_catalog_fingerprint
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_CATALOG_SUPPLEMENT_FINGERPRINT_MISMATCH"
                    )

                if (
                    int(
                        state.get(
                            "catalog_count"
                        )
                        or 0
                    )
                    != int(
                        catalog_runtime_payload.get(
                            "catalog_count"
                        )
                        or 0
                    )
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_CATALOG_SUPPLEMENT_COUNT_MISMATCH"
                    )

                if (
                    int(
                        state.get(
                            "catalog_option_count"
                        )
                        or 0
                    )
                    != int(
                        catalog_runtime_payload.get(
                            "option_count"
                        )
                        or 0
                    )
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_CATALOG_SUPPLEMENT_OPTION_COUNT_MISMATCH"
                    )

            local_html = _rewrite_text(
                local_html,
                replacements,
            )

            # QCC_AUTO_TWIN_NETWORK_STERILIZATION
            #
            # Runtime Twin must not retain actionable absolute
            # references to REAL. Evidence files remain immutable;
            # only the generated localhost runtime is sterilized.
            (
                local_html,
                network_sterilization_stats,
            ) = sterilize_runtime_html(
                local_html
            )

            (
                runtime_dir
                / "network_sterilization.json"
            ).write_text(
                json.dumps(
                    network_sterilization_stats,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )

            local_html = _inject_guard(
                local_html
            )

            # QCC_AUTO_TWIN_STATIC_CATALOG_RUNTIME_ADAPTER
            #
            # Catalog runtime is local-only and consumes the already
            # materialized/sanitized supplemental payload.
            #
            # No fetch/XHR and no provider-specific behavior.
            if catalog_runtime_payload is not None:
                (
                    runtime_dir
                    / AUTO_TWIN_CATALOG_RUNTIME_ADAPTER_FILENAME
                ).write_text(
                    catalog_runtime_adapter_source(),
                    encoding="utf-8",
                    newline="\n",
                )

                local_html = (
                    inject_catalog_runtime_adapter(
                        local_html,
                        catalog_runtime_payload,
                    )
                )

            (
                runtime_dir
                / "index.html"
            ).write_text(
                local_html,
                encoding="utf-8",
                newline="\n",
            )

            state_metadata = {
                "state_id":
                    state_id,

                "procedure_code":
                    procedure,

                "flow_variant":
                    variant,

                "source_capture_id":
                    state[
                        "source_capture_id"
                    ],

                "pathname":
                    state[
                        "pathname"
                    ],

                "functional_state":
                    state[
                        "functional_state"
                    ],

                "rendering_profile_id":
                    state[
                        "rendering_profile_id"
                    ],

                "runtime_renderer_version":
                    AUTO_TWIN_RUNTIME_RENDERER_VERSION,

                "runtime_html_source":
                    runtime_html_source,

                "network_sterilizer_version":
                    AUTO_TWIN_NETWORK_STERILIZER_VERSION,

                "fingerprint":
                    state.get(
                        "fingerprint"
                    ),
            }

            if catalog_runtime_payload is not None:
                state_metadata[
                    "catalog_runtime_adapter_version"
                ] = (
                    AUTO_TWIN_CATALOG_RUNTIME_ADAPTER_VERSION
                )

                state_metadata[
                    "catalog_runtime_adapter"
                ] = (
                    "STATIC_CATALOG_V1"
                )

                state_metadata[
                    "catalog_source_capture_id"
                ] = (
                    catalog_source_capture_id
                )

                state_metadata[
                    "catalog_fingerprint"
                ] = (
                    catalog_runtime_payload[
                        "catalog_fingerprint"
                    ]
                )

                state_metadata[
                    "catalog_count"
                ] = int(
                    catalog_runtime_payload[
                        "catalog_count"
                    ]
                )

                state_metadata[
                    "catalog_option_count"
                ] = int(
                    catalog_runtime_payload[
                        "option_count"
                    ]
                )

            (
                runtime_dir
                / "state.json"
            ).write_text(
                json.dumps(
                    state_metadata,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )

            runtime_registry[
                "states"
            ].append({
                **deepcopy(
                    state_metadata
                ),

                "runtime_entry":
                    (
                        "states/"
                        + f"{state_index:02d}-"
                        + state_id
                        + "/runtime/index.html"
                    ),
            })

            revision_state_manifest.append({
                "state_id":
                    state_id,

                "source_capture_id":
                    state[
                        "source_capture_id"
                    ],

                "pathname":
                    state[
                        "pathname"
                    ],

                "functional_state":
                    state[
                        "functional_state"
                    ],
            })

        # ----------------------------------------------------
        # Global registry + human inspection index
        # ----------------------------------------------------

        runtime_root = (
            staging
            / "runtime"
        )

        runtime_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        # QCC_AUTO_TWIN_CAUSAL_NAVIGATION_RUNTIME_V1
        #
        # Resolve exclusively against the physical materialized state
        # registry. This also restores fingerprint authority for
        # MATERIALIZED_CARRY_FORWARD states through runtime/state.json.
        navigation_runtime_payload = (
            build_navigation_runtime_payload(
                plan.get(
                    "navigation_transitions",
                    (),
                ),
                runtime_registry[
                    "states"
                ],
            )
        )

        (
            runtime_root
            / AUTO_TWIN_NAVIGATION_RUNTIME_FILENAME
        ).write_text(
            json.dumps(
                navigation_runtime_payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )

        runtime_registry[
            "navigation_runtime_adapter_version"
        ] = (
            AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION
        )

        runtime_registry[
            "navigation_transition_count"
        ] = int(
            navigation_runtime_payload[
                "transition_count"
            ]
        )

        # Deliberately second-pass:
        #
        # - fresh REAL_CAPTURE HTML already exists;
        # - carried-forward HTML has already been copied;
        # - runtime registry now contains authoritative fingerprints
        #   for both.
        #
        # The local listener is inserted before the network guard so
        # learned navigation owns the action before any original inline
        # onclick/form behavior can execute.
        for runtime_state in runtime_registry[
            "states"
        ]:
            outgoing = (
                outgoing_navigation_transitions(
                    navigation_runtime_payload,
                    runtime_state.get(
                        "state_id"
                    ),
                )
            )

            runtime_entry = _safe_relative_path(
                runtime_state.get(
                    "runtime_entry"
                ),
                error=(
                    "QCC_AUTO_TWIN_NAVIGATION_RUNTIME_ENTRY_INVALID"
                ),
            )

            runtime_html_path = (
                staging
                / Path(
                    runtime_entry
                )
            )

            if not runtime_html_path.is_file():
                raise ValueError(
                    "QCC_AUTO_TWIN_NAVIGATION_RUNTIME_HTML_MISSING:"
                    + str(
                        runtime_state.get(
                            "state_id"
                        )
                        or ""
                    )
                )

            local_html = (
                runtime_html_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            )

            # QCC_AUTO_TWIN_NAVIGATION_ACTION_IDENTITY_RESTORE
            #
            # Chrome MHTML may preserve the visual node while omitting
            # inline event attributes observed by QCC in REAL.
            #
            # Restore ONLY attributes explicitly owned by outgoing
            # learned transitions and only from unique QCC evidence.
            if outgoing:
                navigation_qcc_capture_path = (
                    runtime_html_path.parent.parent
                    / "evidence"
                    / "qcc_capture.json"
                )

                if not navigation_qcc_capture_path.is_file():
                    raise ValueError(
                        "QCC_AUTO_TWIN_NAVIGATION_QCC_CAPTURE_MISSING:"
                        + str(
                            runtime_state.get(
                                "state_id"
                            )
                            or ""
                        )
                    )

                try:
                    navigation_qcc_capture_payload = json.loads(
                        navigation_qcc_capture_path.read_text(
                            encoding="utf-8"
                        )
                    )

                except (
                    OSError,
                    json.JSONDecodeError,
                ) as exc:
                    raise ValueError(
                        "QCC_AUTO_TWIN_NAVIGATION_QCC_CAPTURE_INVALID:"
                        + str(
                            runtime_state.get(
                                "state_id"
                            )
                            or ""
                        )
                    ) from exc

                local_html = (
                    restore_navigation_action_identity(
                        local_html,
                        qcc_capture_payload=(
                            navigation_qcc_capture_payload
                        ),
                        transitions=outgoing,
                    )
                )

            local_html = (
                inject_navigation_runtime_adapter(
                    local_html,
                    state_id=(
                        runtime_state.get(
                            "state_id"
                        )
                    ),
                    transitions=outgoing,
                )
            )

            runtime_html_path.write_text(
                local_html,
                encoding="utf-8",
                newline="\n",
            )

        (
            runtime_root
            / "renderer.json"
        ).write_text(
            json.dumps(
                {
                    "schema_version":
                        AUTO_TWIN_RUNTIME_RENDERER_SCHEMA_VERSION,

                    "record_type":
                        AUTO_TWIN_RUNTIME_RENDERER_TYPE,

                    "renderer_version":
                        AUTO_TWIN_RUNTIME_RENDERER_VERSION,

                    "canonical_runtime_html":
                        "MHTML_RENDERED_HTML",

                    "declarative_shadow_dom":
                        True,

                    "relative_asset_rebasing":
                        True,

                    "shadow_adopted_stylesheets":
                        True,

                    "shadow_adopted_stylesheet_mode":
                        "INLINE_STYLE_PER_ROOT",

                    "catalog_runtime_adapter_version":
                        AUTO_TWIN_CATALOG_RUNTIME_ADAPTER_VERSION,

                    "catalog_runtime_adapter_mode":
                        "INLINE_STATIC_CATALOG_PAYLOAD",

                    "network_sterilizer_version":
                        AUTO_TWIN_NETWORK_STERILIZER_VERSION,

                    "network_sterilization_mode":
                        "LOCAL_RUNTIME_EXTERNAL_REFERENCE_STRIP",
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )

        (
            runtime_root
            / "registry.json"
        ).write_text(
            json.dumps(
                runtime_registry,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )

        links = []

        for item in runtime_registry[
            "states"
        ]:
            links.append(
                '<li><a href="../'
                + item[
                    "runtime_entry"
                ]
                + '">'
                + html.escape(
                    item[
                        "state_id"
                    ]
                )
                + "</a></li>"
            )

        inspection_html = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>QCC AUTO TWIN · EX01 TITULAR</title>
<style>
body { font-family: sans-serif; margin: 32px; }
li { margin: 12px 0; }
code { background: #eee; padding: 2px 5px; }
</style>
</head>
<body>
<h1>QCC AUTO TWIN</h1>
<p>Procedure: <code>%s</code></p>
<p>Variant: <code>%s</code></p>
<p>Plan: <code>%s</code></p>
<ul>
%s
</ul>
</body>
</html>
""" % (
            html.escape(
                procedure
            ),
            html.escape(
                variant
            ),
            html.escape(
                str(
                    plan.get(
                        "plan_id"
                    )
                )
            ),
            "\n".join(
                links
            ),
        )

        (
            runtime_root
            / "index.html"
        ).write_text(
            inspection_html,
            encoding="utf-8",
            newline="\n",
        )

        # ----------------------------------------------------
        # Immutable artifact manifest
        # ----------------------------------------------------

        artifact_manifest = []

        for path in sorted(
            item
            for item
            in staging.rglob("*")
            if item.is_file()
        ):
            relative = path.relative_to(
                staging
            ).as_posix()

            if (
                "/runtime/"
                in (
                    "/"
                    + relative
                )
                or relative.startswith(
                    "runtime/"
                )
            ):
                kind = "RUNTIME"

            elif "/source/" in (
                "/"
                + relative
            ):
                kind = "SOURCE"

            else:
                kind = "EVIDENCE"

            artifact_manifest.append(
                _artifact_record(
                    root=staging,
                    path=path,
                    kind=kind,
                )
            )

        content_identity = [
            {
                "path":
                    item[
                        "path"
                    ],

                "sha256":
                    item[
                        "sha256"
                    ],

                "size_bytes":
                    item[
                        "size_bytes"
                    ],
            }
            for item
            in artifact_manifest
        ]

        content_sha256 = (
            _sha256_bytes(
                _canonical_bytes(
                    content_identity
                )
            )
        )

        revision = (
            build_auto_twin_materialized_revision(
                twin_key=(
                    twin_key
                ),
                materialization_mode=(
                    plan[
                        "materialization_mode"
                    ]
                ),
                source_capture_ids=(
                    plan[
                        "source_capture_ids"
                    ]
                ),
                candidate_refs=[],
                state_manifest=(
                    revision_state_manifest
                ),
                artifact_manifest=(
                    artifact_manifest
                ),
                content_sha256=(
                    content_sha256
                ),
            )
        )

        revision_id = (
            revision[
                "materialized_revision_id"
            ]
        )

        final_dir = (
            twin_root
            / revision_id
        )

        if final_dir.exists():
            # Idempotent build: compare expected content.
            for artifact in artifact_manifest:
                existing = (
                    final_dir
                    / artifact[
                        "path"
                    ]
                )

                if not existing.is_file():
                    raise ValueError(
                        "QCC_AUTO_TWIN_MATERIALIZATION_EXISTING_REVISION_INCOMPLETE"
                    )

                content = existing.read_bytes()

                if (
                    len(content)
                    != artifact[
                        "size_bytes"
                    ]
                    or _sha256_bytes(
                        content
                    )
                    != artifact[
                        "sha256"
                    ]
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_MATERIALIZATION_EXISTING_REVISION_CONFLICT"
                    )

            shutil.rmtree(
                staging
            )

        else:
            # Optimización física best-effort: nunca falla la
            # materialización; el layout lógico no cambia.
            dedupe_staged_revision(
                staging,
                twin_root=twin_root,
                artifact_manifest=artifact_manifest,
            )

            os.rename(
                staging,
                final_dir,
            )

        store = (
            AutoTwinMaterializedRevisionStore(
                root=(
                    materialized_root
                )
            )
        )

        persisted = store.save(
            revision
        )

        return {
            "revision":
                persisted,

            "revision_dir":
                str(
                    final_dir
                ),

            "runtime_index":
                str(
                    final_dir
                    / "runtime"
                    / "index.html"
                ),

            "state_count":
                len(
                    revision_state_manifest
                ),

            "artifact_count":
                len(
                    artifact_manifest
                ),

            "content_sha256":
                content_sha256,
        }

    except Exception:
        if staging.exists():
            shutil.rmtree(
                staging,
                ignore_errors=True,
            )

        raise
