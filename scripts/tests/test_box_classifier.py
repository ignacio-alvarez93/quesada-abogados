from backend.services.box_classifier import classify_folder, classify_file, detect_expedient_state


def main():
    folders = [
        "PARA PRESENTAR",
        "PATA PRESENTAR",
        "APORTAR",
        "REQ DOC",
        "RES CONCESION",
        "RES DENEGACION",
        "POLICIALES",
        "Nueva carpeta",
    ]

    files = [
        "PASAPORTE.pdf",
        "NIE.pdf",
        "HOJA DE ENCARGO.pdf",
        "Justificante_Anexo - 2024-04-11.pdf",
        "RES CONCESION.pdf",
        "REQ_DOC.pdf",
        "TASA_PAGADA.pdf",
        "NOTAS CARPETA.pdf",
    ]

    print("CARPETAS")
    for f in folders:
        print(f, "=>", classify_folder(f))

    print("\nARCHIVOS")
    for f in files:
        print(f, "=>", classify_file(f))

    print("\nESTADO")
    print(detect_expedient_state(["PRESENTACION", "REQUERIMIENTO"], ["PASAPORTE", "NIE"]))


if __name__ == "__main__":
    main()
