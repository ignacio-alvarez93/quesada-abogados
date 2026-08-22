(function () {
    "use strict";

    const LAB_VERSION = "1.0";

    const state = {
        sequence: 0,
        selectedFile: null
    };


    function byId(id) {
        return document.getElementById(id);
    }


    function text(value) {
        return String(value || "").trim();
    }


    function setStatus(message, detail) {
        const status = byId("labStatus");

        if (!status) {
            return;
        }

        const payload = {
            message: String(message || ""),
            detail: detail || null
        };

        status.textContent =
            JSON.stringify(
                payload,
                null,
                2
            );
    }


    function removeErrors() {
        document
            .querySelectorAll(
                "#tbAdjuntos .dvReError"
            )
            .forEach(function (item) {
                item.remove();
            });

        document
            .querySelectorAll(
                "#tbAdjuntos .lblObligaCl"
            )
            .forEach(function (item) {
                item.classList.remove(
                    "lblObligaCl"
                );
            });
    }


    function markRequired(element) {
        if (!element) {
            return;
        }

        element.classList.add(
            "lblObligaCl"
        );

        const error =
            document.createElement(
                "div"
            );

        error.className =
            (
                "dvReError "
                + "dvReErrorL "
                + "dvReObli"
            );

        element
            .parentElement
            .appendChild(
                error
            );
    }


    function uploadedCodes() {
        return Array
            .from(
                document.querySelectorAll(
                    "#tabla_datos_adj tbody tr"
                )
            )
            .map(function (row) {
                const cells =
                    Array.from(
                        row.cells || []
                    );

                return (
                    cells.length > 4
                        ? text(
                            cells[4]
                                .textContent
                        )
                        : ""
                );
            })
            .filter(Boolean);
    }


    function requiredCodes() {
        return text(
            byId(
                "listaIdsDocOb"
            ).value
        )
            .split("|")
            .map(text)
            .filter(Boolean);
    }


    function selectedDescription() {
        const select =
            byId(
                "docAdjuntarAdjuntos"
            );

        const code =
            text(
                select.value
            );

        if (code === "999") {
            return text(
                byId(
                    "desDocumentoAdjuntos"
                ).value
            );
        }

        const option =
            select.options[
                select.selectedIndex
            ];

        return (
            option
                ? text(
                    option.textContent
                )
                : ""
        );
    }


    function codeAlreadyAttached(code) {
        if (
            code === "999"
            || code === "10"
        ) {
            return false;
        }

        return uploadedCodes()
            .includes(
                code
            );
    }


    async function sha256File(file) {
        try {
            if (
                window.crypto
                && window.crypto.subtle
            ) {
                const buffer =
                    await file.arrayBuffer();

                const digest =
                    await window.crypto.subtle.digest(
                        "SHA-256",
                        buffer
                    );

                return Array
                    .from(
                        new Uint8Array(
                            digest
                        )
                    )
                    .map(function (value) {
                        return value
                            .toString(16)
                            .padStart(2, "0");
                    })
                    .join("")
                    .toUpperCase();
            }
        } catch (error) {
            // Fallback below.
        }

        return (
            "LAB-"
            + String(file.size)
            + "-"
            + String(
                file.lastModified || 0
            )
        );
    }


    function resetAttachForm() {
        byId(
            "fileDocumentoAdjuntos"
        ).value = "";

        byId(
            "docAdjuntarAdjuntos"
        ).value = "";

        byId(
            "desDocumentoAdjuntos"
        ).value = "";

        byId(
            "labPluploadInput"
        ).value = "";

        state.selectedFile = null;

        setDocAdjuntarAdjuntos();

        removeErrors();
    }


    function createDeleteCell(row) {
        const cell =
            row.insertCell();

        const link =
            document.createElement(
                "a"
            );

        link.href = "#";
        link.textContent = "Eliminar";

        link.addEventListener(
            "click",
            function (event) {
                event.preventDefault();
                row.remove();

                setStatus(
                    "ROW_DELETED"
                );
            }
        );

        cell.appendChild(
            link
        );
    }


    function appendUploadedRow(
        *,
        filename,
        description,
        hash,
        code
    ) {
        state.sequence += 1;

        const tbody =
            document.querySelector(
                "#tabla_datos_adj tbody"
            );

        const row =
            tbody.insertRow();

        row.id =
            (
                "filaAdjunto_"
                + Date.now()
                + "_"
                + state.sequence
            );

        createDeleteCell(
            row
        );

        row.insertCell()
            .textContent =
                filename;

        row.insertCell()
            .textContent =
                description;

        row.insertCell()
            .textContent =
                hash;

        row.insertCell()
            .textContent =
                code;

        return row;
    }


    async function attachCurrentFile() {
        removeErrors();

        const fileNameField =
            byId(
                "fileDocumentoAdjuntos"
            );

        const select =
            byId(
                "docAdjuntarAdjuntos"
            );

        const other =
            byId(
                "desDocumentoAdjuntos"
            );

        const filename =
            text(
                fileNameField.value
            );

        const code =
            text(
                select.value
            );

        const otherText =
            text(
                other.value
            );

        if (
            codeAlreadyAttached(
                code
            )
        ) {
            setStatus(
                "DOCUMENT_ALREADY_ATTACHED",
                {
                    code: code
                }
            );

            return;
        }

        if (
            !filename
            || !state.selectedFile
        ) {
            markRequired(
                fileNameField
            );
        }

        if (!code) {
            markRequired(
                select
            );
        }

        if (
            code === "999"
            && !otherText
        ) {
            markRequired(
                other
            );
        }

        if (
            document.querySelector(
                "#tbAdjuntos .dvReError"
            )
        ) {
            setStatus(
                "VALIDATION_ERROR"
            );

            return;
        }

        const description =
            selectedDescription();

        const hash =
            await sha256File(
                state.selectedFile
            );

        appendUploadedRow(
            {
                filename:
                    filename,

                description:
                    description,

                hash:
                    hash,

                code:
                    code
            }
        );

        setStatus(
            "FILE_UPLOADED",
            {
                filename:
                    filename,

                description:
                    description,

                hash:
                    hash,

                code:
                    code
            }
        );

        /*
         * Mercurio real reemplaza
         * #cont_tabla_datos_adj con la respuesta
         * del upload y después limpia:
         *
         * #tbAdjuntos input,#tbAdjuntos select
         *
         * Aquí conservamos la misma semántica
         * observable para el automation contract.
         */
        resetAttachForm();
    }


    function fileAdded(event) {
        const input =
            event.currentTarget;

        const files =
            Array.from(
                input.files || []
            );

        if (!files.length) {
            state.selectedFile = null;

            byId(
                "fileDocumentoAdjuntos"
            ).value = "";

            return;
        }

        /*
         * Mercurio:
         * multi_selection=false
         * y conserva un único fichero.
         */
        state.selectedFile =
            files[
                files.length - 1
            ];

        byId(
            "fileDocumentoAdjuntos"
        ).value =
            state.selectedFile.name;

        setStatus(
            "FILE_SELECTED",
            {
                filename:
                    state.selectedFile.name,

                size:
                    state.selectedFile.size,

                type:
                    state.selectedFile.type
            }
        );
    }


    function seedRow(
        filename,
        description,
        hash,
        code
    ) {
        appendUploadedRow(
            {
                filename:
                    filename,
                description:
                    description,
                hash:
                    hash,
                code:
                    code
            }
        );
    }


    function applyFixture() {
        const params =
            new URLSearchParams(
                window.location.search
            );

        const fixture =
            text(
                params.get(
                    "fixture"
                )
            ).toLowerCase();

        if (
            !fixture
            || fixture === "empty"
        ) {
            return;
        }

        if (
            fixture === "partial"
        ) {
            seedRow(
                "01_pasaporte_lab.pdf",
                (
                    "Pasaporte, título de viaje "
                    + "o cédula de inscripción "
                    + "completos, válidos y en vigor "
                    + "de la persona extranjera."
                ),
                "LABHASH-PASSPORT",
                "1"
            );

            return;
        }

        if (
            fixture === "complete"
        ) {
            seedRow(
                "01_pasaporte_lab.pdf",
                (
                    "Pasaporte, título de viaje "
                    + "o cédula de inscripción "
                    + "completos, válidos y en vigor "
                    + "de la persona extranjera."
                ),
                "LABHASH-PASSPORT",
                "1"
            );

            seedRow(
                "02_recursos_lab.pdf",
                "Recursos económicos",
                "LABHASH-RESOURCES",
                "39"
            );

            seedRow(
                "03_seguro_lab.pdf",
                (
                    "Documentación acreditativa "
                    + "de seguro de enfermedad"
                ),
                "LABHASH-INSURANCE",
                "47"
            );

            seedRow(
                "04_tasa_052_lab.pdf",
                "Tasa (mod. 790 cód. 052)",
                "LABHASH-TAX",
                "51"
            );

            return;
        }
    }


    window.setDocAdjuntarAdjuntos =
        function () {
            const code =
                text(
                    byId(
                        "docAdjuntarAdjuntos"
                    ).value
                );

            byId(
                "otrosDocumentoContainer"
            )
                .classList
                .toggle(
                    "hidden",
                    code !== "999"
                );
        };


    window.continuarPre =
        function () {
            const uploaded =
                new Set(
                    uploadedCodes()
                );

            const missing =
                requiredCodes()
                    .filter(function (code) {
                        return !uploaded.has(
                            code
                        );
                    });

            if (missing.length) {
                setStatus(
                    "REQUIRED_DOCUMENTS_MISSING",
                    {
                        required:
                            requiredCodes(),

                        uploaded:
                            Array.from(
                                uploaded
                            ),

                        missing:
                            missing
                    }
                );

                return false;
            }

            /*
             * LAB SAFETY BOUNDARY:
             * Mercurio real enviaría #FrmDatos.
             * El laboratorio nunca hace POST.
             */
            setStatus(
                "DOCUMENTATION_COMPLETE",
                {
                    required:
                        requiredCodes(),

                    uploaded:
                        Array.from(
                            uploaded
                        ),

                    submitted:
                        false
                }
            );

            return false;
        };


    window.__MERCURIO_LAB__ = {
        version:
            LAB_VERSION,

        requiredCodes:
            requiredCodes,

        uploadedCodes:
            uploadedCodes,

        seedRow:
            seedRow,

        reset:
            function () {
                document
                    .querySelector(
                        "#tabla_datos_adj tbody"
                    )
                    .replaceChildren();

                resetAttachForm();

                setStatus(
                    "RESET"
                );
            }
    };


    document.addEventListener(
        "DOMContentLoaded",
        function () {
            const fileInput =
                byId(
                    "labPluploadInput"
                );

            /*
             * El browse_button real de Plupload
             * es #addDou.
             */
            byId(
                "addDou"
            )
                .addEventListener(
                    "click",
                    function () {
                        fileInput.click();
                    }
                );

            fileInput.addEventListener(
                "change",
                fileAdded
            );

            byId(
                "btnOpeAdjuntar"
            )
                .addEventListener(
                    "click",
                    function () {
                        attachCurrentFile()
                            .catch(
                                function (error) {
                                    setStatus(
                                        "UPLOAD_ERROR",
                                        {
                                            error:
                                                String(
                                                    error
                                                )
                                        }
                                    );
                                }
                            );
                    }
                );

            setDocAdjuntarAdjuntos();

            applyFixture();

            setStatus(
                "READY",
                {
                    version:
                        LAB_VERSION,

                    required:
                        requiredCodes(),

                    uploaded:
                        uploadedCodes()
                }
            );
        }
    );
})();
