"""Preloaded mapper regressions: real governance and synthetic native controls only.

QCC_EX01_R6_POSTFORM adaptation: the preload never writes a control whose
r-tabs surface is not the active one (the certified engine has no
hidden-tab write exception). Such a canonical control is DEFERRED and
written on its own surface once human navigation reaches it, in the same
VOLCAR. Scenarios that relied on hidden-tab writes now perform that human
navigation; the original assertions are kept on the surface where the
write happens, and the hidden-tab phase asserts that nothing was written.
"""
from contextlib import contextmanager
from collections import Counter

import pytest
import app.run_presentacion_asistida as runner
from qcc_full_mapper_doubles import (
    _TabbedMercurioBrowser, _datos, _run_full_mapper, _FakeActionClient,
    ALL_EX01_FIELDS, FAMILIAR_BLOCK, PERSONAL, PRESENTER, NOTIFICATION,
    TEN_FIELDS, NOTIFICATION_IDENTITY, _log_text,
    EXTRANJERO, DOMICILIO, NOTIFICACION, REPRESENTANTE,
)


@contextmanager
def mapper(browser, datos, tmp_path, **navigation):
    state = runner._MapperPreload(browser, datos, str(tmp_path), navigation)
    runner._ACTIVE_MAPPER_PRELOADS.append(state)
    try:
        yield state
    finally:
        runner._ACTIVE_MAPPER_PRELOADS.remove(state)


@pytest.mark.parametrize('kind,field', [
    ('INPUT_VALUE', 'preNombrePresentador'),
    ('SELECT', 'preTipodocumentoPresentador'),
    ('CHECKBOX', 'chkHijosCargo'),
    ('RADIO', 'chkHijosCargo'),
])
def test_hidden_canonical_native_control(tmp_path, kind, field):
    browser = _TabbedMercurioBrowser(
        fields=[field], panels={field: PRESENTER},
        selects=[field] if kind == 'SELECT' else [],
        checkboxes=[field] if kind == 'CHECKBOX' else [],
    )
    if kind == 'RADIO':
        elements = browser._elements
        def radio_elements():
            result = elements()
            result[0]['type'] = result[0]['attributes']['type'] = 'radio'
            return result
        browser._elements = radio_elements

    def write():
        if kind == 'INPUT_VALUE':
            return runner.set_value(browser, field, 'Ada', session_dir=str(tmp_path))
        if kind == 'SELECT':
            return runner.select_by_text_or_value(browser, field, value='PA', session_dir=str(tmp_path))
        if kind == 'CHECKBOX':
            return runner.set_checkbox(browser, field, value=True, session_dir=str(tmp_path))
        return runner.set_radio_checked(browser, field, session_dir=str(tmp_path))

    with runner.governed_section(browser, str(tmp_path), preload_fields={field}) as section:
        # Hidden tab: deferred, nothing written, no recapture.
        assert write() == 'DEFERRED_DEPENDENCY'
        assert browser.writes == []
        assert section.deferred == {field: 'DEFERRED_DEPENDENCY'}
        assert browser.capture_calls == 1
    browser.form.active_panel = PRESENTER  # human navigation
    with runner.governed_section(browser, str(tmp_path), preload_fields={field}) as section:
        outcome = write()
        assert not section.deferred
    assert outcome == 'OK'
    assert browser.writes == [field]
    assert 'POSTCONDITION_VERIFIED' in _log_text(str(tmp_path))
    assert browser.capture_calls == 2


