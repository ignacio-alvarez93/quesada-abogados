"""WO-KNOW-CHAT-01: contrato de la vista «Chat Knowledge».

La vista se carga por ruta con un stub aislado de Flet en ``sys.modules``
(no se muestra nada ni se necesita Flet instalado); ``app/main.py`` y
``frontend/layouts/sidebar.py`` se verifican por AST y, para
``navigate``, compilando solo esa función con dependencias simuladas.
"""

from __future__ import annotations

import ast
from datetime import date
import importlib.util
from pathlib import Path
import sys
import types
from unittest import mock

import pytest

from backend.services.knowledge_chat_service import (
    KnowledgeChatAnswerKind,
    KnowledgeChatCitation,
    KnowledgeChatContextStatus,
    KnowledgeChatCrmContext,
    KnowledgeChatCorpusStatus,
    KnowledgeChatExpedientSelection,
    KnowledgeChatMode,
    KnowledgeChatResponse,
)


REPO = Path(__file__).resolve().parents[2]
VIEW_PATH = REPO / "frontend" / "views" / "knowledge_chat_view.py"
MAIN_PATH = REPO / "app" / "main.py"
SIDEBAR_PATH = REPO / "frontend" / "layouts" / "sidebar.py"
COMPONENT_MODULES = (
    "frontend.components",
    "frontend.components.app_alert",
    "frontend.components.app_button",
    "frontend.components.app_empty_state",
)

FORBIDDEN_ACTIONS = (
    "Guardar criterio",
    "Enviar a cliente",
    "Presentar en Mercurio",
    "Crear escrito",
)

USER = {"id": 7, "username": "operador.ficticio"}


