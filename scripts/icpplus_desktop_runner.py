from __future__ import annotations

from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)
from pathlib import Path
from threading import (
    Condition,
    Thread,
)
import ctypes


# ============================================================
# WINDOWS DPI AWARENESS
# ============================================================
#
# Debe configurarse antes de trabajar con HWND, GetClientRect,
# ClientToScreen o coordenadas físicas.
#
# PER_MONITOR_AWARE_V2 evita la virtualización de coordenadas
# de Windows cuando el monitor usa 125 %, 150 %, etc.
# ============================================================

def _configure_process_dpi_awareness():
    user32_dpi = ctypes.windll.user32

    try:
        set_context = (
            user32_dpi.SetProcessDpiAwarenessContext
        )

        set_context.argtypes = [
            ctypes.c_void_p
        ]

        # Win32 BOOL = 32 bits.
        set_context.restype = (
            ctypes.c_int
        )

        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        per_monitor_v2 = (
            ctypes.c_void_p(-4)
        )

        if set_context(
            per_monitor_v2
        ):
            return (
                "PER_MONITOR_AWARE_V2"
            )

    except AttributeError:
        pass


    # --------------------------------------------------------
    # Fallback para Windows donde V2 no esté disponible.
    # --------------------------------------------------------

    try:
        shcore = (
            ctypes.windll.shcore
        )

        set_awareness = (
            shcore.SetProcessDpiAwareness
        )

        set_awareness.argtypes = [
            ctypes.c_int
        ]

        set_awareness.restype = (
            ctypes.c_long
        )

        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        result = set_awareness(
            2
        )

        if result == 0:
            return (
                "PER_MONITOR_AWARE"
            )

    except (
        AttributeError,
        OSError,
    ):
        pass


    # --------------------------------------------------------
    # Último fallback:
    # System DPI aware.
    # --------------------------------------------------------

    try:
        set_legacy = (
            user32_dpi.SetProcessDPIAware
        )

        # Win32 BOOL = 32 bits.
        set_legacy.restype = (
            ctypes.c_int
        )

        if set_legacy():
            return (
                "SYSTEM_DPI_AWARE"
            )

    except AttributeError:
        pass


    return (
        "UNCHANGED_OR_ALREADY_CONFIGURED"
    )


PROCESS_DPI_AWARENESS = (
    _configure_process_dpi_awareness()
)

print(
    "PROCESS_DPI_AWARENESS =",
    PROCESS_DPI_AWARENESS,
)

import hashlib
import hmac
import json
import os
import secrets
import subprocess
import time
import unicodedata

import keyboard
import mouse
from dotenv import load_dotenv


# ============================================================
# CONFIG
# ============================================================

OFFICIAL_URL = (
    "https://sede.administracionespublicas.gob.es/"
    "pagina/index/directorio/icpplus"
)

FLOW_FILE = Path(
    "config/automation/icpplus/"
    "supported_flows.json"
)

FLOW_KEY = (
    "ASTURIAS:"
    "POLICIA_TOMA_HUELLAS_TIE"
)

HOST = "127.0.0.1"
PORT = 8765


# ============================================================
# OBSERVER EXECUTION IDENTITY
# ============================================================
#
# El fragmento URL no viaja al servidor HTTP.
#
# Solo sirve para que el Observer pueda demostrar qué pestaña
# nació de ESTA ejecución. Una vez vinculada mediante tabId,
# las siguientes navegaciones pueden perder el fragmento.
# ============================================================

OBSERVER_RUN_TOKEN = (
    secrets.token_urlsafe(
        24
    )
)

OBSERVER_RUN_FRAGMENT = (
    "qa_observer="
    f"{OBSERVER_RUN_TOKEN}"
)

OBSERVER_NAVIGATION_URL = (
    f"{OFFICIAL_URL}"
    f"#{OBSERVER_RUN_FRAGMENT}"
)


# ============================================================
# LOCAL ICP PLUS TEST PROFILE
# ============================================================
#
# Datos personales reutilizables exclusivamente para smoke:
#
# - NIE
# - nombre
# - nacionalidad
# - teléfono
# - email
#
# Provincia, trámite y oficina NO pertenecen al perfil.
# Posteriormente vendrán desde Automatizaciones del CRM.
# ============================================================

load_dotenv(
    ".env.local",
    override=False,
)


def test_profile_value(
    env_name,
    prompt,
    *,
    uppercase=False,
):

    value = (
        os.getenv(
            env_name,
            ""
        )
        or ""
    ).strip()

    if value:

        print(
            prompt.rstrip(": "),
            "= [ENV LOCAL]"
        )

    else:

        value = input(
            prompt
        ).strip()

    if uppercase:
        value = value.upper()

    return value


# ============================================================
# INPUT
# ============================================================

print(
    "=============================================="
)
print(
    " ICP-DESKTOP-5C-GOVERNED"
)
print(
    " F11 · LIVE DOM + OBSERVER"
)
print(
    " DOM MAP + PHYSICAL INPUT"
)
print(
    "=============================================="
)

print()
print("DATOS PARA ESTA PRUEBA")
print()

nie = test_profile_value(
    "ICPPLUS_TEST_NIE",
    "NIE: ",
    uppercase=True,
)

nombre = test_profile_value(
    "ICPPLUS_TEST_NAME",
    "Nombre: ",
    uppercase=True,
)

nacionalidad = test_profile_value(
    "ICPPLUS_TEST_NATIONALITY",
    "Nacionalidad: ",
    uppercase=True,
)

telefono = test_profile_value(
    "ICPPLUS_TEST_PHONE",
    "Telefono: ",
)

email = test_profile_value(
    "ICPPLUS_TEST_EMAIL",
    "Email: ",
)


if not all(
    (
        nie,
        nombre,
        nacionalidad,
        telefono,
        email,
    )
):
    raise RuntimeError(
        "INPUT_REQUIRED"
    )


# ============================================================
# FLOW CATALOG
# ============================================================

flow_data = json.loads(
    FLOW_FILE.read_text(
        encoding="utf-8"
    )
)

flow = flow_data[
    "flows"
][FLOW_KEY]

province = flow[
    "province"
]

procedure = flow[
    "procedure"
]

office_items = flow[
    "procedure_specific_offices"
]["items"]


print()
print("OFICINAS:")

for item in office_items:
    print(
        " -",
        item["key"],
        "|",
        item["provider_text"],
    )


office_key = input(
    "\nOficina "
    "[CNP_OVIEDO_EXPEDICION_TIE]: "
).strip()

if not office_key:
    office_key = (
        "CNP_OVIEDO_EXPEDICION_TIE"
    )

office = next(
    (
        item
        for item in office_items
        if item["key"] == office_key
    ),
    None,
)

if not office:
    raise RuntimeError(
        f"OFFICE_NOT_FOUND:{office_key}"
    )


# ============================================================
# OBSERVER EVENT BUS
# ============================================================

