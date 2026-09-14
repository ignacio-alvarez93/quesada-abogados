"""Runtime-only scope for QCC web observation.

An observation scope is NOT a PresentationSession.

It exists so Site Architecture / AUTO TWIN can correlate:

    CURRENT A
    + trusted human action
    + CURRENT B

without manufacturing business presentation state.

Legacy contracts still expose a field named ``session_id``.
During the compatibility phase that field may carry ``scope_id``.
"""

from __future__ import annotations

from dataclasses import (
    dataclass,
)


QCC_OBSERVATION_SCOPE_MODE_DISCOVERY = "DISCOVERY"
QCC_OBSERVATION_SCOPE_MODE_OBSERVATION = "OBSERVATION"

_QCC_OBSERVATION_SCOPE_MODES = {
    QCC_OBSERVATION_SCOPE_MODE_DISCOVERY,
    QCC_OBSERVATION_SCOPE_MODE_OBSERVATION,
}


def _required_text(
    value,
    error,
):
    normalized = str(
        value
        or ""
    ).strip()

    if not normalized:
        raise ValueError(
            error
        )

    return normalized


@dataclass(
    frozen=True,
    slots=True,
)
class QccObservationScope:
    """Identity boundary for non-business browser observation."""

    scope_id: str
    browser_profile_key: str
    site_code: str
    environment: str
    mode: str = (
        QCC_OBSERVATION_SCOPE_MODE_OBSERVATION
    )

    def __post_init__(
        self,
    ) -> None:
        scope_id = _required_text(
            self.scope_id,
            "QCC_OBSERVATION_SCOPE_ID_REQUIRED",
        )

        browser_profile_key = _required_text(
            self.browser_profile_key,
            "QCC_OBSERVATION_SCOPE_PROFILE_REQUIRED",
        )

        site_code = _required_text(
            self.site_code,
            "QCC_OBSERVATION_SCOPE_SITE_REQUIRED",
        ).upper()

        environment = _required_text(
            getattr(
                self.environment,
                "value",
                self.environment,
            ),
            "QCC_OBSERVATION_SCOPE_ENVIRONMENT_REQUIRED",
        ).upper()

        mode = _required_text(
            self.mode,
            "QCC_OBSERVATION_SCOPE_MODE_REQUIRED",
        ).upper()

        if mode not in _QCC_OBSERVATION_SCOPE_MODES:
            raise ValueError(
                "QCC_OBSERVATION_SCOPE_MODE_INVALID"
            )

        object.__setattr__(
            self,
            "scope_id",
            scope_id,
        )

        object.__setattr__(
            self,
            "browser_profile_key",
            browser_profile_key,
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
            "mode",
            mode,
        )

    # --------------------------------------------------------
    # COMPATIBILITY ALIASES
    #
    # Existing runtime-only observation contracts currently
    # use session_id/provider names.
    #
    # This does NOT make this object a PresentationSession.
    # --------------------------------------------------------

    @property
    def session_id(
        self,
    ) -> str:
        return self.scope_id

    @property
    def provider(
        self,
    ) -> str:
        return self.site_code


def build_profile_observation_scope(
    *,
    browser_profile_key,
    site_code,
    environment,
    discovery=False,
) -> QccObservationScope:
    profile = _required_text(
        browser_profile_key,
        "QCC_OBSERVATION_SCOPE_PROFILE_REQUIRED",
    )

    site = _required_text(
        site_code,
        "QCC_OBSERVATION_SCOPE_SITE_REQUIRED",
    ).upper()

    env = _required_text(
        getattr(
            environment,
            "value",
            environment,
        ),
        "QCC_OBSERVATION_SCOPE_ENVIRONMENT_REQUIRED",
    ).upper()

    mode = (
        QCC_OBSERVATION_SCOPE_MODE_DISCOVERY
        if discovery
        else QCC_OBSERVATION_SCOPE_MODE_OBSERVATION
    )

    return QccObservationScope(
        scope_id=(
            "qcc-observation::"
            + profile
            + "::"
            + site
            + "::"
            + env
        ),
        browser_profile_key=profile,
        site_code=site,
        environment=env,
        mode=mode,
    )
