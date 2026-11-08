import ast
import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import flet as ft

from backend.services.trend_intelligence_dashboard_service import (
    MAX_EXPLANATIONS, MAX_SNAPSHOTS, TrendDashboardRow, TrendDashboardState,
)
from frontend.components.trend_intelligence_analytics_panel import (
    HEADER_HEIGHT, ROW_HEIGHT, trend_intelligence_analytics_panel,
)
from frontend.views.marketing_trend_intelligence_view import marketing_trend_intelligence_view

PANEL = 'frontend/components/trend_intelligence_analytics_panel.py'
VIEW = 'frontend/views/marketing_trend_intelligence_view.py'


def _texts(control):
    found, stack = [], [control]
    while stack:
        node = stack.pop()
        if isinstance(node, ft.Text) and node.value is not None:
            found.append(str(node.value))
        children = []
        for attr in ('content', 'controls'):
            child = getattr(node, attr, None)
            if isinstance(child, list):
                children.extend(child)
            elif isinstance(child, ft.Control):
                children.append(child)
        stack.extend(reversed(children))  # document order
    return found


def _title(control):
    controls = getattr(getattr(control, 'content', None), 'controls', None) or []
    return getattr(controls[0], 'value', None) if controls else None


def _render(state=None, error=None):
    page, service = Mock(), Mock()
    if error is not None:
        service.state.side_effect = error
    else:
        service.state.return_value = state
    card = trend_intelligence_analytics_panel(page, service)
    asyncio.run(page.run_task.call_args.args[0]())
    service.state.assert_called_once_with()
    return card, ' | '.join(_texts(card))


def _snapshot(**overrides):
    values = dict(topic_id=1, status='EMERGING', score=72.5, velocity=1.25, observation_count=4,
                  source_count=2, window_start='2026-09-22T00:00:00+00:00',
                  window_end='2026-09-22T23:59:59+00:00', country='', language='')
    values.update(overrides)
    return SimpleNamespace(**values)


def _explanation():
    return SimpleNamespace(
        contributing_sources=(SimpleNamespace(source_code='SOURCE_X', health_state='FAILED'),),
        provenance=(SimpleNamespace(collector_key='RSS_COLLECTOR', collector_version='1.0', provider='FEEDLY'),),
        partial_sources=('SOURCE_X',),
        recurrence=(SimpleNamespace(window_end='2026-09-21T23:59:59+00:00', score=40.0, status='DORMANT'),),
    )


