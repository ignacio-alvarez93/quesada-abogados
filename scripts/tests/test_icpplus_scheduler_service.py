import unittest
from datetime import (
    datetime,
    timedelta,
    timezone,
)

from backend.services import (
    icpplus_scheduler_service
    as scheduler,
)


class IcpPlusSchedulerServiceTest(
    unittest.TestCase
):
    def setUp(self):
        self.store = {}

        self.original_get = (
            scheduler
            .config_service
            .get_config
        )

        self.original_set = (
            scheduler
            .config_service
            .set_config
        )

        scheduler.config_service.get_config = (
            lambda key, default="":
                self.store.get(
                    key,
                    default,
                )
        )

        scheduler.config_service.set_config = (
            lambda key, value:
                self.store.__setitem__(
                    key,
                    value,
                )
        )

        self.now = datetime(
            2026,
            8,
            21,
            12,
            0,
            tzinfo=timezone.utc,
        )


    def tearDown(self):
        scheduler.config_service.get_config = (
            self.original_get
        )

        scheduler.config_service.set_config = (
            self.original_set
        )


    def create(
        self,
        *,
        office="CNP_OVIEDO",
        province="ASTURIAS",
        interval=15,
        duration=120,
    ):
        return scheduler.create_schedule(
            province_key=province,
            procedure_key=(
                "POLICIA_TOMA_HUELLAS_TIE"
            ),
            office_key=office,
            office_text=office,
            interval_minutes=interval,
            duration_minutes=duration,
            now=self.now,
        )


    def test_interval_below_15_is_rejected(
        self,
    ):
        with self.assertRaises(
            ValueError
        ):
            self.create(
                interval=14
            )


    def test_multiple_different_schedulers_allowed(
        self,
    ):
        self.create(
            office="CNP_OVIEDO"
        )

        self.create(
            office="CNP_LUARCA"
        )

        self.assertEqual(
            scheduler.active_count(),
            2,
        )


    def test_duplicate_active_target_rejected(
        self,
    ):
        self.create()

        with self.assertRaises(
            ValueError
        ):
            self.create()


    def test_first_run_is_after_interval(
        self,
    ):
        item = self.create(
            interval=15
        )

        self.assertEqual(
            datetime.fromisoformat(
                item[
                    "next_run_at"
                ]
            ),
            self.now
            + timedelta(
                minutes=15
            ),
        )


    def test_only_one_scheduler_can_be_claimed(
        self,
    ):
        self.create(
            office="CNP_OVIEDO"
        )

        self.create(
            office="CNP_LUARCA"
        )

        due_at = (
            self.now
            + timedelta(
                minutes=15
            )
        )

        first = (
            scheduler.claim_next_due(
                now=due_at
            )
        )

        second = (
            scheduler.claim_next_due(
                now=due_at
            )
        )

        self.assertIsNotNone(
            first
        )

        self.assertIsNone(
            second
        )


    def test_global_15_minute_cooldown_after_finish(
        self,
    ):
        self.create(
            office="CNP_OVIEDO"
        )

        self.create(
            office="CNP_LUARCA"
        )

        due_at = (
            self.now
            + timedelta(
                minutes=15
            )
        )

        first = (
            scheduler.claim_next_due(
                now=due_at
            )
        )

        finished = (
            due_at
            + timedelta(
                minutes=2
            )
        )

        scheduler.mark_run_finished(
            first[
                "scheduler_id"
            ],
            result={
                "availability_status":
                    "UNAVAILABLE",
            },
            finished_at=finished,
        )

        # Solo han pasado 14 minutos desde que terminó
        # el bot anterior.
        too_early = (
            finished
            + timedelta(
                minutes=14
            )
        )

        self.assertIsNone(
            scheduler.claim_next_due(
                now=too_early
            )
        )

        # Exactamente 15 minutos después sí puede
        # ejecutarse el siguiente scheduler en cola.
        allowed = (
            finished
            + timedelta(
                minutes=15
            )
        )

        second = (
            scheduler.claim_next_due(
                now=allowed
            )
        )

        self.assertIsNotNone(
            second
        )

        self.assertNotEqual(
            first[
                "scheduler_id"
            ],
            second[
                "scheduler_id"
            ],
        )


    def test_next_candidate_reports_queued_time(
        self,
    ):
        first = self.create(
            office="CNP_OVIEDO"
        )

        self.create(
            office="CNP_LUARCA"
        )

        due_at = (
            self.now
            + timedelta(
                minutes=15
            )
        )

        running = (
            scheduler.claim_next_due(
                now=due_at
            )
        )

        self.assertEqual(
            running[
                "scheduler_id"
            ],
            first[
                "scheduler_id"
            ],
        )

        finished = (
            due_at
            + timedelta(
                minutes=3
            )
        )

        scheduler.mark_run_finished(
            running[
                "scheduler_id"
            ],
            finished_at=finished,
        )

        candidate = (
            scheduler.next_candidate(
                now=finished
            )
        )

        expected = (
            finished
            + timedelta(
                minutes=15
            )
        )

        self.assertEqual(
            datetime.fromisoformat(
                candidate[
                    "effective_run_at"
                ]
            ),
            expected,
        )

        self.assertTrue(
            candidate[
                "queued"
            ]
        )

        self.assertEqual(
            datetime.fromisoformat(
                candidate[
                    "warning_at"
                ]
            ),
            expected
            - timedelta(
                minutes=1
            ),
        )


