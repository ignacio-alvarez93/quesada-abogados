(function () {
    "use strict";

    const LAB_VERSION = "1.0";

    const state = {
        sequence: 0,
        uploader: null
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
        {
            filename,
            description,
            hash,
            code
        }
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
            || !state.uploader
            || !state.uploader.files
            || !state.uploader.files.length
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

        state.uploader.settings.multipart_params.id_tipo_documento =
            code;

        state.uploader.settings.multipart_params.de_documento =
            description;

        state.uploader.settings.multipart_params.texto_otros =
            otherText;

        setStatus(
            "UPLOAD_STARTING",
            {
                filename: filename,
                description: description,
                code: code
            }
        );

        state.uploader.start();
    }


    function initializeUploader() {
        if (!window.plupload) {
            throw new Error("MERCURIO_LAB_PLUPLOAD_MISSING");
        }

        const uploader = new window.plupload.Uploader({
            runtimes: "html5,html4",
            browse_button: "addDou",
            url: "uploadDocumento",
            multi_selection: false,
            maxNumberOfFiles: 6,
            filters: {
                max_file_size: "6mb",
                mime_types: [
                    {
                        title: "Image files",
                        extensions: "jpg,jpeg,gif,png,bmp,tif,tiff,JPG,JPEG,GIF,PNG,BMP,TIF,TIFF"
                    },
                    {
                        title: "PDF files",
                        extensions: "pdf"
                    }
                ]
            },
            init: {
                PostInit: function () {
                    byId("btnOpeAdjuntar").onclick = function () {
                        attachCurrentFile().catch(function (error) {
                            setStatus("UPLOAD_ERROR", {
                                error: String(error)
                            });
                        });
                    };
                },

                FilesAdded: function (up, files) {
                    while (up.files.length > 1) {
                        up.removeFile(up.files[0]);
                    }

                    const file = files[files.length - 1];

                    byId("fileDocumentoAdjuntos").value =
                        file ? file.name : "";

                    setStatus("FILE_SELECTED", {
                        filename: file ? file.name : "",
                        size: file ? file.size : 0
                    });
                },

                FileUploaded: function (up, file, result) {
                    byId("cont_tabla_datos_adj").innerHTML =
                        String(result.response || "");

                    setStatus("FILE_UPLOADED", {
                        filename: file.name,
                        status: result.status
                    });

                    resetAttachForm();
                },

                UploadComplete: function (up, files) {
                    state.lastUploadComplete = true;
                },

                Error: function (up, error) {
                    setStatus("UPLOAD_ERROR", {
                        code: error.code,
                        message: error.message
                    });
                }
            }
        });

        state.uploader = uploader;
        uploader.init();
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
            try {
                initializeUploader();
            } catch (error) {
                setStatus("INIT_ERROR", {
                    error: String(
                        error && (error.stack || error.message) || error
                    )
                });

                return;
            }

            setDocAdjuntarAdjuntos();
            applyFixture();

            setStatus(
                "READY",
                {
                    version: LAB_VERSION,
                    required: requiredCodes(),
                    uploaded: uploadedCodes()
                }
            );
        }
    );

})();
