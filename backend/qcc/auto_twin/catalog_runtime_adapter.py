"""Runtime local genérico para catálogos AUTO TWIN.

V2 desacopla la funcionalidad del Twin de la supervivencia física de los
nodos option capturados.

Fuentes:

    catalogs.json
        ↓
    payload embebido
        ↓
    selector/host capturado
        ↓
    combobox capturado
        ↓
    ┌───────────────────────────────┐
    │ options DOM capturadas viven │ → reutilizar
    └───────────────────────────────┘
                   o
    ┌───────────────────────────────┐
    │ options DOM no sobreviven     │ → popup local desde catálogo
    └───────────────────────────────┘

No conoce proveedor ni implementación concreta.
"""

from __future__ import annotations

import json


AUTO_TWIN_CATALOG_RUNTIME_ADAPTER_V1_VERSION = 1

AUTO_TWIN_CATALOG_RUNTIME_ADAPTER_VERSION = 2

AUTO_TWIN_CATALOG_RUNTIME_ADAPTER_TYPE = (
    "QCC_AUTO_TWIN_STATIC_CATALOG_RUNTIME"
)

AUTO_TWIN_CATALOG_RUNTIME_ADAPTER_FILENAME = (
    "catalog_runtime_adapter.js"
)

AUTO_TWIN_CATALOG_RUNTIME_PAYLOAD_ELEMENT_ID = (
    "qcc-auto-twin-catalog-runtime-data"
)

AUTO_TWIN_CATALOG_RUNTIME_SCRIPT_MARKER = (
    "data-qcc-auto-twin-catalog-runtime"
)


