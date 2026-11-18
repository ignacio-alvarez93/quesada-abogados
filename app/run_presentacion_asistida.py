"""
Lanzador externo de Presentación Asistida Mercurio.

Versión ampliada:
- Rellena más campos de extranjero, domicilio y notificación.
- Selecciona países por texto real del desplegable, no por código fijo.
- Guarda log de campos no encontrados/vacíos.
"""

import argparse
import functools
import json
import re
import time
import unicodedata
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
    
from backend.automation.automation_artifacts import save_page_source
from backend.automation.automation_logger import write_log
from backend.automation.browser_actions import click_js, field_exists, js, wait_for_js
from backend.automation.browser_session import get_session_dir
from backend.automation.connectors.mercurio_connector import MercurioConnector
from backend.qcc.client.action_client import (
    QccActionClient,
)
from backend.qcc.client.presentation_reporter import (
    QccPresentationReporter,
)


def build_qcc_reporter(
    args,
    session_dir,
):
    """Construye QCC sin convertirlo en dependencia del runner.

    Si la identidad no está disponible o cualquier validación
    QCC falla, Mercurio continúa sin reporter.
    """

    try:
        session_id = str(
            getattr(
                args,
                "qcc_session_id",
                "",
            )
            or ""
        ).strip()

        expediente_id = int(
            getattr(
                args,
                "expediente_id",
                0,
            )
            or 0
        )

        client_id = int(
            getattr(
                args,
                "cliente_id",
                0,
            )
            or 0
        )

        if (
            not session_id
            or expediente_id <= 0
            or client_id <= 0
        ):
            write_log(
                session_dir,
                "QCC reporter deshabilitado: "
                "identidad incompleta",
            )
            return None

        procedure = str(
            getattr(
                args,
                "tipo",
                "",
            )
            or "MERCURIO"
        ).strip() or "MERCURIO"

        browser_profile_key = str(
            getattr(
                args,
                "browser_profile_key",
                "",
            )
            or ""
        ).strip()

        return QccPresentationReporter(
            session_id=session_id,
            expedient_id=expediente_id,
            client_id=client_id,
            procedure=procedure,
            provider="MERCURIO",
            runtime="SELENIUMBASE_ASSISTED",
            browser_profile_key=(
                browser_profile_key
                or None
            ),
            browser_session_mode=(
                "ASSISTED"
                if browser_profile_key
                else None
            ),
        )

    except Exception as exc:
        write_log(
            session_dir,
            "QCC reporter no disponible: "
            f"{type(exc).__name__}",
        )

        return None



def build_qcc_action_client(
    args,
    session_dir,
):
    """Construye el consumidor de acciones QCC.

    No conoce ni controla SeleniumBase.
    """

    session_id = str(
        getattr(
            args,
            "qcc_session_id",
            "",
        )
        or ""
    ).strip()

    if not session_id:
        write_log(
            session_dir,
            (
                "QCC action client deshabilitado: "
                "qcc_session_id ausente"
            ),
        )
        return None

    try:
        return QccActionClient(
            session_id=session_id,
        )

    except Exception as exc:
        write_log(
            session_dir,
            (
                "QCC action client no disponible: "
                f"{type(exc).__name__}"
            ),
        )

        return None



def qcc_report(
    reporter,
    method_name,
    session_dir,
    **kwargs,
):
    """Invocación QCC absolutamente fail-open."""

    if reporter is None:
        return False

    try:
        method = getattr(
            reporter,
            method_name,
        )

        return bool(
            method(
                **kwargs
            )
        )

    except Exception as exc:
        write_log(
            session_dir,
            "QCC publish omitido "
            f"{method_name}: "
            f"{type(exc).__name__}",
        )

        return False


def _extract_blocked_auto_detail(result):
    """Value-free description of a blocked ``run_auto`` early return.

    ``run_auto`` and its ``fill_datos_*`` helpers early-return a
    ``{"ok": False, ...}`` dict (sometimes wrapping the original
    ``fill_section`` result under ``detail``) the moment a governed
    write is denied/failed/requires a human. Returns ``None`` when
    ``result`` does not represent a blocked run (``None`` itself, or
    any mapping that is not an explicit ``ok=False``), so callers can
    tell "blocked" apart from "completed" without guessing from the
    absence of an exception.
    """

    if not isinstance(result, dict) or result.get("ok") is not False:
        return None

    detail = result.get("detail")

    if isinstance(detail, dict):
        blocked_field = detail.get("blocked_field")
        blocked_outcome = detail.get("blocked_outcome")
    else:
        blocked_field = result.get("blocked_field")
        blocked_outcome = result.get("blocked_outcome")

    return {
        "label": result.get("label"),
        "blocked_field": blocked_field,
        "blocked_outcome": blocked_outcome,
    }


def run_auto_with_qcc(
    browser,
    provincia_codigo,
    datos_mercurio,
    session_dir,
    reporter=None,
    action_client=None,
    abort_handler=None,
):
    """Envelope observacional sobre run_auto().

    No cambia ninguna interacción Mercurio.
    """

    qcc_report(
        reporter,
        "automating",
        session_dir,
        step="AUTO_FLOW",
        progress=5,
        message=(
            "Iniciando flujo asistido Mercurio"
        ),
    )

    try:
        result = run_auto(
            browser,
            provincia_codigo,
            datos_mercurio,
            session_dir,
            reporter=reporter,
            action_client=action_client,
            abort_handler=abort_handler,
        )

    except Exception as exc:
        qcc_report(
            reporter,
            "error",
            session_dir,
            step="AUTO_FLOW",
            message=(
                "Error durante presentación: "
                f"{type(exc).__name__}"
            ),
        )

        raise

    if _is_qcc_aborted_result(result):
        write_log(
            session_dir,
            "QCC auto flow ABORTADO por el operador",
        )

        return result

    blocked = _extract_blocked_auto_detail(result)

    if blocked is not None:
        write_log(
            session_dir,
            "QCC auto flow BLOQUEADO: rellenado detenido "
            f"label={blocked['label'] or '-'} "
            f"campo={blocked['blocked_field'] or '-'} "
            f"outcome={blocked['blocked_outcome'] or '-'}. "
            "Contexto de presentación conservado; "
            "pendiente de corrección/acción humana.",
        )

        qcc_report(
            reporter,
            "waiting_user",
            session_dir,
            step="AUTO_FLOW_BLOCKED",
            progress=50,
            message=(
                "Rellenado automático detenido: "
                "se requiere corrección o acción humana"
            ),
            event_details=blocked,
        )

        return result

    write_log(
        session_dir,
        (
            "QCC auto flow finalizado sin "
            "marcar COMPLETED: la fase "
            "documental continúa aparte"
        ),
    )

    return result


def normalize(value):
    value = "" if value is None else str(value)
    value = value.strip().upper()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"\s+", " ", value)
    return value


def limpiar_piso_runner(value):
    value = "" if value is None else str(value).strip()
    m = re.search(r"\d+", value)
    return m.group(0) if m else value


def resolve_tipo_via_text(value, text=""):
    if text:
        return text
    value = (value or "").strip().upper()
    return {
        "CL": "CALLE",
        "AV": "AVENIDA",
        "PZ": "PLAZA",
        "PS": "PASEO",
        "CM": "CAMINO",
        "CT": "CARRETERA",
        "RD": "RONDA",
        "TR": "TRAVESIA",
        "UR": "URBANIZACION",
        "ZZ": "DESCONOCIDO",
    }.get(value, text or value)


def set_value(browser, field_id, value, session_dir=None, trigger_change=True):
    if field_id in ("extPiso", "notPisoNotificacion"):
        value = limpiar_piso_runner(value)

    if value in (None, "", "None"):
        if session_dir:
            write_log(session_dir, f"VACIO: {field_id}")
        return GOVERNED_OUTCOME_SKIPPED

    def _apply():
        script = f"""
        (function(){{
            const el = document.getElementById({json.dumps(field_id)});
            if (!el) return false;
            el.value = {json.dumps(str(value))};
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            {"el.dispatchEvent(new Event('change', { bubbles: true }));" if trigger_change else ""}
            if (window.jQuery) window.jQuery(el).trigger('change');
            return true;
        }})();
        """
        js(browser, script)

    def _verify():
        return _verify_input_value(
            browser, field_id, str(value), session_dir=session_dir
        )

    result = _governed_write(
        browser,
        action_kind="INPUT_VALUE",
        field_id=field_id,
        apply=_apply,
        session_dir=session_dir,
        verify=_verify,
        already_satisfied=lambda: _input_value_satisfied(browser, field_id, str(value)),
    )

    return _governed_outcome(result)


def governed_set_value(
    browser,
    field_id,
    value,
    *,
    session_dir=None,
    environment=None,
):
    """Governed variant of ``set_value`` routed through the QCC V2
    state-aware execution engine (real live SeleniumBase integration).

    Opt-in only: no existing call site in this module invokes it, so
    default Mercurio behavior/certification is unchanged. It exists as
    the concrete, real integration point wiring the certified
    Execution Gate into the actual SeleniumBase runtime, reusing
    Mercurio's own already-certified site policy
    (``backend.automation.site_policies.mercurio``) and state
    recognizer (``backend.automation.site_recognizers.mercurio``).

    Returns the ``StateAwareExecutionResult``; the caller decides how
    to react to anything other than a governed, confirmed success.
    """

    from backend.automation.site_architecture.seleniumbase_executor import (
        build_seleniumbase_executor,
        build_seleniumbase_snapshot_provider,
        default_transient_error_classifier,
    )
    from backend.automation.site_architecture.site_target import (
        SiteEnvironment,
        SiteTarget,
        SiteTargetMode,
    )
    from backend.automation.site_architecture.state_aware_execution import (
        ActionIntent,
        StateAwareExecutionRequest,
        execute_state_aware_action,
    )
    from backend.automation.site_policies.mercurio import (
        MERCURIO_SITE_CODE,
        build_mercurio_interaction_policy,
        build_mercurio_profile,
    )
    from backend.automation.site_recognizers.default_registry import (
        build_default_site_state_recognizer_registry,
    )

    env = environment or SiteEnvironment.LAB
    profile = build_mercurio_profile(env)
    policy = build_mercurio_interaction_policy()

    target = SiteTarget(
        url=profile.allowed_origins[0] + "/mercurio/",
        mode=SiteTargetMode.MANAGED_EXECUTION,
        site_code=MERCURIO_SITE_CODE,
        environment=env,
    )

    registration = (
        build_default_site_state_recognizer_registry()
        .get_by_site_code(MERCURIO_SITE_CODE)
    )

    action_intent = ActionIntent(
        action_kind="INPUT_VALUE",
        action_selector=f"#{field_id}",
        idempotent=True,
        expects_state_transition=False,
        action_value=value,
    )

    request = StateAwareExecutionRequest(
        target=target,
        profile=profile,
        policy=policy,
        action_intent=action_intent,
        state_recognizer=(
            registration.recognizer
            if registration is not None
            else None
        ),
        provider="MERCURIO",
    )

    result = execute_state_aware_action(
        request,
        snapshot_provider=(
            build_seleniumbase_snapshot_provider(browser)
        ),
        executor=build_seleniumbase_executor(browser),
        transient_error_classifier=(
            default_transient_error_classifier
        ),
    )

    if session_dir:
        write_log(
            session_dir,
            "governed set_value "
            f"{field_id} -> {result.decision}/"
            f"{result.result_status}",
        )

    return result


GOVERNED_OUTCOME_OK = "OK"
GOVERNED_OUTCOME_SKIPPED = "SKIPPED"
GOVERNED_OUTCOME_DENIED = "DENIED"
GOVERNED_OUTCOME_FAILED = "FAILED"
GOVERNED_OUTCOME_HUMAN_HANDOFF = "HUMAN_HANDOFF"
# QCC_EX01_R6_POSTFORM: a canonical mapper field NOT written yet -- never
# SUCCESS, never fatal by itself. NOT_PRESENT: the control is absent from
# the live DOM. DEPENDENCY: it exists but its surface (r-tabs panel) is
# not the active one, or a dependency inside it is not settled. Nothing
# is ever written on a hidden surface: it is retried once that surface is
# reached by human navigation, else the VOLCAR fails closed.
GOVERNED_OUTCOME_DEFERRED_NOT_PRESENT = "DEFERRED_NOT_PRESENT"
GOVERNED_OUTCOME_DEFERRED_DEPENDENCY = "DEFERRED_DEPENDENCY"
# QCC_PRESENTER_PRELOAD_PROOF_V1: a control of a surface not reached yet
# that Mercurio holds write-blocked (readonly / pointer-events none) and
# whose live value does not prove the expected one.
GOVERNED_OUTCOME_DEFERRED_PRELOAD_UNPROVEN = "DEFERRED_PRELOAD_UNPROVEN"
_GOVERNED_DEFERRED_OUTCOMES = frozenset({
    GOVERNED_OUTCOME_DEFERRED_NOT_PRESENT,
    GOVERNED_OUTCOME_DEFERRED_DEPENDENCY,
    GOVERNED_OUTCOME_DEFERRED_PRELOAD_UNPROVEN,
})
# Nothing written: the live control already holds the expected value.
GOVERNED_ALREADY_SATISFIED_REASON = "ALREADY_SATISFIED"


# QCC_ASSISTED_REAL_SMOKE_V4: action kinds Mercurio's own interaction
# policy (``build_mercurio_interaction_policy``) always marks
# AUTOMATION_ALLOWED. For exactly these kinds, a governed write that
# comes back BLOCKED_POLICY/INTERACTION_POLICY_DENY can only be
# explained by the live element having resolved (it matched a real
# action in the fresh capture) but failed Action Safety's
# visible/disabled/interactable check at that exact snapshot moment --
# never by a missing/unmanaged site rule. That is the live-DOM-
# readiness race confirmed in the REAL smoke (a prior RADIO/SELECT
# dependency write whose Mercurio-side reveal/enable handler had not
# finished yet), not a genuine policy denial.
_DEPENDENCY_RETRY_ACTION_KINDS = frozenset({
    "INPUT_VALUE",
    "SELECT",
    "RADIO",
    "CHECKBOX",
})

_DEPENDENCY_READINESS_TIMEOUT_SECONDS = 4
_DEPENDENCY_READINESS_POLL_INTERVAL_SECONDS = 0.25
# QCC_EX01_R11_FIX3_CASCADE: bounded window for a dependent address
# option that Mercurio loads by AJAX after its parent changes. The
# historical cascade allowed 1.2 s settle + 4 s; the governed one only
# 4 s (REAL 18-11-2026: WAIT_FAIL after 4 s). Polled, ABORT serviced,
# returns as soon as the intended option is offered: never a sleep.
_CASCADE_OPTION_TIMEOUT_SECONDS = 12
_MAPPER_CASCADE_DIAGNOSTIC_MARKER = "/*QCC_MAPPER_CASCADE_DIAGNOSTIC*/"


def _field_readiness_js(field_id):
    """JAVASCRIPT BOOLEAN EXPRESSION contract: an IIFE CALL, never a
    statement. Must stay directly composable as
    ``(<this>) && (<other>)`` -- a trailing statement semicolon after
    the call (``})();``) is invalid inside that expression position
    and was the confirmed V5->V6 regression (``MALFORMED_COMPOSED_
    READINESS_JS``): every call site below already supplies its own
    statement terminator where one is actually needed.
    """
    return f"""
    (function(){{
        const el = document.getElementById({json.dumps(field_id)});
        if (!el) return false;
        if (el.disabled) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        if (el.getAttribute('aria-hidden') === 'true') return false;
        if (el.closest('[style*="display: none"]')) return false;
        return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
    }})()
    """


def _wait_for_dependency_readiness(browser, field_id, session_dir=None):
    """Bounded, deterministic wait for ``field_id`` to become visible,
    enabled and interactable in the LIVE DOM.

    Never grants authorization by itself: it only delays re-asking the
    certified gate until Mercurio's own dependency transition has had
    a bounded chance to finish, instead of looping/sleeping blindly.
    """

    try:
        wait_for_js(
            browser,
            _field_readiness_js(field_id),
            timeout=_DEPENDENCY_READINESS_TIMEOUT_SECONDS,
            interval=_DEPENDENCY_READINESS_POLL_INTERVAL_SECONDS,
        )
        return True
    except Exception as exc:
        if session_dir:
            write_log(
                session_dir,
                "DEPENDENCY_READINESS_TIMEOUT "
                f"field={field_id}: {type(exc).__name__}",
            )
        return False


# QCC_ASSISTED_AUTO_READINESS_V5: EX01_DETECTED_CONDITION is presence
# -only (``document.getElementById`` truthy), proven by the REAL smoke
# to be premature -- Mercurio can inject the personal-data screen's
# DOM nodes before its own async reveal/enable handler has finished,
# leaving extPasaporte/extNie disabled/non-interactable for a bounded
# window. EX01_READY_CONDITION adds the SAME LIVE-DOM interactability
# check already certified for the per-field dependency wait
# (``_field_readiness_js``), but evaluated at the PAGE level, before
# FILL_STAGE_ENTERED, so fill_datos_extranjero never races it.
EX01_PERSONAL_CANDIDATE_DETECTED_JS = (
    "(document.getElementById('extNombre') || "
    "document.getElementById('extNie') || "
    "document.getElementById('extPasaporte') || "
    "document.getElementById('extNacionalidad'))"
)


def _ex01_personal_canonical_write_fields(datos_mercurio):
    """EXT_PASAPORTE_DEPENDENCY / NIE branch resolution.

    Returns the document field id(s) the real mapper output will
    actually write for the EX01 personal-data screen: ``extPasaporte``
    when the client carries a passport value, ``extNie`` when it
    carries a NIE value, both when it carries both. Never requires
    readiness of the unused alternate branch -- a client with only a
    NIE must never block on extPasaporte becoming interactable, and
    vice versa. Falls back to ``extNombre`` (always part of the
    canonical write) when neither document value is present.
    """

    extranjero = (datos_mercurio or {}).get("extranjero", {}) or {}

    fields = [
        field_id
        for field_id in ("extPasaporte", "extNie")
        if str(extranjero.get(field_id) or "").strip()
    ]

    return fields or ["extNombre"]


def _ex01_personal_ready_js(datos_mercurio):
    """EX01_READY_CONDITION: candidate screen detected AND the
    canonical document field(s) that will actually be written are
    visible, enabled and interactable in the LIVE DOM -- never merely
    present.

    QCC_EX01_R11_FIX2: one line (CDP contract, ``_one_line_js``). The
    multi-line composition left ``wait_for_js``'s ``return`` on the
    first line, so ``sb_cdp.Chrome.evaluate`` raised ``SyntaxError:
    Illegal return statement`` on every poll (silenced by
    ``wait_for_js``) and EX01_READY never fired with both fields
    interactable (REAL 131, 18/11)."""

    fields = _ex01_personal_canonical_write_fields(datos_mercurio)
    readiness = " && ".join(
        f"({_field_readiness_js(field_id)})" for field_id in fields
    )
    return _one_line_js(f"{EX01_PERSONAL_CANDIDATE_DETECTED_JS} && {readiness}")


# QCC_EX01_RENOVACION_TITULAR_130_V1: identidad del supuesto preciso
# EX-01-2-01 Renovación Titular (datosForAut=130, grupo gsup_28).
# Fuentes: ERP RENOVACION_TITULAR -> tipo EX01 / mapper MERCURIO_EX01;
# supuesto/valor según tools/mercurio_lab/ex01/contract.py y
# docs/ai/CURRENT_STATE.md §8; capacidad observable "Datos del
# familiar" (pestFamiliar) según site_recognizers/mercurio.py. La
# selección del supuesto es HUMANA: el runner solo lee el DOM vivo y
# bloquea si no coincide o es ambigua. 131 (Familiar) nunca es 130.
EX01_RENOVACION_TITULAR_IDENTITY = {
    "procedure": "EX01_RENOVACION_TITULAR",
    "tipo_formulario_objetivo": "EX01",
    "mapper_codigo": "MERCURIO_EX01",
    "supuesto_id": "EX-01-2-01",
    "datos_for_aut": "130",
    "supuesto_group": "gsup_28",
}
EX01_RENOVACION_FAMILIAR_DATOS_FOR_AUT = "131"
EX01_RENOVACION_TITULAR_LABEL = "EX-01-2-01 Renovación Titular"

EX01_TITULAR_IDENTITY_MATCH = "MATCH"
EX01_TITULAR_IDENTITY_MISMATCH = "MISMATCH"
EX01_TITULAR_IDENTITY_AMBIGUOUS = "AMBIGUOUS"

_EX01_FORM_PANEL_IDS = (
    "tab-datos_autorizacion",
    "tab-datos_personales",
    "tab-datos_familiar",
    "tab-datos_presentador",
    "tab-datos_notificacion",
)
_EX01_AUTHORIZATION_PANEL_ID = "tab-datos_autorizacion"
_EX01_PERSONAL_PANEL_ID = "tab-datos_personales"
_EX01_PRESENTER_PANEL_ID = "tab-datos_presentador"


def _ex01_sole_active_panel_js(panel_id):
    """Live predicate: ``panel_id`` is the ONLY active EX01 r-tabs
    panel. Same signal as the Mercurio recognizer (fail closed on
    absence or ambiguity). One line, no ``//``."""

    return " ".join((
        "(function(){",
        f"const ids = {json.dumps(list(_EX01_FORM_PANEL_IDS))};",
        "const active = ids.filter(function(id){",
        "const el = document.getElementById(id);",
        "return !!el && !!el.classList && el.classList.contains('r-tabs-state-active');",
        "});",
        f"return active.length === 1 && active[0] === {json.dumps(panel_id)};",
        "})()",
    ))


EX01_TITULAR_PERSONAL_SURFACE_JS = (
    f"{EX01_PERSONAL_CANDIDATE_DETECTED_JS} && "
    f"{_ex01_sole_active_panel_js(_EX01_PERSONAL_PANEL_ID)}"
)

EX01_TITULAR_PRESENTER_SURFACE_JS = (
    "document.getElementById('preNombrePresentador') && "
    f"{_ex01_sole_active_panel_js(_EX01_PRESENTER_PANEL_ID)}"
)

_EX01_TITULAR_IDENTITY_MARKER = "/*QCC_EX01_TITULAR_IDENTITY*/"


def _ex01_titular_identity_evidence_js():
    """Read-only, value-free probe of the LIVE DOM at decision time
    (never a reused capture): EX01 page, active panels, the human's
    datosForAut selection with its gsup_* group, and the observable
    "Datos del familiar" capability. One line (CDP contract).

    QCC_EX01_R11_FIX2: in REAL nuevaSolicitud-EX01 (39/39 REAL
    site_architecture captures) the group is NOT an ancestor of the
    radio: ``div.dvGrSup`` holds a disabled ``input.optGrSup#gsup_*``
    marker as a sibling of the ``ul.ulSupuestos`` that contains the
    datosForAut radio, all inside ``tab-datos_autorizacion``. The old
    ``closest('[id^="gsup_"]')`` was always null in REAL. The group
    is only observed when the radio's own ``ul.ulSupuestos`` is a
    direct child of that same ``div.dvGrSup`` holding exactly one
    direct ``optGrSup`` marker; marker count and document-wide id
    count are reported so plural/duplicated markers fail closed."""

    return " ".join((
        _EX01_TITULAR_IDENTITY_MARKER,
        "(function(){",
        f"const ids = {json.dumps(list(_EX01_FORM_PANEL_IDS))};",
        "const active = ids.filter(function(id){",
        "const el = document.getElementById(id);",
        "return !!el && !!el.classList && el.classList.contains('r-tabs-state-active');",
        "});",
        "const checked = Array.from(document.querySelectorAll(",
        "'input[type=\"radio\"][name=\"datosForAut\"]'",
        ")).filter(function(el){ return !!el.checked; });",
        "const sel = checked.length === 1 ? checked[0] : null;",
        "const canClose = !!sel && typeof sel.closest === 'function';",
        "const box = canClose ? sel.closest('div.dvGrSup') : null;",
        "const list = canClose ? sel.closest('ul.ulSupuestos') : null;",
        "const markers = (box && list && list.parentElement === box)",
        "? Array.from(box.children).filter(function(el){",
        "return el.matches('input.optGrSup[id^=\"gsup_\"]');",
        "}) : [];",
        "const group = markers.length === 1 ? markers[0] : null;",
        "const groupIdCount = group ? Array.from(",
        "document.querySelectorAll('[id^=\"gsup_\"]')",
        ").filter(function(el){ return el.id === group.id; }).length : 0;",
        "const panel = canClose ? sel.closest('.r-tabs-panel') : null;",
        "const tab = document.getElementById('pestFamiliar');",
        "let familiar = 'ABSENT';",
        "if (tab) {",
        "const style = window.getComputedStyle ? window.getComputedStyle(tab) : null;",
        "familiar = (tab.hidden || (style && style.display === 'none'))",
        "? 'HIDDEN' : 'VISIBLE';",
        "}",
        "return {",
        "pathname: String(window.location.pathname || ''),",
        "active_panels: active,",
        "checked_count: checked.length,",
        "datos_for_aut: sel ? String(sel.value || '') : null,",
        "supuesto_id: sel ? String(sel.id || '') : null,",
        "supuesto_group: group ? String(group.id || '') : null,",
        "supuesto_group_markers: markers.length,",
        "supuesto_group_id_count: groupIdCount,",
        "supuesto_panel: panel ? String(panel.id || '') : null,",
        "familiar_tab: familiar",
        "};",
        "})()",
    ))


def classify_ex01_renovacion_titular_evidence(evidence):
    """Pure decision over live evidence: ``(status, reason)``.

    MATCH only for EX01 + sole active Datos del extranjero/a panel +
    exactly one datosForAut=130 (EX-01-2-01) on the authorization
    panel, in the div.dvGrSup whose single, unique optGrSup marker is
    gsup_28 + no visible "Datos del familiar" capability. Anything
    contradictory is MISMATCH; anything missing or plural is
    AMBIGUOUS. Both block.
    """

    from backend.automation.site_recognizers.mercurio import (
        MERCURIO_EX01_NEW_REQUEST_PATH,
    )

    identity = EX01_RENOVACION_TITULAR_IDENTITY

    if not isinstance(evidence, dict):
        return EX01_TITULAR_IDENTITY_AMBIGUOUS, "EVIDENCE_UNREADABLE"

    if str(evidence.get("pathname") or "") != MERCURIO_EX01_NEW_REQUEST_PATH:
        return EX01_TITULAR_IDENTITY_MISMATCH, "NOT_EX01_FORM"

    active = list(evidence.get("active_panels") or ())
    if len(active) != 1:
        return EX01_TITULAR_IDENTITY_AMBIGUOUS, "ACTIVE_PANEL_AMBIGUOUS"
    if active[0] != _EX01_PERSONAL_PANEL_ID:
        return EX01_TITULAR_IDENTITY_MISMATCH, "NOT_PERSONAL_SURFACE"

    if evidence.get("checked_count") != 1:
        return EX01_TITULAR_IDENTITY_AMBIGUOUS, "SUPUESTO_SELECTION_AMBIGUOUS"

    datos_for_aut = str(evidence.get("datos_for_aut") or "")
    if datos_for_aut == EX01_RENOVACION_FAMILIAR_DATOS_FOR_AUT:
        return EX01_TITULAR_IDENTITY_MISMATCH, "SUPUESTO_FAMILIAR_131"
    if datos_for_aut != identity["datos_for_aut"]:
        return EX01_TITULAR_IDENTITY_MISMATCH, "SUPUESTO_NOT_130"

    supuesto_id = str(evidence.get("supuesto_id") or "")
    if not supuesto_id:
        return EX01_TITULAR_IDENTITY_AMBIGUOUS, "SUPUESTO_ID_UNOBSERVED"
    if supuesto_id != identity["supuesto_id"]:
        return EX01_TITULAR_IDENTITY_MISMATCH, "SUPUESTO_ID_MISMATCH"

    panel = str(evidence.get("supuesto_panel") or "")
    if not panel:
        return EX01_TITULAR_IDENTITY_AMBIGUOUS, "SUPUESTO_PANEL_UNOBSERVED"
    if panel != _EX01_AUTHORIZATION_PANEL_ID:
        return EX01_TITULAR_IDENTITY_MISMATCH, "SUPUESTO_PANEL_MISMATCH"

    # bool is an int subclass: never accept True as "one marker".
    markers = evidence.get("supuesto_group_markers")
    if type(markers) is not int:
        markers = 0
    if markers > 1:
        return EX01_TITULAR_IDENTITY_AMBIGUOUS, "SUPUESTO_GROUP_AMBIGUOUS"
    group = str(evidence.get("supuesto_group") or "")
    if markers != 1 or not group:
        return EX01_TITULAR_IDENTITY_AMBIGUOUS, "SUPUESTO_GROUP_UNOBSERVED"
    id_count = evidence.get("supuesto_group_id_count")
    if type(id_count) is not int or id_count != 1:
        return EX01_TITULAR_IDENTITY_AMBIGUOUS, "SUPUESTO_GROUP_AMBIGUOUS"
    if group != identity["supuesto_group"]:
        return EX01_TITULAR_IDENTITY_MISMATCH, "SUPUESTO_GROUP_MISMATCH"

    familiar_tab = evidence.get("familiar_tab")
    if familiar_tab == "VISIBLE":
        return EX01_TITULAR_IDENTITY_MISMATCH, "FAMILIAR_CAPABILITY_VISIBLE"
    if familiar_tab not in ("HIDDEN", "ABSENT"):
        return EX01_TITULAR_IDENTITY_AMBIGUOUS, "FAMILIAR_CAPABILITY_UNKNOWN"

    return EX01_TITULAR_IDENTITY_MATCH, identity["procedure"]


def _verify_ex01_renovacion_titular_identity(browser, session_dir, phase):
    """Reads the identity evidence from the LIVE DOM right now and
    classifies it. Logs only branch codes/structure, never PII."""

    try:
        evidence = js(browser, _ex01_titular_identity_evidence_js())
    except Exception as exc:
        write_log(
            session_dir,
            f"EX01_TITULAR_IDENTITY_PROBE_ERROR phase={phase}: {type(exc).__name__}",
        )
        evidence = None

    status, reason = classify_ex01_renovacion_titular_evidence(evidence)
    observed = evidence if isinstance(evidence, dict) else {}

    write_log(
        session_dir,
        "EX01_TITULAR_IDENTITY "
        f"phase={phase} status={status} reason={reason} "
        f"datosForAut={observed.get('datos_for_aut') or '-'} "
        f"group={observed.get('supuesto_group') or '-'} "
        f"group_markers={observed.get('supuesto_group_markers', '-')} "
        f"panel={observed.get('supuesto_panel') or '-'} "
        f"familiar_tab={observed.get('familiar_tab') or '-'}",
    )

    return {
        "ok": status == EX01_TITULAR_IDENTITY_MATCH,
        "mode": f"ex01_titular_identity_{status.lower()}",
        "label": EX01_RENOVACION_TITULAR_LABEL,
        "status": status,
        "reason": reason,
        "phase": phase,
    }


def _classify_mercurio_environment_from_origin(origin):
    """Classifies an ACTUAL browser origin as LAB or REAL.

    Never trusts caller-claimed metadata: only the concrete origin
    observed in the live DOM capture. Any other origin is
    deliberately left unclassified (``None``) so the caller fails
    closed instead of silently defaulting to LAB.
    """

    from backend.automation.site_architecture.site_target import (
        SiteEnvironment,
    )
    from backend.automation.site_policies.mercurio import (
        MERCURIO_LAB_ORIGIN,
        MERCURIO_REAL_ORIGIN,
    )

    origin = str(origin or "").strip()

    if not origin:
        return None

    if origin == MERCURIO_REAL_ORIGIN:
        return SiteEnvironment.REAL

    if origin == MERCURIO_LAB_ORIGIN:
        return SiteEnvironment.LAB

    host = (urlsplit(origin).hostname or "").lower()

    if host in ("127.0.0.1", "localhost"):
        return SiteEnvironment.LAB

    return None


def _fail_closed_governed_result(*, action_kind, field_id, reason):
    """Builds a governed-shaped denial WITHOUT ever invoking the
    executor: used only when the actual live target cannot be
    trusted (unrecognized origin, or a claimed environment that
    contradicts it). Never carries a raw field value."""

    from backend.automation.site_architecture.execution_evidence import (
        build_execution_evidence,
    )
    from backend.automation.site_architecture.outcome_classification import (
        ACTION_DISPOSITION_CONFIRMED_NOT_EXECUTED,
    )
    from backend.automation.site_architecture.state_aware_execution import (
        STATE_AWARE_EXECUTION_BLOCKED_POLICY,
        STATE_AWARE_EXECUTION_SCHEMA_VERSION,
        STATE_AWARE_RESULT_BLOCKED,
        StateAwareExecutionResult,
    )

    evidence = build_execution_evidence(
        provider="MERCURIO",
        action_kind=action_kind,
        action_selector=f"#{field_id}",
        gate_reason=reason,
        attempt_count=0,
        final_disposition=ACTION_DISPOSITION_CONFIRMED_NOT_EXECUTED,
        result_status=STATE_AWARE_RESULT_BLOCKED,
    )

    return StateAwareExecutionResult(
        schema_version=STATE_AWARE_EXECUTION_SCHEMA_VERSION,
        decision=STATE_AWARE_EXECUTION_BLOCKED_POLICY,
        result_status=STATE_AWARE_RESULT_BLOCKED,
        outcome=None,
        disposition=ACTION_DISPOSITION_CONFIRMED_NOT_EXECUTED,
        executed=False,
        attempt_count=0,
        recovery_attempts=(),
        gate_decision=None,
        gate_reason=reason,
        reason=reason,
        evidence=evidence,
    )


