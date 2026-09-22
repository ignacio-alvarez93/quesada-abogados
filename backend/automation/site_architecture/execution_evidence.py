"""Structured, PII-safe execution evidence (V1).

QCC_EXECUTION_EVIDENCE_V1

Produces one deterministic, explainable record per governed execution
attempt, sufficient to answer: which session/browser, which
provider/site, which canonical state, which action, which policy,
which selector source, whether the selector was healed, which
evidence authorized execution, expected/observed successor, attempt
count, recovery attempts and final disposition.

Deliberately never carries: raw field values being typed, full DOM,
cookies/tokens, or any other sensitive runtime payload. Only
structural/functional identity (fingerprints, state codes, selectors,
kinds) is recorded, consistent with the rest of QCC Site Architecture.
"""

from __future__ import annotations

from dataclasses import dataclass

from .safe_recovery import (
    RecoveryAttempt,
)


EXECUTION_EVIDENCE_SCHEMA_VERSION = 1


def _text(value):
    value = str(value or "").strip()
    return value or None


@dataclass(
    frozen=True,
    slots=True,
)
class ExecutionEvidence:
    schema_version: int

    session_id: str | None
    provider: str | None
    site_code: str | None
    environment: str | None

    canonical_state_before: str | None
    canonical_state_after: str | None
    recognized_state_before: str | None
    recognized_state_after: str | None

    action_kind: str
    action_selector: str
    action_frame_path: str

    interaction_policy: str | None

    selector_source: str | None
    selector_healed: bool
    selector_confidence: str | None

    gate_decision: str | None
    gate_reason: str | None

    expected_successor_state_id: str | None
    observed_outcome: str | None

    attempt_count: int
    recovery_attempts: tuple[RecoveryAttempt, ...]

    final_disposition: str | None
    result_status: str | None

    def to_public_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "provider": self.provider,
            "site_code": self.site_code,
            "environment": self.environment,
            "canonical_state_before": self.canonical_state_before,
            "canonical_state_after": self.canonical_state_after,
            "recognized_state_before": self.recognized_state_before,
            "recognized_state_after": self.recognized_state_after,
            "action_kind": self.action_kind,
            "action_selector": self.action_selector,
            "action_frame_path": self.action_frame_path,
            "interaction_policy": self.interaction_policy,
            "selector_source": self.selector_source,
            "selector_healed": self.selector_healed,
            "selector_confidence": self.selector_confidence,
            "gate_decision": self.gate_decision,
            "gate_reason": self.gate_reason,
            "expected_successor_state_id": (
                self.expected_successor_state_id
            ),
            "observed_outcome": self.observed_outcome,
            "attempt_count": self.attempt_count,
            "recovery_attempts": [
                attempt.to_public_dict()
                for attempt in self.recovery_attempts
            ],
            "final_disposition": self.final_disposition,
            "result_status": self.result_status,
        }


def build_execution_evidence(
    *,
    session_id=None,
    provider=None,
    site_code=None,
    environment=None,
    canonical_state_before=None,
    canonical_state_after=None,
    recognized_state_before=None,
    recognized_state_after=None,
    action_kind,
    action_selector,
    action_frame_path="main",
    interaction_policy=None,
    selector_source=None,
    selector_healed=False,
    selector_confidence=None,
    gate_decision=None,
    gate_reason=None,
    expected_successor_state_id=None,
    observed_outcome=None,
    attempt_count=0,
    recovery_attempts=(),
    final_disposition=None,
    result_status=None,
) -> ExecutionEvidence:
    recovery_attempts = tuple(recovery_attempts or ())

    for attempt in recovery_attempts:
        if not isinstance(attempt, RecoveryAttempt):
            raise TypeError(
                "QCC_EXECUTION_EVIDENCE_RECOVERY_ATTEMPT_INVALID"
            )

    if not isinstance(attempt_count, int) or isinstance(
        attempt_count, bool
    ):
        raise TypeError(
            "QCC_EXECUTION_EVIDENCE_ATTEMPT_COUNT_INVALID"
        )

    if attempt_count < 0:
        raise ValueError(
            "QCC_EXECUTION_EVIDENCE_ATTEMPT_COUNT_NEGATIVE"
        )

    action_kind_text = _text(action_kind)
    action_selector_text = _text(action_selector)

    if not action_kind_text or not action_selector_text:
        raise ValueError(
            "QCC_EXECUTION_EVIDENCE_ACTION_IDENTITY_REQUIRED"
        )

    if not isinstance(selector_healed, bool):
        raise TypeError(
            "QCC_EXECUTION_EVIDENCE_SELECTOR_HEALED_INVALID"
        )

    return ExecutionEvidence(
        schema_version=EXECUTION_EVIDENCE_SCHEMA_VERSION,
        session_id=_text(session_id),
        provider=_text(provider),
        site_code=_text(site_code),
        environment=_text(environment),
        canonical_state_before=_text(canonical_state_before),
        canonical_state_after=_text(canonical_state_after),
        recognized_state_before=_text(recognized_state_before),
        recognized_state_after=_text(recognized_state_after),
        action_kind=action_kind_text,
        action_selector=action_selector_text,
        action_frame_path=(
            _text(action_frame_path) or "main"
        ),
        interaction_policy=_text(interaction_policy),
        selector_source=_text(selector_source),
        selector_healed=selector_healed,
        selector_confidence=_text(selector_confidence),
        gate_decision=_text(gate_decision),
        gate_reason=_text(gate_reason),
        expected_successor_state_id=(
            _text(expected_successor_state_id)
        ),
        observed_outcome=_text(observed_outcome),
        attempt_count=attempt_count,
        recovery_attempts=recovery_attempts,
        final_disposition=_text(final_disposition),
        result_status=_text(result_status),
    )
