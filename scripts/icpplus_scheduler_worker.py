"""
Worker autónomo de vigilancia ICP Plus.

Puede permanecer activo aunque el CRM Flet esté cerrado.

Características:
- un único carril de ejecución;
- utiliza el bot one-shot productivo;
- respeta FIFO;
- respeta cooldown global de 15 minutos;
- aviso persistente T-60;
- no recupera en ráfaga intentos perdidos;
- no reserva citas;
- no interactúa con CAPTCHA;
- no conoce clientes ni expedientes.

Requiere sesión de Windows iniciada porque el runner productivo
utiliza Chrome normal + interacción física de teclado/ratón.
"""

from __future__ import annotations

from datetime import (
    datetime,
    timedelta,
)
import argparse
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import time


PROJECT_ROOT = Path(
    __file__
).resolve().parents[1]

if str(
    PROJECT_ROOT
) not in sys.path:
    sys.path.insert(
        0,
        str(
            PROJECT_ROOT
        ),
    )


from backend.services.sqlite_runtime_service import (
    configure_sqlite_runtime,
)

from database.connection import (
    initialize_database,
)

from backend.services.icpplus_availability_service import (
    IcpPlusAvailabilityService,
)

from backend.services import (
    icpplus_profile_service,
    icpplus_scheduler_service,
    icpplus_state_service,
    icpplus_ui_presence_service,
)


POLL_SECONDS = 1.0

SINGLE_INSTANCE_MUTEX_NAME = (
    r"Local\QuesadaAbogadosICPPlusSchedulerWorkerV1"
)

ERROR_ALREADY_EXISTS = 183


def now_local():
    return (
        datetime.now()
        .astimezone()
    )


def print_marker(
    *parts,
):
    print(
        "[ICPPLUS-SCHEDULER]",
        *parts,
        flush=True,
    )


def initialize_runtime():
    configure_sqlite_runtime()
    initialize_database()
    configure_sqlite_runtime()


def persist_result(
    schedule,
    result,
):
    result = dict(
        result
        or {}
    )

    flow_key = str(
        result.get(
            "flow_key"
        )
        or (
            str(
                schedule.get(
                    "province_key"
                )
                or ""
            )
            + ":"
            + str(
                schedule.get(
                    "procedure_key"
                )
                or ""
            )
        )
    )

    return (
        icpplus_state_service
        .record_result(
            provider="ICP_PLUS",
            flow_key=flow_key,
            province_key=(
                schedule.get(
                    "province_key"
                )
            ),
            procedure_key=(
                schedule.get(
                    "procedure_key"
                )
            ),
            office_key=(
                schedule.get(
                    "office_key"
                )
            ),
            office_text=(
                schedule.get(
                    "office_text"
                )
            ),
            result=result,
        )
    )


def execute_schedule(
    service,
    schedule,
):
    scheduler_id = str(
        schedule[
            "scheduler_id"
        ]
    )

    print_marker(
        "RUN_START",
        scheduler_id,
        schedule.get(
            "province_key"
        ),
        "|",
        schedule.get(
            "procedure_key"
        ),
        "|",
        schedule.get(
            "office_key"
        ),
    )

    result = None

    try:
        profile = (
            icpplus_profile_service
            .get_profile()
        )

        result = (
            service.check_availability(
                province_key=(
                    schedule[
                        "province_key"
                    ]
                ),
                procedure_key=(
                    schedule[
                        "procedure_key"
                    ]
                ),
                office_scope="SINGLE",
                office_key=(
                    schedule[
                        "office_key"
                    ]
                ),
                profile=profile,
            )
        )

        persist_result(
            schedule,
            result,
        )

        portal_status = str(
            result.get(
                "portal_status"
            )
            or "UNKNOWN"
        ).upper()

        availability_status = str(
            result.get(
                "availability_status"
            )
            or "UNKNOWN"
        ).upper()

        print_marker(
            "RUN_RESULT",
            scheduler_id,
            "PORTAL=",
            portal_status,
            "AVAILABILITY=",
            availability_status,
            "APPOINTMENTS=",
            len(
                result.get(
                    "appointments"
                )
                or []
            ),
        )

        return result

    except Exception as exc:
        result = {
            "portal_status":
                "UNKNOWN",

            "availability_status":
                "UNKNOWN",

            "result_class":
                "SCHEDULER_EXECUTION_ERROR",

            "navigation_error":
                (
                    type(exc).__name__
                    + ":"
                    + str(exc)
                ),

            "appointments":
                [],
        }

        try:
            persist_result(
                schedule,
                result,
            )
        except Exception as persist_exc:
            print_marker(
                "RESULT_PERSIST_ERROR",
                repr(
                    persist_exc
                ),
            )

        print_marker(
            "RUN_ERROR",
            scheduler_id,
            repr(
                exc
            ),
        )

        return result

    finally:
        finished_at = (
            now_local()
        )

        try:
            updated = (
                icpplus_scheduler_service
                .mark_run_finished(
                    scheduler_id,
                    result=result,
                    finished_at=(
                        finished_at
                    ),
                )
            )

            print_marker(
                "RUN_FINISHED",
                scheduler_id,
                "NEXT=",
                updated.get(
                    "next_run_at"
                ),
                "STATUS=",
                updated.get(
                    "status"
                ),
            )

        except Exception as exc:
            print_marker(
                "MARK_FINISHED_ERROR",
                scheduler_id,
                repr(
                    exc
                ),
            )


