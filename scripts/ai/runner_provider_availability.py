"""Provider-neutral availability classification for the governed Runner.

A failed provider attempt is one of four things, and the orchestrator must not
confuse them:

* PROVIDER_QUOTA_EXHAUSTED - the account/session ran out of allowance. Not a
  work failure: the worker waits (worktree/DAG preserved) until the provider
  recovers. Requires *contextual message evidence*; an HTTP 429 alone is
  ordinary rate limiting (transient), never quota.
* PROVIDER_AUTH_BLOCKED    - credentials missing/invalid/expired. Nothing the
  Runner may retry; a human/provider change is needed.
* PROVIDER_TRANSIENT_ERROR - network/overload/5xx/rate limit: bounded retry.
* PROVIDER_EXECUTION_ERROR - anything else: the existing failure policy.

Adapters feed structured metadata (HTTP status, terminal reason) plus message
text into `classify_provider_failure`; this module knows no provider ids, so
Codex and future providers reuse it unchanged.

Persisted evidence is deliberately small and secret-free: a condition code, a
status number, a short reason code, the matched reset phrase and a redacted,
length-capped message excerpt. Credentials, tokens and headers are never kept.

Reset hints such as ``resets 3pm (Europe/Madrid)`` are resolved to a UTC
instant only when the hint names an explicit IANA timezone that is available;
anything else yields None and the caller falls back to bounded backoff.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta, timezone
from enum import Enum
from typing import Callable, Optional

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None  # type: ignore[assignment]

    class ZoneInfoNotFoundError(Exception):  # type: ignore[no-redef]
        pass

MESSAGE_EXCERPT_CHARS = 240


class ProviderCondition(str, Enum):
    QUOTA_EXHAUSTED = "PROVIDER_QUOTA_EXHAUSTED"
    AUTH_BLOCKED = "PROVIDER_AUTH_BLOCKED"
    TRANSIENT_ERROR = "PROVIDER_TRANSIENT_ERROR"
    EXECUTION_ERROR = "PROVIDER_EXECUTION_ERROR"


# Shared transient vocabulary (rate limits, overload, network, 5xx). Re-exported
# by runner_providers as TRANSIENT_ERROR_RE.
TRANSIENT_ERROR_RE = re.compile(
    r"rate[ _-]?limit|too many requests|429|overloaded|50[234]|"
    r"service unavailable|temporar(?:y|ily) unavailable|econnreset|etimedout|"
    r"connection (?:reset|refused|aborted)|network (?:error|is unreachable)|"
    r"socket hang up|try again",
    re.IGNORECASE,
)

# Allowance exhaustion, not mere rate limiting: "rate limit" is deliberately absent.
_QUOTA_RE = re.compile(
    r"hit your (?:\w+ )?(?:session |usage |weekly |daily |monthly |message )?limit|"
    r"(?:session|usage|weekly|daily|monthly|message) limit|"
    r"quota (?:exceeded|exhausted|reached)|exceeded your (?:current )?quota|"
    r"insufficient[_ ]quota|out of (?:credits|usage)|credit balance is too low",
    re.IGNORECASE,
)
_AUTH_RE = re.compile(
    r"not logged in|please (?:run )?/?login|invalid[ _-]?api[ _-]?key|invalid x-api-key|"
    r"authentication[ _-]?(?:error|failed|required)|unauthori[sz]ed|"
    r"oauth token (?:has )?(?:expired|revoked)|credentials? (?:are |is )?(?:invalid|expired|missing)|"
    r"(?:token|session) (?:has )?expired, please",
    re.IGNORECASE,
)
_TRANSIENT_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504, 529})
# Statuses under which message-level quota evidence is accepted (None = no
# structured status available, e.g. a CLI that only prints text).
_QUOTA_STATUSES = frozenset({None, 402, 429})

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]+"),
    re.compile(r"(?i)\b(?:api[_-]?key|token|secret|password|authorization|cookie)\b\s*[:=]\s*\S+"),
    re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"),
)


def redact(text: Optional[str], limit: int = MESSAGE_EXCERPT_CHARS) -> str:
    """Length-capped copy of `text` with credential-shaped substrings removed."""
    out = " ".join(str(text or "").split())
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    return out[:limit]


@dataclass(frozen=True)
class ProviderClassification:
    condition: ProviderCondition
    reason: str
    http_status: Optional[int] = None
    terminal_reason: Optional[str] = None
    reset_hint: Optional[str] = None
    message_excerpt: str = ""

    def as_dict(self) -> dict:
        return {
            "condition": self.condition.value, "reason": self.reason, "http_status": self.http_status,
            "terminal_reason": self.terminal_reason, "reset_hint": self.reset_hint,
            "message_excerpt": self.message_excerpt,
        }

    @classmethod
    def from_dict(cls, data) -> Optional["ProviderClassification"]:
        if not isinstance(data, dict):
            return None
        try:
            condition = ProviderCondition(data.get("condition"))
        except ValueError:
            return None
        status = data.get("http_status")
        return cls(
            condition=condition, reason=str(data.get("reason") or ""),
            http_status=status if isinstance(status, int) and not isinstance(status, bool) else None,
            terminal_reason=redact(data.get("terminal_reason"), 80) or None,
            reset_hint=redact(data.get("reset_hint"), 80) or None,
            message_excerpt=redact(data.get("message_excerpt")),
        )


_RESET_RE = re.compile(
    r"resets?\s+(?:at\s+)?(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>[ap]m)?\s*"
    r"\((?P<tz>[A-Za-z][A-Za-z0-9_+\-]*(?:/[A-Za-z0-9_+\-]+){0,2})\)",
    re.IGNORECASE,
)


def extract_reset_hint(text: Optional[str]) -> Optional[str]:
    """The matched reset phrase (e.g. 'resets 3pm (Europe/Madrid)') or None."""
    match = _RESET_RE.search(text or "")
    return match.group(0) if match else None


def parse_reset_hint(
    text: Optional[str], now: datetime, tz_lookup: Optional[Callable] = None,
) -> Optional[datetime]:
    """Next UTC instant strictly after `now` at which the hinted wall-clock
    time occurs in the hinted IANA timezone, or None when it cannot be derived
    safely (no explicit timezone, unknown timezone, out-of-range time,
    naive `now`). Calendar arithmetic happens in the hinted zone so DST shifts
    are honoured; the result is always UTC."""
    match = _RESET_RE.search(text or "")
    if match is None or now.tzinfo is None:
        return None
    hour, minute = int(match.group("hour")), int(match.group("minute") or 0)
    ampm = (match.group("ampm") or "").lower()
    if ampm:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if ampm == "pm" else 0)
    elif hour > 23:
        return None
    if minute > 59:
        return None
    lookup = tz_lookup or ZoneInfo
    if lookup is None:
        return None
    try:
        tz = lookup(match.group("tz"))
    except (ZoneInfoNotFoundError, ValueError, OSError, KeyError):
        return None
    local_now = now.astimezone(tz)
    day = local_now.date()
    for _ in range(3):
        candidate = datetime.combine(day, dtime(hour, minute), tzinfo=tz).astimezone(timezone.utc)
        if candidate > now.astimezone(timezone.utc):
            return candidate
        day += timedelta(days=1)
    return None  # pragma: no cover - unreachable for a sane clock


def classify_provider_failure(
    *, http_status: Optional[int] = None, terminal_reason: Optional[str] = None,
    message: Optional[str] = None, stderr: Optional[str] = None, error_text: Optional[str] = None,
) -> ProviderClassification:
    """Structured metadata first, message evidence second. An HTTP 429 is
    quota exhaustion only when the message also says so."""
    text = "\n".join(part for part in (message, stderr, error_text) if part)
    common = dict(
        http_status=http_status, terminal_reason=redact(terminal_reason, 80) or None,
        message_excerpt=redact(message or error_text or stderr),
    )
    if _QUOTA_RE.search(text) and http_status in _QUOTA_STATUSES:
        basis = f"STATUS_{http_status}+" if http_status else ""
        return ProviderClassification(
            ProviderCondition.QUOTA_EXHAUSTED, f"{basis}QUOTA_MESSAGE",
            reset_hint=extract_reset_hint(text), **common,
        )
    if http_status == 401 or _AUTH_RE.search(text):
        return ProviderClassification(
            ProviderCondition.AUTH_BLOCKED, "STATUS_401" if http_status == 401 else "AUTH_MESSAGE", **common,
        )
    if http_status in _TRANSIENT_STATUSES or TRANSIENT_ERROR_RE.search(text):
        return ProviderClassification(
            ProviderCondition.TRANSIENT_ERROR,
            f"STATUS_{http_status}" if http_status in _TRANSIENT_STATUSES else "TRANSIENT_MESSAGE", **common,
        )
    return ProviderClassification(ProviderCondition.EXECUTION_ERROR, "UNCLASSIFIED", **common)