class EventBus:

    def __init__(self):
        self.condition = Condition()
        self.sequence = 0
        self.events = []

        self.bound_tab_id = None
        self.bound_window_id = None
        self.bound_frame_id = None

        self.rejected_sources = set()


    @staticmethod
    def _observer_source(
        payload
    ):

        source = (
            payload.get(
                "observerSource"
            )
        )

        if not isinstance(
            source,
            dict,
        ):
            return {}

        return source


    @staticmethod
    def _has_run_token(
        payload
    ):

        url = str(
            payload.get(
                "url"
            )
            or ""
        )

        if "#" not in url:
            return False

        fragment = (
            url.split(
                "#",
                1,
            )[1]
        )

        parts = {
            item
            for item in fragment.split("&")
            if item
        }

        return (
            OBSERVER_RUN_FRAGMENT
            in parts
        )


    def _reject_wrong_source(
        self,
        *,
        tab_id,
        window_id,
        frame_id,
        payload,
    ):

        key = (
            tab_id,
            window_id,
            frame_id,
        )

        if (
            key
            not in self.rejected_sources
        ):
            self.rejected_sources.add(
                key
            )

            print(
                "OBSERVER_EVENT_REJECTED_WRONG_SOURCE =",
                f"tabId={tab_id}",
                f"windowId={window_id}",
                f"frameId={frame_id}",
                "eventType="
                f"{payload.get('eventType')}",
            )


    def add(self, payload):

        with self.condition:

            source = (
                self._observer_source(
                    payload
                )
            )

            tab_id = (
                source.get(
                    "tabId"
                )
            )

            window_id = (
                source.get(
                    "windowId"
                )
            )

            frame_id = (
                source.get(
                    "frameId"
                )
            )


            # ------------------------------------------------
            # FASE 1 · TODAVÍA NO HAY SOURCE BOUND
            #
            # No aceptamos absolutamente nada de otras
            # pestañas. Solo puede vincular el bus un evento
            # cuyo URL contenga el token generado por ESTA
            # ejecución.
            # ------------------------------------------------

            if (
                self.bound_tab_id
                is None
            ):

                if not self._has_run_token(
                    payload
                ):
                    return None

                if not isinstance(
                    tab_id,
                    int,
                ):
                    print(
                        "OBSERVER_SOURCE_BIND_FAILED = "
                        "TAB_ID_MISSING"
                    )
                    return None

                if frame_id not in {
                    0,
                    None,
                }:
                    return None

                self.bound_tab_id = (
                    tab_id
                )

                self.bound_window_id = (
                    window_id
                )

                self.bound_frame_id = (
                    frame_id
                )

                print(
                    "OBSERVER_SOURCE_BOUND =",
                    f"tabId={tab_id}",
                    f"windowId={window_id}",
                    f"frameId={frame_id}",
                )


            # ------------------------------------------------
            # FASE 2 · SOURCE YA VINCULADO
            #
            # tabId es la identidad principal.
            #
            # NAVIGATION_ERROR puede no llevar windowId;
            # en ese caso tabId sigue siendo suficiente.
            # ------------------------------------------------

            else:

                wrong_tab = (
                    tab_id
                    != self.bound_tab_id
                )

                wrong_window = (
                    self.bound_window_id
                    is not None
                    and window_id
                    is not None
                    and window_id
                    != self.bound_window_id
                )

                wrong_frame = (
                    frame_id
                    not in {
                        0,
                        None,
                    }
                )

                if (
                    wrong_tab
                    or wrong_window
                    or wrong_frame
                ):

                    self._reject_wrong_source(
                        tab_id=tab_id,
                        window_id=window_id,
                        frame_id=frame_id,
                        payload=payload,
                    )

                    return None


            self.sequence += 1

            item = {
                "seq":
                    self.sequence,

                "payload":
                    payload,
            }

            self.events.append(
                item
            )

            self.condition.notify_all()

            return self.sequence


    def current_seq(self):
        with self.condition:
            return self.sequence


    def wait(
        self,
        predicate,
        after_seq=0,
        timeout=20,
        raise_on_portal_status=True,
    ):

        deadline = (
            time.time()
            + timeout
        )

        with self.condition:

            while True:

                for item in self.events:

                    if (
                        item["seq"]
                        <= after_seq
                    ):
                        continue

                    payload = (
                        item["payload"]
                    )

                    portal_status = (
                        payload.get(
                            "portalStatus"
                        )
                    )

                    if (
                        raise_on_portal_status
                        and
                        portal_status in {
                            "BLOCKED",
                            "DOWN",
                            "DEGRADED",
                        }
                    ):

                        raise RuntimeError(
                            "PORTAL_"
                            f"{portal_status}:"
                            f"{payload.get('url')}:"
                            f"{payload.get('supportId')}:"
                            f"{payload.get('navigationError')}"
                        )

                    if predicate(
                        payload
                    ):
                        return (
                            item["seq"],
                            payload,
                        )

                remaining = (
                    deadline
                    - time.time()
                )

                if remaining <= 0:
                    raise TimeoutError(
                        "OBSERVER_TIMEOUT"
                    )

                self.condition.wait(
                    min(
                        remaining,
                        0.5,
                    )
                )


BUS = EventBus()


class Handler(
    BaseHTTPRequestHandler
):

    def do_POST(self):

        if self.path != "/icpplus":
            self.send_response(404)
            self.end_headers()
            return

        length = int(
            self.headers.get(
                "Content-Length",
                "0",
            )
        )

        payload = json.loads(
            self.rfile.read(
                length
            ).decode(
                "utf-8"
            )
        )

        seq = BUS.add(
            payload
        )

        event_type = (
            payload.get(
                "eventType"
            )
        )

        page = (
            payload.get(
                "page"
            )
        )

        if (
            seq is not None
            and event_type in {
                "SEMANTIC_STATE",
                "DOM_STATE",
                "NAVIGATION_ERROR",
            }
        ):
            print(
                f"[OBS {seq:02d}]",
                event_type,
                "|",
                page,
                "|",
                payload.get(
                    "portalStatus"
                ),
                "|",
                payload.get(
                    "availabilityStatus"
                ),
            )

        self.send_response(204)

        self.send_header(
            "Access-Control-Allow-Origin",
            "*",
        )

        self.end_headers()


    def log_message(
        self,
        format,
        *args,
    ):
        return


server = ThreadingHTTPServer(
    (
        HOST,
        PORT,
    ),
    Handler,
)

server_thread = Thread(
    target=server.serve_forever,
    daemon=True,
)

server_thread.start()

print()
print(
    "Observer receiver =",
    f"http://{HOST}:{PORT}",
)


# ============================================================
# WINDOWS / CHROME
# ============================================================

user32 = ctypes.windll.user32


EnumWindowsProc = ctypes.WINFUNCTYPE(
    ctypes.c_bool,
    ctypes.c_void_p,
    ctypes.c_void_p,
)


def get_class(hwnd):

    buffer = (
        ctypes.create_unicode_buffer(
            256
        )
    )

    user32.GetClassNameW(
        hwnd,
        buffer,
        256,
    )

    return buffer.value


def get_title(hwnd):

    length = (
        user32.GetWindowTextLengthW(
            hwnd
        )
    )

    if not length:
        return ""

    buffer = (
        ctypes.create_unicode_buffer(
            length + 1
        )
    )

    user32.GetWindowTextW(
        hwnd,
        buffer,
        length + 1,
    )

    return buffer.value


def chrome_windows():

    result = []

    @EnumWindowsProc
    def callback(
        hwnd,
        _,
    ):

        if not user32.IsWindowVisible(
            hwnd
        ):
            return True

        if (
            get_class(hwnd)
            == "Chrome_WidgetWin_1"
        ):
            result.append(
                hwnd
            )

        return True

    user32.EnumWindows(
        callback,
        0,
    )

    return result


def activate_chrome(hwnd):

    # IMPORTANTE:
    #
    # Esta función SOLO debe dar foco a Chrome.
    #
    # No hacemos ShowWindow(..., SW_MAXIMIZE) porque,
    # una vez activado F11, modificar el estado de la
    # ventana invalidaría la geometría DOM que acabamos
    # de recibir del Observer.
    #
    # Solo restauramos si Windows indica que la ventana
    # está realmente minimizada.

    if user32.IsIconic(
        hwnd
    ):
        user32.ShowWindow(
            hwnd,
            9,  # SW_RESTORE
        )

        time.sleep(
            0.4
        )

    user32.keybd_event(
        0x12,
        0,
        0,
        0,
    )

    user32.SetForegroundWindow(
        hwnd
    )

    user32.keybd_event(
        0x12,
        0,
        2,
        0,
    )

    time.sleep(
        0.25
    )

    if (
        user32.GetForegroundWindow()
        != hwnd
    ):
        raise RuntimeError(
            "CHROME_FOCUS_FAILED"
        )


def close_owned_chrome(
    hwnd,
):

    if not hwnd:
        return

    if not user32.IsWindow(
        hwnd
    ):
        return

    print()
    print(
        "CLOSING_OWNED_CHROME =",
        hwnd,
    )

    WM_CLOSE = 0x0010

    user32.PostMessageW(
        hwnd,
        WM_CLOSE,
        0,
        0,
    )

    deadline = (
        time.time()
        + 5
    )

    while (
        time.time()
        < deadline
    ):

        if not user32.IsWindow(
            hwnd
        ):

            print(
                "OWNED_CHROME_CLOSED = OK"
            )

            return

        time.sleep(
            0.1
        )

    print(
        "OWNED_CHROME_CLOSE_TIMEOUT"
    )


