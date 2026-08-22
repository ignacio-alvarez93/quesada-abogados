"""Captura diagnóstica del DOM actual del navegador.

Infraestructura genérica y agnóstica de consumidor.

Captura el estado DOM actual del Chrome gobernado:
- documento principal;
- documentos de iframe accesibles;
- Shadow DOM abiertos;
- inventario estructural completo;
- metadatos de diagnóstico.

No conoce consumidores ni dominios funcionales.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re

DOM_CAPTURE_SCHEMA_VERSION = 1


def _evaluate_browser_value(
    browser,
    expression,
):
    """Evalúa una expresión JS y devuelve su valor.

    SeleniumBase sb_cdp expone ``evaluate`` y espera una
    expresión JavaScript sin ``return`` de nivel superior.

    Selenium WebDriver ``execute_script`` necesita en cambio
    ``return`` para devolver el resultado al proceso Python.
    """

    if hasattr(
        browser,
        "evaluate",
    ):
        return browser.evaluate(
            expression
        )

    if hasattr(
        browser,
        "execute_script",
    ):
        return browser.execute_script(
            "return "
            + str(
                expression
            ).lstrip()
        )

    raise RuntimeError(
        "DOM_CAPTURE_BROWSER_EVALUATION_UNSUPPORTED"
    )




def _safe_label(value):
    text = str(
        value
        or "dom_inspect"
    ).strip()

    text = re.sub(
        r"[^A-Za-z0-9_.-]+",
        "_",
        text,
    )

    return (
        text.strip("._")
        or "dom_inspect"
    )


def _write_text(
    path,
    value,
):
    path = Path(path)

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        str(
            value
            or ""
        ),
        encoding="utf-8",
    )


def _write_json(
    path,
    value,
):
    path = Path(path)

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _capture_browser_payload(
    browser,
):
    """
    Extrae mediante JavaScript todo el DOM accesible.

    El HTML principal corresponde al DOM vivo actual,
    no necesariamente al HTML recibido originalmente
    desde el servidor.
    """

    script = r"""
