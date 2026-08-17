import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.automation.connectors import (
    whatsapp_connector,
)


class FakeBrowser:
    def __init__(self, body_text):
        self.body_text = body_text

    def get_text(self, selector):
        if selector != "body":
            raise ValueError(selector)

        return self.body_text


class WhatsAppSessionContractTest(
    unittest.TestCase
):
    def test_detects_login_state(self):
        connector = (
            whatsapp_connector
            .WhatsAppConnector()
        )

        connector.browser = FakeBrowser(
            "Scan this QR code "
            "to use WhatsApp on your computer"
        )

        self.assertEqual(
            connector.detect_session_status(),
            whatsapp_connector
            .SESSION_STATUS_NEEDS_LOGIN,
        )

    def test_detects_ready_state(self):
        connector = (
            whatsapp_connector
            .WhatsAppConnector()
        )

        connector.browser = FakeBrowser(
            "Search or start new chat"
        )

        self.assertEqual(
            connector.detect_session_status(),
            whatsapp_connector
            .SESSION_STATUS_READY,
        )

    def test_empty_page_is_loading(self):
        connector = (
            whatsapp_connector
            .WhatsAppConnector()
        )

        connector.browser = FakeBrowser("")

        self.assertEqual(
            connector.detect_session_status(),
            whatsapp_connector
            .SESSION_STATUS_LOADING,
        )

    def test_start_uses_governed_persistent_session(
        self,
    ):
        class FakeGovernedSession:
            instances = []

            def __init__(
                self,
                *,
                config,
                profile_resolver,
            ):
                self.config = config
                self.profile_resolver = (
                    profile_resolver
                )

                self.browser = object()
                self.start_calls = 0
                self.shutdown_modes = []

                self.__class__.instances.append(
                    self
                )

            def start(
                self,
            ):
                self.start_calls += 1

                return self.browser

            def shutdown(
                self,
                mode,
            ):
                self.shutdown_modes.append(
                    mode
                )

                return SimpleNamespace(
                    has_error=False,
                    control_released=True,
                    browser_closed=True,
                )

        with patch.object(
            whatsapp_connector,
            "open_url",
        ) as open_url_mock:
            connector = (
                whatsapp_connector
                .WhatsAppConnector(
                    profile_key="whatsapp_dev",
                    headless=True,
                    browser_session_factory=(
                        FakeGovernedSession
                    ),
                )
            )

            browser = connector.start()

        self.assertEqual(
            len(
                FakeGovernedSession.instances
            ),
            1,
        )

        session = (
            FakeGovernedSession.instances[0]
        )

        self.assertIs(
            browser,
            session.browser,
        )

        self.assertIs(
            connector.browser,
            session.browser,
        )

        self.assertEqual(
            session.config.consumer,
            "whatsapp",
        )

        self.assertEqual(
            session.config.mode.value,
            "PERSISTENT",
        )

        self.assertEqual(
            session.config.profile_key,
            "whatsapp_dev",
        )

        self.assertTrue(
            session.config.headless
        )

        self.assertIs(
            session.profile_resolver,
            whatsapp_connector
            .get_whatsapp_profile_dir,
        )

        self.assertEqual(
            session.start_calls,
            1,
        )

        open_url_mock.assert_called_once_with(
            browser,
            whatsapp_connector.WHATSAPP_WEB_URL,
        )

    def test_start_sets_only_whatsapp_microphone_permission(
        self,
    ):
        class FakeLoop:
            def __init__(
                self,
            ):
                self.completed = []

            def run_until_complete(
                self,
                value,
            ):
                self.completed.append(
                    value
                )

                return value

        class FakePage:
            def __init__(
                self,
            ):
                self.commands = []

            def send(
                self,
                command,
            ):
                payload = next(
                    command
                )

                self.commands.append(
                    payload
                )

                return payload

        class FakeBrowser:
            def __init__(
                self,
            ):
                self.loop = FakeLoop()
                self.page = FakePage()

        class FakeGovernedSession:
            instances = []

            def __init__(
                self,
                *,
                config,
                profile_resolver,
            ):
                self.config = config
                self.profile_resolver = (
                    profile_resolver
                )

                self.browser = FakeBrowser()

                self.__class__.instances.append(
                    self
                )

            def start(
                self,
            ):
                return self.browser

        with patch.object(
            whatsapp_connector,
            "open_url",
        ) as open_url_mock:
            connector = (
                whatsapp_connector
                .WhatsAppConnector(
                    profile_key="whatsapp_dev",
                    browser_session_factory=(
                        FakeGovernedSession
                    ),
                )
            )

            browser = connector.start()

        open_url_mock.assert_called_once_with(
            browser,
            whatsapp_connector.WHATSAPP_WEB_URL,
        )

        self.assertEqual(
            len(
                browser.page.commands
            ),
            1,
        )

        command = (
            browser.page.commands[0]
        )

        self.assertEqual(
            command.get(
                "method"
            ),
            "Browser.setPermission",
        )

        params = (
            command.get(
                "params"
            )
            or {}
        )

        self.assertEqual(
            params.get(
                "origin"
            ),
            whatsapp_connector
            .WHATSAPP_WEB_ORIGIN,
        )

        self.assertEqual(
            params.get(
                "setting"
            ),
            "granted",
        )

        permission = (
            params.get(
                "permission"
            )
            or {}
        )

        self.assertEqual(
            permission.get(
                "name"
            ),
            "microphone",
        )

        self.assertEqual(
            connector
            .call_media_permission_result[
                "configured"
            ],
            True,
        )

        self.assertEqual(
            connector
            .call_media_permission_result[
                "permission"
            ],
            "microphone",
        )

        self.assertNotIn(
            "camera",
            str(
                command
            ).lower(),
        )


    def test_start_preserves_chat_when_cdp_permission_transport_is_missing(
        self,
    ):
        class FakeGovernedSession:
            instances = []

            def __init__(
                self,
                *,
                config,
                profile_resolver,
            ):
                self.config = config
                self.profile_resolver = (
                    profile_resolver
                )
                self.browser = object()

                self.__class__.instances.append(
                    self
                )

            def start(
                self,
            ):
                return self.browser

        with patch.object(
            whatsapp_connector,
            "open_url",
        ) as open_url_mock:
            connector = (
                whatsapp_connector
                .WhatsAppConnector(
                    browser_session_factory=(
                        FakeGovernedSession
                    ),
                )
            )

            browser = connector.start()

        self.assertIs(
            browser,
            connector.browser,
        )

        open_url_mock.assert_called_once_with(
            browser,
            whatsapp_connector.WHATSAPP_WEB_URL,
        )

        result = (
            connector
            .call_media_permission_result
        )

        self.assertFalse(
            result[
                "configured"
            ]
        )

        self.assertEqual(
            result[
                "reason"
            ],
            "CDP_PERMISSION_TRANSPORT_UNAVAILABLE",
        )


    def test_reads_enabled_call_microphone_state(
        self,
    ):
        class FakeBrowser:
            def evaluate(
                self,
                expression,
            ):
                return {
                    "call_present": True,
                    "mute": {
                        "testid": "mic-mute",
                        "aria_label":
                            "Silenciar micrófono",
                        "disabled": False,
                        "aria_disabled":
                            "false",
                    },
                    "unmute": None,
                    "split": {
                        "testid":
                            "mic-split-button",
                        "aria_label":
                            "Silenciar micrófono",
                        "disabled": False,
                        "aria_disabled":
                            "",
                    },
                }

        connector = (
            whatsapp_connector
            .WhatsAppConnector()
        )

        connector.browser = FakeBrowser()

        result = (
            connector
            .read_call_microphone_state()
        )

        self.assertEqual(
            result[
                "state"
            ],
            whatsapp_connector
            .WHATSAPP_CALL_MIC_STATE_ENABLED,
        )

        self.assertFalse(
            result[
                "click_required"
            ]
        )

        self.assertEqual(
            result[
                "selector"
            ],
            whatsapp_connector
            .WHATSAPP_CALL_MIC_MUTE_SELECTOR,
        )


    def test_reads_muted_call_microphone_state(
        self,
    ):
        class FakeBrowser:
            def evaluate(
                self,
                expression,
            ):
                return {
                    "call_present": True,
                    "mute": None,
                    "unmute": {
                        "testid": "mic-unmute",
                        "aria_label":
                            "Desactivar silencio del micrófono",
                        "disabled": False,
                        "aria_disabled":
                            "false",
                    },
                    "split": {
                        "testid":
                            "mic-split-button",
                        "aria_label":
                            "Desactivar silencio del micrófono",
                        "disabled": False,
                        "aria_disabled":
                            "",
                    },
                }

        connector = (
            whatsapp_connector
            .WhatsAppConnector()
        )

        connector.browser = FakeBrowser()

        result = (
            connector
            .read_call_microphone_state()
        )

        self.assertEqual(
            result[
                "state"
            ],
            whatsapp_connector
            .WHATSAPP_CALL_MIC_STATE_MUTED,
        )

        self.assertTrue(
            result[
                "click_required"
            ]
        )

        self.assertEqual(
            result[
                "selector"
            ],
            whatsapp_connector
            .WHATSAPP_CALL_MIC_UNMUTE_SELECTOR,
        )


    def test_unknown_microphone_state_never_requests_click(
        self,
    ):
        class FakeBrowser:
            def evaluate(
                self,
                expression,
            ):
                return {
                    "call_present": True,
                    "mute": None,
                    "unmute": None,
                    "split": {
                        "testid":
                            "mic-split-button",
                        "aria_label":
                            "Estado inesperado",
                        "disabled": False,
                        "aria_disabled":
                            "",
                    },
                }

        connector = (
            whatsapp_connector
            .WhatsAppConnector()
        )

        connector.browser = FakeBrowser()

        result = (
            connector
            .read_call_microphone_state()
        )

        self.assertEqual(
            result[
                "state"
            ],
            whatsapp_connector
            .WHATSAPP_CALL_MIC_STATE_UNKNOWN,
        )

        self.assertFalse(
            result[
                "click_required"
            ]
        )


    def test_ensure_microphone_enabled_is_idempotent(
        self,
    ):
        class FakeBrowser:
            find_calls = 0

            def evaluate(
                self,
                expression,
            ):
                return {
                    "call_present": True,
                    "mute": {
                        "testid": "mic-mute",
                        "aria_label":
                            "Silenciar micrófono",
                        "disabled": False,
                        "aria_disabled":
                            "false",
                    },
                    "unmute": None,
                    "split": {
                        "testid":
                            "mic-split-button",
                        "aria_label":
                            "Silenciar micrófono",
                        "disabled": False,
                        "aria_disabled":
                            "",
                    },
                }

            def find_element(
                self,
                selector,
            ):
                self.find_calls += 1

                raise AssertionError(
                    "No debe buscar control "
                    "si el micro ya está activo"
                )

        browser = FakeBrowser()

        connector = (
            whatsapp_connector
            .WhatsAppConnector()
        )

        connector.browser = browser

        result = (
            connector
            .ensure_call_microphone_enabled()
        )

        self.assertTrue(
            result[
                "ready"
            ]
        )

        self.assertFalse(
            result[
                "changed"
            ]
        )

        self.assertEqual(
            result[
                "reason"
            ],
            "MICROPHONE_ALREADY_ENABLED",
        )

        self.assertEqual(
            browser.find_calls,
            0,
        )


    def test_ensure_microphone_enabled_clicks_unmute_once_and_verifies(
        self,
    ):
        class FakeElement:
            def __init__(
                self,
            ):
                self.mouse_click_calls = 0

            def mouse_click(
                self,
            ):
                self.mouse_click_calls += 1

        class FakeBrowser:
            def __init__(
                self,
            ):
                self.read_count = 0
                self.find_selectors = []
                self.element = FakeElement()

            def evaluate(
                self,
                expression,
            ):
                self.read_count += 1

                if self.read_count == 1:
                    return {
                        "call_present": True,
                        "mute": None,
                        "unmute": {
                            "testid":
                                "mic-unmute",
                            "aria_label":
                                "Desactivar silencio del micrófono",
                            "disabled":
                                False,
                            "aria_disabled":
                                "false",
                        },
                        "split": {
                            "testid":
                                "mic-split-button",
                            "aria_label":
                                "Desactivar silencio del micrófono",
                            "disabled":
                                False,
                            "aria_disabled":
                                "",
                        },
                    }

                return {
                    "call_present": True,
                    "mute": {
                        "testid":
                            "mic-mute",
                        "aria_label":
                            "Silenciar micrófono",
                        "disabled":
                            False,
                        "aria_disabled":
                            "false",
                    },
                    "unmute": None,
                    "split": {
                        "testid":
                            "mic-split-button",
                        "aria_label":
                            "Silenciar micrófono",
                        "disabled":
                            False,
                        "aria_disabled":
                            "",
                    },
                }

            def find_element(
                self,
                selector,
            ):
                self.find_selectors.append(
                    selector
                )

                return self.element

        browser = FakeBrowser()

        connector = (
            whatsapp_connector
            .WhatsAppConnector()
        )

        connector.browser = browser

        result = (
            connector
            .ensure_call_microphone_enabled(
                verify_timeout=0.1,
                poll_interval=0.01,
            )
        )

        self.assertTrue(
            result[
                "ready"
            ]
        )

        self.assertTrue(
            result[
                "changed"
            ]
        )

        self.assertEqual(
            result[
                "reason"
            ],
            "MICROPHONE_ENABLED",
        )

        self.assertEqual(
            result[
                "initial_state"
            ],
            whatsapp_connector
            .WHATSAPP_CALL_MIC_STATE_MUTED,
        )

        self.assertEqual(
            result[
                "final_state"
            ],
            whatsapp_connector
            .WHATSAPP_CALL_MIC_STATE_ENABLED,
        )

        self.assertEqual(
            browser.find_selectors,
            [
                whatsapp_connector
                .WHATSAPP_CALL_MIC_UNMUTE_SELECTOR
            ],
        )

        self.assertEqual(
            browser
            .element
            .mouse_click_calls,
            1,
        )


    def test_voice_call_uses_exact_accessible_button_and_clicks_once(
        self,
    ):
        class Snapshot:
            def __init__(
                self,
                *,
                present,
                phase,
                direction,
                provider_call_id=None,
            ):
                self.present = present
                self.phase = phase
                self.direction = direction
                self.provider_call_id = (
                    provider_call_id
                )
                self.external_call_key = None
                self.participant_phone = None

        class FakeElement:
            def __init__(
                self,
            ):
                self.mouse_click_calls = 0

            def mouse_click(
                self,
            ):
                self.mouse_click_calls += 1

        class FakeBrowser:
            def __init__(
                self,
            ):
                self.element = FakeElement()
                self.find_selectors = []

            def evaluate(
                self,
                expression,
            ):
                return {
                    "found": True,
                    "aria_label":
                        "Llamada",
                    "disabled": False,
                    "aria_disabled":
                        "false",
                }

            def find_element(
                self,
                selector,
            ):
                self.find_selectors.append(
                    selector
                )

                return self.element

        browser = FakeBrowser()

        connector = (
            whatsapp_connector
            .WhatsAppConnector()
        )

        connector.browser = browser

        snapshots = iter(
            [
                Snapshot(
                    present=False,
                    phase=(
                        whatsapp_connector
                        .WHATSAPP_CALL_PHASE_ABSENT
                    ),
                    direction=(
                        whatsapp_connector
                        .WHATSAPP_CALL_DIRECTION_UNKNOWN
                    ),
                ),
                Snapshot(
                    present=True,
                    phase=(
                        whatsapp_connector
                        .WHATSAPP_CALL_PHASE_CONNECTING
                    ),
                    direction=(
                        whatsapp_connector
                        .WHATSAPP_CALL_DIRECTION_UNKNOWN
                    ),
                ),
            ]
        )

        connector.read_call_snapshot = (
            lambda:
                next(
                    snapshots
                )
        )

        result = (
            connector
            .start_voice_call(
                confirm_timeout=0.1,
                poll_interval=0.01,
            )
        )

        self.assertTrue(
            result[
                "ok"
            ]
        )

        self.assertFalse(
            result[
                "uncertain"
            ]
        )

        self.assertTrue(
            result[
                "clicked"
            ]
        )

        self.assertEqual(
            result[
                "reason"
            ],
            "VOICE_CALL_SURFACE_STARTED",
        )

        self.assertEqual(
            browser.find_selectors,
            [
                whatsapp_connector
                .WHATSAPP_VOICE_CALL_BUTTON_SELECTOR
            ],
        )

        self.assertEqual(
            browser
            .element
            .mouse_click_calls,
            1,
        )


    def test_voice_call_does_not_click_when_call_already_present(
        self,
    ):
        class Snapshot:
            present = True
            phase = (
                whatsapp_connector
                .WHATSAPP_CALL_PHASE_ACTIVE
            )
            direction = (
                whatsapp_connector
                .WHATSAPP_CALL_DIRECTION_OUTBOUND
            )
            provider_call_id = "CALL-EXISTING"
            external_call_key = None
            participant_phone = None

        class FakeBrowser:
            def evaluate(
                self,
                expression,
            ):
                raise AssertionError(
                    "No debe buscar botón con "
                    "una llamada ya presente"
                )

            def find_element(
                self,
                selector,
            ):
                raise AssertionError(
                    "No debe hacer click con "
                    "una llamada ya presente"
                )

        connector = (
            whatsapp_connector
            .WhatsAppConnector()
        )

        connector.browser = FakeBrowser()

        connector.read_call_snapshot = (
            lambda:
                Snapshot()
        )

        result = (
            connector
            .start_voice_call()
        )

        self.assertFalse(
            result[
                "ok"
            ]
        )

        self.assertFalse(
            result[
                "uncertain"
            ]
        )

        self.assertFalse(
            result[
                "clicked"
            ]
        )

        self.assertEqual(
            result[
                "reason"
            ],
            "CALL_ALREADY_PRESENT",
        )


    def test_voice_call_never_retries_unconfirmed_click(
        self,
    ):
        class Snapshot:
            present = False
            phase = (
                whatsapp_connector
                .WHATSAPP_CALL_PHASE_ABSENT
            )
            direction = (
                whatsapp_connector
                .WHATSAPP_CALL_DIRECTION_UNKNOWN
            )
            provider_call_id = None
            external_call_key = None
            participant_phone = None

        class FakeElement:
            def __init__(
                self,
            ):
                self.mouse_click_calls = 0

            def mouse_click(
                self,
            ):
                self.mouse_click_calls += 1

        class FakeBrowser:
            def __init__(
                self,
            ):
                self.element = FakeElement()

            def evaluate(
                self,
                expression,
            ):
                return {
                    "found": True,
                    "aria_label":
                        "Llamada",
                    "disabled": False,
                    "aria_disabled":
                        "false",
                }

            def find_element(
                self,
                selector,
            ):
                return self.element

        browser = FakeBrowser()

        connector = (
            whatsapp_connector
            .WhatsAppConnector()
        )

        connector.browser = browser

        connector.read_call_snapshot = (
            lambda:
                Snapshot()
        )

        result = (
            connector
            .start_voice_call(
                confirm_timeout=0.02,
                poll_interval=0.01,
            )
        )

        self.assertFalse(
            result[
                "ok"
            ]
        )

        self.assertTrue(
            result[
                "uncertain"
            ]
        )

        self.assertTrue(
            result[
                "clicked"
            ]
        )

        self.assertEqual(
            result[
                "reason"
            ],
            "VOICE_CALL_START_UNCONFIRMED",
        )

        self.assertEqual(
            browser
            .element
            .mouse_click_calls,
            1,
        )


    def test_close_delegates_to_governed_session(
        self,
    ):
        class FakeGovernedSession:
            instances = []

            def __init__(
                self,
                *,
                config,
                profile_resolver,
            ):
                self.config = config
                self.profile_resolver = (
                    profile_resolver
                )

                self.browser = object()
                self.shutdown_modes = []

                self.__class__.instances.append(
                    self
                )

            def start(
                self,
            ):
                return self.browser

            def shutdown(
                self,
                mode,
            ):
                self.shutdown_modes.append(
                    mode
                )

                return SimpleNamespace(
                    has_error=False,
                    control_released=True,
                    browser_closed=True,
                )

        with patch.object(
            whatsapp_connector,
            "open_url",
        ):
            connector = (
                whatsapp_connector
                .WhatsAppConnector(
                    browser_session_factory=(
                        FakeGovernedSession
                    )
                )
            )

            connector.start()

        session = (
            FakeGovernedSession.instances[0]
        )

        result = connector.close()

        self.assertTrue(
            result
        )

        self.assertEqual(
            len(
                session.shutdown_modes
            ),
            1,
        )

        self.assertEqual(
            session.shutdown_modes[0].value,
            "CLOSE",
        )

        self.assertIsNone(
            connector.browser
        )

        self.assertIsNone(
            connector._browser_session
        )

    def test_close_never_stops_unmanaged_browser(
        self,
    ):
        connector = (
            whatsapp_connector
            .WhatsAppConnector()
        )

        class FakeDriver:
            def __init__(
                self,
            ):
                self.stopped = False

            def stop(
                self,
            ):
                self.stopped = True

                raise AssertionError(
                    "driver.stop() no debe ejecutarse"
                )

        class FakeChrome:
            def __init__(
                self,
            ):
                self.driver = FakeDriver()

        fake_browser = FakeChrome()

        connector.browser = (
            fake_browser
        )

        result = connector.close()

        self.assertFalse(
            result
        )

        self.assertFalse(
            fake_browser.driver.stopped
        )

        self.assertIs(
            connector.browser,
            fake_browser,
        )

    def test_connector_has_no_direct_browser_factory_dependency(
        self,
    ):
        source_path = (
            Path(
                whatsapp_connector.__file__
            )
            .resolve()
        )

        tree = ast.parse(
            source_path.read_text(
                encoding="utf-8",
            )
        )

        imported_names = []

        for node in ast.walk(
            tree
        ):
            if isinstance(
                node,
                ast.ImportFrom,
            ):
                imported_names.extend(
                    alias.name
                    for alias in node.names
                )

            elif isinstance(
                node,
                ast.Import,
            ):
                imported_names.extend(
                    alias.name
                    for alias in node.names
                )

        self.assertNotIn(
            "start_seleniumbase_chrome",
            imported_names,
        )

    def test_profile_directory_is_local_runtime(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            fake_root = Path(temp)

            with patch(
                "backend.automation.connectors."
                "whatsapp_connector."
                "get_project_root",
                return_value=fake_root,
            ):
                profile = (
                    whatsapp_connector
                    .get_whatsapp_profile_dir(
                        "whatsapp_dev"
                    )
                )

            self.assertEqual(
                profile,
                fake_root
                / "data"
                / "browser_profiles"
                / "whatsapp_dev",
            )

            self.assertTrue(
                profile.exists()
            )


if __name__ == "__main__":
    unittest.main()
