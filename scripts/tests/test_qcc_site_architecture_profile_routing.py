from datetime import (
    datetime,
    timezone,
)
from pathlib import Path

from backend.qcc.bridge.server import (
    _qcc_resolve_context_store_for_profile,
)
from backend.qcc.context.browser_registry import (
    QccBrowserRegistry,
)
from backend.qcc.context.store import (
    QccContextStore,
)
from backend.qcc.contracts.protocol import (
    QccPresentationSession,
    QccPresentationStatus,
)


SERVER = Path(
    "backend/qcc/bridge/server.py"
)


def _session(
    session_id,
):
    return QccPresentationSession(
        session_id=session_id,
        expedient_id=1,
        client_id=1,
        procedure="TEST",
        provider="MERCURIO",
        runtime="SELENIUMBASE_ASSISTED",
        started_at=datetime.now(
            timezone.utc
        ),
        status=(
            QccPresentationStatus
            .AUTOMATING
        ),
        current_step="RUNNING",
        progress=25,
        requires_user_action=False,
    )


def test_known_profile_resolves_exact_context_store():
    legacy = QccContextStore()
    registry = QccBrowserRegistry()

    session_a = _session(
        "session-a"
    )

    session_b = _session(
        "session-b"
    )

    registry.set_active_session(
        profile_key="profile-a",
        session=session_a,
    )

    registry.set_active_session(
        profile_key="profile-b",
        session=session_b,
    )

    legacy.set_active_session(
        session_b
    )

    resolved = (
        _qcc_resolve_context_store_for_profile(
            legacy_store=legacy,
            browser_registry=registry,
            browser_profile_key="profile-a",
        )
    )

    assert resolved is (
        registry.get_store(
            "profile-a"
        )
    )

    assert (
        resolved
        .get_active_session()
        .session_id
        == "session-a"
    )


def test_explicit_unknown_profile_never_falls_back_to_other_legacy_session():
    legacy = QccContextStore()
    registry = QccBrowserRegistry()

    legacy.set_active_session(
        _session(
            "session-b"
        )
    )

    resolved = (
        _qcc_resolve_context_store_for_profile(
            legacy_store=legacy,
            browser_registry=registry,
            browser_profile_key="profile-a",
        )
    )

    assert resolved is None

    assert (
        legacy
        .get_active_session()
        .session_id
        == "session-b"
    )


def test_missing_profile_preserves_legacy_compatibility():
    legacy = QccContextStore()
    registry = QccBrowserRegistry()

    assert (
        _qcc_resolve_context_store_for_profile(
            legacy_store=legacy,
            browser_registry=registry,
            browser_profile_key=None,
        )
        is legacy
    )

    assert (
        _qcc_resolve_context_store_for_profile(
            legacy_store=legacy,
            browser_registry=registry,
            browser_profile_key="",
        )
        is legacy
    )


def test_missing_registry_fails_closed_for_explicit_profile():
    legacy = QccContextStore()

    legacy.set_active_session(
        _session(
            "legacy-session"
        )
    )

    assert (
        _qcc_resolve_context_store_for_profile(
            legacy_store=legacy,
            browser_registry=None,
            browser_profile_key="profile-a",
        )
        is None
    )


def test_capture_resolves_profile_before_ingestor():
    text = SERVER.read_text(
        encoding="utf-8"
    )

    route_start = text.index(
        'if path == "/qcc/site-architecture/capture":'
    )

    route_end = text.index(
        "# POST /qcc/session",
        route_start,
    )

    block = text[
        route_start:
        route_end
    ]

    profile_read = block.index(
        'payload.get(\n'
        '                        "browser_profile_key"'
    )

    resolver = block.index(
        "_qcc_resolve_context_store_for_profile("
    )

    snapshot = block.index(
        "context_store.snapshot()"
    )

    ingest = block.index(
        "result = ingestor.ingest("
    )

    assert (
        profile_read
        < resolver
        < snapshot
        < ingest
    )


def test_profile_identity_is_routing_metadata_only():
    text = SERVER.read_text(
        encoding="utf-8"
    )

    route_start = text.index(
        'if path == "/qcc/site-architecture/capture":'
    )

    route_end = text.index(
        "# POST /qcc/session",
        route_start,
    )

    block = text[
        route_start:
        route_end
    ]

    assert (
        'capture["browser_profile_key"]'
        not in block
    )

    assert (
        "capture.get("
        + '"browser_profile_key"'
        not in block
    )

    assert (
        "browser_profile_key = str("
        in block
    )
