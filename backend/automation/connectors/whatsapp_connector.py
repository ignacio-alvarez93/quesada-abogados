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
import json
import re
import time
import unicodedata

import mycdp.browser as cdp_browser
import mycdp.input_ as cdp_input

from backend.automation.browser_actions import (
    open_url,
)
from backend.automation.browser_contracts import (
    BrowserSessionConfig,
    BrowserSessionMode,
    BrowserShutdownMode,
)
from backend.automation.browser_session import (
    get_project_root,
)
from backend.automation.seleniumbase_browser_session import (
    SeleniumBaseBrowserSession,
)
from backend.communications.phone_normalization import (
    normalize_phone,
)


from backend.automation.connectors.whatsapp_call_history_reader import (
    read_whatsapp_call_history,
)

from backend.automation.connectors.whatsapp_call_observer import (
    WHATSAPP_CALL_DIRECTION_INBOUND,
    WHATSAPP_CALL_DIRECTION_OUTBOUND,
    WHATSAPP_CALL_DIRECTION_UNKNOWN,
    WHATSAPP_CALL_PHASE_ABSENT,
    WHATSAPP_CALL_PHASE_ACTIVE,
    WHATSAPP_CALL_PHASE_CONNECTING,
    WHATSAPP_CALL_PHASE_ENDED_TRANSIENT,
    WHATSAPP_CALL_PHASE_INCOMING_RINGING,
    WHATSAPP_CALL_PHASE_OUTGOING_DIALING,
    WHATSAPP_CALL_PHASE_SURFACE_PRESENT,
    WhatsAppCallSnapshot,
    read_whatsapp_call_snapshot,
)


WHATSAPP_WEB_URL = (
    "https://web.whatsapp.com/"
)

WHATSAPP_WEB_ORIGIN = (
    "https://web.whatsapp.com"
)

WHATSAPP_CALL_MIC_STATE_ABSENT = (
    "ABSENT"
)

WHATSAPP_CALL_MIC_STATE_ENABLED = (
    "ENABLED"
)

WHATSAPP_CALL_MIC_STATE_MUTED = (
    "MUTED"
)

WHATSAPP_CALL_MIC_STATE_UNKNOWN = (
    "UNKNOWN"
)

WHATSAPP_CALL_MIC_MUTE_SELECTOR = (
    'button[data-testid="mic-mute"]'
)

WHATSAPP_CALL_MIC_UNMUTE_SELECTOR = (
    'button[data-testid="mic-unmute"]'
)

WHATSAPP_CALL_MIC_SPLIT_SELECTOR = (
    '[data-testid="mic-split-button"]'
)

WHATSAPP_AUDIO_CALL_SURFACE_SELECTOR = (
    '[data-testid="voip-container-audio-call"]'
)

WHATSAPP_VOICE_CALL_BUTTON_SELECTOR = (
    '#main header button[aria-label="Llamada"]'
)

WHATSAPP_CHATS_TAB_SELECTOR = (
    'button[aria-label="Chats"]'
)

WHATSAPP_CALLS_TAB_SELECTOR = (
    'button[aria-label="Llamadas"]'
)




# CALL-UX-4 · controles certificados con DOM real
# WhatsApp Web ES · 2026-08-16.
#
# La superficie fue observada realmente como:
# [data-testid="move_resize_component"]
#
# Aceptar:
# button[aria-label="Aceptar"]
#
# Rechazar:
# button[aria-label="Rechazar"]
#
# Nunca se utilizan clases CSS efímeras.
WHATSAPP_INCOMING_CALL_SURFACE_SELECTOR = (
    '[data-testid="move_resize_component"]'
)

WHATSAPP_INCOMING_CALL_ACCEPT_ARIA_LABEL = (
    "Aceptar"
)

WHATSAPP_INCOMING_CALL_REJECT_ARIA_LABEL = (
    "Rechazar"
)

WHATSAPP_INCOMING_CALL_ACCEPT_SELECTOR = (
    WHATSAPP_INCOMING_CALL_SURFACE_SELECTOR
    + ' button[aria-label="Aceptar"]'
)

WHATSAPP_INCOMING_CALL_REJECT_SELECTOR = (
    WHATSAPP_INCOMING_CALL_SURFACE_SELECTOR
    + ' button[aria-label="Rechazar"]'
)

