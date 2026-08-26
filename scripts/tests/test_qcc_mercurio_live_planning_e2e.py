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
        "QCC_MERCURIO_E2E_TIMEOUT:"
        + expression
    )


def _open_options(
    browser,
):
    """Instrumentación exclusiva del Twin LAB."""

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
    """Reproduce en LAB el resultado de interacción humana."""

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


class _LiveObservationIngestor:
    """Adapter E2E: entrega al Bridge una observación ya viva.

    9D ya prueba por separado el ingestor/capture
    real de Site Architecture. Este E2E concentra
    la prueba en Navigation Intelligence 9E.
    """

    def __init__(
        self,
    ):
        self._state = None
        self._fingerprint = None
        self._counter = 0

    def set_snapshot(
        self,
        snapshot,
    ):
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

        self._state = state
        self._fingerprint = fingerprint

    def ingest(
        self,
        capture,
        *,
        context=None,
    ):
        assert self._state is not None
        assert self._fingerprint is not None

        self._counter += 1

        return {
            "capture_id":
                f"live-e2e-{self._counter}",

            "context_mode":
                "ASSISTED_PRESENTATION",

            "session_id":
                "merc-live-9e",

            "page": {
                "url":
                    "MERCURIO_TWIN",
            },

            "site_code":
                "MERCURIO",

            "received_at":
                "2026-08-26T13:30:00+00:00",

            "state_observation": {
                "state":
                    self._state,

                "fingerprint":
                    self._fingerprint,
            },

            "counts": {
                "elements":
                    0,
            },
        }


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


