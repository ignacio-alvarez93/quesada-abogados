"""
Prueba manual del motor documental.

Uso:
    python -m app.test_expedient_document_state 123

Si no pasas ID:
    python -m app.test_expedient_document_state
diagnostica los últimos expedientes activos con ruta Box.
"""

import sys
import json

from backend.services import expedient_document_state_service as doc_state


def compact(result):
    return {
        "expediente_id": result["expediente_id"],
        "numero_expediente": result["expediente"].get("numero_expediente"),
        "tipo": result["expediente"].get("tipo_expediente_nombre"),
        "subtipo": result["expediente"].get("subtipo_expediente_nombre") or result["expediente"].get("subtipo_expediente"),
        "estado_sugerido": result["estado_sugerido"],
        "confianza": result["confianza"],
        "resumen": result["resumen"],
        "faltantes": result["faltantes"],
        "senales": result["senales"],
    }


def main():
    if len(sys.argv) > 1:
        expediente_id = int(sys.argv[1])
        result = doc_state.diagnose_expediente_document_state(expediente_id)
        print(json.dumps(compact(result), ensure_ascii=False, indent=2))
        return

    results = doc_state.diagnose_all_active_expedientes(limit=20)
    print(json.dumps([compact(r) for r in results], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