def open_clean_chrome():

    before = set(
        chrome_windows()
    )

    subprocess.run(
        'start chrome --new-window "about:blank"',
        shell=True,
    )

    deadline = (
        time.time()
        + 8
    )

    hwnd = None

    while time.time() < deadline:

        current = (
            chrome_windows()
        )

        new = [
            item
            for item in current
            if item not in before
        ]

        if new:
            hwnd = new[0]
            break

        # Seguridad de ownership:
        # nunca adoptar una ventana Chrome que ya existiera
        # antes de iniciar esta ejecución.

        time.sleep(
            0.25
        )

    if not hwnd:
        raise RuntimeError(
            "CHROME_WINDOW_NOT_FOUND"
        )

    activate_chrome(
        hwnd
    )

    return hwnd


# ============================================================
# OBSERVER HELPERS
# ============================================================

def wait_semantic(
    page,
    after_seq,
    timeout=20,
):

    return BUS.wait(
        lambda payload:
            (
                payload.get(
                    "eventType"
                )
                == "SEMANTIC_STATE"
                and
                payload.get(
                    "page"
                )
                == page
            ),
        after_seq=after_seq,
        timeout=timeout,
    )


def wait_semantic_any(
    pages,
    after_seq,
    timeout=20,
):

    wanted = set(
        pages
    )

    return BUS.wait(
        lambda payload:
            (
                payload.get(
                    "eventType"
                )
                == "SEMANTIC_STATE"
                and
                payload.get(
                    "page"
                )
                in wanted
            ),
        after_seq=after_seq,
        timeout=timeout,
    )


# ============================================================
# NORMALIZATION
# ============================================================

def norm(value):

    value = str(
        value or ""
    ).strip().upper()

    value = (
        unicodedata.normalize(
            "NFKD",
            value,
        )
        .encode(
            "ascii",
            "ignore",
        )
        .decode(
            "ascii"
        )
    )

    return " ".join(
        value.split()
    )


# ============================================================
# PHYSICAL INPUT
# ============================================================

CHROME_HWND = None


# ============================================================
# LIVE DOM -> PHYSICAL INPUT GEOMETRY
# ============================================================
#
# No existen coordenadas físicas históricas.
#
# Toda interacción se resuelve mediante geometría DOM fresca
# del Observer y conversión al área cliente Win32 de la
# ventana Chrome propiedad de esta ejecución.
# ============================================================


class POINT(
    ctypes.Structure
):
    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
    ]


class RECT(
    ctypes.Structure
):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def dom_rect_to_screen(
    rect,
):
    """
    Convierte coordenadas CSS del viewport DOM
    a coordenadas del área cliente real de Chrome.

    En F11 el viewport web ocupa prácticamente
    toda el área cliente del HWND.

    El cociente client/viewport corrige además
    diferencias de escalado DPI.
    """

    if not CHROME_HWND:
        raise RuntimeError(
            "CHROME_HWND_MISSING"
        )

    center_x = rect.get(
        "centerX"
    )

    center_y = rect.get(
        "centerY"
    )

    viewport_width = rect.get(
        "viewportWidth"
    )

    viewport_height = rect.get(
        "viewportHeight"
    )

    if (
        center_x is None
        or center_y is None
        or not viewport_width
        or not viewport_height
    ):
        raise RuntimeError(
            "DOM_GEOMETRY_INCOMPLETE"
        )


    client = RECT()

    if not user32.GetClientRect(
        CHROME_HWND,
        ctypes.byref(client),
    ):
        raise RuntimeError(
            "GET_CLIENT_RECT_FAILED"
        )


    origin = POINT(
        0,
        0,
    )

    if not user32.ClientToScreen(
        CHROME_HWND,
        ctypes.byref(origin),
    ):
        raise RuntimeError(
            "CLIENT_TO_SCREEN_FAILED"
        )


    client_width = (
        client.right
        - client.left
    )

    client_height = (
        client.bottom
        - client.top
    )


    scale_x = (
        client_width
        / float(viewport_width)
    )

    scale_y = (
        client_height
        / float(viewport_height)
    )


    screen_x = round(
        origin.x
        + center_x
        * scale_x
    )

    screen_y = round(
        origin.y
        + center_y
        * scale_y
    )


    print(
        "DOM_CENTER =",
        (
            center_x,
            center_y,
        ),
    )

    print(
        "DOM_VIEWPORT =",
        (
            viewport_width,
            viewport_height,
        ),
    )

    print(
        "WIN32_CLIENT_ORIGIN =",
        (
            origin.x,
            origin.y,
        ),
    )

    print(
        "WIN32_CLIENT_SIZE =",
        (
            client_width,
            client_height,
        ),
    )

    print(
        "DOM_WIN32_SCALE =",
        (
            round(scale_x, 4),
            round(scale_y, 4),
        ),
    )

    print(
        "CALCULATED_SCREEN_CENTER =",
        (
            screen_x,
            screen_y,
        ),
    )

    print(
        "OBSERVER_ESTIMATED_CENTER =",
        (
            rect.get(
                "screenCenterX"
            ),
            rect.get(
                "screenCenterY"
            ),
        ),
    )


    return (
        screen_x,
        screen_y,
    )


def click_item(
    item,
    description,
):

    global CHROME_HWND

    if not item:
        raise RuntimeError(
            f"CONTROL_NOT_FOUND:{description}"
        )

    rect = (
        item.get(
            "rect"
        )
        or {}
    )

    if not rect.get(
        "visible"
    ):
        raise RuntimeError(
            f"CONTROL_NOT_VISIBLE:{description}"
        )

    x, y = (
        dom_rect_to_screen(
            rect
        )
    )

    activate_chrome(
        CHROME_HWND
    )

    print(
        "CLICK",
        description,
        "->",
        (x, y),
    )

    mouse.move(
        x,
        y,
        duration=0.40,
    )

    mouse.click(
        button="left"
    )

    time.sleep(
        0.8
    )


def find_action(
    state,
    *,
    action_id=None,
    text_contains=None,
):

    actions = (
        state.get(
            "actionControls"
        )
        or []
    )

    if action_id:

        matches = [
            item
            for item in actions
            if (
                item.get("id")
                == action_id
            )
        ]

        visible = [
            item
            for item in matches
            if (
                item.get("rect")
                or {}
            ).get("visible")
        ]

        if visible:
            return visible[0]

        if matches:
            return matches[0]


    if text_contains:

        wanted = norm(
            text_contains
        )

        matches = [
            item
            for item in actions
            if wanted in norm(
                item.get("text")
            )
        ]

        visible = [
            item
            for item in matches
            if (
                item.get("rect")
                or {}
            ).get("visible")
        ]

        if visible:
            return visible[0]

        if matches:
            return matches[0]


    raise RuntimeError(
        "ACTION_NOT_FOUND:"
        f"id={action_id}:"
        f"text={text_contains}"
    )


