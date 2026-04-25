from database.connection import initialize_database
from backend.services.client_csv_service import (
    preview_clients_from_csv,
    import_clients_from_csv,
)


def main():
    initialize_database()

    file_path = "hubspot-crm-exports-clientes-2026-04-25-2.csv"

    print("PREVISUALIZACION")
    preview = preview_clients_from_csv(file_path)

    print(f"Filas detectadas: {len(preview)}")

    for item in preview[:5]:
        print(item)

    print("\nIMPORTACION")
    result = import_clients_from_csv(file_path)

    print(result)


if __name__ == "__main__":
    main()