if __name__ == "__main__":
    unittest.main()


def test_overdue_attempts_are_skipped_not_replayed():
    import json
    from datetime import (
        datetime,
        timedelta,
        timezone,
    )

    from backend.services import (
        icpplus_scheduler_service
        as scheduler,
    )

    store = {}

    original_get = (
        scheduler.config_service.get_config
    )
    original_set = (
        scheduler.config_service.set_config
    )

    scheduler.config_service.get_config = (
        lambda key, default="":
            store.get(
                key,
                default,
            )
    )

    scheduler.config_service.set_config = (
        lambda key, value:
            store.__setitem__(
                key,
                value,
            )
    )

    try:
        created_at = datetime(
            2026,
            8,
            21,
            12,
            0,
            tzinfo=timezone.utc,
        )

        schedule = (
            scheduler.create_schedule(
                province_key="ASTURIAS",
                procedure_key="POLICIA_TOMA_HUELLAS_TIE",
                office_key="CNP_OVIEDO",
                interval_minutes=30,
                duration_minutes=300,
                now=created_at,
            )
        )

        # next_run original = 12:30.
        # Worker vuelve a las 13:42.
        restarted_at = datetime(
            2026,
            8,
            21,
            13,
            42,
            tzinfo=timezone.utc,
        )

        changed = (
            scheduler.reconcile_overdue(
                now=restarted_at
            )
        )

        assert (
            schedule[
                "scheduler_id"
            ]
            in changed
        )

        updated = scheduler.get_schedule(
            schedule[
                "scheduler_id"
            ]
        )

        # 12:30, 13:00 y 13:30 quedan omitidos.
        # El siguiente turno válido es 14:00.
        assert (
            datetime.fromisoformat(
                updated[
                    "next_run_at"
                ]
            )
            == datetime(
                2026,
                8,
                21,
                14,
                0,
                tzinfo=timezone.utc,
            )
        )

        assert (
            updated[
                "skipped_attempt_count"
            ]
            == 3
        )

    finally:
        scheduler.config_service.get_config = (
            original_get
        )

        scheduler.config_service.set_config = (
            original_set
        )


def test_warning_event_is_idempotent():
    from datetime import (
        datetime,
        timedelta,
        timezone,
    )

    from backend.services import (
        icpplus_scheduler_service
        as scheduler,
    )

    store = {}

    original_get = (
        scheduler.config_service.get_config
    )
    original_set = (
        scheduler.config_service.set_config
    )

    scheduler.config_service.get_config = (
        lambda key, default="":
            store.get(
                key,
                default,
            )
    )

    scheduler.config_service.set_config = (
        lambda key, value:
            store.__setitem__(
                key,
                value,
            )
    )

    try:
        now = datetime(
            2026,
            8,
            21,
            12,
            0,
            tzinfo=timezone.utc,
        )

        schedule = (
            scheduler.create_schedule(
                province_key="ASTURIAS",
                procedure_key="POLICIA_TOMA_HUELLAS_TIE",
                office_key="CNP_OVIEDO",
                interval_minutes=15,
                duration_minutes=60,
                now=now,
            )
        )

        run_at = (
            now
            + timedelta(
                minutes=15
            )
        )

        first = scheduler.record_warning(
            schedule[
                "scheduler_id"
            ],
            effective_run_at=run_at,
            warned_at=(
                run_at
                - timedelta(
                    seconds=60
                )
            ),
        )

        second = scheduler.record_warning(
            schedule[
                "scheduler_id"
            ],
            effective_run_at=run_at,
            warned_at=(
                run_at
                - timedelta(
                    seconds=30
                )
            ),
        )

        assert (
            first[
                "event_id"
            ]
            == second[
                "event_id"
            ]
        )

    finally:
        scheduler.config_service.get_config = (
            original_get
        )

        scheduler.config_service.set_config = (
            original_set
        )


