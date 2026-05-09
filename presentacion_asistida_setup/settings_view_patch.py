# --- AÑADIR EN build_tipos() ---
url_presentacion = text_input(
    "URL presentación",
    editing.get("url_presentacion", ""),
    width=560
)

# En form:
ft.Row([codigo, nombre, activo], wrap=True, spacing=10),
url_presentacion,
descripcion,

# En save():
"url_presentacion": url_presentacion.value,
