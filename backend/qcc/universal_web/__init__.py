"""Universal Web Twin (UWT) — provider-neutral foundation.

UWT-2: Functional State Detector.

Distinguishes SAME_FUNCTIONAL_STATE / FUNCTIONAL_STATE_CHANGED / UNKNOWN
from normalized QCC Site Architecture observable web evidence.

UWT-3: Universal State / Transition Graph.

Provider-neutral directed graph of UWT-2 functional states and the
actions that transition between them. Topology only: no branch-cause
semantics (UWT-4), no AUTO TWIN materialization.

UWT-4: Universal Branch Context.

Provider-neutral, site-neutral representation of branch-relevant context
(radio/checkbox/select/tab/toggle discriminators) built on top of UWT-2.
Does not branch by value: only explicitly established branch-relevant
observations are represented (branch_context.py / branch_discriminators.py).

Provider-neutral, site-neutral, additive to QCC Site Architecture. Does
not implement Branch-Scoped AUTO TWIN Materialization.
"""

from .functional_state import (
    EXTERNAL_UI_BOUNDARY_CERTIFICATE_CHOOSER,
    EXTERNAL_UI_BOUNDARY_FILE_DIALOG,
    EXTERNAL_UI_BOUNDARY_KINDS,
    EXTERNAL_UI_BOUNDARY_NATIVE_DIALOG,
    EXTERNAL_UI_BOUNDARY_OTHER,
    FUNCTIONAL_STATE_SCHEMA_VERSION,
    FUNCTIONAL_STATE_TYPE,
    ExternalUIBoundary,
    FunctionalState,
    build_external_ui_boundary,
    build_functional_state,
)

from .functional_delta import (
    FUNCTIONAL_DELTA_SCHEMA_VERSION,
    FUNCTIONAL_DELTA_TYPE,
    FUNCTIONAL_STATE_CHANGED,
    SAME_FUNCTIONAL_STATE,
    UNKNOWN,
    UNKNOWN_REASON_CONTRADICTORY_EVIDENCE,
    UNKNOWN_REASON_EVIDENCE_UNAVAILABLE,
    UNKNOWN_REASON_EXTERNAL_UI_BOUNDARY,
    UNKNOWN_REASON_MISSING_OBSERVATION,
    FunctionalDelta,
    compare_functional_state,
)

from .stable_state_fingerprint import (
    STABLE_STATE_FINGERPRINT_ALGORITHM,
    STABLE_STATE_FINGERPRINT_SCHEMA_VERSION,
    StableStateFingerprint,
    build_stable_state_fingerprint,
)

from .state_signals import (
    KNOWN_FUNCTIONAL_SIGNAL_NAMES,
    KNOWN_NON_FUNCTIONAL_SIGNAL_NAMES,
    STATE_SIGNAL_SCHEMA_VERSION,
    SignalCategory,
    StateSignal,
    build_state_signal,
)

from .state_graph import (
    STATE_GRAPH_SCHEMA_VERSION,
    STATE_GRAPH_TYPE,
    STATE_NODE_SCHEMA_VERSION,
    STATE_TRANSITION_SCHEMA_VERSION,
    ActionIdentity,
    GraphInvariantError,
    GraphValidationResult,
    StateGraph,
    StateNode,
    StateTransition,
    build_action_identity,
    derive_state_node_id,
    derive_transition_id,
)

from .branch_discriminators import (
    BRANCH_DISCRIMINATOR_SCHEMA_VERSION,
    DISCRIMINATOR_KIND_CHECKBOX,
    DISCRIMINATOR_KIND_RADIO,
    DISCRIMINATOR_KIND_SELECT,
    DISCRIMINATOR_KIND_TAB,
    DISCRIMINATOR_KIND_TOGGLE,
    DISCRIMINATOR_KINDS,
    BranchDiscriminator,
    BranchDiscriminatorError,
    build_branch_discriminator,
)

from .branch_context import (
    BRANCH_CONTEXT_SCHEMA_VERSION,
    BRANCH_CONTEXT_TYPE,
    BranchContext,
    BranchContextError,
    build_branch_context,
)


__all__ = (
    "EXTERNAL_UI_BOUNDARY_CERTIFICATE_CHOOSER",
    "EXTERNAL_UI_BOUNDARY_FILE_DIALOG",
    "EXTERNAL_UI_BOUNDARY_KINDS",
    "EXTERNAL_UI_BOUNDARY_NATIVE_DIALOG",
    "EXTERNAL_UI_BOUNDARY_OTHER",
    "FUNCTIONAL_STATE_SCHEMA_VERSION",
    "FUNCTIONAL_STATE_TYPE",
    "ExternalUIBoundary",
    "FunctionalState",
    "build_external_ui_boundary",
    "build_functional_state",
    "FUNCTIONAL_DELTA_SCHEMA_VERSION",
    "FUNCTIONAL_DELTA_TYPE",
    "FUNCTIONAL_STATE_CHANGED",
    "SAME_FUNCTIONAL_STATE",
    "UNKNOWN",
    "UNKNOWN_REASON_CONTRADICTORY_EVIDENCE",
    "UNKNOWN_REASON_EVIDENCE_UNAVAILABLE",
    "UNKNOWN_REASON_EXTERNAL_UI_BOUNDARY",
    "UNKNOWN_REASON_MISSING_OBSERVATION",
    "FunctionalDelta",
    "compare_functional_state",
    "STABLE_STATE_FINGERPRINT_ALGORITHM",
    "STABLE_STATE_FINGERPRINT_SCHEMA_VERSION",
    "StableStateFingerprint",
    "build_stable_state_fingerprint",
    "KNOWN_FUNCTIONAL_SIGNAL_NAMES",
    "KNOWN_NON_FUNCTIONAL_SIGNAL_NAMES",
    "STATE_SIGNAL_SCHEMA_VERSION",
    "SignalCategory",
    "StateSignal",
    "build_state_signal",
    "STATE_GRAPH_SCHEMA_VERSION",
    "STATE_GRAPH_TYPE",
    "STATE_NODE_SCHEMA_VERSION",
    "STATE_TRANSITION_SCHEMA_VERSION",
    "ActionIdentity",
    "GraphInvariantError",
    "GraphValidationResult",
    "StateGraph",
    "StateNode",
    "StateTransition",
    "build_action_identity",
    "derive_state_node_id",
    "derive_transition_id",
    "BRANCH_DISCRIMINATOR_SCHEMA_VERSION",
    "DISCRIMINATOR_KIND_CHECKBOX",
    "DISCRIMINATOR_KIND_RADIO",
    "DISCRIMINATOR_KIND_SELECT",
    "DISCRIMINATOR_KIND_TAB",
    "DISCRIMINATOR_KIND_TOGGLE",
    "DISCRIMINATOR_KINDS",
    "BranchDiscriminator",
    "BranchDiscriminatorError",
    "build_branch_discriminator",
    "BRANCH_CONTEXT_SCHEMA_VERSION",
    "BRANCH_CONTEXT_TYPE",
    "BranchContext",
    "BranchContextError",
    "build_branch_context",
)
