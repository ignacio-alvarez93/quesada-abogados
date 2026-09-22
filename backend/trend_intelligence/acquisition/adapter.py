"""
Bridges the acquisition layer (Collector + Normalizer) into the
unchanged V1 TrendSourceAdapter contract, tracking a deterministic
run lifecycle and cursor checkpoint along the way.

CollectorSourceAdapter.collect() is eager: it drains exactly one
collector batch, normalizes every raw item, persists the final run
counters/status/cursor, and returns only the accepted
TrendObservationInput items. TrendIngestionService.ingest() then
consumes them exactly like any other V1 adapter.
"""

from datetime import datetime, timezone

from backend.trend_intelligence.acquisition.contracts import (
    CollectorError,
    NormalizationError,
)
from backend.trend_intelligence.acquisition.models import (
    ERROR_NONE,
    ERROR_PARSE,
    RUN_STATUS_FAILED,
    RUN_STATUS_PARTIAL,
    RUN_STATUS_SUCCESS,
)


class CollectorSourceAdapter:
    def __init__(
        self,
        *,
        source_code,
        collector,
        normalizer,
        trend_service,
        clock=None,
    ):
        self._source_code = str(source_code or "").strip().upper()

        if not self._source_code:
            raise ValueError("source_code obligatorio")

        self.collector = collector
        self.normalizer = normalizer
        self.trend_service = trend_service
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def source_code(self):
        return self._source_code

    def collect(self):
        run = self.trend_service.start_collector_run(
            source_code=self._source_code,
            collector_key=self.collector.collector_key,
            collector_version=self.collector.collector_version,
            provider=self.collector.provider,
            started_at=self._clock(),
        )

        try:
            batch = self.collector.collect(cursor=run.cursor)
        except CollectorError as exc:
            self.trend_service.complete_collector_run(
                run,
                status=RUN_STATUS_FAILED,
                error_classification=exc.classification,
                error_message=str(exc)[:500],
                completed_at=self._clock(),
            )
            raise

        accepted = []
        items_seen = 0
        items_rejected = 0
        last_rejection_reason = None

        for raw_item in batch.items:
            items_seen += 1

            try:
                normalized = self.normalizer.normalize(raw_item)
            except NormalizationError as exc:
                items_rejected += 1
                last_rejection_reason = str(exc)[:500]
                continue

            accepted.append(normalized)

        items_accepted = len(accepted)

        if items_rejected == 0:
            status = RUN_STATUS_SUCCESS
            error_classification = ERROR_NONE
            error_message = None
        elif items_accepted > 0:
            status = RUN_STATUS_PARTIAL
            error_classification = ERROR_PARSE
            error_message = last_rejection_reason
        else:
            status = RUN_STATUS_FAILED
            error_classification = ERROR_PARSE
            error_message = last_rejection_reason

        next_cursor = (
            batch.next_cursor
            if batch.next_cursor is not None
            else run.cursor
        )

        self.trend_service.complete_collector_run(
            run,
            status=status,
            items_seen=items_seen,
            items_accepted=items_accepted,
            items_rejected=items_rejected,
            error_classification=error_classification,
            error_message=error_message,
            cursor=next_cursor,
            completed_at=self._clock(),
        )

        return iter(accepted)
