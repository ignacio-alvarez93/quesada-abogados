"""Registro genérico de gobierno gestionado por sitio.

Resuelve:

URL viva + site_code
    ->
environment
ManagedSiteProfile
SiteInteractionPolicy
SiteTarget(MANAGED_EXECUTION)

No gobierna acciones.
No ejecuta navegador.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

from .managed_execution import (
    ManagedSiteProfile,
)
from .site_interaction_policy import (
    SiteInteractionPolicy,
)
from .site_target import (
    SiteEnvironment,
    SiteTarget,
    SiteTargetMode,
)


ProfileBuilder = Callable[
    [SiteEnvironment],
    ManagedSiteProfile,
]

PolicyBuilder = Callable[
    [],
    SiteInteractionPolicy,
]


def _site_code(
    value,
):
    normalized = str(
        value
        or ""
    ).strip().upper()

    if not normalized:
        raise ValueError(
            "QCC_MANAGED_GOVERNANCE_SITE_CODE_REQUIRED"
        )

    return normalized


def _environment(
    value,
):
    if isinstance(
        value,
        SiteEnvironment,
    ):
        return value

    try:
        return SiteEnvironment(
            str(
                value
                or ""
            ).strip().upper()
        )

    except ValueError as exc:
        raise ValueError(
            "QCC_MANAGED_GOVERNANCE_ENVIRONMENT_INVALID"
        ) from exc


def _origin(
    value,
):
    raw = str(
        value
        or ""
    ).strip()

    parsed = urlsplit(
        raw
    )

    if (
        parsed.scheme.lower()
        not in {
            "http",
            "https",
        }
        or not parsed.hostname
    ):
        raise ValueError(
            "QCC_MANAGED_GOVERNANCE_ORIGIN_INVALID"
        )

    if (
        parsed.path
        not in {
            "",
            "/",
        }
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(
            "QCC_MANAGED_GOVERNANCE_ORIGIN_INVALID"
        )

    # Reutilizamos la normalización universal
    # de origin de SiteTarget.
    return SiteTarget(
        url=raw
    ).origin


def _url_origin(
    value,
):
    try:
        return SiteTarget(
            url=value
        ).origin

    except Exception as exc:
        raise ValueError(
            "QCC_MANAGED_GOVERNANCE_URL_INVALID"
        ) from exc


@dataclass(
    frozen=True,
    slots=True,
)
class ManagedSiteGovernanceOrigin:
    environment: SiteEnvironment
    origin: str

    def __post_init__(
        self,
    ):
        object.__setattr__(
            self,
            "environment",
            _environment(
                self.environment
            ),
        )

        object.__setattr__(
            self,
            "origin",
            _origin(
                self.origin
            ),
        )


@dataclass(
    frozen=True,
    slots=True,
)
class ManagedSiteGovernanceRegistration:
    """Configuración genérica de un sitio gobernable."""

    site_code: str

    origins: tuple[
        ManagedSiteGovernanceOrigin,
        ...,
    ]

    profile_builder: ProfileBuilder
    policy_builder: PolicyBuilder

    def __post_init__(
        self,
    ):
        site_code = _site_code(
            self.site_code
        )

        if not callable(
            self.profile_builder
        ):
            raise TypeError(
                "QCC_MANAGED_GOVERNANCE_PROFILE_BUILDER_INVALID"
            )

        if not callable(
            self.policy_builder
        ):
            raise TypeError(
                "QCC_MANAGED_GOVERNANCE_POLICY_BUILDER_INVALID"
            )

        origins = tuple(
            self.origins
            or ()
        )

        if not origins:
            raise ValueError(
                "QCC_MANAGED_GOVERNANCE_ORIGINS_REQUIRED"
            )

        for item in origins:
            if not isinstance(
                item,
                ManagedSiteGovernanceOrigin,
            ):
                raise TypeError(
                    "QCC_MANAGED_GOVERNANCE_ORIGIN_REGISTRATION_INVALID"
                )

        normalized_origins = [
            item.origin
            for item in origins
        ]

        if (
            len(
                set(
                    normalized_origins
                )
            )
            != len(
                normalized_origins
            )
        ):
            raise ValueError(
                "QCC_MANAGED_GOVERNANCE_ORIGIN_DUPLICATE"
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

    def environment_for_origin(
        self,
        origin,
    ):
        normalized = _origin(
            origin
        )

        for item in self.origins:
            if (
                item.origin
                == normalized
            ):
                return item.environment

        return None


@dataclass(
    frozen=True,
    slots=True,
)
class ResolvedManagedSiteGovernance:
    """Resolución runtime-only del gobierno de un sitio."""

    site_code: str
    environment: SiteEnvironment

    target: SiteTarget
    profile: ManagedSiteProfile
    policy: SiteInteractionPolicy


class ManagedSiteGovernanceRegistry:
    """Registro provider-agnostic de sitios gobernables."""

    def __init__(
        self,
    ):
        self._registrations = {}
        self._origin_index = {}

    def register(
        self,
        registration,
    ):
        if not isinstance(
            registration,
            ManagedSiteGovernanceRegistration,
        ):
            raise TypeError(
                "QCC_MANAGED_GOVERNANCE_REGISTRATION_INVALID"
            )

        site_code = (
            registration.site_code
        )

        if (
            site_code
            in self._registrations
        ):
            raise ValueError(
                "QCC_MANAGED_GOVERNANCE_SITE_ALREADY_REGISTERED:"
                + site_code
            )

        for item in registration.origins:
            owner = (
                self._origin_index
                .get(
                    item.origin
                )
            )

            if owner is not None:
                raise ValueError(
                    "QCC_MANAGED_GOVERNANCE_ORIGIN_ALREADY_REGISTERED:"
                    + item.origin
                    + ":"
                    + owner
                )

        self._registrations[
            site_code
        ] = registration

        for item in registration.origins:
            self._origin_index[
                item.origin
            ] = site_code

    def get_by_site_code(
        self,
        site_code,
    ):
        return self._registrations.get(
            _site_code(
                site_code
            )
        )

    def resolve(
        self,
        *,
        url,
        site_code,
    ):
        """Resuelve configuración gestionada desde URL viva.

        Una URL no registrada devuelve None.

        Un origin registrado para otro site_code
        también devuelve None.

        No existe fallback permisivo.
        """

        expected_site = _site_code(
            site_code
        )

        origin = _url_origin(
            url
        )

        owner = self._origin_index.get(
            origin
        )

        if (
            owner is None
            or owner != expected_site
        ):
            return None

        registration = (
            self._registrations[
                owner
            ]
        )

        environment = (
            registration
            .environment_for_origin(
                origin
            )
        )

        if environment is None:
            return None

        profile = (
            registration
            .profile_builder(
                environment
            )
        )

        policy = (
            registration
            .policy_builder()
        )

        if not isinstance(
            profile,
            ManagedSiteProfile,
        ):
            raise TypeError(
                "QCC_MANAGED_GOVERNANCE_PROFILE_INVALID"
            )

        if not isinstance(
            policy,
            SiteInteractionPolicy,
        ):
            raise TypeError(
                "QCC_MANAGED_GOVERNANCE_POLICY_INVALID"
            )

        if (
            profile.site_code
            != owner
            or policy.site_code
            != owner
            or profile.environment
            != environment
            or profile.interaction_policy
            != policy.policy_code
        ):
            raise ValueError(
                "QCC_MANAGED_GOVERNANCE_CONFIGURATION_MISMATCH"
            )

        target = SiteTarget(
            url=url,
            mode=(
                SiteTargetMode
                .MANAGED_EXECUTION
            ),
            site_code=owner,
            environment=environment,
        )

        return ResolvedManagedSiteGovernance(
            site_code=owner,
            environment=environment,
            target=target,
            profile=profile,
            policy=policy,
        )

    def registrations(
        self,
    ):
        return tuple(
            self._registrations[
                key
            ]
            for key
            in sorted(
                self._registrations
            )
        )