def test_mercurio_twin_live_intent_replans_until_target(
    tmp_path,
):
    """
    E2E 9E:

    Mercurio Twin vivo
    -> Chrome real
    -> fingerprints reales
    -> Navigation Knowledge
    -> QCC Bridge
    -> NavigationIntent transport
    -> CURRENT capture
    -> automatic replanning.
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
                    "qcc-9e-live-planning-e2e"
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

        # -----------------------------------------
        # STATE A · ENTRY_IDLE
        # -----------------------------------------

        open_url(
            browser,
            (
                base_url
                + "/mercurio/"
                "entradaMercurio.html"
            ),
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

        idle = _capture(
            browser,
            tmp_path / "captures",
            "idle",
        )

        idle_state = (
            recognize_mercurio_state(
                idle
            )
        )

        idle_fp = (
            build_functional_state_fingerprint(
                idle
            )
        )

        assert (
            idle_state
            == MercurioGeneralState
            .MERCURIO_ENTRY_IDLE
            .value
        )

        # -----------------------------------------
        # STATE B · ENTRY_OPTIONS
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

        options = _capture(
            browser,
            tmp_path / "captures",
            "options",
        )

        options_state = (
            recognize_mercurio_state(
                options
            )
        )

        options_fp = (
            build_functional_state_fingerprint(
                options
            )
        )

        assert (
            options_state
            == MercurioGeneralState
            .MERCURIO_ENTRY_OPTIONS
            .value
        )

        # -----------------------------------------
        # STATE C · MODEL_SELECTION
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

        model = _capture(
            browser,
            tmp_path / "captures",
            "model",
        )

        model_state = (
            recognize_mercurio_state(
                model
            )
        )

        model_fp = (
            build_functional_state_fingerprint(
                model
            )
        )

        assert (
            model_state
            == MercurioGeneralState
            .MERCURIO_MODEL_SELECTION
            .value
        )

        assert idle_fp != options_fp
        assert options_fp != model_fp

        # -----------------------------------------
        # KNOWLEDGE REALMENTE OBSERVADO
        # -----------------------------------------

        idle_to_options = (
            detect_state_transition(
                idle,
                options,
                action={
                    "kind":
                        "BUTTON",

                    "policy":
                        "REQUIRES_POLICY",

                    "selector":
                        (
                            '[aria-label='
                            '"CONTINUAR PRESENTACIÓN"]'
                        ),

                    "frame_path":
                        "main",
                },
            )
        )

        options_to_model = (
            detect_state_transition(
                options,
                model,
                action={
                    "kind":
                        "BUTTON",

                    "policy":
                        "REQUIRES_POLICY",

                    "selector":
                        (
                            'button['
                            'onclick="irOpcion()"]'
                        ),

                    "frame_path":
                        "main",
                },
            )
        )

        assert (
            idle_to_options["changed"]
            is True
        )

        assert (
            options_to_model["changed"]
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
            "MERCURIO",
            idle_to_options,
            before_state=(
                idle_state
            ),
            after_state=(
                options_state
            ),
        )

        knowledge.record_transition(
            "MERCURIO",
            options_to_model,
            before_state=(
                options_state
            ),
            after_state=(
                model_state
            ),
        )

        graph = knowledge.build_graph(
            "MERCURIO"
        )

        assert graph["node_count"] == 3
        assert graph["edge_count"] == 2

        # -----------------------------------------
        # BRIDGE + SESSION + INTENT TRANSPORT
        # -----------------------------------------

        ingestor = (
            _LiveObservationIngestor()
        )

        bridge = QccBridgeServer(
            port=0,
            site_architecture_ingestor=(
                ingestor
            ),
            navigation_knowledge_store=(
                knowledge
            ),
        )

        bridge.start()

        bridge_url = (
            f"http://{bridge.host}:"
            f"{bridge.port}"
        )

        reporter = (
            QccPresentationReporter(
                session_id="merc-live-9e",
                expedient_id=1,
                client_id=1,
                procedure="TEST",
                provider="MERCURIO",
                runtime=(
                    "SELENIUMBASE_ASSISTED"
                ),
                bridge_base_url=(
                    bridge_url
                ),
            )
        )

        assert reporter.started() is True

        intent_client = (
            QccNavigationIntentClient(
                session_id="merc-live-9e",
                bridge_base_url=(
                    bridge_url
                ),
            )
        )

        intent = QccNavigationIntent(
            session_id="merc-live-9e",
            site_code="MERCURIO",
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

        # Aún no hay CURRENT.
        assert (
            bridge.context_store
            .get_live_navigation()
            is None
        )

        # -----------------------------------------
        # CURRENT = IDLE
        # -----------------------------------------

        ingestor.set_snapshot(
            idle
        )

        payload = _post_capture(
            bridge
        )

        assert (
            payload[
                "live_projection"
            ][
                "projected"
            ]
            is True
        )

        assert (
            payload[
                "live_planning"
            ][
                "refreshed"
            ]
            is True
        )

        live = (
            bridge.context_store
            .snapshot()[
                "live_navigation"
            ]
        )

        assert (
            live["current"]["state"]
            == idle_state
        )

        assert (
            live["target"]["state"]
            == model_state
        )

        assert (
            live["route"][
                "reachable"
            ]
            is True
        )

        assert (
            live["route"][
                "remaining_steps"
            ]
            == 2
        )

        assert (
            live["next_step"][
                "selector"
            ]
            == (
                '[aria-label='
                '"CONTINUAR PRESENTACIÓN"]'
            )
        )

        assert live["governance"] is None

        # -----------------------------------------
        # CURRENT = OPTIONS
        # -----------------------------------------

        ingestor.set_snapshot(
            options
        )

        _post_capture(
            bridge
        )

        live = (
            bridge.context_store
            .snapshot()[
                "live_navigation"
            ]
        )

        assert (
            live["current"]["state"]
            == options_state
        )

        assert (
            live["target"]["state"]
            == model_state
        )

        assert (
            live["route"][
                "remaining_steps"
            ]
            == 1
        )

        assert (
            live["next_step"][
                "selector"
            ]
            == (
                'button['
                'onclick="irOpcion()"]'
            )
        )

        assert live["governance"] is None

        # -----------------------------------------
        # CURRENT = TARGET
        # -----------------------------------------

        ingestor.set_snapshot(
            model
        )

        _post_capture(
            bridge
        )

        live = (
            bridge.context_store
            .snapshot()[
                "live_navigation"
            ]
        )

        assert (
            live["current"]["state"]
            == model_state
        )

        assert (
            live["target"]["state"]
            == model_state
        )

        assert (
            live["current"][
                "fingerprint"
            ]
            == model_fp
        )

        assert (
            live["target"][
                "fingerprint"
            ]
            == model_fp
        )

        assert (
            live["route"][
                "reachable"
            ]
            is True
        )

        assert (
            live["route"][
                "remaining_steps"
            ]
            == 0
        )

        assert live["next_step"] is None

        # 9E sigue siendo puramente descriptivo.
        assert live["governance"] is None

    finally:
        if bridge is not None:
            bridge.close()

        if (
            browser_session.browser
            is not None
        ):
            browser_session.shutdown(
                BrowserShutdownMode.CLOSE
            )

        twin.shutdown()
        twin.server_close()

        twin_thread.join(
            timeout=5
        )
