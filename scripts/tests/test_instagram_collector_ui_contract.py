import ast
from pathlib import Path
from unittest.mock import Mock
import flet as ft
from frontend.layouts.sidebar import MENU_GROUPS, KNOWN_ACTIVE_VIEWS, sidebar_menu
from frontend.views.marketing_trend_intelligence_view import marketing_trend_intelligence_view


def test_marketing_only_new_entry_active():
    marketing = next(g for g in MENU_GROUPS if g['title'] == 'Marketing')
    assert len(marketing['items']) == 5
    assert [name for name, _ in marketing['items'] if name in KNOWN_ACTIVE_VIEWS] == ['IT / Tendencias']
    assert marketing['items'][-1][0] == 'IT / Tendencias'


def test_sidebar_geometry_and_navigation():
    navigate = Mock()
    sidebar = sidebar_menu(navigate)
    assert sidebar.width == 310
    assert sidebar.bgcolor == '#003B7A'
    menu = sidebar.content.controls[2].content
    index = next(i for i, group in enumerate(MENU_GROUPS) if group['title'] == 'Marketing')
    item = menu.controls[index].controls[1].controls[-1]
    item.on_click(None)
    navigate.assert_called_once_with('IT / Tendencias')


def test_ui_has_no_storage_or_browser_imports():
    for path in ['frontend/components/instagram_collector_panel.py', 'frontend/views/marketing_trend_intelligence_view.py',
                 'frontend/components/trend_intelligence_analytics_panel.py']:
        source = Path(path).read_text(encoding='utf-8-sig')
        tree = ast.parse(source)
        imports = [n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        imports += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert not any(any(term in name.lower() for term in ('sqlite', 'selenium', 'repositories')) for name in imports)
        assert 'SELECT ' not in source


def test_open_only_schedules_read():
    page, service = Mock(), Mock()
    view = marketing_trend_intelligence_view(page, service)
    assert isinstance(view, ft.Container)
    service.execute.assert_not_called()
    service.start.assert_not_called()
    assert page.run_task.call_args.args[0].__name__ == 'refresh'


def test_navigation_uses_shared_controller():
    source = Path('app/main.py').read_text(encoding='utf-8')
    assert 'create_crm_instagram_control as create_crm_instagram_runtime' in source
    calls = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)
             and getattr(n.func, 'id', None) == 'marketing_trend_intelligence_view']
    # Exactly one navigation call: page first, the shared controller still SECOND
    # positional; optional analytics only as the separate `trends` keyword.
    assert len(calls) == 1
    call = calls[0]
    assert [a.id for a in call.args] == ['page', 'instagram_runtime']
    assert [k.arg for k in call.keywords] == ['trends']
    assert call.keywords[0].value.func.id == 'create_crm_trend_dashboard'


def test_sidebar_original_preserved_except_two_authorized_additions():
    import hashlib
    source = Path('frontend/layouts/sidebar.py').read_text(encoding='utf-8')
    lines = [line for line in source.splitlines() if '"IT / Tendencias"' not in line]
    digest = hashlib.sha256(ast.dump(ast.parse('\n'.join(lines))).encode()).hexdigest()
    assert digest == '07f6f2e987c83e9fbc43693d787b3917118ca1f36881a6ad09638dc08363e213'

def test_refresh_renders_empty_state_without_execution():
    import asyncio
    page, service = Mock(), Mock()
    service.state.return_value = dict(settings={}, busy=False, retained=False,
        effective='NOT_CONFIGURED', status='NOT_CONFIGURED', latest=None, rows=[], history=[])
    view = marketing_trend_intelligence_view(page, service)
    asyncio.run(page.run_task.call_args.args[0]())
    service.state.assert_called_once_with()
    service.execute.assert_not_called()
    # Approved R3 layout: run is the last header action; Resultados uses the shared empty_state.
    run = view.content.controls[0].controls[1].controls[-1]
    assert run.disabled is True
    empty = view.content.controls[-2].content.controls[1].controls[-1]
    assert 'Sin resultados' in empty.content.controls[1].value


def test_outer_header_does_not_wrap_and_is_centered():
    view = marketing_trend_intelligence_view(Mock(), Mock())
    header = view.content.controls[0]
    assert isinstance(header, ft.Row)
    assert header.wrap is not True
    assert header.vertical_alignment == ft.CrossAxisAlignment.CENTER
    assert header.alignment == ft.MainAxisAlignment.SPACE_BETWEEN
    title = header.controls[0].controls[0]
    assert title.value == 'IT / Tendencias'
    assert header.controls[1].controls[-1].disabled is True
