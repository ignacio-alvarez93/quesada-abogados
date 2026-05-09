from backend.services.box_watch_service import initialize_box_watch_schema, sync_rules_from_config

if __name__ == "__main__":
    initialize_box_watch_schema()
    inserted = sync_rules_from_config()
    print(f"Vigilancia Box inicializada correctamente. Reglas sincronizadas: {inserted}.")
