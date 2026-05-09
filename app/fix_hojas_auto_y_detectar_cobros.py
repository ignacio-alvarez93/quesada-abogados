from pathlib import Path
import re

SERVICE_PATH = Path("backend/services/economic_service.py")
VIEW_PATH = Path("frontend/views/economic_view.py")


def patch_service():
    text = SERVICE_PATH.read_text(encoding="utf-8")

    if "def next_numero_hoja(" not in text:
        marker = "def next_numero_cobro(fecha_cobro):"
        if marker not in text:
            raise RuntimeError("No se encontró def next_numero_cobro en economic_service.py")

        text = text.replace(
            marker,
            'def next_numero_hoja(fecha_firma):\n'
            '    return _next_number("eco_hojas_encargo", "numero_hoja", "HE", fecha_firma)\n\n\n'
            + marker,
            1,
        )

    if 'numero_hoja = _text(data.get("numero_hoja")) or next_numero_hoja' not in text:
        pattern = r"(def create_hoja_encargo\(data\):\n)"
        if not re.search(pattern, text):
            raise RuntimeError("No se encontró def create_hoja_encargo en economic_service.py")

        text = re.sub(
            pattern,
            r'\1'
            '    numero_hoja = _text(data.get("numero_hoja")) or next_numero_hoja(data.get("fecha_firma"))\n',
            text,
            count=1,
        )

    if '_text(data.get("numero_hoja")),' in text:
        text = text.replace(
            '_text(data.get("numero_hoja")),',
            'numero_hoja,',
            1,
        )

    SERVICE_PATH.write_text(text, encoding="utf-8")


def patch_view():
    text = VIEW_PATH.read_text(encoding="utf-8")

    if "def refresh_cobro_hojas_for_expediente" not in text:
        marker = "    def open_hoja_dialog(e=None):"
        if marker not in text:
            raise RuntimeError("No se encontró open_hoja_dialog para insertar helpers de refresco.")

        helper = """
    def _set_dropdown_options(dropdown, values, empty_label):
        dropdown.options = [ft.dropdown.Option(empty_label)] + [
            ft.dropdown.Option(value) for value in values
        ]
        dropdown.value = empty_label

    def refresh_cobro_hojas_for_expediente(e=None):
        cliente_id = _id(cobro_cliente_ac.get_value())
        expediente_id = None if cobro_expediente_dd.value == "Sin expediente" else _id(cobro_expediente_dd.value)

        if not cliente_id:
            _set_dropdown_options(cobro_hoja_dd, [], "Sin hoja")
            page.update()
            return

        hojas = economic_service.get_hojas_for_select(
            cliente_id=cliente_id,
            expediente_id=expediente_id,
        )
        _set_dropdown_options(cobro_hoja_dd, [h["display"] for h in hojas], "Sin hoja")
        page.update()

    def refresh_factura_hojas_for_expediente(e=None):
        cliente_id = _id(factura_cliente_ac.get_value())
        expediente_id = None if factura_expediente_dd.value == "Sin expediente" else _id(factura_expediente_dd.value)

        if not cliente_id:
            _set_dropdown_options(factura_hoja_dd, [], "Sin hoja")
            page.update()
            return

        hojas = economic_service.get_hojas_for_select(
            cliente_id=cliente_id,
            expediente_id=expediente_id,
        )
        _set_dropdown_options(factura_hoja_dd, [h["display"] for h in hojas], "Sin hoja")
        page.update()

"""
        text = text.replace(marker, helper + marker, 1)

    if "cobro_expediente_dd.on_change = refresh_cobro_hojas_for_expediente" not in text:
        marker = "    # Cobro dialog"
        if marker in text:
            text = text.replace(
                marker,
                "    cobro_expediente_dd.on_change = refresh_cobro_hojas_for_expediente\n\n" + marker,
                1,
            )
        else:
            marker = "    cobro_fecha ="
            text = text.replace(
                marker,
                "    cobro_expediente_dd.on_change = refresh_cobro_hojas_for_expediente\n\n" + marker,
                1,
            )

    if "factura_expediente_dd.on_change = refresh_factura_hojas_for_expediente" not in text:
        marker = "    # Factura dialog"
        if marker in text:
            text = text.replace(
                marker,
                "    factura_expediente_dd.on_change = refresh_factura_hojas_for_expediente\n\n" + marker,
                1,
            )
        else:
            marker = "    fra_fecha ="
            text = text.replace(
                marker,
                "    factura_expediente_dd.on_change = refresh_factura_hojas_for_expediente\n\n" + marker,
                1,
            )

    hoja_save_start = text.find("def save_hoja")
    cobro_open_start = text.find("def open_cobro_dialog")
    save_hoja_block = text[hoja_save_start:cobro_open_start] if hoja_save_start != -1 and cobro_open_start != -1 else ""

    if "refresh_runtime_options()" not in save_hoja_block:
        text = text.replace(
            '            hoja_dialog.open = False\n            show_message(success_alert("Hoja de encargo creada"))\n',
            '            hoja_dialog.open = False\n            refresh_runtime_options()\n            show_message(success_alert("Hoja de encargo creada"))\n',
            1,
        )

    text = text.replace('text_input("Nº hoja"', 'text_input("Nº hoja automático"')

    VIEW_PATH.write_text(text, encoding="utf-8")


def main():
    patch_service()
    patch_view()
    print("Parche aplicado correctamente.")
    print("- Hojas con numeración automática HE-AÑO0001")
    print("- Cobros recargan hojas por cliente/expediente")
    print("- Facturas recargan hojas por cliente/expediente")
    print("- Al guardar hoja se refrescan listas")


if __name__ == "__main__":
    main()