def test_ui_has_no_storage_browser_or_backend_imports():
    for path in (PANEL, VIEW):
        source = Path(path).read_text(encoding='utf-8-sig')
        tree = ast.parse(source)
        imports = [n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        imports += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert not any(term in name.lower() for name in imports
                       for term in ('sqlite', 'selenium', 'browser', 'repositories', 'backend', 'database'))
        for term in ('SELECT ', 'INSERT ', 'CREATE ', 'sqlite3', 'mode=ro'):
            assert term not in source


def test_protected_files_unchanged():
    digest = hashlib.sha256(Path('frontend/components/instagram_collector_panel.py').read_bytes()).hexdigest()
    assert digest == '751dd92e3edf2aff6a8005fcdaf9ebdfbcde37f68395366a6a5e7aa5d5c1be4f'


def test_view_without_trends_adds_nothing_and_schedules_only_collector():
    page = Mock()
    view = marketing_trend_intelligence_view(page, Mock())
    titles = [_title(c) for c in view.content.controls]
    assert 'Analítica de tendencias' not in titles
    assert titles[-2:] == ['Resultados', 'Historial / Log']
    assert page.run_task.call_count == 1
    assert page.run_task.call_args.args[0].__name__ == 'refresh'


def test_view_with_trends_inserts_before_resultados_without_reading_or_running():
    page, collector, trends = Mock(), Mock(), Mock()
    baseline = marketing_trend_intelligence_view(Mock(), Mock())
    view = marketing_trend_intelligence_view(page, collector, trends=trends)
    controls = view.content.controls
    titles = [_title(c) for c in controls]
    assert len(controls) == len(baseline.content.controls) + 1
    assert titles.index('Analítica de tendencias') == titles.index('Resultados') - 1
    assert titles[-2:] == ['Resultados', 'Historial / Log']
    # Collector header, run action and placement are untouched.
    header = controls[0]
    assert isinstance(header, ft.Row) and header.wrap is not True
    assert header.controls[0].controls[0].value == 'IT / Tendencias'
    assert header.controls[1].controls[-1].disabled is True
    # Opening only schedules reads; collector refresh stays the last task.
    assert [c.args[0].__name__ for c in page.run_task.call_args_list] == ['load_analytics', 'refresh']
    trends.state.assert_not_called()
    collector.execute.assert_not_called()
    collector.start.assert_not_called()


def test_positional_contract_preserved():
    import inspect
    params = inspect.signature(marketing_trend_intelligence_view).parameters
    assert list(params) == ['page', 'service', 'trends']
    assert params['trends'].default is None


def test_card_layout_is_constrained():
    card, _ = _render(TrendDashboardState('EMPTY', domain_code='D', domain_name='Dom'))
    header = card.content.controls[1].controls[0]
    assert isinstance(header, ft.Row) and header.wrap is not True
    assert header.vertical_alignment == ft.CrossAxisAlignment.CENTER
    assert card.expand is not True
    stack = [card]
    while stack:
        node = stack.pop()
        assert not (isinstance(node, ft.Container) and node.expand is True and node.content is None)
        for attr in ('content', 'controls'):
            child = getattr(node, attr, None)
            stack.extend(child if isinstance(child, list) else [child] if isinstance(child, ft.Control) else [])


def test_non_ready_states_are_distinct_and_honest():
    cases = {
        'Sin dominio configurado': TrendDashboardState('NO_DOMAIN', reason='NOT_CONFIGURED'),
        'Sin base de datos': TrendDashboardState('NO_STORE'),
        'Sin snapshots': TrendDashboardState('EMPTY', domain_code='D', domain_name='Dom'),
        'Esquema incompleto': TrendDashboardState('SCHEMA_INCOMPLETE', missing_tables=('ti_trend_snapshots',)),
        'Error': TrendDashboardState('ERROR', reason='READ_FAILED'),
    }
    rendered = {}
    for label, state in cases.items():
        _, text = _render(state)
        assert label in text
        assert 'Puntuación' not in text
        rendered[label] = text
    assert len(set(rendered.values())) == len(cases)
    assert 'ti_trend_snapshots' in rendered['Esquema incompleto']
    assert 'No se crea' in rendered['Sin base de datos']
    assert 'Dom (D)' in rendered['Sin snapshots']
    _, unregistered = _render(TrendDashboardState('NO_DOMAIN', reason='NOT_REGISTERED', domain_code='X'))
    assert 'no está registrado' in unregistered and 'Dominio: X' in unregistered
    _, invalid = _render(TrendDashboardState('ERROR', reason='INVALID_SETTINGS'))
    assert 'no es válida' in invalid


def test_service_exception_renders_safe_error():
    _, text = _render(error=RuntimeError('boom /secret/path'))
    assert 'Error' in text and 'secret' not in text


def test_ready_shows_real_values_and_sin_datos_for_missing():
    rows = (
        TrendDashboardRow(snapshot=_snapshot(), topic=SimpleNamespace(name='Topic A'),
                          baseline_mean=None, baseline_samples=None,
                          explanation=_explanation(), explanation_status='READY'),
        TrendDashboardRow(snapshot=_snapshot(topic_id=2, score=10.0, velocity=-0.5), topic=None,
                          baseline_mean=3.5, baseline_samples=2,
                          explanation=None, explanation_status='NOT_REQUESTED'),
    )
    _, text = _render(TrendDashboardState('READY', domain_code='D', domain_name='Dom', rows=rows,
                                          partial_sources=('SOURCE_X',)))
    for expected in ('Datos disponibles', 'Topic A', '72.5', '+1.25', '-0.50', '3.50 (2 muestras)',
                     'SOURCE_X [FAILED]', 'RSS_COLLECTOR 1.0 · FEEDLY', '40.0 DORMANT', 'EMERGING'):
        assert expected in text, expected
    cells = text.split(' | ')
    assert 'Sin datos' in cells  # missing baseline/topic/scope are never shown as zero
    assert '0.00' not in cells and '0' not in cells


def test_ready_without_explanations_does_not_invent_partial_count():
    rows = (TrendDashboardRow(snapshot=_snapshot(), topic=None, baseline_mean=None, baseline_samples=None,
                              explanation=None, explanation_status='FAILED'),)
    _, text = _render(TrendDashboardState('READY', domain_code='D', domain_name='Dom', rows=rows))
    assert 'No disponible' in text
    cells = text.split(' | ')
    index = cells.index('Fuentes con cobertura parcial')
    assert cells[index + 1] == 'Sin datos'


# Content width left for the card at a 1280 px desktop: sidebar 310, layout
# padding 16+4, collector panel padding 2x20, card padding 2x18 and border.
CONTENT_WIDTH_1280 = 1280 - 310 - 20 - 40 - 36 - 2
LONG_TOPIC = 'Topic ' + 'muy largo ' * 12


def _walk(control):
    stack = [control]
    while stack:
        node = stack.pop()
        yield node
        children = []
        for attr in ('content', 'controls'):
            child = getattr(node, attr, None)
            children.extend(child if isinstance(child, list) else [child] if isinstance(child, ft.Control) else [])
        stack.extend(reversed(children))  # document order


def _tables(card):
    # app_table root: bordered container whose content is the scrolling row.
    return [node for node in _walk(card) if isinstance(node, ft.Container)
            and isinstance(node.content, ft.Row) and node.content.scroll is not None
            and node.border_radius == 12]


def _parts(table):
    inner = table.content.controls[0]
    header, body = inner.content.controls
    return inner, header.content.controls, body.content


def _ready(count, explained=MAX_EXPLANATIONS):
    rows = tuple(
        TrendDashboardRow(snapshot=_snapshot(topic_id=i, score=float(100 - i)),
                          topic=SimpleNamespace(name=LONG_TOPIC if i == 0 else f'Topic {i:02d}'),
                          baseline_mean=None, baseline_samples=None,
                          explanation=_explanation() if i < explained else None,
                          explanation_status='READY' if i < explained else 'NOT_REQUESTED')
        for i in range(count))
    return TrendDashboardState('READY', domain_code='D', domain_name='Dom', rows=rows)


def test_single_row_table_reserves_no_large_blank_area():
    card, _ = _render(_ready(1, explained=1))
    snapshots, explanations = _tables(card)
    for table in (snapshots, explanations):
        _, _, body = _parts(table)
        assert len(body.controls) == 1
        # Header + one row + scrollbar allowance; previously a fixed 320/220 px.
        assert table.height == HEADER_HEIGHT + ROW_HEIGHT + 14
        assert table.height - HEADER_HEIGHT - ROW_HEIGHT <= 20


def test_twenty_snapshots_stay_bounded_scrollable_and_ordered():
    card, text = _render(_ready(MAX_SNAPSHOTS))
    snapshots, explanations = _tables(card)
    _, headers, body = _parts(snapshots)
    assert len(body.controls) == MAX_SNAPSHOTS
    assert body.scroll == ft.ScrollMode.AUTO
    assert ROW_HEIGHT * 4 < snapshots.height - HEADER_HEIGHT < ROW_HEIGHT * MAX_SNAPSHOTS
    # Rows keep the service order (score DESC) and only top explanations are shown.
    topics = [row.content.controls[0].content.value for row in body.controls]
    assert topics == [LONG_TOPIC] + [f'Topic {i:02d}' for i in range(1, MAX_SNAPSHOTS)]
    scores = [row.content.controls[2].content.value for row in body.controls]
    assert scores == [f'{100 - i:.1f}' for i in range(MAX_SNAPSHOTS)]
    assert len(_parts(explanations)[2].controls) == MAX_EXPLANATIONS
    assert 'Datos disponibles' in text


def test_rightmost_columns_reachable_on_narrow_viewport():
    card, _ = _render(_ready(2))
    tables = _tables(card)
    assert len(tables) == 2
    for table, last in zip(tables, ('País / Idioma', 'Historial')):
        inner, headers, body = _parts(table)
        assert headers[-1].content.value == last
        # Wider than the 1280 px content area, so the scrollbar must stay visible
        # and the scroll extent must cover every column (none silently clipped).
        assert inner.width > CONTENT_WIDTH_1280
        assert table.content.scroll == ft.ScrollMode.ALWAYS
        assert inner.width >= sum(h.width for h in headers)
        for row in body.controls:
            cells = row.content.controls
            assert len(cells) == len(headers)
            assert [c.width for c in cells] == [h.width for h in headers]


def test_long_values_wrap_and_expose_full_text():
    card, text = _render(_ready(1, explained=1))
    assert LONG_TOPIC in text
    for table in _tables(card):
        for row in _parts(table)[2].controls:
            for cell in row.content.controls:
                assert isinstance(cell.content, ft.Text)
                assert cell.content.max_lines == 2
                assert cell.content.tooltip == cell.content.value


def test_ready_statuses_and_labels_preserved_with_responsive_table():
    state = _ready(3)
    rows = list(state.rows)
    rows[1] = TrendDashboardRow(snapshot=_snapshot(topic_id=1, status='DORMANT', score=None), topic=None,
                                baseline_mean=None, baseline_samples=None, explanation=None,
                                explanation_status='FAILED')
    card, text = _render(TrendDashboardState('READY', domain_code='D', domain_name='Dom', rows=tuple(rows)))
    snapshots, explanations = _tables(card)
    labels = [h.content.value for h in _parts(snapshots)[1]]
    assert labels == ['Tema', 'Estado', 'Puntuación', 'Velocidad', 'Observaciones', 'Fuentes',
                      'Línea base', 'Ventana', 'País / Idioma']
    assert [h.content.value for h in _parts(explanations)[1]] == [
        'Tema', 'Fuentes contribuyentes', 'Procedencia', 'Cobertura parcial', 'Historial']
    statuses = [row.content.controls[1].content.value for row in _parts(snapshots)[2].controls]
    assert statuses == ['EMERGING', 'DORMANT', 'EMERGING']
    assert 'No disponible' in text and 'Sin datos' in text.split(' | ')
