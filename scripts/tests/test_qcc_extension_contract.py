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
    assert manifest["version"] == "0.1.0"

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


def test_qcc_v1_shell_has_no_host_permissions():
    manifest = _load_manifest(
        QCC_DIR / "manifest.json"
    )

    assert "host_permissions" not in manifest


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
