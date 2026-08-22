from backend.automation.site_architecture.geometry import (
    normalize_element_geometry,
    normalize_viewport,
)


def test_normalize_viewport_preserves_browser_geometry():
    viewport = normalize_viewport({
        "inner_width": 1280,
        "inner_height": 720,
        "client_width": 1265,
        "client_height": 705,
        "scroll_x": 120,
        "scroll_y": 340,
        "device_pixel_ratio": 1.25,
        "screen_x": 40,
        "screen_y": 20,
        "outer_width": 1296,
        "outer_height": 839,
    })

    assert viewport.inner_width == 1280
    assert viewport.scroll_y == 340
    assert viewport.device_pixel_ratio == 1.25
    assert viewport.screen_x == 40
    assert viewport.outer_height == 839


def test_main_element_geometry_uses_top_level_viewport():
    geometry = normalize_element_geometry({
        "frame_path": "main",
        "rect": {
            "x": 100,
            "y": 200,
            "width": 80,
            "height": 40,
        },
    })

    assert (
        geometry["coordinate_space"]
        == "TOP_LEVEL_VIEWPORT"
    )

    assert geometry["center"] == {
        "x": 140.0,
        "y": 220.0,
    }


def test_frame_element_geometry_remains_frame_relative():
    geometry = normalize_element_geometry({
        "frame_path": "1.2",
        "rect": {
            "x": 10,
            "y": 20,
            "width": 100,
            "height": 30,
        },
    })

    assert (
        geometry["coordinate_space"]
        == "FRAME_VIEWPORT"
    )
    assert geometry["frame_path"] == "1.2"


def test_missing_rect_does_not_invent_geometry():
    geometry = normalize_element_geometry({
        "frame_path": "main",
        "rect": None,
    })

    assert geometry["viewport_rect"] is None
    assert geometry["center"] is None
