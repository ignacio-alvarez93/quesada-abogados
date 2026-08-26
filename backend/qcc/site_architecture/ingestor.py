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
    observe_site_state,
    persist_site_architecture_from_qcc_capture,
)
from backend.automation.site_recognizers import (
    build_default_site_state_recognizer_registry,
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
        recognizer_registry=None,
    ):
        self._output_root = Path(
            output_root
        )

        self._recognizer_registry = (
            recognizer_registry
            if recognizer_registry
            is not None
            else (
                build_default_site_state_recognizer_registry()
            )
        )

    @staticmethod
    def _context_info(
        context,
        *,
        observed_site_code=None,
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

        provider = (
            str(
                active_session.get(
                    "provider"
                )
                or ""
            ).strip().upper()
            if active_session
            else ""
        )

        site_code = str(
            observed_site_code
            or ""
        ).strip().upper()

        session_bound = (
            bool(
                session_id
            )
            and bool(
                site_code
            )
            and provider
            == site_code
        )

        return {
            "context_mode": (
                "ASSISTED_PRESENTATION"
                if session_bound
                else "MANUAL"
            ),

            "session_id": (
                session_id
                if session_bound
                else None
            ),

            "active_session": (
                active_session
                if session_bound
                else None
            ),

            "session_bound":
                session_bound,
        }

    def _observe_state(
        self,
        snapshot,
    ):
        registration = None

        try:
            registration = (
                self._recognizer_registry
                .resolve_snapshot(
                    snapshot
                )
            )
        except ValueError:
            # Una web no registrada o no resoluble
            # sigue teniendo fingerprint funcional.
            registration = None

        recognizer = (
            registration.recognizer
            if registration is not None
            else None
        )

        observation = (
            observe_site_state(
                snapshot,
                recognizer=recognizer,
            )
        )

        return {
            "site_code":
                (
                    registration.site_code
                    if registration is not None
                    else None
                ),

            "observation":
                observation,
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

            state_result = (
                self._observe_state(
                    snapshot
                )
            )

            state_observation = (
                state_result[
                    "observation"
                ]
            )

            state_observation_path = (
                capture_dir
                / "state_observation.json"
            )

            state_observation_path.write_text(
                json.dumps(
                    state_observation,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

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
                context,
                observed_site_code=(
                    state_result[
                        "site_code"
                    ]
                ),
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
            "site_code":
                state_result[
                    "site_code"
                ],

            "state_observation":
                state_observation,

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

                "state_observation":
                    "state_observation.json",

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
