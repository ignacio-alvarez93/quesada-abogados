from enum import StrEnum


class MercurioGeneralState(StrEnum):
    SEDE_HOME = "SEDE_HOME"
    SEDE_EXTRANJERIA = "SEDE_EXTRANJERIA"
    SEDE_MERCURIO = "SEDE_MERCURIO"

    MERCURIO_INICIO = "MERCURIO_INICIO"
    MERCURIO_MODO_ACCESO = "MERCURIO_MODO_ACCESO"

    MERCURIO_ENTRY_IDLE = "MERCURIO_ENTRY_IDLE"
    MERCURIO_ENTRY_OPTIONS = "MERCURIO_ENTRY_OPTIONS"
    MERCURIO_ENTRY_SELECTION_COMMITTED = (
        "MERCURIO_ENTRY_SELECTION_COMMITTED"
    )

    MERCURIO_MODEL_SELECTION = (
        "MERCURIO_MODEL_SELECTION"
    )


GENERAL_TRANSITIONS = {
    MercurioGeneralState.SEDE_HOME:
        MercurioGeneralState.SEDE_EXTRANJERIA,

    MercurioGeneralState.SEDE_EXTRANJERIA:
        MercurioGeneralState.SEDE_MERCURIO,

    MercurioGeneralState.SEDE_MERCURIO:
        MercurioGeneralState.MERCURIO_INICIO,

    MercurioGeneralState.MERCURIO_INICIO:
        MercurioGeneralState.MERCURIO_MODO_ACCESO,

    MercurioGeneralState.MERCURIO_MODO_ACCESO:
        MercurioGeneralState.MERCURIO_ENTRY_IDLE,

    MercurioGeneralState.MERCURIO_ENTRY_IDLE:
        MercurioGeneralState.MERCURIO_ENTRY_OPTIONS,

    MercurioGeneralState.MERCURIO_ENTRY_OPTIONS:
        MercurioGeneralState.MERCURIO_ENTRY_SELECTION_COMMITTED,

    MercurioGeneralState.MERCURIO_ENTRY_SELECTION_COMMITTED:
        MercurioGeneralState.MERCURIO_MODEL_SELECTION,
}
