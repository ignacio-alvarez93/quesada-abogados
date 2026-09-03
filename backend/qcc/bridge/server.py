"""Servidor HTTP local de Quesada Chrome Companion.

Contrato inicial:

    GET /qcc/health

El bridge:

- escucha únicamente en loopback;
- no accede a base de datos;
- no conoce SeleniumBase;
- no comparte proceso ni puerto con ICP Plus;
- no contiene lógica jurídica.
"""

from __future__ import annotations

import json
import threading
from datetime import (
    datetime,
    timezone,
)
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)
from typing import Any
from urllib.parse import (
    unquote,
    urlparse,
)

from backend.qcc.contracts.actions import (
    QccActionRequest,
)
from backend.qcc.actions.store import (
    QccActionStore,
)
from backend.qcc.contracts.tools import (
    QccToolRequest,
)
from backend.qcc.tools.store import (
    QccToolStore,
)
from backend.qcc.contracts.live_navigation import (
    QccLiveNavigationContext,
)
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
    QccPresentationSession,
)
from backend.qcc.context.store import (
    QccContextStore,
)
from backend.qcc.context.browser_registry import (
    QccBrowserRegistry,
)
from backend.qcc.context.human_action_canonicalizer import (
    QccHumanDomSignal,
    canonicalize_human_dom_signal,
)
from backend.qcc.context.human_transition_correlator import (
    correlate_observed_human_transition,
)
from backend.qcc.context.live_action_evidence import (
    QccLiveActionEvidence,
)
from backend.qcc.context.human_listener_plan import (
    build_human_listener_plan,
)
from backend.qcc.context.live_state_projection import (
    LIVE_STATE_SITE_UNRECOGNIZED,
    project_ingested_state_observation,
)
from backend.qcc.context.live_planning_coordinator import (
    clear_live_navigation_plan,
    refresh_live_navigation_plan,
)
from backend.qcc.context.live_governance_coordinator import (
    apply_live_navigation_governance,
)
from backend.qcc.context.navigation_intent import (
    QccNavigationIntent,
)
from backend.qcc.navigation_knowledge import (
    NavigationKnowledgeStore,
)
from backend.qcc.navigation_learning import (
    HumanNavigationCandidateStore,
    process_observed_human_navigation_learning,
)
from backend.automation.site_architecture.managed_governance_registry import (
    ManagedSiteGovernanceRegistry,
)
from backend.automation.site_policies.default_registry import (
    build_default_managed_site_governance_registry,
)
from backend.qcc.site_architecture import (
    QccSiteArchitectureIngestor,
)
from backend.qcc.site_architecture.ingestor import (
    QCC_VISUAL_ARTIFACT_MAX_BYTES,
)
from backend.automation.site_architecture import (
    analyze_qcc_catalog_experiment,
)


QCC_BRIDGE_HOST = "127.0.0.1"
QCC_BRIDGE_PORT = 8766

QCC_REQUEST_MAX_BYTES = 65536
QCC_SITE_ARCHITECTURE_MAX_BYTES = (
    64 * 1024 * 1024
)

QCC_CATALOG_EXPERIMENT_MAX_BYTES = (
    64 * 1024 * 1024
)


def _health_payload() -> dict[str, Any]:
    return {
        "service": "qcc_bridge",
        "status": "ok",
        "protocol_version": QCC_PROTOCOL_VERSION,
    }


def _human_addressable_live_actions(
    actions,
) -> tuple[dict[str, Any], ...]:
    """Project raw live actions into human-click evidence.

    The complete Site Architecture action inventory remains
    authoritative for safety/governance.

    Human-click evidence is intentionally narrower:
    a physical DOM signal can only be canonicalized against
    an action with a complete addressable identity.

    Missing kind/policy/selector actions are therefore omitted
    from this projection, never reclassified or repaired here.
    """

    projected = []

    for action in (
        actions
        or ()
    ):
        if not isinstance(
            action,
            dict,
        ):
            continue

        kind = str(
            action.get(
                "kind"
            )
            or ""
        ).strip()

        policy = str(
            action.get(
                "policy"
            )
            or ""
        ).strip()

        selector = str(
            action.get(
                "selector"
            )
            or ""
        ).strip()

        if (
            not kind
            or not policy
            or not selector
        ):
            continue

        projected.append(
            action
        )

    return tuple(
        projected
    )


