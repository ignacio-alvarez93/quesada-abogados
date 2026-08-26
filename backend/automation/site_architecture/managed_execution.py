"""Autorización fail-closed de ejecución web gobernada QCC."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from .site_target import (
    SiteEnvironment,
    SiteTarget,
    SiteTargetMode,
)


MANAGED_EXECUTION_SCHEMA_VERSION = 1

MANAGED_EXECUTION_AUTHORIZED = (
    "AUTHORIZED"
)

MANAGED_EXECUTION_DENY = "DENY"


class ManagedSiteProfileConfigurationError(
    ValueError,
):
    """Configuración inválida de ManagedSiteProfile."""


def _text(value):
    return str(
        value
        or ""
    ).strip()


def _normalize_site_code(
    value,
):
    result = _text(
        value
    ).upper()

    if not result:
        raise ManagedSiteProfileConfigurationError(
            "MANAGED_SITE_CODE_REQUIRED"
        )

    return result


def _normalize_environment(
    value,
):
    if isinstance(
        value,
        SiteEnvironment,
    ):
        return value

    try:
        return SiteEnvironment(
            _text(
                value
            ).upper()
        )
    except ValueError as exc:
        raise ManagedSiteProfileConfigurationError(
            "MANAGED_ENVIRONMENT_INVALID"
        ) from exc


def _normalize_origin(
    value,
):
    raw = _text(
        value
    )

    if not raw:
        raise ManagedSiteProfileConfigurationError(
            "MANAGED_ORIGIN_INVALID"
        )

    parts = urlsplit(
        raw
    )

    if (
        parts.path not in {
            "",
            "/",
        }
        or parts.query
        or parts.fragment
    ):
        raise ManagedSiteProfileConfigurationError(
            "MANAGED_ORIGIN_MUST_BE_ORIGIN_ONLY"
        )

    try:
        target = SiteTarget(
            url=raw
        )
    except ValueError as exc:
        raise ManagedSiteProfileConfigurationError(
            "MANAGED_ORIGIN_INVALID"
        ) from exc

    return target.origin


def _normalize_path_prefix(
    value,
):
    path = _text(
        value
    )

    if (
        not path
        or not path.startswith("/")
        or "?" in path
        or "#" in path
    ):
        raise ManagedSiteProfileConfigurationError(
            "MANAGED_PATH_PREFIX_INVALID"
        )

    while (
        len(path) > 1
        and path.endswith("/")
    ):
        path = path[:-1]

    return path


def _normalize_policy(
    value,
):
    policy = _text(
        value
    ).upper()

    if not policy:
        raise ManagedSiteProfileConfigurationError(
            "MANAGED_INTERACTION_POLICY_REQUIRED"
        )

    return policy


def _normalize_capability(
    value,
):
    capability = _text(
        value
    ).upper()

    if not capability:
        raise ManagedSiteProfileConfigurationError(
            "MANAGED_CAPABILITY_INVALID"
        )

    return capability


def _normalize_many(
    values,
    *,
    normalizer,
    empty_error,
    allow_empty=False,
):
    if isinstance(
        values,
        str,
    ):
        values = (
            values,
        )

    if not isinstance(
        values,
        (
            list,
            tuple,
            set,
            frozenset,
        ),
    ):
        raise ManagedSiteProfileConfigurationError(
            empty_error
        )

    result = []

    for value in values:
        normalized = normalizer(
            value
        )

        if normalized not in result:
            result.append(
                normalized
            )

    if (
        not result
        and not allow_empty
    ):
        raise ManagedSiteProfileConfigurationError(
            empty_error
        )

    return tuple(
        result
    )


@dataclass(
    frozen=True,
    slots=True,
)
class ManagedSiteProfile:
    """
    Perfil de autorización para ejecución activa.

    Describe dónde puede trabajar un runtime gobernado.

    No ejecuta acciones.
    No conoce SeleniumBase.
    No conoce proveedores concretos.
    """

    site_code: str

    environment: SiteEnvironment

    allowed_origins: tuple[str, ...]

    allowed_path_prefixes: tuple[str, ...]

    interaction_policy: str

    capabilities: tuple[str, ...] = ()

    def __post_init__(
        self,
    ):
        site_code = (
            _normalize_site_code(
                self.site_code
            )
        )

        environment = (
            _normalize_environment(
                self.environment
            )
        )

        allowed_origins = (
            _normalize_many(
                self.allowed_origins,
                normalizer=(
                    _normalize_origin
                ),
                empty_error=(
                    "MANAGED_ALLOWED_ORIGINS_REQUIRED"
                ),
            )
        )

        allowed_path_prefixes = (
            _normalize_many(
                self.allowed_path_prefixes,
                normalizer=(
                    _normalize_path_prefix
                ),
                empty_error=(
                    "MANAGED_ALLOWED_PATHS_REQUIRED"
                ),
            )
        )

        interaction_policy = (
            _normalize_policy(
                self.interaction_policy
            )
        )

        capabilities = (
            _normalize_many(
                self.capabilities,
                normalizer=(
                    _normalize_capability
                ),
                empty_error=(
                    "MANAGED_CAPABILITY_INVALID"
                ),
                allow_empty=True,
            )
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

        object.__setattr__(
            self,
            "allowed_origins",
            allowed_origins,
        )

        object.__setattr__(
            self,
            "allowed_path_prefixes",
            allowed_path_prefixes,
        )

        object.__setattr__(
            self,
            "interaction_policy",
            interaction_policy,
        )

        object.__setattr__(
            self,
            "capabilities",
            capabilities,
        )

    def to_public_dict(
        self,
    ):
        return {
            "schema_version":
                MANAGED_EXECUTION_SCHEMA_VERSION,

            "site_code":
                self.site_code,

            "environment":
                self.environment.value,

            "allowed_origins":
                list(
                    self.allowed_origins
                ),

            "allowed_path_prefixes":
                list(
                    self.allowed_path_prefixes
                ),

            "interaction_policy":
                self.interaction_policy,

            "capabilities":
                list(
                    self.capabilities
                ),
        }


def _path_allowed(
    pathname,
    prefixes,
):
    pathname = (
        _text(
            pathname
        )
        or "/"
    )

    for prefix in prefixes:
        if prefix == "/":
            return True

        if pathname == prefix:
            return True

        if pathname.startswith(
            prefix + "/"
        ):
            return True

    return False


def _decision(
    target,
    profile,
    *,
    decision,
    reason,
):
    return {
        "schema_version":
            MANAGED_EXECUTION_SCHEMA_VERSION,

        "decision":
            decision,

        "authorized":
            (
                decision
                == MANAGED_EXECUTION_AUTHORIZED
            ),

        "reason":
            reason,

        "target":
            target.to_public_dict(),

        "profile":
            profile.to_public_dict(),
    }


def authorize_managed_target(
    target,
    profile,
):
    """
    Autoriza únicamente el contexto del sitio.

    AUTHORIZED NO autoriza ninguna acción DOM.

    Una acción concreta deberá superar además
    su propia política Action Safety.
    """

    if not isinstance(
        target,
        SiteTarget,
    ):
        raise ValueError(
            "MANAGED_TARGET_INVALID"
        )

    if not isinstance(
        profile,
        ManagedSiteProfile,
    ):
        raise ValueError(
            "MANAGED_PROFILE_INVALID"
        )

    if (
        target.mode
        != SiteTargetMode.MANAGED_EXECUTION
    ):
        return _decision(
            target,
            profile,
            decision=MANAGED_EXECUTION_DENY,
            reason="TARGET_NOT_MANAGED",
        )

    if (
        target.site_code
        != profile.site_code
    ):
        return _decision(
            target,
            profile,
            decision=MANAGED_EXECUTION_DENY,
            reason="SITE_CODE_MISMATCH",
        )

    if (
        target.environment
        != profile.environment
    ):
        return _decision(
            target,
            profile,
            decision=MANAGED_EXECUTION_DENY,
            reason="ENVIRONMENT_MISMATCH",
        )

    if (
        target.origin
        not in profile.allowed_origins
    ):
        return _decision(
            target,
            profile,
            decision=MANAGED_EXECUTION_DENY,
            reason="ORIGIN_NOT_ALLOWED",
        )

    if not _path_allowed(
        target.pathname,
        profile.allowed_path_prefixes,
    ):
        return _decision(
            target,
            profile,
            decision=MANAGED_EXECUTION_DENY,
            reason="PATH_NOT_ALLOWED",
        )

    return _decision(
        target,
        profile,
        decision=MANAGED_EXECUTION_AUTHORIZED,
        reason="MANAGED_TARGET_AUTHORIZED",
    )