def _already_satisfied_governed_result(*, action_kind, field_id):
    """Governed-shaped result for a write that was NOT needed: the live
    control already matches the expected value. Never executed, never
    carries the value."""

    from backend.automation.site_architecture.execution_evidence import (
        build_execution_evidence,
    )
    from backend.automation.site_architecture.outcome_classification import (
        ACTION_DISPOSITION_CONFIRMED_NOT_EXECUTED,
    )
    from backend.automation.site_architecture.state_aware_execution import (
        STATE_AWARE_EXECUTION_BLOCKED_POLICY,
        STATE_AWARE_EXECUTION_SCHEMA_VERSION,
        STATE_AWARE_RESULT_SUCCESS,
        StateAwareExecutionResult,
    )

    reason = GOVERNED_ALREADY_SATISFIED_REASON
    evidence = build_execution_evidence(
        provider="MERCURIO",
        action_kind=action_kind,
        action_selector=f"#{field_id}",
        gate_reason=reason,
        attempt_count=0,
        final_disposition=ACTION_DISPOSITION_CONFIRMED_NOT_EXECUTED,
        result_status=STATE_AWARE_RESULT_SUCCESS,
    )

    return StateAwareExecutionResult(
        schema_version=STATE_AWARE_EXECUTION_SCHEMA_VERSION,
        decision=STATE_AWARE_EXECUTION_BLOCKED_POLICY,
        result_status=STATE_AWARE_RESULT_SUCCESS,
        outcome=None,
        disposition=ACTION_DISPOSITION_CONFIRMED_NOT_EXECUTED,
        executed=False,
        attempt_count=0,
        recovery_attempts=(),
        gate_decision=None,
        gate_reason=reason,
        reason=reason,
        evidence=evidence,
    )


def _governed_outcome(result):
    """Maps a ``StateAwareExecutionResult`` onto the smallest outcome
    callers need to react safely: did a real DOM mutation happen, and
    if not, is that a policy/evidence denial, a human handoff, or an
    execution failure. Never inferred from the absence of an
    exception, always from the governed decision/disposition."""

    from backend.automation.site_architecture.outcome_classification import (
        ACTION_DISPOSITION_EFFECT_UNKNOWN,
    )
    from backend.automation.site_architecture.state_aware_execution import (
        STATE_AWARE_EXECUTION_ALLOWED,
        STATE_AWARE_EXECUTION_REQUIRES_HUMAN,
    )

    if not result.executed and result.reason in _GOVERNED_DEFERRED_OUTCOMES:
        return result.reason

    if not result.executed and result.reason == GOVERNED_ALREADY_SATISFIED_REASON:
        return GOVERNED_OUTCOME_OK

    if (
        result.decision == STATE_AWARE_EXECUTION_ALLOWED
        and result.executed
    ):
        if result.disposition == ACTION_DISPOSITION_EFFECT_UNKNOWN:
            return GOVERNED_OUTCOME_FAILED
        return GOVERNED_OUTCOME_OK

    if result.decision == STATE_AWARE_EXECUTION_REQUIRES_HUMAN:
        return GOVERNED_OUTCOME_HUMAN_HANDOFF

    return GOVERNED_OUTCOME_DENIED


def _log_governed_write(session_dir, field_id, action_kind, result):
    """Value-free governed write log: identity, decision and reason
    codes only. Never the field's supplied/selected value."""

    if not session_dir:
        return

    write_log(
        session_dir,
        "governed_write "
        f"field={field_id} kind={action_kind} "
        f"decision={result.decision} "
        f"status={result.result_status} "
        f"outcome={_governed_outcome(result)} "
        f"reason={result.reason}",
    )


# QCC_FILL_PERFORMANCE_NATIVE_CONTROLS_V1: value-free field read-back
# used by every governed form-control postcondition. ONE LOGICAL LINE
# and no top-level ``return`` (same CDP ``evaluate`` contract as
# ``_field_readiness_js``). The leading marker comment keeps it
# distinguishable from readiness probes and DOM writes.
_FIELD_READBACK_MARKER = "/*QCC_FIELD_READBACK*/"
_FIELD_SCROLL_MARKER = "/*QCC_FIELD_SCROLL_INTO_VIEW*/"


def _field_readback_js(field_id):
    return " ".join((
        _FIELD_READBACK_MARKER,
        "(function(){",
        f"const el = document.getElementById({json.dumps(field_id)});",
        "if (!el) return { exists: false };",
        "const idx = typeof el.selectedIndex === 'number' ? el.selectedIndex : -1;",
        "const opt = (el.options && idx >= 0) ? el.options[idx] : null;",
        "return {",
        "exists: true,",
        "tag: String(el.tagName || '').toLowerCase(),",
        "type: String(el.type || '').toLowerCase(),",
        "value: el.value == null ? '' : String(el.value),",
        "checked: !!el.checked,",
        "selected_index: idx,",
        "selected_value: opt ? String(opt.value == null ? '' : opt.value) : null,",
        "selected_text: opt ? String(opt.textContent || opt.text || '') : null",
        "};",
        "})()",
    ))


def _field_scroll_into_view_js(field_id):
    return " ".join((
        _FIELD_SCROLL_MARKER,
        "(function(){",
        f"const el = document.getElementById({json.dumps(field_id)});",
        "if (!el || typeof el.scrollIntoView !== 'function') return false;",
        "el.scrollIntoView({ block: 'center', inline: 'nearest' });",
        "return true;",
        "})()",
    ))


# QCC_FULL_MAPPER_FAST_PATH_V1: targeted, value-free probe of ONE live
# control. Mirrors the full DOM capture's own per-element signals
# (``dom_inspector`` visibilityOf/interactionSignalsOf) plus the page
# identity and the Mercurio tab panel (r-tabs) that contains the
# control. ONE LOGICAL LINE, no top-level ``return`` (CDP ``evaluate``
# contract, same as ``_field_readback_js``).
_FIELD_LOCAL_PROBE_MARKER = "/*QCC_FIELD_LOCAL_PROBE*/"


def _field_local_probe_js(field_id):
    return " ".join((
        _FIELD_LOCAL_PROBE_MARKER,
        "(function(){",
        "const page = { origin: String(window.location.origin || ''), pathname: String(window.location.pathname || '') };",
        f"const el = document.getElementById({json.dumps(field_id)});",
        "if (!el) return { exists: false, origin: page.origin, pathname: page.pathname };",
        "const rect = el.getBoundingClientRect();",
        "const style = window.getComputedStyle(el);",
        "const root = document.documentElement;",
        "const vw = Number(window.innerWidth || (root && root.clientWidth) || 0);",
        "const vh = Number(window.innerHeight || (root && root.clientHeight) || 0);",
        "const panel = el.closest('.r-tabs-panel, .mf-tabs--tab-content');",
        "let panelVisible = true;",
        "if (panel) { const ps = window.getComputedStyle(panel); panelVisible = ps.display !== 'none' && ps.visibility !== 'hidden' && panel.getClientRects().length > 0; }",
        "const panelActive = !!panel && panel.classList.contains('r-tabs-state-active');",
        # QCC_EX01_R6_POSTFORM: hidden by something INSIDE its panel (own
        # display/hidden/aria-hidden/type=hidden, or an ancestor below the
        # panel) -- a dependency, never the panel's own inactivity.
        "let hiddenWithinPanel = !!el.hidden || String(el.type || '').toLowerCase() === 'hidden' || String(el.getAttribute('aria-hidden') || '').toLowerCase() === 'true';",
        "if (panel) { for (let n = el; n && n !== panel; n = n.parentElement) { if (n.hidden || n.getAttribute('aria-hidden') === 'true' || window.getComputedStyle(n).display === 'none') { hiddenWithinPanel = true; break; } } if (style.visibility === 'hidden' && window.getComputedStyle(panel).visibility !== 'hidden') hiddenWithinPanel = true; }",
        "return {",
        "exists: true,",
        "origin: page.origin,",
        "pathname: page.pathname,",
        "visible: !!(rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden'),",
        "disabled: !!el.disabled,",
        "interaction_signals: {",
        "hidden: !!el.hidden,",
        "aria_hidden: String(el.getAttribute('aria-hidden') || '').toLowerCase() === 'true',",
        "aria_disabled: String(el.getAttribute('aria-disabled') || '').toLowerCase() === 'true',",
        "readonly: !!el.readOnly,",
        "in_viewport: !!(rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.bottom > 0 && rect.left < vw && rect.top < vh),",
        "opacity: String(style.opacity || ''),",
        "pointer_events: String(style.pointerEvents || '')",
        "},",
        "panel_id: panel ? String(panel.id || '') : null,",
        "panel_active: !!panel && panelActive && panelVisible,",
        "panel_inactive: !!panel && !panelActive && !panelVisible,",
        "hidden_within_panel: hiddenWithinPanel",
        "};",
        "})()",
    ))


def _probe_field_locally(browser, field_id):
    try:
        probe = js(browser, _field_local_probe_js(field_id))
    except Exception:
        return None

    return probe if isinstance(probe, dict) else None


def _probe_off_viewport(probe):
    signals = probe.get("interaction_signals") or {}
    return (
        probe.get("visible") is True
        and probe.get("disabled") is not True
        and signals.get("in_viewport") is False
    )


def _probe_surface_consistent(probe):
    """QCC_EX01_R2: the section capture may only be reused when the
    control sits on the surface that capture recognized -- no r-tabs
    panel at all (page identity is the surface) or the ACTIVE displayed
    panel. Any other panel state is not evidence for a write: the
    caller falls back to a fresh full capture and the unchanged gate
    decides (a hidden/inactive control is still denied)."""

    if not probe.get("panel_id"):
        return probe.get("panel_inactive") is not True
    return probe.get("panel_active") is True


_SECTION_FAST_PATH_ACTION_KINDS = frozenset({
    "INPUT_VALUE",
    "SELECT",
    "CHECKBOX",
    "RADIO",
})


class _GovernedSection:
    """One stable mapper section/page under a single governance check.

    Holds the ONE full Site Architecture capture taken at section entry
    (origin binding + functional-state recognition). Ordinary writes
    inside the section reuse it and only pay a targeted local probe,
    the write itself and a targeted read-back. A fresh full capture is
    only taken on entry, after invalidation (transition trigger,
    postcondition/policy failure, page or surface change, unusable
    local probe), for any non-ordinary write, or when the engine's own
    recovery asks for one.
    """

    def __init__(self, browser, session_dir=None, label=""):
        from backend.automation.site_architecture.seleniumbase_executor import (
            build_seleniumbase_snapshot_provider,
        )

        self.browser = browser
        self.session_dir = session_dir
        self.label = label
        self.capture = None
        self.full_capture_count = 0
        self.reused_count = 0
        # QCC_EX01_R6_POSTFORM: canonical mapper DOM field ids this
        # section may DEFER (never write) while their surface is not the
        # active one (empty = generic section), the ones whose surface was
        # reached by human navigation, and the per-field deferrals.
        self.preload_fields = frozenset()
        self.required_fields = set()
        self.deferred = {}
        self._provider = build_seleniumbase_snapshot_provider(browser)

    def capture_fresh(self):
        self.capture = None
        self.full_capture_count += 1
        self.capture = self._provider()
        return self.capture

    def capture_fresh_or_none(self):
        try:
            return self.capture_fresh()
        except Exception:
            return None

    def invalidate(self):
        self.capture = None

    def matches_page(self, probe):
        if self.capture is None or not isinstance(probe, dict):
            return False
        page = self.capture.snapshot.get("page") or {}
        origin = str(probe.get("origin") or "")
        pathname = str(probe.get("pathname") or "")
        return bool(origin) and (
            origin == str(page.get("origin") or "")
            and pathname == urlsplit(str(page.get("url") or "")).path
        )

    def active_panel_ids(self):
        """Ids of the r-tabs panels the section capture itself saw
        active (same class evidence the Mercurio recognizer uses)."""

        if self.capture is None:
            return frozenset()

        from backend.automation.site_recognizers import mercurio as ex01

        payload = ex01._snapshot_payload(self.capture.snapshot)
        active = set()

        for element in ex01._elements(payload):
            if not isinstance(element, dict):
                continue
            tokens = ex01._class_tokens(element) | {
                str(token) for token in (element.get("classes") or ())
            }
            if "r-tabs-state-active" in tokens:
                active.add(str(ex01._element_field(element, "id") or "").strip())

        active.discard("")
        return frozenset(active)

    def proves_surface(self, probe):
        """QCC_EX01_R3: reuse evidence for ONE ordinary write. Same page,
        the control exists, its panel is active now AND is a panel the
        section capture recognized as active. A control on any other
        panel means the functional state changed since the capture:
        never authorized from it."""

        if not (
            self.matches_page(probe)
            and probe.get("exists") is True
            and _probe_surface_consistent(probe)
        ):
            return False

        panel_id = str(probe.get("panel_id") or "").strip()
        return not panel_id or panel_id in self.active_panel_ids()


_ACTIVE_GOVERNED_SECTIONS = []


def _active_governed_section(browser):
    for section in reversed(_ACTIVE_GOVERNED_SECTIONS):
        if section.browser is browser:
            return section
    return None


@contextmanager
def governed_section(browser, session_dir=None, label="", preload_fields=None):
    """Opens (or joins, when one is already open for ``browser``) a
    section-scoped governance context for ordinary writes.

    ``preload_fields`` (QCC_EX01_R6_POSTFORM) is only ever passed by an
    audited canonical Mercurio mapper section: the canonical DOM field
    ids that, found on a surface that is not the active one, are DEFERRED
    instead of denied. It never grants a write on a hidden surface. Never
    global: a joined section gets it added and restored on exit.
    """

    existing = _active_governed_section(browser)
    preload_fields = frozenset(preload_fields or ()) & _CANONICAL_DOM_FIELDS

    if existing is not None:
        previous = existing.preload_fields
        existing.preload_fields = previous | preload_fields
        try:
            yield existing
        finally:
            existing.preload_fields = previous
        return

    section = _GovernedSection(browser, session_dir, label)
    section.preload_fields = preload_fields
    _ACTIVE_GOVERNED_SECTIONS.append(section)

    try:
        yield section
    finally:
        _ACTIVE_GOVERNED_SECTIONS.remove(section)
        if session_dir:
            write_log(
                session_dir,
                "GOVERNED_SECTION_CLOSED "
                f"label={label or '-'} "
                f"full_page_captures={section.full_capture_count} "
                f"reused_captures={section.reused_count} "
                f"deferred={len(section.deferred)}",
            )


def _read_field_state(browser, field_id):
    try:
        state = js(browser, _field_readback_js(field_id))
    except Exception:
        return None

    return state if isinstance(state, dict) else None


def _log_postcondition_failure(session_dir, field_id, action_kind, reason):
    """Value-free: reason codes only, never the supplied/read value."""

    if not session_dir:
        return

    write_log(
        session_dir,
        "governed_write_postcondition "
        f"field={field_id} kind={action_kind} "
        f"verified=False reason={reason}",
    )


def _apply_failure_reason(apply_result, default):
    """Only ever a short reason CODE from the apply script, never a
    value/option list."""

    if isinstance(apply_result, dict):
        reason = str(apply_result.get("reason") or "")
        if re.fullmatch(r"[A-Z0-9_]{1,64}", reason):
            return reason
    return default


