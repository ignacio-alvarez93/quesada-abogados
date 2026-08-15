"""
Contratos puros de infraestructura de navegador.

Este módulo define vocabulario común para las automatizaciones del ERP.

No conoce:
- SeleniumBase;
- Chrome;
- Flet;
- SQLite;
- WhatsApp;
- Mercurio;
- DEHú.

Las implementaciones concretas pertenecen a capas posteriores.
"""

from dataclasses import dataclass
from enum import Enum


class BrowserSessionMode(str, Enum):
    """
    Naturaleza funcional de una sesión de navegador.
    """

    EPHEMERAL = "EPHEMERAL"
    PERSISTENT = "PERSISTENT"
    ASSISTED = "ASSISTED"


class BrowserSessionState(str, Enum):
    """
    Estado técnico común de una sesión de navegador.

    No representa estados funcionales del proveedor.
    """

    CREATED = "CREATED"
    STARTING = "STARTING"
    READY = "READY"
    NEEDS_USER_ACTION = "NEEDS_USER_ACTION"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"
    FAILED = "FAILED"
    STOPPING = "STOPPING"
    CLOSED = "CLOSED"


class BrowserShutdownMode(str, Enum):
    """
    Intención de finalización de una sesión.

    DETACH:
        dejar de controlar el navegador sin exigir su cierre.

    CLOSE:
        solicitar un cierre ordenado de la sesión.

    KILL:
        terminación forzada extraordinaria.
    """

    DETACH = "DETACH"
    CLOSE = "CLOSE"
    KILL = "KILL"


class BrowserInfrastructureError(RuntimeError):
    """
    Error base de infraestructura de navegador.
    """


class BrowserSessionConfigurationError(
    BrowserInfrastructureError,
    ValueError,
):
    """
    Configuración inválida de una sesión.
    """


class BrowserSessionLifecycleError(
    BrowserInfrastructureError,
):
    """
    Violación o fallo del ciclo de vida de una sesión.
    """


class BrowserSessionControlError(
    BrowserInfrastructureError,
):
    """
    Pérdida o imposibilidad de control de una sesión.
    """


def _normalize_enum(
    value,
    enum_type,
    *,
    field_name,
):
    if isinstance(
        value,
        enum_type,
    ):
        return value

    try:
        return enum_type(
            str(value or "")
            .strip()
            .upper()
        )
    except ValueError as exc:
        raise BrowserSessionConfigurationError(
            f"{field_name} inválido: {value!r}"
        ) from exc


@dataclass(
    frozen=True,
)
class BrowserSessionConfig:
    """
    Configuración lógica de una sesión.

    ``consumer`` identifica quién solicita la sesión:
    por ejemplo whatsapp, mercurio o dehu.

    ``profile_key`` es una identidad lógica.
    Este contrato no conoce ni resuelve rutas físicas.
    """

    consumer: str
    mode: BrowserSessionMode = (
        BrowserSessionMode.EPHEMERAL
    )
    headless: bool = False
    profile_key: str | None = None

    def __post_init__(
        self,
    ):
        consumer = str(
            self.consumer
            or ""
        ).strip()

        if not consumer:
            raise BrowserSessionConfigurationError(
                "consumer no puede estar vacío"
            )

        mode = _normalize_enum(
            self.mode,
            BrowserSessionMode,
            field_name="mode",
        )

        profile_key = (
            None
            if self.profile_key is None
            else str(
                self.profile_key
            ).strip()
        )

        if (
            self.profile_key is not None
            and not profile_key
        ):
            raise BrowserSessionConfigurationError(
                "profile_key no puede estar vacío"
            )

        object.__setattr__(
            self,
            "consumer",
            consumer,
        )

        object.__setattr__(
            self,
            "mode",
            mode,
        )

        object.__setattr__(
            self,
            "headless",
            bool(
                self.headless
            ),
        )

        object.__setattr__(
            self,
            "profile_key",
            profile_key,
        )


