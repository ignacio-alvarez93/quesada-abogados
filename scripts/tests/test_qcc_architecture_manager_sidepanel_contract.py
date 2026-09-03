from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

HTML = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "sidepanel"
    / "index.html"
)

CSS = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "sidepanel"
    / "sidepanel.css"
)


def _read(path):
    return path.read_text(
        encoding="utf-8"
    )


def test_launcher_is_qcc_architecture_management():
    html = _read(HTML)

    assert (
        "GESTIÓN DE QCC ARCHITECTURE"
        in html
    )

    assert (
        "Gestión de QCC Architecture"
        in html
    )

    assert (
        "Abrir gestión"
        in html
    )

    assert (
        "HERRAMIENTAS DE NAVEGADOR"
        not in html
    )


def test_architecture_manager_has_own_profile_context():
    html = _read(HTML)

    for element_id in (
        "architecture-current-profile",
        "architecture-current-origin",
        "architecture-current-policy",
        "architecture-current-source",
    ):
        assert (
            f'id="{element_id}"'
            in html
        )

    assert (
        "perfil físico de este"
        in html
    )

    assert (
        "Multi-Browser remota"
        in html
    )


def test_architecture_manager_exposes_policy_controls():
    html = _read(HTML)

    for element_id in (
        "architecture-profile-default",
        "architecture-origin-allow",
        "architecture-origin-deny",
        "architecture-origin-inherit",
        "architecture-origin-list",
        "architecture-policy-feedback",
    ):
        assert (
            f'id="{element_id}"'
            in html
        )


def test_policy_controls_start_disabled():
    html = _read(HTML)

    for element_id in (
        "architecture-profile-default",
        "architecture-origin-allow",
        "architecture-origin-deny",
        "architecture-origin-inherit",
    ):
        pos = html.index(
            f'id="{element_id}"'
        )

        block = html[
            pos:
            pos + 180
        ]

        assert "disabled" in block


def test_existing_dom_tools_remain_available():
    html = _read(HTML)

    for element_id in (
        "tool-dom-inspect",
        "tool-generic-harvest-enable",
        "tool-generic-dom-harvest",
        "tool-generic-dynamic-harvest",
        "tool-generic-harvest-disable",
        "tool-catalog-refresh",
        "tool-catalog-capture",
        "tool-catalog-relation-harvest",
    ):
        assert (
            f'id="{element_id}"'
            in html
        )


def test_architecture_manager_css_contract_exists():
    css = _read(CSS)

    assert (
        "QCC_ARCHITECTURE_MANAGER_UI_V1"
        in css
    )

    for selector in (
        ".qcc-architecture-management",
        ".qcc-architecture-summary",
        ".qcc-architecture-actions",
        ".qcc-architecture-origin-list",
        ".qcc-architecture-origin-item",
    ):
        assert selector in css