def load_view(name="know_chat01_view"):
    spec = importlib.util.spec_from_file_location(name, VIEW_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------
# Stub aislado de Flet
# ------------------------------------------------------------


class Node:
    def __init__(self, kind, args=(), kwargs=None):
        self.kind = kind
        self.args = args
        self.__dict__.update(kwargs or {})

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return Node(f"{self.kind}.{name}")

    def __call__(self, *args, **kwargs):
        return Node(self.kind, args, kwargs)


def flet_stub():
    module = types.ModuleType("flet")
    module.__getattr__ = lambda name: Node(f"flet.{name}")
    return module


def walk(node):
    yield node

    if not isinstance(node, Node):
        return

    children = list(node.args)
    children.append(node.__dict__.get("content"))
    children.extend(node.__dict__.get("controls") or [])

    for child in children:
        if isinstance(child, Node):
            yield from walk(child)


def texts(root):
    out = []

    for node in walk(root):
        if node.kind == "flet.Text":
            # La vista actualiza ``.value`` tras construir el control.
            value = node.__dict__.get(
                "value",
                node.args[0] if node.args else None,
            )
            out.append(str(value))

    return out


def find(root, kind, **attrs):
    return [
        node
        for node in walk(root)
        if node.kind == kind
        and all(node.__dict__.get(k) == v for k, v in attrs.items())
    ]


@pytest.fixture
def stubbed_flet():
    with mock.patch.dict(sys.modules, {"flet": flet_stub()}):
        for name in COMPONENT_MODULES:
            sys.modules.pop(name, None)
        yield
        for name in COMPONENT_MODULES:
            sys.modules.pop(name, None)


class FakePage:
    def __init__(self):
        self.updates = 0
        self.threads = 0
        self.tasks = []

    def update(self):
        self.updates += 1

    def run_thread(self, work, *args):
        self.threads += 1
        work(*args)

    def run_task(self, handler, *args):
        self.tasks.append((handler, args))

    async def launch_url(self, url):
        return url


def _response(*, crm=None, kind=KnowledgeChatAnswerKind.DOCUMENTARY):
    return KnowledgeChatResponse(
        kind=kind,
        question="¿Qué dice el artículo 2?",
        mode=KnowledgeChatMode.BOE,
        as_of=date(2010, 1, 1),
        temporal_basis="AS_OF",
        search_terms=("artículo 2",),
        documentary_text="MODO DOCUMENTAL…",
        citations=(
            KnowledgeChatCitation(
                source_key="BOE_CONSOLIDATED",
                source_label="BOE · legislación consolidada (texto informativo)",
                authority="OFFICIAL_SECONDARY",
                is_official_primary=False,
                external_id="BOE-A-2099-90001",
                document_title="Real Decreto ficticio",
                block_id="a2",
                block_title="Artículo 2",
                url="https://example.test/a2",
                url_kind="BLOCK",
                version_effective_from=date(2000, 1, 1),
                excerpt="Artículo 2. Plazo ficticio de tres meses.",
                match_label="Título del bloque/artículo",
            ),
        )
        if kind is KnowledgeChatAnswerKind.DOCUMENTARY
        else (),
        crm_context=crm or KnowledgeChatCrmContext(),
        insufficient_evidence=(
            ("Falta evidencia ficticia.",)
            if kind is KnowledgeChatAnswerKind.INSUFFICIENT_EVIDENCE
            else ()
        ),
        message="Consulta rechazada ficticia."
        if kind is KnowledgeChatAnswerKind.REJECTED
        else "",
    )


class FakeService:
    context_supported = True

    def __init__(self, response=None):
        self.asks = []
        self.resolves = []
        self.response = response or _response()

    def ask_from_input(self, **kwargs):
        self.asks.append(kwargs)
        return self.response

    def resolve_expedient(self, current_user, numero):
        self.resolves.append((current_user, numero))
        return KnowledgeChatExpedientSelection(
            status=KnowledgeChatContextStatus.GRANTED,
            expediente_id=11,
            expediente_ref=numero,
        )

    def corpus_status(self):
        return KnowledgeChatCorpusStatus(
            available=True,
            documents_by_source=(("BOE_CONSOLIDATED", 2), ("BOE", 0)),
        )


def _render(service, current_user=USER, **kwargs):
    view = load_view()
    page = FakePage()
    root = view.knowledge_chat_view(
        page,
        service=service,
        current_user=current_user,
        **kwargs,
    )
    return view, page, root


def _question_field(root):
    return find(root, "flet.TextField", label="Pregunta (español)")[0]


def _checkbox(root, prefix):
    return next(
        node
        for node in find(root, "flet.Checkbox")
        if str(node.__dict__.get("label", "")).startswith(prefix)
    )


def _send(root, question="¿Qué dice el artículo 2?"):
    field = _question_field(root)
    field.value = question
    field.on_submit(None)


# ------------------------------------------------------------
# Estático: sin SQL/HTTP en la vista
# ------------------------------------------------------------


def test_view_has_no_sql_http_or_backend_imports():
    tree = ast.parse(VIEW_PATH.read_text(encoding="utf-8"))
    modules = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    for banned in (
        "sqlite3", "database", "backend", "urllib", "http", "requests",
        "socket", "subprocess", "threading",
    ):
        assert banned not in modules, banned

    top_level = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "flet" not in top_level

    source = VIEW_PATH.read_text(encoding="utf-8").upper()
    for sql in ("SELECT ", "INSERT ", "UPDATE ", "DELETE FROM", "PRAGMA"):
        assert sql not in source, sql


def test_view_module_imports_without_flet_and_builds_models():
    with mock.patch.dict(sys.modules, {"flet": None}):
        view = load_view("know_chat01_view_without_flet")

    model = view.build_turn_model(_response())

    assert model["fundamento"]["label"] == "FUNDAMENTO BOE"
    assert model["crm"]["label"] == "HECHOS DEL CRM"
    assert model["interpretation"]["label"] == "INTERPRETACIÓN / INFERENCIA"
    assert model["fundamento"]["citations"][0]["url"] == "https://example.test/a2"
    assert model["fundamento"]["citations"][0]["official"] is False
    assert model["temporal"] == "Fecha de referencia 2010-01-01"


def test_turn_model_keeps_crm_facts_out_of_legal_basis():
    view = load_view()
    crm = KnowledgeChatCrmContext(
        status=KnowledgeChatContextStatus.GRANTED,
        expediente_ref="EXP-FICT-0001",
        facts=(("Tipo de expediente", "ARRAIGO FICTICIO"),),
    )

    model = view.build_turn_model(_response(crm=crm))

    assert model["crm"]["facts"] == [("Tipo de expediente", "ARRAIGO FICTICIO")]
    assert "ARRAIGO FICTICIO" not in repr(model["fundamento"])


# ------------------------------------------------------------
# Render y flujo de consulta
# ------------------------------------------------------------


def test_view_renders_title_corpus_status_and_no_forbidden_actions(stubbed_flet):
    _view, page, root = _render(FakeService())
    rendered = " ".join(texts(root))

    assert "Chat Knowledge" in rendered
    assert "BOE_CONSOLIDATED: 2 norma(s)" in rendered
    assert page.threads >= 1

    for label in FORBIDDEN_ACTIONS:
        assert label not in rendered


def test_send_runs_in_background_and_renders_separated_sections(stubbed_flet):
    service = FakeService()
    _view, page, root = _render(service)
    threads_before = page.threads

    _send(root)

    assert page.threads == threads_before + 1
    assert service.asks == [
        {
            "question": "¿Qué dice el artículo 2?",
            "mode": "BOE",
            "as_of_text": "",
            "current_user": USER,
            "expediente_id": None,
            "context_confirmed": False,
        }
    ]

    rendered = " ".join(texts(root))
    for section in (
        "FUNDAMENTO BOE",
        "HECHOS DEL CRM",
        "INTERPRETACIÓN / INFERENCIA",
    ):
        assert section in rendered

    assert "Artículo 2. Plazo ficticio de tres meses." in rendered
    assert _question_field(root).value == ""


def test_insufficient_evidence_section_is_visible(stubbed_flet):
    service = FakeService(
        _response(kind=KnowledgeChatAnswerKind.INSUFFICIENT_EVIDENCE)
    )
    _view, _page, root = _render(service)

    _send(root)
    rendered = " ".join(texts(root))

    assert "EVIDENCIA INSUFICIENTE / AUSENTE" in rendered
    assert "Falta evidencia ficticia." in rendered


def test_rejected_input_keeps_question_for_correction(stubbed_flet):
    service = FakeService(_response(kind=KnowledgeChatAnswerKind.REJECTED))
    _view, _page, root = _render(service)

    _send(root, "¿?")

    assert _question_field(root).value == "¿?"


def test_context_mode_without_selection_never_sends_expedient(stubbed_flet):
    service = FakeService()
    _view, _page, root = _render(service)

    mode = _checkbox(root, "Usar contexto")
    mode.value = True
    mode.on_change(None)
    _checkbox(root, "Confirmo").value = True

    _send(root)

    assert service.asks[-1]["mode"] == "BOE_WITH_EXPEDIENT"
    assert service.asks[-1]["expediente_id"] is None
    assert service.asks[-1]["context_confirmed"] is False


def test_context_requires_explicit_confirmation(stubbed_flet):
    service = FakeService()
    _view, _page, root = _render(service, initial_expediente_id=11)

    _send(root)
    assert service.asks[-1]["mode"] == "BOE_WITH_EXPEDIENT"
    assert service.asks[-1]["expediente_id"] == 11
    assert service.asks[-1]["context_confirmed"] is False

    _checkbox(root, "Confirmo").value = True
    _send(root)
    assert service.asks[-1]["context_confirmed"] is True


def test_expedient_selection_uses_exact_number_via_service(stubbed_flet):
    service = FakeService()
    _view, _page, root = _render(service)

    field = find(root, "flet.TextField", label="Número exacto de expediente")[0]
    field.value = "EXP-FICT-0001"
    select = next(
        node
        for node in walk(root)
        if node.kind == "flet.OutlinedButton"
        and "Seleccionar" in texts(node.__dict__.get("content"))
    )
    select.on_click(None)

    assert service.resolves == [(USER, "EXP-FICT-0001")]
    assert "Expediente seleccionado: EXP-FICT-0001" in " ".join(texts(root))


def test_new_conversation_clears_in_memory_history(stubbed_flet):
    service = FakeService()
    _view, _page, root = _render(service)
    _send(root)

    new = next(
        node
        for node in walk(root)
        if node.kind == "flet.OutlinedButton"
        and "Nueva consulta" in texts(node.__dict__.get("content"))
    )
    new.on_click(None)

    assert "FUNDAMENTO BOE" not in " ".join(texts(root))


def test_unauthenticated_context_mode_shows_denial_warning(stubbed_flet):
    _view, _page, root = _render(FakeService(), current_user=None)

    mode = _checkbox(root, "Usar contexto")
    mode.value = True
    mode.on_change(None)

    assert any("DENEGADO" in text for text in texts(root))


def test_service_failure_never_raises_into_flet(stubbed_flet):
    class Exploding(FakeService):
        def ask_from_input(self, **kwargs):
            raise RuntimeError("C:/ruta/privada.db no such table")

        def corpus_status(self):
            raise RuntimeError("C:/ruta/privada.db")

    _view, _page, root = _render(Exploding())
    _send(root)
    rendered = " ".join(texts(root))

    assert "Corpus Knowledge no disponible" in rendered
    assert "privada.db" not in rendered


def test_history_is_bounded_in_memory(stubbed_flet):
    service = FakeService()
    view, _page, root = _render(service)

    for _ in range(view.MAX_HISTORY + 3):
        _send(root)

    rendered = texts(root)
    assert sum(1 for t in rendered if t == "FUNDAMENTO BOE") == view.MAX_HISTORY


# ------------------------------------------------------------
# Sidebar y enrutamiento
# ------------------------------------------------------------


def _assigned_literals(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        target.id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }


def test_sidebar_adds_chat_knowledge_without_removing_or_reordering():
    values = _assigned_literals(SIDEBAR_PATH)
    groups = ast.literal_eval(values["MENU_GROUPS"])
    active = ast.literal_eval(values["KNOWN_ACTIVE_VIEWS"])

    assert [group["title"] for group in groups] == [
        "Contactos", "Expedientes", "Económico", "Contabilidad", "Fiscal",
        "Nóminas", "Documentos / Box", "Reporting", "Marketing",
        "Comunicaciones", "Conocimiento", "Automatización", "Sistema",
    ]

    knowledge = next(g for g in groups if g["title"] == "Conocimiento")
    assert [label for label, _icon in knowledge["items"]] == [
        "Chat Knowledge", "BOE", "Resoluciones", "Requerimientos",
        "Jurisprudencia", "Base interna",
    ]
    assert sum(
        1 for g in groups for label, _ in g["items"] if label == "Chat Knowledge"
    ) == 1
    assert "Chat Knowledge" in active
    assert "BOE" not in active and "Base interna" not in active


def test_main_routes_chat_knowledge_and_keeps_sandbox_and_login():
    source = MAIN_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    imports = {
        (node.module, alias.name)
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert ("frontend.views.knowledge_chat_view", "knowledge_chat_view") in imports
    assert (
        "backend.services.knowledge_chat_service",
        "build_knowledge_chat_service",
    ) in imports

    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "knowledge_chat_view"
    ]
    assert len(calls) == 1
    assert {k.arg for k in calls[0].keywords} == {
        "service", "current_user", "initial_expediente_id",
    }

    values = _assigned_literals(MAIN_PATH)
    assert ast.literal_eval(values["SANDBOX_VIEWS"]) == ("IT / Tendencias",)
    assert 'navigate("Clientes")' in source


def _compile_navigate(**namespace):
    tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
    node = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "navigate"
    )
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), "<navigate>", "exec"),
        namespace,
    )
    return namespace["navigate"]


