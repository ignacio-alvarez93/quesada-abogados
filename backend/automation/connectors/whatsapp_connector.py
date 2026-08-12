"""
Conector base de WhatsApp Web.

Responsabilidades V1:
- resolver perfil Chrome persistente;
- abrir WhatsApp Web;
- identificar de forma conservadora si la sesión:
  * necesita autenticación;
  * está lista;
  * todavía está cargando;
- mantener el navegador bajo control del proceso externo.

No importa conversaciones todavía.
No envía mensajes todavía.
No contiene persistencia de negocio.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import time
import unicodedata

import mycdp.input_ as cdp_input

from backend.automation.browser_actions import (
    open_url,
)
from backend.automation.browser_session import (
    get_project_root,
    start_seleniumbase_chrome,
)
from backend.communications.phone_normalization import (
    normalize_phone,
)


WHATSAPP_WEB_URL = (
    "https://web.whatsapp.com/"
)

SESSION_STATUS_NEEDS_LOGIN = (
    "NEEDS_LOGIN"
)

SESSION_STATUS_READY = (
    "READY"
)

SESSION_STATUS_LOADING = (
    "LOADING"
)

SESSION_STATUS_UNKNOWN = (
    "UNKNOWN"
)

CHAT_KIND_INDIVIDUAL = (
    "INDIVIDUAL"
)

CHAT_KIND_GROUP = (
    "GROUP"
)

CHAT_KIND_SELF = (
    "SELF"
)

CHAT_KIND_UNKNOWN = (
    "UNKNOWN"
)

MESSAGE_DIRECTION_INBOUND = (
    "INBOUND"
)

MESSAGE_DIRECTION_OUTBOUND = (
    "OUTBOUND"
)

MESSAGE_DIRECTION_UNKNOWN = (
    "UNKNOWN"
)

MESSAGE_TYPE_TEXT = (
    "TEXT"
)

MESSAGE_TYPE_STICKER = (
    "STICKER"
)

MESSAGE_TYPE_UNKNOWN_MEDIA = (
    "UNKNOWN_MEDIA"
)

MESSAGE_STATUS_RECEIVED = (
    "RECEIVED"
)

MESSAGE_STATUS_SENT = (
    "SENT"
)

MESSAGE_STATUS_DELIVERED = (
    "DELIVERED"
)

MESSAGE_STATUS_READ = (
    "READ"
)

MESSAGE_STATUS_UNKNOWN = (
    "UNKNOWN"
)


class WhatsAppSendStateUncertainError(
    RuntimeError
):
    """El envío pudo ejecutarse pero no pudo confirmarse."""


MESSAGE_COMPOSER_SELECTOR = (
    '[data-testid="conversation-compose-box-input"]'
)

MESSAGE_SEND_ARIA_LABEL = (
    "Enviar"
)

MESSAGE_SEND_SELECTOR = (
    '#main footer '
    'button[aria-label="Enviar"]'
)


@dataclass(frozen=True)
class WhatsAppMessageSnapshot:
    """Mensaje visible normalizado desde WhatsApp Web."""

    provider_message_id: str
    direction: str
    body_text: str
    provider_timestamp: str | None
    message_type: str
    provider_status: str
    sender: str | None = None
    metadata: dict | None = None


@dataclass(frozen=True)
class WhatsAppChatSnapshot:
    """Vista ligera de una conversación presente en la lista de WhatsApp."""

    position: int
    display_name: str
    primary_detail: str = ""
    preview: str = ""
    unread_count: int = 0
    virtual_offset: int | None = None


_PHONE_PATTERN = re.compile(
    r"\+[0-9][0-9 ()-]{7,}"
)

_PRE_PLAIN_PATTERN = re.compile(
    r"^\["
    r"(?P<time>\d{1,2}:\d{2})"
    r",\s*"
    r"(?P<date>\d{1,2}/\d{1,2}/\d{4})"
    r"\]\s*"
    r"(?P<sender>.*?)"
    r":\s*$"
)


def parse_whatsapp_pre_plain_text(
    value,
):
    """Normaliza fecha/hora y remitente de data-pre-plain-text."""
    raw = str(
        value
        or ""
    ).strip()

    if not raw:
        return {
            "provider_timestamp": None,
            "sender": None,
            "date": None,
            "time": None,
        }

    match = _PRE_PLAIN_PATTERN.match(
        raw
    )

    if not match:
        return {
            "provider_timestamp": None,
            "sender": None,
            "date": None,
            "time": None,
        }

    raw_time = match.group(
        "time"
    )

    raw_date = match.group(
        "date"
    )

    sender = (
        match.group(
            "sender"
        ).strip()
        or None
    )

    try:
        parsed = datetime.strptime(
            f"{raw_date} {raw_time}",
            "%d/%m/%Y %H:%M",
        )

        provider_timestamp = (
            parsed.isoformat(
                timespec="seconds"
            )
        )
    except ValueError:
        provider_timestamp = None

    return {
        "provider_timestamp":
            provider_timestamp,
        "sender":
            sender,
        "date":
            raw_date,
        "time":
            raw_time,
    }


def normalize_chat_identity(
    value,
):
    """Normaliza un nombre visible para comparar identidad de conversación."""
    text = unicodedata.normalize(
        "NFKC",
        str(value or ""),
    )

    cleaned = []

    for char in text:
        category = (
            unicodedata.category(
                char
            )
        )

        if char in (
            "\ufe0e",
            "\ufe0f",
        ):
            continue

        if category.startswith(
            "S"
        ):
            continue

        if category.startswith(
            "C"
        ):
            continue

        cleaned.append(
            char
        )

    return " ".join(
        "".join(
            cleaned
        ).split()
    ).casefold()


def extract_phone_from_profile_text(
    value,
):
    """Extrae el primer teléfono internacional visible en Info. del contacto."""
    text = str(value or "")

    match = _PHONE_PATTERN.search(
        text
    )

    if not match:
        return None

    return (
        match.group(0)
        .strip()
    )


def get_whatsapp_profile_dir(
    profile_key="whatsapp_dev",
):
    clean_key = (
        str(profile_key or "")
        .strip()
        .replace("\\", "_")
        .replace("/", "_")
    )

    if not clean_key:
        raise ValueError(
            "profile_key de WhatsApp vacío"
        )

    profile_dir = (
        get_project_root()
        / "data"
        / "browser_profiles"
        / clean_key
    )

    profile_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return profile_dir


class WhatsAppConnector:
    def __init__(
        self,
        *,
        profile_key="whatsapp_dev",
        headless=False,
    ):
        self.profile_key = str(
            profile_key
            or "whatsapp_dev"
        ).strip()

        self.profile_dir = (
            get_whatsapp_profile_dir(
                self.profile_key
            )
        )

        self.headless = bool(
            headless
        )

        self.browser = None

    def start(self):
        self.browser = (
            start_seleniumbase_chrome(
                headless=self.headless,
                user_data_dir=(
                    self.profile_dir
                ),
            )
        )

        open_url(
            self.browser,
            WHATSAPP_WEB_URL,
        )

        return self.browser

    def _page_text(self):
        if not self.browser:
            return ""

        try:
            return str(
                self.browser.get_text("body")
                or ""
            )
        except Exception:
            return ""

    def detect_session_status(self):
        if not self.browser:
            return SESSION_STATUS_UNKNOWN

        text = (
            self._page_text()
            .strip()
            .lower()
        )

        if not text:
            return SESSION_STATUS_LOADING

        login_markers = (
            "link with phone number",
            "use whatsapp on your computer",
            "scan this qr code",
            "vincular con el número de teléfono",
            "usar whatsapp en tu ordenador",
            "escanea el código qr",
        )

        if any(
            marker in text
            for marker in login_markers
        ):
            return SESSION_STATUS_NEEDS_LOGIN

        ready_markers = (
            "search or start new chat",
            "buscar un chat o iniciar uno nuevo",
            "search",
            "buscar",
        )

        if any(
            marker in text
            for marker in ready_markers
        ):
            return SESSION_STATUS_READY

        return SESSION_STATUS_UNKNOWN

    def dismiss_known_overlays(self):
        """Cierra únicamente overlays de WhatsApp expresamente conocidos.

        Los diálogos desconocidos nunca se cierran automáticamente.
        """
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        dialogs = self.browser.evaluate(
            """
            (() => (
                Array.from(
                    document.querySelectorAll(
                        '[role="dialog"]'
                    )
                )
                .map((dialog) => ({
                    text:
                        (dialog.innerText || "")
                        .trim()
                }))
            ))()
            """
        ) or []

        known_closed = 0
        unknown = []

        for dialog in dialogs:
            dialog_text = str(
                dialog.get("text")
                or ""
            )

            lowered = (
                dialog_text
                .lower()
            )

            if (
                "novedades en whatsapp web"
                in lowered
            ):
                element = (
                    self.browser
                    .find_element(
                        '[role="dialog"] '
                        'button[aria-label="Cerrar"]'
                    )
                )

                mouse_click = getattr(
                    element,
                    "mouse_click",
                    None,
                )

                if callable(mouse_click):
                    mouse_click()
                else:
                    element.click()

                known_closed += 1
                time.sleep(1)

            else:
                unknown.append(
                    dialog_text[:500]
                )

        return {
            "known_closed":
                known_closed,
            "unknown_dialogs":
                unknown,
            "blocked":
                bool(unknown),
        }

    def prepare_chat_interface(self):
        """Prepara de forma conservadora la interfaz antes de operar con chats."""
        if (
            self.detect_session_status()
            != SESSION_STATUS_READY
        ):
            raise RuntimeError(
                "WhatsApp Web no está READY"
            )

        overlay_result = (
            self.dismiss_known_overlays()
        )

        if overlay_result["blocked"]:
            return {
                "ready": False,
                "reason": (
                    "UNKNOWN_DIALOG"
                ),
                "overlay_result":
                    overlay_result,
            }

        info = self.browser.evaluate(
            """
            (() => {
                const grid =
                    document.querySelector(
                        '[aria-label="Lista de chats"]'
                    );

                if (!grid) {
                    return {
                        found: false,
                        total_rows: 0,
                        visible_rows: 0
                    };
                }

                return {
                    found: true,
                    total_rows:
                        Number(
                            grid.getAttribute(
                                'aria-rowcount'
                            )
                            || 0
                        ),
                    visible_rows:
                        grid.querySelectorAll(
                            '[role="row"]'
                        ).length
                };
            })()
            """
        )

        return {
            "ready":
                bool(
                    info
                    and info.get("found")
                ),
            "reason":
                None,
            "overlay_result":
                overlay_result,
            "chat_list":
                info or {},
        }

    def list_visible_chat_snapshots(
        self,
        *,
        viewport_only=False,
    ):
        """Lee filas materializadas, opcionalmente solo las presentes en viewport."""
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        rows = self.browser.evaluate(
            """
            (() => {
                const grid =
                    document.querySelector(
                        '[aria-label="Lista de chats"]'
                    );

                if (!grid) {
                    return [];
                }

                let scroll = grid;

                while (
                    scroll
                    && scroll !== document.body
                    && !(
                        scroll.scrollHeight
                        > scroll.clientHeight
                    )
                ) {
                    scroll =
                        scroll.parentElement;
                }

                const scrollRect =
                    scroll
                    ? scroll.getBoundingClientRect()
                    : null;

                return Array.from(
                    grid.querySelectorAll(
                        '[role="row"]'
                    )
                )
                .map((row) => {
                    const rowTestId =
                        row.getAttribute(
                            'data-testid'
                        ) || "";

                    const positionMatch =
                        rowTestId.match(
                            /^list-item-(\\d+)$/
                        );

                    if (!positionMatch) {
                        return null;
                    }

                    const titleContainer =
                        row.querySelector(
                            '[data-testid="cell-frame-title"]'
                        );

                    const titleElement =
                        titleContainer
                        ? titleContainer.querySelector(
                            '[title]'
                        )
                        : null;

                    const primary =
                        row.querySelector(
                            '[data-testid="cell-frame-primary-detail"]'
                        );

                    const secondary =
                        row.querySelector(
                            '[data-testid="cell-frame-secondary"]'
                        );

                    const unread =
                        row.querySelector(
                            '[data-testid="icon-unread-count"]'
                        );

                    const unreadLabel =
                        unread
                        ? (
                            unread.getAttribute(
                                'aria-label'
                            )
                            || unread.innerText
                            || ""
                        )
                        : "";

                    const unreadMatch =
                        unreadLabel.match(
                            /\\d+/
                        );

                    const displayName =
                        titleElement
                        ? (
                            titleElement.getAttribute(
                                'title'
                            )
                            || titleElement.innerText
                            || ""
                        ).trim()
                        : (
                            titleContainer
                            ? (
                                titleContainer.innerText
                                || ""
                            ).trim()
                            : ""
                        );

                    const style =
                        row.getAttribute(
                            'style'
                        ) || "";

                    const transformMatch =
                        style.match(
                            /translateY\\(([-0-9.]+)px\\)/
                        );

                    const rowRect =
                        row.getBoundingClientRect();

                    const inViewport =
                        Boolean(
                            scrollRect
                            && rowRect.bottom
                                > scrollRect.top
                            && rowRect.top
                                < scrollRect.bottom
                        );

                    return {
                        position:
                            Number(
                                positionMatch[1]
                            ),

                        in_viewport:
                            inViewport,

                        virtual_offset:
                            transformMatch
                            ? Math.round(
                                Number(
                                    transformMatch[1]
                                )
                            )
                            : null,

                        display_name:
                            displayName,

                        primary_detail:
                            primary
                            ? (
                                primary.innerText
                                || ""
                            ).trim()
                            : "",

                        preview:
                            secondary
                            ? (
                                secondary.innerText
                                || ""
                            ).trim()
                            : "",

                        unread_count:
                            unreadMatch
                            ? Number(
                                unreadMatch[0]
                            )
                            : 0
                    };
                })
                .filter(Boolean);
            })()
            """
        ) or []

        snapshots = []

        for row in rows:
            if (
                viewport_only
                and not row.get(
                    "in_viewport"
                )
            ):
                continue

            display_name = str(
                row.get(
                    "display_name"
                )
                or ""
            ).strip()

            if not display_name:
                continue

            snapshots.append(
                WhatsAppChatSnapshot(
                    position=int(
                        row.get(
                            "position"
                        )
                        or 0
                    ),
                    display_name=(
                        display_name
                    ),
                    primary_detail=str(
                        row.get(
                            "primary_detail"
                        )
                        or ""
                    ).strip(),
                    preview=str(
                        row.get(
                            "preview"
                        )
                        or ""
                    ).strip(),
                    unread_count=max(
                        0,
                        int(
                            row.get(
                                "unread_count"
                            )
                            or 0
                        ),
                    ),
                    virtual_offset=(
                        int(
                            row[
                                "virtual_offset"
                            ]
                        )
                        if row.get(
                            "virtual_offset"
                        )
                        is not None
                        else None
                    ),
                )
            )

        return snapshots

    def scroll_chat_list_to_ratio(
        self,
        ratio,
    ):
        """Desplaza la lista virtual de chats a una proporción 0..1."""
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        ratio = min(
            1.0,
            max(
                0.0,
                float(ratio),
            ),
        )

        return (
            self.browser.evaluate(
                f"""
                (() => {{
                    const grid =
                        document.querySelector(
                            '[aria-label="Lista de chats"]'
                        );

                    if (!grid) {{
                        return {{
                            moved: false,
                            reason:
                                'CHAT_LIST_NOT_FOUND'
                        }};
                    }}

                    let scroll = grid;

                    while (
                        scroll
                        && scroll !== document.body
                        && !(
                            scroll.scrollHeight
                            > scroll.clientHeight
                        )
                    ) {{
                        scroll =
                            scroll.parentElement;
                    }}

                    if (!scroll) {{
                        return {{
                            moved: false,
                            reason:
                                'SCROLL_CONTAINER_NOT_FOUND'
                        }};
                    }}

                    const maxScroll =
                        Math.max(
                            0,
                            scroll.scrollHeight
                            - scroll.clientHeight
                        );

                    scroll.scrollTop =
                        maxScroll * {ratio};

                    return {{
                        moved: true,
                        ratio:
                            {ratio},
                        scroll_top:
                            scroll.scrollTop,
                        max_scroll:
                            maxScroll
                    }};
                }})()
                """
            )
            or {}
        )

    def open_chat_by_phone(
        self,
        phone,
        *,
        timeout=15,
    ):
        """Abre y verifica un chat individual por teléfono.

        Un compositor visible no basta para considerar
        correcta la navegación. La identidad final se
        verifica leyendo el teléfono observable desde
        Info. del contacto.

        Si la identidad no puede verificarse, nunca
        devuelve verified=True.
        """
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        expected = normalize_phone(
            phone
        )

        if not expected.valid:
            raise ValueError(
                "Teléfono WhatsApp no válido"
            )

        target_url = (
            "https://web.whatsapp.com/"
            "send?phone="
            + expected.digits
        )

        open_url(
            self.browser,
            target_url,
        )

        deadline = (
            time.time()
            + max(
                1,
                int(timeout),
            )
        )

        composer_found = False

        while time.time() < deadline:
            composer_found = bool(
                self.browser.evaluate(
                    """
                    (() => Boolean(
                        document.querySelector(
                            '[data-testid="conversation-compose-box-input"]'
                        )
                    ))()
                    """
                )
            )

            if composer_found:
                break

            time.sleep(0.25)

        if not composer_found:
            return {
                "opened": False,
                "verified": False,
                "reason":
                    "COMPOSER_NOT_FOUND",
                "expected_phone":
                    expected.e164,
                "observed_phone":
                    None,
            }

        profile_open = (
            self.open_contact_profile(
                timeout=min(
                    10,
                    max(
                        1,
                        int(timeout),
                    ),
                )
            )
        )

        if not profile_open:
            return {
                "opened": True,
                "verified": False,
                "reason":
                    "PROFILE_OPEN_FAILED",
                "expected_phone":
                    expected.e164,
                "observed_phone":
                    None,
            }

        try:
            classification = (
                self.classify_open_profile()
            )

            kind = classification.get(
                "kind",
                CHAT_KIND_UNKNOWN,
            )

            if (
                kind
                != CHAT_KIND_INDIVIDUAL
            ):
                return {
                    "opened": True,
                    "verified": False,
                    "reason":
                        "NOT_INDIVIDUAL_CHAT",
                    "kind":
                        kind,
                    "expected_phone":
                        expected.e164,
                    "observed_phone":
                        None,
                }

            observed_raw = (
                self.get_open_contact_phone()
            )

            observed = normalize_phone(
                observed_raw
            )

            if not observed.valid:
                return {
                    "opened": True,
                    "verified": False,
                    "reason":
                        "PHONE_UNVERIFIABLE",
                    "kind":
                        kind,
                    "expected_phone":
                        expected.e164,
                    "observed_phone":
                        observed_raw,
                }

            verified = (
                observed.digits
                == expected.digits
            )

            return {
                "opened": True,
                "verified":
                    verified,
                "reason":
                    (
                        None
                        if verified
                        else
                        "PHONE_MISMATCH"
                    ),
                "kind":
                    kind,
                "expected_phone":
                    expected.e164,
                "observed_phone":
                    observed.e164,
            }

        finally:
            self.close_contact_profile(
                timeout=5,
            )

    def open_chat_by_virtual_offset(
        self,
        virtual_offset,
        *,
        expected_display_name=None,
        timeout=10,
    ):
        """Centra y abre una fila virtual identificada por su translateY."""
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        target_offset = int(
            virtual_offset
        )

        centered = (
            self.browser.evaluate(
                f"""
                (() => {{
                    const rows =
                        Array.from(
                            document.querySelectorAll(
                                '[data-testid^="list-item-"]'
                            )
                        );

                    for (const row of rows) {{
                        const style =
                            row.getAttribute(
                                'style'
                            ) || '';

                        const transformMatch =
                            style.match(
                                /translateY\\(([-0-9.]+)px\\)/
                            );

                        if (!transformMatch) {{
                            continue;
                        }}

                        const offset =
                            Math.round(
                                Number(
                                    transformMatch[1]
                                )
                            );

                        if (
                            offset !==
                            {target_offset}
                        ) {{
                            continue;
                        }}

                        row.scrollIntoView({{
                            block: 'center',
                            inline: 'nearest'
                        }});

                        return true;
                    }}

                    return false;
                }})()
                """
            )
        )

        if not centered:
            return {
                "opened": False,
                "reason":
                    "VIRTUAL_ROW_NOT_MATERIALIZED",
                "virtual_offset":
                    target_offset,
            }

        time.sleep(0.35)

        position = (
            self.browser.evaluate(
                f"""
                (() => {{
                    const rows =
                        Array.from(
                            document.querySelectorAll(
                                '[data-testid^="list-item-"]'
                            )
                        );

                    for (const row of rows) {{
                        const style =
                            row.getAttribute(
                                'style'
                            ) || '';

                        const transformMatch =
                            style.match(
                                /translateY\\(([-0-9.]+)px\\)/
                            );

                        if (!transformMatch) {{
                            continue;
                        }}

                        const offset =
                            Math.round(
                                Number(
                                    transformMatch[1]
                                )
                            );

                        if (
                            offset !==
                            {target_offset}
                        ) {{
                            continue;
                        }}

                        const testid =
                            row.getAttribute(
                                'data-testid'
                            ) || '';

                        const positionMatch =
                            testid.match(
                                /^list-item-(\\d+)$/
                            );

                        return positionMatch
                            ? Number(
                                positionMatch[1]
                            )
                            : null;
                    }}

                    return null;
                }})()
                """
            )
        )

        if position is None:
            return {
                "opened": False,
                "reason":
                    "VIRTUAL_ROW_NOT_MATERIALIZED",
                "virtual_offset":
                    target_offset,
            }

        result = self.open_chat(
            int(position),
            expected_display_name=(
                expected_display_name
            ),
            timeout=timeout,
        )

        result[
            "virtual_offset"
        ] = target_offset

        result[
            "position"
        ] = int(position)

        return result

    def open_chat(
        self,
        position,
        *,
        expected_display_name=None,
        timeout=10,
    ):
        """Abre un chat y verifica que la conversación esperada quedó activa."""
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        position = int(
            position
        )

        expected_name = str(
            expected_display_name
            or ""
        ).strip()

        expected_identity = (
            normalize_chat_identity(
                expected_name
            )
        )

        selector = (
            f'[data-testid="list-item-{position}"] '
            '[role="gridcell"][tabindex="0"]'
        )

        element = (
            self.browser
            .find_element(
                selector
            )
        )

        mouse_click = getattr(
            element,
            "mouse_click",
            None,
        )

        if not callable(
            mouse_click
        ):
            raise RuntimeError(
                "El elemento de chat "
                "no soporta mouse_click()"
            )

        mouse_click()

        deadline = (
            time.time()
            + max(
                1,
                int(timeout),
            )
        )

        while (
            time.time()
            < deadline
        ):
            result = (
                self.browser.evaluate(
                    """
                    (() => {
                        const composer =
                            document.querySelector(
                                '[data-testid="conversation-compose-box-input"]'
                            );

                        const title =
                            document.querySelector(
                                '[data-testid="conversation-info-header-chat-title"]'
                            );

                        const activeName =
                            title
                            ? String(
                                title.innerText
                                || title.textContent
                                || ""
                            ).trim()
                            : "";

                        const main =
                            document.querySelector(
                                '#main'
                            );

                        const mainText =
                            main
                            ? String(
                                main.innerText
                                || main.textContent
                                || ""
                            ).trim()
                            : "";

                        if (!composer) {
                            return {
                                opened: false,
                                composer_found: false,
                                composer_aria_label: null,
                                active_display_name:
                                    activeName,
                                main_text:
                                    mainText
                            };
                        }

                        return {
                            opened: true,
                            composer_found: true,
                            composer_aria_label:
                                composer.getAttribute(
                                    'aria-label'
                                ),
                            active_display_name:
                                activeName,
                            main_text:
                                mainText
                        };
                    })()
                    """
                )
            )

            if (
                result
                and result.get(
                    "opened"
                )
            ):
                active_name = str(
                    result.get(
                        "active_display_name"
                    )
                    or ""
                ).strip()

                active_identity = (
                    normalize_chat_identity(
                        active_name
                    )
                )

                if not expected_name:
                    return result

                if (
                    active_name
                    == expected_name
                ):
                    return result

                if (
                    expected_identity
                    and active_identity
                    and (
                        active_identity
                        == expected_identity
                    )
                ):
                    return result

            time.sleep(0.25)

        return {
            "opened": False,
            "composer_found":
                (
                    bool(
                        result.get(
                            "composer_found"
                        )
                    )
                    if isinstance(
                        result,
                        dict,
                    )
                    else False
                ),
            "composer_aria_label":
                (
                    result.get(
                        "composer_aria_label"
                    )
                    if isinstance(
                        result,
                        dict,
                    )
                    else None
                ),
            "active_display_name":
                (
                    result.get(
                        "active_display_name"
                    )
                    if isinstance(
                        result,
                        dict,
                    )
                    else None
                ),
            "main_text":
                (
                    result.get(
                        "main_text"
                    )
                    if isinstance(
                        result,
                        dict,
                    )
                    else None
                ),
            "reason":
                (
                    "CHAT_IDENTITY_MISMATCH"
                    if expected_name
                    else "OPEN_TIMEOUT"
                ),
        }

    def open_contact_profile(
        self,
        *,
        expected_display_name=None,
        timeout=10,
    ):
        """Abre de forma fiable el perfil correspondiente al chat activo."""
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        expected_name = str(
            expected_display_name
            or ""
        ).strip()

        expected_identity = (
            normalize_chat_identity(
                expected_name
            )
        )

        def read_drawer_state():
            return (
                self.browser.evaluate(
                    """
                    (() => {
                        const drawer =
                            document.querySelector(
                                '[data-testid="drawer-right"]'
                            );

                        if (!drawer) {
                            return {
                                found: false,
                                has_content: false,
                                recognized: false,
                                header: null,
                                subject: null
                            };
                        }

                        const lines =
                            String(
                                drawer.innerText
                                || ""
                            )
                            .split('\\n')
                            .map(
                                value => value.trim()
                            )
                            .filter(Boolean);

                        const header =
                            lines.length >= 1
                            ? lines[0]
                            : "";

                        const subject =
                            lines.length >= 2
                            ? lines[1]
                            : "";

                        const lowered =
                            String(
                                header
                                || ""
                            )
                            .trim()
                            .toLowerCase();

                        const recognized =
                            (
                                lowered.startsWith(
                                    'info. del contacto'
                                )
                                || lowered.startsWith(
                                    'info. del grupo'
                                )
                            );

                        return {
                            found: true,
                            has_content:
                                lines.length > 0,
                            recognized:
                                recognized,
                            header:
                                header || null,
                            subject:
                                subject || null
                        };
                    })()
                    """
                )
                or {}
            )

        drawer_state = (
            read_drawer_state()
        )

        if (
            drawer_state.get(
                "recognized"
            )
        ):
            drawer_subject = str(
                drawer_state.get(
                    "subject"
                )
                or ""
            ).strip()

            drawer_identity = (
                normalize_chat_identity(
                    drawer_subject
                )
            )

            if not expected_name:
                return True

            if (
                drawer_subject
                == expected_name
            ):
                return True

            if (
                expected_identity
                and drawer_identity
                and (
                    drawer_identity
                    == expected_identity
                )
            ):
                return True

        if drawer_state.get(
            "has_content"
        ):
            closed = (
                self.close_contact_profile(
                    timeout=min(
                        3,
                        max(
                            1,
                            int(timeout),
                        ),
                    )
                )
            )

            if not closed:
                return False

        element = (
            self.browser
            .find_element(
                '[title="Información del perfil"]'
            )
        )

        mouse_click = getattr(
            element,
            "mouse_click",
            None,
        )

        if not callable(
            mouse_click
        ):
            raise RuntimeError(
                "Información del perfil "
                "no soporta mouse_click()"
            )

        mouse_click()

        deadline = (
            time.time()
            + max(
                1,
                int(timeout),
            )
        )

        while (
            time.time()
            < deadline
        ):
            state = (
                read_drawer_state()
            )

            if state.get(
                "recognized"
            ):
                return True

            time.sleep(
                0.25
            )

        return False

    def classify_open_profile(
        self,
    ):
        """Clasifica el drawer abierto como contacto, grupo o desconocido."""
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        drawer_text = (
            self.browser.evaluate(
                """
                (() => {
                    const drawer =
                        document.querySelector(
                            '[data-testid="drawer-right"]'
                        );

                    return drawer
                        ? (
                            drawer.innerText
                            || ""
                        ).trim()
                        : "";
                })()
                """
            )
            or ""
        )

        lowered = (
            str(drawer_text)
            .strip()
            .lower()
        )

        if not lowered:
            return {
                "kind": CHAT_KIND_UNKNOWN,
                "drawer_text": "",
            }

        if lowered.startswith(
            "info. del contacto"
        ):
            return {
                "kind":
                    CHAT_KIND_INDIVIDUAL,
                "drawer_text":
                    str(drawer_text),
            }

        if lowered.startswith(
            "info. del grupo"
        ):
            return {
                "kind":
                    CHAT_KIND_GROUP,
                "drawer_text":
                    str(drawer_text),
            }

        return {
            "kind":
                CHAT_KIND_UNKNOWN,
            "drawer_text":
                str(drawer_text),
        }

    def close_contact_profile(
        self,
        *,
        timeout=5,
    ):
        """Cierra el drawer derecho de información del contacto."""
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        drawer_found = (
            self.browser.evaluate(
                """
                (() => Boolean(
                    document.querySelector(
                        '[data-testid="drawer-right"]'
                    )
                ))()
                """
            )
        )

        if not drawer_found:
            return True

        close_button = None

        selectors = (
            '[data-testid="drawer-right"] '
            'button[aria-label="Cerrar"]',
            '[data-testid="drawer-right"] '
            '[aria-label="Cerrar"]',
        )

        for selector in selectors:
            try:
                close_button = (
                    self.browser
                    .find_element(
                        selector
                    )
                )

                if close_button:
                    break

            except Exception:
                continue

        if not close_button:
            return False

        mouse_click = getattr(
            close_button,
            "mouse_click",
            None,
        )

        if callable(mouse_click):
            mouse_click()
        else:
            click = getattr(
                close_button,
                "click",
                None,
            )

            if not callable(click):
                return False

            click()

        deadline = (
            time.time()
            + max(
                1,
                int(timeout),
            )
        )

        while (
            time.time()
            < deadline
        ):
            found = (
                self.browser.evaluate(
                    """
                    (() => Boolean(
                        document.querySelector(
                            '[data-testid="drawer-right"]'
                        )
                    ))()
                    """
                )
            )

            if not found:
                return True

            time.sleep(0.25)

        return False

    def get_message_composer_state(
        self,
    ):
        """Devuelve el estado observable del compositor activo.

        No escribe ni envía mensajes.
        """
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        result = self.browser.evaluate(
            """
            (() => {
                const composer =
                    document.querySelector(
                        '[data-testid="conversation-compose-box-input"]'
                    );

                if (!composer) {
                    return {
                        found: false,
                        text: '',
                        send_found: false
                    };
                }

                const text =
                    String(
                        composer.innerText
                        || composer.textContent
                        || ''
                    ).trim();

                const footer =
                    document.querySelector(
                        '#main footer'
                    );

                const sendButton =
                    footer
                    ? Array.from(
                        footer.querySelectorAll(
                            'button, [role="button"]'
                        )
                    ).find(
                        node =>
                            node.getClientRects().length
                            && String(
                                node.getAttribute(
                                    'aria-label'
                                )
                                || ''
                            ).trim()
                            === 'Enviar'
                    )
                    : null;

                return {
                    found: true,
                    text: text,
                    send_found:
                        Boolean(sendButton)
                };
            })()
            """
        )

        result = (
            result
            if isinstance(
                result,
                dict,
            )
            else {}
        )

        return {
            "found": bool(
                result.get(
                    "found"
                )
            ),
            "text": str(
                result.get(
                    "text"
                )
                or ""
            ),
            "send_found": bool(
                result.get(
                    "send_found"
                )
            ),
        }

    def set_message_composer_text(
        self,
        text,
        *,
        timeout=3,
    ):
        """Escribe texto mediante CDP en el compositor activo.

        No pulsa Enviar.
        """
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        value = str(
            text
            or ""
        )

        if not value.strip():
            raise ValueError(
                "El texto del mensaje no puede estar vacío"
            )

        initial = (
            self.get_message_composer_state()
        )

        if not initial[
            "found"
        ]:
            raise RuntimeError(
                "Compositor de WhatsApp no localizado"
            )

        if initial[
            "text"
        ]:
            raise RuntimeError(
                "El compositor contiene un borrador previo"
            )

        self.browser.send_keys(
            MESSAGE_COMPOSER_SELECTOR,
            value,
        )

        deadline = (
            time.time()
            + max(
                0.5,
                float(timeout),
            )
        )

        while (
            time.time()
            < deadline
        ):
            state = (
                self.get_message_composer_state()
            )

            if (
                state["text"]
                == value
                and state[
                    "send_found"
                ]
            ):
                return state

            time.sleep(
                0.05
            )

        raise RuntimeError(
            "WhatsApp no confirmó el texto "
            "en el compositor"
        )

    def _dispatch_composer_key_event(
        self,
        element,
        event_type,
        **kwargs,
    ):
        command = (
            cdp_input
            .dispatch_key_event(
                event_type,
                **kwargs,
            )
        )

        self.browser.loop.run_until_complete(
            element._tab.send(
                command
            )
        )

    def clear_message_composer(
        self,
        *,
        timeout=3,
    ):
        """Vacía de forma segura el contenteditable de WhatsApp.

        Usa eventos reales de teclado CDP:
        Ctrl+A + Backspace.

        No pulsa Enviar.
        """
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        initial = (
            self.get_message_composer_state()
        )

        if not initial[
            "found"
        ]:
            raise RuntimeError(
                "Compositor de WhatsApp no localizado"
            )

        if not initial[
            "text"
        ]:
            return initial

        element = (
            self.browser
            .find_element(
                MESSAGE_COMPOSER_SELECTOR
            )
        )

        if not element:
            raise RuntimeError(
                "Elemento del compositor no localizado"
            )

        self.browser.loop.run_until_complete(
            element.focus_async()
        )

        self._dispatch_composer_key_event(
            element,
            "rawKeyDown",
            modifiers=2,
            key="Control",
            code="ControlLeft",
            windows_virtual_key_code=17,
            native_virtual_key_code=17,
            location=1,
        )

        self._dispatch_composer_key_event(
            element,
            "rawKeyDown",
            modifiers=2,
            key="a",
            code="KeyA",
            windows_virtual_key_code=65,
            native_virtual_key_code=65,
        )

        self._dispatch_composer_key_event(
            element,
            "keyUp",
            modifiers=2,
            key="a",
            code="KeyA",
            windows_virtual_key_code=65,
            native_virtual_key_code=65,
        )

        self._dispatch_composer_key_event(
            element,
            "keyUp",
            modifiers=0,
            key="Control",
            code="ControlLeft",
            windows_virtual_key_code=17,
            native_virtual_key_code=17,
            location=1,
        )

        self._dispatch_composer_key_event(
            element,
            "rawKeyDown",
            modifiers=0,
            key="Backspace",
            code="Backspace",
            windows_virtual_key_code=8,
            native_virtual_key_code=8,
        )

        self._dispatch_composer_key_event(
            element,
            "keyUp",
            modifiers=0,
            key="Backspace",
            code="Backspace",
            windows_virtual_key_code=8,
            native_virtual_key_code=8,
        )

        deadline = (
            time.time()
            + max(
                0.5,
                float(timeout),
            )
        )

        while (
            time.time()
            < deadline
        ):
            state = (
                self.get_message_composer_state()
            )

            if (
                not state[
                    "text"
                ]
                and not state[
                    "send_found"
                ]
            ):
                return state

            time.sleep(
                0.05
            )

        raise RuntimeError(
            "WhatsApp no confirmó el vaciado "
            "del compositor"
        )

    def send_text_message(
        self,
        text,
        *,
        timeout=10,
    ):
        """Envía un único mensaje de texto al chat activo.

        El envío se confirma únicamente cuando aparece un
        nuevo snapshot OUTBOUND con:
        - provider_message_id nuevo;
        - cuerpo exactamente igual al solicitado.

        Devuelve el WhatsAppMessageSnapshot confirmado.

        No persiste información de negocio.
        """
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        value = str(
            text
            or ""
        )

        if not value.strip():
            raise ValueError(
                "El texto del mensaje no puede estar vacío"
            )

        before = (
            self.list_visible_message_snapshots(
                limit=200
            )
        )

        before_ids = {
            item.provider_message_id
            for item in before
            if item.provider_message_id
        }

        self.set_message_composer_text(
            value
        )

        try:
            send_button = (
                self.browser
                .find_element(
                    MESSAGE_SEND_SELECTOR
                )
            )
        except Exception as exc:
            try:
                self.clear_message_composer()
            except Exception:
                pass

            raise RuntimeError(
                "Botón Enviar de WhatsApp "
                "no localizado"
            ) from exc

        if not send_button:
            try:
                self.clear_message_composer()
            except Exception:
                pass

            raise RuntimeError(
                "Botón Enviar de WhatsApp "
                "no localizado"
            )

        mouse_click = getattr(
            send_button,
            "mouse_click",
            None,
        )

        click = getattr(
            send_button,
            "click",
            None,
        )

        if callable(
            mouse_click
        ):
            click_callable = (
                mouse_click
            )
        elif callable(
            click
        ):
            click_callable = (
                click
            )
        else:
            try:
                self.clear_message_composer()
            except Exception:
                pass

            raise RuntimeError(
                "Botón Enviar de WhatsApp "
                "no soporta click"
            )

        try:
            click_callable()
        except Exception as exc:
            # Una excepción durante el click es ambigua:
            # no se reintenta automáticamente porque el
            # mensaje podría haber sido enviado igualmente.
            raise WhatsAppSendStateUncertainError(
                "Estado de envío de WhatsApp incierto: "
                "falló la operación de click"
            ) from exc

        deadline = (
            time.time()
            + max(
                1.0,
                float(timeout),
            )
        )

        while (
            time.time()
            < deadline
        ):
            current = (
                self.list_visible_message_snapshots(
                    limit=200
                )
            )

            candidates = [
                item
                for item in current
                if (
                    item.provider_message_id
                    and item.provider_message_id
                    not in before_ids
                    and item.direction
                    == MESSAGE_DIRECTION_OUTBOUND
                    and item.body_text
                    == value
                )
            ]

            if len(
                candidates
            ) == 1:
                return candidates[
                    0
                ]

            if len(
                candidates
            ) > 1:
                raise WhatsAppSendStateUncertainError(
                    "Confirmación ambigua de envío: "
                    "WhatsApp expone varios mensajes "
                    "OUTBOUND nuevos con el mismo cuerpo"
                )

            time.sleep(
                0.1
            )

        # No reintentamos ni volvemos a pulsar Enviar.
        # Si el click ocurrió, la ausencia temporal del
        # snapshot deja un estado incierto que deberá
        # resolverse mediante sincronización/reconciliación.
        raise WhatsAppSendStateUncertainError(
            "Estado de envío de WhatsApp incierto: "
            "no apareció un nuevo mensaje OUTBOUND "
            "confirmable dentro del timeout"
        )

    def list_visible_message_snapshots(
        self,
        *,
        limit=200,
    ):
        """Extrae mensajes actualmente cargados del chat activo.

        Este método pertenece al transporte WhatsApp:
        - no persiste;
        - no conoce clientes ni expedientes;
        - no conoce SQLite;
        - no envía mensajes.
        """
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        effective_limit = max(
            1,
            int(limit),
        )

        rows = (
            self.browser.evaluate(
                """
                (() => {
                    const main =
                        document.querySelector(
                            '#main'
                        );

                    if (!main) {
                        return [];
                    }

                    function contentFromNode(
                        node
                    ) {
                        if (!node) {
                            return '';
                        }

                        let result = '';

                        function walk(
                            current
                        ) {
                            if (
                                current.nodeType
                                === Node.TEXT_NODE
                            ) {
                                result += (
                                    current.textContent
                                    || ''
                                );
                                return;
                            }

                            if (
                                current.nodeType
                                !== Node.ELEMENT_NODE
                            ) {
                                return;
                            }

                            if (
                                current.tagName
                                === 'IMG'
                            ) {
                                const alt =
                                    current.getAttribute(
                                        'alt'
                                    );

                                if (alt) {
                                    result += alt;
                                }

                                return;
                            }

                            for (
                                const child
                                of current.childNodes
                            ) {
                                walk(child);
                            }
                        }

                        walk(node);

                        return result.trim();
                    }

                    const mainRect =
                        main.getBoundingClientRect();

                    const roots =
                        Array.from(
                            main.querySelectorAll(
                                '[data-testid^="conv-msg-"]'
                            )
                        );

                    return roots.map(
                        root => {
                            const rawTestId =
                                root.getAttribute(
                                    'data-testid'
                                );

                            const providerId =
                                rawTestId
                                ? rawTestId.replace(
                                    /^conv-msg-/,
                                    ''
                                )
                                : '';

                            const preNode =
                                root.querySelector(
                                    '[data-pre-plain-text]'
                                );

                            const selectableNodes =
                                Array.from(
                                    root.querySelectorAll(
                                        '[data-testid="selectable-text"]'
                                    )
                                )
                                .filter(
                                    node => {
                                        const parent =
                                            node.parentElement
                                            ? node.parentElement
                                                .closest(
                                                    '[data-testid="selectable-text"]'
                                                )
                                            : null;

                                        return !parent;
                                    }
                                );

                            const bodyText =
                                selectableNodes
                                .map(
                                    contentFromNode
                                )
                                .filter(Boolean)
                                .join('\\n')
                                .trim();

                            const meta =
                                root.querySelector(
                                    '[data-testid="msg-meta"]'
                                );

                            const metaText =
                                meta
                                ? String(
                                    meta.innerText
                                    || meta.textContent
                                    || ''
                                ).trim()
                                : '';

                            const arias =
                                Array.from(
                                    root.querySelectorAll(
                                        '[aria-label]'
                                    )
                                )
                                .map(
                                    node =>
                                        String(
                                            node.getAttribute(
                                                'aria-label'
                                            )
                                            || ''
                                        ).trim()
                                )
                                .filter(Boolean);

                            const testids =
                                Array.from(
                                    root.querySelectorAll(
                                        '[data-testid]'
                                    )
                                )
                                .map(
                                    node =>
                                        node.getAttribute(
                                            'data-testid'
                                        )
                                )
                                .filter(Boolean);

                            const sticker =
                                Boolean(
                                    root.querySelector(
                                        '[data-testid="sticker-container"]'
                                    )
                                );

                            const hasTailIn =
                                Boolean(
                                    root.querySelector(
                                        '[data-testid="tail-in"]'
                                    )
                                );

                            const hasTailOut =
                                Boolean(
                                    root.querySelector(
                                        '[data-testid="tail-out"]'
                                    )
                                );

                            const messageContainer =
                                root.querySelector(
                                    '[data-testid="msg-container"]'
                                )
                                || root;

                            const messageRect =
                                messageContainer
                                .getBoundingClientRect();

                            const messageCenter =
                                messageRect.left
                                + (
                                    messageRect.width
                                    / 2
                                );

                            const centerRatio =
                                mainRect.width
                                ? (
                                    (
                                        messageCenter
                                        - mainRect.left
                                    )
                                    / mainRect.width
                                )
                                : null;

                            const imageInfo =
                                Array.from(
                                    root.querySelectorAll(
                                        'img'
                                    )
                                )
                                .map(
                                    img => ({
                                        alt:
                                            img.getAttribute(
                                                'alt'
                                            ),
                                        src:
                                            String(
                                                img.getAttribute(
                                                    'src'
                                                )
                                                || ''
                                            ).slice(
                                                0,
                                                250
                                            )
                                    })
                                );

                            const reactionLabels =
                                Array.from(
                                    root.querySelectorAll(
                                        '[data-testid="reaction-bubble"]'
                                    )
                                )
                                .map(
                                    node =>
                                        node.getAttribute(
                                            'aria-label'
                                        )
                                )
                                .filter(Boolean);

                            return {
                                provider_message_id:
                                    providerId,

                                pre_plain_text:
                                    preNode
                                    ? preNode.getAttribute(
                                        'data-pre-plain-text'
                                    )
                                    : null,

                                body_text:
                                    bodyText,

                                meta_text:
                                    metaText,

                                arias,

                                testids:
                                    Array.from(
                                        new Set(
                                            testids
                                        )
                                    ),

                                has_tail_in:
                                    hasTailIn,

                                has_tail_out:
                                    hasTailOut,

                                center_ratio:
                                    centerRatio,

                                has_sticker:
                                    sticker,

                                image_info:
                                    imageInfo,

                                video_count:
                                    root.querySelectorAll(
                                        'video'
                                    ).length,

                                audio_count:
                                    root.querySelectorAll(
                                        'audio'
                                    ).length,

                                reaction_labels:
                                    reactionLabels
                            };
                        }
                    );
                })()
                """
            )
            or []
        )

        rows = rows[
            -effective_limit:
        ]

        parsed_rows = []

        for row in rows:
            provider_id = str(
                row.get(
                    "provider_message_id"
                )
                or ""
            ).strip()

            if not provider_id:
                continue

            pre = (
                parse_whatsapp_pre_plain_text(
                    row.get(
                        "pre_plain_text"
                    )
                )
            )

            parsed_rows.append(
                {
                    "raw":
                        row,
                    "provider_message_id":
                        provider_id,
                    "body_text":
                        str(
                            row.get(
                                "body_text"
                            )
                            or ""
                        ).strip(),
                    "sender":
                        pre.get(
                            "sender"
                        ),
                    "date":
                        pre.get(
                            "date"
                        ),
                    "time":
                        (
                            pre.get(
                                "time"
                            )
                            or str(
                                row.get(
                                    "meta_text"
                                )
                                or ""
                            ).strip()
                            or None
                        ),
                    "provider_timestamp":
                        pre.get(
                            "provider_timestamp"
                        ),
                }
            )

        # WhatsApp no incluye data-pre-plain-text en
        # algunos contenidos, por ejemplo stickers.
        # Inferimos únicamente la fecha de un mensaje
        # adyacente visible y conservamos la procedencia
        # en metadata.
        for index, item in enumerate(
            parsed_rows
        ):
            if item[
                "provider_timestamp"
            ]:
                continue

            raw_time = item.get(
                "time"
            )

            if not raw_time:
                continue

            inferred_date = None

            for cursor in range(
                index - 1,
                -1,
                -1,
            ):
                candidate = (
                    parsed_rows[
                        cursor
                    ].get(
                        "date"
                    )
                )

                if candidate:
                    inferred_date = (
                        candidate
                    )
                    break

            if inferred_date is None:
                for cursor in range(
                    index + 1,
                    len(parsed_rows),
                ):
                    candidate = (
                        parsed_rows[
                            cursor
                        ].get(
                            "date"
                        )
                    )

                    if candidate:
                        inferred_date = (
                            candidate
                        )
                        break

            if inferred_date:
                try:
                    parsed = (
                        datetime.strptime(
                            (
                                f"{inferred_date} "
                                f"{raw_time}"
                            ),
                            "%d/%m/%Y %H:%M",
                        )
                    )

                    item[
                        "provider_timestamp"
                    ] = parsed.isoformat(
                        timespec="seconds"
                    )

                    item[
                        "timestamp_inferred"
                    ] = True

                except ValueError:
                    pass

        snapshots = []

        for item in parsed_rows:
            raw = item[
                "raw"
            ]

            arias = [
                str(value or "")
                .strip()
                for value in (
                    raw.get(
                        "arias"
                    )
                    or []
                )
            ]

            normalized_arias = [
                unicodedata.normalize(
                    "NFKC",
                    value,
                )
                .casefold()
                .strip()
                for value in arias
            ]

            own_marker = any(
                value in (
                    "tú:",
                    "tu:",
                    "you:",
                )
                for value in normalized_arias
            )

            read_marker = any(
                value in (
                    "leído",
                    "leido",
                    "read",
                )
                for value in normalized_arias
            )

            delivered_marker = any(
                value in (
                    "entregado",
                    "delivered",
                )
                for value in normalized_arias
            )

            sent_marker = any(
                value in (
                    "enviado",
                    "sent",
                )
                for value in normalized_arias
            )

            direction_source = None

            if own_marker:
                direction = (
                    MESSAGE_DIRECTION_OUTBOUND
                )

                direction_source = (
                    "OWN_MARKER"
                )

            elif (
                read_marker
                or delivered_marker
                or sent_marker
            ):
                direction = (
                    MESSAGE_DIRECTION_OUTBOUND
                )

                direction_source = (
                    "DELIVERY_STATUS"
                )

            elif raw.get(
                "has_tail_out"
            ):
                direction = (
                    MESSAGE_DIRECTION_OUTBOUND
                )

                direction_source = (
                    "TAIL"
                )

            elif item.get(
                "sender"
            ):
                direction = (
                    MESSAGE_DIRECTION_INBOUND
                )

                direction_source = (
                    "SENDER"
                )

            elif raw.get(
                "has_tail_in"
            ):
                direction = (
                    MESSAGE_DIRECTION_INBOUND
                )

                direction_source = (
                    "TAIL"
                )

            else:
                center_ratio = raw.get(
                    "center_ratio"
                )

                try:
                    center_ratio = float(
                        center_ratio
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    center_ratio = None

                if (
                    center_ratio is not None
                    and center_ratio <= 0.40
                ):
                    direction = (
                        MESSAGE_DIRECTION_INBOUND
                    )

                    direction_source = (
                        "GEOMETRY"
                    )

                elif (
                    center_ratio is not None
                    and center_ratio >= 0.60
                ):
                    direction = (
                        MESSAGE_DIRECTION_OUTBOUND
                    )

                    direction_source = (
                        "GEOMETRY"
                    )

                else:
                    direction = (
                        MESSAGE_DIRECTION_UNKNOWN
                    )

                    direction_source = (
                        "UNKNOWN"
                    )

            if (
                direction
                == MESSAGE_DIRECTION_INBOUND
            ):
                provider_status = (
                    MESSAGE_STATUS_RECEIVED
                )

            elif read_marker:
                provider_status = (
                    MESSAGE_STATUS_READ
                )

            elif delivered_marker:
                provider_status = (
                    MESSAGE_STATUS_DELIVERED
                )

            elif sent_marker:
                provider_status = (
                    MESSAGE_STATUS_SENT
                )

            else:
                provider_status = (
                    MESSAGE_STATUS_UNKNOWN
                )

            if raw.get(
                "has_sticker"
            ):
                message_type = (
                    MESSAGE_TYPE_STICKER
                )

            elif item.get(
                "body_text"
            ):
                message_type = (
                    MESSAGE_TYPE_TEXT
                )

            else:
                message_type = (
                    MESSAGE_TYPE_UNKNOWN_MEDIA
                )

            metadata = {
                "transport":
                    "WHATSAPP_WEB",
                "direction_source":
                    direction_source,
                "meta_text":
                    raw.get(
                        "meta_text"
                    ),
                "timestamp_inferred":
                    bool(
                        item.get(
                            "timestamp_inferred"
                        )
                    ),
                "reaction_labels":
                    list(
                        raw.get(
                            "reaction_labels"
                        )
                        or []
                    ),
                "image_count":
                    len(
                        raw.get(
                            "image_info"
                        )
                        or []
                    ),
                "video_count":
                    int(
                        raw.get(
                            "video_count"
                        )
                        or 0
                    ),
                "audio_count":
                    int(
                        raw.get(
                            "audio_count"
                        )
                        or 0
                    ),
            }

            snapshots.append(
                WhatsAppMessageSnapshot(
                    provider_message_id=(
                        item[
                            "provider_message_id"
                        ]
                    ),
                    direction=direction,
                    body_text=(
                        item.get(
                            "body_text"
                        )
                        or ""
                    ),
                    provider_timestamp=(
                        item.get(
                            "provider_timestamp"
                        )
                    ),
                    message_type=(
                        message_type
                    ),
                    provider_status=(
                        provider_status
                    ),
                    sender=(
                        item.get(
                            "sender"
                        )
                    ),
                    metadata=metadata,
                )
            )

        return snapshots

    def get_open_contact_phone(
        self,
    ):
        """Obtiene el teléfono visible en Info. del contacto."""
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        drawer_text = (
            self.browser.evaluate(
                """
                (() => {
                    const drawer =
                        document.querySelector(
                            '[data-testid="drawer-right"]'
                        );

                    return drawer
                        ? (
                            drawer.innerText
                            || ""
                        )
                        : "";
                })()
                """
            )
            or ""
        )

        return (
            extract_phone_from_profile_text(
                drawer_text
            )
        )

    def close(self):
        """Finaliza únicamente el navegador de esta sesión WhatsApp.

        El wrapper sb_cdp.Chrome de la versión instalada no expone quit(),
        pero su driver interno sí dispone de stop()/quit(). Se utiliza
        driver.stop() para cerrar limpiamente el proceso Chrome y la conexión
        CDP, sin modificar el comportamiento de Mercurio ni DEHú.
        """
        if not self.browser:
            return False

        driver = getattr(
            self.browser,
            "driver",
            None,
        )

        stop = getattr(
            driver,
            "stop",
            None,
        )

        if not callable(stop):
            return False

        try:
            stop()
            return True
        except Exception:
            return False