def ensure_action_visible(
    state,
    *,
    expected_page,
    action_id=None,
    text_contains=None,
    max_scroll_steps=12,
    wheel_delta=-1,
    wheel_burst=1,
    safe_margin_y=0,
):
    """
    Garantiza que una acción pueda localizarse y sea visible.

    Soporta dos situaciones:

    1. La acción ya existe en actionControls pero está
       fuera del viewport.

    2. La acción todavía no aparece en actionControls,
       por ejemplo cuando la página termina de incorporar
       contenido al avanzar físicamente por ella.

    Nunca utiliza coordenadas históricas.
    """

    current_state = state

    for step in range(
        max_scroll_steps + 1
    ):

        if (
            current_state.get("page")
            != expected_page
        ):
            raise RuntimeError(
                "VISIBILITY_PAGE_CHANGED:"
                f"expected={expected_page}:"
                f"actual={current_state.get('page')}"
            )


        # ----------------------------------------------------
        # La acción puede no estar publicada todavía.
        # Eso NO debe abortar antes de intentar scroll.
        # ----------------------------------------------------

        action = None

        try:
            action = find_action(
                current_state,
                action_id=action_id,
                text_contains=text_contains,
            )

        except RuntimeError as exc:

            if not str(exc).startswith(
                "ACTION_NOT_FOUND:"
            ):
                raise


        if action is None:

            print(
                "ACTION_DISCOVERY =",
                expected_page,
                action_id or text_contains,
                f"step={step}",
                "found=False",
            )

        else:

            rect = (
                action.get("rect")
                or {}
            )

            visible = bool(
                rect.get("visible")
            )

            center_y = (
                rect.get(
                    "centerY"
                )
            )

            viewport_height = (
                rect.get(
                    "viewportHeight"
                )
            )

            safe_vertical = True

            if safe_margin_y:

                safe_vertical = (
                    isinstance(
                        center_y,
                        (int, float),
                    )
                    and isinstance(
                        viewport_height,
                        (int, float),
                    )
                    and center_y >= safe_margin_y
                    and center_y <= (
                        viewport_height
                        - safe_margin_y
                    )
                )

            print(
                "ACTION_VISIBILITY =",
                expected_page,
                action_id or text_contains,
                f"step={step}",
                f"visible={visible}",
                f"safe_vertical={safe_vertical}",
            )

            if (
                visible
                and safe_vertical
            ):

                print(
                    "ACTION_VISIBLE_SAFE = OK"
                )

                return (
                    current_state,
                    action,
                )

            if (
                visible
                and not safe_vertical
            ):

                print(
                    "ACTION_VISIBLE_BUT_EDGE =",
                    action_id or text_contains,
                    "| centerY=",
                    center_y,
                    "| viewportHeight=",
                    viewport_height,
                    "| safeMarginY=",
                    safe_margin_y,
                )


        # ----------------------------------------------------
        # Límite estricto.
        # ----------------------------------------------------

        if step >= max_scroll_steps:
            break


        # ----------------------------------------------------
        # Scroll físico mínimo.
        # ----------------------------------------------------

        activate_chrome(
            CHROME_HWND
        )

        before_scroll = (
            BUS.current_seq()
        )

        effective_wheel_burst = (
            wheel_burst
        )

        if (
            action is not None
            and bool(
                (
                    action.get("rect")
                    or {}
                ).get("visible")
            )
            and safe_margin_y
        ):
            # La acción ya ha entrado en pantalla.
            # A partir de aquí refinamos posición sin
            # saltarnos el objetivo.
            effective_wheel_burst = 1

        print(
            "ADAPTIVE_SCROLL_BURST =",
            step + 1,
            "/",
            max_scroll_steps,
            "| delta=",
            wheel_delta,
            "| burst=",
            effective_wheel_burst,
        )

        for _ in range(
            effective_wheel_burst
        ):

            mouse.wheel(
                wheel_delta
            )

            time.sleep(
                0.05
            )

        time.sleep(
            0.15
        )


        # ----------------------------------------------------
        # Exigir geometría/DOM semántico posterior al scroll.
        # ----------------------------------------------------

        _, current_state = (
            wait_semantic(
                expected_page,
                after_seq=before_scroll,
                timeout=4,
            )
        )


    raise RuntimeError(
        "ACTION_NOT_VISIBLE_AFTER_SCROLL:"
        f"page={expected_page}:"
        f"id={action_id}:"
        f"text={text_contains}:"
        f"max_steps={max_scroll_steps}"
    )


def click_action(
    state,
    *,
    action_id=None,
    text_contains=None,
):
    """
    Governed action policy:

    1. Observer must already have validated the current page.
    2. Resolve the action from the current semantic DOM.
    3. Click exclusively using its live DOM geometry.

    Historical physical anchors are not allowed.
    """

    page = state.get(
        "page"
    )

    action_name = (
        action_id
        or text_contains
    )

    if not page:
        raise RuntimeError(
            "ACTION_PAGE_MISSING"
        )

    if not action_name:
        raise RuntimeError(
            "ACTION_NAME_MISSING"
        )

    item = find_action(
        state,
        action_id=action_id,
        text_contains=text_contains,
    )

    click_item(
        item,
        action_name,
    )


def find_option(
    control,
    *,
    value=None,
    text=None,
):

    options = (
        control.get(
            "options"
        )
        or []
    )

    if value is not None:

        for option in options:

            if (
                str(
                    option.get(
                        "value"
                    )
                )
                == str(value)
            ):
                return option


    if text is not None:

        wanted = norm(
            text
        )

        exact = [
            option
            for option in options
            if norm(
                option.get(
                    "text"
                )
            ) == wanted
        ]

        if exact:
            return exact[0]


        partial = [
            option
            for option in options
            if wanted in norm(
                option.get(
                    "text"
                )
            )
        ]

        if len(partial) == 1:
            return partial[0]


    raise RuntimeError(
        "OPTION_NOT_FOUND:"
        f"value={value}:"
        f"text={text}"
    )


def select_option(
    control,
    *,
    value=None,
    text=None,
    description,
):

    option = find_option(
        control,
        value=value,
        text=text,
    )

    index = int(
        option["index"]
    )

    click_item(
        control,
        description,
    )

    keyboard.press_and_release(
        "home"
    )

    time.sleep(
        0.2
    )

    for _ in range(index):
        keyboard.press_and_release(
            "down"
        )

    keyboard.press_and_release(
        "enter"
    )

    time.sleep(
        0.8
    )

    print(
        "SELECTED",
        description,
        "=",
        option.get("text"),
        "| value=",
        option.get("value"),
    )


def fill_text(
    control,
    value,
    description,
):

    click_item(
        control,
        description,
    )

    keyboard.press_and_release(
        "ctrl+a"
    )

    keyboard.write(
        value,
        delay=0.08,
    )

    time.sleep(
        0.6
    )


def observer_value_proof(
    value,
):
    """
    HMAC efímero de un valor textual.

    El secreto cambia en cada ejecución y nunca se persiste.
    """

    raw = str(
        value or ""
    )

    return hmac.new(
        OBSERVER_RUN_TOKEN.encode(
            "utf-8"
        ),
        raw.encode(
            "utf-8"
        ),
        hashlib.sha256,
    ).hexdigest()


def observer_control_matches_value(
    control,
    expected_value,
):

    actual_proof = str(
        control.get(
            "valueProof"
        )
        or ""
    )

    if not actual_proof:
        return False

    expected_proof = (
        observer_value_proof(
            expected_value
        )
    )

    return hmac.compare_digest(
        actual_proof,
        expected_proof,
    )


