"""Governed dynamic-form Twin experiments — AUTO TWIN (UWT-6B2).

Responsabilidad:

    LOCAL AUTO TWIN ya abierto en un navegador gobernado
        ↓
    capturar BEFORE
        ↓
    ejecutar EXACTAMENTE una acción de cambio de estado permitida
        ↓
    capturar AFTER
        ↓
    calcular efectos dinámicos (UWT-6B1)
        ↓
    restaurar BEFORE (UWT-6A2)
        ↓
    capturar RESTORED
        ↓
    verificar restauración
        ↓
    evidencia estructural compacta

Este servicio NO captura DOM, NO normaliza Site Architecture, NO
calcula efectos dinámicos, NO construye el plan de restauración y NO
lo ejecuta: todas esas autoridades se reutilizan sin duplicar. Solo
orquesta ONE governed local Twin experiment y aplica las puertas de
seguridad (Twin-only, main-frame-only, sin efectos de navegación, sin
persistencia de valores de runtime, sin fuga de literales).
"""

from __future__ import annotations

from urllib.parse import urlsplit

from backend.automation.dom_inspector import (
    capture_dom_payload,
)
from backend.automation.site_architecture.dynamic_form_effects import (
    build_dynamic_form_effect_evidence,
)
from backend.automation.site_architecture.normalizer import (
    normalize_dom_capture,
)
from backend.qcc.auto_twin.form_runtime_hydration import (
    build_form_runtime_hydration_plan,
)
from backend.services.twin_form_runtime_service import (
    TwinFormRuntimeService,
)


DYNAMIC_FORM_EXPERIMENT_SCHEMA_VERSION = 1

ACTION_SELECT = "SELECT"
ACTION_CHECKBOX = "CHECKBOX"
ACTION_RADIO = "RADIO"

ALLOWED_ACTION_KINDS = frozenset({
    ACTION_SELECT,
    ACTION_CHECKBOX,
    ACTION_RADIO,
})

MAIN_FRAME_PATH = "main"

TWIN_ONLY_LOOPBACK_HOSTNAME = "127.0.0.1"

RUNTIME_VALUES_PERSISTED = "NO"

_MUTATION_FIELDS = {
    ACTION_SELECT: frozenset({"selected_value"}),
    ACTION_CHECKBOX: frozenset({"checked"}),
    ACTION_RADIO: frozenset({"checked"}),
}

_SETTLE_PHASE_AFTER_MUTATION = "AFTER_MUTATION"
_SETTLE_PHASE_AFTER_RESTORE = "AFTER_RESTORE"


class TwinDynamicFormExperimentError(RuntimeError):
    """Fallo gobernado y determinista de un experimento B2."""


def _noop_settle_hook(browser, phase):
    return None


def _text(value):
    return str(value or "").strip()


def _metadata(payload):
    value = (payload or {}).get("metadata") if isinstance(payload, dict) else None
    return value if isinstance(value, dict) else {}


def _origin_hostname(payload):
    metadata = _metadata(payload)

    origin = _text(metadata.get("origin"))
    url = _text(metadata.get("url"))

    return (
        urlsplit(origin).hostname
        or urlsplit(url).hostname
    )


def _navigation_identity(payload):
    url = _text(_metadata(payload).get("url"))

    parsed = urlsplit(url)

    return (
        parsed.hostname,
        parsed.port,
        parsed.path,
        parsed.query,
    )


