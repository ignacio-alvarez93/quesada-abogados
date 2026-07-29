"""
Resolución transversal de referencias oficiales contra expedientes.

El resolvedor nunca interpreta el contenido del correo. Recibe una
referencia ya normalizada por el procesador y decide:

- si la familia está soportada;
- si existe una coincidencia exacta;
- si existen varias coincidencias;
- si la referencia no está registrada todavía.
"""


STATUS_MATCHED = "MATCHED"
STATUS_NOT_FOUND = "NOT_FOUND"
STATUS_MULTIPLE = "MULTIPLE"
STATUS_FAMILY_NOT_AVAILABLE = (
    "FAMILY_NOT_AVAILABLE"
)
STATUS_REFERENCE_NOT_DETECTED = (
    "REFERENCE_NOT_DETECTED"
)


def _text(value):
    return str(value or "").strip()


def _upper(value):
    return _text(value).upper()


def _find_extranjeria_candidates(
    conn,
    reference_value,
):
    reference_value = _text(reference_value)

    if not reference_value:
        return []

    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT
                e.id,
                e.cliente_id,
                e.numero_expediente,
                e.numero_expediente_extranjeria,
                e.activo,

                c.nombre,
                c.primer_apellido,
                c.segundo_apellido

            FROM expedientes e

            JOIN clientes c
              ON c.id = e.cliente_id

            WHERE e.activo = 1
              AND TRIM(
                    COALESCE(
                        e.numero_expediente_extranjeria,
                        ''
                    )
                  ) = ?

            ORDER BY e.id ASC
            """,
            (reference_value,),
        ).fetchall()
    ]


def resolve(
    conn,
    *,
    reference_value,
    reference_type,
    family_hint,
):
    reference_value = _text(reference_value)
    reference_type = _upper(reference_type)
    family_hint = _upper(family_hint)

    if not reference_value:
        return {
            "status":
                STATUS_REFERENCE_NOT_DETECTED,
            "reference_value":
                "",
            "reference_type":
                reference_type or "UNKNOWN",
            "family_hint":
                family_hint or "UNKNOWN",
            "candidates": [],
        }

    if (
        reference_type == "NACIONALIDAD_R"
        or family_hint == "NACIONALIDAD"
    ):
        return {
            "status":
                STATUS_FAMILY_NOT_AVAILABLE,
            "reference_value":
                reference_value,
            "reference_type":
                "NACIONALIDAD_R",
            "family_hint":
                "NACIONALIDAD",
            "candidates": [],
        }

    if (
        reference_type
        != "EXTRANJERIA_NUMERIC"
        or family_hint
        != "EXTRANJERIA"
    ):
        return {
            "status":
                STATUS_FAMILY_NOT_AVAILABLE,
            "reference_value":
                reference_value,
            "reference_type":
                reference_type or "UNKNOWN",
            "family_hint":
                family_hint or "UNKNOWN",
            "candidates": [],
        }

    candidates = _find_extranjeria_candidates(
        conn,
        reference_value,
    )

    if len(candidates) == 0:
        status = STATUS_NOT_FOUND
    elif len(candidates) > 1:
        status = STATUS_MULTIPLE
    else:
        status = STATUS_MATCHED

    return {
        "status": status,
        "reference_value": reference_value,
        "reference_type": reference_type,
        "family_hint": family_hint,
        "candidates": candidates,
    }
