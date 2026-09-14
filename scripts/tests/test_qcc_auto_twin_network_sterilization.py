from backend.qcc.auto_twin.runtime_network_sterilization import (
    AUTO_TWIN_NETWORK_STERILIZER_VERSION,
    sterilize_runtime_html,
)


def test_sterilizer_is_versioned():
    assert (
        AUTO_TWIN_NETWORK_STERILIZER_VERSION
        == 1
    )


def test_remote_base_becomes_local():
    html, stats = sterilize_runtime_html(
        '<html><head>'
        '<base href="https://example.invalid/app/">'
        '</head></html>'
    )

    assert (
        '<base href="./" '
        'data-qcc-auto-twin-network-sterilized="1">'
        in html
    )

    assert (
        "example.invalid"
        not in html
    )

    assert (
        stats[
            "base_tags_rewritten"
        ]
        == 1
    )


def test_remote_resource_links_are_removed():
    html, stats = sterilize_runtime_html(
        '<link rel="manifest" '
        'href="https://example.invalid/site.webmanifest">'
        '<link rel="modulepreload" '
        'href="//example.invalid/chunk.js">'
        '<link rel="stylesheet" href="assets/local.css">'
    )

    assert (
        "site.webmanifest"
        not in html
    )

    assert (
        "chunk.js"
        not in html
    )

    assert (
        'href="assets/local.css"'
        in html
    )

    assert (
        stats[
            "external_link_tags_removed"
        ]
        == 2
    )


def test_remote_script_is_removed_local_script_survives():
    html, stats = sterilize_runtime_html(
        '<script src="https://example.invalid/app.js"></script>'
        '<script src="assets/local.js"></script>'
    )

    assert (
        "example.invalid"
        not in html
    )

    assert (
        'src="assets/local.js"'
        in html
    )

    assert (
        stats[
            "external_script_tags_removed"
        ]
        == 1
    )


def test_external_navigation_is_neutralized():
    html, stats = sterilize_runtime_html(
        '<a href="https://example.invalid/path">X</a>'
        '<form action="//example.invalid/post"></form>'
    )

    assert (
        'href="#"'
        in html
    )

    assert (
        'action="#"'
        in html
    )

    assert (
        "example.invalid"
        not in html
    )

    assert (
        stats[
            "external_attributes_rewritten"
        ]
        == 2
    )


def test_external_media_is_inert():
    html, _ = sterilize_runtime_html(
        '<img src="https://example.invalid/a.png">'
        '<video poster="//example.invalid/p.jpg"></video>'
        '<img srcset="https://example.invalid/a.png 1x">'
    )

    assert (
        'src="data:,"'
        in html
    )

    assert (
        'poster="data:,"'
        in html
    )

    assert (
        'srcset=""'
        in html
    )

    assert (
        "example.invalid"
        not in html
    )


def test_relative_and_data_resources_are_preserved():
    source = (
        '<img src="assets/logo.svg">'
        '<img src="data:image/png;base64,AA==">'
        '<a href="#main">Main</a>'
    )

    result, _ = (
        sterilize_runtime_html(
            source
        )
    )

    assert result == source
