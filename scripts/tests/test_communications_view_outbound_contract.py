from pathlib import Path
import re
import unittest


ROOT = (
    Path(__file__).resolve()
    .parents[2]
)

VIEW = (
    ROOT
    / "frontend"
    / "views"
    / "communications_view.py"
)

APP = (
    ROOT
    / "app"
    / "main.py"
)


class CommunicationsViewOutboundContractTest(
    unittest.TestCase
):
    @classmethod
    def setUpClass(
        cls,
    ):
        cls.view_text = VIEW.read_text(
            encoding="utf-8"
        )

        cls.app_text = APP.read_text(
            encoding="utf-8"
        )

    def test_view_accepts_runtime_and_username(
        self,
    ):
        self.assertIn(
            "whatsapp_runtime=None,",
            self.view_text,
        )

        self.assertIn(
            "current_username=None,",
            self.view_text,
        )

    def test_app_injects_runtime_and_username(
        self,
    ):
        self.assertIn(
            "whatsapp_runtime=(",
            self.app_text,
        )

        self.assertIn(
            "current_username=(",
            self.app_text,
        )

    def test_view_sends_only_through_runtime(
        self,
    ):
        self.assertIn(
            "whatsapp_runtime",
            self.view_text,
        )

        self.assertIn(
            ".send_text_message(",
            self.view_text,
        )

        self.assertNotIn(
            "WhatsAppConnector(",
            self.view_text,
        )

    def test_double_send_guard_exists(
        self,
    ):
        self.assertIn(
            '"sending": False',
            self.view_text,
        )

        self.assertRegex(
            self.view_text,
            (
                r'if\s+state\.get\(\s*'
                r'"sending"\s*'
                r'\)\s*:\s*'
                r'return'
            ),
        )

        self.assertIn(
            'state["sending"] = True',
            self.view_text,
        )

    def test_uncertain_send_is_blocked(
        self,
    ):
        self.assertIn(
            '"send_blocked_thread_ids": set()',
            self.view_text,
        )

        self.assertIn(
            "if uncertain:",
            self.view_text,
        )

        self.assertIn(
            "No reenvíes este mensaje",
            self.view_text,
        )

    def test_draft_is_cleared_on_thread_change(
        self,
    ):
        self.assertIn(
            "previous_thread_id",
            self.view_text,
        )

        self.assertIn(
            "_clear_composer()",
            self.view_text,
        )


    def test_view_can_open_persistent_whatsapp_runtime(
        self,
    ):
        self.assertIn(
            'def open_whatsapp(',
            self.view_text,
        )

        self.assertIn(
            '"Abrir WhatsApp"',
            self.view_text,
        )

        self.assertIn(
            'whatsapp_runtime.start()',
            self.view_text,
        )

        self.assertIn(
            'whatsapp_runtime.started',
            self.view_text,
        )

        self.assertIn(
            '"run_thread"',
            self.view_text,
        )


    def test_composer_refreshes_after_initial_thread_load(
        self,
    ):
        self.assertIn(
            "_refresh_composer_controls()",
            self.view_text,
        )

        initial_load_marker = (
            "load_data(\n"
            "        preserve_selection=True,\n"
            "    )\n\n"
            "    _refresh_composer_controls()"
        )

        self.assertIn(
            initial_load_marker,
            self.view_text,
        )


    def test_selecting_thread_routes_persistent_whatsapp(
        self,
    ):
        self.assertIn(
            "def _route_whatsapp_thread(",
            self.view_text,
        )

        self.assertIn(
            "open_thread_for_selection(",
            self.view_text,
        )

        self.assertIn(
            "_route_whatsapp_thread(\n"
            "                    new_thread_id",
            self.view_text,
        )

        self.assertNotIn(
            "and whatsapp_runtime.started",
            self.view_text,
        )

        self.assertIn(
            "if whatsapp_runtime is not None:",
            self.view_text,
        )

        self.assertIn(
            "if not whatsapp_runtime.started:",
            self.view_text,
        )

        self.assertIn(
            "whatsapp_runtime.start()",
            self.view_text,
        )


    def test_open_whatsapp_does_not_route_implicitly(
        self,
    ):
        start = self.view_text.index(
            "    def open_whatsapp("
        )

        end = self.view_text.index(
            "\n    def ",
            start + 10,
        )

        block = self.view_text[
            start:end
        ]

        self.assertNotIn(
            "verify_and_open_thread(",
            block,
        )

        self.assertIn(
            "Selecciona una conversación ",
            block,
        )


