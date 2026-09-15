import json
import os
import threading
import time
from urllib.request import (
    Request,
    urlopen,
)

import pytest

from backend.automation.browser_actions import (
    open_url,
)
from backend.automation.browser_contracts import (
    BrowserSessionConfig,
    BrowserSessionMode,
    BrowserShutdownMode,
)
from backend.automation.seleniumbase_browser_session import (
    SeleniumBaseBrowserSession,
)
from backend.automation.site_architecture import (
    build_functional_state_fingerprint,
    capture_site_architecture,
    detect_state_transition,
)
from backend.automation.site_architecture.managed_execution import (
    ManagedSiteProfile,
)
from backend.automation.site_architecture.managed_governance_registry import (
    ManagedSiteGovernanceOrigin,
    ManagedSiteGovernanceRegistration,
    ManagedSiteGovernanceRegistry,
)
from backend.automation.site_architecture.site_interaction_policy import (
    SITE_INTERACTION_HUMAN_ONLY,
)
from backend.automation.site_architecture.site_target import (
    SiteEnvironment,
)
from backend.automation.site_policies.mercurio import (
    MERCURIO_ALLOWED_PATH_PREFIXES,
    MERCURIO_CAPABILITIES,
    MERCURIO_INTERACTION_POLICY_CODE,
    MERCURIO_SITE_CODE,
    build_mercurio_interaction_policy,
)
from backend.automation.site_recognizers.mercurio import (
    recognize_mercurio_state,
)
from backend.qcc.bridge.server import (
    QccBridgeServer,
)
from backend.qcc.client.navigation_intent_client import (
    QccNavigationIntentClient,
)
from backend.qcc.client.presentation_reporter import (
    QccPresentationReporter,
)
from backend.qcc.context.navigation_intent import (
    QccNavigationIntent,
)
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
)
from backend.qcc.navigation_knowledge import (
    NavigationKnowledgeStore,
)
from backend.qcc.site_architecture import (
    QccSiteArchitectureIngestor,
)
from tools.mercurio_lab.core.states import (
    MercurioGeneralState,
)
from tools.mercurio_lab.server import (
    MercurioLabHandler,
    MercurioLabServer,
)


RUN_LIVE_BROWSER_TESTS = (
    os.environ.get(
        "QCC_RUN_LIVE_BROWSER_TESTS",
        "",
    ).strip()
    == "1"
)


pytestmark = pytest.mark.skipif(
    not RUN_LIVE_BROWSER_TESTS,
    reason=(
        "Live Chrome test opt-in: "
        "QCC_RUN_LIVE_BROWSER_TESTS=1"
    ),
)


def _browser_eval(
    browser,
    expression,
):
    if hasattr(
        browser,
        "evaluate",
    ):
        return browser.evaluate(
            expression
        )

    if hasattr(
        browser,
        "execute_script",
    ):
        return browser.execute_script(
            "return "
            + expression
        )

    raise RuntimeError(
        "LIVE_TEST_BROWSER_EVALUATION_UNSUPPORTED"
    )


def _wait_until(
    browser,
    expression,
    *,
    timeout=10,
):
    deadline = (
        time.monotonic()
        + timeout
    )

    while (
        time.monotonic()
        < deadline
    ):
        try:
            result = _browser_eval(
                browser,
                (
                    "(function(){"
                    f"return !!({expression});"
                    "})()"
                ),
            )

            if result:
                return

        except Exception:
            pass

        time.sleep(
            0.1
        )

    raise TimeoutError(
        "QCC_MERCURIO_9F_E2E_TIMEOUT:"
        + expression
    )


def _open_options(
    browser,
):
    """Twin LAB: emula resultado de acción humana."""

    return _browser_eval(
        browser,
        """
        (function(){
            if (
                typeof window.mostrarOpcion
                !== 'function'
            ) {
                return false;
            }

            window.mostrarOpcion();

            return true;
        })()
        """,
    )


def _continue_to_model(
    browser,
):
    """Twin LAB: emula preparación + avance humano."""

    return _browser_eval(
        browser,
        """
        (function(){
            const radio =
                document.getElementById(
                    'bscIniciales'
                );

            const province =
                document.getElementById(
                    'provincia'
                );

            if (
                !radio
                || !province
                || typeof window.irOpcion
                    !== 'function'
            ) {
                return false;
            }

            radio.checked = true;

            radio.dispatchEvent(
                new Event(
                    'change',
                    {bubbles: true}
                )
            );

            province.value = '33';

            province.dispatchEvent(
                new Event(
                    'change',
                    {bubbles: true}
                )
            );

            if (
                typeof window.establecerCodProvincia
                === 'function'
            ) {
                window.establecerCodProvincia();
            }

            window.irOpcion();

            return true;
        })()
        """,
    )


