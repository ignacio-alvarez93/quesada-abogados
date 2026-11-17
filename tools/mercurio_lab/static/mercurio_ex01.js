(function () {
    "use strict";

    const PANELS = [
        "tab-datos_autorizacion",
        "tab-datos_personales",
        "tab-datos_familiar",
        "tab-datos_presentador",
        "tab-datos_notificacion",
    ];

    const TAB_ORDER = [
        {
            panelId: "tab-datos_autorizacion",
            anchorId: "d-li-autorizacionSup",
        },
        {
            panelId: "tab-datos_personales",
            anchorId: "d-li-personales",
        },
        {
            panelId: "tab-datos_familiar",
            anchorId: "d-li-familiar",
        },
        {
            panelId: "tab-datos_presentador",
            anchorId: "d-li-presentador",
        },
        {
            panelId: "tab-datos_notificacion",
            anchorId: "d-li-notificacion",
        },
    ];


    function byId(id) {
        return document.getElementById(id);
    }

    function updateTabStates(panelId) {
        const activeIndex =
            TAB_ORDER.findIndex(
                function (entry) {
                    return (
                        entry.panelId
                        === panelId
                    );
                }
            );

        if (activeIndex < 0) {
            return;
        }

        TAB_ORDER.forEach(
            function (entry, index) {
                const anchor =
                    byId(entry.anchorId);

                if (!anchor) {
                    return;
                }

                const tab =
                    anchor.closest("li");

                if (!tab) {
                    return;
                }

                tab.classList.remove(
                    "r-tabs-state-active",
                    "r-tabs-state-default",
                    "r-tabs-state-disabled"
                );

                if (index < activeIndex) {
                    tab.classList.add(
                        "r-tabs-state-default"
                    );

                    return;
                }

                if (index === activeIndex) {
                    tab.classList.add(
                        "r-tabs-state-active"
                    );

                    return;
                }

                tab.classList.add(
                    "r-tabs-state-disabled"
                );
            }
        );
    }


    function activate(panelId, state) {
        PANELS.forEach(function (id) {
            const panel = byId(id);

            if (!panel) {
                return;
            }

            panel.classList.remove(
                "r-tabs-state-active"
            );

            panel.classList.add(
                "r-tabs-state-default"
            );

            panel.style.display = "none";
        });

        const selected = byId(panelId);

        if (selected) {
            selected.classList.remove(
                "r-tabs-state-default"
            );

            selected.classList.add(
                "r-tabs-state-active"
            );

            selected.style.display = "block";
        }

        updateTabStates(panelId);

        document.body.dataset.ex01State =
            state;
    }

    function applyAuthorization() {
        const selected =
            document.querySelector(
                'input[name="datosForAut"]:checked'
            );

        if (!selected) {
            return false;
        }

        byId(
            "idOpcionAutorizacion"
        ).value = selected.value;

        byId(
            "codOpcionAutorizacion"
        ).value = selected.id;

        byId(
            "supuestoSeleccionadoSup"
        ).value = selected.id;

        // 130 Renovación Titular / 131 Renovación Familiar: only 131
        // exposes "Datos del familiar" (pestFamiliar).
        const familiar =
            selected.id ===
            "EX-01-2-02";

        if (
            selected.id ===
            "EX-01-2-01"
            || familiar
        ) {
            byId(
                "viaAccesoNew"
            ).value = "MER";

            byId(
                "tipoPermisoNew"
            ).value = "NLR";
        }

        byId(
            "muestraFamiliar"
        ).value = familiar ? "S" : "N";

        const familiarTab =
            byId("pestFamiliar");

        if (familiarTab) {
            familiarTab.style.display =
                familiar ? "" : "none";
        }

        return true;
    }

    function showsFamiliar() {
        const flag =
            byId("muestraFamiliar");

        return (
            !!flag
            && flag.value === "S"
        );
    }

    window.controlCheckExcludes =
        function controlCheckExcludes() {
            return true;
        };

    window.continuarTab =
        function continuarTab(step) {
            if (
                step ===
                "autorizacionSup"
            ) {
                if (!applyAuthorization()) {
                    return false;
                }

                activate(
                    "tab-datos_personales",
                    "EX01_PERSONAL"
                );

                return false;
            }

            if (step === "personales") {
                if (showsFamiliar()) {
                    activate(
                        "tab-datos_familiar",
                        "EX01_FAMILIAR"
                    );

                    return false;
                }

                activate(
                    "tab-datos_presentador",
                    "EX01_PRESENTER"
                );

                return false;
            }

            if (step === "familiar") {
                if (!showsFamiliar()) {
                    return false;
                }

                activate(
                    "tab-datos_presentador",
                    "EX01_PRESENTER"
                );

                return false;
            }

            if (step === "presentador") {
                const colectivo =
                    byId(
                        "colectivoDestinatario"
                    );

                if (colectivo) {
                    colectivo.value = "AB";
                }

                activate(
                    "tab-datos_notificacion",
                    "EX01_NOTIFICATION"
                );

                return false;
            }

            return false;
        };

    window.enviaDatosSup =
        function enviaDatosSup() {
            window.location.assign(
                "/mercurio/" +
                "presentacionTelematicaDocumentacion.html"
            );
        };

    function readMercurioCatalogs() {
        const node =
            byId("mercurioTwinCatalogs");

        if (!node) {
            return {};
        }

        try {
            return JSON.parse(
                node.textContent || "{}"
            );
        } catch (_) {
            return {};
        }
    }


    const MERCURIO_CATALOGS =
        readMercurioCatalogs();


    function fallbackOption() {
        return {
            value: "",
            label: "--",
        };
    }


    function replaceOptions(
        select,
        rows
    ) {
        if (!select) {
            return;
        }

        const normalized =
            (
                Array.isArray(rows)
                && rows.length
            )
                ? rows
                : [fallbackOption()];

        select.replaceChildren();

        normalized.forEach(
            function (row) {
                const option =
                    document.createElement(
                        "option"
                    );

                option.value =
                    String(
                        row.value || ""
                    );

                option.textContent =
                    String(
                        row.label || ""
                    );

                select.appendChild(
                    option
                );
            }
        );

        select.value = "";
    }


    const CASCADES = [
        {
            province: "extCodigoProvincia",
            municipality: "extCodigoMunicipio",
            locality: "extCodigoLocalidad",
        },
        {
            province: "reaCodigoProvinciaReagrupante",
            municipality: "reaCodigoMunicipioReagrupante",
            locality: "reaCodigoLocalidadReagrupante",
        },
    ];


    function syncLocalities(cascade) {
        const province =
            byId(cascade.province);

        const municipality =
            byId(cascade.municipality);

        const locality =
            byId(cascade.locality);

        if (
            !province
            || !municipality
            || !locality
        ) {
            return;
        }

        const key =
            province.value
            + ":"
            + municipality.value;

        const rows =
            (
                MERCURIO_CATALOGS
                    .localities
                || {}
            )[key];

        replaceOptions(
            locality,
            rows
        );
    }


    function syncMunicipalities(cascade) {
        const province =
            byId(cascade.province);

        const municipality =
            byId(cascade.municipality);

        const locality =
            byId(cascade.locality);

        if (
            !province
            || !municipality
        ) {
            return;
        }

        const rows =
            (
                MERCURIO_CATALOGS
                    .municipalities
                || {}
            )[province.value];

        replaceOptions(
            municipality,
            rows
        );

        replaceOptions(
            locality,
            null
        );
    }


    function initializeMercurioCatalogs(cascade) {
        const province =
            byId(cascade.province);

        const municipality =
            byId(cascade.municipality);

        const configuredProvince =
            byId("provincia");

        if (
            province
            && configuredProvince
            && configuredProvince.value
        ) {
            province.value =
                configuredProvince.value;
        }

        if (province) {
            province.addEventListener(
                "change",
                function () {
                    syncMunicipalities(cascade);
                }
            );
        }

        if (municipality) {
            municipality.addEventListener(
                "change",
                function () {
                    syncLocalities(cascade);
                }
            );
        }

        syncMunicipalities(cascade);
    }


    CASCADES.forEach(
        initializeMercurioCatalogs
    );

    activate(
        "tab-datos_autorizacion",
        "EX01_AUTHORIZATION"
    );
})();
