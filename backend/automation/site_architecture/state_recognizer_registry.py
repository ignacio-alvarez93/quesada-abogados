"""Registro genérico de reconocedores semánticos de estado."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit


StateRecognizer = Callable[
    [object],
    object,
]

ArchitectureScopeResolver = Callable[
    [object, dict],
    object,
]


def _normalized_site_code(
    value,
):
    normalized = str(
        value
        or ""
    ).strip().upper()

    if not normalized:
        raise ValueError(
            "QCC_STATE_RECOGNIZER_SITE_CODE_REQUIRED"
        )

    return normalized


def _normalized_architecture_scope(
    value,
):
    normalized = str(
        value
        or ""
    ).strip().upper()

    if not normalized:
        return None

    if (
        len(normalized) > 128
        or not normalized[0].isalpha()
        or any(
            character
            not in (
                "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                "0123456789_.:/-"
            )
            for character
            in normalized
        )
    ):
        raise ValueError(
            "QCC_ARCHITECTURE_SCOPE_INVALID"
        )

    return normalized


def _normalized_origin(
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
        parsed.scheme
        not in {
            "http",
            "https",
        }
        or not parsed.netloc
    ):
        raise ValueError(
            "QCC_STATE_RECOGNIZER_ORIGIN_INVALID"
        )

    return (
        f"{parsed.scheme.lower()}://"
        f"{parsed.netloc.lower()}"
    )


@dataclass(
    frozen=True,
    slots=True,
)
class SiteStateRecognizerRegistration:
    site_code: str
    origins: tuple[str, ...]
    recognizer: StateRecognizer

    def __post_init__(
        self,
    ):
        site_code = (
            _normalized_site_code(
                self.site_code
            )
        )

        if not callable(
            self.recognizer
        ):
            raise TypeError(
                "QCC_STATE_RECOGNIZER_INVALID"
            )

        origins = tuple(
            dict.fromkeys(
                _normalized_origin(
                    origin
                )
                for origin
                in self.origins
            )
        )

        if not origins:
            raise ValueError(
                "QCC_STATE_RECOGNIZER_ORIGIN_REQUIRED"
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


class SiteStateRecognizerRegistry:
    """Resuelve recognizers por origin sin conocer sitios concretos."""

    def __init__(
        self,
    ):
        self._registrations: dict[
            str,
            SiteStateRecognizerRegistration,
        ] = {}

        self._origin_index: dict[
            str,
            str,
        ] = {}

        self._retention_scope_resolvers: dict[
            str,
            ArchitectureScopeResolver,
        ] = {}

    def register(
        self,
        registration:
            SiteStateRecognizerRegistration,
    ) -> None:
        if not isinstance(
            registration,
            SiteStateRecognizerRegistration,
        ):
            raise TypeError(
                "QCC_STATE_RECOGNIZER_REGISTRATION_INVALID"
            )

        site_code = (
            registration.site_code
        )

        if (
            site_code
            in self._registrations
        ):
            raise ValueError(
                "QCC_STATE_RECOGNIZER_SITE_ALREADY_REGISTERED:"
                f"{site_code}"
            )

        for origin in (
            registration.origins
        ):
            owner = (
                self._origin_index
                .get(
                    origin
                )
            )

            if owner is not None:
                raise ValueError(
                    "QCC_STATE_RECOGNIZER_ORIGIN_ALREADY_REGISTERED:"
                    f"{origin}:{owner}"
                )

        self._registrations[
            site_code
        ] = registration

        for origin in (
            registration.origins
        ):
            self._origin_index[
                origin
            ] = site_code

    def register_retention_scope_resolver(
        self,
        *,
        site_code,
        resolver,
    ) -> None:
        normalized_site_code = (
            _normalized_site_code(
                site_code
            )
        )

        if (
            normalized_site_code
            not in self._registrations
        ):
            raise ValueError(
                "QCC_ARCHITECTURE_SCOPE_SITE_NOT_REGISTERED:"
                f"{normalized_site_code}"
            )

        if not callable(
            resolver
        ):
            raise TypeError(
                "QCC_ARCHITECTURE_SCOPE_RESOLVER_INVALID"
            )

        if (
            normalized_site_code
            in self._retention_scope_resolvers
        ):
            raise ValueError(
                "QCC_ARCHITECTURE_SCOPE_RESOLVER_ALREADY_REGISTERED:"
                f"{normalized_site_code}"
            )

        self._retention_scope_resolvers[
            normalized_site_code
        ] = resolver


    def resolve_architecture_scope(
        self,
        snapshot,
        observation,
    ):
        registration = (
            self.resolve_snapshot(
                snapshot
            )
        )

        if registration is None:
            return None

        resolver = (
            self._retention_scope_resolvers
            .get(
                registration.site_code
            )
        )

        if resolver is None:
            return None

        raw_scope = resolver(
            snapshot,
            observation,
        )

        return (
            _normalized_architecture_scope(
                raw_scope
            )
        )


    def get_by_site_code(
        self,
        site_code,
    ):
        normalized = (
            _normalized_site_code(
                site_code
            )
        )

        return self._registrations.get(
            normalized
        )

    def resolve_url(
        self,
        url,
    ):
        origin = (
            _normalized_origin(
                url
            )
        )

        site_code = (
            self._origin_index.get(
                origin
            )
        )

        if site_code is None:
            return None

        return self._registrations[
            site_code
        ]

    def resolve_snapshot(
        self,
        snapshot,
    ):
        page = (
            getattr(
                snapshot,
                "page",
                None,
            )
        )

        if page is not None:
            url = getattr(
                page,
                "url",
                None,
            )

            origin = getattr(
                page,
                "origin",
                None,
            )

        elif isinstance(
            snapshot,
            dict,
        ):
            page_data = (
                snapshot.get(
                    "page"
                )
                or {}
            )

            url = (
                page_data.get(
                    "url"
                )
            )

            origin = (
                page_data.get(
                    "origin"
                )
            )

        else:
            raise ValueError(
                "QCC_STATE_RECOGNIZER_SNAPSHOT_INVALID"
            )

        candidate = (
            url
            or origin
        )

        if not candidate:
            return None

        return self.resolve_url(
            candidate
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
