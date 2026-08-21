"""
Perfil informativo global para consultas ICP Plus.

No pertenece a ningún expediente.

Uso actual:
    Configuración CRM
        -> perfil ICP Plus
        -> consulta de disponibilidad.

Uso futuro:
    cliente/expediente TOMA_DE_HUELLAS
        -> mapper
        -> mismo contrato de ejecución.

No contiene SQL directo.
"""

import re

from backend.services import config_service


ICPPLUS_PROFILE_KEYS = (
    "icpplus_nombre",
    "icpplus_nacionalidad",
    "icpplus_nie",
    "icpplus_telefono",
    "icpplus_email",
)


IDENTITY_KEYS = (
    "icpplus_nombre",
    "icpplus_nacionalidad",
    "icpplus_nie",
)


CONTACT_KEYS = (
    "icpplus_telefono",
    "icpplus_email",
)


def _text(value):
    return str(
        value
        or ""
    ).strip()


def _normalize_nie(value):
    normalized = re.sub(
        r"[\s\-]",
        "",
        _text(value),
    ).upper()

    if not normalized:
        return ""

    if not re.fullmatch(
        r"[XYZ]\d{7}[A-Z]",
        normalized,
    ):
        raise ValueError(
            "NIE ICP Plus no válido"
        )

    return normalized


def _normalize_phone(value):
    value = _text(value)

    if not value:
        return ""

    normalized = re.sub(
        r"[\s\-().]",
        "",
        value,
    )

    if normalized.startswith(
        "00"
    ):
        normalized = (
            "+"
            + normalized[2:]
        )

    if not re.fullmatch(
        r"\+?\d{7,15}",
        normalized,
    ):
        raise ValueError(
            "Teléfono ICP Plus no válido"
        )

    return normalized


def _normalize_email(value):
    value = _text(value).lower()

    if not value:
        return ""

    if not re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+",
        value,
    ):
        raise ValueError(
            "Email ICP Plus no válido"
        )

    return value


def normalize_profile(data):
    data = dict(
        data
        or {}
    )

    return {
        "icpplus_nombre":
            _text(
                data.get(
                    "icpplus_nombre"
                )
            ),

        "icpplus_nacionalidad":
            _text(
                data.get(
                    "icpplus_nacionalidad"
                )
            ),

        "icpplus_nie":
            _normalize_nie(
                data.get(
                    "icpplus_nie"
                )
            ),

        "icpplus_telefono":
            _normalize_phone(
                data.get(
                    "icpplus_telefono"
                )
            ),

        "icpplus_email":
            _normalize_email(
                data.get(
                    "icpplus_email"
                )
            ),
    }


def validate_profile(data):
    try:
        normalized = (
            normalize_profile(
                data
            )
        )

    except ValueError as exc:
        return {
            "valid":
                False,
            "errors":
                [str(exc)],
            "profile":
                dict(
                    data
                    or {}
                ),
        }

    required = {
        "icpplus_nombre":
            "Nombre",

        "icpplus_nacionalidad":
            "Nacionalidad",

        "icpplus_nie":
            "NIE",

        "icpplus_telefono":
            "Teléfono",

        "icpplus_email":
            "Email",
    }

    errors = []

    for key, label in (
        required.items()
    ):
        if not normalized.get(
            key
        ):
            errors.append(
                f"{label} es obligatorio"
            )

    return {
        "valid":
            not errors,

        "errors":
            errors,

        "profile":
            normalized,
    }


def get_profile():
    return {
        key:
            config_service.get_config(
                key,
                "",
            )
        for key
        in ICPPLUS_PROFILE_KEYS
    }


def save_profile(data):
    validation = (
        validate_profile(
            data
        )
    )

    if not validation[
        "valid"
    ]:
        raise ValueError(
            "; ".join(
                validation[
                    "errors"
                ]
            )
        )

    normalized = (
        validation[
            "profile"
        ]
    )

    for key, value in (
        normalized.items()
    ):
        config_service.set_config(
            key,
            value,
        )

    return normalized


def is_profile_complete():
    return validate_profile(
        get_profile()
    )["valid"]


def _validated_profile(
    profile=None,
):
    source = (
        get_profile()
        if profile is None
        else profile
    )

    validation = (
        validate_profile(
            source
        )
    )

    if not validation[
        "valid"
    ]:
        raise ValueError(
            "; ".join(
                validation[
                    "errors"
                ]
            )
        )

    return (
        validation[
            "profile"
        ]
    )


def build_payload(
    profile=None,
):
    """
    Contrato de identidad compatible con el motor existente.
    """

    normalized = (
        _validated_profile(
            profile
        )
    )

    return {
        "nombre":
            normalized[
                "icpplus_nombre"
            ],

        "nacionalidad":
            normalized[
                "icpplus_nacionalidad"
            ],

        "nie":
            normalized[
                "icpplus_nie"
            ],
    }


def build_contact_payload(
    profile=None,
):
    normalized = (
        _validated_profile(
            profile
        )
    )

    return {
        "telefono":
            normalized[
                "icpplus_telefono"
            ],

        "email":
            normalized[
                "icpplus_email"
            ],
    }


def build_execution_profile(
    profile=None,
):
    """
    Perfil completo preparado para una ejecución ICP Plus.
    """

    normalized = (
        _validated_profile(
            profile
        )
    )

    return {
        "identity":
            {
                "nombre":
                    normalized[
                        "icpplus_nombre"
                    ],

                "nacionalidad":
                    normalized[
                        "icpplus_nacionalidad"
                    ],

                "nie":
                    normalized[
                        "icpplus_nie"
                    ],
            },

        "contact":
            {
                "telefono":
                    normalized[
                        "icpplus_telefono"
                    ],

                "email":
                    normalized[
                        "icpplus_email"
                    ],
            },
    }