def _capture(
    browser,
    root,
    label,
):
    return (
        capture_site_architecture(
            browser,
            root,
            label=label,
        )[
            "snapshot"
        ]
    )


def _safe_live_actions(
    snapshot,
):
    return (
        QccSiteArchitectureIngestor
        ._live_action_evidence(
            snapshot
        )
    )


def _find_live_action(
    snapshot,
    *,
    selector,
):
    matches = [
        action
        for action
        in _safe_live_actions(
            snapshot
        )
        if (
            action.get(
                "selector"
            )
            == selector
        )
    ]

    assert len(matches) == 1, (
        selector,
        matches,
    )

    return matches[0]


def _safe_identity(
    action,
):
    return {
        "kind":
            action["kind"],

        "policy":
            action["policy"],

        "selector":
            action["selector"],

        "frame_path":
            action["frame_path"],
    }


class _LiveGovernanceIngestor:
    """Entrega al Bridge evidencia de snapshots Chrome reales."""

    def __init__(
        self,
        *,
        session_id,
    ):
        self._session_id = (
            session_id
        )

        self._snapshot = None
        self._counter = 0

    def set_snapshot(
        self,
        snapshot,
    ):
        self._snapshot = snapshot

    def ingest(
        self,
        capture,
        *,
        context=None,
    ):
        assert self._snapshot is not None

        snapshot = self._snapshot

        state = (
            recognize_mercurio_state(
                snapshot
            )
        )

        fingerprint = (
            build_functional_state_fingerprint(
                snapshot
            )
        )

        assert state is not None
        assert len(fingerprint) == 64

        self._counter += 1

        return {
            "capture_id":
                (
                    "merc-live-9f-"
                    f"{self._counter}"
                ),

            "context_mode":
                "ASSISTED_PRESENTATION",

            "session_id":
                self._session_id,

            "site_code":
                MERCURIO_SITE_CODE,

            "page": {
                "url":
                    snapshot.page.url,

                "title":
                    snapshot.page.title,
            },

            "received_at":
                "2026-08-26T14:00:00+00:00",

            "state_observation": {
                "state":
                    state,

                "fingerprint":
                    fingerprint,
            },

            # Evidencia obtenida del DOM real
            # de ESTA captura.
            "live_actions":
                _safe_live_actions(
                    snapshot
                ),

            "counts":
                dict(
                    snapshot.counts
                ),
        }


def _build_test_governance_registry(
    base_url,
):
    """Solo cambia origin LAB para el puerto efímero.

    La política Mercurio es exactamente la productiva.
    """

    def profile_builder(
        environment,
    ):
        assert (
            environment
            == SiteEnvironment.LAB
        )

        return ManagedSiteProfile(
            site_code=(
                MERCURIO_SITE_CODE
            ),
            environment=(
                SiteEnvironment.LAB
            ),
            allowed_origins=(
                base_url,
            ),
            allowed_path_prefixes=(
                MERCURIO_ALLOWED_PATH_PREFIXES
            ),
            interaction_policy=(
                MERCURIO_INTERACTION_POLICY_CODE
            ),
            capabilities=(
                MERCURIO_CAPABILITIES
            ),
        )

    registry = (
        ManagedSiteGovernanceRegistry()
    )

    registry.register(
        ManagedSiteGovernanceRegistration(
            site_code=(
                MERCURIO_SITE_CODE
            ),

            origins=(
                ManagedSiteGovernanceOrigin(
                    environment=(
                        SiteEnvironment.LAB
                    ),
                    origin=base_url,
                ),
            ),

            profile_builder=(
                profile_builder
            ),

            policy_builder=(
                build_mercurio_interaction_policy
            ),
        )
    )

    return registry


def _post_capture(
    bridge,
):
    body = json.dumps({
        "protocol_version":
            QCC_PROTOCOL_VERSION,

        "capture": {
            "e2e":
                True,
        },
    }).encode(
        "utf-8"
    )

    request = Request(
        (
            f"http://{bridge.host}:"
            f"{bridge.port}"
            "/qcc/site-architecture/capture"
        ),
        data=body,
        headers={
            "Content-Type":
                "application/json",
        },
        method="POST",
    )

    with urlopen(
        request,
        timeout=3,
    ) as response:
        return json.loads(
            response.read().decode(
                "utf-8"
            )
        )


