from pathlib import Path


WORKER = (
    Path(__file__)
    .resolve()
    .parents[1]
    / "icpplus_scheduler_worker.py"
)


def test_worker_is_independent_from_flet():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    assert "import flet" not in text
    assert "frontend." not in text


def test_worker_uses_productive_availability_service():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    assert (
        "IcpPlusAvailabilityService"
        in text
    )

    assert (
        ".check_availability("
        in text
    )

    assert (
        'office_scope="SINGLE"'
        in text
    )


def test_worker_persists_normal_result():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    assert (
        "icpplus_state_service"
        in text
    )

    assert (
        ".record_result("
        in text
    )


def test_worker_uses_scheduler_claim_and_finish():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    assert (
        ".claim_next_due("
        in text
    )

    assert (
        ".mark_run_finished("
        in text
    )


def test_worker_reconciles_missed_runs():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    assert (
        ".reconcile_overdue("
        in text
    )

    assert (
        ".record_warning("
        in text
    )


def test_worker_has_safe_isolated_dry_run():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    assert (
        'parser.add_argument(\n        "--dry-run"'
        in text
    )

    assert (
        "def dry_run_demo"
        in text
    )

    assert (
        "DATABASE=DISABLED"
        in text
    )

    assert (
        "CHROME=DISABLED"
        in text
    )

    assert (
        "REAL_BOT=DISABLED"
        in text
    )

    assert (
        "DRY_GLOBAL_COOLDOWN"
        in text
    )


def test_worker_has_single_instance_guard():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    assert (
        "SINGLE_INSTANCE_MUTEX_NAME"
        in text
    )

    assert (
        "CreateMutexW"
        in text
    )

    assert (
        "SECOND_INSTANCE_BLOCKED"
        in text
    )


def test_worker_uses_windows_notification_only_without_erp_ui():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    assert (
        "show_windows_notification"
        in text
    )

    assert (
        "icpplus_ui_presence_service"
        in text
    )

    assert (
        ".is_alive("
        in text
    )

    assert (
        "ERP_UI_ALIVE"
        in text
    )

    assert (
        "--notification-smoke"
        in text
    )
