"""Persistencia inmutable de revisiones materializadas AUTO TWIN.

Layout:

    data/qcc/auto_twin/materialized/
        <twin_key>/
            <materialized_revision_id>/
                manifest.json

Contrato:

- solo acepta MaterializedRevision válidas;
- primera escritura es atómica;
- misma identidad es idempotente;
- nunca sobrescribe una revisión existente;
- no existe update/delete;
- no conoce ACTIVE;
- no promociona;
- no sirve runtime;
- no materializa artefactos todavía.
"""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import threading
import uuid

from .materialized_revision import (
    validate_auto_twin_materialized_revision,
)


AUTO_TWIN_MATERIALIZED_STORE_SCHEMA_VERSION = 1

AUTO_TWIN_MATERIALIZED_STORE_TYPE = (
    "QCC_AUTO_TWIN_MATERIALIZED_REVISION_STORE"
)

DEFAULT_AUTO_TWIN_MATERIALIZED_ROOT = (
    Path("data")
    / "qcc"
    / "auto_twin"
    / "materialized"
)

AUTO_TWIN_MATERIALIZED_MANIFEST_FILENAME = (
    "manifest.json"
)


_SAFE_SEGMENT_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
)


_IDENTITY_FIELDS = (
    "schema_version",
    "record_type",
    "materialized_revision_id",
    "twin_key",
    "materialization_mode",
    "generation_source",
    "immutable",
    "source_capture_ids",
    "candidate_refs",
    "state_manifest",
    "artifact_manifest",
    "content_sha256",
)


def _safe_segment(
    value,
    *,
    error,
) -> str:
    result = str(
        value
        or ""
    ).strip()

    if not _SAFE_SEGMENT_RE.fullmatch(
        result
    ):
        raise ValueError(
            error
        )

    return result


def _semantic_identity(
    record,
) -> dict:
    return {
        field:
            deepcopy(
                record.get(
                    field
                )
            )
        for field
        in _IDENTITY_FIELDS
    }


