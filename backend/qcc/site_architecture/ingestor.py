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


QCC_VISUAL_EVIDENCE_SCHEMA_VERSION = 1

QCC_VISUAL_ARTIFACT_MAX_BYTES = (
    32 * 1024 * 1024
)

QCC_VISUAL_ARTIFACT_FILENAMES = {
    "viewport":
        "screenshot_viewport.png",

    "full_page":
        "screenshot_full_page.png",
}

QCC_PNG_SIGNATURE = (
    b"\x89PNG\r\n\x1a\n"
)



QCC_HTML_EVIDENCE_SCHEMA_VERSION = 1
QCC_HTML_ARTIFACT_FILENAME = "page.html"

QCC_PAGE_ARCHIVE_EVIDENCE_SCHEMA_VERSION = 1

QCC_PAGE_ARCHIVE_ARTIFACT_MAX_BYTES = (
    64 * 1024 * 1024
)

QCC_PAGE_ARCHIVE_ARTIFACT_FILENAMES = {
    "mhtml":
        "page.mhtml",
}



def _extract_main_frame_html(capture):
    """
    Extrae el HTML serializado del frame principal.

    Fuente:
    document.documentElement.outerHTML

    No reconstruye, normaliza ni añade DOCTYPE.
    """
    if not isinstance(
        capture,
        dict,
    ):
        return None

    frames = capture.get(
        "frames"
    )

    if not isinstance(
        frames,
        list,
    ):
        return None

    for frame in frames:
        if not isinstance(
            frame,
            dict,
        ):
            continue

        if (
            frame.get(
                "frame_id"
            )
            != 0
        ):
            continue

        result = frame.get(
            "result"
        )

        if not isinstance(
            result,
            dict,
        ):
            return None

        html = result.get(
            "html"
        )

        if (
            not isinstance(
                html,
                str,
            )
            or not html.strip()
        ):
            return None

        return html

    return None


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

    @staticmethod
    def _live_action_evidence(
        snapshot,
    ):
        """Proyecta evidencia JIT mínima del DOM vivo.

        Esta evidencia:
        - procede exclusivamente del snapshot actual;
        - no contiene text/value/html/payload;
        - no se persiste en metadata.json;
        - no concede permisos;
        - existe solo para gobierno JIT posterior.
        """

        actions = (
            getattr(
                snapshot,
                "actions",
                (),
            )
            or ()
        )

        evidence = []

        for action in actions:
            if not isinstance(
                action,
                dict,
            ):
                continue

            interaction = (
                action.get(
                    "interaction"
                )
                or {}
            )

            if not isinstance(
                interaction,
                dict,
            ):
                interaction = {}

            selector = str(
                action.get(
                    "selector"
                )
                or ""
            ).strip()

            evidence.append({
                "kind":
                    str(
                        action.get(
                            "kind"
                        )
                        or ""
                    ).strip(),

                "policy":
                    str(
                        action.get(
                            "policy"
                        )
                        or ""
                    ).strip(),

                "selector":
                    (
                        selector
                        or None
                    ),

                "frame_path":
                    str(
                        action.get(
                            "frame_path"
                        )
                        or "main"
                    ),

                "interaction": {
                    "visible":
                        interaction.get(
                            "visible"
                        ),

                    "disabled":
                        interaction.get(
                            "disabled"
                        ),

                    "interactable":
                        interaction.get(
                            "interactable"
                        ),
                },
            })

        return tuple(
            evidence
        )

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

    def attach_visual_artifact(
        self,
        capture_id,
        *,
        kind,
        content,
    ):
        """
        Adjunta evidencia visual binaria a una captura
        Site Architecture previamente persistida.

        No modifica qcc_capture.json ni
        site_architecture.json.

        Contrato fail-closed:
        - capture_id simple;
        - kind conocido;
        - PNG real por firma;
        - límite independiente por artefacto;
        - captura ya existente.
        """

        normalized_capture_id = str(
            capture_id
            or ""
        ).strip()

        if (
            not normalized_capture_id
            or normalized_capture_id
            in {".", ".."}
            or "/" in normalized_capture_id
            or "\\" in normalized_capture_id
            or Path(
                normalized_capture_id
            ).name
            != normalized_capture_id
        ):
            raise ValueError(
                "QCC_VISUAL_ARTIFACT_CAPTURE_ID_INVALID"
            )

        normalized_kind = str(
            kind
            or ""
        ).strip().lower()

        filename = (
            QCC_VISUAL_ARTIFACT_FILENAMES
            .get(
                normalized_kind
            )
        )

        if not filename:
            raise ValueError(
                "QCC_VISUAL_ARTIFACT_KIND_INVALID"
            )

        if isinstance(
            content,
            memoryview,
        ):
            binary = (
                content.tobytes()
            )

        elif isinstance(
            content,
            bytearray,
        ):
            binary = bytes(
                content
            )

        elif isinstance(
            content,
            bytes,
        ):
            binary = content

        else:
            raise ValueError(
                "QCC_VISUAL_ARTIFACT_CONTENT_INVALID"
            )

        if (
            not binary
            or len(binary)
            > QCC_VISUAL_ARTIFACT_MAX_BYTES
        ):
            raise ValueError(
                "QCC_VISUAL_ARTIFACT_SIZE_INVALID"
            )

        if not binary.startswith(
            QCC_PNG_SIGNATURE
        ):
            raise ValueError(
                "QCC_VISUAL_ARTIFACT_PNG_INVALID"
            )

        capture_dir = (
            self._output_root
            / normalized_capture_id
        )

        if (
            not capture_dir.exists()
            or not capture_dir.is_dir()
        ):
            raise ValueError(
                "QCC_VISUAL_ARTIFACT_CAPTURE_UNKNOWN"
            )

        metadata_path = (
            capture_dir
            / "metadata.json"
        )

        if not metadata_path.exists():
            raise ValueError(
                "QCC_VISUAL_ARTIFACT_METADATA_MISSING"
            )

        try:
            metadata = json.loads(
                metadata_path.read_text(
                    encoding="utf-8"
                )
            )

        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError(
                "QCC_VISUAL_ARTIFACT_METADATA_INVALID"
            ) from exc

        if not isinstance(
            metadata,
            dict,
        ):
            raise ValueError(
                "QCC_VISUAL_ARTIFACT_METADATA_INVALID"
            )

        if (
            str(
                metadata.get(
                    "capture_id"
                )
                or ""
            )
            != normalized_capture_id
        ):
            raise ValueError(
                "QCC_VISUAL_ARTIFACT_CAPTURE_MISMATCH"
            )

        artifact_path = (
            capture_dir
            / filename
        )

        artifact_tmp = (
            capture_dir
            / (
                filename
                + ".tmp"
            )
        )

        metadata_tmp = (
            capture_dir
            / "metadata.json.tmp"
        )

        artifacts = metadata.get(
            "artifacts"
        )

        if not isinstance(
            artifacts,
            dict,
        ):
            artifacts = {}
            metadata[
                "artifacts"
            ] = artifacts

        artifact_key = (
            "screenshot_"
            + normalized_kind
        )

        artifacts[
            artifact_key
        ] = filename

        visual_evidence = (
            metadata.get(
                "visual_evidence"
            )
        )

        if not isinstance(
            visual_evidence,
            dict,
        ):
            visual_evidence = {
                "schema_version":
                    QCC_VISUAL_EVIDENCE_SCHEMA_VERSION,
            }

            metadata[
                "visual_evidence"
            ] = visual_evidence

        visual_evidence[
            "schema_version"
        ] = (
            QCC_VISUAL_EVIDENCE_SCHEMA_VERSION
        )

        visual_evidence[
            normalized_kind
        ] = {
            "artifact":
                filename,

            "content_type":
                "image/png",

            "bytes":
                len(binary),
        }

        try:
            artifact_tmp.write_bytes(
                binary
            )

            metadata_tmp.write_text(
                json.dumps(
                    metadata,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            artifact_tmp.replace(
                artifact_path
            )

            metadata_tmp.replace(
                metadata_path
            )

        except Exception:
            artifact_tmp.unlink(
                missing_ok=True
            )

            metadata_tmp.unlink(
                missing_ok=True
            )

            raise

        return {
            "capture_id":
                normalized_capture_id,

            "kind":
                normalized_kind,

            "artifact":
                filename,

            "content_type":
                "image/png",

            "bytes":
                len(binary),
        }


    def attach_page_archive_artifact(
        self,
        capture_id,
        *,
        kind,
        content,
    ):
        """
        QCC_PAGE_ARCHIVE_ARTIFACT_V1

        Adjunta una representación autocontenida
        de la página a una captura ya persistida.

        Actualmente:
        - mhtml -> page.mhtml

        El MHTML procede de:
        chrome.pageCapture.saveAsMHTML()

        No modifica el DOM raw ni Site Architecture.
        """
        normalized_capture_id = str(
            capture_id
            or ""
        ).strip()

        if (
            not normalized_capture_id
            or normalized_capture_id
            in {".", ".."}
            or "/" in normalized_capture_id
            or "\\" in normalized_capture_id
            or Path(
                normalized_capture_id
            ).name
            != normalized_capture_id
        ):
            raise ValueError(
                "QCC_PAGE_ARCHIVE_CAPTURE_ID_INVALID"
            )

        normalized_kind = str(
            kind
            or ""
        ).strip().lower()

        filename = (
            QCC_PAGE_ARCHIVE_ARTIFACT_FILENAMES
            .get(
                normalized_kind
            )
        )

        if not filename:
            raise ValueError(
                "QCC_PAGE_ARCHIVE_KIND_INVALID"
            )

        if isinstance(
            content,
            memoryview,
        ):
            binary = (
                content.tobytes()
            )

        elif isinstance(
            content,
            bytearray,
        ):
            binary = bytes(
                content
            )

        elif isinstance(
            content,
            bytes,
        ):
            binary = content

        else:
            raise ValueError(
                "QCC_PAGE_ARCHIVE_CONTENT_INVALID"
            )

        if (
            not binary
            or len(binary)
            > QCC_PAGE_ARCHIVE_ARTIFACT_MAX_BYTES
        ):
            raise ValueError(
                "QCC_PAGE_ARCHIVE_SIZE_INVALID"
            )


        # Contrato mínimo Blink MHTML.
        #
        # No intentamos parsear todo MIME aquí;
        # sí evitamos persistir bytes arbitrarios
        # bajo extensión .mhtml.
        header_probe = (
            binary[:16384]
            .lower()
        )

        if (
            b"mime-version:"
            not in header_probe
            or b"multipart/related"
            not in header_probe
        ):
            raise ValueError(
                "QCC_PAGE_ARCHIVE_MHTML_INVALID"
            )


        capture_dir = (
            self._output_root
            / normalized_capture_id
        )

        if (
            not capture_dir.exists()
            or not capture_dir.is_dir()
        ):
            raise ValueError(
                "QCC_PAGE_ARCHIVE_CAPTURE_UNKNOWN"
            )

        metadata_path = (
            capture_dir
            / "metadata.json"
        )

        if not metadata_path.exists():
            raise ValueError(
                "QCC_PAGE_ARCHIVE_METADATA_MISSING"
            )

        try:
            metadata = json.loads(
                metadata_path.read_text(
                    encoding="utf-8"
                )
            )

        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError(
                "QCC_PAGE_ARCHIVE_METADATA_INVALID"
            ) from exc

        if not isinstance(
            metadata,
            dict,
        ):
            raise ValueError(
                "QCC_PAGE_ARCHIVE_METADATA_INVALID"
            )

        if (
            str(
                metadata.get(
                    "capture_id"
                )
                or ""
            )
            != normalized_capture_id
        ):
            raise ValueError(
                "QCC_PAGE_ARCHIVE_CAPTURE_MISMATCH"
            )


        artifact_path = (
            capture_dir
            / filename
        )

        artifact_tmp = (
            capture_dir
            / (
                filename
                + ".tmp"
            )
        )

        metadata_tmp = (
            capture_dir
            / "metadata.json.tmp"
        )


        artifacts = metadata.get(
            "artifacts"
        )

        if not isinstance(
            artifacts,
            dict,
        ):
            artifacts = {}

            metadata[
                "artifacts"
            ] = artifacts

        artifacts[
            "page_mhtml"
        ] = filename


        page_archive_evidence = (
            metadata.get(
                "page_archive_evidence"
            )
        )

        if not isinstance(
            page_archive_evidence,
            dict,
        ):
            page_archive_evidence = {}

            metadata[
                "page_archive_evidence"
            ] = page_archive_evidence


        page_archive_evidence[
            "schema_version"
        ] = (
            QCC_PAGE_ARCHIVE_EVIDENCE_SCHEMA_VERSION
        )

        page_archive_evidence[
            "mhtml"
        ] = {
            "artifact":
                filename,

            "content_type":
                "multipart/related",

            "source":
                "chrome.pageCapture.saveAsMHTML",

            "bytes":
                len(binary),
        }


        try:
            artifact_tmp.write_bytes(
                binary
            )

            metadata_tmp.write_text(
                json.dumps(
                    metadata,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            artifact_tmp.replace(
                artifact_path
            )

            metadata_tmp.replace(
                metadata_path
            )

        except Exception:
            artifact_tmp.unlink(
                missing_ok=True
            )

            metadata_tmp.unlink(
                missing_ok=True
            )

            raise


        return {
            "capture_id":
                normalized_capture_id,

            "kind":
                normalized_kind,

            "artifact":
                filename,

            "content_type":
                "multipart/related",

            "bytes":
                len(binary),
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

            # QCC_PAGE_HTML_MATERIALIZED_V1
            #
            # Materializamos como artefacto independiente
            # exactamente el outerHTML observado por QCC.
            page_html = (
                _extract_main_frame_html(
                    capture
                )
            )

            page_html_bytes = None

            if page_html is not None:
                page_html_path = (
                    capture_dir
                    / QCC_HTML_ARTIFACT_FILENAME
                )

                page_html_path.write_text(
                    page_html,
                    encoding="utf-8",
                )

                page_html_bytes = len(
                    page_html.encode(
                        "utf-8"
                    )
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

            live_actions = (
                self._live_action_evidence(
                    snapshot
                )
            )

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

        # QCC_HTML_EVIDENCE_METADATA_V1
        if page_html_bytes is not None:
            metadata[
                "artifacts"
            ][
                "page_html"
            ] = (
                QCC_HTML_ARTIFACT_FILENAME
            )

            metadata[
                "html_evidence"
            ] = {
                "schema_version":
                    QCC_HTML_EVIDENCE_SCHEMA_VERSION,

                "artifact":
                    QCC_HTML_ARTIFACT_FILENAME,

                "content_type":
                    "text/html; charset=utf-8",

                "source":
                    "document.documentElement.outerHTML",

                "bytes":
                    page_html_bytes,
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

        # `live_actions` es deliberadamente runtime-only.
        #
        # No forma parte de metadata.json ni del
        # contexto persistente de QCC.
        runtime_result = dict(
            metadata
        )

        runtime_result[
            "live_actions"
        ] = live_actions

        return runtime_result
