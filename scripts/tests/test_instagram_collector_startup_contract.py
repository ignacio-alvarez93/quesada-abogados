"""Execute CRM composition without importing Flet or its database."""
import ast
from pathlib import Path
from unittest.mock import Mock


TREE = ast.parse(Path('app/main.py').read_text(encoding='utf-8'))


def function(name):
    return next(n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and n.name == name)


def test_one_safe_runtime_per_crm_session():
    calls = [n for n in ast.walk(TREE) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == 'create_crm_instagram_runtime']
    assert len(calls) == 1
    assert not calls[0].args and not calls[0].keywords


def test_authenticated_startup_renders_before_dispatch():
    node = function('on_login_success')
    runtime = Mock()
    order = []
    runtime.start.side_effect = lambda: order.append('instagram')
    namespace = dict(current_user={}, instagram_runtime=runtime)
    for call in ast.walk(node):
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
            name = call.func.id
            namespace[name] = Mock(side_effect=lambda *a, _name=name: order.append(_name))
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<startup>', 'exec'), namespace)
    namespace['on_login_success']({'id': 1})
    runtime.start.assert_called_once_with()
    assert order.index('navigate') < order.index('instagram')
    assert order.index('navigate') < order.index('start_whatsapp_session_services') < order.index('instagram')


def test_shutdown_requests_cleanup_independently():
    node = function('on_page_close')
    runtime = Mock()
    namespace = dict(instagram_runtime=runtime, icpplus_warning_watch_shutdown={},
                     icpplus_ui_presence_service=Mock(), icpplus_ui_instance_id='test')
    for name in ['close_whatsapp_session_services', 'close_dehu_session_services',
                 'close_icpplus_session_services', 'close_qcc_bridge_session_services']:
        namespace[name] = Mock(side_effect=RuntimeError('offline failure'))
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<shutdown>', 'exec'), namespace)
    namespace['on_page_close']()
    runtime.close.assert_called_once_with()


def test_close_handler_installed_before_login():
    assignment = next(n for n in ast.walk(TREE) if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Attribute) and t.attr == 'on_close' for t in n.targets))
    assert assignment.lineno < function('on_login_success').lineno


def test_only_authenticated_callback_dispatches_collection():
    starts = [n for n in ast.walk(TREE) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute) and n.func.attr == 'start'
              and isinstance(n.func.value, ast.Name) and n.func.value.id == 'instagram_runtime']
    assert len(starts) == 1
    assert starts[0] in list(ast.walk(function('on_login_success')))
    main = next(n for n in TREE.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'main')
    owners = [n for n in main.body if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == 'instagram_runtime' for t in n.targets)]
    assert len(owners) == 1


def test_repeated_login_callbacks_share_one_real_worker():
    from backend.services.instagram_collector_runtime_service import InstagramCollectorRuntimeService
    from backend.services.instagram_collector_configuration_service import InstagramStartupConfiguration

    lookup = Mock(load=Mock(return_value=InstagramStartupConfiguration('DISABLED')))
    runtime = InstagramCollectorRuntimeService(configuration_service=lookup)
    node = function('on_login_success')
    namespace = dict(current_user={}, instagram_runtime=runtime)
    for call in ast.walk(node):
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
            namespace[call.func.id] = Mock()
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<startup>', 'exec'), namespace)
    try:
        lookup.load.assert_not_called()
        for _ in range(8):
            namespace['on_login_success']({'id': 1})
        runtime.start().result(5)
        lookup.load.assert_called_once_with()
        assert runtime.snapshot.status == 'DISABLED'
    finally:
        runtime.close().result(5)


def test_instagram_close_failure_preserves_other_shutdowns_and_qcc_last():
    order = []
    runtime = Mock(close=Mock(side_effect=RuntimeError('dispatch failure')))
    namespace = dict(instagram_runtime=runtime, icpplus_warning_watch_shutdown={},
                     icpplus_ui_presence_service=Mock(), icpplus_ui_instance_id='test')
    names = ['close_whatsapp_session_services', 'close_dehu_session_services',
             'close_icpplus_session_services', 'close_qcc_bridge_session_services']
    for name in names:
        namespace[name] = Mock(side_effect=lambda _name=name: order.append(_name))
    node = function('on_page_close')
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<shutdown>', 'exec'), namespace)
    namespace['on_page_close']()
    assert order == names
    runtime.close.assert_called_once_with()


def test_qcc_startup_remains_independent_and_idempotent_before_login():
    server = Mock(is_running=True)
    factory = Mock(return_value=server)
    namespace = dict(QccBridgeServer=factory, qcc_bridge_owner={'server': None})
    node = function('start_qcc_bridge_session_services')
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<qcc>', 'exec'), namespace)
    assert namespace[node.name]() is True
    assert namespace[node.name]() is True
    factory.assert_called_once_with()
    server.start.assert_called_once_with()
    main = next(n for n in TREE.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'main')
    startup = next(n for n in main.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                   and isinstance(n.value.func, ast.Name) and n.value.func.id == node.name)
    assert startup.lineno < function('on_login_success').lineno
