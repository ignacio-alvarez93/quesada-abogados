"""Registry multi-browser para QCC.

La identidad persistente de un navegador gestionado
es ``profile_key``.

``session_id`` continúa identificando una ejecución
concreta dentro de ese perfil.

Cada perfil posee su propio QccContextStore para impedir
que dos navegadores simultáneos se sobrescriban entre sí.
"""

from __future__ import annotations

import threading
from typing import Callable

from backend.qcc.context.store import (
    QccContextStore,
)
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
    QccPresentationSession,
)


class QccBrowserRegistry:
    """Registry thread-safe de contextos QCC por profile_key."""

    def __init__(
        self,
        *,
        store_factory: (
            Callable[[], QccContextStore]
            | None
        ) = None,
    ) -> None:
        self._lock = threading.RLock()

        self._store_factory = (
            store_factory
            or QccContextStore
        )

        self._stores: dict[
            str,
            QccContextStore,
        ] = {}

        self._session_profiles: dict[
            str,
            str,
        ] = {}

        self._profile_modes: dict[
            str,
            str,
        ] = {}

        self._revision = 0


    @staticmethod
    def normalize_profile_key(
        profile_key,
    ) -> str:
        value = str(
            profile_key
            or ""
        ).strip()

        if not value:
            raise ValueError(
                "QCC_BROWSER_PROFILE_KEY_REQUIRED"
            )

        return value


    @staticmethod
    def normalize_session_id(
        session_id,
    ) -> str:
        value = str(
            session_id
            or ""
        ).strip()

        if not value:
            raise ValueError(
                "QCC_BROWSER_SESSION_ID_REQUIRED"
            )

        return value


    @staticmethod
    def normalize_browser_session_mode(
        mode,
    ) -> str:
        value = str(
            mode
            or ""
        ).strip().upper()

        if value not in {
            "EPHEMERAL",
            "PERSISTENT",
            "ASSISTED",
        }:
            raise ValueError(
                "QCC_BROWSER_SESSION_MODE_INVALID"
            )

        return value


    def set_profile_mode(
        self,
        *,
        profile_key,
        mode,
    ) -> int:
        key = self.normalize_profile_key(
            profile_key
        )

        normalized_mode = (
            self.normalize_browser_session_mode(
                mode
            )
        )

        with self._lock:
            store = self._stores.get(
                key
            )

            if store is None:
                store = self._store_factory()

                if not isinstance(
                    store,
                    QccContextStore,
                ):
                    raise TypeError(
                        "QCC_BROWSER_CONTEXT_STORE_INVALID"
                    )

                self._stores[
                    key
                ] = store

                self._revision += 1

            previous = (
                self._profile_modes.get(
                    key
                )
            )

            if previous == normalized_mode:
                return self._revision

            self._profile_modes[
                key
            ] = normalized_mode

            self._revision += 1

            return self._revision


    def get_profile_mode(
        self,
        profile_key,
    ) -> str | None:
        key = self.normalize_profile_key(
            profile_key
        )

        with self._lock:
            return self._profile_modes.get(
                key
            )


    @property
    def revision(
        self,
    ) -> int:
        with self._lock:
            return self._revision


    def profile_keys(
        self,
    ) -> tuple[str, ...]:
        with self._lock:
            return tuple(
                sorted(
                    self._stores
                )
            )


    def get_store(
        self,
        profile_key,
    ) -> QccContextStore | None:
        key = self.normalize_profile_key(
            profile_key
        )

        with self._lock:
            return self._stores.get(
                key
            )


    def get_or_create_store(
        self,
        profile_key,
    ) -> QccContextStore:
        key = self.normalize_profile_key(
            profile_key
        )

        with self._lock:
            store = self._stores.get(
                key
            )

            if store is None:
                store = self._store_factory()

                if not isinstance(
                    store,
                    QccContextStore,
                ):
                    raise TypeError(
                        "QCC_BROWSER_CONTEXT_STORE_INVALID"
                    )

                self._stores[key] = store
                self._revision += 1

            return store


    def get_store_for_session(
        self,
        session_id,
    ) -> QccContextStore | None:
        normalized_session_id = (
            self.normalize_session_id(
                session_id
            )
        )

        with self._lock:
            profile_key = (
                self._session_profiles.get(
                    normalized_session_id
                )
            )

            if profile_key is None:
                return None

            return self._stores.get(
                profile_key
            )


    def get_profile_for_session(
        self,
        session_id,
    ) -> str | None:
        normalized_session_id = (
            self.normalize_session_id(
                session_id
            )
        )

        with self._lock:
            return self._session_profiles.get(
                normalized_session_id
            )


    def set_active_session(
        self,
        *,
        profile_key,
        session: QccPresentationSession,
    ) -> int:
        key = self.normalize_profile_key(
            profile_key
        )

        if not isinstance(
            session,
            QccPresentationSession,
        ):
            raise TypeError(
                "QCC_BROWSER_SESSION_TYPE_INVALID"
            )

        session_id = (
            self.normalize_session_id(
                session.session_id
            )
        )

        with self._lock:
            owner = (
                self._session_profiles.get(
                    session_id
                )
            )

            if (
                owner is not None
                and owner != key
            ):
                raise ValueError(
                    "QCC_BROWSER_SESSION_PROFILE_CONFLICT"
                )

            store = self._stores.get(
                key
            )

            if store is None:
                store = self._store_factory()

                if not isinstance(
                    store,
                    QccContextStore,
                ):
                    raise TypeError(
                        "QCC_BROWSER_CONTEXT_STORE_INVALID"
                    )

                self._stores[key] = store

            previous = (
                store.get_active_session()
            )

            if (
                previous is not None
                and previous.session_id
                != session_id
            ):
                previous_owner = (
                    self._session_profiles.get(
                        previous.session_id
                    )
                )

                if previous_owner == key:
                    self._session_profiles.pop(
                        previous.session_id,
                        None,
                    )

            store.set_active_session(
                session
            )

            self._session_profiles[
                session_id
            ] = key

            self._revision += 1

            return self._revision


    def clear_active_session(
        self,
        *,
        profile_key,
        session_id: str | None = None,
    ) -> bool:
        key = self.normalize_profile_key(
            profile_key
        )

        with self._lock:
            store = self._stores.get(
                key
            )

            if store is None:
                return False

            current = (
                store.get_active_session()
            )

            if current is None:
                return False

            if (
                session_id is not None
                and current.session_id
                != self.normalize_session_id(
                    session_id
                )
            ):
                return False

            cleared = (
                store.clear_active_session(
                    session_id=current.session_id
                )
            )

            if not cleared:
                return False

            owner = (
                self._session_profiles.get(
                    current.session_id
                )
            )

            if owner == key:
                self._session_profiles.pop(
                    current.session_id,
                    None,
                )

            self._revision += 1

            return True


    def snapshot(
        self,
        profile_key,
    ) -> dict:
        key = self.normalize_profile_key(
            profile_key
        )

        with self._lock:
            store = self._stores.get(
                key
            )

            registry_revision = (
                self._revision
            )

            if store is None:
                return {
                    "protocol_version":
                        QCC_PROTOCOL_VERSION,

                    "registry_revision":
                        registry_revision,

                    "browser_profile_key":
                        key,

                    "browser_session_mode":
                        self._profile_modes.get(
                            key
                        ),

                    "revision":
                        0,

                    "active":
                        False,

                    "active_session":
                        None,

                    "live_navigation":
                        None,
                }

            payload = store.snapshot()

            return {
                **payload,

                "registry_revision":
                    registry_revision,

                "browser_profile_key":
                    key,

                "browser_session_mode":
                    self._profile_modes.get(
                        key
                    ),
            }


    def snapshots(
        self,
    ) -> list[dict]:
        with self._lock:
            keys = sorted(
                self._stores
            )

        return [
            self.snapshot(
                key
            )
            for key in keys
        ]
