"""
Multi-source acquisition orchestration layer.

Runs every registered (source_code -> adapter factory) pair through the
existing CollectorSourceAdapter / TrendIngestionService contracts, unchanged.
This module adds no new network, parsing or persistence logic: it only
sequences registered sources and isolates per-source failure.

A fresh adapter instance is requested from the factory for every run, so
all cursor/retry state continues to flow through
TrendIntelligenceService.start_collector_run/complete_collector_run, never
through orchestrator-held state. That is also what makes retrying a run
idempotent: a retried source resumes from its last persisted cursor and
TrendIngestionService dedupes already-seen items by content hash.

One source raising is an isolation boundary, not a pipeline abort: it is
captured as a failed outcome for that source only. Sources are run
sequentially and each ingestion call is independently persisted, so a
failing source can never roll back or otherwise corrupt observations
already committed for a different, successful source.
"""

from dataclasses import dataclass
from typing import Callable

from backend.trend_intelligence.acquisition.contracts import CollectorError
from backend.trend_intelligence.acquisition.models import ERROR_UNKNOWN


@dataclass(frozen=True, slots=True)
class RegisteredSource:
    source_code: str
    adapter_factory: Callable[[], object]
    domain_code: str | None = None
    domain_confidence: float = 1.0
    domain_detection_method: str = "SOURCE"


@dataclass(frozen=True, slots=True)
class SourceAcquisitionOutcome:
    source_code: str
    ok: bool
    report: object | None = None
    error_classification: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class AcquisitionRunReport:
    outcomes: tuple[SourceAcquisitionOutcome, ...]

    @property
    def succeeded(self):
        return tuple(outcome for outcome in self.outcomes if outcome.ok)

    @property
    def failed(self):
        return tuple(outcome for outcome in self.outcomes if not outcome.ok)


class SourceAcquisitionOrchestrator:
    """Registry + sequential runner for Collector-backed sources.

    Domain-neutral: it has no knowledge of any specific business vertical,
    and no dependency on Selenium/UI automation. It only coordinates
    whatever Collector/Normalizer/adapter the caller registers.
    """

    def __init__(self, *, ingestion_service):
        self._ingestion_service = ingestion_service
        self._registered: dict[str, RegisteredSource] = {}

    def register(self, registered: RegisteredSource):
        code = str(registered.source_code or "").strip().upper()

        if not code:
            raise ValueError("source_code obligatorio")

        self._registered[code] = registered

    def registered_source_codes(self):
        return tuple(sorted(self._registered))

    def run_all(self):
        outcomes = tuple(
            self._run_one(self._registered[code])
            for code in sorted(self._registered)
        )
        return AcquisitionRunReport(outcomes=outcomes)

    def run_source(self, source_code):
        code = str(source_code or "").strip().upper()
        registered = self._registered.get(code)

        if registered is None:
            raise ValueError(f"Fuente no registrada: {source_code}")

        return self._run_one(registered)

    def _run_one(self, registered):
        adapter = registered.adapter_factory()

        try:
            report = self._ingestion_service.ingest(
                adapter,
                domain_code=registered.domain_code,
                domain_confidence=registered.domain_confidence,
                domain_detection_method=registered.domain_detection_method,
            )
        except CollectorError as exc:
            return SourceAcquisitionOutcome(
                source_code=registered.source_code,
                ok=False,
                error_classification=exc.classification,
                error_message=str(exc)[:500],
            )
        except Exception as exc:
            # Isolation boundary: an unexpected failure in one source's
            # collector/normalizer/adapter must not abort sibling sources.
            return SourceAcquisitionOutcome(
                source_code=registered.source_code,
                ok=False,
                error_classification=ERROR_UNKNOWN,
                error_message=str(exc)[:500],
            )

        return SourceAcquisitionOutcome(
            source_code=registered.source_code,
            ok=True,
            report=report,
        )