@dataclass(
    frozen=True,
)
class BrowserSessionIdentity:
    """
    Identidad lógica e inmutable de una instancia de sesión.

    ``session_id`` identifica una ejecución concreta.

    ``consumer``, ``mode`` y ``profile_key`` permiten
    correlacionarla con la configuración que la originó.

    No contiene:
    - PID;
    - ruta física de perfil;
    - browser;
    - driver;
    - thread;
    - event loop.
    """

    session_id: str
    consumer: str
    mode: BrowserSessionMode
    profile_key: str | None = None

    def __post_init__(
        self,
    ):
        session_id = str(
            self.session_id
            or ""
        ).strip()

        consumer = str(
            self.consumer
            or ""
        ).strip()

        if not session_id:
            raise BrowserSessionConfigurationError(
                "session_id no puede estar vacío"
            )

        if not consumer:
            raise BrowserSessionConfigurationError(
                "consumer no puede estar vacío"
            )

        mode = _normalize_enum(
            self.mode,
            BrowserSessionMode,
            field_name="mode",
        )

        profile_key = (
            None
            if self.profile_key is None
            else str(
                self.profile_key
            ).strip()
        )

        if (
            self.profile_key is not None
            and not profile_key
        ):
            raise BrowserSessionConfigurationError(
                "profile_key no puede estar vacío"
            )

        object.__setattr__(
            self,
            "session_id",
            session_id,
        )

        object.__setattr__(
            self,
            "consumer",
            consumer,
        )

        object.__setattr__(
            self,
            "mode",
            mode,
        )

        object.__setattr__(
            self,
            "profile_key",
            profile_key,
        )

    @classmethod
    def from_config(
        cls,
        *,
        session_id,
        config,
    ):
        if not isinstance(
            config,
            BrowserSessionConfig,
        ):
            raise BrowserSessionConfigurationError(
                "config debe ser BrowserSessionConfig"
            )

        return cls(
            session_id=session_id,
            consumer=config.consumer,
            mode=config.mode,
            profile_key=config.profile_key,
        )


@dataclass(
    frozen=True,
)
class BrowserSessionHealth:
    """
    Fotografía técnica y pasiva de una sesión.

    ``worker_available`` puede ser None cuando el consumidor
    no utiliza un worker dedicado.

    No incluye estados funcionales específicos del proveedor.
    """

    state: BrowserSessionState
    browser_available: bool = False
    control_available: bool = False
    worker_available: bool | None = None
    detail: str = ""
    last_error: str = ""

    def __post_init__(
        self,
    ):
        state = _normalize_enum(
            self.state,
            BrowserSessionState,
            field_name="state",
        )

        object.__setattr__(
            self,
            "state",
            state,
        )

        object.__setattr__(
            self,
            "browser_available",
            bool(
                self.browser_available
            ),
        )

        object.__setattr__(
            self,
            "control_available",
            bool(
                self.control_available
            ),
        )

        if (
            self.worker_available
            is not None
        ):
            object.__setattr__(
                self,
                "worker_available",
                bool(
                    self.worker_available
                ),
            )

        object.__setattr__(
            self,
            "detail",
            str(
                self.detail
                or ""
            ),
        )

        object.__setattr__(
            self,
            "last_error",
            str(
                self.last_error
                or ""
            ),
        )

