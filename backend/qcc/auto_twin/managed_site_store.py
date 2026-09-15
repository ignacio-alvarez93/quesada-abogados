"""Persistencia canónica de sitios gestionados AUTO TWIN.

Fuente compartida por todos los navegadores QCC.

Persistencia:
    data/qcc/auto_twin/managed_sites.json

Características:
- JSON versionado;
- escritura atómica;
- registry provider-neutral;
- sin dependencia de Chrome;
- sin dependencia de Site Architecture;
- sin materialización TWIN.
"""

from __future__ import annotations

import json
from pathlib import Path
import threading

from .managed_site_registry import (
    AutoTwinManagedSite,
    AutoTwinManagedSiteRegistry,
)


AUTO_TWIN_MANAGED_SITE_STORE_SCHEMA_VERSION = 1

AUTO_TWIN_MANAGED_SITE_STORE_TYPE = (
    "QCC_AUTO_TWIN_MANAGED_SITE_STORE"
)

DEFAULT_AUTO_TWIN_MANAGED_SITE_STORE_PATH = (
    Path("data")
    / "qcc"
    / "auto_twin"
    / "managed_sites.json"
)


class AutoTwinManagedSiteStore:
    """Store persistente y thread-safe de TWINs gestionados."""

    def __init__(
        self,
        *,
        path=(
            DEFAULT_AUTO_TWIN_MANAGED_SITE_STORE_PATH
        ),
    ) -> None:
        self._path = Path(
            path
        )

        self._lock = (
            threading.RLock()
        )

        self._registry = (
            AutoTwinManagedSiteRegistry()
        )

        self._revision = 0

        self._load()

    @property
    def path(
        self,
    ) -> Path:
        return self._path

    @property
    def revision(
        self,
    ) -> int:
        with self._lock:
            return self._revision

    @property
    def registry(
        self,
    ) -> AutoTwinManagedSiteRegistry:
        return self._registry

    @staticmethod
    def _site_from_payload(
        payload,
    ) -> AutoTwinManagedSite:
        if not isinstance(
            payload,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_MANAGED_SITE_PAYLOAD_INVALID"
            )

        return AutoTwinManagedSite(
            twin_key=payload.get(
                "twin_key"
            ),
            site_code=payload.get(
                "site_code"
            ),
            origins=tuple(
                payload.get(
                    "origins"
                )
                or ()
            ),
            path_prefixes=tuple(
                payload.get(
                    "path_prefixes"
                )
                or ()
            ),
            enabled=bool(
                payload.get(
                    "enabled",
                    True,
                )
            ),
            auto_update=bool(
                payload.get(
                    "auto_update",
                    True,
                )
            ),
            discover_unknown_states=bool(
                payload.get(
                    "discover_unknown_states",
                    True,
                )
            ),
        )

    @staticmethod
    def _registry_sites(
        registry,
    ) -> list[
        AutoTwinManagedSite
    ]:
        return [
            registry.get(
                twin_key
            )
            for twin_key
            in registry.twin_keys()
        ]

    @classmethod
    def _payload_for(
        cls,
        *,
        registry,
        revision,
    ) -> dict:
        sites = [
            site.to_dict()
            for site
            in cls._registry_sites(
                registry
            )
            if site is not None
        ]

        return {
            "schema_version":
                AUTO_TWIN_MANAGED_SITE_STORE_SCHEMA_VERSION,

            "store_type":
                AUTO_TWIN_MANAGED_SITE_STORE_TYPE,

            "revision":
                int(
                    revision
                ),

            "count":
                len(
                    sites
                ),

            "managed_twins":
                sites,
        }

    def _load(
        self,
    ) -> None:
        if not self._path.is_file():
            return

        try:
            payload = json.loads(
                self._path.read_text(
                    encoding="utf-8"
                )
            )

        except (
            OSError,
            ValueError,
            TypeError,
        ) as exc:
            raise ValueError(
                "QCC_AUTO_TWIN_STORE_READ_INVALID"
            ) from exc

        if not isinstance(
            payload,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_STORE_PAYLOAD_INVALID"
            )

        if (
            payload.get(
                "schema_version"
            )
            != AUTO_TWIN_MANAGED_SITE_STORE_SCHEMA_VERSION
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_STORE_SCHEMA_INVALID"
            )

        if (
            payload.get(
                "store_type"
            )
            != AUTO_TWIN_MANAGED_SITE_STORE_TYPE
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_STORE_TYPE_INVALID"
            )

        revision = payload.get(
            "revision",
            0,
        )

        if (
            not isinstance(
                revision,
                int,
            )
            or revision < 0
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_STORE_REVISION_INVALID"
            )

        raw_sites = payload.get(
            "managed_twins"
        )

        if not isinstance(
            raw_sites,
            list,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_STORE_SITES_INVALID"
            )

        registry = (
            AutoTwinManagedSiteRegistry()
        )

        for raw_site in raw_sites:
            registry.register(
                self._site_from_payload(
                    raw_site
                )
            )

        declared_count = payload.get(
            "count"
        )

        if (
            declared_count is not None
            and declared_count
            != len(
                raw_sites
            )
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_STORE_COUNT_INVALID"
            )

        self._registry = registry
        self._revision = revision

    def _persist_candidate(
        self,
        *,
        registry,
        revision,
    ) -> None:
        payload = self._payload_for(
            registry=registry,
            revision=revision,
        )

        self._path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary = (
            self._path.with_suffix(
                self._path.suffix
                + ".tmp"
            )
        )

        temporary.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        temporary.replace(
            self._path
        )

    def register(
        self,
        site,
    ) -> int:
        if not isinstance(
            site,
            AutoTwinManagedSite,
        ):
            raise TypeError(
                "QCC_AUTO_TWIN_MANAGED_SITE_INVALID"
            )

        with self._lock:
            candidate = (
                AutoTwinManagedSiteRegistry()
            )

            for existing in (
                self._registry_sites(
                    self._registry
                )
            ):
                if existing is not None:
                    candidate.register(
                        existing
                    )

            candidate.register(
                site
            )

            next_revision = (
                self._revision
                + 1
            )

            self._persist_candidate(
                registry=candidate,
                revision=next_revision,
            )

            self._registry = candidate
            self._revision = (
                next_revision
            )

            return self._revision

    def update_settings(
        self,
        twin_key,
        *,
        enabled=None,
        auto_update=None,
        discover_unknown_states=None,
    ) -> int:
        """Actualiza únicamente gobierno operativo del TWIN.

        No modifica:
        - twin_key;
        - site_code;
        - origins;
        - path scopes.

        No existe borrado destructivo.
        """

        with self._lock:
            current = self._registry.get(
                twin_key
            )

            if current is None:
                raise ValueError(
                    "QCC_AUTO_TWIN_NOT_FOUND"
                )

            values = {
                "enabled":
                    current.enabled,

                "auto_update":
                    current.auto_update,

                "discover_unknown_states":
                    current.discover_unknown_states,
            }

            provided = {
                "enabled":
                    enabled,

                "auto_update":
                    auto_update,

                "discover_unknown_states":
                    discover_unknown_states,
            }

            changed = False

            for key, value in (
                provided.items()
            ):
                if value is None:
                    continue

                if not isinstance(
                    value,
                    bool,
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_SETTING_BOOL_REQUIRED"
                    )

                if values[key] != value:
                    values[key] = value
                    changed = True

            if not changed:
                return self._revision

            updated = AutoTwinManagedSite(
                twin_key=
                    current.twin_key,

                site_code=
                    current.site_code,

                origins=
                    current.origins,

                path_prefixes=
                    current.path_prefixes,

                enabled=
                    values["enabled"],

                auto_update=
                    values["auto_update"],

                discover_unknown_states=
                    values[
                        "discover_unknown_states"
                    ],
            )

            candidate = (
                AutoTwinManagedSiteRegistry()
            )

            for existing in (
                self._registry_sites(
                    self._registry
                )
            ):
                if (
                    existing is None
                    or existing.twin_key
                    == current.twin_key
                ):
                    continue

                candidate.register(
                    existing
                )

            candidate.register(
                updated
            )

            next_revision = (
                self._revision
                + 1
            )

            self._persist_candidate(
                registry=candidate,
                revision=next_revision,
            )

            self._registry = candidate
            self._revision = (
                next_revision
            )

            return self._revision

    def get(
        self,
        twin_key,
    ) -> AutoTwinManagedSite | None:
        with self._lock:
            return self._registry.get(
                twin_key
            )

    def get_by_site_code(
        self,
        site_code,
    ) -> AutoTwinManagedSite | None:
        """Resuelve identidad gestionada por site_code canónico."""

        with self._lock:
            return (
                self._registry
                .get_by_site_code(
                    site_code
                )
            )

    def resolve_url(
        self,
        url,
    ) -> AutoTwinManagedSite | None:
        with self._lock:
            return self._registry.resolve_url(
                url
            )

    def snapshot(
        self,
    ) -> dict:
        with self._lock:
            return self._payload_for(
                registry=self._registry,
                revision=self._revision,
            )