def test_unknown_hidden_control_cannot_claim_canonical_authority(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_wait_for_dependency_readiness", lambda *a, **k: False)
    field = 'unknownSecret'
    browser = _TabbedMercurioBrowser(fields=[field], panels={field: PRESENTER})
    with runner.governed_section(browser, str(tmp_path), preload_fields={field}) as section:
        assert field not in section.preload_fields
        outcome = runner.set_value(browser, field, 'x', session_dir=str(tmp_path))
    assert outcome == 'DENIED'
    assert browser.writes == []


def test_metadata_never_resolved_or_written(tmp_path):
    datos = _datos('MERCURIO_EX01')
    metadata = {'ruta_box_dni_representante': 'private/path', 'representante_legal_contacto_id': '123',
                'preUnknown': 'not canonical', 'box_file_id': '456'}
    datos['representante'].update(metadata)
    browser = _TabbedMercurioBrowser(fields=ALL_EX01_FIELDS)
    result, _, _ = _run_full_mapper(tmp_path, browser, datos)
    assert result is None or result.get('ok') is not False
    assert not set(metadata) & set(browser.writes + browser.form.local_probes)
    assert all(datos['representante'][k] == v for k, v in metadata.items())
    assert _log_text(str(tmp_path)).count('NON_DOM_MAPPER_METADATA_SKIPPED') == len(metadata)


@pytest.mark.parametrize('mode', ['MERCURIO_EX01', 'MERCURIO_EX01_FAMILIAR', 'MERCURIO_EX02'])
def test_complete_preload_before_first_continue(tmp_path, mode):
    datos = _datos(mode, familiar=FAMILIAR_BLOCK, reagrupante=FAMILIAR_BLOCK)
    if mode == 'MERCURIO_EX02':
        datos['reagrupante'] = {'reaNombreReagrupante': 'R'}
    browser = _TabbedMercurioBrowser(fields=ALL_EX01_FIELDS + list(FAMILIAR_BLOCK))
    active_surface = set(EXTRANJERO) | set(DOMICILIO)
    nav_calls = []
    def first_continue(*args, **kwargs):
        # Everything of the active surface is volcado before the first
        # human CONTINUAR; nothing of a hidden one (presenter,
        # notification, family) is ever written from it.
        assert set(browser.writes) == active_surface
        nav_calls.append(True)
        return {'ok': False, 'mode': 'timeout'}
    result, _, _ = _run_full_mapper(tmp_path, browser, datos, extra={'wait_for_human_navigation': first_continue})
    assert result['ok'] is False  # Human continuation deliberately withheld.
    if mode == 'MERCURIO_EX02':
        # EX02 surface dispatch is not part of the EX01 130/131 post-form:
        # its sponsor surface is hidden here, so it fails closed before
        # any CONTINUAR and writes nothing.
        assert result['label'] == 'REAGRUPANTE_EX02_BLOCKED'
        assert nav_calls == [] and browser.writes == []
        return
    assert nav_calls == [True]
    assert max(Counter(browser.writes).values()) == 1


def test_absent_deferred_retry_and_no_duplicate_write(tmp_path):
    field = 'preNombrePresentador'
    browser = _TabbedMercurioBrowser(fields=ALL_EX01_FIELDS, absent={field})
    with mapper(browser, _datos('MERCURIO_EX01'), tmp_path) as state:
        first = state.resume(('extranjero', 'domicilio_extranjero'))
        assert first['ok']
        assert first['deferred'][field] == 'DEFERRED_NOT_PRESENT'
        assert field not in browser.writes and field not in state.verified
        before = list(browser.writes)
        # The rest of the hidden presenter surface was not written either.
        assert not set(REPRESENTANTE) & set(before)
        browser.form.absent.remove(field)
        browser.form.active_panel = PRESENTER
        assert state.resume(('representante',))['ok']
        presenter = list(REPRESENTANTE)
        assert browser.writes == before + presenter
        assert not set(REPRESENTANTE) & set(state.deferred)
        assert state.resume(('representante',))['ok']
        assert browser.writes == before + presenter
        browser.form.values[field] = ''
        assert state.resume(('representante',))['ok']
        assert browser.writes == before + presenter + [field]
        browser.form.active_panel = NOTIFICATION
        assert state.resume(('notificacion',))['ok']
        assert not state.deferred
        assert browser.writes.count(field) == 2


def test_required_active_missing_fails_closed(tmp_path):
    browser = _TabbedMercurioBrowser(fields=ALL_EX01_FIELDS, absent={'extNombre'})
    with mapper(browser, _datos('MERCURIO_EX01'), tmp_path) as state:
        result = state.resume(('extranjero',))
    assert not result['ok']
    assert 'REQUIRED_ACTIVE_MISSING' in _log_text(str(tmp_path))
    assert 'extNombre' not in browser.writes


def test_internal_hidden_dependency_not_granted_exception(tmp_path):
    field = 'preNombrePresentador'
    browser = _TabbedMercurioBrowser(fields=ALL_EX01_FIELDS, hidden={field})
    with mapper(browser, _datos('MERCURIO_EX01'), tmp_path) as state:
        assert state.resume(('extranjero',))['ok']
        assert state.deferred[field] == 'DEFERRED_DEPENDENCY'
        assert field not in browser.writes
        browser.form.hidden.clear()
        assert state.resume(())['ok']
        # Still not on the displayed surface: never written from here.
        assert field not in browser.writes and field not in state.verified
        browser.form.active_panel = PRESENTER
        assert state.resume(())['ok']
        assert field in state.verified


def test_cascade_missing_options_defers_without_blocking_unrelated(tmp_path):
    province, town = 'preCodigoProvinciaPresentador', 'preCodigoMunicipioPresentador'
    datos = _datos('MERCURIO_EX01')
    datos['representante'].update({province: '33', town + '_text': 'OVIEDO'})
    browser = _TabbedMercurioBrowser(fields=ALL_EX01_FIELDS + [province, town], selects=[province, town],
                                    options={province: [('', '' )], town: [('', '')]})
    with mapper(browser, datos, tmp_path) as state:
        assert state.resume(('extranjero',))['ok']
        assert state.deferred[province] == state.deferred[town] == 'DEFERRED_DEPENDENCY'
        assert town not in browser.writes
        # Unrelated controls are not blocked by the deferred cascade.
        assert set(EXTRANJERO) | set(DOMICILIO) <= set(state.verified)
        browser.form.options[province] = [('33', 'ASTURIAS')]
        browser.form.options[town] = [('001', 'OVIEDO')]
        browser.form.active_panel = PRESENTER
        assert state.resume(('representante',))['ok']
        assert not {province, town} & set(state.deferred)
        assert browser.form.values[town] == '001'
        browser.form.active_panel = NOTIFICATION
        assert state.resume(('notificacion',))['ok']
        assert not state.deferred
        assert 'notNombreNotificacion' in state.verified


def test_ten_preloaded_fields_one_capture(tmp_path):
    browser = _TabbedMercurioBrowser(fields=list(TEN_FIELDS), active_panel=PRESENTER,
                                    checkboxes=['chkHijosCargo'])
    with runner.governed_section(browser, str(tmp_path), preload_fields=TEN_FIELDS):
        result = runner.fill_section(browser, TEN_FIELDS, str(tmp_path))
    assert result['ok']
    assert browser.capture_calls == 1
    assert len(browser.form.readbacks) == 10


@pytest.mark.parametrize('later', [False, True])
def test_abort_during_preload_and_deferred_continuation(tmp_path, later):
    browser = _TabbedMercurioBrowser(fields=ALL_EX01_FIELDS, absent={'preNombrePresentador'})
    client = _FakeActionClient()
    closed = []
    with mapper(browser, _datos('MERCURIO_EX01'), tmp_path, action_client=client,
                abort_handler=lambda: closed.append(True) or True) as state:
        if later:
            assert state.resume(('extranjero',))['ok']
        before = list(browser.writes)
        client.actions.append({'action': 'PRESENTATION_ABORT'})
        result = state.resume(())
        assert runner._is_qcc_aborted_result(result)
        assert closed == [True]
        assert browser.writes == before
        assert state.resume(()) == result

def test_deferred_retry_is_continuation_of_same_volcar(tmp_path):
    field = 'preNombrePresentador'
    browser = _TabbedMercurioBrowser(fields=ALL_EX01_FIELDS, absent={field})
    calls = []
    def navigate(browser_arg, session_dir, label, ready_js, **kwargs):
        calls.append(label)
        if label == 'Datos del presentador':
            assert field not in browser.writes
            assert 'reason=DEFERRED_NOT_PRESENT' in _log_text(str(tmp_path))
            browser.form.absent.remove(field)
            browser.form.active_panel = PRESENTER
        else:
            browser.form.active_panel = NOTIFICATION
        return {'ok': True, 'mode': 'human_dom_detected'}
    result, trace, _ = _run_full_mapper(tmp_path, browser, _datos('MERCURIO_EX01'),
                                       extra={'wait_for_human_navigation': navigate})
    assert result is None or result.get('ok') is not False
    assert calls == ['Datos del presentador', 'Domicilio de notificación / CONCLUIR']
    assert trace == ['FINAL_HUMAN_CONCLUIR']
    assert set(browser.writes) == set(ALL_EX01_FIELDS) - NOTIFICATION_IDENTITY
    assert max(Counter(browser.writes).values()) == 1


def test_hidden_canonical_postcondition_failure_is_not_success(tmp_path):
    field = 'preNombrePresentador'
    browser = _TabbedMercurioBrowser(fields=[field], ignore_writes={field}, active_panel=PRESENTER)
    with runner.governed_section(browser, str(tmp_path), preload_fields={field}):
        assert runner.set_value(browser, field, 'P', session_dir=str(tmp_path)) == 'FAILED'


def test_preload_does_not_override_human_only_policy(tmp_path, monkeypatch):
    from dataclasses import replace
    import backend.automation.site_policies.mercurio as policy_module
    original = policy_module.build_mercurio_interaction_policy()
    monkeypatch.setattr(policy_module, 'build_mercurio_interaction_policy', lambda: replace(
        original, action_kind_rules={**original.action_kind_rules, 'INPUT_VALUE': 'HUMAN_ONLY'}))
    field = 'preNombrePresentador'
    browser = _TabbedMercurioBrowser(fields=[field], active_panel=PRESENTER)
    with runner.governed_section(browser, str(tmp_path), preload_fields={field}):
        outcome = runner.set_value(browser, field, 'P', session_dir=str(tmp_path))
    assert outcome == 'HUMAN_HANDOFF'
    assert browser.writes == []


def test_generated_javascript_distinguishes_panel_hiding_from_inner_hiding():
    import json
    import shutil
    import subprocess
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js required for generated JavaScript verification')
    # QCC_EX01_R6_POSTFORM: the presenter surface predicate is the R6 one
    # (presenter control present AND its panel the SOLE active EX01 panel);
    # the fake document resolves the form panels by id.
    harness = r'''
const panel = {id: 'tab-datos_presentador', display: 'none', visibility: 'visible',
  classList: {contains: () => false}, getClientRects: () => [], parentElement: null};
const inner = {display: 'block', visibility: 'visible', parentElement: panel,
  getAttribute: () => null};
const el = {id: 'preNombrePresentador', type: 'text', tagName: 'INPUT', disabled: false,
  hidden: false, display: 'block', visibility: 'visible', parentElement: inner,
  getAttribute: () => null, closest: () => panel,
  getClientRects: () => [], getBoundingClientRect: () => ({x:0,y:0,top:0,left:0,bottom:0,right:0,width:0,height:0})};
global.document = {getElementById: id => id === panel.id ? panel : (id.startsWith('tab-') ? null : el),
  documentElement: {clientWidth:100,clientHeight:100}};
global.window = {location: {origin:'https://sede.administracionespublicas.gob.es',pathname:'/mercurio/inicioMercurio.html'},
  innerWidth:100, innerHeight:100, getComputedStyle: n => ({display:n.display,visibility:n.visibility,opacity:'1',pointerEvents:'auto'})};
const probe = PROBE;
const ready = READY;
let results = [eval(probe).hidden_within_panel, eval(ready)];
inner.display = 'none'; results.push(eval(probe).hidden_within_panel);
inner.display = 'block'; inner.getAttribute = key => key === 'aria-hidden' ? 'true' : null;
results.push(eval(probe).hidden_within_panel);
inner.getAttribute = () => null; el.hidden = true; results.push(eval(probe).hidden_within_panel);
el.hidden = false; panel.display = 'block'; panel.classList.contains = () => true;
panel.getClientRects = () => [{}]; results.push(eval(ready));
console.log(JSON.stringify(results));
'''
    harness = harness.replace('PROBE', json.dumps(runner._field_local_probe_js('preNombrePresentador')))
    harness = harness.replace('READY', json.dumps(runner.EX01_TITULAR_PRESENTER_SURFACE_JS))
    result = subprocess.run([node, '-e', harness], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == [False, False, True, True, True, True]

def test_active_cascade_waits_for_matching_option_without_sleep(tmp_path, monkeypatch):
    province, town = 'extCodigoProvincia', 'extCodigoMunicipio'
    datos = _datos('MERCURIO_EX01')
    datos['domicilio_extranjero'].update({province: '33', town + '_text': 'OVIEDO'})
    browser = _TabbedMercurioBrowser(fields=ALL_EX01_FIELDS + [province, town], selects=[province, town],
                                    options={province: [('33', 'ASTURIAS')], town: [('', '')]})
    waits = []
    def ready(browser_arg, condition, **kwargs):
        assert browser_arg is browser
        assert town in condition and 'OVIEDO' in condition
        waits.append(condition)
        browser.form.options[town] = [('001', 'OVIEDO')]
        return True
    monkeypatch.setattr(runner, 'wait_for_js', ready)
    monkeypatch.setattr(runner.time, 'sleep', lambda *a: pytest.fail('No arbitrary sleeps'))
    with mapper(browser, datos, tmp_path) as state:
        assert state.resume(('extranjero', 'domicilio_extranjero'))['ok']
        # Only the hidden later surfaces stay deferred, never the cascade.
        assert set(state.deferred) == set(REPRESENTANTE) | set(NOTIFICACION)
        assert browser.form.values[town] == '001'
    assert len(waits) == 1


def test_abort_while_waiting_for_active_dependency(tmp_path):
    field = 'extCodigoProvincia'
    datos = _datos('MERCURIO_EX01')
    datos['domicilio_extranjero'] = {field: '33'}
    browser = _TabbedMercurioBrowser(fields=ALL_EX01_FIELDS + [field], selects=[field], options={field: []})
    client = _FakeActionClient()
    evaluate = browser.evaluate
    def queue_abort(script):
        result = evaluate(script)
        if 'const wantedValue = "33"' in script:
            client.actions.append({'action': 'PRESENTATION_ABORT'})
        return result
    browser.evaluate = queue_abort
    closed = []
    with mapper(browser, datos, tmp_path, action_client=client,
                abort_handler=lambda: closed.append(True) or True) as state:
        result = state.resume(('extranjero', 'domicilio_extranjero'))
        assert runner._is_qcc_aborted_result(result)
        assert closed == [True]
        assert 'preNombrePresentador' not in browser.writes

def test_dependency_readiness_javascript_checks_requested_option():
    import json
    import shutil
    import subprocess
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js required for generated JavaScript verification')
    script = r'''
const el = {tagName: 'SELECT', disabled: false, options: [], offsetWidth:10,
  getAttribute: () => null, closest: () => null, getClientRects: () => [{}]};
global.document = {getElementById: () => el};
global.window = {getComputedStyle: () => ({display:'block',visibility:'visible'})};
const condition = CONDITION;
let results = [eval(condition)];
el.options = [{value:'002',textContent:'AVILES'}]; results.push(eval(condition));
el.options = [{value:'001',textContent:'Oviedo'}]; results.push(eval(condition));
el.disabled = true; results.push(eval(condition));
console.log(JSON.stringify(results));
'''.replace('CONDITION', json.dumps(runner._preload_dependency_ready_js('extCodigoMunicipio', '', 'ÓVIEDO')))
    result = subprocess.run([node, '-e', script], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == [False, False, True, False]
