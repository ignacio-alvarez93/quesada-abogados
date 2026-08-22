"""Modelos canónicos de QCC Site Architecture."""

from __future__ import annotations

from dataclasses import (
    asdict,
    dataclass,
    field,
)
from typing import Any

from .schema import (
    SITE_ARCHITECTURE_SCHEMA_VERSION,
    require_supported_schema_version,
)


@dataclass(frozen=True, slots=True)
class SiteArchitectureSource:
    kind: str
    schema_version: int


@dataclass(frozen=True, slots=True)
class SiteArchitecturePage:
    url: str = ""
    origin: str = ""
    pathname: str = ""
    query: str = ""
    title: str = ""
    ready_state: str = ""
    signature: str | None = None


@dataclass(frozen=True, slots=True)
class SiteArchitectureViewport:
    inner_width: float | None = None
    inner_height: float | None = None
    client_width: float | None = None
    client_height: float | None = None
    scroll_x: float | None = None
    scroll_y: float | None = None
    device_pixel_ratio: float | None = None
    screen_x: float | None = None
    screen_y: float | None = None
    outer_width: float | None = None
    outer_height: float | None = None


@dataclass(frozen=True, slots=True)
class SiteArchitectureSnapshot:
    source: SiteArchitectureSource

    schema_version: int = (
        SITE_ARCHITECTURE_SCHEMA_VERSION
    )

    captured_at: str | None = None

    page: SiteArchitecturePage = field(
        default_factory=SiteArchitecturePage
    )

    viewport: SiteArchitectureViewport = field(
        default_factory=SiteArchitectureViewport
    )

    documents: tuple[dict[str, Any], ...] = ()
    elements: tuple[dict[str, Any], ...] = ()
    frames: tuple[dict[str, Any], ...] = ()
    shadow_roots: tuple[dict[str, Any], ...] = ()

    counts: dict[str, int] = field(
        default_factory=dict
    )

    diagnostics: tuple[str, ...] = ()

    def __post_init__(self):
        require_supported_schema_version(
            self.schema_version
        )

    def to_dict(self) -> dict[str, Any]:
        """Devuelve representación JSON-safe."""
        return asdict(self)