WHATSAPP_VOICE_CALL_ARIA_LABEL = (
    "Llamada"
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

MESSAGE_TYPE_DOCUMENT = (
    "DOCUMENT"
)

MESSAGE_TYPE_IMAGE = (
    "IMAGE"
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


class WhatsAppAttachmentStageStateUncertainError(
    RuntimeError
):
    """La carga del adjunto pudo ejecutarse pero no pudo confirmarse."""


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


# WA-UX-PERF-12D · selectores observados físicamente
# en WhatsApp Web 2026-08-17.
#
# No dependen de clases CSS efímeras.
WHATSAPP_ATTACH_BUTTON_SELECTOR = (
    'button[aria-label="Adjuntar"]'
)

WHATSAPP_DOCUMENT_ATTACH_SELECTOR = (
    '[role="menu"] '
    '[role="menuitem"]'
    '[aria-label="Documento"]'
)

WHATSAPP_DOCUMENT_CAPTURE_SELECTOR = (
    'input[type="file"]'
    '[data-qa-wa-document-input="1"]'
)

WHATSAPP_ATTACHMENT_PREVIEW_SELECTOR = (
    '[data-testid="drawer-middle"]'
)

WHATSAPP_ATTACHMENT_CAPTION_SELECTOR = (
    '[data-testid="media-caption-input-container"]'
)

WHATSAPP_ATTACHMENT_REMOVE_SELECTOR = (
    '[role="button"]'
    '[aria-label="Quitar archivo adjunto"]'
)

WHATSAPP_ATTACHMENT_ADD_SELECTOR = (
    'button[aria-label="Añadir archivo"]'
)


WHATSAPP_ATTACHMENT_SEND_ONE_SELECTOR = (
    '[data-testid="drawer-middle"] '
    '[role="button"]'
    '[aria-label="Enviar 1 seleccionado"]'
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
class WhatsAppActiveChatFingerprint:
    """Huella ligera del chat actualmente abierto.

    Sirve para detectar cambios sin extraer ni persistir
    el historial completo de mensajes.
    """

    chat_open: bool
    active_display_name: str
    active_identity: str
    visible_message_count: int
    last_provider_message_id: str | None

    # Estado observable del último mensaje cuando WhatsApp
    # expone SENT / DELIVERED / READ en su accesibilidad.
    #
    # Default para conservar compatibilidad con todos los
    # constructores posicionales históricos del runtime/tests.
    last_provider_message_status: str | None = None


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


def diff_sidebar_chat_fingerprints(
    previous,
    current,
):
    """Compara dos huellas del sidebar de WhatsApp.

    Devuelve únicamente identidades cuyo estado observable
    cambió entre snapshots.

    Regla crítica:
    position y virtual_offset son cambios operativos.
    Por sí solos NO significan mensaje nuevo.

    content_changed solo se activa cuando cambia alguna
    señal funcional:
    - preview;
    - primary_detail;
    - unread_count;
    - ambiguous;
    - aparición/desaparición.
    """
    previous = (
        previous
        if isinstance(
            previous,
            dict,
        )
        else {}
    )

    current = (
        current
        if isinstance(
            current,
            dict,
        )
        else {}
    )

    identities = set(
        previous
    ) | set(
        current
    )

    changes = []

    for identity in sorted(
        identities
    ):
        before = previous.get(
            identity
        )

        after = current.get(
            identity
        )

        appeared = (
            before is None
            and after is not None
        )

        disappeared = (
            before is not None
            and after is None
        )

        if appeared:
            preview_changed = True
            primary_detail_changed = True
            unread_changed = True
            ambiguous_changed = bool(
                after.get(
                    "ambiguous"
                )
            )
            position_changed = True
            virtual_offset_changed = True
            content_changed = True

        elif disappeared:
            preview_changed = True
            primary_detail_changed = True
            unread_changed = True
            ambiguous_changed = bool(
                before.get(
                    "ambiguous"
                )
            )
            position_changed = True
            virtual_offset_changed = True
            content_changed = True

        else:
            preview_changed = (
                str(
                    before.get(
                        "preview"
                    )
                    or ""
                )
                != str(
                    after.get(
                        "preview"
                    )
                    or ""
                )
            )

            primary_detail_changed = (
                str(
                    before.get(
                        "primary_detail"
                    )
                    or ""
                )
                != str(
                    after.get(
                        "primary_detail"
                    )
                    or ""
                )
            )

            unread_changed = (
                int(
                    before.get(
                        "unread_count"
                    )
                    or 0
                )
                != int(
                    after.get(
                        "unread_count"
                    )
                    or 0
                )
            )

            ambiguous_changed = (
                bool(
                    before.get(
                        "ambiguous"
                    )
                )
                != bool(
                    after.get(
                        "ambiguous"
                    )
                )
            )

            position_changed = (
                before.get(
                    "position"
                )
                != after.get(
                    "position"
                )
            )

            virtual_offset_changed = (
                before.get(
                    "virtual_offset"
                )
                != after.get(
                    "virtual_offset"
                )
            )

            content_changed = bool(
                preview_changed
                or primary_detail_changed
                or unread_changed
                or ambiguous_changed
            )

        any_changed = bool(
            appeared
            or disappeared
            or content_changed
            or position_changed
            or virtual_offset_changed
        )

        if not any_changed:
            continue

        if appeared:
            change_type = (
                "SIDEBAR_THREAD_APPEARED"
            )

        elif disappeared:
            change_type = (
                "SIDEBAR_THREAD_DISAPPEARED"
            )

        elif content_changed:
            change_type = (
                "SIDEBAR_THREAD_CHANGED"
            )

        else:
            change_type = (
                "SIDEBAR_THREAD_REORDERED"
            )

        changes.append(
            {
                "identity":
                    identity,
                "change_type":
                    change_type,
                "appeared":
                    appeared,
                "disappeared":
                    disappeared,
                "content_changed":
                    content_changed,
                "preview_changed":
                    preview_changed,
                "primary_detail_changed":
                    primary_detail_changed,
                "unread_changed":
                    unread_changed,
                "ambiguous_changed":
                    ambiguous_changed,
                "position_changed":
                    position_changed,
                "virtual_offset_changed":
                    virtual_offset_changed,
                "previous":
                    before,
                "current":
                    after,
            }
        )

    return changes


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
        browser_session_factory=None,
    ):
        self.profile_key = str(
            profile_key
            or "whatsapp_dev"
        ).strip()

        self.headless = bool(
            headless
        )

        self._browser_session_factory = (
            browser_session_factory
            or SeleniumBaseBrowserSession
        )

        if not callable(
            self._browser_session_factory
        ):
            raise TypeError(
                "browser_session_factory debe ser callable"
            )

        # BrowserSession es propietaria del lifecycle técnico.
        #
        # ``browser`` se conserva como superficie autorizada
        # del connector para no alterar la semántica WhatsApp
        # ya existente ni sus adapters CDP especializados.
        self._browser_session = None
        self.browser = None

        # Resultado de la política de medios aplicada
        # específicamente al origen de WhatsApp Web.
        #
        # No forma parte de BrowserSessionConfig:
        # el permiso pertenece al consumidor WhatsApp,
        # no a la infraestructura genérica de navegador.
        self._call_media_permission_result = None

    def _build_browser_session(
        self,
    ):
        if (
            self._browser_session
            is None
        ):
            config = BrowserSessionConfig(
                consumer="whatsapp",
                mode=(
                    BrowserSessionMode.PERSISTENT
                ),
                headless=self.headless,
                profile_key=self.profile_key,
            )

            self._browser_session = (
                self._browser_session_factory(
                    config=config,
                    profile_resolver=(
                        get_whatsapp_profile_dir
                    ),
                )
            )

        return self._browser_session

    def start(self):
        session = (
            self._build_browser_session()
        )

        self.browser = (
            session.start()
        )

        open_url(
            self.browser,
            WHATSAPP_WEB_URL,
        )

        # Política específica de llamadas WhatsApp.
        #
        # Se aplica en cada arranque porque Browser.setPermission
        # es un override del browser context actual. No mutamos
        # BrowserSessionConfig ni editamos Preferences a mano.
        #
        # Un fallo de permisos no destruye el transporte de chat:
        # queda diagnosticado y la futura acción de llamada podrá
        # exigir explícitamente configured=True antes de marcar.
        try:
            self.configure_call_media_permissions()

        except Exception as exc:
            self._call_media_permission_result = {
                "configured": False,
                "reason": (
                    "MICROPHONE_PERMISSION_ERROR"
                ),
                "origin": (
                    WHATSAPP_WEB_ORIGIN
                ),
                "permission": (
                    "microphone"
                ),
                "setting": (
                    "granted"
                ),
                "error_type": (
                    type(exc).__name__
                ),
                "message": str(
                    exc
                ),
            }

        return self.browser

    @property
    def call_media_permission_result(
        self,
    ):
        result = (
            self._call_media_permission_result
        )

        return (
            dict(result)
            if isinstance(
                result,
                dict,
            )
            else result
        )

    def configure_call_media_permissions(
        self,
    ):
        """Concede micrófono únicamente a WhatsApp Web.

        Usa Browser.setPermission mediante el transporte CDP
        ya poseído por sb_cdp.Chrome.

        No:
        - concede permisos globales;
        - concede cámara;
        - modifica BrowserSessionConfig;
        - escribe manualmente Preferences;
        - toca el estado mute/unmute de una llamada.
        """
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        page = getattr(
            self.browser,
            "page",
            None,
        )

        loop = getattr(
            self.browser,
            "loop",
            None,
        )

        send = getattr(
            page,
            "send",
            None,
        )

        run_until_complete = getattr(
            loop,
            "run_until_complete",
            None,
        )

        if (
            not callable(send)
            or not callable(
                run_until_complete
            )
        ):
            result = {
                "configured": False,
                "reason": (
                    "CDP_PERMISSION_TRANSPORT_UNAVAILABLE"
                ),
                "origin": (
                    WHATSAPP_WEB_ORIGIN
                ),
                "permission": (
                    "microphone"
                ),
                "setting": (
                    "granted"
                ),
            }

            self._call_media_permission_result = (
                result
            )

            return dict(
                result
            )

        command = (
            cdp_browser.set_permission(
                permission=(
                    cdp_browser
                    .PermissionDescriptor(
                        name="microphone"
                    )
                ),
                setting=(
                    cdp_browser
                    .PermissionSetting(
                        "granted"
                    )
                ),
                origin=(
                    WHATSAPP_WEB_ORIGIN
                ),
            )
        )

        run_until_complete(
            send(
                command
            )
        )

        result = {
            "configured": True,
            "reason": (
                "MICROPHONE_PERMISSION_GRANTED"
            ),
            "origin": (
                WHATSAPP_WEB_ORIGIN
            ),
            "permission": (
                "microphone"
            ),
            "setting": (
                "granted"
            ),
        }

        self._call_media_permission_result = (
            result
        )

        return dict(
            result
        )

    def read_call_microphone_state(
        self,
    ):
        """Lee pasivamente el estado del micrófono de llamada.

        Contrato observado en WhatsApp Web real:

        ENABLED:
            button[data-testid="mic-mute"]
            aria-label="Silenciar micrófono"

        MUTED:
            button[data-testid="mic-unmute"]
            aria-label="Desactivar silencio del micrófono"

        Nunca realiza clicks.
        """
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        snapshot = (
            self.browser.evaluate(
                """
                (() => {
                    const clean = (value) =>
                        (value || "")
                        .replace(/\\s+/g, " ")
                        .trim();

                    const call =
                        document.querySelector(
                            '[data-testid="voip-container-audio-call"]'
                        );

                    const mute =
                        document.querySelector(
                            'button[data-testid="mic-mute"]'
                        );

                    const unmute =
                        document.querySelector(
                            'button[data-testid="mic-unmute"]'
                        );

                    const split =
                        document.querySelector(
                            '[data-testid="mic-split-button"]'
                        );

                    const describe = (node) => {
                        if (!node) {
                            return null;
                        }

                        return {
                            testid:
                                clean(
                                    node.getAttribute(
                                        "data-testid"
                                    )
                                ),
                            aria_label:
                                clean(
                                    node.getAttribute(
                                        "aria-label"
                                    )
                                ),
                            disabled:
                                !!node.disabled,
                            aria_disabled:
                                clean(
                                    node.getAttribute(
                                        "aria-disabled"
                                    )
                                )
                        };
                    };

                    return {
                        call_present:
                            !!call,
                        mute:
                            describe(mute),
                        unmute:
                            describe(unmute),
                        split:
                            describe(split)
                    };
                })()
                """
            )
            or {}
        )

        if not isinstance(
            snapshot,
            dict,
        ):
            snapshot = {}

        call_present = bool(
            snapshot.get(
                "call_present"
            )
        )

        mute = (
            snapshot.get(
                "mute"
            )
            if isinstance(
                snapshot.get(
                    "mute"
                ),
                dict,
            )
            else None
        )

        unmute = (
            snapshot.get(
                "unmute"
            )
            if isinstance(
                snapshot.get(
                    "unmute"
                ),
                dict,
            )
            else None
        )

        split = (
            snapshot.get(
                "split"
            )
            if isinstance(
                snapshot.get(
                    "split"
                ),
                dict,
            )
            else None
        )

        if not call_present:
            return {
                "state":
                    WHATSAPP_CALL_MIC_STATE_ABSENT,
                "call_present":
                    False,
                "selector":
                    None,
                "action_label":
                    "",
                "click_required":
                    False,
                "evidence":
                    snapshot,
            }

        mute_label = str(
            (
                mute
                or {}
            ).get(
                "aria_label"
            )
            or ""
        ).strip()

        unmute_label = str(
            (
                unmute
                or {}
            ).get(
                "aria_label"
            )
            or ""
        ).strip()

        split_label = str(
            (
                split
                or {}
            ).get(
                "aria_label"
            )
            or ""
        ).strip()

        normalized_mute_label = (
            mute_label.lower()
        )

        normalized_unmute_label = (
            unmute_label.lower()
        )

        normalized_split_label = (
            split_label.lower()
        )

        enabled_evidence = bool(
            mute is not None
            and (
                normalized_mute_label
                == "silenciar micrófono"
                or normalized_split_label
                == "silenciar micrófono"
            )
        )

        muted_evidence = bool(
            unmute is not None
            and (
                normalized_unmute_label
                == "desactivar silencio del micrófono"
                or normalized_split_label
                == "desactivar silencio del micrófono"
            )
        )

        # Dos estados simultáneos serían una superficie
        # inconsistente; nunca hacemos click en ese caso.
        if (
            enabled_evidence
            and not muted_evidence
        ):
            return {
                "state":
                    WHATSAPP_CALL_MIC_STATE_ENABLED,
                "call_present":
                    True,
                "selector":
                    WHATSAPP_CALL_MIC_MUTE_SELECTOR,
                "action_label":
                    (
                        mute_label
                        or split_label
                    ),
                "click_required":
                    False,
                "evidence":
                    snapshot,
            }

        if (
            muted_evidence
            and not enabled_evidence
        ):
            disabled = bool(
                (
                    unmute
                    or {}
                ).get(
                    "disabled"
                )
            )

            aria_disabled = str(
                (
                    unmute
                    or {}
                ).get(
                    "aria_disabled"
                )
                or ""
            ).strip().lower()

            if aria_disabled == "true":
                disabled = True

            return {
                "state":
                    WHATSAPP_CALL_MIC_STATE_MUTED,
                "call_present":
                    True,
                "selector":
                    WHATSAPP_CALL_MIC_UNMUTE_SELECTOR,
                "action_label":
                    (
                        unmute_label
                        or split_label
                    ),
                "click_required":
                    not disabled,
                "control_disabled":
                    disabled,
                "evidence":
                    snapshot,
            }

        return {
            "state":
                WHATSAPP_CALL_MIC_STATE_UNKNOWN,
            "call_present":
                True,
            "selector":
                None,
            "action_label":
                (
                    unmute_label
                    or mute_label
                    or split_label
                ),
            "click_required":
                False,
            "evidence":
                snapshot,
        }

    def ensure_call_microphone_enabled(
        self,
        *,
        verify_timeout=2.0,
        poll_interval=0.10,
    ):
        """Garantiza micro activo sin toggle ciego.

        Solo pulsa cuando existe evidencia inequívoca
        de estado MUTED y el target exacto mic-unmute.

        Después exige observar ENABLED.
        """
        initial = (
            self.read_call_microphone_state()
        )

        initial_state = (
            initial.get(
                "state"
            )
        )

        if (
            initial_state
            == WHATSAPP_CALL_MIC_STATE_ENABLED
        ):
            return {
                "ready": True,
                "changed": False,
                "reason":
                    "MICROPHONE_ALREADY_ENABLED",
                "initial_state":
                    initial_state,
                "final_state":
                    initial_state,
                "initial":
                    initial,
                "final":
                    initial,
            }

        if (
            initial_state
            == WHATSAPP_CALL_MIC_STATE_ABSENT
        ):
            return {
                "ready": False,
                "changed": False,
                "reason":
                    "CALL_SURFACE_ABSENT",
                "initial_state":
                    initial_state,
                "final_state":
                    initial_state,
                "initial":
                    initial,
                "final":
                    initial,
            }

        if (
            initial_state
            != WHATSAPP_CALL_MIC_STATE_MUTED
        ):
            return {
                "ready": False,
                "changed": False,
                "reason":
                    "MICROPHONE_STATE_UNKNOWN",
                "initial_state":
                    initial_state,
                "final_state":
                    initial_state,
                "initial":
                    initial,
                "final":
                    initial,
            }

        if not bool(
            initial.get(
                "click_required"
            )
        ):
            return {
                "ready": False,
                "changed": False,
                "reason":
                    "MICROPHONE_UNMUTE_CONTROL_DISABLED",
                "initial_state":
                    initial_state,
                "final_state":
                    initial_state,
                "initial":
                    initial,
                "final":
                    initial,
            }

        element = (
            self.browser.find_element(
                WHATSAPP_CALL_MIC_UNMUTE_SELECTOR
            )
        )

        if element is None:
            return {
                "ready": False,
                "changed": False,
                "reason":
                    "MICROPHONE_UNMUTE_CONTROL_NOT_FOUND",
                "initial_state":
                    initial_state,
                "final_state":
                    initial_state,
                "initial":
                    initial,
                "final":
                    initial,
            }

        mouse_click = getattr(
            element,
            "mouse_click",
            None,
        )

        if callable(
            mouse_click
        ):
            mouse_click()

        else:
            click = getattr(
                element,
                "click",
                None,
            )

            if not callable(
                click
            ):
                return {
                    "ready": False,
                    "changed": False,
                    "reason":
                        "MICROPHONE_UNMUTE_CONTROL_NOT_CLICKABLE",
                    "initial_state":
                        initial_state,
                    "final_state":
                        initial_state,
                    "initial":
                        initial,
                    "final":
                        initial,
                }

            click()

        timeout = max(
            0.0,
            float(
                verify_timeout
                or 0.0
            ),
        )

        interval = max(
            0.01,
            float(
                poll_interval
                or 0.10
            ),
        )

        deadline = (
            time.monotonic()
            + timeout
        )

        final = initial

        while True:
            final = (
                self.read_call_microphone_state()
            )

            final_state = (
                final.get(
                    "state"
                )
            )

            if (
                final_state
                == WHATSAPP_CALL_MIC_STATE_ENABLED
            ):
                return {
                    "ready": True,
                    "changed": True,
                    "reason":
                        "MICROPHONE_ENABLED",
                    "initial_state":
                        initial_state,
                    "final_state":
                        final_state,
                    "initial":
                        initial,
                    "final":
                        final,
                }

            if (
                time.monotonic()
                >= deadline
            ):
                break

            time.sleep(
                interval
            )

        return {
            "ready": False,
            "changed": True,
            "reason":
                "MICROPHONE_ENABLE_NOT_CONFIRMED",
            "initial_state":
                initial_state,
            "final_state":
                final.get(
                    "state"
                ),
            "initial":
                initial,
            "final":
                final,
        }

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

    def get_sidebar_chat_fingerprint(
        self,
        *,
        viewport_only=True,
    ):
        """Obtiene una huella ligera del sidebar de WhatsApp.

        Reutiliza exclusivamente la lectura DOM ya existente
        de las filas materializadas.

        No:
        - navega;
        - hace click;
        - desplaza la lista;
        - usa find_element;
        - abre perfiles;
        - persiste datos.

        La clave lógica es la identidad visible normalizada.
        position y virtual_offset se conservan como información
        operativa, pero NO forman parte de la identidad lógica
        de la conversación.
        """

        snapshots = (
            self.list_visible_chat_snapshots(
                viewport_only=viewport_only,
            )
        )

        result = {}

        for snapshot in snapshots:
            identity = (
                normalize_chat_identity(
                    snapshot.display_name
                )
            )

            if not identity:
                continue

            # Dos chats visibles con la misma identidad
            # normalizada son ambiguos.
            #
            # No elegimos arbitrariamente uno de ellos.
            if identity in result:
                existing = result[
                    identity
                ]

                existing[
                    "ambiguous"
                ] = True

                continue

            result[
                identity
            ] = {
                "identity":
                    identity,
                "display_name":
                    snapshot.display_name,
                "primary_detail":
                    snapshot.primary_detail,
                "preview":
                    snapshot.preview,
                "unread_count":
                    max(
                        0,
                        int(
                            snapshot.unread_count
                            or 0
                        ),
                    ),
                "position":
                    int(
                        snapshot.position
                    ),
                "virtual_offset":
                    snapshot.virtual_offset,
                "ambiguous":
                    False,
            }


        return result


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

    def _find_chat_search_selector(
        self,
    ):
        """Localiza el buscador lateral en reposo o búsqueda activa."""
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        result = (
            self.browser.evaluate(
                """
                (() => {
                    const nodes = Array.from(
                        document.querySelectorAll(
                            '[contenteditable="true"], '
                            + '[role="textbox"], '
                            + 'input'
                        )
                    );

                    for (const node of nodes) {
                        const label = String(
                            node.getAttribute(
                                'aria-label'
                            )
                            || ''
                        )
                        .trim()
                        .toLowerCase();

                        const isInitialSearch = (
                            label.includes(
                                'buscar un chat'
                            )
                            || label.includes(
                                'search or start new chat'
                            )
                        );

                        const isActiveSearch = (
                            node.tagName === 'INPUT'
                            && node.getAttribute(
                                'role'
                            ) === 'textbox'
                            && node.getAttribute(
                                'data-tab'
                            ) === '3'
                        );

                        if (
                            !isInitialSearch
                            && !isActiveSearch
                        ) {
                            continue;
                        }

                        if (isActiveSearch) {
                            return (
                                'input[role="textbox"]'
                                + '[data-tab="3"]'
                            );
                        }

                        const testid = String(
                            node.getAttribute(
                                'data-testid'
                            )
                            || ''
                        ).trim();

                        if (testid) {
                            return (
                                '[data-testid="'
                                + testid
                                + '"]'
                            );
                        }

                        const aria = String(
                            node.getAttribute(
                                'aria-label'
                            )
                            || ''
                        );

                        if (aria) {
                            return (
                                '[aria-label="'
                                + aria.replace(
                                    /"/g,
                                    '\\\"'
                                )
                                + '"]'
                            );
                        }
                    }

                    return null;
                })()
                """
            )
        )

        return (
            str(result).strip()
            if result
            else None
        )


    def get_chat_search_state(
        self,
    ):
        selector = (
            self._find_chat_search_selector()
        )

        if not selector:
            return {
                "found": False,
                "selector": None,
                "text": "",
            }

        selector_js = json.dumps(
            selector,
            ensure_ascii=False,
        )

        result = (
            self.browser.evaluate(
                f"""
                (() => {{
                    const node =
                        document.querySelector(
                            {selector_js}
                        );

                    if (!node) {{
                        return {{
                            found: false,
                            text: ''
                        }};
                    }}

                    return {{
                        found: true,
                        text: String(
                            node.value
                            || node.innerText
                            || node.textContent
                            || ''
                        ).trim()
                    }};
                }})()
                """
            )
            or {}
        )

        return {
            "found": bool(
                result.get(
                    "found"
                )
            ),
            "selector": selector,
            "text": str(
                result.get(
                    "text"
                )
                or ""
            ),
        }

    def clear_chat_search(
        self,
        *,
        timeout=3,
    ):
        """Vacía el buscador lateral mediante teclado CDP."""
        state = (
            self.get_chat_search_state()
        )

        if not state["found"]:
            return False

        # Si WhatsApp está en estado de búsqueda activa,
        # usamos exclusivamente el botón de cierre asociado
        # al MISMO contenedor del input de búsqueda.
        #
        # No usamos:
        #   button[aria-label="End icon button"]
        # de forma global, porque WhatsApp puede renderizar
        # otros botones equivalentes fuera del buscador.
        if state["text"]:
            close_selector = (
                '[data-qa-whatsapp-search-close="1"]'
            )

            try:
                marked = (
                    self.browser.evaluate(
                        """
                        (() => {
                            document
                                .querySelectorAll(
                                    '[data-qa-whatsapp-search-close]'
                                )
                                .forEach(
                                    node =>
                                        node.removeAttribute(
                                            'data-qa-whatsapp-search-close'
                                        )
                                );

                            const input =
                                document.querySelector(
                                    'input[role="textbox"]'
                                    + '[data-tab="3"]'
                                );

                            if (!input) {
                                return false;
                            }

                            let container =
                                input.parentElement;

                            for (
                                let depth = 0;
                                container && depth < 6;
                                depth += 1
                            ) {
                                const buttons =
                                    Array.from(
                                        container.querySelectorAll(
                                            'button'
                                        )
                                    );

                                const closeButton =
                                    buttons.find(
                                        button => {
                                            const aria =
                                                String(
                                                    button.getAttribute(
                                                        'aria-label'
                                                    )
                                                    || ''
                                                );

                                            const text =
                                                String(
                                                    button.innerText
                                                    || button.textContent
                                                    || ''
                                                );

                                            return (
                                                aria ===
                                                    'End icon button'
                                                && text.includes(
                                                    'ic-close'
                                                )
                                            );
                                        }
                                    );

                                if (closeButton) {
                                    closeButton.setAttribute(
                                        'data-qa-whatsapp-search-close',
                                        '1'
                                    );

                                    return true;
                                }

                                container =
                                    container.parentElement;
                            }

                            return false;
                        })()
                        """
                    )
                )
            except Exception:
                marked = False

            if marked:
                try:
                    close_button = (
                        self.browser.find_element(
                            close_selector
                        )
                    )
                except Exception:
                    close_button = None

                mouse_click = (
                    getattr(
                        close_button,
                        "mouse_click",
                        None,
                    )
                    if close_button
                    else None
                )

                if callable(
                    mouse_click
                ):

                    mouse_click()

                    deadline = (
                        time.time()
                        + max(
                            0.5,
                            float(timeout),
                        )
                    )

                    while time.time() < deadline:
                        current = (
                            self.get_chat_search_state()
                        )

                        if (
                            current["found"]
                            and not current["text"]
                        ):

                            try:
                                self.browser.evaluate(
                                    """
                                    (() => {
                                        document
                                            .querySelectorAll(
                                                '[data-qa-whatsapp-search-close]'
                                            )
                                            .forEach(
                                                node =>
                                                    node.removeAttribute(
                                                        'data-qa-whatsapp-search-close'
                                                    )
                                            );

                                        return true;
                                    })()
                                    """
                                )
                            except Exception:
                                pass

                            return True

                        time.sleep(
                            0.05
                        )

        # No confiamos únicamente en state["text"].
        # WhatsApp puede conservar contenido visible en
        # el contenteditable aunque su lectura textual
        # temporal no lo refleje como esperamos.
        #
        # Ctrl+A + Backspace también es seguro cuando
        # el buscador ya está vacío.
        selector = state["selector"]

        element = (
            self.browser.find_element(
                selector
            )
        )

        if not element:
            return False

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

        while time.time() < deadline:
            current = (
                self.get_chat_search_state()
            )

            if (
                current["found"]
                and not current["text"]
            ):
                return True

            time.sleep(0.05)

        # Fallback para el contenteditable de WhatsApp.
        # En algunas versiones Ctrl+A + Backspace modifica
        # la selección pero React conserva el texto visible.
        try:
            self.browser.evaluate(
                """
                (() => {
                    const node =
                        document.querySelector(%s);

                    if (!node) {
                        return false;
                    }

                    node.focus();

                    if (
                        node.isContentEditable
                        || node.getAttribute(
                            'contenteditable'
                        ) === 'true'
                    ) {
                        node.replaceChildren();

                        node.dispatchEvent(
                            new InputEvent(
                                'input',
                                {
                                    bubbles: true,
                                    inputType:
                                        'deleteContentBackward',
                                    data: null
                                }
                            )
                        );
                    } else {
                        node.value = '';

                        node.dispatchEvent(
                            new Event(
                                'input',
                                {
                                    bubbles: true
                                }
                            )
                        );
                    }

                    node.dispatchEvent(
                        new Event(
                            'change',
                            {
                                bubbles: true
                            }
                        )
                    );

                    return true;
                })()
                """
                % json.dumps(
                    selector
                )
            )
        except Exception:
            return False

        deadline = (
            time.time()
            + max(
                0.5,
                float(timeout),
            )
        )

        while time.time() < deadline:
            current = (
                self.get_chat_search_state()
            )

            if (
                current["found"]
                and not current["text"]
            ):
                return True

            time.sleep(
                0.05
            )

        return False

    def _get_fast_chat_routing_state(
        self,
    ):
        """Comprueba si puede iniciarse routing sin preparación pesada.

        FAST_ROUTE solo se permite cuando una única lectura DOM
        demuestra simultáneamente:

        - lista de chats presente;
        - buscador activo presente;
        - buscador vacío;
        - ningún diálogo abierto.

        Cualquier duda obliga al caller a usar SAFE_ROUTE.
        """
        if not self.browser:
            return {
                "ready": False,
                "reason": "BROWSER_NOT_STARTED",
                "selector": None,
                "text": "",
            }

        result = (
            self.browser.evaluate(
                """
                (() => {
                    const dialogs =
                        Array.from(
                            document.querySelectorAll(
                                '[role="dialog"]'
                            )
                        )
                        .filter(
                            node =>
                                node.getClientRects().length
                                > 0
                        );

                    if (dialogs.length) {
                        return {
                            ready: false,
                            reason: 'DIALOG_PRESENT',
                            selector: null,
                            text: ''
                        };
                    }

                    const grid =
                        document.querySelector(
                            '[aria-label="Lista de chats"]'
                        );

                    if (!grid) {
                        return {
                            ready: false,
                            reason: 'CHAT_LIST_NOT_FOUND',
                            selector: null,
                            text: ''
                        };
                    }

                    const input =
                        document.querySelector(
                            'input[role="textbox"]'
                            + '[data-tab="3"]'
                        );

                    if (!input) {
                        return {
                            ready: false,
                            reason: 'SEARCH_INPUT_NOT_FOUND',
                            selector: null,
                            text: ''
                        };
                    }

                    const text =
                        String(
                            input.value
                            || input.innerText
                            || input.textContent
                            || ''
                        ).trim();

                    if (text) {
                        return {
                            ready: false,
                            reason: 'SEARCH_NOT_EMPTY',
                            selector:
                                'input[role="textbox"][data-tab="3"]',
                            text: text
                        };
                    }

                    return {
                        ready: true,
                        reason: null,
                        selector:
                            'input[role="textbox"][data-tab="3"]',
                        text: ''
                    };
                })()
                """
            )
            or {}
        )

        return {
            "ready": bool(
                result.get(
                    "ready"
                )
            ),
            "reason": (
                str(
                    result.get(
                        "reason"
                    )
                    or ""
                ).strip()
                or None
            ),
            "selector": (
                str(
                    result.get(
                        "selector"
                    )
                    or ""
                ).strip()
                or None
            ),
            "text": str(
                result.get(
                    "text"
                )
                or ""
            ),
        }


    def _set_chat_search_value_fast(
        self,
        selector,
        value,
        *,
        timeout=0.5,
    ):
        """Actualiza el buscador mediante el setter nativo del input.

        Si React/WhatsApp no refleja exactamente el nuevo valor,
        devuelve False y el caller degrada a teclado CDP.
        """
        if not self.browser:
            return False

        selector = str(
            selector
            or ""
        ).strip()

        if not selector:
            return False

        value = str(
            value
            or ""
        )

        try:
            changed = (
                self.browser.evaluate(
                    """
                    (() => {
                        const selector = %s;
                        const value = %s;

                        const node =
                            document.querySelector(
                                selector
                            );

                        if (!node) {
                            return false;
                        }

                        node.focus();

                        const descriptor =
                            Object.getOwnPropertyDescriptor(
                                HTMLInputElement.prototype,
                                'value'
                            );

                        if (
                            descriptor
                            && descriptor.set
                        ) {
                            descriptor.set.call(
                                node,
                                value
                            );
                        } else {
                            node.value = value;
                        }

                        node.dispatchEvent(
                            new InputEvent(
                                'input',
                                {
                                    bubbles: true,
                                    inputType:
                                        value
                                        ? 'insertText'
                                        : 'deleteContentBackward',
                                    data:
                                        value
                                        ? value
                                        : null
                                }
                            )
                        );

                        node.dispatchEvent(
                            new Event(
                                'change',
                                {
                                    bubbles: true
                                }
                            )
                        );

                        return true;
                    })()
                    """
                    % (
                        json.dumps(
                            selector,
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            value,
                            ensure_ascii=False,
                        ),
                    )
                )
            )
        except Exception:
            return False

        if not changed:
            return False

        deadline = (
            time.time()
            + max(
                0.1,
                float(timeout),
            )
        )

        while time.time() < deadline:
            state = (
                self.get_chat_search_state()
            )

            if (
                state.get(
                    "found"
                )
                and str(
                    state.get(
                        "text"
                    )
                    or ""
                )
                == value
            ):
                return True

            time.sleep(
                0.02
            )

        return False


    def _request_chat_search_clear_fast(
        self,
        selector,
    ):
        """Solicita limpiar el buscador sin esperar confirmación.

        Este helper se usa únicamente DESPUÉS de haber abierto
        y validado correctamente el chat de destino.

        No bloquea esperando a que React termine de restaurar
        la lista normal.

        Seguridad:
        el siguiente routing ejecuta siempre
        _get_fast_chat_routing_state(). Si WhatsApp todavía
        no está limpio/listo, FAST_ROUTE será rechazado y el
        flujo degradará a SAFE_ROUTE.
        """
        selector = str(
            selector
            or ""
        ).strip()

        if (
            not self.browser
            or not selector
        ):
            return False

        try:
            changed = (
                self.browser.evaluate(
                    """
                    (() => {
                        const selector = %s;

                        const node =
                            document.querySelector(
                                selector
                            );

                        if (!node) {
                            return false;
                        }

                        node.focus();

                        const descriptor =
                            Object.getOwnPropertyDescriptor(
                                HTMLInputElement.prototype,
                                'value'
                            );

                        if (
                            descriptor
                            && descriptor.set
                        ) {
                            descriptor.set.call(
                                node,
                                ''
                            );
                        } else {
                            node.value = '';
                        }

                        node.dispatchEvent(
                            new InputEvent(
                                'input',
                                {
                                    bubbles: true,
                                    inputType:
                                        'deleteContentBackward',
                                    data: null
                                }
                            )
                        );

                        node.dispatchEvent(
                            new Event(
                                'change',
                                {
                                    bubbles: true
                                }
                            )
                        );

                        return true;
                    })()
                    """
                    % json.dumps(
                        selector,
                        ensure_ascii=False,
                    )
                )
            )

        except Exception:
            return False

        return bool(
            changed
        )


    def search_and_open_chat_by_phone(
        self,
        phone,
        *,
        expected_display_name=None,
        timeout=10,
    ):
        """Busca un teléfono dentro del WhatsApp ya abierto.

        No navega ni recarga web.whatsapp.com.
        """
        expected = normalize_phone(
            phone
        )

        if not expected.valid:
            raise ValueError(
                "Teléfono WhatsApp no válido"
            )

        display_hint = str(
            expected_display_name
            or ""
        ).strip()

        # Optimización de routing de selección.
        #
        # Evitamos clear + prepare únicamente cuando una sola
        # lectura DOM demuestra que la interfaz ya está en un
        # estado conocido y limpio.

        fast_state = (
            self._get_fast_chat_routing_state()
        )


        fast_route = bool(
            fast_state.get(
                "ready"
            )
        )

        if fast_route:

            search_state = {
                "found": True,
                "selector":
                    fast_state.get(
                        "selector"
                    ),
                "text": "",
            }

            selector = (
                fast_state.get(
                    "selector"
                )
            )

        else:
            print(
                "[WA-SEARCH] SAFE_ROUTE fallback "
                f"reason={ascii(fast_state.get('reason'))}",
                flush=True,
            )

            # Ruta conservadora histórica.


            pre_clear = (
                self.clear_chat_search()
            )



            if not pre_clear:
                return {
                    "opened": False,
                    "reason":
                        "CHAT_SEARCH_NOT_CLEAR",
                }



            prepared = (
                self.prepare_chat_interface()
            )



            if not prepared.get(
                "ready"
            ):
                return {
                    "opened": False,
                    "reason":
                        prepared.get(
                            "reason"
                        )
                        or "CHAT_INTERFACE_NOT_READY",
                }


            search_state = (
                self.get_chat_search_state()
            )


            if not search_state[
                "found"
            ]:
                return {
                    "opened": False,
                    "reason":
                        "CHAT_SEARCH_NOT_FOUND",
                }


            selector = (
                self._find_chat_search_selector()
            )


        if not selector:
            return {
                "opened": False,
                "reason":
                    "CHAT_SEARCH_NOT_FOUND",
            }

        # E.164 facilita búsqueda tanto de
        # contactos guardados como números sin guardar.


        fast_input = (
            self._set_chat_search_value_fast(
                selector,
                expected.e164,
                timeout=0.35,
            )
        )

        if not fast_input:
            # Fallback al comportamiento probado mediante
            # SeleniumBase/CDP.
            self.browser.send_keys(
                selector,
                expected.e164,
            )



        # WhatsApp virtualiza y reutiliza las filas del
        # listado lateral. No podemos localizar list-item-N
        # y volver a buscarlo posteriormente porque el mismo
        # identificador puede representar otro chat.
        #
        # Estrategia:
        # 1. JavaScript identifica la fila exacta.
        # 2. Marca temporalmente SU nodo clicable.
        # 3. SeleniumBase recupera ese mismo nodo marcado.
        # 4. mouse_click() genera la interacción real CDP.
        deadline = (
            time.time()
            + max(
                1,
                int(timeout),
            )
        )

        result_marked = False
        result_text = ""
        target_selector = (
            '[data-qa-whatsapp-routing-target="1"]'
        )

        while time.time() < deadline:
            candidate = (
                self.browser.evaluate(
                    """
                    (() => {
                        const expectedName = %s;
                        const expectedPhone = %s;

                        const normalize = value =>
                            String(value || '')
                                .replace(/\\s+/g, ' ')
                                .trim()
                                .toLocaleLowerCase();

                        const digits = value =>
                            String(value || '')
                                .replace(/\\D+/g, '');

                        const normalizedName =
                            normalize(expectedName);

                        const phoneDigits =
                            digits(expectedPhone);

                        document
                            .querySelectorAll(
                                '[data-qa-whatsapp-routing-target]'
                            )
                            .forEach(
                                node =>
                                    node.removeAttribute(
                                        'data-qa-whatsapp-routing-target'
                                    )
                            );

                        const rows = Array.from(
                            document.querySelectorAll(
                                '[role="row"][data-testid^="list-item-"]'
                            )
                        );

                        for (const row of rows) {
                            const rect =
                                row.getBoundingClientRect();

                            const style =
                                window.getComputedStyle(
                                    row
                                );

                            if (
                                rect.width <= 0
                                || rect.height <= 0
                                || style.display === 'none'
                                || style.visibility === 'hidden'
                            ) {
                                continue;
                            }

                            const titleNodes =
                                Array.from(
                                    row.querySelectorAll(
                                        '[title]'
                                    )
                                );

                            let matched = null;

                            if (normalizedName) {
                                matched = titleNodes.find(
                                    node =>
                                        normalize(
                                            node.getAttribute(
                                                'title'
                                            )
                                        )
                                        === normalizedName
                                );
                            }

                            if (
                                !matched
                                && phoneDigits
                            ) {
                                matched = titleNodes.find(
                                    node =>
                                        digits(
                                            node.getAttribute(
                                                'title'
                                            )
                                        )
                                        === phoneDigits
                                );
                            }

                            if (!matched) {
                                continue;
                            }

                            // La estructura visual de las filas
                            // de WhatsApp no es homogénea.
                            //
                            // cell-frame-container puede existir
                            // pero no ser el verdadero hit-target.
                            // Priorizamos las mismas superficies
                            // interactivas que ya utiliza open_chat().
                            // La fila puede estar materializada en el
                            // DOM pero fuera del viewport. Esto ocurre
                            // especialmente con resultados que conservan
                            // su posición virtual original.
                            row.scrollIntoView({
                                block: 'center',
                                inline: 'nearest'
                            });

                            // Priorizamos la superficie interactiva
                            // exterior completa de la fila. El gridcell
                            // cercano al título suele medir solo ~24 px
                            // y no es el hit-target más fiable.
                            const targetCandidates = [
                                row.querySelector(
                                    '[role="gridcell"][tabindex="0"]'
                                ),
                                row.querySelector(
                                    '[data-testid="cell-frame-container"]'
                                ),
                                row.querySelector(
                                    '[role="gridcell"]'
                                ),
                                row.querySelector(
                                    '[tabindex="0"]'
                                ),
                                (
                                    matched
                                    && matched.closest(
                                        '[role="gridcell"]'
                                    )
                                ),
                                row
                            ];

                            const target =
                                targetCandidates.find(
                                    node => Boolean(node)
                                );

                            if (!target) {
                                continue;
                            }

                            target.setAttribute(
                                'data-qa-whatsapp-routing-target',
                                '1'
                            );

                            const targetKind = (
                                target.getAttribute(
                                    'role'
                                )
                                || target.getAttribute(
                                    'data-testid'
                                )
                                || target.tagName
                                || 'UNKNOWN'
                            );

                            return {
                                marked: true,
                                target_kind:
                                    targetKind,
                                text: String(
                                    row.innerText
                                    || row.textContent
                                    || ''
                                ).trim()
                            };
                        }

                        return {
                            marked: false,
                            text: ''
                        };
                    })()
                    """
                    % (
                        json.dumps(
                            display_hint,
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            expected.e164,
                            ensure_ascii=False,
                        ),
                    )
                )
                or {}
            )

            if (
                isinstance(
                    candidate,
                    dict,
                )
                and candidate.get(
                    "marked"
                )
            ):
                result_marked = True

                result_text = str(
                    candidate.get(
                        "text"
                    )
                    or ""
                ).strip()

                break

            time.sleep(
                0.1
            )



        if not result_marked:
            try:
                self.clear_chat_search()
            except Exception:
                pass

            return {
                "opened": False,
                "reason":
                    "CHAT_SEARCH_NO_MATCHING_RESULT",
            }

        # B6 ya ha hecho scrollIntoView() y ha marcado
        # exactamente la superficie interactiva.
        #
        # Intentamos recuperar el WebElement inmediatamente.
        # Otros flujos del propio conector ya usan
        # find_element() -> mouse_click() sin espera fija.
        #
        # Solo si Selenium todavía no ve el nodo marcado damos
        # un pequeño margen de layout y repetimos UNA vez.

        try:
            result_element = (
                self.browser.find_element(
                    target_selector
                )
            )
        except Exception:
            result_element = None

        if not result_element:
            time.sleep(
                0.05
            )

            try:
                result_element = (
                    self.browser.find_element(
                        target_selector
                    )
                )
            except Exception:
                result_element = None


        if not result_element:
            try:
                self.clear_chat_search()
            except Exception:
                pass

            return {
                "opened": False,
                "reason":
                    "CHAT_SEARCH_MARKED_RESULT_NOT_FOUND",
            }

        mouse_click = getattr(
            result_element,
            "mouse_click",
            None,
        )

        if not callable(
            mouse_click
        ):
            try:
                self.clear_chat_search()
            except Exception:
                pass

            return {
                "opened": False,
                "reason":
                    "CHAT_SEARCH_RESULT_NO_MOUSE_CLICK",
            }


        # B7.3S · interacción primaria probada.
        #
        # El intento anterior emitía manualmente mousePressed +
        # mouseReleased mediante CDP. Aunque ambos eventos podían
        # emitirse correctamente, WhatsApp no siempre procesaba
        # esa secuencia como activación real de la fila.
        #
        # El retry histórico utiliza mouse_click() sobre un
        # WebElement recién localizado y ha demostrado ser la
        # interacción más fiable. Lo convertimos también en el
        # primer intento.
        #
        # Seguimos haciendo UN solo click antes de confirmar.
        # Si WhatsApp no cambia de chat, B8 re-localiza la fila
        # antes de permitir un segundo intento.
        primary_click_emitted = False

        try:
            mouse_click()
            primary_click_emitted = True

        except Exception as exc:
            print(
                "[WA-SEARCH] B7 primary mouse_click failed "
                f"{type(exc).__name__}",
                flush=True,
            )


        if not primary_click_emitted:
            # No hacemos un segundo click inmediato.
            #
            # La confirmación/retry conserva la barrera
            # histórica y volverá a localizar el nodo.
            print(
                "[WA-SEARCH] B7 primary click "
                "not emitted; confirmation/fallback required",
                flush=True,
            )

        # El marcador se mantiene hasta terminar la
        # confirmación de identidad.
        #
        # No participa en B8 y eliminarlo aquí introducía una
        # llamada CDP adicional en la ruta crítica.
        #
        # Si el primer click falla, el propio retry limpia
        # cualquier marcador antes de volver a localizar.
        # En todos los casos existe además un cleanup final
        # después de confirmación/retry.

        # Confirmamos que el chat REALMENTE cambió.
        #
        # El compositor no basta como señal porque puede seguir
        # presente mientras WhatsApp mantiene abierto el chat
        # anterior. La cabecera debe coincidir con el nombre o
        # teléfono esperado.
        expected_identity = (
            normalize_chat_identity(
                display_hint
            )
            if display_hint
            else ""
        )

        expected_phone_digits = (
            expected.digits
        )

        def wait_for_expected_chat(
            wait_seconds,
        ):
            deadline = (
                time.time()
                + max(
                    0.2,
                    float(wait_seconds),
                )
            )

            last_active_name = ""

            while time.time() < deadline:
                state = (
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
                                    || ''
                                ).trim()
                                : '';

                            return {
                                composer_found:
                                    Boolean(composer),
                                active_display_name:
                                    activeName
                            };
                        })()
                        """
                    )
                    or {}
                )

                composer_found = bool(
                    state.get(
                        "composer_found"
                    )
                )

                last_active_name = str(
                    state.get(
                        "active_display_name"
                    )
                    or ""
                ).strip()

                active_identity = (
                    normalize_chat_identity(
                        last_active_name
                    )
                )

                active_phone_digits = (
                    "".join(
                        char
                        for char in last_active_name
                        if char.isdigit()
                    )
                )

                name_matches = bool(
                    expected_identity
                    and active_identity
                    and (
                        active_identity
                        == expected_identity
                    )
                )

                phone_matches = bool(
                    expected_phone_digits
                    and active_phone_digits
                    and (
                        active_phone_digits
                        == expected_phone_digits
                    )
                )

                if (
                    composer_found
                    and (
                        name_matches
                        or phone_matches
                    )
                ):
                    return (
                        True,
                        last_active_name,
                    )

                time.sleep(
                    0.12
                )

            return (
                False,
                last_active_name,
            )

        # Primer click: normalmente WhatsApp responde casi
        # inmediatamente. No esperamos todo routing_timeout
        # antes de decidir si hace falta un retry.

        opened, active_display_name = (
            wait_for_expected_chat(
                min(
                    1.0,
                    max(
                        0.5,
                        float(timeout),
                    ),
                )
            )
        )


        retried = False

        if not opened:
            print(
                "[WA-SEARCH] B7.3 first click not confirmed "
                f"active={ascii(active_display_name)}",
                flush=True,
            )

            # WhatsApp puede ignorar ocasionalmente un
            # mouse_click aunque la fila estuviera bien
            # localizada. No reutilizamos el WebElement:
            # volvemos a localizar exactamente la misma fila
            # por nombre/teléfono porque el DOM puede haber
            # sido re-renderizado.
            retry_marked = (
                self.browser.evaluate(
                    """
                    (() => {
                        const expectedName = %s;
                        const expectedPhone = %s;

                        const normalize = value =>
                            String(value || '')
                                .replace(/\\s+/g, ' ')
                                .trim()
                                .toLocaleLowerCase();

                        const digits = value =>
                            String(value || '')
                                .replace(/\\D+/g, '');

                        const normalizedName =
                            normalize(expectedName);

                        const phoneDigits =
                            digits(expectedPhone);

                        document
                            .querySelectorAll(
                                '[data-qa-whatsapp-routing-target]'
                            )
                            .forEach(
                                node =>
                                    node.removeAttribute(
                                        'data-qa-whatsapp-routing-target'
                                    )
                            );

                        const rows = Array.from(
                            document.querySelectorAll(
                                '[role="row"][data-testid^="list-item-"]'
                            )
                        );

                        for (const row of rows) {
                            const titleNodes =
                                Array.from(
                                    row.querySelectorAll(
                                        '[title]'
                                    )
                                );

                            let matched = null;

                            if (normalizedName) {
                                matched = titleNodes.find(
                                    node =>
                                        normalize(
                                            node.getAttribute(
                                                'title'
                                            )
                                        )
                                        === normalizedName
                                );
                            }

                            if (
                                !matched
                                && phoneDigits
                            ) {
                                matched = titleNodes.find(
                                    node =>
                                        digits(
                                            node.getAttribute(
                                                'title'
                                            )
                                        )
                                        === phoneDigits
                                );
                            }

                            if (!matched) {
                                continue;
                            }

                            row.scrollIntoView({
                                block: 'center',
                                inline: 'nearest'
                            });

                            const target =
                                row.querySelector(
                                    '[role="gridcell"][tabindex="0"]'
                                )
                                || row.querySelector(
                                    '[data-testid="cell-frame-container"]'
                                )
                                || row;

                            if (!target) {
                                continue;
                            }

                            target.setAttribute(
                                'data-qa-whatsapp-routing-target',
                                '1'
                            );

                            return true;
                        }

                        return false;
                    })()
                    """
                    % (
                        json.dumps(
                            display_hint,
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            expected.e164,
                            ensure_ascii=False,
                        ),
                    )
                )
            )

            if retry_marked:
                # Dejamos que scrollIntoView complete el layout
                # antes de recuperar un WebElement nuevo.
                time.sleep(
                    0.15
                )

                try:
                    retry_element = (
                        self.browser.find_element(
                            target_selector
                        )
                    )
                except Exception:
                    retry_element = None

                retry_click = (
                    getattr(
                        retry_element,
                        "mouse_click",
                        None,
                    )
                    if retry_element
                    else None
                )

                if callable(
                    retry_click
                ):
                    retried = True



                    retry_click()




                    opened, active_display_name = (
                        wait_for_expected_chat(
                            min(
                                4.0,
                                max(
                                    1.5,
                                    float(timeout),
                                ),
                            )
                        )
                    )


        # El marcador únicamente sirve como puente temporal
        # entre JavaScript y SeleniumBase.
        #
        # Cleanup único: se realiza DESPUÉS de confirmar o
        # agotar el retry, nunca antes de B8.

        try:
            self.browser.evaluate(
                """
                (() => {
                    document
                        .querySelectorAll(
                            '[data-qa-whatsapp-routing-target]'
                        )
                        .forEach(
                            node =>
                                node.removeAttribute(
                                    'data-qa-whatsapp-routing-target'
                                )
                        );

                    return true;
                })()
                """
            )
        except Exception:
            pass



        # MUY IMPORTANTE:
        # el siguiente routing debe comenzar siempre con
        # el buscador vacío. El chat abierto se mantiene.
        try:

            cleared = (
                self._request_chat_search_clear_fast(
                    selector
                )
            )

            if not cleared:
                # Si ni siquiera pudimos solicitar el clear,
                # utilizamos inmediatamente el mecanismo
                # conservador histórico.
                cleared = (
                    self.clear_chat_search()
                )


        except Exception as exc:
            print(
                "[WA-SEARCH] B9 clear skipped "
                f"{type(exc).__name__}",
                flush=True,
            )

        return {
            "opened": opened,
            "reason": (
                None
                if opened
                else "CHAT_SEARCH_OPEN_TIMEOUT"
            ),
            "display_name":
                result_text,
        }

    def _verify_active_chat_phone(
        self,
        phone,
        *,
        timeout=10,
    ):
        """Verifica el teléfono del chat actualmente abierto."""
        expected = normalize_phone(
            phone
        )

        if not expected.valid:
            raise ValueError(
                "Teléfono WhatsApp no válido"
            )


        composer = (
            self.get_message_composer_state()
        )


        if not composer[
            "found"
        ]:
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
                    8,
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

            if kind not in (
                CHAT_KIND_INDIVIDUAL,
                CHAT_KIND_SELF,
            ):
                return {
                    "opened": True,
                    "verified": False,
                    "reason":
                        "NOT_SENDABLE_CHAT",
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
                        else "PHONE_MISMATCH"
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

    def open_chat_by_phone(
        self,
        phone,
        *,
        expected_display_name=None,
        verify_identity=True,
        timeout=15,
    ):
        """Abre un chat por teléfono sin recargar WhatsApp Web.

        Con verify_identity=False realiza navegación ligera
        mediante búsqueda y validación visual de la cabecera,
        sin abrir el perfil del contacto.

        Con verify_identity=True exige además verificación
        telefónica fuerte antes de considerar seguro el
        destinatario para operaciones sensibles.
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

        # En navegación ligera no abrimos el perfil.
        # La presencia del compositor únicamente permite
        # reutilizar el chat cuando el llamador no exige
        # verificación fuerte de identidad.
        if not verify_identity:

            composer = (
                self.get_message_composer_state()
            )


            if composer.get(
                "found"
            ) and expected_display_name:
                # No asumimos que el chat actual sea el
                # solicitado: seguimos por búsqueda para
                # hacer la navegación determinista.
                pass

        else:
            # Fast path seguro para operaciones sensibles:
            # verifica telefónicamente el chat actual.
            current = (
                self._verify_active_chat_phone(
                    expected.e164,
                    timeout=min(
                        5,
                        max(
                            1,
                            int(timeout),
                        ),
                    ),
                )
            )

            if current.get(
                "verified"
            ):
                current[
                    "navigation"
                ] = "CURRENT_CHAT"

                return current


        searched = (
            self.search_and_open_chat_by_phone(
                expected.e164,
                expected_display_name=(
                    expected_display_name
                ),
                timeout=timeout,
            )
        )


        if not searched.get(
            "opened"
        ):
            return {
                "opened": False,
                "verified": False,
                "reason":
                    searched.get(
                        "reason"
                    )
                    or "CHAT_SEARCH_FAILED",
                "expected_phone":
                    expected.e164,
                "observed_phone":
                    None,
                "navigation":
                    "CHAT_SEARCH",
            }

        if not verify_identity:
            return {
                "opened": True,
                "verified": False,
                "verification_skipped": True,
                "reason": None,
                "expected_phone":
                    expected.e164,
                "observed_phone":
                    None,
                "navigation":
                    "CHAT_SEARCH",
                "display_name":
                    searched.get(
                        "display_name"
                    ),
            }

        verified = (
            self._verify_active_chat_phone(
                expected.e164,
                timeout=min(
                    8,
                    max(
                        1,
                        int(timeout),
                    ),
                ),
            )
        )

        verified[
            "navigation"
        ] = "CHAT_SEARCH"

        return verified

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

        row_selector = (
            f'[data-testid="list-item-{position}"]'
        )

        candidate_selectors = (
            (
                row_selector
                + ' [role="gridcell"][tabindex="0"]'
            ),
            (
                row_selector
                + ' [role="gridcell"]'
            ),
            (
                row_selector
                + ' [tabindex="0"]'
            ),
            row_selector,
        )

        element = None
        selected_selector = None

        for selector in candidate_selectors:
            try:
                candidate = (
                    self.browser
                    .find_element(
                        selector
                    )
                )
            except Exception:
                candidate = None

            if candidate:
                element = candidate
                selected_selector = selector
                break


        if element is None:
            return {
                "opened": False,
                "composer_found": False,
                "composer_aria_label": None,
                "active_display_name": None,
                "main_text": None,
                "reason": "CHAT_ROW_NOT_FOUND",
            }

        mouse_click = getattr(
            element,
            "mouse_click",
            None,
        )

        click = getattr(
            element,
            "click",
            None,
        )

        if callable(
            mouse_click
        ):
            mouse_click()

        elif callable(
            click
        ):
            click()

        else:
            return {
                "opened": False,
                "composer_found": False,
                "composer_aria_label": None,
                "active_display_name": None,
                "main_text": None,
                "reason": "CHAT_ROW_NOT_CLICKABLE",
            }

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

    def get_active_chat_fingerprint(
        self,
    ):
        """Obtiene una huella barata del chat activo.

        Realiza una sola lectura DOM.

        No:
        - navega;
        - hace click;
        - abre perfiles;
        - escribe;
        - persiste;
        - extrae el contenido completo de los mensajes.
        """
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        result = (
            self.browser.evaluate(
                """
                (() => {
                    const main =
                        document.querySelector(
                            '#main'
                        );

                    const composer =
                        document.querySelector(
                            '[data-testid="conversation-compose-box-input"]'
                        );

                    const title =
                        document.querySelector(
                            '[data-testid="conversation-info-header-chat-title"]'
                        );

                    const activeDisplayName =
                        title
                        ? String(
                            title.innerText
                            || title.textContent
                            || ''
                        ).trim()
                        : '';

                    if (
                        !main
                        || !composer
                        || !title
                    ) {
                        return {
                            chat_open: false,
                            active_display_name:
                                activeDisplayName,
                            visible_message_count: 0,
                            last_provider_message_id:
                                null,
                            last_provider_message_status:
                                null
                        };
                    }

                    const messages =
                        Array.from(
                            main.querySelectorAll(
                                '[data-testid^="conv-msg-"]'
                            )
                        );

                    const lastMessage =
                        messages.length
                        ? messages[
                            messages.length - 1
                        ]
                        : null;

                    const rawLastTestId =
                        lastMessage
                        ? String(
                            lastMessage.getAttribute(
                                'data-testid'
                            )
                            || ''
                        )
                        : '';

                    const lastProviderMessageId =
                        rawLastTestId
                        ? rawLastTestId.replace(
                            /^conv-msg-/,
                            ''
                        )
                        : '';

                    // El cambio de ✓ a ✓✓ no modifica ni el
                    // provider id ni el número de mensajes.
                    //
                    // Leemos únicamente atributos aria del ÚLTIMO
                    // mensaje dentro de esta misma evaluate; no
                    // hacemos extracción completa del historial.
                    const lastAriaValues =
                        lastMessage
                        ? Array.from(
                            lastMessage.querySelectorAll(
                                '[aria-label]'
                            )
                        ).map(
                            node => String(
                                node.getAttribute(
                                    'aria-label'
                                )
                                || ''
                            )
                            .normalize('NFKC')
                            .trim()
                            .toLocaleLowerCase()
                        )
                        : [];

                    let lastProviderMessageStatus = null;

                    if (
                        lastAriaValues.some(
                            value =>
                                value === 'leído'
                                || value === 'leido'
                                || value === 'read'
                        )
                    ) {
                        lastProviderMessageStatus = 'READ';

                    } else if (
                        lastAriaValues.some(
                            value =>
                                value === 'entregado'
                                || value === 'delivered'
                        )
                    ) {
                        lastProviderMessageStatus = 'DELIVERED';

                    } else if (
                        lastAriaValues.some(
                            value =>
                                value === 'enviado'
                                || value === 'sent'
                        )
                    ) {
                        lastProviderMessageStatus = 'SENT';
                    }

                    return {
                        chat_open: true,
                        active_display_name:
                            activeDisplayName,
                        visible_message_count:
                            messages.length,
                        last_provider_message_id:
                            lastProviderMessageId
                            || null,
                        last_provider_message_status:
                            lastProviderMessageStatus
                    };
                })()
                """
            )
            or {}
        )

        chat_open = bool(
            result.get(
                "chat_open"
            )
        )

        active_display_name = str(
            result.get(
                "active_display_name"
            )
            or ""
        ).strip()

        return WhatsAppActiveChatFingerprint(
            chat_open=chat_open,
            active_display_name=(
                active_display_name
            ),
            active_identity=(
                normalize_chat_identity(
                    active_display_name
                )
                if active_display_name
                else ""
            ),
            visible_message_count=max(
                0,
                int(
                    result.get(
                        "visible_message_count"
                    )
                    or 0
                ),
            ),
            last_provider_message_id=(
                str(
                    result.get(
                        "last_provider_message_id"
                    )
                    or ""
                ).strip()
                or None
            ),
            last_provider_message_status=(
                str(
                    result.get(
                        "last_provider_message_status"
                    )
                    or ""
                ).strip().upper()
                or None
            ),
        )


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


        element = (
            self.browser.find_element(
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



        try:
            command = (
                cdp_input.insert_text(
                    value
                )
            )

            self.browser.loop.run_until_complete(
                element._tab.send(
                    command
                )
            )


        except Exception:
            # Input.insertText puede haber llegado a Chrome
            # antes de que la llamada Python falle.
            #
            # Nunca repetimos la escritura hasta comprobar
            # qué quedó realmente en el compositor.
            after_error = (
                self.get_message_composer_state()
            )

            if (
                after_error[
                    "text"
                ]
                == value
                and after_error[
                    "send_found"
                ]
            ):
                # Input.insertText pudo completarse antes
                # de que Python recibiera la excepción.
                # No repetimos la escritura.
                pass

            elif not after_error[
                "text"
            ]:
                # Solo existe fallback cuando sabemos que
                # CDP no dejó ningún contenido.
                self.browser.send_keys(
                    MESSAGE_COMPOSER_SELECTOR,
                    value,
                )


            else:
                # Contenido parcial/diferente = estado ambiguo.
                # No añadimos más texto automáticamente.
                raise RuntimeError(
                    "Estado incierto del compositor tras "
                    "Input.insertText; no se aplica fallback"
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

    def _dispatch_element_mouse_click_sequential(
        self,
        element,
    ):
        """Emite un click izquierdo CDP de forma secuencial.

        A diferencia de Element.mouse_click(), no usa:
        - flash_async;
        - create_task para pressed/released;
        - page.wait() genérico.

        Cada Input.dispatchMouseEvent debe ser confirmado por
        CDP antes de emitir el siguiente.

        No implica que la navegación haya tenido éxito:
        el caller debe validar después la identidad del chat.
        """
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        if not element:
            raise RuntimeError(
                "Elemento CDP no disponible"
            )



        position = (
            self.browser.loop.run_until_complete(
                element.get_position_async()
            )
        )

        if not position:
            raise RuntimeError(
                "No se pudo calcular posición CDP"
            )

        center = position.center

        if not center:
            raise RuntimeError(
                "No se pudo calcular centro CDP"
            )



        pressed = (
            cdp_input.dispatch_mouse_event(
                "mousePressed",
                x=float(
                    center[0]
                ),
                y=float(
                    center[1]
                ),
                modifiers=0,
                button=cdp_input.MouseButton(
                    "left"
                ),
                buttons=1,
                click_count=1,
            )
        )

        self.browser.loop.run_until_complete(
            element._tab.send(
                pressed
            )
        )



        released = (
            cdp_input.dispatch_mouse_event(
                "mouseReleased",
                x=float(
                    center[0]
                ),
                y=float(
                    center[1]
                ),
                modifiers=0,
                button=cdp_input.MouseButton(
                    "left"
                ),
                buttons=1,
                click_count=1,
            )
        )

        self.browser.loop.run_until_complete(
            element._tab.send(
                released
            )
        )



        return True


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

    def _dispatch_send_button_fast(
        self,
    ):
        """Intenta despachar un único click DOM en Enviar.

        Estados:

        DISPATCHED
            El click ya fue emitido. El caller NO puede
            reintentar automáticamente por ninguna vía.

        NOT_AVAILABLE
            No se emitió ningún click. El caller puede usar
            el mecanismo SeleniumBase conservador.

        La confirmación real del envío sigue dependiendo de
        la aparición posterior de un snapshot OUTBOUND nuevo.
        """
        if not self.browser:
            return {
                "status": "NOT_AVAILABLE",
                "reason": "BROWSER_NOT_STARTED",
            }

        try:
            result = (
                self.browser.evaluate(
                    """
                    (() => {
                        const selector = %s;

                        const node =
                            document.querySelector(
                                selector
                            );

                        if (!node) {
                            return {
                                status: 'NOT_AVAILABLE',
                                reason: 'SEND_BUTTON_NOT_FOUND'
                            };
                        }

                        const target =
                            node.closest('button')
                            || node;

                        const rect =
                            target.getBoundingClientRect();

                        const style =
                            window.getComputedStyle(
                                target
                            );

                        const visible =
                            rect.width > 0
                            && rect.height > 0
                            && style.display !== 'none'
                            && style.visibility !== 'hidden';

                        if (!visible) {
                            return {
                                status: 'NOT_AVAILABLE',
                                reason: 'SEND_BUTTON_NOT_VISIBLE'
                            };
                        }

                        const disabled =
                            target.disabled === true
                            || target.getAttribute(
                                'aria-disabled'
                            ) === 'true';

                        if (disabled) {
                            return {
                                status: 'NOT_AVAILABLE',
                                reason: 'SEND_BUTTON_DISABLED'
                            };
                        }

                        target.click();

                        return {
                            status: 'DISPATCHED',
                            reason: null
                        };
                    })()
                    """
                    % json.dumps(
                        MESSAGE_SEND_SELECTOR,
                        ensure_ascii=False,
                    )
                )
                or {}
            )

        except Exception as exc:
            # No sabemos si evaluate llegó a ejecutar click.
            # Por seguridad, una excepción es ambigua:
            # nunca debemos emitir un segundo click.
            raise WhatsAppSendStateUncertainError(
                "Estado de envío de WhatsApp incierto: "
                "falló el dispatch DOM del botón Enviar"
            ) from exc

        return {
            "status": str(
                result.get(
                    "status"
                )
                or "NOT_AVAILABLE"
            ),
            "reason": (
                str(
                    result.get(
                        "reason"
                    )
                    or ""
                ).strip()
                or None
            ),
        }


    def get_document_attachment_preview_state(
        self,
        *,
        expected_filename=None,
    ):
        """Inspecciona el preview actual de adjuntos.

        No modifica WhatsApp y nunca pulsa Enviar.
        """
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        filename = str(
            expected_filename
            or ""
        ).strip()

        result = (
            self.browser.evaluate(
                """
                (() => {
                    const expectedFilename = %s;

                    const root =
                        document.querySelector(
                            %s
                        );

                    if (!root) {
                        return {
                            preview_found: false,
                            filename_present: false,
                            document_labels: [],
                            caption_found: false,
                            remove_found: false,
                            add_found: false,
                            send_found: false,
                            send_aria_label: null,
                            selected_count: null
                        };
                    }

                    const caption =
                        root.querySelector(
                            %s
                        );

                    const remove =
                        root.querySelector(
                            %s
                        );

                    const add =
                        root.querySelector(
                            %s
                        );

                    const documentTabs =
                        Array.from(
                            root.querySelectorAll(
                                '[role="tab"][aria-label]'
                            )
                        )
                        .filter(
                            node => {
                                const label =
                                    String(
                                        node.getAttribute(
                                            'aria-label'
                                        )
                                        || ''
                                    );

                                return (
                                    label.includes(
                                        'Abrir documento'
                                    )
                                );
                            }
                        );

                    const documentLabels =
                        documentTabs.map(
                            node =>
                                String(
                                    node.getAttribute(
                                        'aria-label'
                                    )
                                    || ''
                                )
                        );

                    const filenamePresent =
                        expectedFilename
                        ? documentLabels.some(
                            label =>
                                label.includes(
                                    expectedFilename
                                )
                        )
                        : Boolean(
                            documentLabels.length
                        );

                    let send =
                        Array.from(
                            root.querySelectorAll(
                                '[role="button"][aria-label]'
                            )
                        )
                        .find(
                            node => {
                                const label =
                                    String(
                                        node.getAttribute(
                                            'aria-label'
                                        )
                                        || ''
                                    );

                                return (
                                    /^Enviar\\s+\\d+\\s+seleccionado/
                                        .test(
                                            label
                                        )
                                );
                            }
                        )
                        || null;

                    if (!send) {
                        const sendIcon =
                            root.querySelector(
                                '[data-testid="wds-ic-send-filled"]'
                            );

                        send =
                            sendIcon
                            ? sendIcon.closest(
                                '[role="button"]'
                            )
                            : null;
                    }

                    const sendLabel =
                        send
                        ? String(
                            send.getAttribute(
                                'aria-label'
                            )
                            || ''
                        )
                        : '';

                    const countMatch =
                        sendLabel.match(
                            /^Enviar\\s+(\\d+)/
                        );

                    const selectedCount =
                        countMatch
                        ? Number(
                            countMatch[1]
                        )
                        : null;

                    return {
                        preview_found:
                            Boolean(
                                root
                                && caption
                                && remove
                                && documentTabs.length
                            ),

                        filename_present:
                            filenamePresent,

                        document_labels:
                            documentLabels,

                        caption_found:
                            Boolean(
                                caption
                            ),

                        remove_found:
                            Boolean(
                                remove
                            ),

                        add_found:
                            Boolean(
                                add
                            ),

                        send_found:
                            Boolean(
                                send
                            ),

                        send_aria_label:
                            sendLabel || null,

                        selected_count:
                            selectedCount
                    };
                })()
                """
                % (
                    json.dumps(
                        filename,
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        WHATSAPP_ATTACHMENT_PREVIEW_SELECTOR,
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        WHATSAPP_ATTACHMENT_CAPTION_SELECTOR,
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        WHATSAPP_ATTACHMENT_REMOVE_SELECTOR,
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        WHATSAPP_ATTACHMENT_ADD_SELECTOR,
                        ensure_ascii=False,
                    ),
                )
            )
            or {}
        )

        if not isinstance(
            result,
            dict,
        ):
            result = {}

        return {
            "preview_found":
                bool(
                    result.get(
                        "preview_found"
                    )
                ),

            "filename_present":
                bool(
                    result.get(
                        "filename_present"
                    )
                ),

            "document_labels":
                list(
                    result.get(
                        "document_labels"
                    )
                    or []
                ),

            "caption_found":
                bool(
                    result.get(
                        "caption_found"
                    )
                ),

            "remove_found":
                bool(
                    result.get(
                        "remove_found"
                    )
                ),

            "add_found":
                bool(
                    result.get(
                        "add_found"
                    )
                ),

            "send_found":
                bool(
                    result.get(
                        "send_found"
                    )
                ),

            "send_aria_label":
                (
                    str(
                        result.get(
                            "send_aria_label"
                        )
                        or ""
                    ).strip()
                    or None
                ),

            "selected_count":
                (
                    int(
                        result[
                            "selected_count"
                        ]
                    )
                    if result.get(
                        "selected_count"
                    )
                    is not None
                    else None
                ),
        }

    def _install_document_input_click_interceptor(
        self,
    ):
        """Captura el input documental sin abrir FilePicker nativo.

        El interceptor afecta exclusivamente a:
            input[type=file][accept="*"][multiple]

        Debe restaurarse inmediatamente después de capturar
        el input creado por WhatsApp.
        """
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        result = (
            self.browser.evaluate(
                """
                (() => {
                    /* QA_WA_ATTACHMENT_INSTALL */

                    if (
                        window.__qaWaDocumentOriginalClick
                    ) {
                        return {
                            installed: false,
                            reason:
                                'INTERCEPTOR_ALREADY_INSTALLED'
                        };
                    }

                    document.querySelectorAll(
                        'input[type="file"]'
                        + '[data-qa-wa-document-input="1"]'
                    ).forEach(
                        node => {
                            try {
                                node.removeAttribute(
                                    'data-qa-wa-document-input'
                                );
                            } catch (_) {
                                // Cleanup best effort.
                            }
                        }
                    );

                    window.__qaWaDocumentOriginalClick =
                        HTMLInputElement.prototype.click;

                    window.__qaWaDocumentCaptured = [];

                    HTMLInputElement.prototype.click =
                        function(...args) {
                            const isDocumentInput = (
                                String(
                                    this.type
                                    || ''
                                ).toLowerCase()
                                === 'file'
                                && String(
                                    this.getAttribute(
                                        'accept'
                                    )
                                    || ''
                                )
                                === '*'
                                && Boolean(
                                    this.multiple
                                )
                            );

                            if (
                                isDocumentInput
                            ) {
                                this.setAttribute(
                                    'data-qa-wa-document-input',
                                    '1'
                                );

                                if (
                                    !window
                                        .__qaWaDocumentCaptured
                                        .includes(
                                            this
                                        )
                                ) {
                                    window
                                        .__qaWaDocumentCaptured
                                        .push(
                                            this
                                        );
                                }

                                // Deliberadamente:
                                // no abrimos el diálogo del SO.
                                return;
                            }

                            return window
                                .__qaWaDocumentOriginalClick
                                .apply(
                                    this,
                                    args
                                );
                        };

                    return {
                        installed: true,
                        reason: null
                    };
                })()
                """
            )
            or {}
        )

        if not isinstance(
            result,
            dict,
        ):
            result = {}

        if not result.get(
            "installed"
        ):
            raise RuntimeError(
                "No se pudo instalar el interceptor "
                "del input documental de WhatsApp"
            )

        return True

    def _restore_document_input_click_interceptor(
        self,
    ):
        """Restaura HTMLInputElement.click tras la captura."""
        if not self.browser:
            return False

        try:
            self.browser.evaluate(
                """
                (() => {
                    /* QA_WA_ATTACHMENT_RESTORE */

                    if (
                        window.__qaWaDocumentOriginalClick
                    ) {
                        HTMLInputElement.prototype.click =
                            window
                                .__qaWaDocumentOriginalClick;
                    }

                    const captured =
                        Array.isArray(
                            window.__qaWaDocumentCaptured
                        )
                        ? window
                            .__qaWaDocumentCaptured
                        : [];

                    captured.forEach(
                        node => {
                            try {
                                node.removeAttribute(
                                    'data-qa-wa-document-input'
                                );
                            } catch (_) {
                                // Cleanup best effort.
                            }
                        }
                    );

                    document.querySelectorAll(
                        'input[type="file"]'
                        + '[data-qa-wa-document-input="1"]'
                    ).forEach(
                        node => {
                            try {
                                node.removeAttribute(
                                    'data-qa-wa-document-input'
                                );
                            } catch (_) {
                                // Cleanup best effort.
                            }
                        }
                    );

                    delete window
                        .__qaWaDocumentCaptured;

                    delete window
                        .__qaWaDocumentOriginalClick;

                    return true;
                })()
                """
            )

        except Exception:
            return False

        return True

    def _get_captured_document_input_count(
        self,
    ):
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        result = (
            self.browser.evaluate(
                """
                (() => {
                    /* QA_WA_ATTACHMENT_COUNT */

                    const captured =
                        Array.isArray(
                            window.__qaWaDocumentCaptured
                        )
                        ? window
                            .__qaWaDocumentCaptured
                            .filter(
                                node => (
                                    Boolean(
                                        node
                                    )
                                    && Boolean(
                                        node.isConnected
                                    )
                                    && String(
                                        node.type
                                        || ''
                                    ).toLowerCase()
                                    === 'file'
                                    && String(
                                        node.getAttribute(
                                            'accept'
                                        )
                                        || ''
                                    )
                                    === '*'
                                    && Boolean(
                                        node.multiple
                                    )
                                    && node.getAttribute(
                                        'data-qa-wa-document-input'
                                    )
                                    === '1'
                                )
                            )
                        : [];

                    window.__qaWaDocumentCaptured =
                        captured;

                    return captured.length;
                })()
                """
            )
        )

        return int(
            result
            or 0
        )

    def stage_document_attachment(
        self,
        file_path,
        *,
        timeout=8,
    ):
        """Carga UN documento en el preview del chat activo.

        Esta operación:
        - valida el fichero local;
        - abre Adjuntar → Documento;
        - captura el input efímero de WhatsApp;
        - usa send_file() directamente sobre CDP;
        - confirma nombre y preview.

        Esta operación NO:
        - pulsa Enviar;
        - persiste información;
        - reintenta una carga incierta;
        - depende de automatización GUI del escritorio;
        - usa el FilePicker nativo del navegador.
        """
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        path = Path(
            file_path
        ).expanduser()

        try:
            path = path.resolve(
                strict=True
            )
        except Exception as exc:
            raise FileNotFoundError(
                "El archivo adjunto no existe"
            ) from exc

        if not path.is_file():
            raise ValueError(
                "La ruta del adjunto no es un archivo"
            )

        file_name = (
            path.name
        )

        file_size = int(
            path.stat().st_size
        )

        active = (
            self.get_active_chat_fingerprint()
        )

        if not active.chat_open:
            raise RuntimeError(
                "No hay un chat WhatsApp activo"
            )

        initial_preview = (
            self.get_document_attachment_preview_state()
        )

        if initial_preview[
            "preview_found"
        ]:
            raise RuntimeError(
                "Ya existe un preview de adjunto "
                "abierto en WhatsApp"
            )

        self._install_document_input_click_interceptor()

        captured_element = None

        try:
            try:
                attach_button = (
                    self.browser.find_element(
                        WHATSAPP_ATTACH_BUTTON_SELECTOR
                    )
                )
            except Exception as exc:
                raise RuntimeError(
                    "Botón Adjuntar de WhatsApp "
                    "no localizado"
                ) from exc

            if not attach_button:
                raise RuntimeError(
                    "Botón Adjuntar de WhatsApp "
                    "no localizado"
                )

            attach_click = getattr(
                attach_button,
                "mouse_click",
                None,
            )

            if not callable(
                attach_click
            ):
                raise RuntimeError(
                    "Botón Adjuntar de WhatsApp "
                    "no soporta mouse_click"
                )

            attach_error = None

            try:
                attach_click()
            except Exception as exc:
                # No repetimos automáticamente:
                # el menú podría haberse abierto ya.
                attach_error = exc

            deadline = (
                time.time()
                + max(
                    1.0,
                    float(timeout),
                )
            )

            document_button = None

            while (
                time.time()
                < deadline
            ):
                try:
                    document_button = (
                        self.browser.find_element(
                            WHATSAPP_DOCUMENT_ATTACH_SELECTOR
                        )
                    )
                except Exception:
                    document_button = None

                if document_button:
                    break

                time.sleep(
                    0.05
                )

            if not document_button:
                if attach_error:
                    raise RuntimeError(
                        "WhatsApp no confirmó la apertura "
                        "del menú Adjuntar"
                    ) from attach_error

                raise RuntimeError(
                    "Menuitem Documento de WhatsApp "
                    "no localizado"
                )

            document_click = getattr(
                document_button,
                "mouse_click",
                None,
            )

            if not callable(
                document_click
            ):
                raise RuntimeError(
                    "Menuitem Documento de WhatsApp "
                    "no soporta mouse_click"
                )

            document_error = None

            try:
                document_click()
            except Exception as exc:
                # Igual que arriba:
                # no emitimos un segundo click a ciegas.
                document_error = exc

            captured_count = 0

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
                captured_count = (
                    self
                    ._get_captured_document_input_count()
                )

                if captured_count:
                    break

                time.sleep(
                    0.05
                )

            if captured_count != 1:
                if document_error:
                    raise RuntimeError(
                        "WhatsApp no confirmó la creación "
                        "del input documental"
                    ) from document_error

                raise RuntimeError(
                    "Número ambiguo de inputs "
                    "documentales de WhatsApp: "
                    f"{captured_count}"
                )

            try:
                captured_element = (
                    self.browser.find_element(
                        WHATSAPP_DOCUMENT_CAPTURE_SELECTOR
                    )
                )
            except Exception as exc:
                raise RuntimeError(
                    "Input documental capturado "
                    "no localizado"
                ) from exc

            if not captured_element:
                raise RuntimeError(
                    "Input documental capturado "
                    "no localizado"
                )

        finally:
            # Barrera crítica:
            # la mutación de prototype nunca debe sobrevivir
            # a la fase de captura.
            self._restore_document_input_click_interceptor()

        send_file = getattr(
            captured_element,
            "send_file",
            None,
        )

        if not callable(
            send_file
        ):
            raise RuntimeError(
                "El input documental no soporta send_file"
            )

        load_error = None

        try:
            send_file(
                str(
                    path
                )
            )

        except Exception as exc:
            # send_file pudo llegar a Chrome antes de que
            # Python recibiera la excepción.
            #
            # Nunca cargamos otra vez sin inspeccionar
            # primero el preview.
            load_error = exc

        deadline = (
            time.time()
            + max(
                1.0,
                float(timeout),
            )
        )

        preview = {}

        while (
            time.time()
            < deadline
        ):
            preview = (
                self
                .get_document_attachment_preview_state(
                    expected_filename=file_name,
                )
            )

            if (
                preview[
                    "preview_found"
                ]
                and preview[
                    "filename_present"
                ]
                and preview[
                    "send_found"
                ]
            ):
                return {
                    "staged": True,
                    "filename":
                        file_name,
                    "size":
                        file_size,
                    "active_display_name":
                        active.active_display_name,
                    "preview":
                        preview,
                    "load_error_reconciled":
                        bool(
                            load_error
                        ),
                }

            time.sleep(
                0.1
            )

        if load_error:
            raise WhatsAppAttachmentStageStateUncertainError(
                "Estado de carga de adjunto incierto: "
                "send_file produjo una excepción y "
                "WhatsApp no confirmó el preview"
            ) from load_error

        raise WhatsAppAttachmentStageStateUncertainError(
            "Estado de carga de adjunto incierto: "
            "WhatsApp no confirmó el preview "
            "del archivo dentro del timeout"
        )

    def send_document_attachment(
        self,
        file_path,
        *,
        timeout=12,
    ):
        """Envía UN documento al chat activo con confirmación fuerte.

        Contrato de seguridad:
        - fija los provider IDs existentes antes del staging;
        - fija la identidad del chat antes del staging;
        - reutiliza stage_document_attachment();
        - exige preview + filename + un único seleccionado;
        - revalida el destinatario inmediatamente antes del click;
        - emite exactamente un click de envío;
        - nunca reintenta el click;
        - confirma mediante un nuevo snapshot OUTBOUND DOCUMENT
          cuyo filename coincide exactamente con el solicitado.

        Una vez emitido el click, cualquier resultado no confirmable
        se considera estado incierto y nunca provoca retry.
        """
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        path = Path(
            file_path
        ).expanduser()

        try:
            path = path.resolve(
                strict=True
            )
        except Exception as exc:
            raise FileNotFoundError(
                "El archivo adjunto no existe"
            ) from exc

        if not path.is_file():
            raise ValueError(
                "La ruta del adjunto no es un archivo"
            )

        filename = path.name

        active_before = (
            self.get_active_chat_fingerprint()
        )

        if not active_before.chat_open:
            raise RuntimeError(
                "No hay un chat WhatsApp activo"
            )

        expected_identity = str(
            active_before.active_identity
            or ""
        ).strip()

        if not expected_identity:
            raise RuntimeError(
                "No se pudo fijar la identidad "
                "del destinatario"
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

        staged = (
            self.stage_document_attachment(
                path,
                timeout=timeout,
            )
        )

        preview = (
            staged.get(
                "preview"
            )
            or {}
        )

        if not staged.get(
            "staged"
        ):
            raise RuntimeError(
                "WhatsApp no confirmó el staging "
                "del documento"
            )

        if (
            str(
                staged.get(
                    "filename"
                )
                or ""
            )
            != filename
        ):
            raise RuntimeError(
                "El filename staged no coincide "
                "con el archivo solicitado"
            )

        if not preview.get(
            "preview_found"
        ):
            raise RuntimeError(
                "WhatsApp no confirmó el preview "
                "del documento"
            )

        if not preview.get(
            "filename_present"
        ):
            raise RuntimeError(
                "WhatsApp no confirmó el filename "
                "en el preview"
            )

        if not preview.get(
            "send_found"
        ):
            raise RuntimeError(
                "WhatsApp no confirmó el botón "
                "de envío del preview"
            )

        if preview.get(
            "selected_count"
        ) != 1:
            raise RuntimeError(
                "El preview no contiene exactamente "
                "un documento seleccionado"
            )

        send_aria_label = str(
            preview.get(
                "send_aria_label"
            )
            or ""
        ).strip()

        if (
            send_aria_label
            != "Enviar 1 seleccionado"
        ):
            raise RuntimeError(
                "Semántica inesperada del botón "
                "de envío del preview"
            )

        try:
            send_button = (
                self.browser.find_element(
                    WHATSAPP_ATTACHMENT_SEND_ONE_SELECTOR
                )
            )
        except Exception as exc:
            raise RuntimeError(
                "Botón de envío del documento "
                "no localizado"
            ) from exc

        if not send_button:
            raise RuntimeError(
                "Botón de envío del documento "
                "no localizado"
            )

        send_click = getattr(
            send_button,
            "mouse_click",
            None,
        )

        if not callable(
            send_click
        ):
            raise RuntimeError(
                "Botón de envío del documento "
                "no soporta mouse_click"
            )

        # Última barrera inmediatamente antes
        # de cruzar el punto irreversible.
        active_pre_send = (
            self.get_active_chat_fingerprint()
        )

        if not active_pre_send.chat_open:
            raise RuntimeError(
                "No se puede revalidar el chat "
                "antes de enviar"
            )

        actual_identity = str(
            active_pre_send.active_identity
            or ""
        ).strip()

        if (
            not actual_identity
            or actual_identity
            != expected_identity
        ):
            raise RuntimeError(
                "El destinatario cambió durante "
                "el staging; envío cancelado"
            )

        # ====================================================
        # PUNTO IRREVERSIBLE
        #
        # Este método realiza EXACTAMENTE un intento de click.
        # Una excepción no autoriza un segundo click porque
        # el evento pudo haber llegado ya a WhatsApp.
        # ====================================================

        click_error = None

        try:
            send_click()

        except Exception as exc:
            click_error = exc

        deadline = (
            time.time()
            + max(
                0.05,
                float(
                    timeout
                ),
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

            matches = [
                item
                for item in current
                if (
                    item.provider_message_id
                    and item.provider_message_id
                    not in before_ids
                    and item.direction
                    == MESSAGE_DIRECTION_OUTBOUND
                    and item.message_type
                    == MESSAGE_TYPE_DOCUMENT
                    and str(
                        (
                            item.metadata
                            or {}
                        ).get(
                            "filename"
                        )
                        or ""
                    )
                    == filename
                )
            ]

            if len(
                matches
            ) == 1:
                return matches[0]

            if len(
                matches
            ) > 1:
                raise WhatsAppSendStateUncertainError(
                    "Estado de envío incierto: "
                    "aparecieron múltiples documentos "
                    "OUTBOUND nuevos con el mismo filename"
                )

            time.sleep(
                0.05
            )

        if click_error:
            raise WhatsAppSendStateUncertainError(
                "Estado de envío incierto: "
                "el click produjo una excepción y "
                "WhatsApp no permitió confirmar "
                "el documento OUTBOUND"
            ) from click_error

        raise WhatsAppSendStateUncertainError(
            "Estado de envío incierto: "
            "el click fue emitido pero WhatsApp "
            "no permitió confirmar exactamente "
            "un documento OUTBOUND nuevo"
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


        # Primero intentamos lookup + click en una sola
        # operación DOM.
        #
        # Solo usamos SeleniumBase si sabemos con certeza
        # que NO se emitió ningún click.

        fast_dispatch = (
            self._dispatch_send_button_fast()
        )

        if (
            fast_dispatch.get(
                "status"
            )
            != "DISPATCHED"
        ):
            # Ningún click fue emitido por FAST_DOM.
            # Podemos degradar con seguridad al mecanismo
            # histórico probado.

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
                # Exactamente la misma semántica histórica:
                # una excepción después de intentar click
                # es ambigua y jamás se reintenta.
                raise WhatsAppSendStateUncertainError(
                    "Estado de envío de WhatsApp incierto: "
                    "falló la operación de click"
                ) from exc

        confirm_attempts = 0

        # Backoff corto al principio:
        # los mensajes normales suelen materializarse
        # rápidamente. Tras los primeros intentos,
        # convergemos al polling conservador histórico
        # de 100 ms.
        confirm_poll_delays = (
            0.02,
            0.025,
            0.035,
            0.05,
            0.075,
            0.1,
        )

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
            confirm_attempts += 1


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

            delay_index = min(
                max(
                    0,
                    confirm_attempts - 1,
                ),
                len(
                    confirm_poll_delays
                )
                - 1,
            )

            remaining = (
                deadline
                - time.time()
            )

            if remaining <= 0:
                break

            time.sleep(
                min(
                    confirm_poll_delays[
                        delay_index
                    ],
                    remaining,
                )
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

                    const allRoots =
                        Array.from(
                            main.querySelectorAll(
                                '[data-testid^="conv-msg-"]'
                            )
                        );

                    // WA-UX-PERF-14C1:
                    // limitar ANTES de extraer contenido pesado.
                    //
                    // Conserva exactamente los últimos N mensajes,
                    // pero evita recorrer nodos que después serían
                    // descartados en Python.
                    const roots =
                        allRoots.slice(
                            -__WA_MESSAGE_LIMIT__
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

                            // WhatsApp representa una respuesta
                            // mediante un bloque semántico:
                            //
                            //   [data-testid="quoted-message"]
                            //
                            // El selectable-text de la cita NO forma
                            // parte del body real de la respuesta.
                            const quotedMessage =
                                root.querySelector(
                                    '[data-testid="quoted-message"]'
                                );

                            const quotedSelectableNodes =
                                quotedMessage
                                ? Array.from(
                                    quotedMessage.querySelectorAll(
                                        '[data-testid="selectable-text"]'
                                    )
                                )
                                : [];

                            const quotedBodyText =
                                quotedSelectableNodes
                                .map(
                                    contentFromNode
                                )
                                .filter(Boolean)
                                .join('\\n')
                                .trim();

                            const bodySelectableNodes =
                                selectableNodes.filter(
                                    node =>
                                        !node.closest(
                                            '[data-testid="quoted-message"]'
                                        )
                                );

                            const bodyText =
                                bodySelectableNodes
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

                            const documentThumb =
                                root.querySelector(
                                    '[data-testid="document-thumb"]'
                                );

                            const imageThumb =
                                root.querySelector(
                                    '[data-testid="image-thumb"]'
                                    + '[aria-label="Abrir foto"]'
                                );

                            const documentFilename =
                                documentThumb
                                ? (
                                    Array.from(
                                        documentThumb.querySelectorAll(
                                            'span[dir="auto"]'
                                        )
                                    )
                                    .map(
                                        node =>
                                            String(
                                                node.textContent
                                                || ''
                                            ).trim()
                                    )
                                    .find(Boolean)
                                    || ''
                                )
                                : '';

                            const documentSizeNode =
                                documentThumb
                                ? (
                                    Array.from(
                                        documentThumb.querySelectorAll(
                                            '[title]'
                                        )
                                    )
                                    .find(
                                        node => {
                                            const value =
                                                String(
                                                    node.getAttribute(
                                                        'title'
                                                    )
                                                    || ''
                                                ).trim();

                                            return (
                                                /^\d+(?:[.,]\d+)?\s*(?:B|KB|MB|GB|TB)$/i
                                                    .test(
                                                        value
                                                    )
                                            );
                                        }
                                    )
                                    || null
                                )
                                : null;

                            const documentSizeText =
                                documentSizeNode
                                ? String(
                                    documentSizeNode.getAttribute(
                                        'title'
                                    )
                                    || ''
                                ).trim()
                                : '';

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

                                has_document:
                                    Boolean(
                                        documentThumb
                                    ),

                                has_image:
                                    Boolean(
                                        imageThumb
                                    ),

                                document_filename:
                                    documentFilename
                                    || null,

                                document_size_text:
                                    documentSizeText
                                    || null,

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
                                    reactionLabels,

                                has_quoted_message:
                                    Boolean(
                                        quotedMessage
                                    ),

                                quoted_body_text:
                                    quotedBodyText
                            };
                        }
                    );
                })()
                """.replace(
                    "__WA_MESSAGE_LIMIT__",
                    str(
                        effective_limit
                    ),
                )
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

            elif raw.get(
                "has_document"
            ):
                message_type = (
                    MESSAGE_TYPE_DOCUMENT
                )

            elif raw.get(
                "has_image"
            ):
                message_type = (
                    MESSAGE_TYPE_IMAGE
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

            if message_type == MESSAGE_TYPE_DOCUMENT:
                document_filename = str(
                    raw.get(
                        "document_filename"
                    )
                    or ""
                ).strip()

                document_size_text = str(
                    raw.get(
                        "document_size_text"
                    )
                    or ""
                ).strip()

                if document_filename:
                    metadata[
                        "filename"
                    ] = (
                        document_filename
                    )

                if document_size_text:
                    metadata[
                        "file_size_text"
                    ] = (
                        document_size_text
                    )

            if bool(
                raw.get(
                    "has_quoted_message"
                )
            ):
                quoted_body_text = str(
                    raw.get(
                        "quoted_body_text"
                    )
                    or ""
                ).strip()

                metadata[
                    "reply"
                ] = {
                    # WhatsApp confirma semánticamente que
                    # existe una cita mediante quoted-message.
                    #
                    # No inventamos todavía autor ni id del
                    # mensaje citado si el DOM no los expone
                    # de forma estable.
                    "provider_message_id":
                        None,
                    "sender":
                        None,
                    "body_text":
                        quoted_body_text,
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

    def download_visible_document(
        self,
        provider_message_id,
        *,
        download_dir,
        timeout=30,
    ):
        """Descarga UN documento visible del chat activo.

        Contrato:
        - localiza el mensaje por provider_message_id;
        - rechaza documentos fallidos o todavía cargando;
        - abre el visor documental;
        - configura la carpeta de descarga gobernada;
        - pulsa Descargar exactamente una vez;
        - espera al archivo final, nunca devuelve .tmp;
        - restaura la política de descarga del navegador;
        - no persiste información.
        """
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        normalized_provider_id = str(
            provider_message_id
            or ""
        ).strip()

        if not normalized_provider_id:
            raise ValueError(
                "provider_message_id es obligatorio"
            )

        target_dir = Path(
            download_dir
        ).expanduser()

        target_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        target_dir = target_dir.resolve()

        page = getattr(
            self.browser,
            "page",
            None,
        )

        loop = getattr(
            self.browser,
            "loop",
            None,
        )

        send = getattr(
            page,
            "send",
            None,
        )

        run_until_complete = getattr(
            loop,
            "run_until_complete",
            None,
        )

        if (
            not callable(send)
            or not callable(
                run_until_complete
            )
        ):
            raise RuntimeError(
                "Transporte CDP de descarga "
                "no disponible"
            )

        active = (
            self.get_active_chat_fingerprint()
        )

        if not active.chat_open:
            raise RuntimeError(
                "No hay un chat WhatsApp activo"
            )

        before = {}

        for file_path in target_dir.iterdir():
            if not file_path.is_file():
                continue

            try:
                stat = file_path.stat()
            except OSError:
                continue

            before[str(file_path)] = (
                int(stat.st_size),
                int(stat.st_mtime_ns),
            )

        run_until_complete(
            send(
                cdp_browser
                .set_download_behavior(
                    behavior="allow",
                    download_path=str(
                        target_dir
                    ),
                    events_enabled=True,
                )
            )
        )

        viewer_opened = False

        try:
            provider_js = repr(
                normalized_provider_id
            )

            open_result = (
                self.browser.evaluate(
                    """
                    (() => {
                        const providerId = %s;

                        const root =
                            Array.from(
                                document
                                .querySelectorAll(
                                    '#main '
                                    + '[data-testid^="conv-msg-"]'
                                )
                            )
                            .find(
                                node =>
                                    node.getAttribute(
                                        'data-testid'
                                    )
                                    === (
                                        'conv-msg-'
                                        + providerId
                                    )
                            );

                        if (!root) {
                            return {
                                opened: false,
                                reason:
                                    'MESSAGE_NOT_VISIBLE'
                            };
                        }

                        if (
                            root.querySelector(
                                '[data-testid="fail-container"]'
                            )
                        ) {
                            return {
                                opened: false,
                                reason:
                                    'DOCUMENT_FAILED'
                            };
                        }

                        if (
                            root.querySelector(
                                '[data-testid="loading-spinner"]'
                            )
                        ) {
                            return {
                                opened: false,
                                reason:
                                    'DOCUMENT_LOADING'
                            };
                        }

                        const thumb =
                            root.querySelector(
                                '[data-testid="document-thumb"]'
                            );

                        if (!thumb) {
                            return {
                                opened: false,
                                reason:
                                    'DOCUMENT_NOT_FOUND'
                            };
                        }

                        const title =
                            String(
                                thumb.getAttribute(
                                    'title'
                                )
                                || ''
                            ).trim();

                        if (
                            !title.startsWith(
                                'Ver '
                            )
                        ) {
                            return {
                                opened: false,
                                reason:
                                    'DOCUMENT_NOT_READY',
                                title
                            };
                        }

                        let filename = title;

                        const match =
                            title.match(
                                /^Ver\\s+"([\\s\\S]*)"$/
                            );

                        if (
                            match
                            && match[1]
                        ) {
                            filename =
                                match[1];
                        }

                        thumb.click();

                        return {
                            opened: true,
                            reason: null,
                            filename
                        };
                    })()
                    """
                    % provider_js
                )
                or {}
            )

            if not open_result.get(
                "opened"
            ):
                reason = str(
                    open_result.get(
                        "reason"
                    )
                    or "DOCUMENT_OPEN_FAILED"
                )

                raise RuntimeError(
                    "No se pudo abrir el "
                    "documento WhatsApp "
                    f"({reason})"
                )

            viewer_opened = True

            expected_filename = str(
                open_result.get(
                    "filename"
                )
                or ""
            ).strip()

            deadline = (
                time.time()
                + max(
                    1,
                    float(
                        timeout
                    ),
                )
            )

            while (
                time.time()
                < deadline
            ):
                ready = (
                    self.browser.evaluate(
                        """
                        (() => Boolean(
                            document.querySelector(
                                'button'
                                + '[aria-label="Descargar"]'
                            )
                        ))()
                        """
                    )
                )

                if ready:
                    break

                time.sleep(
                    0.1
                )
            else:
                raise RuntimeError(
                    "El visor de WhatsApp "
                    "no mostró Descargar"
                )

            clicked = (
                self.browser.evaluate(
                    """
                    (() => {
                        const button =
                            document.querySelector(
                                'button'
                                + '[aria-label="Descargar"]'
                            );

                        if (!button) {
                            return false;
                        }

                        button.click();

                        return true;
                    })()
                    """
                )
            )

            if not clicked:
                raise RuntimeError(
                    "No se pudo pulsar "
                    "Descargar en WhatsApp"
                )

            downloaded = None

            deadline = (
                time.time()
                + max(
                    1,
                    float(
                        timeout
                    ),
                )
            )

            while (
                time.time()
                < deadline
            ):
                candidates = []

                for file_path in (
                    target_dir.iterdir()
                ):
                    if not file_path.is_file():
                        continue

                    if (
                        file_path.suffix.lower()
                        in (
                            ".tmp",
                            ".crdownload",
                        )
                    ):
                        continue

                    try:
                        stat = (
                            file_path.stat()
                        )
                    except OSError:
                        continue

                    current = (
                        int(
                            stat.st_size
                        ),
                        int(
                            stat.st_mtime_ns
                        ),
                    )

                    if (
                        before.get(
                            str(
                                file_path
                            )
                        )
                        == current
                    ):
                        continue

                    if (
                        current[0]
                        <= 0
                    ):
                        continue

                    candidates.append(
                        (
                            current[1],
                            file_path,
                            current[0],
                        )
                    )

                if candidates:
                    candidates.sort(
                        key=lambda item:
                            item[0],
                        reverse=True,
                    )

                    _, candidate, size_1 = (
                        candidates[0]
                    )

                    time.sleep(
                        0.2
                    )

                    try:
                        size_2 = int(
                            candidate.stat()
                            .st_size
                        )
                    except OSError:
                        size_2 = -1

                    if (
                        size_1 > 0
                        and size_1
                        == size_2
                    ):
                        downloaded = (
                            candidate
                        )
                        break

                time.sleep(
                    0.1
                )

            if downloaded is None:
                raise RuntimeError(
                    "La descarga WhatsApp "
                    "no alcanzó un archivo final"
                )

            return {
                "provider_message_id": (
                    normalized_provider_id
                ),
                "expected_filename": (
                    expected_filename
                    or None
                ),
                "filename": (
                    downloaded.name
                ),
                "file_path": str(
                    downloaded
                ),
                "size_bytes": int(
                    downloaded.stat()
                    .st_size
                ),
            }

        finally:
            if viewer_opened:
                try:
                    self.browser.evaluate(
                        """
                        (() => {
                            const button =
                                document.querySelector(
                                    'button'
                                    + '[aria-label="Cerrar"]'
                                );

                            if (!button) {
                                return false;
                            }

                            button.click();

                            return true;
                        })()
                        """
                    )
                except Exception:
                    pass

            try:
                run_until_complete(
                    send(
                        cdp_browser
                        .set_download_behavior(
                            behavior="default",
                        )
                    )
                )
            except Exception:
                pass


    def download_visible_image(
        self,
        provider_message_id,
        *,
        download_dir,
        timeout=30,
    ):
        """Descarga UNA foto visible del chat activo.

        Contrato:
        - localiza el mensaje por provider_message_id;
        - exige image-thumb / Abrir foto;
        - abre el visor multimedia;
        - descarga mediante CDP a la carpeta gobernada;
        - nunca devuelve .tmp/.crdownload;
        - restaura la política de descarga;
        - no persiste ni importa directamente.
        """
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        normalized_provider_id = str(
            provider_message_id
            or ""
        ).strip()

        if not normalized_provider_id:
            raise ValueError(
                "provider_message_id es obligatorio"
            )

        target_dir = Path(
            download_dir
        ).expanduser()

        target_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        target_dir = target_dir.resolve()

        page = getattr(
            self.browser,
            "page",
            None,
        )

        loop = getattr(
            self.browser,
            "loop",
            None,
        )

        send = getattr(
            page,
            "send",
            None,
        )

        run_until_complete = getattr(
            loop,
            "run_until_complete",
            None,
        )

        if (
            not callable(send)
            or not callable(
                run_until_complete
            )
        ):
            raise RuntimeError(
                "Transporte CDP de descarga "
                "no disponible"
            )

        active = (
            self.get_active_chat_fingerprint()
        )

        if not active.chat_open:
            raise RuntimeError(
                "No hay un chat WhatsApp activo"
            )

        before = {}

        for file_path in target_dir.iterdir():
            if not file_path.is_file():
                continue

            try:
                stat = file_path.stat()
            except OSError:
                continue

            before[str(file_path)] = (
                int(stat.st_size),
                int(stat.st_mtime_ns),
            )

        run_until_complete(
            send(
                cdp_browser
                .set_download_behavior(
                    behavior="allow",
                    download_path=str(
                        target_dir
                    ),
                    events_enabled=True,
                )
            )
        )

        viewer_opened = False

        try:
            provider_js = repr(
                normalized_provider_id
            )

            open_result = (
                self.browser.evaluate(
                    """
                    (() => {
                        const providerId = %s;

                        const root =
                            Array.from(
                                document
                                .querySelectorAll(
                                    '#main '
                                    + '[data-testid^="conv-msg-"]'
                                )
                            )
                            .find(
                                node =>
                                    node.getAttribute(
                                        'data-testid'
                                    )
                                    === (
                                        'conv-msg-'
                                        + providerId
                                    )
                            );

                        if (!root) {
                            return {
                                opened: false,
                                reason:
                                    'MESSAGE_NOT_VISIBLE'
                            };
                        }

                        if (
                            root.querySelector(
                                '[data-testid="fail-container"]'
                            )
                        ) {
                            return {
                                opened: false,
                                reason:
                                    'IMAGE_FAILED'
                            };
                        }

                        if (
                            root.querySelector(
                                '[data-testid="loading-spinner"]'
                            )
                        ) {
                            return {
                                opened: false,
                                reason:
                                    'IMAGE_LOADING'
                            };
                        }

                        const thumb =
                            root.querySelector(
                                '[data-testid="image-thumb"]'
                                + '[aria-label="Abrir foto"]'
                            );

                        if (!thumb) {
                            return {
                                opened: false,
                                reason:
                                    'IMAGE_NOT_FOUND'
                            };
                        }

                        thumb.click();

                        return {
                            opened: true,
                            reason: null
                        };
                    })()
                    """
                    % provider_js
                )
                or {}
            )

            if not open_result.get(
                "opened"
            ):
                reason = str(
                    open_result.get(
                        "reason"
                    )
                    or "IMAGE_OPEN_FAILED"
                )

                raise RuntimeError(
                    "No se pudo abrir la "
                    "imagen WhatsApp "
                    f"({reason})"
                )

            viewer_opened = True

            deadline = (
                time.time()
                + max(
                    1,
                    float(
                        timeout
                    ),
                )
            )

            while time.time() < deadline:
                ready = bool(
                    self.browser.evaluate(
                        """
                        (() => Boolean(
                            document.querySelector(
                                'button'
                                + '[aria-label="Descargar"]'
                            )
                        ))()
                        """
                    )
                )

                if ready:
                    break

                time.sleep(
                    0.1
                )

            else:
                raise RuntimeError(
                    "El visor de imagen WhatsApp "
                    "no mostró Descargar"
                )

            clicked = bool(
                self.browser.evaluate(
                    """
                    (() => {
                        const button =
                            document.querySelector(
                                'button'
                                + '[aria-label="Descargar"]'
                            );

                        if (!button) {
                            return false;
                        }

                        button.click();

                        return true;
                    })()
                    """
                )
            )

            if not clicked:
                raise RuntimeError(
                    "No se pudo pulsar Descargar "
                    "en la imagen WhatsApp"
                )

            downloaded = None

            deadline = (
                time.time()
                + max(
                    1,
                    float(
                        timeout
                    ),
                )
            )

            while time.time() < deadline:
                candidates = []

                for file_path in (
                    target_dir.iterdir()
                ):
                    if not file_path.is_file():
                        continue

                    if (
                        file_path.suffix.lower()
                        in (
                            ".tmp",
                            ".crdownload",
                        )
                    ):
                        continue

                    try:
                        stat = (
                            file_path.stat()
                        )
                    except OSError:
                        continue

                    current = (
                        int(
                            stat.st_size
                        ),
                        int(
                            stat.st_mtime_ns
                        ),
                    )

                    if (
                        before.get(
                            str(
                                file_path
                            )
                        )
                        == current
                    ):
                        continue

                    if current[0] <= 0:
                        continue

                    candidates.append(
                        (
                            current[1],
                            file_path,
                            current[0],
                        )
                    )

                if candidates:
                    candidates.sort(
                        key=lambda item:
                            item[0],
                        reverse=True,
                    )

                    _, candidate, size_1 = (
                        candidates[0]
                    )

                    time.sleep(
                        0.2
                    )

                    try:
                        size_2 = int(
                            candidate.stat()
                            .st_size
                        )
                    except OSError:
                        size_2 = -1

                    if (
                        size_1 > 0
                        and size_1 == size_2
                    ):
                        downloaded = candidate
                        break

                time.sleep(
                    0.1
                )

            if downloaded is None:
                raise RuntimeError(
                    "La descarga de imagen WhatsApp "
                    "no alcanzó un archivo final"
                )

            return {
                "provider_message_id":
                    normalized_provider_id,
                "media_type":
                    "IMAGE",
                "expected_filename":
                    None,
                "filename":
                    downloaded.name,
                "file_path":
                    str(
                        downloaded
                    ),
                "size_bytes":
                    int(
                        downloaded.stat()
                        .st_size
                    ),
            }

        finally:
            if viewer_opened:
                try:
                    self.browser.evaluate(
                        """
                        (() => {
                            const button =
                                document.querySelector(
                                    'button'
                                    + '[aria-label="Cerrar"]'
                                );

                            if (!button) {
                                return false;
                            }

                            button.click();

                            return true;
                        })()
                        """
                    )
                except Exception:
                    pass

            try:
                run_until_complete(
                    send(
                        cdp_browser
                        .set_download_behavior(
                            behavior="default",
                        )
                    )
                )
            except Exception:
                pass


    def download_today_documents_from_media_hub(
        self,
        *,
        download_dir,
        timeout=30,
        max_documents=100,
    ):
        """Descarga todos los documentos de HOY del Media Hub global.

        Fuente:
        - Media Hub global de WhatsApp;
        - pestaña Documentos;
        - filas cronológicas más recientes.

        Selección:
        - fecha visible = Hoy;
        - cualquier remitente;
        - cualquier conversación del Media Hub.

        No persiste información.
        El destino debe ser resuelto por Runtime.
        """
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        limit = max(
            1,
            int(
                max_documents
            ),
        )

        per_document_timeout = max(
            1.0,
            float(
                timeout
            ),
        )

        target_dir = Path(
            download_dir
        ).expanduser()

        target_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        target_dir = (
            target_dir.resolve()
        )

        page = getattr(
            self.browser,
            "page",
            None,
        )

        loop = getattr(
            self.browser,
            "loop",
            None,
        )

        send = getattr(
            page,
            "send",
            None,
        )

        run_until_complete = getattr(
            loop,
            "run_until_complete",
            None,
        )

        if (
            not callable(
                send
            )
            or not callable(
                run_until_complete
            )
        ):
            raise RuntimeError(
                "Transporte CDP de descarga "
                "no disponible"
            )

        active = (
            self.get_active_chat_fingerprint()
        )

        if not active.chat_open:
            prepared = (
                self.prepare_chat_interface()
            )

            if (
                isinstance(
                    prepared,
                    dict,
                )
                and not prepared.get(
                    "ready",
                    True,
                )
            ):
                raise RuntimeError(
                    "La lista de chats WhatsApp "
                    "no está disponible"
                )

            snapshots = (
                self.list_visible_chat_snapshots(
                    viewport_only=True,
                )
            )

            if not snapshots:
                snapshots = (
                    self.list_visible_chat_snapshots(
                        viewport_only=False,
                    )
                )

            if not snapshots:
                raise RuntimeError(
                    "No hay conversaciones WhatsApp "
                    "disponibles para abrir "
                    "Contenido multimedia"
                )

            fallback = snapshots[0]

            if (
                fallback.virtual_offset
                is not None
            ):
                routing = (
                    self.open_chat_by_virtual_offset(
                        fallback.virtual_offset,
                        expected_display_name=(
                            fallback.display_name
                        ),
                        timeout=min(
                            15,
                            max(
                                1,
                                int(
                                    per_document_timeout
                                ),
                            ),
                        ),
                    )
                )

            else:
                routing = (
                    self.open_chat(
                        fallback.position,
                        expected_display_name=(
                            fallback.display_name
                        ),
                        timeout=min(
                            15,
                            max(
                                1,
                                int(
                                    per_document_timeout
                                ),
                            ),
                        ),
                    )
                )

            if not routing.get(
                "opened"
            ):
                raise RuntimeError(
                    "No se pudo abrir una conversación "
                    "WhatsApp para acceder al Media Hub "
                    f"({routing.get('reason') or 'CHAT_OPEN_FAILED'})"
                )

            active = (
                self.get_active_chat_fingerprint()
            )

            if not active.chat_open:
                raise RuntimeError(
                    "WhatsApp no confirmó el chat "
                    "abierto para acceder al Media Hub"
                )

        downloaded_items = []
        skipped_items = []
        errors = []

        scanned = 0
        matched = 0

        processed_keys = set()

        hub_open = False
        download_behavior_enabled = False


        def snapshot_files():
            snapshot = {}

            for file_path in (
                target_dir.iterdir()
            ):
                if not file_path.is_file():
                    continue

                try:
                    stat = (
                        file_path.stat()
                    )
                except OSError:
                    continue

                snapshot[
                    str(
                        file_path
                    )
                ] = (
                    int(
                        stat.st_size
                    ),
                    int(
                        stat.st_mtime_ns
                    ),
                )

            return snapshot


        def changed_final_file(
            before,
        ):
            candidates = []

            for file_path in (
                target_dir.iterdir()
            ):
                if not file_path.is_file():
                    continue

                if (
                    file_path.suffix.lower()
                    in (
                        ".tmp",
                        ".crdownload",
                    )
                ):
                    continue

                try:
                    stat = (
                        file_path.stat()
                    )
                except OSError:
                    continue

                current = (
                    int(
                        stat.st_size
                    ),
                    int(
                        stat.st_mtime_ns
                    ),
                )

                if (
                    before.get(
                        str(
                            file_path
                        )
                    )
                    == current
                ):
                    continue

                if current[0] <= 0:
                    continue

                candidates.append(
                    (
                        current[1],
                        file_path,
                        current[0],
                    )
                )

            if not candidates:
                return None

            candidates.sort(
                key=lambda item:
                    item[0],
                reverse=True,
            )

            _, candidate, size_1 = (
                candidates[0]
            )

            time.sleep(
                0.2
            )

            try:
                size_2 = int(
                    candidate.stat()
                    .st_size
                )
            except OSError:
                return None

            if (
                size_1 <= 0
                or size_1
                != size_2
            ):
                return None

            return candidate


        def close_document_viewer():
            try:
                return bool(
                    self.browser.evaluate(
                        """
                        (() => {
                            const download =
                                document.querySelector(
                                    'button'
                                    + '[aria-label="Descargar"]'
                                );

                            if (!download) {
                                return false;
                            }

                            const dialog =
                                download.closest(
                                    '[role="dialog"]'
                                );

                            const close =
                                dialog
                                ? dialog.querySelector(
                                    'button'
                                    + '[aria-label="Cerrar"]'
                                  )
                                : null;

                            if (!close) {
                                return false;
                            }

                            close.click();

                            return true;
                        })()
                        """
                    )
                )
            except Exception:
                return False


        def read_rows():
            return (
                self.browser.evaluate(
                    """
                    (() => {
                        const clean = value =>
                            String(
                                value || ''
                            )
                            .replace(
                                /\\s+/g,
                                ' '
                            )
                            .trim();

                        const mediaRows =
                            Array.from(
                                document
                                .querySelectorAll(
                                    '[data-testid='
                                    + '"media-hub-list-row"]'
                                )
                            );

                        const rows =
                            mediaRows.map(
                                mediaRow => {
                                    const item =
                                        mediaRow.closest(
                                            '[role="listitem"]'
                                        );

                                    const text =
                                        clean(
                                            (
                                                item
                                                || mediaRow
                                            ).innerText
                                        );

                                    const itemId =
                                        clean(
                                            item
                                            ?.getAttribute(
                                                'data-testid'
                                            )
                                        );

                                    const viewer =
                                        mediaRow
                                        .querySelector(
                                            '[role="button"]'
                                            + '[title^="Ver "]'
                                        );

                                    const title =
                                        clean(
                                            viewer
                                            ?.getAttribute(
                                                'title'
                                            )
                                        );

                                    let filename = '';

                                    const match =
                                        title.match(
                                            /^Ver\\s+"([\\s\\S]*)"$/
                                        );

                                    if (
                                        match
                                        && match[1]
                                    ) {
                                        filename =
                                            match[1];
                                    }

                                    return {
                                        key:
                                            itemId,

                                        text,

                                        today:
                                            /(^|\\s)Hoy(\\s|$)/i
                                            .test(
                                                text
                                            ),

                                        expected_filename:
                                            filename
                                            || null,
                                    };
                                }
                            );

                        const first =
                            mediaRows[0]
                            || null;

                        let scroller =
                            first;

                        while (scroller) {
                            const style =
                                getComputedStyle(
                                    scroller
                                );

                            if (
                                scroller.scrollHeight
                                > (
                                    scroller.clientHeight
                                    + 5
                                )
                                && (
                                    style.overflowY
                                    === 'auto'
                                    || style.overflowY
                                    === 'scroll'
                                )
                            ) {
                                break;
                            }

                            scroller =
                                scroller.parentElement;
                        }

                        return {
                            rows,

                            scroll_top:
                                scroller
                                ? scroller.scrollTop
                                : null,

                            scroll_height:
                                scroller
                                ? scroller.scrollHeight
                                : null,

                            client_height:
                                scroller
                                ? scroller.clientHeight
                                : null,
                        };
                    })()
                    """
                )
                or {}
            )


        def scroll_next_page():
            return (
                self.browser.evaluate(
                    """
                    (() => {
                        const first =
                            document.querySelector(
                                '[data-testid='
                                + '"media-hub-list-row"]'
                            );

                        if (!first) {
                            return {
                                moved: false,
                                reason:
                                    'ROW_MISSING'
                            };
                        }

                        let scroller =
                            first;

                        while (scroller) {
                            const style =
                                getComputedStyle(
                                    scroller
                                );

                            if (
                                scroller.scrollHeight
                                > (
                                    scroller.clientHeight
                                    + 5
                                )
                                && (
                                    style.overflowY
                                    === 'auto'
                                    || style.overflowY
                                    === 'scroll'
                                )
                            ) {
                                break;
                            }

                            scroller =
                                scroller.parentElement;
                        }

                        if (!scroller) {
                            return {
                                moved: false,
                                reason:
                                    'SCROLLER_MISSING'
                            };
                        }

                        const before =
                            scroller.scrollTop;

                        const step =
                            Math.max(
                                300,
                                Math.floor(
                                    scroller.clientHeight
                                    * 0.8
                                )
                            );

                        scroller.scrollTop =
                            Math.min(
                                scroller.scrollHeight
                                - scroller.clientHeight,
                                before + step
                            );

                        return {
                            moved:
                                scroller.scrollTop
                                > before + 1,

                            before,

                            after:
                                scroller.scrollTop,
                        };
                    })()
                    """
                )
                or {}
            )


        def open_and_download_row(
            row,
        ):
            nonlocal download_behavior_enabled

            row_key = str(
                row.get(
                    "key"
                )
                or ""
            ).strip()

            if not row_key:
                raise RuntimeError(
                    "MEDIA_ROW_ID_MISSING"
                )

            if not download_behavior_enabled:
                run_until_complete(
                    send(
                        cdp_browser
                        .set_download_behavior(
                            behavior="allow",
                            download_path=str(
                                target_dir
                            ),
                            events_enabled=True,
                        )
                    )
                )

                download_behavior_enabled = True

            before = (
                snapshot_files()
            )

            row_key_js = repr(
                row_key
            )

            opened = (
                self.browser.evaluate(
                    """
                    (() => {
                        const itemId = %s;

                        const item =
                            Array.from(
                                document
                                .querySelectorAll(
                                    '[role="listitem"]'
                                )
                            )
                            .find(
                                node =>
                                    node.getAttribute(
                                        'data-testid'
                                    )
                                    === itemId
                            );

                        if (!item) {
                            return {
                                opened: false,
                                reason:
                                    'ROW_NOT_RENDERED'
                            };
                        }

                        const mediaRow =
                            item.querySelector(
                                '[data-testid='
                                + '"media-hub-list-row"]'
                            );

                        if (!mediaRow) {
                            return {
                                opened: false,
                                reason:
                                    'MEDIA_ROW_MISSING'
                            };
                        }

                        const titled =
                            mediaRow.querySelector(
                                '[role="button"]'
                                + '[title^="Ver "]'
                            );

                        const childButton =
                            mediaRow.querySelector(
                                '[role="button"]'
                            );

                        const parentButton =
                            mediaRow.closest(
                                '[role="button"]'
                            );

                        const target =
                            titled
                            || childButton
                            || parentButton
                            || mediaRow;

                        target.click();

                        return {
                            opened: true
                        };
                    })()
                    """
                    % row_key_js
                )
                or {}
            )

            if not opened.get(
                "opened"
            ):
                raise RuntimeError(
                    str(
                        opened.get(
                            "reason"
                        )
                        or "MEDIA_ROW_OPEN_FAILED"
                    )
                )

            deadline = (
                time.time()
                + per_document_timeout
            )

            viewer_ready = False
            downloaded = None

            # Algunos tipos podrían descargar directamente.
            # Otros abren primero el visor documental.
            while time.time() < deadline:
                downloaded = (
                    changed_final_file(
                        before
                    )
                )

                if downloaded is not None:
                    break

                viewer_ready = bool(
                    self.browser.evaluate(
                        """
                        (() => Boolean(
                            document.querySelector(
                                'button'
                                + '[aria-label="Descargar"]'
                            )
                        ))()
                        """
                    )
                )

                if viewer_ready:
                    break

                time.sleep(
                    0.1
                )

            if (
                downloaded is None
                and not viewer_ready
            ):
                raise RuntimeError(
                    "MEDIA_DOCUMENT_VIEWER_TIMEOUT"
                )

            if (
                downloaded is None
                and viewer_ready
            ):
                clicked = bool(
                    self.browser.evaluate(
                        """
                        (() => {
                            const button =
                                document.querySelector(
                                    'button'
                                    + '[aria-label="Descargar"]'
                                );

                            if (!button) {
                                return false;
                            }

                            button.click();

                            return true;
                        })()
                        """
                    )
                )

                if not clicked:
                    raise RuntimeError(
                        "MEDIA_DOCUMENT_DOWNLOAD_CLICK_FAILED"
                    )

                deadline = (
                    time.time()
                    + per_document_timeout
                )

                while time.time() < deadline:
                    downloaded = (
                        changed_final_file(
                            before
                        )
                    )

                    if downloaded is not None:
                        break

                    time.sleep(
                        0.1
                    )

            if downloaded is None:
                raise RuntimeError(
                    "MEDIA_DOCUMENT_DOWNLOAD_TIMEOUT"
                )

            return {
                "row_key": row_key,
                "expected_filename": (
                    row.get(
                        "expected_filename"
                    )
                ),
                "filename": (
                    downloaded.name
                ),
                "file_path": str(
                    downloaded
                ),
                "size_bytes": int(
                    downloaded.stat()
                    .st_size
                ),
                "row_text": (
                    row.get(
                        "text"
                    )
                ),
            }


        try:
            # ==============================================
            # 1. ABRIR MEDIA HUB
            # ==============================================

            existing_hub = bool(
                self.browser.evaluate(
                    """
                    (() => Boolean(
                        document.querySelector(
                            '[data-testid='
                            + '"media-hub-modal"]'
                        )
                    ))()
                    """
                )
            )

            if not existing_hub:
                entry = (
                    self.browser.evaluate(
                        """
                        (() => {
                            const visible = el => {
                                if (!el) {
                                    return false;
                                }

                                const style =
                                    getComputedStyle(
                                        el
                                    );

                                const rect =
                                    el
                                    .getBoundingClientRect();

                                return (
                                    style.display
                                    !== 'none'
                                    && style.visibility
                                    !== 'hidden'
                                    && rect.width > 0
                                    && rect.height > 0
                                );
                            };

                            const media =
                                Array.from(
                                    document
                                    .querySelectorAll(
                                        '[aria-label='
                                        + '"Contenido multimedia"]'
                                    )
                                )
                                .find(
                                    visible
                                );

                            if (media) {
                                media.click();

                                return {
                                    clicked: true,
                                    strategy:
                                        'DIRECT_MEDIA'
                                };
                            }

                            const info =
                                document.querySelector(
                                    '[data-testid='
                                    + '"conversation-info-header"]'
                                )
                                || document.querySelector(
                                    '[aria-label='
                                    + '"Información del perfil"]'
                                );

                            if (!info) {
                                return {
                                    clicked: false,
                                    reason:
                                        'INFO_ENTRY_MISSING'
                                };
                            }

                            info.click();

                            return {
                                clicked: true,
                                strategy:
                                    'OPEN_INFO'
                            };
                        })()
                        """
                    )
                    or {}
                )

                if not entry.get(
                    "clicked"
                ):
                    raise RuntimeError(
                        "No se pudo abrir "
                        "Contenido multimedia "
                        f"({entry.get('reason')})"
                    )

                if (
                    entry.get(
                        "strategy"
                    )
                    == "OPEN_INFO"
                ):
                    deadline = (
                        time.time()
                        + min(
                            15.0,
                            per_document_timeout,
                        )
                    )

                    media_visible = False

                    while time.time() < deadline:
                        media_visible = bool(
                            self.browser.evaluate(
                                """
                                (() => {
                                    const visible = el => {
                                        if (!el) {
                                            return false;
                                        }

                                        const style =
                                            getComputedStyle(
                                                el
                                            );

                                        const rect =
                                            el
                                            .getBoundingClientRect();

                                        return (
                                            style.display
                                            !== 'none'
                                            && style.visibility
                                            !== 'hidden'
                                            && rect.width > 0
                                            && rect.height > 0
                                        );
                                    };

                                    return Array.from(
                                        document
                                        .querySelectorAll(
                                            '[aria-label='
                                            + '"Contenido multimedia"]'
                                        )
                                    ).some(
                                        visible
                                    );
                                })()
                                """
                            )
                        )

                        if media_visible:
                            break

                        time.sleep(
                            0.1
                        )

                    if not media_visible:
                        raise RuntimeError(
                            "Contenido multimedia "
                            "no apareció"
                        )

                    clicked = bool(
                        self.browser.evaluate(
                            """
                            (() => {
                                const visible = el => {
                                    if (!el) {
                                        return false;
                                    }

                                    const style =
                                        getComputedStyle(
                                            el
                                        );

                                    const rect =
                                        el
                                        .getBoundingClientRect();

                                    return (
                                        style.display
                                        !== 'none'
                                        && style.visibility
                                        !== 'hidden'
                                        && rect.width > 0
                                        && rect.height > 0
                                    );
                                };

                                const media =
                                    Array.from(
                                        document
                                        .querySelectorAll(
                                            '[aria-label='
                                            + '"Contenido multimedia"]'
                                        )
                                    )
                                    .find(
                                        visible
                                    );

                                if (!media) {
                                    return false;
                                }

                                media.click();

                                return true;
                            })()
                            """
                        )
                    )

                    if not clicked:
                        raise RuntimeError(
                            "No se pudo pulsar "
                            "Contenido multimedia"
                        )

            deadline = (
                time.time()
                + min(
                    15.0,
                    per_document_timeout,
                )
            )

            while time.time() < deadline:
                hub_open = bool(
                    self.browser.evaluate(
                        """
                        (() => Boolean(
                            document.querySelector(
                                '[data-testid='
                                + '"media-hub-modal"]'
                            )
                        ))()
                        """
                    )
                )

                if hub_open:
                    break

                time.sleep(
                    0.1
                )

            if not hub_open:
                raise RuntimeError(
                    "Media Hub no apareció"
                )

            # ==============================================
            # 2. PESTAÑA DOCUMENTOS
            # ==============================================

            docs_clicked = bool(
                self.browser.evaluate(
                    """
                    (() => {
                        const tab =
                            document.querySelector(
                                '[data-testid='
                                + '"tab-docs"]'
                            );

                        if (!tab) {
                            return false;
                        }

                        if (
                            tab.getAttribute(
                                'aria-selected'
                            )
                            !== 'true'
                        ) {
                            tab.click();
                        }

                        return true;
                    })()
                    """
                )
            )

            if not docs_clicked:
                raise RuntimeError(
                    "Pestaña Documentos "
                    "no disponible"
                )

            # La selección de tab precede a la carga
            # de filas virtualizadas aproximadamente 1 s.
            deadline = (
                time.time()
                + min(
                    15.0,
                    per_document_timeout,
                )
            )

            initial_state = {}

            while time.time() < deadline:
                initial_state = (
                    read_rows()
                )

                if (
                    initial_state.get(
                        "rows"
                    )
                ):
                    break

                time.sleep(
                    0.2
                )

            rows = (
                initial_state.get(
                    "rows"
                )
                or []
            )

            # Cuenta sin documentación o sin filas recientes.
            if not rows:
                return {
                    "scope":
                        "MEDIA_HUB",

                    "date_scope":
                        "TODAY",

                    "direction_scope":
                        "ALL",

                    "scanned": 0,
                    "matched": 0,
                    "downloaded": 0,
                    "skipped": [],
                    "errors": [],
                    "items": [],
                }

            # Orden descendente: si la primera fila
            # no es Hoy, no existe ningún documento
            # de Hoy más abajo.
            if not bool(
                rows[0].get(
                    "today"
                )
            ):
                return {
                    "scope":
                        "MEDIA_HUB",

                    "date_scope":
                        "TODAY",

                    "direction_scope":
                        "ALL",

                    "scanned": 0,
                    "matched": 0,
                    "downloaded": 0,
                    "skipped": [],
                    "errors": [],
                    "items": [],
                }

            # ==============================================
            # 3. TODOS LOS DOCUMENTOS DE HOY · VENTANA VIRTUAL
            # ==============================================

            while True:
                state = (
                    read_rows()
                )

                rows = (
                    state.get(
                        "rows"
                    )
                    or []
                )

                if not rows:
                    break

                reached_older_day = False

                for row in rows:
                    row_key = str(
                        row.get(
                            "key"
                        )
                        or ""
                    ).strip()

                    if not row_key:
                        continue

                    if (
                        row_key
                        in processed_keys
                    ):
                        continue

                    if not bool(
                        row.get(
                            "today"
                        )
                    ):
                        reached_older_day = True
                        break

                    processed_keys.add(
                        row_key
                    )

                    scanned += 1

                    matched += 1

                    if (
                        len(
                            downloaded_items
                        )
                        >= limit
                    ):
                        skipped_items.append(
                            {
                                "row_key":
                                    row_key,
                                "reason":
                                    "MAX_DOCUMENTS_REACHED",
                                "row_text":
                                    row.get(
                                        "text"
                                    ),
                            }
                        )

                        reached_older_day = True
                        break

                    try:
                        item = (
                            open_and_download_row(
                                row
                            )
                        )

                        downloaded_items.append(
                            item
                        )

                    except Exception as exc:
                        errors.append(
                            {
                                "row_key":
                                    row_key,
                                "row_text":
                                    row.get(
                                        "text"
                                    ),
                                "error":
                                    str(
                                        exc
                                    ),
                            }
                        )

                    finally:
                        close_document_viewer()

                        # Visor y Media Hub son overlays
                        # distintos. Esperamos únicamente
                        # a que desaparezca Descargar.
                        viewer_deadline = (
                            time.time()
                            + 3.0
                        )

                        while (
                            time.time()
                            < viewer_deadline
                        ):
                            viewer_open = bool(
                                self.browser.evaluate(
                                    """
                                    (() => Boolean(
                                        document.querySelector(
                                            'button'
                                            + '[aria-label="Descargar"]'
                                        )
                                    ))()
                                    """
                                )
                            )

                            if not viewer_open:
                                break

                            time.sleep(
                                0.1
                            )

                if reached_older_day:
                    break

                movement = (
                    scroll_next_page()
                )

                if not movement.get(
                    "moved"
                ):
                    break

                # Esperar a que cambie la ventana virtual.
                previous_keys = {
                    str(
                        row.get(
                            "key"
                        )
                        or ""
                    )
                    for row in rows
                }

                refresh_deadline = (
                    time.time()
                    + 3.0
                )

                while time.time() < refresh_deadline:
                    refreshed = (
                        read_rows()
                    )

                    current_keys = {
                        str(
                            row.get(
                                "key"
                            )
                            or ""
                        )
                        for row in (
                            refreshed.get(
                                "rows"
                            )
                            or []
                        )
                    }

                    if (
                        current_keys
                        != previous_keys
                    ):
                        break

                    time.sleep(
                        0.1
                    )

            return {
                "scope":
                    "MEDIA_HUB",

                "date_scope":
                    "TODAY",

                "direction_scope":
                    "ALL",

                "scanned":
                    int(
                        scanned
                    ),

                "matched":
                    int(
                        matched
                    ),

                "downloaded":
                    len(
                        downloaded_items
                    ),

                "skipped":
                    skipped_items,

                "errors":
                    errors,

                "items":
                    downloaded_items,
            }

        finally:
            # Cerrar un visor residual antes de tocar
            # el propio Media Hub.
            close_document_viewer()

            if hub_open:
                try:
                    self.browser.evaluate(
                        """
                        (() => {
                            const hub =
                                document.querySelector(
                                    '[data-testid='
                                    + '"media-hub-modal"]'
                                );

                            if (!hub) {
                                return false;
                            }

                            const dialog =
                                hub.closest(
                                    '[role="dialog"]'
                                );

                            const close =
                                (
                                    hub.querySelector(
                                        'button'
                                        + '[aria-label="Cerrar"]'
                                    )
                                    || (
                                        dialog
                                        ? dialog.querySelector(
                                            'button'
                                            + '[aria-label="Cerrar"]'
                                          )
                                        : null
                                    )
                                );

                            if (!close) {
                                return false;
                            }

                            close.click();

                            return true;
                        })()
                        """
                    )

                except Exception:
                    pass

            if download_behavior_enabled:
                try:
                    run_until_complete(
                        send(
                            cdp_browser
                            .set_download_behavior(
                                behavior="default",
                            )
                        )
                    )
                except Exception:
                    pass



    def download_today_images_from_media_hub(
        self,
        *,
        download_dir,
        timeout=30,
        max_images=100,
    ):
        """Descarga las imágenes de HOY del Media Hub global.

        Contrato:
        - Media Hub global;
        - pestaña Archivos multimedia;
        - cualquier chat;
        - cualquier remitente/dirección;
        - solo fotografías;
        - excluye vídeo y GIF;
        - no persiste ni escanea Bandeja Documental.

        En la versión física observada de WhatsApp Web,
        el contenido de HOY puede aparecer como prefijo
        sin encabezado explícito, antes de la primera
        frontera histórica (Ayer/fecha/semana anterior).
        """
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        limit = max(
            1,
            int(
                max_images
            ),
        )

        per_image_timeout = max(
            1.0,
            float(
                timeout
            ),
        )

        target_dir = Path(
            download_dir
        ).expanduser()

        target_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        target_dir = (
            target_dir.resolve()
        )

        page = getattr(
            self.browser,
            "page",
            None,
        )

        loop = getattr(
            self.browser,
            "loop",
            None,
        )

        send = getattr(
            page,
            "send",
            None,
        )

        run_until_complete = getattr(
            loop,
            "run_until_complete",
            None,
        )

        if (
            not callable(
                send
            )
            or not callable(
                run_until_complete
            )
        ):
            raise RuntimeError(
                "Transporte CDP de descarga "
                "no disponible"
            )

        active = (
            self.get_active_chat_fingerprint()
        )

        if not active.chat_open:
            prepared = (
                self.prepare_chat_interface()
            )

            if (
                isinstance(
                    prepared,
                    dict,
                )
                and not prepared.get(
                    "ready",
                    True,
                )
            ):
                raise RuntimeError(
                    "La lista de chats WhatsApp "
                    "no está disponible"
                )

            snapshots = (
                self.list_visible_chat_snapshots(
                    viewport_only=True,
                )
            )

            if not snapshots:
                snapshots = (
                    self.list_visible_chat_snapshots(
                        viewport_only=False,
                    )
                )

            if not snapshots:
                raise RuntimeError(
                    "No hay conversaciones WhatsApp "
                    "disponibles para abrir "
                    "Contenido multimedia"
                )

            fallback = snapshots[0]

            if (
                fallback.virtual_offset
                is not None
            ):
                routing = (
                    self.open_chat_by_virtual_offset(
                        fallback.virtual_offset,
                        expected_display_name=(
                            fallback.display_name
                        ),
                        timeout=min(
                            15,
                            max(
                                1,
                                int(
                                    per_image_timeout
                                ),
                            ),
                        ),
                    )
                )

            else:
                routing = (
                    self.open_chat(
                        fallback.position,
                        expected_display_name=(
                            fallback.display_name
                        ),
                        timeout=min(
                            15,
                            max(
                                1,
                                int(
                                    per_image_timeout
                                ),
                            ),
                        ),
                    )
                )

            if not routing.get(
                "opened"
            ):
                raise RuntimeError(
                    "No se pudo abrir una conversación "
                    "WhatsApp para acceder al Media Hub "
                    f"({routing.get('reason') or 'CHAT_OPEN_FAILED'})"
                )

            active = (
                self.get_active_chat_fingerprint()
            )

            if not active.chat_open:
                raise RuntimeError(
                    "WhatsApp no confirmó el chat "
                    "abierto para acceder al Media Hub"
                )

        downloaded_items = []
        skipped_items = []
        errors = []

        scanned = 0
        matched = 0

        processed_keys = set()

        hub_open = False
        download_behavior_enabled = False


        def snapshot_files():
            snapshot = {}

            for file_path in target_dir.iterdir():
                if not file_path.is_file():
                    continue

                try:
                    stat = file_path.stat()
                except OSError:
                    continue

                snapshot[
                    str(
                        file_path
                    )
                ] = (
                    int(
                        stat.st_size
                    ),
                    int(
                        stat.st_mtime_ns
                    ),
                )

            return snapshot


        def changed_final_file(
            before,
        ):
            candidates = []

            for file_path in target_dir.iterdir():
                if not file_path.is_file():
                    continue

                if (
                    file_path.suffix.lower()
                    in (
                        ".tmp",
                        ".crdownload",
                    )
                ):
                    continue

                try:
                    stat = file_path.stat()
                except OSError:
                    continue

                current = (
                    int(
                        stat.st_size
                    ),
                    int(
                        stat.st_mtime_ns
                    ),
                )

                if (
                    before.get(
                        str(
                            file_path
                        )
                    )
                    == current
                ):
                    continue

                if current[0] <= 0:
                    continue

                candidates.append(
                    (
                        current[1],
                        file_path,
                        current[0],
                    )
                )

            if not candidates:
                return None

            candidates.sort(
                key=lambda item:
                    item[0],
                reverse=True,
            )

            _, candidate, size_1 = (
                candidates[0]
            )

            time.sleep(
                0.2
            )

            try:
                size_2 = int(
                    candidate.stat()
                    .st_size
                )
            except OSError:
                return None

            if (
                size_1 <= 0
                or size_1
                != size_2
            ):
                return None

            return candidate


        def close_image_viewer():
            try:
                return bool(
                    self.browser.evaluate(
                        """
                        (() => {
                            const viewer =
                                document.querySelector(
                                    '[data-testid="media-viewer-modal"]'
                                );

                            if (!viewer) {
                                return false;
                            }

                            const download =
                                viewer.querySelector(
                                    'button'
                                    + '[aria-label="Descargar"]'
                                );

                            if (!download) {
                                return false;
                            }

                            const visible = el => {
                                if (!el) {
                                    return false;
                                }

                                const style =
                                    getComputedStyle(
                                        el
                                    );

                                const rect =
                                    el.getBoundingClientRect();

                                return (
                                    style.display !== 'none'
                                    && style.visibility !== 'hidden'
                                    && rect.width > 0
                                    && rect.height > 0
                                );
                            };

                            const close =
                                Array.from(
                                    viewer.querySelectorAll(
                                        'button'
                                        + '[aria-label="Cerrar"]'
                                    )
                                )
                                .find(
                                    visible
                                );

                            if (!close) {
                                return false;
                            }

                            close.click();

                            return true;
                        })()
                        """
                    )
                )

            except Exception:
                return False


        def read_media_state():
            return (
                self.browser.evaluate(
                    r"""
                    (() => {
                        const clean = value =>
                            String(
                                value || ''
                            )
                            .replace(
                                /\s+/g,
                                ' '
                            )
                            .trim();

                        const tab =
                            document.querySelector(
                                '[data-testid="tab-media"]'
                            );

                        if (!tab) {
                            return {
                                ready: false,
                                rows: []
                            };
                        }

                        const root =
                            tab.closest(
                                '[data-testid="popup-contents"]'
                            )
                            || tab.closest(
                                '[data-testid="media-hub-modal"]'
                            )
                            || document;

                        const rows =
                            Array.from(
                                root.querySelectorAll(
                                    '[role="listitem"]'
                                    + '[data-testid^="list-item-"]'
                                )
                            );

                        const months =
                            (
                                'enero|febrero|marzo|abril|mayo|'
                                + 'junio|julio|agosto|septiembre|'
                                + 'octubre|noviembre|diciembre'
                            );

                        const explicitDate =
                            new RegExp(
                                '\\b\\d{1,2}\\s+de\\s+('
                                + months
                                + ')\\s+de\\s+\\d{4}\\b',
                                'i'
                            );

                        const dateRange =
                            new RegExp(
                                '\\b\\d{1,2}[–-]\\d{1,2}'
                                + '\\s+de\\s+('
                                + months
                                + ')\\s+de\\s+\\d{4}\\b',
                                'i'
                            );

                        const historicLabel =
                            /^(Ayer|La semana pasada|Esta semana|Este mes|El mes pasado)(\s|$)/i;

                        const isBoundary = row => {
                            const first =
                                row.children
                                && row.children.length
                                ? row.children[0]
                                : null;

                            const raw =
                                clean(
                                    first
                                    ? (
                                        first.innerText
                                        || first.textContent
                                    )
                                    : ''
                                );

                            if (
                                /^Hoy(\s|$)/i.test(
                                    raw
                                )
                            ) {
                                return false;
                            }

                            return (
                                historicLabel.test(
                                    raw
                                )
                                || explicitDate.test(
                                    raw
                                )
                                || dateRange.test(
                                    raw
                                )
                            );
                        };

                        const mapped =
                            rows.map(
                                row => {
                                    const rowKey =
                                        clean(
                                            row.getAttribute(
                                                'data-testid'
                                            )
                                        );

                                    const first =
                                        row.children
                                        && row.children.length
                                        ? row.children[0]
                                        : null;

                                    const boundaryText =
                                        clean(
                                            first
                                            ? (
                                                first.innerText
                                                || first.textContent
                                            )
                                            : ''
                                        );

                                    const tiles =
                                        Array.from(
                                            row.querySelectorAll(
                                                '[data-testid="media-canvas"]'
                                            )
                                        )
                                        .map(
                                            (
                                                tile,
                                                tileIndex
                                            ) => {
                                                const aria =
                                                    clean(
                                                        tile.getAttribute(
                                                            'aria-label'
                                                        )
                                                    );

                                                const text =
                                                    clean(
                                                        tile.innerText
                                                        || tile.textContent
                                                    );

                                                const hasProvider =
                                                    Boolean(
                                                        tile.querySelector(
                                                            '[data-testid="media-url-provider"]'
                                                        )
                                                    );

                                                const hasImage =
                                                    Boolean(
                                                        tile.querySelector(
                                                            '[data-testid="media-canvas-img"]'
                                                        )
                                                    );

                                                const hasGif =
                                                    Boolean(
                                                        tile.querySelector(
                                                            '[data-testid="msg-gif"]'
                                                        )
                                                    );

                                                const duration =
                                                    Array.from(
                                                        tile.querySelectorAll(
                                                            'span'
                                                        )
                                                    )
                                                    .map(
                                                        node =>
                                                            clean(
                                                                node.textContent
                                                            )
                                                    )
                                                    .find(
                                                        value =>
                                                            /^\d{1,2}:\d{2}$/
                                                            .test(
                                                                value
                                                            )
                                                    )
                                                    || null;

                                                const isVideo =
                                                    /Video de/i.test(
                                                        aria
                                                    )
                                                    || Boolean(
                                                        duration
                                                    );

                                                const isGif =
                                                    /GIF de/i.test(
                                                        aria
                                                    )
                                                    || hasGif;

                                                const isImage =
                                                    /Imagen de/i.test(
                                                        aria
                                                    )
                                                    && hasImage
                                                    && !isVideo
                                                    && !isGif;

                                                let kind =
                                                    'UNKNOWN_MEDIA';

                                                if (isImage) {
                                                    kind =
                                                        'IMAGE';
                                                } else if (isVideo) {
                                                    kind =
                                                        'VIDEO';
                                                } else if (isGif) {
                                                    kind =
                                                        'GIF';
                                                }

                                                return {
                                                    key:
                                                        (
                                                            rowKey
                                                            + '|'
                                                            + tileIndex
                                                            + '|'
                                                            + aria
                                                            + '|'
                                                            + text
                                                        ),

                                                    row_key:
                                                        rowKey,

                                                    tile_index:
                                                        tileIndex,

                                                    aria,

                                                    text,

                                                    kind,

                                                    has_provider:
                                                        hasProvider,

                                                    has_image:
                                                        hasImage,

                                                    has_gif:
                                                        hasGif,

                                                    duration,
                                                };
                                            }
                                        );

                                    return {
                                        key:
                                            rowKey,

                                        boundary:
                                            isBoundary(
                                                row
                                            ),

                                        boundary_text:
                                            boundaryText,

                                        text:
                                            clean(
                                                row.innerText
                                                || row.textContent
                                            ),

                                        tiles,
                                    };
                                }
                            );

                        const first =
                            rows[0]
                            || null;

                        let scroller =
                            first;

                        while (scroller) {
                            const style =
                                getComputedStyle(
                                    scroller
                                );

                            if (
                                scroller.scrollHeight
                                > (
                                    scroller.clientHeight
                                    + 5
                                )
                                && (
                                    style.overflowY
                                    === 'auto'
                                    || style.overflowY
                                    === 'scroll'
                                )
                            ) {
                                break;
                            }

                            scroller =
                                scroller.parentElement;
                        }

                        return {
                            ready: true,
                            rows:
                                mapped,

                            scroll_top:
                                scroller
                                ? scroller.scrollTop
                                : null,

                            scroll_height:
                                scroller
                                ? scroller.scrollHeight
                                : null,

                            client_height:
                                scroller
                                ? scroller.clientHeight
                                : null,
                        };
                    })()
                    """
                )
                or {}
            )


        def scroll_media_top():
            return (
                self.browser.evaluate(
                    """
                    (() => {
                        const tab =
                            document.querySelector(
                                '[data-testid="tab-media"]'
                            );

                        const root =
                            tab
                            ? (
                                tab.closest(
                                    '[data-testid="popup-contents"]'
                                )
                                || tab.closest(
                                    '[data-testid="media-hub-modal"]'
                                )
                                || document
                            )
                            : document;

                        const first =
                            root.querySelector(
                                '[role="listitem"]'
                                + '[data-testid^="list-item-"]'
                            );

                        if (!first) {
                            return {
                                moved: false,
                                reason:
                                    'ROW_MISSING'
                            };
                        }

                        let scroller =
                            first;

                        while (scroller) {
                            const style =
                                getComputedStyle(
                                    scroller
                                );

                            if (
                                scroller.scrollHeight
                                > (
                                    scroller.clientHeight
                                    + 5
                                )
                                && (
                                    style.overflowY
                                    === 'auto'
                                    || style.overflowY
                                    === 'scroll'
                                )
                            ) {
                                break;
                            }

                            scroller =
                                scroller.parentElement;
                        }

                        if (!scroller) {
                            return {
                                moved: false,
                                reason:
                                    'SCROLLER_MISSING'
                            };
                        }

                        const before =
                            scroller.scrollTop;

                        scroller.scrollTop = 0;

                        return {
                            moved:
                                before > 1,

                            before,

                            after:
                                scroller.scrollTop,
                        };
                    })()
                    """
                )
                or {}
            )


        def scroll_next_page():
            return (
                self.browser.evaluate(
                    """
                    (() => {
                        const tab =
                            document.querySelector(
                                '[data-testid="tab-media"]'
                            );

                        const root =
                            tab
                            ? (
                                tab.closest(
                                    '[data-testid="popup-contents"]'
                                )
                                || tab.closest(
                                    '[data-testid="media-hub-modal"]'
                                )
                                || document
                            )
                            : document;

                        const first =
                            root.querySelector(
                                '[role="listitem"]'
                                + '[data-testid^="list-item-"]'
                            );

                        if (!first) {
                            return {
                                moved: false,
                                reason:
                                    'ROW_MISSING'
                            };
                        }

                        let scroller =
                            first;

                        while (scroller) {
                            const style =
                                getComputedStyle(
                                    scroller
                                );

                            if (
                                scroller.scrollHeight
                                > (
                                    scroller.clientHeight
                                    + 5
                                )
                                && (
                                    style.overflowY
                                    === 'auto'
                                    || style.overflowY
                                    === 'scroll'
                                )
                            ) {
                                break;
                            }

                            scroller =
                                scroller.parentElement;
                        }

                        if (!scroller) {
                            return {
                                moved: false,
                                reason:
                                    'SCROLLER_MISSING'
                            };
                        }

                        const before =
                            scroller.scrollTop;

                        const step =
                            Math.max(
                                300,
                                Math.floor(
                                    scroller.clientHeight
                                    * 0.8
                                )
                            );

                        scroller.scrollTop =
                            Math.min(
                                scroller.scrollHeight
                                - scroller.clientHeight,
                                before + step
                            );

                        return {
                            moved:
                                scroller.scrollTop
                                > before + 1,

                            before,

                            after:
                                scroller.scrollTop,
                        };
                    })()
                    """
                )
                or {}
            )


        def open_and_download_image(
            tile,
        ):
            nonlocal download_behavior_enabled

            row_key = str(
                tile.get(
                    "row_key"
                )
                or ""
            ).strip()

            tile_index = int(
                tile.get(
                    "tile_index"
                )
                or 0
            )

            if not row_key:
                raise RuntimeError(
                    "MEDIA_IMAGE_ROW_ID_MISSING"
                )

            if not download_behavior_enabled:
                run_until_complete(
                    send(
                        cdp_browser
                        .set_download_behavior(
                            behavior="allow",
                            download_path=str(
                                target_dir
                            ),
                            events_enabled=True,
                        )
                    )
                )

                download_behavior_enabled = True

            before = (
                snapshot_files()
            )

            opened = (
                self.browser.evaluate(
                    r"""
                    (() => {
                        const rowKey = %s;
                        const tileIndex = %d;

                        const row =
                            document.querySelector(
                                '[role="listitem"]'
                                + '[data-testid="'
                                + rowKey
                                + '"]'
                            );

                        if (!row) {
                            return {
                                opened: false,
                                reason:
                                    'ROW_NOT_RENDERED'
                            };
                        }

                        const tiles =
                            Array.from(
                                row.querySelectorAll(
                                    '[data-testid="media-canvas"]'
                                )
                            );

                        const tile =
                            tiles[
                                tileIndex
                            ];

                        if (!tile) {
                            return {
                                opened: false,
                                reason:
                                    'IMAGE_TILE_NOT_RENDERED'
                            };
                        }

                        const aria =
                            String(
                                tile.getAttribute(
                                    'aria-label'
                                )
                                || ''
                            ).trim();

                        const image =
                            tile.querySelector(
                                '[data-testid="media-canvas-img"]'
                            );

                        const gif =
                            tile.querySelector(
                                '[data-testid="msg-gif"]'
                            );

                        const duration =
                            Array.from(
                                tile.querySelectorAll(
                                    'span'
                                )
                            )
                            .map(
                                node =>
                                    String(
                                        node.textContent
                                        || ''
                                    ).trim()
                            )
                            .find(
                                value =>
                                    /^\d{1,2}:\d{2}$/
                                    .test(
                                        value
                                    )
                            );

                        if (
                            !/Imagen de/i.test(
                                aria
                            )
                            || /Video de/i.test(
                                aria
                            )
                            || /GIF de/i.test(
                                aria
                            )
                            || !image
                            || gif
                            || duration
                        ) {
                            return {
                                opened: false,
                                reason:
                                    'MEDIA_NOT_IMAGE'
                            };
                        }

                        // Contrato físico:
                        // el click del media-canvas genérico
                        // no abre siempre el visor.
                        image.click();

                        return {
                            opened: true,
                            strategy:
                                'MEDIA_CANVAS_IMG',
                            aria:
                                aria
                        };
                    })()
                    """
                    % (
                        repr(
                            row_key
                        ),
                        tile_index,
                    )
                )
                or {}
            )

            if not opened.get(
                "opened"
            ):
                raise RuntimeError(
                    str(
                        opened.get(
                            "reason"
                        )
                        or "MEDIA_IMAGE_OPEN_FAILED"
                    )
                )

            deadline = (
                time.time()
                + per_image_timeout
            )

            viewer_ready = False

            while time.time() < deadline:
                viewer_ready = bool(
                    self.browser.evaluate(
                        """
                        (() => Boolean(
                            document.querySelector(
                                'button'
                                + '[aria-label="Descargar"]'
                            )
                        ))()
                        """
                    )
                )

                if viewer_ready:
                    break

                time.sleep(
                    0.1
                )

            if not viewer_ready:
                raise RuntimeError(
                    "MEDIA_IMAGE_VIEWER_TIMEOUT"
                )

            clicked = bool(
                self.browser.evaluate(
                    """
                    (() => {
                        const button =
                            document.querySelector(
                                'button'
                                + '[aria-label="Descargar"]'
                            );

                        if (!button) {
                            return false;
                        }

                        button.click();

                        return true;
                    })()
                    """
                )
            )

            if not clicked:
                raise RuntimeError(
                    "MEDIA_IMAGE_DOWNLOAD_CLICK_FAILED"
                )

            deadline = (
                time.time()
                + per_image_timeout
            )

            downloaded = None

            while time.time() < deadline:
                downloaded = (
                    changed_final_file(
                        before
                    )
                )

                if downloaded is not None:
                    break

                time.sleep(
                    0.1
                )

            if downloaded is None:
                raise RuntimeError(
                    "MEDIA_IMAGE_DOWNLOAD_TIMEOUT"
                )

            return {
                "row_key":
                    row_key,

                "tile_index":
                    tile_index,

                "media_type":
                    "IMAGE",

                "aria_label":
                    tile.get(
                        "aria"
                    ),

                "row_text":
                    tile.get(
                        "text"
                    ),

                "filename":
                    downloaded.name,

                "file_path":
                    str(
                        downloaded
                    ),

                "size_bytes":
                    int(
                        downloaded.stat()
                        .st_size
                    ),
            }


        try:
            # ==============================================
            # 1. ABRIR MEDIA HUB
            # ==============================================

            existing_hub = bool(
                self.browser.evaluate(
                    """
                    (() => Boolean(
                        document.querySelector(
                            '[data-testid="media-hub-modal"]'
                        )
                        || document.querySelector(
                            '[data-testid="tab-media"]'
                        )
                    ))()
                    """
                )
            )

            if not existing_hub:
                entry = (
                    self.browser.evaluate(
                        """
                        (() => {
                            const visible = el => {
                                if (!el) {
                                    return false;
                                }

                                const style =
                                    getComputedStyle(
                                        el
                                    );

                                const rect =
                                    el.getBoundingClientRect();

                                return (
                                    style.display !== 'none'
                                    && style.visibility !== 'hidden'
                                    && rect.width > 0
                                    && rect.height > 0
                                );
                            };

                            const media =
                                Array.from(
                                    document.querySelectorAll(
                                        '[aria-label="Contenido multimedia"]'
                                    )
                                )
                                .find(
                                    visible
                                );

                            if (media) {
                                media.click();

                                return {
                                    clicked: true,
                                    strategy:
                                        'DIRECT_MEDIA'
                                };
                            }

                            const info =
                                document.querySelector(
                                    '[data-testid="conversation-info-header"]'
                                )
                                || document.querySelector(
                                    '[aria-label="Información del perfil"]'
                                );

                            if (!info) {
                                return {
                                    clicked: false,
                                    reason:
                                        'INFO_ENTRY_MISSING'
                                };
                            }

                            info.click();

                            return {
                                clicked: true,
                                strategy:
                                    'OPEN_INFO'
                            };
                        })()
                        """
                    )
                    or {}
                )

                if not entry.get(
                    "clicked"
                ):
                    raise RuntimeError(
                        "No se pudo abrir "
                        "Contenido multimedia "
                        f"({entry.get('reason')})"
                    )

                if (
                    entry.get(
                        "strategy"
                    )
                    == "OPEN_INFO"
                ):
                    deadline = (
                        time.time()
                        + min(
                            15.0,
                            per_image_timeout,
                        )
                    )

                    media_visible = False

                    while time.time() < deadline:
                        media_visible = bool(
                            self.browser.evaluate(
                                """
                                (() => {
                                    const visible = el => {
                                        if (!el) {
                                            return false;
                                        }

                                        const style =
                                            getComputedStyle(
                                                el
                                            );

                                        const rect =
                                            el.getBoundingClientRect();

                                        return (
                                            style.display !== 'none'
                                            && style.visibility !== 'hidden'
                                            && rect.width > 0
                                            && rect.height > 0
                                        );
                                    };

                                    return Array.from(
                                        document.querySelectorAll(
                                            '[aria-label="Contenido multimedia"]'
                                        )
                                    ).some(
                                        visible
                                    );
                                })()
                                """
                            )
                        )

                        if media_visible:
                            break

                        time.sleep(
                            0.1
                        )

                    if not media_visible:
                        raise RuntimeError(
                            "Contenido multimedia "
                            "no apareció"
                        )

                    clicked = bool(
                        self.browser.evaluate(
                            """
                            (() => {
                                const visible = el => {
                                    if (!el) {
                                        return false;
                                    }

                                    const style =
                                        getComputedStyle(
                                            el
                                    );

                                    const rect =
                                        el.getBoundingClientRect();

                                    return (
                                        style.display !== 'none'
                                        && style.visibility !== 'hidden'
                                        && rect.width > 0
                                        && rect.height > 0
                                    );
                                };

                                const media =
                                    Array.from(
                                        document.querySelectorAll(
                                            '[aria-label="Contenido multimedia"]'
                                        )
                                    )
                                    .find(
                                        visible
                                    );

                                if (!media) {
                                    return false;
                                }

                                media.click();

                                return true;
                            })()
                            """
                        )
                    )

                    if not clicked:
                        raise RuntimeError(
                            "No se pudo pulsar "
                            "Contenido multimedia"
                        )

            deadline = (
                time.time()
                + min(
                    15.0,
                    per_image_timeout,
                )
            )

            while time.time() < deadline:
                hub_open = bool(
                    self.browser.evaluate(
                        """
                        (() => Boolean(
                            document.querySelector(
                                '[data-testid="tab-media"]'
                            )
                        ))()
                        """
                    )
                )

                if hub_open:
                    break

                time.sleep(
                    0.1
                )

            if not hub_open:
                raise RuntimeError(
                    "Media Hub no apareció"
                )

            # ==============================================
            # 2. TAB ARCHIVOS MULTIMEDIA
            # ==============================================

            media_clicked = bool(
                self.browser.evaluate(
                    """
                    (() => {
                        const tab =
                            document.querySelector(
                                '[data-testid="tab-media"]'
                            );

                        if (!tab) {
                            return false;
                        }

                        if (
                            tab.getAttribute(
                                'aria-selected'
                            )
                            !== 'true'
                        ) {
                            tab.click();
                        }

                        return true;
                    })()
                    """
                )
            )

            if not media_clicked:
                raise RuntimeError(
                    "Pestaña Archivos multimedia "
                    "no disponible"
                )

            deadline = (
                time.time()
                + min(
                    15.0,
                    per_image_timeout,
                )
            )

            initial_state = {}

            while time.time() < deadline:
                initial_state = (
                    read_media_state()
                )

                if (
                    initial_state.get(
                        "ready"
                    )
                    and initial_state.get(
                        "rows"
                    )
                ):
                    break

                time.sleep(
                    0.2
                )

            if not initial_state.get(
                "rows"
            ):
                return {
                    "scope":
                        "MEDIA_HUB",

                    "date_scope":
                        "TODAY",

                    "direction_scope":
                        "ALL",

                    "media_type_scope":
                        "IMAGE",

                    "scanned": 0,
                    "matched": 0,
                    "downloaded": 0,
                    "skipped": [],
                    "errors": [],
                    "items": [],
                }

            # Siempre comenzamos desde el inicio cronológico.
            scroll_media_top()

            time.sleep(
                0.3
            )

            # ==============================================
            # 3. PREFIJO DE HOY · VENTANA VIRTUAL
            # ==============================================

            while True:
                state = (
                    read_media_state()
                )

                rows = (
                    state.get(
                        "rows"
                    )
                    or []
                )

                if not rows:
                    break

                reached_older_day = False
                reached_limit = False

                for row in rows:
                    if bool(
                        row.get(
                            "boundary"
                        )
                    ):
                        reached_older_day = True
                        break

                    for tile in (
                        row.get(
                            "tiles"
                        )
                        or []
                    ):
                        tile_key = str(
                            tile.get(
                                "key"
                            )
                            or ""
                        ).strip()

                        if not tile_key:
                            continue

                        if (
                            tile_key
                            in processed_keys
                        ):
                            continue

                        processed_keys.add(
                            tile_key
                        )

                        scanned += 1

                        kind = str(
                            tile.get(
                                "kind"
                            )
                            or ""
                        ).strip().upper()

                        if kind != "IMAGE":
                            skipped_items.append(
                                {
                                    "key":
                                        tile_key,

                                    "kind":
                                        kind
                                        or "UNKNOWN_MEDIA",

                                    "reason":
                                        (
                                            "VIDEO_EXCLUDED"
                                            if kind == "VIDEO"
                                            else (
                                                "GIF_EXCLUDED"
                                                if kind == "GIF"
                                                else "NOT_IMAGE"
                                            )
                                        ),

                                    "row_text":
                                        tile.get(
                                            "text"
                                        ),
                                }
                            )

                            continue

                        matched += 1

                        if (
                            len(
                                downloaded_items
                            )
                            >= limit
                        ):
                            skipped_items.append(
                                {
                                    "key":
                                        tile_key,

                                    "kind":
                                        "IMAGE",

                                    "reason":
                                        "MAX_IMAGES_REACHED",

                                    "row_text":
                                        tile.get(
                                            "text"
                                        ),
                                }
                            )

                            reached_limit = True
                            break

                        try:
                            item = (
                                open_and_download_image(
                                    tile
                                )
                            )

                            downloaded_items.append(
                                item
                            )

                        except Exception as exc:
                            errors.append(
                                {
                                    "key":
                                        tile_key,

                                    "kind":
                                        "IMAGE",

                                    "row_text":
                                        tile.get(
                                            "text"
                                        ),

                                    "error":
                                        str(
                                            exc
                                        ),
                                }
                            )

                        finally:
                            close_image_viewer()

                            viewer_deadline = (
                                time.time()
                                + 3.0
                            )

                            while (
                                time.time()
                                < viewer_deadline
                            ):
                                viewer_open = bool(
                                    self.browser.evaluate(
                                        """
                                        (() => Boolean(
                                            document.querySelector(
                                                '[data-testid="media-viewer-modal"]'
                                            )
                                        ))()
                                        """
                                    )
                                )

                                if not viewer_open:
                                    break

                                time.sleep(
                                    0.1
                                )

                    if reached_limit:
                        break

                if (
                    reached_older_day
                    or reached_limit
                ):
                    break

                previous_keys = {
                    str(
                        row.get(
                            "key"
                        )
                        or ""
                    )
                    for row in rows
                }

                movement = (
                    scroll_next_page()
                )

                if not movement.get(
                    "moved"
                ):
                    break

                refresh_deadline = (
                    time.time()
                    + 3.0
                )

                while time.time() < refresh_deadline:
                    refreshed = (
                        read_media_state()
                    )

                    current_keys = {
                        str(
                            row.get(
                                "key"
                            )
                            or ""
                        )
                        for row in (
                            refreshed.get(
                                "rows"
                            )
                            or []
                        )
                    }

                    if (
                        current_keys
                        != previous_keys
                    ):
                        break

                    time.sleep(
                        0.1
                    )

            return {
                "scope":
                    "MEDIA_HUB",

                "date_scope":
                    "TODAY",

                "direction_scope":
                    "ALL",

                "media_type_scope":
                    "IMAGE",

                "scanned":
                    int(
                        scanned
                    ),

                "matched":
                    int(
                        matched
                    ),

                "downloaded":
                    len(
                        downloaded_items
                    ),

                "skipped":
                    skipped_items,

                "errors":
                    errors,

                "items":
                    downloaded_items,
            }

        finally:
            close_image_viewer()

            if hub_open:
                try:
                    self.browser.evaluate(
                        """
                        (() => {
                            const hub =
                                document.querySelector(
                                    '[data-testid="media-hub-modal"]'
                                );

                            const tab =
                                document.querySelector(
                                    '[data-testid="tab-media"]'
                                );

                            const root =
                                hub
                                || (
                                    tab
                                    ? tab.closest(
                                        '[data-testid="popup-contents"]'
                                      )
                                    : null
                                );

                            if (!root) {
                                return false;
                            }

                            const visible = el => {
                                if (!el) {
                                    return false;
                                }

                                const style =
                                    getComputedStyle(
                                        el
                                    );

                                const rect =
                                    el.getBoundingClientRect();

                                return (
                                    style.display !== 'none'
                                    && style.visibility !== 'hidden'
                                    && rect.width > 0
                                    && rect.height > 0
                                );
                            };

                            const close =
                                Array.from(
                                    root.querySelectorAll(
                                        'button'
                                        + '[aria-label="Cerrar"]'
                                    )
                                )
                                .find(
                                    visible
                                );

                            if (!close) {
                                return false;
                            }

                            close.click();

                            return true;
                        })()
                        """
                    )

                except Exception:
                    pass

            if download_behavior_enabled:
                try:
                    run_until_complete(
                        send(
                            cdp_browser
                            .set_download_behavior(
                                behavior="default",
                            )
                        )
                    )

                except Exception:
                    pass


    @staticmethod
    def _voice_call_snapshot_summary(
        snapshot,
    ):
        if snapshot is None:
            return {
                "present": False,
                "phase":
                    WHATSAPP_CALL_PHASE_ABSENT,
                "direction":
                    WHATSAPP_CALL_DIRECTION_UNKNOWN,
                "provider_call_id":
                    None,
                "external_call_key":
                    None,
                "participant_phone":
                    None,
            }

        return {
            "present":
                bool(
                    getattr(
                        snapshot,
                        "present",
                        False,
                    )
                ),
            "phase":
                getattr(
                    snapshot,
                    "phase",
                    None,
                ),
            "direction":
                getattr(
                    snapshot,
                    "direction",
                    None,
                ),
            "provider_call_id":
                getattr(
                    snapshot,
                    "provider_call_id",
                    None,
                ),
            "external_call_key":
                getattr(
                    snapshot,
                    "external_call_key",
                    None,
                ),
            "participant_phone":
                getattr(
                    snapshot,
                    "participant_phone",
                    None,
                ),
        }


    def start_voice_call(
        self,
        *,
        confirm_timeout=1.0,
        poll_interval=0.05,
    ):
        """Inicia UNA llamada de voz sobre el chat ya verificado.

        Responsabilidades:
        - no navega;
        - no resuelve destinatarios;
        - no persiste;
        - nunca pulsa videollamada;
        - nunca reintenta un click con efecto externo;
        - confirma, cuando es posible, que apareció
          una superficie de llamada.

        El caller debe haber verificado previamente
        la identidad del chat activo.
        """
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        # Nunca iniciamos otra llamada si ya existe
        # cualquier superficie VOIP activa.
        existing = (
            self.read_call_snapshot()
        )

        if bool(
            getattr(
                existing,
                "present",
                False,
            )
        ):
            return {
                "ok": False,
                "uncertain": False,
                "clicked": False,
                "reason":
                    "CALL_ALREADY_PRESENT",
                "selector":
                    WHATSAPP_VOICE_CALL_BUTTON_SELECTOR,
                "snapshot":
                    self._voice_call_snapshot_summary(
                        existing
                    ),
                "_snapshot":
                    existing,
            }

        control = (
            self.browser.evaluate(
                """
                (() => {
                    const button =
                        document.querySelector(
                            '#main header '
                            + 'button[aria-label="Llamada"]'
                        );

                    if (!button) {
                        return {
                            found: false
                        };
                    }

                    return {
                        found: true,
                        aria_label:
                            (
                                button.getAttribute(
                                    "aria-label"
                                )
                                || ""
                            ).trim(),
                        disabled:
                            !!button.disabled,
                        aria_disabled:
                            (
                                button.getAttribute(
                                    "aria-disabled"
                                )
                                || ""
                            ).trim()
                    };
                })()
                """
            )
            or {}
        )

        if not isinstance(
            control,
            dict,
        ):
            control = {}

        if not bool(
            control.get(
                "found"
            )
        ):
            return {
                "ok": False,
                "uncertain": False,
                "clicked": False,
                "reason":
                    "VOICE_CALL_BUTTON_NOT_FOUND",
                "selector":
                    WHATSAPP_VOICE_CALL_BUTTON_SELECTOR,
                "control":
                    control,
            }

        aria_label = str(
            control.get(
                "aria_label"
            )
            or ""
        ).strip()

        if (
            aria_label
            != WHATSAPP_VOICE_CALL_ARIA_LABEL
        ):
            return {
                "ok": False,
                "uncertain": False,
                "clicked": False,
                "reason":
                    "VOICE_CALL_BUTTON_IDENTITY_MISMATCH",
                "selector":
                    WHATSAPP_VOICE_CALL_BUTTON_SELECTOR,
                "control":
                    control,
            }

        disabled = bool(
            control.get(
                "disabled"
            )
        )

        if (
            str(
                control.get(
                    "aria_disabled"
                )
                or ""
            )
            .strip()
            .lower()
            == "true"
        ):
            disabled = True

        if disabled:
            return {
                "ok": False,
                "uncertain": False,
                "clicked": False,
                "reason":
                    "VOICE_CALL_BUTTON_DISABLED",
                "selector":
                    WHATSAPP_VOICE_CALL_BUTTON_SELECTOR,
                "control":
                    control,
            }

        try:
            element = (
                self.browser.find_element(
                    WHATSAPP_VOICE_CALL_BUTTON_SELECTOR
                )
            )
        except Exception as exc:
            return {
                "ok": False,
                "uncertain": False,
                "clicked": False,
                "reason":
                    "VOICE_CALL_BUTTON_NOT_FOUND",
                "selector":
                    WHATSAPP_VOICE_CALL_BUTTON_SELECTOR,
                "error_type":
                    type(
                        exc
                    ).__name__,
                "message":
                    str(
                        exc
                    ),
            }

        if element is None:
            return {
                "ok": False,
                "uncertain": False,
                "clicked": False,
                "reason":
                    "VOICE_CALL_BUTTON_NOT_FOUND",
                "selector":
                    WHATSAPP_VOICE_CALL_BUTTON_SELECTOR,
            }

        # Desde este punto una excepción es potencialmente
        # incierta: el click podría haber llegado al browser.
        click_attempted = False

        try:
            click_attempted = True

            mouse_click = getattr(
                element,
                "mouse_click",
                None,
            )

            if callable(
                mouse_click
            ):
                mouse_click()

            else:
                click = getattr(
                    element,
                    "click",
                    None,
                )

                if not callable(
                    click
                ):
                    return {
                        "ok": False,
                        "uncertain": False,
                        "clicked": False,
                        "reason":
                            "VOICE_CALL_BUTTON_NOT_CLICKABLE",
                        "selector":
                            WHATSAPP_VOICE_CALL_BUTTON_SELECTOR,
                    }

                click()

        except Exception as exc:
            return {
                "ok": False,
                "uncertain": True,
                "clicked":
                    bool(
                        click_attempted
                    ),
                "reason":
                    "VOICE_CALL_CLICK_UNCERTAIN",
                "selector":
                    WHATSAPP_VOICE_CALL_BUTTON_SELECTOR,
                "error_type":
                    type(
                        exc
                    ).__name__,
                "message":
                    str(
                        exc
                    ),
            }

        timeout = max(
            0.0,
            float(
                confirm_timeout
                or 0.0
            ),
        )

        interval = max(
            0.01,
            float(
                poll_interval
                or 0.05
            ),
        )

        deadline = (
            time.monotonic()
            + timeout
        )

        last_snapshot = None

        while True:
            try:
                last_snapshot = (
                    self.read_call_snapshot()
                )
            except Exception:
                last_snapshot = None

            if (
                last_snapshot is not None
                and bool(
                    getattr(
                        last_snapshot,
                        "present",
                        False,
                    )
                )
            ):
                summary = (
                    self
                    ._voice_call_snapshot_summary(
                        last_snapshot
                    )
                )

                return {
                    "ok": True,
                    "uncertain": False,
                    "clicked": True,
                    "reason":
                        "VOICE_CALL_SURFACE_STARTED",
                    "selector":
                        WHATSAPP_VOICE_CALL_BUTTON_SELECTOR,
                    "snapshot":
                        summary,
                    "_snapshot":
                        last_snapshot,
                }

            if (
                time.monotonic()
                >= deadline
            ):
                break

            time.sleep(
                interval
            )

        # Nunca reintentamos el click:
        # existe una acción externa potencial.
        return {
            "ok": False,
            "uncertain": True,
            "clicked": True,
            "reason":
                "VOICE_CALL_START_UNCONFIRMED",
            "selector":
                WHATSAPP_VOICE_CALL_BUTTON_SELECTOR,
            "snapshot":
                self._voice_call_snapshot_summary(
                    last_snapshot
                ),
            "_snapshot":
                last_snapshot,
        }


    def _act_on_incoming_call(
        self,
        *,
        action,
        expected_provider_call_id=None,
        expected_external_call_key=None,
        confirm_timeout=2.0,
        poll_interval=0.05,
    ):
        """
        Ejecuta UNA acción sobre una llamada entrante.

        Garantías:
        - exige superficie INCOMING_RINGING real;
        - exige dirección INBOUND;
        - verifica identidad provider opcional;
        - verifica capability del snapshot;
        - verifica aria-label exacto;
        - verifica control habilitado;
        - realiza un único click;
        - nunca reintenta el side effect;
        - después solo observa para confirmar.
        """

        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        normalized_action = str(
            action
            or ""
        ).strip().upper()

        action_contracts = {
            "ACCEPT": {
                "selector":
                    WHATSAPP_INCOMING_CALL_ACCEPT_SELECTOR,
                "aria_label":
                    WHATSAPP_INCOMING_CALL_ACCEPT_ARIA_LABEL,
                "capability":
                    "can_accept",
                "prefix":
                    "CALL_ACCEPT",
            },
            "REJECT": {
                "selector":
                    WHATSAPP_INCOMING_CALL_REJECT_SELECTOR,
                "aria_label":
                    WHATSAPP_INCOMING_CALL_REJECT_ARIA_LABEL,
                "capability":
                    "can_reject",
                "prefix":
                    "CALL_REJECT",
            },
        }

        contract = action_contracts.get(
            normalized_action
        )

        if contract is None:
            raise ValueError(
                "Acción de llamada entrante "
                "no soportada"
            )

        selector = contract[
            "selector"
        ]

        expected_label = contract[
            "aria_label"
        ]

        capability = contract[
            "capability"
        ]

        prefix = contract[
            "prefix"
        ]

        initial = (
            self.read_call_snapshot()
        )

        summary = (
            self._voice_call_snapshot_summary(
                initial
            )
        )

        if not bool(
            getattr(
                initial,
                "present",
                False,
            )
        ):
            return {
                "ok": False,
                "uncertain": False,
                "clicked": False,
                "reason":
                    f"{prefix}_CALL_ABSENT",
                "selector": selector,
                "snapshot": summary,
                "_snapshot": initial,
            }

        if (
            getattr(
                initial,
                "phase",
                None,
            )
            != WHATSAPP_CALL_PHASE_INCOMING_RINGING
            or getattr(
                initial,
                "direction",
                None,
            )
            != WHATSAPP_CALL_DIRECTION_INBOUND
        ):
            return {
                "ok": False,
                "uncertain": False,
                "clicked": False,
                "reason":
                    f"{prefix}_NOT_INCOMING_RINGING",
                "selector": selector,
                "snapshot": summary,
                "_snapshot": initial,
            }

        clean_expected_provider = str(
            expected_provider_call_id
            or ""
        ).strip()

        clean_expected_external = str(
            expected_external_call_key
            or ""
        ).strip()

        actual_provider = str(
            getattr(
                initial,
                "provider_call_id",
                None,
            )
            or ""
        ).strip()

        actual_external = str(
            getattr(
                initial,
                "external_call_key",
                None,
            )
            or ""
        ).strip()

        if (
            clean_expected_provider
            and actual_provider
            != clean_expected_provider
        ):
            return {
                "ok": False,
                "uncertain": False,
                "clicked": False,
                "reason":
                    f"{prefix}_IDENTITY_MISMATCH",
                "selector": selector,
                "snapshot": summary,
                "_snapshot": initial,
            }

        if (
            clean_expected_external
            and actual_external
            != clean_expected_external
        ):
            return {
                "ok": False,
                "uncertain": False,
                "clicked": False,
                "reason":
                    f"{prefix}_IDENTITY_MISMATCH",
                "selector": selector,
                "snapshot": summary,
                "_snapshot": initial,
            }

        if not bool(
            getattr(
                initial,
                capability,
                False,
            )
        ):
            return {
                "ok": False,
                "uncertain": False,
                "clicked": False,
                "reason":
                    f"{prefix}_NOT_AVAILABLE",
                "selector": selector,
                "snapshot": summary,
                "_snapshot": initial,
            }

        selector_json = json.dumps(
            selector
        )

        control = (
            self.browser.evaluate(
                f"""
                (() => {{
                    const button =
                        document.querySelector(
                            {selector_json}
                        );

                    if (!button) {{
                        return {{
                            found: false
                        }};
                    }}

                    return {{
                        found: true,
                        aria_label:
                            (
                                button.getAttribute(
                                    "aria-label"
                                )
                                || ""
                            ).trim(),
                        aria_disabled:
                            (
                                button.getAttribute(
                                    "aria-disabled"
                                )
                                || ""
                            ).trim(),
                        disabled:
                            !!button.disabled
                    }};
                }})()
                """
            )
            or {}
        )

        if not isinstance(
            control,
            dict,
        ):
            control = {}

        if not bool(
            control.get(
                "found"
            )
        ):
            return {
                "ok": False,
                "uncertain": False,
                "clicked": False,
                "reason":
                    f"{prefix}_CONTROL_NOT_FOUND",
                "selector": selector,
                "control": control,
                "snapshot": summary,
                "_snapshot": initial,
            }

        aria_label = str(
            control.get(
                "aria_label"
            )
            or ""
        ).strip()

        if aria_label != expected_label:
            return {
                "ok": False,
                "uncertain": False,
                "clicked": False,
                "reason":
                    f"{prefix}_CONTROL_IDENTITY_MISMATCH",
                "selector": selector,
                "control": control,
                "snapshot": summary,
                "_snapshot": initial,
            }

        disabled = bool(
            control.get(
                "disabled"
            )
        )

        if (
            str(
                control.get(
                    "aria_disabled"
                )
                or ""
            ).strip().lower()
            == "true"
        ):
            disabled = True

        if disabled:
            return {
                "ok": False,
                "uncertain": False,
                "clicked": False,
                "reason":
                    f"{prefix}_CONTROL_DISABLED",
                "selector": selector,
                "control": control,
                "snapshot": summary,
                "_snapshot": initial,
            }

        try:
            element = (
                self.browser.find_element(
                    selector
                )
            )

        except Exception as exc:
            return {
                "ok": False,
                "uncertain": False,
                "clicked": False,
                "reason":
                    f"{prefix}_CONTROL_NOT_FOUND",
                "selector": selector,
                "error_type":
                    type(exc).__name__,
                "message":
                    str(exc),
                "snapshot": summary,
                "_snapshot": initial,
            }

        if element is None:
            return {
                "ok": False,
                "uncertain": False,
                "clicked": False,
                "reason":
                    f"{prefix}_CONTROL_NOT_FOUND",
                "selector": selector,
                "snapshot": summary,
                "_snapshot": initial,
            }

        click_attempted = False

        try:
            click_attempted = True

            mouse_click = getattr(
                element,
                "mouse_click",
                None,
            )

            if callable(
                mouse_click
            ):
                mouse_click()

            else:
                click = getattr(
                    element,
                    "click",
                    None,
                )

                if not callable(
                    click
                ):
                    return {
                        "ok": False,
                        "uncertain": False,
                        "clicked": False,
                        "reason":
                            f"{prefix}_CONTROL_NOT_CLICKABLE",
                        "selector": selector,
                        "snapshot": summary,
                        "_snapshot": initial,
                    }

                click()

        except Exception as exc:
            return {
                "ok": False,
                "uncertain": True,
                "clicked":
                    bool(
                        click_attempted
                    ),
                "reason":
                    f"{prefix}_CLICK_UNCERTAIN",
                "selector": selector,
                "error_type":
                    type(exc).__name__,
                "message":
                    str(exc),
                "snapshot": summary,
                "_snapshot": initial,
            }

        timeout = max(
            0.0,
            float(
                confirm_timeout
                or 0.0
            ),
        )

        interval = max(
            0.01,
            float(
                poll_interval
                or 0.05
            ),
        )

        deadline = (
            time.monotonic()
            + timeout
        )

        last_snapshot = initial

        while True:
            try:
                last_snapshot = (
                    self.read_call_snapshot()
                )

            except Exception:
                last_snapshot = None

            if normalized_action == "ACCEPT":
                if (
                    last_snapshot is not None
                    and bool(
                        getattr(
                            last_snapshot,
                            "present",
                            False,
                        )
                    )
                    and (
                        getattr(
                            last_snapshot,
                            "phase",
                            None,
                        )
                        in {
                            WHATSAPP_CALL_PHASE_CONNECTING,
                            WHATSAPP_CALL_PHASE_ACTIVE,
                        }
                        or bool(
                            getattr(
                                last_snapshot,
                                "can_hangup",
                                False,
                            )
                        )
                    )
                ):
                    return {
                        "ok": True,
                        "uncertain": False,
                        "clicked": True,
                        "reason":
                            "CALL_ACCEPTED",
                        "selector": selector,
                        "snapshot":
                            self._voice_call_snapshot_summary(
                                last_snapshot
                            ),
                        "_snapshot":
                            last_snapshot,
                    }

            else:
                if (
                    last_snapshot is not None
                    and (
                        not bool(
                            getattr(
                                last_snapshot,
                                "present",
                                False,
                            )
                        )
                        or getattr(
                            last_snapshot,
                            "phase",
                            None,
                        )
                        == WHATSAPP_CALL_PHASE_ENDED_TRANSIENT
                    )
                ):
                    return {
                        "ok": True,
                        "uncertain": False,
                        "clicked": True,
                        "reason":
                            "CALL_REJECTED",
                        "selector": selector,
                        "snapshot":
                            self._voice_call_snapshot_summary(
                                last_snapshot
                            ),
                        "_snapshot":
                            last_snapshot,
                    }

            if (
                time.monotonic()
                >= deadline
            ):
                break

            time.sleep(
                interval
            )

        # Side effect ya intentado:
        # jamás se vuelve a pulsar automáticamente.
        return {
            "ok": False,
            "uncertain": True,
            "clicked": True,
            "reason":
                (
                    "CALL_ACCEPT_UNCONFIRMED"
                    if normalized_action
                    == "ACCEPT"
                    else
                    "CALL_REJECT_UNCONFIRMED"
                ),
            "selector": selector,
            "snapshot":
                (
                    self._voice_call_snapshot_summary(
                        last_snapshot
                    )
                    if last_snapshot
                    is not None
                    else None
                ),
            "_snapshot":
                last_snapshot,
        }


    def accept_incoming_call(
        self,
        *,
        expected_provider_call_id=None,
        expected_external_call_key=None,
        confirm_timeout=2.0,
    ):
        return self._act_on_incoming_call(
            action="ACCEPT",
            expected_provider_call_id=(
                expected_provider_call_id
            ),
            expected_external_call_key=(
                expected_external_call_key
            ),
            confirm_timeout=(
                confirm_timeout
            ),
        )


    def reject_incoming_call(
        self,
        *,
        expected_provider_call_id=None,
        expected_external_call_key=None,
        confirm_timeout=2.0,
    ):
        return self._act_on_incoming_call(
            action="REJECT",
            expected_provider_call_id=(
                expected_provider_call_id
            ),
            expected_external_call_key=(
                expected_external_call_key
            ),
            confirm_timeout=(
                confirm_timeout
            ),
        )



    def read_primary_navigation_state(
        self,
    ):
        """Lee pasivamente la pestaña primaria activa."""
        if not self.browser:
            raise RuntimeError(
                "WhatsApp Web no está iniciado"
            )

        result = (
            self.browser.evaluate(
                """
                (() => {
                    const chats =
                        document.querySelector(
                            'button[aria-label="Chats"]'
                        );

                    const calls =
                        document.querySelector(
                            'button[aria-label="Llamadas"]'
                        );

                    return {
                        chats_present:
                            !!chats,

                        calls_present:
                            !!calls,

                        chats_pressed:
                            chats
                            ? chats.getAttribute(
                                "aria-pressed"
                            )
                            : null,

                        calls_pressed:
                            calls
                            ? calls.getAttribute(
                                "aria-pressed"
                            )
                            : null,
                    };
                })()
                """
            )
            or {}
        )

        return {
            "chats_present":
                bool(
                    result.get(
                        "chats_present"
                    )
                ),

            "calls_present":
                bool(
                    result.get(
                        "calls_present"
                    )
                ),

            "chats_pressed":
                result.get(
                    "chats_pressed"
                ),

            "calls_pressed":
                result.get(
                    "calls_pressed"
                ),
        }


    def _activate_primary_navigation_tab(
        self,
        tab,
        *,
        timeout=5,
    ):
        """
        Activa exactamente una pestaña primaria.

        Hace como máximo un click.
        Después solo observa aria-pressed.
        """
        import time

        normalized = str(
            tab
            or ""
        ).strip().upper()

        if normalized == "CHATS":
            selector = (
                WHATSAPP_CHATS_TAB_SELECTOR
            )
            state_key = (
                "chats_pressed"
            )

        elif normalized == "CALLS":
            selector = (
                WHATSAPP_CALLS_TAB_SELECTOR
            )
            state_key = (
                "calls_pressed"
            )

        else:
            raise ValueError(
                "Pestaña WhatsApp no válida"
            )

        before = (
            self
            .read_primary_navigation_state()
        )

        if (
            before.get(
                state_key
            )
            == "true"
        ):
            return {
                "tab":
                    normalized,
                "clicked":
                    False,
                "already_active":
                    True,
                "state":
                    before,
            }

        script = f"""
            (() => {{
                const button =
                    document.querySelector(
                        {selector!r}
                    );

                if (!button) {{
                    return {{
                        clicked: false,
                        reason:
                            "BUTTON_NOT_FOUND"
                    }};
                }}

                if (
                    button.disabled
                    || button.getAttribute(
                        "aria-disabled"
                    ) === "true"
                ) {{
                    return {{
                        clicked: false,
                        reason:
                            "BUTTON_DISABLED"
                    }};
                }}

                button.click();

                return {{
                    clicked: true,
                    reason: null
                }};
            }})()
        """

        click_result = (
            self.browser.evaluate(
                script
            )
            or {}
        )

        if not click_result.get(
            "clicked"
        ):
            raise RuntimeError(
                "No se pudo activar "
                f"{normalized}: "
                + str(
                    click_result.get(
                        "reason"
                    )
                    or "UNKNOWN"
                )
            )

        deadline = (
            time.time()
            + max(
                0.5,
                float(timeout),
            )
        )

        while time.time() < deadline:
            current = (
                self
                .read_primary_navigation_state()
            )

            if (
                current.get(
                    state_key
                )
                == "true"
            ):
                return {
                    "tab":
                        normalized,
                    "clicked":
                        True,
                    "already_active":
                        False,
                    "state":
                        current,
                }

            time.sleep(
                0.1
            )

        raise TimeoutError(
            "WhatsApp no confirmó "
            f"pestaña {normalized}"
        )


    def open_calls_tab(
        self,
        *,
        timeout=5,
    ):
        return (
            self
            ._activate_primary_navigation_tab(
                "CALLS",
                timeout=timeout,
            )
        )


    def open_chats_tab(
        self,
        *,
        timeout=5,
    ):
        return (
            self
            ._activate_primary_navigation_tab(
                "CHATS",
                timeout=timeout,
            )
        )


    def read_visible_call_history(
        self,
    ):
        """Lee pasivamente el historial visible de llamadas."""
        return read_whatsapp_call_history(
            self.browser
        )


    def read_call_snapshot(
        self,
    ):
        """Lee pasivamente la superficie de llamada WhatsApp."""
        return read_whatsapp_call_snapshot(
            self.browser
        )


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
        """Finaliza la sesión WhatsApp únicamente si es propia.

        El lifecycle físico pertenece a
        ``SeleniumBaseBrowserSession``.

        Un browser inyectado externamente sin BrowserSession
        asociada no se destruye: el connector no puede asumir
        ownership de un recurso que no creó.

        Deliberadamente NO utiliza ``driver.stop()``.
        """

        session = (
            self._browser_session
        )

        if session is None:
            return False

        try:
            result = session.shutdown(
                BrowserShutdownMode.CLOSE
            )
        except Exception:
            return False

        successful = bool(
            result is not None
            and not result.has_error
            and result.control_released
            is True
            and result.browser_closed
            is True
        )

        if successful:
            self.browser = None
            self._browser_session = None

        return successful
