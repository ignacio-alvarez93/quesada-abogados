"""QCC Contract Watcher — retention protection adapter (1H).

Smallest possible bridge between the provider-neutral retention
protection contract ``QccSiteArchitectureIngestor`` accepts
(``protected_capture_ids``, see
``backend.qcc.site_architecture.ingestor``) and Contract Watcher's own
governed, durable notion of "not yet independently evidenced" (see
``contract_watcher_governed_protected_capture_ids`` in
``contract_watcher_persisted_backlog``).

``backend.qcc.site_architecture`` never imports this module or anything
else from ``backend.qcc.auto_twin``: it only ever consumes an opaque
collection/callable handed to it by whatever constructs the ingestor.
This module is that construction-time glue, kept entirely on the AUTO
TWIN side of the boundary.

Remaining invocation boundary (explicitly out of scope for this Work
Order, per its own instructions): the actual production
``QccSiteArchitectureIngestor()`` used for live capture ingestion is
constructed inside ``backend/qcc/bridge/server.py`` (QCC Bridge
transport), which this Work Order is not permitted to modify. Wiring
``contract_watcher_retention_protected_capture_id_provider(...)`` into
that real ingestor -- i.e. actually passing
``protected_capture_ids=...`` to the ``QccSiteArchitectureIngestor``
instance the bridge/Runner constructs for live traffic -- is therefore
left to whatever process wires up ``QccBridgeServer`` (it already
accepts an injectable ``site_architecture_ingestor``), and is reported
here rather than solved by reaching into forbidden modules or inventing
hidden global coupling.
"""

from __future__ import annotations

from .contract_watcher_persisted_backlog import (
    contract_watcher_governed_protected_capture_ids,
)
from .observation_store import AutoTwinObservationStore


def contract_watcher_retention_protected_capture_id_provider(
    observation_store,
    *,
    capture_root=None,
    evidence_store=None,
    history_store=None,
):
    """Builds the zero-argument provider ``protected_capture_ids`` expects.

    Every invocation of the returned callable recomputes the protected
    set fresh, entirely from durable state (the persisted capture
    store, ``observation_store``'s own persisted snapshot and Contract
    Watcher's evidence/history stores) -- never from an in-memory
    cursor kept by this adapter. Calling it again after a process
    restart, against the same durable stores, reconstructs the exact
    same protected set.

    Raises whatever ``contract_watcher_governed_protected_capture_ids``
    raises; this adapter never swallows a resolution failure.
    ``QccSiteArchitectureIngestor`` itself is the layer responsible for
    treating a raising provider as a fail-closed "skip pruning this
    pass" signal.
    """

    if not isinstance(observation_store, AutoTwinObservationStore):
        raise TypeError(
            "QCC_CONTRACT_WATCHER_RETENTION_ADAPTER_OBSERVATION_STORE_INVALID"
        )

    capture_root_kwargs = (
        {} if capture_root is None else {"capture_root": capture_root}
    )

    def _provider():
        return contract_watcher_governed_protected_capture_ids(
            observation_store,
            evidence_store=evidence_store,
            history_store=history_store,
            **capture_root_kwargs,
        )

    return _provider
