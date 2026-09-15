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

__all__ = [
    "parse_boe_consolidated_structure",
    "BoeConsolidatedHttpTransport",
    "BoeConsolidatedProvider",
    "BoeConsolidatedTransport",
    "BoeConsolidatedTransportError",
]
