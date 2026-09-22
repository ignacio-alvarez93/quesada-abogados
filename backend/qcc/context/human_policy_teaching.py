"""Governed HUMAN_ONLY teaching from a trusted human action.

QCC_HUMAN_POLICY_TEACHING_V1

A human can TEACH the backend that a specific, exactly-identified action
must remain HUMAN_ONLY. This is deliberately the only direction this
module supports:

- teaching may RESTRICT an action to HUMAN_ONLY;
- teaching NEVER promotes an action to AUTOMATION_ALLOWED;
- there is no API here that can widen authority.

A future automation candidate lifecycle (evidence accumulation +
separate governed promotion, symmetric to selector self-healing) is
explicitly out of scope for this module. Nothing here creates execution
authority.

Identity and safety are delegated to the SAME trusted resolution path
already used to canonicalize human DOM signals
(``resolve_human_dom_signal``): session/profile/scope validation,
freshness, evidence matching and ambiguity rejection are therefore not
reimplemented here.

The override key is deliberately NOT state-scoped
(site_code + environment + kind + selector + frame_path only). A taught
restriction is conservative by construction: it applies to every
occurrence of that exact physical action on that site/environment,
regardless of which functional state it is observed in. This is the
fail-closed choice: broadening a restriction is always safe, narrowing
it is not.
"""

from __future__ import annotations

from dataclasses import (
    dataclass,
)
from datetime import (
    datetime,
    timezone,
)
from uuid import (
    uuid4,
)

from backend.qcc.context.human_action_canonicalizer import (
    QccHumanDomSignal,
    resolve_human_dom_signal,
)
from backend.qcc.context.observed_human_action import (
    QccObservedHumanAction,
)
from backend.qcc.context.store import (
    QccContextStore,
)


QCC_HUMAN_POLICY_TEACHING_SCHEMA_VERSION = 1

QCC_HUMAN_POLICY_TEACHING_RESTRICTION_HUMAN_ONLY = (
    "HUMAN_ONLY"
)

# The only restriction this module ever produces. Kept as an explicit
# constant (rather than an open string) so a future restriction level
# cannot be introduced by accident without touching this contract.
_SUPPORTED_RESTRICTIONS = frozenset({
    QCC_HUMAN_POLICY_TEACHING_RESTRICTION_HUMAN_ONLY,
})


def _required_text(
    value,
    error,
):
    text = str(
        value
        or ""
    ).strip()

    if not text:
        raise ValueError(
            error
        )

    return text


@dataclass(
    frozen=True,
    slots=True,
)
class QccHumanPolicyTeachingRecord:
    """Provenance-complete record of one teaching event.

    Immutable. Append-only from the store's perspective: a record is
    never mutated in place, only superseded by a newer record with the
    same action identity (see ``HumanPolicyTeachingStore``).
    """

    teaching_id: str

    site_code: str
    environment: str

    action_kind: str
    action_selector: str
    action_frame_path: str

    # State identity: provenance only, never part of the override key.
    before_state: str | None
    before_fingerprint: str

    # Exact backend-persisted capture that produced the evidence this
    # teaching was resolved against. Audit identity only.
    evidence_capture_id: str | None

    previous_effective_policy: str
    resulting_restriction: str

    taught_by: str
    session_id: str
    taught_at: datetime

    def __post_init__(
        self,
    ) -> None:
        object.__setattr__(
            self,
            "teaching_id",
            _required_text(
                self.teaching_id,
                "QCC_HUMAN_POLICY_TEACHING_ID_REQUIRED",
            ),
        )

        object.__setattr__(
            self,
            "site_code",
            _required_text(
                self.site_code,
                "QCC_HUMAN_POLICY_TEACHING_SITE_REQUIRED",
            ).upper(),
        )

        object.__setattr__(
            self,
            "environment",
            _required_text(
                self.environment,
                "QCC_HUMAN_POLICY_TEACHING_ENVIRONMENT_REQUIRED",
            ).upper(),
        )

        object.__setattr__(
            self,
            "action_kind",
            _required_text(
                self.action_kind,
                "QCC_HUMAN_POLICY_TEACHING_KIND_REQUIRED",
            ).upper(),
        )

        object.__setattr__(
            self,
            "action_selector",
            _required_text(
                self.action_selector,
                "QCC_HUMAN_POLICY_TEACHING_SELECTOR_REQUIRED",
            ),
        )

        object.__setattr__(
            self,
            "action_frame_path",
            str(
                self.action_frame_path
                or "main"
            ).strip()
            or "main",
        )

        object.__setattr__(
            self,
            "before_state",
            (
                None
                if self.before_state is None
                else (
                    str(
                        self.before_state
                    ).strip().upper()
                    or None
                )
            ),
        )

        object.__setattr__(
            self,
            "before_fingerprint",
            _required_text(
                self.before_fingerprint,
                "QCC_HUMAN_POLICY_TEACHING_FINGERPRINT_REQUIRED",
            ).lower(),
        )

        object.__setattr__(
            self,
            "evidence_capture_id",
            (
                str(
                    self.evidence_capture_id
                    or ""
                ).strip()
                or None
            ),
        )

        object.__setattr__(
            self,
            "previous_effective_policy",
            _required_text(
                self.previous_effective_policy,
                "QCC_HUMAN_POLICY_TEACHING_PREVIOUS_POLICY_REQUIRED",
            ).upper(),
        )

        resulting_restriction = _required_text(
            self.resulting_restriction,
            "QCC_HUMAN_POLICY_TEACHING_RESTRICTION_REQUIRED",
        ).upper()

        if resulting_restriction not in _SUPPORTED_RESTRICTIONS:
            raise ValueError(
                "QCC_HUMAN_POLICY_TEACHING_RESTRICTION_UNSUPPORTED"
            )

        object.__setattr__(
            self,
            "resulting_restriction",
            resulting_restriction,
        )

        object.__setattr__(
            self,
            "taught_by",
            _required_text(
                self.taught_by,
                "QCC_HUMAN_POLICY_TEACHING_ACTOR_REQUIRED",
            ),
        )

        object.__setattr__(
            self,
            "session_id",
            _required_text(
                self.session_id,
                "QCC_HUMAN_POLICY_TEACHING_SESSION_ID_REQUIRED",
            ),
        )

        taught_at = self.taught_at

        if not isinstance(
            taught_at,
            datetime,
        ):
            raise ValueError(
                "QCC_HUMAN_POLICY_TEACHING_TIME_INVALID"
            )

        if (
            taught_at.tzinfo is None
            or taught_at.utcoffset() is None
        ):
            raise ValueError(
                "QCC_HUMAN_POLICY_TEACHING_TIME_TZ_REQUIRED"
            )

        object.__setattr__(
            self,
            "taught_at",
            taught_at.astimezone(
                timezone.utc
            ),
        )

    def action_identity(
        self,
    ) -> tuple[str, str, str, str]:
        """Override key: (site, environment, kind, selector, frame_path).

        Deliberately excludes state: see module docstring.
        """

        return (
            self.site_code,
            self.environment,
            self.action_kind,
            self.action_selector,
            self.action_frame_path,
        )

    def to_dict(
        self,
    ) -> dict:
        return {
            "schema_version":
                QCC_HUMAN_POLICY_TEACHING_SCHEMA_VERSION,

            "teaching_id":
                self.teaching_id,

            "site_code":
                self.site_code,

            "environment":
                self.environment,

            "action": {
                "kind":
                    self.action_kind,

                "selector":
                    self.action_selector,

                "frame_path":
                    self.action_frame_path,
            },

            "before_state":
                self.before_state,

            "before_fingerprint":
                self.before_fingerprint,

            "evidence_capture_id":
                self.evidence_capture_id,

            "previous_effective_policy":
                self.previous_effective_policy,

            "resulting_restriction":
                self.resulting_restriction,

            "taught_by":
                self.taught_by,

            "session_id":
                self.session_id,

            "taught_at":
                self.taught_at.isoformat(),
        }


