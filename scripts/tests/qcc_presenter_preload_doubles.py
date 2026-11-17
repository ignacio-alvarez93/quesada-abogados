"""Certificate-held presenter double (QCC_EX01_R6_POSTFORM).

Extracted from the historical ``test_qcc_presenter_preload_proof``
helpers (read-only reference ``data/qcc_ex01_r2_reference``) so the
restored post-form EX01 suites share them without collecting that suite.

REAL evidence: Mercurio renders the certificate-managed presenter
identity as ``readonly="readonly"`` (``preTipodocumentoPresentador``:
``readonly`` + ``pointer-events: none``). Offline, fictitious values only.
"""

from qcc_full_mapper_doubles import (
    DOMICILIO,
    EXTRANJERO,
    NOTIFICACION,
    _TabbedMercurioBrowser,
    _datos,
)


NAME, DOC_TYPE, DOC = "preNombrePresentador", "preTipodocumentoPresentador", "preNiePresentador"
VIA, ADDRESS, EMAIL = "preTipoViaPresentador", "preDomicilioPresentador", "preEmailPresentador"
PRE_PROVINCE, PRE_TOWN, PRE_LOCALITY = (
    "preCodigoProvinciaPresentador", "preCodigoMunicipioPresentador", "preCodigoLocalidadPresentador",
)
IDENTITY = {NAME: "LETRADO EJEMPLO", DOC_TYPE: "NIE", DOC: "X0000000T"}
DOMICILE = {VIA: "CL", VIA + "_text": "CALLE", ADDRESS: "URIA", EMAIL: "p@example.invalid"}
REPRESENTANTE = {**IDENTITY, **DOMICILE}
PRE_CASCADE = [PRE_PROVINCE, PRE_TOWN, PRE_LOCALITY]
FIELDS = (list(EXTRANJERO) + list(DOMICILIO) + list(NOTIFICACION)
          + [NAME, DOC_TYPE, DOC, VIA, ADDRESS, EMAIL])
SELECTS = [DOC_TYPE, VIA]


def _presenter_datos(**extra):
    datos = _datos("MERCURIO_EX01")
    datos["representante"] = {**REPRESENTANTE, **extra}
    return datos


def _browser(*, readonly=(), pointer_none=(), certificate=None, fields=FIELDS, selects=SELECTS, **kwargs):
    """Mercurio double whose ``readonly`` / ``pointer_none`` controls are
    reported by the live local probe exactly as the real page does, and
    whose ``certificate`` values were set by Mercurio itself."""

    browser = _TabbedMercurioBrowser(fields=fields, selects=selects, **kwargs)
    browser.readonly = set(readonly)
    browser.pointer_none = set(pointer_none)
    probe = browser.form.local_probe

    def local_probe(field_id):
        result = probe(field_id)
        if result.get("exists"):
            signals = result["interaction_signals"]
            signals["readonly"] = field_id in browser.readonly
            if field_id in browser.pointer_none:
                signals["pointer_events"] = "none"
        return result

    browser.form.local_probe = local_probe
    for field_id, value in (certificate or {}).items():
        browser.form.values[field_id] = value
        if field_id in selects:
            browser.form.selects.add(field_id)
    return browser


def _certificate_browser(**kwargs):
    return _browser(readonly={NAME, DOC}, pointer_none={DOC_TYPE}, certificate=IDENTITY, **kwargs)
