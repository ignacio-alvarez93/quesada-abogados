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
