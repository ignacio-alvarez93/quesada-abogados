from database.connection import initialize_database
from backend.services.auth_service import create_user, user_exists


def main():
    initialize_database()

    username = "admin"
    password = "1234"

    if user_exists(username):
        print("El usuario admin ya existe")
        return

    if create_user(username, password):
        print("Usuario admin creado correctamente")
    else:
        print("No se pudo crear el usuario admin")


if __name__ == "__main__":
    main()