class TwinDynamicFormExperimentService:
    """Owner de orquestación de un experimento gobernado de Twin."""

    def __init__(
        self,
        *,
        capture_provider=None,
        form_runtime_service=None,
    ):
        self._capture_provider = (
            capture_provider
            or capture_dom_payload
        )

        self._form_runtime_service = (
            form_runtime_service
            or TwinFormRuntimeService()
        )

    # ------------------------------------------------------------
    # Validation (no browser interaction)
    # ------------------------------------------------------------

    def _validate_action(self, action):
        if not isinstance(action, dict):
            raise TwinDynamicFormExperimentError(
                "ACTION_INVALID"
            )

        kind = _text(action.get("kind")).upper()

        if kind not in ALLOWED_ACTION_KINDS:
            raise TwinDynamicFormExperimentError(
                "ACTION_KIND_NOT_ALLOWED:" + kind
            )

        selector = _text(action.get("selector"))

        if not selector:
            raise TwinDynamicFormExperimentError(
                "ACTION_SELECTOR_REQUIRED"
            )

        frame_path = (
            _text(action.get("frame_path"))
            or MAIN_FRAME_PATH
        )

        if frame_path != MAIN_FRAME_PATH:
            raise TwinDynamicFormExperimentError(
                "ACTION_FRAME_NOT_MAIN:" + frame_path
            )

        return kind, selector, frame_path

    def _validate_mutation(self, kind, mutation):
        if not isinstance(mutation, dict):
            raise TwinDynamicFormExperimentError(
                "MUTATION_INVALID"
            )

        allowed_fields = _MUTATION_FIELDS[kind]

        if set(mutation) != allowed_fields:
            raise TwinDynamicFormExperimentError(
                "MUTATION_FIELDS_INVALID"
            )

        if kind == ACTION_SELECT:
            value = mutation.get("selected_value")

            if (
                not isinstance(value, str)
                or not value.strip()
            ):
                raise TwinDynamicFormExperimentError(
                    "MUTATION_SELECTED_VALUE_INVALID"
                )

            return

        checked = mutation.get("checked")

        if not isinstance(checked, bool):
            raise TwinDynamicFormExperimentError(
                "MUTATION_CHECKED_INVALID"
            )

        if (
            kind == ACTION_RADIO
            and checked is not True
        ):
            raise TwinDynamicFormExperimentError(
                "MUTATION_RADIO_CHECKED_MUST_BE_TRUE"
            )

    # ------------------------------------------------------------
    # Capture / Twin-only gate / navigation guard
    # ------------------------------------------------------------

    def _capture(self, browser):
        payload = self._capture_provider(browser)

        if not isinstance(payload, dict):
            raise TwinDynamicFormExperimentError(
                "CAPTURE_PAYLOAD_INVALID"
            )

        return payload

    def _require_twin_only(self, payload):
        hostname = _origin_hostname(payload)

        if hostname != TWIN_ONLY_LOOPBACK_HOSTNAME:
            raise TwinDynamicFormExperimentError(
                "TWIN_ONLY_GATE_REJECTED_HOST:"
                + str(hostname)
            )

    def _require_no_navigation(
        self,
        before_payload,
        candidate_payload,
        *,
        phase,
    ):
        if (
            _navigation_identity(before_payload)
            != _navigation_identity(candidate_payload)
        ):
            raise TwinDynamicFormExperimentError(
                "NAVIGATION_SIDE_EFFECT_DETECTED:" + phase
            )

    # ------------------------------------------------------------
    # Site Architecture action lookup (fail closed on ambiguity)
    # ------------------------------------------------------------

    def _locate_action(
        self,
        snapshot,
        *,
        kind,
        selector,
        frame_path,
    ):
        matches = [
            dict(entry)
            for entry in (snapshot.actions or ())
            if (
                isinstance(entry, dict)
                and _text(entry.get("kind")).upper() == kind
                and _text(entry.get("frame_path")) == frame_path
                and _text(entry.get("selector")) == selector
            )
        ]

        if not matches:
            raise TwinDynamicFormExperimentError(
                "ACTION_NOT_FOUND_IN_INVENTORY"
            )

        if len(matches) != 1:
            raise TwinDynamicFormExperimentError(
                "ACTION_AMBIGUOUS_IN_INVENTORY"
            )

        return matches[0]

    # ------------------------------------------------------------
    # Structural mutation identity (UWT-6B3-1A)
    #
    # Privacy-safe STRUCTURAL identity of the executed mutation,
    # derived exclusively from the OBSERVED AFTER snapshot. Never
    # echoes the caller's mutation literal (selected_value, free
    # text, etc.) — only the physical structural position/state
    # that the materialized state ended up in.
    # ------------------------------------------------------------

    def _build_mutation_identity(self, *, kind, form_state):
        if not isinstance(form_state, dict):
            raise TwinDynamicFormExperimentError(
                "MUTATION_IDENTITY_FORM_STATE_MISSING"
            )

        if kind == ACTION_SELECT:
            selected_indexes = tuple(
                form_state.get("selected_indexes") or ()
            )

            if len(selected_indexes) == 0:
                raise TwinDynamicFormExperimentError(
                    "MUTATION_IDENTITY_SELECT_ZERO_SELECTED_INDEXES"
                )

            if len(selected_indexes) > 1:
                raise TwinDynamicFormExperimentError(
                    "MUTATION_IDENTITY_SELECT_MULTIPLE_SELECTED_INDEXES"
                )

            selected_index = selected_indexes[0]

            if (
                not isinstance(selected_index, int)
                or isinstance(selected_index, bool)
                or selected_index < 0
            ):
                raise TwinDynamicFormExperimentError(
                    "MUTATION_IDENTITY_SELECT_INVALID_SELECTED_INDEX"
                )

            return {
                "kind": ACTION_SELECT,
                "selected_index": selected_index,
            }

        checked = form_state.get("checked")

        if not isinstance(checked, bool):
            raise TwinDynamicFormExperimentError(
                "MUTATION_IDENTITY_CHECKED_UNRESOLVED"
            )

        if (
            kind == ACTION_RADIO
            and checked is not True
        ):
            raise TwinDynamicFormExperimentError(
                "MUTATION_IDENTITY_RADIO_OBSERVED_CONTRADICTION"
            )

        return {
            "kind": kind,
            "checked": checked,
        }

    # ------------------------------------------------------------
    # Browser execution owner (SeleniumBase interface only)
    # ------------------------------------------------------------

    def _execute_mutation(
        self,
        *,
        browser,
        kind,
        selector,
        mutation,
    ):
        if kind == ACTION_SELECT:
            browser.select_option_by_value(
                selector,
                mutation["selected_value"],
            )

            return

        if kind == ACTION_CHECKBOX:
            if mutation["checked"]:
                browser.check_if_unchecked(selector)
            else:
                browser.uncheck_if_checked(selector)

            return

        if kind == ACTION_RADIO:
            if not browser.is_checked(selector):
                browser.click(selector)

            return

        raise TwinDynamicFormExperimentError(
            "ACTION_KIND_NOT_ALLOWED:" + kind
        )

    # ------------------------------------------------------------
    # Result projection (no raw captures, no literal mutation dump)
    # ------------------------------------------------------------

    def _build_result(
        self,
        *,
        effect_evidence,
        mutation_identity,
        restoration_effect_count,
        catalogs_exact,
    ):
        result = {
            "schema_version":
                DYNAMIC_FORM_EXPERIMENT_SCHEMA_VERSION,

            "status":
                "SUCCESS",

            "action":
                effect_evidence["action"],

            "mutation_identity":
                mutation_identity,

            "effect_count":
                effect_evidence["effect_count"],

            "effects":
                effect_evidence["form_effects"],

            "restoration": {
                "exact": True,
                "effect_count": restoration_effect_count,
                "catalogs_exact": catalogs_exact,
            },

            "runtime_values_persisted":
                RUNTIME_VALUES_PERSISTED,
        }

        if "catalog_dynamic_evidence" in effect_evidence:
            result["catalog_dynamic_evidence"] = (
                effect_evidence["catalog_dynamic_evidence"]
            )

            result["catalog_causal_relations"] = (
                effect_evidence["catalog_causal_relations"]
            )

        return result

    # ------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------

    def run_experiment(
        self,
        *,
        browser,
        action,
        mutation,
        source_catalog_key=None,
        settle_hook=None,
    ) -> dict:
        settle = settle_hook or _noop_settle_hook

        kind, selector, frame_path = self._validate_action(
            action
        )

        self._validate_mutation(kind, mutation)

        before_payload = self._capture(browser)
        self._require_twin_only(before_payload)

        before_snapshot = normalize_dom_capture(
            before_payload
        )

        validated_action = self._locate_action(
            before_snapshot,
            kind=kind,
            selector=selector,
            frame_path=frame_path,
        )

        self._execute_mutation(
            browser=browser,
            kind=kind,
            selector=selector,
            mutation=mutation,
        )

        settle(browser, _SETTLE_PHASE_AFTER_MUTATION)

        after_payload = self._capture(browser)
        self._require_twin_only(after_payload)
        self._require_no_navigation(
            before_payload,
            after_payload,
            phase=_SETTLE_PHASE_AFTER_MUTATION,
        )

        after_snapshot = normalize_dom_capture(
            after_payload
        )

        effect_evidence = build_dynamic_form_effect_evidence(
            before_snapshot,
            after_snapshot,
            action=validated_action,
            source_catalog_key=source_catalog_key,
        )

        after_action = self._locate_action(
            after_snapshot,
            kind=kind,
            selector=selector,
            frame_path=frame_path,
        )

        mutation_identity = self._build_mutation_identity(
            kind=kind,
            form_state=after_action.get("form_state"),
        )

        restore_plan = build_form_runtime_hydration_plan(
            before_payload
        )

        self._form_runtime_service.apply_hydration_plan(
            browser=browser,
            plan=restore_plan,
            runtime_values={},
        )

        settle(browser, _SETTLE_PHASE_AFTER_RESTORE)

        restored_payload = self._capture(browser)
        self._require_twin_only(restored_payload)
        self._require_no_navigation(
            before_payload,
            restored_payload,
            phase=_SETTLE_PHASE_AFTER_RESTORE,
        )

        restored_snapshot = normalize_dom_capture(
            restored_payload
        )

        restoration_evidence = build_dynamic_form_effect_evidence(
            before_snapshot,
            restored_snapshot,
            action=validated_action,
            source_catalog_key=None,
        )

        catalogs_exact = (
            before_snapshot.catalogs
            == restored_snapshot.catalogs
        )

        restoration_exact = (
            restoration_evidence["effect_count"] == 0
            and catalogs_exact
        )

        if not restoration_exact:
            raise TwinDynamicFormExperimentError(
                "RESTORATION_FAILED"
            )

        return self._build_result(
            effect_evidence=effect_evidence,
            mutation_identity=mutation_identity,
            restoration_effect_count=(
                restoration_evidence["effect_count"]
            ),
            catalogs_exact=catalogs_exact,
        )