def fill_text_verified(
    state,
    *,
    control_key,
    value,
    description,
    expected_page,
    max_attempts=2,
):
    """
    Escritura física verificada.

    Contrato:
    1. resolver control desde DOM fresco;
    2. click físico;
    3. confirmar foco mediante Observer;
    4. cerrar sugerencias/autofill con ESC;
    5. escribir;
    6. tomar baseline DESPUÉS de la escritura;
    7. esperar un SEMANTIC_STATE posterior;
    8. verificar el valor real.

    Nunca imprime el contenido del campo.
    """

    current_state = state

    expected_value = str(
        value or ""
    ).strip()


    for attempt in range(
        1,
        max_attempts + 1,
    ):

        if (
            current_state.get("page")
            != expected_page
        ):
            raise RuntimeError(
                "FIELD_PAGE_CHANGED:"
                f"{description}:"
                f"expected={expected_page}:"
                f"actual={current_state.get('page')}"
            )


        controls = (
            current_state.get(
                "navigationControls"
            )
            or {}
        )

        control = (
            controls.get(
                control_key
            )
            or {}
        )

        if not control:
            raise RuntimeError(
                "FIELD_CONTROL_NOT_FOUND:"
                f"{description}"
            )


        print(
            "FIELD_WRITE =",
            description,
            f"attempt={attempt}",
        )


        # ----------------------------------------------------
        # 1. CLICK REAL
        # ----------------------------------------------------

        click_item(
            control,
            description,
        )


        # ----------------------------------------------------
        # 2. CONFIRMAR FOCO CON ESTADO POSTERIOR AL CLICK
        # ----------------------------------------------------

        focus_baseline = (
            BUS.current_seq()
        )

        _, current_state = (
            wait_semantic(
                expected_page,
                after_seq=focus_baseline,
                timeout=4,
            )
        )

        focused_control = (
            (
                current_state.get(
                    "navigationControls"
                )
                or {}
            ).get(
                control_key
            )
            or {}
        )

        if not focused_control.get(
            "focused"
        ):

            print(
                "FIELD_FOCUS_MISMATCH =",
                description,
                f"attempt={attempt}",
            )

            if attempt < max_attempts:
                print(
                    "FIELD_RETRY_WITH_FRESH_DOM =",
                    description,
                )
                continue

            break


        print(
            "FIELD_FOCUS_VERIFIED =",
            description,
            "OK",
        )


        # ----------------------------------------------------
        # 3. CERRAR SUGERENCIAS DE AUTOCOMPLETADO
        #
        # ESC no modifica el contenido. Solo cierra dropdowns
        # o sugerencias del navegador si están abiertos.
        # ----------------------------------------------------

        keyboard.press_and_release(
            "esc"
        )

        time.sleep(
            0.20
        )


        # ----------------------------------------------------
        # 4. ESCRIBIR
        # ----------------------------------------------------

        keyboard.press_and_release(
            "ctrl+a"
        )

        keyboard.write(
            value,
            delay=0.08,
        )

        time.sleep(
            0.40
        )


        # ----------------------------------------------------
        # MUY IMPORTANTE:
        #
        # baseline DESPUÉS de terminar de escribir.
        #
        # Así nunca verificamos contra un heartbeat generado
        # por el click o mientras aún se estaba escribiendo.
        # ----------------------------------------------------

        verification_baseline = (
            BUS.current_seq()
        )

        _, current_state = (
            wait_semantic(
                expected_page,
                after_seq=verification_baseline,
                timeout=4,
            )
        )


        fresh_control = (
            (
                current_state.get(
                    "navigationControls"
                )
                or {}
            ).get(
                control_key
            )
            or {}
        )

        if "valueProof" not in fresh_control:
            raise RuntimeError(
                "OBSERVER_VALUE_PROOF_UNAVAILABLE:"
                f"{description}"
            )


        if observer_control_matches_value(
            fresh_control,
            expected_value,
        ):

            print(
                "FIELD_VALUE_VERIFIED =",
                description,
                "OK",
            )

            return current_state


        print(
            "FIELD_VALUE_MISMATCH =",
            description,
            f"attempt={attempt}",
        )


        if attempt < max_attempts:

            print(
                "FIELD_RETRY_WITH_FRESH_DOM =",
                description,
            )

            time.sleep(
                0.40
            )


    raise RuntimeError(
        "FIELD_VALUE_MISMATCH:"
        f"{description}"
    )


def fill_text_verified_by_tab(
    state,
    *,
    source_control_key,
    target_control_key,
    value,
    description,
    expected_page,
):
    """
    Escribe un campo utilizando TAB desde el control anterior.

    Caso de uso:
    EMAIL -> EMAIL_REPEAT.

    Evita que un popup de autocompletado de Chrome intercepte
    físicamente el click sobre el segundo campo.
    """

    if (
        state.get("page")
        != expected_page
    ):
        raise RuntimeError(
            "TAB_FIELD_PAGE_CHANGED:"
            f"{description}:"
            f"actual={state.get('page')}"
        )


    controls = (
        state.get(
            "navigationControls"
        )
        or {}
    )

    source_control = (
        controls.get(
            source_control_key
        )
        or {}
    )


    # El campo anterior debe seguir siendo el foco actual.
    if not source_control.get(
        "focused"
    ):
        raise RuntimeError(
            "TAB_SOURCE_NOT_FOCUSED:"
            f"{description}:"
            f"source={source_control_key}"
        )


    print(
        "TAB_SOURCE_FOCUS_VERIFIED =",
        source_control_key,
        "OK",
    )


    activate_chrome(
        CHROME_HWND
    )


    # --------------------------------------------------------
    # Cerrar sugerencias/autofill sin abandonar el input.
    # --------------------------------------------------------

    keyboard.press_and_release(
        "esc"
    )

    time.sleep(
        0.25
    )


    # --------------------------------------------------------
    # Pasar físicamente al siguiente campo.
    # Baseline ANTES del TAB.
    # --------------------------------------------------------

    before_tab = (
        BUS.current_seq()
    )

    keyboard.press_and_release(
        "tab"
    )

    _, state = (
        wait_semantic(
            expected_page,
            after_seq=before_tab,
            timeout=4,
        )
    )


    target_control = (
        (
            state.get(
                "navigationControls"
            )
            or {}
        ).get(
            target_control_key
        )
        or {}
    )


    if not target_control.get(
        "focused"
    ):
        raise RuntimeError(
            "TAB_TARGET_NOT_FOCUSED:"
            f"{description}:"
            f"target={target_control_key}"
        )


    print(
        "TAB_TARGET_FOCUS_VERIFIED =",
        description,
        "OK",
    )


    # --------------------------------------------------------
    # Escribir ya con #emailDOS confirmado como foco.
    # --------------------------------------------------------

    keyboard.press_and_release(
        "ctrl+a"
    )

    keyboard.write(
        value,
        delay=0.08,
    )

    time.sleep(
        0.40
    )


    # Baseline posterior a la escritura.
    verification_baseline = (
        BUS.current_seq()
    )

    _, state = (
        wait_semantic(
            expected_page,
            after_seq=verification_baseline,
            timeout=4,
        )
    )


    target_control = (
        (
            state.get(
                "navigationControls"
            )
            or {}
        ).get(
            target_control_key
        )
        or {}
    )

    expected_value = str(
        value or ""
    ).strip()


    if not observer_control_matches_value(
        target_control,
        expected_value,
    ):
        raise RuntimeError(
            "TAB_FIELD_VALUE_MISMATCH:"
            f"{description}"
        )


    print(
        "FIELD_VALUE_VERIFIED =",
        description,
        "OK",
    )

    return state


# ============================================================
# FLOW
# ============================================================

