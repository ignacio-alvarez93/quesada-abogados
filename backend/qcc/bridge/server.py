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
from pathlib import Path
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
    parse_qs,
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
from backend.qcc.auto_twin import (
    AUTO_TWIN_CANDIDATE_STATUS_REJECTED,
    AUTO_TWIN_CANDIDATE_STATUS_VALIDATED,
    AUTO_TWIN_DISCOVERY_PROFILE_KEY,
    AutoTwinCandidateRevisionStore,
    AutoTwinManagedSite,
    AutoTwinManagedSiteStore,
    AutoTwinObservationStore,
    AutoTwinValidationEvidenceStore,
    build_auto_twin_profile_policy,
    load_auto_twin_persisted_capture_bundle,
    project_auto_twin_candidate_revision,
    project_ingested_auto_twin_observation,
    run_auto_twin_validation_evaluation,
)
from backend.qcc.auto_twin.catalog_probe_decision import (
    build_auto_twin_catalog_probe_decision,
)
from backend.qcc.context.human_action_canonicalizer import (
    QccHumanDomSignal,
    canonicalize_human_dom_signal,
    resolve_human_dom_signal,
)
from backend.qcc.context.human_transition_correlator import (
    correlate_observed_human_transition,
    finalize_observed_human_transition,
    finalize_observed_human_transition_against_next_action,
)
from backend.qcc.context.live_action_evidence import (
    QccLiveActionEvidence,
)
from backend.qcc.context.human_listener_plan import (
    build_human_listener_plan,
)
from backend.qcc.context.observation_scope import (
    build_profile_observation_scope,
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
from backend.qcc.auto_twin.catalog_dependency_probe import (
    analyze_auto_twin_governed_catalog_probe,
)
from backend.qcc.auto_twin.catalog_dependency_store import (
    AutoTwinCatalogDependencyStore,
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

QCC_CATALOG_DEPENDENCY_PROBE_MAX_BYTES = (
    64 * 1024 * 1024
)



def _trusted_navigation_context_from_ingest_result(
    result,
):
    # QCC_NAVIGATION_CONTEXT_TRUST_BOUNDARY_V1
    #
    # Semantic navigation context is derived by backend from the
    # exact ingested Snapshot A. The later human DOM signal never
    # supplies semantic branch authority.

    from pathlib import Path

    from backend.qcc.context.navigation_context import (
        normalize_navigation_context,
    )


    def txt(value):
        return str(
            value
            if value is not None
            else ""
        ).strip()


    def checked_value(record):
        if (
            "checked"
            in record
            and isinstance(
                record.get(
                    "checked"
                ),
                bool,
            )
        ):
            return record.get(
                "checked"
            )

        signals = (
            record.get(
                "state_signals"
            )
            or {}
        )

        if (
            isinstance(
                signals,
                dict,
            )
            and isinstance(
                signals.get(
                    "checked"
                ),
                bool,
            )
        ):
            return signals.get(
                "checked"
            )

        return None


    def escape_attribute(value):
        return (
            txt(value)
            .replace(
                "\\",
                "\\\\",
            )
            .replace(
                '"',
                '\\"',
            )
        )


    def walk(value):
        if isinstance(
            value,
            dict,
        ):
            yield value

            for child in (
                value.values()
            ):
                yield from walk(
                    child
                )

        elif isinstance(
            value,
            (
                list,
                tuple,
            ),
        ):
            for child in value:
                yield from walk(
                    child
                )


    def derive(payload):
        groups = {}

        for record in walk(
            payload
        ):
            attributes = (
                record.get(
                    "attributes"
                )
                or {}
            )

            if not isinstance(
                attributes,
                dict,
            ):
                attributes = {}


            tag = (
                txt(
                    record.get(
                        "tag"
                    )
                )
                or txt(
                    attributes.get(
                        "tag"
                    )
                )
            ).lower()


            type_ = (
                txt(
                    record.get(
                        "type"
                    )
                )
                or txt(
                    attributes.get(
                        "type"
                    )
                )
            ).lower()


            if type_ not in {
                "radio",
                "checkbox",
            }:
                continue


            if (
                tag
                and tag != "input"
            ):
                continue


            if (
                checked_value(
                    record
                )
                is not True
            ):
                continue


            kind = (
                "RADIO"
                if type_
                == "radio"
                else "CHECKBOX"
            )


            name = (
                txt(
                    record.get(
                        "name"
                    )
                )
                or txt(
                    attributes.get(
                        "name"
                    )
                )
            )


            element_id = (
                txt(
                    record.get(
                        "id"
                    )
                )
                or txt(
                    attributes.get(
                        "id"
                    )
                )
            )


            if (
                not name
                and not element_id
            ):
                continue


            value = (
                txt(
                    record.get(
                        "value"
                    )
                )
                or txt(
                    attributes.get(
                        "value"
                    )
                )
                or element_id
            )


            if not value:
                continue


            if name:
                selector = (
                    'input[type="'
                    + type_
                    + '"][name="'
                    + escape_attribute(
                        name
                    )
                    + '"]'
                )

                key = (
                    "name:"
                    + name
                    + ":"
                    + kind
                )

            else:
                selector = (
                    '[id="'
                    + escape_attribute(
                        element_id
                    )
                    + '"]'
                )

                key = (
                    "id:"
                    + element_id
                    + ":"
                    + kind
                )


            identity = (
                "main",
                key,
                kind,
                selector,
            )


            group = groups.setdefault(
                identity,
                {
                    "key":
                        key,

                    "selector":
                        selector,

                    "frame_path":
                        "main",

                    "kind":
                        kind,

                    "selected_values":
                        [],
                },
            )


            if (
                value
                not in group[
                    "selected_values"
                ]
            ):
                group[
                    "selected_values"
                ].append(
                    value
                )


        normalized = []

        for group in (
            groups.values()
        ):
            group[
                "selected_values"
            ] = sorted(
                group[
                    "selected_values"
                ]
            )

            normalized.append(
                group
            )


        return (
            normalize_navigation_context(
                normalized
            )
        )


    direct = derive(
        result
    )

    if direct:
        return direct


    capture_ids = []

    for record in walk(
        result
    ):
        for key in (
            "capture_id",
            "source_capture_id",
            "trigger_capture_id",
        ):
            value = txt(
                record.get(
                    key
                )
            )

            if (
                value
                and value
                not in capture_ids
            ):
                capture_ids.append(
                    value
                )


    capture_root = (
        Path("data")
        / "qcc"
        / "site_architecture"
    )


    for capture_id in (
        capture_ids
    ):
        # QCC_TRUSTED_CAPTURE_ID_RESOLUTION_V1
        #
        # Site Architecture may namespace captures below
        # provider/profile/site directories. capture_id remains
        # the immutable exact-evidence identity.
        #
        # Never choose "latest" and never guess:
        # exactly one persisted qcc_capture.json must own the id.
        capture_path = (
            capture_root
            / capture_id
            / "qcc_capture.json"
        )

        if not capture_path.is_file():
            capture_matches = tuple(
                candidate
                for candidate
                in capture_root.rglob(
                    "qcc_capture.json"
                )
                if (
                    candidate.parent.name
                    == capture_id
                )
            )

            if (
                len(
                    capture_matches
                )
                != 1
            ):
                continue

            capture_path = (
                capture_matches[
                    0
                ]
            )

        try:
            import json

            capture = json.loads(
                capture_path.read_text(
                    encoding="utf-8"
                )
            )

        except (
            OSError,
            ValueError,
        ):
            continue


        context = derive(
            capture
        )

        if context:
            return context


    return ()


def _health_payload() -> dict[str, Any]:
    return {
        "service": "qcc_bridge",
        "status": "ok",
        "protocol_version": QCC_PROTOCOL_VERSION,
    }



# ---------------------------------------------------------
# QCC_AUTO_TWIN_AUTOMATIC_MATERIALIZATION_HOOK_V1
#
# Se llama tras cada artefacto profundo.
# Si todavía falta MHTML o viewport devuelve WAITING.
#
# Fail-open:
# una incidencia AUTO TWIN nunca invalida la captura QCC.
# ---------------------------------------------------------
def _qcc_project_auto_twin_materialization_after_artifact(
    *,
    server,
    capture_id,
):
    normalized_capture_id = str(
        capture_id
        or ""
    ).strip()

    if not normalized_capture_id:
        return {
            "status": "SKIPPED",
            "reason": "CAPTURE_ID_EMPTY",
        }

    ingestor = getattr(
        server,
        "qcc_site_architecture_ingestor",
        None,
    )

    managed_store = getattr(
        server,
        "qcc_auto_twin_store",
        None,
    )

    observation_store = getattr(
        server,
        "qcc_auto_twin_observation_store",
        None,
    )

    human_navigation_candidate_store = getattr(
        server,
        "qcc_human_navigation_candidate_store",
        None,
    )

    if (
        ingestor is None
        or managed_store is None
        or observation_store is None
    ):
        return {
            "status": "SKIPPED",
            "reason":
                "AUTO_TWIN_MATERIALIZATION_UNAVAILABLE",
        }

    capture_root = getattr(
        ingestor,
        "output_root",
        None,
    )

    if capture_root is None:
        capture_root = getattr(
            ingestor,
            "_output_root",
            None,
        )

    if capture_root is None:
        return {
            "status": "SKIPPED",
            "reason":
                "SITE_ARCHITECTURE_ROOT_UNAVAILABLE",
        }

    try:
        from backend.qcc.auto_twin.automatic_materialization import (
            reconcile_auto_twin_discovery_materialization,
        )

        reconcile_kwargs = {
            "managed_site_store":
                managed_store,

            "observation_store":
                observation_store,

            "capture_root":
                capture_root,

            "trigger_capture_id":
                normalized_capture_id,

            "human_navigation_candidate_store":
                human_navigation_candidate_store,
        }

        # QCC_AUTO_TWIN_FIXED_POINT_CLOSURE_V1
        #
        # The reconciler deliberately requires both causal transition
        # endpoints to exist physically in the latest immutable Twin
        # revision.
        #
        # Therefore, when pass 1 materializes a newly discovered target
        # state, one bounded second pass closes any transition that has
        # just become materializable.
        #
        # Two passes are sufficient:
        #   pass 1 -> materialize new state(s)
        #   pass 2 -> materialize newly eligible transition(s)
        #
        # If pass 1 is already a no-op, no second pass is needed.
        first_result = (
            reconcile_auto_twin_discovery_materialization(
                **reconcile_kwargs
            )
        )


        if (
            isinstance(
                first_result,
                dict,
            )
            and first_result.get(
                "status"
            )
            == "MATERIALIZED"
        ):
            closure_result = (
                reconcile_auto_twin_discovery_materialization(
                    **reconcile_kwargs
                )
            )


            if (
                isinstance(
                    closure_result,
                    dict,
                )
                and closure_result.get(
                    "status"
                )
                == "MATERIALIZED"
            ):
                final_result = closure_result
            else:
                final_result = first_result

        else:
            final_result = first_result

        # QCC_AUTO_TWIN_NAVIGATION_VALIDATION_QUEUE_V1
        #
        # Never run SeleniumBase inside the ingestion request.
        # The Bridge only publishes the immutable revision locator.
        #
        # NO_CHANGE is intentionally accepted as a recovery path:
        # after a restart, an existing materialized revision may still
        # contain transitions that have not yet been TWIN_VALIDATED.
        if (
            isinstance(
                final_result,
                dict,
            )
            and final_result.get(
                "status"
            )
            in {
                "MATERIALIZED",
                "NO_CHANGE",
            }
        ):
            validation_twin_key = str(
                final_result.get(
                    "twin_key"
                )
                or ""
            ).strip()

            validation_revision_id = str(
                final_result.get(
                    "materialized_revision_id"
                )
                or ""
            ).strip()

            if (
                validation_twin_key
                and validation_revision_id
            ):
                try:
                    from backend.qcc.auto_twin.navigation_transition_validation_coordinator import (
                        get_default_navigation_transition_validation_coordinator,
                    )

                    (
                        get_default_navigation_transition_validation_coordinator()
                        .enqueue(
                            twin_key=(
                                validation_twin_key
                            ),
                            revision_id=(
                                validation_revision_id
                            ),
                        )
                    )

                except Exception as validation_exc:
                    print(
                        "[QCC-AUTO-TWIN-NAV-VALIDATION] ENQUEUE_ERROR",
                        validation_twin_key,
                        validation_revision_id,
                        type(
                            validation_exc
                        ).__name__,
                        str(
                            validation_exc
                        ),
                        flush=True,
                    )

        return final_result

    except Exception as exc:

        return {
            "status":
                "ERROR",

            "reason":
                (
                    type(exc).__name__
                    + ":"
                    + str(exc)
                ),

            "capture_id":
                normalized_capture_id,
        }


def _qcc_bind_discovery_observation_scope(
    *,
    context_store,
    auto_twin_store,
    managed_governance_registry,
    browser_profile_key,
    ingest_result,
):
    """Bind site-level Discovery to its technical runtime scope.

    Provider-neutral.

    Authority:
        registered browser/profile routing
        + AUTO TWIN managed URL
        + Discovery profile policy
        + governed live URL environment

    This function never creates a PresentationSession.
    """

    base = {
        "processed":
            False,

        "reason":
            None,

        "scope_id":
            None,

        "browser_profile_key":
            (
                str(
                    browser_profile_key
                    or ""
                ).strip()
                or None
            ),

        "site_code":
            None,

        "environment":
            None,
    }

    if context_store is None:
        return {
            **base,
            "reason":
                "CONTEXT_UNAVAILABLE",
        }

    # A real business PresentationSession always wins.
    if (
        context_store.get_active_session()
        is not None
    ):
        return {
            **base,
            "reason":
                "PRESENTATION_ACTIVE",
        }

    profile_key = str(
        browser_profile_key
        or ""
    ).strip()

    if not profile_key:
        return {
            **base,
            "reason":
                "PROFILE_UNBOUND",
        }

    if auto_twin_store is None:
        return {
            **base,
            "reason":
                "AUTO_TWIN_STORE_UNAVAILABLE",
        }

    if managed_governance_registry is None:
        return {
            **base,
            "reason":
                "GOVERNANCE_UNAVAILABLE",
        }

    try:
        profile_policy = (
            build_auto_twin_profile_policy(
                profile_key
            )
        )

    except (
        TypeError,
        ValueError,
    ):
        return {
            **base,
            "reason":
                "PROFILE_POLICY_INVALID",
        }

    if (
        getattr(
            profile_policy,
            "active_discovery",
            False,
        )
        is not True
        or getattr(
            profile_policy,
            "observe_managed_twins",
            False,
        )
        is not True
    ):
        return {
            **base,
            "reason":
                "PROFILE_NOT_DISCOVERY",
        }

    if not isinstance(
        ingest_result,
        dict,
    ):
        return {
            **base,
            "reason":
                "INGEST_RESULT_INVALID",
        }

    page = (
        ingest_result.get(
            "page"
        )
        or {}
    )

    if not isinstance(
        page,
        dict,
    ):
        page = {}

    page_url = str(
        page.get(
            "url"
        )
        or ""
    ).strip()

    if not page_url:
        return {
            **base,
            "reason":
                "PAGE_URL_UNAVAILABLE",
        }

    try:
        managed_twin = (
            auto_twin_store.resolve_url(
                page_url
            )
        )

    except (
        TypeError,
        ValueError,
    ):
        managed_twin = None

    if managed_twin is None:
        return {
            **base,
            "reason":
                "URL_NOT_MANAGED",
        }

    if (
        getattr(
            managed_twin,
            "enabled",
            False,
        )
        is not True
    ):
        return {
            **base,
            "reason":
                "MANAGED_TWIN_DISABLED",
        }

    site_code = str(
        getattr(
            managed_twin,
            "site_code",
            None,
        )
        or ""
    ).strip().upper()

    observed_site_code = str(
        ingest_result.get(
            "site_code"
        )
        or ""
    ).strip().upper()

    # QCC_DISCOVERY_MANAGED_SITE_AUTHORITY_V1
    #
    # Discovery site identity is resolved from the managed
    # live URL. The ingestor may legitimately have no provider
    # site_code yet.
    #
    # Missing observation != contradiction.
    #
    # An explicit contradictory site_code remains fail-closed.
    if not site_code:
        return {
            **base,
            "reason":
                "MANAGED_SITE_CODE_UNAVAILABLE",
        }

    if (
        observed_site_code
        and observed_site_code
        != site_code
    ):
        return {
            **base,
            "site_code":
                site_code,

            "reason":
                "SITE_MISMATCH",
        }

    try:
        governed_scope = (
            managed_governance_registry.resolve(
                url=page_url,
                site_code=site_code,
            )
        )

    except (
        TypeError,
        ValueError,
    ):
        governed_scope = None

    if governed_scope is None:
        return {
            **base,
            "site_code":
                site_code,

            "reason":
                "ENVIRONMENT_UNRESOLVED",
        }

    environment = getattr(
        governed_scope,
        "environment",
        None,
    )

    if environment is None:
        return {
            **base,
            "site_code":
                site_code,

            "reason":
                "ENVIRONMENT_UNAVAILABLE",
        }

    try:
        scope = (
            build_profile_observation_scope(
                browser_profile_key=(
                    profile_key
                ),
                site_code=(
                    site_code
                ),
                environment=(
                    environment
                ),
                discovery=True,
            )
        )

        context_store.set_observation_scope(
            scope
        )

        context_store.set_navigation_environment(
            environment,
            session_id=(
                scope.scope_id
            ),
        )

    except (
        TypeError,
        ValueError,
    ):
        return {
            **base,
            "site_code":
                site_code,

            "reason":
                "OBSERVATION_SCOPE_BIND_FAILED",
        }

    normalized_environment = str(
        getattr(
            environment,
            "value",
            environment,
        )
        or ""
    ).strip().upper()

    return {
        **base,

        "processed":
            True,

        "reason":
            "DISCOVERY_SCOPE_BOUND",

        "scope_id":
            scope.scope_id,

        "site_code":
            scope.site_code,

        "environment":
            normalized_environment
            or None,
    }


def _qcc_runtime_site_code(
    *,
    ingest_result,
    discovery_observation_scope,
):
    """Return canonical site identity for live runtime projection.

    QCC_DISCOVERY_RUNTIME_SITE_IDENTITY_V1

    Persistence remains untouched.

    Priority:
    1. explicit ingestor observation when present;
    2. authoritative managed-site ObservationScope when the
       Discovery binding succeeded;
    3. otherwise no site identity.

    Missing observation is not a contradiction.
    """

    observed = ""

    if isinstance(
        ingest_result,
        dict,
    ):
        observed = str(
            ingest_result.get(
                "site_code"
            )
            or ""
        ).strip().upper()

    if observed:
        return observed

    if not isinstance(
        discovery_observation_scope,
        dict,
    ):
        return None

    if (
        discovery_observation_scope.get(
            "processed"
        )
        is not True
    ):
        return None

    bound = str(
        discovery_observation_scope.get(
            "site_code"
        )
        or ""
    ).strip().upper()

    return (
        bound
        or None
    )


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
        parsed = urlparse(
            self.path
        )

        path = (
            parsed.path.rstrip("/")
            or "/"
        )

        if path == "/qcc/health":
            self._send_json(
                200,
                _health_payload(),
            )
            return

        # ---------------------------------------------
        # QCC_MULTI_BROWSER_READ_API_V1
        #
        # GET /qcc/context
        #     -> legacy global
        #
        # GET /qcc/context?browser_profile_key=<key>
        #     -> contexto exacto del profile
        #
        # Un profile desconocido devuelve contexto
        # inactivo y NO se registra como phantom.
        # ---------------------------------------------
        if path == "/qcc/context":
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

            query = parse_qs(
                parsed.query,
                keep_blank_values=True,
            )

            profile_values = query.get(
                "browser_profile_key"
            )

            if profile_values is not None:
                if len(profile_values) != 1:
                    self._send_json(
                        400,
                        {
                            "error":
                                "QCC_BROWSER_PROFILE_KEY_AMBIGUOUS",
                        },
                    )
                    return

                profile_key = str(
                    profile_values[0]
                    or ""
                ).strip()

                if not profile_key:
                    self._send_json(
                        400,
                        {
                            "error":
                                "QCC_BROWSER_PROFILE_KEY_REQUIRED",
                        },
                    )
                    return

                if browser_registry is None:
                    self._send_json(
                        503,
                        {
                            "error":
                                "QCC_BROWSER_REGISTRY_UNAVAILABLE",
                        },
                    )
                    return

                try:
                    snapshot = (
                        browser_registry.snapshot(
                            profile_key
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
                    snapshot,
                )
                return

            # Compatibilidad exacta pre-multi-browser.
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

        # ---------------------------------------------
        # GET /qcc/browsers
        #
        # Inventario resumido.
        #
        # No expone todos los detalles internos del
        # QccContextStore: solo lo necesario para que
        # el Side Panel permita elegir un navegador.
        # ---------------------------------------------
        if path == "/qcc/browsers":
            browser_registry = getattr(
                self.server,
                "qcc_browser_registry",
                None,
            )

            if browser_registry is None:
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_BROWSER_REGISTRY_UNAVAILABLE",
                    },
                )
                return

            browsers = []

            for profile_key in (
                browser_registry.profile_keys()
            ):
                snapshot = (
                    browser_registry.snapshot(
                        profile_key
                    )
                )

                active_session = (
                    snapshot.get(
                        "active_session"
                    )
                    if snapshot.get(
                        "active"
                    )
                    else None
                )

                if not isinstance(
                    active_session,
                    dict,
                ):
                    active_session = None

                browsers.append({
                    "browser_profile_key":
                        profile_key,

                    "browser_session_mode":
                        snapshot.get(
                            "browser_session_mode"
                        ),

                    "active":
                        bool(
                            snapshot.get(
                                "active"
                            )
                        ),

                    "session_id":
                        (
                            active_session.get(
                                "session_id"
                            )
                            if active_session
                            else None
                        ),

                    "provider":
                        (
                            active_session.get(
                                "provider"
                            )
                            if active_session
                            else None
                        ),

                    "runtime":
                        (
                            active_session.get(
                                "runtime"
                            )
                            if active_session
                            else None
                        ),

                    "status":
                        (
                            active_session.get(
                                "status"
                            )
                            if active_session
                            else None
                        ),

                    "current_step":
                        (
                            active_session.get(
                                "current_step"
                            )
                            if active_session
                            else None
                        ),

                    "progress":
                        (
                            active_session.get(
                                "progress"
                            )
                            if active_session
                            else None
                        ),

                    "requires_user_action":
                        (
                            active_session.get(
                                "requires_user_action"
                            )
                            if active_session
                            else False
                        ),
                })

            self._send_json(
                200,
                {
                    "protocol_version":
                        QCC_PROTOCOL_VERSION,

                    "registry_revision":
                        browser_registry.revision,

                    "count":
                        len(
                            browsers
                        ),

                    "browsers":
                        browsers,
                },
            )
            return

        # ---------------------------------------------
        # QCC_AUTO_TWIN_CATALOG_PROBE_DECISION_API_V1
        #
        # GET /qcc/auto-twin/catalog-probe-decision
        #
        # Query:
        #   browser_profile_key=<physical profile>
        #   url=<current page url>
        #
        # Autoridad backend:
        # - browser registrado;
        # - profile policy active_catalog_probe=True;
        # - URL perteneciente a managed TWIN habilitado.
        #
        # Esta ruta NO ejecuta interacción web.
        # HARVEST_ALLOWED se verifica adicionalmente
        # en la extensión antes de cualquier mutación.
        # ---------------------------------------------
        if (
            path
            == "/qcc/auto-twin/catalog-probe-decision"
        ):
            auto_twin_store = getattr(
                self.server,
                "qcc_auto_twin_store",
                None,
            )

            browser_registry = getattr(
                self.server,
                "qcc_browser_registry",
                None,
            )

            if (
                auto_twin_store is None
                or browser_registry is None
            ):
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_AUTO_TWIN_CATALOG_PROBE_AUTHORITY_UNAVAILABLE",
                    },
                )
                return

            query = parse_qs(
                parsed.query,
                keep_blank_values=True,
            )

            profile_values = query.get(
                "browser_profile_key"
            )

            url_values = query.get(
                "url"
            )

            if (
                profile_values is None
                or len(profile_values) != 1
            ):
                self._send_json(
                    400,
                    {
                        "error":
                            "QCC_BROWSER_PROFILE_KEY_REQUIRED",
                    },
                )
                return

            if (
                url_values is None
                or len(url_values) != 1
            ):
                self._send_json(
                    400,
                    {
                        "error":
                            "QCC_AUTO_TWIN_CATALOG_PROBE_URL_REQUIRED",
                    },
                )
                return

            decision = (
                build_auto_twin_catalog_probe_decision(
                    auto_twin_store,
                    browser_registry,

                    browser_profile_key=(
                        profile_values[0]
                    ),

                    url=(
                        url_values[0]
                    ),
                )
            )

            self._send_json(
                200,
                {
                    "protocol_version":
                        QCC_PROTOCOL_VERSION,

                    **decision,
                },
            )
            return

        # ---------------------------------------------
        # QCC_AUTO_TWIN_READ_API_V1
        #
        # GET /qcc/auto-twins
        # GET /qcc/auto-twins/<twin_key>
        # ---------------------------------------------
        if path == "/qcc/auto-twins":
            auto_twin_store = getattr(
                self.server,
                "qcc_auto_twin_store",
                None,
            )

            if auto_twin_store is None:
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_AUTO_TWIN_STORE_UNAVAILABLE",
                    },
                )
                return

            self._send_json(
                200,
                {
                    "protocol_version":
                        QCC_PROTOCOL_VERSION,

                    **auto_twin_store.snapshot(),
                },
            )
            return

        # ---------------------------------------------
        # QCC_AUTO_TWIN_CANDIDATE_READ_API_V1
        #
        # GET /qcc/auto-twins/<twin_key>/candidates
        #
        # Auditoría read-only de revisiones candidatas.
        # No existe promoción desde esta ruta.
        # ---------------------------------------------
        auto_twin_candidate_parts = [
            unquote(
                part
            )
            for part
            in path.strip("/").split("/")
            if part
        ]

        is_auto_twin_candidate_read_route = (
            len(auto_twin_candidate_parts) == 4
            and auto_twin_candidate_parts[0] == "qcc"
            and auto_twin_candidate_parts[1] == "auto-twins"
            and auto_twin_candidate_parts[3] == "candidates"
        )

        if is_auto_twin_candidate_read_route:
            auto_twin_store = getattr(
                self.server,
                "qcc_auto_twin_store",
                None,
            )

            candidate_store = getattr(
                self.server,
                "qcc_auto_twin_candidate_store",
                None,
            )

            if (
                auto_twin_store is None
                or candidate_store is None
            ):
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_AUTO_TWIN_CANDIDATE_STORE_UNAVAILABLE",
                    },
                )
                return

            twin_key = str(
                auto_twin_candidate_parts[2]
                or ""
            ).strip()

            if not twin_key:
                self._send_json(
                    400,
                    {
                        "error":
                            "QCC_AUTO_TWIN_KEY_REQUIRED",
                    },
                )
                return

            try:
                managed_twin = (
                    auto_twin_store.get(
                        twin_key
                    )
                )

                if managed_twin is None:
                    self._send_json(
                        404,
                        {
                            "error":
                                "QCC_AUTO_TWIN_NOT_FOUND",
                        },
                    )
                    return

                snapshot = (
                    candidate_store.snapshot(
                        twin_key
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

            candidates = snapshot.get(
                "candidates"
            )

            if not isinstance(
                candidates,
                list,
            ):
                candidates = []

            pending = [
                candidate
                for candidate
                in candidates
                if (
                    isinstance(
                        candidate,
                        dict,
                    )
                    and str(
                        candidate.get(
                            "status"
                        )
                        or ""
                    ).strip().upper()
                    == "PENDING_VALIDATION"
                )
            ]

            latest_candidate = (
                max(
                    candidates,
                    key=lambda item: int(
                        item.get(
                            "candidate_revision"
                        )
                        or 0
                    ),
                )
                if candidates
                else None
            )

            self._send_json(
                200,
                {
                    "protocol_version":
                        QCC_PROTOCOL_VERSION,

                    "managed_twin":
                        managed_twin.to_dict(),

                    "candidate_store_revision":
                        snapshot.get(
                            "revision"
                        ),

                    "candidate_count":
                        len(
                            candidates
                        ),

                    "pending_candidate_count":
                        len(
                            pending
                        ),

                    "latest_candidate":
                        latest_candidate,

                    "candidates":
                        candidates,
                },
            )
            return

        # ---------------------------------------------
        # QCC_AUTO_TWIN_VALIDATION_EVIDENCE_READ_API_V1
        #
        # GET /qcc/auto-twins/<twin_key>/evidence
        #
        # GET /qcc/auto-twins/<twin_key>/candidates/
        #     <candidate_id>/evidence
        #
        # Auditoría técnica read-only.
        #
        # ManagedSiteStore:
        #     autoridad sobre existencia del TWIN.
        #
        # CandidateRevisionStore:
        #     autoridad sobre existencia/lifecycle
        #     del candidato.
        #
        # ValidationEvidenceStore:
        #     autoridad sobre historial técnico.
        #
        # Esta superficie:
        # - no escribe evidencia;
        # - no cambia status;
        # - no valida automáticamente;
        # - no materializa;
        # - no promociona ACTIVE.
        # ---------------------------------------------
        auto_twin_evidence_parts = [
            unquote(
                part
            )
            for part
            in path.strip("/").split("/")
            if part
        ]

        is_auto_twin_evidence_read_route = (
            len(
                auto_twin_evidence_parts
            )
            == 4
            and auto_twin_evidence_parts[0] == "qcc"
            and auto_twin_evidence_parts[1] == "auto-twins"
            and auto_twin_evidence_parts[3] == "evidence"
        )

        is_auto_twin_candidate_evidence_read_route = (
            len(
                auto_twin_evidence_parts
            )
            == 6
            and auto_twin_evidence_parts[0] == "qcc"
            and auto_twin_evidence_parts[1] == "auto-twins"
            and auto_twin_evidence_parts[3] == "candidates"
            and auto_twin_evidence_parts[5] == "evidence"
        )

        if (
            is_auto_twin_evidence_read_route
            or is_auto_twin_candidate_evidence_read_route
        ):
            auto_twin_store = getattr(
                self.server,
                "qcc_auto_twin_store",
                None,
            )

            evidence_store = getattr(
                self.server,
                "qcc_auto_twin_validation_evidence_store",
                None,
            )

            if (
                auto_twin_store is None
                or evidence_store is None
            ):
                self._send_json(
                    503,
                    {
                        "error":
                            (
                                "QCC_AUTO_TWIN_VALIDATION_"
                                "EVIDENCE_STORE_UNAVAILABLE"
                            ),
                    },
                )
                return

            twin_key = str(
                auto_twin_evidence_parts[2]
                or ""
            ).strip()

            if not twin_key:
                self._send_json(
                    400,
                    {
                        "error":
                            "QCC_AUTO_TWIN_KEY_REQUIRED",
                    },
                )
                return

            try:
                managed_twin = (
                    auto_twin_store.get(
                        twin_key
                    )
                )

                if managed_twin is None:
                    self._send_json(
                        404,
                        {
                            "error":
                                "QCC_AUTO_TWIN_NOT_FOUND",
                        },
                    )
                    return

                # -------------------------------------
                # Candidate-specific evidence
                # -------------------------------------
                if (
                    is_auto_twin_candidate_evidence_read_route
                ):
                    candidate_store = getattr(
                        self.server,
                        "qcc_auto_twin_candidate_store",
                        None,
                    )

                    if candidate_store is None:
                        self._send_json(
                            503,
                            {
                                "error":
                                    (
                                        "QCC_AUTO_TWIN_CANDIDATE_"
                                        "STORE_UNAVAILABLE"
                                    ),
                            },
                        )
                        return

                    candidate_id = str(
                        auto_twin_evidence_parts[4]
                        or ""
                    ).strip()

                    if not candidate_id:
                        self._send_json(
                            400,
                            {
                                "error":
                                    (
                                        "QCC_AUTO_TWIN_"
                                        "CANDIDATE_ID_REQUIRED"
                                    ),
                            },
                        )
                        return

                    candidate = (
                        candidate_store.get_candidate(
                            twin_key,
                            candidate_id,
                        )
                    )

                    if candidate is None:
                        self._send_json(
                            404,
                            {
                                "error":
                                    (
                                        "QCC_AUTO_TWIN_"
                                        "CANDIDATE_NOT_FOUND"
                                    ),
                            },
                        )
                        return

                    snapshot = (
                        evidence_store.candidate_snapshot(
                            twin_key,
                            candidate_id,
                        )
                    )

                    evidence_candidate = (
                        snapshot.get(
                            "candidate"
                        )
                    )

                    if not isinstance(
                        evidence_candidate,
                        dict,
                    ):
                        evidence_candidate = {}

                    evidence = (
                        evidence_candidate.get(
                            "evidence"
                        )
                    )

                    if not isinstance(
                        evidence,
                        list,
                    ):
                        evidence = []

                    latest_evidence = (
                        evidence_candidate.get(
                            "latest_evidence"
                        )
                    )

                    if not isinstance(
                        latest_evidence,
                        dict,
                    ):
                        latest_evidence = None

                    self._send_json(
                        200,
                        {
                            "protocol_version":
                                QCC_PROTOCOL_VERSION,

                            "managed_twin":
                                managed_twin.to_dict(),

                            "candidate":
                                candidate,

                            "evidence_store_revision":
                                snapshot.get(
                                    "revision"
                                ),

                            "has_evidence":
                                bool(
                                    evidence
                                ),

                            "evidence_count":
                                len(
                                    evidence
                                ),

                            "latest_evidence":
                                latest_evidence,

                            "evidence":
                                evidence,
                        },
                    )
                    return

                # -------------------------------------
                # Twin-wide evidence
                # -------------------------------------
                snapshot = (
                    evidence_store.snapshot(
                        twin_key
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

            candidates = snapshot.get(
                "candidates"
            )

            if not isinstance(
                candidates,
                list,
            ):
                candidates = []

            evidence_count = int(
                snapshot.get(
                    "evidence_count"
                )
                or 0
            )

            self._send_json(
                200,
                {
                    "protocol_version":
                        QCC_PROTOCOL_VERSION,

                    "managed_twin":
                        managed_twin.to_dict(),

                    "evidence_store_revision":
                        snapshot.get(
                            "revision"
                        ),

                    "has_evidence":
                        evidence_count > 0,

                    "candidate_count":
                        int(
                            snapshot.get(
                                "candidate_count"
                            )
                            or 0
                        ),

                    "evidence_count":
                        evidence_count,

                    "candidates":
                        candidates,
                },
            )
            return

        # ---------------------------------------------
        # QCC_AUTO_TWIN_OBSERVATION_READ_API_V1
        #
        # GET /qcc/auto-twins/<twin_key>/observations
        #
        # Expone únicamente memoria ligera.
        # Nunca devuelve DOM / HTML / MHTML / screenshots.
        # ---------------------------------------------
        auto_twin_read_parts = [
            unquote(
                part
            )
            for part
            in path.strip("/").split("/")
            if part
        ]

        is_auto_twin_observation_route = (
            len(auto_twin_read_parts) == 4
            and auto_twin_read_parts[0] == "qcc"
            and auto_twin_read_parts[1] == "auto-twins"
            and auto_twin_read_parts[3] == "observations"
        )

        if is_auto_twin_observation_route:
            auto_twin_store = getattr(
                self.server,
                "qcc_auto_twin_store",
                None,
            )

            observation_store = getattr(
                self.server,
                "qcc_auto_twin_observation_store",
                None,
            )

            if (
                auto_twin_store is None
                or observation_store is None
            ):
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_AUTO_TWIN_OBSERVATION_STORE_UNAVAILABLE",
                    },
                )
                return

            twin_key = str(
                auto_twin_read_parts[2]
                or ""
            ).strip()

            if not twin_key:
                self._send_json(
                    400,
                    {
                        "error":
                            "QCC_AUTO_TWIN_KEY_REQUIRED",
                    },
                )
                return

            try:
                managed_twin = (
                    auto_twin_store.get(
                        twin_key
                    )
                )

                if managed_twin is None:
                    self._send_json(
                        404,
                        {
                            "error":
                                "QCC_AUTO_TWIN_NOT_FOUND",
                        },
                    )
                    return

                snapshot = (
                    observation_store.snapshot(
                        twin_key
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

            twin_state = snapshot.get(
                "twin"
            )

            if not isinstance(
                twin_state,
                dict,
            ):
                twin_state = {}

            states = twin_state.get(
                "states"
            )

            if not isinstance(
                states,
                dict,
            ):
                states = {}

            state_list = [
                dict(
                    value
                )
                for value
                in states.values()
                if isinstance(
                    value,
                    dict,
                )
            ]

            state_list.sort(
                key=lambda item: (
                    str(
                        item.get(
                            "pathname"
                        )
                        or ""
                    ),
                    str(
                        item.get(
                            "functional_state"
                        )
                        or ""
                    ),
                )
            )

            last_observation = (
                twin_state.get(
                    "last_observation"
                )
            )

            if not isinstance(
                last_observation,
                dict,
            ):
                last_observation = None

            self._send_json(
                200,
                {
                    "protocol_version":
                        QCC_PROTOCOL_VERSION,

                    "managed_twin":
                        managed_twin.to_dict(),

                    "observation_store_revision":
                        snapshot.get(
                            "revision"
                        ),

                    "has_observations":
                        bool(
                            snapshot.get(
                                "found"
                            )
                        ),

                    "known_state_count":
                        len(
                            state_list
                        ),

                    "last_observation":
                        last_observation,

                    "states":
                        state_list,
                },
            )
            return

        auto_twin_prefix = (
            "/qcc/auto-twins/"
        )

        if path.startswith(
            auto_twin_prefix
        ):
            auto_twin_store = getattr(
                self.server,
                "qcc_auto_twin_store",
                None,
            )

            if auto_twin_store is None:
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_AUTO_TWIN_STORE_UNAVAILABLE",
                    },
                )
                return

            twin_key = str(
                path[
                    len(
                        auto_twin_prefix
                    ):
                ]
                or ""
            ).strip()

            if (
                not twin_key
                or "/" in twin_key
            ):
                self._send_json(
                    400,
                    {
                        "error":
                            "QCC_AUTO_TWIN_KEY_INVALID",
                    },
                )
                return

            try:
                site = auto_twin_store.get(
                    twin_key
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

            if site is None:
                self._send_json(
                    404,
                    {
                        "error":
                            "QCC_AUTO_TWIN_NOT_FOUND",
                    },
                )
                return

            self._send_json(
                200,
                {
                    "protocol_version":
                        QCC_PROTOCOL_VERSION,

                    "store_revision":
                        auto_twin_store.revision,

                    "managed_twin":
                        site.to_dict(),
                },
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
        # QCC_AUTO_TWIN_MANAGE_API_V1
        #
        # POST /qcc/auto-twins
        #     crea un TWIN gestionado.
        #
        # POST /qcc/auto-twins/<twin_key>/settings
        #     modifica únicamente gobierno operativo.
        #
        # No existe DELETE.
        # No sustituye silenciosamente un TWIN existente.
        # ---------------------------------------------
        if path == "/qcc/auto-twins":
            auto_twin_store = getattr(
                self.server,
                "qcc_auto_twin_store",
                None,
            )

            if auto_twin_store is None:
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_AUTO_TWIN_STORE_UNAVAILABLE",
                    },
                )
                return

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

                allowed_top_level = {
                    "protocol_version",
                    "managed_twin",
                }

                if (
                    set(payload)
                    - allowed_top_level
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_REQUEST_FIELDS_INVALID"
                    )

                raw_site = payload.get(
                    "managed_twin"
                )

                if not isinstance(
                    raw_site,
                    dict,
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_MANAGED_SITE_PAYLOAD_INVALID"
                    )

                allowed_site_fields = {
                    "twin_key",
                    "site_code",
                    "origins",
                    "path_prefixes",
                    "enabled",
                    "auto_update",
                    "discover_unknown_states",
                }

                if (
                    set(raw_site)
                    - allowed_site_fields
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_SITE_FIELDS_INVALID"
                    )

                origins = raw_site.get(
                    "origins"
                )

                if (
                    not isinstance(
                        origins,
                        list,
                    )
                    or not origins
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_ORIGINS_REQUIRED"
                    )

                path_prefixes = raw_site.get(
                    "path_prefixes",
                    ["/"],
                )

                if (
                    not isinstance(
                        path_prefixes,
                        list,
                    )
                    or not path_prefixes
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_PATH_PREFIXES_REQUIRED"
                    )

                for bool_field in (
                    "enabled",
                    "auto_update",
                    "discover_unknown_states",
                ):
                    if (
                        bool_field in raw_site
                        and not isinstance(
                            raw_site[
                                bool_field
                            ],
                            bool,
                        )
                    ):
                        raise ValueError(
                            "QCC_AUTO_TWIN_SETTING_BOOL_REQUIRED"
                        )

                site = AutoTwinManagedSite(
                    twin_key=raw_site.get(
                        "twin_key"
                    ),

                    site_code=raw_site.get(
                        "site_code"
                    ),

                    origins=tuple(
                        origins
                    ),

                    path_prefixes=tuple(
                        path_prefixes
                    ),

                    enabled=raw_site.get(
                        "enabled",
                        True,
                    ),

                    auto_update=raw_site.get(
                        "auto_update",
                        True,
                    ),

                    discover_unknown_states=(
                        raw_site.get(
                            "discover_unknown_states",
                            True,
                        )
                    ),
                )

                revision = (
                    auto_twin_store.register(
                        site
                    )
                )

            except (
                TypeError,
                ValueError,
            ) as exc:
                error = str(exc)

                status = (
                    409
                    if error in {
                        "QCC_AUTO_TWIN_KEY_ALREADY_REGISTERED",
                        "QCC_AUTO_TWIN_SITE_CODE_ALREADY_REGISTERED",
                        "QCC_AUTO_TWIN_SCOPE_CONFLICT",
                    }
                    else 400
                )

                self._send_json(
                    status,
                    {
                        "error":
                            error,
                    },
                )
                return

            self._send_json(
                201,
                {
                    "ok":
                        True,

                    "protocol_version":
                        QCC_PROTOCOL_VERSION,

                    "store_revision":
                        revision,

                    "managed_twin":
                        site.to_dict(),
                },
            )
            return

        auto_twin_parts = [
            unquote(
                part
            )
            for part
            in path.strip("/").split("/")
            if part
        ]

        is_auto_twin_settings_route = (
            len(auto_twin_parts) == 4
            and auto_twin_parts[0] == "qcc"
            and auto_twin_parts[1] == "auto-twins"
            and auto_twin_parts[3] == "settings"
        )

        # ---------------------------------------------
        # QCC_AUTO_TWIN_CANDIDATE_VALIDATION_API_V1
        #
        # POST
        # /qcc/auto-twins/<twin_key>/candidates/
        # <candidate_id>/validation
        #
        # Únicamente permite:
        #
        # PENDING_VALIDATION -> VALIDATED
        # PENDING_VALIDATION -> REJECTED
        #
        # VALIDATED NO significa ACTIVE.
        #
        # Esta ruta:
        # - no modifica observation baseline;
        # - no materializa archivos;
        # - no promociona revisiones;
        # - no ejecuta ninguna acción web.
        # ---------------------------------------------
        is_auto_twin_candidate_validation_route = (
            len(auto_twin_parts) == 6
            and auto_twin_parts[0] == "qcc"
            and auto_twin_parts[1] == "auto-twins"
            and auto_twin_parts[3] == "candidates"
            and auto_twin_parts[5] == "validation"
        )

        if is_auto_twin_candidate_validation_route:
            auto_twin_store = getattr(
                self.server,
                "qcc_auto_twin_store",
                None,
            )

            candidate_store = getattr(
                self.server,
                "qcc_auto_twin_candidate_store",
                None,
            )

            if (
                auto_twin_store is None
                or candidate_store is None
            ):
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_AUTO_TWIN_CANDIDATE_STORE_UNAVAILABLE",
                    },
                )
                return

            twin_key = str(
                auto_twin_parts[2]
                or ""
            ).strip()

            candidate_id = str(
                auto_twin_parts[4]
                or ""
            ).strip()

            if not twin_key:
                self._send_json(
                    400,
                    {
                        "error":
                            "QCC_AUTO_TWIN_KEY_REQUIRED",
                    },
                )
                return

            if not candidate_id:
                self._send_json(
                    400,
                    {
                        "error":
                            "QCC_AUTO_TWIN_CANDIDATE_ID_REQUIRED",
                    },
                )
                return

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

                allowed_top_level = {
                    "protocol_version",
                    "target_status",
                }

                if (
                    set(payload)
                    - allowed_top_level
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_REQUEST_FIELDS_INVALID"
                    )

                target_status = str(
                    payload.get(
                        "target_status"
                    )
                    or ""
                ).strip().upper()

                if target_status not in {
                    AUTO_TWIN_CANDIDATE_STATUS_VALIDATED,
                    AUTO_TWIN_CANDIDATE_STATUS_REJECTED,
                }:
                    raise ValueError(
                        "QCC_AUTO_TWIN_CANDIDATE_TARGET_STATUS_INVALID"
                    )

                managed_twin = (
                    auto_twin_store.get(
                        twin_key
                    )
                )

                if managed_twin is None:
                    self._send_json(
                        404,
                        {
                            "error":
                                "QCC_AUTO_TWIN_NOT_FOUND",
                        },
                    )
                    return

                existing_candidate = (
                    candidate_store.get_candidate(
                        twin_key,
                        candidate_id,
                    )
                )

                if existing_candidate is None:
                    self._send_json(
                        404,
                        {
                            "error":
                                "QCC_AUTO_TWIN_CANDIDATE_NOT_FOUND",
                        },
                    )
                    return

                result = (
                    candidate_store
                    .transition_candidate_status(
                        twin_key,
                        candidate_id,
                        target_status=(
                            target_status
                        ),
                    )
                )

            except ValueError as exc:
                error = str(
                    exc
                )

                status = (
                    409
                    if error
                    == (
                        "QCC_AUTO_TWIN_CANDIDATE_"
                        "STATUS_TRANSITION_INVALID"
                    )
                    else 400
                )

                self._send_json(
                    status,
                    {
                        "error":
                            error,
                    },
                )
                return

            self._send_json(
                200,
                {
                    "ok":
                        True,

                    "protocol_version":
                        QCC_PROTOCOL_VERSION,

                    "changed":
                        result.get(
                            "changed"
                        )
                        is True,

                    "candidate_store_revision":
                        result.get(
                            "store_revision"
                        ),

                    "candidate":
                        result.get(
                            "candidate"
                        ),
                },
            )
            return

        if is_auto_twin_settings_route:
            auto_twin_store = getattr(
                self.server,
                "qcc_auto_twin_store",
                None,
            )

            if auto_twin_store is None:
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_AUTO_TWIN_STORE_UNAVAILABLE",
                    },
                )
                return

            twin_key = str(
                auto_twin_parts[2]
                or ""
            ).strip()

            if not twin_key:
                self._send_json(
                    400,
                    {
                        "error":
                            "QCC_AUTO_TWIN_KEY_REQUIRED",
                    },
                )
                return

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

                allowed_top_level = {
                    "protocol_version",
                    "settings",
                }

                if (
                    set(payload)
                    - allowed_top_level
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_REQUEST_FIELDS_INVALID"
                    )

                settings = payload.get(
                    "settings"
                )

                if not isinstance(
                    settings,
                    dict,
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_SETTINGS_INVALID"
                    )

                allowed_settings = {
                    "enabled",
                    "auto_update",
                    "discover_unknown_states",
                }

                if not settings:
                    raise ValueError(
                        "QCC_AUTO_TWIN_SETTINGS_EMPTY"
                    )

                if (
                    set(settings)
                    - allowed_settings
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_SETTINGS_FIELDS_INVALID"
                    )

                for value in (
                    settings.values()
                ):
                    if not isinstance(
                        value,
                        bool,
                    ):
                        raise ValueError(
                            "QCC_AUTO_TWIN_SETTING_BOOL_REQUIRED"
                        )

                existing = (
                    auto_twin_store.get(
                        twin_key
                    )
                )

                if existing is None:
                    self._send_json(
                        404,
                        {
                            "error":
                                "QCC_AUTO_TWIN_NOT_FOUND",
                        },
                    )
                    return

                revision = (
                    auto_twin_store.update_settings(
                        twin_key,

                        enabled=settings.get(
                            "enabled"
                        ),

                        auto_update=settings.get(
                            "auto_update"
                        ),

                        discover_unknown_states=(
                            settings.get(
                                "discover_unknown_states"
                            )
                        ),
                    )
                )

                updated = (
                    auto_twin_store.get(
                        twin_key
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

                    "protocol_version":
                        QCC_PROTOCOL_VERSION,

                    "store_revision":
                        revision,

                    "managed_twin":
                        (
                            updated.to_dict()
                            if updated is not None
                            else None
                        ),
                },
            )
            return

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

            auto_twin_materialization = (
                _qcc_project_auto_twin_materialization_after_artifact(
                    server=(
                        self.server
                    ),
                    capture_id=(
                        result[
                            "capture_id"
                        ]
                    ),
                )
            )

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
                        ],                },
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

            auto_twin_store = getattr(
                self.server,
                "qcc_auto_twin_store",
                None,
            )

            auto_twin_candidate_store = getattr(
                self.server,
                "qcc_auto_twin_candidate_store",
                None,
            )

            auto_twin_validation_evidence_store = getattr(
                self.server,
                "qcc_auto_twin_validation_evidence_store",
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

            auto_twin_materialization = (
                _qcc_project_auto_twin_materialization_after_artifact(
                    server=(
                        self.server
                    ),
                    capture_id=(
                        result[
                            "capture_id"
                        ]
                    ),
                )
            )

            auto_twin_validation = (
                _qcc_project_auto_twin_validation_after_visual(
                    ingestor=(
                        ingestor
                    ),
                    auto_twin_store=(
                        auto_twin_store
                    ),
                    candidate_store=(
                        auto_twin_candidate_store
                    ),
                    evidence_store=(
                        auto_twin_validation_evidence_store
                    ),
                    capture_id=(
                        result[
                            "capture_id"
                        ]
                    ),
                    artifact_kind=(
                        result[
                            "kind"
                        ]
                    ),
                )
            )

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

                    "auto_twin_validation":
                        auto_twin_validation,
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

            auto_twin_store = getattr(
                self.server,
                "qcc_auto_twin_store",
                None,
            )

            auto_twin_observation_store = getattr(
                self.server,
                "qcc_auto_twin_observation_store",
                None,
            )

            auto_twin_candidate_store = getattr(
                self.server,
                "qcc_auto_twin_candidate_store",
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

                # QCC_SITE_ARCHITECTURE_CAPTURE_PROFILE_AUTHORITY_V1
                #
                # browser_profile_key pertenece al envelope
                # de transporte QCC, no al DOM capturado.
                #
                # El Bridge lo proyecta de forma canónica
                # sobre la copia que recibe el ingestor.
                # Nunca confiamos en un valor anidado previo.
                capture = dict(
                    capture
                )

                if browser_profile_key:
                    capture[
                        "browser_profile_key"
                    ] = browser_profile_key
                else:
                    capture.pop(
                        "browser_profile_key",
                        None,
                    )

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
                # QCC_DISCOVERY_OBSERVATION_SCOPE_V1
                #
                # Site-level Discovery must be able to
                # publish CURRENT and human causal evidence
                # without a business PresentationSession.
                #
                # Authority remains backend-only:
                # profile + managed URL + governance scope.
                # -------------------------------------
                discovery_observation_scope = (
                    _qcc_bind_discovery_observation_scope(
                        context_store=(
                            context_store
                        ),

                        auto_twin_store=(
                            auto_twin_store
                        ),

                        managed_governance_registry=(
                            managed_governance_registry
                        ),

                        browser_profile_key=(
                            browser_profile_key
                        ),

                        ingest_result=(
                            result
                        ),
                    )
                )

                # -------------------------------------
                # QCC_DISCOVERY_RUNTIME_SITE_IDENTITY_V1
                #
                # The persisted ingestor result remains
                # immutable. Discovery may obtain site identity
                # only after managed URL resolution.
                #
                # Runtime CURRENT/actions/learning consume this
                # canonical projection copy.
                # -------------------------------------
                runtime_site_code = (
                    _qcc_runtime_site_code(
                        ingest_result=(
                            result
                        ),
                        discovery_observation_scope=(
                            discovery_observation_scope
                        ),
                    )
                )

                runtime_ingest_result = (
                    result
                )

                if (
                    runtime_site_code
                    and not str(
                        result.get(
                            "site_code"
                        )
                        or ""
                    ).strip()
                ):
                    runtime_ingest_result = dict(
                        result
                    )

                    runtime_ingest_result[
                        "site_code"
                    ] = runtime_site_code

                # -------------------------------------
                # QCC_AUTO_TWIN_PASSIVE_OBSERVATION_V1
                #
                # Site Architecture permanece autoritativo.
                #
                # AUTO TWIN consume exclusivamente el resultado
                # ya persistido por el ingestor y referencia su
                # capture_id.
                #
                # Un fallo AUTO TWIN:
                # - nunca invalida la captura;
                # - nunca bloquea CURRENT;
                # - nunca altera NavigationKnowledge;
                # - nunca ejecuta interacción web.
                # -------------------------------------
                auto_twin_observation = None

                if (
                    auto_twin_store is not None
                    and auto_twin_observation_store
                    is not None
                ):
                    try:
                        auto_twin_observation = (
                            project_ingested_auto_twin_observation(
                                auto_twin_store,
                                auto_twin_observation_store,

                                browser_profile_key=(
                                    browser_profile_key
                                ),

                                ingest_result=(
                                    result
                                ),
                            )
                        )

                    except (
                        OSError,
                        TypeError,
                        ValueError,
                    ) as exc:
                        # Fail-open para Site Architecture.
                        # Fail-closed para AUTO TWIN.
                        auto_twin_observation = {
                            "processed":
                                False,

                            "reason":
                                "AUTO_TWIN_OBSERVATION_FAIL_CLOSED",

                            "error_type":
                                type(exc).__name__,
                        }

                result[
                    "auto_twin_observation"
                ] = (
                    auto_twin_observation
                )

                # -------------------------------------
                # QCC_AUTO_TWIN_CANDIDATE_REVISION_V1
                #
                # Únicamente CHANGED + auto_update=True
                # puede producir una revisión candidata.
                #
                # UNKNOWN / KNOWN no generan revisión.
                #
                # La revisión ACTIVE / baseline permanece
                # completamente intacta.
                #
                # Fail-open para Site Architecture.
                # Fail-closed para Candidate Revision.
                # -------------------------------------
                auto_twin_candidate = None

                if (
                    auto_twin_store is not None
                    and auto_twin_candidate_store
                    is not None
                    and auto_twin_observation
                    is not None
                ):
                    try:
                        auto_twin_candidate = (
                            project_auto_twin_candidate_revision(
                                auto_twin_store,
                                auto_twin_candidate_store,
                                auto_twin_observation,
                            )
                        )

                    except (
                        OSError,
                        TypeError,
                        ValueError,
                    ) as exc:
                        auto_twin_candidate = {
                            "processed":
                                False,

                            "reason":
                                "AUTO_TWIN_CANDIDATE_FAIL_CLOSED",

                            "error_type":
                                type(exc).__name__,
                        }

                result[
                    "auto_twin_candidate"
                ] = (
                    auto_twin_candidate
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
                    # PresentationSession OR technical
                    # ObservationScope.
                    active_session = (
                        context_store
                        .get_observation_identity()
                    )

                    capture_session_id = str(
                        result.get(
                            "session_id"
                        )
                        or ""
                    ).strip()

                    # Discovery has no business session_id.
                    # Use the technical scope installed for
                    # this exact profile/site/environment.
                    if not capture_session_id:
                        scope_for_capture = (
                            context_store
                            .get_observation_scope()
                        )

                        if scope_for_capture is not None:
                            capture_session_id = (
                                scope_for_capture
                                .scope_id
                            )

                    observed_site_for_scope = str(
                        runtime_site_code
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
                            runtime_ingest_result,
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
                                    runtime_site_code
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
                    and runtime_site_code
                ):
                    try:
                        human_navigation_learning = (
                            process_observed_human_navigation_learning(
                                human_navigation_candidate_store,
                                navigation_knowledge_store,
                                # CURRENT posterior únicamente
                                # actualiza el destino provisional.
                                # El episodio se cierra contra una
                                # siguiente acción humana válida.
                                transition=None,
                                site_code=(
                                    runtime_site_code
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
                human_listener_evidence_id = None

                # QCC_DISCOVERY_HUMAN_LISTENER_AUTO_ARM_RESET_FIX_V1
                #
                # Defaults are established before projection.
                # A successfully derived Discovery listener may
                # overwrite them below.
                #
                # They must NOT be reset unconditionally after
                # build_human_listener_plan().
                human_listener_scope_id = None
                human_listener_auto_arm = False

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
                        .get_observation_identity()
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
                                    runtime_site_code
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
                                navigation_context=(
                                    _trusted_navigation_context_from_ingest_result(
                                        result
                                    )
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

                            human_listener_evidence_id = (
                                evidence.evidence_id
                            )

                            human_listener_scope_id = (
                                active_for_actions
                                .session_id
                            )

                            # Only site-level technical
                            # Discovery is auto-armed here.
                            #
                            # Presentation flows keep their
                            # existing explicit listener path.
                            scope_for_actions = (
                                context_store
                                .get_observation_scope()
                            )

                            human_listener_auto_arm = (
                                context_store
                                .get_active_session()
                                is None

                                and scope_for_actions
                                is not None

                                and scope_for_actions
                                .scope_id
                                == human_listener_scope_id

                                and str(
                                    scope_for_actions.mode
                                    or ""
                                ).strip().upper()
                                == "DISCOVERY"
                            )

                        except (
                            TypeError,
                            ValueError,
                        ):
                            human_listener_plan = None
                            human_listener_evidence_id = None
                            human_listener_scope_id = None
                            human_listener_auto_arm = False


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
                            runtime_site_code
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

                    # Opaque identity of the exact canonical
                    # action snapshot that armed this listener.
                    #
                    # It carries no policy/state authority.
                    "human_listener_evidence_id":
                        human_listener_evidence_id,

                    # Opaque runtime routing identity.
                    #
                    # It is NOT a business session and does
                    # not grant policy/authority.
                    "human_listener_scope_id":
                        human_listener_scope_id,

                    "human_listener_auto_arm":
                        human_listener_auto_arm,

                    "observation_scope_binding":
                        discovery_observation_scope,

                    "counts":
                        result["counts"],
                },
            )
            return

        # ---------------------------------------------
        # QCC_AUTO_TWIN_CATALOG_DEPENDENCY_PROBE_API_V1
        #
        # POST /qcc/auto-twin/catalog-dependency-probe
        #
        # Recibe evidencia física producida por el executor
        # genérico de catálogo REAL.
        #
        # Seguridad:
        # - NO confía en artifact.authority;
        # - revalida profile + URL contra autoridad backend;
        # - exige active_discovery + active_catalog_probe
        #   mediante el analyzer;
        # - exige restauración exacta;
        # - NO ejecuta navegador;
        # - persiste únicamente conocimiento causal
        #   sanitizado e idempotente;
        # - NO materializa revisiones.
        #
        # La respuesta es una proyección sanitizada:
        # NO devuelve el payload RAW de opciones.
        # ---------------------------------------------
        if (
            path
            == "/qcc/auto-twin/catalog-dependency-probe"
        ):
            auto_twin_store = getattr(
                self.server,
                "qcc_auto_twin_store",
                None,
            )

            browser_registry = getattr(
                self.server,
                "qcc_browser_registry",
                None,
            )

            dependency_store = getattr(
                self.server,
                "qcc_auto_twin_catalog_dependency_store",
                None,
            )

            if (
                auto_twin_store is None
                or browser_registry is None
            ):
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_AUTHORITY_UNAVAILABLE",
                    },
                )
                return

            if dependency_store is None:
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_STORE_UNAVAILABLE",
                    },
                )
                return

            try:
                payload = self._read_json_with_limit(
                    max_bytes=(
                        QCC_CATALOG_DEPENDENCY_PROBE_MAX_BYTES
                    ),
                    length_error=(
                        "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_REQUEST_TOO_LARGE"
                    ),
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

                browser_profile_key = str(
                    payload.get(
                        "browser_profile_key"
                    )
                    or ""
                ).strip()

                if not browser_profile_key:
                    raise ValueError(
                        "QCC_BROWSER_PROFILE_KEY_REQUIRED"
                    )

                page_url = str(
                    payload.get(
                        "url"
                    )
                    or ""
                ).strip()

                if not page_url:
                    raise ValueError(
                        "QCC_AUTO_TWIN_CATALOG_PROBE_URL_REQUIRED"
                    )

                probe = payload.get(
                    "probe"
                )

                if not isinstance(
                    probe,
                    dict,
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_PROBE_INVALID"
                    )

                # -------------------------------------
                # Backend is the authority.
                #
                # Deliberately ignore probe.authority
                # for authorization purposes.
                # -------------------------------------
                decision = (
                    build_auto_twin_catalog_probe_decision(
                        auto_twin_store,
                        browser_registry,
                        browser_profile_key=(
                            browser_profile_key
                        ),
                        url=(
                            page_url
                        ),
                    )
                )

                analysis = (
                    analyze_auto_twin_governed_catalog_probe(
                        probe,
                        authoritative_decision=(
                            decision
                        ),
                    )
                )

                persistence = (
                    dependency_store.record_dependency(
                        analysis
                    )
                )

            except OSError:
                self._send_json(
                    500,
                    {
                        "error":
                            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_PERSIST_FAILED",
                    },
                )
                return

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

            target = analysis[
                "target"
            ]

            self._send_json(
                200,
                {
                    "ok":
                        True,

                    "dependency_fingerprint":
                        analysis[
                            "dependency_fingerprint"
                        ],

                    "dependency_created":
                        persistence[
                            "created"
                        ],

                    "dependency_store_revision":
                        persistence[
                            "revision"
                        ],

                    "twin_key":
                        analysis[
                            "twin_key"
                        ],

                    "site_code":
                        analysis[
                            "site_code"
                        ],

                    "origin":
                        analysis[
                            "origin"
                        ],

                    "pathname":
                        analysis[
                            "pathname"
                        ],

                    "route":
                        analysis[
                            "route"
                        ],

                    "source":
                        analysis[
                            "source"
                        ],

                    "trigger":
                        analysis[
                            "trigger"
                        ],

                    "target": {
                        "catalog_key":
                            target[
                                "catalog_key"
                            ],

                        "selector":
                            target[
                                "selector"
                            ],

                        "before_options_count":
                            target[
                                "before_options_count"
                            ],

                        "options_count":
                            target[
                                "options_count"
                            ],

                        "before_options_signature":
                            target[
                                "before_options_signature"
                            ],

                        "options_signature":
                            target[
                                "options_signature"
                            ],
                    },

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

                    "provenance":
                        analysis[
                            "provenance"
                        ],
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
        # POST /qcc/browser-profile
        #
        # Registro genérico de BrowserSession gobernada.
        #
        # No representa una presentación.
        # No crea session_id.
        # No controla Chrome.
        # ---------------------------------------------
        if path == "/qcc/browser-profile":
            if browser_registry is None:
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_BROWSER_REGISTRY_UNAVAILABLE",
                    },
                )
                return

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

                if not browser_profile_key:
                    raise ValueError(
                        "QCC_BROWSER_PROFILE_KEY_REQUIRED"
                    )

                browser_session_mode = str(
                    payload.get(
                        "browser_session_mode"
                    )
                    or ""
                ).strip().upper()

                registry_revision = (
                    browser_registry
                    .set_profile_mode(
                        profile_key=(
                            browser_profile_key
                        ),
                        mode=(
                            browser_session_mode
                        ),
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

                    "registry_revision":
                        registry_revision,

                    "browser_profile_key":
                        browser_profile_key,

                    "browser_session_mode":
                        browser_session_mode,
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

                browser_session_mode = str(
                    payload.get(
                        "browser_session_mode"
                    )
                    or ""
                ).strip().upper()

                if (
                    browser_session_mode
                    and browser_session_mode
                    not in {
                        "EPHEMERAL",
                        "PERSISTENT",
                        "ASSISTED",
                    }
                ):
                    raise ValueError(
                        "QCC_BROWSER_SESSION_MODE_INVALID"
                    )

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

            if (
                browser_profile_key
                and browser_session_mode
            ):
                try:
                    browser_registry.set_profile_mode(
                        profile_key=(
                            browser_profile_key
                        ),
                        mode=(
                            browser_session_mode
                        ),
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

                required_signal_fields = {
                    "event_id",
                    "selector",
                    "frame_path",
                    "observed_at",
                }

                allowed_signal_fields = (
                    required_signal_fields
                    | {
                        "evidence_id",
                    }
                )

                signal_fields = set(
                    signal_payload
                )

                if (
                    not required_signal_fields
                    .issubset(
                        signal_fields
                    )
                    or (
                        signal_fields
                        - allowed_signal_fields
                    )
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
                        evidence_id=(
                            signal_payload.get(
                                "evidence_id"
                            )
                        ),
                    )
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

                # ---------------------------------------------
                # HUMAN CAUSAL EPISODE BOUNDARY
                #
                # La siguiente acción Y se resuelve PRIMERO
                # contra CURRENT + LiveActionEvidence canónicos.
                #
                # Una señal Y inválida nunca puede cerrar X ni
                # fabricar una transición contra un snapshot B1.
                # ---------------------------------------------
                resolved_next_action = (
                    resolve_human_dom_signal(
                        context_store,
                        signal,
                    )
                )

                pending_previous_action = (
                    context_store
                    .get_observed_human_action(
                        now=(
                            signal.observed_at
                        )
                    )
                )

                # QCC_HUMAN_BOUNDARY_DIAG_V1
                print(
                    "[QCC-HUMAN-DIAG] "
                    "NEXT_ACTION "
                    f"next_event={resolved_next_action.event_id!r} "
                    "pending="
                    f"{pending_previous_action is not None} "
                    "pending_event="
                    f"{getattr(pending_previous_action, 'event_id', None)!r}",
                    flush=True,
                )

                finalized_transition = None

                if (
                    pending_previous_action
                    is not None
                    and pending_previous_action.event_id
                    != resolved_next_action.event_id
                ):
                    # QCC_NEXT_ACTION_EVIDENCE_BOUNDARY_V1
                    #
                    # X closes against exact Y.before, not
                    # mutable CURRENT and not the last provisional
                    # snapshot that happened to reach the Bridge.
                    finalized_transition = (
                        finalize_observed_human_transition_against_next_action(
                            context_store,
                            next_action=(
                                resolved_next_action
                            ),
                        )
                    )

                    print(
                        "[QCC-HUMAN-DIAG] "
                        "FINALIZE "
                        f"ok={finalized_transition is not None} "
                        "changed="
                        f"{getattr(finalized_transition, 'changed', None)!r} "
                        "before_fp="
                        f"{getattr(finalized_transition, 'before_fingerprint', None)!r} "
                        "after_fp="
                        f"{getattr(finalized_transition, 'after_fingerprint', None)!r}",
                        flush=True,
                    )

                    if (
                        finalized_transition is not None
                        and human_navigation_candidate_store
                        is not None
                        and navigation_knowledge_store
                        is not None
                    ):
                        try:
                            process_observed_human_navigation_learning(
                                human_navigation_candidate_store,
                                navigation_knowledge_store,
                                transition=(
                                    finalized_transition
                                ),
                            )

                            print(
                                "[QCC-HUMAN-DIAG] "
                                "LEARNING=OK",
                                flush=True,
                            )

                        except (
                            OSError,
                            TypeError,
                            ValueError,
                        ) as exc:
                            # Fail closed para aprendizaje.
                            # Diagnóstico temporal:
                            # no expone DOM ni datos del cliente.
                            print(
                                "[QCC-HUMAN-DIAG] "
                                "LEARNING=ERROR "
                                f"type={type(exc).__name__} "
                                f"error={str(exc)!r}",
                                flush=True,
                            )

                    if finalized_transition is None:
                        # No fabricamos causalidad.
                        #
                        # Si X no puede cerrarse de forma segura,
                        # descartamos únicamente ese episodio causal
                        # y permitimos continuar observando Y.
                        context_store.clear_observed_human_action(
                            session_id=(
                                pending_previous_action.session_id
                            )
                        )

                        context_store.clear_observed_human_transition(
                            session_id=(
                                pending_previous_action.session_id
                            )
                        )

                observed = (
                    context_store
                    .set_observed_human_action(
                        resolved_next_action,
                        require_current_match=(
                            signal.evidence_id
                            is None
                        ),
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
                    "QCC_HUMAN_DOM_SIGNAL_EVIDENCE_ID_NOT_FOUND",
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

        # ---------------------------------------------
        # QCC_OBSERVATION_SCOPE_COMPAT_ROUTE_V1
        #
        # Runtime observation contracts historically
        # transport their identity in a field/route named
        # session_id.
        #
        # A technical ObservationScope may therefore
        # arrive here as the opaque route id.
        #
        # This does NOT create/register a PresentationSession.
        # ---------------------------------------------
        for profile_key in (
            browser_registry.profile_keys()
            or ()
        ):
            try:
                profile_store = (
                    browser_registry.get_store(
                        profile_key
                    )
                )

            except (
                TypeError,
                ValueError,
            ):
                continue

            if profile_store is None:
                continue

            scope_getter = getattr(
                profile_store,
                "get_observation_scope",
                None,
            )

            if not callable(
                scope_getter
            ):
                continue

            scope = (
                scope_getter()
            )

            if (
                scope is not None
                and scope.scope_id
                == normalized_session_id
            ):
                return profile_store

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



# ---------------------------------------------------------
# QCC_AUTO_TWIN_RUNTIME_VALIDATION_HOOK_V1
#
# Proyección técnica posterior al screenshot viewport.
#
# IMPORTANTE:
# - el PNG ya está persistido cuando entra aquí;
# - cualquier error AUTO TWIN es fail-open para el Bridge;
# - no cambia lifecycle;
# - no valida automáticamente;
# - no materializa ni promociona revisiones.
# ---------------------------------------------------------
def _qcc_project_auto_twin_validation_after_visual(
    *,
    ingestor,
    auto_twin_store,
    candidate_store,
    evidence_store,
    capture_id,
    artifact_kind,
):
    normalized_capture_id = str(
        capture_id
        or ""
    ).strip()

    normalized_kind = str(
        artifact_kind
        or ""
    ).strip().lower()

    base = {
        "processed":
            False,

        "reason":
            None,

        "status":
            None,

        "capture_id":
            (
                normalized_capture_id
                or None
            ),

        "profile_key":
            None,

        "site_code":
            None,

        "twin_key":
            None,

        "candidate_id":
            None,

        "real_capture_id":
            None,

        "verdict":
            None,

        "ready_for_validation":
            None,

        "evidence_id":
            None,
    }

    if normalized_kind != "viewport":
        return {
            **base,
            "reason":
                "VISUAL_KIND_NOT_VALIDATION",
        }

    if (
        ingestor is None
        or auto_twin_store is None
        or candidate_store is None
        or evidence_store is None
    ):
        return {
            **base,
            "reason":
                "AUTO_TWIN_VALIDATION_UNAVAILABLE",
        }

    try:
        # El bundle se carga por el capture_id exacto que
        # acaba de recibir el endpoint visual.
        #
        # No se enumera ningún directorio.
        twin_bundle = (
            load_auto_twin_persisted_capture_bundle(
                capture_id=(
                    normalized_capture_id
                ),
                root=(
                    ingestor.output_root
                ),
                require_viewport_image=True,
            )
        )

        twin_capture = (
            twin_bundle.get(
                "capture"
            )
            or {}
        )

        profile_key = str(
            twin_capture.get(
                "browser_profile_key"
            )
            or ""
        ).strip()

        base[
            "profile_key"
        ] = (
            profile_key
            or None
        )

        # Defensa explícita además del profile policy.
        if (
            profile_key
            != AUTO_TWIN_DISCOVERY_PROFILE_KEY
        ):
            return {
                **base,
                "reason":
                    "PROFILE_NOT_VALIDATION",
            }

        profile_policy = (
            build_auto_twin_profile_policy(
                profile_key
            )
        )

        if (
            getattr(
                profile_policy,
                "validate_twin",
                False,
            )
            is not True
        ):
            return {
                **base,
                "reason":
                    "PROFILE_NOT_VALIDATION",
            }

        # La identidad del managed TWIN no se deduce
        # del origin localhost ni del pathname.
        #
        # Site Architecture aporta site_code y el registry
        # garantiza unicidad.
        site_code = str(
            twin_bundle.get(
                "site_code"
            )
            or ""
        ).strip().upper()

        base[
            "site_code"
        ] = (
            site_code
            or None
        )

        if not site_code:
            return {
                **base,
                "reason":
                    "SITE_CODE_UNAVAILABLE",
            }

        managed_twin = (
            auto_twin_store
            .get_by_site_code(
                site_code
            )
        )

        if managed_twin is None:
            return {
                **base,
                "reason":
                    "MANAGED_TWIN_NOT_FOUND",
            }

        base[
            "twin_key"
        ] = managed_twin.twin_key

        run_result = (
            run_auto_twin_validation_evaluation(
                managed_twin=(
                    managed_twin
                ),
                profile_policy=(
                    profile_policy
                ),
                candidate_store=(
                    candidate_store
                ),
                evidence_store=(
                    evidence_store
                ),
                twin_capture_id=(
                    normalized_capture_id
                ),
                capture_root=(
                    ingestor.output_root
                ),
            )
        )

        decision = (
            run_result.get(
                "decision"
            )
            if isinstance(
                run_result,
                dict,
            )
            else None
        )

        if not isinstance(
            decision,
            dict,
        ):
            decision = {}

        evaluation = (
            run_result.get(
                "evaluation"
            )
            if isinstance(
                run_result,
                dict,
            )
            else None
        )

        if not isinstance(
            evaluation,
            dict,
        ):
            evaluation = {}

        return {
            **base,

            "processed":
                True,

            "reason":
                "AUTO_TWIN_VALIDATION_RUNNER_COMPLETED",

            "status":
                (
                    run_result.get(
                        "status"
                    )
                    if isinstance(
                        run_result,
                        dict,
                    )
                    else None
                ),

            "candidate_id":
                decision.get(
                    "candidate_id"
                ),

            "real_capture_id":
                decision.get(
                    "real_capture_id"
                ),

            "verdict":
                evaluation.get(
                    "verdict"
                ),

            "ready_for_validation":
                (
                    evaluation.get(
                        "ready_for_validation"
                    )
                    if evaluation
                    else None
                ),

            "evidence_id":
                evaluation.get(
                    "evidence_id"
                ),
        }

    except Exception as exc:
        # El screenshot ya pertenece a Site Architecture.
        #
        # Un fallo técnico AUTO TWIN no puede convertir
        # la persistencia visual en un error HTTP.
        return {
            **base,

            "reason":
                "AUTO_TWIN_VALIDATION_FAIL_CLOSED",

            "error_type":
                type(exc).__name__,
        }


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
        auto_twin_store: (
            AutoTwinManagedSiteStore
            | None
        ) = None,
        auto_twin_observation_store: (
            AutoTwinObservationStore
            | None
        ) = None,
        auto_twin_candidate_store: (
            AutoTwinCandidateRevisionStore
            | None
        ) = None,
        auto_twin_validation_evidence_store: (
            AutoTwinValidationEvidenceStore
            | None
        ) = None,
        auto_twin_catalog_dependency_store: (
            AutoTwinCatalogDependencyStore
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

        self._auto_twin_store = (
            auto_twin_store
            if auto_twin_store is not None
            else AutoTwinManagedSiteStore()
        )

        self._auto_twin_observation_store = (
            auto_twin_observation_store
            if auto_twin_observation_store is not None
            else AutoTwinObservationStore()
        )

        self._auto_twin_candidate_store = (
            auto_twin_candidate_store
            if auto_twin_candidate_store is not None
            else AutoTwinCandidateRevisionStore()
        )

        self._auto_twin_validation_evidence_store = (
            auto_twin_validation_evidence_store
            if auto_twin_validation_evidence_store is not None
            else AutoTwinValidationEvidenceStore()
        )

        self._auto_twin_catalog_dependency_store = (
            auto_twin_catalog_dependency_store
            if auto_twin_catalog_dependency_store is not None
            else AutoTwinCatalogDependencyStore()
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

        self._server.qcc_auto_twin_store = (
            self._auto_twin_store
        )

        self._server.qcc_auto_twin_observation_store = (
            self._auto_twin_observation_store
        )

        self._server.qcc_auto_twin_candidate_store = (
            self._auto_twin_candidate_store
        )

        self._server.qcc_auto_twin_validation_evidence_store = (
            self._auto_twin_validation_evidence_store
        )

        self._server.qcc_auto_twin_catalog_dependency_store = (
            self._auto_twin_catalog_dependency_store
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
    def auto_twin_store(
        self,
    ) -> AutoTwinManagedSiteStore:
        return self._auto_twin_store

    @property
    def auto_twin_observation_store(
        self,
    ) -> AutoTwinObservationStore:
        return self._auto_twin_observation_store

    @property
    def auto_twin_candidate_store(
        self,
    ) -> AutoTwinCandidateRevisionStore:
        return self._auto_twin_candidate_store

    @property
    def auto_twin_validation_evidence_store(
        self,
    ) -> AutoTwinValidationEvidenceStore:
        return self._auto_twin_validation_evidence_store

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
