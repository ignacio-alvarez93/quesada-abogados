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
