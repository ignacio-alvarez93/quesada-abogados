"""
Lector pasivo del historial visible de llamadas de WhatsApp Web.

No:
- navega;
- hace click;
- modifica DOM;
- persiste;
- conoce SQLite;
- conoce CommunicationCall.

Devuelve hechos provider-level.
"""


CALL_HISTORY_JS = r"""
(() => {
    const clean = value =>
        String(value ?? "")
        .replace(/\s+/g, " ")
        .trim();


    const visible = node => {
        if (!node) return false;

        try {
            const rect = node.getBoundingClientRect();
            const style = getComputedStyle(node);

            return (
                rect.width > 0
                && rect.height > 0
                && style.display !== "none"
                && style.visibility !== "hidden"
            );
        }
        catch (_) {
            return false;
        }
    };


    const reactProps = node => {
        const result = [];

        if (!node) return result;

        for (
            const key
            of Object.getOwnPropertyNames(node)
        ) {
            if (
                key.startsWith("__reactProps$")
            ) {
                try {
                    result.push(node[key]);
                }
                catch (_) {}
            }
        }

        return result;
    };


    const reactFibers = node => {
        const result = [];

        if (!node) return result;

        for (
            const key
            of Object.getOwnPropertyNames(node)
        ) {
            if (
                key.startsWith("__reactFiber$")
            ) {
                try {
                    result.push(node[key]);
                }
                catch (_) {}
            }
        }

        return result;
    };


    const findObjects = (
        roots,
        predicate,
        maxDepth,
        maxNodes,
        maxResults
    ) => {
        const queue = roots
            .filter(Boolean)
            .map(value => ({
                value,
                depth: 0,
            }));

        const visited = new WeakSet();
        const found = [];

        let inspected = 0;

        while (
            queue.length
            && inspected < maxNodes
            && found.length < maxResults
        ) {
            const current = queue.shift();
            const value = current.value;

            if (
                !value
                || (
                    typeof value !== "object"
                    && typeof value !== "function"
                )
            ) {
                continue;
            }

            if (visited.has(value)) {
                continue;
            }

            visited.add(value);
            inspected += 1;

            try {
                if (predicate(value)) {
                    found.push(value);
                }
            }
            catch (_) {}

            if (
                current.depth >= maxDepth
            ) {
                continue;
            }

            let keys = [];

            try {
                keys = Object.keys(value);
            }
            catch (_) {
                continue;
            }

            for (
                const key
                of keys.slice(0, 120)
            ) {
                let child;

                try {
                    child = value[key];
                }
                catch (_) {
                    continue;
                }

                if (
                    child
                    && (
                        typeof child === "object"
                        || typeof child === "function"
                    )
                ) {
                    queue.push({
                        value: child,
                        depth:
                            current.depth + 1,
                    });
                }
            }
        }

        return found;
    };


    const serializeId = value => {
        if (!value) return null;

        try {
            return (
                value._serialized
                || value.user
                || value.id
                || null
            );
        }
        catch (_) {
            return null;
        }
    };


    const isCallLog = value => {
        try {
            return Boolean(
                value
                && (
                    value.__x_type === "call_log"
                    || value.kind === "callLog"
                )
            );
        }
        catch (_) {
            return false;
        }
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


    const parseExternalKey = value => {
        const text = clean(value);

        const match = text.match(
            /^(true|false)_(.+?@lid)_(.+)$/i
        );

        if (!match) {
            return null;
        }

        return {
            direction:
                match[1].toLowerCase()
                === "true"
                    ? "OUTBOUND"
                    : "INBOUND",

            peer_lid:
                match[2],

            provider_call_id:
                match[3],
        };
    };


    const callSummary = value => {
        let providerCallId = null;
        let externalCallKey = null;

        try {
            providerCallId =
                clean(
                    value.__x_id
                    && value.__x_id.id
                )
                || null;
        }
        catch (_) {}

        try {
            externalCallKey =
                clean(
                    value.__x_id
                    && value.__x_id.$1
                )
                || null;
        }
        catch (_) {}

        const identity =
            parseExternalKey(
                externalCallKey
            );

        if (!identity) {
            return null;
        }

        return {
            provider_call_id:
                providerCallId,

            external_call_key:
                externalCallKey,

            peer_lid:
                identity.peer_lid,

            direction:
                identity.direction,

            provider_timestamp:
                value.__x_t
                ?? null,

            call_duration_seconds:
                value.__x_callDuration
                ?? null,

            raw_outcome:
                value.__x_callOutcome
                ?? null,

            raw_final_outcome:
                value.__x_finalCallOutcome
                ?? null,

            is_video:
                value.__x_isVideoCall
                ?? null,
        };
    };


    const contactSummary = value => ({
        lid:
            serializeId(
                value.__x_id
            ),

        phone_id:
            serializeId(
                value.__x_phoneNumber
            ),

        display_name:
            clean(
                value.__x_name
                || value.__x_formattedName
                || value.__x_pushname
                || value.__x_shortName
                || ""
            )
            || null,
    });


    const dedupeCalls = values => {
        const result = [];
        const seen = new Set();

        for (const value of values) {
            const item =
                callSummary(value);

            if (
                !item
                || !item.external_call_key
                || seen.has(
                    item.external_call_key
                )
            ) {
                continue;
            }

            seen.add(
                item.external_call_key
            );

            result.push(item);
        }

        return result;
    };


    const dedupeContacts = values => {
        const result = [];
        const seen = new Set();

        for (const value of values) {
            const item =
                contactSummary(value);

            if (
                !item.lid
                || seen.has(item.lid)
            ) {
                continue;
            }

            seen.add(item.lid);
            result.push(item);
        }

        return result;
    };


    const statusPattern =
        /^(Entrante|Saliente|Perdida|Incoming|Outgoing|Missed)(\s*\(\d+\))?$/i;

    const timePattern =
        /\b([01]?\d|2[0-3]):[0-5]\d\b/;


    const rowKind = value => {
        const text =
            clean(value).toUpperCase();

        if (
            text.startsWith("SALIENTE")
            || text.startsWith("OUTGOING")
        ) {
            return "OUTBOUND";
        }

        if (
            text.startsWith("PERDIDA")
            || text.startsWith("MISSED")
        ) {
            return "MISSED";
        }

        if (
            text.startsWith("ENTRANTE")
            || text.startsWith("INCOMING")
        ) {
            return "INBOUND";
        }

        return null;
    };


    const expectedCount = value => {
        const match =
            clean(value).match(
                /\((\d+)\)/
            );

        if (!match) {
            return 1;
        }

        return Math.max(
            1,
            Number(match[1]) || 1
        );
    };


    const compatible = (
        call,
        kind
    ) => {
        if (!call) return false;

        if (
            kind === "OUTBOUND"
        ) {
            return (
                call.direction
                === "OUTBOUND"
            );
        }

        if (
            kind === "INBOUND"
        ) {
            return (
                call.direction
                === "INBOUND"
            );
        }

        if (
            kind === "MISSED"
        ) {
            if (
                call.direction
                !== "INBOUND"
            ) {
                return false;
            }

            const outcome =
                clean(
                    call.raw_outcome
                ).toUpperCase();

            const finalOutcome =
                clean(
                    call.raw_final_outcome
                ).toUpperCase();

            return (
                [
                    "MISSED",
                    "CANCELED",
                    "REJECTED",
                    "ACCEPTEDELSEWHERE",
                ].includes(outcome)
                || [
                    "MISSED",
                    "CANCELED",
                    "REJECTED",
                ].includes(finalOutcome)
            );
        }

        return false;
    };


    const allNodes =
        Array.from(
            document.querySelectorAll(
                "span, div, p"
            )
        );


    const statusNodes =
        allNodes.filter(node => {
            if (!visible(node)) {
                return false;
            }

            const text =
                clean(
                    node.innerText
                    || node.textContent
                );

            return (
                text.length <= 80
                && statusPattern.test(text)
            );
        });


    const rows = [];
    const seenRows = new WeakSet();


    for (
        const statusNode
        of statusNodes
    ) {
        const state =
            clean(
                statusNode.innerText
                || statusNode.textContent
            );

        const kind =
            rowKind(state);

        if (!kind) {
            continue;
        }

        let current = statusNode;
        let row = null;

        for (
            let depth = 0;
            current && depth < 8;
            depth += 1
        ) {
            const text =
                clean(
                    current.innerText
                    || current.textContent
                );

            if (
                visible(current)
                && text.length <= 220
                && text !== state
                && text.includes(state)
            ) {
                row = current;
                break;
            }

            current =
                current.parentElement;
        }

        if (
            !row
            || seenRows.has(row)
        ) {
            continue;
        }

        seenRows.add(row);

        rows.push({
            node: row,
            state,
            kind,
            expected_count:
                expectedCount(state),

            text:
                clean(
                    row.innerText
                    || row.textContent
                ),
        });
    }


    const output = [];
    const skipped = [];
    const outputKeys = new Set();


    for (
        const rowInfo
        of rows
    ) {
        const scopes = [];
        const contactRegistry =
            new Map();

        let domNode =
            rowInfo.node;


        for (
            let domDepth = 0;
            domNode && domDepth <= 6;
            domDepth += 1
        ) {
            const scopeRoots = [];

            const propsRoots =
                reactProps(domNode);

            if (propsRoots.length) {
                scopeRoots.push({
                    dom_depth:
                        domDepth,

                    fiber_depth:
                        -1,

                    roots:
                        propsRoots,
                });
            }


            for (
                const firstFiber
                of reactFibers(domNode)
            ) {
                let fiber =
                    firstFiber;

                for (
                    let fiberDepth = 0;
                    fiber
                    && fiberDepth <= 7;
                    fiberDepth += 1
                ) {
                    const roots = [];

                    try {
                        if (
                            fiber.memoizedProps
                        ) {
                            roots.push(
                                fiber.memoizedProps
                            );
                        }
                    }
                    catch (_) {}

                    try {
                        if (
                            fiber.pendingProps
                        ) {
                            roots.push(
                                fiber.pendingProps
                            );
                        }
                    }
                    catch (_) {}

                    if (roots.length) {
                        scopeRoots.push({
                            dom_depth:
                                domDepth,

                            fiber_depth:
                                fiberDepth,

                            roots,
                        });
                    }

                    try {
                        fiber =
                            fiber.return;
                    }
                    catch (_) {
                        fiber = null;
                    }
                }
            }


            for (
                const scope
                of scopeRoots
            ) {
                const calls =
                    dedupeCalls(
                        findObjects(
                            scope.roots,
                            isCallLog,
                            4,
                            700,
                            100
                        )
                    );


                const contacts =
                    dedupeContacts(
                        findObjects(
                            scope.roots,
                            isContact,
                            5,
                            700,
                            40
                        )
                    );


                for (
                    const contact
                    of contacts
                ) {
                    if (
                        contact.lid
                        && !contactRegistry.has(
                            contact.lid
                        )
                    ) {
                        contactRegistry.set(
                            contact.lid,
                            contact
                        );
                    }
                }


                if (calls.length) {
                    scopes.push({
                        dom_depth:
                            scope.dom_depth,

                        fiber_depth:
                            scope.fiber_depth,

                        calls,
                    });
                }
            }


            domNode =
                domNode.parentElement;
        }


        /*
         * Anchor:
         * scope más próximo con exactamente
         * una llamada compatible.
         */
        let anchor = null;

        for (
            const scope
            of scopes
        ) {
            const compatibleCalls =
                scope.calls.filter(
                    call =>
                        compatible(
                            call,
                            rowInfo.kind
                        )
                );

            if (
                compatibleCalls.length
                === 1
            ) {
                anchor =
                    compatibleCalls[0];

                break;
            }
        }


        if (!anchor) {
            skipped.push({
                row_text:
                    rowInfo.text,

                row_state:
                    rowInfo.state,

                reason:
                    "ANCHOR_NOT_FOUND",
            });

            continue;
        }


        /*
         * Grupo:
         * mismo peer LID,
         * dirección/semántica compatible,
         * contiene anchor,
         * count exacto al contador UI.
         */
        let selected = null;

        for (
            const scope
            of scopes
        ) {
            const candidates =
                scope.calls
                .filter(
                    call =>
                        call.peer_lid
                        === anchor.peer_lid
                        && compatible(
                            call,
                            rowInfo.kind
                        )
                );


            const unique = [];
            const seen = new Set();

            for (
                const call
                of candidates
            ) {
                if (
                    seen.has(
                        call.external_call_key
                    )
                ) {
                    continue;
                }

                seen.add(
                    call.external_call_key
                );

                unique.push(call);
            }


            const containsAnchor =
                unique.some(
                    call =>
                        call.external_call_key
                        === anchor.external_call_key
                );


            if (
                containsAnchor
                && unique.length
                === rowInfo.expected_count
            ) {
                selected = unique;
                break;
            }
        }


        if (!selected) {
            skipped.push({
                row_text:
                    rowInfo.text,

                row_state:
                    rowInfo.state,

                expected_count:
                    rowInfo.expected_count,

                peer_lid:
                    anchor.peer_lid,

                reason:
                    "EXACT_GROUP_NOT_FOUND",
            });

            continue;
        }


        const contact =
            contactRegistry.get(
                anchor.peer_lid
            );


        if (
            !contact
            || !contact.phone_id
        ) {
            skipped.push({
                row_text:
                    rowInfo.text,

                row_state:
                    rowInfo.state,

                peer_lid:
                    anchor.peer_lid,

                reason:
                    "PEER_CONTACT_NOT_FOUND",
            });

            continue;
        }


        selected.sort(
            (left, right) =>
                Number(
                    right.provider_timestamp
                    || 0
                )
                - Number(
                    left.provider_timestamp
                    || 0
                )
        );


        for (
            const call
            of selected
        ) {
            if (
                outputKeys.has(
                    call.external_call_key
                )
            ) {
                continue;
            }

            outputKeys.add(
                call.external_call_key
            );

            output.push({
                ...call,

                peer_phone_id:
                    contact.phone_id,

                peer_display_name:
                    contact.display_name,

                row_state:
                    rowInfo.state,

                row_text:
                    rowInfo.text,

                row_group_count:
                    rowInfo.expected_count,
            });
        }
    }


    return {
        version:
            "CALL-SYNC-4A",

        read_only:
            true,

        rows_scanned:
            rows.length,

        items:
            output,

        skipped_rows:
            skipped,
    };
})()
"""


