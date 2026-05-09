from pathlib import Path

PATH = Path("frontend/views/expedient_traceability_view.py")

def main():
    text = PATH.read_text(encoding="utf-8")

    start = text.find("    def economic_resume_expediente(expediente_id):")
    end = text.find("    def build_detail():", start)

    if start != -1 and end != -1:
        replacement = """    def economic_resume_expediente(expediente_id):
        return economic_service.get_resumen_economico_expediente(expediente_id)

"""
        text = text[:start] + replacement + text[end:]

    if '"Cobrado"' not in text:
        text = text.replace(
            '                _money(h.get("importe_neto")),\n                economic_badge(h.get("estado")),',
            '                _money(h.get("importe_neto")),\n                _money(h.get("cobrado")),\n                _money(h.get("pendiente")),\n                economic_badge(h.get("estado")),',
        )
        text = text.replace(
            '["Nº hoja", "Firma", "Procedimiento", "Bruto", "Dto. consultas", "Neto", "Estado"]',
            '["Nº hoja", "Firma", "Procedimiento", "Bruto", "Dto. consultas", "Neto", "Cobrado", "Pendiente", "Estado"]',
        )

    PATH.write_text(text, encoding="utf-8")
    print("expedient_traceability_view.py corregido.")

if __name__ == "__main__":
    main()
