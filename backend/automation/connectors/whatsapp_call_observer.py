"""
Observador pasivo de llamadas de WhatsApp Web.

Responsabilidad:
- leer la superficie VOIP actualmente materializada;
- normalizar lifecycle observable;
- extraer identidad técnica del proveedor;
- devolver WhatsAppCallSnapshot.

No:
- navega;
- hace click;
- modifica el DOM;
- persiste;
- conoce CommunicationCall;
- conoce SQLite/Supabase;
- conoce Flet.
"""

from dataclasses import dataclass
import re


WHATSAPP_CALL_DIRECTION_INBOUND = (
    "INBOUND"
)

WHATSAPP_CALL_DIRECTION_OUTBOUND = (
    "OUTBOUND"
)

WHATSAPP_CALL_DIRECTION_UNKNOWN = (
    "UNKNOWN"
)

WHATSAPP_CALL_PHASE_ABSENT = (
    "ABSENT"
)

WHATSAPP_CALL_PHASE_SURFACE_PRESENT = (
    "SURFACE_PRESENT"
)

WHATSAPP_CALL_PHASE_INCOMING_RINGING = (
    "INCOMING_RINGING"
)

WHATSAPP_CALL_PHASE_OUTGOING_DIALING = (
    "OUTGOING_DIALING"
)

WHATSAPP_CALL_PHASE_CONNECTING = (
    "CONNECTING"
)

WHATSAPP_CALL_PHASE_ACTIVE = (
    "ACTIVE"
)

WHATSAPP_CALL_PHASE_ENDED_TRANSIENT = (
    "ENDED_TRANSIENT"
)


@dataclass(frozen=True)
class WhatsAppCallSnapshot:
    """Fotografía pasiva de la superficie VOIP de WhatsApp Web.

    Es un modelo exclusivo del transporte WhatsApp.

    No:
    - persiste;
    - conoce CommunicationCall;
    - conoce SQLite;
    - conoce clientes;
    - ejecuta acciones sobre la llamada.
    """

    present: bool
    phase: str
    direction: str

    provider_call_id: str | None = None
    external_call_key: str | None = None

    participant_lid: str | None = None
    participant_phone_id: str | None = None
    participant_phone: str | None = None
    participant_display_name: str | None = None

    is_video: bool | None = None
    visible_state: str | None = None

    can_accept: bool = False
    can_reject: bool = False
    can_hangup: bool = False

    identity_complete: bool = False


