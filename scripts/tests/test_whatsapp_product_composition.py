from pathlib import Path
import unittest


APP_MAIN_PATH = Path(
    "app/main.py"
)

VIEW_PATH = Path(
    "frontend/views/communications_view.py"
)


class WhatsAppProductCompositionTest(
    unittest.TestCase
):
    @classmethod
    def setUpClass(
        cls,
    ):
        cls.app_source = (
            APP_MAIN_PATH.read_text(
                encoding="utf-8"
            )
        )

        cls.view_source = (
            VIEW_PATH.read_text(
                encoding="utf-8"
            )
        )

    def test_product_root_builds_shared_communication_repository(
        self,
    ):
        self.assertIn(
            "communication_repository = (",
            self.app_source,
        )

        self.assertIn(
            "SQLiteCommunicationRepository()",
            self.app_source,
        )

    def test_message_and_call_services_share_repository(
        self,
    ):
        self.assertIn(
            """CommunicationService(
            repository=(
                communication_repository
            )""",
            self.app_source,
        )

        self.assertIn(
            """CommunicationCallService(
            repository=(
                communication_repository
            )""",
            self.app_source,
        )

    def test_runtime_receives_both_application_services(
        self,
    ):
        self.assertIn(
            """WhatsAppRuntimeService(
        communication_service=(
            communication_service
        ),
        call_service=(
            communication_call_service
        ),""",
            self.app_source,
        )

    def test_communications_view_receives_same_message_service(
        self,
    ):
        self.assertIn(
            """content = communications_view(
                page,
                service=(
                    communication_service
                ),
                whatsapp_runtime=(
                    whatsapp_runtime
                ),""",
            self.app_source,
        )

    def test_call_watch_starts_only_after_successful_login(
        self,
    ):
        login_pos = self.app_source.index(
            "def on_login_success(user):"
        )

        watch_start_pos = self.app_source.index(
            "start_whatsapp_session_services()",
            login_pos,
        )

        initial_start_pos = self.app_source.index(
            "def start():"
        )

        self.assertGreater(
            watch_start_pos,
            login_pos,
        )

        # La pantalla de login no arranca WhatsApp.
        initial_start_block = (
            self.app_source[
                initial_start_pos:
            ]
        )

        initial_start_block = (
            initial_start_block.split(
                "page.add(main_container)",
                1,
            )[0]
        )

        self.assertNotIn(
            "start_whatsapp_session_services()",
            initial_start_block,
        )


    def test_authenticated_ui_is_rendered_before_call_watch_start(
        self,
    ):
        start = self.app_source.index(
            "def on_login_success(user):"
        )

        end = self.app_source.index(
            "    def start():",
            start,
        )

        login_block = (
            self.app_source[
                start:end
            ]
        )

        self.assertLess(
            login_block.index(
                'navigate("Clientes")'
            ),
            login_block.index(
                "start_whatsapp_session_services()"
            ),
        )


    def test_process_exit_closes_whatsapp_runtime(
        self,
    ):
        self.assertIn(
            "atexit.register(",
            self.app_source,
        )

        self.assertIn(
            "close_whatsapp_session_services",
            self.app_source,
        )

        self.assertIn(
            "whatsapp_runtime.close()",
            self.app_source,
        )


    def test_frontend_still_does_not_import_sqlite_repository(
        self,
    ):
        self.assertNotIn(
            "SQLiteCommunicationRepository",
            self.view_source,
        )

        self.assertNotIn(
            "sqlite3",
            self.view_source,
        )


if __name__ == "__main__":
    unittest.main()
