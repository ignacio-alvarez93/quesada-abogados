from database.connection import initialize_database
from backend.services.client_service import (
    create_client,
    get_all_clients,
    update_client,
    search_clients,
    archive_client,
)


def main():
    initialize_database()

    create_client({
        "nombre": "Maria",
        "primer_apellido": "Lopez",
        "telefono": "611111111",
        "email": "maria@test.com",
        "estado_cliente": "Asesoramiento inicial"
    })

    print("Cliente creado")

    clientes = get_all_clients()
    print("\nCLIENTES ACTIVOS:")
    for c in clientes:
        print(c["id"], c["nombre"], c["primer_apellido"], c["telefono"])

    if clientes:
        client_id = clientes[0]["id"]

        update_client(client_id, {
            "nombre": "Maria",
            "primer_apellido": "Lopez",
            "segundo_apellido": "Garcia",
            "telefono": "622222222",
            "email": "maria.actualizada@test.com",
            "estado_cliente": "Pendiente de documentacion"
        })

        print("\nCliente actualizado")

        resultados = search_clients("Maria")
        print("\nBUSQUEDA:")
        for r in resultados:
            print(r["id"], r["nombre"], r["primer_apellido"], r["telefono"])

        archive_client(client_id)
        print("\nCliente archivado")


if __name__ == "__main__":
    main()