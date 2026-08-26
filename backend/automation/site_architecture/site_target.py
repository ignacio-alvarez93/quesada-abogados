"""Contrato universal de objetivo web para QCC."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit


SITE_TARGET_SCHEMA_VERSION = 1


class SiteTargetMode(str, Enum):
    """Modo funcional de uso de una web."""

    PASSIVE_INSPECTION = "PASSIVE_INSPECTION"
    MANAGED_EXECUTION = "MANAGED_EXECUTION"


class SiteEnvironment(str, Enum):
    """Entorno de una automatización gobernada."""

    LAB = "LAB"
    REAL = "REAL"


class SiteTargetConfigurationError(
    ValueError,
):
    """Configuración inválida de SiteTarget."""


def _normalize_enum(
    value,
    enum_type,
    *,
    field_name,
    allow_none=False,
):
    if value is None and allow_none:
        return None

    if isinstance(
        value,
        enum_type,
    ):
        return value

    normalized = str(
        value
        or ""
    ).strip().upper()

    if not normalized and allow_none:
        return None

    try:
        return enum_type(
            normalized
        )

    except ValueError as exc:
        raise SiteTargetConfigurationError(
            f"{field_name} inválido: {value!r}"
        ) from exc


def _normalize_site_code(
    value,
):
    if value is None:
        return None

    normalized = str(
        value
        or ""
    ).strip().upper()

    return normalized or None


def _origin_from_parts(
    parts,
):
    scheme = (
        parts.scheme
        .strip()
        .lower()
    )

    host = (
        parts.hostname
        or ""
    ).strip().lower()

    if ":" in host:
        host_for_origin = (
            f"[{host}]"
        )
    else:
        host_for_origin = host

    try:
        port = parts.port

    except ValueError as exc:
        raise SiteTargetConfigurationError(
            "SITE_TARGET_PORT_INVALID"
        ) from exc

    default_port = (
        80
        if scheme == "http"
        else 443
    )

    if (
        port is not None
        and port != default_port
    ):
        host_for_origin += (
            f":{port}"
        )

    return (
        f"{scheme}://"
        f"{host_for_origin}"
    )


@dataclass(
    frozen=True,
    slots=True,
)
class SiteTarget:
    """
    Objetivo web universal de QCC.

    PASSIVE_INSPECTION:
        puede utilizarse sobre cualquier web HTTP/HTTPS.

    MANAGED_EXECUTION:
        exige site_code y environment explícitos.

    ``url`` es runtime-only y puede contener query.
    ``to_public_dict`` nunca publica query ni fragment.
    """

    url: str

    mode: SiteTargetMode = (
        SiteTargetMode.PASSIVE_INSPECTION
    )

    site_code: str | None = None

    environment: (
        SiteEnvironment
        | None
    ) = None

    def __post_init__(
        self,
    ):
        url = str(
            self.url
            or ""
        ).strip()

        if not url:
            raise SiteTargetConfigurationError(
                "SITE_TARGET_URL_REQUIRED"
            )

        parts = urlsplit(
            url
        )

        scheme = (
            parts.scheme
            .strip()
            .lower()
        )

        if scheme not in {
            "http",
            "https",
        }:
            raise SiteTargetConfigurationError(
                "SITE_TARGET_SCHEME_INVALID"
            )

        if not parts.hostname:
            raise SiteTargetConfigurationError(
                "SITE_TARGET_HOST_REQUIRED"
            )

        if (
            parts.username is not None
            or parts.password is not None
        ):
            raise SiteTargetConfigurationError(
                "SITE_TARGET_CREDENTIALS_FORBIDDEN"
            )

        mode = _normalize_enum(
            self.mode,
            SiteTargetMode,
            field_name="mode",
        )

        environment = (
            _normalize_enum(
                self.environment,
                SiteEnvironment,
                field_name="environment",
                allow_none=True,
            )
        )

        site_code = (
            _normalize_site_code(
                self.site_code
            )
        )

        if (
            mode
            == SiteTargetMode.MANAGED_EXECUTION
        ):
            if not site_code:
                raise SiteTargetConfigurationError(
                    "SITE_TARGET_SITE_CODE_REQUIRED"
                )

            if environment is None:
                raise SiteTargetConfigurationError(
                    "SITE_TARGET_ENVIRONMENT_REQUIRED"
                )

        object.__setattr__(
            self,
            "url",
            url,
        )

        object.__setattr__(
            self,
            "mode",
            mode,
        )

        object.__setattr__(
            self,
            "site_code",
            site_code,
        )

        object.__setattr__(
            self,
            "environment",
            environment,
        )

    @property
    def origin(
        self,
    ):
        return _origin_from_parts(
            urlsplit(
                self.url
            )
        )

    @property
    def host(
        self,
    ):
        return str(
            urlsplit(
                self.url
            ).hostname
            or ""
        ).lower()

    @property
    def pathname(
        self,
    ):
        return (
            urlsplit(
                self.url
            ).path
            or "/"
        )

    @property
    def has_query(
        self,
    ):
        return bool(
            urlsplit(
                self.url
            ).query
        )

    def to_public_dict(
        self,
    ):
        """
        Representación segura para contratos/logs.

        No expone query, fragment ni credenciales.
        """

        return {
            "schema_version":
                SITE_TARGET_SCHEMA_VERSION,

            "mode":
                self.mode.value,

            "site_code":
                self.site_code,

            "environment":
                (
                    self.environment.value
                    if self.environment
                    is not None
                    else None
                ),

            "origin":
                self.origin,

            "host":
                self.host,

            "pathname":
                self.pathname,

            "has_query":
                self.has_query,
        }
