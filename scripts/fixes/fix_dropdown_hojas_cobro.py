from pathlib import Path
import re

SERVICE_PATH = Path("backend/services/economic_service.py")
VIEW_PATH = Path("frontend/views/economic_view.py")


def patch_service():
    text = SERVICE_PATH.read_text(encoding="utf-8")

    new_function = """def get_hojas_for_select(cliente_id=None, expediente_id=None):
    sql = \"\"\"
        SELECT DISTINCT
            h.*,
            e.numero_expediente
        FROM eco_hojas_encargo h
        LEFT JOIN expedientes e ON e.id = h.expediente_id
        LEFT JOIN expediente_clientes ec
            ON ec.expediente_id = h.expediente_id
           AND ec.activo = 1
        WHERE h.activo = 1
    \"\"\"
    params = []

    if expediente_id:
        sql += " AND h.expediente_id = ?"
        params.append(int(expediente_id))

    if cliente_id:
        sql += \"\"\"
            AND (
                h.cliente_id = ?
                OR e.cliente_id = ?
                OR ec.cliente_id = ?
            )
        \"\"\"
        params.extend([int(cliente_id), int(cliente_id), int(cliente_id)])

    sql += " ORDER BY h.created_at DESC, h.id DESC"

    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        result = []

        for row in rows:
            item = _dict(row)

            try:
                if "_hoja_totales" in globals():
                    item.update(_hoja_totales(conn, item["id"]))
            except Exception:
                pass

            pendiente_txt = ""
            if "pendiente" in item:
                try:
                    pendiente_txt = f" · Pendiente {float(item.get(\'pendiente\') or 0):.2f} €"
                except Exception:
                    pendiente_txt = ""

            item["display"] = (
                f"{item[\'id\']} - {item.get(\'numero_hoja\') or \'HOJA\'}"
                f" · {item.get(\'numero_expediente\') or \'\'}"
                f" · Neto {float(item.get(\'importe_neto\') or 0):.2f} €"
                f"{pendiente_txt}"
            )
            result.append(item)

        return result
"""

    pattern = r"def get_hojas_for_select\(cliente_id=None, expediente_id=None\):.*?\ndef create_hoja_encargo\(data\):"

    if not re.search(pattern, text, flags=re.S):
        raise RuntimeError("No se pudo localizar get_hojas_for_select en economic_service.py")

    text = re.sub(
        pattern,
        new_function + "\n\ndef create_hoja_encargo(data):",
        text,
        count=1,
        flags=re.S,
    )

    SERVICE_PATH.write_text(text, encoding="utf-8")


def patch_view():
    text = VIEW_PATH.read_text(encoding="utf-8")

    new_refresh = """    def refresh_cobro_hojas_for_expediente(e=None):
        cliente_id = _id(cobro_cliente_ac.get_value())
        expediente_id = None if cobro_expediente_dd.value == "Sin expediente" else _id(cobro_expediente_dd.value)

        if not expediente_id:
            cobro_hoja_dd.options = [ft.dropdown.Option("Sin hoja")]
            cobro_hoja_dd.value = "Sin hoja"
            page.update()
            return

        hojas = economic_service.get_hojas_for_select(
            cliente_id=cliente_id,
            expediente_id=expediente_id,
        )

        if not hojas:
            hojas = economic_service.get_hojas_for_select(
                cliente_id=None,
                expediente_id=expediente_id,
            )

        cobro_hoja_dd.options = [ft.dropdown.Option("Sin hoja")] + [
            ft.dropdown.Option(h["display"]) for h in hojas
        ]
        cobro_hoja_dd.value = "Sin hoja"
        page.update()
"""

    pattern = r"    def refresh_cobro_hojas_for_expediente\(e=None\):.*?\n    def refresh_factura_dependencies"

    if re.search(pattern, text, flags=re.S):
        text = re.sub(
            pattern,
            new_refresh + "\n    def refresh_factura_dependencies",
            text,
            count=1,
            flags=re.S,
        )
    else:
        marker = "    def open_cobro_dialog(e=None):"
        if marker not in text:
            raise RuntimeError("No se pudo localizar open_cobro_dialog en economic_view.py")
        text = text.replace(marker, new_refresh + "\n" + marker, 1)

    if "cobro_expediente_dd.on_change = refresh_cobro_hojas_for_expediente" not in text:
        marker = "    cobro_fecha ="
        if marker in text:
            text = text.replace(
                marker,
                "    cobro_expediente_dd.on_change = refresh_cobro_hojas_for_expediente\n\n" + marker,
                1,
            )

    VIEW_PATH.write_text(text, encoding="utf-8")


def main():
    patch_service()
    patch_view()
    print("Corregido dropdown de hojas en Nuevo cobro.")


if __name__ == "__main__":
    main()