def _canonical_input_value(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _input_value_matches(state, expected):
    return (
        state.get("value") == expected
        or _canonical_input_value(state.get("value"))
        == _canonical_input_value(expected)
    )


def _verify_input_value(browser, field_id, expected, session_dir=None):
    state = _read_field_state(browser, field_id)

    if state is None:
        reason = "READBACK_UNAVAILABLE"
    elif not state.get("exists"):
        reason = "NO_EXISTE"
    elif not _input_value_matches(state, expected):
        reason = "INPUT_VALUE_MISMATCH"
    else:
        return True

    _log_postcondition_failure(session_dir, field_id, "INPUT_VALUE", reason)
    return False


def _verify_select_option(
    browser,
    field_id,
    apply_result,
    session_dir=None,
    *,
    selected_value_keys=("value",),
):
    """SELECT postcondition: the apply script must have matched an
    option, and the LIVE control must now have exactly that option
    selected. A placeholder (empty-value) match is never a valid
    selection."""

    if not isinstance(apply_result, dict):
        reason = "APPLY_RESULT_UNAVAILABLE"
    elif apply_result.get("ok") is not True:
        reason = _apply_failure_reason(apply_result, "SELECT_NOT_APPLIED")
    else:
        expected = next(
            (
                apply_result.get(key)
                for key in selected_value_keys
                if apply_result.get(key) is not None
            ),
            None,
        )
        expected = "" if expected is None else str(expected)
        state = _read_field_state(browser, field_id)

        if not expected:
            reason = "SELECT_PLACEHOLDER_ONLY"
        elif state is None:
            reason = "READBACK_UNAVAILABLE"
        elif not state.get("exists"):
            reason = "NO_EXISTE"
        elif state.get("selected_value") is None:
            # Non-<select> fallback (set_piso_mercurio 'input' mode).
            if state.get("value") != expected:
                reason = "SELECT_OPTION_NOT_SELECTED"
            else:
                return True
        elif (
            state.get("selected_index", -1) < 0
            or state.get("selected_value") != expected
            or state.get("value") != expected
        ):
            reason = "SELECT_OPTION_NOT_SELECTED"
        else:
            return True

    _log_postcondition_failure(session_dir, field_id, "SELECT", reason)
    return False


def _verify_checked_state(
    browser, field_id, action_kind, expected, apply_result=None, session_dir=None
):
    if isinstance(apply_result, dict) and apply_result.get("ok") is False:
        reason = _apply_failure_reason(apply_result, "CHECKED_NOT_APPLIED")
    else:
        state = _read_field_state(browser, field_id)

        if state is None:
            reason = "READBACK_UNAVAILABLE"
        elif not state.get("exists"):
            reason = "NO_EXISTE"
        elif bool(state.get("checked")) != bool(expected):
            reason = f"{action_kind}_STATE_MISMATCH"
        else:
            return True

    _log_postcondition_failure(session_dir, field_id, action_kind, reason)
    return False


# QCC_PRESENTER_PRELOAD_PROOF_V1: read-only "already satisfied" checks of
# the exact expected live state. Never write, never log the value.
def _input_value_satisfied(browser, field_id, expected):
    state = _read_field_state(browser, field_id)
    return bool(
        expected
        and state is not None
        and state.get("exists")
        and _input_value_matches(state, expected)
    )


def _select_option_satisfied(browser, field_id, wanted_value, wanted_text):
    """``wanted_text`` is already ``normalize()``d, exactly as the
    apply script's exact-text tier compares option texts."""

    state = _read_field_state(browser, field_id)
    if state is None or not state.get("exists"):
        return False
    selected = state.get("selected_value")
    if (
        not selected
        or state.get("selected_index", -1) < 0
        or state.get("value") != selected
    ):
        # No option / placeholder (empty-value) option is never valid.
        return False
    return bool(
        (wanted_value and selected == wanted_value)
        or (wanted_text and normalize(state.get("selected_text")) == wanted_text)
    )


def _checked_state_satisfied(browser, field_id, expected, input_type):
    state = _read_field_state(browser, field_id)
    return bool(
        state is not None
        and state.get("exists")
        and state.get("type") == input_type
        and bool(state.get("checked")) == bool(expected)
    )


def _snapshot_interaction_state(snapshot, action_kind, field_id):
    """Interaction state (e.g. ``OFF_VIEWPORT``) of the governed target
    in an already-captured snapshot, or ``None`` if not resolvable."""

    selector = f"#{field_id}"

    for action in (snapshot or {}).get("actions") or ():
        if not isinstance(action, dict):
            continue
        if str(action.get("kind") or "").strip().upper() != action_kind:
            continue
        if str(action.get("selector") or "").strip() != selector:
            continue
        interaction = action.get("interaction") or {}
        if isinstance(interaction, dict):
            return interaction.get("state")
    return None


def _reusing_snapshot_provider(fresh_provider, initial_capture):
    """Serves the capture ``_governed_write`` already took (to bind the
    actual origin) as the engine's FIRST snapshot instead of capturing
    the whole live DOM a second time moments later; every subsequent
    call (recognize/re-resolve recovery, post-action observation) is a
    fresh live capture."""

    pending = [initial_capture] if initial_capture is not None else []

    def _provider():
        if pending:
            return pending.pop()
        return fresh_provider()

    return _provider


# QCC_EX01_FAMILIAR_FAMILY_CASCADE_STATE_V1: the Mercurio EX01 recognizer
# maps only the autorizacion/personales/presentador/notificacion r-tabs
# panels. With the REAL "Datos del familiar" panel (tab-datos_familiar)
# active it recognizes nothing, so every family cascade write was gated
# FUNCTIONAL_STATE_UNKNOWN. Only family controls (``_is_ex01_family_control``),
# only when that panel is the sole active one.
_FAMILY_CASCADE_FIELDS = frozenset({
    "reaCodigoProvinciaReagrupante",
    "reaCodigoMunicipioReagrupante",
    "reaCodigoLocalidadReagrupante",
})
_EX01_FAMILY_PANEL_ID = "tab-datos_familiar"
EX01_FAMILY_FUNCTIONAL_STATE = "EX01_FAMILY"


def _is_ex01_family_control(field_id):
    """QCC_EX01_R6_FAMILIAR_131: the historical preload wrote the ordinary
    family controls while their tab was hidden; that exception is not
    ported, so they are written on their own surface and need the same
    narrow family state as the cascade. Only ``rea*Reagrupante`` ids; the
    recognizer itself still requires the EX01 path and the sole active
    family panel (EX02 uses its own path and is unaffected)."""

    field_id = str(field_id or "")
    return field_id in _FAMILY_CASCADE_FIELDS or (
        field_id.startswith("rea") and field_id.endswith("Reagrupante")
    )


def _ex01_family_surface_recognizer(recognizer):
    """Mercurio recognizer plus the supported EX01 "Datos del familiar"
    surface. Never overrides a recognized state; absence or ambiguity of
    the active panel stays unknown (fail closed).

    QCC_EX01_R6_FAMILIAR_131: the base recognizer does not know the
    family panel, so "familiar + another panel active" used to come back
    as that other panel's state. On the EX01 path the family panel
    active together with any other panel is ambiguous: unknown."""

    from backend.automation.site_recognizers import mercurio as ex01

    def _recognize(snapshot):
        payload = ex01._snapshot_payload(snapshot)
        origin, pathname = ex01._page_origin_and_path(payload)
        if (origin not in (ex01.MERCURIO_REAL_ORIGIN, ex01.MERCURIO_LAB_ORIGIN,
                           ex01.MERCURIO_LAB_LOCALHOST_ORIGIN)
                or pathname != ex01.MERCURIO_EX01_NEW_REQUEST_PATH):
            return recognizer(snapshot)
        panels = {*ex01._EX01_ACTIVE_PANEL_STATES, _EX01_FAMILY_PANEL_ID}
        active = {
            str(ex01._element_field(element, "id") or "").strip()
            for element in ex01._elements(payload)
            if "r-tabs-state-active" in ex01._class_tokens(element)
        } & panels
        if _EX01_FAMILY_PANEL_ID in active and len(active) > 1:
            return None
        state = recognizer(snapshot)
        if state is not None:
            return state
        return EX01_FAMILY_FUNCTIONAL_STATE if active == {_EX01_FAMILY_PANEL_ID} else None

    return _recognize


def _postcondition_not_verified(result):
    """Downgrades an executed transition-trigger write whose own
    postcondition failed: the effect is unknown, never OK."""

    from dataclasses import replace

    from backend.automation.site_architecture.outcome_classification import (
        ACTION_DISPOSITION_EFFECT_UNKNOWN,
        OUTCOME_HUMAN_HANDOFF,
    )
    from backend.automation.site_architecture.state_aware_execution import (
        STATE_AWARE_POSTCONDITION_NOT_VERIFIED,
        STATE_AWARE_RESULT_HUMAN_HANDOFF,
    )

    return replace(
        result,
        disposition=ACTION_DISPOSITION_EFFECT_UNKNOWN,
        result_status=STATE_AWARE_RESULT_HUMAN_HANDOFF,
        outcome=OUTCOME_HUMAN_HANDOFF,
        reason=STATE_AWARE_POSTCONDITION_NOT_VERIFIED,
    )


def _governed_write(
    browser,
    *,
    action_kind,
    field_id,
    apply,
    session_dir=None,
    environment=None,
    idempotent=True,
    expects_state_transition=False,
    verify=None,
    already_satisfied=None,
):
    """Routes one presentation DOM write through the QCC V2
    state-aware execution engine.

    Authorization is bound to the ACTUAL live browser origin
    captured from the real DOM (never to a caller-constructed
    profile): an unrecognized origin, or a claimed ``environment``
    that contradicts the actual target, both fail closed before
    ``apply`` is ever invoked. ``apply`` performs the concrete DOM
    write (preserving its own value/event semantics) and is only
    ever called once the certified execution gate allows it.

    QCC_FILL_PERFORMANCE_NATIVE_CONTROLS_V1:

    - ``verify`` is the write's own postcondition (value/option/
      checked state read back from the live control). A write is only
      ``OK`` once it returns ``True``; "the gate allowed it and the
      executor did not raise" is never enough on its own.
    - Ordinary writes (``expects_state_transition=False``, the
      default) never pay a generic post-action full-DOM transition
      observation: ``verify`` replaces it. Writes explicitly declared
      as transition triggers keep the engine's full post-action
      observation, and ``verify`` is additionally enforced afterwards.
    - A target the governance snapshot itself reports as
      ``OFF_VIEWPORT`` (an ordinary control below the fold) is
      scrolled into view and re-captured, so the certified
      visible/enabled/interactable check is evaluated on the control
      as a human would see it -- never relaxed.

    QCC_FULL_MAPPER_FAST_PATH_V1: inside an open ``governed_section``
    an ordinary (non-transition INPUT_VALUE/SELECT/CHECKBOX/RADIO)
    write reuses the section's single full capture for origin binding
    and state recognition, and refreshes ONLY the target control's
    interaction from a targeted local probe before the unchanged gate
    is evaluated -- and only while the probe proves the same page and
    the same active surface. Anything else (non-ordinary write, page
    or surface change, unusable probe, inactive panel) takes a fresh
    full capture; any non-OK outcome invalidates the section capture.

    QCC_EX01_R6_POSTFORM: a canonical field of an audited mapper section
    (``preload_fields``) whose control is absent or sits on a surface
    that is not the active one is DEFERRED, never written: no hidden-tab
    write exception exists. ``already_satisfied`` is a read-only check
    of the expected live value: a control Mercurio already holds with it
    is verified without any write.
    """

    from backend.automation.site_architecture.outcome_classification import (
        ACTION_DISPOSITION_CONFIRMED,
    )
    from backend.automation.site_architecture.seleniumbase_executor import (
        build_seleniumbase_snapshot_provider,
        default_transient_error_classifier,
    )
    from backend.automation.site_architecture.site_target import (
        SiteTarget,
        SiteTargetMode,
    )
    from backend.automation.site_architecture.state_aware_execution import (
        STATE_AWARE_EXECUTION_BLOCKED_POLICY,
        ActionIntent,
        StateAwareExecutionRequest,
        execute_state_aware_action,
        with_local_target_interaction,
    )
    from backend.automation.site_policies.mercurio import (
        MERCURIO_SITE_CODE,
        build_mercurio_interaction_policy,
        build_mercurio_profile,
    )
    from backend.automation.site_recognizers.default_registry import (
        build_default_site_state_recognizer_registry,
    )

    section = _active_governed_section(browser)
    probe = None
    preload_contract = False

    if section is None:
        snapshot_provider = build_seleniumbase_snapshot_provider(browser)

        try:
            initial_capture = snapshot_provider()
        except Exception:
            initial_capture = None
    else:
        snapshot_provider = section.capture_fresh

        fast_path_eligible = (
            not expects_state_transition
            and action_kind in _SECTION_FAST_PATH_ACTION_KINDS
        )
        preload_contract = (
            fast_path_eligible
            and verify is not None
            and field_id in section.preload_fields
        )

        if not fast_path_eligible:
            # Non-ordinary / transition writes never reuse evidence.
            section.invalidate()

        if preload_contract:
            if section.capture is None:
                section.capture_fresh_or_none()
            probe = _probe_field_locally(browser, field_id)
            deferred = _preload_surface_outcome(
                section, probe, action_kind, field_id, session_dir,
                already_satisfied,
            )
            if deferred is not None:
                return deferred

        if fast_path_eligible and section.capture is not None:
            if probe is None:
                probe = _probe_field_locally(browser, field_id)
            if (
                preload_contract
                and already_satisfied is not None
                and section.proves_surface(probe)
                and _probe_write_blocked_on_surface(probe)
                and already_satisfied()
            ):
                return _already_satisfied_field(
                    section, field_id, action_kind, already_satisfied, session_dir
                )
            if not section.proves_surface(probe):
                # Page/surface change, unknown target or unusable
                # local readiness: recover with a fresh full capture.
                probe = None
                section.invalidate()
        else:
            probe = None

        if section.capture is None:
            section.capture_fresh_or_none()

        initial_capture = section.capture

    try:
        page = initial_capture.snapshot.get("page") or {}
        actual_url = str(page.get("url") or "")
        actual_origin = str(page.get("origin") or "")
    except Exception:
        initial_capture = None
        probe = None
        actual_url, actual_origin = "", ""

    actual_environment = (
        _classify_mercurio_environment_from_origin(actual_origin)
    )

    if actual_environment is None:
        result = _fail_closed_governed_result(
            action_kind=action_kind,
            field_id=field_id,
            reason="SITE_ENVIRONMENT_UNRECOGNIZED",
        )
        _log_governed_write(session_dir, field_id, action_kind, result)
        return result

    if environment is not None and environment != actual_environment:
        result = _fail_closed_governed_result(
            action_kind=action_kind,
            field_id=field_id,
            reason="ENVIRONMENT_MISMATCH",
        )
        _log_governed_write(session_dir, field_id, action_kind, result)
        return result

    profile = build_mercurio_profile(actual_environment)
    policy = build_mercurio_interaction_policy()

    target = SiteTarget(
        url=actual_url,
        mode=SiteTargetMode.MANAGED_EXECUTION,
        site_code=MERCURIO_SITE_CODE,
        environment=actual_environment,
    )

    registration = (
        build_default_site_state_recognizer_registry()
        .get_by_site_code(MERCURIO_SITE_CODE)
    )

    action_intent = ActionIntent(
        action_kind=action_kind,
        action_selector=f"#{field_id}",
        idempotent=idempotent,
        expects_state_transition=expects_state_transition,
    )

    state_recognizer = (
        registration.recognizer
        if registration is not None
        else None
    )
    if state_recognizer is not None and _is_ex01_family_control(field_id):
        state_recognizer = _ex01_family_surface_recognizer(state_recognizer)

    request = StateAwareExecutionRequest(
        target=target,
        profile=profile,
        policy=policy,
        action_intent=action_intent,
        state_recognizer=state_recognizer,
        provider="MERCURIO",
    )

    def _executor(*, action_kind, selector, frame_path="main", value=None):
        apply()

    if probe is not None and _probe_off_viewport(probe):
        try:
            js(browser, _field_scroll_into_view_js(field_id))
        except Exception:
            pass
        probe = _probe_field_locally(browser, field_id)
        if not section.proves_surface(probe):
            # Local readiness unusable after the scroll: the engine
            # evaluates a fresh full capture instead.
            probe = None
            initial_capture = None
            section.invalidate()

    if probe is not None:
        derived_capture = with_local_target_interaction(
            initial_capture, action_intent, probe
        )

        if derived_capture is None:
            # No local evidence for this control: never reuse the
            # section capture's (older) interaction for it.
            probe = None
            initial_capture = None
            section.invalidate()
        else:
            initial_capture = derived_capture
            section.reused_count += 1

    initial_interaction_state = (
        _snapshot_interaction_state(
            initial_capture.snapshot, action_kind, field_id
        )
        if initial_capture is not None
        else None
    )

    if probe is None and initial_interaction_state == "OFF_VIEWPORT":
        try:
            js(browser, _field_scroll_into_view_js(field_id))
        except Exception:
            pass
        # The pre-scroll capture no longer reflects the viewport: the
        # engine must evaluate a fresh one.
        initial_capture = None

    # Postcondition replaces the post-action transition observation
    # ONLY for ordinary (non-transition) writes.
    engine_postcondition = (
        verify
        if verify is not None and not expects_state_transition
        else None
    )

    result = execute_state_aware_action(
        request,
        snapshot_provider=_reusing_snapshot_provider(
            snapshot_provider, initial_capture
        ),
        executor=_executor,
        transient_error_classifier=(
            default_transient_error_classifier
        ),
        postcondition=engine_postcondition,
    )

    if (
        result.decision == STATE_AWARE_EXECUTION_BLOCKED_POLICY
        and result.gate_reason == "INTERACTION_POLICY_DENY"
        and action_kind in _DEPENDENCY_RETRY_ACTION_KINDS
    ):
        write_log(
            session_dir,
            "governed_write_dependency_wait "
            f"field={field_id} kind={action_kind} "
            f"initial_state={initial_interaction_state or '-'}: "
            "resolved live element not yet interactable, "
            "waiting boundedly for Mercurio dependency transition",
        )

        if _wait_for_dependency_readiness(
            browser, field_id, session_dir=session_dir
        ):
            # A dependency-revealed control may surface below the fold.
            try:
                js(browser, _field_scroll_into_view_js(field_id))
            except Exception:
                pass

            # Re-resolve/evaluate fresh: a brand-new live DOM snapshot
            # is captured inside execute_state_aware_action() itself,
            # it is never reused from the earlier, now-stale attempt.
            result = execute_state_aware_action(
                request,
                snapshot_provider=(
                    section.capture_fresh
                    if section is not None
                    else build_seleniumbase_snapshot_provider(browser)
                ),
                executor=_executor,
                transient_error_classifier=(
                    default_transient_error_classifier
                ),
                postcondition=engine_postcondition,
            )

    # QCC_EX01_R3: an executed write is only OK on observed evidence.
    # The engine's own CONFIRMED postcondition path already ran
    # ``verify``; any other OK (transition trigger, or an unchanged
    # fingerprint reported as merely EXECUTION_ATTEMPTED) still needs
    # ``verify`` -- and a form control without one is never OK.
    if _governed_outcome(result) == GOVERNED_OUTCOME_OK and (
        expects_state_transition
        or result.disposition != ACTION_DISPOSITION_CONFIRMED
        or (verify is None and action_kind in _SECTION_FAST_PATH_ACTION_KINDS)
    ):
        try:
            verified = verify is not None and bool(verify())
        except Exception:
            verified = False
        if not verified:
            result = _postcondition_not_verified(result)

    if section is not None and (
        expects_state_transition
        or _governed_outcome(result) != GOVERNED_OUTCOME_OK
    ):
        # Transition trigger, policy denial or failed postcondition:
        # the section capture can no longer be trusted.
        section.invalidate()

    if preload_contract and _governed_outcome(result) == GOVERNED_OUTCOME_OK:
        section.deferred.pop(field_id, None)
        mapper = _active_mapper_preload(browser)
        if mapper is not None:
            mapper.verified[field_id] = verify

    _log_governed_write(session_dir, field_id, action_kind, result)
    return result


def _defer_preloaded_field(section, field_id, action_kind, reason, session_dir):
    section.deferred[field_id] = reason
    result = _fail_closed_governed_result(
        action_kind=action_kind, field_id=field_id, reason=reason
    )
    _log_governed_write(session_dir, field_id, action_kind, result)
    return result


def _already_satisfied_field(section, field_id, action_kind, check, session_dir):
    """Nothing written: the live control already holds the expected
    value. Recorded as verified for this presentation (``check`` is the
    read-only revalidation used before any later rewrite)."""

    section.deferred.pop(field_id, None)
    mapper = _active_mapper_preload(section.browser)
    if mapper is not None:
        mapper.verified[field_id] = check
    write_log(
        session_dir,
        f"GOVERNED_WRITE_ALREADY_SATISFIED field={field_id} kind={action_kind}",
    )
    result = _already_satisfied_governed_result(
        action_kind=action_kind, field_id=field_id
    )
    _log_governed_write(session_dir, field_id, action_kind, result)
    return result


def _probe_signals_block_write(probe):
    """Readonly / aria-disabled / pointer-blocked: a human could not
    change this control either (REAL: certificate-managed presenter
    identity is ``readonly`` or ``pointer-events: none``)."""

    signals = probe.get("interaction_signals") or {}
    return (
        signals.get("readonly") is True
        or signals.get("aria_disabled") is True
        or str(signals.get("pointer_events") or "").strip().lower() == "none"
    )


def _probe_write_blocked_on_surface(probe):
    """A displayed control of the current surface that the gate will
    deny for a reason no dependency wait can fix."""

    return (
        probe.get("exists") is True
        and probe.get("panel_inactive") is not True
        and probe.get("visible") is True
        and (probe.get("disabled") is True or _probe_signals_block_write(probe))
    )


def _probe_surface_inactive(probe):
    """The control sits in an r-tabs panel that is not the displayed one."""

    return bool(probe.get("panel_id")) and (
        probe.get("panel_inactive") is True or probe.get("panel_active") is not True
    )


def _preload_surface_outcome(
    section, probe, action_kind, field_id, session_dir, already_satisfied
):
    """QCC_EX01_R6_POSTFORM: outcome for a canonical mapper control that
    is absent or not on the active surface, or ``None`` (ordinary gate).

    Never writes. On a surface not reached yet the control is deferred
    (retried once human navigation reaches it); on a reached (required)
    surface it fails closed. A live value that already proves the
    expected one is verified read-only. Only for a recognized origin and
    the page of the section capture: anything else takes the ordinary
    fail-closed path.
    """

    capture = section.capture
    try:
        origin = str((capture.snapshot.get("page") or {}).get("origin") or "")
    except Exception:
        return None
    if (
        _classify_mercurio_environment_from_origin(origin) is None
        or not section.matches_page(probe)
    ):
        return None

    required = field_id in section.required_fields

    if probe.get("exists") is not True:
        if required:
            result = _fail_closed_governed_result(
                action_kind=action_kind, field_id=field_id,
                reason="REQUIRED_ACTIVE_MISSING",
            )
            _log_governed_write(session_dir, field_id, action_kind, result)
            return result
        return _defer_preloaded_field(
            section, field_id, action_kind,
            GOVERNED_OUTCOME_DEFERRED_NOT_PRESENT, session_dir,
        )

    if not _probe_surface_inactive(probe):
        return None

    panel = probe.get("panel_id") or "-"

    if required:
        # The human reached this surface, yet its control is not on the
        # displayed one: never written, never deferred.
        reason = (
            "PRELOADED_TARGET_UNPROVEN"
            if _probe_signals_block_write(probe)
            else "REQUIRED_SURFACE_INACTIVE"
        )
        result = _fail_closed_governed_result(
            action_kind=action_kind, field_id=field_id, reason=reason
        )
        _log_governed_write(session_dir, field_id, action_kind, result)
        return result

    if already_satisfied is not None and already_satisfied():
        return _already_satisfied_field(
            section, field_id, action_kind, already_satisfied, session_dir
        )

    if probe.get("hidden_within_panel") is True or probe.get("disabled") is True:
        return _defer_preloaded_field(
            section, field_id, action_kind,
            GOVERNED_OUTCOME_DEFERRED_DEPENDENCY, session_dir,
        )

    if _probe_signals_block_write(probe):
        write_log(
            session_dir,
            f"PRELOADED_TARGET_UNPROVEN_DEFERRED field={field_id} "
            f"kind={action_kind} panel={panel}",
        )
        return _defer_preloaded_field(
            section, field_id, action_kind,
            GOVERNED_OUTCOME_DEFERRED_PRELOAD_UNPROVEN, session_dir,
        )

    write_log(
        session_dir,
        f"PRELOAD_SURFACE_INACTIVE_DEFERRED field={field_id} "
        f"kind={action_kind} panel={panel} writes=NO",
    )
    return _defer_preloaded_field(
        section, field_id, action_kind,
        GOVERNED_OUTCOME_DEFERRED_DEPENDENCY, session_dir,
    )


def set_checkbox(browser, field_id, value=True, session_dir=None):
    """Marca/desmarca checkboxes reales de Mercurio por id."""
    truthy = normalize(value) in {"SI", "S", "TRUE", "1", "YES", "Y"}
    applied = {}

    def _apply():
        script = f"""
        (function(){{
            const el = document.getElementById({json.dumps(field_id)});
            if (!el) return {{ ok: false, reason: 'NO_EXISTE' }};
            if ((el.type || '').toLowerCase() !== 'checkbox') {{
                return {{ ok: false, reason: 'NO_ES_CHECKBOX', type: el.type || '' }};
            }}
            el.checked = {json.dumps(bool(truthy))};
            if (el.checked && !el.value) el.value = 'true';
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            if (window.jQuery) window.jQuery(el).trigger('change');
            return {{ ok: true, checked: el.checked }};
        }})();
        """
        applied["result"] = js(browser, script)

    def _verify():
        return _verify_checked_state(
            browser,
            field_id,
            "CHECKBOX",
            truthy,
            apply_result=applied.get("result"),
            session_dir=session_dir,
        )

    result = _governed_write(
        browser,
        action_kind="CHECKBOX",
        field_id=field_id,
        apply=_apply,
        session_dir=session_dir,
        verify=_verify,
        already_satisfied=lambda: _checked_state_satisfied(
            browser, field_id, truthy, "checkbox"
        ),
    )

    return _governed_outcome(result)


def set_radio_checked(browser, field_id, checked=True, session_dir=None):
    """Marca un radio real de Mercurio por id, gobernado por QCC."""

    def _apply():
        script = f"""
        (function(){{
            const el = document.getElementById({json.dumps(field_id)});
            if (!el) return false;
            el.checked = {json.dumps(bool(checked))};
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            if (window.jQuery) window.jQuery(el).trigger('change');
            return true;
        }})();
        """
        js(browser, script)

    def _verify():
        return _verify_checked_state(
            browser, field_id, "RADIO", checked, session_dir=session_dir
        )

    result = _governed_write(
        browser,
        action_kind="RADIO",
        field_id=field_id,
        apply=_apply,
        session_dir=session_dir,
        verify=_verify,
        already_satisfied=lambda: _checked_state_satisfied(
            browser, field_id, checked, "radio"
        ),
    )

    return _governed_outcome(result)


def select_by_text_or_value(browser, field_id, value=None, text=None, session_dir=None, trace=None):
    """
    Selecciona un <select> por:
    1) value exacto si se aporta
    2) texto normalizado exacto
    3) texto normalizado contenido controlado

    Evita falsos positivos tipo MARRUECOS -> COSTA MARFIL,
    dando prioridad a coincidencia exacta normalizada.

    QCC_EX01_R11_FIX3_CASCADE: ``trace`` (dict opcional) recibe
    ``dispatched``: si el script aplicó una opción y despachó ``change``
    (un ALREADY_SATISFIED o un DENIED nunca lo despachan). Sin valores.
    """
    value = "" if value is None else str(value).strip()
    text = "" if text is None else str(text).strip()
    norm_text = normalize(text)
    applied = {}

    def _apply():
        script = f"""
    (function(){{
        const id = {json.dumps(field_id)};
        const wantedValue = {json.dumps(value)};
        const wantedText = {json.dumps(norm_text)};

        function norm(v) {{
            return (v || '').toString().trim().toUpperCase()
                .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '')
                .replace(/\\s+/g, ' ');
        }}

        const el = document.getElementById(id);
        if (!el) return {{ ok: false, reason: 'NO_EXISTE' }};

        let selected = '';

        if (wantedValue) {{
            for (const opt of el.options || []) {{
                if ((opt.value || '').toString() === wantedValue) {{
                    el.value = opt.value;
                    selected = opt.textContent || opt.innerText || opt.value;
                    break;
                }}
            }}
        }}

        if (!selected && wantedText) {{
            for (const opt of el.options || []) {{
                const optText = norm(opt.textContent || opt.innerText || '');
                if (optText === wantedText) {{
                    el.value = opt.value;
                    selected = opt.textContent || opt.innerText || opt.value;
                    break;
                }}
            }}
        }}

        if (!selected && wantedText) {{
            const candidates = [];
            for (const opt of el.options || []) {{
                const optText = norm(opt.textContent || opt.innerText || '');
                if (optText.includes(wantedText) || wantedText.includes(optText)) {{
                    candidates.push(opt);
                }}
            }}
            if (candidates.length === 1) {{
                const opt = candidates[0];
                el.value = opt.value;
                selected = opt.textContent || opt.innerText || opt.value;
            }}
        }}

        if (!selected) return {{
            ok: false,
            reason: 'NO_MATCH',
            wantedText,
            options: Array.from(el.options || []).map(o => [o.value, o.textContent]).slice(0, 120)
        }};

        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        if (window.jQuery) {{
            window.jQuery(el).trigger('change');
        }}
        return {{ ok: true, value: el.value, selected: selected }};
    }})();
    """
        applied["result"] = js(browser, script)

    def _verify():
        return _verify_select_option(
            browser, field_id, applied.get("result"), session_dir=session_dir
        )

    result = _governed_write(
        browser,
        action_kind="SELECT",
        field_id=field_id,
        apply=_apply,
        session_dir=session_dir,
        verify=_verify,
        already_satisfied=lambda: _select_option_satisfied(
            browser, field_id, value, norm_text
        ),
    )

    # QCC_EX01_R6_POSTFORM: a canonical mapper SELECT whose intended
    # option is not offered yet selected nothing: a dependency not
    # settled, deferred (the mapper waits for that option), never OK.
    section = _active_governed_section(browser)
    applied_result = applied.get("result")
    if trace is not None:
        trace["dispatched"] = (
            isinstance(applied_result, dict) and applied_result.get("ok") is True
        )
    if (
        section is not None
        and field_id in section.preload_fields
        and isinstance(applied_result, dict)
        and applied_result.get("reason") == "NO_MATCH"
    ):
        result = _defer_preloaded_field(
            section, field_id, "SELECT", GOVERNED_OUTCOME_DEFERRED_DEPENDENCY, session_dir
        )

    return _governed_outcome(result)


def wait_select_options(browser, field_id, min_options=2, timeout=4):
    condition = f"""
    (function(){{
        const el = document.getElementById({json.dumps(field_id)});
        return el && el.options && el.options.length >= {int(min_options)};
    }})()
    """
    return wait_for_js(browser, condition, timeout=timeout)


def select_municipio_localidad(browser, values, session_dir, prefix="ext"):
    """
    Secuencia correcta:
    provincia -> espera municipios -> municipio por texto -> espera localidades -> localidad por texto.

    QCC_EX01_RENOVACION_TITULAR_130_V1: esperas acotadas; cada select
    queda bajo su postcondición y la cascada se detiene en el primer
    resultado no OK (nunca continúa como si el anterior hubiera ido bien).

    QCC_EX01_R6_POSTFORM: bajo VOLCAR DATOS (preload activo) la cascada
    es la gobernada de ``_run_governed_cascade``.
    """
    prov_id = f"{prefix}CodigoProvincia" if prefix == "ext" else f"{prefix}CodigoProvinciaNotificacion"
    mun_id = f"{prefix}CodigoMunicipio" if prefix == "ext" else f"{prefix}CodigoMunicipioNotificacion"
    loc_id = f"{prefix}CodigoLocalidad" if prefix == "ext" else f"{prefix}CodigoLocalidadNotificacion"

    provincia_value = values.get(prov_id, "")
    provincia_text = values.get(prov_id + "_text", "")
    municipio_text = values.get(mun_id + "_text", "")
    localidad_text = values.get(loc_id + "_text", "") or municipio_text

    if _active_mapper_preload(browser) is not None:
        return _run_governed_cascade(browser, (
            (prov_id, provincia_value, provincia_text or provincia_value),
            (mun_id, "", municipio_text),
            (loc_id, "", localidad_text),
        ), session_dir)

    def _blocked(field_id, outcome):
        write_log(session_dir, f"Cascada detenida: campo={field_id} outcome={outcome}")
        return {"ok": False, "blocked_field": field_id, "blocked_outcome": outcome}

    if provincia_value or provincia_text:
        outcome = select_by_text_or_value(browser, prov_id, value=provincia_value, text=provincia_text or provincia_value, session_dir=session_dir)
        if _fill_section_blocked(outcome):
            return _blocked(prov_id, outcome)
        time.sleep(1.2)

    if municipio_text and field_exists(browser, mun_id):
        try:
            wait_select_options(browser, mun_id, min_options=2, timeout=4)
        except Exception as exc:
            write_log(session_dir, f"WAIT_FAIL municipio {mun_id}: {exc}")
        outcome = select_by_text_or_value(browser, mun_id, text=municipio_text, session_dir=session_dir)
        if _fill_section_blocked(outcome):
            return _blocked(mun_id, outcome)
        time.sleep(1.5)

    if localidad_text and field_exists(browser, loc_id):
        try:
            # En muchos Mercurio, localidad carga después de municipio.
            wait_select_options(browser, loc_id, min_options=2, timeout=2)
        except Exception as exc:
            write_log(session_dir, f"WAIT_FAIL localidad {loc_id}: {exc}")
        outcome = select_by_text_or_value(browser, loc_id, text=localidad_text, session_dir=session_dir)
        if _fill_section_blocked(outcome):
            return _blocked(loc_id, outcome)

    return {"ok": True, "blocked_field": None, "blocked_outcome": None}


def _wait_cascade_option(browser, field_id, text, session_dir):
    """QCC_EX01_R6_POSTFORM: waits (bounded, ABORT serviced under VOLCAR
    DATOS) for the intended cascade option instead of a fixed settle
    sleep. ``True`` = offered; ``False`` = the cascade must stop (option
    never offered, or ABORT recorded on the mapper)."""

    preload = _active_mapper_preload(browser)
    navigation = preload.navigation if preload is not None else {}
    condition = _preload_dependency_ready_js(field_id, "", text)
    result = _wait_for_js_with_qcc_control(
        browser,
        condition,
        session_dir,
        timeout=_CASCADE_OPTION_TIMEOUT_SECONDS,
        interval=_DEPENDENCY_READINESS_POLL_INTERVAL_SECONDS,
        action_client=navigation.get("action_client"),
        reporter=navigation.get("reporter"),
        abort_handler=navigation.get("abort_handler"),
        step="MAPPER_CASCADE",
    )
    if _is_qcc_aborted_result(result):
        if preload is not None:
            preload.aborted = result
        return False
    if result.get("ok"):
        return True
    # The verdict is the condition AT the deadline: the sliced wait stops
    # polling up to one interval (plus one operator-channel round trip)
    # early, and an option Mercurio loaded in that window is still ready.
    wait = "TIMEOUT"
    try:
        if js(browser, f"return !!({condition});"):
            return True
    except Exception:
        wait = "JS_ERROR"
    write_log(
        session_dir,
        f"WAIT_FAIL cascade {field_id} wait={wait} "
        f"timeout_s={_CASCADE_OPTION_TIMEOUT_SECONDS}",
    )
    return False


def _mapper_cascade_diagnostic_js(field_id, text, parent_id):
    """Read-only structural state of one cascade level. One line, no
    ``//`` (CDP contract). Returns ids/booleans/counts only."""

    return " ".join((
        _MAPPER_CASCADE_DIAGNOSTIC_MARKER,
        "(function(){",
        f"const ids = {json.dumps({'child': field_id, 'parent': parent_id or ''})};",
        _FAMILY_CASCADE_JS_NORM,
        f"const text = norm({json.dumps(str(text or ''))});",
        "const child = document.getElementById(ids.child);",
        "const parent = ids.parent ? document.getElementById(ids.parent) : null;",
        "const opts = child && child.options ? Array.from(child.options) : [];",
        "const useful = opts.filter(function(o){ return String(o.value || '') !== ''; });",
        "const exact = useful.filter(function(o){ return !!text && norm(o.textContent) === text; }).length;",
        "const partial = useful.filter(function(o){ const t = norm(o.textContent);"
        " return !!text && !!t && (t.includes(text) || text.includes(t)); }).length;",
        "return {",
        "child_exists: !!child, child_disabled: !!(child && child.disabled),",
        f"child_ready: !!child && !!({_one_line_js(_field_readiness_js(field_id))}),",
        "useful_options: useful.length,",
        "target_match: exact ? 'EXACT' : (partial === 1 ? 'PARTIAL' : (partial > 1 ? 'AMBIGUOUS' : 'NONE')),",
        "parent_exists: !!parent, parent_disabled: !!(parent && parent.disabled),",
        "parent_selected: !!(parent && parent.selectedIndex >= 0 && String(parent.value || '') !== ''),",
        "jquery_active: (window.jQuery && typeof window.jQuery.active === 'number') ? window.jQuery.active : null",
        "};",
        "})()",
    ))


def _diagnose_mapper_cascade_level(browser, field_id, text, parent_id, parent_event, session_dir):
    """QCC_EX01_R11_FIX3_CASCADE: why a dependent cascade level was not
    offered. Read-only; logs ids, booleans, counts and codes only.

    ``parent_event``: ``DISPATCHED`` (the governed parent write applied an
    option and fired ``change``), ``ALREADY_SATISFIED`` (verified without
    writing: no ``change``), ``NOT_WRITTEN`` (gate DENIED) or ``-``.
    No useful option after a parent nobody changed is an origin problem
    (Mercurio fixed the parent and never loaded its list); after a
    dispatched change it is the AJAX list that never arrived."""

    try:
        state = js(browser, _mapper_cascade_diagnostic_js(field_id, text, parent_id))
    except Exception:
        state = None
    state = state if isinstance(state, dict) else {}

    if not state:
        cause = "DIAGNOSTIC_UNAVAILABLE"
    elif not state.get("child_exists"):
        cause = "DEPENDENT_MISSING"
    elif state.get("parent_exists") and not state.get("parent_selected"):
        cause = "PARENT_NOT_SELECTED"
    elif not state.get("useful_options"):
        cause = (
            "DEPENDENT_OPTIONS_NOT_LOADED"
            if parent_event == "DISPATCHED"
            else "PARENT_FIXED_NO_DEPENDENT_LOAD"
        )
    elif state.get("target_match") == "AMBIGUOUS":
        cause = "TARGET_OPTION_AMBIGUOUS"
    elif state.get("target_match") not in ("EXACT", "PARTIAL"):
        cause = "TARGET_OPTION_MISSING"
    elif state.get("child_disabled"):
        cause = "DEPENDENT_DISABLED"
    elif not state.get("child_ready"):
        cause = "DEPENDENT_NOT_INTERACTABLE"
    else:
        cause = "TARGET_OPTION_LATE"

    write_log(
        session_dir,
        "MAPPER_CASCADE_DIAGNOSTIC "
        f"field={field_id} parent={parent_id or '-'} parent_event={parent_event} "
        f"parent_disabled={state.get('parent_disabled')} "
        f"parent_selected={state.get('parent_selected')} "
        f"child_exists={state.get('child_exists')} "
        f"child_disabled={state.get('child_disabled')} "
        f"child_ready={state.get('child_ready')} "
        f"useful_options={state.get('useful_options')} "
        f"target_match={state.get('target_match')} "
        f"jquery_active={state.get('jquery_active')} cause={cause}",
    )
    return cause


def _run_governed_cascade(browser, levels, session_dir):
    """Province -> municipality -> locality under VOLCAR DATOS.

    ``levels`` = ``((field_id, value, text), ...)`` parent first. Every
    select stays under its postcondition and the cascade stops at the
    first level that is not verified, with one exception (REAL evidence:
    a province Mercurio already fixed is NOT_INTERACTABLE): a parent the
    gate DENIED was never written, so the next level is attempted only
    once its own intended option is proven offered; the parent stays
    unverified and is reported; without a verified dependent level it
    fails closed. A dependent option never offered is a dependency not
    settled: ``DEFERRED_DEPENDENCY``, never OK.

    QCC_EX01_R11_FIX3_CASCADE: the parent's ``change`` is never forced
    (a fixed/disabled or already satisfied parent is not rewritten). A
    dependent option not offered within the bounded window carries a
    structural ``cause`` (see ``_diagnose_mapper_cascade_level``).
    """

    def _blocked(field_id, outcome, cause=None):
        write_log(
            session_dir,
            f"Cascada detenida: campo={field_id} outcome={outcome} cause={cause or '-'}",
        )
        result = {"ok": False, "blocked_field": field_id, "blocked_outcome": outcome}
        if cause:
            result["cause"] = cause
        return result

    unwritten_parent = None
    parent_id, parent_event = None, "-"

    for index, (field_id, value, text) in enumerate(levels):
        if not (value or text):
            continue
        trace = {}
        if index:
            if not field_exists(browser, field_id):
                continue
            if not _wait_cascade_option(browser, field_id, text, session_dir):
                preload = _active_mapper_preload(browser)
                if preload is not None and preload.aborted:
                    # PRESENTATION_ABORT wins: nothing more is read or written.
                    return _blocked(field_id, GOVERNED_OUTCOME_DEFERRED_DEPENDENCY)
                cause = _diagnose_mapper_cascade_level(
                    browser, field_id, text, parent_id, parent_event, session_dir
                )
                return _blocked(field_id, GOVERNED_OUTCOME_DEFERRED_DEPENDENCY, cause)
            outcome = select_by_text_or_value(
                browser, field_id, text=text, session_dir=session_dir, trace=trace
            )
        else:
            outcome = select_by_text_or_value(
                browser, field_id, value=value, text=text, session_dir=session_dir, trace=trace
            )
        if outcome == GOVERNED_OUTCOME_OK:
            event = "DISPATCHED" if trace.get("dispatched") else "ALREADY_SATISFIED"
        elif outcome == GOVERNED_OUTCOME_DENIED:
            event = "NOT_WRITTEN"
        else:
            event = "-"
        write_log(
            session_dir,
            f"MAPPER_CASCADE_LEVEL field={field_id} outcome={outcome} change_event={event}",
        )
        parent_id, parent_event = field_id, event
        if outcome == GOVERNED_OUTCOME_OK:
            if index:
                unwritten_parent = None
            continue
        if index == 0 and outcome == GOVERNED_OUTCOME_DENIED:
            unwritten_parent = field_id
            write_log(
                session_dir,
                f"CASCADE_PARENT_NOT_WRITTEN field={field_id} outcome={outcome} "
                "dependent_requires_intended_option=YES",
            )
            continue
        return _blocked(field_id, outcome)

    if unwritten_parent is not None:
        return _blocked(unwritten_parent, GOVERNED_OUTCOME_DENIED)

    return {"ok": True, "blocked_field": None, "blocked_outcome": None}


def load_datos_mercurio(path):
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"No existe datos_mercurio.json: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


FORMULARIO_OBJETIVO_LABELS = {
    "EX01": "EX01 - Residencia temporal no lucrativa",
    "EX02": "EX02 - Reagrupación familiar",
    "EX32": "EX32 - Residencia de familiar de ciudadano de la Unión",
}


MAPPER_CODIGO_LABELS = {
    "MERCURIO_EX01": "EX01 - Titular",
    "MERCURIO_EX01_FAMILIAR": "EX01 - Familiar",
    "MERCURIO_EX02": "EX02 - Reagrupación familiar",
    "MERCURIO_EX32": "EX32 - Familiar de ciudadano UE",
}


def get_tipo_formulario_objetivo(datos_mercurio):
    """
    Lee el formulario objetivo desde datos_mercurio.json.

    No automatiza clicks sobre el supuesto porque Mercurio cambia el DOM y
    una selección errónea podría iniciar un formulario incorrecto.
    El runner lo usa para guiar la pausa humana y dejar trazabilidad en log.
    """
    presentacion = datos_mercurio.get("presentacion", {}) if isinstance(datos_mercurio, dict) else {}
    tipo = str(presentacion.get("tipo_formulario_objetivo") or "").strip().upper()
    return tipo or "EX32"


def describe_tipo_formulario_objetivo(tipo_formulario_objetivo):
    tipo = str(tipo_formulario_objetivo or "").strip().upper()
    label = FORMULARIO_OBJETIVO_LABELS.get(tipo, "")
    return f"{tipo} ({label})" if label else (tipo or "NO DEFINIDO")


def get_mapper_codigo(datos_mercurio):
    """
    Lee el mapper interno desde datos_mercurio.json.

    Diferencia el modo de volcado sin alterar la selección humana del
    formulario/supuesto en Mercurio. Ejemplo:
    - tipo_formulario_objetivo=EX01
    - mapper_codigo=MERCURIO_EX01_FAMILIAR
    """
    presentacion = datos_mercurio.get("presentacion", {}) if isinstance(datos_mercurio, dict) else {}
    mapper_codigo = str(presentacion.get("mapper_codigo") or "").strip().upper()
    if mapper_codigo:
        return mapper_codigo

    # Fallback conservador para exports antiguos sin mapper_codigo.
    tipo = get_tipo_formulario_objetivo(datos_mercurio)
    return {
        "EX01": "MERCURIO_EX01",
        "EX02": "MERCURIO_EX02",
        "EX32": "MERCURIO_EX32",
    }.get(tipo, "")


def describe_mapper_codigo(mapper_codigo):
    mapper = str(mapper_codigo or "").strip().upper()
    label = MAPPER_CODIGO_LABELS.get(mapper, "")
    return f"{mapper} ({label})" if label else (mapper or "NO DEFINIDO")


def get_mercurio_mapper_mode(datos_mercurio):
    """
    Punto único de enrutamiento interno del runner.

    No decide ni selecciona el supuesto Mercurio. Solo informa al código
    qué variante de volcado debe aplicar después de la selección humana.
    """
    mapper_codigo = get_mapper_codigo(datos_mercurio)
    return {
        "mapper_codigo": mapper_codigo,
        "is_ex01": mapper_codigo == "MERCURIO_EX01",
        "is_ex01_familiar": mapper_codigo == "MERCURIO_EX01_FAMILIAR",
        "is_ex02": mapper_codigo == "MERCURIO_EX02",
        "is_ex32": mapper_codigo == "MERCURIO_EX32",
    }


def _handle_qcc_abort(
    action,
    session_dir,
    *,
    reporter=None,
    abort_handler=None,
    step="ABORTED",
):
    """ABORTAR PRESENTACIÓN: gobernado, nunca control directo aquí.

    Este módulo nunca decide cómo se cierra el navegador: delega en
    ``abort_handler`` (en la práctica ``MercurioConnector.close_browser``,
    ya certificado e idempotente) el ownership exacto de ESTA
    presentación ``qcc_assisted``. Nunca mata procesos Chrome de
    forma genérica ni fuerza la salida del propio proceso.
    """

    write_log(
        session_dir,
        "PRESENTATION_ABORT recibido "
        f"action_id={action.get('action_id')}",
    )

    closed = False

    if abort_handler is not None:
        try:
            closed = bool(abort_handler())
        except Exception as exc:
            write_log(
                session_dir,
                "PRESENTATION_ABORT: error en cierre "
                f"gobernado: {type(exc).__name__}",
            )

    qcc_report(
        reporter,
        "aborted",
        session_dir,
        message=(
            "Presentación abortada por el usuario"
            if closed
            else (
                "Presentación abortada; cierre de "
                "navegador no confirmado"
            )
        ),
    )

    return {
        "ok": False,
        "mode": "aborted",
        "label": step,
        "action": action,
        "browser_closed": closed,
    }


# QCC_OPERATOR_ACTION_CONSUMPTION_FIX_V1: root cause was
# QUEUE_TO_RUNTIME / PHASE_LIMITED_ACTION_CONSUMPTION -- the Bridge
# queued PRESENTATION_ABORT correctly, but the runtime only consumed
# actions inside the READY_TO_FILL / DOCUMENTS_READY waiters. Every
# operator-visible, non-terminal wait now goes through the ONE helper
# below, in bounded short slices, so ABORT is always serviceable.
QCC_CONTROL_CHECK_SLICE_SECONDS = 1.0
QCC_BLOCKED_CONTROL_TIMEOUT_SECONDS = 1800
QCC_BLOCKED_CONTROL_POLL_INTERVAL_SECONDS = 0.25


def _qcc_action_channel_available(action_client):
    return callable(getattr(action_client, "consume_next", None))


def _is_qcc_aborted_result(result):
    """True for a governed abort result, including the
    ``FILL_START_NOT_CONFIRMED`` wrapper that nests it under
    ``detail``."""

    if not isinstance(result, dict):
        return False

    if result.get("mode") == "aborted":
        return True

    detail = result.get("detail")

    return isinstance(detail, dict) and detail.get("mode") == "aborted"


def _service_qcc_operator_action(
    action_client,
    session_dir,
    *,
    reporter=None,
    abort_handler=None,
    step,
    expected_actions=(),
):
    """Consume at most ONE pending QCC operator action.

    Returns:
    - ``None`` when there is no client/no pending action, or the
      action is not expected in this phase (logged and discarded);
    - the governed ``_handle_qcc_abort`` result on PRESENTATION_ABORT;
    - the raw action dict when its name is in ``expected_actions``.

    Never creates a second transport: it only reuses the existing
    ``action_client.consume_next()``.
    """

    if not _qcc_action_channel_available(action_client):
        return None

    try:
        action = action_client.consume_next()
    except Exception as exc:
        write_log(
            session_dir,
            f"{step}: consumo de acción QCC omitido: "
            f"{type(exc).__name__}",
        )
        return None

    if not isinstance(action, dict):
        return None

    action_name = str(
        action.get(
            "action",
            "",
        )
    ).strip()

    if action_name == "PRESENTATION_ABORT":
        return _handle_qcc_abort(
            action,
            session_dir,
            reporter=reporter,
            abort_handler=abort_handler,
            step=step,
        )

    if action_name in expected_actions:
        return action

    write_log(
        session_dir,
        (
            f"{step}: acción inesperada "
            f"descartada {action_name or '-'}"
        ),
    )

    return None


def _wait_for_js_with_qcc_control(
    browser,
    condition_js,
    session_dir,
    *,
    timeout,
    interval,
    action_client=None,
    reporter=None,
    abort_handler=None,
    step,
    check_slice=QCC_CONTROL_CHECK_SLICE_SECONDS,
):
    """Same ``wait_for_js`` predicate, split into bounded short
    slices up to the same overall ``timeout``. Operator actions are
    serviced before every slice (ABORT has priority over one more
    check). Returns ``{"ok": True}``, the aborted result, or
    ``{"ok": False, "mode": "timeout", ...}``.
    """

    deadline = time.monotonic() + timeout
    last_error = None

    while True:
        control = _service_qcc_operator_action(
            action_client,
            session_dir,
            reporter=reporter,
            abort_handler=abort_handler,
            step=step,
        )

        if _is_qcc_aborted_result(control):
            return control

        remaining = deadline - time.monotonic()

        if remaining <= 0:
            return {
                "ok": False,
                "mode": "timeout",
                "error": repr(
                    last_error
                    or TimeoutError(
                        "Timeout esperando condición JS"
                    )
                ),
            }

        try:
            wait_for_js(
                browser,
                condition_js,
                timeout=min(check_slice, remaining),
                interval=interval,
            )
            return {"ok": True}
        except Exception as exc:
            last_error = exc


def wait_for_qcc_operator_control(
    action_client,
    session_dir,
    reporter=None,
    *,
    abort_handler=None,
    step,
    timeout=QCC_BLOCKED_CONTROL_TIMEOUT_SECONDS,
    poll_interval=QCC_BLOCKED_CONTROL_POLL_INTERVAL_SECONDS,
):
    """Bounded QCC operator-control wait for a blocked/not-OK phase
    whose presentation runtime/browser is still owned and active.

    Keeps PRESENTATION_ABORT serviceable instead of falling straight
    into the hidden console menu. Returns ``None`` without a client,
    the aborted result, or ``operator_control_timeout``.
    """

    if not _qcc_action_channel_available(action_client):
        return None

    write_log(
        session_dir,
        f"{step}: esperando PRESENTATION_ABORT desde QCC "
        f"(máx. {timeout}s)",
    )

    deadline = time.monotonic() + timeout

    while True:
        control = _service_qcc_operator_action(
            action_client,
            session_dir,
            reporter=reporter,
            abort_handler=abort_handler,
            step=step,
        )

        if _is_qcc_aborted_result(control):
            return control

        if time.monotonic() >= deadline:
            write_log(
                session_dir,
                f"{step}: espera de control QCC agotada",
            )
            return {
                "ok": False,
                "mode": "operator_control_timeout",
                "label": step,
            }

        time.sleep(
            poll_interval
        )


def _one_line_js(expression):
    """QCC_FULL_MAPPER_FAST_PATH_V1: same CDP ``evaluate`` contract as
    ``_field_readiness_js``. ``wait_for_js`` wraps the predicate as
    ``return !!(<expr>);`` and SeleniumBase only strips that ``return``
    when it sits on the LAST line, so a multi-line predicate (e.g. the
    presenter -> notification and final documents screens) raised
    ``Illegal return statement`` on every poll and could only ever time
    out. Collapsing whitespace is only safe without ``//`` comments, so
    such an expression is returned unchanged."""

    expression = str(expression or "")

    if "//" in expression:
        return expression

    return " ".join(expression.split())


def wait_for_human_navigation(
    browser,
    session_dir,
    label,
    ready_js,
    timeout=300,
    interval=0.5,
    fallback_prompt=None,
    qcc_reporter=None,
    qcc_step="HUMAN_NAVIGATION",
    qcc_progress=0,
    action_client=None,
    abort_handler=None,
    allow_console_fallback=True,
):
    """
    Espera a que el usuario pulse CONTINUAR manualmente en Mercurio y a que
    la pantalla destino esté lista.

    No automatiza el click de CONTINUAR: solo observa el DOM.
    Si no se detecta la pantalla en plazo, conserva el fallback por ENTER.

    Con ``action_client`` QCC la espera ocurre en intervalos cortos
    acotados, atendiendo PRESENTATION_ABORT entre ellos, y el
    fallback oculto por ENTER nunca se usa como mecanismo de control:
    un timeout devuelve ``human_navigation_timeout``.

    QCC_EX01_RENOVACION_TITULAR_130_V1: ``allow_console_fallback=False``
    elimina también el fallback ENTER sin QCC; un timeout devuelve
    ``human_navigation_timeout`` (fail-closed).
    """
    ready_js = _one_line_js(ready_js)

    print()
    print("=" * 80)
    print(f"PAUSA HUMANA ASISTIDA: {label}")
    print("Pulsa MANUALMENTE CONTINUAR en Mercurio.")
    print("No hace falta volver a CMD si la pantalla destino se detecta correctamente.")
    print("=" * 80)
    write_log(session_dir, f"Espera humana asistida iniciada: {label}")

    qcc_report(
        qcc_reporter,
        "waiting_user",
        session_dir,
        step=qcc_step,
        progress=qcc_progress,
        message=(
            f"Acción manual requerida: {label}"
        ),
    )

    qcc_controlled = _qcc_action_channel_available(action_client)

    if qcc_controlled:
        wait_result = _wait_for_js_with_qcc_control(
            browser,
            ready_js,
            session_dir,
            timeout=timeout,
            interval=interval,
            action_client=action_client,
            reporter=qcc_reporter,
            abort_handler=abort_handler,
            step=qcc_step,
        )

        if _is_qcc_aborted_result(wait_result):
            return wait_result

        if not wait_result.get("ok"):
            write_log(
                session_dir,
                f"Espera humana asistida timeout (QCC): {label}",
            )
            return {
                "ok": False,
                "mode": "human_navigation_timeout",
                "label": label,
                "error": wait_result.get("error"),
            }

    try:
        if not qcc_controlled:
            wait_for_js(browser, ready_js, timeout=timeout, interval=interval)
        write_log(session_dir, f"Espera humana asistida OK: {label}")
        print(f"[OK] Pantalla detectada: {label}")

        qcc_report(
            qcc_reporter,
            "user_action_detected",
            session_dir,
            step=qcc_step,
            progress=qcc_progress,
            message=(
                f"Acción manual detectada: {label}"
            ),
        )

        qcc_report(
            qcc_reporter,
            "resuming",
            session_dir,
            step=qcc_step,
            progress=qcc_progress,
            message=(
                f"Reanudando tras: {label}"
            ),
        )

        return {
            "ok": True,
            "mode": "human_dom_detected",
            "label": label,
        }
    except Exception as exc:
        write_log(session_dir, f"Espera humana asistida timeout/fallo: {label}: {repr(exc)}")
        if not allow_console_fallback:
            return {
                "ok": False,
                "mode": "human_navigation_timeout",
                "label": label,
                "error": repr(exc),
            }
        print()
        print("=" * 80)
        print(f"No se ha podido detectar automáticamente: {label}")
        print("Si ya has avanzado correctamente en Mercurio, usa el fallback por consola.")
        print("=" * 80)
        input(fallback_prompt or "Pulsa ENTER para continuar...")
        try:
            wait_for_js(browser, ready_js, timeout=10, interval=0.5)
            write_log(session_dir, f"Fallback ENTER confirmado por DOM: {label}")

            qcc_report(
                qcc_reporter,
                "user_action_detected",
                session_dir,
                step=qcc_step,
                progress=qcc_progress,
                message=(
                    f"Acción manual confirmada: {label}"
                ),
            )

            qcc_report(
                qcc_reporter,
                "resuming",
                session_dir,
                step=qcc_step,
                progress=qcc_progress,
                message=(
                    f"Reanudando tras fallback: {label}"
                ),
            )

            return {
                "ok": True,
                "mode":
                    "human_enter_fallback_confirmed",
                "label": label,
            }
        except Exception as confirm_exc:
            write_log(session_dir, f"Fallback ENTER sin confirmación DOM: {label}: {repr(confirm_exc)}")
            return {
                "ok": False,
                "mode": "human_enter_fallback_not_confirmed",
                "label": label,
                "error": repr(confirm_exc),
            }


MERCURIO_MODE_ACCESS_READY_JS = r"""
(function(){
    return (
        window.location.pathname
            .endsWith('/mercurio/modoAcceso.html')
    );
})()
"""



def step_continuar_inicial(
    browser,
    session_dir,
    reporter=None,
):
    """
    Entrada inicial Mercurio.

    Paso seguro ya validado históricamente:
    CONTINUAR se ejecuta automáticamente mediante
    la función nativa de Mercurio.
    """
    print("[1] Pantalla inicial -> Continuar automático")
    write_log(
        session_dir,
        "Pantalla inicial -> continuar('INI')",
    )

    qcc_report(
        reporter,
        "automating",
        session_dir,
        step="CONTINUE_FROM_START",
        progress=5,
        message="Continuando desde inicio de Mercurio",
    )

    wait_for_js(
        browser,
        "typeof continuar === 'function'",
    )

    js(
        browser,
        "continuar('INI');",
    )

    return {
        "ok": True,
        "mode": "automated_js",
        "label": "CONTINUE_FROM_START",
    }


def pause_certificado(
    browser,
    session_dir,
    reporter=None,
    action_client=None,
    abort_handler=None,
):
    """
    Modo de acceso mixto.

    AUTOMÁTICO:
    - CONTINUAR ABOGACÍA.

    HUMANO:
    - selección del certificado digital nativo.

    Tras seleccionar el certificado, el runner
    detecta automáticamente entradaMercurio.html.
    """
    print("[2] Modo acceso -> Continuar Abogacía automático")

    write_log(
        session_dir,
        "Modo acceso -> validarYEnviar('AB')",
    )

    qcc_report(
        reporter,
        "automating",
        session_dir,
        step="CERTIFICATE_ACCESS",
        progress=10,
        message="Abriendo selección de certificado",
    )

    wait_for_js(
        browser,
        "typeof validarYEnviar === 'function'",
    )

    js(
        browser,
        "validarYEnviar('AB');",
    )

    print()
    print("=" * 80)
    print("PAUSA HUMANA: selecciona el certificado digital.")
    print(
        "El script continuará automáticamente "
        "al detectar Opciones disponibles."
    )
    print("=" * 80)

    write_log(
        session_dir,
        "Pausa humana: selección certificado",
    )

    return wait_for_human_navigation(
        browser,
        session_dir,
        "Seleccionar certificado digital",
        (
            "window.location.pathname"
            ".endsWith('/mercurio/entradaMercurio.html')"
            " && typeof mostrarOpcion === 'function'"
        ),
        timeout=300,
        fallback_prompt=(
            "Pulsa ENTER cuando Mercurio esté "
            "en Opciones disponibles..."
        ),
        qcc_reporter=reporter,
        qcc_step="CERTIFICATE_SELECTION",
        qcc_progress=12,
        action_client=action_client,
        abort_handler=abort_handler,
    )

MERCURIO_ENTRY_OPTIONS_VISIBLE_JS = r"""
(function(){
    function visible(el) {
        if (!el) return false;

        const style = window.getComputedStyle(el);

        return (
            style.display !== 'none'
            && style.visibility !== 'hidden'
            && el.getClientRects().length > 0
        );
    }

    return (
        visible(
            document.getElementById('bscIniciales')
        )
        && visible(
            document.getElementById('provincia')
        )
    );
})()
"""


MERCURIO_MODEL_SELECTION_READY_JS = r"""
(function(){
    function visible(el) {
        if (!el) return false;

        const style = window.getComputedStyle(el);

        return (
            style.display !== 'none'
            && style.visibility !== 'hidden'
            && el.getClientRects().length > 0
        );
    }

    const model = document.querySelector(
        'input[name="datosForL"]'
    );

    const warning = document.querySelector(
        '.mdCer'
    );

    return (
        visible(model)
        && !visible(warning)
    );
})()
"""



def step_presentar_nueva_solicitud(
    browser,
    provincia_codigo,
    session_dir,
    tipo_formulario_objetivo="",
    reporter=None,
):
    """
    Pre-form de nueva solicitud.

    Recupera el comportamiento estable anterior
    a 6affadc:

    AUTOMÁTICO:
    - mostrar opciones;
    - seleccionar BI;
    - seleccionar provincia;
    - CONTINUAR;
    - cerrar aviso Mercurio.

    La selección del supuesto concreto permanece
    fuera de esta función y continúa siendo humana.
    """
    tipo_desc = describe_tipo_formulario_objetivo(
        tipo_formulario_objetivo
    )

    print(
        "[3] Opciones disponibles -> "
        "Presentar nueva solicitud automático"
    )
    print(
        f"Formulario Mercurio objetivo: {tipo_desc}"
    )

    write_log(
        session_dir,
        f"Formulario Mercurio objetivo: {tipo_desc}",
    )

    qcc_report(
        reporter,
        "automating",
        session_dir,
        step="OPEN_PRESENTATION_OPTIONS",
        progress=18,
        message="Abriendo opciones de presentación",
    )

    wait_for_js(
        browser,
        "typeof mostrarOpcion === 'function'",
    )

    js(
        browser,
        "mostrarOpcion();",
    )

    print(
        "[4] Seleccionando BI + provincia "
        f"{provincia_codigo}"
    )

    wait_for_js(
        browser,
        (
            "document.getElementById('bscIniciales')"
            " && document.getElementById('provincia')"
        ),
    )

    radio_outcome = set_radio_checked(
        browser,
        "bscIniciales",
        checked=True,
        session_dir=session_dir,
    )

    provincia_selector_field = "provincia"

    def _apply_provincia_inicial():
        js(
            browser,
            f"""
            (function(){{
                const provincia =
                    document.getElementById(
                        {json.dumps(provincia_selector_field)}
                    );
                if (!provincia) return false;

                provincia.value = {
                    json.dumps(
                        str(provincia_codigo)
                    )
                };

                provincia.dispatchEvent(
                    new Event(
                        'change',
                        {{ bubbles: true }}
                    )
                );
                return true;
            }})();
            """,
        )

    def _verify_provincia_inicial():
        return _verify_select_option(
            browser,
            provincia_selector_field,
            {"ok": True, "value": str(provincia_codigo)},
            session_dir=session_dir,
        )

    provincia_result = _governed_write(
        browser,
        action_kind="SELECT",
        field_id=provincia_selector_field,
        apply=_apply_provincia_inicial,
        session_dir=session_dir,
        verify=_verify_provincia_inicial,
    )

    provincia_outcome = _governed_outcome(provincia_result)

    js(
        browser,
        """
        (function(){
            if (
                typeof establecerCodProvincia
                === 'function'
            ) {
                establecerCodProvincia();
            }
        })();
        """,
    )

    governed_ok = (
        radio_outcome == GOVERNED_OUTCOME_OK
        and provincia_outcome == GOVERNED_OUTCOME_OK
    )

    if not governed_ok:
        write_log(
            session_dir,
            "Selección BI/provincia inicial bloqueada: "
            f"radio={radio_outcome} provincia={provincia_outcome}",
        )

    print(
        "[5] Modal opciones -> CONTINUAR automático"
    )

    qcc_report(
        reporter,
        "automating",
        session_dir,
        step="CONTINUE_TO_MODEL_SELECTION",
        progress=24,
        message="Accediendo a selección de modelo",
    )

    wait_for_js(
        browser,
        "typeof irOpcion === 'function'",
    )

    js(
        browser,
        "irOpcion();",
    )

    print(
        "[6] Aviso Mercurio -> cierre automático"
    )

    try:
        wait_for_js(
            browser,
            "document.querySelector('.mdCer')",
            timeout=15,
            interval=0.25,
        )

        click_js(
            browser,
            ".mdCer",
        )

    except Exception as exc:
        write_log(
            session_dir,
            (
                "Aviso Mercurio no encontrado "
                "o ya cerrado: "
                f"{type(exc).__name__}"
            ),
        )

    # No esperar aquí a que la selección de modelo
    # permanezca visible.
    #
    # Mercurio puede avanzar inmediatamente al EX01
    # mientras este paso termina. El flujo histórico
    # continuaba directamente hacia pause_supuesto()
    # y posteriormente fill_datos_extranjero().
    try:
        html_path = save_page_source(
            browser,
            session_dir,
            label="despues_aviso_mercurio",
        )

        write_log(
            session_dir,
            (
                "HTML guardado tras aviso Mercurio: "
                f"{html_path}"
            ),
        )

    except Exception as exc:
        write_log(
            session_dir,
            (
                "No se pudo guardar HTML tras aviso: "
                f"{repr(exc)}"
            ),
        )

    return {
        "ok": governed_ok,
        "mode": "automated_preform",
        "label": "MODEL_SELECTION_READY",
        "radio_outcome": radio_outcome,
        "provincia_outcome": provincia_outcome,
    }

EX01_READINESS_TIMEOUT_SECONDS = 300
EX01_READINESS_POLL_INTERVAL_SECONDS = 0.5

# QCC_OPERATOR_ACTION_CONSUMPTION_FIX_V1 -- OBSERVABILITY ONLY: the
# structural predicates evaluated by ``_field_readiness_js``, per
# canonical write field, so the next REAL smoke shows exactly which
# one stays false. Every probe is a ``return !!(...)`` boolean: it can
# never return field contents or any personal data.
EX01_READINESS_DIAGNOSTIC_PROBES = (
    ("disabled", "el.disabled"),
    ("display_none", "window.getComputedStyle(el).display === 'none'"),
    (
        "visibility_hidden",
        "window.getComputedStyle(el).visibility === 'hidden'",
    ),
    ("aria_hidden", "el.getAttribute('aria-hidden') === 'true'"),
    ("hidden_ancestor", "el.closest('[style*=\"display: none\"]')"),
    (
        "zero_size",
        "!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)",
    ),
)

EX01_READINESS_DIAGNOSTIC_KEYS = (
    ("field", "exists")
    + tuple(key for key, _expr in EX01_READINESS_DIAGNOSTIC_PROBES)
    + ("interactable",)
)


def _ex01_diagnostic_probe_js(field_id, expression):
    return (
        "return !!((function(){ "
        f"const el = document.getElementById({json.dumps(field_id)}); "
        f"return !!el && !!({expression}); "
        "})());"
    )


def _ex01_diagnostic_probe(browser, field_id, expression):
    try:
        return bool(js(browser, _ex01_diagnostic_probe_js(field_id, expression)))
    except Exception:
        return None


def _ex01_readiness_diagnostic(
    browser, datos_mercurio, session_dir, phase="timeout"
):
    """Value-free structural diagnostic for every canonical write
    field: one boolean per predicate of ``_field_readiness_js``.
    Fail-open: a probe that cannot be evaluated is reported ``None``
    and an unreadable DOM yields ``[]``.

    QCC_EX01_READINESS_IMMEDIATE_DIAGNOSTIC_V1: ``phase`` only tags
    the log line (``initial`` / ``timeout``); it never alters probes.
    """

    diagnostic = []

    for field_id in _ex01_personal_canonical_write_fields(datos_mercurio):
        exists = _ex01_diagnostic_probe(browser, field_id, "true")

        if exists is None:
            write_log(
                session_dir,
                f"EX01_READINESS_DIAGNOSTIC phase={phase} "
                f"field={field_id} no disponible",
            )
            return []

        entry = {"field": field_id, "exists": exists}

        if exists:
            for key, expression in EX01_READINESS_DIAGNOSTIC_PROBES:
                entry[key] = _ex01_diagnostic_probe(
                    browser, field_id, expression
                )

            entry["interactable"] = not any(
                entry[key] is not False
                for key, _expr in EX01_READINESS_DIAGNOSTIC_PROBES
            )

        write_log(
            session_dir,
            f"EX01_READINESS_DIAGNOSTIC phase={phase} "
            + " ".join(f"{key}={value}" for key, value in entry.items()),
        )

        diagnostic.append(entry)

    return diagnostic


_JS_ERROR_CLASS_RE = re.compile(
    r"\b(SyntaxError|ReferenceError|TypeError|RangeError|EvalError)\b"
)


def _ex01_readiness_predicate_probe(browser, condition_js, session_dir, phase):
    """QCC_EX01_R11_FIX2 -- OBSERVABILITY ONLY: evaluates the readiness
    predicate ONCE exactly as ``wait_for_js`` sends it and logs
    ``true``/``false``/``error:<Exc>[:<JsErrorClass>]``, so an
    evaluation error is never confused with a genuine ``false``. Only
    exception/JS error class names are logged, never messages, field
    values or the page. Never decides readiness."""

    try:
        outcome = "true" if js(browser, f"return !!({condition_js});") else "false"
    except Exception as exc:
        outcome = f"error:{type(exc).__name__}"
        match = _JS_ERROR_CLASS_RE.search(str(exc))
        if match:
            outcome += f":{match.group(1)}"

    write_log(
        session_dir,
        f"EX01_READINESS_PREDICATE phase={phase} result={outcome}",
    )

    return outcome


def _wait_for_ex01_personal_readiness(
    browser,
    session_dir,
    datos_mercurio,
    reporter=None,
    timeout=EX01_READINESS_TIMEOUT_SECONDS,
    interval=EX01_READINESS_POLL_INTERVAL_SECONDS,
    action_client=None,
    abort_handler=None,
):
    """EX01_READY_CONDITION: bounded, field-level readiness check.

    QCC_ASSISTED_OPERATOR_CONTROLS_V1: invoked from ``run_auto``
    AFTER the operator has already pressed VOLCAR DATOS (QCC
    reported READY_TO_FILL as soon as ``pause_supuesto`` detected the
    EX01 candidate screen -- it no longer waits here first). This
    wait is purely automatic and bounded: it must never fall back to
    the CMD ENTER prompt, and must never report
    ``requires_user_action=True``. It governs only WHEN the already
    explicitly authorized fill may start, never WHETHER to fill.

    QCC_OPERATOR_ACTION_CONSUMPTION_FIX_V1: the same predicate is
    checked in bounded short slices up to the same overall timeout,
    servicing PRESENTATION_ABORT between them.
    """

    write_log(session_dir, "QCC_FILL_READINESS_START step=EX01_READINESS")

    qcc_report(
        reporter,
        "automating",
        session_dir,
        step="EX01_READINESS",
        progress=30,
        message="Comprobando automáticamente Datos del extranjero/a",
    )

    # QCC_EX01_READINESS_IMMEDIATE_DIAGNOSTIC_V1 -- OBSERVABILITY ONLY:
    # one value-free structural snapshot up front, so a REAL smoke
    # does not have to wait for the timeout to see which field blocks.
    # Fail-open and result discarded: the readiness predicate, timeout
    # and polling below are unchanged.
    write_log(session_dir, "EX01_READINESS_START")
    _ex01_readiness_diagnostic(
        browser,
        datos_mercurio,
        session_dir,
        phase="initial",
    )

    ready_js = _ex01_personal_ready_js(datos_mercurio)
    _ex01_readiness_predicate_probe(browser, ready_js, session_dir, "initial")

    wait_result = _wait_for_js_with_qcc_control(
        browser,
        ready_js,
        session_dir,
        timeout=timeout,
        interval=interval,
        action_client=action_client,
        reporter=reporter,
        abort_handler=abort_handler,
        step="EX01_READINESS",
    )

    if _is_qcc_aborted_result(wait_result):
        return wait_result

    if not wait_result.get("ok"):
        write_log(
            session_dir,
            "EX01_READINESS_TIMEOUT: TimeoutError",
        )
        _ex01_readiness_predicate_probe(browser, ready_js, session_dir, "timeout")
        write_log(session_dir, "QCC_FILL_READINESS_FAIL step=EX01_READINESS")
        return {
            "ok": False,
            "mode": "ex01_readiness_timeout",
            "label": "Datos del extranjero/a",
            "error": wait_result.get("error"),
            "diagnostic": _ex01_readiness_diagnostic(
                browser,
                datos_mercurio,
                session_dir,
                phase="timeout",
            ),
        }

    write_log(session_dir, "EX01_READY")
    write_log(session_dir, "QCC_FILL_READINESS_PASS step=EX01_READINESS")

    qcc_report(
        reporter,
        "resuming",
        session_dir,
        step="EX01_READINESS",
        progress=30,
        message="Datos del extranjero/a lista",
    )

    return {
        "ok": True,
        "mode": "ex01_readiness_automatic",
        "label": "Datos del extranjero/a",
    }


def pause_supuesto(
    browser,
    session_dir,
    tipo_formulario_objetivo="",
    reporter=None,
    datos_mercurio=None,
    action_client=None,
    abort_handler=None,
):
    """
    Único paso humano restante de este flujo: el usuario selecciona en
    Mercurio el EX01/supuesto correcto. El hand-off humano termina en
    cuanto la pantalla candidata de Datos del extranjero/a se detecta
    en el DOM (EX01_DETECTED/EX01_CANDIDATE_DETECTED).

    QCC_ASSISTED_OPERATOR_CONTROLS_V1: a partir de aquí la presentación
    es SEMI-AUTOMÁTICA, no automática. Esta función ya NO espera a
    EX01_READY (comprobación de interactuabilidad en vivo de 300s):
    ese bounded wait de nivel de campo se conserva, pero se mueve al
    momento del propio comando VOLCAR DATOS
    (``_wait_for_ex01_personal_readiness``, invocado desde
    ``run_auto`` justo antes de ``fill_datos_extranjero``). Esta
    función devuelve el control en cuanto detecta la pantalla
    candidata, para que QCC pueda mostrar READY_TO_FILL de inmediato
    y el operador decida cuándo volcar los datos.
    """
    tipo_desc = describe_tipo_formulario_objetivo(tipo_formulario_objetivo)
    mapper_mode = get_mercurio_mapper_mode(datos_mercurio)
    print()
    print("=" * 80)
    print("PAUSA HUMANA: selecciona manualmente el supuesto concreto.")
    print(f"FORMULARIO OBJETIVO SEGÚN ERP: {tipo_desc}")
    if mapper_mode.get("is_ex01"):
        print(f"SUPUESTO OBJETIVO: {EX01_RENOVACION_TITULAR_LABEL}")
    print()
    print("Regla de seguridad:")
    print("- Selecciona en Mercurio el supuesto/formulario que corresponda a ese objetivo.")
    print("- Si Mercurio muestra otra cosa o tienes dudas, NO continúes y guarda HTML.")
    print()
    print("El script continuará automáticamente cuando Mercurio tenga lista la pantalla de Datos del extranjero/a.")
    print("=" * 80)
    write_log(session_dir, f"Pausa humana supuesto. Formulario objetivo={tipo_desc}")

    if mapper_mode.get("is_ex02"):
        # EX02's first screen after this pause is Datos del
        # reagrupante, not the EX01 personal-data surface: detection
        # stays existence-based here, unchanged by this fix.
        return wait_for_human_navigation(
            browser,
            session_dir,
            "Datos del extranjero/a",
            EX01_PERSONAL_CANDIDATE_DETECTED_JS,
            timeout=300,
            fallback_prompt="Pulsa ENTER cuando estés en Datos del extranjero/a...",
            qcc_reporter=reporter,
            qcc_step="PROCEDURE_SELECTION",
            qcc_progress=30,
            action_client=action_client,
            abort_handler=abort_handler,
        )

    if mapper_mode.get("is_ex01"):
        # QCC_EX01_RENOVACION_TITULAR_130_V1: the human picks the
        # supuesto and presses CONTINUAR; the runner waits for the
        # concrete Datos del extranjero/a panel to be the sole active
        # one (presence of ext* nodes alone is not that screen), with
        # no ENTER fallback, then decides identity from a fresh live
        # read -- never from an earlier capture.
        write_log(session_dir, "EX01_TITULAR_SURFACE_CHECK_STARTED")

        surface_result = wait_for_human_navigation(
            browser,
            session_dir,
            "Datos del extranjero/a",
            EX01_TITULAR_PERSONAL_SURFACE_JS,
            timeout=300,
            allow_console_fallback=False,
            qcc_reporter=reporter,
            qcc_step="PROCEDURE_SELECTION",
            qcc_progress=30,
            action_client=action_client,
            abort_handler=abort_handler,
        )

        if not surface_result.get("ok"):
            return surface_result

        identity_result = _verify_ex01_renovacion_titular_identity(
            browser,
            session_dir,
            phase="PROCEDURE_SELECTION",
        )

        if not identity_result.get("ok"):
            return identity_result

        write_log(session_dir, "EX01_CANDIDATE_DETECTED")

        return surface_result

    write_log(session_dir, "EX01_DETECTED_CANDIDATE_CHECK_STARTED")

    candidate_result = wait_for_human_navigation(
        browser,
        session_dir,
        "Datos del extranjero/a",
        EX01_PERSONAL_CANDIDATE_DETECTED_JS,
        timeout=300,
        fallback_prompt="Pulsa ENTER cuando estés en Datos del extranjero/a...",
        qcc_reporter=reporter,
        qcc_step="PROCEDURE_SELECTION",
        qcc_progress=30,
        action_client=action_client,
        abort_handler=abort_handler,
    )

    if not candidate_result.get("ok"):
        return candidate_result

    write_log(session_dir, "EX01_CANDIDATE_DETECTED")

    return candidate_result


def select_piso_by_options(browser, field_id, value=None, session_dir=None):
    """
    Selecciona piso leyendo las <option> reales de Mercurio.

    Casos:
        JSON: "5"    -> option "05"
        JSON: "05"   -> option "05"
        JSON: "5 C"  -> option "05"

    Si el campo no es select, escribe el piso a 2 dígitos.
    """
    raw = "" if value is None else str(value).strip()
    if not raw:
        if session_dir:
            write_log(session_dir, f"VACIO piso {field_id}")
        return False

    m = re.search(r"\d+", raw)
    wanted_num = m.group(0) if m else raw

    try:
        wanted_int = int(wanted_num)
    except Exception:
        wanted_int = None

    script = f"""
    (function(){{
        const id = {json.dumps(field_id)};
        const raw = {json.dumps(raw)};
        const wantedNum = {json.dumps(wanted_num)};
        const wantedInt = {json.dumps(wanted_int)};

        const el = document.getElementById(id);
        if (!el) return {{ ok: false, reason: 'NO_EXISTE' }};

        function fire() {{
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            if (window.jQuery) window.jQuery(el).trigger('change');
        }}

        const z2 = wantedInt !== null ? String(wantedInt).padStart(2, '0') : raw;

        if (!el.options) {{
            el.value = z2;
            fire();
            return {{ ok: true, mode: 'input', value: el.value }};
        }}

        for (const opt of el.options || []) {{
            const ov = (opt.value || '').toString().trim();
            const ot = (opt.textContent || opt.innerText || '').toString().trim();

            const ovNum = ov.match(/\\d+/);
            const otNum = ot.match(/\\d+/);

            if (wantedInt !== null) {{
                if (ovNum && parseInt(ovNum[0], 10) === wantedInt) {{
                    el.value = opt.value;
                    fire();
                    return {{ ok: true, mode: 'select_value_num', selectedValue: opt.value, selectedText: ot }};
                }}

                if (otNum && parseInt(otNum[0], 10) === wantedInt) {{
                    el.value = opt.value;
                    fire();
                    return {{ ok: true, mode: 'select_text_num', selectedValue: opt.value, selectedText: ot }};
                }}
            }}
        }}

        for (const opt of el.options || []) {{
            const ov = (opt.value || '').toString().trim();
            const ot = (opt.textContent || opt.innerText || '').toString().trim();

            if (ov === z2 || ot === z2 || ov === raw || ot === raw || ov === wantedNum || ot === wantedNum) {{
                el.value = opt.value;
                fire();
                return {{ ok: true, mode: 'select_exact', selectedValue: opt.value, selectedText: ot }};
            }}
        }}

        return {{
            ok: false,
            reason: 'NO_MATCH_PISO',
            raw: raw,
            wantedNum: wantedNum,
            z2: z2,
            options: Array.from(el.options || []).map(o => [o.value, o.textContent]).slice(0, 80)
        }};
    }})();
    """

    result = js(browser, script)
    if session_dir:
        write_log(session_dir, f"select_piso {field_id} raw={raw!r} -> {result}")
    return result


def classify_piso_mercurio(value):
    """
    Clasifica el piso antes de tocar el DOM.

    Regla clave:
    - Solo selecciona BAJO EXTERIOR/INTERIOR si el valor original es claramente bajo.
    - Si hay número, siempre prevalece el número: "1" -> PISO 01.
    """
    raw = "" if value is None else str(value).strip()
    if not raw:
        return {"kind": "empty", "raw": raw, "formatted": "", "num": ""}

    norm = normalize(raw)

    m = re.search(r"\d+", raw)
    if m:
        num = m.group(0).zfill(2)
        return {"kind": "piso", "raw": raw, "formatted": "PISO " + num, "num": num}

    if norm in {"BJ", "BJO", "BAJO", "BJ EXT", "BJO EXT", "BAJO EXT", "BAJO EXTERIOR"}:
        return {"kind": "bajo_exterior", "raw": raw, "formatted": "BAJO EXTERIOR", "num": ""}

    if norm in {"BI", "BJO INT", "BAJO INT", "BAJO INTERIOR"}:
        return {"kind": "bajo_interior", "raw": raw, "formatted": "BAJO INTERIOR", "num": ""}

    return {"kind": "raw", "raw": raw, "formatted": raw, "num": ""}


def format_piso_mercurio(value):
    return classify_piso_mercurio(value)["formatted"]


def set_piso_mercurio(browser, field_id, value=None, session_dir=None):
    """
    Selección segura de piso en Mercurio.

    - BJ/BJ EXT -> PBE / BAJO EXTERIOR.
    - BI        -> PBI / BAJO INTERIOR.
    - 1/01/1 C  -> PISO 01 / P01, sin poder caer en BAJO EXTERIOR.
    """
    info = classify_piso_mercurio(value)
    formatted = info["formatted"]
    kind = info["kind"]
    num = info["num"]
    raw = info["raw"]

    if not formatted:
        if session_dir:
            write_log(session_dir, f"VACIO piso {field_id}")
        return GOVERNED_OUTCOME_SKIPPED

    applied = {}

    def _apply():
        script = f"""
    (function(){{
        const id = {json.dumps(field_id)};
        const raw = {json.dumps(raw)};
        const kind = {json.dumps(kind)};
        const formatted = {json.dumps(formatted)};
        const num = {json.dumps(num)};

        const el = document.getElementById(id);
        if (!el) return {{ ok: false, reason: 'NO_EXISTE', raw, kind, formatted, num }};

        function norm(v) {{
            return (v || '').toString().trim().toUpperCase()
                .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
                .replace(/\s+/g, ' ');
        }}

        function fire() {{
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            if (window.jQuery) window.jQuery(el).trigger('change');
        }}

        if (!el.options) {{
            el.value = formatted;
            fire();
            return {{ ok: true, mode: 'input', value: el.value, raw, kind, formatted, num }};
        }}

        // BAJOS: solo si el valor original fue clasificado explícitamente como bajo.
        if (kind === 'bajo_exterior' || kind === 'bajo_interior') {{
            const wantedCode = kind === 'bajo_exterior' ? 'PBE' : 'PBI';
            const wantedText = kind === 'bajo_exterior' ? 'BAJO EXTERIOR' : 'BAJO INTERIOR';

            for (const opt of el.options || []) {{
                const ov = norm(opt.value);
                const ot = norm(opt.textContent || opt.innerText || '');

                if (ov === wantedCode || ot === wantedText) {{
                    el.value = opt.value;
                    fire();
                    return {{
                        ok: true,
                        mode: 'bajo_exterior_interior',
                        selectedValue: opt.value,
                        selectedText: opt.textContent,
                        raw,
                        kind,
                        wanted: wantedText
                    }};
                }}
            }}
        }}

        // PISOS NUMÉRICOS: si raw trae número, jamás se permite seleccionar PBE/PBI.
        if (kind === 'piso') {{
            const wantedText = 'PISO ' + num;
            const wantedValue = 'P' + num;
            const wantedValueNoZero = 'P' + String(parseInt(num, 10));
            const numericNoZero = String(parseInt(num, 10));

            // 1) Preferencia exacta por value Mercurio habitual: P01, P02...
            for (const opt of el.options || []) {{
                const ov = norm(opt.value);
                const ot = norm(opt.textContent || opt.innerText || '');
                if (ov === wantedValue || ot === wantedText) {{
                    el.value = opt.value;
                    fire();
                    return {{ ok: true, mode: 'piso_exact', selectedValue: opt.value, selectedText: opt.textContent, raw, kind, wanted: wantedText }};
                }}
            }}

            // 2) Fallback numérico, pero exigiendo texto que empiece por PISO.
            for (const opt of el.options || []) {{
                const ov = norm(opt.value);
                const ot = norm(opt.textContent || opt.innerText || '');
                if ((ov === num || ov === numericNoZero || ov === wantedValueNoZero) && ot.startsWith('PISO')) {{
                    el.value = opt.value;
                    fire();
                    return {{ ok: true, mode: 'piso_value_num_text_piso', selectedValue: opt.value, selectedText: opt.textContent, raw, kind, wanted: wantedText }};
                }}
            }}

            return {{
                ok: false,
                reason: 'NO_MATCH_PISO_NUMERICO',
                raw,
                kind,
                formatted,
                num,
                options: Array.from(el.options || []).map(o => [o.value, o.textContent]).slice(0, 160)
            }};
        }}

        // Resto: coincidencia exacta estricta, sin fallback a bajo.
        const wanted = norm(formatted);
        for (const opt of el.options || []) {{
            const ov = norm(opt.value);
            const ot = norm(opt.textContent || opt.innerText || '');
            if (ov === wanted || ot === wanted) {{
                el.value = opt.value;
                fire();
                return {{ ok: true, mode: 'raw_exact', selectedValue: opt.value, selectedText: opt.textContent, raw, kind, wanted: formatted }};
            }}
        }}

        return {{
            ok: false,
            reason: 'NO_MATCH_PISO_RAW',
            raw,
            kind,
            formatted,
            num,
            options: Array.from(el.options || []).map(o => [o.value, o.textContent]).slice(0, 160)
        }};
    }})();
    """
        applied["result"] = js(browser, script)

    def _verify():
        return _verify_select_option(
            browser,
            field_id,
            applied.get("result"),
            session_dir=session_dir,
            selected_value_keys=("selectedValue", "value"),
        )

    result = _governed_write(
        browser,
        action_kind="SELECT",
        field_id=field_id,
        apply=_apply,
        session_dir=session_dir,
        verify=_verify,
    )

    return _governed_outcome(result)

def _fill_section_blocked(outcome):
    return outcome not in (
        *_GOVERNED_DEFERRED_OUTCOMES,
        GOVERNED_OUTCOME_OK,
        GOVERNED_OUTCOME_SKIPPED,
    )


# QCC_EX01_R6_POSTFORM: canonical Mercurio DOM controls of each mapper
# block (REAL EX01 inventory). Anything else a payload carries (Box paths,
# CRM ids, stale aliases) is metadata: never resolved nor written.
_CANONICAL_MAPPER_FIELDS = {
    "extranjero": frozenset("""
        chkHijosCargo extApellido1 extApellido2 extCodigoNacionalidad
        extCodigoPaisNacimiento extEstadoCivil extFechaNacimiento extLugarNacimiento
        extMadre extNie extNombre extPadre
        extPasaporte extSexo extNieRepresentante extNombreRepresentante
        extTipodocumentoRepresentante extTituloRepresentante
    """.split()),
    "domicilio_extranjero": frozenset("""
        extCodigoLocalidad extCodigoMunicipio extCodigoPostal extCodigoProvincia
        extDomicilio extEmail extLetra extNumero
        extPiso extTelefono extTelefonoMovil extTipoVia
    """.split()),
    "notificacion": frozenset("""
        notCodigoLocalidadNotificacion notCodigoMunicipioNotificacion notCodigoPostalNotificacion notCodigoProvinciaNotificacion
        notDomicilioNotificacion notEmailNotificacion notNieNotificacion notNombreNotificacion
        notNumeroNotificacion notPisoNotificacion notTelefonoMovilNotificacion notTipoViaNotificacion
        notTipodocumentoNotificacion
    """.split()),
    "representante": frozenset("""
        preBloquePresentador preCodigoLocalidadPresentador preCodigoMunicipioPresentador preCodigoPostalPresentador
        preCodigoProvinciaPresentador preDomicilioPresentador preEmailPresentador preEmailRepLegalPresentador
        preEscaleraPresentador preHectometroPresentador preKilometroPresentador preLetraPresentador
        preNiePresentador preNieRepresentantePresentador preNombrePresentador preNombreRepresentantePresentador
        preNumeroPresentador prePisoPresentador preTelefonoMovilPresentador preTelefonoMovilRepLegalPresentador
        preTelefonoPresentador preTipoViaPresentador preTipodocumentoPresentador preTipodocumentoRepresentantePresentador
        preTituloRepresentantePresentador
    """.split()),
}
_CANONICAL_DOM_FIELDS = frozenset().union(*_CANONICAL_MAPPER_FIELDS.values())


def _project_mapper_fields(block, values, session_dir):
    projected = {}
    for key, value in (values or {}).items():
        if key.removesuffix("_text") in _CANONICAL_MAPPER_FIELDS[block]:
            projected[key] = value
        else:
            write_log(session_dir, f"NON_DOM_MAPPER_METADATA_SKIPPED key={key}")
    return projected


# QCC_EX01_R6_FAMILIAR_131: stale mapper alias with no observed EX01
# control (tools/mercurio_lab/ex01 inventory: Nombre / DNI-NIE-PAS /
# Número / Título). A datos_mercurio.json generated before the mapper fix
# may still carry it: never resolved nor written, logged by key only.
_NON_DOM_STALE_MAPPER_KEYS = frozenset({"extVinculoRepresentante"})


def fill_section(browser, values, session_dir):
    with governed_section(browser, session_dir, label="fill_section"):
        return _fill_section_fields(browser, values, session_dir)


def _fill_section_fields(browser, values, session_dir):
    """
    Procesa campos normales y también campos solo-texto:
        extCodigoPaisNacimiento_text = "MARRUECOS"
    se convierte en select de:
        extCodigoPaisNacimiento

    Cada escritura individual está gobernada por QCC V2. En cuanto una
    de ellas resulta DENIED/FAILED/HUMAN_HANDOFF, el rellenado se
    detiene inmediatamente: los campos restantes NO se escriben como
    si el anterior hubiera tenido éxito.
    """
    processed = set()
    blocked_field = None
    blocked_outcome = None

    write_log(
        session_dir,
        f"FILL_STAGE_ENTERED field_count={len(values)}",
    )

    stale = sorted(
        key for key in values
        if key.removesuffix("_text") in _NON_DOM_STALE_MAPPER_KEYS
    )
    for key in stale:
        write_log(session_dir, f"NON_DOM_MAPPER_METADATA_SKIPPED key={key}")
    values = {key: value for key, value in values.items() if key not in stale}

    # Primero campos base.
    for field_id, value in values.items():
        if field_id.endswith("_text"):
            continue

        processed.add(field_id)
        text_value = values.get(field_id + "_text", "")

        if field_id.startswith("chk"):
            outcome = set_checkbox(browser, field_id, value=value, session_dir=session_dir)
        elif (
            field_id.startswith("extCodigoPais") or field_id.startswith("extCodigoNacionalidad")
            or field_id.startswith("reaCodigoPais") or field_id.startswith("reaCodigoNacionalidad")
        ):
            outcome = select_by_text_or_value(browser, field_id, value=value, text=text_value or value, session_dir=session_dir)
        elif field_id.startswith("extCodigoMunicipio") or field_id.startswith("extCodigoLocalidad"):
            # Se gestiona en cascada aparte.
            continue
        elif field_id.startswith("notCodigoMunicipio") or field_id.startswith("notCodigoLocalidad"):
            continue
        elif field_id.startswith("reaCodigoMunicipio") or field_id.startswith("reaCodigoLocalidad"):
            continue
        elif (
            field_id.startswith("extCodigoProvincia") or field_id.startswith("notCodigoProvincia")
            or field_id.startswith("reaCodigoProvincia")
        ):
            # Provincia/municipio/localidad se gestiona en cascada aparte.
            continue
        elif field_id.startswith("preCodigoProvincia") or field_id.startswith("preCodigoMunicipio") or field_id.startswith("preCodigoLocalidad"):
            # Provincia/municipio/localidad del presentador se gestiona en cascada aparte.
            continue
        elif field_id in ("extPiso", "notPisoNotificacion", "prePisoPresentador", "reaPisoReagrupante"):
            outcome = set_piso_mercurio(browser, field_id, value=value, session_dir=session_dir)
        elif field_id.startswith("preTipoVia"):
            # Presentador: NO usar variables externas tipo tipo_via.
            # El mapper entrega preTipoViaPresentador y preTipoViaPresentador_text.
            outcome = select_by_text_or_value(
                browser,
                field_id,
                value="",
                text=resolve_tipo_via_text(value, text_value),
                session_dir=session_dir,
            )
        elif field_id.startswith("extTipoVia") or field_id.startswith("notTipoVia") or field_id.startswith("reaTipoVia"):
            outcome = select_by_text_or_value(
                browser,
                field_id,
                value="",  # Mercurio no usa AV/CL; usa codigos propios como BZ/ED. Seleccionar por texto.
                text=resolve_tipo_via_text(value, text_value),
                session_dir=session_dir,
            )
        elif (
            field_id.startswith("extEstadoCivil") or field_id.startswith("extSexo")
            or field_id.startswith("reaEstadoCivil") or field_id.startswith("reaSexo")
            or field_id.startswith("reaParentesco")
        ):
            outcome = select_by_text_or_value(browser, field_id, value=value, text=text_value or value, session_dir=session_dir)
        elif (
            field_id.startswith("notTipodocumento") or field_id.startswith("preTipodocumento")
            or field_id.startswith("reaTipoDocumento")
        ):
            outcome = select_by_text_or_value(browser, field_id, value=value, text=text_value or value, session_dir=session_dir)
        elif field_id.startswith("extTipodocumento"):
            # QCC_EX01_R6_FAMILIAR_131: observed EX01 SELECT (twin inventory
            # _EX01_OBSERVED_SELECT_CLASSES); an empty one stays unwritten.
            if not str(value or "").strip() and not str(text_value or "").strip():
                write_log(session_dir, f"VACIO: {field_id}")
                outcome = GOVERNED_OUTCOME_SKIPPED
            else:
                outcome = select_by_text_or_value(browser, field_id, value=value, text=text_value or value, session_dir=session_dir)
        else:
            outcome = set_value(browser, field_id, value, session_dir=session_dir, trigger_change=True)

        if _fill_section_blocked(outcome):
            blocked_field, blocked_outcome = field_id, outcome
            write_log(
                session_dir,
                f"fill_section detenido: campo={field_id} outcome={outcome}",
            )
            break

    # Después campos que solo vienen como *_text.
    if blocked_field is None:
        for text_key, text_value in values.items():
            if not text_key.endswith("_text"):
                continue

            base_id = text_key[:-5]
            if base_id in processed:
                continue

            if base_id.startswith("extCodigoMunicipio") or base_id.startswith("extCodigoLocalidad"):
                continue
            if base_id.startswith("notCodigoMunicipio") or base_id.startswith("notCodigoLocalidad"):
                continue
            if base_id.startswith("reaCodigoMunicipio") or base_id.startswith("reaCodigoLocalidad"):
                continue
            if base_id.startswith("extCodigoProvincia") or base_id.startswith("notCodigoProvincia") or base_id.startswith("reaCodigoProvincia"):
                continue
            if base_id.startswith("preCodigoProvincia") or base_id.startswith("preCodigoMunicipio") or base_id.startswith("preCodigoLocalidad"):
                continue

            outcome = select_by_text_or_value(browser, base_id, text=text_value, session_dir=session_dir)

            if _fill_section_blocked(outcome):
                blocked_field, blocked_outcome = base_id, outcome
                write_log(
                    session_dir,
                    f"fill_section detenido: campo={base_id} outcome={outcome}",
                )
                break

    write_log(
        session_dir,
        "FILL_STAGE_RESULT "
        f"ok={blocked_field is None} "
        f"blocked_field={blocked_field or '-'} "
        f"blocked_outcome={blocked_outcome or '-'}",
    )

    return {
        "ok": blocked_field is None,
        "blocked_field": blocked_field,
        "blocked_outcome": blocked_outcome,
    }


def fill_datos_extranjero(browser, datos_mercurio, session_dir):
    preload = _active_mapper_preload(browser)
    if preload is not None:
        # QCC_EX01_R6_POSTFORM: under VOLCAR DATOS the canonical mapper
        # runs on the active Datos del extranjero/a surface; every later
        # surface (presenter, notification) is deferred, never written.
        result = preload.resume(_EXTRANJERO_SURFACE_BLOCKS)
        if not result.get("ok"):
            return result
        # QCC_EX01_R11_FIX3_CASCADE: FILLED only once every mapped control
        # of this ACTIVE surface is verified; a later surface may stay
        # deferred, a mandatory control of this one may not.
        pending = preload.pending_on(_EXTRANJERO_SURFACE_BLOCKS)
        if pending:
            field, outcome = next(iter(pending.items()))
            write_log(
                session_dir,
                f"MAPPER_ACTIVE_SURFACE_PENDING fields={sorted(pending)} outcome={outcome}",
            )
            return {"ok": False, "label": "EXTRANJERO_BLOCKED", "blocked_field": field,
                    "blocked_outcome": outcome, "cause": "ACTIVE_FIELD_PENDING"}
        return result
    print("[7] Rellenando datos completos del extranjero/a")
    write_log(session_dir, "Rellenando datos completos extranjero")

    wait_for_js(browser, "document.getElementById('extPasaporte') || document.getElementById('extNie')")

    extranjero = datos_mercurio.get("extranjero", {})
    domicilio = datos_mercurio.get("domicilio_extranjero", {})
    notificacion = datos_mercurio.get("notificacion", {})

    with governed_section(browser, session_dir, label="EX01_PERSONAL"):
        result = fill_section(browser, extranjero, session_dir)
        if not result["ok"]:
            write_log(session_dir, f"Datos del extranjero detenidos: {result}")
            return result

        result = fill_section(browser, domicilio, session_dir)
        if not result["ok"]:
            write_log(session_dir, f"Domicilio del extranjero detenido: {result}")
            return result

        result = select_municipio_localidad(browser, domicilio, session_dir, prefix="ext")
        if not result["ok"]:
            write_log(session_dir, f"Cascada domicilio del extranjero detenida: {result}")
            return result

        # Notificación puede estar en otra pestaña, pero si los campos existen, se rellenan.
        result = fill_section(browser, notificacion, session_dir)
        if not result["ok"]:
            write_log(session_dir, f"Datos de notificación detenidos: {result}")
            return result

        result = select_municipio_localidad(browser, notificacion, session_dir, prefix="not")
        if not result["ok"]:
            write_log(session_dir, f"Cascada de notificación detenida: {result}")
            return result

    print("Datos completos rellenados.")
    write_log(session_dir, "Datos completos rellenados")
    return {"ok": True, "blocked_field": None, "blocked_outcome": None}




def select_municipio_localidad_presentador(browser, values, session_dir):
    """
    Cascada provincia -> municipio -> localidad para Datos del presentador.
    No modifica la función genérica existente para extranjero/notificación.
    """
    prov_id = "preCodigoProvinciaPresentador"
    mun_id = "preCodigoMunicipioPresentador"
    loc_id = "preCodigoLocalidadPresentador"

    provincia_value = values.get(prov_id, "")
    provincia_text = values.get(prov_id + "_text", "")
    municipio_text = values.get(mun_id + "_text", "")
    localidad_text = values.get(loc_id + "_text", "") or municipio_text

    if _active_mapper_preload(browser) is not None:
        # QCC_EX01_R6_POSTFORM: same governed cascade as ext/not.
        return _run_governed_cascade(browser, (
            (prov_id, provincia_value, provincia_text or provincia_value),
            (mun_id, "", municipio_text),
            (loc_id, "", localidad_text),
        ), session_dir)

    if provincia_value or provincia_text:
        select_by_text_or_value(browser, prov_id, value=provincia_value, text=provincia_text or provincia_value, session_dir=session_dir)
        time.sleep(1.2)

    if municipio_text and field_exists(browser, mun_id):
        try:
            wait_select_options(browser, mun_id, min_options=2, timeout=4)
        except Exception as exc:
            write_log(session_dir, f"WAIT_FAIL municipio presentador {mun_id}: {exc}")
        select_by_text_or_value(browser, mun_id, text=municipio_text, session_dir=session_dir)
        time.sleep(1.5)

    if localidad_text and field_exists(browser, loc_id):
        try:
            wait_select_options(browser, loc_id, min_options=2, timeout=2)
        except Exception as exc:
            write_log(session_dir, f"WAIT_FAIL localidad presentador {loc_id}: {exc}")
        select_by_text_or_value(browser, loc_id, text=localidad_text, session_dir=session_dir)



def select_municipio_localidad_reagrupante(browser, values, session_dir):
    """
    Cascada provincia -> municipio -> localidad para la pestaña Datos del familiar
    de EX01 familiar. Mercurio usa prefijo rea*Reagrupante.
    """
    prov_id = "reaCodigoProvinciaReagrupante"
    mun_id = "reaCodigoMunicipioReagrupante"
    loc_id = "reaCodigoLocalidadReagrupante"

    provincia_value = values.get(prov_id, "")
    provincia_text = values.get(prov_id + "_text", "")
    municipio_text = values.get(mun_id + "_text", "")
    localidad_text = values.get(loc_id + "_text", "") or municipio_text

    if provincia_value or provincia_text:
        select_by_text_or_value(browser, prov_id, value=provincia_value, text=provincia_text or provincia_value, session_dir=session_dir)
        time.sleep(1.2)

    if municipio_text and field_exists(browser, mun_id):
        try:
            wait_select_options(browser, mun_id, min_options=2, timeout=4)
        except Exception as exc:
            write_log(session_dir, f"WAIT_FAIL municipio familiar {mun_id}: {exc}")
        select_by_text_or_value(browser, mun_id, text=municipio_text, session_dir=session_dir)
        time.sleep(1.5)

    if localidad_text and field_exists(browser, loc_id):
        try:
            wait_select_options(browser, loc_id, min_options=2, timeout=2)
        except Exception as exc:
            write_log(session_dir, f"WAIT_FAIL localidad familiar {loc_id}: {exc}")
        select_by_text_or_value(browser, loc_id, text=localidad_text, session_dir=session_dir)


# QCC_EX01_R6_FAMILIAR_131: EX01 Renovación Familiar (datosForAut=131)
# reuses the EX01 core and only adds "Datos del familiar". Mercurio keeps
# every r-tabs panel in one DOM, so rea* node presence is not that screen:
# the surface is the family panel as the SOLE active one, read live.
# Its province -> municipality -> locality cascade is governed per level
# (live surface, parent still holding its verified option, child really
# offering the target), then SETTLE -> REVERIFY with a bounded retry from
# the first lost level. Never stable -> fail closed on the family surface.
# EX02 keeps ``select_municipio_localidad_reagrupante`` unchanged.
_EX01_FAMILY_SURFACE_JS = (
    "(document.getElementById('reaNombreReagrupante') || "
    "document.getElementById('reaDocumentoReagrupante') || "
    "document.getElementById('reaNieReagrupante')) && "
    f"{_ex01_sole_active_panel_js(_EX01_FAMILY_PANEL_ID)}"
)
_FAMILY_CASCADE_MEMBERS = (
    "reaCodigoProvinciaReagrupante",
    "reaCodigoMunicipioReagrupante",
    "reaCodigoLocalidadReagrupante",
)
_FAMILY_CASCADE_MAX_ATTEMPTS = 3
_FAMILY_CASCADE_READY_MARKER = "/*QCC_FAMILY_CASCADE_READY*/"
_FAMILY_CASCADE_DIAGNOSTIC_MARKER = "/*QCC_FAMILY_CASCADE_DIAGNOSTIC*/"
_FAMILY_CASCADE_SETTLED_JS = " ".join((
    "/*QCC_FAMILY_CASCADE_SETTLED*/",
    "(function(){",
    "return !(window.jQuery && window.jQuery.active > 0) && document.readyState === 'complete';",
    "})()",
))
_FAMILY_CASCADE_JS_NORM = (
    "const norm = function(v){ return String(v || '').trim().toUpperCase()"
    ".normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').replace(/\\s+/g, ' '); };"
)
# Shared with select_by_text_or_value: value, exact text, unique partial.
_FAMILY_CASCADE_JS_TARGET_PRESENT = (
    "const opts = child && child.options ? Array.from(child.options) : [];"
    " const targetPresent = opts.some(function(o){ return (!!want.value && o.value === want.value)"
    " || (!!text && norm(o.textContent) === text); }) || (!!text && opts.filter(function(o){"
    " const t = norm(o.textContent); return !!t && (t.includes(text) || text.includes(t)); }).length === 1);"
)


def _ex01_family_surface_active(browser):
    try:
        return bool(js(browser, f"return !!({_EX01_FAMILY_SURFACE_JS});"))
    except Exception:
        return False


def _family_cascade_ready_js(field_id, value, text, parent):
    """Live, read-only readiness of ONE family cascade level. One line,
    no ``//`` (CDP contract)."""

    parent_id, parent_value = parent or ("", "")
    return " ".join((
        _FAMILY_CASCADE_READY_MARKER,
        "(function(){",
        f"const ids = {json.dumps({'child': field_id, 'parent': parent_id})};",
        f"const want = {json.dumps({'value': str(value or ''), 'parent_value': str(parent_value or '')})};",
        _FAMILY_CASCADE_JS_NORM,
        f"const text = norm({json.dumps(str(text or ''))});",
        f"if (!({_ex01_sole_active_panel_js(_EX01_FAMILY_PANEL_ID)})) return false;",
        f"if (!({_one_line_js(_field_readiness_js(field_id))})) return false;",
        "const child = document.getElementById(ids.child);",
        "if (!child || child.disabled || !child.options) return false;",
        "if (ids.parent) {",
        "const parent = document.getElementById(ids.parent);",
        "if (!parent || parent.selectedIndex < 0 || parent.value !== want.parent_value) return false;",
        "}",
        _FAMILY_CASCADE_JS_TARGET_PRESENT,
        "return targetPresent;",
        "})()",
    ))


def _family_cascade_diagnostic_js(field_id, value, text, parent_id):
    return " ".join((
        _FAMILY_CASCADE_DIAGNOSTIC_MARKER,
        "(function(){",
        f"const ids = {json.dumps({'child': field_id, 'parent': parent_id or ''})};",
        f"const want = {json.dumps({'value': str(value or '')})};",
        _FAMILY_CASCADE_JS_NORM,
        f"const text = norm({json.dumps(str(text or ''))});",
        "const child = document.getElementById(ids.child);",
        "const parent = ids.parent ? document.getElementById(ids.parent) : null;",
        _FAMILY_CASCADE_JS_TARGET_PRESENT,
        "return {",
        f"surface_active: !!({_ex01_sole_active_panel_js(_EX01_FAMILY_PANEL_ID)}),",
        "child_exists: !!child, child_disabled: !!(child && child.disabled),",
        "child_option_count: opts.length, target_option_present: targetPresent,",
        "parent_exists: !!parent,",
        "parent_selected_index: parent && typeof parent.selectedIndex === 'number' ? parent.selectedIndex : -1,",
        "parent_selected_value: parent ? String(parent.value == null ? '' : parent.value) : null,",
        "jquery_active: (window.jQuery && typeof window.jQuery.active === 'number') ? window.jQuery.active : null",
        "};",
        "})()",
    ))


def _diagnose_family_cascade_level(browser, field_id, value, text, parent, session_dir):
    """Why a family level was not ready: SURFACE_LOST, PARENT_LOST,
    CHILD_UNAVAILABLE, TARGET_OPTION_MISSING/PRESENT. Read-only; logs ids,
    counts and booleans only (never option texts or values)."""

    parent_id, parent_value = parent or ("", "")
    try:
        state = js(browser, _family_cascade_diagnostic_js(field_id, value, text, parent_id))
    except Exception:
        state = None
    state = state if isinstance(state, dict) else {}

    parent_matches = None
    if parent and state:
        parent_matches = (
            state.get("parent_selected_index", -1) >= 0
            and state.get("parent_selected_value") == parent_value
        )

    if not state:
        cause = "DIAGNOSTIC_UNAVAILABLE"
    elif not state.get("surface_active"):
        cause = "SURFACE_LOST"
    elif parent_matches is False:
        cause = "PARENT_LOST"
    elif not state.get("child_exists") or state.get("child_disabled"):
        cause = "CHILD_UNAVAILABLE"
    elif state.get("target_option_present"):
        cause = "TARGET_OPTION_PRESENT"
    else:
        cause = "TARGET_OPTION_MISSING"

    write_log(
        session_dir,
        "FAMILY_CASCADE_READINESS_DIAGNOSTIC "
        f"field={field_id} parent={parent_id or '-'} "
        f"child_exists={state.get('child_exists')} "
        f"child_disabled={state.get('child_disabled')} "
        f"child_options={state.get('child_option_count')} "
        f"target_option_present={state.get('target_option_present')} "
        f"parent_matches={parent_matches} "
        f"jquery_active={state.get('jquery_active')} cause={cause}",
    )
    return cause


def _wait_family_cascade_condition(browser, condition, session_dir, control):
    """Bounded wait. Returns ``(ready, aborted_result)``; the verdict is
    the condition AT the deadline. PRESENTATION_ABORT is serviced while
    waiting when the QCC channel exists."""

    action_client = control.get("action_client")

    if _qcc_action_channel_available(action_client):
        result = _wait_for_js_with_qcc_control(
            browser,
            condition,
            session_dir,
            timeout=_DEPENDENCY_READINESS_TIMEOUT_SECONDS,
            interval=_DEPENDENCY_READINESS_POLL_INTERVAL_SECONDS,
            action_client=action_client,
            reporter=control.get("reporter"),
            abort_handler=control.get("abort_handler"),
            step="FAMILY_CASCADE",
        )
        if _is_qcc_aborted_result(result):
            return False, result
        if result.get("ok"):
            return True, None
    else:
        try:
            wait_for_js(
                browser,
                condition,
                timeout=_DEPENDENCY_READINESS_TIMEOUT_SECONDS,
                interval=_DEPENDENCY_READINESS_POLL_INTERVAL_SECONDS,
            )
            return True, None
        except Exception:
            pass

    try:
        return bool(js(browser, f"return !!({condition});")), None
    except Exception:
        return False, None


def _family_cascade_member_kept(browser, field_id, expected, session_dir):
    """Read-back: the member still holds the option verified for it."""

    state = _read_field_state(browser, field_id)

    if state is None:
        reason = "READBACK_UNAVAILABLE"
    elif not state.get("exists"):
        reason = "NO_EXISTE"
    elif (
        state.get("selected_index", -1) < 0
        or state.get("selected_value") != expected
        or state.get("value") != expected
    ):
        reason = "SELECT_OPTION_NOT_SELECTED"
    else:
        return True

    write_log(
        session_dir,
        f"FAMILY_CASCADE_REVERIFY field={field_id} verified=False reason={reason}",
    )
    return False


def _family_cascade_targets(values):
    prov_id, mun_id, loc_id = _FAMILY_CASCADE_MEMBERS
    values = values or {}

    def _text(key):
        return str(values.get(key) or "").strip()

    provincia_value = _text(prov_id)
    municipio_text = _text(mun_id + "_text")
    levels = (
        (prov_id, provincia_value, _text(prov_id + "_text") or provincia_value),
        (mun_id, "", municipio_text),
        (loc_id, "", _text(loc_id + "_text") or municipio_text),
    )
    return [level for level in levels if level[1] or level[2]]


def select_municipio_localidad_familiar_ex01(
    browser,
    values,
    session_dir,
    *,
    reporter=None,
    action_client=None,
    abort_handler=None,
):
    """Cascada provincia -> municipio -> localidad de "Datos del familiar"
    (EX01 Familiar). Devuelve ``ok/blocked_field/blocked_outcome`` y
    ``family_cascade`` (opción verificada por nivel), o el resultado
    abortado. Sin esperas fijas: cada espera es acotada."""

    control = {
        "reporter": reporter,
        "action_client": action_client,
        "abort_handler": abort_handler,
    }
    targets = _family_cascade_targets(values)
    members = [field_id for field_id, _value, _text in targets]

    def _blocked(field_id, outcome):
        write_log(
            session_dir,
            f"FAMILY_CASCADE_BLOCKED field={field_id} outcome={outcome}",
        )
        return {
            "ok": False,
            "blocked_field": field_id,
            "blocked_outcome": outcome,
            "family_cascade": {},
        }

    if not targets:
        write_log(session_dir, "FAMILY_CASCADE_NOT_APPLICABLE fields=[]")
        return {"ok": True, "blocked_field": None, "blocked_outcome": None, "family_cascade": {}}

    if tuple(members) != _FAMILY_CASCADE_MEMBERS[:len(members)]:
        missing = next(f for f in _FAMILY_CASCADE_MEMBERS if f not in members)
        return _blocked(missing, "FAMILY_CASCADE_INCOMPLETE")

    write_log(session_dir, f"FAMILY_CASCADE_START fields={members}")
    selected = {}
    start = 0

    for attempt in range(1, _FAMILY_CASCADE_MAX_ATTEMPTS + 1):
        failed_at, cause = None, None

        for index in range(start, len(targets)):
            field_id, value, text = targets[index]
            parent = (members[index - 1], selected[members[index - 1]]) if index else None

            ready, aborted = _wait_family_cascade_condition(
                browser,
                _family_cascade_ready_js(field_id, value, text, parent),
                session_dir,
                control,
            )
            if aborted is not None:
                return aborted
            if not ready:
                write_log(session_dir, f"WAIT_FAIL cascade {field_id}")
                cause = _diagnose_family_cascade_level(
                    browser, field_id, value, text, parent, session_dir
                )
                failed_at = index
                break

            outcome = select_by_text_or_value(
                browser, field_id, value=value, text=text, session_dir=session_dir
            )
            if _fill_section_blocked(outcome):
                return _blocked(field_id, outcome)

            kept = str((_read_field_state(browser, field_id) or {}).get("selected_value") or "")
            if not kept:
                return _blocked(field_id, "SELECT_OPTION_NOT_SELECTED")
            selected[field_id] = kept

        if cause in ("SURFACE_LOST", "DIAGNOSTIC_UNAVAILABLE"):
            return _blocked(members[failed_at], f"FAMILY_CASCADE_{cause}")

        settled, aborted = _wait_family_cascade_condition(
            browser, _FAMILY_CASCADE_SETTLED_JS, session_dir, control
        )
        if aborted is not None:
            return aborted

        if not _ex01_family_surface_active(browser):
            return _blocked(members[0], "FAMILY_CASCADE_SURFACE_LOST")

        checked = members[:failed_at] if failed_at is not None else members
        lost = [
            f for f in checked
            if not _family_cascade_member_kept(browser, f, selected[f], session_dir)
        ]

        if failed_at is None and settled and not lost:
            write_log(
                session_dir,
                f"FAMILY_CASCADE_STABLE attempt={attempt} settled=True fields={members}",
            )
            return {
                "ok": True,
                "blocked_field": None,
                "blocked_outcome": None,
                "family_cascade": {f: selected[f] for f in members},
            }

        if lost:
            restart = members.index(lost[0])
        elif failed_at is not None:
            restart = failed_at
        else:
            restart = len(members)

        if attempt == _FAMILY_CASCADE_MAX_ATTEMPTS:
            # Unsettled: no member can be trusted.
            unverified = members[restart:] or list(members)
            write_log(
                session_dir,
                f"FAMILY_CASCADE_NEVER_STABLE attempts={attempt} lost={lost} "
                f"settled={settled} unverified={unverified}",
            )
            return _blocked(unverified[0], "FAMILY_CASCADE_NEVER_STABLE")

        for field_id in members[restart:]:
            selected.pop(field_id, None)

        if lost and failed_at is None:
            write_log(
                session_dir,
                f"FAMILY_CASCADE_UNSTABLE attempt={attempt} lost={lost} "
                f"retry_from={members[restart]}",
            )
        elif lost:
            write_log(
                session_dir,
                f"FAMILY_CASCADE_PARENT_LOST attempt={attempt} lost={lost} "
                f"child={members[failed_at]} stale_verification=INVALIDATED "
                f"retry_from={members[restart]}",
            )
        elif failed_at is not None:
            write_log(
                session_dir,
                f"FAMILY_CASCADE_TARGET_PENDING attempt={attempt} "
                f"field={members[failed_at]} cause={cause} parent_rewrite=NO",
            )
        else:
            write_log(
                session_dir,
                f"FAMILY_CASCADE_UNSETTLED attempt={attempt} fields={members}",
            )

        start = restart

    return _blocked(members[0], "FAMILY_CASCADE_NEVER_STABLE")


def _ex01_family_cascade_divergence(browser, session_dir, family_cascade):
    """After the human CONTINUAR: read-only re-verification of the family
    cascade. A divergence is never repaired from another surface."""

    family_cascade = family_cascade or {}
    diverged = [
        field_id for field_id, expected in family_cascade.items()
        if not _family_cascade_member_kept(browser, field_id, expected, session_dir)
    ]

    if not diverged:
        write_log(
            session_dir,
            f"FAMILY_CASCADE_POST_CONTINUE_VERIFIED fields={list(family_cascade)}",
        )
        return None

    write_log(
        session_dir,
        f"FAMILY_CASCADE_OFF_SURFACE_DIVERGENCE block=familiar fields={diverged} repair=NO",
    )
    return {
        "ok": False,
        "blocked_field": diverged[0],
        "blocked_outcome": "FAMILY_CASCADE_OFF_SURFACE_DIVERGENCE",
    }


def _ex01_family_relation_problem(datos_mercurio):
    """Reason code when "Datos del familiar" has no usable canonical CRM
    relation, else ``None``. The mapper falls back to the applicant when
    no contact is selected: that is never a family member."""

    datos_mercurio = datos_mercurio or {}
    familiar = datos_mercurio.get("familiar") or {}

    if not familiar:
        return "FAMILY_BLOCK_EMPTY"

    def _value(block, key):
        return normalize(str(block.get(key) or "").strip())

    documents = {
        _value(familiar, key)
        for key in ("reaDocumentoReagrupante", "reaPasaporteReagrupante", "reaNieReagrupante")
        if _value(familiar, key)
    }

    if not _value(familiar, "reaNombreReagrupante") or not documents:
        return "FAMILY_IDENTITY_MISSING"

    if not _value(familiar, "reaParentescoReagrupante"):
        return "FAMILY_RELATION_MISSING"

    extranjero = datos_mercurio.get("extranjero") or {}
    applicant = {
        _value(extranjero, key)
        for key in ("extNie", "extPasaporte")
        if _value(extranjero, key)
    }

    if documents & applicant:
        return "FAMILY_RELATION_IS_APPLICANT"

    return None


def is_field_visible(browser, field_id):
    """Devuelve True solo si el campo existe y está visible en la pestaña activa."""
    script = f"""
    (function(){{
        const el = document.getElementById({json.dumps(field_id)});
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        if (el.closest('[style*="display: none"]')) return false;
        return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
    }})();
    """
    return bool(js(browser, script))


def filter_visible_values(browser, values, session_dir=None, label=""):
    """
    Filtra un bloque de valores para no escribir campos de pestañas ocultas.

    Mercurio deja en el DOM campos de las 4 pantallas EX02 aunque todavía no
    se haya avanzado a ellas. Para EX02 rellenamos solo lo visible en cada paso.
    """
    values = values or {}
    visible = {}
    hidden = []

    for key, value in values.items():
        if key.endswith("_text"):
            continue
        if is_field_visible(browser, key):
            visible[key] = value
            text_key = key + "_text"
            if text_key in values:
                visible[text_key] = values.get(text_key)
        else:
            hidden.append(key)

    if session_dir:
        write_log(
            session_dir,
            f"EX02 visible_only {label}: visibles={sorted(visible.keys())} ocultos={hidden}",
        )
    return visible



def fill_datos_reagrupado_ex02(browser, datos_mercurio, session_dir):
    """
    EX02 pantalla 2: Datos del reagrupado/solicitante.

    Fuente: cliente del expediente ya mapeado como:
    - datos_mercurio['extranjero']
    - datos_mercurio['domicilio_extranjero']

    No rellena reagrupante, presentador ni notificación.
    """
    print("[8] Rellenando DATOS DEL REAGRUPADO/SOLICITANTE EX02")
    write_log(session_dir, "Rellenando datos del reagrupado/solicitante EX02")

    wait_for_js(browser, "document.getElementById('extPasaporte') || document.getElementById('extNie')", timeout=15, interval=0.5)

    extranjero = datos_mercurio.get("extranjero", {}) or {}
    domicilio = datos_mercurio.get("domicilio_extranjero", {}) or {}

    result = fill_section(browser, extranjero, session_dir)
    if not result["ok"]:
        write_log(session_dir, f"Reagrupado/solicitante EX02 detenido: {result}")
        return False

    result = fill_section(browser, domicilio, session_dir)
    if not result["ok"]:
        write_log(session_dir, f"Domicilio reagrupado EX02 detenido: {result}")
        return False

    select_municipio_localidad(browser, domicilio, session_dir, prefix="ext")

    print("Datos del reagrupado/solicitante EX02 rellenados.")
    write_log(session_dir, "Datos del reagrupado/solicitante EX02 rellenados")
    return True

def fill_datos_familiar_ex01(
    browser,
    datos_mercurio,
    session_dir,
    *,
    reporter=None,
    action_client=None,
    abort_handler=None,
):
    """
    Rellena la pestaña Datos del familiar de EX01 familiar.

    En MERCURIO_EX01_FAMILIAR:
    - Datos del extranjero/a = familiar extranjero solicitante.
    - Datos del familiar = titular de los medios económicos / familiar que da derecho.

    QCC_EX01_R6_FAMILIAR_131: fail-closed sin relación CRM canónica, fuera
    de la pestaña Datos del familiar activa (lectura viva) o con la cascada
    no estable. Devuelve ``ok/blocked_field/blocked_outcome`` (y
    ``family_cascade`` si ok) o el resultado abortado.
    """
    print("[8] Rellenando DATOS DEL FAMILIAR")
    write_log(session_dir, "Rellenando datos del familiar EX01")

    familiar = datos_mercurio.get("familiar", {}) or {}
    problem = _ex01_family_relation_problem(datos_mercurio)
    if problem:
        write_log(session_dir, f"FAMILY_RELATION_BLOCKED reason={problem}")
        print("No hay relación familiar canónica utilizable en datos_mercurio.json")
        return {"ok": False, "blocked_field": None, "blocked_outcome": problem}

    if not _ex01_family_surface_active(browser):
        write_log(session_dir, "FAMILY_SURFACE_NOT_ACTIVE outcome=BLOCKED")
        return {"ok": False, "blocked_field": None, "blocked_outcome": "FAMILY_SURFACE_NOT_ACTIVE"}

    with governed_section(browser, session_dir, label="EX01_FAMILIAR"):
        result = fill_section(browser, familiar, session_dir)
        if not result["ok"]:
            write_log(session_dir, f"Datos del familiar detenidos: {result}")
            return result

        result = select_municipio_localidad_familiar_ex01(
            browser,
            familiar,
            session_dir,
            reporter=reporter,
            action_client=action_client,
            abort_handler=abort_handler,
        )
        if not result.get("ok"):
            write_log(session_dir, "Cascada del familiar detenida")
            return result

    print("Datos del familiar rellenados.")
    write_log(session_dir, "Datos del familiar rellenados")
    return result



def fill_datos_reagrupante_ex02(browser, datos_mercurio, session_dir):
    """
    EX02 pantalla 1: Datos del reagrupante.

    Fuente: datos_mercurio['reagrupante'], generado desde
    datos_especificos.reagrupante_*.

    No usa filtro de visibilidad: Mercurio puede tener campos cargados/ocultos,
    pero aquí solo se invoca cuando el usuario ya está en la pantalla correcta.
    """
    print("[7] Rellenando DATOS DEL REAGRUPANTE EX02")
    write_log(session_dir, "Rellenando datos del reagrupante EX02")

    reagrupante = datos_mercurio.get("reagrupante", {}) or {}
    if not reagrupante:
        write_log(session_dir, "Reagrupante EX02 vacío en datos_mercurio.json")
        print("No hay bloque reagrupante en datos_mercurio.json")
        return False

    wait_for_js(
        browser,
        "document.getElementById('reaNombreReagrupante') || document.getElementById('reaNieReagrupante') || document.getElementById('reaPasaporteReagrupante')",
        timeout=15,
        interval=0.5,
    )

    result = fill_section(browser, reagrupante, session_dir)
    if not result["ok"]:
        write_log(session_dir, f"Datos del reagrupante EX02 detenidos: {result}")
        return False

    select_municipio_localidad_reagrupante(browser, reagrupante, session_dir)

    print("Datos del reagrupante EX02 rellenados.")
    write_log(session_dir, "Datos del reagrupante EX02 rellenados")
    return True

def click_continuar_ex02_extranjero_to_reagrupante(
    browser,
    session_dir,
    reporter=None,
):
    """Espera humana desde Datos del extranjero/reagrupado a Datos del reagrupante."""
    print("[8] ESPERA HUMANA - CONTINUAR a DATOS DEL REAGRUPANTE EX02")
    write_log(session_dir, "Espera humana EX02: extranjero/reagrupado -> reagrupante")
    return wait_for_human_navigation(
        browser,
        session_dir,
        "Datos del reagrupante EX02",
        "document.getElementById('reaNombreReagrupante') || document.getElementById('reaNieReagrupante') || document.getElementById('reaPasaporteReagrupante')",
        timeout=300,
        fallback_prompt="Pulsa ENTER cuando estés en Datos del reagrupante...",
        qcc_reporter=reporter,
        qcc_step="CONTINUE_TO_SPONSOR",
        qcc_progress=42,
    )


def click_continuar_ex02_reagrupante_to_presentador(
    browser,
    session_dir,
    reporter=None,
):
    """Espera humana desde Datos del reagrupante a Datos del presentador."""
    print("[9] ESPERA HUMANA - CONTINUAR a DATOS DEL PRESENTADOR")
    write_log(session_dir, "Espera humana EX02: reagrupante -> presentador")
    return wait_for_human_navigation(
        browser,
        session_dir,
        "Datos del presentador",
        "document.getElementById('preNombrePresentador')",
        timeout=300,
        fallback_prompt="Pulsa ENTER cuando estés en Datos del presentador...",
        qcc_reporter=reporter,
        qcc_step="CONTINUE_TO_PRESENTER",
        qcc_progress=68,
    )

def click_continuar_ex02_reagrupante_to_reagrupado(
    browser,
    session_dir,
    reporter=None,
):
    """Espera humana desde Datos del reagrupante a Datos del reagrupado/solicitante."""
    print("[8] ESPERA HUMANA - CONTINUAR a DATOS DEL REAGRUPADO/SOLICITANTE")
    write_log(session_dir, "Espera humana EX02: reagrupante -> reagrupado/solicitante")
    return wait_for_human_navigation(
        browser,
        session_dir,
        "Datos del reagrupado/solicitante",
        "document.getElementById('extNombre') || document.getElementById('extNie') || document.getElementById('extPasaporte') || document.getElementById('extNacionalidad')",
        timeout=300,
        fallback_prompt="Pulsa ENTER cuando estés en Datos del reagrupado/solicitante...",
        qcc_reporter=reporter,
        qcc_step="CONTINUE_TO_APPLICANT",
        qcc_progress=52,
    )


def click_continuar_ex02_reagrupado_to_presentador(
    browser,
    session_dir,
    reporter=None,
):
    """Espera humana desde Datos del reagrupado/solicitante a Datos del presentador."""
    print("[9] ESPERA HUMANA - CONTINUAR a DATOS DEL PRESENTADOR")
    write_log(session_dir, "Espera humana EX02: reagrupado/solicitante -> presentador")
    return wait_for_human_navigation(
        browser,
        session_dir,
        "Datos del presentador",
        "document.getElementById('preNombrePresentador')",
        timeout=300,
        fallback_prompt="Pulsa ENTER cuando estés en Datos del presentador...",
        qcc_reporter=reporter,
        qcc_step="CONTINUE_TO_PRESENTER",
        qcc_progress=68,
    )


def click_continuar_extranjero_to_familiar(
    browser,
    session_dir,
    reporter=None,
    action_client=None,
    abort_handler=None,
):
    """
    Avance humano desde Datos del extranjero/a a Datos del familiar en EX01 familiar.

    QCC_EX01_R6_FAMILIAR_131: postcondición = panel Datos del familiar
    como único activo (no la mera presencia de rea*); sin fallback ENTER.
    """
    print("[8] PAUSA HUMANA - CONTINUAR a DATOS DEL FAMILIAR")
    write_log(session_dir, "Pausa humana obligatoria: continuar extranjero -> familiar")

    print()
    print("=" * 80)
    print("PAUSA HUMANA")
    print("Pulsa MANUALMENTE CONTINUAR para pasar a Datos del familiar.")
    print("=" * 80)

    return wait_for_human_navigation(
        browser,
        session_dir,
        "Datos del familiar",
        _EX01_FAMILY_SURFACE_JS,
        timeout=300,
        allow_console_fallback=False,
        qcc_reporter=reporter,
        qcc_step="CONTINUE_TO_FAMILY_MEMBER",
        qcc_progress=52,
        action_client=action_client,
        abort_handler=abort_handler,
    )


def click_continuar_familiar_to_presentador(
    browser,
    session_dir,
    reporter=None,
    action_client=None,
    abort_handler=None,
):
    """
    Avance humano desde Datos del familiar a Datos del presentador en EX01 familiar.

    QCC_EX01_R6_FAMILIAR_131: postcondición = panel Datos del presentador
    como único activo (preNombrePresentador existe desde el inicio en el
    DOM de una sola página); sin fallback ENTER.
    """
    print("[9] PAUSA HUMANA - CONTINUAR a DATOS DEL PRESENTADOR")
    write_log(session_dir, "Pausa humana obligatoria: continuar familiar -> presentador")

    print()
    print("=" * 80)
    print("PAUSA HUMANA")
    print("Pulsa MANUALMENTE CONTINUAR para pasar desde Datos del familiar a Datos del presentador.")
    print("=" * 80)

    return wait_for_human_navigation(
        browser,
        session_dir,
        "Datos del presentador",
        EX01_TITULAR_PRESENTER_SURFACE_JS,
        timeout=300,
        allow_console_fallback=False,
        qcc_reporter=reporter,
        qcc_step="CONTINUE_TO_PRESENTER",
        qcc_progress=68,
        action_client=action_client,
        abort_handler=abort_handler,
    )



def click_continuar(
    browser,
    session_dir,
    reporter=None,
    action_client=None,
    abort_handler=None,
    ex01_titular=False,
):
    """
    Avance seguro desde Datos del extranjero/a a Datos del presentador.

    Mercurio genera error cuando este click se automatiza.
    Por tanto, este punto queda estrictamente humano:
    - NO click JS
    - NO keyboard
    - NO CDP click
    - NO Selenium click

    El usuario pulsa CONTINUAR manualmente y el script solo espera confirmación.

    QCC_EX01_RENOVACION_TITULAR_130_V1: con ``ex01_titular`` la
    postcondición es el panel Datos del presentador como único activo
    (no la mera presencia del nodo) y no hay fallback ENTER.
    """
    print("[8] PAUSA HUMANA - CONTINUAR a DATOS DEL PRESENTADOR")
    write_log(session_dir, "Pausa humana obligatoria: continuar extranjero -> presentador")

    print()
    print("=" * 80)
    print("PAUSA HUMANA")
    print("Pulsa MANUALMENTE el botón CONTINUAR en Mercurio")
    print("para pasar desde Datos del extranjero/a a Datos del presentador.")
    print()
    print("Cuando estés en Datos del presentador, vuelve aquí y pulsa ENTER.")
    print("=" * 80)

    if ex01_titular:
        return wait_for_human_navigation(
            browser,
            session_dir,
            "Datos del presentador",
            EX01_TITULAR_PRESENTER_SURFACE_JS,
            timeout=300,
            allow_console_fallback=False,
            qcc_reporter=reporter,
            qcc_step="CONTINUE_TO_PRESENTER",
            qcc_progress=68,
            action_client=action_client,
            abort_handler=abort_handler,
        )

    return wait_for_human_navigation(
        browser,
        session_dir,
        "Datos del presentador",
        "document.getElementById('preNombrePresentador')",
        timeout=300,
        fallback_prompt="Pulsa ENTER cuando estés en Datos del presentador...",
        qcc_reporter=reporter,
        qcc_step="CONTINUE_TO_PRESENTER",
        qcc_progress=68,
        action_client=action_client,
        abort_handler=abort_handler,
    )



def hardcode_presentador_asturias_oviedo(browser, session_dir):
    """
    Fuerza SOLO provincia/municipio/localidad del presentador.

    Valores Mercurio:
    - Provincia ASTURIAS = 33
    - Municipio OVIEDO = 44
    - Localidad OVIEDO = 190100

    No espera AJAX: si las options no existen, las crea y selecciona.
    """
    write_log(session_dir, "Hardcode presentador: ASTURIAS / OVIEDO / OVIEDO")

    script = """
    (function(){
        function ensureOption(select, value, text) {
            if (!select) return false;
            let found = false;
            for (const opt of select.options || []) {
                if ((opt.value || '').toString() === value) {
                    found = true;
                    break;
                }
            }
            if (!found) {
                const opt = document.createElement('option');
                opt.value = value;
                opt.textContent = text;
                select.appendChild(opt);
            }
            select.value = value;
            select.dispatchEvent(new Event('input', {bubbles:true}));
            select.dispatchEvent(new Event('change', {bubbles:true}));
            if (window.jQuery) window.jQuery(select).trigger('change');
            return true;
        }

        const provincia = document.getElementById('preCodigoProvinciaPresentador');
        const municipio = document.getElementById('preCodigoMunicipioPresentador');
        const localidad = document.getElementById('preCodigoLocalidadPresentador');

        const okProvincia = ensureOption(provincia, '33', 'ASTURIAS');

        if (typeof controlaProvinciaPRE === 'function') {
            try { controlaProvinciaPRE(); } catch(e) {}
        }

        const okMunicipio = ensureOption(municipio, '44', 'OVIEDO');
        const okLocalidad = ensureOption(localidad, '190100', 'OVIEDO');

        return {
            ok: !!(okProvincia && okMunicipio && okLocalidad),
            provincia: provincia ? provincia.value : null,
            municipio: municipio ? municipio.value : null,
            localidad: localidad ? localidad.value : null
        };
    })();
    """

    result = js(browser, script)
    write_log(session_dir, f"HARDCODE presentador ubicación -> {result}")
    return result


def fill_datos_presentador(browser, datos_mercurio, session_dir):
    """
    Vuelca datos_mercurio['representante'] y fuerza ASTURIAS/OVIEDO.

    QCC_EX01_R6_POSTFORM: bajo VOLCAR DATOS (EX01 130/131) es la
    continuación del mismo preload sobre la superficie del presentador
    alcanzada por el CONTINUAR humano.
    """
    preload = _active_mapper_preload(browser)
    if preload is not None:
        return bool(preload.resume(("representante",)).get("ok"))
    print("[9] Rellenando DATOS DEL PRESENTADOR")
    write_log(session_dir, "Rellenando datos del presentador")

    representante = datos_mercurio.get("representante", {}) or {}
    if not representante:
        write_log(session_dir, "Representante vacío en datos_mercurio.json")
        print("No hay bloque representante en datos_mercurio.json")
        return False

    wait_for_js(browser, "document.getElementById('preNombrePresentador')", timeout=15, interval=0.5)

    with governed_section(browser, session_dir, label="PRESENTER"):
        result = fill_section(browser, representante, session_dir)
        if not result["ok"]:
            write_log(session_dir, f"Datos del presentador detenidos: {result}")
            return False

        select_municipio_localidad_presentador(browser, representante, session_dir)

    print("Datos del presentador rellenados.")
    write_log(session_dir, "Datos del presentador rellenados")
    return True


def fill_datos_notificacion(browser, datos_mercurio, session_dir):
    """Bloque ``notificacion`` del VOLCAR DATOS EX01 (130/131).

    QCC_EX01_R6_POSTFORM: nunca se escribe ni se verifica con su pestaña
    oculta (Mercurio la bloquea y re-hidrata en el CONTINUAR humano del
    presentador). Solo cuando la superficie Notificación/CONCLUIR está
    activa se continúa el mismo preload sobre ella. ``None`` = no hay
    VOLCAR de mapper en curso o la superficie no está activa: sus campos
    siguen diferidos y el volcado no se completa (fail closed).
    """
    preload = _active_mapper_preload(browser)
    if preload is None or not preload.started:
        return None
    if not _notification_section_active(browser):
        write_log(session_dir, "NOTIFICATION_SURFACE_NOT_ACTIVE writes=NO")
        return None
    return preload.resume(("notificacion",))


def _notification_section_active(browser):
    try:
        return bool(
            js(browser, _one_line_js(POST_PRESENTER_NOTIFICATION_READY_JS))
        )
    except Exception:
        return False


POST_PRESENTER_NOTIFICATION_READY_JS = """
(() => {
    const notification =
        document.getElementById(
            'tab-datos_notificacion'
        );

    const presenter =
        document.getElementById(
            'tab-datos_presentador'
        );

    const conclude =
        document.getElementById(
            'btnConcluirSup'
        );

    if (!notification || !conclude) {
        return false;
    }

    const visible = (element) => {
        const style =
            window.getComputedStyle(
                element
            );

        return (
            style.display !== 'none'
            && style.visibility !== 'hidden'
            && element.getClientRects().length > 0
        );
    };

    const notificationActive = (
        notification.classList.contains(
            'r-tabs-state-active'
        )
        && visible(notification)
    );

    const concludeVisible =
        visible(conclude);

    const presenterInactive = (
        !presenter
        || !presenter.classList.contains(
            'r-tabs-state-active'
        )
        || !visible(presenter)
    );

    return (
        notificationActive
        && concludeVisible
        && presenterInactive
    );
})()
""".strip()


def _presenter_transition_ready_js():
    """
    Acepta tanto la pantalla intermedia
    Notificación/CONCLUIR como el destino documental.

    Esto evita perder una transición si el usuario
    avanza más rápido que el polling del runner.
    """

    from backend.automation.mercurio_document_dom_reader import (
        MERCURIO_DOCUMENT_PAGE_READY_EXPRESSION,
    )

    return (
        "("
        + POST_PRESENTER_NOTIFICATION_READY_JS
        + ") || ("
        + MERCURIO_DOCUMENT_PAGE_READY_EXPRESSION
        + ")"
    )


def _read_mercurio_document_page_state(
    browser,
):
    """
    Devuelve estado documental únicamente cuando
    la pantalla documental está realmente reconocida.

    Fallos de lectura se tratan como ausencia de
    pantalla documental; nunca provocan navegación.
    """

    from backend.automation.mercurio_document_dom_reader import (
        read_mercurio_document_state,
    )

    try:
        state = (
            read_mercurio_document_state(
                browser
            )
        )

    except Exception:
        return None

    if (
        state.page_detected
        and state.contract_compatible
    ):
        return state

    return None


def click_continuar_presentador(
    browser,
    session_dir,
    reporter=None,
    action_client=None,
    abort_handler=None,
):
    """
    Espera el CONTINUAR manual desde Datos del presentador.

    QCC/SeleniumBase solo observan la transición:
    - NO click JS
    - NO keyboard
    - NO CDP click
    - NO Selenium click

    La transición se considera confirmada cuando:
    - Notificación está activa y visible.
    - CONCLUIR está visible.
    - Presentador ya no está activo/visible.
    """

    print(
        "[10] PAUSA HUMANA - "
        "CONTINUAR desde DATOS DEL PRESENTADOR"
    )

    write_log(
        session_dir,
        "Pausa humana obligatoria: "
        "continuar presentador -> notificación",
    )

    print()
    print("=" * 80)
    print("PAUSA HUMANA")
    print(
        "Pulsa MANUALMENTE CONTINUAR "
        "desde Datos del presentador."
    )
    print(
        "El script continuará al detectar "
        "la pantalla de notificación / CONCLUIR."
    )
    print("=" * 80)

    result = wait_for_human_navigation(
        browser,
        session_dir,
        (
            "Domicilio de notificación / "
            "CONCLUIR"
        ),
        _presenter_transition_ready_js(),
        timeout=300,
        interval=0.5,
        fallback_prompt=(
            "Pulsa ENTER solo si ya estás "
            "en la pantalla de notificación "
            "y ves CONCLUIR..."
        ),
        qcc_reporter=reporter,
        qcc_step="CONTINUE_FROM_PRESENTER",
        qcc_progress=78,
        action_client=action_client,
        abort_handler=abort_handler,
    )

    write_log(
        session_dir,
        "Continuar presentador confirmado "
        f"por modo={result.get('mode')}",
    )

    return result

DOCUMENT_UPLOAD_READY_JS = """
(() => {
    const container =
        document.getElementById(
            'tbAdjuntos'
        );

    const fileInput =
        document.getElementById(
            'fileDocumentoAdjuntos'
        );

    const browse =
        document.getElementById(
            'addDou'
        );

    const documentType =
        document.getElementById(
            'docAdjuntarAdjuntos'
        );

    if (
        !container
        || !fileInput
        || !browse
        || !documentType
    ) {
        return false;
    }

    const visible = (element) => {
        const style =
            window.getComputedStyle(
                element
            );

        return (
            style.display !== 'none'
            && style.visibility !== 'hidden'
            && element.getClientRects().length > 0
        );
    };

    return (
        visible(container)
        && visible(fileInput)
        && visible(browse)
        && visible(documentType)
    );
})()
""".strip()


def pause_humana_final_presentacion(
    browser,
    session_dir,
    reporter=None,
    action_client=None,
    abort_handler=None,
):
    """
    Espera la acción humana CONCLUIR.

    QCC/SeleniumBase no pulsan CONCLUIR.
    El avance se confirma observando la pantalla
    documental real de Mercurio.
    """

    print()
    print("=" * 80)
    print("PAUSA HUMANA FINAL")
    print(
        "El bot ha terminado el volcado "
        "de datos."
    )
    print(
        "Revisa la solicitud y pulsa "
        "CONCLUIR manualmente en Mercurio."
    )
    print(
        "El script continuará al detectar "
        "la pantalla documental."
    )
    print("=" * 80)

    write_log(
        session_dir,
        (
            "Pausa humana final: "
            "esperando CONCLUIR -> "
            "pantalla documental"
        ),
    )

    document_state = (
        _read_mercurio_document_page_state(
            browser
        )
    )

    if document_state is not None:
        result = {
            "ok": True,
            "mode":
                "document_dom_already_ready",
            "label":
                "Documentación de la solicitud",
        }

        write_log(
            session_dir,
            (
                "Pantalla documental ya presente; "
                "se omite espera FINAL_REVIEW"
            ),
        )

    else:
        result = wait_for_human_navigation(
            browser,
            session_dir,
            "Documentación de la solicitud",
            DOCUMENT_UPLOAD_READY_JS,
            timeout=300,
            interval=0.5,
            fallback_prompt=(
                "Pulsa ENTER solo si ya estás "
                "en la pantalla de documentación "
                "de Mercurio..."
            ),
            qcc_reporter=reporter,
            qcc_step="FINAL_REVIEW",
            qcc_progress=82,
            action_client=action_client,
            abort_handler=abort_handler,
        )

        # With QCC there is no ENTER fallback: an abort or a timeout
        # never reports DOCUMENTS_READY for an unconfirmed screen.
        if _is_qcc_aborted_result(result) or (
            _qcc_action_channel_available(action_client)
            and not result.get("ok")
        ):
            return result

    qcc_report(
        reporter,
        "waiting_user",
        session_dir,
        step="DOCUMENTS_READY",
        progress=88,
        message=(
            "Pantalla documental preparada; "
            "documentación pendiente"
        ),
    )

    write_log(
        session_dir,
        (
            "Pantalla documental confirmada "
            f"por modo={result.get('mode')}"
        ),
    )

    return result


def wait_for_qcc_fill_start(
    action_client,
    session_dir,
    reporter=None,
    *,
    abort_handler=None,
    poll_interval=0.25,
):
    """READY_TO_FILL -> VOLCAR DATOS (QCC_ASSISTED_OPERATOR_CONTROLS_V1).

    Presentación asistida SEMI-AUTOMÁTICA: el formulario ya está en
    pantalla (EX01_CANDIDATE_DETECTED) y este punto detiene el flujo
    hasta que el operador pulse explícitamente VOLCAR DATOS desde
    QCC. Nunca cae al fallback de ENTER por consola ni aplica un
    timeout de 300s propio: permanece esperando la acción explícita
    (o un ABORTAR PRESENTACIÓN, atendido aquí con prioridad).

    La espera ocurre en el hilo principal. QCC no controla
    directamente SeleniumBase: solo delega en ``abort_handler`` (el
    cierre gobernado ya certificado) cuando el operador aborta.
    """

    qcc_report(
        reporter,
        "waiting_user",
        session_dir,
        step="READY_TO_FILL",
        progress=35,
        message="Formulario listo para volcar datos",
    )

    write_log(
        session_dir,
        "READY_TO_FILL: esperando VOLCAR_DATOS/"
        "PRESENTATION_ABORT desde QCC",
    )

    if not _qcc_action_channel_available(action_client):
        write_log(
            session_dir,
            (
                "READY_TO_FILL: QCC action client no "
                "disponible; el volcado permanece "
                "pendiente de acción explícita"
            ),
        )

        return {
            "ok": False,
            "mode": "fill_start_channel_unavailable",
        }

    while True:
        action = _service_qcc_operator_action(
            action_client,
            session_dir,
            reporter=reporter,
            abort_handler=abort_handler,
            step="READY_TO_FILL",
            expected_actions=("PRESENTATION_FILL_START",),
        )

        if _is_qcc_aborted_result(action):
            return action

        if action is None:
            time.sleep(
                poll_interval
            )
            continue

        write_log(
            session_dir,
            (
                "QCC_FILL_ACTION_CONSUMED "
                f"action_id={action.get('action_id')} "
                "step=READY_TO_FILL"
            ),
        )

        qcc_report(
            reporter,
            "user_action_detected",
            session_dir,
            step="READY_TO_FILL",
            progress=35,
            message="VOLCAR DATOS confirmado",
        )

        return {
            "ok": True,
            "mode": "fill_start_confirmed",
            "action": action,
        }


def wait_for_qcc_documents_start(
    action_client,
    session_dir,
    reporter=None,
    *,
    abort_handler=None,
    poll_interval=0.25,
):
    """Espera DOCUMENTS_START desde QCC.

    La espera ocurre en el hilo principal.
    QCC no controla directamente SeleniumBase.
    """

    if not _qcc_action_channel_available(action_client):
        write_log(
            session_dir,
            (
                "DOCUMENTOS QCC: "
                "action client no disponible"
            ),
        )

        return None

    print()
    print("=" * 80)
    print("DOCUMENTACIÓN PREPARADA")
    print(
        "Esperando 'Iniciar documentación' "
        "en Quesada Chrome Companion..."
    )
    print("=" * 80)

    write_log(
        session_dir,
        (
            "DOCUMENTOS QCC: "
            "esperando DOCUMENTS_START"
        ),
    )

    while True:
        action = _service_qcc_operator_action(
            action_client,
            session_dir,
            reporter=reporter,
            abort_handler=abort_handler,
            step="DOCUMENTS_READY",
            expected_actions=("DOCUMENTS_START",),
        )

        if _is_qcc_aborted_result(action):
            return action

        if action is None:
            time.sleep(
                poll_interval
            )
            continue

        write_log(
            session_dir,
            (
                "DOCUMENTOS QCC: "
                "DOCUMENTS_START recibido "
                f"action_id="
                f"{action.get('action_id')}"
            ),
        )

        qcc_report(
            reporter,
            "user_action_detected",
            session_dir,
            step="DOCUMENTS_START",
            progress=89,
            message=(
                "Inicio documental solicitado "
                "desde QCC"
            ),
        )

        qcc_report(
            reporter,
            "resuming",
            session_dir,
            step="DOCUMENTS_RUNNING",
            progress=90,
            message=(
                "Iniciando subida documental "
                "asistida"
            ),
        )

        return action



# =============================================================================
# SUBIDA DOCUMENTAL ASISTIDA - PARA PRESENTAR
# =============================================================================

DOCUMENT_ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff"}


def copy_text_to_clipboard(text_value, session_dir=None):
    """
    Copiado robusto al portapapeles.

    Prioridad:
    1) clip.exe recibiendo bytes UTF-16LE para rutas Windows con acentos/espacios.
    2) powershell Set-Clipboard.
    3) tkinter.
    4) pyperclip si está instalado.

    Devuelve True solo si puede verificar que el portapapeles contiene exactamente la ruta.
    """
    value = "" if text_value is None else str(text_value)

    def log(msg):
        if session_dir:
            write_log(session_dir, msg)

    def verify_clipboard(expected):
        # Verificación por PowerShell Get-Clipboard.
        try:
            import subprocess
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            current = (result.stdout or "").strip()
            if current == expected:
                log(f"CLIPBOARD verified powershell OK: {expected}")
                return True
            log(f"CLIPBOARD verify powershell FAIL current={current!r} expected={expected!r}")
        except Exception as exc:
            log(f"CLIPBOARD verify powershell ERROR: {repr(exc)}")

        # Verificación por tkinter.
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            current = root.clipboard_get()
            root.destroy()
            if current == expected:
                log(f"CLIPBOARD verified tkinter OK: {expected}")
                return True
            log(f"CLIPBOARD verify tkinter FAIL current={current!r} expected={expected!r}")
        except Exception as exc:
            log(f"CLIPBOARD verify tkinter ERROR: {repr(exc)}")

        return False

    # 1) clip.exe con UTF-16LE: suele ser lo más fiable para Windows + rutas con acentos.
    try:
        import subprocess
        subprocess.run(
            ["cmd", "/c", "clip"],
            input=value.encode("utf-16le"),
            check=True,
            timeout=5,
        )
        log(f"CLIPBOARD clip.exe UTF-16LE OK: {value}")
        if verify_clipboard(value):
            return True
    except Exception as exc:
        log(f"CLIPBOARD clip.exe UTF-16LE FAIL: {repr(exc)}")

    # 2) PowerShell Set-Clipboard.
    try:
        import subprocess
        ps_value = value.replace("'", "''")
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Set-Clipboard -Value '{ps_value}'"],
            check=True,
            timeout=5,
            capture_output=True,
            text=True,
        )
        log(f"CLIPBOARD powershell Set-Clipboard OK: {value}")
        if verify_clipboard(value):
            return True
    except Exception as exc:
        log(f"CLIPBOARD powershell Set-Clipboard FAIL: {repr(exc)}")

    # 3) tkinter.
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(value)
        root.update()
        root.destroy()
        log(f"CLIPBOARD tkinter OK: {value}")
        if verify_clipboard(value):
            return True
    except Exception as exc:
        log(f"CLIPBOARD tkinter FAIL: {repr(exc)}")

    # 4) pyperclip opcional.
    try:
        import pyperclip
        pyperclip.copy(value)
        log(f"CLIPBOARD pyperclip OK: {value}")
        if verify_clipboard(value):
            return True
    except Exception as exc:
        log(f"CLIPBOARD pyperclip FAIL: {repr(exc)}")

    return False



