"""
Lectura estructural del estado documental de Mercurio.

Responsabilidad:
- observar el DOM actual;
- producir un snapshot normalizado;
- delegar la interpretación funcional en
  ``mercurio_document_state``.

No:
- hace clicks;
- modifica campos;
- dispara eventos;
- adjunta archivos;
- avanza Mercurio;
- conoce QCC;
- conoce SQLite/Supabase.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.automation.mercurio_document_state import (
    MercurioDocumentState,
    build_mercurio_document_state,
)


class MercurioDocumentDomReadError(
    RuntimeError
):
    """Error controlado leyendo el DOM documental."""


MERCURIO_DOCUMENT_SNAPSHOT_EXPRESSION = r"""
(function () {
    function cleanText(value) {
        return String(value || "")
            .replace(/\s+/g, " ")
            .trim();
    }

    const requiredCodesField =
        document.querySelector(
            "#listaIdsDocOb"
        );

    const documentTypeSelect =
        document.querySelector(
            "#docAdjuntarAdjuntos"
        );

    const uploadedTable =
        document.querySelector(
            "#tabla_datos_adj"
        );

    const fileInput =
        document.querySelector(
            "#tbAdjuntos input[type='file']"
        );

    const continueButton =
        document.querySelector(
            "#continuaNot"
        );

    const requiredItems =
        Array.from(
            document.querySelectorAll(
                ".listaObligatoria [iddocob]"
            )
        ).map(function (item) {
            return {
                code:
                    cleanText(
                        item.getAttribute(
                            "iddocob"
                        )
                        || item.id
                    ),

                label:
                    cleanText(
                        item.textContent
                    )
            };
        });

    const uploadedRows =
        Array.from(
            document.querySelectorAll(
                "#tabla_datos_adj tbody tr"
            )
        ).map(function (row) {
            const cells =
                Array.from(
                    row.cells
                    || []
                );

            return {
                row_id:
                    cleanText(
                        row.id
                    ),

                filename:
                    cells.length > 1
                        ? cleanText(
                            cells[1].textContent
                        )
                        : "",

                description:
                    cells.length > 2
                        ? cleanText(
                            cells[2].textContent
                        )
                        : "",

                hash:
                    cells.length > 3
                        ? cleanText(
                            cells[3].textContent
                        )
                        : "",

                code:
                    cells.length > 4
                        ? cleanText(
                            cells[4].textContent
                        )
                        : ""
            };
        });

    return {
        url:
            String(
                window.location.href
                || ""
            ),

        markers: {
            required_codes_field:
                Boolean(
                    requiredCodesField
                ),

            document_type_select:
                Boolean(
                    documentTypeSelect
                ),

            uploaded_table:
                Boolean(
                    uploadedTable
                ),

            file_input:
                Boolean(
                    fileInput
                ),

            continue_button:
                Boolean(
                    continueButton
                )
        },

        required_codes_raw:
            requiredCodesField
                ? String(
                    requiredCodesField.value
                    || ""
                )
                : "",

        required_items:
            requiredItems,

        uploaded_rows:
            uploadedRows
    };
})()
"""


def _evaluate_read_only(
    browser,
    expression: str,
):
    """
    Evalúa una expresión JS sin alterar el navegador.

    Compatibilidad:
    - SeleniumBase CDP/sb_cdp: ``evaluate``.
    - Selenium/WebDriver: ``execute_script``.
    """

    evaluate = getattr(
        browser,
        "evaluate",
        None,
    )

    if callable(
        evaluate
    ):
        return evaluate(
            expression
        )

    execute_script = getattr(
        browser,
        "execute_script",
        None,
    )

    if callable(
        execute_script
    ):
        return execute_script(
            "return "
            + expression
        )

    raise MercurioDocumentDomReadError(
        "MERCURIO_DOCUMENT_DOM_EVALUATION_UNSUPPORTED"
    )


def read_mercurio_document_snapshot(
    browser,
) -> dict[str, Any]:
    """
    Obtiene el snapshot documental actual.

    El JavaScript asociado es estrictamente observacional.
    """

    payload = _evaluate_read_only(
        browser,
        MERCURIO_DOCUMENT_SNAPSHOT_EXPRESSION,
    )

    if not isinstance(
        payload,
        Mapping,
    ):
        raise MercurioDocumentDomReadError(
            "MERCURIO_DOCUMENT_DOM_INVALID_PAYLOAD"
        )

    return dict(
        payload
    )


def read_mercurio_document_state(
    browser,
) -> MercurioDocumentState:
    """
    Lee DOM + construye el modelo funcional D1.
    """

    snapshot = (
        read_mercurio_document_snapshot(
            browser
        )
    )

    return (
        build_mercurio_document_state(
            snapshot
        )
    )
