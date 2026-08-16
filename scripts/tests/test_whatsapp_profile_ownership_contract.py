"""
Contrato de ownership del perfil persistente WhatsApp.

La aplicación productiva mantiene una única vía gobernada:

app/main.py
    -> WhatsAppRuntimeService
    -> WhatsAppConnector
    -> SeleniumBaseBrowserSession

No debe reaparecer un runner externo que abra otro Chrome
sobre el mismo profile_key.
"""

from pathlib import Path


PROJECT_ROOT = (
    Path(__file__).resolve().parents[2]
)

APP_MAIN = (
    PROJECT_ROOT
    / "app"
    / "main.py"
)

LEGACY_RUNNER = (
    PROJECT_ROOT
    / "app"
    / "run_whatsapp_session.py"
)

LEGACY_SERVICE = (
    PROJECT_ROOT
    / "backend"
    / "services"
    / "whatsapp_session_service.py"
)


def test_legacy_external_whatsapp_entrypoints_are_absent():
    assert not LEGACY_RUNNER.exists(), (
        "No debe existir un runner externo WhatsApp "
        "con ownership independiente del perfil persistente"
    )

    assert not LEGACY_SERVICE.exists(), (
        "No debe existir un servicio productivo que lance "
        "otro proceso WhatsApp sobre el mismo perfil"
    )


def test_erp_has_single_whatsapp_runtime_composition_root():
    source = APP_MAIN.read_text(
        encoding="utf-8"
    )

    assert (
        source.count(
            "WhatsAppRuntimeService("
        )
        == 1
    ), (
        "app/main.py debe componer exactamente "
        "un WhatsAppRuntimeService productivo"
    )

    assert (
        "backend.services.whatsapp_session_service"
        not in source
    )

    assert (
        "start_whatsapp_session_external"
        not in source
    )


def test_product_tree_has_no_legacy_external_launcher_symbol():
    roots = (
        PROJECT_ROOT / "app",
        PROJECT_ROOT / "backend",
        PROJECT_ROOT / "frontend",
    )

    findings = []

    for root in roots:
        for path in root.rglob("*.py"):
            text = path.read_text(
                encoding="utf-8",
                errors="replace",
            )

            if (
                "start_whatsapp_session_external"
                in text
            ):
                findings.append(
                    str(
                        path.relative_to(
                            PROJECT_ROOT
                        )
                    )
                )

    assert findings == [], (
        "La antigua vía externa WhatsApp "
        f"ha reaparecido: {findings}"
    )


TESTS = (
    test_legacy_external_whatsapp_entrypoints_are_absent,
    test_erp_has_single_whatsapp_runtime_composition_root,
    test_product_tree_has_no_legacy_external_launcher_symbol,
)


def main():
    passed = 0

    for test in TESTS:
        test()
        passed += 1

    print(
        "WHATSAPP PROFILE OWNERSHIP "
        f"{passed}/{len(TESTS)} OK"
    )


if __name__ == "__main__":
    main()