def get_cliente_nombre_for_documento(datos_mercurio):
    if not isinstance(datos_mercurio, dict):
        return ""

    for source_name in ("extranjero", "cliente", "datos_cliente"):
        source = datos_mercurio.get(source_name, {}) or {}
        if not isinstance(source, dict):
            continue

        nombre = source.get("extNombre") or source.get("nombre") or source.get("nombre_cliente") or ""
        apellido1 = source.get("extApellido1") or source.get("apellido1") or source.get("primer_apellido") or ""
        apellido2 = source.get("extApellido2") or source.get("apellido2") or source.get("segundo_apellido") or ""
        candidate = " ".join(str(x).strip() for x in (nombre, apellido1, apellido2) if str(x).strip())
        if candidate:
            return candidate
    return ""


def build_descripcion_documento(path, datos_mercurio):
    nombre_doc = Path(path).stem.strip()
    nombre_cliente = get_cliente_nombre_for_documento(datos_mercurio).strip()
    descripcion = f"{nombre_doc} - {nombre_cliente}" if nombre_cliente else nombre_doc
    return descripcion[:120]


def resolve_para_presentar_dir(args, datos_mercurio, session_dir):
    candidates = []
    raw = (getattr(args, "documentos_dir", "") or "").strip()
    if raw:
        candidates.append(Path(raw))

    def collect_values(obj):
        if isinstance(obj, dict):
            for v in obj.values():
                yield v
                yield from collect_values(v)
        elif isinstance(obj, list):
            for v in obj:
                yield v
                yield from collect_values(v)

    for value in collect_values(datos_mercurio):
        if isinstance(value, str):
            s = value.strip().strip('"').strip("'")
            if s and not s.lower().startswith(("http://", "https://")):
                if "box" in s.lower() or "para presentar" in normalize(s).lower() or "para_presentar" in normalize(s).lower():
                    candidates.append(Path(s))

    for name in ("datos_mercurio.json", "datos_expediente.json", "session.json", "datos_cliente.json"):
        p = Path(session_dir) / name
        if not p.exists():
            continue
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            for value in collect_values(obj):
                if isinstance(value, str):
                    s = value.strip().strip('"').strip("'")
                    if s and not s.lower().startswith(("http://", "https://")):
                        if "box" in s.lower() or "para presentar" in normalize(s).lower() or "para_presentar" in normalize(s).lower():
                            candidates.append(Path(s))
        except Exception:
            pass

    checked = []
    for candidate in candidates:
        try:
            candidate = Path(candidate)
            checked.append(str(candidate))
            if candidate.exists() and candidate.is_dir() and normalize(candidate.name) == "PARA PRESENTAR":
                return candidate
            pp = candidate / "PARA PRESENTAR"
            if pp.exists() and pp.is_dir():
                return pp
            if "PARA PRESENTAR" in normalize(str(candidate)):
                return candidate
        except Exception:
            continue

    write_log(session_dir, f"PARA PRESENTAR no resuelta. Candidatos revisados: {checked}")
    return None


