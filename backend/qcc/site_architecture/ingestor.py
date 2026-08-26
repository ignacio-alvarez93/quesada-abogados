"""Ingestión local de capturas Site Architecture procedentes de QCC."""

from __future__ import annotations

import json
import shutil
from datetime import (
    datetime,
    timezone,
)
from pathlib import Path
from uuid import uuid4

from backend.automation.site_architecture import (
    persist_site_architecture_from_qcc_capture,
)
from backend.automation.site_architecture.site_target import (
    SiteTarget,
    SiteTargetMode,
)


DEFAULT_QCC_SITE_ARCHITECTURE_ROOT = (
    Path("data")
    / "qcc"
    / "site_architecture"
)


class QccSiteArchitectureIngestor:
    def __init__(
        self,
        *,
        output_root=DEFAULT_QCC_SITE_ARCHITECTURE_ROOT,
    ):
        self._output_root = Path(
            output_root
        )

    @staticmethod
    def _context_info(
        context,
    ):
        if not isinstance(context, dict):
            context = {}

        active_session = (
            context.get("active_session")
            if context.get("active")
            else None
        )

        if not isinstance(
            active_session,
            dict,
        ):
            active_session = None

        session_id = (
            str(
                active_session.get(
                    "session_id"
                )
                or ""
            ).strip()
            if active_session
            else ""
        )

        return {
            "context_mode": (
                "ASSISTED_PRESENTATION"
                if session_id
                else "MANUAL"
            ),
            "session_id": (
                session_id
                or None
            ),
            "active_session":
                active_session,
        }

    def ingest(
        self,
        capture,
        *,
        context=None,
    ):
        received_at = datetime.now(
            timezone.utc
        )

        capture_id = (
            received_at.strftime(
                "%Y%m%d_%H%M%S_%f"
            )
            + "_"
            + uuid4().hex[:8]
        )

        capture_dir = (
            self._output_root
            / capture_id
        )

        capture_dir.mkdir(
            parents=True,
            exist_ok=False,
        )

        raw_path = (
            capture_dir
            / "qcc_capture.json"
        )

        try:
            raw_path.write_text(
                json.dumps(
                    capture,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            normalized = (
                persist_site_architecture_from_qcc_capture(
                    capture,
                    capture_dir,
                )
            )

            snapshot = normalized[
                "snapshot"
            ]

            # La inspección DOM es siempre pasiva,
            # incluso cuando existe una presentación
            # asistida activa en la misma pestaña.
            site_target = SiteTarget(
                url=snapshot.page.url,
                mode=(
                    SiteTargetMode
                    .PASSIVE_INSPECTION
                ),
            )

        except Exception:
            shutil.rmtree(
                capture_dir,
                ignore_errors=True,
            )
            raise

        context_info = (
            self._context_info(
                context
            )
        )

        metadata = {
            "capture_id":
                capture_id,
            "source":
                "QCC_EXTENSION",
            "received_at":
                received_at.isoformat(),
            "captured_at":
                capture.get(
                    "captured_at"
                ),
            **context_info,
            "target_mode":
                site_target.mode.value,
            "site_target":
                site_target.to_public_dict(),
            "page": {
                "url":
                    snapshot.page.url,
                "title":
                    snapshot.page.title,
            },
            "counts":
                dict(
                    snapshot.counts
                ),
            "artifacts": {
                "raw_capture":
                    "qcc_capture.json",
                "site_architecture":
                    "site_architecture.json",
                "metadata":
                    "metadata.json",
            },
        }

        (
            capture_dir
            / "metadata.json"
        ).write_text(
            json.dumps(
                metadata,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return metadata