class _QccBridgeHandler(BaseHTTPRequestHandler):
    server_version = "QccBridge/0.1"

    def _send_json(
        self,
        status_code: int,
        payload: dict[str, Any],
    ) -> None:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        self.send_response(status_code)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )
        self.send_header(
            "Content-Length",
            str(len(body)),
        )
        self.send_header(
            "Cache-Control",
            "no-store",
        )
        self.end_headers()

        self.wfile.write(body)

    def _drain_request_body(
        self,
        length,
    ) -> None:
        """Descarta un body pendiente sin cargarlo completo en memoria."""

        remaining = max(
            int(length),
            0,
        )

        while remaining > 0:
            chunk = self.rfile.read(
                min(
                    65536,
                    remaining,
                )
            )

            if not chunk:
                break

            remaining -= len(chunk)

    def _read_json_with_limit(
        self,
        *,
        max_bytes,
        length_error,
    ) -> dict[str, Any]:
        raw_length = self.headers.get(
            "Content-Length",
            "0",
        )

        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError(
                length_error
            ) from exc

        if length <= 0:
            raise ValueError(
                length_error
            )

        if length > max_bytes:
            self._drain_request_body(
                length
            )

            raise ValueError(
                length_error
            )

        raw = self.rfile.read(
            length
        )

        try:
            payload = json.loads(
                raw.decode(
                    "utf-8"
                )
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError(
                "QCC_REQUEST_JSON_INVALID"
            ) from exc

        if not isinstance(
            payload,
            dict,
        ):
            raise ValueError(
                "QCC_REQUEST_JSON_INVALID"
            )

        return payload

    def _read_json(
        self,
    ) -> dict[str, Any]:
        return self._read_json_with_limit(
            max_bytes=QCC_REQUEST_MAX_BYTES,
            length_error="QCC_REQUEST_LENGTH_INVALID",
        )

    def _read_binary_with_limit(
        self,
        *,
        max_bytes,
        length_error,
    ) -> bytes:
        """
        Lee un artefacto binario con Content-Length
        obligatorio y límite independiente.

        No interpreta ni transforma el contenido.
        La validación semántica del PNG pertenece
        al ingestor.
        """

        raw_length = self.headers.get(
            "Content-Length",
            "0",
        )

        try:
            length = int(
                raw_length
            )

        except ValueError as exc:
            raise ValueError(
                length_error
            ) from exc

        if length <= 0:
            raise ValueError(
                length_error
            )

        if length > max_bytes:
            self._drain_request_body(
                length
            )

            raise ValueError(
                length_error
            )

        content = self.rfile.read(
            length
        )

        if len(content) != length:
            raise ValueError(
                length_error
            )

        return content

    def do_GET(self) -> None:
        if self.path == "/qcc/health":
            self._send_json(
                200,
                _health_payload(),
            )
            return

        if self.path == "/qcc/context":
            context_store = getattr(
                self.server,
                "qcc_context_store",
                None,
            )

            if context_store is None:
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_CONTEXT_UNAVAILABLE",
                    },
                )
                return

            self._send_json(
                200,
                context_store.snapshot(),
            )
            return

        self._send_json(
            404,
            {
                "error": "QCC_ROUTE_NOT_FOUND",
            },
        )

    def do_POST(self) -> None:
        parsed = urlparse(
            self.path
        )

        path = (
            parsed.path.rstrip("/")
            or "/"
        )

        context_store = getattr(
            self.server,
            "qcc_context_store",
            None,
        )

        browser_registry = getattr(
            self.server,
            "qcc_browser_registry",
            None,
        )

        # QCC_MULTI_BROWSER_SESSION_ROUTING_V1
        #
        # Toda ruta explícitamente dirigida a
        # /qcc/session/<id>/... trabaja contra el
        # QccContextStore propietario de ESA sesión.
        #
        # Las sesiones legacy sin browser_profile_key
        # siguen usando context_store global.
        route_session_id = (
            _qcc_session_id_from_path(
                path
            )
        )

        if route_session_id:
            context_store = (
                _qcc_resolve_context_store_for_session(
                    legacy_store=(
                        context_store
                    ),
                    browser_registry=(
                        browser_registry
                    ),
                    session_id=(
                        route_session_id
                    ),
                )
            )

        action_store = getattr(
            self.server,
            "qcc_action_store",
            None,
        )

        tool_store = getattr(
            self.server,
            "qcc_tool_store",
            None,
        )

        # ---------------------------------------------
        # QCC_CANONICAL_OBSERVE_BRIDGE_V1
        #
        # POST /qcc/site-architecture/observe
        #
        # Gate analítico previo a persistencia.
        #
        # IMPORTANTE:
        # - no genera capture_id;
        # - no escribe archivos;
        # - no proyecta navegación viva;
        # - no modifica knowledge;
        # - fingerprint pertenece al backend.
        # ---------------------------------------------
        if (
            path
            == "/qcc/site-architecture/observe"
        ):
            ingestor = getattr(
                self.server,
                "qcc_site_architecture_ingestor",
                None,
            )

            if ingestor is None:
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_SITE_ARCHITECTURE_UNAVAILABLE",
                    },
                )
                return

            try:
                payload = (
                    self._read_json_with_limit(
                        max_bytes=(
                            QCC_SITE_ARCHITECTURE_MAX_BYTES
                        ),
                        length_error=(
                            "QCC_SITE_ARCHITECTURE_REQUEST_TOO_LARGE"
                        ),
                    )
                )

                if (
                    payload.get(
                        "protocol_version"
                    )
                    != QCC_PROTOCOL_VERSION
                ):
                    raise ValueError(
                        "QCC_PROTOCOL_VERSION_INVALID"
                    )

                capture = payload.get(
                    "capture"
                )

                if not isinstance(
                    capture,
                    dict,
                ):
                    raise ValueError(
                        "QCC_SITE_ARCHITECTURE_CAPTURE_INVALID"
                    )

                result = (
                    ingestor.observe_candidate(
                        capture
                    )
                )

                baseline_capture_id = str(
                    payload.get(
                        "baseline_capture_id"
                    )
                    or ""
                ).strip()

                baseline_fingerprint = None
                changed = None

                if baseline_capture_id:
                    baseline_fingerprint = (
                        ingestor
                        .persisted_capture_fingerprint(
                            baseline_capture_id
                        )
                    )

                    changed = (
                        result[
                            "fingerprint"
                        ]
                        != baseline_fingerprint
                    )

            except ValueError as exc:
                self._send_json(
                    400,
                    {
                        "error":
                            str(exc),
                    },
                )
                return

            self._send_json(
                200,
                {
                    "ok":
                        True,

                    "persisted":
                        False,

                    "baseline_capture_id":
                        (
                            baseline_capture_id
                            or None
                        ),

                    "baseline_fingerprint":
                        baseline_fingerprint,

                    "changed":
                        changed,

                    "fingerprint":
                        result[
                            "fingerprint"
                        ],

                    "site_code":
                        result[
                            "site_code"
                        ],

                    "state_observation":
                        result[
                            "state_observation"
                        ],

                    "page":
                        result[
                            "page"
                        ],

                    "counts":
                        result[
                            "counts"
                        ],
                },
            )
            return

        # ---------------------------------------------
        # QCC Extension -> Bridge: PAGE ARCHIVE
        # POST /qcc/site-architecture/page-artifact
        #
        # Adjunta page.mhtml a una captura
        # Site Architecture ya persistida.
        # ---------------------------------------------
        if (
            path
            == "/qcc/site-architecture/page-artifact"
        ):
            ingestor = getattr(
                self.server,
                "qcc_site_architecture_ingestor",
                None,
            )

            if ingestor is None:
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_SITE_ARCHITECTURE_UNAVAILABLE",
                    },
                )
                return

            try:
                protocol_version = str(
                    self.headers.get(
                        "X-QCC-Protocol-Version",
                        "",
                    )
                    or ""
                ).strip()

                if (
                    protocol_version
                    != str(
                        QCC_PROTOCOL_VERSION
                    )
                ):
                    raise ValueError(
                        "QCC_PROTOCOL_VERSION_INVALID"
                    )

                capture_id = str(
                    self.headers.get(
                        "X-QCC-Capture-Id",
                        "",
                    )
                    or ""
                ).strip()

                if not capture_id:
                    raise ValueError(
                        "QCC_PAGE_ARCHIVE_CAPTURE_ID_REQUIRED"
                    )

                artifact_kind = str(
                    self.headers.get(
                        "X-QCC-Page-Kind",
                        "",
                    )
                    or ""
                ).strip().lower()

                if artifact_kind != "mhtml":
                    raise ValueError(
                        "QCC_PAGE_ARCHIVE_KIND_INVALID"
                    )

                content_type = str(
                    self.headers.get(
                        "Content-Type",
                        "",
                    )
                    or ""
                )

                normalized_content_type = (
                    content_type
                    .split(
                        ";",
                        1,
                    )[0]
                    .strip()
                    .lower()
                )

                if normalized_content_type not in {
                    "multipart/related",
                    "application/x-mimearchive",
                }:
                    raise ValueError(
                        "QCC_PAGE_ARCHIVE_CONTENT_TYPE_INVALID"
                    )

                content = (
                    self._read_binary_with_limit(
                        max_bytes=(
                            64
                            * 1024
                            * 1024
                        ),
                        length_error=(
                            "QCC_PAGE_ARCHIVE_REQUEST_TOO_LARGE"
                        ),
                    )
                )

                result = (
                    ingestor
                    .attach_page_archive_artifact(
                        capture_id,
                        kind=artifact_kind,
                        content=content,
                    )
                )

            except ValueError as exc:
                self._send_json(
                    400,
                    {
                        "error":
                            str(exc),
                    },
                )
                return

            self._send_json(
                200,
                {
                    "ok":
                        True,

                    "capture_id":
                        result[
                            "capture_id"
                        ],

                    "kind":
                        result[
                            "kind"
                        ],

                    "artifact":
                        result[
                            "artifact"
                        ],

                    "content_type":
                        result[
                            "content_type"
                        ],

                    "bytes":
                        result[
                            "bytes"
                        ],
                },
            )
            return

        # ---------------------------------------------
        # QCC Extension -> Bridge:
        # POST /qcc/site-architecture/visual-artifact
        #
        # Adjunta evidencia visual binaria a una
        # captura Site Architecture YA persistida.
        #
        # El PNG NO forma parte de qcc_capture.json.
        # ---------------------------------------------
        if (
            path
            == "/qcc/site-architecture/visual-artifact"
        ):
            ingestor = getattr(
                self.server,
                "qcc_site_architecture_ingestor",
                None,
            )

            if ingestor is None:
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_SITE_ARCHITECTURE_UNAVAILABLE",
                    },
                )
                return

            try:
                protocol_version = str(
                    self.headers.get(
                        "X-QCC-Protocol-Version",
                        "",
                    )
                    or ""
                ).strip()

                if (
                    protocol_version
                    != str(
                        QCC_PROTOCOL_VERSION
                    )
                ):
                    raise ValueError(
                        "QCC_PROTOCOL_VERSION_INVALID"
                    )

                capture_id = str(
                    self.headers.get(
                        "X-QCC-Capture-Id",
                        "",
                    )
                    or ""
                ).strip()

                if not capture_id:
                    raise ValueError(
                        "QCC_VISUAL_ARTIFACT_CAPTURE_ID_REQUIRED"
                    )

                artifact_kind = str(
                    self.headers.get(
                        "X-QCC-Visual-Kind",
                        "",
                    )
                    or ""
                ).strip().lower()

                if not artifact_kind:
                    raise ValueError(
                        "QCC_VISUAL_ARTIFACT_KIND_REQUIRED"
                    )

                content_type = str(
                    self.headers.get(
                        "Content-Type",
                        "",
                    )
                    or ""
                )

                normalized_content_type = (
                    content_type
                    .split(
                        ";",
                        1,
                    )[0]
                    .strip()
                    .lower()
                )

                if (
                    normalized_content_type
                    != "image/png"
                ):
                    raise ValueError(
                        "QCC_VISUAL_ARTIFACT_CONTENT_TYPE_INVALID"
                    )

                content = (
                    self._read_binary_with_limit(
                        max_bytes=(
                            QCC_VISUAL_ARTIFACT_MAX_BYTES
                        ),
                        length_error=(
                            "QCC_VISUAL_ARTIFACT_REQUEST_TOO_LARGE"
                        ),
                    )
                )

                result = (
                    ingestor.attach_visual_artifact(
                        capture_id,
                        kind=artifact_kind,
                        content=content,
                    )
                )

            except ValueError as exc:
                self._send_json(
                    400,
                    {
                        "error":
                            str(exc),
                    },
                )
                return

            self._send_json(
                200,
                {
                    "ok":
                        True,

                    "capture_id":
                        result[
                            "capture_id"
                        ],

                    "kind":
                        result[
                            "kind"
                        ],

                    "artifact":
                        result[
                            "artifact"
                        ],

                    "content_type":
                        result[
                            "content_type"
                        ],

                    "bytes":
                        result[
                            "bytes"
                        ],
                },
            )
            return

        # ---------------------------------------------
        # QCC Extension -> Bridge:
        # POST /qcc/site-architecture/capture
        #
        # Funciona con Chrome manual o con una
        # presentación asistida activa.
        # ---------------------------------------------
        if path == "/qcc/site-architecture/capture":
            ingestor = getattr(
                self.server,
                "qcc_site_architecture_ingestor",
                None,
            )

            navigation_knowledge_store = getattr(
                self.server,
                "qcc_navigation_knowledge_store",
                None,
            )

            human_navigation_candidate_store = getattr(
                self.server,
                "qcc_human_navigation_candidate_store",
                None,
            )

            managed_governance_registry = getattr(
                self.server,
                "qcc_managed_governance_registry",
                None,
            )

            if ingestor is None:
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_SITE_ARCHITECTURE_UNAVAILABLE",
                    },
                )
                return

            try:
                payload = self._read_json_with_limit(
                    max_bytes=(
                        QCC_SITE_ARCHITECTURE_MAX_BYTES
                    ),
                    length_error=(
                        "QCC_SITE_ARCHITECTURE_REQUEST_TOO_LARGE"
                    ),
                )

                if (
                    payload.get("protocol_version")
                    != QCC_PROTOCOL_VERSION
                ):
                    raise ValueError(
                        "QCC_PROTOCOL_VERSION_INVALID"
                    )

                capture = payload.get(
                    "capture"
                )

                if not isinstance(
                    capture,
                    dict,
                ):
                    raise ValueError(
                        "QCC_SITE_ARCHITECTURE_CAPTURE_INVALID"
                    )

                browser_profile_key = str(
                    payload.get(
                        "browser_profile_key"
                    )
                    or ""
                ).strip()

                # QCC_SITE_ARCHITECTURE_PROFILE_ROUTING_V1
                #
                # La identidad física/lógica del Chrome
                # se resuelve ANTES del ingest.
                #
                # Si un profile_key explícito todavía no
                # está registrado, la captura queda sin
                # contexto asistido. Nunca hereda la
                # active_session legacy de otro Chrome.
                context_store = (
                    _qcc_resolve_context_store_for_profile(
                        legacy_store=(
                            context_store
                        ),
                        browser_registry=(
                            browser_registry
                        ),
                        browser_profile_key=(
                            browser_profile_key
                        ),
                    )
                )

                context = (
                    context_store.snapshot()
                    if context_store is not None
                    else None
                )

                result = ingestor.ingest(
                    capture,
                    context=context,
                )

                # -------------------------------------
                # RUNTIME ENVIRONMENT SCOPE
                #
                # Para sitios gestionados la URL viva es
                # la única fuente autorizada para decidir
                # LAB / REAL.
                #
                # Nunca se deriva environment del intent,
                # del fingerprint ni del grafo.
                # -------------------------------------
                runtime_navigation_environment = None
                managed_environment_required = False
                block_live_projection = False

                if (
                    context_store is not None
                    and managed_governance_registry
                    is not None
                ):
                    active_session = (
                        context_store
                        .get_active_session()
                    )

                    capture_session_id = str(
                        result.get(
                            "session_id"
                        )
                        or ""
                    ).strip()

                    observed_site_for_scope = str(
                        result.get(
                            "site_code"
                        )
                        or ""
                    ).strip().upper()

                    expected_site_for_scope = (
                        str(
                            active_session.provider
                            or ""
                        ).strip().upper()
                        if active_session
                        is not None
                        else None
                    )

                    # Solo vinculamos environment si la
                    # propia captura ya está ligada a la
                    # sesión/provider activos.
                    if (
                        active_session is not None
                        and capture_session_id
                        == active_session.session_id
                        and observed_site_for_scope
                        == expected_site_for_scope
                    ):
                        governance_registration = (
                            managed_governance_registry
                            .get_by_site_code(
                                observed_site_for_scope
                            )
                        )

                        if (
                            governance_registration
                            is not None
                        ):
                            managed_environment_required = (
                                True
                            )

                            scope_page = (
                                result.get(
                                    "page"
                                )
                                or {}
                            )

                            if not isinstance(
                                scope_page,
                                dict,
                            ):
                                scope_page = {}

                            resolved_scope = (
                                managed_governance_registry
                                .resolve(
                                    url=(
                                        scope_page.get(
                                            "url"
                                        )
                                    ),
                                    site_code=(
                                        observed_site_for_scope
                                    ),
                                )
                            )

                            if resolved_scope is None:
                                # Fail closed.
                                #
                                # Una captura que el
                                # recognizer identifica,
                                # pero cuyo origin no puede
                                # vincularse al sitio
                                # gestionado, nunca puede
                                # convertirse en CURRENT.
                                context_store.clear_live_navigation(
                                    session_id=(
                                        active_session
                                        .session_id
                                    )
                                )

                                block_live_projection = (
                                    True
                                )

                            else:
                                # El ContextStore impide
                                # LAB -> REAL o REAL -> LAB
                                # dentro de la misma
                                # session_id.
                                context_store.set_navigation_environment(
                                    resolved_scope.environment,
                                    session_id=(
                                        active_session
                                        .session_id
                                    ),
                                )

                                runtime_navigation_environment = (
                                    context_store
                                    .get_navigation_environment()
                                )

                if block_live_projection:
                    live_projection = {
                        "projected":
                            False,

                        "reason":
                            LIVE_STATE_SITE_UNRECOGNIZED,

                        "revision":
                            (
                                context_store.revision
                                if context_store
                                is not None
                                else None
                            ),
                    }

                else:
                    live_projection = (
                        project_ingested_state_observation(
                            context_store,
                            result,
                        )
                    )

                # -------------------------------------
                # HUMAN CAUSAL JOIN
                #
                # Si existe una trusted human action
                # pendiente de A, esta nueva CURRENT
                # constituye la observación B candidata.
                #
                # Runtime-only. No NavigationKnowledge.
                # -------------------------------------
                human_transition_evidence = None

                if (
                    live_projection.get(
                        "projected"
                    )
                    is True
                    and context_store is not None
                    and runtime_navigation_environment
                    is not None
                ):
                    try:
                        human_transition_evidence = (
                            correlate_observed_human_transition(
                                context_store,
                                after_site_code=(
                                    result.get(
                                        "site_code"
                                    )
                                ),
                                after_observed_at=(
                                    result.get(
                                        "received_at"
                                    )
                                ),
                            )
                        )

                    except (
                        TypeError,
                        ValueError,
                    ):
                        # Fail closed:
                        # una correlación dudosa nunca
                        # se convierte en transición.
                        human_transition_evidence = None

                # Se añade únicamente al resultado runtime.
                # metadata.json ya fue escrito por el
                # ingestor antes de llegar aquí.
                result[
                    "human_transition_evidence"
                ] = (
                    human_transition_evidence
                    .to_runtime_dict()
                    if human_transition_evidence
                    is not None
                    else None
                )

                # -------------------------------------
                # TRUSTED HUMAN NAVIGATION LEARNING
                #
                # Solo backend:
                # causal evidence -> candidates ->
                # confirmed -> NavigationKnowledge.
                #
                # Un fallo de aprendizaje nunca rompe
                # la captura ni el CURRENT vivo.
                # -------------------------------------
                human_navigation_learning = None

                if (
                    live_projection.get(
                        "projected"
                    )
                    is True
                    and human_navigation_candidate_store
                    is not None
                    and navigation_knowledge_store
                    is not None
                    and runtime_navigation_environment
                    is not None
                    and result.get(
                        "site_code"
                    )
                ):
                    try:
                        human_navigation_learning = (
                            process_observed_human_navigation_learning(
                                human_navigation_candidate_store,
                                navigation_knowledge_store,
                                transition=(
                                    human_transition_evidence
                                ),
                                site_code=(
                                    result.get(
                                        "site_code"
                                    )
                                ),
                                environment=(
                                    runtime_navigation_environment
                                ),
                            )
                        )

                    except (
                        OSError,
                        TypeError,
                        ValueError,
                    ):
                        # Fail closed para aprendizaje.
                        # Fail open para Site Architecture.
                        human_navigation_learning = {
                            "learning_type":
                                "QCC_HUMAN_NAVIGATION_LEARNING",

                            "processed":
                                False,

                            "reason":
                                "LEARNING_FAIL_CLOSED",
                        }

                result[
                    "human_navigation_learning"
                ] = (
                    human_navigation_learning
                )

                human_listener_plan = None

                # -------------------------------------
                # CANONICAL LIVE ACTION EVIDENCE
                #
                # Ligamos el inventario normalizado por
                # backend al CURRENT A exacto.
                #
                # Nunca se publica en /qcc/context.
                # Nunca concede permiso.
                # -------------------------------------
                if (
                    live_projection.get(
                        "projected"
                    )
                    is True
                    and context_store is not None
                    and runtime_navigation_environment
                    is not None
                ):
                    active_for_actions = (
                        context_store
                        .get_active_session()
                    )

                    current_for_actions = (
                        context_store
                        .get_live_navigation()
                    )

                    observation_for_actions = (
                        result.get(
                            "state_observation"
                        )
                        or {}
                    )

                    if (
                        active_for_actions is not None
                        and current_for_actions
                        is not None
                        and isinstance(
                            observation_for_actions,
                            dict,
                        )
                    ):
                        canonical_actions = (
                            _human_addressable_live_actions(
                                result.get(
                                    "live_actions"
                                )
                                or ()
                            )
                        )

                        evidence = (
                            QccLiveActionEvidence(
                                session_id=(
                                    active_for_actions
                                    .session_id
                                ),
                                site_code=(
                                    str(
                                        result.get(
                                            "site_code"
                                        )
                                        or ""
                                    )
                                ),
                                environment=(
                                    runtime_navigation_environment
                                ),
                                before_state=(
                                    current_for_actions
                                    .current_state
                                ),
                                before_fingerprint=(
                                    current_for_actions
                                    .current_fingerprint
                                ),
                                actions=tuple(
                                    canonical_actions
                                ),
                                captured_at=(
                                    datetime.now(
                                        timezone.utc
                                    )
                                ),
                            )
                        )

                        context_store.set_live_action_evidence(
                            evidence
                        )

                        # ---------------------------------
                        # HUMAN LISTENER TRANSPORT PLAN
                        #
                        # Solo locator:
                        # selector + frame_path.
                        #
                        # Nunca policy/kind/environment/
                        # fingerprint.
                        # ---------------------------------
                        try:
                            human_listener_plan = (
                                build_human_listener_plan(
                                    context_store
                                )
                                .to_transport_dict()
                            )

                        except (
                            TypeError,
                            ValueError,
                        ):
                            human_listener_plan = None

                # IMPORTANTE:
                #
                # Solo planificamos si ESTA captura
                # produjo el CURRENT vivo.
                #
                # Una captura manual, ajena al sitio
                # de la sesión o stale nunca puede
                # reactivar/recalcular una ruta usando
                # un CURRENT anterior.
                live_planning = None
                live_governance = None

                if (
                    live_projection.get(
                        "projected"
                    )
                    is True
                    and context_store is not None
                    and navigation_knowledge_store
                    is not None
                    and (
                        not managed_environment_required
                        or runtime_navigation_environment
                        is not None
                    )
                ):
                    # El plan canónico completo existe
                    # únicamente durante ESTA captura.
                    #
                    # Para sitios gestionados usamos el
                    # environment resuelto desde la URL
                    # viva. Para sitios no gestionados
                    # se conserva el namespace GENERIC
                    # histórico.
                    planning_kwargs = {
                        "include_runtime_plan":
                            True,
                    }

                    if (
                        runtime_navigation_environment
                        is not None
                    ):
                        planning_kwargs[
                            "environment"
                        ] = (
                            runtime_navigation_environment
                        )

                    live_planning = (
                        refresh_live_navigation_plan(
                            context_store,
                            navigation_knowledge_store,
                            **planning_kwargs,
                        )
                    )

                    planning_payload = (
                        live_planning.get(
                            "planning"
                        )
                        if isinstance(
                            live_planning,
                            dict,
                        )
                        else None
                    )

                    runtime_plan = (
                        planning_payload.get(
                            "runtime_plan"
                        )
                        if isinstance(
                            planning_payload,
                            dict,
                        )
                        else None
                    )

                    # Solo una planificación producida
                    # por ESTA captura puede gobernarse.
                    if (
                        isinstance(
                            runtime_plan,
                            dict,
                        )
                        and managed_governance_registry
                        is not None
                    ):
                        page = (
                            result.get(
                                "page"
                            )
                            or {}
                        )

                        if not isinstance(
                            page,
                            dict,
                        ):
                            page = {}

                        observed_site_code = (
                            result.get(
                                "site_code"
                            )
                        )

                        # IMPORTANTE:
                        #
                        # Un sitio reconocido/planiﬁcable
                        # no tiene por qué ser todavía un
                        # sitio con ejecución gestionada.
                        #
                        # - no registrado => governance
                        #   no aplica;
                        # - registrado + origin inválido
                        #   => el coordinador devuelve DENY.
                        governance_registration = (
                            managed_governance_registry
                            .get_by_site_code(
                                observed_site_code
                            )
                            if observed_site_code
                            else None
                        )

                        if (
                            governance_registration
                            is not None
                        ):
                            live_governance = (
                                apply_live_navigation_governance(
                                    context_store,
                                    managed_governance_registry,
                                    planning_result=(
                                        live_planning
                                    ),
                                    live_actions=(
                                        result.get(
                                            "live_actions",
                                            (),
                                        )
                                    ),
                                    page_url=(
                                        page.get(
                                            "url"
                                        )
                                    ),
                                    site_code=(
                                        observed_site_code
                                    ),
                                )
                            )

                # -------------------------------------
                # PUBLIC PROJECTION
                #
                # El runtime_plan es exclusivamente
                # efímero. Nunca cruza HTTP.
                # -------------------------------------
                public_live_planning = (
                    live_planning
                )

                if isinstance(
                    live_planning,
                    dict,
                ):
                    public_live_planning = dict(
                        live_planning
                    )

                    public_planning = (
                        public_live_planning.get(
                            "planning"
                        )
                    )

                    if isinstance(
                        public_planning,
                        dict,
                    ):
                        public_planning = dict(
                            public_planning
                        )

                        public_planning.pop(
                            "runtime_plan",
                            None,
                        )

                        public_live_planning[
                            "planning"
                        ] = public_planning

            except (
                TypeError,
                ValueError,
            ) as exc:
                self._send_json(
                    400,
                    {
                        "error":
                            str(exc),
                    },
                )
                return

            self._send_json(
                200,
                {
                    "ok":
                        True,
                    "capture_id":
                        result["capture_id"],
                    "context_mode":
                        result["context_mode"],
                    "session_id":
                        result["session_id"],
                    "page":
                        result["page"],

                    "site_code":
                        result.get(
                            "site_code"
                        ),

                    "state_observation":
                        result.get(
                            "state_observation"
                        ),

                    "live_projection":
                        live_projection,

                    "live_planning":
                        public_live_planning,

                    "live_governance":
                        live_governance,

                    # Efímero. No forma parte de
                    # /qcc/context.
                    "human_listener_plan":
                        human_listener_plan,

                    "counts":
                        result["counts"],
                },
            )
            return

        # ---------------------------------------------
        # QCC Extension -> Bridge:
        # POST /qcc/site-architecture/catalog-experiment
        #
        # Analiza en memoria un experimento reversible.
        # NO persiste el payload RAW.
        # ---------------------------------------------
        if (
            path
            == "/qcc/site-architecture/catalog-experiment"
        ):
            try:
                payload = self._read_json_with_limit(
                    max_bytes=(
                        QCC_CATALOG_EXPERIMENT_MAX_BYTES
                    ),
                    length_error=(
                        "QCC_CATALOG_EXPERIMENT_REQUEST_TOO_LARGE"
                    ),
                )

                if (
                    payload.get("protocol_version")
                    != QCC_PROTOCOL_VERSION
                ):
                    raise ValueError(
                        "QCC_PROTOCOL_VERSION_INVALID"
                    )

                experiment = payload.get(
                    "experiment"
                )

                if not isinstance(
                    experiment,
                    dict,
                ):
                    raise ValueError(
                        "QCC_CATALOG_EXPERIMENT_INVALID"
                    )

                analysis = (
                    analyze_qcc_catalog_experiment(
                        experiment
                    )
                )

            except (
                TypeError,
                ValueError,
            ) as exc:
                self._send_json(
                    400,
                    {
                        "error":
                            str(exc),
                    },
                )
                return

            self._send_json(
                200,
                {
                    "ok":
                        True,

                    "source_catalog_key":
                        analysis[
                            "source_catalog_key"
                        ],

                    "evidence_count":
                        analysis[
                            "evidence_count"
                        ],

                    "causal_relations":
                        analysis[
                            "causal_relations"
                        ],

                    "causal_relation_count":
                        analysis[
                            "causal_relation_count"
                        ],

                    "restoration_exact":
                        analysis[
                            "restoration_exact"
                        ],

                    "compared_catalogs":
                        analysis[
                            "compared_catalogs"
                        ],
                },
            )
            return

        # ---------------------------------------------
        # Runtime -> Bridge: snapshot de sesión
        # ---------------------------------------------
        if path == "/qcc/session":
            try:
                payload = self._read_json()

                if (
                    payload.get(
                        "protocol_version"
                    )
                    != QCC_PROTOCOL_VERSION
                ):
                    raise ValueError(
                        "QCC_PROTOCOL_VERSION_INVALID"
                    )

                browser_profile_key = str(
                    payload.get(
                        "browser_profile_key"
                    )
                    or ""
                ).strip()

                raw_session = payload.get(
                    "session"
                )

                session = (
                    QccPresentationSession
                    .from_payload(
                        raw_session
                    )
                )

            except ValueError as exc:
                self._send_json(
                    400,
                    {
                        "error":
                            str(exc),
                    },
                )
                return

            if context_store is None:
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_CONTEXT_UNAVAILABLE",
                    },
                )
                return

            # browser_registry ya está enlazado al
            # principio de do_POST().

            if (
                browser_profile_key
                and browser_registry is None
            ):
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_BROWSER_REGISTRY_UNAVAILABLE",
                    },
                )
                return

            legacy_previous = (
                context_store
                .get_active_session()
            )

            profile_previous = None
            registry_revision = None

            if browser_profile_key:
                profile_store = (
                    browser_registry
                    .get_store(
                        browser_profile_key
                    )
                )

                if profile_store is not None:
                    profile_previous = (
                        profile_store
                        .get_active_session()
                    )

                try:
                    registry_revision = (
                        browser_registry
                        .set_active_session(
                            profile_key=(
                                browser_profile_key
                            ),
                            session=session,
                        )
                    )

                except (
                    TypeError,
                    ValueError,
                ) as exc:
                    self._send_json(
                        409,
                        {
                            "error":
                                str(exc),
                        },
                    )
                    return

            revision = (
                context_store
                .set_active_session(
                    session
                )
            )

            # En modo multi-profile únicamente limpiamos
            # recursos de la sesión anterior DEL MISMO
            # profile_key.
            #
            # Nunca usamos legacy_previous para borrar
            # acciones de otro navegador.
            previous_for_cleanup = (
                profile_previous
                if browser_profile_key
                else legacy_previous
            )

            if (
                previous_for_cleanup is not None
                and previous_for_cleanup.session_id
                != session.session_id
            ):
                if action_store is not None:
                    action_store.clear_session(
                        previous_for_cleanup.session_id
                    )

                if tool_store is not None:
                    tool_store.clear_session(
                        previous_for_cleanup.session_id
                    )

            self._send_json(
                200,
                {
                    "ok":
                        True,

                    "revision":
                        revision,

                    "registry_revision":
                        registry_revision,

                    "session_id":
                        session.session_id,

                    "browser_profile_key":
                        (
                            browser_profile_key
                            or None
                        ),
                },
            )
            return

        # POST /qcc/session/<id>/navigation
        #
        # Proyecta navegación viva ya calculada.
        # El Bridge NO calcula rutas ni permisos.
        # ---------------------------------------------
        navigation_parts = [
            unquote(
                part
            )
            for part
            in path.strip("/").split("/")
            if part
        ]

        is_navigation_route = (
            len(navigation_parts) == 4
            and navigation_parts[0] == "qcc"
            and navigation_parts[1] == "session"
            and navigation_parts[3] == "navigation"
        )

        is_navigation_intent_route = (
            len(navigation_parts) == 4
            and navigation_parts[0] == "qcc"
            and navigation_parts[1] == "session"
            and navigation_parts[3]
                == "navigation-intent"
        )

        if is_navigation_route:
            if context_store is None:
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_LIVE_NAVIGATION_UNAVAILABLE",
                    },
                )
                return

            session_id = str(
                navigation_parts[2]
            ).strip()

            # Leer siempre el body antes de responder.
            # Conserva el comportamiento robusto del
            # resto de canales QCC en Windows.
            try:
                payload = self._read_json()

                if (
                    payload.get(
                        "protocol_version"
                    )
                    != QCC_PROTOCOL_VERSION
                ):
                    raise ValueError(
                        "QCC_PROTOCOL_VERSION_INVALID"
                    )

                navigation = (
                    QccLiveNavigationContext
                    .from_payload(
                        payload.get(
                            "navigation"
                        )
                    )
                )

            except (
                TypeError,
                ValueError,
            ) as exc:
                self._send_json(
                    400,
                    {
                        "error":
                            str(exc),
                    },
                )
                return

            active_session = (
                context_store
                .get_active_session()
            )

            if (
                active_session is None
                or active_session.session_id
                != session_id
            ):
                self._send_json(
                    409,
                    {
                        "error":
                            "QCC_LIVE_NAVIGATION_SESSION_NOT_ACTIVE",
                    },
                )
                return

            if (
                navigation.session_id
                != session_id
            ):
                self._send_json(
                    409,
                    {
                        "error":
                            "QCC_LIVE_NAVIGATION_SESSION_MISMATCH",
                    },
                )
                return

            try:
                revision = (
                    context_store
                    .set_live_navigation(
                        navigation
                    )
                )

            except ValueError:
                # La sesión puede haber cambiado entre
                # la validación anterior y el write.
                self._send_json(
                    409,
                    {
                        "error":
                            "QCC_LIVE_NAVIGATION_SESSION_NOT_ACTIVE",
                    },
                )
                return

            self._send_json(
                200,
                {
                    "ok":
                        True,

                    "revision":
                        revision,

                    "session_id":
                        session_id,
                },
            )
            return

        # ---------------------------------------------
        # Runtime -> Bridge:
        # POST /qcc/session/<id>/navigation-intent
        #
        # intent=dict -> SET
        # intent=null -> CLEAR
        #
        # Declara destino. No ejecuta ni gobierna.
        # ---------------------------------------------
        if is_navigation_intent_route:
            if context_store is None:
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_NAVIGATION_INTENT_UNAVAILABLE",
                    },
                )
                return

            session_id = str(
                navigation_parts[2]
            ).strip()

            try:
                payload = (
                    self._read_json()
                )

                if (
                    payload.get(
                        "protocol_version"
                    )
                    != QCC_PROTOCOL_VERSION
                ):
                    raise ValueError(
                        "QCC_PROTOCOL_VERSION_INVALID"
                    )

                raw_intent = payload.get(
                    "intent"
                )

                intent = (
                    None
                    if raw_intent is None
                    else (
                        QccNavigationIntent
                        .from_payload(
                            raw_intent
                        )
                    )
                )

            except (
                TypeError,
                ValueError,
            ) as exc:
                self._send_json(
                    400,
                    {
                        "error":
                            str(exc),
                    },
                )
                return

            active_session = (
                context_store
                .get_active_session()
            )

            if (
                active_session is None
                or active_session.session_id
                != session_id
            ):
                self._send_json(
                    409,
                    {
                        "error":
                            "QCC_NAVIGATION_INTENT_SESSION_NOT_ACTIVE",
                    },
                )
                return

            # -----------------------------------------
            # CLEAR
            # -----------------------------------------
            if intent is None:
                cleared = (
                    context_store
                    .clear_navigation_intent(
                        session_id=(
                            session_id
                        )
                    )
                )

                planning = (
                    clear_live_navigation_plan(
                        context_store
                    )
                )

                self._send_json(
                    200,
                    {
                        "ok":
                            True,

                        "session_id":
                            session_id,

                        "cleared":
                            bool(
                                cleared
                            ),

                        "revision":
                            context_store.revision,

                        "live_planning":
                            planning,
                    },
                )
                return

            # -----------------------------------------
            # SET
            # -----------------------------------------
            if (
                intent.session_id
                != session_id
            ):
                self._send_json(
                    409,
                    {
                        "error":
                            "QCC_NAVIGATION_INTENT_SESSION_MISMATCH",
                    },
                )
                return

            expected_site = str(
                active_session.provider
                or ""
            ).strip().upper()

            if (
                intent.site_code
                != expected_site
            ):
                self._send_json(
                    409,
                    {
                        "error":
                            "QCC_NAVIGATION_INTENT_SITE_MISMATCH",
                    },
                )
                return

            try:
                revision = (
                    context_store
                    .set_navigation_intent(
                        intent
                    )
                )

            except ValueError as exc:
                self._send_json(
                    409,
                    {
                        "error":
                            str(exc),
                    },
                )
                return

            # Si CURRENT ya existe, el destino nuevo
            # debe reflejarse inmediatamente.
            planning = None

            navigation_knowledge_store = getattr(
                self.server,
                "qcc_navigation_knowledge_store",
                None,
            )

            managed_governance_registry = getattr(
                self.server,
                "qcc_managed_governance_registry",
                None,
            )

            runtime_navigation_environment = (
                context_store
                .get_navigation_environment()
            )

            managed_environment_required = False

            if (
                managed_governance_registry
                is not None
            ):
                managed_environment_required = (
                    managed_governance_registry
                    .get_by_site_code(
                        intent.site_code
                    )
                    is not None
                )

            if (
                navigation_knowledge_store
                is not None
                and context_store
                .get_live_navigation()
                is not None
                and (
                    not managed_environment_required
                    or runtime_navigation_environment
                    is not None
                )
            ):
                planning_kwargs = {}

                if (
                    runtime_navigation_environment
                    is not None
                ):
                    planning_kwargs[
                        "environment"
                    ] = (
                        runtime_navigation_environment
                    )

                planning = (
                    refresh_live_navigation_plan(
                        context_store,
                        navigation_knowledge_store,
                        **planning_kwargs,
                    )
                )

            self._send_json(
                200,
                {
                    "ok":
                        True,

                    "session_id":
                        session_id,

                    "revision":
                        (
                            context_store.revision
                            if planning is not None
                            else revision
                        ),

                    "live_planning":
                        planning,
                },
            )
            return

        # ---------------------------------------------
        # QCC Extension -> Bridge:
        # POST /qcc/session/<id>/human-dom-action
        #
        # Señal mínima de una acción física observada.
        #
        # El navegador NO puede aportar:
        # - policy
        # - kind
        # - site_code
        # - environment
        # - before_state
        # - before_fingerprint
        #
        # Todo ello se reconstruye desde la evidencia
        # canónica runtime asociada al CURRENT A.
        # ---------------------------------------------
        human_action_parts = [
            unquote(
                part
            )
            for part
            in path.strip("/").split("/")
            if part
        ]

        is_human_dom_action_route = (
            len(
                human_action_parts
            )
            == 4
            and human_action_parts[0]
            == "qcc"
            and human_action_parts[1]
            == "session"
            and human_action_parts[3]
            == "human-dom-action"
        )

        if is_human_dom_action_route:
            if context_store is None:
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_CONTEXT_UNAVAILABLE",
                    },
                )
                return

            session_id = (
                human_action_parts[2]
            )

            try:
                payload = (
                    self._read_json_with_limit(
                        max_bytes=(
                            QCC_REQUEST_MAX_BYTES
                        ),
                        length_error=(
                            "QCC_HUMAN_DOM_ACTION_REQUEST_TOO_LARGE"
                        ),
                    )
                )

                if (
                    payload.get(
                        "protocol_version"
                    )
                    != QCC_PROTOCOL_VERSION
                ):
                    raise ValueError(
                        "QCC_PROTOCOL_VERSION_INVALID"
                    )

                allowed_top_level = {
                    "protocol_version",
                    "signal",
                }

                if (
                    set(
                        payload
                    )
                    != allowed_top_level
                ):
                    raise ValueError(
                        "QCC_HUMAN_DOM_ACTION_PAYLOAD_INVALID"
                    )

                signal_payload = (
                    payload.get(
                        "signal"
                    )
                )

                if not isinstance(
                    signal_payload,
                    dict,
                ):
                    raise ValueError(
                        "QCC_HUMAN_DOM_SIGNAL_INVALID"
                    )

                allowed_signal_fields = {
                    "event_id",
                    "selector",
                    "frame_path",
                    "observed_at",
                }

                if (
                    set(
                        signal_payload
                    )
                    != allowed_signal_fields
                ):
                    raise ValueError(
                        "QCC_HUMAN_DOM_SIGNAL_FIELD_INVALID"
                    )

                raw_observed_at = str(
                    signal_payload.get(
                        "observed_at"
                    )
                    or ""
                ).strip()

                if not raw_observed_at:
                    raise ValueError(
                        "QCC_HUMAN_DOM_SIGNAL_TIME_REQUIRED"
                    )

                if raw_observed_at.endswith(
                    "Z"
                ):
                    raw_observed_at = (
                        raw_observed_at[:-1]
                        + "+00:00"
                    )

                try:
                    observed_at = (
                        datetime.fromisoformat(
                            raw_observed_at
                        )
                    )

                except ValueError as exc:
                    raise ValueError(
                        "QCC_HUMAN_DOM_SIGNAL_TIME_INVALID"
                    ) from exc

                signal = (
                    QccHumanDomSignal(
                        event_id=(
                            signal_payload.get(
                                "event_id"
                            )
                        ),
                        session_id=(
                            session_id
                        ),
                        selector=(
                            signal_payload.get(
                                "selector"
                            )
                        ),
                        frame_path=(
                            signal_payload.get(
                                "frame_path"
                            )
                        ),
                        observed_at=(
                            observed_at
                        ),
                    )
                )

                observed = (
                    canonicalize_human_dom_signal(
                        context_store,
                        signal,
                    )
                )

            except (
                TypeError,
                ValueError,
            ) as exc:
                error = str(
                    exc
                )

                conflict_errors = {
                    "QCC_HUMAN_DOM_SIGNAL_SESSION_NOT_ACTIVE",
                    "QCC_HUMAN_DOM_SIGNAL_CURRENT_REQUIRED",
                    "QCC_HUMAN_DOM_SIGNAL_CURRENT_SESSION_MISMATCH",
                    "QCC_HUMAN_DOM_SIGNAL_ENVIRONMENT_REQUIRED",
                    "QCC_HUMAN_DOM_SIGNAL_EVIDENCE_REQUIRED",
                    "QCC_HUMAN_DOM_SIGNAL_EVIDENCE_SESSION_MISMATCH",
                    "QCC_HUMAN_DOM_SIGNAL_EVIDENCE_ENVIRONMENT_MISMATCH",
                    "QCC_HUMAN_DOM_SIGNAL_EVIDENCE_FINGERPRINT_MISMATCH",
                    "QCC_HUMAN_DOM_SIGNAL_ACTION_AMBIGUOUS",
                    "QCC_OBSERVED_HUMAN_ACTION_AMBIGUOUS",
                }

                self._send_json(
                    (
                        409
                        if error
                        in conflict_errors
                        else 400
                    ),
                    {
                        "error":
                            error,
                    },
                )
                return

            # Respuesta deliberadamente mínima.
            #
            # No devolvemos policy, kind, selector,
            # environment ni fingerprint.
            self._send_json(
                200,
                {
                    "ok":
                        True,

                    "accepted":
                        True,

                    "event_id":
                        observed.event_id,
                },
            )
            return

        # ---------------------------------------------
        # Side Panel -> Bridge:
        # POST /qcc/session/<id>/tool
        #
        # Runtime -> Bridge:
        # POST /qcc/session/<id>/tool/consume
        # ---------------------------------------------
        tool_parts = [
            unquote(
                part
            )
            for part
            in path.strip("/").split("/")
            if part
        ]

        is_tool_route = (
            len(tool_parts) == 4
            and tool_parts[0] == "qcc"
            and tool_parts[1] == "session"
            and tool_parts[3] == "tool"
        )

        is_tool_consume_route = (
            len(tool_parts) == 5
            and tool_parts[0] == "qcc"
            and tool_parts[1] == "session"
            and tool_parts[3] == "tool"
            and tool_parts[4] == "consume"
        )

        if (
            is_tool_route
            or is_tool_consume_route
        ):
            if (
                context_store is None
                or tool_store is None
            ):
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_TOOL_CHANNEL_UNAVAILABLE",
                    },
                )
                return

            session_id = str(
                tool_parts[2]
            ).strip()

            try:
                payload = self._read_json()

                if (
                    payload.get(
                        "protocol_version"
                    )
                    != QCC_PROTOCOL_VERSION
                ):
                    raise ValueError(
                        "QCC_PROTOCOL_VERSION_INVALID"
                    )

            except ValueError as exc:
                self._send_json(
                    400,
                    {
                        "error":
                            str(exc),
                    },
                )
                return

            active_session = (
                context_store
                .get_active_session()
            )

            if (
                active_session is None
                or active_session.session_id
                != session_id
            ):
                self._send_json(
                    409,
                    {
                        "error":
                            "QCC_TOOL_SESSION_NOT_ACTIVE",
                    },
                )
                return

            if is_tool_route:
                try:
                    request = (
                        QccToolRequest
                        .from_payload(
                            payload,
                            session_id=session_id,
                        )
                    )

                    queued = (
                        tool_store
                        .submit(
                            request
                        )
                    )

                except (
                    TypeError,
                    ValueError,
                ) as exc:
                    self._send_json(
                        400,
                        {
                            "error":
                                str(exc),
                        },
                    )
                    return

                self._send_json(
                    200,
                    {
                        "ok":
                            True,

                        "tool_request_id":
                            queued.tool_request_id,

                        "session_id":
                            session_id,

                        "pending":
                            tool_store
                            .pending_count(
                                session_id
                            ),
                    },
                )
                return

            queued_tool = (
                tool_store
                .consume_next(
                    session_id
                )
            )

            self._send_json(
                200,
                {
                    "ok":
                        True,

                    "available":
                        queued_tool
                        is not None,

                    "tool":
                        (
                            queued_tool
                            .to_payload()
                            if queued_tool
                            is not None
                            else None
                        ),

                    "pending":
                        tool_store
                        .pending_count(
                            session_id
                        ),
                },
            )
            return

        # ---------------------------------------------
        # Side Panel -> Bridge:
        # POST /qcc/session/<id>/action
        #
        # Runtime -> Bridge:
        # POST /qcc/session/<id>/action/consume
        # ---------------------------------------------
        parts = [
            unquote(
                part
            )
            for part
            in path.strip("/").split("/")
            if part
        ]

        is_action_route = (
            len(parts) == 4
            and parts[0] == "qcc"
            and parts[1] == "session"
            and parts[3] == "action"
        )

        is_consume_route = (
            len(parts) == 5
            and parts[0] == "qcc"
            and parts[1] == "session"
            and parts[3] == "action"
            and parts[4] == "consume"
        )

        if not (
            is_action_route
            or is_consume_route
        ):
            self._send_json(
                404,
                {
                    "error":
                        "QCC_ROUTE_NOT_FOUND",
                },
            )
            return

        if (
            context_store is None
            or action_store is None
        ):
            self._send_json(
                503,
                {
                    "error":
                        "QCC_ACTION_CHANNEL_UNAVAILABLE",
                },
            )
            return

        session_id = str(
            parts[2]
        ).strip()

        # Leer SIEMPRE el body antes de responder.
        #
        # En Windows, cerrar una conexión HTTP con bytes
        # de request todavía pendientes puede provocar
        # WinError 10053 en el cliente en lugar de permitir
        # que urllib lea correctamente nuestro 4xx.
        try:
            payload = self._read_json()

            if (
                payload.get(
                    "protocol_version"
                )
                != QCC_PROTOCOL_VERSION
            ):
                raise ValueError(
                    "QCC_PROTOCOL_VERSION_INVALID"
                )

        except ValueError as exc:
            self._send_json(
                400,
                {
                    "error":
                        str(exc),
                },
            )
            return

        active_session = (
            context_store
            .get_active_session()
        )

        if (
            active_session is None
            or active_session.session_id
            != session_id
        ):
            self._send_json(
                409,
                {
                    "error":
                        "QCC_ACTION_SESSION_NOT_ACTIVE",
                },
            )
            return

        if is_action_route:
            try:
                request = (
                    QccActionRequest
                    .from_payload(
                        payload,
                        session_id=session_id,
                    )
                )

                queued = (
                    action_store
                    .submit(
                        request
                    )
                )

            except (
                TypeError,
                ValueError,
            ) as exc:
                self._send_json(
                    400,
                    {
                        "error":
                            str(exc),
                    },
                )
                return

            self._send_json(
                200,
                {
                    "ok":
                        True,

                    "action_id":
                        queued.action_id,

                    "session_id":
                        session_id,

                    "pending":
                        action_store
                        .pending_count(
                            session_id
                        ),
                },
            )
            return

        action = (
            action_store
            .consume_next(
                session_id
            )
        )

        self._send_json(
            200,
            {
                "ok":
                    True,

                "available":
                    action is not None,

                "action":
                    (
                        action.to_payload()
                        if action is not None
                        else None
                    ),

                "pending":
                    action_store
                    .pending_count(
                        session_id
                    ),
            },
        )

    def log_message(
        self,
        format: str,
        *args: object,
    ) -> None:
        # Evitamos ruido de requests HTTP en consola.
        return


