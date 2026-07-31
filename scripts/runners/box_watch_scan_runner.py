import argparse
import sys
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.services.sqlite_runtime_service import configure_sqlite_runtime  # noqa: E402
from backend.services import box_watch_job_service, box_watch_service  # noqa: E402
from backend.services import document_semantic_scan_service  # noqa: E402


def _progress_adapter(job_id, totals):
    """
    Adaptador de progreso del runner externo.

    Importante:
    No debe escribir en SQLite en cada archivo/carpeta porque ralentiza mucho
    el escaneo y puede provocar database is locked si la UI lee a la vez.

    Regla:
    - actualizar como máximo cada 3 segundos;
    - actualizar siempre al cambiar de ruta;
    - el resumen final se guarda completo en finish_job().
    """
    throttle_seconds = 3.0
    state = {
        "last_update_at": 0.0,
        "last_route_index": None,
    }

    def on_progress(payload):
        payload = payload or {}

        route_index = int(payload.get("route_index") or 0)
        total_routes = int(payload.get("total_routes") or totals.get("total_routes") or 0)
        processed = int(payload.get("processed") or 0)
        processed_folders = int(payload.get("processed_folders") or 0)
        label = payload.get("current_file") or payload.get("route_label") or "Escaneando Box"

        now = time.monotonic()
        route_changed = route_index != state.get("last_route_index")
        enough_time = (now - float(state.get("last_update_at") or 0)) >= throttle_seconds

        if not route_changed and not enough_time:
            return

        if total_routes > 0 and route_index > 0:
            percent = min(99.0, max(0.0, ((route_index - 1) / total_routes) * 100))
        else:
            percent = float(payload.get("percent") or 0)

        totals["total_routes"] = max(totals.get("total_routes") or 0, total_routes)
        totals["completed_routes"] = max(0, route_index - 1)
        totals["total_archivos"] = max(totals.get("total_archivos") or 0, processed)
        totals["total_carpetas"] = max(totals.get("total_carpetas") or 0, processed_folders)

        box_watch_job_service.update_job_progress(
            job_id,
            label=label,
            percent=percent,
            completed_routes=totals["completed_routes"],
            total_routes=totals["total_routes"],
            total_archivos=totals["total_archivos"],
            total_carpetas=totals["total_carpetas"],
            total_errores=totals.get("total_errores") or 0,
        )

        state["last_update_at"] = now
        state["last_route_index"] = route_index

    return on_progress


def run_job(job_id):
    configure_sqlite_runtime()

    job = box_watch_job_service.get_job(job_id)
    if not job:
        raise SystemExit(f"No existe job Box Watch #{job_id}")

    route_ids = job.get("route_ids") or None

    routes = box_watch_service.get_configured_box_routes(active_only=True)
    if route_ids:
        wanted = {int(x) for x in route_ids}
        routes = [r for r in routes if int(r.get("id")) in wanted]

    totals = {
        "total_routes": len(routes),
        "completed_routes": 0,
        "total_archivos": 0,
        "total_carpetas": 0,
        "total_errores": 0,
    }

    box_watch_job_service.mark_job_running(
        job_id,
        total_routes=len(routes),
        label="Escaneo Box Watch iniciado desde runner externo",
    )

    try:
        # IMPORTANTE:
        # No pasamos progress_callback granular.
        # En rutas grandes, el callback por archivo/carpeta ralentiza mucho el escaneo
        # aunque se limite la escritura a SQLite. El resumen final se registra en finish_job().
        results = box_watch_service.scan_configured_routes(
            route_ids=route_ids,
            progress_callback=None,
            calculate_hash=False,
        )

        total_errores = sum(
            1 for r in results
            if str(r.get("estado") or "").upper() == "ERROR"
            or str(r.get("scan_mode") or "").upper() == "ERROR"
        )
        totals["total_errores"] = total_errores

        try:
            semantic_summary = (
                document_semantic_scan_service
                .process_box_scan_results(
                    results,
                    source_scan_job_id=job_id,
                )
            )
        except Exception as semantic_exc:
            semantic_summary = {
                "enabled": True,
                "source_scan_job_id": job_id,
                "scan_runs_detected": 0,
                "scan_runs_processed": 0,
                "affected_expedients": 0,
                "processed": 0,
                "changed": 0,
                "unchanged": 0,
                "events_created": 0,
                "events_skipped": 0,
                "errors": 1,
                "runner_error": str(
                    semantic_exc
                ),
                "run_results": [],
            }

        if results:
            results[0][
                "semantic_processing"
            ] = semantic_summary

        box_watch_job_service.finish_job(
            job_id,
            results,
        )
        print(f"OK job #{job_id}: {len(results)} ruta(s), errores={total_errores}")
        return 0

    except Exception as exc:
        box_watch_job_service.fail_job(
            job_id,
            "".join(traceback.format_exception_only(type(exc), exc)).strip(),
        )
        traceback.print_exc()
        return 1


def main():
    configure_sqlite_runtime()

    parser = argparse.ArgumentParser(description="Runner externo de escaneo Box Watch")
    parser.add_argument("--job-id", type=int, required=True)
    args = parser.parse_args()

    return run_job(args.job_id)


if __name__ == "__main__":
    raise SystemExit(main())