def acquire_single_instance():
    # El worker productivo actual es Windows.
    # Un Named Mutex evita dos gobernadores simultáneos.

    if os.name != "nt":
        return object()

    kernel32 = ctypes.WinDLL(
        "kernel32",
        use_last_error=True,
    )

    kernel32.CreateMutexW.restype = (
        ctypes.c_void_p
    )

    ctypes.set_last_error(
        0
    )

    handle = kernel32.CreateMutexW(
        None,
        False,
        SINGLE_INSTANCE_MUTEX_NAME,
    )

    if not handle:
        raise OSError(
            ctypes.get_last_error(),
            "CreateMutexW failed",
        )

    error = ctypes.get_last_error()

    if error == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(
            handle
        )

        return None

    return (
        kernel32,
        handle,
    )


def release_single_instance(
    guard,
):
    if not guard:
        return

    if os.name != "nt":
        return

    kernel32, handle = guard

    try:
        kernel32.CloseHandle(
            handle
        )
    except Exception:
        pass


def _windows_notification_text(
    event,
):
    event = dict(
        event
        or {}
    )

    province = str(
        event.get(
            "province_key"
        )
        or "ICP Plus"
    ).replace(
        "_",
        " ",
    ).title()

    procedure = str(
        event.get(
            "procedure_text"
        )
        or event.get(
            "procedure_key"
        )
        or "Trámite ICP Plus"
    )

    office = str(
        event.get(
            "office_text"
        )
        or event.get(
            "office_key"
        )
        or "Oficina ICP Plus"
    )

    run_time = ""

    effective_raw = event.get(
        "effective_run_at"
    )

    if effective_raw:
        try:
            run_time = (
                datetime.fromisoformat(
                    str(
                        effective_raw
                    )
                )
                .astimezone()
                .strftime(
                    "%H:%M"
                )
            )
        except Exception:
            run_time = ""

    title = (
        "ICP Plus · próxima comprobación"
    )

    body_lines = [
        province,
        procedure,
        office,
    ]

    if run_time:
        body_lines.append(
            f"Inicio previsto: {run_time}"
        )

    body = "\n".join(
        body_lines
    )

    return (
        title[:63],
        body[:240],
    )


def show_windows_notification(
    event,
):
    # Notificación best-effort.
    # No usa Flet, BBDD ni Chrome.

    if os.name != "nt":
        print_marker(
            "WINDOWS_NOTIFICATION_SKIPPED",
            "NON_WINDOWS",
        )

        return False

    title, body = (
        _windows_notification_text(
            event
        )
    )

    powershell_script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "Add-Type -AssemblyName System.Drawing;"
        "$n=New-Object System.Windows.Forms.NotifyIcon;"
        "$n.Icon=[System.Drawing.SystemIcons]::Information;"
        "$n.BalloonTipIcon="
        "[System.Windows.Forms.ToolTipIcon]::Info;"
        "$n.BalloonTipTitle="
        "$env:QUESADA_ICPPLUS_NOTIFY_TITLE;"
        "$n.BalloonTipText="
        "$env:QUESADA_ICPPLUS_NOTIFY_BODY;"
        "$n.Visible=$true;"
        "$n.ShowBalloonTip(10000);"
        "Start-Sleep -Seconds 6;"
        "$n.Dispose();"
    )

    environment = os.environ.copy()

    environment[
        "QUESADA_ICPPLUS_NOTIFY_TITLE"
    ] = title

    environment[
        "QUESADA_ICPPLUS_NOTIFY_BODY"
    ] = body

    creationflags = getattr(
        subprocess,
        "CREATE_NO_WINDOW",
        0,
    )

    try:
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                powershell_script,
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )

        print_marker(
            "WINDOWS_NOTIFICATION",
            "SENT",
            event.get(
                "scheduler_id"
            ),
        )

        return True

    except Exception as exc:
        print_marker(
            "WINDOWS_NOTIFICATION_ERROR",
            repr(
                exc
            ),
        )

        return False


