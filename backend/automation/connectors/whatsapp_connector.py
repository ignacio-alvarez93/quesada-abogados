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
from pathlib import Path
import re
import time
import unicodedata

from backend.automation.browser_actions import (
    open_url,
)
from backend.automation.browser_session import (
    get_project_root,
    start_seleniumbase_chrome,
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

                        if (!composer) {
                            return {
                                opened: false,
                                composer_aria_label: null,
                                active_display_name:
                                    activeName
                            };
                        }

                        return {
                            opened: true,
                            composer_aria_label:
                                composer.getAttribute(
                                    'aria-label'
                                ),
                            active_display_name:
                                activeName
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
            "composer_aria_label":
                None,
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