class CommunicationsViewEmptyToFirstContractTests(
    unittest.TestCase
):
    def test_empty_to_first_message_remounts_only_central_host(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        start = source.index(
            '            previous_messages = list('
        )

        end = source.index(
            '            sidebar_refreshed = (',
            start,
        )

        block = source[
            start:
            end
        ]

        self.assertIn(
            "empty_to_first_message = (",
            block,
        )

        self.assertIn(
            "created_count > 0",
            block,
        )

        self.assertIn(
            "and not previous_messages",
            block,
        )

        self.assertIn(
            "_refresh_chat_panel_control()",
            block,
        )

        empty_branch_start = block.index(
            "if empty_to_first_message:"
        )

        incremental_start = block.index(
            "elif incremental_candidate:"
        )

        empty_branch = block[
            empty_branch_start:
            incremental_start
        ]

        # La transición 0 -> 1 nunca debe intentar actualizar
        # directamente el Column todavía desmontado.
        self.assertNotIn(
            "_refresh_message_history_control()",
            empty_branch,
        )

        self.assertNotIn(
            "_append_new_message_history_controls(",
            empty_branch,
        )

        # Tampoco debe reconstruir toda Comunicaciones.
        self.assertNotIn(
            "_safe_update()",
            empty_branch,
        )

        # El host central se monta antes de los caminos
        # incrementales ordinarios.
        self.assertLess(
            empty_branch_start,
            incremental_start,
        )


class CommunicationsViewHistoryTopLoadArmingTests(
    unittest.TestCase
):
    def test_initial_top_event_requires_prior_arming(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            '"message_history_top_load_armed": False',
            source,
        )

        start = source.index(
            "    async def _on_message_history_scroll("
        )

        end = source.index(
            "\n    message_history_control.on_scroll",
            start,
        )

        block = source[
            start:
            end
        ]

        self.assertIn(
            "if at_bottom:",
            block,
        )

        self.assertIn(
            "if extent_before > 40.0:",
            block,
        )

        self.assertIn(
            '"message_history_top_load_armed",',
            block,
        )

        top_reached_pos = block.index(
            "await _load_older_message_history()"
        )

        armed_check_pos = block.index(
            'or not state.get(\n'
            '                "message_history_top_load_armed",'
        )

        self.assertLess(
            armed_check_pos,
            top_reached_pos,
        )

    def test_history_prepend_consumes_arm(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        start = source.index(
            "    async def _load_older_message_history("
        )

        end = source.index(
            "\n    async def _on_message_history_scroll(",
            start,
        )

        block = source[
            start:
            end
        ]

        self.assertIn(
            "El permiso se consume antes del prepend",
            block,
        )

        marker = block.index(
            '"message_history_top_load_armed"'
        )

        self.assertIn(
            "] = False",
            block[
                marker:
                marker + 180
            ],
        )

    def test_programmatic_scroll_guard_is_preserved(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        load_start = source.index(
            "    async def _load_older_message_history("
        )

        scroll_start = source.index(
            "\n    async def _on_message_history_scroll(",
            load_start,
        )

        scroll_end = source.index(
            "\n    message_history_control.on_scroll",
            scroll_start,
        )

        load_block = source[
            load_start:
            scroll_start
        ]

        scroll_block = source[
            scroll_start:
            scroll_end
        ]

        # V9 mantiene la protección programática tanto para
        # el fallback excepcional por scroll_key como para la
        # restauración geométrica diferida por offset.
        self.assertIn(
            '"message_history_programmatic_scroll"',
            load_block,
        )

        self.assertIn(
            '"message_history_programmatic_scroll"',
            scroll_block,
        )

        self.assertIn(
            "scroll_key=anchor_key",
            load_block,
        )

        self.assertIn(
            "offset=preserved_offset",
            scroll_block,
        )

        # El fallback excepcional por scroll_key conserva
        # temporalmente la espera de 120 ms.
        self.assertIn(
            "await asyncio.sleep(",
            load_block,
        )

        self.assertIn(
            "0.12",
            load_block,
        )

        # El camino geométrico principal ya no necesita una
        # espera artificial: la restauración se dispara solo
        # después de recibir la geometría real post-prepend.
        self.assertNotIn(
            "await asyncio.sleep(",
            scroll_block,
        )


class CommunicationsViewHistoryInitializationGateTests(
    unittest.TestCase
):
    def test_history_cannot_arm_before_bottom_initialization(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            '"message_history_scroll_initialized": False',
            source,
        )

        start = source.index(
            "    async def _on_message_history_scroll("
        )

        end = source.index(
            "\n    message_history_control.on_scroll",
            start,
        )

        block = source[
            start:
            end
        ]

        init_guard = block.index(
            'if not state.get(\n'
            '            "message_history_scroll_initialized",'
        )

        arm_guard = block.index(
            "if extent_before > 40.0:"
        )

        self.assertLess(
            init_guard,
            arm_guard,
        )

    def test_thread_change_resets_history_initialization(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        start = source.index(
            "        if (\n"
            "            previous_thread_id\n"
            "            != new_thread_id"
        )

        end = source.index(
            "        load_thread_messages()",
            start,
        )

        block = source[
            start:
            end
        ]

        self.assertIn(
            '"message_history_scroll_initialized"',
            block,
        )

        marker = block.index(
            '"message_history_scroll_initialized"'
        )

        self.assertIn(
            "] = False",
            block[
                marker:
                marker + 150
            ],
        )


class CommunicationsViewHistoryPostPrependRearmTests(
    unittest.TestCase
):
    def test_prepend_requires_separate_rearm_phase(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            '"message_history_top_rearm_required": False',
            source,
        )

        load_start = source.index(
            "    async def _load_older_message_history("
        )

        load_end = source.index(
            "\n    async def _on_message_history_scroll(",
            load_start,
        )

        load_block = source[
            load_start:
            load_end
        ]

        self.assertIn(
            '"message_history_top_rearm_required"',
            load_block,
        )

        marker = load_block.index(
            '"message_history_top_rearm_required"'
        )

        self.assertIn(
            "] = True",
            load_block[
                marker:
                marker + 180
            ],
        )

    def test_post_prepend_residual_scroll_cannot_arm(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        start = source.index(
            "    async def _on_message_history_scroll("
        )

        end = source.index(
            "\n    message_history_control.on_scroll",
            start,
        )

        block = source[
            start:
            end
        ]

        self.assertIn(
            "if extent_before > 300.0:",
            block,
        )

        rearm_pos = block.index(
            'if state.get(\n'
            '            "message_history_top_rearm_required",'
        )

        arm_pos = block.index(
            "if extent_before > 40.0:"
        )

        self.assertLess(
            rearm_pos,
            arm_pos,
        )

        # El bloque de rearme debe terminar con return,
        # por lo que el mismo evento nunca puede armar.
        rearm_block = block[
            rearm_pos:
            arm_pos
        ]

        self.assertIn(
            "\n            return\n",
            rearm_block,
        )

    def test_bottom_clears_post_prepend_rearm_requirement(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        start = source.index(
            "    async def _on_message_history_scroll("
        )

        end = source.index(
            "\n    message_history_control.on_scroll",
            start,
        )

        block = source[
            start:
            end
        ]

        bottom_start = block.index(
            "if at_bottom:"
        )

        preinit_start = block.index(
            "# Antes de haber confirmado el fondo",
            bottom_start,
        )

        bottom_block = block[
            bottom_start:
            preinit_start
        ]

        self.assertIn(
            '"message_history_top_rearm_required"',
            bottom_block,
        )

        marker = bottom_block.index(
            '"message_history_top_rearm_required"'
        )

        self.assertIn(
            "] = False",
            bottom_block[
                marker:
                marker + 160
            ],
        )


class CommunicationsViewHistoryLoadingGuardTests(
    unittest.TestCase
):
    def test_loading_older_blocks_scroll_before_rearm_or_arm(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        start = source.index(
            "    async def _on_message_history_scroll("
        )

        end = source.index(
            "\n    message_history_control.on_scroll",
            start,
        )

        block = source[
            start:
            end
        ]

        loading_guard = block.index(
            'if state.get(\n'
            '            "message_history_loading_older"'
        )

        rearm_guard = block.index(
            'if state.get(\n'
            '            "message_history_top_rearm_required",'
        )

        arm_guard = block.index(
            "if extent_before > 40.0:"
        )

        self.assertLess(
            loading_guard,
            rearm_guard,
        )

        self.assertLess(
            loading_guard,
            arm_guard,
        )

        loading_block = block[
            loading_guard:
            rearm_guard
        ]

        self.assertIn(
            "\n            return\n",
            loading_block,
        )


class CommunicationsViewHistoryUserScrollGateTests(
    unittest.TestCase
):
    def test_user_scroll_signal_is_required_before_pagination(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            '"message_history_user_scroll_active": False',
            source,
        )

        start = source.index(
            "    async def _on_message_history_scroll("
        )

        end = source.index(
            "\n    message_history_control.on_scroll",
            start,
        )

        block = source[
            start:
            end
        ]

        self.assertIn(
            "event_type == ft.ScrollType.USER",
            block,
        )

        self.assertIn(
            "direction == ft.ScrollDirection.IDLE",
            block,
        )

        self.assertIn(
            '"message_history_user_scroll_active",',
            block,
        )

        human_gate = block.index(
            'if not state.get(\n'
            '            "message_history_user_scroll_active",'
        )

        rearm_gate = block.index(
            'if state.get(\n'
            '            "message_history_top_rearm_required",'
        )

        arm_gate = block.index(
            "if extent_before > 40.0:"
        )

        self.assertLess(
            human_gate,
            rearm_gate,
        )

        self.assertLess(
            human_gate,
            arm_gate,
        )

    def test_prepend_consumes_current_user_scroll_intent(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        start = source.index(
            "    async def _load_older_message_history("
        )

        end = source.index(
            "\n    async def _on_message_history_scroll(",
            start,
        )

        block = source[
            start:
            end
        ]

        self.assertIn(
            "Ningún UPDATE tardío del prepend",
            block,
        )

        marker = block.index(
            '"message_history_user_scroll_active"'
        )

        self.assertIn(
            "] = False",
            block[
                marker:
                marker + 180
            ],
        )

    def test_user_idle_clears_scroll_intent(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        start = source.index(
            "    async def _on_message_history_scroll("
        )

        end = source.index(
            "\n    message_history_control.on_scroll",
            start,
        )

        block = source[
            start:
            end
        ]

        self.assertIn(
            "ft.ScrollDirection.IDLE",
            block,
        )


class CommunicationsViewHistoryExactViewportTests(
    unittest.TestCase
):
    def test_scroll_geometry_is_recorded_before_guards(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        start = source.index(
            "    async def _on_message_history_scroll("
        )

        end = source.index(
            "\n    message_history_control.on_scroll",
            start,
        )

        block = source[
            start:
            end
        ]

        self.assertIn(
            '"message_history_last_scroll_pixels"',
            block,
        )

        self.assertIn(
            '"message_history_last_max_scroll_extent"',
            block,
        )

        geometry_pos = block.index(
            '"message_history_last_scroll_pixels"'
        )

        loading_guard = block.index(
            'if state.get(\n'
            '            "message_history_loading_older"'
        )

        self.assertLess(
            geometry_pos,
            loading_guard,
        )

    def test_prepend_registers_pending_viewport_preservation(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        start = source.index(
            "    async def _load_older_message_history("
        )

        end = source.index(
            "\n    async def _on_message_history_scroll(",
            start,
        )

        block = source[
            start:
            end
        ]

        self.assertIn(
            "previous_scroll_pixels",
            block,
        )

        self.assertIn(
            "previous_max_scroll_extent",
            block,
        )

        self.assertIn(
            '"message_history_pending_viewport_preserve"',
            block,
        )

    def test_scroll_key_remains_exceptional_fallback(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        start = source.index(
            "    async def _load_older_message_history("
        )

        end = source.index(
            "\n    async def _on_message_history_scroll(",
            start,
        )

        block = source[
            start:
            end
        ]

        self.assertIn(
            "PREVIOUS_GEOMETRY_MISSING",
            block,
        )

        self.assertIn(
            "scroll_key=anchor_key",
            block,
        )




class CommunicationsViewHistoryDeferredViewportTests(
    unittest.TestCase
):
    def test_prepend_does_not_wait_for_layout_event(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        start = source.index(
            "    async def _load_older_message_history("
        )

        end = source.index(
            "\n    async def _on_message_history_scroll(",
            start,
        )

        block = source[
            start:
            end
        ]

        self.assertNotIn(
            "asyncio.wait_for(",
            block,
        )

        self.assertNotIn(
            "history prepend layout wait timeout",
            block,
        )

        self.assertIn(
            '"message_history_pending_viewport_preserve"',
            block,
        )

    def test_post_layout_event_applies_extent_compensation(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        start = source.index(
            "    async def _on_message_history_scroll("
        )

        end = source.index(
            "\n    message_history_control.on_scroll",
            start,
        )

        block = source[
            start:
            end
        ]

        self.assertIn(
            "pending_preserve = state.get(",
            block,
        )

        self.assertIn(
            "max_scroll_extent",
            block,
        )

        self.assertIn(
            "inserted_extent = max(",
            block,
        )

        self.assertIn(
            "preserved_offset = (",
            block,
        )

        self.assertIn(
            "offset=preserved_offset",
            block,
        )

    def test_pending_preservation_is_consumed_before_scroll_to(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        start = source.index(
            "    async def _on_message_history_scroll("
        )

        end = source.index(
            "\n    message_history_control.on_scroll",
            start,
        )

        block = source[
            start:
            end
        ]

        clear_pos = block.index(
            '"message_history_pending_viewport_preserve"\n'
            '                ] = None'
        )

        scroll_pos = block.index(
            "offset=preserved_offset"
        )

        self.assertLess(
            clear_pos,
            scroll_pos,
        )


class CommunicationsViewHistoryPostCloseCleanupTests(
    unittest.TestCase
):
    def test_user_scroll_activation_state_is_explicit(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        start = source.index(
            "    async def _on_message_history_scroll("
        )

        end = source.index(
            "\n    message_history_control.on_scroll",
            start,
        )

        block = source[
            start:end
        ]

        user_gate_pos = block.index(
            "if event_type == ft.ScrollType.USER:"
        )

        idle_pos = block.index(
            "if direction == ft.ScrollDirection.IDLE:",
            user_gate_pos,
        )

        deactivate_pos = block.index(
            '"message_history_user_scroll_active"\n'
            '                ] = False',
            idle_pos,
        )

        else_pos = block.index(
            "            else:",
            deactivate_pos,
        )

        activate_pos = block.index(
            '"message_history_user_scroll_active"\n'
            '                ] = True',
            else_pos,
        )

        self.assertLess(
            user_gate_pos,
            idle_pos,
        )

        self.assertLess(
            idle_pos,
            deactivate_pos,
        )

        self.assertLess(
            deactivate_pos,
            else_pos,
        )

        self.assertLess(
            else_pos,
            activate_pos,
        )

    def test_geometric_restore_has_no_artificial_sleep(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        start = source.index(
            "    async def _on_message_history_scroll("
        )

        end = source.index(
            "\n    message_history_control.on_scroll",
            start,
        )

        block = source[
            start:
            end
        ]

        restore_start = block.index(
            "offset=preserved_offset"
        )

        restore_end = block.index(
            "\n\n                return",
            restore_start,
        )

        restore_block = block[
            restore_start:
            restore_end
        ]

        self.assertNotIn(
            "asyncio.sleep",
            restore_block,
        )


class CommunicationsViewIndividualStatusBubbleTests(
    unittest.TestCase
):
    def test_status_items_are_read_from_sync_result(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        callback_start = source.index(
            "        if visible_synced_thread:"
        )

        callback_end = source.index(
            "\n        else:",
            callback_start,
        )

        block = source[
            callback_start:
            callback_end
        ]

        self.assertIn(
            "sync_items = list(",
            block,
        )

        sync_items_start = block.index(
            "sync_items = list("
        )

        sync_items_end = block.index(
            "\n\n",
            sync_items_start,
        )

        sync_items_block = block[
            sync_items_start:
            sync_items_end
        ]

        self.assertIn(
            "sync_result.get(",
            sync_items_block,
        )

        # Importante: no usar simplemente
        # assertNotIn("result.get("), porque esa cadena
        # también forma parte de "sync_result.get(".
        self.assertNotIn(
            "\n                result.get(",
            sync_items_block,
        )


    def test_status_controls_are_indexed_by_message_identity(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "message_status_controls = {}",
            source,
        )

        start = source.index(
            "    def _build_message_bubble("
        )

        end = source.index(
            "\n    # Control persistente del historial.",
            start,
        )

        block = source[
            start:
            end
        ]

        self.assertIn(
            "status_control = ft.Text(",
            block,
        )

        self.assertIn(
            "message_status_controls[",
            block,
        )

        self.assertIn(
            "_message_status_identity(",
            block,
        )

    def test_individual_status_helper_requires_advanced_items(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        start = source.index(
            "    def _update_advanced_message_status_controls("
        )

        end = source.index(
            "\n    def _refresh_message_history_control(",
            start,
        )

        block = source[
            start:
            end
        ]

        self.assertIn(
            '"status_advanced"',
            block,
        )

        self.assertIn(
            "if not advanced_items:",
            block,
        )


    def test_status_advanced_has_individual_fast_path(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "def _update_advanced_message_status_controls(",
            source,
        )

        callback_start = source.index(
            "        if visible_synced_thread:"
        )

        callback_end = source.index(
            "\n        else:",
            callback_start,
        )

        block = source[
            callback_start:
            callback_end
        ]

        self.assertIn(
            "status_advanced_count > 0",
            block,
        )

        self.assertIn(
            "created_count == 0",
            block,
        )

        self.assertIn(
            "_update_advanced_message_status_controls(",
            block,
        )

        individual_pos = block.index(
            "_update_advanced_message_status_controls("
        )

        fallback_pos = block.index(
            "_refresh_message_history_control()"
        )

        self.assertLess(
            individual_pos,
            fallback_pos,
        )

    def test_individual_status_path_updates_only_status_control(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        start = source.index(
            "    def _update_advanced_message_status_controls("
        )

        end = source.index(
            "\n    def _refresh_message_history_control(",
            start,
        )

        block = source[
            start:
            end
        ]

        self.assertIn(
            "control.value = symbol",
            block,
        )

        self.assertIn(
            "control.update()",
            block,
        )

        self.assertNotIn(
            "message_history_control.update()",
            block,
        )

        self.assertNotIn(
            "_force_message_history_bottom",
            block,
        )

    def test_rebuilds_reset_status_control_index(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertGreaterEqual(
            source.count(
                "message_status_controls.clear()"
            ),
            2,
        )


class CommunicationsViewMixedStatusDeltaTests(
    unittest.TestCase
):
    def test_created_plus_status_uses_two_partial_updates(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        callback_start = source.index(
            "        if visible_synced_thread:"
        )

        callback_end = source.index(
            "\n        else:",
            callback_start,
        )

        block = source[
            callback_start:
            callback_end
        ]

        self.assertIn(
            "created_count > 0",
            block,
        )

        self.assertIn(
            "status_advanced_count > 0",
            block,
        )

        self.assertIn(
            "appended = (",
            block,
        )

        self.assertIn(
            "status_updated = (",
            block,
        )

        self.assertIn(
            "_append_new_message_history_controls(",
            block,
        )

        self.assertIn(
            "_update_advanced_message_status_controls(",
            block,
        )




class CommunicationsViewWatcherCadenceTests(
    unittest.TestCase
):
    def test_productive_whatsapp_watchers_use_500ms(
        self,
    ):
        from pathlib import Path

        source = Path(
            "frontend/views/communications_view.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertEqual(
            source.count(
                "interval_seconds=0.5,"
            ),
            2,
        )

        self.assertNotIn(
            "interval_seconds=1.0,",
            source,
        )




if __name__ == "__main__":
    unittest.main()