def _assert_ephemeral_not_public(
    payload,
):
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
    )

    assert (
        '"runtime_plan"'
        not in serialized
    )

    assert (
        '"live_actions"'
        not in serialized
    )


def test_mercurio_twin_live_jit_governance(
    tmp_path,
):
    """
    E2E 9F:

    Mercurio Twin vivo
    -> Chrome SeleniumBase real
    -> Site Architecture real
    -> live actions reales
    -> knowledge observado
    -> NavigationIntent
    -> plan canónico runtime-only
    -> Managed Governance Registry
    -> govern_navigation_plan
    -> governance proyectado.

    Ningún click sensible es ejecutado por 9F.
    """

    twin = MercurioLabServer(
        ("127.0.0.1", 0),
        MercurioLabHandler,
    )

    twin_thread = threading.Thread(
        target=twin.serve_forever,
        daemon=True,
    )

    twin_thread.start()

    host, port = (
        twin.server_address
    )

    base_url = (
        f"http://{host}:{port}"
    )

    browser_session = (
        SeleniumBaseBrowserSession(
            config=BrowserSessionConfig(
                consumer=(
                    "qcc-9f-live-governance-e2e"
                ),
                mode=(
                    BrowserSessionMode
                    .ASSISTED
                ),
                headless=True,
                profile_key=None,
            )
        )
    )

    bridge = None

    try:
        browser = (
            browser_session.start()
        )

        entry_url = (
            base_url
            + "/mercurio/"
            "entradaMercurio.html"
        )

        # =========================================
        # LEARNING PASS
        #
        # Solo construye conocimiento observado.
        # =========================================

        open_url(
            browser,
            entry_url,
        )

        _wait_until(
            browser,
            (
                "window.location.pathname"
                " === "
                "'/mercurio/"
                "entradaMercurio.html'"
            ),
        )

        learned_idle = _capture(
            browser,
            tmp_path / "learning",
            "idle",
        )

        learned_idle_state = (
            recognize_mercurio_state(
                learned_idle
            )
        )

        learned_idle_fp = (
            build_functional_state_fingerprint(
                learned_idle
            )
        )

        assert (
            learned_idle_state
            == MercurioGeneralState
            .MERCURIO_ENTRY_IDLE
            .value
        )

        idle_action = (
            _find_live_action(
                learned_idle,
                selector=(
                    '[aria-label='
                    '"CONTINUAR PRESENTACIÓN"]'
                ),
            )
        )

        assert (
            idle_action[
                "interaction"
            ][
                "visible"
            ]
            is True
        )

        assert (
            _open_options(
                browser
            )
            is not False
        )

        _wait_until(
            browser,
            """
            (function(){
                const el =
                    document.getElementById(
                        'twinEntryOptions'
                    );

                return (
                    el
                    && !el.hidden
                );
            })()
            """,
        )

        learned_options = _capture(
            browser,
            tmp_path / "learning",
            "options",
        )

        learned_options_state = (
            recognize_mercurio_state(
                learned_options
            )
        )

        learned_options_fp = (
            build_functional_state_fingerprint(
                learned_options
            )
        )

        assert (
            learned_options_state
            == MercurioGeneralState
            .MERCURIO_ENTRY_OPTIONS
            .value
        )

        options_action = (
            _find_live_action(
                learned_options,
                selector=(
                    'button['
                    'onclick="irOpcion()"]'
                ),
            )
        )

        assert (
            options_action[
                "interaction"
            ][
                "visible"
            ]
            is True
        )

        assert (
            _continue_to_model(
                browser
            )
            is not False
        )

        _wait_until(
            browser,
            (
                "window.location.pathname"
                ".startsWith("
                "'/mercurio/"
                "seleccionModelo-'"
                ")"
            ),
        )

        learned_model = _capture(
            browser,
            tmp_path / "learning",
            "model",
        )

        learned_model_state = (
            recognize_mercurio_state(
                learned_model
            )
        )

        learned_model_fp = (
            build_functional_state_fingerprint(
                learned_model
            )
        )

        assert (
            learned_model_state
            == MercurioGeneralState
            .MERCURIO_MODEL_SELECTION
            .value
        )

        assert (
            learned_idle_fp
            != learned_options_fp
        )

        assert (
            learned_options_fp
            != learned_model_fp
        )

        idle_to_options = (
            detect_state_transition(
                learned_idle,
                learned_options,
                action=(
                    _safe_identity(
                        idle_action
                    )
                ),
            )
        )

        options_to_model = (
            detect_state_transition(
                learned_options,
                learned_model,
                action=(
                    _safe_identity(
                        options_action
                    )
                ),
            )
        )

        assert (
            idle_to_options[
                "changed"
            ]
            is True
        )

        assert (
            options_to_model[
                "changed"
            ]
            is True
        )

        knowledge = (
            NavigationKnowledgeStore(
                root=(
                    tmp_path
                    / "knowledge"
                )
            )
        )

        knowledge.record_transition(
            MERCURIO_SITE_CODE,
            idle_to_options,
            before_state=(
                learned_idle_state
            ),
            after_state=(
                learned_options_state
            ),
        )

        knowledge.record_transition(
            MERCURIO_SITE_CODE,
            options_to_model,
            before_state=(
                learned_options_state
            ),
            after_state=(
                learned_model_state
            ),
        )

        graph = knowledge.build_graph(
            MERCURIO_SITE_CODE
        )

        assert graph["node_count"] == 3
        assert graph["edge_count"] == 2

        # =========================================
        # REAL JIT PASS
        #
        # Volvemos a IDLE y cada governance usa
        # el snapshot del estado que está AHORA
        # abierto en Chrome.
        # =========================================

        open_url(
            browser,
            entry_url,
        )

        _wait_until(
            browser,
            (
                "window.location.pathname"
                " === "
                "'/mercurio/"
                "entradaMercurio.html'"
            ),
        )

        ingestor = (
            _LiveGovernanceIngestor(
                session_id=(
                    "merc-live-9f"
                )
            )
        )

        bridge = QccBridgeServer(
            port=0,
            site_architecture_ingestor=(
                ingestor
            ),
            navigation_knowledge_store=(
                knowledge
            ),
            managed_governance_registry=(
                _build_test_governance_registry(
                    base_url
                )
            ),
        )

        bridge.start()

        bridge_url = (
            f"http://{bridge.host}:"
            f"{bridge.port}"
        )

        reporter = (
            QccPresentationReporter(
                session_id="merc-live-9f",
                expedient_id=1,
                client_id=1,
                procedure="TEST",
                provider=(
                    MERCURIO_SITE_CODE
                ),
                runtime=(
                    "SELENIUMBASE_ASSISTED"
                ),
                bridge_base_url=(
                    bridge_url
                ),
            )
        )

        assert (
            reporter.started()
            is True
        )

        intent_client = (
            QccNavigationIntentClient(
                session_id=(
                    "merc-live-9f"
                ),
                bridge_base_url=(
                    bridge_url
                ),
            )
        )

        intent = QccNavigationIntent(
            session_id="merc-live-9f",
            site_code=(
                MERCURIO_SITE_CODE
            ),
            target_state=(
                MercurioGeneralState
                .MERCURIO_MODEL_SELECTION
                .value
            ),
        )

        assert (
            intent_client.publish(
                intent
            )
            is True
        )

        # -----------------------------------------
        # LIVE IDLE
        # -----------------------------------------

        live_idle = _capture(
            browser,
            tmp_path / "live",
            "idle",
        )

        assert (
            build_functional_state_fingerprint(
                live_idle
            )
            == learned_idle_fp
        )

        ingestor.set_snapshot(
            live_idle
        )

        idle_payload = _post_capture(
            bridge
        )

        _assert_ephemeral_not_public(
            idle_payload
        )

        assert (
            idle_payload[
                "live_planning"
            ][
                "refreshed"
            ]
            is True
        )

        assert (
            idle_payload[
                "live_governance"
            ][
                "applied"
            ]
            is True
        )

        assert (
            idle_payload[
                "live_governance"
            ][
                "decision"
            ]
            == SITE_INTERACTION_HUMAN_ONLY
        )

        assert (
            idle_payload[
                "live_governance"
            ][
                "automation_allowed"
            ]
            is False
        )

        live_context = (
            bridge.context_store
            .snapshot()[
                "live_navigation"
            ]
        )

        assert (
            live_context[
                "current"
            ][
                "state"
            ]
            == learned_idle_state
        )

        assert (
            live_context[
                "route"
            ][
                "remaining_steps"
            ]
            == 2
        )

        assert (
            live_context[
                "next_step"
            ][
                "selector"
            ]
            == idle_action[
                "selector"
            ]
        )

        assert (
            live_context[
                "governance"
            ][
                "reason"
            ]
            == "SITE_POLICY_HUMAN_ONLY"
        )

        # -----------------------------------------
        # HUMAN OUTCOME -> LIVE OPTIONS
        # -----------------------------------------

        assert (
            _open_options(
                browser
            )
            is not False
        )

        _wait_until(
            browser,
            """
            (function(){
                const el =
                    document.getElementById(
                        'twinEntryOptions'
                    );

                return (
                    el
                    && !el.hidden
                );
            })()
            """,
        )

        live_options = _capture(
            browser,
            tmp_path / "live",
            "options",
        )

        assert (
            build_functional_state_fingerprint(
                live_options
            )
            == learned_options_fp
        )

        ingestor.set_snapshot(
            live_options
        )

        options_payload = (
            _post_capture(
                bridge
            )
        )

        _assert_ephemeral_not_public(
            options_payload
        )

        assert (
            options_payload[
                "live_governance"
            ][
                "decision"
            ]
            == SITE_INTERACTION_HUMAN_ONLY
        )

        assert (
            options_payload[
                "live_governance"
            ][
                "automation_allowed"
            ]
            is False
        )

        live_context = (
            bridge.context_store
            .snapshot()[
                "live_navigation"
            ]
        )

        assert (
            live_context[
                "current"
            ][
                "state"
            ]
            == learned_options_state
        )

        assert (
            live_context[
                "route"
            ][
                "remaining_steps"
            ]
            == 1
        )

        assert (
            live_context[
                "next_step"
            ][
                "selector"
            ]
            == options_action[
                "selector"
            ]
        )

        assert (
            live_context[
                "governance"
            ][
                "reason"
            ]
            == "SITE_POLICY_HUMAN_ONLY"
        )

        # -----------------------------------------
        # HUMAN OUTCOME -> LIVE TARGET
        # -----------------------------------------

        assert (
            _continue_to_model(
                browser
            )
            is not False
        )

        _wait_until(
            browser,
            (
                "window.location.pathname"
                ".startsWith("
                "'/mercurio/"
                "seleccionModelo-'"
                ")"
            ),
        )

        live_model = _capture(
            browser,
            tmp_path / "live",
            "model",
        )

        assert (
            build_functional_state_fingerprint(
                live_model
            )
            == learned_model_fp
        )

        ingestor.set_snapshot(
            live_model
        )

        model_payload = (
            _post_capture(
                bridge
            )
        )

        _assert_ephemeral_not_public(
            model_payload
        )

        assert (
            model_payload[
                "live_governance"
            ][
                "applied"
            ]
            is True
        )

        assert (
            model_payload[
                "live_governance"
            ][
                "decision"
            ]
            == "NO_ACTION_REQUIRED"
        )

        assert (
            model_payload[
                "live_governance"
            ][
                "automation_allowed"
            ]
            is False
        )

        live_context = (
            bridge.context_store
            .snapshot()[
                "live_navigation"
            ]
        )

        assert (
            live_context[
                "current"
            ][
                "fingerprint"
            ]
            == learned_model_fp
        )

        assert (
            live_context[
                "target"
            ][
                "fingerprint"
            ]
            == learned_model_fp
        )

        assert (
            live_context[
                "route"
            ][
                "reachable"
            ]
            is True
        )

        assert (
            live_context[
                "route"
            ][
                "remaining_steps"
            ]
            == 0
        )

        assert (
            live_context[
                "next_step"
            ]
            is None
        )

        assert (
            live_context[
                "governance"
            ][
                "decision"
            ]
            == "NO_ACTION_REQUIRED"
        )

        assert (
            live_context[
                "governance"
            ][
                "reason"
            ]
            == "ALREADY_AT_TARGET"
        )

        assert (
            live_context[
                "governance"
            ][
                "automation_allowed"
            ]
            is False
        )

    finally:
        if bridge is not None:
            bridge.close()

        try:
            browser_session.shutdown(
                BrowserShutdownMode.CLOSE
            )
        except Exception:
            pass

        twin.shutdown()
        twin.server_close()

        twin_thread.join(
            timeout=2.0
        )