def test_warning_skip_advances_only_one_attempt():
    from datetime import (
        datetime,
        timedelta,
        timezone,
    )

    from backend.services import (
        icpplus_scheduler_service
        as scheduler,
    )

    store = {}

    original_get = scheduler.config_service.get_config
    original_set = scheduler.config_service.set_config

    scheduler.config_service.get_config = (
        lambda key, default="":
            store.get(key, default)
    )

    scheduler.config_service.set_config = (
        lambda key, value:
            store.__setitem__(key, value)
    )

    try:
        now = datetime(
            2026, 8, 21, 12, 0,
            tzinfo=timezone.utc,
        )

        item = scheduler.create_schedule(
            province_key="ASTURIAS",
            procedure_key="POLICIA_TOMA_HUELLAS_TIE",
            office_key="CNP_OVIEDO",
            interval_minutes=15,
            duration_minutes=60,
            now=now,
        )

        run_at = (
            now
            + timedelta(minutes=15)
        )

        event = scheduler.record_warning(
            item["scheduler_id"],
            effective_run_at=run_at,
            warned_at=(
                run_at
                - timedelta(seconds=60)
            ),
        )

        result = scheduler.handle_warning_action(
            event["event_id"],
            action="SKIP",
            acted_at=(
                run_at
                - timedelta(seconds=30)
            ),
        )

        updated = result["schedule"]

        assert updated["attempt_count"] == 0
        assert updated["skipped_attempt_count"] == 1

        assert (
            datetime.fromisoformat(
                updated["next_run_at"]
            )
            == run_at
            + timedelta(minutes=15)
        )

        state = scheduler.get_state()

        assert (
            state["global"][
                "last_run_finished_at"
            ]
            is None
        )

        assert (
            result["event"]["resolution"]
            == "SKIP"
        )

    finally:
        scheduler.config_service.get_config = (
            original_get
        )

        scheduler.config_service.set_config = (
            original_set
        )


def test_warning_stop_terminates_schedule():
    from datetime import (
        datetime,
        timedelta,
        timezone,
    )

    from backend.services import (
        icpplus_scheduler_service
        as scheduler,
    )

    store = {}

    original_get = scheduler.config_service.get_config
    original_set = scheduler.config_service.set_config

    scheduler.config_service.get_config = (
        lambda key, default="":
            store.get(key, default)
    )

    scheduler.config_service.set_config = (
        lambda key, value:
            store.__setitem__(key, value)
    )

    try:
        now = datetime(
            2026, 8, 21, 12, 0,
            tzinfo=timezone.utc,
        )

        item = scheduler.create_schedule(
            province_key="ASTURIAS",
            procedure_key="POLICIA_TOMA_HUELLAS_TIE",
            office_key="CNP_OVIEDO",
            interval_minutes=15,
            duration_minutes=60,
            now=now,
        )

        run_at = (
            now
            + timedelta(minutes=15)
        )

        event = scheduler.record_warning(
            item["scheduler_id"],
            effective_run_at=run_at,
            warned_at=(
                run_at
                - timedelta(seconds=60)
            ),
        )

        result = scheduler.handle_warning_action(
            event["event_id"],
            action="STOP",
            acted_at=(
                run_at
                - timedelta(seconds=30)
            ),
        )

        assert (
            result["schedule"]["status"]
            == "STOPPED"
        )

        assert (
            result["schedule"]["next_run_at"]
            is None
        )

        assert (
            result["event"]["resolution"]
            == "STOP"
        )

    finally:
        scheduler.config_service.get_config = (
            original_get
        )

        scheduler.config_service.set_config = (
            original_set
        )


