from pathlib import Path

VIEW_PATH = Path("frontend/views/economic_view.py")


def main():
    if not VIEW_PATH.exists():
        raise RuntimeError(f"No existe {VIEW_PATH}")

    text = VIEW_PATH.read_text(encoding="utf-8")

    old = '''            if cobro_hoja_dd.value == "Sin hoja" and cobro_tipo.value != "CONSULTA":
                raise ValueError("Selecciona una hoja de encargo para el cobro")
'''

    new = '''            # Las consultas previas pueden registrarse sin expediente y sin hoja.
            # Los pagos de expediente sí deben vincularse a una hoja de encargo.
            if cobro_tipo.value != "CONSULTA" and cobro_hoja_dd.value == "Sin hoja":
                raise ValueError("Selecciona una hoja de encargo para el cobro")
'''

    if old in text:
        text = text.replace(old, new, 1)
    else:
        old_alt = '''            if cobro_hoja_dd.value == "Sin hoja":
                raise ValueError("Selecciona una hoja de encargo para el cobro")
'''
        if old_alt in text:
            text = text.replace(old_alt, new, 1)
        else:
            raise RuntimeError(
                "No se encontró la validación de hoja en save_cobro. "
                "Busca manualmente 'Selecciona una hoja de encargo para el cobro'."
            )

    VIEW_PATH.write_text(text, encoding="utf-8")
    print("economic_view.py corregido: cobros tipo CONSULTA permitidos sin hoja.")


if __name__ == "__main__":
    main()