def worker_loop(
    *,
    poll_seconds=POLL_SECONDS,
):
    initialize_runtime()

    service = (
        IcpPlusAvailabilityService()
    )

    print_marker(
        "STARTED",
        "PID=",
        os.getpid(),
    )

    print_marker(
        "MIN_INTERVAL=",
        icpplus_scheduler_service
        .MIN_INTERVAL_MINUTES,
        "GLOBAL_COOLDOWN=",
        icpplus_scheduler_service
        .GLOBAL_COOLDOWN_MINUTES,
        "WARNING_SECONDS=",
        icpplus_scheduler_service
        .WARNING_SECONDS,
    )

    try:
        # Al arrancar no ejecutamos automáticamente algo
        # que venció mientras el proceso/PC estaba apagado.
        reconciled = (
            icpplus_scheduler_service
            .reconcile_overdue(
                now=now_local()
            )
        )

        if reconciled:
            print_marker(
                "RECONCILED",
                len(
                    reconciled
                ),
                "SCHEDULE(S)",
            )

        while True:
            now = (
                now_local()
            )

            candidate = (
                icpplus_scheduler_service
                .next_candidate(
                    now=now
                )
            )

            # Si no existe candidato reclamable puede haber
            # quedado un turno vencido fuera de la tolerancia
            # técnica. Lo reconciliamos, nunca lo recuperamos.
            if not candidate:
                reconciled = (
                    icpplus_scheduler_service
                    .reconcile_overdue(
                        now=now
                    )
                )

                if reconciled:
                    print_marker(
                        "RECONCILED_STALE",
                        len(
                            reconciled
                        ),
                        "SCHEDULE(S)",
                    )

                    candidate = (
                        icpplus_scheduler_service
                        .next_candidate(
                            now=now
                        )
                    )

            if candidate:
                effective_run_at = (
                    datetime.fromisoformat(
                        candidate[
                            "effective_run_at"
                        ]
                    )
                )

                warning_at = (
                    datetime.fromisoformat(
                        candidate[
                            "warning_at"
                        ]
                    )
                )

                if (
                    warning_at
                    <= now
                    < effective_run_at
                ):
                    event = (
                        icpplus_scheduler_service
                        .record_warning(
                            candidate[
                                "scheduler_id"
                            ],
                            effective_run_at=(
                                effective_run_at
                            ),
                            warned_at=now,
                        )
                    )

                    if event.get(
                        "_created"
                    ):
                        print_marker(
                            "WARNING",
                            event.get(
                                "scheduler_id"
                            ),
                            "RUN_AT=",
                            event.get(
                                "effective_run_at"
                            ),
                        )

                        if (
                            icpplus_ui_presence_service
                            .is_alive(
                                max_age_seconds=5
                            )
                        ):
                            print_marker(
                                "WINDOWS_NOTIFICATION_SKIPPED",
                                "ERP_UI_ALIVE",
                            )

                        else:
                            show_windows_notification(
                                event
                            )

                if now >= effective_run_at:
                    claimed = (
                        icpplus_scheduler_service
                        .claim_next_due(
                            now=now
                        )
                    )

                    if claimed:
                        execute_schedule(
                            service,
                            claimed,
                        )

            time.sleep(
                float(
                    poll_seconds
                )
            )

    except KeyboardInterrupt:
        print_marker(
            "STOP_REQUESTED"
        )

    finally:
        try:
            service.close()
        except Exception as exc:
            print_marker(
                "SERVICE_CLOSE_ERROR",
                repr(
                    exc
                ),
            )

        print_marker(
            "STOPPED"
        )