CATALOG_RUNTIME_ADAPTER_JS = r"""
(() => {
    "use strict";

    const VERSION = 2;
    const DATA_ID =
        "qcc-auto-twin-catalog-runtime-data";

    const GLOBAL_KEY =
        "__qccAutoTwinCatalogRuntime";

    if (window[GLOBAL_KEY]) {
        return;
    }

    const normalize = value =>
        String(value || "")
        .replace(/\s+/g, " ")
        .trim();

    const dataNode =
        document.getElementById(
            DATA_ID
        );

    if (!dataNode) {
        return;
    }

    let payload = null;

    try {
        payload = JSON.parse(
            dataNode.textContent || "{}"
        );
    } catch (_error) {
        return;
    }

    const catalogs =
        Array.isArray(payload.catalogs)
        ? payload.catalogs
        : [];

    const bindings = new Map();

    let openBinding = null;


    // --------------------------------------------------
    // Document-level local fallback UI.
    // --------------------------------------------------

    const ensureDocumentStyle = () => {
        if (
            document.querySelector(
                "style[data-qcc-auto-twin-catalog-document-style]"
            )
        ) {
            return;
        }

        const style =
            document.createElement(
                "style"
            );

        style.setAttribute(
            "data-qcc-auto-twin-catalog-document-style",
            "2"
        );

        style.textContent = `
[data-qcc-auto-twin-catalog-popup] {
    position: fixed !important;
    display: none !important;
    z-index: 2147483646 !important;
    box-sizing: border-box !important;
    max-height: 300px !important;
    overflow-y: auto !important;
    overflow-x: hidden !important;
    background: #ffffff !important;
    color: #222222 !important;
    border: 1px solid #b8b8b8 !important;
    border-radius: 2px !important;
    box-shadow: 0 4px 12px rgba(0,0,0,.22) !important;
    font-family: Arial, sans-serif !important;
    font-size: 14px !important;
}

[data-qcc-auto-twin-catalog-popup]
[role="option"] {
    display: block !important;
    box-sizing: border-box !important;
    padding: 7px 10px !important;
    min-height: 30px !important;
    cursor: pointer !important;
    background: #ffffff !important;
    color: #222222 !important;
    white-space: normal !important;
}

[data-qcc-auto-twin-catalog-popup]
[role="option"]:hover {
    background: #eeeeee !important;
}

[data-qcc-auto-twin-catalog-popup]
[role="option"][aria-selected="true"] {
    font-weight: 600 !important;
    background: #eeeeee !important;
}

[data-qcc-auto-twin-catalog-popup]
[role="option"][aria-disabled="true"] {
    opacity: .5 !important;
    cursor: default !important;
}

[data-qcc-auto-twin-catalog-popup]
[data-qcc-auto-twin-open="1"] {
    display: block !important;
}
        `;

        (
            document.head
            || document.documentElement
        ).appendChild(
            style
        );
    };


    ensureDocumentStyle();


    const runtime = {
        version:
            VERSION,

        recordType:
            "QCC_AUTO_TWIN_STATIC_CATALOG_RUNTIME",

        pathname:
            payload.pathname || "",

        bindings,

        ready:
            false,

        select(
            selector,
            label
        ) {
            const binding =
                bindings.get(
                    selector
                );

            if (!binding) {
                return false;
            }

            return (
                binding.selectByLabel(
                    label
                )
            );
        },

        snapshot() {
            return Array.from(
                bindings.values()
            ).map(
                binding =>
                    binding.snapshot()
            );
        },
    };


    window[
        GLOBAL_KEY
    ] = runtime;


    const emit = (
        host,
        catalog,
        state
    ) => {
        host.dispatchEvent(
            new CustomEvent(
                "qcc-auto-twin-catalog-change",
                {
                    bubbles:
                        true,

                    composed:
                        true,

                    detail: {
                        catalog_key:
                            catalog.catalog_key
                            || "",

                        selector:
                            catalog.selector
                            || "",

                        selected_label:
                            state.selected_label
                            || "",

                        selected_value:
                            state.selected_value
                            || "",

                        selected_index:
                            state.selected_index,
                    },
                }
            )
        );
    };


    const ensureShadowStyle = root => {
        if (!root) {
            return;
        }

        if (
            root.querySelector(
                "style[data-qcc-auto-twin-catalog-style]"
            )
        ) {
            return;
        }

        const style =
            document.createElement(
                "style"
            );

        style.setAttribute(
            "data-qcc-auto-twin-catalog-style",
            "2"
        );

        style.textContent = `
[data-qcc-auto-twin-force-visible="1"] {
    display: block !important;
    visibility: visible !important;
    opacity: 1 !important;
    pointer-events: auto !important;
}
        `;

        root.appendChild(
            style
        );
    };


    const visibleAncestors = (
        root,
        optionNodes
    ) => {
        const touched =
            new Set();

        for (
            const optionNode
            of optionNodes
        ) {
            let current =
                optionNode;

            while (
                current
                && current !== root
            ) {
                let hidden =
                    false;

                try {
                    const computed =
                        getComputedStyle(
                            current
                        );

                    hidden = (
                        computed.display
                        === "none"

                        || computed.visibility
                        === "hidden"

                        || computed.opacity
                        === "0"
                    );

                } catch (_error) {
                    hidden =
                        false;
                }

                if (
                    hidden
                    || current.hasAttribute(
                        "hidden"
                    )
                    || current.getAttribute(
                        "aria-hidden"
                    ) === "true"
                ) {
                    current.setAttribute(
                        "data-qcc-auto-twin-force-visible",
                        "1"
                    );

                    touched.add(
                        current
                    );
                }

                current =
                    current.parentElement;
            }
        }

        return touched;
    };


    const clearVisibleAncestors = (
        touched
    ) => {
        for (
            const element
            of touched
        ) {
            element.removeAttribute(
                "data-qcc-auto-twin-force-visible"
            );
        }

        touched.clear();
    };


    const bindCatalog = catalog => {
        const selector =
            normalize(
                catalog.selector
            );

        if (!selector) {
            return null;
        }

        let host = null;

        try {
            host =
                document.querySelector(
                    selector
                );
        } catch (_error) {
            return null;
        }

        if (!host) {
            return null;
        }

        const options =
            Array.isArray(
                catalog.options
            )
            ? catalog.options
            : [];

        const root =
            host.shadowRoot;

        if (root) {
            ensureShadowStyle(
                root
            );
        }

        const combobox =
            root
            ? root.querySelector(
                '[role="combobox"]'
            )
            : null;

        const capturedOptions =
            root
            ? Array.from(
                root.querySelectorAll(
                    '[role="option"]'
                )
            )
            : [];

        const optionByLabel =
            new Map();

        options.forEach(
            (
                option,
                index
            ) => {
                const label =
                    normalize(
                        option.label
                    );

                if (
                    label
                    && !optionByLabel.has(
                        label
                    )
                ) {
                    optionByLabel.set(
                        label,
                        {
                            option,
                            index,
                        }
                    );
                }
            }
        );

        const state = {
            selected_label:
                normalize(
                    (
                        catalog.state
                        || {}
                    ).selected_label
                ),

            selected_value:
                normalize(
                    (
                        catalog.state
                        || {}
                    ).selected_value
                ),

            selected_index:
                Number.isInteger(
                    (
                        catalog.state
                        || {}
                    ).selected_index
                )
                ? catalog.state.selected_index
                : -1,
        };


        host.setAttribute(
            "data-qcc-auto-twin-catalog",
            "1"
        );

        host.setAttribute(
            "data-qcc-auto-twin-catalog-key",
            normalize(
                catalog.catalog_key
            )
        );

        host.setAttribute(
            "data-qcc-auto-twin-catalog-selector",
            selector
        );

        if (!options.length) {
            host.setAttribute(
                "data-qcc-auto-twin-catalog-empty",
                "1"
            );
        }


        let forcedVisible =
            new Set();

        let fallbackPopup =
            null;

        const fallbackOptionNodes =
            [];


        const positionFallbackPopup = () => {
            if (!fallbackPopup) {
                return;
            }

            const rect =
                host.getBoundingClientRect();

            const viewportWidth =
                Math.max(
                    document.documentElement.clientWidth,
                    window.innerWidth || 0
                );

            const viewportHeight =
                Math.max(
                    document.documentElement.clientHeight,
                    window.innerHeight || 0
                );

            let width =
                Math.max(
                    rect.width,
                    220
                );

            width =
                Math.min(
                    width,
                    Math.max(
                        220,
                        viewportWidth - 16
                    )
                );

            let left =
                rect.left;

            if (
                left + width
                > viewportWidth - 8
            ) {
                left =
                    Math.max(
                        8,
                        viewportWidth
                        - width
                        - 8
                    );
            }

            let top =
                rect.bottom + 2;

            const maxHeight =
                Math.min(
                    300,
                    Math.max(
                        120,
                        viewportHeight - 16
                    )
                );

            if (
                top + maxHeight
                > viewportHeight - 8
            ) {
                top =
                    Math.max(
                        8,
                        rect.top
                        - maxHeight
                        - 2
                    );
            }

            fallbackPopup.style.left =
                `${Math.round(left)}px`;

            fallbackPopup.style.top =
                `${Math.round(top)}px`;

            fallbackPopup.style.width =
                `${Math.round(width)}px`;

            fallbackPopup.style.maxHeight =
                `${Math.round(maxHeight)}px`;
        };


        let selectByIndex =
            null;


        const ensureFallbackPopup = () => {
            if (fallbackPopup) {
                return fallbackPopup;
            }

            fallbackPopup =
                document.createElement(
                    "div"
                );

            fallbackPopup.setAttribute(
                "data-qcc-auto-twin-catalog-popup",
                "1"
            );

            fallbackPopup.setAttribute(
                "data-qcc-auto-twin-catalog-selector",
                selector
            );

            fallbackPopup.setAttribute(
                "role",
                "listbox"
            );


            options.forEach(
                (
                    option,
                    index
                ) => {
                    const label =
                        normalize(
                            option.label
                        );

                    if (!label) {
                        return;
                    }

                    const node =
                        document.createElement(
                            "div"
                        );

                    node.setAttribute(
                        "role",
                        "option"
                    );

                    node.setAttribute(
                        "data-qcc-auto-twin-catalog-option-index",
                        String(
                            index
                        )
                    );

                    node.setAttribute(
                        "aria-disabled",
                        option.disabled
                        ? "true"
                        : "false"
                    );

                    node.textContent =
                        label;

                    node.addEventListener(
                        "click",
                        event => {
                            event.preventDefault();
                            event.stopPropagation();

                            if (
                                option.disabled
                                || typeof selectByIndex
                                !== "function"
                            ) {
                                return;
                            }

                            selectByIndex(
                                index
                            );
                        },
                        true
                    );

                    fallbackPopup.appendChild(
                        node
                    );

                    fallbackOptionNodes.push(
                        node
                    );
                }
            );


            document.body.appendChild(
                fallbackPopup
            );

            positionFallbackPopup();

            return fallbackPopup;
        };


        const allRuntimeOptionNodes = () => {
            if (
                capturedOptions.length
            ) {
                return capturedOptions;
            }

            return fallbackOptionNodes;
        };


        const reflectState = () => {
            host.setAttribute(
                "data-qcc-auto-twin-selected-label",
                state.selected_label
            );

            host.setAttribute(
                "data-qcc-auto-twin-selected-value",
                state.selected_value
            );

            host.setAttribute(
                "data-qcc-auto-twin-selected-index",
                String(
                    state.selected_index
                )
            );

            if (combobox) {
                combobox.setAttribute(
                    "data-qcc-auto-twin-selected-label",
                    state.selected_label
                );

                combobox.setAttribute(
                    "aria-valuetext",
                    state.selected_label
                );

                const input =
                    combobox.matches(
                        "input,textarea"
                    )
                    ? combobox
                    : combobox.querySelector(
                        "input,textarea"
                    );

                if (input) {
                    try {
                        input.value =
                            state.selected_label;
                    } catch (_error) {
                        // Read-only surfaces remain harmless.
                    }
                }
            }


            for (
                const optionNode
                of allRuntimeOptionNodes()
            ) {
                const label =
                    normalize(
                        optionNode.textContent
                    );

                const selected = (
                    label
                    && label
                    === state.selected_label
                );

                optionNode.setAttribute(
                    "aria-selected",
                    selected
                    ? "true"
                    : "false"
                );

                if (selected) {
                    optionNode.setAttribute(
                        "data-qcc-auto-twin-selected",
                        "1"
                    );

                } else {
                    optionNode.removeAttribute(
                        "data-qcc-auto-twin-selected"
                    );
                }
            }
        };


        const close = () => {
            host.removeAttribute(
                "data-qcc-auto-twin-open"
            );

            if (combobox) {
                combobox.setAttribute(
                    "aria-expanded",
                    "false"
                );
            }

            clearVisibleAncestors(
                forcedVisible
            );

            if (fallbackPopup) {
                fallbackPopup.removeAttribute(
                    "data-qcc-auto-twin-open"
                );
            }

            if (
                openBinding
                && openBinding.host
                === host
            ) {
                openBinding =
                    null;
            }
        };


        const open = () => {
            if (!options.length) {
                return false;
            }

            if (
                openBinding
                && openBinding.host
                !== host
            ) {
                openBinding.close();
            }

            host.setAttribute(
                "data-qcc-auto-twin-open",
                "1"
            );

            if (combobox) {
                combobox.setAttribute(
                    "aria-expanded",
                    "true"
                );
            }


            if (
                capturedOptions.length
            ) {
                forcedVisible =
                    visibleAncestors(
                        root,
                        capturedOptions
                    );

            } else {
                const popup =
                    ensureFallbackPopup();

                popup.setAttribute(
                    "data-qcc-auto-twin-open",
                    "1"
                );

                positionFallbackPopup();

                reflectState();
            }


            openBinding =
                binding;

            return true;
        };


        selectByIndex = index => {
            const item =
                options[
                    index
                ];

            if (
                !item
                || item.disabled
            ) {
                return false;
            }

            const label =
                normalize(
                    item.label
                );

            if (!label) {
                return false;
            }

            const rawValue =
                normalize(
                    item.value
                );

            state.selected_label =
                label;

            // Never manufacture raw provider values.
            state.selected_value =
                rawValue;

            state.selected_index =
                index;

            options.forEach(
                (
                    option,
                    optionIndex
                ) => {
                    option.selected = (
                        optionIndex
                        === index
                    );
                }
            );

            reflectState();

            close();

            host.dispatchEvent(
                new Event(
                    "input",
                    {
                        bubbles:
                            true,

                        composed:
                            true,
                    }
                )
            );

            host.dispatchEvent(
                new Event(
                    "change",
                    {
                        bubbles:
                            true,

                        composed:
                            true,
                    }
                )
            );

            emit(
                host,
                catalog,
                state
            );

            return true;
        };


        const selectByLabel = label => {
            const match =
                optionByLabel.get(
                    normalize(
                        label
                    )
                );

            if (!match) {
                return false;
            }

            return selectByIndex(
                match.index
            );
        };


        const binding = {
            catalog,
            host,
            root,
            combobox,
            capturedOptions,
            fallbackOptionNodes,
            state,
            open,
            close,
            selectByIndex,
            selectByLabel,

            snapshot() {
                return {
                    catalog_key:
                        catalog.catalog_key
                        || "",

                    selector,

                    option_count:
                        options.length,

                    captured_option_count:
                        capturedOptions.length,

                    runtime_option_count:
                        capturedOptions.length
                        || fallbackOptionNodes.length,

                    fallback:
                        capturedOptions.length
                        === 0
                        && options.length > 0,

                    selected_label:
                        state.selected_label,

                    selected_value:
                        state.selected_value,

                    selected_index:
                        state.selected_index,

                    open:
                        host.getAttribute(
                            "data-qcc-auto-twin-open"
                        ) === "1",
                };
            },
        };


        if (combobox) {
            combobox.addEventListener(
                "click",
                event => {
                    event.preventDefault();
                    event.stopImmediatePropagation();

                    if (
                        host.getAttribute(
                            "data-qcc-auto-twin-open"
                        ) === "1"
                    ) {
                        close();

                    } else {
                        open();
                    }
                },
                true
            );
        }


        capturedOptions.forEach(
            optionNode => {
                const label =
                    normalize(
                        optionNode.textContent
                    );

                const match =
                    optionByLabel.get(
                        label
                    );

                if (!match) {
                    return;
                }

                optionNode.addEventListener(
                    "click",
                    event => {
                        event.preventDefault();
                        event.stopImmediatePropagation();

                        selectByIndex(
                            match.index
                        );
                    },
                    true
                );
            }
        );


        host.addEventListener(
            "click",
            event => {
                if (
                    event.composedPath().some(
                        element => (
                            element
                            && element.getAttribute
                            && (
                                element.getAttribute(
                                    "role"
                                ) === "option"

                                || element.getAttribute(
                                    "role"
                                ) === "combobox"
                            )
                        )
                    )
                ) {
                    return;
                }

                event.preventDefault();
                event.stopImmediatePropagation();

                if (
                    host.getAttribute(
                        "data-qcc-auto-twin-open"
                    ) === "1"
                ) {
                    close();

                } else {
                    open();
                }
            },
            true
        );


        reflectState();

        return binding;
    };


    for (
        const catalog
        of catalogs
    ) {
        const binding =
            bindCatalog(
                catalog
            );

        if (binding) {
            bindings.set(
                normalize(
                    catalog.selector
                ),
                binding
            );
        }
    }


    document.addEventListener(
        "click",
        event => {
            if (!openBinding) {
                return;
            }

            if (
                event.composedPath().includes(
                    openBinding.host
                )
            ) {
                return;
            }

            const popup =
                event.target
                && event.target.closest
                ? event.target.closest(
                    "[data-qcc-auto-twin-catalog-popup]"
                )
                : null;

            if (popup) {
                return;
            }

            openBinding.close();
        },
        false
    );


    window.addEventListener(
        "resize",
        () => {
            if (
                openBinding
                && openBinding.host
            ) {
                const selector =
                    openBinding.catalog.selector;

                const popup =
                    Array.from(
                        document.querySelectorAll(
                            "[data-qcc-auto-twin-catalog-popup]"
                        )
                    ).find(
                        node => (
                            node.getAttribute(
                                "data-qcc-auto-twin-catalog-selector"
                            )
                            === selector
                        )
                    );

                if (popup) {
                    const rect =
                        openBinding.host
                        .getBoundingClientRect();

                    popup.style.left =
                        `${Math.round(rect.left)}px`;

                    popup.style.top =
                        `${Math.round(rect.bottom + 2)}px`;
                }
            }
        }
    );


    runtime.ready =
        true;

    document.dispatchEvent(
        new CustomEvent(
            "qcc-auto-twin-catalog-runtime-ready",
            {
                detail: {
                    version:
                        VERSION,

                    binding_count:
                        bindings.size,
                },
            }
        )
    );
})();
""".strip()