class AutoTwinMaterializedRevisionStore:
    """Store filesystem-only, sin mutaciones posteriores."""

    def __init__(
        self,
        *,
        root=None,
    ):
        self._root = Path(
            root
            if root is not None
            else DEFAULT_AUTO_TWIN_MATERIALIZED_ROOT
        )

        self._lock = threading.RLock()

    @property
    def root(
        self,
    ) -> Path:
        return self._root

    def _revision_directory(
        self,
        *,
        twin_key,
        materialized_revision_id,
    ) -> Path:
        safe_twin_key = _safe_segment(
            twin_key,
            error=(
                "QCC_AUTO_TWIN_MATERIALIZED_STORE_TWIN_KEY_INVALID"
            ),
        )

        safe_revision_id = _safe_segment(
            materialized_revision_id,
            error=(
                "QCC_AUTO_TWIN_MATERIALIZED_STORE_REVISION_ID_INVALID"
            ),
        )

        return (
            self._root
            / safe_twin_key
            / safe_revision_id
        )

    def manifest_path(
        self,
        *,
        twin_key,
        materialized_revision_id,
    ) -> Path:
        return (
            self._revision_directory(
                twin_key=twin_key,
                materialized_revision_id=(
                    materialized_revision_id
                ),
            )
            / AUTO_TWIN_MATERIALIZED_MANIFEST_FILENAME
        )

    def save(
        self,
        record,
    ) -> dict:
        """Persiste una revisión una sola vez.

        Si la misma identidad ya existe, devuelve el registro persistido.
        ``created_at`` no forma parte de la identidad determinista:
        la primera materialización conserva su timestamp.
        """

        canonical = (
            validate_auto_twin_materialized_revision(
                record
            )
        )

        twin_key = canonical[
            "twin_key"
        ]

        revision_id = canonical[
            "materialized_revision_id"
        ]

        manifest = self.manifest_path(
            twin_key=twin_key,
            materialized_revision_id=(
                revision_id
            ),
        )

        with self._lock:
            if manifest.exists():
                existing = self._read_manifest(
                    manifest
                )

                if (
                    _semantic_identity(
                        existing
                    )
                    != _semantic_identity(
                        canonical
                    )
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_MATERIALIZED_STORE_IMMUTABLE_CONFLICT"
                    )

                return deepcopy(
                    existing
                )

            directory = manifest.parent

            directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            payload = (
                json.dumps(
                    canonical,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
                + "\n"
            )

            temp = (
                directory
                / (
                    ".manifest."
                    + uuid.uuid4().hex
                    + ".tmp"
                )
            )

            try:
                with temp.open(
                    "x",
                    encoding="utf-8",
                    newline="\n",
                ) as handle:
                    handle.write(
                        payload
                    )

                    handle.flush()

                    os.fsync(
                        handle.fileno()
                    )

                # Recheck before replacement. Store is deliberately
                # append-only and never overwrites an existing manifest.
                if manifest.exists():
                    existing = self._read_manifest(
                        manifest
                    )

                    if (
                        _semantic_identity(
                            existing
                        )
                        != _semantic_identity(
                            canonical
                        )
                    ):
                        raise ValueError(
                            "QCC_AUTO_TWIN_MATERIALIZED_STORE_IMMUTABLE_CONFLICT"
                        )

                    return deepcopy(
                        existing
                    )

                os.replace(
                    temp,
                    manifest,
                )

            finally:
                if temp.exists():
                    temp.unlink()

            persisted = self._read_manifest(
                manifest
            )

            if (
                persisted
                != canonical
            ):
                raise ValueError(
                    "QCC_AUTO_TWIN_MATERIALIZED_STORE_POST_WRITE_MISMATCH"
                )

            return deepcopy(
                persisted
            )

    def _read_manifest(
        self,
        path,
    ) -> dict:
        try:
            payload = json.loads(
                Path(
                    path
                ).read_text(
                    encoding="utf-8"
                )
            )

        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError(
                "QCC_AUTO_TWIN_MATERIALIZED_STORE_MANIFEST_INVALID"
            ) from exc

        return (
            validate_auto_twin_materialized_revision(
                payload
            )
        )

    def get(
        self,
        *,
        twin_key,
        materialized_revision_id,
    ):
        safe_twin_key = _safe_segment(
            twin_key,
            error=(
                "QCC_AUTO_TWIN_MATERIALIZED_STORE_TWIN_KEY_INVALID"
            ),
        )

        safe_revision_id = _safe_segment(
            materialized_revision_id,
            error=(
                "QCC_AUTO_TWIN_MATERIALIZED_STORE_REVISION_ID_INVALID"
            ),
        )

        manifest = self.manifest_path(
            twin_key=safe_twin_key,
            materialized_revision_id=(
                safe_revision_id
            ),
        )

        with self._lock:
            if not manifest.is_file():
                return None

            record = self._read_manifest(
                manifest
            )

            if (
                record[
                    "twin_key"
                ]
                != safe_twin_key
            ):
                raise ValueError(
                    "QCC_AUTO_TWIN_MATERIALIZED_STORE_TWIN_KEY_MISMATCH"
                )

            if (
                record[
                    "materialized_revision_id"
                ]
                != safe_revision_id
            ):
                raise ValueError(
                    "QCC_AUTO_TWIN_MATERIALIZED_STORE_REVISION_ID_MISMATCH"
                )

            return deepcopy(
                record
            )

    def list(
        self,
        *,
        twin_key=None,
    ) -> list[dict]:
        """Lista manifiestos válidos sin reparar ni modificar nada."""

        with self._lock:
            if not self._root.exists():
                return []

            if twin_key is None:
                twin_dirs = sorted(
                    path
                    for path in self._root.iterdir()
                    if path.is_dir()
                )

            else:
                safe_twin_key = _safe_segment(
                    twin_key,
                    error=(
                        "QCC_AUTO_TWIN_MATERIALIZED_STORE_TWIN_KEY_INVALID"
                    ),
                )

                candidate = (
                    self._root
                    / safe_twin_key
                )

                twin_dirs = (
                    [candidate]
                    if candidate.is_dir()
                    else []
                )

            result = []

            for twin_dir in twin_dirs:
                for revision_dir in sorted(
                    path
                    for path in twin_dir.iterdir()
                    if path.is_dir()
                ):
                    manifest = (
                        revision_dir
                        / AUTO_TWIN_MATERIALIZED_MANIFEST_FILENAME
                    )

                    if not manifest.is_file():
                        continue

                    record = self._read_manifest(
                        manifest
                    )

                    if (
                        record[
                            "twin_key"
                        ]
                        != twin_dir.name
                    ):
                        raise ValueError(
                            "QCC_AUTO_TWIN_MATERIALIZED_STORE_TWIN_KEY_MISMATCH"
                        )

                    if (
                        record[
                            "materialized_revision_id"
                        ]
                        != revision_dir.name
                    ):
                        raise ValueError(
                            "QCC_AUTO_TWIN_MATERIALIZED_STORE_REVISION_ID_MISMATCH"
                        )

                    result.append(
                        record
                    )

            result.sort(
                key=lambda record: (
                    record[
                        "twin_key"
                    ],
                    record[
                        "created_at"
                    ],
                    record[
                        "materialized_revision_id"
                    ],
                )
            )

            return deepcopy(
                result
            )
