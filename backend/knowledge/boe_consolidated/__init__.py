"""Provider BOE Legislación Consolidada para Knowledge."""

from .parser import (
    parse_boe_consolidated_structure,
)
from .provider import (
    BoeConsolidatedProvider,
    BoeConsolidatedTransport,
)
from .transport import (
    BoeConsolidatedHttpTransport,
    BoeConsolidatedTransportError,
)
from .validity import (
    resolve_boe_consolidated_validity,
)

__all__ = [
    "parse_boe_consolidated_structure",
    "BoeConsolidatedHttpTransport",
    "BoeConsolidatedProvider",
    "BoeConsolidatedTransport",
    "BoeConsolidatedTransportError",
    "resolve_boe_consolidated_validity",
]
