"""Servicio de aplicación del Chat Knowledge (WO-KNOW-CHAT-01).

Capa de aplicación entre la vista Flet y el dominio Knowledge existente:

    knowledge_chat_view -> KnowledgeChatService
        -> KnowledgeQueryService (retrieval / procedencia / vigencia)
        -> KnowledgeChatContextRepository (lectura mínima CRM)

Qué hace:

- adapta de forma determinista y acotada una pregunta en español a
  términos útiles para la búsqueda léxica existente: identificadores
  ``BOE-A-AAAA-NNNNN``, número de disposición (``1155/2024``), artículo
  y palabras clave. No reescribe ``KnowledgeQueryService`` ni añade
  embeddings;
- compone, deduplica (identidad canónica / bloque / versión) y limita
  los hallazgos de BOE y BOE_CONSOLIDATED;
- responde en MODO DOCUMENTAL (extractivo): extractos literales,
  enlaces EXACTOS almacenados en ``KnowledgeProvenance`` /
  ``KnowledgeItem``, vigencia estructurada y limitaciones. No existe en
  el repositorio un proveedor de IA de consulta autorizado: la síntesis
  jurídica generativa queda ``NOT_CONFIGURED`` y nunca se simula;
- separa siempre: (i) FUNDAMENTO_BOE, (ii) HECHOS_CRM autorizados,
  (iii) interpretación/inferencia (vacía en V1), (iv) evidencia
  insuficiente;
- el contexto CRM solo se lee con expediente explícitamente
  seleccionado, contexto confirmado, sesión autenticada y autorizador
  inyectado; en otro caso falla cerrado (``DENIED``) y conserva la
  respuesta BOE.

Qué NO hace: escribir en Knowledge ni en el CRM, copiar hechos del CRM
al índice, llamar a red/IA, ejecutar instrucciones contenidas en el
corpus o en el CRM (son datos no fiables), registrar PII en logs ni
devolver excepciones crudas a la UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path
import re
from typing import Mapping, Protocol, runtime_checkable
import unicodedata

from backend.knowledge.answer_orchestration import (
    KnowledgeAnswer,
    KnowledgeAnswerMode,
)
from backend.knowledge.contracts import KnowledgeAuthority
from backend.knowledge.evidence_sufficiency import (
    KnowledgeEvidenceSufficiencyService,
)
from backend.knowledge.query import (
    KnowledgeProvenance,
    KnowledgeQueryService,
    KnowledgeSearchHit,
    KnowledgeSearchMatchKind,
)
from backend.knowledge.source_registry import get_knowledge_source
from backend.knowledge.validity import (
    KnowledgeValidityStatus,
    unknown_validity,
)


CHAT_SOURCES = ("BOE_CONSOLIDATED", "BOE")

MIN_QUESTION_CHARS = 3
MAX_QUESTION_CHARS = 1000
DEFAULT_RESULT_LIMIT = 8
MAX_RESULT_LIMIT = 20
EXCERPT_MAX_CHARS = 600

MAX_IDENTIFIER_TERMS = 3
MAX_DISPOSITION_TERMS = 3
MAX_ARTICLE_TERMS = 2
MAX_KEYWORD_TERMS = 4
MAX_PHRASE_WORDS = 8

# Límite interno por búsqueda: el filtrado por fuente/precisión se
# aplica después, por eso es mayor que el límite visible.
SEARCH_SCAN_LIMIT = 200

ANSWER_LABEL_DOCUMENTARY = (
    "MODO DOCUMENTAL (extractivo): extractos literales del corpus "
    "Knowledge. No es una respuesta jurídica generada por IA."
)

LEGAL_BASIS_LABEL = "FUNDAMENTO_BOE"
CRM_FACTS_LABEL = "HECHOS_CRM"

CRM_FACTS_NOTICE = (
    "HECHOS DEL CRM: datos operativos del expediente seleccionado, en "
    "lectura. No son fundamento normativo."
)

SYNTHESIS_NOT_CONFIGURED = "NOT_CONFIGURED"

SYNTHESIS_NOTICE = (
    "Síntesis jurídica con IA: no configurada. No existe en esta "
    "versión un proveedor de IA de consulta autorizado; no se genera "
    "texto sintético (fase futura con opt-in y minimización de datos)."
)

INTERPRETATION_NOTE = (
    "Sin interpretación ni inferencia: este modo no interpreta la "
    "norma. Los extractos y su relación con el expediente deben ser "
    "valorados por un abogado (KNOW-002 / KNOW-003)."
)

HUMAN_VALIDATION_NOTICE = (
    "Una respuesta con fuentes no implica criterio validado por "
    "abogado. La validación jurídica humana es obligatoria antes de "
    "usarla en actuaciones."
)

UNTRUSTED_CONTENT_NOTICE = (
    "Los extractos del corpus y los datos del CRM se muestran como "
    "datos no fiables: nunca se ejecutan instrucciones contenidas en "
    "ellos."
)

LIMITATION_LEXICAL = (
    "Búsqueda léxica (coincidencia literal sin tildes equivalentes) "
    "sobre el corpus ingerido; sin ranking semántico."
)

LIMITATION_CONSOLIDATED = (
    "El texto consolidado del BOE tiene finalidad informativa: la "
    "publicación oficial prevalece."
)

LIMITATION_LATEST_KNOWN = (
    "Sin fecha de referencia: se usa la última versión conocida en el "
    "corpus, que no equivale necesariamente a la vigente hoy."
)

LIMITATION_BOE_DAILY = (
    "Las publicaciones del BOE diario no tienen estructura por "
    "artículos en Knowledge: solo se localizan por identificador "
    "exacto."
)

_SOURCE_LABELS = {
    "BOE": "BOE · publicación oficial (fuente primaria)",
    "BOE_CONSOLIDATED": (
        "BOE · legislación consolidada (texto informativo, no es la "
        "publicación oficial)"
    ),
}

_VALIDITY_LABELS = {
    KnowledgeValidityStatus.IN_FORCE: (
        "Vigente según banderas oficiales de BOE consolidado"
    ),
    KnowledgeValidityStatus.REPEALED: (
        "Derogada o anulada según BOE consolidado"
    ),
    KnowledgeValidityStatus.EXPLICIT_END_OF_VALIDITY: (
        "Vigencia agotada según BOE consolidado"
    ),
    KnowledgeValidityStatus.UNKNOWN: "Vigencia desconocida",
}

_MATCH_LABELS = {
    KnowledgeSearchMatchKind.IDENTIFIER: "Identificador exacto",
    KnowledgeSearchMatchKind.DOCUMENT_TITLE: "Título de la norma",
    KnowledgeSearchMatchKind.BLOCK_TITLE: "Título del bloque/artículo",
    KnowledgeSearchMatchKind.CONTENT: "Contenido literal",
}


class KnowledgeChatMode(str, Enum):
    BOE = "BOE"
    BOE_WITH_EXPEDIENT = "BOE_WITH_EXPEDIENT"


class KnowledgeChatAnswerKind(str, Enum):
    # Extractos reales recuperados (KnowledgeAnswerMode.SOURCE_BACKED).
    DOCUMENTARY = "DOCUMENTARY"
    # Sin evidencia recuperable (KnowledgeAnswerMode.INSUFFICIENT_EVIDENCE).
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    # Corpus/esquema ausente o ilegible.
    CORPUS_UNAVAILABLE = "CORPUS_UNAVAILABLE"
    # Entrada malformada; no se consulta nada.
    REJECTED = "REJECTED"


class KnowledgeChatContextStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    NOT_FOUND = "NOT_FOUND"
    UNAVAILABLE = "UNAVAILABLE"


class KnowledgeChatValidationError(ValueError):
    """Entrada del chat rechazada; el mensaje es apto para la UI."""


# ============================================================
# SESSION / AUTHORIZATION
# ============================================================


@dataclass(frozen=True, slots=True)
class KnowledgeChatSession:
    """Identidad de la sesión ERP autenticada (``authenticate_user``)."""

    user_id: int | None = None
    username: str = ""

    @property
    def authenticated(self) -> bool:
        return (
            isinstance(self.user_id, int)
            and not isinstance(self.user_id, bool)
            and self.user_id > 0
            and bool(str(self.username or "").strip())
        )

    @classmethod
    def from_current_user(cls, user) -> "KnowledgeChatSession":
        if isinstance(user, KnowledgeChatSession):
            return user

        if not isinstance(user, Mapping):
            return cls()

        user_id = user.get("id")

        if isinstance(user_id, bool) or not isinstance(user_id, int):
            user_id = None

        return cls(
            user_id=user_id,
            username=str(user.get("username") or "").strip(),
        )


@dataclass(frozen=True, slots=True)
class KnowledgeChatContextAuthorization:
    granted: bool
    basis: str = ""
    reason: str = ""


@runtime_checkable
class KnowledgeChatContextReader(Protocol):
    def is_active_user(self, user_id: int, username: str) -> bool:
        ...

    def find_expedient_id_by_number(self, numero_expediente: str):
        ...

    def get_expedient_projection(self, expediente_id: int):
        ...


@runtime_checkable
class KnowledgeChatContextAuthorizer(Protocol):
    def authorize(
        self,
        session: KnowledgeChatSession,
        expediente_id: int | None,
    ) -> KnowledgeChatContextAuthorization:
        ...


class ErpSessionParityContextAuthorizer:
    """Autorización de contexto con paridad respecto a la vista Expedientes.

    El ERP no tiene RBAC por expediente: cualquier usuario autenticado y
    activo puede abrir cualquier expediente en «Expedientes». Este
    autorizador NO concede más que eso y lo declara en ``basis``:
    exige sesión autenticada cuya identidad (id + username) coincide con
    un usuario activo en la autoridad ERP. No inventa roles ni permisos.
    """

    BASIS = "ERP_SESSION_PARITY_SIN_RBAC_POR_EXPEDIENTE"

    def __init__(self, context_reader: KnowledgeChatContextReader) -> None:
        if not isinstance(context_reader, KnowledgeChatContextReader):
            raise TypeError(
                "context_reader debe implementar KnowledgeChatContextReader"
            )

        self._reader = context_reader

    def authorize(
        self,
        session: KnowledgeChatSession,
        expediente_id: int | None,
    ) -> KnowledgeChatContextAuthorization:
        if not isinstance(session, KnowledgeChatSession) or (
            not session.authenticated
        ):
            return KnowledgeChatContextAuthorization(
                granted=False,
                reason="No hay sesión ERP autenticada demostrable.",
            )

        if not self._reader.is_active_user(
            session.user_id,
            session.username,
        ):
            return KnowledgeChatContextAuthorization(
                granted=False,
                reason=(
                    "La identidad de sesión no coincide con un usuario "
                    "activo del ERP."
                ),
            )

        return KnowledgeChatContextAuthorization(
            granted=True,
            basis=self.BASIS,
            reason=(
                "Usuario autenticado y activo; mismo alcance que la "
                "vista Expedientes (no existe control de permisos por "
                "expediente)."
            ),
        )


# ============================================================
# REQUEST / RESPONSE CONTRACTS
# ============================================================


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_question(value) -> str:
    text = _CONTROL_CHARS.sub(" ", str(value if value is not None else ""))
    return " ".join(text.split())


@dataclass(frozen=True, slots=True)
class KnowledgeChatRequest:
    question: str
    mode: KnowledgeChatMode = KnowledgeChatMode.BOE
    as_of: date | None = None
    source_key: str | None = None
    limit: int = DEFAULT_RESULT_LIMIT
    session: KnowledgeChatSession = field(
        default_factory=KnowledgeChatSession
    )
    expediente_id: int | None = None
    context_confirmed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.question, str):
            raise KnowledgeChatValidationError(
                "La pregunta debe ser texto."
            )

        question = _clean_question(self.question)

        if len(question) < MIN_QUESTION_CHARS:
            raise KnowledgeChatValidationError(
                "La pregunta es demasiado corta."
            )

        if len(question) > MAX_QUESTION_CHARS:
            raise KnowledgeChatValidationError(
                f"La pregunta supera {MAX_QUESTION_CHARS} caracteres."
            )

        if not any(char.isalnum() for char in question):
            raise KnowledgeChatValidationError(
                "La pregunta no contiene texto consultable."
            )

        object.__setattr__(self, "question", question)

        try:
            mode = KnowledgeChatMode(self.mode)
        except ValueError:
            raise KnowledgeChatValidationError(
                "Modo de consulta no reconocido."
            ) from None

        object.__setattr__(self, "mode", mode)

        if self.as_of is not None and (
            not isinstance(self.as_of, date)
            or isinstance(self.as_of, datetime)
        ):
            raise KnowledgeChatValidationError(
                "La fecha de referencia debe ser una fecha."
            )

        if self.source_key is not None:
            source_key = str(self.source_key).strip().upper()

            if source_key not in CHAT_SOURCES:
                raise KnowledgeChatValidationError(
                    "Fuente no admitida en el chat: use BOE o "
                    "BOE_CONSOLIDATED."
                )

            object.__setattr__(self, "source_key", source_key)

        if (
            not isinstance(self.limit, int)
            or isinstance(self.limit, bool)
            or not 1 <= self.limit <= MAX_RESULT_LIMIT
        ):
            raise KnowledgeChatValidationError(
                f"El límite de resultados debe estar entre 1 y "
                f"{MAX_RESULT_LIMIT}."
            )

        if not isinstance(self.session, KnowledgeChatSession):
            raise KnowledgeChatValidationError(
                "Identidad de sesión no válida."
            )

        if self.expediente_id is not None and (
            isinstance(self.expediente_id, bool)
            or not isinstance(self.expediente_id, int)
            or self.expediente_id < 1
        ):
            raise KnowledgeChatValidationError(
                "Identificador de expediente no válido."
            )

        if not isinstance(self.context_confirmed, bool):
            raise KnowledgeChatValidationError(
                "La confirmación de contexto debe ser booleana."
            )


@dataclass(frozen=True, slots=True)
class KnowledgeChatCitation:
    """Cita estructurada; todos los campos proceden de datos almacenados."""

    source_key: str
    source_label: str
    authority: str
    is_official_primary: bool

    external_id: str
    document_title: str = ""

    block_id: str = ""
    block_title: str = ""

    # URL EXACTA almacenada (bloque si existe, si no documento).
    url: str = ""
    url_kind: str = ""

    version_key: str = ""
    version_effective_from: date | None = None
    version_published_on: date | None = None
    is_current_version: bool | None = None

    validity_status: str = KnowledgeValidityStatus.UNKNOWN.value
    validity_label: str = _VALIDITY_LABELS[KnowledgeValidityStatus.UNKNOWN]
    validity_reason: str = ""
    validity_end_date: date | None = None
    repealed_by_external_id: str = ""

    # Publicación oficial (BOE diario) con la misma identidad, si está
    # ingerida. Vacío = no consta; nunca se fabrica un enlace.
    official_publication_url: str = ""
    official_publication_note: str = ""

    match_kind: str = ""
    match_label: str = ""
    excerpt: str = ""


@dataclass(frozen=True, slots=True)
class KnowledgeChatCrmContext:
    status: KnowledgeChatContextStatus = (
        KnowledgeChatContextStatus.NOT_REQUESTED
    )
    reason: str = ""
    authorization_basis: str = ""
    expediente_ref: str = ""

    # (etiqueta, valor) de la lista permitida.
    facts: tuple[tuple[str, str], ...] = ()
    events: tuple[str, ...] = ()
    events_truncated: bool = False

    label: str = CRM_FACTS_LABEL
    notice: str = CRM_FACTS_NOTICE


@dataclass(frozen=True, slots=True)
class KnowledgeChatResponse:
    kind: KnowledgeChatAnswerKind
    question: str = ""
    mode: KnowledgeChatMode = KnowledgeChatMode.BOE

    as_of: date | None = None
    temporal_basis: str = ""
    search_terms: tuple[str, ...] = ()

    answer_label: str = ANSWER_LABEL_DOCUMENTARY
    legal_basis_label: str = LEGAL_BASIS_LABEL

    # (i) Fundamento BOE: texto documental + citas.
    documentary_text: str = ""
    citations: tuple[KnowledgeChatCitation, ...] = ()
    truncated: bool = False
    evidence_level: str = ""
    evidence_note: str = ""

    # (ii) Hechos CRM autorizados.
    crm_context: KnowledgeChatCrmContext = field(
        default_factory=KnowledgeChatCrmContext
    )

    # (iii) Interpretación / inferencia: vacía en V1.
    interpretation_text: str = ""
    interpretation_note: str = INTERPRETATION_NOTE
    synthesis_status: str = SYNTHESIS_NOT_CONFIGURED
    synthesis_notice: str = SYNTHESIS_NOTICE

    # (iv) Evidencia insuficiente / ausente.
    insufficient_evidence: tuple[str, ...] = ()

    limitations: tuple[str, ...] = ()
    notices: tuple[str, ...] = (
        HUMAN_VALIDATION_NOTICE,
        UNTRUSTED_CONTENT_NOTICE,
    )

    # Mensaje fijo para REJECTED / CORPUS_UNAVAILABLE.
    message: str = ""


@dataclass(frozen=True, slots=True)
class KnowledgeChatExpedientSelection:
    status: KnowledgeChatContextStatus
    expediente_id: int | None = None
    expediente_ref: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class KnowledgeChatCorpusStatus:
    available: bool
    documents_by_source: tuple[tuple[str, int], ...] = ()
    reason: str = ""


# ============================================================
# QUERY ADAPTATION (determinista, acotada)
# ============================================================


_TERM_IDENTIFIER = "IDENTIFIER"
_TERM_DISPOSITION = "DISPOSITION"
_TERM_ARTICLE = "ARTICLE"
_TERM_PHRASE = "PHRASE"
_TERM_KEYWORD = "KEYWORD"

_TERM_PRIORITY = {
    _TERM_IDENTIFIER: 0,
    _TERM_DISPOSITION: 1,
    _TERM_ARTICLE: 2,
    _TERM_PHRASE: 3,
    _TERM_KEYWORD: 4,
}

_BOE_ID_RE = re.compile(r"\bBOE-([A-Z])-(\d{4})-(\d{1,6})\b", re.IGNORECASE)

_NUMBER_RE = re.compile(r"(?<!\d/)(?<!\d)(\d{1,5}/\d{4})(?![\d/])")

_RANK_SUFFIX_RE = re.compile(
    r"(real decreto[- ]ley|real decreto legislativo|real decreto|"
    r"ley organica|decreto[- ]ley|decreto legislativo|ley|decreto|"
    r"orden|reglamento|instruccion|resolucion)"
    r"(?:\s+[a-z]{2,5}/)?\s*(?:n[o.º°]*\s*)?$"
)

_ARTICLE_SUFFIXES = ("bis", "ter", "quater", "quinquies")

# Tolera tildes para poder aplicarse al texto original y al plegado.
_ARTICLE_RE = re.compile(
    r"\bart(?:[ií]culos?|s?\.)?\s*(\d{1,4})"
    r"(?:\s*(" + "|".join(_ARTICLE_SUFFIXES) + r"))?(?![\w/])"
)

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

_PUNCTUATION_RE = re.compile(r"[¿?¡!.,;:\"'«»()\[\]{}]")

_STOPWORDS = frozenset(
    """
    a al algo algun alguna algunas alguno algunos ante antes aquel
    aquella aquellas aquello aquellos aqui asi aun bajo bien cada
    como con contra cual cuales cualquier cuando cuanto cuantos de
    debe deben deberia decir del desde dice dicen donde dos el ella
    ellas ellos en entre era eran es esa esas ese eso esos esta estan
    estar estas este esto estos fue fueron ha han hasta hay hacer la
    las le les lo los mas me mi mis mucho muy nada ni no nos nuestra
    nuestro o os otra otras otro otros para pero poco por porque
    puede pueden puedo que quien quienes se sea segun ser si sido
    sin sobre solo son su sus tambien tanto te tiene tienen todo
    todos tras tu tus un una unas uno unos usted ustedes y ya
    articulo articulos norma normas normativa ley leyes real decreto
    organica legislativo orden boe establece regula pregunta consulta
    saber quiero necesito explica explicame informacion respecto
    relacion caso
    """.split()
)


def _fold(value) -> str:
    """casefold + sin diacríticos + espacios colapsados."""

    normalized = unicodedata.normalize("NFKD", str(value or "")).casefold()
    stripped = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    return " ".join(stripped.split())


@dataclass(frozen=True, slots=True)
class _SearchTerm:
    kind: str
    needle: str
    display: str

    # DISPOSITION: número y rango plegado opcional.
    number: str = ""
    rank: str = ""

    # ARTICLE: número y sufijo plegados ("2", "bis").
    article: str = ""


@dataclass(frozen=True, slots=True)
class _AdaptedQuery:
    identifiers: tuple[_SearchTerm, ...] = ()
    dispositions: tuple[_SearchTerm, ...] = ()
    articles: tuple[_SearchTerm, ...] = ()
    phrase: _SearchTerm | None = None
    keywords: tuple[_SearchTerm, ...] = ()

    @property
    def norm_terms(self) -> tuple[_SearchTerm, ...]:
        return self.identifiers + self.dispositions

    @property
    def text_terms(self) -> tuple[_SearchTerm, ...]:
        phrase = (self.phrase,) if self.phrase is not None else ()
        return phrase + self.keywords

    @property
    def all_terms(self) -> tuple[_SearchTerm, ...]:
        return self.norm_terms + self.articles + self.text_terms

    @property
    def displays(self) -> tuple[str, ...]:
        return tuple(term.display for term in self.all_terms)


def adapt_question(question: str) -> _AdaptedQuery:
    """Deriva términos de búsqueda deterministas a partir de la pregunta.

    Preserva identificadores ``BOE-X-AAAA-N``, número de disposición y
    artículo; el resto se reduce a una frase corta y palabras clave
    sin palabras vacías. Misma pregunta, mismos términos.
    """

    text = _clean_question(question)
    residual = text

    identifiers: list[_SearchTerm] = []

    for match in _BOE_ID_RE.finditer(text):
        identifier = match.group(0).upper()

        if identifier not in {term.needle for term in identifiers}:
            identifiers.append(
                _SearchTerm(_TERM_IDENTIFIER, identifier, identifier)
            )

        residual = residual.replace(match.group(0), " ")

    folded = _fold(residual)
    dispositions: list[_SearchTerm] = []

    for match in _NUMBER_RE.finditer(folded):
        number = match.group(1)
        rank_match = _RANK_SUFFIX_RE.search(folded[: match.start()])
        rank = rank_match.group(1) if rank_match else ""

        if number in {term.number for term in dispositions}:
            continue

        display = f"{rank} {number}".strip()
        dispositions.append(
            _SearchTerm(
                _TERM_DISPOSITION,
                number,
                display,
                number=number,
                rank=rank,
            )
        )

    articles: list[_SearchTerm] = []

    for match in _ARTICLE_RE.finditer(folded):
        number = match.group(1)
        suffix = match.group(2) or ""
        article = f"{number} {suffix}".strip()

        if article in {term.article for term in articles}:
            continue

        articles.append(
            _SearchTerm(
                _TERM_ARTICLE,
                f"artículo {article}",
                f"artículo {article}",
                article=article,
            )
        )

    # Frase literal contigua (con tildes, tal como se escribió), sin
    # palabras vacías en los extremos. Si no aparece en el corpus,
    # mandan las palabras clave.
    free_words = [
        word.casefold()
        for word in _WORD_RE.findall(
            _PUNCTUATION_RE.sub(
                " ",
                _NUMBER_RE.sub(" ", _ARTICLE_RE.sub(" ", residual.casefold())),
            )
        )
    ]

    while free_words and _fold(free_words[0]) in _STOPWORDS:
        free_words.pop(0)

    while free_words and _fold(free_words[-1]) in _STOPWORDS:
        free_words.pop()

    phrase = None

    if 2 <= len(free_words) <= MAX_PHRASE_WORDS:
        phrase_text = " ".join(free_words)
        phrase = _SearchTerm(_TERM_PHRASE, phrase_text, phrase_text)

    keywords: list[_SearchTerm] = []
    seen: set[str] = set()

    for word in _WORD_RE.findall(_PUNCTUATION_RE.sub(" ", residual)):
        key = _fold(word)

        if key in _STOPWORDS or key in seen:
            continue

        if len(key) < 4 and not (word.isupper() and len(word) >= 2):
            continue

        seen.add(key)
        keywords.append(
            _SearchTerm(_TERM_KEYWORD, word.casefold(), word.casefold())
        )

        if len(keywords) >= MAX_KEYWORD_TERMS:
            break

    if phrase is not None and len(keywords) == 1:
        phrase = None

    return _AdaptedQuery(
        identifiers=tuple(identifiers[:MAX_IDENTIFIER_TERMS]),
        dispositions=tuple(dispositions[:MAX_DISPOSITION_TERMS]),
        articles=tuple(articles[:MAX_ARTICLE_TERMS]),
        phrase=phrase,
        keywords=tuple(keywords),
    )


def _title_matches_disposition(title: str, term: _SearchTerm) -> bool:
    folded = _fold(title)
    number = re.search(
        r"(?<!\d)" + re.escape(term.number) + r"(?!\d)",
        folded,
    )

    if number is None:
        return False

    if not term.rank:
        return True

    return term.rank.replace("-", " ") in folded[: number.start()].replace(
        "-", " "
    )


def _article_pattern(term: _SearchTerm) -> re.Pattern:
    parts = term.article.split()
    # "artículo 2" no debe aceptar "artículo 20" ni "artículo 2 bis".
    no_suffix = (
        r"(?!\s*(?:" + "|".join(_ARTICLE_SUFFIXES) + r")\b)"
        if len(parts) == 1
        else ""
    )

    return re.compile(
        r"^\s*art(?:iculo|\.)?\s*"
        + r"\s*".join(re.escape(part) for part in parts)
        + r"(?![\d\w])"
        + no_suffix
    )


def _hit_matches_article(hit: KnowledgeSearchHit, term: _SearchTerm) -> bool:
    pattern = _article_pattern(term)

    if hit.match_kind is KnowledgeSearchMatchKind.BLOCK_TITLE:
        return bool(pattern.search(_fold(hit.provenance.block_title)))

    if hit.match_kind is KnowledgeSearchMatchKind.CONTENT:
        # Solo cuenta si el bloque EMPIEZA por "Artículo N": una mención
        # interna ("según el artículo 2") no es el artículo pedido.
        excerpt = str(hit.matched_text or "")
        return not excerpt.startswith("…") and bool(
            pattern.search(_fold(excerpt))
        )

    return False


# ============================================================
# SERVICE
# ============================================================


@dataclass
class _Candidate:
    hit: KnowledgeSearchHit
    priority: int
    keywords: set[str]


def _hit_key(provenance: KnowledgeProvenance) -> tuple[str, str, str, str]:
    return (
        provenance.source_key,
        provenance.external_id,
        provenance.block_id,
        provenance.version_key,
    )


def _truncate(text: str, limit: int = EXCERPT_MAX_CHARS) -> str:
    value = " ".join(str(text or "").split())

    if len(value) <= limit:
        return value

    return value[:limit].rstrip() + "…"


class KnowledgeChatService:
    """Fachada de aplicación del Chat Knowledge (solo lectura)."""

    def __init__(
        self,
        query_service: KnowledgeQueryService | None,
        *,
        item_repository=None,
        corpus_listing=None,
        context_reader: KnowledgeChatContextReader | None = None,
        context_authorizer: KnowledgeChatContextAuthorizer | None = None,
        unavailable_reason: str = "",
    ) -> None:
        if query_service is not None and not isinstance(
            query_service, KnowledgeQueryService
        ):
            raise TypeError("query_service debe ser KnowledgeQueryService")

        if context_reader is not None and not isinstance(
            context_reader, KnowledgeChatContextReader
        ):
            raise TypeError(
                "context_reader debe implementar KnowledgeChatContextReader"
            )

        if context_authorizer is not None and not isinstance(
            context_authorizer, KnowledgeChatContextAuthorizer
        ):
            raise TypeError(
                "context_authorizer debe implementar "
                "KnowledgeChatContextAuthorizer"
            )

        self._query = query_service
        self._items = item_repository
        self._listing = corpus_listing
        self._reader = context_reader
        self._authorizer = context_authorizer
        self._unavailable_reason = (
            str(unavailable_reason or "").strip()
            or "El corpus Knowledge no está configurado."
        )

    @property
    def synthesis_status(self) -> str:
        return SYNTHESIS_NOT_CONFIGURED

    @property
    def context_supported(self) -> bool:
        return self._reader is not None and self._authorizer is not None

    # ---------------- corpus ----------------

    def corpus_status(self) -> KnowledgeChatCorpusStatus:
        if self._query is None:
            return KnowledgeChatCorpusStatus(
                available=False,
                reason=self._unavailable_reason,
            )

        if self._listing is None:
            return KnowledgeChatCorpusStatus(
                available=True,
                reason="Recuento de normas no disponible.",
            )

        try:
            counts = tuple(
                (
                    source,
                    len(self._listing.list_document_identities(source)),
                )
                for source in CHAT_SOURCES
            )
        except Exception:  # noqa: BLE001 - nunca se propaga a la UI
            return KnowledgeChatCorpusStatus(
                available=False,
                reason=(
                    "El corpus Knowledge no pudo leerse (esquema no "
                    "inicializado o base no disponible)."
                ),
            )

        return KnowledgeChatCorpusStatus(
            available=True,
            documents_by_source=counts,
            reason=(
                ""
                if any(count for _source, count in counts)
                else "El corpus BOE está vacío: no hay normas ingeridas."
            ),
        )

    # ---------------- entry points ----------------

    def ask_from_input(
        self,
        *,
        question,
        mode=KnowledgeChatMode.BOE,
        as_of_text: str = "",
        source_key: str | None = None,
        limit: int = DEFAULT_RESULT_LIMIT,
        current_user=None,
        expediente_id: int | None = None,
        context_confirmed: bool = False,
    ) -> KnowledgeChatResponse:
        """Entrada para la UI: nunca lanza; la validación es REJECTED."""

        try:
            request = KnowledgeChatRequest(
                question=question,
                mode=mode,
                as_of=parse_as_of(as_of_text),
                source_key=source_key or None,
                limit=limit,
                session=KnowledgeChatSession.from_current_user(
                    current_user
                ),
                expediente_id=expediente_id,
                context_confirmed=bool(context_confirmed),
            )
        except KnowledgeChatValidationError as exc:
            return KnowledgeChatResponse(
                kind=KnowledgeChatAnswerKind.REJECTED,
                question=_clean_question(question)[:MAX_QUESTION_CHARS]
                if isinstance(question, str)
                else "",
                message=str(exc),
            )

        return self.ask(request)

    def ask(self, request: KnowledgeChatRequest) -> KnowledgeChatResponse:
        if not isinstance(request, KnowledgeChatRequest):
            raise TypeError("request debe ser KnowledgeChatRequest")

        crm_context = self._crm_context(request)

        if self._query is None:
            return self._unavailable(request, crm_context)

        try:
            return self._documentary(request, crm_context)
        except Exception:  # noqa: BLE001 - fallo de corpus, sin traza a UI
            return self._unavailable(
                request,
                crm_context,
                reason=(
                    "No se pudo consultar el corpus Knowledge (esquema "
                    "no inicializado, base no disponible o datos "
                    "inconsistentes)."
                ),
            )

    def resolve_expedient(
        self,
        current_user,
        numero_expediente: str,
    ) -> KnowledgeChatExpedientSelection:
        """Resuelve UN expediente por número exacto para el usuario activo."""

        session = KnowledgeChatSession.from_current_user(current_user)
        numero = " ".join(str(numero_expediente or "").split())

        if not self.context_supported:
            return KnowledgeChatExpedientSelection(
                status=KnowledgeChatContextStatus.DENIED,
                reason="El contexto CRM no está habilitado en este entorno.",
            )

        if not session.authenticated:
            return KnowledgeChatExpedientSelection(
                status=KnowledgeChatContextStatus.DENIED,
                reason="Se requiere una sesión ERP autenticada.",
            )

        if not numero:
            return KnowledgeChatExpedientSelection(
                status=KnowledgeChatContextStatus.NOT_FOUND,
                reason="Indique el número exacto del expediente.",
            )

        try:
            decision = self._authorizer.authorize(session, None)

            if not decision.granted:
                return KnowledgeChatExpedientSelection(
                    status=KnowledgeChatContextStatus.DENIED,
                    reason=decision.reason,
                )

            expediente_id = self._reader.find_expedient_id_by_number(numero)
        except Exception:  # noqa: BLE001
            return KnowledgeChatExpedientSelection(
                status=KnowledgeChatContextStatus.UNAVAILABLE,
                reason="No se pudo leer el CRM en modo lectura.",
            )

        if expediente_id is None:
            return KnowledgeChatExpedientSelection(
                status=KnowledgeChatContextStatus.NOT_FOUND,
                reason=(
                    "No existe un expediente activo con ese número exacto."
                ),
            )

        return KnowledgeChatExpedientSelection(
            status=KnowledgeChatContextStatus.GRANTED,
            expediente_id=int(expediente_id),
            expediente_ref=numero,
            reason=decision.reason,
        )

    # ---------------- CRM context ----------------

    def _crm_context(
        self,
        request: KnowledgeChatRequest,
    ) -> KnowledgeChatCrmContext:
        if request.mode is not KnowledgeChatMode.BOE_WITH_EXPEDIENT:
            return KnowledgeChatCrmContext()

        def denied(reason: str) -> KnowledgeChatCrmContext:
            return KnowledgeChatCrmContext(
                status=KnowledgeChatContextStatus.DENIED,
                reason=reason,
            )

        # Comprobaciones sin acceso a datos: deben fallar ANTES de
        # cualquier lectura del CRM.
        if request.expediente_id is None:
            return denied("No hay expediente seleccionado explícitamente.")

        if not request.context_confirmed:
            return denied(
                "El uso del contexto del expediente no fue confirmado."
            )

        if not request.session.authenticated:
            return denied("No hay sesión ERP autenticada demostrable.")

        if not self.context_supported:
            return denied(
                "El contexto CRM no está habilitado en este entorno."
            )

        try:
            decision = self._authorizer.authorize(
                request.session,
                request.expediente_id,
            )
        except Exception:  # noqa: BLE001
            return KnowledgeChatCrmContext(
                status=KnowledgeChatContextStatus.UNAVAILABLE,
                reason="No se pudo verificar la autorización en el CRM.",
            )

        if not isinstance(
            decision, KnowledgeChatContextAuthorization
        ) or not decision.granted:
            return denied(
                getattr(decision, "reason", "")
                or "Acceso al contexto no autorizado."
            )

        try:
            projection = self._reader.get_expedient_projection(
                request.expediente_id
            )
        except Exception:  # noqa: BLE001
            return KnowledgeChatCrmContext(
                status=KnowledgeChatContextStatus.UNAVAILABLE,
                reason="No se pudo leer el expediente en modo lectura.",
                authorization_basis=decision.basis,
            )

        if projection is None:
            return KnowledgeChatCrmContext(
                status=KnowledgeChatContextStatus.NOT_FOUND,
                reason="El expediente seleccionado no existe o no está activo.",
                authorization_basis=decision.basis,
            )

        events = tuple(
            " · ".join(
                part
                for part in (
                    event.fecha_evento,
                    event.tipo_evento,
                    (
                        f"{event.estado_anterior} → {event.estado_nuevo}"
                        if event.estado_anterior or event.estado_nuevo
                        else ""
                    ),
                )
                if part
            )
            for event in projection.events
        )

        return KnowledgeChatCrmContext(
            status=KnowledgeChatContextStatus.GRANTED,
            reason=decision.reason,
            authorization_basis=decision.basis,
            expediente_ref=projection.numero_expediente,
            facts=tuple(
                (label, value) for _key, label, value in projection.facts
            ),
            events=events,
            events_truncated=projection.events_truncated,
        )

    # ---------------- BOE retrieval ----------------

    def _sources(self, request: KnowledgeChatRequest) -> tuple[str, ...]:
        return (request.source_key,) if request.source_key else CHAT_SOURCES

    def _search(self, needle: str, request: KnowledgeChatRequest):
        result = self._query.search(
            needle,
            source_key=request.source_key,
            as_of=request.as_of,
            limit=SEARCH_SCAN_LIMIT,
        )

        allowed = self._sources(request)

        hits = tuple(
            hit
            for hit in result.hits
            if hit.provenance.source_key in allowed
        )

        return hits, result.truncated, result.temporal_basis

    def _official_record(self, source_key: str, external_id: str):
        if self._items is None:
            return None

        try:
            return self._items.get_current(source_key, external_id)
        except Exception:  # noqa: BLE001
            return None

    def _record_provenance(self, item) -> KnowledgeProvenance:
        source = get_knowledge_source(item.source_key)

        return KnowledgeProvenance(
            source_key=item.source_key,
            provider=source.provider,
            authority=source.authority.value,
            identifier_scheme="BOE_ID",
            external_id=item.external_id,
            document_canonical_key=item.canonical_key,
            representation="SOURCE_ITEM_RECORD",
            document_title=item.title,
            document_uri=item.canonical_uri,
            source_revision=item.source_revision,
            language=item.language,
        )

    def _documentary(
        self,
        request: KnowledgeChatRequest,
        crm_context: KnowledgeChatCrmContext,
    ) -> KnowledgeChatResponse:
        adapted = adapt_question(request.question)
        candidates: dict[tuple, _Candidate] = {}
        missing: list[str] = []
        truncated = False
        temporal_basis = "AS_OF" if request.as_of else "LATEST_KNOWN"

        def add(hit: KnowledgeSearchHit, term: _SearchTerm) -> None:
            key = _hit_key(hit.provenance)
            priority = _TERM_PRIORITY[term.kind]
            candidate = candidates.get(key)

            if candidate is None:
                candidate = _Candidate(hit=hit, priority=priority, keywords=set())
                candidates[key] = candidate
            elif (priority, hit.rank) < (
                candidate.priority,
                candidate.hit.rank,
            ):
                candidate.hit = hit
                candidate.priority = priority

            if term.kind in (_TERM_PHRASE, _TERM_KEYWORD):
                candidate.keywords.add(term.needle)

        # 1) Normas pedidas explícitamente: definen el alcance.
        scope: set[tuple[str, str]] = set()

        for term in adapted.identifiers:
            hits, more, _basis = self._search(term.needle, request)
            truncated = truncated or more
            found = [
                hit
                for hit in hits
                if hit.match_kind is KnowledgeSearchMatchKind.IDENTIFIER
            ]

            if not found and "BOE" in self._sources(request):
                item = self._official_record("BOE", term.needle)

                if item is not None:
                    found = [
                        KnowledgeSearchHit(
                            KnowledgeSearchMatchKind.IDENTIFIER,
                            self._record_provenance(item),
                            matched_text=item.external_id,
                        )
                    ]

            if not found:
                missing.append(
                    f"La norma {term.display} no consta en el corpus "
                    "Knowledge ingerido."
                )

            for hit in found:
                scope.add(
                    (hit.provenance.source_key, hit.provenance.external_id)
                )
                add(hit, term)

        for term in adapted.dispositions:
            hits, more, _basis = self._search(term.number, request)
            truncated = truncated or more
            found = [
                hit
                for hit in hits
                if hit.match_kind
                in (
                    KnowledgeSearchMatchKind.IDENTIFIER,
                    KnowledgeSearchMatchKind.DOCUMENT_TITLE,
                )
                and _title_matches_disposition(
                    hit.provenance.document_title,
                    term,
                )
            ]

            if not found:
                missing.append(
                    f"La disposición «{term.display}» no consta en el "
                    "corpus Knowledge ingerido."
                )

            for hit in found:
                scope.add(
                    (hit.provenance.source_key, hit.provenance.external_id)
                )
                add(hit, term)

        norm_requested = bool(adapted.norm_terms)

        def in_scope(hit: KnowledgeSearchHit) -> bool:
            if not norm_requested:
                return True

            return (
                hit.provenance.source_key,
                hit.provenance.external_id,
            ) in scope

        # 2) Artículos (dentro del alcance si se pidió una norma).
        for term in adapted.articles:
            matched = []

            for needle in (f"artículo {term.article}", f"articulo {term.article}"):
                hits, more, _basis = self._search(needle, request)
                truncated = truncated or more
                matched.extend(
                    hit
                    for hit in hits
                    if in_scope(hit) and _hit_matches_article(hit, term)
                )

            if not matched:
                missing.append(
                    f"No se localizó el {term.display}"
                    + (
                        " en la norma indicada"
                        if norm_requested
                        else ""
                    )
                    + " dentro del corpus."
                )

            for hit in matched:
                add(hit, term)

        # 3) Frase y palabras clave (solo si no hay ya un artículo
        #    concreto resuelto: evita ruido sobre una consulta precisa).
        article_resolved = any(
            candidate.priority == _TERM_PRIORITY[_TERM_ARTICLE]
            for candidate in candidates.values()
        )

        if not article_resolved and not (norm_requested and not scope):
            for term in adapted.text_terms:
                hits, more, _basis = self._search(term.needle, request)
                truncated = truncated or more

                for hit in hits:
                    if in_scope(hit):
                        add(hit, term)

        if not adapted.all_terms:
            missing.append(
                "La pregunta no contiene términos útiles para buscar "
                "(identificador, disposición, artículo o palabras clave)."
            )

        ordered = sorted(
            candidates.values(),
            key=lambda candidate: (
                candidate.priority,
                -len(candidate.keywords),
                candidate.hit.rank,
                candidate.hit.provenance.source_key,
                candidate.hit.provenance.external_id,
                candidate.hit.provenance.block_id,
            ),
        )

        if len(ordered) > request.limit:
            truncated = True

        selected = ordered[: request.limit]

        if not selected:
            if not missing:
                missing.append(
                    "Sin coincidencias en el corpus BOE para: "
                    + ", ".join(adapted.displays)
                    + "."
                )

            answer = KnowledgeAnswer(
                mode=KnowledgeAnswerMode.INSUFFICIENT_EVIDENCE,
                query=request.question,
                source_key=request.source_key,
                as_of=request.as_of,
                missing_evidence=tuple(missing),
                reason=(
                    "No existe evidencia recuperable en Knowledge para "
                    "esta consulta; no se fabrica una respuesta."
                ),
            )

            return KnowledgeChatResponse(
                kind=KnowledgeChatAnswerKind.INSUFFICIENT_EVIDENCE,
                question=request.question,
                mode=request.mode,
                as_of=request.as_of,
                temporal_basis=temporal_basis,
                search_terms=adapted.displays,
                crm_context=crm_context,
                insufficient_evidence=answer.missing_evidence,
                limitations=self._limitations(request, ()),
                message=answer.reason,
            )

        citations = tuple(
            self._citation(candidate, request) for candidate in selected
        )

        answer = KnowledgeAnswer(
            mode=KnowledgeAnswerMode.SOURCE_BACKED,
            query=request.question,
            source_key=request.source_key,
            as_of=request.as_of,
            content_text="\n\n".join(
                citation.excerpt
                or citation.document_title
                or citation.external_id
                for citation in citations
            ),
            citations=tuple(candidate.hit.provenance for candidate in selected),
            temporal_basis=temporal_basis,
            reason="Extractos recuperados del corpus Knowledge.",
        )

        evidence_level, evidence_note = self._evidence_level(answer)

        return KnowledgeChatResponse(
            kind=KnowledgeChatAnswerKind.DOCUMENTARY,
            question=request.question,
            mode=request.mode,
            as_of=request.as_of,
            temporal_basis=temporal_basis,
            search_terms=adapted.displays,
            documentary_text=self._documentary_text(
                citations,
                adapted,
                request,
                temporal_basis,
            ),
            citations=citations,
            truncated=truncated,
            evidence_level=evidence_level,
            evidence_note=evidence_note,
            crm_context=crm_context,
            insufficient_evidence=tuple(missing),
            limitations=self._limitations(request, citations),
        )

    def _evidence_level(self, answer: KnowledgeAnswer) -> tuple[str, str]:
        try:
            report = KnowledgeEvidenceSufficiencyService(
                query_service=self._query
            ).evaluate(answer)
        except Exception:  # noqa: BLE001
            return "", "Nivel evidencial no calculable."

        return (
            report.level.value,
            f"Categoría por conteo de normas distintas citadas "
            f"({report.source_count}); no es un grado de confianza. "
            + (
                "Evidencia cruda de recuperación, no revisada por "
                "abogado."
                if report.is_raw_evidence
                else ""
            ),
        )

    def _citation(
        self,
        candidate: _Candidate,
        request: KnowledgeChatRequest,
    ) -> KnowledgeChatCitation:
        hit = candidate.hit
        provenance = hit.provenance
        source = get_knowledge_source(provenance.source_key)

        excerpt = ""

        if provenance.block_id and (
            hit.match_kind is KnowledgeSearchMatchKind.BLOCK_TITLE
            or candidate.priority == _TERM_PRIORITY[_TERM_ARTICLE]
        ):
            excerpt = self._version_text(provenance)

        if not excerpt and hit.match_kind is KnowledgeSearchMatchKind.CONTENT:
            excerpt = _truncate(hit.matched_text)

        validity = self._validity(provenance)

        official_url = ""
        official_note = ""

        if provenance.source_key == "BOE_CONSOLIDATED":
            record = self._official_record("BOE", provenance.external_id)

            if record is not None and record.canonical_uri:
                official_url = record.canonical_uri
                official_note = (
                    "Publicación oficial BOE ingerida con la misma "
                    "identidad."
                )
            else:
                official_note = (
                    "La publicación oficial de esta norma no está "
                    f"ingerida en Knowledge (identificador "
                    f"{provenance.external_id}); consulte el BOE oficial."
                )

        url = provenance.block_uri or provenance.document_uri
        url_kind = (
            "BLOCK"
            if provenance.block_uri
            else ("DOCUMENT" if provenance.document_uri else "")
        )

        return KnowledgeChatCitation(
            source_key=provenance.source_key,
            source_label=_SOURCE_LABELS.get(
                provenance.source_key,
                source.display_name,
            ),
            authority=provenance.authority,
            is_official_primary=(
                source.authority is KnowledgeAuthority.OFFICIAL_PRIMARY
            ),
            external_id=provenance.external_id,
            document_title=provenance.document_title,
            block_id=provenance.block_id,
            block_title=provenance.block_title,
            url=url,
            url_kind=url_kind,
            version_key=provenance.version_key,
            version_effective_from=provenance.effective_from,
            version_published_on=provenance.published_on,
            is_current_version=provenance.is_current,
            validity_status=validity.status.value,
            validity_label=_VALIDITY_LABELS[validity.status],
            validity_reason=validity.reason,
            validity_end_date=validity.end_date,
            repealed_by_external_id=validity.repealed_by_external_id,
            official_publication_url=official_url,
            official_publication_note=official_note,
            match_kind=hit.match_kind.value,
            match_label=_MATCH_LABELS[hit.match_kind],
            excerpt=excerpt,
        )

    def _version_text(self, provenance: KnowledgeProvenance) -> str:
        """Texto literal de la MISMA versión citada (nunca otra)."""

        try:
            history = self._query.get_block_history(
                provenance.source_key,
                provenance.external_id,
                provenance.block_id,
            )
        except Exception:  # noqa: BLE001
            return ""

        for entry in history.versions:
            if entry.provenance.version_key == provenance.version_key:
                return _truncate(entry.content_text)

        return ""

    def _validity(self, provenance: KnowledgeProvenance):
        try:
            return self._query.get_document_validity(
                provenance.source_key,
                provenance.external_id,
            )
        except Exception:  # noqa: BLE001
            return unknown_validity(
                source_key=provenance.source_key,
                external_id=provenance.external_id,
                reason="La vigencia no pudo resolverse.",
            )

    @staticmethod
    def _documentary_text(
        citations: tuple[KnowledgeChatCitation, ...],
        adapted: _AdaptedQuery,
        request: KnowledgeChatRequest,
        temporal_basis: str,
    ) -> str:
        documents = {
            (citation.source_key, citation.external_id)
            for citation in citations
        }

        lines = [
            ANSWER_LABEL_DOCUMENTARY,
            (
                f"Hallazgos: {len(citations)} fragmento(s) en "
                f"{len(documents)} norma(s) del corpus BOE para la "
                f"búsqueda adaptada: {', '.join(adapted.displays)}."
            ),
            (
                f"Fecha de referencia: {request.as_of.isoformat()} "
                "(versiones aplicables en esa fecha)."
                if temporal_basis == "AS_OF"
                else "Fecha de referencia: no indicada (última versión "
                "conocida en el corpus)."
            ),
        ]

        for index, citation in enumerate(citations, start=1):
            location = citation.block_title or citation.block_id or "Norma"
            lines.append(
                f"[{index}] {citation.document_title or citation.external_id}"
                f" ({citation.external_id}) · {location} · "
                f"{citation.source_label}"
            )

            if citation.excerpt:
                lines.append(f"    «{citation.excerpt}»")

        return "\n".join(lines)

    @staticmethod
    def _limitations(
        request: KnowledgeChatRequest,
        citations: tuple[KnowledgeChatCitation, ...],
    ) -> tuple[str, ...]:
        limitations = [LIMITATION_LEXICAL, LIMITATION_BOE_DAILY]

        if request.as_of is None:
            limitations.append(LIMITATION_LATEST_KNOWN)

        if any(
            citation.source_key == "BOE_CONSOLIDATED"
            for citation in citations
        ) or not citations:
            limitations.append(LIMITATION_CONSOLIDATED)

        return tuple(limitations)

    def _unavailable(
        self,
        request: KnowledgeChatRequest,
        crm_context: KnowledgeChatCrmContext,
        *,
        reason: str = "",
    ) -> KnowledgeChatResponse:
        message = reason or self._unavailable_reason

        return KnowledgeChatResponse(
            kind=KnowledgeChatAnswerKind.CORPUS_UNAVAILABLE,
            question=request.question,
            mode=request.mode,
            as_of=request.as_of,
            crm_context=crm_context,
            insufficient_evidence=(
                "Corpus Knowledge no disponible: no hay evidencia "
                "consultable.",
            ),
            limitations=(LIMITATION_CONSOLIDATED,),
            message=message,
        )


# ============================================================
# INPUT HELPERS / COMPOSITION
# ============================================================


def parse_as_of(value) -> date | None:
    """``AAAA-MM-DD`` o ``DD/MM/AAAA``; vacío = sin fecha."""

    if value is None:
        return None

    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    text = str(value).strip()

    if not text:
        return None

    for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue

    raise KnowledgeChatValidationError(
        "Fecha de referencia no válida: use AAAA-MM-DD o DD/MM/AAAA."
    )


def build_knowledge_chat_service(
    db_path=None,
    *,
    context_db_path=None,
) -> KnowledgeChatService:
    """Composición por defecto sobre los adaptadores SQLite existentes.

    No ejecuta migraciones ni ``initialize_schema``: si la base no
    existe, el servicio responde CORPUS_UNAVAILABLE. Construirlo no
    abre conexiones.
    """

    from backend.knowledge.boe_consolidated.validity import (
        resolve_boe_consolidated_validity,
    )
    from backend.knowledge.sqlite_repository import SQLiteKnowledgeRepository
    from backend.knowledge.sqlite_structure_repository import (
        DEFAULT_DB_PATH,
        SQLiteKnowledgeStructureRepository,
    )
    from backend.repositories.knowledge_chat_context_repository import (
        KnowledgeChatContextRepository,
    )

    knowledge_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH

    context_reader = KnowledgeChatContextRepository(
        context_db_path if context_db_path is not None else db_path
    )
    authorizer = ErpSessionParityContextAuthorizer(context_reader)

    if not knowledge_path.is_file():
        return KnowledgeChatService(
            None,
            context_reader=context_reader,
            context_authorizer=authorizer,
            unavailable_reason=(
                "No existe la base del corpus Knowledge en este entorno."
            ),
        )

    structures = SQLiteKnowledgeStructureRepository(knowledge_path)
    items = SQLiteKnowledgeRepository(knowledge_path)

    return KnowledgeChatService(
        KnowledgeQueryService(
            structures,
            items,
            validity_resolvers={
                "BOE_CONSOLIDATED": resolve_boe_consolidated_validity,
            },
        ),
        item_repository=items,
        corpus_listing=structures,
        context_reader=context_reader,
        context_authorizer=authorizer,
    )
