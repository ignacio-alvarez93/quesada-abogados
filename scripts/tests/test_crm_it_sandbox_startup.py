"""QUESADA_SANDBOX en app/main.py: AST + mocks, sin importar Flet ni el CRM."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


MAIN_PATH = Path("app/main.py")
LAUNCHER_PATH = Path("scripts/dev/crm_it_sandbox_launcher.py")
TREE = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
MAIN = next(n for n in TREE.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "main")

SESSION_STARTERS = {
    "start_icpplus_warning_watch",
    "maybe_start_icpplus_warning_ui_smoke",
    "start_whatsapp_session_services",
    "start_whatsapp_call_history_recovery",
    "start_qcc_bridge_session_services",
    "maybe_start_global_call_ui_smoke",
    "maybe_start_post_call_ui_smoke",
}


def function(name):
    return next(n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and n.name == name)


def compile_function(name, **namespace):
    node = function(name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), f"<{name}>", "exec"), namespace)
    return namespace[name]


def referenced_names(node):
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _is_sandbox_if(node, negated=False):
    expected = "not SANDBOX_MODE" if negated else "SANDBOX_MODE"
    return isinstance(node, ast.If) and ast.unparse(node.test) == expected


def run_prelude(environ, project_root, cwd):
    """Ejecuta el prólogo de módulo (hasta load_dotenv) con dependencias simuladas."""
    end = next(i for i, n in enumerate(TREE.body) if _is_sandbox_if(n, negated=True))
    body = [n for n in TREE.body[:end + 1] if not isinstance(n, (ast.Import, ast.ImportFrom))]
    load_dotenv = Mock()
    namespace = dict(
        __file__=str(Path(project_root) / "app" / "main.py"),
        Path=Path,
        json=json,
        os=SimpleNamespace(environ=environ, getcwd=lambda: str(cwd)),
        load_dotenv=load_dotenv,
    )
    exec(compile(ast.Module(body=body, type_ignores=[]), "<prelude>", "exec"), namespace)
    return namespace, load_dotenv


@pytest.fixture
def sealed(tmp_path):
    root = tmp_path / "sbx"
    project = root / "crm"
    (project / "app").mkdir(parents=True)
    (root / "quesada_sandbox_seal.json").write_text(
        json.dumps({"worktree": str(project.resolve())}), encoding="utf-8",
    )
    env = {"QUESADA_SANDBOX": "1", "QUESADA_SANDBOX_ROOT": str(root)}
    return SimpleNamespace(root=root, project=project, env=env)


# ------------------------------------------------------------
# Validación del flag antes de efectos laterales
# ------------------------------------------------------------

def test_flag_resolved_before_dotenv_flet_and_backend_imports():
    index = {}
    for i, node in enumerate(TREE.body):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "SANDBOX_MODE" for t in node.targets
        ):
            index.setdefault("flag", i)
        elif _is_sandbox_if(node, negated=True):
            index.setdefault("dotenv", i)
        elif isinstance(node, ast.Import) and any(a.name == "flet" for a in node.names):
            index.setdefault("flet", i)
        elif isinstance(node, ast.ImportFrom) and node.module.split(".")[0] in {"backend", "database", "frontend"}:
            index.setdefault("backend", i)
    assert index["flag"] < index["dotenv"] < index["flet"] < index["backend"]
    calls = [n for n in ast.walk(TREE) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "load_dotenv"]
    guarded = next(n for n in TREE.body if _is_sandbox_if(n, negated=True))
    assert len(calls) == 1 and calls[0] in list(ast.walk(guarded))


@pytest.mark.parametrize("environ", [{}, {"QUESADA_SANDBOX": "0"}])
def test_normal_mode_loads_env_local_as_before(tmp_path, environ):
    namespace, load_dotenv = run_prelude(environ, tmp_path, tmp_path)
    assert namespace["SANDBOX_MODE"] is False
    load_dotenv.assert_called_once_with(tmp_path.resolve() / ".env.local", override=False)


def test_sandbox_mode_never_loads_env_local(sealed):
    namespace, load_dotenv = run_prelude(sealed.env, sealed.project, sealed.project)
    assert namespace["SANDBOX_MODE"] is True
    load_dotenv.assert_not_called()


@pytest.mark.parametrize("value", ["", " ", "true", "yes", "on", " 1", "1 ", "2", "01"])
def test_ambiguous_flag_fails_closed(tmp_path, value):
    with pytest.raises(SystemExit, match="QUESADA_SANDBOX_AMBIGUOUS"):
        run_prelude({"QUESADA_SANDBOX": value}, tmp_path, tmp_path)


def _break_root(s):
    s.env["QUESADA_SANDBOX_ROOT"] = ""


def _foreign_root(s):
    s.env["QUESADA_SANDBOX_ROOT"] = str(s.root.parent)


def _env_local(s):
    (s.project / ".env.local").write_text("SECRET=1", encoding="utf-8")


def _no_seal(s):
    (s.root / "quesada_sandbox_seal.json").unlink()


def _bad_seal(s):
    (s.root / "quesada_sandbox_seal.json").write_text('{"worktree": "C:/otro"}', encoding="utf-8")


@pytest.mark.parametrize("damage, error", [
    (_break_root, "QUESADA_SANDBOX_ROOT_MISSING"),
    (_foreign_root, "SANDBOX_PROJECT_ROOT_OUTSIDE_SANDBOX"),
    (_env_local, "SANDBOX_ENV_LOCAL_PRESENT"),
    (_no_seal, "SANDBOX_SEAL_INVALID"),
    (_bad_seal, "SANDBOX_SEAL_MISMATCH"),
])
def test_sandbox_requires_coherent_sealed_root(sealed, damage, error):
    damage(sealed)
    with pytest.raises(SystemExit, match=error):
        run_prelude(sealed.env, sealed.project, sealed.project)


def test_sandbox_requires_cwd_on_worktree(sealed):
    with pytest.raises(SystemExit, match="SANDBOX_CWD_MISMATCH"):
        run_prelude(sealed.env, sealed.project, sealed.root)


# ------------------------------------------------------------
# Login sandbox -> Marketing -> IT
# ------------------------------------------------------------

def test_sandbox_login_goes_to_it_without_session_services():
    node = function("on_sandbox_login_success")
    assert not referenced_names(node) & (SESSION_STARTERS | {"instagram_runtime"})
    navigate, current_user = Mock(), {}
    callback = compile_function("on_sandbox_login_success", navigate=navigate, current_user=current_user)
    callback({"id": 7})
    navigate.assert_called_once_with("IT / Tendencias")
    assert current_user["value"] == {"id": 7}


def test_normal_login_flow_is_unchanged():
    node = function("on_login_success")
    order = []
    runtime = Mock()
    runtime.start.side_effect = lambda: order.append("instagram_runtime.start")
    namespace = dict(current_user={}, instagram_runtime=runtime)
    for call in ast.walk(node):
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
            name = call.func.id
            namespace[name] = Mock(side_effect=lambda *a, _n=name: order.append((_n, *a)))
    compile_function("on_login_success", **namespace)({"id": 1})
    assert order == [
        ("navigate", "Clientes"),
        ("start_icpplus_warning_watch",),
        ("maybe_start_icpplus_warning_ui_smoke",),
        ("start_whatsapp_session_services",),
        "instagram_runtime.start",
        ("maybe_start_global_call_ui_smoke",),
        ("maybe_start_post_call_ui_smoke",),
    ]


@pytest.mark.parametrize("sandbox, expected", [(True, "sandbox"), (False, "normal")])
def test_login_view_receives_mode_callback(sandbox, expected):
    login_view = Mock(return_value="LOGIN")
    container = SimpleNamespace(content=None)
    callbacks = dict(sandbox=object(), normal=object())
    start = compile_function(
        "start", SANDBOX_MODE=sandbox, login_view=login_view, main_container=container,
        page=Mock(), on_sandbox_login_success=callbacks["sandbox"],
        on_login_success=callbacks["normal"],
    )
    start()
    assert login_view.call_args.kwargs["on_login_success"] is callbacks[expected]
    assert container.content == "LOGIN"


def _navigate(sandbox):
    views = dict(
        marketing_trend_intelligence_view=Mock(return_value="IT"),
        reporting_view=Mock(return_value="REPORTING"),
        clients_view=Mock(return_value="CLIENTES"),
        communications_view=Mock(return_value="WA"),
        icpplus_view=Mock(return_value="ICP"),
    )
    namespace = dict(
        SANDBOX_MODE=sandbox, SANDBOX_VIEWS=("IT / Tendencias",), active_view={"value": None},
        main_container=SimpleNamespace(content=None), page=Mock(), ft=Mock(),
        main_layout=Mock(side_effect=lambda **k: k["content"]), sidebar_menu=Mock(),
        instagram_runtime=Mock(), create_crm_trend_dashboard=Mock(return_value="TRENDS"),
        whatsapp_runtime=Mock(), **views,
    )
    return compile_function("navigate", **namespace), namespace, views


@pytest.mark.parametrize("view", ["Clientes", "WhatsApp", "Citas ICP Plus", "Reporting", "Configuración"])
def test_sandbox_blocks_views_outside_it(view):
    navigate, namespace, views = _navigate(True)
    navigate(view)
    assert not any(mock.called for mock in views.values())
    namespace["ft"].Text.assert_called_once()
    assert "no disponible en SANDBOX" in namespace["ft"].Text.call_args.args[0]


def test_sandbox_renders_marketing_it_with_session_controller():
    navigate, namespace, views = _navigate(True)
    navigate("IT / Tendencias")
    views["marketing_trend_intelligence_view"].assert_called_once_with(
        namespace["page"], namespace["instagram_runtime"], trends="TRENDS",
    )
    assert namespace["main_container"].content == "IT"
    namespace["instagram_runtime"].start.assert_not_called()
    namespace["instagram_runtime"].execute.assert_not_called()


def test_normal_mode_navigation_unchanged():
    navigate, namespace, views = _navigate(False)
    navigate("Reporting")
    views["reporting_view"].assert_called_once_with(namespace["page"])
    assert namespace["main_container"].content == "REPORTING"


# ------------------------------------------------------------
# QCC, heartbeat, WhatsApp, Collector
# ------------------------------------------------------------

def test_qcc_owner_carries_sandbox_policy():
    owner = next(n for n in MAIN.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "qcc_bridge_owner" for t in n.targets))
    pairs = {ast.literal_eval(k): ast.unparse(v) for k, v in zip(owner.value.keys, owner.value.values)}
    assert pairs == {"server": "None", "disabled": "SANDBOX_MODE"}


@pytest.mark.parametrize("disabled, started", [(True, False), (False, True)])
def test_qcc_bridge_inhibited_only_in_sandbox(disabled, started):
    server = Mock(is_running=True)
    factory = Mock(return_value=server)
    start = compile_function("start_qcc_bridge_session_services", QccBridgeServer=factory,
                             qcc_bridge_owner={"server": None, "disabled": disabled})
    assert start() is started
    assert factory.called is started
    assert server.start.called is started


def test_sandbox_close_handler_skips_heartbeat_and_qcc():
    node = function("on_sandbox_page_close")
    assert not referenced_names(node) & {
        "icpplus_ui_presence_service", "close_qcc_bridge_session_services",
        "close_whatsapp_session_services", "QccBridgeServer",
    }
    runtime = Mock()
    assert compile_function("on_sandbox_page_close", instagram_runtime=runtime)() is False
    runtime.close.assert_called_once_with()


def test_sandbox_close_handler_replaces_normal_before_qcc_startup():
    def position(predicate):
        return next(i for i, n in enumerate(MAIN.body) if predicate(n))

    normal = position(lambda n: isinstance(n, ast.Assign)
                      and ast.unparse(n) == "page.on_close = on_page_close")
    sandbox = position(lambda n: _is_sandbox_if(n)
                       and ast.unparse(n.body[0]) == "page.on_close = on_sandbox_page_close")
    qcc = position(lambda n: isinstance(n, ast.Expr)
                   and ast.unparse(n) == "start_qcc_bridge_session_services()")
    assert normal < sandbox < qcc


def test_collector_runtime_factory_refused_in_sandbox():
    creation = next(i for i, n in enumerate(MAIN.body) if isinstance(n, ast.Assign)
                    and ast.unparse(n) == "instagram_runtime = create_crm_instagram_runtime()")
    guard = MAIN.body[creation + 1]
    assert _is_sandbox_if(guard)
    assert ast.unparse(guard.body[0]) == (
        "instagram_runtime.runtime_factory = refuse_sandbox_collector_runtime"
    )
    with pytest.raises(RuntimeError, match="SANDBOX_COLLECTOR_DISABLED"):
        compile_function("refuse_sandbox_collector_runtime")()


def test_refused_factory_keeps_collector_without_runtime_even_if_configured():
    from backend.services.instagram_collector_configuration_service import InstagramStartupConfiguration
    from backend.services.instagram_collector_control_service import InstagramCollectorControlService

    refuse = compile_function("refuse_sandbox_collector_runtime")
    control = InstagramCollectorControlService(
        lookup=Mock(), save_setting=Mock(), repository=Mock(), runtime_factory=refuse,
    )
    control.configuration = Mock(load=Mock(return_value=InstagramStartupConfiguration("IDLE", config=Mock())))
    control.start().result(5)
    state = control.state()
    assert state["history"][-1]["status"] == "ERROR"
    assert state["retained"] is False
    control.save_setting.assert_not_called()


def test_session_starters_only_reachable_from_normal_login():
    sandbox_reachable = set()
    for name in ("on_sandbox_login_success", "on_sandbox_page_close", "start", "navigate"):
        sandbox_reachable |= referenced_names(function(name))
    assert not sandbox_reachable & (SESSION_STARTERS - {"start_qcc_bridge_session_services"})
    assert "start_whatsapp_session_services" in referenced_names(function("on_login_success"))


# ------------------------------------------------------------
# El launcher nunca importa app.main en --prepare
# ------------------------------------------------------------

def test_launcher_references_app_main_only_in_launch():
    tree = ast.parse(LAUNCHER_PATH.read_text(encoding="utf-8"))
    owners = []
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef):
            for node in ast.walk(fn):
                if isinstance(node, ast.Constant) and node.value == "app.main":
                    owners.append(fn.name)
    assert owners == ["launch"]
    prepare = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "prepare")
    called = {n.func.id for n in ast.walk(prepare) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"launch", "validate_launch"}
    assert "Popen" not in ast.unparse(prepare)
