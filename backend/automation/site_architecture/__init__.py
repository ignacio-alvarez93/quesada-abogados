"""QCC Site Architecture."""

from .models import (
    SiteArchitecturePage,
    SiteArchitectureSnapshot,
    SiteArchitectureSource,
    SiteArchitectureViewport,
)
from .schema import (
    SITE_ARCHITECTURE_SCHEMA_VERSION,
    SITE_ARCHITECTURE_SOURCE_DOM_CAPTURE,
)


__all__ = (
    "SITE_ARCHITECTURE_SCHEMA_VERSION",
    "SITE_ARCHITECTURE_SOURCE_DOM_CAPTURE",
    "SiteArchitecturePage",
    "SiteArchitectureSnapshot",
    "SiteArchitectureSource",
    "SiteArchitectureViewport",
)

from .normalizer import (
    normalize_dom_capture,
)

__all__ += (
    "normalize_dom_capture",
)

from .semantics import (
    SiteElementSemantic,
    classify_element_semantics,
)

__all__ += (
    "SiteElementSemantic",
    "classify_element_semantics",
)

from .selectors import (
    SelectorCandidate,
    SelectorConfidence,
    SelectorProfile,
    SelectorStrategy,
    build_selector_candidates,
    resolve_selector_profile,
)

__all__ += (
    "SelectorCandidate",
    "SelectorConfidence",
    "SelectorProfile",
    "SelectorStrategy",
    "build_selector_candidates",
    "resolve_selector_profile",
)

from .snapshot import (
    build_normalized_snapshot_payload,
    write_normalized_snapshot,
)

__all__ += (
    "build_normalized_snapshot_payload",
    "write_normalized_snapshot",
)

from .contract_diff import (
    ContractChange,
    diff_site_architecture,
)

__all__ += (
    "ContractChange",
    "diff_site_architecture",
)

from .service import (
    capture_site_architecture,
    persist_site_architecture_from_raw,
)

__all__ += (
    "capture_site_architecture",
    "persist_site_architecture_from_raw",
)

from .qcc_capture_adapter import (
    adapt_qcc_extension_capture,
)
from .service import (
    persist_site_architecture_from_qcc_capture,
)

__all__ += (
    "adapt_qcc_extension_capture",
    "persist_site_architecture_from_qcc_capture",
)

from .catalogs import (
    CATALOG_EVIDENCE_DOM_ATTRIBUTE_REFERENCE,
    CATALOG_RELATION_DOM_REFERENCE,
    build_catalog_reference_graph,
    normalize_catalogs,
)

__all__ += (
    "CATALOG_EVIDENCE_DOM_ATTRIBUTE_REFERENCE",
    "CATALOG_RELATION_DOM_REFERENCE",
    "build_catalog_reference_graph",
    "normalize_catalogs",
)

from .catalog_dynamics import (
    CATALOG_CAUSAL_EVIDENCE_OBSERVED_MUTATION,
    CATALOG_DYNAMIC_OPTIONS_CHANGED,
    CATALOG_DYNAMIC_SOURCE_SELECTION_CHANGED,
    CATALOG_RELATION_DEPENDS_ON,
    CATALOG_RELATION_INFLUENCES,
    build_catalog_causal_relations,
    build_catalog_dynamic_evidence,
)

__all__ += (
    "CATALOG_DYNAMIC_OPTIONS_CHANGED",
    "CATALOG_DYNAMIC_SOURCE_SELECTION_CHANGED",
    "build_catalog_dynamic_evidence",
)

from .catalog_experiments import (
    QCC_CATALOG_EXPERIMENT_SAFETY_TWIN_ONLY,
    QCC_CATALOG_EXPERIMENT_TWIN_ORIGIN,
    QCC_CATALOG_EXPERIMENT_TYPE,
    analyze_qcc_catalog_experiment,
)

__all__ += (
    "QCC_CATALOG_EXPERIMENT_SAFETY_TWIN_ONLY",
    "QCC_CATALOG_EXPERIMENT_TYPE",
    "analyze_qcc_catalog_experiment",
)

from .action_inventory import (
    ACTION_INVENTORY_SCHEMA_VERSION,
    ACTION_POLICY_NAVIGATION,
    ACTION_POLICY_REQUIRES_POLICY,
    ACTION_POLICY_STATE_CHANGE,
    ACTION_POLICY_VALUE_CHANGE,
    build_action_inventory,
)


from .state_fingerprint import (
    FUNCTIONAL_STATE_HASH_ALGORITHM,
    FUNCTIONAL_STATE_SCHEMA_VERSION,
    FUNCTIONAL_STATE_TYPE,
    build_functional_state_fingerprint,
    build_functional_state_payload,
    canonicalize_functional_state,
)


from .state_transition import (
    STATE_TRANSITION_CHANGED,
    STATE_TRANSITION_CONFIDENCE_HIGH,
    STATE_TRANSITION_CONFIDENCE_LOW,
    STATE_TRANSITION_CONFIDENCE_MEDIUM,
    STATE_TRANSITION_SCHEMA_VERSION,
    STATE_TRANSITION_TYPE,
    STATE_TRANSITION_UNCHANGED,
    detect_state_transition,
)


from .action_safety import (
    ACTION_SAFETY_DENY,
    ACTION_SAFETY_HUMAN_ONLY,
    ACTION_SAFETY_NAVIGATION_CANDIDATE,
    ACTION_SAFETY_REVERSIBLE_CANDIDATE,
    ACTION_SAFETY_REVIEW_REQUIRED,
    ACTION_SAFETY_SCHEMA_VERSION,
    evaluate_action_safety,
)


from .site_target import (
    SITE_TARGET_SCHEMA_VERSION,
    SiteEnvironment,
    SiteTarget,
    SiteTargetConfigurationError,
    SiteTargetMode,
)


from .managed_execution import (
    MANAGED_EXECUTION_AUTHORIZED,
    MANAGED_EXECUTION_DENY,
    MANAGED_EXECUTION_SCHEMA_VERSION,
    ManagedSiteProfile,
    ManagedSiteProfileConfigurationError,
    authorize_managed_target,
)

__all__ += (
    "MANAGED_EXECUTION_AUTHORIZED",
    "MANAGED_EXECUTION_DENY",
    "MANAGED_EXECUTION_SCHEMA_VERSION",
    "ManagedSiteProfile",
    "ManagedSiteProfileConfigurationError",
    "authorize_managed_target",
)


from .site_interaction_policy import (
    SITE_INTERACTION_AUTOMATION_ALLOWED,
    SITE_INTERACTION_DENY,
    SITE_INTERACTION_HUMAN_ONLY,
    SITE_INTERACTION_SCHEMA_VERSION,
    SiteInteractionPolicy,
    SiteInteractionPolicyConfigurationError,
    evaluate_site_interaction,
)

__all__ += (
    "SITE_INTERACTION_AUTOMATION_ALLOWED",
    "SITE_INTERACTION_DENY",
    "SITE_INTERACTION_HUMAN_ONLY",
    "SITE_INTERACTION_SCHEMA_VERSION",
    "SiteInteractionPolicy",
    "SiteInteractionPolicyConfigurationError",
    "evaluate_site_interaction",
)

from .navigation_graph import (
    NAVIGATION_GRAPH_SCHEMA_VERSION,
    NAVIGATION_GRAPH_TYPE,
    build_navigation_graph,
)

__all__ += (
    "NAVIGATION_GRAPH_SCHEMA_VERSION",
    "NAVIGATION_GRAPH_TYPE",
    "build_navigation_graph",
)