def dry_run_demo():
    """
    Simulación autónoma del ciclo del scheduler.

    IMPORTANTE:
    - no inicializa SQLite;
    - no lee config_service;
    - no modifica schedulers persistidos;
    - no crea IcpPlusAvailabilityService;
    - no abre Chrome;
    - no ejecuta el runner productivo.

    La línea temporal se comprime para poder validar
    rápidamente warning -> claim -> run -> cooldown.
    """

    print_marker(
        "DRY_RUN",
        "SAFE_SIMULATION=YES",
    )

    print_marker(
        "DRY_RUN",
        "DATABASE=DISABLED",
        "CHROME=DISABLED",
        "REAL_BOT=DISABLED",
    )

    simulated_now = (
        datetime.now()
        .astimezone()
    )

    schedule = {
        "scheduler_id":
            "ICPPLUS-DRYRUN-001",

        "province_key":
            "ASTURIAS",

        "procedure_key":
            "POLICIA_TOMA_HUELLAS_TIE",

        "procedure_text":
            "Policía · Toma de huellas TIE",

        "office_key":
            "CNP_OVIEDO",

        "office_text":
            "CNP Oviedo",

        "interval_minutes":
            15,

        "status":
            "ACTIVE",
    }

    # En producción sería T-60 segundos.
    # En esta simulación comprimimos la espera.
    effective_run_at = (
        simulated_now
        + timedelta(
            seconds=4
        )
    )

    warning_at = (
        simulated_now
        + timedelta(
            seconds=1
        )
    )

    print_marker(
        "DRY_SCHEDULER_DETECTED",
        schedule[
            "scheduler_id"
        ],
        "|",
        schedule[
            "province_key"
        ],
        "|",
        schedule[
            "procedure_text"
        ],
        "|",
        schedule[
            "office_text"
        ],
    )

    print_marker(
        "DRY_EFFECTIVE_RUN_AT",
        effective_run_at.isoformat(
            timespec="seconds"
        ),
    )

    warning_emitted = False
    claimed = False

    while True:
        now = (
            datetime.now()
            .astimezone()
        )

        if (
            not warning_emitted
            and now >= warning_at
        ):
            warning_emitted = True

            print_marker(
                "DRY_WARNING",
                schedule[
                    "scheduler_id"
                ],
                "PRODUCTION_OFFSET=T-60",
            )

        if (
            not claimed
            and now >= effective_run_at
        ):
            claimed = True

            schedule[
                "status"
            ] = "RUNNING"

            print_marker(
                "DRY_CLAIMED",
                schedule[
                    "scheduler_id"
                ],
            )

            print_marker(
                "DRY_RUN_START",
                "REAL_BOT=NO",
            )

            fake_result = {
                "portal_status":
                    "ONLINE",

                "availability_status":
                    "UNAVAILABLE",

                "result_class":
                    "UNAVAILABLE",

                "appointments":
                    [],
            }

            time.sleep(
                0.5
            )

            schedule[
                "status"
            ] = "ACTIVE"

            print_marker(
                "DRY_RUN_RESULT",
                "PORTAL=",
                fake_result[
                    "portal_status"
                ],
                "AVAILABILITY=",
                fake_result[
                    "availability_status"
                ],
            )

            print_marker(
                "DRY_RUN_FINISHED",
                schedule[
                    "scheduler_id"
                ],
            )

            print_marker(
                "DRY_GLOBAL_COOLDOWN",
                "15_MINUTES",
            )

            print_marker(
                "DRY_NEXT_BOT_NOT_BEFORE",
                (
                    datetime.now()
                    .astimezone()
                    + timedelta(
                        minutes=15
                    )
                ).isoformat(
                    timespec="seconds"
                ),
            )

            break

        time.sleep(
            0.1
        )

    print_marker(
        "DRY_RUN_COMPLETE",
        "OK",
    )

    return True


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Worker autónomo ICP Plus"
        )
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Ejecuta una simulación aislada "
            "sin BBDD, Chrome ni bot real."
        ),
    )

    parser.add_argument(
        "--notification-smoke",
        action="store_true",
        help=(
            "Muestra una notificación Windows "
            "sintética sin BBDD ni bot real."
        ),
    )

    args = parser.parse_args()

    if args.dry_run:
        dry_run_demo()
        return

    if args.notification_smoke:
        effective = (
            datetime.now()
            .astimezone()
            + timedelta(
                seconds=60
            )
        )

        show_windows_notification(
            {
                "scheduler_id":
                    "ICPPLUS-NOTIFICATION-SMOKE",

                "province_key":
                    "ASTURIAS",

                "procedure_text":
                    (
                        "Policía · "
                        "Toma de huellas TIE"
                    ),

                "office_text":
                    "CNP Oviedo",

                "effective_run_at":
                    effective.isoformat(),
            }
        )

        print_marker(
            "NOTIFICATION_SMOKE_COMPLETE"
        )

        return

    guard = acquire_single_instance()

    if guard is None:
        print_marker(
            "ALREADY_RUNNING",
            "SECOND_INSTANCE_BLOCKED",
        )

        return

    print_marker(
        "SINGLE_INSTANCE",
        "ACQUIRED",
    )

    try:
        worker_loop()

    finally:
        release_single_instance(
            guard
        )

        print_marker(
            "SINGLE_INSTANCE",
            "RELEASED",
        )


if __name__ == "__main__":
    main()
