"""Bridge local para Quesada Chrome Companion."""

from backend.qcc.bridge.server import (
    QCC_BRIDGE_HOST,
    QCC_BRIDGE_PORT,
    QCC_PROTOCOL_VERSION,
    QccBridgeServer,
)

__all__ = [
    "QCC_BRIDGE_HOST",
    "QCC_BRIDGE_PORT",
    "QCC_PROTOCOL_VERSION",
    "QccBridgeServer",
]
