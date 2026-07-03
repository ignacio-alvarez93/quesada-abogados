import argparse
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.services import box_watch_job_service, box_watch_service  # noqa: E402


def _progress_adapter(job_id, totals):
    def on_progress(payload):
        payload = payload or {}

        route_index = int(payload.get("route_index") or 0)
        total_routes = int(payload.get("total_routes") or totals.get("total_routes") or 0)
        processed = int(payload.get("processed") or 0)
        processed_folders = int(payload.get("processed_folders") or 0)
        label = payload.get("current_file") or payload.get("route_label") or "Escaneando Box"

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

    return on_progress


def run_job(job_id):
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
        results = box_watch_service.scan_configured_routes(
            route_ids=route_ids,
            progress_callback=_progress_adapter(job_id, totals),
            calculate_hash=False,
        )

        total_errores = sum(
            1 for r in results
            if str(r.get("estado") or "").upper() == "ERROR"
            or str(r.get("scan_mode") or "").upper() == "ERROR"
        )
        totals["total_errores"] = total_errores

        box_watch_job_service.finish_job(job_id, results)
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
    parser = argparse.ArgumentParser(description="Runner externo de escaneo Box Watch")
    parser.add_argument("--job-id", type=int, required=True)
    args = parser.parse_args()

    return run_job(args.job_id)


if __name__ == "__main__":
    raise SystemExit(main())
