from database.connection import get_connection


def _fetch_all(query, params=None):
    conn = get_connection()

    try:
        cursor = conn.cursor()
        cursor.execute(query, params or [])
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _fetch_names(query, params=None):
    rows = _fetch_all(query, params)
    return [row["nombre"] for row in rows]


def get_paises():
    return _fetch_all(
        """
        SELECT id, nombre, nacionalidad, codigo_iso, codigo_iso3
        FROM paises
        WHERE activo = 1
        ORDER BY nombre
        """
    )


def get_paises_nombres():
    return _fetch_names(
        """
        SELECT nombre
        FROM paises
        WHERE activo = 1
        ORDER BY nombre
        """
    )


def get_nacionalidades():
    rows = _fetch_all(
        """
        SELECT COALESCE(NULLIF(TRIM(nacionalidad), ''), nombre) AS nombre
        FROM paises
        WHERE activo = 1
        ORDER BY nombre
        """
    )
    return [row["nombre"] for row in rows]


def get_comunidades_autonomas():
    return _fetch_all(
        """
        SELECT id, nombre, codigo_comunidad
        FROM comunidades_autonomas
        WHERE activo = 1
        ORDER BY nombre
        """
    )


def get_provincias():
    return _fetch_all(
        """
        SELECT id, nombre, codigo_provincia
        FROM provincias
        WHERE activo = 1
        ORDER BY nombre
        """
    )


def get_provincias_nombres():
    return _fetch_names(
        """
        SELECT nombre
        FROM provincias
        WHERE activo = 1
        ORDER BY nombre
        """
    )


def get_localidades_by_provincia(provincia_nombre):
    if not provincia_nombre:
        return []

    provincia_nombre = provincia_nombre.strip()

    return _fetch_names(
        """
        SELECT l.nombre
        FROM localidades l
        INNER JOIN provincias p ON p.id = l.provincia_id
        WHERE l.activo = 1
          AND p.activo = 1
          AND LOWER(TRIM(p.nombre)) = LOWER(TRIM(?))
        ORDER BY l.nombre
        """,
        [provincia_nombre],
    )


def get_tipos_via():
    return _fetch_names(
        """
        SELECT nombre
        FROM tipos_via
        WHERE activo = 1
        ORDER BY nombre
        """
    )


def get_estados_civiles():
    return _fetch_names(
        """
        SELECT nombre
        FROM estados_civiles
        WHERE activo = 1
        ORDER BY nombre
        """
    )