def list_documentos_para_presentar(documentos_dir, session_dir):
    documentos_dir = Path(documentos_dir) if documentos_dir else None
    if not documentos_dir or not documentos_dir.exists() or not documentos_dir.is_dir():
        write_log(session_dir, f"DOCUMENTOS: carpeta PARA PRESENTAR inválida: {documentos_dir}")
        return []

    if normalize(documentos_dir.name) != "PARA PRESENTAR":
        posible = documentos_dir / "PARA PRESENTAR"
        if posible.exists() and posible.is_dir():
            documentos_dir = posible
        else:
            write_log(session_dir, f"DOCUMENTOS: la carpeta no es PARA PRESENTAR: {documentos_dir}")
            return []

    docs = []
    for path in sorted(documentos_dir.iterdir(), key=lambda p: p.name.lower()):
        if path.is_file() and path.suffix.lower() in DOCUMENT_ALLOWED_EXTENSIONS:
            docs.append(path.resolve())

    write_log(session_dir, f"DOCUMENTOS PARA PRESENTAR detectados: {[str(p) for p in docs]}")
    return docs


def classify_documento_mercurio(path):
    name = normalize(path.name).lower()
    rules = [
        ("1", ["pasaporte", "passport", "titulo viaje", "cedula"]),
        ("30", ["antecedente", "penal", "penales"]),
        ("3", ["vinculo", "familiar", "familia", "matrimonio", "nacimiento", "parentesco"]),
        ("186", ["convivencia", "unidad familiar"]),
        ("187", ["permanencia", "padron", "padrón", "empadronamiento", "historico", "histórico"]),
        ("51", ["tasa", "790", "052"]),
    ]
    for code, keywords in rules:
        for kw in keywords:
            if normalize(kw).lower() in name:
                return code
    return "999"


