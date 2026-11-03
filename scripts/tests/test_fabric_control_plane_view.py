"""FCP-11H-08: Fabric Control Plane Flet view (model, renderer, navigation).

The model is exercised against a FAKE gateway module (synthetic answers in
the FCP-11G-07 schema); the renderer against an ISOLATED Flet stub injected
into `sys.modules` (no Flet installation is needed, nothing is displayed);
`app/main.py` and `frontend/layouts/sidebar.py` only through their AST
(importing them would pull Flet, dotenv and the app's services). The view
module is loaded by file path: `frontend/views/__init__.py` eagerly imports
Flet views, which a Flet-less CI cannot import. Nothing is read from disk,
executed, sent anywhere or skipped.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
VIEW_PATH = REPO / "frontend" / "views" / "fabric_control_plane_view.py"


def load_view(name: str = "fcp11h08_fabric_control_plane_view") -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, VIEW_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fv = load_view()
MAIN_PATH = REPO / "app" / "main.py"
SIDEBAR_PATH = REPO / "frontend" / "layouts" / "sidebar.py"
SCHEMA = "fcp11g07-control-plane-gateway-v1"
AS_OF = "2026-11-03T12:00:00Z"
SECRET = "sk-ant-api03-SYNTHETICSECRETVALUE0123456789"
PRIVATE_PATH = "C:/private/client-data/worktree"
FLAGS = ("certified", "authorizes_action", "execution_allowed", "network_used", "write_performed")
COMPONENT_MODULES = ("frontend.components.app_alert", "frontend.components.app_button",
                     "frontend.components.app_empty_state")


# ---------------------------------------------------------------------------
# Isolated Flet stub: every attribute is a recording factory
# ---------------------------------------------------------------------------

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


def flet_stub() -> types.ModuleType:
    module = types.ModuleType("flet")
    module.__getattr__ = lambda name: Node(f"flet.{name}")
    return module


def walk(node):
    yield node
    children = list(node.args) if isinstance(node, Node) else []
    if isinstance(node, Node):
        children += [node.__dict__.get("content")] + list(node.__dict__.get("controls") or [])
    for child in children:
        if isinstance(child, Node):
            yield from walk(child)


def texts(root) -> list:
    out = []
    for n in walk(root):
        if n.kind == "flet.Text":
            value = n.args[0] if n.args else n.__dict__.get("value")
            out.append(value)
    return out


def handlers(root) -> list:
    return [n.on_click for n in walk(root) if callable(n.__dict__.get("on_click"))]


class StubFletMixin:
    def stub_flet(self):
        patcher = mock.patch.dict(sys.modules, {"flet": flet_stub()})
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in COMPONENT_MODULES:  # re-import the reused components over the stub
            sys.modules.pop(name, None)


# ---------------------------------------------------------------------------
# Synthetic gateway answers
# ---------------------------------------------------------------------------

def status(outcome="SUCCESS", lifecycle="TERMINAL", condition="PRESENT"):
    return {"condition": condition, "source_value": outcome, "cause": None, "lifecycle": lifecycle,
            "runner_outcome": outcome, "actor": "NONE"}


def answer(name, result, revision="a" * 64, next_offset=None, **flags):
    body = {"schema": SCHEMA, "schema_version": 1, "query": name, "observed_at_utc": AS_OF,
            "request": {}, "sources": {"snapshot": revision}, "result": result,
            "page": None if name == "summary" else {"offset": 0, "limit": 50, "total": 1, "returned": 1,
                                                    "next_offset": next_offset},
            "revision": "b" * 64}
    body.update({f: False for f in FLAGS})
    body.update(flags)
    return body


def summary_answer(root="PRESENT", attention_class="AUTH", **kw):
    return answer("summary", {
        "root_condition": root, "root_cause": None if root == "PRESENT" else "SOURCE_ABSENT",
        "root_actor": "NONE", "attention_class": attention_class, "actor": "HUMAN", "origin": "PROVIDER",
        "class_counts": {"AUTH": 1, "CLEAR": 2}, "pipelines_shown": 1, "pipelines_omitted": 0,
        "workers_shown": 2, "workers_omitted": 0}, **kw)


def pipelines_answer(rows=None, **kw):
    if rows is None:
        rows = [{"pipeline_id": "pipe-1", "status": status("NONE", "WAITING"), "record_status": status(),
                 "agreement": "CONSISTENT", "attention_class": "AUTH", "primary_reason": "PROVIDER_AUTH_BLOCKED",
                 "workers": [
                     {"worker_id": "w1", "record_status": status(), "result_status": status(),
                      "agreement": "CONSISTENT", "attention_class": "CLEAR", "primary_reason": None},
                     {"worker_id": "w2", "record_status": status("BLOCKED", "WAITING"),
                      "result_status": status("UNKNOWN", "UNKNOWN", "MISSING"), "agreement": "CONSISTENT",
                      "attention_class": "AUTH", "primary_reason": "PROVIDER_AUTH_BLOCKED"}]}]
    return answer("pipelines", {"root_condition": "PRESENT", "pipelines": rows}, **kw)


def attention_answer(items=None, **kw):
    if items is None:
        items = [{"pipeline_id": "pipe-1", "worker_id": "w2", "attention_class": "AUTH", "actor": "HUMAN",
                  "origin": "PROVIDER", "primary_reason": "PROVIDER_AUTH_BLOCKED"},
                 {"pipeline_id": "pipe-1", "worker_id": "w1", "attention_class": "CLEAR", "actor": "NONE",
                  "origin": "NONE", "primary_reason": None}]
    return answer("attention", {"items": items}, **kw)


class FakeGatewayError(Exception):
    def __init__(self, code, message="fixed text"):
        super().__init__(code)
        self.code, self.message = code, message


class FakeGateway:
    """Stands in for `fabric_control_plane_gateway` (same public names)."""
    SCHEMA = SCHEMA
    GatewayError = FakeGatewayError

    def __init__(self, answers=None, fail=None):
        self.answers = answers or {"summary": summary_answer(), "pipelines": pipelines_answer(),
                                   "attention": attention_answer()}
        self.fail = fail or {}
        self.requests = []

    def GatewayRequest(self, query, allowed_roots, state_root, observed_at_utc, **kw):  # noqa: N802
        return {"query": query, "allowed_roots": allowed_roots, "state_root": state_root,
                "observed_at_utc": observed_at_utc, **kw}

    def query(self, request):
        self.requests.append(request)
        if request["query"] in self.fail:
            raise self.fail[request["query"]]
        return self.answers[request["query"]]


SOURCES = fv.ControlPlaneSources(("C:/synthetic/runtime",), "C:/synthetic/runtime/pipelines")


def model(**answers):
    base = {"summary": summary_answer(), "pipelines": pipelines_answer(), "attention": attention_answer()}
    base.update(answers)
    return fv.build_model(base["summary"], base["pipelines"], base["attention"], schema=SCHEMA)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class ModelTests(unittest.TestCase):
    def test_ready_model_copies_the_gateway_values(self):
        m = model()
        self.assertEqual(m["state"], fv.STATE_READY)
        self.assertEqual(m["headline"], {"attention_class": "AUTH", "actor": "HUMAN", "origin": "PROVIDER"})
        self.assertEqual(m["counts"], {"pipelines_shown": 1, "pipelines_omitted": 0, "workers_shown": 2,
                                       "workers_omitted": 0})
        (p,) = m["pipelines"]
        self.assertEqual((p["pipeline_id"], p["lifecycle"], p["outcome"], p["attention_class"]),
                         ("pipe-1", "WAITING", "NONE", "AUTH"))
        w2 = p["workers"][1]
        self.assertEqual((w2["outcome"], w2["result_outcome"], w2["primary_reason"]),
                         ("BLOCKED", "UNKNOWN", "PROVIDER_AUTH_BLOCKED"))
        self.assertTrue(m["consistent"])
        self.assertIsNone(m["error"])

    def test_missing_root_is_empty_never_success(self):
        m = model(summary=summary_answer(root="MISSING", attention_class="UNKNOWN"),
                  pipelines=pipelines_answer(rows=[]), attention=attention_answer(items=[]))
        self.assertEqual(m["state"], fv.STATE_EMPTY)
        self.assertEqual((m["root"]["condition"], m["root"]["cause"]), ("MISSING", "SOURCE_ABSENT"))
        self.assertNotIn("SUCCESS", repr(m))

    def test_present_root_without_pipelines_is_empty(self):
        self.assertEqual(model(pipelines=pipelines_answer(rows=[]))["state"], fv.STATE_EMPTY)

    def test_absent_or_malformed_fields_become_unknown_never_success(self):
        rows = [{"pipeline_id": 7, "status": "SUCCESS", "workers": [{"record_status": None, "agreement": ["x"]}]}]
        m = model(summary=answer("summary", {"class_counts": "x", "pipelines_shown": -3}),
                  pipelines=pipelines_answer(rows=rows), attention=attention_answer(items=["junk"]))
        p = m["pipelines"][0]
        self.assertEqual((p["pipeline_id"], p["outcome"], p["condition"]), ("7", fv.UNKNOWN, fv.UNKNOWN))
        self.assertEqual(p["workers"][0], {"worker_id": fv.UNKNOWN, "condition": fv.UNKNOWN,
                                           "lifecycle": fv.UNKNOWN, "outcome": fv.UNKNOWN,
                                           "result_outcome": fv.UNKNOWN, "agreement": fv.UNKNOWN,
                                           "attention_class": fv.UNKNOWN, "primary_reason": fv.UNKNOWN})
        self.assertEqual((m["state"], m["counts"]["pipelines_shown"], m["class_counts"]),
                         (fv.STATE_EMPTY, 0, {}))
        self.assertEqual(m["attention"][0]["attention_class"], fv.UNKNOWN)
        self.assertNotIn("SUCCESS", repr(m))

    def test_foreign_schema_or_query_fails_closed(self):
        for bad in (dict(summary_answer(), schema="other-v1"), dict(summary_answer(), query="pipelines"),
                    None, ["summary"]):
            m = model(summary=bad)
            self.assertEqual((m["state"], m["error"]["code"]), (fv.STATE_ERROR, fv.VIEW_RESPONSE_INVALID))
            self.assertEqual(m["pipelines"], [])

    def test_any_authority_flag_set_fails_closed(self):
        for flag in FLAGS:
            m = model(attention=attention_answer(**{flag: True}))
            self.assertEqual((m["state"], m["error"]["code"]), (fv.STATE_ERROR, fv.VIEW_AUTHORITY_FLAG), flag)

    def test_divergent_snapshot_revisions_are_flagged_inconsistent(self):
        self.assertFalse(model(pipelines=pipelines_answer(revision="c" * 64))["consistent"])
        self.assertFalse(model(summary=dict(summary_answer(), sources={}))["consistent"])

    def test_clear_items_are_hidden_and_more_pages_are_signalled(self):
        m = model(pipelines=pipelines_answer(next_offset=50), attention=attention_answer(next_offset=50))
        self.assertEqual([i["worker_id"] for i in m["attention"]], ["w2"])
        self.assertTrue(m["pipelines_more"] and m["attention_more"])
        self.assertFalse(model()["pipelines_more"])

    def test_strings_are_bounded(self):
        rows = [{"pipeline_id": "p" * 500, "status": status(), "workers": []}]
        self.assertEqual(len(model(pipelines=pipelines_answer(rows=rows))["pipelines"][0]["pipeline_id"]),
                         fv.MAX_TEXT)

    def test_governed_actions_are_never_authorized(self):
        for m in (model(), fv.error_model("GATEWAY_ROOTS_INVALID", "x")):
            self.assertEqual({a["action"] for a in m["actions"]}, {"pause", "cancel", "resume", "retry"})
            self.assertEqual({a["availability"] for a in m["actions"]}, {fv.ACTION_NOT_AUTHORIZED})
            self.assertEqual(set(m["actions"][0]), {"action", "label", "availability"})

    def test_error_model_keeps_only_fixed_codes(self):
        m = fv.error_model(PRIVATE_PATH, SECRET * 3)
        self.assertEqual(m["error"]["code"], fv.VIEW_INTERNAL_ERROR)
        self.assertLessEqual(len(m["error"]["message"]), fv.MAX_TEXT)
        self.assertEqual(fv.error_model("GATEWAY_ROOTS_INVALID", 5)["error"]["message"], fv.UNKNOWN)

    def test_sources_are_the_runner_default_layout(self):
        sources = fv.control_plane_sources(Path("C:/repo"))
        self.assertEqual(sources.allowed_roots, (str(Path("C:/repo/runtime/claude_runner")),))
        self.assertEqual(sources.state_root, str(Path("C:/repo/runtime/claude_runner/pipelines")))
        self.assertEqual(fv.utc_text(datetime(2026, 11, 3, 13, 0, 5, 999, tzinfo=timezone.utc)),
                         "2026-11-03T13:00:05Z")


class ObserveTests(unittest.TestCase):
    def test_observe_asks_only_the_three_read_queries(self):
        gw = FakeGateway()
        m = fv.observe(SOURCES, AS_OF, gateway=gw)
        self.assertEqual(m["state"], fv.STATE_READY)
        self.assertEqual([r["query"] for r in gw.requests], ["summary", "pipelines", "attention"])
        for r in gw.requests:
            self.assertEqual((r["allowed_roots"], r["state_root"], r["observed_at_utc"], r["limit"]),
                             (SOURCES.allowed_roots, SOURCES.state_root, AS_OF, fv.PAGE_LIMIT))
            self.assertEqual(set(r), {"query", "allowed_roots", "state_root", "observed_at_utc", "limit"})

    def test_gateway_refusal_is_an_error_state_and_stops(self):
        gw = FakeGateway(fail={"summary": FakeGatewayError("GATEWAY_PATH_OUTSIDE_ROOTS", "outside roots")})
        m = fv.observe(SOURCES, AS_OF, gateway=gw)
        self.assertEqual((m["state"], m["error"]["code"], m["error"]["message"]),
                         (fv.STATE_ERROR, "GATEWAY_PATH_OUTSIDE_ROOTS", "outside roots"))
        self.assertEqual(len(gw.requests), 1)

    def test_unexpected_exception_is_a_safe_error(self):
        gw = FakeGateway(fail={"attention": RuntimeError(PRIVATE_PATH + SECRET)})
        m = fv.observe(SOURCES, AS_OF, gateway=gw)
        self.assertEqual(m["error"]["code"], fv.VIEW_INTERNAL_ERROR)
        self.assertNotIn(SECRET, repr(m))
        self.assertNotIn("client-data", repr(m))

    def test_bad_sources_are_refused_without_a_query(self):
        gw = FakeGateway()
        m = fv.observe({"state_root": PRIVATE_PATH}, AS_OF, gateway=gw)
        self.assertEqual((m["state"], gw.requests), (fv.STATE_ERROR, []))


# ---------------------------------------------------------------------------
# Renderer (isolated Flet stub)
# ---------------------------------------------------------------------------

class RendererTests(StubFletMixin, unittest.TestCase):
    def setUp(self):
        self.stub_flet()
        self.page = mock.Mock()
        self.ticks = []

    def clock(self):
        self.ticks.append(1)
        return datetime(2026, 11, 3, 12, 0, len(self.ticks), tzinfo=timezone.utc)

    def view(self, gateway, sources=SOURCES):
        return fv.fabric_control_plane_view(self.page, sources=sources, gateway=gateway, now_utc=self.clock)

    def test_ready_view_shows_pipelines_workers_attention_and_unauthorized_actions(self):
        all_text = " ".join(texts(self.view(FakeGateway())))
        for expected in (fv.VIEW_TITLE, "pipe-1", "w1", "w2", "HUMAN ATTENTION", "PROVIDER_AUTH_BLOCKED",
                         "Pausar: No autorizada", "Cancelar: No autorizada", "Reanudar: No autorizada",
                         "Solo observación"):
            self.assertIn(expected, all_text)
        self.assertNotIn("C:/synthetic", all_text)

    def test_only_the_refresh_button_has_a_handler(self):
        root = self.view(FakeGateway())
        (handler,) = handlers(root)
        self.assertIn("Actualizar", texts(root))
        self.assertEqual(handler.__name__, "refresh")

    def test_reads_once_on_open_and_again_only_on_user_refresh(self):
        gw = FakeGateway()
        root = self.view(gw)
        self.assertEqual((len(self.ticks), len(gw.requests)), (1, 3))
        self.page.update.assert_not_called()
        (refresh,) = handlers(root)
        m = refresh(object())
        self.assertEqual((len(self.ticks), len(gw.requests)), (2, 6))
        self.assertEqual(gw.requests[-1]["observed_at_utc"], "2026-11-03T12:00:02Z")
        self.assertEqual(m["state"], fv.STATE_READY)
        self.page.update.assert_called_once_with()

    def test_error_and_empty_states_are_explicit(self):
        err = " ".join(texts(self.view(FakeGateway(fail={"summary": FakeGatewayError("GATEWAY_ROOTS_INVALID")}))))
        self.assertIn("no están disponibles", err)
        self.assertIn("GATEWAY_ROOTS_INVALID", err)
        self.assertNotIn("pipe-1", err)
        empty = FakeGateway({"summary": summary_answer(root="MISSING"), "pipelines": pipelines_answer(rows=[]),
                             "attention": attention_answer(items=[])})
        self.assertIn("Sin pipelines observados", " ".join(texts(self.view(empty))))
        none = " ".join(texts(self.view(FakeGateway(), sources=None)))
        self.assertIn("GATEWAY_SOURCE_REQUIRED", none)

    def test_inconsistent_reads_warn_the_operator(self):
        gw = FakeGateway({"summary": summary_answer(), "pipelines": pipelines_answer(revision="d" * 64),
                          "attention": attention_answer()})
        self.assertIn("Las fuentes cambiaron entre lecturas", " ".join(texts(self.view(gw))))


# ---------------------------------------------------------------------------
# Static: authority, no direct I/O, minimal navigation wiring
# ---------------------------------------------------------------------------

def tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


class StaticTests(unittest.TestCase):
    def test_view_has_no_flet_sql_filesystem_clock_loop_or_process_at_module_level(self):
        module = tree(VIEW_PATH)
        top = {a.name.split(".")[0] for n in module.body if isinstance(n, ast.Import) for a in n.names}
        top |= {n.module.split(".")[0] for n in module.body if isinstance(n, ast.ImportFrom) and n.module}
        self.assertNotIn("flet", top)
        every = {a.name.split(".")[0] for n in ast.walk(module) if isinstance(n, ast.Import) for a in n.names}
        every |= {n.module for n in ast.walk(module) if isinstance(n, ast.ImportFrom) and n.module}
        for banned in ("os", "sqlite3", "subprocess", "socket", "threading", "asyncio", "time", "shutil",
                       "backend", "database", "urllib", "http", "requests"):
            self.assertFalse({m for m in every if m == banned or m.startswith(banned + ".")}, banned)
        self.assertLessEqual({m for m in every if m.startswith("scripts.")}, {"scripts.ai"})
        names = {n.id for n in ast.walk(module) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(module) if isinstance(n, ast.Attribute)}
        self.assertFalse(names & {"open", "exec", "eval"})
        self.assertFalse(attrs & {"read_text", "read_bytes", "write_text", "write_bytes", "exists", "iterdir",
                                  "run_task", "run_thread", "Timer", "sleep", "execute", "resolve"})

    def test_view_imports_cleanly_without_flet(self):
        with mock.patch.dict(sys.modules, {"flet": None}):
            module = load_view("fcp11h08_view_without_flet")
            sources = module.ControlPlaneSources(SOURCES.allowed_roots, SOURCES.state_root)
            self.assertEqual(module.observe(sources, AS_OF, gateway=FakeGateway())["state"], fv.STATE_READY)

    def test_sidebar_lists_the_view_under_sistema_without_altering_existing_items(self):
        module = tree(SIDEBAR_PATH)
        values = {t.id: n.value for n in module.body if isinstance(n, ast.Assign) for t in n.targets
                  if isinstance(t, ast.Name)}
        groups = ast.literal_eval(values["MENU_GROUPS"])
        sistema = next(g for g in groups if g["title"] == "Sistema")
        labels = [label for label, _ in sistema["items"]]
        self.assertEqual(labels, ["Configuración", fv.VIEW_TITLE, "Legacy"])
        self.assertEqual(sum(1 for g in groups for label, _ in g["items"] if label == fv.VIEW_TITLE), 1)
        self.assertEqual([g["title"] for g in groups][:3], ["Contactos", "Expedientes", "Económico"])
        active = ast.literal_eval(values["KNOWN_ACTIVE_VIEWS"])
        self.assertIn(fv.VIEW_TITLE, active)
        self.assertLessEqual({"Clientes", "Configuración", "Twins", "Citas ICP Plus", "Reporting"}, active)

    def test_main_routes_the_view_with_explicit_sources_and_keeps_existing_routes(self):
        source = MAIN_PATH.read_text(encoding="utf-8")
        module = ast.parse(source)
        imports = [n for n in module.body if isinstance(n, ast.ImportFrom)
                   and n.module == "frontend.views.fabric_control_plane_view"]
        self.assertEqual(len(imports), 1)
        self.assertEqual({a.name for a in imports[0].names}, {"control_plane_sources", "fabric_control_plane_view"})
        compares = {n.comparators[0].value for n in ast.walk(module) if isinstance(n, ast.Compare)
                    and isinstance(n.left, ast.Name) and n.left.id == "view_name"
                    and isinstance(n.comparators[0], ast.Constant)}
        self.assertLessEqual({fv.VIEW_TITLE, "Configuración", "Clientes", "Twins", "Reporting", "WhatsApp"},
                             compares)
        calls = [n for n in ast.walk(module) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "fabric_control_plane_view"]
        self.assertEqual(len(calls), 1)
        self.assertEqual({k.arg for k in calls[0].keywords}, {"sources"})
        self.assertIn("content = settings_view(page)", source)


if __name__ == "__main__":
    unittest.main()