@dataclass(
    frozen=True,
)
class BrowserSessionTransition:
    """
    Transición técnica de estado de una sesión.

    Este contrato describe un cambio ya decidido u observado.

    No define todavía la matriz de transiciones permitidas.
    Esa política pertenecerá al lifecycle de BrowserSession.

    ``reason`` y ``detail`` son diagnósticos técnicos.
    No representan estados de negocio del proveedor.
    """

    previous_state: BrowserSessionState
    current_state: BrowserSessionState
    reason: str = ""
    detail: str = ""

    def __post_init__(
        self,
    ):
        previous_state = _normalize_enum(
            self.previous_state,
            BrowserSessionState,
            field_name="previous_state",
        )

        current_state = _normalize_enum(
            self.current_state,
            BrowserSessionState,
            field_name="current_state",
        )

        if (
            previous_state
            == current_state
        ):
            raise BrowserSessionLifecycleError(
                "Una transición requiere cambio de estado"
            )

        object.__setattr__(
            self,
            "previous_state",
            previous_state,
        )

        object.__setattr__(
            self,
            "current_state",
            current_state,
        )

        object.__setattr__(
            self,
            "reason",
            str(
                self.reason
                or ""
            ).strip(),
        )

        object.__setattr__(
            self,
            "detail",
            str(
                self.detail
                or ""
            ),
        )


@dataclass(
    frozen=True,
)
class BrowserShutdownResult:
    """
    Resultado técnico de una petición de shutdown.

    Separa hechos que no deben confundirse:

    ``control_released``:
        la infraestructura ya no controla la sesión.

    ``browser_closed``:
        se ha verificado que el navegador quedó cerrado.

    ``process_terminated``:
        se ha verificado que el proceso correspondiente terminó.

    ``browser_closed`` y ``process_terminated`` son tri-state:
    None significa que ese hecho no se conoce o no aplica.

    El contrato no conoce stop(), quit(), close(), disconnect()
    ni ninguna implementación concreta de SeleniumBase.
    """

    mode: BrowserShutdownMode
    state_before: BrowserSessionState
    state_after: BrowserSessionState
    control_released: bool = False
    browser_closed: bool | None = None
    process_terminated: bool | None = None
    detail: str = ""
    error: str = ""

    def __post_init__(
        self,
    ):
        mode = _normalize_enum(
            self.mode,
            BrowserShutdownMode,
            field_name="mode",
        )

        state_before = _normalize_enum(
            self.state_before,
            BrowserSessionState,
            field_name="state_before",
        )

        state_after = _normalize_enum(
            self.state_after,
            BrowserSessionState,
            field_name="state_after",
        )

        object.__setattr__(
            self,
            "mode",
            mode,
        )

        object.__setattr__(
            self,
            "state_before",
            state_before,
        )

        object.__setattr__(
            self,
            "state_after",
            state_after,
        )

        object.__setattr__(
            self,
            "control_released",
            bool(
                self.control_released
            ),
        )

        if (
            self.browser_closed
            is not None
        ):
            object.__setattr__(
                self,
                "browser_closed",
                bool(
                    self.browser_closed
                ),
            )

        if (
            self.process_terminated
            is not None
        ):
            object.__setattr__(
                self,
                "process_terminated",
                bool(
                    self.process_terminated
                ),
            )

        object.__setattr__(
            self,
            "detail",
            str(
                self.detail
                or ""
            ),
        )

        object.__setattr__(
            self,
            "error",
            str(
                self.error
                or ""
            ),
        )

    @property
    def has_error(
        self,
    ):
        return bool(
            self.error
        )


@dataclass(
    frozen=True,
)
class BrowserSessionSnapshot:
    """
    Fotografía técnica inmutable de una sesión concreta.

    Combina identidad y health sin introducir detalles
    específicos de SeleniumBase ni del proveedor.
    """

    identity: BrowserSessionIdentity
    health: BrowserSessionHealth

    def __post_init__(
        self,
    ):
        if not isinstance(
            self.identity,
            BrowserSessionIdentity,
        ):
            raise BrowserSessionConfigurationError(
                "identity debe ser BrowserSessionIdentity"
            )

        if not isinstance(
            self.health,
            BrowserSessionHealth,
        ):
            raise BrowserSessionConfigurationError(
                "health debe ser BrowserSessionHealth"
            )

    @property
    def state(
        self,
    ):
        return self.health.state