def _navigate_namespace(sandbox=False):
    return dict(
        SANDBOX_MODE=sandbox,
        SANDBOX_VIEWS=("IT / Tendencias",),
        active_view={"value": None},
        main_container=types.SimpleNamespace(content=None),
        page=mock.Mock(),
        ft=mock.Mock(),
        main_layout=mock.Mock(side_effect=lambda **k: k["content"]),
        sidebar_menu=mock.Mock(),
        whatsapp_runtime=mock.Mock(),
        current_user={"value": USER},
        knowledge_chat_view=mock.Mock(return_value="CHAT"),
        build_knowledge_chat_service=mock.Mock(return_value="SERVICE"),
    )


def test_navigate_invokes_chat_view_with_session_identity():
    namespace = _navigate_namespace()
    navigate = _compile_navigate(**namespace)

    navigate("Chat Knowledge", context_expediente_id=11)

    namespace["knowledge_chat_view"].assert_called_once_with(
        namespace["page"],
        service="SERVICE",
        current_user=USER,
        initial_expediente_id=11,
    )
    assert namespace["main_container"].content == "CHAT"


def test_sandbox_still_blocks_chat_knowledge():
    namespace = _navigate_namespace(sandbox=True)
    navigate = _compile_navigate(**namespace)

    navigate("Chat Knowledge")

    namespace["knowledge_chat_view"].assert_not_called()
    namespace["build_knowledge_chat_service"].assert_not_called()
