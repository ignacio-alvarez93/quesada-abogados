(function () {
    "use strict";

    const PANELS = [
        "tab-datos_autorizacion",
        "tab-datos_personales",
        "tab-datos_familiar",
        "tab-datos_presentador",
        "tab-datos_notificacion",
    ];

    function byId(id) {
        return document.getElementById(id);
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

        if (
            selected.id ===
            "EX-01-2-01"
        ) {
            byId(
                "viaAccesoNew"
            ).value = "MER";

            byId(
                "tipoPermisoNew"
            ).value = "NLR";

            byId(
                "muestraFamiliar"
            ).value = "N";
        }

        return true;
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
                activate(
                    "tab-datos_presentador",
                    "EX01_PRESENTER"
                );

                return false;
            }

            if (step === "familiar") {
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

    activate(
        "tab-datos_autorizacion",
        "EX01_AUTHORIZATION"
    );
})();
