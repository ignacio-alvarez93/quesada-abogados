# --- MODIFICADO PARA URL PRESENTACION ---
# SOLO PARTE RELEVANTE A INSERTAR

def create_tipo_expediente(data):
    codigo = _normalize_code(data.get("codigo") or data.get("nombre"))
    nombre = _normalize_text(data.get("nombre"))
    descripcion = (data.get("descripcion") or "").strip()
    url_presentacion = (data.get("url_presentacion") or "").strip()

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO config_tipos_expediente (codigo, nombre, descripcion, url_presentacion, activo)
            VALUES (?, ?, ?, ?, ?)
            """,
            (codigo, nombre, descripcion, url_presentacion, int(data.get("activo", 1))),
        )
        conn.commit()
        return cur.lastrowid


def update_tipo_expediente(record_id, data):
    codigo = _normalize_code(data.get("codigo") or data.get("nombre"))
    nombre = _normalize_text(data.get("nombre"))
    descripcion = (data.get("descripcion") or "").strip()
    url_presentacion = (data.get("url_presentacion") or "").strip()

    with _connect() as conn:
        conn.execute(
            """
            UPDATE config_tipos_expediente
            SET codigo = ?, nombre = ?, descripcion = ?, url_presentacion = ?, activo = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (codigo, nombre, descripcion, url_presentacion, int(data.get("activo", 1)), record_id),
        )
        conn.commit()