def preparar_documento_mercurio(browser, path, code, session_dir):
    """Prepara un documento en el Plupload de Mercurio."""

    path = (
        Path(path)
        .expanduser()
        .resolve(strict=True)
    )

    if not path.is_file():
        raise RuntimeError(
            f"MERCURIO_DOCUMENT_NOT_FILE: {path}"
        )

    wait_for_js(
        browser,
        "document.getElementById('docAdjuntarAdjuntos')"
        " && document.getElementById('addDou')"
        " && document.querySelector('.moxie-shim input[type=file]')",
        timeout=25,
    )

    select_by_text_or_value(
        browser,
        "docAdjuntarAdjuntos",
        value=code,
        session_dir=session_dir,
    )
    time.sleep(0.3)

    input_element = browser.find_element(
        ".moxie-shim input[type=file]",
        timeout=20,
    )

    send_file = getattr(
        input_element,
        "send_file",
        None,
    )

    if not callable(send_file):
        raise RuntimeError(
            "MERCURIO_PLUPLOAD_SEND_FILE_UNAVAILABLE"
        )

    send_error = None

    try:
        send_file(str(path))
    except Exception as exc:
        send_error = exc

    deadline = time.monotonic() + 15

    while time.monotonic() < deadline:
        selected = js(
            browser,
            "return "
            "(document.getElementById('fileDocumentoAdjuntos') || {})"
            ".value || '';",
        )

        selected_name = (
            str(selected or "")
            .strip()
            .replace("\\", "/")
            .rsplit("/", 1)[-1]
            .casefold()
        )

        if selected_name == path.name.casefold():
            write_log(
                session_dir,
                "DOCUMENTO Plupload preparado "
                f"path={path} code={code}",
            )
            return True

        time.sleep(0.2)

    if send_error is not None:
        raise RuntimeError(
            "MERCURIO_PLUPLOAD_SEND_FILE_FAILED"
        ) from send_error

    raise RuntimeError(
        "MERCURIO_PLUPLOAD_FILE_NOT_RECONCILED"
    )



