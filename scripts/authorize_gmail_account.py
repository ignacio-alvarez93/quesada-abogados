"""
Autoriza la cuenta Gmail mediante OAuth 2.0.

Abre el navegador únicamente cuando no existe un token válido.
"""

from backend.services.email_platform import (
    email_account_service,
    gmail_oauth_service,
)


ACCOUNT_EMAIL = (
    "quesadaabogadosextranjeria@gmail.com"
)


def main():
    accounts = (
        email_account_service
        .get_active_incoming_accounts(
            provider="GMAIL_API"
        )
    )

    account = next(
        (
            item
            for item in accounts
            if (
                item.get("email_address")
                or ""
            ).strip().lower()
            == ACCOUNT_EMAIL
        ),
        None,
    )

    if not account:
        raise RuntimeError(
            "La cuenta Gmail no está configurada. "
            "Ejecuta primero "
            "scripts/setup_gmail_email_account.py"
        )

    paths = gmail_oauth_service.get_paths(
        account
    )

    print(
        "Archivo OAuth:",
        paths["client_secret_path"],
    )
    print(
        "Token local:",
        paths["token_path"],
    )

    credentials = (
        gmail_oauth_service
        .load_credentials(
            account,
            interactive=True,
        )
    )

    print(
        "Autorización Gmail completada:",
        bool(credentials.valid),
    )


if __name__ == "__main__":
    main()
