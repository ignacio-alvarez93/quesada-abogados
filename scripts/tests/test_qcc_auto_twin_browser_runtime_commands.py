from pathlib import Path
from types import SimpleNamespace
import json
import threading


from backend.automation.browser_contracts import (
    BrowserShutdownMode,
)

from backend.services.twin_browser_runtime_service import (
    TwinBrowserRuntimeService,
)


class FakeLocalRuntime:
    def __init__(self):
        self.running = None

    def get_status(
        self,
        *,
        twin_key,
    ):
        if self.running is None:
            return {
                "twin_key":
                    twin_key,

                "status":
                    "STOPPED",

                "revision_id":
                    None,

                "base_url":
                    None,
            }

        return dict(
            self.running
        )

    def start(
        self,
        *,
        twin_key,
        revision_id,
    ):
        self.running = {
            "twin_key":
                twin_key,

            "status":
                "RUNNING",

            "revision_id":
                revision_id,

            "base_url":
                "http://127.0.0.1:45678",
        }

        return dict(
            self.running
        )

    def stop(
        self,
        *,
        twin_key,
    ):
        self.running = None

        return {
            "twin_key":
                twin_key,

            "status":
                "STOPPED",
        }


class FakeBrowser:
    def __init__(self):
        self.calls = []

    def execute_script(
        self,
        script,
        *args,
    ):
        result = {
            "thread_id":
                threading.get_ident(),

            "script":
                script,

            "args":
                list(
                    args
                ),
        }

        self.calls.append(
            result
        )

        return result


class FakeSession:
    def __init__(
        self,
        *,
        config,
        profile_resolver,
    ):
        self.config = config

        self.identity = SimpleNamespace(
            profile_key=(
                config.profile_key
            ),
            mode=(
                config.mode
            ),
        )

        self.browser = (
            FakeBrowser()
        )

    def start(self):
        return self.browser

    def shutdown(
        self,
        mode,
    ):
        assert (
            mode
            == BrowserShutdownMode.CLOSE
        )

        return None


class FakeReporter:
    def __init__(
        self,
        **kwargs,
    ):
        self.kwargs = kwargs

    def register(self):
        return True

    def unregister(self):
        return True


def _revision(
    root,
):
    revision = (
        root
        / "red_sara"
        / "matrev-command-test"
    )

    runtime = (
        revision
        / "runtime"
    )

    runtime.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        runtime
        / "registry.json"
    ).write_text(
        json.dumps({
            "states": [
                {
                    "state_id":
                        "AUTO_STATE",

                    "pathname":
                        "/es/nuevo-registro",

                    "runtime_entry":
                        (
                            "states/01-AUTO_STATE/"
                            "runtime/index.html"
                        ),
                }
            ],
        }),
        encoding="utf-8",
    )

    return revision


def test_execute_script_runs_on_browser_owner_thread(
    tmp_path,
):
    _revision(
        tmp_path
    )

    sessions = []

    def factory(
        *,
        config,
        profile_resolver,
    ):
        session = FakeSession(
            config=config,
            profile_resolver=(
                profile_resolver
            ),
        )

        sessions.append(
            session
        )

        return session

    service = TwinBrowserRuntimeService(
        materialized_root=tmp_path,
        local_runtime_service=(
            FakeLocalRuntime()
        ),
        browser_session_factory=(
            factory
        ),
        profile_resolver=(
            lambda key:
                tmp_path
                / "profiles"
                / key
        ),
        browser_open=(
            lambda browser, url:
                None
        ),
        reporter_factory=(
            FakeReporter
        ),
    )

    main_thread = (
        threading.get_ident()
    )

    started = service.start(
        twin_key="red_sara",
        revision_id=(
            "matrev-command-test"
        ),
        pathname=(
            "/es/nuevo-registro"
        ),
    )

    assert (
        started[
            "status"
        ]
        == "RUNNING"
    )

    owner_thread = (
        started[
            "owner_thread_id"
        ]
    )

    assert (
        owner_thread
        is not None
    )

    assert (
        owner_thread
        != main_thread
    )

    result = (
        service.execute_script(
            twin_key="red_sara",
            script=(
                "return arguments[0];"
            ),
            args=[
                "hello"
            ],
        )
    )

    assert (
        result[
            "thread_id"
        ]
        == owner_thread
    )

    assert (
        result[
            "thread_id"
        ]
        != main_thread
    )

    assert (
        result[
            "args"
        ]
        == [
            "hello"
        ]
    )

    stopped = service.stop(
        twin_key="red_sara"
    )

    assert (
        stopped[
            "status"
        ]
        == "STOPPED"
    )


def test_generic_script_executor_wraps_cdp_return_statements():
    from backend.services.twin_browser_runtime_service import (
        _execute_browser_script,
    )

    class FakeCdp:
        def __init__(self):
            self.expression = None

        def evaluate(
            self,
            expression,
        ):
            self.expression = expression

            return {
                "ok":
                    True,
            }

        def execute_script(
            self,
            *args,
        ):
            raise AssertionError(
                "CDP surface must prefer evaluate()"
            )

    browser = FakeCdp()

    result = _execute_browser_script(
        browser=browser,
        script=(
            "return arguments[0];"
        ),
        args=[
            "hello",
        ],
    )

    assert result == {
        "ok":
            True,
    }

    assert (
        browser.expression.startswith(
            "(function(){"
        )
    )

    assert (
        "return arguments[0];"
        in browser.expression
    )

    assert (
        browser.expression.endswith(
            '}).apply(null,["hello"])'
        )
    )

    # Critical contract: return is inside the function,
    # never at evaluate() top level.
    assert not (
        browser.expression
        .lstrip()
        .startswith(
            "return "
        )
    )


def test_generic_script_executor_preserves_webdriver_semantics():
    from backend.services.twin_browser_runtime_service import (
        _execute_browser_script,
    )

    class FakeWebDriver:
        def __init__(self):
            self.call = None

        def execute_script(
            self,
            script,
            *args,
        ):
            self.call = (
                script,
                args,
            )

            return "webdriver-result"

    browser = FakeWebDriver()

    result = _execute_browser_script(
        browser=browser,
        script=(
            "return arguments[0];"
        ),
        args=[
            "hello",
        ],
    )

    assert (
        result
        == "webdriver-result"
    )

    assert browser.call == (
        "return arguments[0];",
        (
            "hello",
        ),
    )
