"""
Connector productivo Desktop para ICP Plus.

Contrato externo:
    check_availability(request) -> dict
    close() -> bool

Motor actual:
- Chrome normal;
- Observer ICP Plus;
- input físico;
- source binding;
- geometría DOM viva;
- sin SeleniumBase;
- sin reserva;
- sin CAPTCHA;
- parada en acOfertarCita.

En esta fase el connector encapsula el runner Desktop validado.
Esto permite integrar inmediatamente el motor en el CRM
manteniendo estable el contrato backend.

No conoce:
- Flet;
- SQLite;
- clientes;
- expedientes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
import subprocess
import sys


SUPPORTED_FLOW = (
    "ASTURIAS:"
    "POLICIA_TOMA_HUELLAS_TIE"
)

SUPPORTED_OFFICE_SCOPE = "SINGLE"


@dataclass(frozen=True)
class IcpPlusProcessResult:
    returncode: int
    stdout: str
    stderr: str


class IcpPlusDesktopConnector:
    def __init__(
        self,
        *,
        runner_path=None,
        process_runner=None,
        timeout=240,
    ):
        self.project_root = (
            Path(__file__)
            .resolve()
            .parents[3]
        )

        self.runner_path = Path(
            runner_path
            or (
                self.project_root
                / "scripts"
                / "icpplus_desktop_runner.py"
            )
        )

        self.process_runner = (
            process_runner
            or subprocess.run
        )

        if not callable(
            self.process_runner
        ):
            raise TypeError(
                "process_runner debe ser callable"
            )

        self.timeout = max(
            30,
            int(timeout),
        )

        self._active = False


    @property
    def running(self):
        return bool(
            self._active
        )


    @staticmethod
    def _text(value):
        return str(
            value
            or ""
        ).strip()


    def _validate_request(
        self,
        request,
    ):
        request = dict(
            request
            or {}
        )

        flow_key = (
            self._text(
                request.get(
                    "flow_key"
                )
            )
            .upper()
        )

        if flow_key != SUPPORTED_FLOW:
            raise ValueError(
                "ICPPLUS_DESKTOP_FLOW_NOT_SUPPORTED:"
                f"{flow_key}"
            )

        office_scope = (
            self._text(
                request.get(
                    "office_scope"
                )
            )
            .upper()
        )

        if (
            office_scope
            != SUPPORTED_OFFICE_SCOPE
        ):
            raise ValueError(
                "ICPPLUS_DESKTOP_OFFICE_SCOPE_"
                "NOT_SUPPORTED:"
                f"{office_scope}"
            )

        identity = dict(
            request.get(
                "identity"
            )
            or {}
        )

        contact = dict(
            request.get(
                "contact"
            )
            or {}
        )

        office = dict(
            request.get(
                "office"
            )
            or {}
        )

        required = {
            "nombre":
                identity.get("nombre"),
            "nacionalidad":
                identity.get("nacionalidad"),
            "nie":
                identity.get("nie"),
            "telefono":
                contact.get("telefono"),
            "email":
                contact.get("email"),
            "office_key":
                office.get("key"),
        }

        missing = [
            key
            for key, value
            in required.items()
            if not self._text(value)
        ]

        if missing:
            raise ValueError(
                "ICPPLUS_DESKTOP_REQUEST_MISSING:"
                + ",".join(missing)
            )

        return {
            "flow_key":
                flow_key,

            "office_scope":
                office_scope,

            "office_key":
                self._text(
                    office.get("key")
                ).upper(),

            "nombre":
                self._text(
                    identity.get("nombre")
                ),

            "nacionalidad":
                self._text(
                    identity.get(
                        "nacionalidad"
                    )
                ),

            "nie":
                self._text(
                    identity.get("nie")
                ),

            "telefono":
                self._text(
                    contact.get(
                        "telefono"
                    )
                ),

            "email":
                self._text(
                    contact.get("email")
                ),
        }


    def _build_environment(
        self,
        normalized,
    ):
        env = os.environ.copy()

        env.update({
            "PYTHONPATH":
                str(
                    self.project_root
                ),

            "PYTHONIOENCODING":
                "utf-8",

            "PYTHONUTF8":
                "1",

            "ICPPLUS_TEST_NAME":
                normalized["nombre"],

            "ICPPLUS_TEST_NATIONALITY":
                normalized[
                    "nacionalidad"
                ],

            "ICPPLUS_TEST_NIE":
                normalized["nie"],

            "ICPPLUS_TEST_PHONE":
                normalized["telefono"],

            "ICPPLUS_TEST_EMAIL":
                normalized["email"],
        })

        return env


    def _execute(
        self,
        normalized,
    ):
        if not self.runner_path.exists():
            raise RuntimeError(
                "ICPPLUS_DESKTOP_RUNNER_NOT_FOUND:"
                f"{self.runner_path}"
            )

        command = [
            sys.executable,
            str(
                self.runner_path
            ),
        ]

        # El runner actual pregunta por office_key.
        # Lo alimentamos por stdin, sin exponerlo como argumento.
        stdin_text = (
            normalized[
                "office_key"
            ]
            + "\n"
        )

        self._active = True

        try:
            completed = (
                self.process_runner(
                    command,
                    cwd=str(
                        self.project_root
                    ),
                    env=(
                        self._build_environment(
                            normalized
                        )
                    ),
                    input=stdin_text,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    timeout=self.timeout,
                    check=False,
                )
            )

        except subprocess.TimeoutExpired:
            return IcpPlusProcessResult(
                returncode=-1,
                stdout="",
                stderr=(
                    "ICPPLUS_DESKTOP_TIMEOUT"
                ),
            )

        finally:
            self._active = False

        return IcpPlusProcessResult(
            returncode=int(
                completed.returncode
            ),
            stdout=str(
                completed.stdout
                or ""
            ),
            stderr=str(
                completed.stderr
                or ""
            ),
        )


    @staticmethod
    def _marker(
        output,
        name,
    ):
        pattern = (
            r"(?m)^"
            + re.escape(name)
            + r"\s*=\s*(.*?)\s*$"
        )

        match = re.search(
            pattern,
            output,
        )

        if not match:
            return None

        return (
            match.group(1)
            .strip()
        )


    @staticmethod
    def _appointments(
        output,
    ):
        result = []

        pattern = re.compile(
            r"(?m)^\s*-\s+"
            r"(\d{1,2}/\d{1,2}/\d{4})"
            r"\s+"
            r"(\d{1,2}:\d{2})"
            r"\s*$"
        )

        for match in pattern.finditer(
            output
        ):
            item = {
                "date":
                    match.group(1),
                "time":
                    match.group(2),
            }

            if item not in result:
                result.append(
                    item
                )

        return result


    def _parse_result(
        self,
        process_result,
        normalized,
    ):
        output = (
            process_result.stdout
            or ""
        )

        page = (
            self._marker(
                output,
                "PAGE",
            )
            or "UNKNOWN"
        ).upper()

        portal_status = (
            self._marker(
                output,
                "PORTAL_STATUS",
            )
            or "UNKNOWN"
        ).upper()

        availability_status = (
            self._marker(
                output,
                "AVAILABILITY_STATUS",
            )
            or "UNKNOWN"
        ).upper()

        result_class = (
            self._marker(
                output,
                "RESULT_CLASS",
            )
            or "UNKNOWN"
        ).upper()

        support_id = (
            self._marker(
                output,
                "SUPPORT_ID",
            )
        )

        navigation_error = (
            self._marker(
                output,
                "NAVIGATION_ERROR",
            )
        )

        appointments = (
            self._appointments(
                output
            )
        )

        if support_id in {
            "",
            "None",
            "null",
            "NULL",
        }:
            support_id = None

        if navigation_error in {
            "",
            "None",
            "null",
            "NULL",
        }:
            navigation_error = None


        # Fallo técnico del proceso:
        # jamás convertirlo falsamente en UNAVAILABLE.
        if (
            process_result.returncode
            != 0
        ):
            portal_status = "UNKNOWN"
            availability_status = (
                "UNKNOWN"
            )

            if result_class == "UNKNOWN":
                result_class = (
                    "EXECUTION_ERROR"
                )

            if not navigation_error:
                navigation_error = (
                    "ICPPLUS_DESKTOP_PROCESS_FAILED:"
                    f"{process_result.returncode}"
                )


        # No inferimos AVAILABLE únicamente porque existan
        # líneas parseables. El Observer es la autoridad.
        if portal_status != "ONLINE":
            availability_status = (
                "UNKNOWN"
            )

        return {
            "provider":
                "ICP_PLUS",

            "flow_key":
                normalized[
                    "flow_key"
                ],

            "office_scope":
                normalized[
                    "office_scope"
                ],

            "office_key":
                normalized[
                    "office_key"
                ],

            "page":
                page,

            "portal_status":
                portal_status,

            "availability_status":
                availability_status,

            "appointments":
                appointments,

            "appointment_count":
                len(
                    appointments
                ),

            "support_id":
                support_id,

            "navigation_error":
                navigation_error,

            "result_class":
                result_class,

            "process_returncode":
                process_result.returncode,
        }


    def check_availability(
        self,
        request,
    ):
        normalized = (
            self._validate_request(
                request
            )
        )

        process_result = (
            self._execute(
                normalized
            )
        )

        return self._parse_result(
            process_result,
            normalized,
        )


    def close(self):
        # El runner posee y cierra exclusivamente su propia
        # ventana Chrome en finally.
        #
        # El connector no usa taskkill ni toca Chromes ajenos.
        self._active = False
        return True
