"""Servicio de aplicación para la pantalla CRM Automatizaciones → Twins.

Frontera arquitectónica:

    Flet
      ↓
    TwinManagementService
      ↓
    AUTO TWIN stores / materialized revisions

La vista nunca inspecciona directamente ``data/qcc``.

Este primer contrato es read-only. Las acciones de Discovery y localhost
se incorporarán mediante runtimes gobernados posteriores.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from backend.qcc.auto_twin.materialized_revision_store import (
    AutoTwinMaterializedRevisionStore,
)

from backend.qcc.auto_twin.profile_policy import (
    AUTO_TWIN_DISCOVERY_PROFILE_KEY,
)

from backend.qcc.auto_twin.managed_site_store import (
    AutoTwinManagedSiteStore,
)

from backend.qcc.auto_twin.observation_store import (
    AutoTwinObservationStore,
)

from backend.qcc.auto_twin.materialization_compatibility import (
    AUTO_TWIN_MATERIALIZATION_COMPATIBLE,
    AUTO_TWIN_MATERIALIZATION_INCOMPATIBLE,
    evaluate_materialized_revision_compatibility,
)

from backend.qcc.auto_twin.automatic_materialization import (
    AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED,
    refresh_stale_twin_materialization,
)

from backend.qcc.site_architecture.ingestor import (
    DEFAULT_QCC_SITE_ARCHITECTURE_ROOT,
)

from backend.services.twin_local_runtime_service import (
    get_default_twin_local_runtime_service,
)

from backend.services.twin_browser_runtime_service import (
    get_default_twin_browser_runtime_service,
)

from backend.services.twin_discovery_runtime_service import (
    get_default_twin_discovery_runtime_service,
)


PROJECT_ROOT = Path(
    __file__
).resolve().parents[2]

DEFAULT_MATERIALIZED_ROOT = (
    PROJECT_ROOT
    / "data"
    / "qcc"
    / "auto_twin"
    / "materialized"
)

DEFAULT_CAPTURE_ROOT = (
    PROJECT_ROOT
    / DEFAULT_QCC_SITE_ARCHITECTURE_ROOT
)


TWIN_CATALOG = (
    {
        "twin_key": "mercurio",
        "site_code": "MERCURIO",
        "label": "Mercurio",
        "enabled": True,
    },
    {
        "twin_key": "red_sara",
        "site_code": "RED_SARA",
        "label": "Red SARA",
        "enabled": True,
    },
    {
        "twin_key": "dehu",
        "site_code": "DEHU",
        "label": "DEHú",
        "enabled": False,
    },
    {
        "twin_key": "nacionalidad",
        "site_code": "NACIONALIDAD",
        "label": "Nacionalidad",
        "enabled": False,
    },
)


class TwinManagementService:
    """Proyección provider-neutral de los Twins conocidos por el CRM."""

    def __init__(
        self,
        *,
        materialized_root=None,
        local_runtime_service=None,
        browser_runtime_service=None,
        discovery_runtime_service=None,
        managed_site_store=None,
        observation_store=None,
        capture_root=None,
        materialization_refresher=None,
    ):
        self.materialized_root = Path(
            materialized_root
            or DEFAULT_MATERIALIZED_ROOT
        )

        self.materialized_store = (
            AutoTwinMaterializedRevisionStore(
                root=self.materialized_root
            )
        )

        self.local_runtime_service = (
            local_runtime_service
            or get_default_twin_local_runtime_service()
        )

        self.browser_runtime_service = (
            browser_runtime_service
            or get_default_twin_browser_runtime_service()
        )

        # QCC_AUTO_TWIN_RUNTIME_MATERIALIZATION_COMPATIBILITY_V1
        #
        # Reused, not redesigned: the SAME managed-site policy and
        # observation evidence the governed Discovery pipeline already
        # owns, consulted here only to decide whether an Open Twin
        # request may trigger a local-evidence-only refresh.
        self.managed_site_store = (
            managed_site_store
            or AutoTwinManagedSiteStore()
        )

        self.observation_store = (
            observation_store
            or AutoTwinObservationStore()
        )

        self.capture_root = Path(
            capture_root
            or DEFAULT_CAPTURE_ROOT
        )

        self.materialization_refresher = (
            materialization_refresher
            or refresh_stale_twin_materialization
        )

        self.discovery_runtime_service = (
            discovery_runtime_service
            or get_default_twin_discovery_runtime_service()
        )

    def _runtime_registry_path(
        self,
        *,
        twin_key,
        revision_id,
    ):
        return (
            self.materialized_root
            / twin_key
            / revision_id
            / "runtime"
            / "registry.json"
        )

    def _runtime_index_path(
        self,
        *,
        twin_key,
        revision_id,
    ):
        return (
            self.materialized_root
            / twin_key
            / revision_id
            / "runtime"
            / "index.html"
        )

    def _project_path(
        self,
        path,
    ):
        path = Path(path)

        try:
            return path.relative_to(
                PROJECT_ROOT
            ).as_posix()

        except ValueError:
            return path.as_posix()

    def _read_runtime_registry(
        self,
        *,
        twin_key,
        revision_id,
    ):
        path = self._runtime_registry_path(
            twin_key=twin_key,
            revision_id=revision_id,
        )

        if not path.is_file():
            return {}

        try:
            payload = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

        except Exception:
            return {}

        return (
            payload
            if isinstance(
                payload,
                dict,
            )
            else {}
        )

    def _materialized_projection(
        self,
        catalog_item,
    ):
        twin_key = catalog_item[
            "twin_key"
        ]

        try:
            records = (
                self.materialized_store.list(
                    twin_key=twin_key
                )
            )

        except Exception as exc:
            return {
                **deepcopy(
                    catalog_item
                ),
                "status": "ERROR",
                "status_label": "Error de lectura",
                "error": str(exc),
                "discovery_profile_key": (
                    AUTO_TWIN_DISCOVERY_PROFILE_KEY
                ),
                "discovery_status": "STOPPED",
                "localhost_status": "STOPPED",
                "localhost_url": None,
                "twin_browser_status": "STOPPED",
                "twin_browser_url": None,
                "twin_browser_profile_key": None,
                "twin_browser_profile_dir": None,
                "twin_browser_session_mode": "PERSISTENT",
                "twin_browser_qcc_registered": False,
                "twin_browser_owner_alive": False,
                "twin_browser_error": None,
                "revision_id": None,
                "created_at": None,
                "state_count": 0,
                "procedure_code": None,
                "flow_variant": None,
                "content_sha256": None,
                "runtime_index": None,
            }

        if not records:
            return {
                **deepcopy(
                    catalog_item
                ),
                "status": "EMPTY",
                "status_label": "Sin revisión",
                "error": None,
                "discovery_profile_key": (
                    AUTO_TWIN_DISCOVERY_PROFILE_KEY
                ),
                "discovery_status": "STOPPED",
                "localhost_status": "STOPPED",
                "localhost_url": None,
                "twin_browser_status": "STOPPED",
                "twin_browser_url": None,
                "twin_browser_profile_key": None,
                "twin_browser_profile_dir": None,
                "twin_browser_session_mode": "PERSISTENT",
                "twin_browser_qcc_registered": False,
                "twin_browser_owner_alive": False,
                "twin_browser_error": None,
                "revision_id": None,
                "created_at": None,
                "state_count": 0,
                "procedure_code": None,
                "flow_variant": None,
                "content_sha256": None,
                "runtime_index": None,
            }

        revision = records[-1]

        revision_id = str(
            revision.get(
                "materialized_revision_id"
            )
            or ""
        )

        registry = (
            self._read_runtime_registry(
                twin_key=twin_key,
                revision_id=revision_id,
            )
        )

        runtime_index = (
            self._runtime_index_path(
                twin_key=twin_key,
                revision_id=revision_id,
            )
        )

        try:
            twin_browser_runtime = (
                self.browser_runtime_service
                .get_status(
                    twin_key=twin_key
                )
            )

        except Exception as exc:
            twin_browser_runtime = {
                "status": "ERROR",
                "url": None,
                "profile_key": None,
                "profile_dir": None,
                "browser_session_mode": "PERSISTENT",
                "qcc_registered": False,
                "owner_thread_alive": False,
                "last_error": str(exc),
            }

        return {
            **deepcopy(
                catalog_item
            ),

            "status": "MATERIALIZED",
            "status_label": "Materializado",
            "error": None,

            # En esta fase representa la capability gobernada.
            # El lifecycle físico se conectará en F3.
            "discovery_profile_key": (
                AUTO_TWIN_DISCOVERY_PROFILE_KEY
            ),

            "discovery_status": (
                self.discovery_runtime_service
                .get_status(
                    twin_key=twin_key
                )[
                    "status"
                ]
            ),

            "discovery_qcc_registered": (
                self.discovery_runtime_service
                .get_status(
                    twin_key=twin_key
                )[
                    "qcc_registered"
                ]
            ),

            "discovery_extension_mode": (
                self.discovery_runtime_service
                .get_status(
                    twin_key=twin_key
                )[
                    "qcc_extension_mode"
                ]
            ),

            "discovery_profile_dir": (
                self.discovery_runtime_service
                .get_status(
                    twin_key=twin_key
                )[
                    "profile_dir"
                ]
            ),

            "localhost_status": (
                self.local_runtime_service
                .get_status(
                    twin_key=twin_key
                )[
                    "status"
                ]
            ),

            "localhost_url": (
                self.local_runtime_service
                .get_status(
                    twin_key=twin_key
                )[
                    "url"
                ]
            ),

            "twin_browser_status": (
                twin_browser_runtime.get(
                    "status"
                )
                or "STOPPED"
            ),

            "twin_browser_url": (
                twin_browser_runtime.get(
                    "url"
                )
            ),

            "twin_browser_profile_key": (
                twin_browser_runtime.get(
                    "profile_key"
                )
            ),

            "twin_browser_profile_dir": (
                twin_browser_runtime.get(
                    "profile_dir"
                )
            ),

            "twin_browser_session_mode": (
                twin_browser_runtime.get(
                    "browser_session_mode"
                )
                or "PERSISTENT"
            ),

            "twin_browser_qcc_registered": (
                twin_browser_runtime.get(
                    "qcc_registered"
                )
                is True
            ),

            "twin_browser_owner_alive": (
                twin_browser_runtime.get(
                    "owner_thread_alive"
                )
                is True
            ),

            "twin_browser_error": (
                twin_browser_runtime.get(
                    "last_error"
                )
            ),

            "revision_id": revision_id,

            "created_at": revision.get(
                "created_at"
            ),

            "state_count": len(
                revision.get(
                    "state_manifest"
                )
                or []
            ),

            "procedure_code": (
                registry.get(
                    "procedure_code"
                )
                or None
            ),

            "flow_variant": (
                registry.get(
                    "flow_variant"
                )
                or None
            ),

            "content_sha256": (
                revision.get(
                    "content_sha256"
                )
                or None
            ),

            "runtime_index": (
                self._project_path(
                    runtime_index
                )
                if runtime_index.is_file()
                else None
            ),
        }

    def _planned_projection(
        self,
        catalog_item,
    ):
        return {
            **deepcopy(
                catalog_item
            ),
            "status": "PLANNED",
            "status_label": "Pendiente",
            "error": None,
            "discovery_profile_key": None,
            "discovery_status": "UNAVAILABLE",
            "localhost_status": "UNAVAILABLE",
            "localhost_url": None,
            "revision_id": None,
            "created_at": None,
            "state_count": 0,
            "procedure_code": None,
            "flow_variant": None,
            "content_sha256": None,
            "runtime_index": None,
        }

    def _catalog_item(
        self,
        twin_key,
    ):
        twin_key = str(
            twin_key
            or ""
        ).strip()

        for item in TWIN_CATALOG:
            if (
                item[
                    "twin_key"
                ]
                == twin_key
            ):
                return item

        raise KeyError(
            "QCC_AUTO_TWIN_UNKNOWN_TWIN:"
            + twin_key
        )

    def get_twin(
        self,
        twin_key,
    ):
        item = self._catalog_item(
            twin_key
        )

        if not item[
            "enabled"
        ]:
            return self._planned_projection(
                item
            )

        return self._materialized_projection(
            item
        )

    def start_discovery(
        self,
        twin_key,
    ):
        twin = self.get_twin(
            twin_key
        )

        if (
            twin[
                "status"
            ]
            not in {
                "MATERIALIZED",
                "EMPTY",
            }
        ):
            raise RuntimeError(
                "QCC_AUTO_TWIN_DISCOVERY_UNAVAILABLE"
            )

        return (
            self.discovery_runtime_service
            .start(
                twin_key=twin_key
            )
        )

    def stop_discovery(
        self,
        twin_key,
    ):
        self._catalog_item(
            twin_key
        )

        return (
            self.discovery_runtime_service
            .stop(
                twin_key=twin_key
            )
        )

    def _managed_auto_update_enabled(
        self,
        twin_key,
    ):
        try:
            managed = (
                self.managed_site_store
                .get(
                    twin_key
                )
            )

        except Exception:
            return False

        return bool(
            managed
        ) and bool(
            getattr(
                managed,
                "enabled",
                False,
            )
        ) and bool(
            getattr(
                managed,
                "auto_update",
                False,
            )
        )

    def _preferred_compatible_revision_id(
        self,
        twin_key,
    ):
        """An already-COMPATIBLE revision this twin already owns, if any.

        QCC_AUTO_TWIN_RUNTIME_MATERIALIZATION_IDEMPOTENCY_V1
        --------------------------------------------------
        AutoTwinMaterializedRevisionStore.list() orders revisions by
        their (content-addressed, not chronological) revision id --
        the SAME convention reconcile_auto_twin_discovery_materialization
        itself relies on for "latest" with no explicit pin. That
        convention is out of this fix's scope to change.

        A fresh refresh's new revision id is therefore not guaranteed
        to sort after the stale one it replaced. Idempotency (never
        rematerializing an already-compatible revision on a later
        Open Twin call) is guaranteed here instead, independently of
        that ordering: scan every revision this twin already has and
        prefer one that is already COMPATIBLE over the raw
        catalog/projection selection.
        """

        try:
            records = (
                self.materialized_store
                .list(
                    twin_key=twin_key
                )
            )

        except Exception:
            return None

        compatible_ids = [
            record.get(
                "materialized_revision_id"
            )
            for record in (
                records
                or []
            )
            if (
                evaluate_materialized_revision_compatibility(
                    materialized_root=(
                        self.materialized_root
                    ),
                    twin_key=twin_key,
                    revision_id=(
                        record.get(
                            "materialized_revision_id"
                        )
                    ),
                )
                == AUTO_TWIN_MATERIALIZATION_COMPATIBLE
            )
        ]

        return (
            compatible_ids[-1]
            if compatible_ids
            else None
        )

    def _resolve_open_revision_id(
        self,
        *,
        twin_key,
        revision_id,
    ):
        """CRM runtime-materialization compatibility gate.

        COMPATIBLE: open the existing immutable revision unchanged.

        STALE_REGENERATABLE + managed auto_update: trigger the SAME
        canonical materializer the governed Discovery pipeline uses,
        from EXISTING local evidence only, and open the resulting NEW
        immutable revision. The old revision is never mutated.

        Otherwise: fail closed with an explicit, generic error -- a
        stale/incompatible runtime is never silently opened.
        """

        preferred = (
            self._preferred_compatible_revision_id(
                twin_key
            )
        )

        if preferred:
            return preferred

        decision = (
            evaluate_materialized_revision_compatibility(
                materialized_root=(
                    self.materialized_root
                ),
                twin_key=twin_key,
                revision_id=revision_id,
            )
        )

        if (
            decision
            == AUTO_TWIN_MATERIALIZATION_COMPATIBLE
        ):
            return revision_id

        if (
            decision
            == AUTO_TWIN_MATERIALIZATION_INCOMPATIBLE
        ):
            raise RuntimeError(
                "QCC_AUTO_TWIN_BROWSER_RUNTIME_REVISION_INCOMPATIBLE:"
                + twin_key
            )

        if not self._managed_auto_update_enabled(
            twin_key
        ):
            raise RuntimeError(
                "QCC_AUTO_TWIN_BROWSER_RUNTIME_REVISION_STALE:"
                + twin_key
            )

        refreshed = (
            self.materialization_refresher(
                twin_key=twin_key,
                revision_id=revision_id,
                managed_site_store=(
                    self.managed_site_store
                ),
                observation_store=(
                    self.observation_store
                ),
                materialized_root=(
                    self.materialized_root
                ),
                capture_root=(
                    self.capture_root
                ),
            )
        )

        refreshed_revision_id = (
            refreshed.get(
                "materialized_revision_id"
            )
            if isinstance(
                refreshed,
                dict,
            )
            else None
        )

        if (
            isinstance(
                refreshed,
                dict,
            )
            and refreshed.get(
                "status"
            )
            == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED
            and refreshed_revision_id
        ):
            return refreshed_revision_id

        # Best-effort auto-heal only: insufficient local evidence to
        # regenerate must not brick the CRM. The old, still-immutable
        # revision is opened as-is.
        return revision_id

    def start_twin_browser(
        self,
        twin_key,
        *,
        pathname=None,
    ):
        """Abre el Twin exclusivamente en SeleniumBase gobernado."""

        twin = self.get_twin(
            twin_key
        )

        if (
            twin[
                "status"
            ]
            != "MATERIALIZED"
        ):
            raise RuntimeError(
                "QCC_AUTO_TWIN_BROWSER_RUNTIME_REVISION_UNAVAILABLE"
            )

        revision_id = twin.get(
            "revision_id"
        )

        if not revision_id:
            raise RuntimeError(
                "QCC_AUTO_TWIN_BROWSER_RUNTIME_REVISION_UNAVAILABLE"
            )

        revision_id = (
            self._resolve_open_revision_id(
                twin_key=twin_key,
                revision_id=revision_id,
            )
        )

        return (
            self.browser_runtime_service
            .start(
                twin_key=twin_key,
                revision_id=revision_id,
                pathname=pathname,
            )
        )

    def stop_twin_browser(
        self,
        twin_key,
    ):
        self._catalog_item(
            twin_key
        )

        return (
            self.browser_runtime_service
            .stop(
                twin_key=twin_key
            )
        )

    def start_localhost(
        self,
        twin_key,
    ):
        twin = self.get_twin(
            twin_key
        )

        if (
            twin[
                "status"
            ]
            != "MATERIALIZED"
        ):
            raise RuntimeError(
                "QCC_AUTO_TWIN_LOCAL_RUNTIME_REVISION_UNAVAILABLE"
            )

        revision_id = twin.get(
            "revision_id"
        )

        if not revision_id:
            raise RuntimeError(
                "QCC_AUTO_TWIN_LOCAL_RUNTIME_REVISION_UNAVAILABLE"
            )

        return (
            self.local_runtime_service
            .start(
                twin_key=twin_key,
                revision_id=revision_id,
            )
        )

    def stop_localhost(
        self,
        twin_key,
    ):
        self._catalog_item(
            twin_key
        )

        return (
            self.local_runtime_service
            .stop(
                twin_key=twin_key
            )
        )

    def list_twins(self):
        result = []

        for item in TWIN_CATALOG:
            if item[
                "enabled"
            ]:
                result.append(
                    self._materialized_projection(
                        item
                    )
                )

            else:
                result.append(
                    self._planned_projection(
                        item
                    )
                )

        return result

    def get_dashboard_snapshot(self):
        twins = self.list_twins()

        materialized = [
            item
            for item in twins
            if item[
                "status"
            ]
            == "MATERIALIZED"
        ]

        return {
            "twins": twins,

            "summary": {
                "total_twins":
                    len(
                        twins
                    ),

                "materialized_twins":
                    len(
                        materialized
                    ),

                "known_states":
                    sum(
                        int(
                            item.get(
                                "state_count"
                            )
                            or 0
                        )
                        for item
                        in materialized
                    ),

                "discovery_profile_key":
                    AUTO_TWIN_DISCOVERY_PROFILE_KEY,
            },
        }
