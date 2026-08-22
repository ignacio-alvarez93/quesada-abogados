"""Normalización geométrica de QCC Site Architecture."""

from __future__ import annotations

from enum import Enum

from .models import (
    SiteArchitectureViewport,
)


class CoordinateSpace(str, Enum):
    TOP_LEVEL_VIEWPORT = "TOP_LEVEL_VIEWPORT"
    FRAME_VIEWPORT = "FRAME_VIEWPORT"


def _number(value):
    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return value

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_viewport(
    value,
):
    if not isinstance(value, dict):
        return SiteArchitectureViewport()

    return SiteArchitectureViewport(
        inner_width=_number(
            value.get("inner_width")
        ),
        inner_height=_number(
            value.get("inner_height")
        ),
        client_width=_number(
            value.get("client_width")
        ),
        client_height=_number(
            value.get("client_height")
        ),
        scroll_x=_number(
            value.get("scroll_x")
        ),
        scroll_y=_number(
            value.get("scroll_y")
        ),
        device_pixel_ratio=_number(
            value.get("device_pixel_ratio")
        ),
        screen_x=_number(
            value.get("screen_x")
        ),
        screen_y=_number(
            value.get("screen_y")
        ),
        outer_width=_number(
            value.get("outer_width")
        ),
        outer_height=_number(
            value.get("outer_height")
        ),
    )


def normalize_element_geometry(
    element,
):
    if not isinstance(element, dict):
        element = {}

    frame_path = str(
        element.get("frame_path")
        or "main"
    )

    coordinate_space = (
        CoordinateSpace.TOP_LEVEL_VIEWPORT
        if frame_path == "main"
        else CoordinateSpace.FRAME_VIEWPORT
    )

    geometry = {
        "coordinate_space":
            coordinate_space.value,
        "frame_path":
            frame_path,
        "viewport_rect":
            None,
        "center":
            None,
    }

    rect = element.get("rect")

    if not isinstance(rect, dict):
        return geometry

    x = _number(rect.get("x"))
    y = _number(rect.get("y"))
    width = _number(rect.get("width"))
    height = _number(rect.get("height"))

    if None in (
        x,
        y,
        width,
        height,
    ):
        return geometry

    geometry["viewport_rect"] = {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
    }

    geometry["center"] = {
        "x": x + (width / 2),
        "y": y + (height / 2),
    }

    return geometry