def _qcc_session_id_from_path(
    path,
) -> str | None:
    """Extrae session_id de rutas /qcc/session/<id>/..."""

    normalized_path = str(
        path
        or ""
    ).strip()

    prefix = "/qcc/session/"

    if not normalized_path.startswith(
        prefix
    ):
        return None

    remainder = normalized_path[
        len(prefix):
    ]

    raw_session_id = (
        remainder.split(
            "/",
            1,
        )[0]
    )

    session_id = unquote(
        raw_session_id
    ).strip()

    return (
        session_id
        or None
    )


def _qcc_resolve_context_store_for_session(
    *,
    legacy_store,
    browser_registry,
    session_id,
):
    """Resuelve el contexto exacto de una sesión.

    Prioridad:
    1. BrowserRegistry si conoce session_id.
    2. QccContextStore legacy para compatibilidad.

    No altera ningún store.
    """

    normalized_session_id = str(
        session_id
        or ""
    ).strip()

    if not normalized_session_id:
        return legacy_store

    if browser_registry is not None:
        registered_store = (
            browser_registry
            .get_store_for_session(
                normalized_session_id
            )
        )

        if registered_store is not None:
            return registered_store

    return legacy_store


def _qcc_resolve_context_store_for_profile(
    *,
    legacy_store,
    browser_registry,
    browser_profile_key,
):
    """Resuelve contexto Site Architecture por profile_key.

    Reglas:
    - sin profile_key: compatibilidad legacy;
    - profile conocido: store exacto;
    - profile explícito desconocido: sin contexto;
    - nunca hereda otro profile desde legacy.
    """

    normalized_profile_key = str(
        browser_profile_key
        or ""
    ).strip()

    if not normalized_profile_key:
        return legacy_store

    if browser_registry is None:
        return None

    try:
        return browser_registry.get_store(
            normalized_profile_key
        )

    except (
        TypeError,
        ValueError,
    ):
        return None


