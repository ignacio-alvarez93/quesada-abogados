"""Persistencia inmutable de evidencia QCC Contract Watcher.

Layout:

    data/qcc/auto_twin/contract_watcher/
        <contract_key>/
            <evidence_id>/
                evidence.json

Mirrors the append-only, atomic-write, identity-checked convention already
established by ``AutoTwinMaterializedRevisionStore``:

- only accepts evidence validated by ``validate_contract_watcher_evidence``;
- first write is atomic (temp file + ``os.replace``);
- observing/persisting the same evidence identity again is idempotent and
  returns the already-persisted record without a duplicate write;
- never overwrites existing evidence with a conflicting identity;
- no update/delete;
- never stores raw page content, only the deterministic comparison result.
"""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import threading
import uuid

from .contract_watcher import (
    validate_contract_watcher_evidence,
)


CONTRACT_WATCHER_STORE_SCHEMA_VERSION = 1

CONTRACT_WATCHER_STORE_TYPE = "QCC_CONTRACT_WATCHER_EVIDENCE_STORE"

DEFAULT_CONTRACT_WATCHER_ROOT = (
    Path("data") / "qcc" / "auto_twin" / "contract_watcher"
)

CONTRACT_WATCHER_EVIDENCE_FILENAME = "evidence.json"


_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _safe_segment(value, *, error):
    result = str(value or "").strip()

    if not _SAFE_SEGMENT_RE.fullmatch(result):
        raise ValueError(error)

    return result


def _semantic_identity(record):
    return {
        key: deepcopy(value)
        for key, value in record.items()
        if key != "created_at"
    }


class ContractWatcherEvidenceStore:
    """Store filesystem-only, sin mutaciones posteriores."""

    def __init__(self, *, root=None):
        self._root = Path(
            root if root is not None else DEFAULT_CONTRACT_WATCHER_ROOT
        )

        self._lock = threading.RLock()

    @property
    def root(self):
        return self._root

    def _evidence_directory(self, *, contract_key, evidence_id):
        safe_contract_key = _safe_segment(
            contract_key,
            error="QCC_CONTRACT_WATCHER_STORE_CONTRACT_KEY_INVALID",
        )

        safe_evidence_id = _safe_segment(
            evidence_id,
            error="QCC_CONTRACT_WATCHER_STORE_EVIDENCE_ID_INVALID",
        )

        return self._root / safe_contract_key / safe_evidence_id

    def evidence_path(self, *, contract_key, evidence_id):
        return (
            self._evidence_directory(
                contract_key=contract_key,
                evidence_id=evidence_id,
            )
            / CONTRACT_WATCHER_EVIDENCE_FILENAME
        )

    def save(self, record):
        """Persiste una evidencia una sola vez (idempotente por identidad)."""

        canonical = validate_contract_watcher_evidence(record)

        contract_key = canonical["contract_key"]
        evidence_id = canonical["evidence_id"]

        path = self.evidence_path(
            contract_key=contract_key,
            evidence_id=evidence_id,
        )

        with self._lock:
            if path.exists():
                existing = self._read(path)

                if _semantic_identity(existing) != _semantic_identity(canonical):
                    raise ValueError(
                        "QCC_CONTRACT_WATCHER_STORE_IMMUTABLE_CONFLICT"
                    )

                return deepcopy(existing)

            directory = path.parent
            directory.mkdir(parents=True, exist_ok=True)

            payload = (
                json.dumps(
                    canonical,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
                + "\n"
            )

            temp = directory / (".evidence." + uuid.uuid4().hex + ".tmp")

            try:
                with temp.open("x", encoding="utf-8", newline="\n") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())

                # Recheck before replacement. Store is deliberately
                # append-only and never overwrites existing evidence.
                if path.exists():
                    existing = self._read(path)

                    if (
                        _semantic_identity(existing)
                        != _semantic_identity(canonical)
                    ):
                        raise ValueError(
                            "QCC_CONTRACT_WATCHER_STORE_IMMUTABLE_CONFLICT"
                        )

                    return deepcopy(existing)

                os.replace(temp, path)

            finally:
                if temp.exists():
                    temp.unlink()

            persisted = self._read(path)

            if persisted != canonical:
                raise ValueError(
                    "QCC_CONTRACT_WATCHER_STORE_POST_WRITE_MISMATCH"
                )

            return deepcopy(persisted)

    def _read(self, path):
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                "QCC_CONTRACT_WATCHER_STORE_EVIDENCE_INVALID"
            ) from exc

        return validate_contract_watcher_evidence(payload)

    def get(self, *, contract_key, evidence_id):
        safe_contract_key = _safe_segment(
            contract_key,
            error="QCC_CONTRACT_WATCHER_STORE_CONTRACT_KEY_INVALID",
        )

        safe_evidence_id = _safe_segment(
            evidence_id,
            error="QCC_CONTRACT_WATCHER_STORE_EVIDENCE_ID_INVALID",
        )

        path = self.evidence_path(
            contract_key=safe_contract_key,
            evidence_id=safe_evidence_id,
        )

        with self._lock:
            if not path.is_file():
                return None

            record = self._read(path)

            if record["contract_key"] != safe_contract_key:
                raise ValueError(
                    "QCC_CONTRACT_WATCHER_STORE_CONTRACT_KEY_MISMATCH"
                )

            if record["evidence_id"] != safe_evidence_id:
                raise ValueError(
                    "QCC_CONTRACT_WATCHER_STORE_EVIDENCE_ID_MISMATCH"
                )

            return deepcopy(record)

    def list(self, *, contract_key=None):
        """Lista evidencia válida sin reparar ni modificar nada."""

        with self._lock:
            if not self._root.exists():
                return []

            if contract_key is None:
                contract_dirs = sorted(
                    path for path in self._root.iterdir() if path.is_dir()
                )
            else:
                safe_contract_key = _safe_segment(
                    contract_key,
                    error="QCC_CONTRACT_WATCHER_STORE_CONTRACT_KEY_INVALID",
                )

                candidate = self._root / safe_contract_key

                contract_dirs = [candidate] if candidate.is_dir() else []

            records = []

            for contract_dir in contract_dirs:
                for evidence_dir in sorted(
                    path for path in contract_dir.iterdir() if path.is_dir()
                ):
                    path = evidence_dir / CONTRACT_WATCHER_EVIDENCE_FILENAME

                    if path.is_file():
                        records.append(self._read(path))

            return records
