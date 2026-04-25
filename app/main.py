from database.connection import initialize_database


def main():
    initialize_database()
    print("Base de datos creada correctamente")


if __name__ == "__main__":
    main()