class QccBridgeServer:
    """Owner explícito del servidor HTTP local QCC."""

    def __init__(
        self,
        *,
        host: str = QCC_BRIDGE_HOST,
        port: int = QCC_BRIDGE_PORT,
        context_store: (
            QccContextStore
            | None
        ) = None,
        browser_registry: (
            QccBrowserRegistry
            | None
        ) = None,
        action_store: (
            QccActionStore
            | None
        ) = None,
        tool_store: (
            QccToolStore
            | None
        ) = None,
        site_architecture_ingestor: (
            QccSiteArchitectureIngestor
            | None
        ) = None,
        navigation_knowledge_store: (
            NavigationKnowledgeStore
            | None
        ) = None,
        human_navigation_candidate_store: (
            HumanNavigationCandidateStore
            | None
        ) = None,
        managed_governance_registry: (
            ManagedSiteGovernanceRegistry
            | None
        ) = None,
    ) -> None:
        if host != QCC_BRIDGE_HOST:
            raise ValueError(
                "QCC_BRIDGE_LOOPBACK_ONLY"
            )

        self._context_store = (
            context_store
            if context_store is not None
            else QccContextStore()
        )

        self._browser_registry = (
            browser_registry
            if browser_registry is not None
            else QccBrowserRegistry()
        )

        self._action_store = (
            action_store
            if action_store is not None
            else QccActionStore()
        )

        self._tool_store = (
            tool_store
            if tool_store is not None
            else QccToolStore()
        )

        self._site_architecture_ingestor = (
            site_architecture_ingestor
            if site_architecture_ingestor is not None
            else QccSiteArchitectureIngestor()
        )

        self._navigation_knowledge_store = (
            navigation_knowledge_store
            if navigation_knowledge_store is not None
            else NavigationKnowledgeStore()
        )

        self._human_navigation_candidate_store = (
            human_navigation_candidate_store
            if human_navigation_candidate_store is not None
            else HumanNavigationCandidateStore()
        )

        self._managed_governance_registry = (
            managed_governance_registry
            if managed_governance_registry
            is not None
            else (
                build_default_managed_site_governance_registry()
            )
        )

        self._server = ThreadingHTTPServer(
            (host, port),
            _QccBridgeHandler,
        )

        self._server.qcc_context_store = (
            self._context_store
        )

        self._server.qcc_browser_registry = (
            self._browser_registry
        )

        self._server.qcc_action_store = (
            self._action_store
        )

        self._server.qcc_tool_store = (
            self._tool_store
        )

        self._server.qcc_site_architecture_ingestor = (
            self._site_architecture_ingestor
        )

        self._server.qcc_navigation_knowledge_store = (
            self._navigation_knowledge_store
        )

        self._server.qcc_human_navigation_candidate_store = (
            self._human_navigation_candidate_store
        )

        self._server.qcc_managed_governance_registry = (
            self._managed_governance_registry
        )

        self._thread: threading.Thread | None = None

    @property
    def host(self) -> str:
        return str(
            self._server.server_address[0]
        )

    @property
    def port(self) -> int:
        return int(
            self._server.server_address[1]
        )

    @property
    def context_store(
        self,
    ) -> QccContextStore:
        return self._context_store

    @property
    def browser_registry(
        self,
    ) -> QccBrowserRegistry:
        return self._browser_registry

    @property
    def action_store(
        self,
    ) -> QccActionStore:
        return self._action_store

    @property
    def tool_store(
        self,
    ) -> QccToolStore:
        return self._tool_store

    @property
    def navigation_knowledge_store(
        self,
    ) -> NavigationKnowledgeStore:
        return self._navigation_knowledge_store

    @property
    def human_navigation_candidate_store(
        self,
    ) -> HumanNavigationCandidateStore:
        return self._human_navigation_candidate_store

    @property
    def managed_governance_registry(
        self,
    ) -> ManagedSiteGovernanceRegistry:
        return self._managed_governance_registry

    @property
    def is_running(self) -> bool:
        return bool(
            self._thread
            and self._thread.is_alive()
        )

    def start(self) -> None:
        if self.is_running:
            return

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="qcc-bridge",
            daemon=True,
        )

        self._thread.start()

    def close(self) -> None:
        if self.is_running:
            self._server.shutdown()

        self._server.server_close()

        thread = self._thread

        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=2.0)

        self._thread = None


def run_qcc_bridge_forever() -> None:
    """Entry point manual de desarrollo."""

    server = QccBridgeServer()

    print(
        "[QCC-BRIDGE] listening",
        f"http://{server.host}:{server.port}",
    )

    try:
        server._server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()

        print(
            "[QCC-BRIDGE] closed"
        )


if __name__ == "__main__":
    run_qcc_bridge_forever()