(function () {

    function cleanText(
        value,
        limit
    ) {
        const text =
            String(value || "")
            .replace(/\s+/g, " ")
            .trim();

        if (
            !limit
            || text.length <= limit
        ) {
            return text;
        }

        return text.slice(
            0,
            limit
        );
    }


    function attributesOf(
        element
    ) {
        const result = {};

        for (
            const attribute
            of Array.from(
                element.attributes
                || []
            )
        ) {
            result[
                String(
                    attribute.name
                    || ""
                )
            ] = String(
                attribute.value
                || ""
            );
        }

        return result;
    }


    function visibilityOf(
        element,
        documentObject
    ) {
        try {
            const rect =
                element
                .getBoundingClientRect();

            const view =
                documentObject
                .defaultView;

            const style =
                view
                ? view.getComputedStyle(
                    element
                )
                : null;

            return Boolean(
                rect.width > 0
                && rect.height > 0
                && (
                    !style
                    || (
                        style.display
                            !== "none"
                        && style.visibility
                            !== "hidden"
                    )
                )
            );

        } catch (_) {
            return false;
        }
    }


    function elementRecord(
        element,
        index,
        framePath,
        documentObject
    ) {
        const tag =
            String(
                element.tagName
                || ""
            ).toLowerCase();

        const record = {
            index:
                index,

            frame_path:
                framePath,

            tag:
                tag,

            id:
                String(
                    element.id
                    || ""
                ),

            name:
                String(
                    element.getAttribute?.(
                        "name"
                    )
                    || ""
                ),

            type:
                String(
                    element.getAttribute?.(
                        "type"
                    )
                    || ""
                ),

            role:
                String(
                    element.getAttribute?.(
                        "role"
                    )
                    || ""
                ),

            classes:
                Array.from(
                    element.classList
                    || []
                ),

            attributes:
                attributesOf(
                    element
                ),

            text:
                cleanText(
                    element.innerText
                    || element.textContent,
                    300
                ),

            visible:
                visibilityOf(
                    element,
                    documentObject
                ),

            disabled:
                Boolean(
                    element.disabled
                ),

            shadow_root:
                Boolean(
                    element.shadowRoot
                )
        };


        try {
            const rect =
                element
                .getBoundingClientRect();

            record.rect = {
                x:
                    Math.round(
                        rect.x
                    ),

                y:
                    Math.round(
                        rect.y
                    ),

                width:
                    Math.round(
                        rect.width
                    ),

                height:
                    Math.round(
                        rect.height
                    )
            };

        } catch (_) {
            record.rect = null;
        }


        if (
            tag === "select"
        ) {
            record.options =
                Array.from(
                    element.options
                    || []
                ).map(
                    (option) => ({
                        value:
                            String(
                                option.value
                                || ""
                            ),

                        text:
                            cleanText(
                                option.textContent,
                                200
                            ),

                        disabled:
                            Boolean(
                                option.disabled
                            ),

                        selected:
                            Boolean(
                                option.selected
                            )
                    })
                );
        }


        if (
            tag === "iframe"
            || tag === "frame"
        ) {
            record.src =
                String(
                    element.getAttribute?.(
                        "src"
                    )
                    || ""
                );
        }


        if (
            tag === "a"
        ) {
            record.href =
                String(
                    element.getAttribute?.(
                        "href"
                    )
                    || ""
                );
        }


        if (
            tag === "form"
        ) {
            record.action =
                String(
                    element.getAttribute?.(
                        "action"
                    )
                    || ""
                );

            record.method =
                String(
                    element.getAttribute?.(
                        "method"
                    )
                    || ""
                );
        }


        return record;
    }


    const result = {
        schema_version:
            1,

        captured_at:
            new Date()
                .toISOString(),

        metadata: {
            url:
                String(
                    window.location.href
                    || ""
                ),

            origin:
                String(
                    window.location.origin
                    || ""
                ),

            pathname:
                String(
                    window.location.pathname
                    || ""
                ),

            title:
                String(
                    document.title
                    || ""
                ),

            ready_state:
                String(
                    document.readyState
                    || ""
                ),

            content_type:
                String(
                    document.contentType
                    || ""
                ),

            character_set:
                String(
                    document.characterSet
                    || ""
                )
        },

        viewport: {
            inner_width:
                Number(
                    window.innerWidth
                    || 0
                ),

            inner_height:
                Number(
                    window.innerHeight
                    || 0
                ),

            client_width:
                Number(
                    document.documentElement
                        ?.clientWidth
                    || 0
                ),

            client_height:
                Number(
                    document.documentElement
                        ?.clientHeight
                    || 0
                ),

            scroll_x:
                Number(
                    window.scrollX
                    || 0
                ),

            scroll_y:
                Number(
                    window.scrollY
                    || 0
                ),

            device_pixel_ratio:
                Number(
                    window.devicePixelRatio
                    || 1
                ),

            screen_x:
                Number(
                    window.screenX
                    || 0
                ),

            screen_y:
                Number(
                    window.screenY
                    || 0
                ),

            outer_width:
                Number(
                    window.outerWidth
                    || 0
                ),

            outer_height:
                Number(
                    window.outerHeight
                    || 0
                )
        },

        html:
            (
                document.documentElement
                ? document
                    .documentElement
                    .outerHTML
                : ""
            ),

        documents:
            [],

        elements:
            [],

        frames:
            [],

        shadows:
            []
    };


    function inspectDocument(
        documentObject,
        framePath
    ) {
        if (
            !documentObject
            || !documentObject
                .documentElement
        ) {
            return;
        }


        const allElements =
            Array.from(
                documentObject
                    .querySelectorAll(
                        "*"
                    )
            );


        const documentRecord = {
            frame_path:
                framePath,

            url:
                "",

            title:
                String(
                    documentObject.title
                    || ""
                ),

            element_count:
                allElements.length,

            forms:
                documentObject
                    .querySelectorAll(
                        "form"
                    ).length,

            inputs:
                documentObject
                    .querySelectorAll(
                        "input"
                    ).length,

            textareas:
                documentObject
                    .querySelectorAll(
                        "textarea"
                    ).length,

            selects:
                documentObject
                    .querySelectorAll(
                        "select"
                    ).length,

            buttons:
                documentObject
                    .querySelectorAll(
                        "button,"
                        + "input[type=button],"
                        + "input[type=submit]"
                    ).length,

            links:
                documentObject
                    .querySelectorAll(
                        "a"
                    ).length,

            tables:
                documentObject
                    .querySelectorAll(
                        "table"
                    ).length
        };


        try {
            documentRecord.url =
                String(
                    documentObject
                        .location
                        ?.href
                    || ""
                );
        } catch (_) {
            documentRecord.url = "";
        }


        result.documents.push(
            documentRecord
        );


        allElements.forEach(
            (
                element,
                index
            ) => {
                result.elements.push(
                    elementRecord(
                        element,
                        index,
                        framePath,
                        documentObject
                    )
                );


                // -----------------------------
                // OPEN SHADOW ROOT
                // -----------------------------

                try {
                    if (
                        element.shadowRoot
                    ) {
                        result.shadows.push({
                            index:
                                result.shadows
                                    .length
                                + 1,

                            frame_path:
                                framePath,

                            host_element_index:
                                index,

                            host_tag:
                                String(
                                    element.tagName
                                    || ""
                                ).toLowerCase(),

                            host_id:
                                String(
                                    element.id
                                    || ""
                                ),

                            host_classes:
                                Array.from(
                                    element.classList
                                    || []
                                ),

                            html:
                                String(
                                    element
                                        .shadowRoot
                                        .innerHTML
                                    || ""
                                )
                        });
                    }
                } catch (_) {
                    // Shadow DOM cerrado:
                    // no es accesible desde JS de página.
                }
            }
        );


        // -------------------------------------
        // IFRAMES / FRAMES
        // -------------------------------------

        const frameElements =
            Array.from(
                documentObject
                    .querySelectorAll(
                        "iframe,frame"
                    )
            );


        frameElements.forEach(
            (
                frameElement,
                frameIndex
            ) => {
                const childPath =
                    framePath === "main"
                    ? String(
                        frameIndex + 1
                    )
                    : (
                        framePath
                        + "."
                        + String(
                            frameIndex + 1
                        )
                    );


                const frameRecord = {
                    index:
                        result.frames.length
                        + 1,

                    frame_path:
                        childPath,

                    parent_frame_path:
                        framePath,

                    tag:
                        String(
                            frameElement
                                .tagName
                            || ""
                        ).toLowerCase(),

                    id:
                        String(
                            frameElement.id
                            || ""
                        ),

                    name:
                        String(
                            frameElement
                                .getAttribute(
                                    "name"
                                )
                            || ""
                        ),

                    src:
                        String(
                            frameElement
                                .getAttribute(
                                    "src"
                                )
                            || ""
                        ),

                    accessible:
                        false,

                    url:
                        "",

                    title:
                        "",

                    html:
                        "",

                    error:
                        null
                };


                try {
                    const childDocument =
                        frameElement
                            .contentDocument;


                    if (
                        childDocument
                        && childDocument
                            .documentElement
                    ) {
                        frameRecord
                            .accessible =
                            true;

                        frameRecord.url =
                            String(
                                childDocument
                                    .location
                                    ?.href
                                || ""
                            );

                        frameRecord.title =
                            String(
                                childDocument
                                    .title
                                || ""
                            );

                        frameRecord.html =
                            String(
                                childDocument
                                    .documentElement
                                    .outerHTML
                                || ""
                            );


                        result.frames.push(
                            frameRecord
                        );


                        inspectDocument(
                            childDocument,
                            childPath
                        );

                        return;
                    }


                    frameRecord.error =
                        "FRAME_DOCUMENT_UNAVAILABLE";

                } catch (error) {
                    frameRecord.error =
                        String(
                            error?.name
                            || "FRAME_ACCESS_ERROR"
                        );
                }


                result.frames.push(
                    frameRecord
                );
            }
        );
    }


    inspectDocument(
        document,
        "main"
    );


    const totals = {
        documents:
            result.documents.length,

        elements:
            result.elements.length,

        forms:
            0,

        inputs:
            0,

        textareas:
            0,

        selects:
            0,

        buttons:
            0,

        links:
            0,

        tables:
            0,

        iframes:
            result.frames.length,

        accessible_iframes:
            result.frames.filter(
                (frame) =>
                    frame.accessible
            ).length,

        inaccessible_iframes:
            result.frames.filter(
                (frame) =>
                    !frame.accessible
            ).length,

        open_shadow_roots:
            result.shadows.length
    };


    for (
        const documentRecord
        of result.documents
    ) {
        totals.forms +=
            documentRecord.forms;

        totals.inputs +=
            documentRecord.inputs;

        totals.textareas +=
            documentRecord.textareas;

        totals.selects +=
            documentRecord.selects;

        totals.buttons +=
            documentRecord.buttons;

        totals.links +=
            documentRecord.links;

        totals.tables +=
            documentRecord.tables;
    }


    result.counts =
        totals;


    return result;
})();
"""

    result = (
        _evaluate_browser_value(
            browser,
            script,
        )
    )

    if not isinstance(
        result,
        dict,
    ):
        raise RuntimeError(
            "DOM_CAPTURE_BROWSER_PAYLOAD_INVALID"
        )

    return result


def capture_dom_snapshot(
    browser,
    output_root,
    *,
    label="dom_inspect",
    timestamp=None,
):
    """Captura el DOM vivo accesible y persiste los artefactos."""

    root = Path(
        output_root
    )

    stamp = (
        timestamp
        or datetime.now()
    )

    capture_dir = (
        root
        / (
            f"{_safe_label(label)}_"
            + stamp.strftime(
                "%Y%m%d_%H%M%S_%f"
            )
        )
    )

    capture_dir.mkdir(
        parents=True,
        exist_ok=False,
    )

    payload = (
        _capture_browser_payload(
            browser
        )
    )

    metadata = dict(
        payload.get(
            "metadata"
        )
        or {}
    )

    counts = dict(
        payload.get(
            "counts"
        )
        or {}
    )

    viewport = dict(
        payload.get(
            "viewport"
        )
        or {}
    )

    page_path = (
        capture_dir
        / "page.html"
    )

    _write_text(
        page_path,
        payload.get(
            "html",
            "",
        ),
    )


    # ==================================================
    # IFRAMES
    # ==================================================

    frame_records = []

    for frame in (
        payload.get(
            "frames"
        )
        or []
    ):
        record = dict(
            frame
        )

        html = str(
            record.pop(
                "html",
                "",
            )
            or ""
        )

        artifact = None

        if (
            record.get(
                "accessible"
            )
            and html
        ):
            index = int(
                record.get(
                    "index"
                )
                or 0
            )

            artifact = (
                "frames/"
                f"frame_{index:03d}.html"
            )

            _write_text(
                capture_dir
                / artifact,
                html,
            )

        record[
            "artifact"
        ] = artifact

        frame_records.append(
            record
        )


    # ==================================================
    # SHADOW ROOTS
    # ==================================================

    shadow_records = []

    for shadow in (
        payload.get(
            "shadows"
        )
        or []
    ):
        record = dict(
            shadow
        )

        html = str(
            record.pop(
                "html",
                "",
            )
            or ""
        )

        index = int(
            record.get(
                "index"
            )
            or 0
        )

        artifact = (
            "shadow_roots/"
            f"shadow_{index:03d}.html"
        )

        _write_text(
            capture_dir
            / artifact,
            html,
        )

        record[
            "artifact"
        ] = artifact

        shadow_records.append(
            record
        )


    # ==================================================
    # INVENTORY
    # ==================================================

    inventory = {
        "schema_version":
            DOM_CAPTURE_SCHEMA_VERSION,

        "metadata":
            metadata,

        "viewport":
            viewport,

        "counts":
            counts,

        "documents":
            list(
                payload.get(
                    "documents"
                )
                or []
            ),

        "elements":
            list(
                payload.get(
                    "elements"
                )
                or []
            ),

        "frames":
            frame_records,

        "shadow_roots":
            shadow_records,
    }

    inventory_path = (
        capture_dir
        / "dom_inventory.json"
    )

    _write_json(
        inventory_path,
        inventory,
    )


    # ==================================================
    # METADATA
    # ==================================================

    metadata_payload = {
        "schema_version":
            DOM_CAPTURE_SCHEMA_VERSION,

        "captured_at":
            payload.get(
                "captured_at"
            ),

        "url":
            metadata.get(
                "url"
            ),

        "title":
            metadata.get(
                "title"
            ),

        "viewport":
            viewport,

        "counts":
            counts,

        "artifacts": {
            "page":
                "page.html",

            "inventory":
                "dom_inventory.json",

            "frames":
                sum(
                    1
                    for record
                    in frame_records
                    if record.get(
                        "artifact"
                    )
                ),

            "shadow_roots":
                len(
                    shadow_records
                ),
        },
    }

    metadata_path = (
        capture_dir
        / "metadata.json"
    )

    _write_json(
        metadata_path,
        metadata_payload,
    )


    return {
        "capture_dir":
            capture_dir,

        "page_path":
            page_path,

        "inventory_path":
            inventory_path,

        "metadata_path":
            metadata_path,

        "counts":
            counts,

        "url":
            metadata.get(
                "url"
            ),

        "title":
            metadata.get(
                "title"
            ),
    }
