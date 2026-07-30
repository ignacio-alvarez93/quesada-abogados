import unittest
from unittest.mock import patch

import flet as ft

from frontend.components import (
    dehu_inbox_panel,
)


class FakePage:
    def __init__(self):
        self.overlay = []
        self.launched_urls = []
        self.update_count = 0

    def update(self):
        self.update_count += 1

    def launch_url(self, url):
        self.launched_urls.append(url)


class DehuInboxPanelTest(
    unittest.TestCase
):
    def test_builds_panel(self):
        page = FakePage()

        with patch.object(
            dehu_inbox_panel.dehu_inbox_service,
            "get_summary",
            return_value={
                "total": 1,
                "notifications": 1,
                "communications": 0,
                "linked": 0,
                "upcoming_7_days": 1,
                "portal_detected": 0,
            },
        ), patch.object(
            dehu_inbox_panel.dehu_inbox_service,
            "list_items",
            return_value={
                "items": [
                    {
                        "id": 1,
                        "item_type": "NOTIFICATION",
                        "family_hint": "EXTRANJERIA",
                        "reference_value":
                            "330020260000001",
                        "detection_origin":
                            "EMAIL_ONLY",
                        "verification_status":
                            "EXPEDIENT_NOT_FOUND",
                        "portal_status": "UNKNOWN",
                        "issuer_name":
                            "Oficina de Extranjería",
                        "recipient_name":
                            "CLIENTE PRUEBA",
                        "concept":
                            "Nueva notificación",
                        "deadline_at":
                            "2026-08-01 23:59:59",
                        "last_seen_at":
                            "2026-07-29 12:00:00",
                        "source_count": 1,
                        "direct_access_url":
                            "https://dehu.redsara.es/",
                        "expediente_id": None,
                    }
                ],
                "total": 1,
                "page": 1,
                "page_size": 10,
                "total_pages": 1,
            },
        ):
            control = (
                dehu_inbox_panel
                .build_dehu_inbox_panel(
                    page,
                )
            )

        self.assertIsInstance(
            control,
            ft.Container,
        )
        self.assertIsNotNone(
            control.content
        )


if __name__ == "__main__":
    unittest.main()
