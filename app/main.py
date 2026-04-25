from database.connection import initialize_database
from backend.services.client_service import create_client, get_all_clients


def main():
    initialize_database()

    # Crear cliente de prueba
    create_client({
        "nombre": "Juan",
        "primer_apellido": "Pérez",
        "telefono": "600000000",
        "email": "juan@test.com"
    })

    print("Cliente creado")

    # Listar clientes
    clientes = get_all_clients()

    print("\nLISTADO DE CLIENTES:\n")
    for c in clientes:
        print(c)


if __name__ == "__main__":
    main()