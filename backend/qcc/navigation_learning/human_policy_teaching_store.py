"""Persisted store for governed HUMAN_ONLY teaching overrides.

QCC_HUMAN_POLICY_TEACHING_STORE_V1

Isolated by site_code / environment, mirroring
``HumanNavigationCandidateStore``. Each override is keyed by the exact
action identity (kind + selector + frame_path) within that scope.

Monotonic by construction: the only record this store ever accepts is a
HUMAN_ONLY restriction (enforced by
``QccHumanPolicyTeachingRecord``), so there is no code path that can
relax an existing override. Recording the same identity again is
idempotent: the newer record supersedes the older one in the latest
slot, but the full history is preserved for audit.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from backend.qcc.context.human_policy_teaching import (
    QCC_HUMAN_POLICY_TEACHING_SCHEMA_VERSION,
    QccHumanPolicyTeachingRecord,
)


HUMAN_POLICY_TEACHING_TYPE = (
    "QCC_HUMAN_POLICY_TEACHING_OVERRIDES"
)

DEFAULT_HUMAN_POLICY_TEACHING_ROOT = Path(
    "data/qcc/navigation_learning"
)

_PATH_CODE_RE = re.compile(
    r"^[A-Za-z0-9_.-]+$"
)


def _code(
    value,
    error,
):
    text = str(
        value
        or ""
    ).strip().upper()

    if (
        not text
        or text in {".", ".."}
        or not _PATH_CODE_RE.fullmatch(
            text
        )
    ):
        raise ValueError(
            error
        )

    return text


def _action_key(
    kind,
    selector,
    frame_path,
) -> str:
    return "|".join((
        kind,
        selector,
        frame_path,
    ))


class HumanPolicyTeachingStore:
    """Persistent store of taught HUMAN_ONLY overrides.

    Never grants execution authority. Never widens authority. See
    ``backend.qcc.context.human_policy_teaching`` for the full contract.
    """

    def __init__(
        self,
        *,
        root=DEFAULT_HUMAN_POLICY_TEACHING_ROOT,
    ):
        self._root = Path(
            root
        )

        self._lock = threading.RLock()

    def _site_dir(
        self,
        site_code,
        environment,
    ):
        return (
            self._root
            / _code(
                site_code,
                "QCC_HUMAN_POLICY_TEACHING_SITE_INVALID",
            )
            / _code(
                environment,
                "QCC_HUMAN_POLICY_TEACHING_ENVIRONMENT_INVALID",
            )
        )

    def _path(
        self,
        site_code,
        environment,
    ):
        return (
            self._site_dir(
                site_code,
                environment,
            )
            / "human_policy_teaching.json"
        )

    def _empty(
        self,
        site_code,
        environment,
    ):
        return {
            "schema_version":
                QCC_HUMAN_POLICY_TEACHING_SCHEMA_VERSION,

            "teaching_type":
                HUMAN_POLICY_TEACHING_TYPE,

            "site_code":
                _code(
                    site_code,
                    "QCC_HUMAN_POLICY_TEACHING_SITE_INVALID",
                ),

            "environment":
                _code(
                    environment,
                    "QCC_HUMAN_POLICY_TEACHING_ENVIRONMENT_INVALID",
                ),

            "revision":
                0,

            # action_key -> latest record dict.
            "overrides":
                {},

            # action_key -> [record dict, ...] append-only.
            "history":
                {},
        }

    def _load(
        self,
        site_code,
        environment,
    ):
        normalized_site = _code(
            site_code,
            "QCC_HUMAN_POLICY_TEACHING_SITE_INVALID",
        )

        normalized_environment = _code(
            environment,
            "QCC_HUMAN_POLICY_TEACHING_ENVIRONMENT_INVALID",
        )

        path = self._path(
            normalized_site,
            normalized_environment,
        )

        if not path.exists():
            return self._empty(
                normalized_site,
                normalized_environment,
            )

        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(
            payload,
            dict,
        ):
            raise ValueError(
                "QCC_HUMAN_POLICY_TEACHING_PAYLOAD_INVALID"
            )

        if (
            payload.get(
                "schema_version"
            )
            != QCC_HUMAN_POLICY_TEACHING_SCHEMA_VERSION
        ):
            raise ValueError(
                "QCC_HUMAN_POLICY_TEACHING_SCHEMA_INVALID"
            )

        if (
            payload.get(
                "teaching_type"
            )
            != HUMAN_POLICY_TEACHING_TYPE
        ):
            raise ValueError(
                "QCC_HUMAN_POLICY_TEACHING_TYPE_INVALID"
            )

        if (
            payload.get("site_code")
            != normalized_site
            or payload.get("environment")
            != normalized_environment
        ):
            raise ValueError(
                "QCC_HUMAN_POLICY_TEACHING_SCOPE_MISMATCH"
            )

        if not isinstance(
            payload.get("overrides"),
            dict,
        ) or not isinstance(
            payload.get("history"),
            dict,
        ):
            raise ValueError(
                "QCC_HUMAN_POLICY_TEACHING_PAYLOAD_INVALID"
            )

        return payload

    def _write(
        self,
        site_code,
        environment,
        payload,
    ):
        site_dir = self._site_dir(
            site_code,
            environment,
        )

        site_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        path = self._path(
            site_code,
            environment,
        )

        temporary = path.with_suffix(
            ".json.tmp"
        )

        temporary.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        temporary.replace(
            path
        )

    def record(
        self,
        record: QccHumanPolicyTeachingRecord,
    ) -> dict:
        """Persist a teaching record. Idempotent per action identity.

        Returns a dict with ``status`` of ``CREATED`` (first time this
        exact identity is taught) or ``ALREADY_TAUGHT`` (identity was
        already HUMAN_ONLY; the new record is still appended to history
        for provenance, but does not change the effective outcome).
        """

        if not isinstance(
            record,
            QccHumanPolicyTeachingRecord,
        ):
            raise TypeError(
                "QCC_HUMAN_POLICY_TEACHING_RECORD_INVALID"
            )

        (
            site_code,
            environment,
            kind,
            selector,
            frame_path,
        ) = record.action_identity()

        key = _action_key(
            kind,
            selector,
            frame_path,
        )

        with self._lock:
            payload = self._load(
                site_code,
                environment,
            )

            already_taught = key in payload["overrides"]

            payload["overrides"][key] = record.to_dict()

            payload["history"].setdefault(
                key,
                [],
            ).append(
                record.to_dict()
            )

            payload["revision"] = int(
                payload.get("revision") or 0
            ) + 1

            self._write(
                site_code,
                environment,
                payload,
            )

        return {
            "status":
                (
                    "ALREADY_TAUGHT"
                    if already_taught
                    else "CREATED"
                ),

            "teaching_id":
                record.teaching_id,

            "action_key":
                key,
        }

    def resolve_restriction(
        self,
        *,
        site_code,
        environment,
        kind,
        selector,
        frame_path="main",
    ) -> str | None:
        """Return the taught restriction for this exact action, if any."""

        payload = self._load(
            site_code,
            environment,
        )

        key = _action_key(
            str(kind or "").strip().upper(),
            str(selector or "").strip(),
            str(frame_path or "main").strip() or "main",
        )

        override = payload["overrides"].get(key)

        if not isinstance(
            override,
            dict,
        ):
            return None

        return override.get(
            "resulting_restriction"
        )

    def snapshot(
        self,
        *,
        site_code,
        environment,
    ) -> dict:
        return self._load(
            site_code,
            environment,
        )
