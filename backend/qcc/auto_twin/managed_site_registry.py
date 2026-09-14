"""Registro canónico de sitios gestionados por AUTO TWIN.

Este módulo responde únicamente:

- qué TWINs están gestionados;
- qué origins/path scopes pertenecen a cada TWIN;
- si deben mantenerse actualizados;
- si una URL viva pertenece a un TWIN gestionado.

No decide:
- capacidades del navegador;
- seguridad de interacción;
- BrowserSessionMode;
- materialización;
- promoción de revisiones.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
from urllib.parse import urlsplit


AUTO_TWIN_MANAGED_SITE_SCHEMA_VERSION = 1


def _text(
    value,
) -> str:
    return str(
        value
        or ""
    ).strip()


def normalize_auto_twin_key(
    value,
) -> str:
    key = _text(
        value
    )

    if not key:
        raise ValueError(
            "QCC_AUTO_TWIN_KEY_REQUIRED"
        )

    return key


def normalize_auto_twin_site_code(
    value,
) -> str:
    site_code = _text(
        value
    ).upper()

    if not site_code:
        raise ValueError(
            "QCC_AUTO_TWIN_SITE_CODE_REQUIRED"
        )

    return site_code


def normalize_auto_twin_origin(
    value,
) -> str:
    raw = _text(
        value
    )

    parsed = urlsplit(
        raw
    )

    scheme = (
        parsed.scheme
        .strip()
        .lower()
    )

    hostname = (
        parsed.hostname
        or ""
    ).strip().lower()

    if (
        scheme not in {
            "http",
            "https",
        }
        or not hostname
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_ORIGIN_INVALID"
        )

    port = parsed.port

    default_port = (
        port is None
        or (
            scheme == "http"
            and port == 80
        )
        or (
            scheme == "https"
            and port == 443
        )
    )

    netloc = hostname

    if not default_port:
        netloc = (
            f"{hostname}:{port}"
        )

    return (
        f"{scheme}://{netloc}"
    )


def normalize_auto_twin_path_prefix(
    value,
) -> str:
    path = _text(
        value
    )

    if not path:
        path = "/"

    if not path.startswith("/"):
        path = "/" + path

    while (
        len(path) > 1
        and path.endswith("/")
    ):
        path = path[:-1]

    return path


def _url_identity(
    url,
) -> tuple[
    str,
    str,
]:
    parsed = urlsplit(
        _text(
            url
        )
    )

    origin = (
        normalize_auto_twin_origin(
            f"{parsed.scheme}://{parsed.netloc}"
        )
    )

    path = (
        parsed.path
        or "/"
    )

    if not path.startswith("/"):
        path = "/" + path

    return (
        origin,
        path,
    )


def _path_matches_prefix(
    path,
    prefix,
) -> bool:
    if prefix == "/":
        return True

    return (
        path == prefix
        or path.startswith(
            prefix + "/"
        )
    )


@dataclass(
    frozen=True,
)
class AutoTwinManagedSite:
    """Ámbito web declarado bajo gestión AUTO TWIN."""

    twin_key: str
    site_code: str

    origins: tuple[
        str,
        ...,
    ]

    path_prefixes: tuple[
        str,
        ...,
    ] = (
        "/",
    )

    enabled: bool = True

    auto_update: bool = True

    discover_unknown_states: bool = True

    schema_version: int = (
        AUTO_TWIN_MANAGED_SITE_SCHEMA_VERSION
    )

    def __post_init__(
        self,
    ) -> None:
        twin_key = (
            normalize_auto_twin_key(
                self.twin_key
            )
        )

        site_code = (
            normalize_auto_twin_site_code(
                self.site_code
            )
        )

        origins = tuple(
            sorted(
                {
                    normalize_auto_twin_origin(
                        value
                    )
                    for value
                    in self.origins
                }
            )
        )

        if not origins:
            raise ValueError(
                "QCC_AUTO_TWIN_ORIGINS_REQUIRED"
            )

        path_prefixes = tuple(
            sorted(
                {
                    normalize_auto_twin_path_prefix(
                        value
                    )
                    for value
                    in self.path_prefixes
                },
                key=lambda item: (
                    len(item),
                    item,
                ),
                reverse=True,
            )
        )

        if not path_prefixes:
            raise ValueError(
                "QCC_AUTO_TWIN_PATH_PREFIXES_REQUIRED"
            )

        object.__setattr__(
            self,
            "twin_key",
            twin_key,
        )

        object.__setattr__(
            self,
            "site_code",
            site_code,
        )

        object.__setattr__(
            self,
            "origins",
            origins,
        )

        object.__setattr__(
            self,
            "path_prefixes",
            path_prefixes,
        )

    def match_specificity(
        self,
        url,
    ) -> int | None:
        """Devuelve longitud del scope más específico."""

        if not self.enabled:
            return None

        origin, path = (
            _url_identity(
                url
            )
        )

        if origin not in self.origins:
            return None

        matches = [
            len(prefix)
            for prefix
            in self.path_prefixes
            if _path_matches_prefix(
                path,
                prefix,
            )
        ]

        if not matches:
            return None

        return max(
            matches
        )

    def matches_url(
        self,
        url,
    ) -> bool:
        return (
            self.match_specificity(
                url
            )
            is not None
        )

    def to_dict(
        self,
    ) -> dict:
        return {
            "schema_version":
                self.schema_version,

            "twin_key":
                self.twin_key,

            "site_code":
                self.site_code,

            "origins":
                list(
                    self.origins
                ),

            "path_prefixes":
                list(
                    self.path_prefixes
                ),

            "enabled":
                self.enabled,

            "auto_update":
                self.auto_update,

            "discover_unknown_states":
                self.discover_unknown_states,
        }


class AutoTwinManagedSiteRegistry:
    """Registry thread-safe de TWINs gestionados."""

    def __init__(
        self,
    ) -> None:
        self._lock = (
            threading.RLock()
        )

        self._sites: dict[
            str,
            AutoTwinManagedSite,
        ] = {}

        self._site_codes: dict[
            str,
            str,
        ] = {}

        self._revision = 0

    @property
    def revision(
        self,
    ) -> int:
        with self._lock:
            return self._revision

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
            if site.twin_key in self._sites:
                raise ValueError(
                    "QCC_AUTO_TWIN_KEY_ALREADY_REGISTERED"
                )

            existing_key = (
                self._site_codes.get(
                    site.site_code
                )
            )

            if existing_key is not None:
                raise ValueError(
                    "QCC_AUTO_TWIN_SITE_CODE_ALREADY_REGISTERED"
                )

            self._assert_no_scope_conflict(
                site
            )

            self._sites[
                site.twin_key
            ] = site

            self._site_codes[
                site.site_code
            ] = site.twin_key

            self._revision += 1

            return self._revision

    def _assert_no_scope_conflict(
        self,
        candidate,
    ) -> None:
        for existing in (
            self._sites.values()
        ):
            shared_origins = (
                set(
                    existing.origins
                )
                & set(
                    candidate.origins
                )
            )

            if not shared_origins:
                continue

            for left in (
                existing.path_prefixes
            ):
                for right in (
                    candidate.path_prefixes
                ):
                    if left == right:
                        raise ValueError(
                            "QCC_AUTO_TWIN_SCOPE_CONFLICT"
                        )

    def get(
        self,
        twin_key,
    ) -> AutoTwinManagedSite | None:
        key = (
            normalize_auto_twin_key(
                twin_key
            )
        )

        with self._lock:
            return self._sites.get(
                key
            )

    def get_by_site_code(
        self,
        site_code,
    ) -> AutoTwinManagedSite | None:
        code = (
            normalize_auto_twin_site_code(
                site_code
            )
        )

        with self._lock:
            twin_key = (
                self._site_codes.get(
                    code
                )
            )

            if twin_key is None:
                return None

            return self._sites.get(
                twin_key
            )

    def resolve_url(
        self,
        url,
    ) -> AutoTwinManagedSite | None:
        """Resuelve el TWIN gestionado más específico."""

        candidates = []

        with self._lock:
            sites = tuple(
                self._sites.values()
            )

        for site in sites:
            specificity = (
                site.match_specificity(
                    url
                )
            )

            if specificity is None:
                continue

            candidates.append((
                specificity,
                site.twin_key,
                site,
            ))

        if not candidates:
            return None

        candidates.sort(
            key=lambda item: (
                item[0],
                item[1],
            ),
            reverse=True,
        )

        best_specificity = (
            candidates[0][0]
        )

        best = [
            item
            for item in candidates
            if item[0]
            == best_specificity
        ]

        if len(best) != 1:
            raise ValueError(
                "QCC_AUTO_TWIN_URL_SCOPE_AMBIGUOUS"
            )

        return best[0][2]

    def twin_keys(
        self,
    ) -> tuple[
        str,
        ...,
    ]:
        with self._lock:
            return tuple(
                sorted(
                    self._sites
                )
            )

    def snapshots(
        self,
    ) -> list[
        dict
    ]:
        with self._lock:
            sites = [
                self._sites[key]
                for key
                in sorted(
                    self._sites
                )
            ]

            revision = (
                self._revision
            )

        return [
            {
                **site.to_dict(),
                "registry_revision":
                    revision,
            }
            for site in sites
        ]