try:

    # --------------------------------------------------------
    # OPEN CHROME NORMAL
    # --------------------------------------------------------

    print()
    print(
        "=============================================="
    )
    print(
        " OPEN NORMAL CHROME"
    )
    print(
        "=============================================="
    )

    # --------------------------------------------------------
    # NUEVA REGLA:
    #
    # 1. abrir Chrome,
    # 2. navegar ANTES de F11,
    # 3. exigir un DOM_STATE fresco,
    # 4. activar F11,
    # 5. exigir geometría semántica fresca.
    #
    # De esta forma nunca utilizamos heartbeats de una pestaña
    # antigua para controlar la ventana recién abierta.
    # --------------------------------------------------------

    navigation_baseline = (
        BUS.current_seq()
    )

    CHROME_HWND = (
        open_clean_chrome()
    )

    activate_chrome(
        CHROME_HWND
    )

    print(
        "CHROME_NAVIGATE_OFFICIAL_URL"
    )

    keyboard.press_and_release(
        "ctrl+l"
    )

    keyboard.write(
        OBSERVER_NAVIGATION_URL,
        delay=0.01,
    )

    keyboard.press_and_release(
        "enter"
    )


    # --------------------------------------------------------
    # No aceptamos SEMANTIC_STATE histórico.
    #
    # content.js debe producir un DOM_STATE NUEVO como
    # consecuencia de ESTA navegación.
    # --------------------------------------------------------

    print(
        "WAITING_FRESH_DOM_STATE..."
    )

    dom_seq, dom_state = BUS.wait(
        lambda payload:
            (
                payload.get(
                    "eventType"
                )
                == "DOM_STATE"
                and
                payload.get(
                    "page"
                )
                == "LANDING"
                and
                str(
                    payload.get(
                        "url"
                    )
                    or ""
                ).startswith(
                    OFFICIAL_URL
                )
            ),
        after_seq=navigation_baseline,
        timeout=20,
    )

    print(
        "FRESH_DOM_STATE = OK"
    )

    print(
        "URL =",
        dom_state.get(
            "url"
        ),
    )


    # --------------------------------------------------------
    # Solo ahora activamos fullscreen.
    # La página real ya está cargada.
    # --------------------------------------------------------

    activate_chrome(
        CHROME_HWND
    )

    before_f11 = (
        BUS.current_seq()
    )

    print(
        "CHROME_FULLSCREEN_F11 = ON"
    )

    keyboard.press_and_release(
        "f11"
    )

    time.sleep(
        1.25
    )


    # --------------------------------------------------------
    # F11 cambia viewport.
    # Obligatoriamente esperamos geometría recalculada.
    # --------------------------------------------------------

    print(
        "WAITING_FRESH_FULLSCREEN_GEOMETRY..."
    )

    seq, state = BUS.wait(
        lambda payload:
            (
                payload.get(
                    "eventType"
                )
                == "SEMANTIC_STATE"
                and
                payload.get(
                    "page"
                )
                == "LANDING"
                and
                str(
                    payload.get(
                        "url"
                    )
                    or ""
                ).startswith(
                    OFFICIAL_URL
                )
            ),
        after_seq=before_f11,
        timeout=6,
    )

    print(
        "FRESH_FULLSCREEN_GEOMETRY = OK"
    )

    print(
        "SEMANTIC_URL =",
        state.get(
            "url"
        ),
    )

    viewport = (
        state.get("viewport")
        or {}
    )

    # --------------------------------------------------------
    # OBSERVER CONTRACT
    #
    # La geometría portable requiere semantic schema >= 6:
    # - value
    # - focused
    # - viewport
    # - rect dinámico
    # --------------------------------------------------------

    privacy_contract_version = (
        state.get(
            "privacyContractVersion"
        )
    )

    if (
        privacy_contract_version
        != 1
    ):
        raise RuntimeError(
            "OBSERVER_PRIVACY_CONTRACT_MISSING:"
            f"{privacy_contract_version}:"
            "reload_extension_required"
        )

    print(
        "OBSERVER_PRIVACY_CONTRACT_VERSION =",
        privacy_contract_version,
    )


    observer_schema_version = (
        state.get(
            "schemaVersion"
        )
    )

    if (
        not isinstance(
            observer_schema_version,
            (int, float),
        )
        or observer_schema_version < 6
    ):
        raise RuntimeError(
            "OBSERVER_SCHEMA_TOO_OLD:"
            f"{observer_schema_version}:"
            "required=6"
        )

    print(
        "OBSERVER_SCHEMA_VERSION =",
        observer_schema_version,
    )


    # --------------------------------------------------------
    # PORTABLE VIEWPORT CONTRACT
    #
    # Ya NO exigimos 1920x1080.
    #
    # Solo exigimos dimensiones DOM válidas. La conversión
    # posterior DOM -> Win32 calcula la escala real entre
    # viewport CSS y cliente físico.
    # --------------------------------------------------------

    viewport_size = (
        viewport.get("innerWidth"),
        viewport.get("innerHeight"),
    )

    print(
        "VIEWPORT =",
        viewport_size,
    )

    viewport_width = (
        viewport.get(
            "innerWidth"
        )
    )

    viewport_height = (
        viewport.get(
            "innerHeight"
        )
    )

    device_pixel_ratio = (
        viewport.get(
            "devicePixelRatio"
        )
    )

    if (
        not isinstance(
            viewport_width,
            (int, float),
        )
        or viewport_width <= 0
        or not isinstance(
            viewport_height,
            (int, float),
        )
        or viewport_height <= 0
    ):
        raise RuntimeError(
            "INVALID_VIEWPORT_GEOMETRY:"
            f"{viewport_size}"
        )

    if (
        not isinstance(
            device_pixel_ratio,
            (int, float),
        )
        or device_pixel_ratio <= 0
    ):
        raise RuntimeError(
            "INVALID_DEVICE_PIXEL_RATIO:"
            f"{device_pixel_ratio}"
        )

    print(
        "DEVICE_PIXEL_RATIO =",
        device_pixel_ratio,
    )

    print(
        "PORTABLE_VIEWPORT_CONTRACT = OK"
    )


    # --------------------------------------------------------
    # LANDING
    # --------------------------------------------------------

    if (
        state.get("page")
        == "LANDING"
    ):

        print()
        print(
            "STAGE = LANDING"
        )

        # ------------------------------------------------
        # El botón oficial puede quedar fuera del viewport
        # cuando Chrome NO está en F11.
        #
        # Si no es visible:
        #   1. activamos Chrome,
        #   2. scroll físico al final,
        #   3. esperamos geometría NUEVA del Observer,
        #   4. volvemos a resolver el botón.
        # ------------------------------------------------

        state, landing_action = (
            ensure_action_visible(
                state,
                expected_page="LANDING",
                action_id="submit",
                text_contains=(
                    "Acceder al Procedimiento"
                ),
                max_scroll_steps=12,
                wheel_delta=-1,
            )
        )

        landing_rect = (
            landing_action.get("rect")
            or {}
        )

        print(
            "LANDING_ACTION_SCREEN_CENTER =",
            (
                landing_rect.get(
                    "screenCenterX"
                ),
                landing_rect.get(
                    "screenCenterY"
                ),
            ),
        )

        before_click = (
            BUS.current_seq()
        )

        click_action(
            state,
            action_id="submit",
            text_contains=(
                "Acceder al Procedimiento"
            ),
        )

        seq, state = (
            wait_semantic(
                "PROVINCE_SELECTION",
                after_seq=before_click,
                timeout=20,
            )
        )


    # --------------------------------------------------------
    # PROVINCE
    # --------------------------------------------------------

    print()
    print(
        "STAGE = PROVINCE_SELECTION"
    )

    controls = (
        state[
            "navigationControls"
        ]
    )

    select_option(
        controls["province"],
        value=province[
            "provider_value"
        ],
        description="PROVINCE",
    )

    before = (
        BUS.current_seq()
    )

    click_action(
        state,
        action_id="btnAceptar",
        text_contains="Aceptar",
    )

    seq, state = (
        wait_semantic(
            "PROCEDURE_SELECTION",
            after_seq=before,
            timeout=20,
        )
    )


    # --------------------------------------------------------
    # PROCEDURE
    # --------------------------------------------------------

    print()
    print(
        "STAGE = PROCEDURE_SELECTION"
    )

    controls = (
        state[
            "navigationControls"
        ]
    )

    procedure_control = None

    for candidate in (
        controls.get(
            "procedureGroups"
        )
        or []
    ):

        try:

            find_option(
                candidate,
                value=procedure[
                    "provider_value"
                ],
            )

            procedure_control = (
                candidate
            )

            break

        except RuntimeError:
            pass


    if not procedure_control:
        raise RuntimeError(
            "PROCEDURE_CONTROL_NOT_FOUND"
        )


    select_option(
        procedure_control,
        value=procedure[
            "provider_value"
        ],
        description="PROCEDURE",
    )


    before = (
        BUS.current_seq()
    )

    click_action(
        state,
        action_id="btnAceptar",
        text_contains="Aceptar",
    )


    seq, state = (
        wait_semantic(
            "PROCEDURE_INFO",
            after_seq=before,
            timeout=20,
        )
    )


    # --------------------------------------------------------
    # PRESENTACION SIN CLAVE
    # --------------------------------------------------------

    print()
    print(
        "STAGE = PROCEDURE_INFO"
    )

    # --------------------------------------------------------
    # El botón puede encontrarse fuera del viewport.
    #
    # No usamos:
    # - scroll histórico;
    # - coordenadas MASTER;
    # - resolución fija para localizarlo.
    #
    # Se desplaza físicamente paso a paso y, después de cada
    # scroll, el Observer publica geometría DOM nueva.
    # --------------------------------------------------------

    state, procedure_info_action = (
        ensure_action_visible(
            state,
            expected_page="PROCEDURE_INFO",
            action_id="btnEntrar",
            text_contains=(
                "Presentación sin Cl@ve"
            ),
            max_scroll_steps=16,
            wheel_delta=-1,
            wheel_burst=4,
            safe_margin_y=120,
        )
    )

    # --------------------------------------------------------
    # FRESH GEOMETRY BARRIER
    #
    # PROCEDURE_INFO requiere varios scrolls. No utilizamos
    # directamente la geometría que declaró visible el botón:
    # esperamos un heartbeat semántico posterior y volvemos
    # a resolver btnEntrar antes del click físico.
    # --------------------------------------------------------

    print(
        "PROCEDURE_INFO_GEOMETRY_SETTLE = WAIT"
    )

    geometry_before = (
        BUS.current_seq()
    )

    time.sleep(
        0.50
    )

    _, state = (
        wait_semantic(
            "PROCEDURE_INFO",
            after_seq=geometry_before,
            timeout=4,
        )
    )

    procedure_info_action = (
        find_action(
            state,
            action_id="btnEntrar",
            text_contains=(
                "Presentación sin Cl@ve"
            ),
        )
    )

    procedure_info_rect = (
        procedure_info_action.get(
            "rect"
        )
        or {}
    )

    if not procedure_info_rect.get(
        "visible"
    ):
        raise RuntimeError(
            "PROCEDURE_INFO_ACTION_MOVED_OUT_OF_VIEW"
        )

    print(
        "PROCEDURE_INFO_GEOMETRY_REFRESH = OK"
    )

    print(
        "PROCEDURE_INFO_ACTION_SCREEN_CENTER =",
        (
            procedure_info_rect.get(
                "screenCenterX"
            ),
            procedure_info_rect.get(
                "screenCenterY"
            ),
        ),
    )

    before = (
        BUS.current_seq()
    )

    print(
        "PROCEDURE_INFO_ENTER = LIVE DOM"
    )

    click_action(
        state,
        action_id="btnEntrar",
        text_contains=(
            "Presentación sin Cl@ve"
        ),
    )

    seq, state = (
        wait_semantic(
            "IDENTITY_FORM",
            after_seq=before,
            timeout=20,
        )
    )


    # --------------------------------------------------------
    # IDENTITY
    # --------------------------------------------------------

    print()
    print(
        "STAGE = IDENTITY_FORM"
    )

    # --------------------------------------------------------
    # Los campos de identidad se verifican igual que contacto.
    #
    # Esto es especialmente importante para NAME porque Chrome
    # puede mostrar un popup de historial/autocomplete después
    # de escribir. Ese popup es UI nativa del navegador y puede
    # interceptar el siguiente click físico destinado al select
    # de nacionalidad.
    # --------------------------------------------------------

    state = fill_text_verified(
        state,
        control_key="identityNie",
        value=nie,
        description="NIE",
        expected_page="IDENTITY_FORM",
    )

    state = fill_text_verified(
        state,
        control_key="identityName",
        value=nombre,
        description="NAME",
        expected_page="IDENTITY_FORM",
    )

    print(
        "IDENTITY_AUTOCOMPLETE_BARRIER = ESC"
    )

    keyboard.press_and_release(
        "esc"
    )

    time.sleep(
        0.35
    )

    # El estado devuelto por fill_text_verified es posterior
    # a la escritura/verificación del nombre. La geometría del
    # select pertenece por tanto al DOM vivo de esta pantalla,
    # no al snapshot inicial.
    controls = (
        state.get(
            "navigationControls"
        )
        or {}
    )

    nationality_control = (
        controls.get(
            "nationality"
        )
        or {}
    )

    if not nationality_control:
        raise RuntimeError(
            "NATIONALITY_CONTROL_NOT_FOUND"
        )

    # --------------------------------------------------------
    # Resolver primero la opción esperada desde el DOM.
    #
    # No confiamos únicamente en que select_option() haya
    # enviado HOME/DOWN/ENTER correctamente: después
    # verificaremos el valor REAL observado por el Observer.
    # --------------------------------------------------------

    expected_nationality_option = (
        find_option(
            nationality_control,
            text=nacionalidad,
        )
    )

    expected_nationality_value = str(
        expected_nationality_option.get(
            "value"
        )
        or ""
    )

    if not expected_nationality_value:
        raise RuntimeError(
            "NATIONALITY_EXPECTED_VALUE_MISSING"
        )

    before_nationality = (
        BUS.current_seq()
    )

    select_option(
        nationality_control,
        text=nacionalidad,
        description="NATIONALITY",
    )


    # --------------------------------------------------------
    # Verificación REAL de la selección.
    # --------------------------------------------------------

    seq, state = (
        wait_semantic(
            "IDENTITY_FORM",
            after_seq=before_nationality,
            timeout=5,
        )
    )

    nationality_control = (
        state.get(
            "navigationControls",
            {}
        ).get(
            "nationality"
        )
        or {}
    )

    actual_nationality_value = str(
        nationality_control.get(
            "selectedValue"
        )
        or ""
    )

    print(
        "NATIONALITY_SELECTION_CHECK =",
        (
            "MATCH"
            if actual_nationality_value
            == expected_nationality_value
            else "MISMATCH"
        ),
    )


    # --------------------------------------------------------
    # Un único recovery local.
    #
    # No repite navegación ni petición al portal:
    # ESC -> DOM fresco -> volver a seleccionar -> verificar.
    # --------------------------------------------------------

    if (
        actual_nationality_value
        != expected_nationality_value
    ):

        print(
            "NATIONALITY_SELECTION_RETRY = 1"
        )

        keyboard.press_and_release(
            "esc"
        )

        time.sleep(
            0.35
        )

        refresh_baseline = (
            BUS.current_seq()
        )

        seq, state = (
            wait_semantic(
                "IDENTITY_FORM",
                after_seq=refresh_baseline,
                timeout=5,
            )
        )

        controls = (
            state.get(
                "navigationControls"
            )
            or {}
        )

        nationality_control = (
            controls.get(
                "nationality"
            )
            or {}
        )

        if not nationality_control:
            raise RuntimeError(
                "NATIONALITY_CONTROL_NOT_FOUND_RETRY"
            )

        # Volvemos a resolver la opción contra el DOM fresco.
        expected_nationality_option = (
            find_option(
                nationality_control,
                text=nacionalidad,
            )
        )

        expected_nationality_value = str(
            expected_nationality_option.get(
                "value"
            )
            or ""
        )

        retry_baseline = (
            BUS.current_seq()
        )

        select_option(
            nationality_control,
            text=nacionalidad,
            description="NATIONALITY",
        )

        seq, state = (
            wait_semantic(
                "IDENTITY_FORM",
                after_seq=retry_baseline,
                timeout=5,
            )
        )

        nationality_control = (
            state.get(
                "navigationControls",
                {}
            ).get(
                "nationality"
            )
            or {}
        )

        actual_nationality_value = str(
            nationality_control.get(
                "selectedValue"
            )
            or ""
        )


    if (
        actual_nationality_value
        != expected_nationality_value
    ):
        raise RuntimeError(
            "NATIONALITY_SELECTION_NOT_CONFIRMED"
        )


    print(
        "NATIONALITY_SELECTION_VERIFIED = OK"
    )

    print(
        "IDENTITY_AFTER_NATIONALITY_REFRESH = OK"
    )


    before = (
        BUS.current_seq()
    )

    print(
        "IDENTITY_ACCEPT = LIVE DOM"
    )

    click_action(
        state,
        action_id="btnEnviar",
        text_contains="Aceptar",
    )


    seq, state = (
        wait_semantic(
            "IDENTITY_VALIDATED",
            after_seq=before,
            timeout=20,
        )
    )


    # --------------------------------------------------------
    # SOLICITAR CITA
    # --------------------------------------------------------

    print()
    print(
        "STAGE = IDENTITY_VALIDATED"
    )


    # --------------------------------------------------------
    # Obtener una geometría fresca de esta pantalla antes
    # de localizar físicamente "Solicitar Cita".
    # --------------------------------------------------------

    before_refresh = (
        BUS.current_seq()
    )

    seq, state = (
        wait_semantic(
            "IDENTITY_VALIDATED",
            after_seq=before_refresh,
            timeout=5,
        )
    )

    print(
        "IDENTITY_VALIDATED_REFRESH = OK"
    )

    before = (
        BUS.current_seq()
    )

    print(
        "REQUEST_APPOINTMENT = LIVE DOM"
    )

    click_action(
        state,
        text_contains="Solicitar Cita",
    )


    seq, state = (
        wait_semantic(
            "OFFICE_SELECTION",
            after_seq=before,
            timeout=20,
        )
    )


    # --------------------------------------------------------
    # OFFICE
    # --------------------------------------------------------

    print()
    print(
        "STAGE = OFFICE_SELECTION"
    )

    controls = (
        state[
            "navigationControls"
        ]
    )

    expected_office_value = str(
        office[
            "provider_value"
        ]
    )

    print(
        "OFFICE_SELECTOR = LIVE DOM"
    )

    select_option(
        controls[
            "procedureOffice"
        ],
        value=expected_office_value,
        description="PROCEDURE_OFFICE",
    )


    # --------------------------------------------------------
    # IMPORTANTE:
    # select_option() indica qué opción intentó seleccionar.
    # Ahora comprobamos el valor REAL observado en el DOM.
    # --------------------------------------------------------

    after_office_select = (
        BUS.current_seq()
    )

    seq, state = (
        wait_semantic(
            "OFFICE_SELECTION",
            after_seq=after_office_select,
            timeout=5,
        )
    )

    office_control = (
        state.get(
            "navigationControls",
            {}
        ).get(
            "procedureOffice"
        )
        or {}
    )

    actual_office_value = str(
        office_control.get(
            "selectedValue"
        )
        or ""
    )

    actual_office_text = (
        office_control.get(
            "selectedText"
        )
    )

    print(
        "OFFICE_EXPECTED_VALUE =",
        expected_office_value,
    )

    print(
        "OFFICE_ACTUAL_VALUE =",
        actual_office_value,
    )

    print(
        "OFFICE_ACTUAL_TEXT =",
        actual_office_text,
    )


    # --------------------------------------------------------
    # Un único retry si la selección física no quedó aplicada.
    # --------------------------------------------------------

    if (
        actual_office_value
        != expected_office_value
    ):

        print(
            "OFFICE_SELECTION_RETRY = 1"
        )

        controls = (
            state[
                "navigationControls"
            ]
        )

        select_option(
            controls[
                "procedureOffice"
            ],
            value=expected_office_value,
            description="PROCEDURE_OFFICE",
        )

        after_retry = (
            BUS.current_seq()
        )

        seq, state = (
            wait_semantic(
                "OFFICE_SELECTION",
                after_seq=after_retry,
                timeout=5,
            )
        )

        office_control = (
            state.get(
                "navigationControls",
                {}
            ).get(
                "procedureOffice"
            )
            or {}
        )

        actual_office_value = str(
            office_control.get(
                "selectedValue"
            )
            or ""
        )

        actual_office_text = (
            office_control.get(
                "selectedText"
            )
        )

        print(
            "OFFICE_RETRY_VALUE =",
            actual_office_value,
        )

        print(
            "OFFICE_RETRY_TEXT =",
            actual_office_text,
        )


    if (
        actual_office_value
        != expected_office_value
    ):
        raise RuntimeError(
            "OFFICE_SELECTION_NOT_CONFIRMED:"
            f"expected={expected_office_value}:"
            f"actual={actual_office_value}"
        )


    print(
        "OFFICE_SELECTION_VERIFIED = OK"
    )


    # --------------------------------------------------------
    # SIGUIENTE · DOM vivo
    # --------------------------------------------------------

    before = (
        BUS.current_seq()
    )

    print(
        "OFFICE_NEXT = LIVE DOM"
    )

    click_action(
        state,
        action_id="btnSiguiente",
        text_contains="Siguiente",
    )

    seq, state = (
        wait_semantic(
            "CONTACT_FORM",
            after_seq=before,
            timeout=20,
        )
    )


    # --------------------------------------------------------
    # CONTACT
    # --------------------------------------------------------

    print()
    print(
        "STAGE = CONTACT_FORM"
    )

    controls = (
        state[
            "navigationControls"
        ]
    )


    print(
        "CONTACT_FIELDS = LIVE DOM"
    )

    state = fill_text_verified(
        state,
        control_key="phone",
        value=telefono,
        description="PHONE",
        expected_page="CONTACT_FORM",
    )

    state = fill_text_verified(
        state,
        control_key="email",
        value=email,
        description="EMAIL",
        expected_page="CONTACT_FORM",
    )

    state = fill_text_verified_by_tab(
        state,
        source_control_key="email",
        target_control_key="emailRepeat",
        value=email,
        description="EMAIL_REPEAT",
        expected_page="CONTACT_FORM",
    )


    # --------------------------------------------------------
    # Contrato final:
    # los tres valores deben seguir presentes simultáneamente
    # antes de permitir pulsar Siguiente.
    # --------------------------------------------------------

    verified_controls = (
        state.get(
            "navigationControls"
        )
        or {}
    )

    expected_contact_values = {
        "phone": telefono,
        "email": email,
        "emailRepeat": email,
    }

    for (
        control_key,
        expected_value,
    ) in expected_contact_values.items():

        control = (
            verified_controls.get(
                control_key
            )
            or {}
        )

        if not observer_control_matches_value(
            control,
            str(
                expected_value
            ).strip(),
        ):
            raise RuntimeError(
                "CONTACT_FINAL_VALUE_MISMATCH:"
                f"{control_key}"
            )

    print(
        "CONTACT_FIELDS_VERIFIED = OK"
    )


    # --------------------------------------------------------
    # Refrescar geometría antes del Siguiente final.
    # --------------------------------------------------------

    after_contact = (
        BUS.current_seq()
    )

    seq, state = (
        wait_semantic(
            "CONTACT_FORM",
            after_seq=after_contact,
            timeout=5,
        )
    )

    print(
        "CONTACT_REFRESH = OK"
    )

    before = (
        BUS.current_seq()
    )

    print(
        "CONTACT_NEXT = LIVE DOM"
    )

    click_action(
        state,
        action_id="btnSiguiente",
        text_contains="Siguiente",
    )


    # --------------------------------------------------------
    # RESULT
    # --------------------------------------------------------

    result_seq, result = BUS.wait(
        lambda payload:
            (
                (
                    payload.get(
                        "eventType"
                    )
                    == "DOM_STATE"
                    and
                    payload.get(
                        "page"
                    )
                    in {
                        "OFFER_APPOINTMENT",
                        "REQUEST_REJECTED",
                    }
                )
                or
                payload.get(
                    "portalStatus"
                )
                in {
                    "BLOCKED",
                    "DOWN",
                    "DEGRADED",
                }
            ),
        after_seq=before,
        timeout=30,
        raise_on_portal_status=False,
    )


    print()
    print(
        "=============================================="
    )
    print(
        " ICP-DESKTOP-5C-GOVERNED · RESULT"
    )
    print(
        "=============================================="
    )

    portal_status = (
        result.get(
            "portalStatus"
        )
        or "UNKNOWN"
    )

    availability_status = (
        result.get(
            "availabilityStatus"
        )
        or "UNKNOWN"
    )

    appointments = (
        result.get(
            "appointments"
        )
        or []
    )

    appointment_count = (
        result.get(
            "appointmentCount"
        )
    )

    if appointment_count is None:
        appointment_count = len(
            appointments
        )

    print(
        "PAGE =",
        result.get(
            "page"
        ),
    )

    print(
        "PORTAL_STATUS =",
        portal_status,
    )

    print(
        "AVAILABILITY_STATUS =",
        availability_status,
    )

    print(
        "SUPPORT_ID =",
        result.get(
            "supportId"
        ),
    )

    print(
        "NAVIGATION_ERROR =",
        result.get(
            "navigationError"
        ),
    )

    print(
        "APPOINTMENT_COUNT =",
        appointment_count,
    )

    print()

    for item in appointments:
        print(
            " -",
            item.get("date"),
            item.get("time"),
        )


    print()
    if portal_status == "BLOCKED":

        print(
            "RESULT_CLASS = PORTAL_BLOCKED"
        )

        print(
            "No retry."
        )

        print(
            "No security-control bypass."
        )

    elif portal_status in {
        "DOWN",
        "DEGRADED",
    }:

        print(
            "RESULT_CLASS = PORTAL_"
            + portal_status
        )

    elif availability_status == "AVAILABLE":

        print(
            "RESULT_CLASS = AVAILABLE"
        )

    elif availability_status == "UNAVAILABLE":

        print(
            "RESULT_CLASS = UNAVAILABLE"
        )

    else:

        print(
            "RESULT_CLASS = UNKNOWN"
        )

    print()

    print(
        "STOP BEFORE CAPTCHA / RESERVATION"
    )

    print(
        "NO appointment selected."
    )

    print(
        "NO CAPTCHA interaction."
    )


except Exception as exc:

    print()
    print(
        "=============================================="
    )
    print(
        " ICP-DESKTOP-5C-GOVERNED · ERROR"
    )
    print(
        "=============================================="
    )

    print(
        type(exc).__name__,
        "=",
        exc,
    )

    raise


finally:

    try:

        close_owned_chrome(
            CHROME_HWND
        )

    finally:

        server.shutdown()
        server.server_close()
