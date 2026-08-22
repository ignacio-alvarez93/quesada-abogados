import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

QCC_DIR = ROOT / "chrome_extension" / "qcc"

ICPPLUS_DIR = ROOT / "tools" / "icpplus_dom_reader"


def _load_manifest(path: Path) -> dict:
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def test_qcc_manifest_is_v3_side_panel_extension():
    manifest = _load_manifest(
        QCC_DIR / "manifest.json"
    )

    assert manifest["manifest_version"] == 3
    assert manifest["name"] == (
        "Quesada Chrome Companion"
    )
    assert manifest["version"] == "0.5.0"

    assert manifest["permissions"] == [
        "sidePanel"
    ]

    assert manifest["side_panel"] == {
        "default_path":
            "sidepanel/index.html"
    }

    assert manifest["background"] == {
        "service_worker":
            "background/service_worker.js"
    }


def test_qcc_v1_shell_has_no_content_scripts():
    manifest = _load_manifest(
        QCC_DIR / "manifest.json"
    )

    assert "content_scripts" not in manifest


def test_qcc_has_only_local_bridge_host_permission():
    manifest = _load_manifest(
        QCC_DIR / "manifest.json"
    )

    assert manifest["host_permissions"] == [
        "http://127.0.0.1:8766/*"
    ]


def test_qcc_required_shell_files_exist():
    expected = (
        QCC_DIR / "manifest.json",
        QCC_DIR
        / "background"
        / "service_worker.js",
        QCC_DIR
        / "sidepanel"
        / "index.html",
        QCC_DIR
        / "sidepanel"
        / "sidepanel.css",
        QCC_DIR
        / "sidepanel"
        / "sidepanel.js",
    )

    for path in expected:
        assert path.is_file(), path


def test_qcc_does_not_embed_icpplus_contract():
    forbidden = (
        "ICP_OBSERVER_EVENT",
        "/icpplus",
        "127.0.0.1:8765",
        "Quesada ICP Plus Observer V7",
    )

    for path in QCC_DIR.rglob("*"):
        if not path.is_file():
            continue

        text = path.read_text(
            encoding="utf-8"
        )

        for token in forbidden:
            assert token not in text, (
                path,
                token,
            )


def test_icpplus_observer_remains_independent():
    manifest = _load_manifest(
        ICPPLUS_DIR / "manifest.json"
    )

    assert manifest["name"] == (
        "Quesada ICP Plus Observer V7"
    )

    assert manifest["version"] == "0.7.0"

    assert (
        ICPPLUS_DIR / "background.js"
    ).is_file()

    assert (
        ICPPLUS_DIR / "content.js"
    ).is_file()

    assert (
        ICPPLUS_DIR / "semantic.js"
    ).is_file()


def test_qcc_sidepanel_uses_bridge_health_contract():
    script = (
        QCC_DIR
        / "sidepanel"
        / "sidepanel.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        '"http://127.0.0.1:8766"'
        in script
    )

    assert "/qcc/health" in script
    assert '"qcc_bridge"' in script
    assert '"CRM conectado"' in script
    assert '"CRM desconectado"' in script



def test_qcc_sidepanel_consumes_context_endpoint():
    script = (
        QCC_DIR
        / "sidepanel"
        / "sidepanel.js"
    ).read_text(
        encoding="utf-8"
    )

    assert "/qcc/context" in script
    assert "active_session" in script
    assert "requires_user_action" in script
    assert '"WAITING_USER"' in script


def test_qcc_sidepanel_has_session_projection_fields():
    html = (
        QCC_DIR
        / "sidepanel"
        / "index.html"
    ).read_text(
        encoding="utf-8"
    )

    required_ids = (
        "session-provider",
        "session-procedure",
        "session-expedient",
        "session-client",
        "session-runtime",
        "session-progress-label",
        "session-progress-value",
        "session-status",
        "session-step",
        "user-action-warning",
    )

    for field_id in required_ids:
        assert f'id="{field_id}"' in html


def test_qcc_sidepanel_remains_runtime_agnostic():
    script = (
        QCC_DIR
        / "sidepanel"
        / "sidepanel.js"
    ).read_text(
        encoding="utf-8"
    )

    assert "SELENIUMBASE_ASSISTED" not in script
    assert "DESKTOP_GUI_ASSISTED" not in script
    assert '"MERCURIO"' not in script
    assert '"ICP_PLUS"' not in script



def test_qcc_sidepanel_supports_dynamic_statuses():
    script = (
        QCC_DIR
        / "sidepanel"
        / "sidepanel.js"
    ).read_text(
        encoding="utf-8"
    )

    css = (
        QCC_DIR
        / "sidepanel"
        / "sidepanel.css"
    ).read_text(
        encoding="utf-8"
    )

    assert "session-last-event" in script

    for status in (
        "automating",
        "waiting-user",
        "user-action-detected",
        "resuming",
        "completed",
        "error",
    ):
        assert (
            f"qcc-session-status--{status}"
            in css
        )


def test_qcc_sidepanel_projects_last_event():
    html = (
        QCC_DIR
        / "sidepanel"
        / "index.html"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        'id="session-last-event"'
        in html
    )


def test_qcc_sidepanel_exposes_documents_start_action():
    html = (
        QCC_DIR
        / "sidepanel"
        / "index.html"
    ).read_text(
        encoding="utf-8"
    )

    script = (
        QCC_DIR
        / "sidepanel"
        / "sidepanel.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        'id="action-documents-start"'
        in html
    )

    assert (
        'id="session-action-controls"'
        in html
    )

    assert (
        "Iniciar documentación"
        in html
    )

    assert (
        '"DOCUMENTS_START"'
        in script
    )

    assert (
        "client_action_id"
        in script
    )

    assert (
        "crypto.randomUUID()"
        in script
    )

    assert (
        'method: "POST"'
        in script
    )

    assert (
        "/qcc/session/"
        in script
    )

    assert (
        '=== "DOCUMENTS_READY"'
        in script
    )


def test_qcc_sidepanel_action_does_not_control_browser():
    script = (
        QCC_DIR
        / "sidepanel"
        / "sidepanel.js"
    ).read_text(
        encoding="utf-8"
    )

    forbidden = (
        "executeScript",
        "chrome.scripting",
        "querySelector(",
        "getElementById('btn",
        "seleniumbase",
    )

    for token in forbidden:
        assert token not in script
