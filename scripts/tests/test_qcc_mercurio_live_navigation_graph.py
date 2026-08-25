import os
import threading
import time

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
    build_navigation_graph,
    capture_site_architecture,
    detect_state_transition,
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
    """
    Evaluación mínima para el LAB harness.

    No forma parte del runtime productivo Mercurio.
    """

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


def _lab_wait_until(
    browser,
    expression,
    *,
    timeout=10,
):
    """
    Espera exclusiva del harness LAB.

    No implementa navegación productiva.
    """

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
                return True

        except Exception:
            pass

        time.sleep(
            0.1
        )

    raise TimeoutError(
        "LIVE_TWIN_STATE_TIMEOUT: "
        + expression
    )


def _lab_trigger_open_options(
    browser,
):
    """
    Instrumentación de laboratorio.

    Esta llamada NO representa permiso para que
    el runtime productivo automatice este botón.
    """

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


def _lab_prepare_and_continue(
    browser,
):
    """
    Instrumentación de laboratorio.

    Reproduce el resultado de la interacción humana
    para poder observar la transición funcional real
    del Twin.
    """

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
    result = capture_site_architecture(
        browser,
        root,
        label=label,
    )

    return result[
        "snapshot"
    ]


def test_live_twin_builds_observed_navigation_graph(
    tmp_path,
):
    """
    E2E:

    Mercurio Twin real
    -> Chrome real
    -> DOM vivo
    -> Site Architecture
    -> Functional State
    -> Transition
    -> Navigation Graph.
    """

    server = MercurioLabServer(
        ("127.0.0.1", 0),
        MercurioLabHandler,
    )

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )

    thread.start()

    host, port = (
        server.server_address
    )

    base_url = (
        f"http://{host}:{port}"
    )

    config = BrowserSessionConfig(
        consumer="qcc-live-twin-test",
        mode=BrowserSessionMode.ASSISTED,
        headless=True,
        profile_key=None,
    )

    session = SeleniumBaseBrowserSession(
        config=config,
    )

    try:
        browser = session.start()

        open_url(
            browser,
            (
                base_url
                + "/mercurio/"
                "entradaMercurio.html"
            ),
        )

        _lab_wait_until(
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
            tmp_path,
            "entry_idle",
        )

        assert (
            idle.page.pathname
            == (
                "/mercurio/"
                "entradaMercurio.html"
            )
        )

        assert (
            _lab_trigger_open_options(
                browser
            )
            is not False
        )

        _lab_wait_until(
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
            tmp_path,
            "entry_options",
        )

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

        assert (
            idle_to_options[
                "changed"
            ]
            is True
        )

        assert (
            _lab_prepare_and_continue(
                browser
            )
            is not False
        )

        _lab_wait_until(
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
            tmp_path,
            "model_selection",
        )

        assert (
            model.page.pathname
            == (
                "/mercurio/"
                "seleccionModelo-33.html"
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
            options_to_model[
                "changed"
            ]
            is True
        )

        graph = (
            build_navigation_graph(
                (
                    idle_to_options,
                    options_to_model,
                )
            )
        )

        assert (
            graph["node_count"]
            == 3
        )

        assert (
            graph["edge_count"]
            == 2
        )

        assert (
            graph[
                "changed_observation_count"
            ]
            == 2
        )

        assert all(
            edge[
                "observation_count"
            ]
            == 1
            for edge in graph[
                "edges"
            ]
        )

    finally:
        if (
            session.browser
            is not None
        ):
            session.shutdown(
                BrowserShutdownMode.CLOSE
            )

        server.shutdown()
        server.server_close()
        thread.join(
            timeout=5
        )