def teach_human_only_from_signal(
    context_store: QccContextStore,
    signal: QccHumanDomSignal,
    *,
    taught_by: str,
    now: datetime | None = None,
) -> QccHumanPolicyTeachingRecord:
    """Resolve a trusted human signal and build a HUMAN_ONLY teaching record.

    Does NOT persist. The caller (Bridge route) owns the
    ``HumanPolicyTeachingStore`` and decides idempotency.

    Reuses ``resolve_human_dom_signal`` so every existing fail-closed
    guarantee (session/profile/scope, staleness, ambiguity) applies
    unchanged: this function raises the exact same ``ValueError``
    identities on those paths, it never re-derives them.
    """

    observed = resolve_human_dom_signal(
        context_store,
        signal,
        now=now,
    )

    if not isinstance(
        observed,
        QccObservedHumanAction,
    ):
        raise TypeError(
            "QCC_HUMAN_POLICY_TEACHING_OBSERVED_ACTION_INVALID"
        )

    reference = (
        now
        if now is not None
        else datetime.now(
            timezone.utc
        )
    )

    return QccHumanPolicyTeachingRecord(
        teaching_id=uuid4().hex,
        site_code=observed.site_code,
        environment=observed.environment,
        action_kind=observed.kind,
        action_selector=observed.selector,
        action_frame_path=observed.frame_path,
        before_state=observed.before_state,
        before_fingerprint=observed.before_fingerprint,
        evidence_capture_id=observed.evidence_capture_id,
        previous_effective_policy=observed.policy,
        resulting_restriction=(
            QCC_HUMAN_POLICY_TEACHING_RESTRICTION_HUMAN_ONLY
        ),
        taught_by=taught_by,
        session_id=observed.session_id,
        taught_at=reference,
    )


def resolve_effective_policy_with_teaching(
    *,
    canonical_policy: str,
    taught_restriction: str | None,
) -> str:
    """Apply a taught override on top of a canonical/static policy.

    Monotonic: a taught restriction can only narrow, never widen,
    canonical authority. ``taught_restriction`` of ``None`` means no
    override exists and the canonical policy is returned unchanged.
    """

    canonical_policy = _required_text(
        canonical_policy,
        "QCC_HUMAN_POLICY_TEACHING_CANONICAL_POLICY_REQUIRED",
    ).upper()

    if taught_restriction is None:
        return canonical_policy

    taught_restriction = _required_text(
        taught_restriction,
        "QCC_HUMAN_POLICY_TEACHING_RESTRICTION_REQUIRED",
    ).upper()

    if taught_restriction not in _SUPPORTED_RESTRICTIONS:
        raise ValueError(
            "QCC_HUMAN_POLICY_TEACHING_RESTRICTION_UNSUPPORTED"
        )

    # HUMAN_ONLY is the only restriction this module can produce, and it
    # always wins over AUTOMATION_ALLOWED/NAVIGATION_CANDIDATE/etc.
    # It is also idempotent against an already HUMAN_ONLY canonical
    # policy, and never downgrades a DENY.
    if canonical_policy == "DENY":
        return canonical_policy

    return taught_restriction