def wait_for_qcc_document_action(
    action_client,
    *,
    document_index,
    document_total,
    document_name,
    proposed_code,
    session_dir,
    reporter=None,
    poll_interval=0.25,
):
    """Publica documento actual y espera decisión humana QCC.

    QCC transporta la intención del usuario.
    Este helper NO controla SeleniumBase ni el DOM.
    """

    if action_client is None:
        write_log(
            session_dir,
            (
                "DOCUMENTO QCC: "
                "action client no disponible"
            ),
        )

        return None

    progress = min(
        96,
        90
        + max(
            1,
            int(
                document_index
                * 6
                / max(
                    document_total,
                    1,
                )
            ),
        ),
    )

    qcc_report(
        reporter,
        "waiting_user",
        session_dir,
        step="DOCUMENT_READY",
        progress=progress,
        message=(
            f"Documento {document_index}/"
            f"{document_total}: "
            f"{document_name}"
        ),
        event_details={
            "document_index":
                document_index,
            "document_total":
                document_total,
            "document_name":
                document_name,
            "document_type_code":
                proposed_code,
        },
    )

    write_log(
        session_dir,
        (
            "DOCUMENTO QCC: esperando decisión "
            f"index={document_index} "
            f"name={document_name} "
            f"code={proposed_code}"
        ),
    )

    while True:
        action = (
            action_client
            .consume_next()
        )

        if action is None:
            time.sleep(
                poll_interval
            )
            continue

        action_name = str(
            action.get(
                "action",
                "",
            )
        ).strip()

        payload = (
            action.get(
                "payload",
                {},
            )
            or {}
        )

        if not isinstance(
            payload,
            dict,
        ):
            write_log(
                session_dir,
                (
                    "DOCUMENTO QCC: payload "
                    "inválido descartado"
                ),
            )
            continue

        action_index = payload.get(
            "document_index"
        )

        if action_index != document_index:
            write_log(
                session_dir,
                (
                    "DOCUMENTO QCC: acción "
                    "de otro documento descartada "
                    f"action={action_name or '-'} "
                    f"index={action_index} "
                    f"expected={document_index}"
                ),
            )
            continue

        if action_name not in (
            "DOCUMENT_PREPARE",
            "DOCUMENT_SKIP",
            "DOCUMENT_FORCE_TYPE",
        ):
            write_log(
                session_dir,
                (
                    "DOCUMENTO QCC: acción "
                    "no aplicable descartada "
                    f"{action_name or '-'}"
                ),
            )
            continue

        write_log(
            session_dir,
            (
                "DOCUMENTO QCC: decisión recibida "
                f"action={action_name} "
                f"index={document_index}"
            ),
        )

        qcc_report(
            reporter,
            "user_action_detected",
            session_dir,
            step="DOCUMENT_ACTION",
            progress=progress,
            message=(
                "Decisión documental recibida "
                f"para {document_name}"
            ),
        )

        return action


def _count_confirmed_mercurio_uploads(
    state,
    *,
    filename,
    code,
):
    """
    Cuenta filas que confirman el documento esperado.

    Contrato:
    - mismo nombre de archivo;
    - mismo código documental Mercurio;
    - hash no vacío.

    No depende del id dinámico de la fila.
    """

    expected_filename = (
        Path(
            str(
                filename
                or ""
            )
        )
        .name
        .casefold()
    )

    expected_code = str(
        code
        or ""
    ).strip()

    if (
        not expected_filename
        or not expected_code
    ):
        return 0

    return sum(
        1
        for document
        in getattr(
            state,
            "uploaded_documents",
            (),
        )
        if (
            str(
                getattr(
                    document,
                    "filename",
                    "",
                )
            )
            .strip()
            .casefold()
            == expected_filename
        )
        and (
            str(
                getattr(
                    document,
                    "code",
                    "",
                )
            ).strip()
            == expected_code
        )
        and bool(
            str(
                getattr(
                    document,
                    "hash_value",
                    "",
                )
            ).strip()
        )
    )


def get_mercurio_document_upload_baseline(
    browser,
    *,
    filename,
    code,
):
    """
    Captura cuántas coincidencias válidas existen
    ANTES de preparar la nueva subida.

    El baseline impide confirmar accidentalmente
    una fila antigua del mismo archivo.
    """

    from backend.automation.mercurio_document_dom_reader import (
        read_mercurio_document_state,
    )

    state = (
        read_mercurio_document_state(
            browser
        )
    )

    if not (
        state.page_detected
        and state.contract_compatible
    ):
        raise RuntimeError(
            "MERCURIO_DOCUMENT_BASELINE_"
            "CONTRACT_NOT_READY"
        )

    return (
        _count_confirmed_mercurio_uploads(
            state,
            filename=filename,
            code=code,
        )
    )


def wait_for_mercurio_document_upload(
    browser,
    *,
    filename,
    code,
    baseline_count,
    timeout=180,
    poll_interval=0.5,
    state_reader=None,
):
    """
    Espera exclusivamente observando el DOM.

    Confirma la subida cuando Mercurio muestra una
    nueva fila válida para:
        filename + code + hash.

    No:
    - pulsa botones;
    - modifica campos;
    - usa teclado;
    - usa ENTER;
    - controla el diálogo de archivos.
    """

    if state_reader is None:
        from backend.automation.mercurio_document_dom_reader import (
            read_mercurio_document_state,
        )

        state_reader = (
            read_mercurio_document_state
        )

    baseline_count = max(
        0,
        int(
            baseline_count
            or 0
        ),
    )

    deadline = (
        time.monotonic()
        + max(
            0,
            float(
                timeout
            ),
        )
    )

    last_error = None

    while True:
        try:
            state = state_reader(
                browser
            )

            if (
                state.page_detected
                and state.contract_compatible
            ):
                current_count = (
                    _count_confirmed_mercurio_uploads(
                        state,
                        filename=filename,
                        code=code,
                    )
                )

                if (
                    current_count
                    > baseline_count
                ):
                    return {
                        "ok": True,
                        "mode":
                            "document_dom_confirmed",
                        "filename":
                            Path(
                                str(
                                    filename
                                )
                            ).name,
                        "code":
                            str(
                                code
                            ),
                        "baseline_count":
                            baseline_count,
                        "current_count":
                            current_count,
                    }

        except Exception as exc:
            last_error = repr(
                exc
            )

        if (
            time.monotonic()
            >= deadline
        ):
            return {
                "ok": False,
                "mode":
                    "document_dom_timeout",
                "filename":
                    Path(
                        str(
                            filename
                        )
                    ).name,
                "code":
                    str(
                        code
                    ),
                "baseline_count":
                    baseline_count,
                "last_error":
                    last_error,
            }

        time.sleep(
            max(
                0,
                float(
                    poll_interval
                ),
            )
        )


def upload_documentos_mercurio_asistido(
    browser,
    documentos_dir,
    datos_mercurio,
    session_dir,
    *,
    reporter=None,
    action_client=None,
):
    print()
    print("=" * 80)
    print("SUBIDA DOCUMENTAL ASISTIDA - PARA PRESENTAR")
    print("=" * 80)

    docs = list_documentos_para_presentar(documentos_dir, session_dir)
    if not docs:
        print("No hay documentos válidos en la carpeta PARA PRESENTAR.")
        return False

    print("Documentos que se van a preparar, siempre desde PARA PRESENTAR:")
    for i, p in enumerate(docs, 1):
        print(f"  {i}. {p}")

    write_log(
        session_dir,
        (
            "DOCUMENTOS: inicio autorizado "
            "desde QCC"
        ),
    )

    resultados = []
    for idx, path in enumerate(docs, 1):
        code = classify_documento_mercurio(path)
        print()
        print("-" * 80)
        print(f"Documento {idx}/{len(docs)}")
        print(f"Archivo: {path.name}")
        print(f"Ruta exacta: {path}")
        print(f"Tipo Mercurio propuesto: {code}")
        print("-" * 80)

        action = wait_for_qcc_document_action(
            action_client,
            document_index=idx,
            document_total=len(docs),
            document_name=path.name,
            proposed_code=code,
            session_dir=session_dir,
            reporter=reporter,
        )

        if action is None:
            write_log(
                session_dir,
                (
                    "DOCUMENTO no procesado: "
                    "QCC Action Channel no disponible "
                    f"path={path}"
                ),
            )

            return False

        action_name = str(
            action.get(
                "action",
                "",
            )
        ).strip()

        if action_name == "DOCUMENT_SKIP":
            resultados.append(
                (
                    str(path),
                    "SALTADO",
                )
            )

            write_log(
                session_dir,
                f"DOCUMENTO saltado: {path}",
            )

            continue

        if (
            action_name
            == "DOCUMENT_FORCE_TYPE"
        ):
            payload = (
                action.get(
                    "payload",
                    {},
                )
                or {}
            )

            forced_code = str(
                payload.get(
                    "value",
                    "",
                )
            ).strip()

            if not forced_code:
                write_log(
                    session_dir,
                    (
                        "DOCUMENTO código forzado "
                        "vacío; documento no procesado "
                        f"path={path}"
                    ),
                )

                return False

            code = forced_code

            write_log(
                session_dir,
                (
                    "DOCUMENTO código forzado "
                    f"{path}: {code}"
                ),
            )

        document_progress = min(
            97,
            91
            + int(
                idx
                * 6
                / max(
                    len(docs),
                    1,
                )
            ),
        )

        qcc_report(
            reporter,
            "resuming",
            session_dir,
            step="DOCUMENT_PREPARING",
            progress=document_progress,
            message=(
                f"Preparando {path.name}"
            ),
        )

        try:
            upload_baseline = (
                get_mercurio_document_upload_baseline(
                    browser,
                    filename=path.name,
                    code=code,
                )
            )

        except Exception as exc:
            write_log(
                session_dir,
                (
                    "DOCUMENTO baseline DOM fallido "
                    f"path={path} "
                    f"code={code} "
                    f"error={repr(exc)}"
                ),
            )

            qcc_report(
                reporter,
                "error",
                session_dir,
                step="DOCUMENT_BASELINE_ERROR",
                progress=document_progress,
                message=(
                    "No se pudo validar el estado "
                    f"previo de {path.name}"
                ),
            )

            return False

        preparar_documento_mercurio(
            browser,
            path,
            code,
            session_dir,
        )

        print()
        print("=" * 80)
        print("ACCIÓN HUMANA")
        print("Documento preparado automáticamente en Mercurio:")
        print(path.name)
        print()
        print(
            "Pulsa SUBIR / ADJUNTAR DOCUMENTO "
            "en Mercurio."
        )
        print(
            "El CRM confirmará automáticamente "
            "la incorporación."
        )
        print("=" * 80)

        qcc_report(
            reporter,
            "waiting_user",
            session_dir,
            step="DOCUMENT_ATTACHING",
            progress=document_progress,
            message=(
                "Adjunta manualmente "
                f"{path.name}; "
                "el CRM confirmará la subida"
            ),
        )

        confirmation = (
            wait_for_mercurio_document_upload(
                browser,
                filename=path.name,
                code=code,
                baseline_count=(
                    upload_baseline
                ),
                timeout=180,
                poll_interval=0.5,
            )
        )

        if not confirmation.get(
            "ok"
        ):
            write_log(
                session_dir,
                (
                    "DOCUMENTO no confirmado por DOM "
                    f"path={path} "
                    f"code={code} "
                    f"result={confirmation}"
                ),
            )

            qcc_report(
                reporter,
                "error",
                session_dir,
                step="DOCUMENT_UPLOAD_TIMEOUT",
                progress=document_progress,
                message=(
                    "Mercurio no confirmó "
                    f"la subida de {path.name}"
                ),
            )

            return False

        resultados.append(
            (
                str(path),
                "ADJUNTADO_DOM",
            )
        )

        write_log(
            session_dir,
            (
                "DOCUMENTO confirmado por DOM: "
                f"path={path} "
                f"code={code} "
                f"result={confirmation}"
            ),
        )

        qcc_report(
            reporter,
            "user_action_detected",
            session_dir,
            step="DOCUMENT_UPLOADED",
            progress=document_progress,
            message=(
                "Documento confirmado en Mercurio: "
                f"{path.name}"
            ),
        )

        qcc_report(
            reporter,
            "resuming",
            session_dir,
            step="DOCUMENTS_RUNNING",
            progress=document_progress,
            message=(
                "Continuando con el siguiente "
                "documento"
            ),
        )

    print()
    print("=" * 80)
    print("RESULTADO SUBIDA DOCUMENTAL ASISTIDA")
    print("=" * 80)
    for ruta, estado in resultados:
        print(f"{estado}: {ruta}")
    write_log(session_dir, f"DOCUMENTOS resultado asistido: {resultados}")
    return True


def run_auto_and_documents_with_qcc(
    browser,
    provincia_codigo,
    datos_mercurio,
    documentos_dir,
    session_dir,
    *,
    reporter=None,
    action_client=None,
    abort_handler=None,
):
    """Ejecuta presentación y espera inicio documental QCC."""

    auto_result = run_auto_with_qcc(
        browser,
        provincia_codigo,
        datos_mercurio,
        session_dir,
        reporter=reporter,
        action_client=action_client,
        abort_handler=abort_handler,
    )

    if _is_qcc_aborted_result(auto_result):
        return auto_result

    if _extract_blocked_auto_detail(auto_result) is not None:
        write_log(
            session_dir,
            (
                "DOCUMENTOS no iniciados: "
                "rellenado automático bloqueado; "
                "se conserva el contexto de presentación "
                "para reintento/resolución humana"
            ),
        )

        # El navegador sigue bajo ownership: ABORTAR PRESENTACIÓN
        # debe seguir atendiéndose (espera acotada) antes de volver
        # al menú de consola.
        control_result = wait_for_qcc_operator_control(
            action_client,
            session_dir,
            reporter=reporter,
            abort_handler=abort_handler,
            step="AUTO_FLOW_BLOCKED",
        )

        if _is_qcc_aborted_result(control_result):
            return control_result

        return auto_result

    if not documentos_dir:
        print()
        print(
            "No se ha encontrado carpeta "
            "PARA PRESENTAR."
        )

        write_log(
            session_dir,
            (
                "DOCUMENTOS no iniciados: "
                "carpeta PARA PRESENTAR ausente"
            ),
        )

        qcc_report(
            reporter,
            "error",
            session_dir,
            step="DOCUMENTS_FOLDER_MISSING",
            progress=88,
            message=(
                "No se ha encontrado la carpeta "
                "PARA PRESENTAR"
            ),
        )

        return auto_result

    action = wait_for_qcc_documents_start(
        action_client,
        session_dir,
        reporter=reporter,
        abort_handler=abort_handler,
    )

    if (
        isinstance(action, dict)
        and action.get("mode") == "aborted"
    ):
        return action

    if action is None:
        print()
        print(
            "QCC Action Channel no disponible. "
            "La documentación no se inicia."
        )

        write_log(
            session_dir,
            (
                "DOCUMENTOS no iniciados: "
                "QCC Action Channel no disponible"
            ),
        )

        return auto_result

    return upload_documentos_mercurio_asistido(
        browser,
        documentos_dir,
        datos_mercurio,
        session_dir,
        reporter=reporter,
        action_client=action_client,
    )


def _mapper_navigation_stopped(result):
    """True when a human CONTINUAR wait between mapper sections did not
    confirm the destination screen (abort, timeout, unconfirmed)."""

    return isinstance(result, dict) and not result.get("ok")


def _mapper_navigation_result(result, step):
    if _is_qcc_aborted_result(result):
        return result

    return {
        "ok": False,
        "label": f"{step}_NOT_CONFIRMED",
        "detail": result,
    }


def _mapper_section_blocked(reporter, session_dir, label, detail=None):
    """A mapper section stopped on a genuine required-field /
    postcondition error: the full mapper stops there, fail closed."""

    write_log(session_dir, f"MAPPER_SECTION_BLOCKED label={label}")

    qcc_report(
        reporter,
        "fill_blocked",
        session_dir,
        step="FILL_BLOCKED",
        message=(
            "Rellenado detenido: se requiere "
            "corrección o acción humana"
        ),
        event_details={"label": label},
    )

    result = {"ok": False, "label": label}
    if detail is not None:
        result["detail"] = detail
    return result


# QCC_EX01_R6_POSTFORM: the one VOLCAR DATOS of an EX01 Titular (130) /
# Familiar (131) presentation. Shared post-form logic: the same presenter
# and notification continuation for both procedures.
_ACTIVE_MAPPER_PRELOADS = []


def _active_mapper_preload(browser):
    return next((p for p in reversed(_ACTIVE_MAPPER_PRELOADS) if p.browser is browser), None)


def _preload_dependency_ready_js(field, value, text):
    """Wait for the intended option, not an arbitrary option count or delay."""
    if "TipoVia" in field:
        text = resolve_tipo_via_text(value, text)
    return " ".join((
        "(() => {",
        f"const el = document.getElementById({json.dumps(field)});",
        "if (!el || el.disabled) return false;",
        f"if (!({_field_readiness_js(field)})) return false;",
        "if (el.tagName !== 'SELECT') return true;",
        "const norm = v => String(v || '').trim().toUpperCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').replace(/\\s+/g, ' ');",
        f"const value = {json.dumps(str(value))}; const text = norm({json.dumps(str(text or value))});",
        "const opts = Array.from(el.options || []);",
        "return opts.some(o => (value && o.value === value) || (text && norm(o.textContent) === text)) ||",
        "(!!text && opts.filter(o => { const t = norm(o.textContent); return t && (t.includes(text) || text.includes(t)); }).length === 1);",
        "})()",
    ))


_MAPPER_CASCADE_TOKENS = ("CodigoProvincia", "CodigoMunicipio", "CodigoLocalidad")


def _is_mapper_cascade_field(field):
    """Address cascade member: owned by a specialized helper, never the generic iterator."""
    return any(token in field for token in _MAPPER_CASCADE_TOKENS)


def _run_mapper_cascade(block, browser, values, session_dir):
    """Historical specialized cascade helper for each canonical block."""
    if block == "domicilio_extranjero":
        return select_municipio_localidad(browser, values, session_dir, prefix="ext")
    if block == "notificacion":
        return select_municipio_localidad(browser, values, session_dir, prefix="not")
    if block == "representante":
        return select_municipio_localidad_presentador(browser, values, session_dir)
    return None


# QCC_PRESENTER_ACTIVE_COMPLETION_V1: presenter identity Mercurio itself
# takes from the authenticated certificate and renders readonly. They are
# verification targets: equivalent -> verified, nothing written, never
# retried; different -> fail closed (human). REAL captures: the certificate
# name is surname-first while the mapper is given-name-first (same tokens).
CERTIFICATE_IDENTITY_VERIFIED = "CERTIFICATE_IDENTITY_VERIFIED"
CERTIFICATE_IDENTITY_MISMATCH = "CERTIFICATE_IDENTITY_MISMATCH"
_CERTIFICATE_NAME_FIELDS = frozenset({"preNombrePresentador"})
_CERTIFICATE_DOCUMENT_FIELDS = frozenset({"preNiePresentador"})
_CERTIFICATE_SELECT_FIELDS = frozenset({"preTipodocumentoPresentador"})
_CERTIFICATE_IDENTITY_FIELDS = (
    _CERTIFICATE_NAME_FIELDS | _CERTIFICATE_DOCUMENT_FIELDS | _CERTIFICATE_SELECT_FIELDS
)
# QCC_NOTIFICATION_CERTIFICATE_AUTHORITY_V1: the Notification identity is
# managed by Mercurio from the authenticated certificate. It is never a
# client mapper target: never written, never compared with the mapper
# value; its only reference is the already verified Presenter identity.
_NOTIFICATION_PRESENTER_IDENTITY = {
    "notNombreNotificacion": "preNombrePresentador",
    "notTipodocumentoNotificacion": "preTipodocumentoPresentador",
    "notNieNotificacion": "preNiePresentador",
}
NOTIFICATION_IDENTITY_SOURCE = "PRESENTER_CERTIFICATE"
# QCC_NOTIFICATION_LOCKED_CONTACT_V1: on the active final Notification
# surface Mercurio locks (readonly + disableLnk) and re-hydrates the
# contact controls together with the identity block (local captures).
# A locked one is Mercurio-managed: its live value is preserved, never
# rewritten nor compared with the mapper. Editable -> ordinary write.
_NOTIFICATION_LOCKED_CONTACT_FIELDS = frozenset({"notTelefonoMovilNotificacion", "notEmailNotificacion"})
NOTIFICATION_CONTACT_MERCURIO_MANAGED = "NOTIFICATION_CONTACT_MERCURIO_MANAGED"


def _certificate_name_tokens(value):
    """Case/accent/punctuation/whitespace-insensitive token multiset.
    Order-insensitive ONLY for the certificate name, multiplicity kept."""
    return Counter(re.sub(r"[^\w\s]", " ", normalize(value)).split())


def _certificate_document_canonical(value):
    return re.sub(r"[^0-9A-Z]", "", normalize(value))


def _certificate_identity_present(browser, field_id):
    """Mercurio exposes the control write-blocked AND already holding a value."""
    probe = _probe_field_locally(browser, field_id)
    if not probe or probe.get("exists") is not True:
        return False
    if not (probe.get("disabled") is True or _probe_signals_block_write(probe)):
        return False
    state = _read_field_state(browser, field_id)
    if not state or not state.get("exists"):
        return False
    if field_id in _CERTIFICATE_SELECT_FIELDS:
        return bool(state.get("selected_value")) and state.get("selected_index", -1) >= 0
    return bool(str(state.get("value") or "").strip())


def _certificate_identity_matches(browser, field_id, value, text):
    if field_id in _CERTIFICATE_SELECT_FIELDS:
        # Same canonical SELECT equivalence as select_by_text_or_value.
        return _select_option_satisfied(
            browser, field_id, str(value or "").strip(), normalize(text or value)
        )
    state = _read_field_state(browser, field_id)
    if not state or not state.get("exists"):
        return False
    live = state.get("value")
    if field_id in _CERTIFICATE_NAME_FIELDS:
        tokens = _certificate_name_tokens(live)
        return bool(tokens) and tokens == _certificate_name_tokens(value)
    canonical = _certificate_document_canonical(live)
    return bool(canonical) and canonical == _certificate_document_canonical(value)


def _selected_option(state):
    """(value, normalized text) of a real selected option, else empty."""
    selected = state.get("selected_value")
    if not selected or state.get("selected_index", -1) < 0 or state.get("value") != selected:
        return "", ""
    return selected, normalize(state.get("selected_text"))


def _notification_identity_matches_presenter(browser, field_id):
    """Live Notification identity vs the live Presenter certificate
    identity, with the same scoped certificate equivalence."""

    presenter = _NOTIFICATION_PRESENTER_IDENTITY[field_id]
    live, reference = _read_field_state(browser, field_id), _read_field_state(browser, presenter)
    if not (live and live.get("exists") and reference and reference.get("exists")):
        return False
    if presenter in _CERTIFICATE_SELECT_FIELDS:
        (value, text), (ref_value, ref_text) = _selected_option(live), _selected_option(reference)
        return bool(value and ref_value) and (value == ref_value or bool(text) and text == ref_text)
    if presenter in _CERTIFICATE_NAME_FIELDS:
        tokens = _certificate_name_tokens(live.get("value"))
        return bool(tokens) and tokens == _certificate_name_tokens(reference.get("value"))
    canonical = _certificate_document_canonical(live.get("value"))
    return bool(canonical) and canonical == _certificate_document_canonical(reference.get("value"))


# Optional "Representante legal, en su caso" group of the presenter. Without
# substantive data (the document type alone is only a placeholder) it is
# NOT_APPLICABLE: never attempted, deferred or blocking.
_PRESENTER_LEGAL_REPRESENTATIVE_FIELDS = frozenset("""
    preNombreRepresentantePresentador preTipodocumentoRepresentantePresentador
    preNieRepresentantePresentador preTituloRepresentantePresentador
    preTelefonoMovilRepLegalPresentador preEmailRepLegalPresentador
""".split())
_PRESENTER_LEGAL_REPRESENTATIVE_SUBSTANTIVE = (
    _PRESENTER_LEGAL_REPRESENTATIVE_FIELDS - {"preTipodocumentoRepresentantePresentador"}
)
_OPTIONAL_LEGAL_REPRESENTATIVE_GROUPS = {
    "representante": (
        "REPRESENTANTE_LEGAL_PRESENTADOR", _PRESENTER_LEGAL_REPRESENTATIVE_FIELDS,
        _PRESENTER_LEGAL_REPRESENTATIVE_SUBSTANTIVE,
    ),
}


def _drop_inapplicable_optional_groups(block, values, session_dir):
    if block not in _OPTIONAL_LEGAL_REPRESENTATIVE_GROUPS:
        return values
    group, fields, substantive = _OPTIONAL_LEGAL_REPRESENTATIVE_GROUPS[block]
    if any(str(values.get(f) or values.get(f + "_text") or "").strip() for f in substantive):
        return values
    dropped = sorted({k.removesuffix("_text") for k in values} & fields)
    if not dropped:
        return values
    write_log(
        session_dir,
        f"OPTIONAL_GROUP_NOT_APPLICABLE group={group} fields={dropped}",
    )
    return {k: v for k, v in values.items() if k.removesuffix("_text") not in dropped}


# QCC_NOTIFICATION_FINAL_GATE_V1: conditional Notification address controls.
# No local REAL capture of the notification surface ever rendered them and
# the historical writer always logged them NO_EXISTE without blocking.
# Identity/contact controls are deliberately excluded: missing on the
# active surface they still fail closed.
_NOTIFICATION_CONDITIONAL_ADDRESS_FIELDS = frozenset("""
    notDomicilioNotificacion notTipoViaNotificacion notNumeroNotificacion
    notPisoNotificacion notCodigoPostalNotificacion notCodigoProvinciaNotificacion
    notCodigoMunicipioNotificacion notCodigoLocalidadNotificacion
""".split())

_MAPPER_BLOCK_LABELS = {
    "extranjero": "EXTRANJERO_BLOCKED",
    "domicilio_extranjero": "EXTRANJERO_BLOCKED",
    "representante": "PRESENTADOR_BLOCKED",
    "notificacion": "NOTIFICACION_BLOCKED",
}
# QCC_EX01_R11_FIX3_CASCADE: blocks whose address cascade is mandatory on
# the surface where the VOLCAR runs (Datos del extranjero/a, shared by 130
# and 131). Presenter/notification cascades keep their deferral until the
# final ``_mapper_preload_pending`` validation.
_ACTIVE_SURFACE_CASCADE_BLOCKS = frozenset({"domicilio_extranjero"})
# Blocks fill_datos_extranjero must leave verified before FILLED.
_EXTRANJERO_SURFACE_BLOCKS = ("extranjero", "domicilio_extranjero")