def read_whatsapp_call_snapshot(
    browser,
):
    """Lee pasivamente la superficie de llamada WhatsApp.

    Ejecuta una única lectura JavaScript.

    La superficie DOM estable se usa para lifecycle/controles.
    React se consulta de forma acotada únicamente para obtener:
    - identidad técnica del interlocutor;
    - provider call id;
    - external call key;
    - tipo voz/vídeo.

    No hace click.
    No navega.
    No modifica el DOM.
    No persiste.
    """
    if not browser:
        raise RuntimeError(
            "WhatsApp Web no está iniciado"
        )

    raw = (
        browser.evaluate(
            r"""
            (() => {
                const clean = value =>
                    String(
                        value ?? ""
                    )
                    .replace(
                        /\s+/g,
                        " "
                    )
                    .trim();


                const serializeId = value => {
                    if (!value) {
                        return null;
                    }

                    try {
                        return (
                            value._serialized
                            || value.user
                            || null
                        );
                    }
                    catch (_) {
                        return null;
                    }
                };


                const getReactProps = node => {
                    if (!node) {
                        return [];
                    }

                    const result = [];

                    for (
                        const key
                        of Object.getOwnPropertyNames(
                            node
                        )
                    ) {
                        if (
                            !key.startsWith(
                                "__reactProps$"
                            )
                        ) {
                            continue;
                        }

                        try {
                            result.push(
                                node[key]
                            );
                        }
                        catch (_) {}
                    }

                    return result;
                };


                const getReactFibers = node => {
                    if (!node) {
                        return [];
                    }

                    const result = [];

                    for (
                        const key
                        of Object.getOwnPropertyNames(
                            node
                        )
                    ) {
                        if (
                            !key.startsWith(
                                "__reactFiber$"
                            )
                        ) {
                            continue;
                        }

                        try {
                            result.push(
                                node[key]
                            );
                        }
                        catch (_) {}
                    }

                    return result;
                };


                const findObject = (
                    roots,
                    predicate,
                    maxDepth,
                    maxNodes
                ) => {
                    const queue =
                        roots
                        .filter(Boolean)
                        .map(
                            value => ({
                                value:
                                    value,

                                depth:
                                    0
                            })
                        );

                    const visited =
                        new WeakSet();

                    let inspected = 0;


                    while (
                        queue.length
                        && inspected < maxNodes
                    ) {
                        const current =
                            queue.shift();

                        const value =
                            current.value;

                        if (
                            !value
                            || (
                                typeof value !== "object"
                                && typeof value !== "function"
                            )
                        ) {
                            continue;
                        }

                        if (
                            visited.has(
                                value
                            )
                        ) {
                            continue;
                        }

                        visited.add(
                            value
                        );

                        inspected += 1;


                        try {
                            if (
                                predicate(
                                    value
                                )
                            ) {
                                return value;
                            }
                        }
                        catch (_) {}


                        if (
                            current.depth
                            >= maxDepth
                        ) {
                            continue;
                        }


                        let keys = [];

                        try {
                            keys =
                                Object.keys(
                                    value
                                );
                        }
                        catch (_) {
                            continue;
                        }


                        for (
                            const key
                            of keys.slice(
                                0,
                                120
                            )
                        ) {
                            let child;

                            try {
                                child =
                                    value[key];
                            }
                            catch (_) {
                                continue;
                            }

                            if (
                                child
                                && (
                                    typeof child
                                        === "object"
                                    || typeof child
                                        === "function"
                                )
                            ) {
                                queue.push({
                                    value:
                                        child,

                                    depth:
                                        current.depth
                                        + 1
                                });
                            }
                        }
                    }

                    return null;
                };


                const isContact = value => {
                    try {
                        return Boolean(
                            value
                            && value.__x_id
                            && value.__x_phoneNumber
                        );
                    }
                    catch (_) {
                        return false;
                    }
                };


                const isCallLog = value => {
                    try {
                        return Boolean(
                            value
                            && (
                                value.__x_type
                                    === "call_log"
                                || value.kind
                                    === "callLog"
                            )
                        );
                    }
                    catch (_) {
                        return false;
                    }
                };


                const surface =
                    document.querySelector(
                        '[data-testid="move_resize_component"]'
                    );

                if (!surface) {
                    return {
                        surface_present:
                            false,

                        surface_text:
                            "",

                        participant_name:
                            "",

                        visible_state:
                            "",

                        controls:
                            [],

                        provider_call_id:
                            null,

                        external_call_key:
                            null,

                        participant_lid:
                            null,

                        participant_phone_id:
                            null,

                        is_video:
                            null
                    };
                }


                const audioCall =
                    document.querySelector(
                        '[data-testid="voip-container-audio-call"]'
                    );

                const participant =
                    document.querySelector(
                        '[data-testid="voip-call-participant-info-name"]'
                    );

                const stateText =
                    document.querySelector(
                        '[data-testid="voip-call-participant-info-call-state-text"]'
                    );


                const controls =
                    Array.from(
                        surface.querySelectorAll(
                            'button, [role="button"]'
                        )
                    )
                    .map(
                        node =>
                            clean(
                                node.getAttribute(
                                    "aria-label"
                                )
                                || node.innerText
                                || node.textContent
                            )
                    )
                    .filter(Boolean);


                /*
                 * CONTACTO
                 *
                 * La identidad del interlocutor apareció
                 * en los props del participante durante
                 * los probes reales.
                 *
                 * Se inspeccionan solo props cercanos;
                 * no se recorre el árbol React global.
                 */
                const contactRoots = [
                    ...getReactProps(
                        participant
                    ),

                    ...getReactProps(
                        audioCall
                    )
                ];


                for (
                    const fiber
                    of getReactFibers(
                        participant
                    )
                ) {
                    try {
                        if (
                            fiber.memoizedProps
                        ) {
                            contactRoots.push(
                                fiber.memoizedProps
                            );
                        }
                    }
                    catch (_) {}
                }


                const contact =
                    findObject(
                        contactRoots,
                        isContact,
                        6,
                        350
                    );


                /*
                 * CALL LOG
                 *
                 * En las pruebas reales msg=call_log
                 * aparece en memoizedProps de un ancestro
                 * cercano al Fiber de la superficie.
                 *
                 * Solo se recorre la cadena return,
                 * con un máximo estricto.
                 */
                let callLog = null;

                const callFibers = [
                    ...getReactFibers(
                        surface
                    ),

                    ...getReactFibers(
                        audioCall
                    )
                ];


                for (
                    const rootFiber
                    of callFibers
                ) {
                    let fiber =
                        rootFiber;

                    for (
                        let depth = 0;
                        fiber && depth < 9;
                        depth += 1
                    ) {
                        let memoizedProps =
                            null;

                        let pendingProps =
                            null;

                        try {
                            memoizedProps =
                                fiber.memoizedProps;
                        }
                        catch (_) {}

                        try {
                            pendingProps =
                                fiber.pendingProps;
                        }
                        catch (_) {}


                        const directCandidates = [];

                        if (
                            memoizedProps
                        ) {
                            directCandidates.push(
                                memoizedProps.msg,
                                memoizedProps
                            );
                        }

                        if (
                            pendingProps
                        ) {
                            directCandidates.push(
                                pendingProps.msg,
                                pendingProps
                            );
                        }


                        callLog =
                            findObject(
                                directCandidates,
                                isCallLog,
                                3,
                                120
                            );

                        if (
                            callLog
                        ) {
                            break;
                        }


                        try {
                            fiber =
                                fiber.return;
                        }
                        catch (_) {
                            fiber =
                                null;
                        }
                    }

                    if (
                        callLog
                    ) {
                        break;
                    }
                }


                let providerCallId =
                    null;

                let externalCallKey =
                    null;

                let isVideo =
                    null;


                if (
                    callLog
                ) {
                    try {
                        providerCallId =
                            clean(
                                callLog.__x_id
                                && callLog.__x_id.id
                            )
                            || null;
                    }
                    catch (_) {}


                    try {
                        externalCallKey =
                            clean(
                                callLog.__x_id
                                && callLog.__x_id.$1
                            )
                            || null;
                    }
                    catch (_) {}


                    try {
                        if (
                            typeof callLog
                                .__x_isVideoCall
                            === "boolean"
                        ) {
                            isVideo =
                                callLog
                                .__x_isVideoCall;
                        }
                    }
                    catch (_) {}
                }


                let participantLid =
                    null;

                let participantPhoneId =
                    null;


                if (
                    contact
                ) {
                    try {
                        participantLid =
                            serializeId(
                                contact.__x_id
                            );
                    }
                    catch (_) {}


                    try {
                        participantPhoneId =
                            serializeId(
                                contact
                                .__x_phoneNumber
                            );
                    }
                    catch (_) {}
                }


                return {
                    surface_present:
                        true,

                    surface_text:
                        clean(
                            surface.innerText
                            || surface.textContent
                        ).slice(
                            0,
                            500
                        ),

                    participant_name:
                        clean(
                            participant
                            ? (
                                participant.innerText
                                || participant.textContent
                            )
                            : ""
                        ),

                    visible_state:
                        clean(
                            stateText
                            ? (
                                stateText.innerText
                                || stateText.textContent
                            )
                            : ""
                        ),

                    controls:
                        controls,

                    provider_call_id:
                        providerCallId,

                    external_call_key:
                        externalCallKey,

                    participant_lid:
                        participantLid,

                    participant_phone_id:
                        participantPhoneId,

                    is_video:
                        isVideo
                };
            })()
            """
        )
        or {}
    )


    present = bool(
        raw.get(
            "surface_present"
        )
    )


    if not present:
        return WhatsAppCallSnapshot(
            present=False,
            phase=(
                WHATSAPP_CALL_PHASE_ABSENT
            ),
            direction=(
                WHATSAPP_CALL_DIRECTION_UNKNOWN
            ),
        )


    provider_call_id = (
        str(
            raw.get(
                "provider_call_id"
            )
            or ""
        ).strip()
        or None
    )

    external_call_key = (
        str(
            raw.get(
                "external_call_key"
            )
            or ""
        ).strip()
        or None
    )

    participant_lid = (
        str(
            raw.get(
                "participant_lid"
            )
            or ""
        ).strip()
        or None
    )

    participant_phone_id = (
        str(
            raw.get(
                "participant_phone_id"
            )
            or ""
        ).strip()
        or None
    )

    participant_display_name = (
        str(
            raw.get(
                "participant_name"
            )
            or ""
        ).strip()
        or None
    )

    visible_state = (
        str(
            raw.get(
                "visible_state"
            )
            or ""
        ).strip()
        or None
    )

    surface_text = str(
        raw.get(
            "surface_text"
        )
        or ""
    ).strip()


    participant_phone = None

    if participant_phone_id:
        phone_base = (
            participant_phone_id
            .split(
                "@",
                1,
            )[0]
        )

        phone_digits = re.sub(
            r"\D+",
            "",
            phone_base,
        )

        if phone_digits:
            participant_phone = (
                "+"
                + phone_digits
            )


    controls = tuple(
        str(
            value
            or ""
        ).strip()
        for value in (
            raw.get(
                "controls"
            )
            or []
        )
        if str(
            value
            or ""
        ).strip()
    )


    normalized_controls = tuple(
        value.casefold()
        for value in controls
    )


    can_accept = any(
        (
            value == "aceptar"
            or value == "accept"
            or value == "answer"
        )
        for value in normalized_controls
    )

    can_reject = any(
        (
            value == "rechazar"
            or value == "reject"
            or value == "decline"
        )
        for value in normalized_controls
    )

    can_hangup = any(
        (
            "finalizar llamada"
            in value
            or "end call"
            in value
            or "hang up"
            in value
        )
        for value in normalized_controls
    )


    direction = (
        WHATSAPP_CALL_DIRECTION_UNKNOWN
    )

    if external_call_key:
        lowered_key = (
            external_call_key
            .casefold()
        )

        if lowered_key.startswith(
            "true_"
        ):
            direction = (
                WHATSAPP_CALL_DIRECTION_OUTBOUND
            )

        elif lowered_key.startswith(
            "false_"
        ):
            direction = (
                WHATSAPP_CALL_DIRECTION_INBOUND
            )


    state_folded = (
        visible_state
        or ""
    ).casefold()

    surface_folded = (
        surface_text
        or ""
    ).casefold()


    outgoing_signal = any(
        token in state_folded
        for token in (
            "llamando",
            "calling",
        )
    )

    ended_signal = any(
        token in (
            state_folded
            + " "
            + surface_folded
        )
        for token in (
            "llamada finalizada",
            "call ended",
        )
    )


    if (
        direction
        == WHATSAPP_CALL_DIRECTION_UNKNOWN
        and can_accept
        and can_reject
    ):
        direction = (
            WHATSAPP_CALL_DIRECTION_INBOUND
        )

    elif (
        direction
        == WHATSAPP_CALL_DIRECTION_UNKNOWN
        and outgoing_signal
    ):
        direction = (
            WHATSAPP_CALL_DIRECTION_OUTBOUND
        )


    timer_visible = bool(
        visible_state
        and re.fullmatch(
            r"\d+:\d{2}"
            r"(?::\d{2})?",
            visible_state,
        )
    )


    if ended_signal:
        phase = (
            WHATSAPP_CALL_PHASE_ENDED_TRANSIENT
        )

    elif (
        can_accept
        and can_reject
    ):
        phase = (
            WHATSAPP_CALL_PHASE_INCOMING_RINGING
        )

    elif timer_visible:
        phase = (
            WHATSAPP_CALL_PHASE_ACTIVE
        )

    elif outgoing_signal:
        phase = (
            WHATSAPP_CALL_PHASE_OUTGOING_DIALING
        )

    elif can_hangup:
        phase = (
            WHATSAPP_CALL_PHASE_CONNECTING
        )

    else:
        phase = (
            WHATSAPP_CALL_PHASE_SURFACE_PRESENT
        )


    is_video_raw = raw.get(
        "is_video"
    )

    is_video = (
        is_video_raw
        if isinstance(
            is_video_raw,
            bool,
        )
        else None
    )


    identity_complete = all(
        (
            provider_call_id,
            external_call_key,
            participant_lid,
            participant_phone_id,
        )
    )


    return WhatsAppCallSnapshot(
        present=True,
        phase=phase,
        direction=direction,
        provider_call_id=(
            provider_call_id
        ),
        external_call_key=(
            external_call_key
        ),
        participant_lid=(
            participant_lid
        ),
        participant_phone_id=(
            participant_phone_id
        ),
        participant_phone=(
            participant_phone
        ),
        participant_display_name=(
            participant_display_name
        ),
        is_video=is_video,
        visible_state=(
            visible_state
        ),
        can_accept=can_accept,
        can_reject=can_reject,
        can_hangup=can_hangup,
        identity_complete=(
            identity_complete
        ),
    )
