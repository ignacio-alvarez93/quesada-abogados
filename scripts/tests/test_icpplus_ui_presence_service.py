from datetime import (
    datetime,
    timedelta,
    timezone,
)

from backend.services import (
    icpplus_ui_presence_service
    as presence,
)


def test_ui_heartbeat_roundtrip(
    tmp_path,
    monkeypatch,
):
    path = (
        tmp_path
        / "heartbeat.json"
    )

    monkeypatch.setattr(
        presence,
        "HEARTBEAT_PATH",
        path,
    )

    now = datetime(
        2026,
        8,
        21,
        12,
        0,
        tzinfo=timezone.utc,
    )

    presence.mark_alive(
        "ERP-TEST",
        now=now,
    )

    assert presence.is_alive(
        now=(
            now
            + timedelta(
                seconds=4
            )
        ),
        max_age_seconds=5,
    )


def test_ui_heartbeat_expires(
    tmp_path,
    monkeypatch,
):
    path = (
        tmp_path
        / "heartbeat.json"
    )

    monkeypatch.setattr(
        presence,
        "HEARTBEAT_PATH",
        path,
    )

    now = datetime(
        2026,
        8,
        21,
        12,
        0,
        tzinfo=timezone.utc,
    )

    presence.mark_alive(
        "ERP-TEST",
        now=now,
    )

    assert not presence.is_alive(
        now=(
            now
            + timedelta(
                seconds=6
            )
        ),
        max_age_seconds=5,
    )


def test_old_ui_instance_cannot_clear_new_one(
    tmp_path,
    monkeypatch,
):
    path = (
        tmp_path
        / "heartbeat.json"
    )

    monkeypatch.setattr(
        presence,
        "HEARTBEAT_PATH",
        path,
    )

    presence.mark_alive(
        "ERP-NEW"
    )

    assert (
        presence.clear(
            "ERP-OLD"
        )
        is False
    )

    assert path.exists()

    assert (
        presence.clear(
            "ERP-NEW"
        )
        is True
    )

    assert not path.exists()


def test_mark_alive_retries_transient_windows_permission_error(
    tmp_path,
    monkeypatch,
):
    from pathlib import Path

    path = (
        tmp_path
        / "heartbeat.json"
    )

    monkeypatch.setattr(
        presence,
        "HEARTBEAT_PATH",
        path,
    )

    original_replace = (
        Path.replace
    )

    calls = {
        "count":
            0,
    }

    def flaky_replace(
        self,
        target,
    ):
        calls[
            "count"
        ] += 1

        if (
            calls[
                "count"
            ]
            == 1
        ):
            raise PermissionError(
                13,
                "Acceso denegado",
            )

        return original_replace(
            self,
            target,
        )

    monkeypatch.setattr(
        Path,
        "replace",
        flaky_replace,
    )

    presence.mark_alive(
        "ERP-RETRY-TEST"
    )

    assert (
        calls[
            "count"
        ]
        == 2
    )

    heartbeat = (
        presence.get_heartbeat()
    )

    assert (
        heartbeat[
            "instance_id"
        ]
        == "ERP-RETRY-TEST"
    )