def catalog_runtime_adapter_source():
    return (
        CATALOG_RUNTIME_ADAPTER_JS
        + "\n"
    )


def _safe_json_for_script(
    payload,
):
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    )

    return (
        serialized
        .replace(
            "<",
            "\\u003c",
        )
        .replace(
            ">",
            "\\u003e",
        )
        .replace(
            "&",
            "\\u0026",
        )
    )


def inject_catalog_runtime_adapter(
    source_html,
    catalog_runtime_payload,
):
    if not isinstance(
        source_html,
        str,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_CATALOG_RUNTIME_HTML_INVALID"
        )

    if not isinstance(
        catalog_runtime_payload,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_CATALOG_RUNTIME_PAYLOAD_INVALID"
        )

    catalogs = (
        catalog_runtime_payload.get(
            "catalogs"
        )
        or []
    )

    if not isinstance(
        catalogs,
        list,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_RUNTIME_CATALOGS_INVALID"
        )

    if not catalogs:
        return source_html

    if (
        AUTO_TWIN_CATALOG_RUNTIME_SCRIPT_MARKER
        in source_html
    ):
        return source_html

    payload = (
        _safe_json_for_script(
            catalog_runtime_payload
        )
    )

    block = (
        "\n"
        '<script type="application/json" id="'
        + AUTO_TWIN_CATALOG_RUNTIME_PAYLOAD_ELEMENT_ID
        + '">'
        + payload
        + "</script>\n"
        + "<script "
        + AUTO_TWIN_CATALOG_RUNTIME_SCRIPT_MARKER
        + '="'
        + str(
            AUTO_TWIN_CATALOG_RUNTIME_ADAPTER_VERSION
        )
        + '">\n'
        + CATALOG_RUNTIME_ADAPTER_JS
        + "\n</script>\n"
    )

    lowered = (
        source_html.lower()
    )

    body_close = (
        lowered.rfind(
            "</body>"
        )
    )

    if body_close >= 0:
        return (
            source_html[
                :body_close
            ]
            + block
            + source_html[
                body_close:
            ]
        )

    html_close = (
        lowered.rfind(
            "</html>"
        )
    )

    if html_close >= 0:
        return (
            source_html[
                :html_close
            ]
            + block
            + source_html[
                html_close:
            ]
        )

    return (
        source_html
        + block
    )
