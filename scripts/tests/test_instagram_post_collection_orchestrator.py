"""TI-4C.3E3A2 post-collection orchestrator (single nominal caller).

Fakes for the runtime and temporary stores under tmp_path; the shared OS lock
is redirected to a temporary per-user dir. No operational database, browser,
network, Chrome profile or Instagram.
"""
import ast
import json
import subprocess
import sys
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock

import pytest

import backend.services.config_service as config_service
import backend.services.trend_post_collection_service as post_collection
from backend.services import instagram_post_collection_orchestrator as orchestrator_module
from backend.services.instagram_collector_configuration_service import InstagramStartupConfiguration
from backend.services.instagram_collector_control_service import (
    InstagramCollectorControlService,
    create_crm_instagram_control,
)
from backend.services.instagram_post_collection_orchestrator import (
    InstagramPostCollectionOrchestrator,
    create_post_collection_hook,
)
from backend.services.trend_post_collection_service import (
    PostCollectionClassification,
    TrendPostCollectionService,
)
from backend.trend_intelligence.producer import create_trend_producer
from scripts.tests.test_trend_intelligence_producer import (
    DOMAIN,
    build_store,
    count,
    day,
    ingest,
    topic_link,
)

ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_PATH = ROOT / "backend" / "services" / "instagram_post_collection_orchestrator.py"


@pytest.fixture(autouse=True)
def lock_root(tmp_path, monkeypatch):
    root = tmp_path / "lockroot"
    root.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(root))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(root))
    return root


def event(**overrides):
    return dict(dict(run_id="abc123", collection_status="SUCCESS", browser_released=True,
                     domain_code=DOMAIN, observation_ids=(3, 4)), **overrides)


def fake_service(result=None):
    service = Mock()
    service.classify_after_collection.return_value = result or PostCollectionClassification("OK", DOMAIN)
    return service


# ------------------------------------------------------------ unit

def test_construction_opens_nothing(tmp_path):
    db_path, factory = Mock(), Mock()
    InstagramPostCollectionOrchestrator(db_path_provider=db_path, service_factory=factory)
    create_post_collection_hook()
    db_path.assert_not_called()
    factory.assert_not_called()
    assert [p.name for p in tmp_path.iterdir()] == ["lockroot"]


def test_forwards_event_preconditions_and_returns_projection(tmp_path):
    service = fake_service()
    factory = Mock(return_value=service)
    hook = InstagramPostCollectionOrchestrator(db_path_provider=lambda: tmp_path / "ti.db", service_factory=factory)
    projection = hook(event(observation_ids=[3, 4]))
    service.classify_after_collection.assert_called_once_with(
        db_path=tmp_path / "ti.db", domain_code=DOMAIN, collection_ok=True, browser_closed=True,
        observation_ids=(3, 4))
    assert projection == dict(PostCollectionClassification("OK", DOMAIN).projection(), run_id="abc123")
    hook(event())
    factory.assert_called_once()  # Lazy and reused.


@pytest.mark.parametrize("overrides,ok,closed", [
    (dict(collection_status="ERROR"), False, True),
    (dict(collection_status="CLEANUP_REQUIRED"), False, True),
    (dict(browser_released=False), True, False),
    (dict(browser_released="yes"), True, False),
    (dict(browser_released=None, collection_status=None), False, False),
])
def test_unconfirmed_preconditions_reach_the_service_as_false(tmp_path, overrides, ok, closed):
    service = fake_service()
    hook = InstagramPostCollectionOrchestrator(db_path_provider=lambda: tmp_path / "ti.db",
                                               service_factory=lambda: service)
    hook(event(**overrides))
    kwargs = service.classify_after_collection.call_args.kwargs
    assert (kwargs["collection_ok"], kwargs["browser_closed"]) == (ok, closed)


def test_real_service_skips_without_confirmed_release(tmp_path):
    hook = InstagramPostCollectionOrchestrator(db_path_provider=lambda: tmp_path / "ti.db",
                                               service_factory=TrendPostCollectionService)
    assert hook(event(browser_released=False))["status"] == "SKIPPED"
    assert hook(event(collection_status="BLOCKED"))["status"] == "SKIPPED"
    assert [p.name for p in tmp_path.iterdir()] == ["lockroot"]


def test_crm_hook_resolves_config_db_and_service_lazily(tmp_path, monkeypatch):
    composed = []
    monkeypatch.setattr(post_collection, "TrendPostCollectionService",
                        lambda: composed.append(1) or TrendPostCollectionService())
    hook = create_post_collection_hook()
    assert composed == []
    # The configuration DB path is read at call time, never at construction.
    absent = tmp_path / "absent.db"
    monkeypatch.setattr(config_service, "DB_PATH", absent)
    assert hook(event())["status"] == "NO_STORE"
    hook(event())
    assert composed == [1]
    assert not absent.exists()


