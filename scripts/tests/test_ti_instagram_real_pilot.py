"""Piloto real Instagram (TI-4C.3E1): solo tmp_path y fakes; sin git, red ni navegador."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sqlite3
from types import SimpleNamespace

import pytest

from backend.automation import browser_session, seleniumbase_browser_session
from backend.automation.browser_profiles import normalize_browser_profile_key
from backend.repositories.instagram_collector_settings_repository import (
    SQLiteInstagramCollectorSettingsRepository,
)
from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceReadOnlyLookup,
    SQLiteTrendIntelligenceRepository,
)
from backend.services.instagram_collector_configuration_service import (
    InstagramCollectorConfigurationService,
)
from backend.services.instagram_collector_control_service import InstagramCollectorControlService
from backend.services.instagram_collector_runtime_service import InstagramCollectorRuntimeService
from backend.trend_intelligence.ingestion import TrendIngestionService
from backend.trend_intelligence.models import TrendDomain, TrendSource
from backend.trend_intelligence.service import TrendIntelligenceService
from backend.trend_intelligence.sources import instagram_browser
from backend.trend_intelligence.sources.instagram import InstagramRawObservation
from backend.trend_intelligence.sources.instagram_browser import InstagramAccessBlockedError
from database.connection import get_readonly_connection


PILOT_PATH = Path("scripts/dev/ti_instagram_real_pilot.py")
SHA = "c" * 40
USERNAME = "sandbox_0a1b2c3d"
ACCOUNT = "cuenta.publica_1"
TOPIC = "MODA_PILOTO"
HASHTAG = "modapiloto"
SECRET_CAPTION = "CAPTION_PRIVADA password=hunter2 cookie=sessionid"


def _load_pilot():
    spec = importlib.util.spec_from_file_location("ti_instagram_real_pilot", PILOT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P = _load_pilot()
FX = P.FX
L = P.L
PLAN = P.Plan(account=ACCOUNT, topic_key=TOPIC, hashtag=HASHTAG)


# ============================================================
# Aislamiento: nada de red, Chrome ni BD fuera de tmp_path
# ============================================================

@pytest.fixture(autouse=True)
def no_browser_no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("navegador/red no permitidos en tests")

    monkeypatch.setattr(browser_session, "start_seleniumbase_chrome", refuse)
    monkeypatch.setattr(seleniumbase_browser_session, "start_seleniumbase_chrome", refuse)
    monkeypatch.setattr(instagram_browser.InstagramBrowserCollector, "start", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture(autouse=True)
def connect_spy(monkeypatch, tmp_path):
    real_connect = sqlite3.connect

    def spy(database, *args, **kwargs):
        text = str(database).replace("\\", "/").lower()
        assert tmp_path.as_posix().lower() in text, text
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spy)


@pytest.fixture(autouse=True)
def no_git(monkeypatch):
    calls = []
    monkeypatch.setattr(L, "_git", lambda *a, **k: pytest.fail("git no permitido"))
    monkeypatch.setattr(L, "run_internal", lambda *a, **k: pytest.fail("sin subprocesos"))
    monkeypatch.setattr(L, "verify_worktree", lambda *a, **k: calls.append(a))
    return calls


# ============================================================
# Sandbox simulado
# ============================================================

def _sandbox_db(tmp_path, *, users=1, ti_schema=True):
    db = tmp_path / "sandbox" / "crm" / "database" / "quesada.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, "
        "password_hash TEXT, is_active INTEGER)"
    )
    for index in range(users):
        conn.execute("INSERT INTO users (username, password_hash, is_active) VALUES (?, 'x', 1)",
                     (f"sandbox_{index:08x}",))
    conn.execute(L.CONFIG_GLOBAL_DDL)
    conn.commit()
    conn.close()
    if ti_schema:
        SQLiteTrendIntelligenceRepository(db).ensure_schema()
    return db


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _settings(db):
    raw = SQLiteTrendIntelligenceReadOnlyLookup(db).get_config(L.COLLECTOR_SETTINGS_KEY)
    return None if raw is None else json.loads(raw)


def _write_settings(db, value):
    SQLiteInstagramCollectorSettingsRepository(db).save(L.COLLECTOR_SETTINGS_KEY, json.dumps(value))


def _count(db, table):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


class FakeCollector:
    """Sustituye al InstagramBrowserCollector real dentro del runtime real."""

    def __init__(self, db, *, behaviour="success", posts=3):
        self.db, self.behaviour, self.posts = db, behaviour, posts
        self.created = []
        self.enabled_seen = []
        self.shutdowns = 0

    def __call__(self, *, profile_key, headless):
        self.created.append((profile_key, headless))
        return self

    def start(self):
        self.enabled_seen.append(_settings(self.db)["enabled"])

    def collect_account(self, account, *, limit):
        assert limit == P.ACCOUNT_LIMIT
        if self.behaviour == "blocked":
            raise InstagramAccessBlockedError(f"login requerido {account} https://www.instagram.com/x/")
        if self.behaviour == "error":
            raise RuntimeError(f"fallo {account} {SECRET_CAPTION}")
        return [
            InstagramRawObservation(
                source_account=account, external_id=f"SHORT{index}",
                canonical_url=f"https://www.instagram.com/p/SHORT{index}/",
                content_type="POST", observed_at="2026-10-17T10:00:00+00:00",
                caption=f"{SECRET_CAPTION} #{HASHTAG}",
            )
            for index in range(min(self.posts, limit))
        ]

    def shutdown(self):
        self.shutdowns += 1
        if self.behaviour == "cleanup":
            raise RuntimeError("no libera")
        return None


def _services(db, collector=None):
    def runtime_factory():
        return InstagramCollectorRuntimeService(
            configuration_service=InstagramCollectorConfigurationService(
                SQLiteTrendIntelligenceReadOnlyLookup(db)),
            ingestion_service=TrendIngestionService(
                TrendIntelligenceService(SQLiteTrendIntelligenceRepository(db))),
            collector_factory=collector or (lambda **k: pytest.fail("sin recogida")),
        )

    factory_calls = []

    def counted_factory():
        factory_calls.append(1)
        return runtime_factory()

    services = P.Services(
        trend_service=TrendIntelligenceService,
        repository=SQLiteTrendIntelligenceRepository,
        settings_repository=SQLiteInstagramCollectorSettingsRepository,
        readonly_lookup=SQLiteTrendIntelligenceReadOnlyLookup,
        readonly_connection=get_readonly_connection,
        source_model=TrendSource,
        domain_model=TrendDomain,
        configuration_service=InstagramCollectorConfigurationService,
        control_service=InstagramCollectorControlService,
        runtime_factory=counted_factory,
        normalize_profile_key=normalize_browser_profile_key,
    )
    return services, factory_calls


@pytest.fixture
def sandbox(tmp_path):
    db = _sandbox_db(tmp_path)
    dest = db.parents[2]
    profiles = tmp_path / "profiles"
    target = FX.Target(dest=dest, worktree=dest / "crm", sha=SHA, db_path=db, username=USERNAME)
    return SimpleNamespace(db=db, dest=dest, profiles=profiles, target=target)


def _configure(sandbox, services, plan=PLAN, **kwargs):
    return P.configure(sandbox.target, services, plan, profiles=sandbox.profiles, **kwargs)


def _collect(sandbox, services, **kwargs):
    kwargs.setdefault("ack", True)
    return P.collect(sandbox.target, services, profiles=sandbox.profiles, **kwargs)


# ============================================================
# Plan y settings
# ============================================================

def test_plan_normalizes_single_public_account():
    assert P.build_plan(["@Cuenta.Publica_1"], " moda_piloto ", "#ModaPiloto") == PLAN


@pytest.mark.parametrize("accounts, code", [
    ([], "ACCOUNT_EXACTLY_ONE_REQUIRED"),
    (None, "ACCOUNT_EXACTLY_ONE_REQUIRED"),
    (["uno", "dos"], "ACCOUNT_EXACTLY_ONE_REQUIRED"),
    (["uno,dos"], "ACCOUNT_INVALID"),
    (["uno dos"], "ACCOUNT_INVALID"),
    ([".empieza"], "ACCOUNT_INVALID"),
    (["acaba."], "ACCOUNT_INVALID"),
    (["do..ble"], "ACCOUNT_INVALID"),
    (["a" * 31], "ACCOUNT_INVALID"),
    (["https://www.instagram.com/x"], "ACCOUNT_INVALID"),
])
def test_plan_rejects_invalid_or_multiple_accounts(accounts, code):
    with pytest.raises(L.SandboxError, match=code):
        P.build_plan(accounts, TOPIC, HASHTAG)


@pytest.mark.parametrize("topic, hashtag, code", [
    ("", HASHTAG, "TOPIC_KEY_INVALID"),
    ("1MODA", HASHTAG, "TOPIC_KEY_INVALID"),
    ("MODA-X", HASHTAG, "TOPIC_KEY_INVALID"),
    (TOPIC, "", "HASHTAG_INVALID"),
    (TOPIC, "#1234", "HASHTAG_INVALID"),
    (TOPIC, "moda piloto", "HASHTAG_INVALID"),
])
def test_plan_rejects_invalid_topic_or_hashtag(topic, hashtag, code):
    with pytest.raises(L.SandboxError, match=code):
        P.build_plan([ACCOUNT], topic, hashtag)


KEY = "it_pilot_ig_0123456789abcdef"


def _tampered(**changes):
    value = P.build_settings(PLAN, KEY)
    value.update(changes)
    return json.dumps(value)


@pytest.mark.parametrize("raw, code", [
    ("{no json", "JSON"),
    (_tampered(extra=1), "KEYS"),
    (_tampered(pilot=dict(marker="SYNTHETIC_SANDBOX")), "NOT_PILOT"),
    (_tampered(accounts=[dict(account="a", limit=5), dict(account="b", limit=5)]), "ACCOUNTS"),
    (_tampered(accounts=[dict(account=ACCOUNT, limit=6)]), "LIMIT"),
    (_tampered(accounts=[dict(account=ACCOUNT, limit=5.0)]), "LIMIT"),
    (_tampered(enabled="false"), "ENABLED"),
    (_tampered(profile_key="instagram_main"), "PROFILE_KEY"),
    (_tampered(profile_key="it_instagram_collector"), "PROFILE_KEY"),
    (_tampered(headless=True), "MISMATCH"),
    (_tampered(source_code="OTRA_FUENTE"), "MISMATCH"),
    (_tampered(domain_code="SANDBOX_MARKETING"), "MISMATCH"),
    (_tampered(accounts=[dict(account=ACCOUNT, limit=5, password="x")]), "MISMATCH"),
])
def test_settings_must_be_exact_pilot_configuration(raw, code):
    with pytest.raises(L.SandboxError, match=f"SETTINGS_INVALID:{code}"):
        P.parse_settings(raw, normalize_profile_key=normalize_browser_profile_key)


def test_settings_roundtrip():
    raw = json.dumps(P.build_settings(PLAN, KEY, enabled=True))
    assert P.parse_settings(raw, normalize_profile_key=normalize_browser_profile_key) == (PLAN, KEY, True)


# ============================================================
# Barreras de destino, sello, checkout y BD
# ============================================================

def test_must_run_from_sealed_checkout_never_from_repository(tmp_path):
    with pytest.raises(L.SandboxError, match="NOT_RUNNING_FROM_SEALED_CHECKOUT"):
        P.validate(str(tmp_path / "sandbox"), repo_root=P.REPO_ROOT, cwd=P.REPO_ROOT)


def test_real_repository_as_dest_is_refused():
    with pytest.raises(L.SandboxError):
        P.validate(str(P.REPO_ROOT.parent), repo_root=P.REPO_ROOT, cwd=P.REPO_ROOT)


def test_cwd_must_be_sealed_checkout(tmp_path):
    dest = tmp_path / "sandbox"
    with pytest.raises(L.SandboxError, match="CWD_NOT_SEALED_CHECKOUT"):
        P.validate(str(dest), repo_root=dest / "crm", cwd=tmp_path)


def test_relative_dest_refused():
    with pytest.raises(L.SandboxError, match="DEST_NOT_ABSOLUTE"):
        P.validate("relativo/sandbox")


class TestRealLauncherBarriers:
    """validate_launch real con TEMP y checkouts simulados (sin git)."""

    @pytest.fixture(autouse=True)
    def fake_environment(self, monkeypatch, tmp_path):
        self.temp = tmp_path / "temp"
        self.temp.mkdir()
        self.checkouts = []
        monkeypatch.setattr(L, "temp_root", lambda: self.temp.resolve())
        monkeypatch.setattr(L, "list_checkouts", lambda repo_root: list(self.checkouts))

    def _validate(self, dest):
        worktree = dest / "crm"
        return P.validate(str(dest), repo_root=worktree, cwd=worktree)

    def _dest(self):
        dest = self.temp / "sb"
        (dest / "crm").mkdir(parents=True)
        return dest

    def test_outside_temp(self, tmp_path):
        with pytest.raises(L.SandboxError, match="DEST_OUTSIDE_TEMP"):
            self._validate(tmp_path / "fuera")

    def test_link_or_reparse_point(self, monkeypatch):
        dest = self._dest()
        monkeypatch.setattr(L, "_is_link_or_reparse",
                            lambda path: Path(path).name == "sb")
        with pytest.raises(L.SandboxError, match="DEST_LINK_OR_REPARSE"):
            self._validate(dest)

    def test_other_worktree_overlap(self):
        dest = self._dest()
        self.checkouts.append(self.temp)
        with pytest.raises(L.SandboxError, match="DEST_OVERLAPS_CHECKOUT"):
            self._validate(dest)

    def test_missing_seal(self):
        with pytest.raises(L.SandboxError, match="SEAL_MISSING"):
            self._validate(self._dest())

    @pytest.mark.parametrize("change", [
        dict(db_path="C:/despacho/quesada.db"),
        dict(kind="OTRO"),
        dict(sha="no-sha"),
        dict(worktree="C:/repo"),
    ])
    def test_altered_seal(self, change):
        dest = self._dest()
        seal = dict(kind=L.SEAL_KIND, version=L.SEAL_VERSION, dest=str(dest),
                    worktree=str(dest / "crm"), db_path=str(dest / "crm" / L.DB_RELATIVE), sha=SHA)
        seal.update(change)
        (dest / L.SEAL_NAME).write_text(json.dumps(seal), encoding="utf-8")
        with pytest.raises(L.SandboxError, match="SEAL_MISMATCH"):
            self._validate(dest)


def test_import_services_requires_sealed_db_paths(monkeypatch, tmp_path):
    db = tmp_path / "crm" / "database" / "quesada.db"
    target = FX.Target(dest=tmp_path, worktree=tmp_path / "crm", sha=SHA, db_path=db, username=USERNAME)
    loaded = {name: SimpleNamespace() for name in P.MODULES}
    loaded["database.connection"].DB_PATH = str(db)
    loaded["backend.repositories.sqlite_trend_intelligence_repository"].DEFAULT_DB_PATH = db
    loaded["backend.services.config_service"].DB_PATH = tmp_path / "despacho" / "quesada.db"
    monkeypatch.setattr(L, "_import_from_worktree", lambda root, modules: (root, loaded))
    with pytest.raises(L.SandboxError, match="EFFECTIVE_DB_PATH_MISMATCH"):
        P.import_services(target)


def test_import_services_rejects_foreign_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    target = FX.Target(dest=tmp_path, worktree=P.REPO_ROOT, sha=SHA,
                       db_path=tmp_path / "quesada.db", username=USERNAME)
    with pytest.raises(L.SandboxError, match="INTERNAL_CWD_MISMATCH"):
        P.import_services(target)


def test_fresh_sandbox_is_accepted(sandbox):
    services, _ = _services(sandbox.db)
    state = P.check_state(services, sandbox.db)
    assert state["settings"] is None and not state["catalog_complete"]
    assert set(state["counts"].values()) == {0}


def test_incomplete_schema_refused(tmp_path):
    db = _sandbox_db(tmp_path, ti_schema=False)
    services, _ = _services(db)
    with pytest.raises(L.SandboxError, match="DB_SCHEMA_INCOMPLETE"):
        P.check_state(services, db)


def test_more_than_one_user_refused(tmp_path):
    db = _sandbox_db(tmp_path, users=2)
    services, _ = _services(db)
    with pytest.raises(L.SandboxError, match="DB_NOT_SANDBOX:USERS"):
        P.check_state(services, db)


def test_seeded_synthetic_sandbox_is_never_converted(sandbox):
    fixture_services = FX.Services(
        trend_service=TrendIntelligenceService, repository=SQLiteTrendIntelligenceRepository,
        settings_repository=SQLiteInstagramCollectorSettingsRepository,
        readonly_lookup=SQLiteTrendIntelligenceReadOnlyLookup,
    )
    from datetime import date
    FX.seed(fixture_services, sandbox.db, today=date(2026, 10, 16))
    before = _digest(sandbox.db)
    services, factory = _services(sandbox.db)
    with pytest.raises(L.SandboxError, match="COLLECTOR_SETTINGS_FOREIGN"):
        _configure(sandbox, services)
    with pytest.raises(L.SandboxError, match="ATTEMPT|COLLECTOR_SETTINGS_FOREIGN"):
        _collect(sandbox, services)
    assert _digest(sandbox.db) == before and factory == []
    assert not os.path.lexists(sandbox.dest / P.ATTEMPT_NAME)


def test_foreign_domain_refused_without_writes(sandbox):
    TrendIntelligenceService(SQLiteTrendIntelligenceRepository(sandbox.db)).create_domain(
        code="EXTRANJERIA", name="Despacho")
    before = _digest(sandbox.db)
    services, _ = _services(sandbox.db)
    with pytest.raises(L.SandboxError, match="FOREIGN_DOMAIN_PRESENT"):
        _configure(sandbox, services)
    assert _digest(sandbox.db) == before


@pytest.mark.parametrize("changes", [
    dict(provider="youtube"),
    dict(base_url="https://instagram.example.com/"),
    dict(collection_mode="API"),
    dict(source_type="NEWS"),
    dict(configuration=None),
])
def test_pilot_source_not_matching_refused(sandbox, changes):
    values = dict(code=P.SOURCE_CODE, name="x", source_type="SOCIAL", provider="instagram",
                  base_url=P.SOURCE_BASE_URL, collection_mode="SELENIUM", configuration=dict(P.METADATA))
    values.update(changes)
    TrendIntelligenceService(SQLiteTrendIntelligenceRepository(sandbox.db)).create_source(**values)
    services, _ = _services(sandbox.db)
    with pytest.raises(L.SandboxError, match="SOURCE_NOT_PILOT"):
        _configure(sandbox, services)


def test_unmarked_pilot_domain_refused(sandbox):
    TrendIntelligenceService(SQLiteTrendIntelligenceRepository(sandbox.db)).create_domain(
        code=P.DOMAIN_CODE, name="Sin marca")
    services, _ = _services(sandbox.db)
    with pytest.raises(L.SandboxError, match="DOMAIN_NOT_PILOT"):
        _configure(sandbox, services)


def test_foreign_source_refused(sandbox):
    TrendIntelligenceService(SQLiteTrendIntelligenceRepository(sandbox.db)).create_source(
        code="RSS_DESPACHO", name="x", source_type="NEWS")
    services, _ = _services(sandbox.db)
    with pytest.raises(L.SandboxError, match="FOREIGN_SOURCE_PRESENT"):
        _configure(sandbox, services)


# ============================================================
# --configure
# ============================================================

def test_configure_writes_catalog_and_disabled_settings_without_collecting(sandbox, no_git):
    collector = FakeCollector(sandbox.db)
    services, factory = _services(sandbox.db, collector)
    result = _configure(sandbox, services)
    assert result == dict(status="CONFIGURED", settings_written=True,
                          collector_enabled=False, catalog_complete=True)
    settings = _settings(sandbox.db)
    assert settings["enabled"] is False and settings["headless"] is False
    assert settings["accounts"] == [dict(account=ACCOUNT, limit=5)]
    assert settings["domain_code"] == P.DOMAIN_CODE and settings["source_code"] == P.SOURCE_CODE
    assert P.PROFILE_KEY_PATTERN.fullmatch(settings["profile_key"])
    assert settings["pilot"] == dict(marker="REAL_PILOT", work_order=P.WORK_ORDER,
                                     topic_key=TOPIC, hashtag=HASHTAG)
    assert not any(k in json.dumps(settings).lower() for k in ("password", "cookie", "token"))

    repository = SQLiteTrendIntelligenceRepository(sandbox.db, readonly=True)
    source = repository.get_source_by_code(P.SOURCE_CODE)
    assert (source.source_type, source.collection_mode, source.provider, source.base_url) == (
        "SOCIAL", "SELENIUM", "instagram", "https://www.instagram.com/")
    assert repository.get_domain_by_code(P.DOMAIN_CODE).metadata["marker"] == "REAL_PILOT"
    topic = repository.get_topic_by_key(TOPIC)
    assert [a.alias_text for a in repository.list_topic_aliases(topic.id)] == [HASHTAG]

    # Sin ejecución, navegador, perfil creado ni intento consumido.
    assert factory == [] and collector.created == []
    assert not os.path.lexists(sandbox.profiles)
    assert not os.path.lexists(sandbox.dest / P.ATTEMPT_NAME)
    assert not os.path.lexists(sandbox.dest / P.LOCK_NAME)
    assert _count(sandbox.db, "ti_observations") == 0
    assert len(no_git) == 1


def test_configured_settings_satisfy_real_collector_contract(sandbox):
    services, _ = _services(sandbox.db)
    _configure(sandbox, services)
    startup = InstagramCollectorConfigurationService(SQLiteTrendIntelligenceReadOnlyLookup(sandbox.db)).load()
    assert startup.status == "DISABLED"


def test_configure_is_idempotent(sandbox):
    services, _ = _services(sandbox.db)
    _configure(sandbox, services)
    settings, before = _settings(sandbox.db), _digest(sandbox.db)
    assert _configure(sandbox, services)["status"] == "ALREADY_CONFIGURED"
    assert _settings(sandbox.db) == settings and _digest(sandbox.db) == before


@pytest.mark.parametrize("plan", [
    P.Plan(account="otra_cuenta", topic_key=TOPIC, hashtag=HASHTAG),
    P.Plan(account=ACCOUNT, topic_key="OTRO_TOPIC", hashtag=HASHTAG),
    P.Plan(account=ACCOUNT, topic_key=TOPIC, hashtag="otrotag"),
])
def test_configure_never_rewrites_a_different_plan(sandbox, plan):
    services, _ = _services(sandbox.db)
    _configure(sandbox, services)
    before = _digest(sandbox.db)
    with pytest.raises(L.SandboxError, match="CONFIG_MISMATCH"):
        _configure(sandbox, services, plan)
    assert _digest(sandbox.db) == before


def test_profile_key_avoids_existing_profiles(sandbox):
    taken = "it_pilot_ig_" + "a" * 16
    (sandbox.profiles / taken).mkdir(parents=True)
    tokens = iter(["a" * 16, "b" * 16])
    services, _ = _services(sandbox.db)
    _configure(sandbox, services, token=lambda n: next(tokens))
    assert _settings(sandbox.db)["profile_key"] == "it_pilot_ig_" + "b" * 16
    assert sorted(p.name for p in sandbox.profiles.iterdir()) == [taken]


def test_profile_key_collision_blocks_before_writing(sandbox):
    (sandbox.profiles / ("it_pilot_ig_" + "a" * 16)).mkdir(parents=True)
    before = _digest(sandbox.db)
    services, _ = _services(sandbox.db)
    with pytest.raises(L.SandboxError, match="PROFILE_KEY_COLLISION"):
        _configure(sandbox, services, token=lambda n: "a" * 16)
    assert _digest(sandbox.db) == before
    assert not os.path.lexists(sandbox.dest / P.LOCK_NAME)


def test_profiles_root_link_refused(sandbox, monkeypatch):
    sandbox.profiles.mkdir()
    monkeypatch.setattr(L, "_is_link_or_reparse", lambda path: Path(path) == sandbox.profiles)
    services, _ = _services(sandbox.db)
    with pytest.raises(L.SandboxError, match="PROFILES_ROOT_LINK_OR_REPARSE"):
        _configure(sandbox, services)
    assert _settings(sandbox.db) is None


def test_configure_refused_once_attempt_used(sandbox):
    services, _ = _services(sandbox.db)
    (sandbox.dest / P.ATTEMPT_NAME).write_text("{}", encoding="utf-8")
    with pytest.raises(L.SandboxError, match="ATTEMPT_ALREADY_USED"):
        _configure(sandbox, services)
    assert _settings(sandbox.db) is None


def test_profile_root_matches_existing_runtime():
    source = Path(instagram_browser.__file__).read_text(encoding="utf-8")
    assert f'"{P.PROFILES_DIRNAME}"' in source


# ============================================================
# --collect
# ============================================================

def _configured(sandbox, behaviour="success", posts=3):
    collector = FakeCollector(sandbox.db, behaviour=behaviour, posts=posts)
    services, factory = _services(sandbox.db, collector)
    _configure(sandbox, services)
    return services, factory, collector


def test_collect_requires_ack_before_anything(sandbox):
    services, factory, collector = _configured(sandbox)
    before = _digest(sandbox.db)
    for ack in (False, None, "yes"):
        with pytest.raises(L.SandboxError, match="ACK_REAL_WEB_READ_REQUIRED"):
            _collect(sandbox, services, ack=ack)
    assert factory == [] and collector.created == [] and _digest(sandbox.db) == before
    assert not os.path.lexists(sandbox.dest / P.ATTEMPT_NAME)


def test_collect_requires_configuration(sandbox):
    services, factory = _services(sandbox.db)
    with pytest.raises(L.SandboxError, match="NOT_CONFIGURED"):
        _collect(sandbox, services)
    assert factory == [] and not os.path.lexists(sandbox.dest / P.ATTEMPT_NAME)


def test_collect_success_single_shot_and_disarmed(sandbox, no_git):
    services, factory, collector = _configured(sandbox)
    baseline = _settings(sandbox.db)
    result = _collect(sandbox, services)
    assert result["status"] == "SUCCESS"
    assert (result["created"], result["duplicates"], result["total"]) == (3, 0, 3)
    assert result["collector_enabled"] is False and result["cleanup"] == "NOT_REQUIRED"
    assert result["producer_not_before_utc"] is not None
    assert factory == [1]
    assert collector.created == [(baseline["profile_key"], False)]
    assert collector.enabled_seen == [True] and collector.shutdowns >= 1
    assert _settings(sandbox.db) == baseline
    assert _count(sandbox.db, "ti_observations") == 3
    assert _count(sandbox.db, "ti_observation_domains") == 3
    for table in ("ti_signals", "ti_trend_snapshots", "ti_trends", "ti_collector_runs"):
        assert _count(sandbox.db, table) == 0  # sin productor ni scheduler
    assert os.path.lexists(sandbox.dest / P.ATTEMPT_NAME)
    assert not os.path.lexists(sandbox.dest / P.LOCK_NAME)
    assert P.read_result(sandbox.dest)["status"] == "SUCCESS"
    text = json.dumps(result) + (sandbox.dest / P.RESULT_NAME).read_text(encoding="utf-8") \
        + (sandbox.dest / P.ATTEMPT_NAME).read_text(encoding="utf-8")
    for secret in ("hunter2", "sessionid", "CAPTION", "instagram.com/p", ACCOUNT, baseline["profile_key"]):
        assert secret not in text

    # Nunca una segunda ejecución sobre el mismo DEST.
    with pytest.raises(L.SandboxError, match="ATTEMPT_ALREADY_USED"):
        _collect(sandbox, services)
    assert factory == [1]


def test_collect_limit_never_exceeds_five(sandbox):
    # El fake afirma limit == 5 y lo respeta como el collector real.
    services, factory, collector = _configured(sandbox, posts=9)
    result = _collect(sandbox, services)
    assert (result["status"], result["created"]) == ("SUCCESS", 5)
    assert _count(sandbox.db, "ti_observations") == 5


@pytest.mark.parametrize("behaviour, expected", [("blocked", "BLOCKED"), ("error", "ERROR")])
def test_blocked_or_error_disarms_and_never_retries(sandbox, behaviour, expected):
    services, factory, collector = _configured(sandbox, behaviour)
    baseline = _settings(sandbox.db)
    result = _collect(sandbox, services)
    assert result["status"] == expected and result["collector_enabled"] is False
    assert result["producer_not_before_utc"] is None
    assert factory == [1] and len(collector.created) == 1
    assert _settings(sandbox.db) == baseline
    assert _count(sandbox.db, "ti_observations") == 0
    assert "hunter2" not in json.dumps(result) and ACCOUNT not in json.dumps(result)
    with pytest.raises(L.SandboxError, match="ATTEMPT_ALREADY_USED"):
        _collect(sandbox, services)
    assert factory == [1]


def test_cleanup_required_is_reported_and_disarmed(sandbox):
    services, factory, collector = _configured(sandbox, "cleanup")
    result = _collect(sandbox, services)
    assert result["status"] == "CLEANUP_REQUIRED"
    assert result["cleanup"] == "CLEANUP_REQUIRED"
    assert result["collector_enabled"] is False
    assert collector.shutdowns >= 2  # cierre del runtime + close()/retry_cleanup


def test_crash_during_execution_disarms_and_consumes_attempt(sandbox, monkeypatch):
    services, factory, collector = _configured(sandbox)
    baseline = _settings(sandbox.db)

    def crash(self):
        assert _settings(sandbox.db)["enabled"] is True
        raise KeyboardInterrupt

    monkeypatch.setattr(InstagramCollectorControlService, "execute", crash)
    result = _collect(sandbox, services)
    assert result["status"] == "INTERRUPTED" and result["collector_enabled"] is False
    assert _settings(sandbox.db) == baseline
    monkeypatch.undo()
    with pytest.raises(L.SandboxError, match="ATTEMPT_ALREADY_USED"):
        _collect(sandbox, services)
    assert factory == []


def test_unexpected_exception_disarms(sandbox, monkeypatch):
    services, factory, collector = _configured(sandbox)
    monkeypatch.setattr(InstagramCollectorControlService, "execute",
                        lambda self: (_ for _ in ()).throw(OSError(SECRET_CAPTION)))
    result = _collect(sandbox, services)
    assert result["status"] == "ERROR" and result["error"] == "UNEXPECTED:OSError"
    assert result["collector_enabled"] is False and _settings(sandbox.db)["enabled"] is False


def test_abrupt_termination_leaves_marker_and_disarm_recovers(sandbox):
    services, factory, collector = _configured(sandbox)
    # Simula un proceso muerto tras armar: marcador presente y enabled=true.
    (sandbox.dest / P.ATTEMPT_NAME).write_text("{}", encoding="utf-8")
    _write_settings(sandbox.db, dict(_settings(sandbox.db), enabled=True))
    with pytest.raises(L.SandboxError, match="ATTEMPT_ALREADY_USED"):
        _collect(sandbox, services)
    assert P.status(sandbox.target, services)["status"] == "ARMED"
    assert P.disarm(sandbox.target, services) == dict(status="DISARMED", collector_enabled=False)
    assert _settings(sandbox.db)["enabled"] is False
    assert P.disarm(sandbox.target, services)["status"] == "DISARMED"
    assert factory == [] and collector.created == []


def test_preexisting_enabled_true_blocks_collect(sandbox):
    services, factory, _ = _configured(sandbox)
    _write_settings(sandbox.db, dict(_settings(sandbox.db), enabled=True))
    with pytest.raises(L.SandboxError, match="ARMED_STATE_UNEXPECTED"):
        _collect(sandbox, services)
    assert factory == [] and not os.path.lexists(sandbox.dest / P.ATTEMPT_NAME)


@pytest.mark.parametrize("changes", [
    dict(accounts=[dict(account=ACCOUNT, limit=5), dict(account="otra", limit=5)]),
    dict(accounts=[dict(account=ACCOUNT, limit=50)]),
    dict(headless=True),
    dict(source_code="OTRA"),
])
def test_tampered_settings_block_collect(sandbox, changes):
    services, factory, _ = _configured(sandbox)
    _write_settings(sandbox.db, dict(_settings(sandbox.db), **changes))
    with pytest.raises(L.SandboxError, match="COLLECTOR_SETTINGS_FOREIGN"):
        _collect(sandbox, services)
    assert factory == [] and not os.path.lexists(sandbox.dest / P.ATTEMPT_NAME)


def test_disarm_refuses_foreign_settings(sandbox):
    services, _ = _services(sandbox.db)
    _write_settings(sandbox.db, dict(enabled=True, source_code="X"))
    with pytest.raises(L.SandboxError, match="SETTINGS_INVALID"):
        P.disarm(sandbox.target, services)
    assert _settings(sandbox.db) == dict(enabled=True, source_code="X")


def test_existing_observations_block_collect(sandbox):
    services, factory, _ = _configured(sandbox)
    TrendIntelligenceService(SQLiteTrendIntelligenceRepository(sandbox.db)).record_observation(
        source_code=P.SOURCE_CODE, observation_type="POST", external_id="x",
        body_text="x", observed_at="2026-10-10T00:00:00+00:00")
    with pytest.raises(L.SandboxError, match="DB_NOT_EMPTY:ti_observations"):
        _collect(sandbox, services)
    assert factory == []


def test_concurrent_instance_lock(sandbox):
    services, factory, _ = _configured(sandbox)
    (sandbox.dest / P.LOCK_NAME).write_text("{}", encoding="utf-8")
    with pytest.raises(L.SandboxError, match="PILOT_LOCKED"):
        _collect(sandbox, services)
    with pytest.raises(L.SandboxError, match="PILOT_LOCKED"):
        _configure(sandbox, services)
    assert factory == [] and not os.path.lexists(sandbox.dest / P.ATTEMPT_NAME)
    assert os.path.lexists(sandbox.dest / P.LOCK_NAME)


def test_profile_link_blocks_collect(sandbox, monkeypatch):
    services, factory, _ = _configured(sandbox)
    key = _settings(sandbox.db)["profile_key"]
    (sandbox.profiles / key).mkdir(parents=True)
    monkeypatch.setattr(L, "_is_link_or_reparse", lambda path: Path(path).name == key)
    with pytest.raises(L.SandboxError, match="PROFILE_LINK_OR_INVALID"):
        _collect(sandbox, services)
    assert factory == []


def test_disarm_failure_is_reported(sandbox, monkeypatch):
    services, factory, _ = _configured(sandbox)
    real_save = SQLiteInstagramCollectorSettingsRepository.save

    def save(self, key, value):
        if json.loads(value)["enabled"] is False:
            raise sqlite3.OperationalError("disk I/O error")
        return real_save(self, key, value)

    monkeypatch.setattr(SQLiteInstagramCollectorSettingsRepository, "save", save)
    result = _collect(sandbox, services)
    assert result["status"] == "DISARM_FAILED" and result["collector_enabled"] is True


# ============================================================
# Estado y CLI
# ============================================================

def test_status_is_read_only_and_redacted(sandbox):
    services, factory, _ = _configured(sandbox)
    before = _digest(sandbox.db)
    report = P.status(sandbox.target, services)
    assert report["status"] == "CONFIGURED" and report["collector_enabled"] is False
    assert report["attempt_used"] is False and report["last_result"] is None
    text = json.dumps(report)
    assert ACCOUNT not in text and _settings(sandbox.db)["profile_key"] not in text
    assert _digest(sandbox.db) == before and factory == []


@pytest.fixture
def cli(monkeypatch, sandbox):
    collector = FakeCollector(sandbox.db)
    services, factory = _services(sandbox.db, collector)
    validated = []

    def validate(dest, *, repo_root, cwd):
        validated.append(dest)
        return sandbox.target

    monkeypatch.setattr(P, "validate", validate)
    monkeypatch.setattr(P, "import_services", lambda target: services)
    monkeypatch.setattr(P, "profiles_root", lambda: sandbox.profiles)
    return SimpleNamespace(factory=factory, collector=collector, validated=validated)


def _main(capsys, *argv):
    code = P.main(["--dest", "X", *argv])
    out = capsys.readouterr().out
    return code, json.loads(out), out


def test_cli_full_flow(cli, capsys, sandbox):
    code, report, _ = _main(capsys)
    assert (code, report["status"], report["mode"]) == (0, "NOT_CONFIGURED", "STATUS")

    code, report, _ = _main(capsys, "--configure", "--account", ACCOUNT,
                            "--topic-key", TOPIC, "--hashtag", HASHTAG)
    assert (code, report["status"], report["collector_enabled"]) == (0, "CONFIGURED", False)
    assert cli.factory == []  # --configure nunca ejecuta

    code, report, out = _main(capsys, "--collect", "--ack-real-web-read")
    assert (code, report["status"], report["collector_enabled"]) == (0, "SUCCESS", False)
    assert report["producer_run"] == "NOT_EXECUTED" and report["created"] == 3
    for secret in ("hunter2", "sessionid", ACCOUNT, "instagram.com/p", str(sandbox.dest)):
        assert secret not in out

    code, report, _ = _main(capsys, "--collect", "--ack-real-web-read")
    assert (code, report["status"], report["error"]) == (2, "BLOCKED", "ATTEMPT_ALREADY_USED")
    assert cli.factory == [1]

    code, report, _ = _main(capsys)
    assert report["attempt_used"] is True and report["last_result"]["status"] == "SUCCESS"


@pytest.mark.parametrize("argv, error", [
    (("--collect",), "ACK_REAL_WEB_READ_REQUIRED"),
    (("--ack-real-web-read",), "ACK_ONLY_WITH_COLLECT"),
    (("--collect", "--ack-real-web-read", "--account", ACCOUNT), "CONFIGURE_ARGUMENTS_ONLY_WITH_CONFIGURE"),
    (("--configure", "--account", "a", "--account", "b", "--topic-key", TOPIC, "--hashtag", HASHTAG),
     "ACCOUNT_EXACTLY_ONE_REQUIRED"),
    (("--configure", "--account", ACCOUNT, "--topic-key", TOPIC), "HASHTAG_INVALID"),
])
def test_cli_rejects_before_validation(cli, capsys, sandbox, argv, error):
    before = _digest(sandbox.db)
    code, report, _ = _main(capsys, *argv)
    assert (code, report["status"], report["error"]) == (2, "BLOCKED", error)
    assert cli.validated == [] and cli.factory == [] and _digest(sandbox.db) == before


def test_cli_dest_required(capsys):
    code = P.main([])
    report = json.loads(capsys.readouterr().out)
    assert (code, report["error"]) == (2, "DEST_REQUIRED")


def test_cli_modes_mutually_exclusive(capsys):
    with pytest.raises(SystemExit):
        P.main(["--dest", "X", "--configure", "--collect"])


def test_cli_unexpected_errors_are_redacted(cli, capsys, monkeypatch):
    monkeypatch.setattr(P, "status", lambda *a: (_ for _ in ()).throw(
        RuntimeError(f"C:/Users/x {SECRET_CAPTION}")))
    code, report, out = _main(capsys)
    assert (code, report["error"]) == (2, "UNEXPECTED:RuntimeError")
    assert "hunter2" not in out


def test_cli_blocked_collect_exit_code(monkeypatch, capsys, sandbox):
    collector = FakeCollector(sandbox.db, behaviour="blocked")
    services, factory = _services(sandbox.db, collector)
    monkeypatch.setattr(P, "validate", lambda dest, **k: sandbox.target)
    monkeypatch.setattr(P, "import_services", lambda target: services)
    monkeypatch.setattr(P, "profiles_root", lambda: sandbox.profiles)
    _main(capsys, "--configure", "--account", ACCOUNT, "--topic-key", TOPIC, "--hashtag", HASHTAG)
    code, report, out = _main(capsys, "--collect", "--ack-real-web-read")
    assert (code, report["status"], report["collector_enabled"]) == (1, "BLOCKED", False)
    assert ACCOUNT not in out


def test_redacted_logging_drops_messages():
    import logging
    record = logging.LogRecord("x", logging.ERROR, __file__, 1, f"msg {ACCOUNT}", None, None)
    assert ACCOUNT not in P._RedactingFormatter().format(record)


def test_cli_source_has_no_forbidden_surfaces():
    source = PILOT_PATH.read_text(encoding="utf-8")
    for forbidden in ("set_config", "import seleniumbase", "webdriver", "TrendProducer",
                      "ensure_schema", "subprocess", "get_browser_profile_dir", "load_dotenv",
                      "add_cookie", "get_cookies"):
        assert forbidden not in source, forbidden
