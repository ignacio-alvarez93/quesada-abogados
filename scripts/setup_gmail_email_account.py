"""
Registra o actualiza la cuenta Gmail del CRM.

No realiza todavía la autorización OAuth.
"""

from backend.services.email_platform import (
    email_account_service,
)


ACCOUNT_EMAIL = (
    "quesadaabogadosextranjeria@gmail.com"
)


def main():
    account = email_account_service.ensure_account(
        nombre="Gmail Extranjería",
        email_address=ACCOUNT_EMAIL,
        provider="GMAIL_API",
        credential_key="QUESADA_GMAIL",
        incoming_enabled=True,
        outgoing_enabled=False,
        config={
            "sender_filter":
                "notificaciones.extranjeria@correo.gob.es",
            "initial_lookback_days": 30,
            "max_results": 100,
            "client_secret_path":
                "data/google_oauth/"
                "gmail_client_secret.json",
            "token_path":
                "data/google_oauth/"
                "gmail_token.json",
        },
    )

    print("Cuenta Gmail configurada:")
    print("  id:", account["id"])
    print(
        "  email:",
        account["email_address"],
    )
    print(
        "  provider:",
        account["provider"],
    )
    print(
        "  credential_key:",
        account["credential_key"],
    )


if __name__ == "__main__":
    main()
