"""
Runner externo para sesión WhatsApp Web.

V1:
- abre Chrome con perfil persistente;
- muestra el QR cuando sea necesario;
- espera autenticación manual;
- informa del estado de sesión;
- mantiene Chrome abierto hasta confirmación humana.

No importa conversaciones.
No envía mensajes.
"""

import argparse
import time

from backend.automation.connectors.whatsapp_connector import (
    SESSION_STATUS_LOADING,
    SESSION_STATUS_NEEDS_LOGIN,
    SESSION_STATUS_READY,
    WhatsAppConnector,
)


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--profile-key",
        default="whatsapp_dev",
    )

    parser.add_argument(
        "--wait-timeout",
        type=int,
        default=300,
    )

    return parser.parse_args()


def main():
    args = parse_args()

    connector = WhatsAppConnector(
        profile_key=args.profile_key,
        headless=False,
    )

    browser = connector.start()

    print()
    print(
        "=============================================="
    )
    print(
        " WHATSAPP WEB · SESIÓN DE DESARROLLO"
    )
    print(
        "=============================================="
    )
    print()
    print(
        "PROFILE KEY:",
        connector.profile_key,
    )
    print()

    deadline = (
        time.time()
        + max(
            30,
            int(args.wait_timeout),
        )
    )

    last_status = None

    while time.time() < deadline:
        status = (
            connector
            .detect_session_status()
        )

        status_changed = (
            status != last_status
        )

        if status_changed:
            print(
                "SESSION STATUS:",
                status,
            )

            if (
                status
                == SESSION_STATUS_NEEDS_LOGIN
            ):
                print(
                    "Escanea el QR desde el móvil."
                )

            last_status = status

        if status == SESSION_STATUS_READY:
            print()
            print(
                "WhatsApp Web está autenticado."
            )
            break

        if status == SESSION_STATUS_LOADING:
            pass

        time.sleep(2)

    else:
        print()
        print(
            "No se pudo confirmar READY "
            "antes del timeout."
        )

    print()
    print(
        "Pulsa ENTER en esta consola "
        "cuando quieras finalizar la sesión."
    )

    try:
        input()

    finally:
        connector.close()


if __name__ == "__main__":
    main()
