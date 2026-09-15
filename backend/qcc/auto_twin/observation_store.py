"""Memoria ligera de estados observados por AUTO TWIN.

AUTO TWIN no duplica la evidencia pesada de Site Architecture.

Solo conserva:
- identidad del TWIN;
- ruta funcional observada;
- estado semántico si existe;
- fingerprint backend-authoritative;
- capture_id que referencia la evidencia original;
- clasificación UNKNOWN / KNOWN / CHANGED.

La evidencia completa continúa perteneciendo a:

    data/qcc/site_architecture/<capture_id>/
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit

from .managed_site_registry import (
    AutoTwinManagedSite,
)

from .navigation_transition_materialization import (
    PROVENANCE_CORROBORATION_KEY,
)


AUTO_TWIN_OBSERVATION_STORE_SCHEMA_VERSION = 1

AUTO_TWIN_OBSERVATION_STORE_TYPE = (
    "QCC_AUTO_TWIN_OBSERVATION_STORE"
)

AUTO_TWIN_OBSERVATION_UNKNOWN = "UNKNOWN"
AUTO_TWIN_OBSERVATION_KNOWN = "KNOWN"
AUTO_TWIN_OBSERVATION_CHANGED = "CHANGED"

AUTO_TWIN_OBSERVATION_SUPERSESSION_SCHEMA_VERSION = 1

AUTO_TWIN_OBSERVATION_SUPERSESSION_TYPE = (
    "QCC_AUTO_TWIN_OBSERVATION_SUPERSESSION"
)

DEFAULT_AUTO_TWIN_OBSERVATION_STORE_PATH = (
    Path("data")
    / "qcc"
    / "auto_twin"
    / "observation_state.json"
)


def _text(
    value,
) -> str:
    return str(
        value
        or ""
    ).strip()


def _url_identity(
    value,
) -> tuple[
    str,
    str,
]:
    parsed = urlsplit(
        _text(
            value
        )
    )

    scheme = (
        parsed.scheme
        or ""
    ).lower()

    host = (
        parsed.hostname
        or ""
    ).lower()

    if (
        scheme not in {
            "http",
            "https",
        }
        or not host
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_OBSERVATION_URL_INVALID"
        )

    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(
            "QCC_AUTO_TWIN_OBSERVATION_URL_INVALID"
        ) from exc

    default_port = (
        port is None
        or (
            scheme == "http"
            and port == 80
        )
        or (
            scheme == "https"
            and port == 443
        )
    )

    netloc = host

    if not default_port:
        netloc = (
            f"{host}:{port}"
        )

    origin = (
        f"{scheme}://{netloc}"
    )

    pathname = (
        parsed.path
        or "/"
    )

    if not pathname.startswith("/"):
        pathname = (
            "/"
            + pathname
        )

    return (
        origin,
        pathname,
    )


def _functional_state(
    state_observation,
) -> str | None:
    if not isinstance(
        state_observation,
        dict,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_STATE_OBSERVATION_INVALID"
        )

    value = _text(
        state_observation.get(
            "state"
        )
    )

    return (
        value.upper()
        if value
        else None
    )


def _fingerprint(
    state_observation,
) -> str:
    if not isinstance(
        state_observation,
        dict,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_STATE_OBSERVATION_INVALID"
        )

    value = _text(
        state_observation.get(
            "fingerprint"
        )
    )

    if not value:
        raise ValueError(
            "QCC_AUTO_TWIN_FINGERPRINT_REQUIRED"
        )

    return value


def _state_variant_key(
    state_observation,
) -> str | None:
    """Optional stable functional variant inside a functional_state.

    Absent/empty by default -- callers that never populate it keep the
    exact previous identity behavior. Never derived here: this only
    reads whatever the recognizer layer (e.g. Mercurio's
    resolve_mercurio_state_variant_key) already resolved.
    """

    if not isinstance(
        state_observation,
        dict,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_STATE_OBSERVATION_INVALID"
        )

    return (
        _text(
            state_observation.get(
                "state_variant_key"
            )
        )
        or None
    )


def _state_identity(
    *,
    pathname,
    functional_state,
    state_variant_key=None,
) -> dict:
    identity = {
        "pathname":
            pathname,

        "functional_state":
            functional_state,
    }

    # Included only when present so the identity payload -- and
    # therefore the resulting state_key -- is byte-for-byte identical
    # to the pre-2D-20J shape whenever no variant is resolved. This is
    # what keeps every existing state_key (every other Mercurio state,
    # every other site) unchanged by this extension.
    if state_variant_key:
        identity[
            "state_variant_key"
        ] = state_variant_key

    return identity


def _state_key(
    identity,
) -> str:
    canonical = json.dumps(
        identity,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode(
            "utf-8"
        )
    ).hexdigest()


def _current_twin_view(
    twin,
) -> dict:
    """Read-only CURRENT/ACTIVE projection of one twin's states.

    Never mutates or drops anything on disk -- this only shapes what a
    *current_only* read returns. Historical entries (including
    superseded ones) remain fully readable through the default,
    unfiltered read path; this view exists solely so materialization
    can consume "current" state without ever seeing a superseded
    state_key as if it were still eligible.
    """

    if not isinstance(
        twin,
        dict,
    ):
        return twin

    states = twin.get(
        "states"
    )

    if not isinstance(
        states,
        dict,
    ):
        return twin

    supersessions = twin.get(
        "supersessions"
    )

    if not isinstance(
        supersessions,
        dict,
    ) or not supersessions:
        return twin

    filtered_states = {
        state_key: state
        for (
            state_key,
            state,
        ) in states.items()
        if state_key not in supersessions
    }

    return {
        **twin,
        "states":
            filtered_states,
    }


class AutoTwinObservationStore:
    """Estado persistente y thread-safe de observaciones TWIN."""

    def __init__(
        self,
        *,
        path=(
            DEFAULT_AUTO_TWIN_OBSERVATION_STORE_PATH
        ),
    ) -> None:
        self._path = Path(
            path
        )

        self._lock = (
            threading.RLock()
        )

        self._revision = 0

        self._twins: dict[
            str,
            dict,
        ] = {}

        self._load()

    @property
    def path(
        self,
    ) -> Path:
        return self._path

    @property
    def revision(
        self,
    ) -> int:
        with self._lock:
            return self._revision

    def _payload(
        self,
        *,
        twins=None,
        revision=None,
        current_only=False,
    ) -> dict:
        effective_twins = (
            self._twins
            if twins is None
            else twins
        )

        effective_revision = (
            self._revision
            if revision is None
            else revision
        )

        rendered_twins = deepcopy(
            effective_twins
        )

        if current_only:
            rendered_twins = {
                twin_key:
                    _current_twin_view(
                        twin
                    )
                for (
                    twin_key,
                    twin,
                ) in rendered_twins.items()
            }

        return {
            "schema_version":
                AUTO_TWIN_OBSERVATION_STORE_SCHEMA_VERSION,

            "store_type":
                AUTO_TWIN_OBSERVATION_STORE_TYPE,

            "revision":
                int(
                    effective_revision
                ),

            "twin_count":
                len(
                    effective_twins
                ),

            "twins":
                rendered_twins,
        }

    def _load(
        self,
    ) -> None:
        if not self._path.is_file():
            return

        try:
            payload = json.loads(
                self._path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                "QCC_AUTO_TWIN_OBSERVATION_STORE_READ_INVALID"
            ) from exc

        if not isinstance(
            payload,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_OBSERVATION_STORE_INVALID"
            )

        if (
            payload.get(
                "schema_version"
            )
            != AUTO_TWIN_OBSERVATION_STORE_SCHEMA_VERSION
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_OBSERVATION_STORE_SCHEMA_INVALID"
            )

        if (
            payload.get(
                "store_type"
            )
            != AUTO_TWIN_OBSERVATION_STORE_TYPE
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_OBSERVATION_STORE_TYPE_INVALID"
            )

        revision = payload.get(
            "revision"
        )

        twins = payload.get(
            "twins"
        )

        if (
            not isinstance(
                revision,
                int,
            )
            or revision < 0
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_OBSERVATION_REVISION_INVALID"
            )

        if not isinstance(
            twins,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_OBSERVATION_TWINS_INVALID"
            )

        self._revision = revision
        self._twins = deepcopy(
            twins
        )

    def _persist(
        self,
        *,
        twins,
        revision,
    ) -> None:
        self._path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary = (
            self._path.with_suffix(
                self._path.suffix
                + ".tmp"
            )
        )

        temporary.write_text(
            json.dumps(
                self._payload(
                    twins=twins,
                    revision=revision,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        temporary.replace(
            self._path
        )

    def observe(
        self,
        managed_twin,
        *,
        capture_id,
        observed_at,
        browser_profile_key,
        url,
        site_code,
        state_observation,
    ) -> dict:
        if not isinstance(
            managed_twin,
            AutoTwinManagedSite,
        ):
            raise TypeError(
                "QCC_AUTO_TWIN_MANAGED_SITE_INVALID"
            )

        if not managed_twin.enabled:
            raise ValueError(
                "QCC_AUTO_TWIN_DISABLED"
            )

        capture_id = _text(
            capture_id
        )

        if not capture_id:
            raise ValueError(
                "QCC_AUTO_TWIN_CAPTURE_ID_REQUIRED"
            )

        browser_profile_key = _text(
            browser_profile_key
        )

        if not browser_profile_key:
            raise ValueError(
                "QCC_AUTO_TWIN_BROWSER_PROFILE_REQUIRED"
            )

        origin, pathname = (
            _url_identity(
                url
            )
        )

        if not managed_twin.matches_url(
            url
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_URL_OUT_OF_SCOPE"
            )

        fingerprint = _fingerprint(
            state_observation
        )

        functional_state = (
            _functional_state(
                state_observation
            )
        )

        state_variant_key = (
            _state_variant_key(
                state_observation
            )
        )

        identity = _state_identity(
            pathname=pathname,
            functional_state=(
                functional_state
            ),
            state_variant_key=(
                state_variant_key
            ),
        )

        state_key = _state_key(
            identity
        )

        observed_at = (
            _text(
                observed_at
            )
            or None
        )

        observed_site_code = (
            _text(
                site_code
            ).upper()
            or None
        )

        with self._lock:
            candidate = deepcopy(
                self._twins
            )

            twin_state = (
                candidate.setdefault(
                    managed_twin.twin_key,
                    {
                        "twin_key":
                            managed_twin.twin_key,

                        "site_code":
                            managed_twin.site_code,

                        "states":
                            {},

                        "last_observation":
                            None,
                    },
                )
            )

            states = twin_state[
                "states"
            ]

            known_state = states.get(
                state_key
            )

            if known_state is None:
                classification = (
                    AUTO_TWIN_OBSERVATION_UNKNOWN
                )

                baseline_fingerprint = (
                    None
                )

                baseline_capture_id = (
                    None
                )

                if (
                    managed_twin
                    .discover_unknown_states
                ):
                    baseline_fingerprint = (
                        fingerprint
                    )

                    baseline_capture_id = (
                        capture_id
                    )

                    states[state_key] = {
                        "state_key":
                            state_key,

                        **identity,

                        "baseline_fingerprint":
                            fingerprint,

                        "baseline_capture_id":
                            capture_id,

                        "first_seen_at":
                            observed_at,

                        "last_seen_at":
                            observed_at,

                        "last_fingerprint":
                            fingerprint,

                        "last_capture_id":
                            capture_id,

                        "observation_count":
                            1,

                        "last_classification":
                            classification,
                    }

            else:
                baseline_fingerprint = (
                    known_state.get(
                        "baseline_fingerprint"
                    )
                )

                baseline_capture_id = (
                    known_state.get(
                        "baseline_capture_id"
                    )
                )

                classification = (
                    AUTO_TWIN_OBSERVATION_KNOWN
                    if (
                        fingerprint
                        == baseline_fingerprint
                    )
                    else (
                        AUTO_TWIN_OBSERVATION_CHANGED
                    )
                )

                known_state[
                    "last_seen_at"
                ] = observed_at

                known_state[
                    "last_fingerprint"
                ] = fingerprint

                known_state[
                    "last_capture_id"
                ] = capture_id

                known_state[
                    "observation_count"
                ] = (
                    int(
                        known_state.get(
                            "observation_count"
                        )
                        or 0
                    )
                    + 1
                )

                known_state[
                    "last_classification"
                ] = classification

            observation = {
                "classification":
                    classification,

                "twin_key":
                    managed_twin.twin_key,

                "site_code":
                    managed_twin.site_code,

                "observed_site_code":
                    observed_site_code,

                "browser_profile_key":
                    browser_profile_key,

                "capture_id":
                    capture_id,

                "observed_at":
                    observed_at,

                "origin":
                    origin,

                "pathname":
                    pathname,

                "functional_state":
                    functional_state,

                "state_variant_key":
                    state_variant_key,

                "state_key":
                    state_key,

                "fingerprint":
                    fingerprint,

                "baseline_fingerprint":
                    baseline_fingerprint,

                "baseline_capture_id":
                    baseline_capture_id,

                "state_registered":
                    state_key in states,

                "discover_unknown_states":
                    (
                        managed_twin
                        .discover_unknown_states
                    ),

                "auto_update":
                    managed_twin.auto_update,
            }

            twin_state[
                "last_observation"
            ] = deepcopy(
                observation
            )

            next_revision = (
                self._revision
                + 1
            )

            self._persist(
                twins=candidate,
                revision=next_revision,
            )

            self._twins = candidate
            self._revision = (
                next_revision
            )

            return {
                **observation,
                "store_revision":
                    self._revision,
            }

    def snapshot(
        self,
        twin_key=None,
        *,
        current_only=False,
    ) -> dict:
        """Historical read by default.

        ``current_only=True`` returns the CURRENT/ACTIVE view instead:
        every superseded state_key is filtered out of each twin's
        ``states``, without ever touching what is persisted on disk.
        The unfiltered (default) read remains the audit/history path
        and keeps returning superseded entries untouched.
        """

        with self._lock:
            if twin_key is None:
                return self._payload(
                    current_only=(
                        current_only
                    ),
                )

            key = _text(
                twin_key
            )

            if not key:
                raise ValueError(
                    "QCC_AUTO_TWIN_KEY_REQUIRED"
                )

            twin = self._twins.get(
                key
            )

            rendered_twin = (
                deepcopy(
                    twin
                )
                if twin is not None
                else None
            )

            if (
                current_only
                and rendered_twin
                is not None
            ):
                rendered_twin = (
                    _current_twin_view(
                        rendered_twin
                    )
                )

            return {
                "schema_version":
                    AUTO_TWIN_OBSERVATION_STORE_SCHEMA_VERSION,

                "store_type":
                    AUTO_TWIN_OBSERVATION_STORE_TYPE,

                "revision":
                    self._revision,

                "twin_key":
                    key,

                "found":
                    twin is not None,

                "twin":
                    rendered_twin,
            }

    def supersede(
        self,
        managed_twin,
        *,
        old_state_key,
        replacement_state_keys,
        reason,
        recorded_at=None,
        provenance=None,
    ) -> dict:
        """Append-safe CURRENT-eligibility supersession.

        Declares ``old_state_key`` no longer eligible for CURRENT
        materialization in favor of one or more
        ``replacement_state_keys`` -- without deleting or rewriting
        its historical entry. The old entry stays fully readable via
        ``snapshot(current_only=False)`` (the default); only
        ``snapshot(current_only=True)`` -- and therefore
        materialization -- stops seeing it.

        Idempotent: calling this again with the exact same
        replacement set is a no-op that returns the existing record.
        Calling it again with a *different* replacement set for the
        same ``old_state_key`` is rejected -- a supersession record is
        itself never silently rebound, mirroring the append-only
        immutability of ``MaterializedRevisionStore``.

        Both ``old_state_key`` and every entry of
        ``replacement_state_keys`` must already exist as observed
        states for this twin: a supersession can only ever point at
        states that have already been validated by a real
        ``observe()`` call, never invented here.
        """

        if not isinstance(
            managed_twin,
            AutoTwinManagedSite,
        ):
            raise TypeError(
                "QCC_AUTO_TWIN_MANAGED_SITE_INVALID"
            )

        old_state_key = _text(
            old_state_key
        )

        if not old_state_key:
            raise ValueError(
                "QCC_AUTO_TWIN_SUPERSESSION_OLD_STATE_KEY_REQUIRED"
            )

        normalized_replacements = tuple(
            dict.fromkeys(
                key
                for key in (
                    _text(candidate)
                    for candidate in (
                        replacement_state_keys
                        or ()
                    )
                )
                if key
            )
        )

        if not normalized_replacements:
            raise ValueError(
                "QCC_AUTO_TWIN_SUPERSESSION_REPLACEMENTS_REQUIRED"
            )

        if (
            old_state_key
            in normalized_replacements
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_SUPERSESSION_SELF_REFERENTIAL"
            )

        reason = _text(
            reason
        )

        if not reason:
            raise ValueError(
                "QCC_AUTO_TWIN_SUPERSESSION_REASON_REQUIRED"
            )

        recorded_at = (
            _text(
                recorded_at
            )
            or None
        )

        if (
            provenance is not None
            and not isinstance(
                provenance,
                dict,
            )
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_SUPERSESSION_PROVENANCE_INVALID"
            )

        with self._lock:
            candidate = deepcopy(
                self._twins
            )

            twin_state = candidate.get(
                managed_twin.twin_key
            )

            if twin_state is None:
                raise ValueError(
                    "QCC_AUTO_TWIN_SUPERSESSION_TWIN_UNKNOWN"
                )

            states = (
                twin_state.get(
                    "states"
                )
                or {}
            )

            if old_state_key not in states:
                raise ValueError(
                    "QCC_AUTO_TWIN_SUPERSESSION_OLD_STATE_UNKNOWN"
                )

            missing_replacements = [
                key
                for key in (
                    normalized_replacements
                )
                if key not in states
            ]

            if missing_replacements:
                raise ValueError(
                    "QCC_AUTO_TWIN_SUPERSESSION_REPLACEMENT_UNKNOWN"
                )

            supersessions = (
                twin_state.setdefault(
                    "supersessions",
                    {},
                )
            )

            existing = supersessions.get(
                old_state_key
            )

            if existing is not None:
                if (
                    list(
                        existing.get(
                            "replacement_state_keys"
                        )
                        or ()
                    )
                    == list(
                        normalized_replacements
                    )
                ):
                    # Idempotent re-supersession of the same target.
                    return deepcopy(
                        existing
                    )

                raise ValueError(
                    "QCC_AUTO_TWIN_SUPERSESSION_IMMUTABLE_CONFLICT"
                )

            record = {
                "schema_version":
                    AUTO_TWIN_OBSERVATION_SUPERSESSION_SCHEMA_VERSION,

                "record_type":
                    AUTO_TWIN_OBSERVATION_SUPERSESSION_TYPE,

                "twin_key":
                    managed_twin.twin_key,

                "old_state_key":
                    old_state_key,

                "replacement_state_keys":
                    list(
                        normalized_replacements
                    ),

                "reason":
                    reason,

                "recorded_at":
                    recorded_at,

                "provenance":
                    deepcopy(
                        provenance
                    )
                    if provenance
                    else {},
            }

            supersessions[
                old_state_key
            ] = record

            next_revision = (
                self._revision
                + 1
            )

            self._persist(
                twins=candidate,
                revision=next_revision,
            )

            self._twins = candidate
            self._revision = (
                next_revision
            )

            return deepcopy(
                record
            )

    def enrich_supersession_provenance(
        self,
        managed_twin,
        *,
        old_state_key,
        replacement_navigation_context_signatures,
    ) -> dict:
        """Append-safe corroboration enrichment (WO 2D-20S).

        Adds ``PROVENANCE_CORROBORATION_KEY`` entries to an EXISTING
        supersession record's ``provenance`` -- never creates a
        supersession, never touches ``old_state_key``,
        ``replacement_state_keys``, ``reason``, ``recorded_at`` or any
        other provenance key, and never rewrites or removes a
        corroboration entry a previous call already wrote.

        Idempotent: re-applying the exact same mapping is a no-op
        that returns the existing record unchanged, without bumping
        ``revision``. Applying a DIFFERENT entry for a
        ``replacement_state_key`` that was already corroborated is
        rejected -- once recorded, a corroboration entry is immutable,
        mirroring the supersession record itself.
        """

        if not isinstance(
            managed_twin,
            AutoTwinManagedSite,
        ):
            raise TypeError(
                "QCC_AUTO_TWIN_MANAGED_SITE_INVALID"
            )

        old_state_key = _text(
            old_state_key
        )

        if not old_state_key:
            raise ValueError(
                "QCC_AUTO_TWIN_SUPERSESSION_OLD_STATE_KEY_REQUIRED"
            )

        if (
            not isinstance(
                replacement_navigation_context_signatures,
                dict,
            )
            or not replacement_navigation_context_signatures
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_SUPERSESSION_PROVENANCE_"
                "CORROBORATION_REQUIRED"
            )

        with self._lock:
            candidate = deepcopy(
                self._twins
            )

            twin_state = candidate.get(
                managed_twin.twin_key
            )

            if twin_state is None:
                raise ValueError(
                    "QCC_AUTO_TWIN_SUPERSESSION_TWIN_UNKNOWN"
                )

            supersessions = (
                twin_state.get(
                    "supersessions"
                )
                or {}
            )

            record = supersessions.get(
                old_state_key
            )

            if record is None:
                raise ValueError(
                    "QCC_AUTO_TWIN_SUPERSESSION_NOT_FOUND"
                )

            declared_replacements = set(
                record.get(
                    "replacement_state_keys"
                )
                or ()
            )

            normalized_entries = {}

            for (
                replacement_key,
                entry,
            ) in (
                replacement_navigation_context_signatures
                .items()
            ):
                key = _text(
                    replacement_key
                )

                if (
                    not key
                    or key
                    not in declared_replacements
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_SUPERSESSION_PROVENANCE_"
                        "CORROBORATION_REPLACEMENT_UNKNOWN"
                    )

                if not isinstance(
                    entry,
                    dict,
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_SUPERSESSION_PROVENANCE_"
                        "CORROBORATION_ENTRY_INVALID"
                    )

                signature = _text(
                    entry.get(
                        "context_signature"
                    )
                )

                fingerprint = _text(
                    entry.get(
                        "fingerprint"
                    )
                )

                if (
                    not signature
                    or not fingerprint
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_SUPERSESSION_PROVENANCE_"
                        "CORROBORATION_ENTRY_INVALID"
                    )

                normalized_entries[key] = {
                    "context_signature":
                        signature.lower(),

                    "fingerprint":
                        fingerprint.lower(),
                }

            provenance = record.setdefault(
                "provenance",
                {},
            )

            existing_corroboration = (
                provenance.get(
                    PROVENANCE_CORROBORATION_KEY
                )
                or {}
            )

            merged_corroboration = dict(
                existing_corroboration
            )

            changed = False

            for (
                key,
                entry,
            ) in normalized_entries.items():
                existing_entry = (
                    existing_corroboration.get(
                        key
                    )
                )

                if existing_entry is not None:
                    if existing_entry == entry:
                        continue

                    raise ValueError(
                        "QCC_AUTO_TWIN_SUPERSESSION_PROVENANCE_"
                        "CORROBORATION_CONFLICT"
                    )

                merged_corroboration[key] = entry
                changed = True

            if not changed:
                return deepcopy(
                    record
                )

            provenance[
                PROVENANCE_CORROBORATION_KEY
            ] = merged_corroboration

            next_revision = (
                self._revision
                + 1
            )

            self._persist(
                twins=candidate,
                revision=next_revision,
            )

            self._twins = candidate
            self._revision = (
                next_revision
            )

            return deepcopy(
                record
            )
