from backend.services.expedient_traceability_service import initialize_traceability_schema

if __name__ == "__main__":
    initialize_traceability_schema()
    print("Trazabilidad de expedientes inicializada correctamente.")
