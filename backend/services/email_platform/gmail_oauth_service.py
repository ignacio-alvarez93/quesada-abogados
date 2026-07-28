"""
Autenticación OAuth 2.0 para Gmail API.

Principios:

- no almacena contraseñas;
- usa exclusivamente gmail.readonly;
- guarda el token renovable fuera de Git;
- permite rutas configurables por cuenta o variables de entorno;
- no depende de Flet.
"""

import json
import os
from pathlib import Path


GMAIL_READONLY_SCOPE = (
    "https://www.googleapis.com/auth/gmail.readonly"
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_CLIENT_SECRET_PATH = (
    PROJECT_ROOT
    / "data"
    / "google_oauth"
    / "gmail_client_secret.json"
)

DEFAULT_TOKEN_PATH = (
    PROJECT_ROOT
    / "data"
    / "google_oauth"
    / "gmail_token.json"
)


def _load_optional_dependencies():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise RuntimeError(
            "Faltan las dependencias de Gmail API. "
            "Ejecuta: pip install -r requirements.txt"
        ) from exc

    return Request, Credentials, InstalledAppFlow


def _account_config(account):
    try:
        config = json.loads(
            account.get("config_json")
            or "{}"
        )
    except Exception:
        config = {}

    credential_key = str(
        account.get("credential_key")
        or "QUESADA_GMAIL"
    ).strip().upper()

    client_secret_path = (
        os.getenv(
            credential_key + "_CLIENT_SECRET_PATH",
            "",
        )
        or config.get("client_secret_path")
        or DEFAULT_CLIENT_SECRET_PATH
    )

    token_path = (
        os.getenv(
            credential_key + "_TOKEN_PATH",
            "",
        )
        or config.get("token_path")
        or DEFAULT_TOKEN_PATH
    )

    return {
        "client_secret_path":
            Path(client_secret_path).expanduser(),
        "token_path":
            Path(token_path).expanduser(),
    }


def get_paths(account):
    config = _account_config(account)

    return {
        "client_secret_path":
            str(config["client_secret_path"]),
        "token_path":
            str(config["token_path"]),
    }


def load_credentials(
    account,
    *,
    interactive=True,
):
    """
    Carga, renueva o crea las credenciales OAuth de Gmail.

    interactive=False:
        nunca abre el navegador; falla si no existe un token válido.

    interactive=True:
        puede abrir el navegador para la autorización inicial.
    """
    Request, Credentials, InstalledAppFlow = (
        _load_optional_dependencies()
    )

    config = _account_config(account)

    client_secret_path = config[
        "client_secret_path"
    ]

    token_path = config["token_path"]

    credentials = None

    if token_path.exists():
        try:
            credentials = (
                Credentials.from_authorized_user_file(
                    str(token_path),
                    [GMAIL_READONLY_SCOPE],
                )
            )
        except Exception as exc:
            raise RuntimeError(
                "El token OAuth de Gmail no se pudo leer: "
                f"{exc}"
            ) from exc

    if (
        credentials
        and credentials.expired
        and credentials.refresh_token
    ):
        try:
            credentials.refresh(Request())
        except Exception as exc:
            raise RuntimeError(
                "No se pudo renovar el token OAuth "
                f"de Gmail: {exc}"
            ) from exc

    if not credentials or not credentials.valid:
        if not interactive:
            raise RuntimeError(
                "Gmail todavía no está autorizado. "
                "Ejecuta el asistente OAuth inicial."
            )

        if not client_secret_path.exists():
            raise RuntimeError(
                "No existe el archivo OAuth de Gmail: "
                + str(client_secret_path)
            )

        flow = (
            InstalledAppFlow
            .from_client_secrets_file(
                str(client_secret_path),
                [GMAIL_READONLY_SCOPE],
            )
        )

        credentials = flow.run_local_server(
            port=0,
            access_type="offline",
            prompt="consent",
        )

    token_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    token_path.write_text(
        credentials.to_json(),
        encoding="utf-8",
    )

    return credentials
