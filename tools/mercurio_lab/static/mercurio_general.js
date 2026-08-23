(function () {
    "use strict";

    function byId(id) {
        return document.getElementById(id);
    }

    function setState(state) {
        document.body.dataset.mercurioState = state;
    }

    function showNotice(message) {
        var notice = byId("twinEntryNotice");

        if (!notice) {
            return;
        }

        notice.textContent = message;
        notice.hidden = false;
    }

    window.entrar = function entrar(mode) {
        if (mode === "C") {
            showNotice(
                "Consulta de solicitud existente todavía no modelada en el Twin."
            );
        }
    };

    window.mostrarOpcion = function mostrarOpcion() {
        var options = byId("twinEntryOptions");

        if (!options) {
            return;
        }

        options.hidden = false;

        setState(
            "MERCURIO_ENTRY_OPTIONS"
        );
    };

    window.ocultaError = function () {
        const notice =
            byId("twinEntryNotice");

        if (notice) {
            notice.hidden = true;
        }
    };


    window.continuar = function (requestType) {
        const selected =
            document.querySelector(
                'input[name="datosForL"]:checked'
            );

        if (!selected) {
            showNotice(
                "Seleccione una solicitud."
            );
            return;
        }

        document.body.dataset.selectedModel =
            selected.value;

        document.body.dataset.requestType =
            String(requestType || "");

        if (selected.value === "EX01") {
            window.location.assign(
                "/mercurio/nuevaSolicitud-EX01.html"
            );
            return;
        }

        showNotice(
            "Modelo "
            + selected.value
            + " preparado en Mercurio Twin."
        );
    };


    window.cerrarOpcion = function () {
        const options =
            byId("twinEntryOptions");

        if (options) {
            options.hidden = true;
        }

        setState(
            "MERCURIO_ENTRY_IDLE"
        );
    };


    window.irOpcion = function irOpcion() {
        var selected = document.querySelector(
            'input[name="opcion"]:checked'
        );

        var province = byId("provincia");

        if (!selected) {
            showNotice(
                "Seleccione una opción."
            );
            return;
        }

        if (
            !province
            || !province.value
        ) {
            showNotice(
                "Seleccione provincia."
            );
            return;
        }

        if (selected.value !== "BI") {
            showNotice(
                "Destino todavía no modelado para "
                + selected.value
                + "."
            );
            return;
        }

        byId("tipoSolicitud").value = "INI";
        byId("codProvincia").value = province.value;

        byId("twinEntryOptions").hidden = true;

        setState(
            "MERCURIO_ENTRY_SELECTION_COMMITTED"
        );

        window.setTimeout(
            function () {
                window.location.assign(
                    "/mercurio/seleccionModelo-"
                    + province.value
                    + ".html"
                );
            },
            500
        );
    };
})();
