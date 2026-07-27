import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.services import (
    expedient_traceability_service
    as trace_service,
)


class DenialAdminTransitionTest(unittest.TestCase):
    def test_denial_code_has_target_state(self):
        self.assertEqual(
            trace_service
            .ADMIN_DOCUMENT_BASE_STATE_TRANSITIONS
            .get("RESOLUCION_DENEGATORIA"),
            "RESUELTO DENEGADO",
        )

        self.assertEqual(
            trace_service
            .ADMIN_DOCUMENT_STATE_TRANSITIONS_BY_WORKFLOW[
                "EXTRANJERIA"
            ].get("RESOLUCION_DENEGATORIA"),
            "RESUELTO DENEGADO",
        )

    def test_denial_label(self):
        self.assertEqual(
            trace_service.ADMIN_DOCUMENT_EVENT_LABELS.get(
                "RESOLUCION_DENEGATORIA"
            ),
            "Resolución denegatoria",
        )


if __name__ == "__main__":
    unittest.main()