class _MapperPreload:
    """One VOLCAR command: canonical payload, deferred queue and verified
    readbacks.

    QCC_EX01_R6_POSTFORM: a block is only written on its own surface,
    once human navigation reached it (``resume(active_blocks)``); any
    other block is deferred, never written on a hidden tab. Notification
    is not even read until its surface is the active one. The family
    surface of 131 stays owned by ``fill_datos_familiar_ex01``.
    """

    def __init__(self, browser, datos, session_dir, navigation):
        self.browser = browser
        self.session_dir = session_dir
        self.navigation = navigation
        self.blocks = ["extranjero", "domicilio_extranjero", "representante", "notificacion"]
        self.values = {
            block: _drop_inapplicable_optional_groups(
                block, _project_mapper_fields(block, datos.get(block), session_dir), session_dir
            )
            for block in self.blocks
        }
        self.verified = {}
        self.deferred = {}
        self.required_blocks = set()
        self.cascaded = set()
        self.aborted = None
        self.started = False

    def _certificate_identity(self, field, values):
        """Verifies (never writes) a certificate-managed presenter identity
        field that Mercurio already exposes write-blocked with a value.
        ``None`` = not a certificate-held control: ordinary handling."""

        value, text = values.get(field, ""), values.get(field + "_text", "")
        if (field not in _CERTIFICATE_IDENTITY_FIELDS or not value
                or not _certificate_identity_present(self.browser, field)):
            return None

        def check():
            return _certificate_identity_matches(self.browser, field, value, text)

        if not check():
            write_log(self.session_dir, f"{CERTIFICATE_IDENTITY_MISMATCH} field={field}")
            return CERTIFICATE_IDENTITY_MISMATCH
        self.verified[field] = check
        self.deferred.pop(field, None)
        write_log(self.session_dir, f"{CERTIFICATE_IDENTITY_VERIFIED} field={field}")
        return CERTIFICATE_IDENTITY_VERIFIED

    def _notification_identity(self, field, block):
        """Verifies (never writes) a Notification identity field against the
        already verified Presenter certificate identity. Before the surface
        is reached a difference is only deferred; on the active surface it
        fails closed. ``None`` = not a Notification identity field."""

        if field not in _NOTIFICATION_PRESENTER_IDENTITY:
            return None
        presenter = _NOTIFICATION_PRESENTER_IDENTITY[field]

        def check():
            verify = self.verified.get(presenter)
            return bool(verify and verify()) and _notification_identity_matches_presenter(self.browser, field)

        source = f"field={field} source={NOTIFICATION_IDENTITY_SOURCE}"
        if check():
            self.verified[field] = check
            self.deferred.pop(field, None)
            write_log(self.session_dir, f"{CERTIFICATE_IDENTITY_VERIFIED} {source}")
            return CERTIFICATE_IDENTITY_VERIFIED
        if block not in self.required_blocks:
            self.deferred[field] = GOVERNED_OUTCOME_DEFERRED_DEPENDENCY
            write_log(self.session_dir, f"NOTIFICATION_IDENTITY_DEFERRED {source}")
            return GOVERNED_OUTCOME_DEFERRED_DEPENDENCY
        outcome = (CERTIFICATE_IDENTITY_MISMATCH if field_exists(self.browser, field)
                   else "REQUIRED_ACTIVE_MISSING")
        write_log(self.session_dir, f"{outcome} {source}")
        return outcome

    def _notification_locked_contact(self, field, block):
        """Settles (never writes) a Notification contact control that
        Mercurio holds write-blocked on the active final Notification
        surface. ``False`` = ordinary mapper write/postcondition."""

        if (field not in _NOTIFICATION_LOCKED_CONTACT_FIELDS or block != "notificacion"
                or block not in self.required_blocks):
            return False

        def check():
            probe = _probe_field_locally(self.browser, field)
            return (bool(probe) and _probe_write_blocked_on_surface(probe)
                    and _notification_section_active(self.browser))

        if not check():
            return False
        self.verified[field] = check
        self.deferred.pop(field, None)
        write_log(self.session_dir,
                  f"{NOTIFICATION_CONTACT_MERCURIO_MANAGED} field={field} outcome=PRESERVED_LIVE")
        return True

    def _settle_absent_notification_fields(self):
        """Historical NOTIFICATION_FIELDS_ABSENT contract, once Notification
        is definitively active: a conditional address control that is not
        on this surface is NOT_APPLICABLE, never left deferred."""

        values = self.values.get("notificacion")
        if not values or not _notification_section_active(self.browser):
            return
        absent = sorted(
            f for f in {k.removesuffix("_text") for k in values} & _NOTIFICATION_CONDITIONAL_ADDRESS_FIELDS
            if not field_exists(self.browser, f)
        )
        if not absent:
            return
        write_log(self.session_dir, f"NOTIFICATION_FIELDS_ABSENT fields={absent} outcome=NOT_APPLICABLE")
        self.values["notificacion"] = {
            k: v for k, v in values.items() if k.removesuffix("_text") not in absent
        }
        for field in absent:
            self.deferred.pop(field, None)
            self.verified.pop(field, None)

    def _defer_notification(self, values):
        """QCC_EX01_R6_POSTFORM: Notification surface not reached by human
        navigation: nothing written, read nor compared yet."""

        pending = sorted(
            f for f in {k.removesuffix("_text") for k in values} if f not in self.verified
        )
        for field in pending:
            self.deferred.setdefault(field, GOVERNED_OUTCOME_DEFERRED_DEPENDENCY)
        if pending:
            write_log(
                self.session_dir,
                f"NOTIFICATION_DEFERRED_UNTIL_ACTIVE fields={len(pending)} writes=NO",
            )

    def _service_operator_action(self):
        control = _service_qcc_operator_action(
            self.navigation.get("action_client"), self.session_dir,
            reporter=self.navigation.get("reporter"),
            abort_handler=self.navigation.get("abort_handler"), step="MAPPER_PRELOAD",
        )
        if _is_qcc_aborted_result(control):
            self.aborted = control
            return control
        return None

    def _resume_cascade(self, block, values):
        """Runs the block's specialized address cascade once its surface is reached.

        It is re-run only if a member it verified was later cleared, or a
        member is still deferred. A DENIED parent never written stays
        unverified and is reported (see ``_run_governed_cascade``); any
        other member not verified fails closed.
        """
        members = sorted(
            (f for f in _CANONICAL_MAPPER_FIELDS[block]
             if _is_mapper_cascade_field(f) and (values.get(f) or values.get(f + "_text"))),
            key=lambda f: next(i for i, t in enumerate(_MAPPER_CASCADE_TOKENS) if t in f),
        )
        if not members:
            return None
        if block not in self.required_blocks:
            for field in members:
                self.deferred.setdefault(field, GOVERNED_OUTCOME_DEFERRED_DEPENDENCY)
            return None
        levels = [f for f in _CANONICAL_MAPPER_FIELDS[block] if _is_mapper_cascade_field(f)]
        if block in self.cascaded:
            lost = [f for f in members if f in self.verified and not self.verified[f]()]
            if not lost and not any(f in self.deferred for f in levels):
                return None
        if self._service_operator_action() is not None:
            return self.aborted
        for field in levels:
            self.verified.pop(field, None)
            self.deferred.pop(field, None)
        write_log(self.session_dir, f"MAPPER_CASCADE_START block={block} fields={members}")
        result = _run_mapper_cascade(block, self.browser, values, self.session_dir)
        if self.aborted:
            return self.aborted
        self.cascaded.add(block)
        write_log(
            self.session_dir,
            f"MAPPER_CASCADE_DONE block={block} "
            f"verified={[f for f in members if f in self.verified]} "
            f"unverified={[f for f in members if f not in self.verified]}",
        )
        if not result or result.get("ok"):
            return None
        field, outcome = result.get("blocked_field"), result.get("blocked_outcome")
        if outcome in _GOVERNED_DEFERRED_OUTCOMES:
            # The level not settled (it may carry no value of its own:
            # the locality defaults to the municipality text) and every
            # member still unverified: the cascade re-runs on next resume.
            for member in {field, *(m for m in members if m not in self.verified)}:
                self.deferred[member] = outcome
            if block not in _ACTIVE_SURFACE_CASCADE_BLOCKS:
                return None
            # QCC_EX01_R11_FIX3_CASCADE: the human is on this surface and
            # these members are mandatory on it: never left as a silent
            # deferral behind a FILLED. Still deferred (a later resume
            # re-runs it), but this VOLCAR stops FILL_BLOCKED for the human.
        if self._service_operator_action() is not None:
            # A queued PRESENTATION_ABORT has priority over the block.
            return self.aborted
        cause = result.get("cause") or outcome
        write_log(
            self.session_dir,
            f"MAPPER_CASCADE_BLOCKED block={block} field={field} outcome={outcome} cause={cause}",
        )
        return {"ok": False, "label": _MAPPER_BLOCK_LABELS[block],
                "blocked_field": field, "blocked_outcome": outcome, "cause": cause}

    def resume(self, active_blocks=()):
        result = self._resume(active_blocks)
        if not result.get("ok") and not _is_qcc_aborted_result(result):
            write_log(self.session_dir, f"MAPPER_SECTION_BLOCKED label={result.get('label')}")
        return result

    def pending_on(self, blocks):
        """QCC_EX01_R11_FIX3_CASCADE: canonical fields of ``blocks`` still
        deferred (field id -> outcome). Empty = every mapped control of
        those surfaces is verified."""

        fields = set().union(*(_CANONICAL_MAPPER_FIELDS[b] for b in blocks))
        return {f: o for f, o in sorted(self.deferred.items()) if f in fields}

    def _resume(self, active_blocks):
        if self.aborted:
            return self.aborted
        self.started = True
        # Human navigation proves these surfaces have been reached. A required
        # field on one of them may no longer be deferred as a future control.
        self.required_blocks.update(active_blocks)
        if not self.values["representante"]:
            return {"ok": False, "label": "PRESENTADOR_BLOCKED", "reason": "EMPTY_REQUIRED_BLOCK"}
        if "notificacion" in self.required_blocks:
            if not _notification_section_active(self.browser):
                write_log(self.session_dir, "NOTIFICATION_SURFACE_NOT_ACTIVE writes=NO")
                return {"ok": False, "label": "NOTIFICACION_BLOCKED", "blocked_field": None,
                        "blocked_outcome": "NOTIFICATION_SURFACE_NOT_ACTIVE"}
            if "notificacion" in active_blocks:
                self._settle_absent_notification_fields()
        all_fields = set().union(*(_CANONICAL_MAPPER_FIELDS[b] for b in self.blocks))
        with governed_section(self.browser, self.session_dir, "MAPPER_PRELOAD",
                              preload_fields=all_fields) as section:
            section.required_fields = set().union(*(
                _CANONICAL_MAPPER_FIELDS[b] for b in self.required_blocks
            ))
            for block in self.blocks:
                values = self.values[block]
                if block == "notificacion" and block not in self.required_blocks:
                    self._defer_notification(values)
                    continue
                # Ordinary controls only: the address cascade runs afterwards
                # in its specialized helper.
                fields = [f for f in dict.fromkeys(k.removesuffix("_text") for k in values)
                          if not _is_mapper_cascade_field(f)]
                for field in fields:
                    if self._service_operator_action() is not None:
                        return self.aborted
                    if field in self.verified:
                        # Revalidate locally after navigation; write again only if cleared.
                        if self.verified[field]():
                            continue
                        del self.verified[field]
                    if self._notification_locked_contact(field, block):
                        continue
                    notification = self._notification_identity(field, block)
                    if notification in (CERTIFICATE_IDENTITY_VERIFIED, GOVERNED_OUTCOME_DEFERRED_DEPENDENCY):
                        continue
                    if notification is not None:
                        return {"ok": False, "label": _MAPPER_BLOCK_LABELS[block],
                                "blocked_field": field, "blocked_outcome": notification}
                    certificate = self._certificate_identity(field, values)
                    if certificate == CERTIFICATE_IDENTITY_VERIFIED:
                        continue
                    if certificate == CERTIFICATE_IDENTITY_MISMATCH:
                        return {"ok": False, "label": _MAPPER_BLOCK_LABELS[block],
                                "blocked_field": field, "blocked_outcome": certificate}
                    outcome = self._write_field(section, block, field, values, active_blocks)
                    if self.aborted:
                        return self.aborted
                    if outcome in _GOVERNED_DEFERRED_OUTCOMES:
                        self.deferred[field] = outcome
                    elif _fill_section_blocked(outcome):
                        return {"ok": False, "label": _MAPPER_BLOCK_LABELS[block],
                                "blocked_field": field, "blocked_outcome": outcome}
                    else:
                        self.deferred.pop(field, None)
                cascade = self._resume_cascade(block, values)
                if cascade is not None:
                    return cascade
        return {"ok": True, "deferred": dict(self.deferred)}

    def _write_field(self, section, block, field, values, active_blocks):
        """One governed write; a dependency not settled on a surface the
        human has just reached is awaited (bounded, ABORT serviced) for
        its intended value/option, then written once more."""

        value, text = values.get(field, ""), values.get(field + "_text", "")
        one = {k: values[k] for k in (field, field + "_text") if k in values}
        result = _fill_section_fields(self.browser, one, self.session_dir)
        outcome = result.get("blocked_outcome") or section.deferred.get(field) or GOVERNED_OUTCOME_OK
        if outcome != GOVERNED_OUTCOME_DEFERRED_DEPENDENCY or block not in active_blocks:
            return outcome
        readiness = _wait_for_js_with_qcc_control(
            self.browser, _preload_dependency_ready_js(field, value, text),
            self.session_dir, timeout=_DEPENDENCY_READINESS_TIMEOUT_SECONDS,
            interval=_DEPENDENCY_READINESS_POLL_INTERVAL_SECONDS,
            action_client=self.navigation.get("action_client"),
            reporter=self.navigation.get("reporter"),
            abort_handler=self.navigation.get("abort_handler"),
            step="MAPPER_DEPENDENCY",
        )
        if _is_qcc_aborted_result(readiness):
            self.aborted = readiness
            return outcome
        if not readiness.get("ok"):
            return outcome
        section.deferred.pop(field, None)
        result = _fill_section_fields(self.browser, one, self.session_dir)
        return result.get("blocked_outcome") or section.deferred.get(field) or GOVERNED_OUTCOME_OK


def _with_mapper_preload(run):
    """Opens the one ``_MapperPreload`` of an EX01 (130/131) VOLCAR DATOS
    around ``run_auto``. An ABORT serviced inside it always wins."""

    @functools.wraps(run)
    def wrapper(browser, provincia_codigo, datos_mercurio, session_dir,
                reporter=None, action_client=None, abort_handler=None):
        mode = get_mercurio_mapper_mode(datos_mercurio or {})
        if not datos_mercurio or not (mode.get("is_ex01") or mode.get("is_ex01_familiar")):
            return run(browser, provincia_codigo, datos_mercurio, session_dir, reporter=reporter,
                       action_client=action_client, abort_handler=abort_handler)
        preload = _MapperPreload(browser, datos_mercurio, session_dir, {
            "reporter": reporter, "action_client": action_client, "abort_handler": abort_handler,
        })
        _ACTIVE_MAPPER_PRELOADS.append(preload)
        try:
            result = run(browser, provincia_codigo, datos_mercurio, session_dir, reporter=reporter,
                         action_client=action_client, abort_handler=abort_handler)
            return preload.aborted or result
        finally:
            _ACTIVE_MAPPER_PRELOADS.remove(preload)

    return wrapper


def _mapper_preload_pending(browser, session_dir):
    """Final continuation of the same VOLCAR before the human CONCLUIR:
    every verified field revalidated, nothing left deferred. ``None`` =
    complete (or no VOLCAR of the mapper was performed)."""

    preload = _active_mapper_preload(browser)
    if preload is None or not preload.started:
        return None
    pending = preload.resume(())
    if not pending.get("ok"):
        return pending
    if preload.deferred:
        write_log(session_dir, f"MAPPER_FIELDS_DEFERRED fields={sorted(preload.deferred)}")
        return {"ok": False, "label": "MAPPER_FIELDS_DEFERRED", "deferred": dict(preload.deferred)}
    return None


@_with_mapper_preload
def run_auto(
    browser,
    provincia_codigo,
    datos_mercurio,
    session_dir,
    reporter=None,
    action_client=None,
    abort_handler=None,
):
    tipo_formulario_objetivo = get_tipo_formulario_objetivo(datos_mercurio)
    mapper_mode = get_mercurio_mapper_mode(datos_mercurio)
    write_log(session_dir, f"Mapper interno Mercurio: {describe_mapper_codigo(mapper_mode.get('mapper_codigo'))}")
    initial_result = step_continuar_inicial(
        browser,
        session_dir,
        reporter=reporter,
    )

    if not initial_result.get("ok"):
        return initial_result

    certificate_result = pause_certificado(
        browser,
        session_dir,
        reporter=reporter,
        action_client=action_client,
        abort_handler=abort_handler,
    )

    if not certificate_result.get("ok"):
        return certificate_result

    presentation_options_result = (
        step_presentar_nueva_solicitud(
            browser,
            provincia_codigo,
            session_dir,
            tipo_formulario_objetivo=(
                tipo_formulario_objetivo
            ),
            reporter=reporter,
        )
    )

    if not presentation_options_result.get("ok"):
        return presentation_options_result

    supuesto_result = pause_supuesto(
        browser,
        session_dir,
        tipo_formulario_objetivo=tipo_formulario_objetivo,
        reporter=reporter,
        datos_mercurio=datos_mercurio,
        action_client=action_client,
        abort_handler=abort_handler,
    )

    if not supuesto_result.get("ok"):
        return supuesto_result

    if datos_mercurio:
        if mapper_mode.get("is_ex02"):
            # Orden real Mercurio EX02:
            # 1) reagrupante desde datos_especificos.reagrupante_*
            # 2) reagrupado/solicitante desde cliente del expediente
            # 3) presentador profesional
            if not fill_datos_reagrupante_ex02(browser, datos_mercurio, session_dir):
                return {"ok": False, "label": "REAGRUPANTE_EX02_BLOCKED"}
            click_continuar_ex02_reagrupante_to_reagrupado(
                browser,
                session_dir,
                reporter=reporter,
            )
            if not fill_datos_reagrupado_ex02(browser, datos_mercurio, session_dir):
                return {"ok": False, "label": "REAGRUPADO_EX02_BLOCKED"}
            click_continuar_ex02_reagrupado_to_presentador(
                browser,
                session_dir,
                reporter=reporter,
            )
        else:
            # QCC_ASSISTED_OPERATOR_CONTROLS_V1: semi-automático, no
            # automático. pause_supuesto ya devolvió el control en
            # cuanto detectó EX01_CANDIDATE; QCC está mostrando
            # READY_TO_FILL. El relleno NO arranca aquí por sí solo:
            # espera el comando explícito VOLCAR DATOS.
            fill_start_result = wait_for_qcc_fill_start(
                action_client,
                session_dir,
                reporter=reporter,
                abort_handler=abort_handler,
            )

            if not fill_start_result.get("ok"):
                return {
                    "ok": False,
                    "label": "FILL_START_NOT_CONFIRMED",
                    "detail": fill_start_result,
                }

            # Comprobación de interactuabilidad en vivo, acotada y
            # automática, AHORA que el volcado está explícitamente
            # autorizado -- nunca antes de VOLCAR DATOS.
            readiness_result = _wait_for_ex01_personal_readiness(
                browser,
                session_dir,
                datos_mercurio,
                reporter=reporter,
                action_client=action_client,
                abort_handler=abort_handler,
            )

            if not readiness_result.get("ok"):
                return readiness_result

            # QCC_EX01_RENOVACION_TITULAR_130_V1: the identity proven at
            # pause_supuesto is never reused -- re-read live right
            # before the first write.
            if mapper_mode.get("is_ex01"):
                identity_result = _verify_ex01_renovacion_titular_identity(
                    browser,
                    session_dir,
                    phase="FILL_START",
                )

                if not identity_result.get("ok"):
                    return identity_result

            qcc_report(
                reporter,
                "filling",
                session_dir,
                step="FILLING",
                progress=40,
                message="Volcando datos en Mercurio",
            )

            write_log(session_dir, "QCC_FILL_MAPPER_START step=FILLING")

            extranjero_result = fill_datos_extranjero(browser, datos_mercurio, session_dir)

            if extranjero_result is None or extranjero_result.get("ok"):
                mapper_outcome = "ok"
            elif _is_qcc_aborted_result(extranjero_result):
                mapper_outcome = "aborted"
            else:
                # Field id and reason codes only, never values.
                mapper_outcome = (
                    "blocked "
                    f"field={extranjero_result.get('blocked_field') or '-'} "
                    f"cause={extranjero_result.get('cause') or extranjero_result.get('blocked_outcome') or '-'}"
                )
            write_log(
                session_dir,
                f"QCC_FILL_MAPPER_RESULT step=FILLING outcome={mapper_outcome}",
            )

            if _is_qcc_aborted_result(extranjero_result):
                return extranjero_result

            if extranjero_result is not None and not extranjero_result.get("ok"):
                qcc_report(
                    reporter,
                    "fill_blocked",
                    session_dir,
                    step="FILL_BLOCKED",
                    message=(
                        "Rellenado detenido: se requiere "
                        "corrección o acción humana"
                    ),
                    event_details=extranjero_result,
                )
                # QCC_EX01_R6_POSTFORM: the VOLCAR also verifies the
                # certificate-held presenter identity; its own label wins.
                return {
                    "ok": False,
                    "label": extranjero_result.get("label") or "EXTRANJERO_BLOCKED",
                    "detail": extranjero_result,
                }

            write_log(session_dir, "QCC_FILL_COMPLETED step=FILLED")

            qcc_report(
                reporter,
                "filled",
                session_dir,
                message="Datos del extranjero/a volcados",
            )
            # QCC_EX01_R2: every EX01 form CONTINUAR/CONCLUIR is
            # HUMAN_ONLY -- the runner only observes the destination
            # screen (ABORTAR serviced meanwhile) and stops if it is
            # not confirmed, never fills the next section blindly.
            if mapper_mode.get("is_ex01_familiar"):
                nav_result = click_continuar_extranjero_to_familiar(
                    browser,
                    session_dir,
                    reporter=reporter,
                    action_client=action_client,
                    abort_handler=abort_handler,
                )
                if _mapper_navigation_stopped(nav_result):
                    return _mapper_navigation_result(
                        nav_result, "CONTINUE_TO_FAMILY_MEMBER"
                    )
                family_result = fill_datos_familiar_ex01(
                    browser,
                    datos_mercurio,
                    session_dir,
                    reporter=reporter,
                    action_client=action_client,
                    abort_handler=abort_handler,
                )
                if _is_qcc_aborted_result(family_result):
                    return family_result
                if not family_result.get("ok"):
                    return {"ok": False, "label": "FAMILIAR_EX01_BLOCKED", "detail": family_result}
                nav_result = click_continuar_familiar_to_presentador(
                    browser,
                    session_dir,
                    reporter=reporter,
                    action_client=action_client,
                    abort_handler=abort_handler,
                )
                if _mapper_navigation_stopped(nav_result):
                    return _mapper_navigation_result(nav_result, "CONTINUE_TO_PRESENTER")
                # QCC_EX01_R6_FAMILIAR_131: never pass to the Presenter
                # with a family cascade that diverged after CONTINUAR.
                divergence = _ex01_family_cascade_divergence(
                    browser, session_dir, family_result.get("family_cascade")
                )
                if divergence is not None:
                    return {"ok": False, "label": "FAMILIAR_EX01_BLOCKED", "detail": divergence}
            else:
                nav_result = click_continuar(
                    browser,
                    session_dir,
                    reporter=reporter,
                    action_client=action_client,
                    abort_handler=abort_handler,
                    ex01_titular=bool(mapper_mode.get("is_ex01")),
                )
            if _mapper_navigation_stopped(nav_result):
                return _mapper_navigation_result(nav_result, "CONTINUE_TO_PRESENTER")
        if not fill_datos_presentador(browser, datos_mercurio, session_dir):
            return {"ok": False, "label": "PRESENTADOR_BLOCKED"}
        nav_result = click_continuar_presentador(
            browser,
            session_dir,
            reporter=reporter,
            action_client=action_client,
            abort_handler=abort_handler,
        )
        if _mapper_navigation_stopped(nav_result):
            return _mapper_navigation_result(nav_result, "CONTINUE_FROM_PRESENTER")

        # QCC_EX01_R6_POSTFORM: Notification only now that the human
        # CONTINUAR made its surface active; then the same VOLCAR is
        # revalidated end to end before the HUMAN_ONLY CONCLUIR gate.
        notification_result = fill_datos_notificacion(browser, datos_mercurio, session_dir)
        if _is_qcc_aborted_result(notification_result):
            return notification_result
        if notification_result is not None and not notification_result.get("ok"):
            return _mapper_section_blocked(
                reporter, session_dir, "NOTIFICACION_BLOCKED", detail=notification_result
            )
        pending = _mapper_preload_pending(browser, session_dir)
        if _is_qcc_aborted_result(pending):
            return pending
        if pending is not None:
            return _mapper_section_blocked(
                reporter, session_dir, pending.get("label") or "MAPPER_FIELDS_DEFERRED",
                detail=pending,
            )
        write_log(session_dir, "MAPPER_FILL_COMPLETED")

        final_result = pause_humana_final_presentacion(
            browser,
            session_dir,
            reporter=reporter,
            action_client=action_client,
            abort_handler=abort_handler,
        )

        if _is_qcc_aborted_result(final_result) or (
            _qcc_action_channel_available(action_client)
            and isinstance(final_result, dict)
            and not final_result.get("ok")
        ):
            return final_result


def _finish_aborted_presentation(
    result,
    session_dir,
    lifecycle,
):
    """Post-abort exit: the governed close already ran through
    ``abort_handler``. Ownership is only released when that close was
    confirmed; otherwise the final ``__main__`` finalizer retries the
    same idempotent ``close_browser``."""

    detail = result.get("detail")
    abort_result = (
        detail
        if isinstance(detail, dict) and detail.get("mode") == "aborted"
        else result
    )

    print("Presentación abortada desde QCC.")

    write_log(
        session_dir,
        "Presentación abortada: se omite menú de consola "
        f"(browser_closed={bool(abort_result.get('browser_closed'))})",
    )

    if abort_result.get("browser_closed") and lifecycle is not None:
        lifecycle[
            "connector"
        ] = None


def main(
    lifecycle=None,
):
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--expediente-id", default="")
    parser.add_argument("--cliente-id", default="")
    parser.add_argument("--qcc-session-id", default="")
    parser.add_argument("--browser-profile-key", default="")
    parser.add_argument("--numero-expediente", default="")
    parser.add_argument("--tipo", default="")
    parser.add_argument("--provincia-codigo", required=True)
    parser.add_argument("--datos-mercurio-json", default="")
    parser.add_argument("--session-dir", default="")
    parser.add_argument("--documentos-dir", default="")
    parser.add_argument("--auto", action="store_true")
    args = parser.parse_args()

    session_dir = get_session_dir(args.session_dir, args.expediente_id)
    datos_mercurio = load_datos_mercurio(args.datos_mercurio_json)
    tipo_formulario_objetivo = get_tipo_formulario_objetivo(datos_mercurio)
    mapper_mode = get_mercurio_mapper_mode(datos_mercurio)
    mapper_codigo = mapper_mode.get("mapper_codigo")
    documentos_dir = resolve_para_presentar_dir(
        args,
        datos_mercurio,
        session_dir,
    )

    qcc_reporter = build_qcc_reporter(
        args,
        session_dir,
    )

    qcc_action_client = (
        build_qcc_action_client(
            args,
            session_dir,
        )
    )

    if lifecycle is not None:
        lifecycle[
            "qcc_reporter"
        ] = qcc_reporter

        lifecycle[
            "qcc_action_client"
        ] = qcc_action_client

    url = (args.url or "").strip()
    if not url:
        raise ValueError("URL vacía")

    print("=" * 80)
    print("PRESENTACIÓN ASISTIDA - QUESADA ABOGADOS")
    print("=" * 80)
    print(f"Expediente ID: {args.expediente_id or '-'}")
    print(f"Número expediente: {args.numero_expediente or '-'}")
    print(f"Tipo: {args.tipo or '-'}")
    print(f"Provincia código Mercurio: {args.provincia_codigo}")
    print(f"Formulario Mercurio objetivo: {describe_tipo_formulario_objetivo(tipo_formulario_objetivo)}")
    print(f"Mapper interno de volcado: {describe_mapper_codigo(mapper_codigo)}")
    print(f"Carpeta sesión: {session_dir}")
    print(f"datos_mercurio.json: {args.datos_mercurio_json or '-'}")
    print(f"Documentos PARA PRESENTAR: {documentos_dir or '-'}")
    print(f"URL: {url}")
    print("=" * 80)

    write_log(
        session_dir,
        "Iniciando Chrome sb_cdp. "
        f"Formulario objetivo={describe_tipo_formulario_objetivo(tipo_formulario_objetivo)}. "
        f"Mapper interno={describe_mapper_codigo(mapper_codigo)}"
    )
    qcc_report(
        qcc_reporter,
        "started",
        session_dir,
    )

    connector = MercurioConnector(
        session_dir=session_dir,
        expediente_id=args.expediente_id,
        profile_key=(
            args.browser_profile_key
            or None
        ),
        headless=False,
    )

    # Registrar ownership ANTES de start_browser().
    #
    # Si BrowserSession alcanza READY pero open_url() falla,
    # el finalizador superior todavía conoce el connector
    # que debe ejecutar el shutdown gobernado.
    if lifecycle is not None:
        lifecycle[
            "connector"
        ] = connector

    try:
        browser = connector.start_browser(
            url
        )

    except Exception as exc:
        qcc_report(
            qcc_reporter,
            "error",
            session_dir,
            step="BROWSER_START",
            message=(
                "Error iniciando navegador: "
                f"{type(exc).__name__}"
            ),
        )

        raise

    if args.auto:
        auto_result = connector.safe_execute(
            "auto inicial",
            lambda: run_auto_and_documents_with_qcc(
                browser,
                args.provincia_codigo,
                datos_mercurio,
                documentos_dir,
                session_dir,
                reporter=qcc_reporter,
                action_client=qcc_action_client,
                abort_handler=connector.close_browser,
            ),
        )

        # ABORTAR PRESENTACIÓN ya ejecutó el cierre gobernado: nunca
        # caer después en el menú oculto de consola.
        if _is_qcc_aborted_result(auto_result):
            _finish_aborted_presentation(
                auto_result,
                session_dir,
                lifecycle,
            )
            return

        print(
            "Flujo automático/documental finalizado. "
            "Chrome permanece bajo control gobernado."
        )

    print()
    print("MENÚ:")
    print("  ENTER / h  -> guardar HTML actual")
    print("  auto       -> ejecutar flujo parcial")
    print("  fill       -> rellenar datos completos con datos_mercurio.json")
    print("  fillpre    -> rellenar solo datos del presentador")
    print("  fillfam    -> rellenar solo datos del familiar EX01")
    print("  fillrea    -> rellenar solo datos del reagrupante EX02")
    print("  human      -> pausa humana final sin disconnect")
    print("  q          -> salir")
    print()

    while True:
        cmd = input("presentacion> ").strip().lower()

        if cmd in ("", "h", "html", "source"):
            try:
                html_path = save_page_source(browser, session_dir)
                print(f"HTML guardado en: {html_path}")
            except Exception as exc:
                print(f"ERROR guardando HTML: {exc}")

        elif cmd == "auto":
            auto_result = connector.safe_execute(
                "auto",
                lambda: run_auto_and_documents_with_qcc(
                browser,
                args.provincia_codigo,
                datos_mercurio,
                documentos_dir,
                session_dir,
                reporter=qcc_reporter,
                action_client=qcc_action_client,
                abort_handler=connector.close_browser,
            ),
            )

            if _is_qcc_aborted_result(auto_result):
                _finish_aborted_presentation(
                    auto_result,
                    session_dir,
                    lifecycle,
                )
                break

        elif cmd == "fill":
            if not datos_mercurio:
                print("No hay datos_mercurio.json cargado.")
            else:
                if mapper_mode.get("is_ex02"):
                    fill_datos_reagrupante_ex02(browser, datos_mercurio, session_dir)
                else:
                    fill_datos_extranjero(browser, datos_mercurio, session_dir)



        elif cmd in ("fillsol", "solicitante", "reagrupado"):
            if not datos_mercurio:
                print("No hay datos_mercurio.json cargado.")
            else:
                fill_datos_reagrupado_ex02(browser, datos_mercurio, session_dir)

        elif cmd in ("fillrea", "reagrupante", "rea"):
            if not datos_mercurio:
                print("No hay datos_mercurio.json cargado.")
            else:
                fill_datos_reagrupante_ex02(browser, datos_mercurio, session_dir)

        elif cmd == "fillpre":
            if not datos_mercurio:
                print("No hay datos_mercurio.json cargado.")
            else:
                fill_datos_presentador(browser, datos_mercurio, session_dir)

        elif cmd in ("fillfam", "familiar"):
            if not datos_mercurio:
                print("No hay datos_mercurio.json cargado.")
            else:
                fill_datos_familiar_ex01(browser, datos_mercurio, session_dir)

        elif cmd in ("fillrea", "reagrupante", "rea"):
            if not datos_mercurio:
                print("No hay datos_mercurio.json cargado.")
            else:
                fill_datos_reagrupante_ex02(browser, datos_mercurio, session_dir)

        elif cmd in ("human", "humano", "pausa"):
            pause_humana_final_presentacion(
                browser,
                session_dir,
                reporter=qcc_reporter,
            )

        elif cmd in ("q", "quit", "exit", "salir"):
            print(
                "Cerrando presentación asistida..."
            )

            write_log(
                session_dir,
                "Cerrando presentación asistida",
            )

            closed = (
                connector.close_browser()
            )

            if closed:
                if lifecycle is not None:
                    lifecycle[
                        "connector"
                    ] = None

            else:
                print(
                    "AVISO: no se pudo confirmar "
                    "el cierre gobernado de Chrome."
                )

                write_log(
                    session_dir,
                    "Cierre gobernado incompleto; "
                    "el connector conserva ownership",
                )

            break

        else:
            print("Comando no reconocido.")


if __name__ == "__main__":
    lifecycle = {}

    try:
        main(
            lifecycle=lifecycle,
        )

    finally:
        # Toda salida Python ordinaria debe ofrecer al owner
        # la oportunidad de cerrar BrowserSession.
        #
        # Incluye:
        # - excepciones no capturadas;
        # - KeyboardInterrupt;
        # - EOFError;
        # - fallo posterior a BrowserSession.start().
        connector = lifecycle.get(
            "connector"
        )

        if connector is not None:
            try:
                closed = (
                    connector.close_browser()
                )

            except Exception as exc:
                closed = False

                print(
                    "ERROR durante cierre final "
                    "de presentación asistida:",
                    repr(
                        exc
                    ),
                )

            if not closed:
                print(
                    "AVISO: el cierre final gobernado "
                    "de Chrome no pudo confirmarse."
                )