def test_last_run_at_exact_end_is_claimable_with_polling_delay():
    from datetime import (
        datetime,
        timedelta,
        timezone,
    )

    from backend.services import (
        icpplus_scheduler_service
        as scheduler,
    )

    store = {}

    original_get = scheduler.config_service.get_config
    original_set = scheduler.config_service.set_config

    scheduler.config_service.get_config = (
        lambda key, default="":
            store.get(
                key,
                default,
            )
    )

    scheduler.config_service.set_config = (
        lambda key, value:
            store.__setitem__(
                key,
                value,
            )
    )

    try:
        created_at = datetime(
            2026,
            8,
            21,
            12,
            0,
            tzinfo=timezone.utc,
        )

        item = scheduler.create_schedule(
            province_key="ASTURIAS",
            procedure_key="POLICIA_TOMA_HUELLAS_TIE",
            office_key="CNP_OVIEDO",
            interval_minutes=15,
            duration_minutes=15,
            now=created_at,
        )

        run_at = datetime.fromisoformat(
            item[
                "next_run_at"
            ]
        )

        ends_at = datetime.fromisoformat(
            item[
                "ends_at"
            ]
        )

        assert run_at == ends_at

        polling_now = (
            run_at
            + timedelta(
                milliseconds=750
            )
        )

        candidate = scheduler.next_candidate(
            now=polling_now
        )

        assert candidate is not None

        assert (
            candidate[
                "scheduler_id"
            ]
            == item[
                "scheduler_id"
            ]
        )

        claimed = scheduler.claim_next_due(
            now=polling_now
        )

        assert claimed is not None

        assert (
            claimed[
                "status"
            ]
            == "RUNNING"
        )

    finally:
        scheduler.config_service.get_config = (
            original_get
        )

        scheduler.config_service.set_config = (
            original_set
        )


def test_due_run_beyond_claim_grace_is_not_replayed():
    from datetime import (
        datetime,
        timedelta,
        timezone,
    )

    from backend.services import (
        icpplus_scheduler_service
        as scheduler,
    )

    store = {}

    original_get = scheduler.config_service.get_config
    original_set = scheduler.config_service.set_config

    scheduler.config_service.get_config = (
        lambda key, default="":
            store.get(
                key,
                default,
            )
    )

    scheduler.config_service.set_config = (
        lambda key, value:
            store.__setitem__(
                key,
                value,
            )
    )

    try:
        created_at = datetime(
            2026,
            8,
            21,
            12,
            0,
            tzinfo=timezone.utc,
        )

        item = scheduler.create_schedule(
            province_key="ASTURIAS",
            procedure_key="POLICIA_TOMA_HUELLAS_TIE",
            office_key="CNP_OVIEDO",
            interval_minutes=15,
            duration_minutes=60,
            now=created_at,
        )

        run_at = datetime.fromisoformat(
            item[
                "next_run_at"
            ]
        )

        too_late = (
            run_at
            + timedelta(
                seconds=(
                    scheduler
                    .CLAIM_LATE_GRACE_SECONDS
                    + 1
                )
            )
        )

        assert (
            scheduler.next_candidate(
                now=too_late
            )
            is None
        )

        assert (
            scheduler.claim_next_due(
                now=too_late
            )
            is None
        )

    finally:
        scheduler.config_service.get_config = (
            original_get
        )

        scheduler.config_service.set_config = (
            original_set
        )


def test_reconcile_resolves_pending_stale_warning():
    from datetime import (
        datetime,
        timedelta,
        timezone,
    )

    from backend.services import (
        icpplus_scheduler_service
        as scheduler,
    )

    store = {}

    original_get = scheduler.config_service.get_config
    original_set = scheduler.config_service.set_config

    scheduler.config_service.get_config = (
        lambda key, default="":
            store.get(
                key,
                default,
            )
    )

    scheduler.config_service.set_config = (
        lambda key, value:
            store.__setitem__(
                key,
                value,
            )
    )

    try:
        created_at = datetime(
            2026,
            8,
            21,
            12,
            0,
            tzinfo=timezone.utc,
        )

        item = scheduler.create_schedule(
            province_key="ASTURIAS",
            procedure_key="POLICIA_TOMA_HUELLAS_TIE",
            office_key="CNP_OVIEDO",
            interval_minutes=15,
            duration_minutes=60,
            now=created_at,
        )

        run_at = datetime.fromisoformat(
            item[
                "next_run_at"
            ]
        )

        warning = scheduler.record_warning(
            item[
                "scheduler_id"
            ],
            effective_run_at=run_at,
            warned_at=(
                run_at
                - timedelta(
                    seconds=60
                )
            ),
        )

        late = (
            run_at
            + timedelta(
                seconds=(
                    scheduler
                    .CLAIM_LATE_GRACE_SECONDS
                    + 1
                )
            )
        )

        changed = scheduler.reconcile_overdue(
            now=late
        )

        assert (
            item[
                "scheduler_id"
            ]
            in changed
        )

        resolved = (
            scheduler
            .get_last_warning_event()
        )

        assert (
            resolved[
                "event_id"
            ]
            == warning[
                "event_id"
            ]
        )

        assert (
            resolved[
                "status"
            ]
            == "RESOLVED"
        )

        assert (
            resolved[
                "resolution"
            ]
            == "RECONCILED"
        )

    finally:
        scheduler.config_service.get_config = (
            original_get
        )

        scheduler.config_service.set_config = (
            original_set
        )