def _optional_int(
    value,
):
    if isinstance(
        value,
        bool,
    ):
        return None

    try:
        number = int(
            value
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    if number < 0:
        return None

    return number


def _clean_text(
    value,
):
    text = str(
        value
        or ""
    ).strip()

    return text or None


def _direction_from_external_key(
    value,
):
    text = str(
        value
        or ""
    ).strip().lower()

    if text.startswith(
        "true_"
    ):
        return "OUTBOUND"

    if text.startswith(
        "false_"
    ):
        return "INBOUND"

    return None


def _normalize_result(
    raw,
):
    if not isinstance(
        raw,
        dict,
    ):
        raise RuntimeError(
            "Resultado histórico WhatsApp inválido"
        )

    normalized = []
    seen = set()

    for item in (
        raw.get("items")
        or []
    ):
        if not isinstance(
            item,
            dict,
        ):
            continue

        external_key = (
            _clean_text(
                item.get(
                    "external_call_key"
                )
            )
        )

        provider_call_id = (
            _clean_text(
                item.get(
                    "provider_call_id"
                )
            )
        )

        peer_lid = (
            _clean_text(
                item.get(
                    "peer_lid"
                )
            )
        )

        peer_phone_id = (
            _clean_text(
                item.get(
                    "peer_phone_id"
                )
            )
        )

        if not (
            external_key
            and provider_call_id
            and peer_lid
            and peer_phone_id
        ):
            continue

        if external_key in seen:
            continue

        seen.add(
            external_key
        )

        normalized.append({
            "provider_call_id":
                provider_call_id,

            "external_call_key":
                external_key,

            "peer_lid":
                peer_lid,

            "peer_phone_id":
                peer_phone_id,

            "peer_display_name":
                _clean_text(
                    item.get(
                        "peer_display_name"
                    )
                ),

            "direction":
                _direction_from_external_key(
                    external_key
                ),

            "provider_timestamp":
                _optional_int(
                    item.get(
                        "provider_timestamp"
                    )
                ),

            "call_duration_seconds":
                _optional_int(
                    item.get(
                        "call_duration_seconds"
                    )
                ),

            "raw_outcome":
                _clean_text(
                    item.get(
                        "raw_outcome"
                    )
                ),

            "raw_final_outcome":
                _clean_text(
                    item.get(
                        "raw_final_outcome"
                    )
                ),

            "row_state":
                _clean_text(
                    item.get(
                        "row_state"
                    )
                ),

            "row_text":
                _clean_text(
                    item.get(
                        "row_text"
                    )
                ),

            "row_group_count":
                _optional_int(
                    item.get(
                        "row_group_count"
                    )
                ),

            "is_video":
                (
                    item.get("is_video")
                    if isinstance(
                        item.get("is_video"),
                        bool,
                    )
                    else None
                ),
        })

    return {
        "version":
            _clean_text(
                raw.get("version")
            )
            or "CALL-SYNC-4A",

        "read_only":
            bool(
                raw.get(
                    "read_only",
                    True,
                )
            ),

        "rows_scanned":
            _optional_int(
                raw.get(
                    "rows_scanned"
                )
            )
            or 0,

        "items":
            normalized,

        "skipped_rows":
            list(
                raw.get(
                    "skipped_rows"
                )
                or []
            ),
    }


def read_whatsapp_call_history(
    browser,
):
    if not browser:
        raise RuntimeError(
            "WhatsApp Web no está iniciado"
        )

    raw = browser.evaluate(
        CALL_HISTORY_JS
    )

    return _normalize_result(
        raw
    )
