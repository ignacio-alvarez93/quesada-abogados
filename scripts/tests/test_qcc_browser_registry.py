from datetime import (
    datetime,
    timezone,
)

import pytest

from backend.qcc.context.browser_registry import (
    QccBrowserRegistry,
)
from backend.qcc.contracts.protocol import (
    QccPresentationSession,
    QccPresentationStatus,
)


def _session(
    session_id,
    *,
    provider="TEST",
):
    return QccPresentationSession(
        session_id=session_id,
        expedient_id=1,
        client_id=1,
        procedure="TEST_PROCEDURE",
        provider=provider,
        runtime="SELENIUMBASE",
        started_at=datetime.now(
            timezone.utc
        ),
        status=(
            QccPresentationStatus
            .AUTOMATING
        ),
        current_step="RUNNING",
        progress=10,
    )


def test_registry_starts_empty():
    registry = QccBrowserRegistry()

    assert registry.revision == 0
    assert registry.profile_keys() == ()


def test_registry_keeps_two_profiles_active_simultaneously():
    registry = QccBrowserRegistry()

    first = _session(
        "session-a"
    )

    second = _session(
        "session-b"
    )

    registry.set_active_session(
        profile_key="profile-a",
        session=first,
    )

    registry.set_active_session(
        profile_key="profile-b",
        session=second,
    )

    snapshot_a = registry.snapshot(
        "profile-a"
    )

    snapshot_b = registry.snapshot(
        "profile-b"
    )

    assert snapshot_a["active"] is True
    assert snapshot_b["active"] is True

    assert (
        snapshot_a["active_session"][
            "session_id"
        ]
        == "session-a"
    )

    assert (
        snapshot_b["active_session"][
            "session_id"
        ]
        == "session-b"
    )


def test_session_resolves_to_exact_profile_store():
    registry = QccBrowserRegistry()

    session = _session(
        "session-lookup"
    )

    registry.set_active_session(
        profile_key="whatsapp_dev",
        session=session,
    )

    assert (
        registry.get_profile_for_session(
            "session-lookup"
        )
        == "whatsapp_dev"
    )

    store = (
        registry.get_store_for_session(
            "session-lookup"
        )
    )

    assert store is not None

    assert (
        store.get_active_session()
        .session_id
        == "session-lookup"
    )


def test_replacing_one_profile_does_not_touch_other_profile():
    registry = QccBrowserRegistry()

    registry.set_active_session(
        profile_key="profile-a",
        session=_session(
            "a-1"
        ),
    )

    registry.set_active_session(
        profile_key="profile-b",
        session=_session(
            "b-1"
        ),
    )

    registry.set_active_session(
        profile_key="profile-a",
        session=_session(
            "a-2"
        ),
    )

    assert (
        registry.snapshot(
            "profile-a"
        )["active_session"]["session_id"]
        == "a-2"
    )

    assert (
        registry.snapshot(
            "profile-b"
        )["active_session"]["session_id"]
        == "b-1"
    )

    assert (
        registry.get_profile_for_session(
            "a-1"
        )
        is None
    )


def test_same_session_cannot_belong_to_two_profiles():
    registry = QccBrowserRegistry()

    session = _session(
        "shared-session"
    )

    registry.set_active_session(
        profile_key="profile-a",
        session=session,
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_BROWSER_SESSION_PROFILE_CONFLICT"
        ),
    ):
        registry.set_active_session(
            profile_key="profile-b",
            session=session,
        )


def test_clear_is_scoped_to_one_profile():
    registry = QccBrowserRegistry()

    registry.set_active_session(
        profile_key="profile-a",
        session=_session(
            "a-1"
        ),
    )

    registry.set_active_session(
        profile_key="profile-b",
        session=_session(
            "b-1"
        ),
    )

    assert registry.clear_active_session(
        profile_key="profile-a",
        session_id="a-1",
    )

    assert (
        registry.snapshot(
            "profile-a"
        )["active"]
        is False
    )

    assert (
        registry.snapshot(
            "profile-b"
        )["active"]
        is True
    )


def test_unknown_profile_snapshot_is_inactive_without_registration():
    registry = QccBrowserRegistry()

    snapshot = registry.snapshot(
        "unknown-profile"
    )

    assert snapshot[
        "browser_profile_key"
    ] == "unknown-profile"

    assert snapshot["active"] is False
    assert snapshot["active_session"] is None
    assert snapshot["live_navigation"] is None

    assert registry.profile_keys() == ()


def test_registry_lists_profiles_deterministically():
    registry = QccBrowserRegistry()

    registry.set_active_session(
        profile_key="z-profile",
        session=_session(
            "z-session"
        ),
    )

    registry.set_active_session(
        profile_key="a-profile",
        session=_session(
            "a-session"
        ),
    )

    snapshots = (
        registry.snapshots()
    )

    assert [
        item["browser_profile_key"]
        for item in snapshots
    ] == [
        "a-profile",
        "z-profile",
    ]