def test_crm_control_wires_the_hook_without_touching_database(tmp_path, monkeypatch):
    path = tmp_path / "absent.db"
    monkeypatch.setattr(config_service, "DB_PATH", path)
    control = create_crm_instagram_control()
    assert isinstance(control.after_collection, InstagramPostCollectionOrchestrator)
    assert control.after_collection._service is None
    control.runtime_factory = lambda: pytest.fail("runtime no permitido")
    control.state()
    assert not path.exists()
    assert control.after_collection._service is None


# ------------------------------------------------ end to end (fakes)

def runtime_for(report, order):
    runtime = Mock()
    started = Future()
    started.set_result(None)
    runtime.start.side_effect = lambda: (order.append("start"), started)[1]
    snapshot = SimpleNamespace(status="SUCCESS", result=report)
    type(runtime).snapshot = PropertyMock(side_effect=lambda: (order.append("snapshot"), snapshot)[1])

    def close():
        order.append("close")
        released = Future()
        released.set_result(True)
        return released

    runtime.close.side_effect = close
    return runtime


def test_end_to_end_classifies_only_after_release(tmp_path, monkeypatch):
    db = tmp_path / "ti.db"
    build_store(db)
    ingest(db, [("old", day(0), ["arraigosocial"])])
    report = ingest(db, [("p1", day(1), ["#ArraigoSocial"]), ("p2", day(1), ["otra"])])
    order = []

    def producer_factory(path):
        order.append("classify")
        return create_trend_producer(path)

    hook = InstagramPostCollectionOrchestrator(
        db_path_provider=lambda: db,
        service_factory=lambda: TrendPostCollectionService(producer_factory=producer_factory))
    control = InstagramCollectorControlService(lookup=Mock(get_config=Mock(return_value=None)),
                                               save_setting=Mock(), repository=Mock(),
                                               runtime_factory=lambda: runtime_for(report, order),
                                               after_collection=hook)
    control.configuration = Mock(load=Mock(return_value=InstagramStartupConfiguration("IDLE", domain_code=DOMAIN)))
    control.execute().result(10)

    assert order == ["start", "snapshot", "close", "classify"]
    state = control.state()
    assert state["status"] == "SUCCESS"
    analysis = state["analysis"]
    assert analysis["status"] == "OK"
    result = analysis["result"]
    assert (result["provisional"], result["trend_scoring"], result["run_id"]) == (True, "NOT_COMPUTED",
                                                                                   state["latest"]["id"])
    assert result["run"] == dict(observations=2, classified=1, already_classified=0, unmatched=1,
                                 ambiguous=0, not_reached=0)
    # The historical observation precedes the run: never walked nor attributed.
    assert result["scan"]["processed"] == 2
    assert topic_link(db, report.observation_ids[0]) == [("ARRAIGO", "HASHTAG_EXACT")]
    for table in ("ti_trend_snapshots", "ti_temporal_metrics", "ti_aggregate_signals"):
        assert count(db, table) == 0
    text = json.dumps(analysis)
    assert "instagram.com" not in text and str(tmp_path) not in text


def test_end_to_end_busy_store_keeps_collection_success(tmp_path):
    from backend.trend_intelligence.process_lock import acquire_process_lock
    db = tmp_path / "ti.db"
    build_store(db)
    report = ingest(db, [("p1", day(1), ["arraigosocial"])])
    hook = InstagramPostCollectionOrchestrator(db_path_provider=lambda: db,
                                               service_factory=TrendPostCollectionService)
    control = InstagramCollectorControlService(lookup=Mock(get_config=Mock(return_value=None)),
                                               save_setting=Mock(), repository=Mock(),
                                               runtime_factory=lambda: runtime_for(report, []),
                                               after_collection=hook)
    control.configuration = Mock(load=Mock(return_value=InstagramStartupConfiguration("IDLE", domain_code=DOMAIN)))
    release = acquire_process_lock(db.resolve())
    try:
        control.execute().result(10)
    finally:
        release()
    state = control.state()
    assert (state["status"], state["analysis"]["status"]) == ("SUCCESS", "BUSY")
    assert topic_link(db, report.observation_ids[0]) == []


# --------------------------------------------------------- static

def test_orchestrator_has_no_producer_windows_or_inverse_dependency():
    source = ORCHESTRATOR_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    modules |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert modules == {"backend.services.config_service", "backend.services.trend_post_collection_service"}
    for token in ("producer", "process_window", "snapshot", "pipeline", "sqlite", "selenium", "threading",
                  "instagram_collector_control_service", "importlib", "__import__"):
        assert token not in source.lower(), token
    # Every import is lazy (inside a function): importing the module opens nothing.
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in tree.body)


def test_import_is_inert():
    code = ("import sys, backend.services.instagram_post_collection_orchestrator as o;"
            "bad=[m for m in sys.modules if m.startswith('backend.trend_intelligence') "
            "or m.endswith('trend_post_collection_service') or m.endswith('config_service') "
            "or m.split('.')[0] in ('flet','seleniumbase','selenium','sqlite3','frontend','app')];"
            "print(bad)")
    output = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                            text=True, check=True).stdout.strip()
    assert output == "[]"
    assert orchestrator_module.create_post_collection_hook is create_post_collection_hook
