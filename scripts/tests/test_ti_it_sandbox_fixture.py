"""Fixture sintética IT del sandbox: solo tmp_path, sin git, red ni navegador reales."""
import ast
from datetime import date, datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from backend.repositories.sqlite_trend_intelligence_repository import (
    ReadOnlyStoreUnavailable,
    SQLiteTrendIntelligenceReadOnlyLookup,
    SQLiteTrendIntelligenceRepository,
)
from backend.repositories.instagram_collector_settings_repository import (
    SQLiteInstagramCollectorSettingsRepository,
)
from backend.trend_intelligence.acquisition.models import CollectorRun
from backend.trend_intelligence.service import TrendIntelligenceService


FIXTURE_PATH = Path("scripts/dev/ti_it_sandbox_fixture.py")
SHA = "b" * 40
TODAY = date(2026, 10, 16)
USERNAME = "sandbox_0a1b2c3d"


def _load_fixture():
    spec = importlib.util.spec_from_file_location("ti_it_sandbox_fixture", FIXTURE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


F = _load_fixture()
L = F.L

SERVICES = F.Services(
    trend_service=TrendIntelligenceService,
    repository=SQLiteTrendIntelligenceRepository,
    settings_repository=SQLiteInstagramCollectorSettingsRepository,
    readonly_lookup=SQLiteTrendIntelligenceReadOnlyLookup,
)


@pytest.fixture
def connect_spy(monkeypatch, tmp_path):
    """Todo sqlite3.connect debe apuntar dentro de tmp_path."""
    real_connect = sqlite3.connect
    targets = []

    def spy(database, *args, **kwargs):
        text = str(database).replace("\\", "/").lower()
        targets.append(text)
        assert tmp_path.as_posix().lower() in text, text
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spy)
    return targets


def _synthetic_db(tmp_path, *, users=1, ti_schema=True):
    """Imitación mínima de la BD del launcher: users, config_global e IT."""
    db = tmp_path / "sandbox" / "crm" / "database" / "quesada.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, "
        "password_hash TEXT, is_active INTEGER)"
    )
    for index in range(users):
        conn.execute(
            "INSERT INTO users (username, password_hash, is_active) VALUES (?, 'x', 1)",
            (f"sandbox_{index:08x}",),
        )
    conn.execute(L.CONFIG_GLOBAL_DDL)
    conn.commit()
    conn.close()
    if ti_schema:
        SQLiteTrendIntelligenceRepository(db).ensure_schema()
    return db


def _counts(db):
    conn = sqlite3.connect(db)
    try:
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ti_%' ORDER BY name"
        )]
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
        counts["config_global"] = conn.execute("SELECT COUNT(*) FROM config_global").fetchone()[0]
        counts["users"] = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        return counts
    finally:
        conn.close()


def _settings(db):
    raw = SQLiteTrendIntelligenceReadOnlyLookup(db).get_config(L.COLLECTOR_SETTINGS_KEY)
    return None if raw is None else json.loads(raw)


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _service(db):
    return TrendIntelligenceService(SQLiteTrendIntelligenceRepository(db))


# ============================================================
# Barreras de destino, sello y checkout
# ============================================================

def _sealed_layout(tmp_path, *, username=USERNAME, db_path=None):
    dest = tmp_path / "sandbox"
    worktree = dest / "crm"
    db = worktree / "database" / "quesada.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    if not db.exists():
        db.write_bytes(b"")
    seal = dict(sha=SHA, db_path=str(db_path or db), username=username)
    return dest, worktree, db, seal


@pytest.fixture
def sealed(monkeypatch, tmp_path):
    dest, worktree, db, seal = _sealed_layout(tmp_path)
    calls = []

    def validate_launch(value, *, repo_root):
        calls.append((value, repo_root))
        return dest, worktree

    monkeypatch.setattr(L, "validate_launch", validate_launch)
    monkeypatch.setattr(L, "read_seal", lambda value: seal)
    return SimpleNamespace(dest=dest, worktree=worktree, db=db, seal=seal, calls=calls)


@pytest.mark.parametrize("dest, code", [(None, "DEST_REQUIRED"), ("", "DEST_REQUIRED"),
                                        ("relative/sandbox", "DEST_NOT_ABSOLUTE")])
def test_dest_required_and_absolute_before_any_check(monkeypatch, dest, code):
    monkeypatch.setattr(L, "validate_launch", lambda *a, **k: pytest.fail("no debe validar"))
    with pytest.raises(L.SandboxError, match=code):
        F.validate_target(dest)


def test_must_run_from_sealed_checkout(sealed):
    # El repo de desarrollo real nunca es <dest>/crm.
    with pytest.raises(L.SandboxError, match="NOT_RUNNING_FROM_SEALED_CHECKOUT"):
        F.validate_target(str(sealed.dest), repo_root=F.REPO_ROOT, cwd=sealed.worktree)
    assert sealed.calls == []


def test_cwd_must_be_sealed_checkout(sealed, tmp_path):
    with pytest.raises(L.SandboxError, match="CWD_NOT_SEALED_CHECKOUT"):
        F.validate_target(str(sealed.dest), repo_root=sealed.worktree, cwd=tmp_path)
    assert sealed.calls == []


def test_valid_target_reuses_launcher_validation(sealed):
    target = F.validate_target(str(sealed.dest), repo_root=sealed.worktree, cwd=sealed.worktree)
    assert sealed.calls == [(str(sealed.dest), sealed.worktree.resolve())]
    assert target == F.Target(dest=sealed.dest, worktree=sealed.worktree, sha=SHA,
                              db_path=sealed.db, username=USERNAME)


@pytest.mark.parametrize("code", [
    "DEST_OUTSIDE_TEMP", "DEST_OVERLAPS_CHECKOUT", "SEAL_MISSING", "SEAL_MISMATCH",
    "WORKTREE_SHA_MISMATCH", "WORKTREE_NOT_DETACHED", "WORKTREE_DIRTY",
    "SANDBOX_DB_MISSING", "ENV_LOCAL_PRESENT", "EFFECTIVE_DB_PATH_MISMATCH:database.connection.DB_PATH",
])
def test_launcher_barriers_propagate_fail_closed(monkeypatch, tmp_path, code):
    dest, worktree, _, _ = _sealed_layout(tmp_path)

    def refuse(*args, **kwargs):
        raise L.SandboxError(code)

    monkeypatch.setattr(L, "validate_launch", refuse)
    monkeypatch.setattr(L, "read_seal", lambda value: pytest.fail("no debe leer el sello"))
    with pytest.raises(L.SandboxError, match=code):
        F.validate_target(str(dest), repo_root=worktree, cwd=worktree)


def test_seal_db_path_must_be_worktree_database(monkeypatch, sealed, tmp_path):
    sealed.seal["db_path"] = str(tmp_path / "otra" / "quesada.db")
    with pytest.raises(L.SandboxError, match="SEAL_DB_PATH_MISMATCH"):
        F.validate_target(str(sealed.dest), repo_root=sealed.worktree, cwd=sealed.worktree)


def test_database_must_already_exist(sealed):
    sealed.db.unlink()
    with pytest.raises(L.SandboxError, match="SANDBOX_DB_MISSING"):
        F.validate_target(str(sealed.dest), repo_root=sealed.worktree, cwd=sealed.worktree)
    assert not sealed.db.exists()


@pytest.mark.parametrize("username", ["admin", "", None, "sandbox_XYZ", "nacho", "sandbox_0a1b2c3d4"])
def test_seal_user_must_be_launcher_generated(sealed, username):
    sealed.seal["username"] = username
    with pytest.raises(L.SandboxError, match="SEAL_USER_NOT_SYNTHETIC"):
        F.validate_target(str(sealed.dest), repo_root=sealed.worktree, cwd=sealed.worktree)


class TestRealLauncherLocationChecks:
    """validate_launch real con TEMP y checkouts simulados (sin git)."""

    @pytest.fixture(autouse=True)
    def fake_environment(self, monkeypatch, tmp_path):
        self.temp = tmp_path / "temp"
        self.temp.mkdir()
        self.checkouts = []
        monkeypatch.setattr(L, "temp_root", lambda: self.temp.resolve())
        monkeypatch.setattr(L, "list_checkouts", lambda repo_root: list(self.checkouts))
        monkeypatch.setattr(L, "_git", lambda *a, **k: pytest.fail("git no permitido"))
        monkeypatch.setattr(L, "run_internal", lambda *a, **k: pytest.fail("sin subprocesos"))

    def _target(self, dest):
        worktree = dest / "crm"
        return F.validate_target(str(dest), repo_root=worktree, cwd=worktree)

    def test_outside_temp(self, tmp_path):
        with pytest.raises(L.SandboxError, match="DEST_OUTSIDE_TEMP"):
            self._target(tmp_path / "fuera")

    def test_overlapping_foreign_checkout(self, tmp_path):
        dest = self.temp / "sb"
        (dest / "crm").mkdir(parents=True)
        self.checkouts.append(self.temp)
        with pytest.raises(L.SandboxError, match="DEST_OVERLAPS_CHECKOUT"):
            self._target(dest)

    def test_inside_git_checkout(self):
        (self.temp / "repo" / ".git").mkdir(parents=True)
        dest = self.temp / "repo" / "sb"
        (dest / "crm").mkdir(parents=True)
        with pytest.raises(L.SandboxError, match="DEST_INSIDE_GIT_CHECKOUT"):
            self._target(dest)

    def test_missing_seal(self):
        dest = self.temp / "sb"
        (dest / "crm").mkdir(parents=True)
        with pytest.raises(L.SandboxError, match="SEAL_MISSING"):
            self._target(dest)

    def test_forged_seal(self):
        dest = self.temp / "sb"
        (dest / "crm").mkdir(parents=True)
        (dest / L.SEAL_NAME).write_text(json.dumps(dict(
            kind=L.SEAL_KIND, version=L.SEAL_VERSION, dest=str(dest),
            worktree=str(dest / "crm"), db_path="C:/otra/quesada.db", sha=SHA,
        )), encoding="utf-8")
        with pytest.raises(L.SandboxError, match="SEAL_MISMATCH"):
            self._target(dest)


def test_import_services_requires_sealed_db_path(monkeypatch, tmp_path):
    db = tmp_path / "crm" / "database" / "quesada.db"
    target = F.Target(dest=tmp_path, worktree=tmp_path / "crm", sha=SHA, db_path=db, username=USERNAME)
    loaded = {name: SimpleNamespace() for name in F.MODULES}
    loaded["database.connection"].DB_PATH = str(tmp_path / "elsewhere.db")
    loaded["backend.repositories.sqlite_trend_intelligence_repository"].DEFAULT_DB_PATH = db
    monkeypatch.setattr(L, "_import_from_worktree", lambda root, modules: (root, loaded))
    with pytest.raises(L.SandboxError, match="EFFECTIVE_DB_PATH_MISMATCH"):
        F.import_services(target)


def test_import_services_rejects_foreign_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    target = F.Target(dest=tmp_path, worktree=F.REPO_ROOT, sha=SHA,
                      db_path=tmp_path / "quesada.db", username=USERNAME)
    with pytest.raises(L.SandboxError, match="INTERNAL_CWD_MISMATCH"):
        F.import_services(target)


# ============================================================
# Comprobación de BD sintética
# ============================================================

def test_fresh_launcher_database_is_accepted(tmp_path, connect_spy):
    db = _synthetic_db(tmp_path)
    assert F.check_synthetic(SERVICES, db) == dict(
        collector_settings_present=False, domain_present=False, observations_present=0,
    )


def test_more_than_one_user_is_not_synthetic(tmp_path, connect_spy):
    db = _synthetic_db(tmp_path, users=2)
    with pytest.raises(L.SandboxError, match="DB_NOT_SYNTHETIC:USERS"):
        F.check_synthetic(SERVICES, db)


def test_incomplete_schema_is_rejected(tmp_path, connect_spy):
    db = _synthetic_db(tmp_path, ti_schema=False)
    with pytest.raises(L.SandboxError, match="DB_SCHEMA_INCOMPLETE"):
        F.check_synthetic(SERVICES, db)


@pytest.mark.parametrize("value", [
    "{not json",
    json.dumps(dict(enabled=True, domain_code="SANDBOX_MARKETING", source_code="SANDBOX_SYNTHETIC_SOCIAL")),
    json.dumps(dict(enabled=False, domain_code="OTRO", source_code="X")),
    json.dumps(dict(F.COLLECTOR_SETTINGS, profile_key="instagram_main")),
])
def test_foreign_collector_settings_are_never_overwritten(tmp_path, connect_spy, value):
    db = _synthetic_db(tmp_path)
    _raw_config(db, value)
    before = _digest(db)
    with pytest.raises(L.SandboxError, match="COLLECTOR_SETTINGS_NOT_SYNTHETIC"):
        F.seed(SERVICES, db, today=TODAY)
    assert _digest(db) == before


def _raw_config(db, value):
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO config_global (key, value) VALUES (?, ?)", (L.COLLECTOR_SETTINGS_KEY, value))
    conn.commit()
    conn.close()


def test_foreign_domain_blocks(tmp_path, connect_spy):
    db = _synthetic_db(tmp_path)
    _service(db).create_domain(code="EXTRANJERIA", name="Real")
    with pytest.raises(L.SandboxError, match="FOREIGN_DOMAIN_PRESENT"):
        F.seed(SERVICES, db, today=TODAY)


def test_unmarked_sandbox_domain_blocks(tmp_path, connect_spy):
    db = _synthetic_db(tmp_path)
    _service(db).create_domain(code=F.DOMAIN_CODE, name="Sin marca")
    with pytest.raises(L.SandboxError, match="DOMAIN_NOT_SYNTHETIC"):
        F.check_synthetic(SERVICES, db)


@pytest.mark.parametrize("changes", [
    dict(provider="instagram"),
    dict(base_url="https://www.instagram.com/"),
    dict(collection_mode="API"),
    dict(configuration=None),
])
def test_non_synthetic_source_blocks(tmp_path, connect_spy, changes):
    db = _synthetic_db(tmp_path)
    values = dict(code=F.SOURCE_CODE, name="x", source_type="SOCIAL", provider=F.SOURCE_PROVIDER,
                  collection_mode="SELENIUM", configuration=dict(F.METADATA))
    values.update(changes)
    _service(db).create_source(**values)
    with pytest.raises(L.SandboxError, match="SOURCE_NOT_SYNTHETIC"):
        F.check_synthetic(SERVICES, db)


def test_collector_run_on_source_blocks(tmp_path, connect_spy):
    db = _synthetic_db(tmp_path)
    F.seed(SERVICES, db, today=TODAY)
    repository = SQLiteTrendIntelligenceRepository(db)
    source = repository.get_source_by_code(F.SOURCE_CODE)
    repository.save_collector_run(CollectorRun(
        id=None, source_id=source.id, collector_key="x", collector_version="1",
        started_at="2026-10-10T00:00:00+00:00",
    ))
    with pytest.raises(L.SandboxError, match="COLLECTOR_RUNS_PRESENT"):
        F.seed(SERVICES, db, today=TODAY)


def test_foreign_observation_in_domain_blocks(tmp_path, connect_spy):
    db = _synthetic_db(tmp_path)
    F.seed(SERVICES, db, today=TODAY)
    service = _service(db)
    observation, _ = service.record_observation(
        source_code=F.SOURCE_CODE, observation_type="POST", external_id="real-1",
        body_text="x", observed_at="2026-10-10T00:00:00+00:00",
    )
    service.assign_observation_domain(observation.id, F.DOMAIN_CODE)
    with pytest.raises(L.SandboxError, match="FOREIGN_OBSERVATION_PRESENT"):
        F.check_synthetic(SERVICES, db)


# ============================================================
# Plan sintético
# ============================================================

def test_observations_are_reproducible_complete_utc_days_before_reference():
    planned = F.build_observations(TODAY)
    assert planned == F.build_observations(TODAY)
    assert 5 <= len(planned) <= 8
    midnight = datetime(2026, 10, 16, tzinfo=timezone.utc)
    for item in planned:
        observed = item["observed_at"]
        assert observed.tzinfo is not None and observed.utcoffset() == timedelta(0)
        assert midnight - timedelta(days=7) <= observed < midnight
    assert len({item["external_id"] for item in planned}) == len(planned)


@pytest.mark.parametrize("value", [None, "2026-10-16", datetime(2026, 10, 16, tzinfo=timezone.utc)])
def test_reference_date_must_be_a_date(value):
    with pytest.raises(L.SandboxError, match="REFERENCE_DATE_INVALID"):
        F.build_observations(value)


def test_observations_are_marked_artificial_without_real_identities():
    topic_keys = {topic["topic_key"] for topic in F.TOPICS}
    for item in F.build_observations(TODAY):
        metadata = item["metadata"]
        assert metadata["synthetic"] is True and metadata["marker"] == "SYNTHETIC_SANDBOX"
        assert item["external_id"].startswith("SYNTHETIC_SANDBOX-")
        assert "SYNTHETIC_SANDBOX" in item["body_text"]
        assert item["author"].startswith("autor_ficticio_")
        assert "url" not in item
        assert metadata["expected_topic"] in topic_keys
        assert metadata["hashtags"]
    text = json.dumps([F.TOPICS, F.COLLECTOR_SETTINGS], default=str).lower()
    source = FIXTURE_PATH.read_text(encoding="utf-8").lower()
    for forbidden in ("instagram.com", "http://", "https://", "@", "password", "token"):
        assert forbidden not in text
    for forbidden in ("instagram.com", "http://", "https://"):
        assert forbidden not in source


def test_collector_settings_never_enabled_nor_with_profile():
    assert F.COLLECTOR_SETTINGS["enabled"] is False
    assert "profile_key" not in F.COLLECTOR_SETTINGS
    assert "accounts" not in F.COLLECTOR_SETTINGS


def test_settings_key_matches_existing_contracts():
    from backend.services import trend_intelligence_dashboard_service as dashboard
    from backend.services import instagram_collector_configuration_service as configuration
    assert L.COLLECTOR_SETTINGS_KEY == dashboard.SETTINGS_KEY == configuration.SETTINGS_KEY


# ============================================================
# Siembra, idempotencia y contratos existentes
# ============================================================

def test_seed_populates_catalog_and_observations_only(tmp_path, connect_spy):
    db = _synthetic_db(tmp_path)
    result = F.seed(SERVICES, db, today=TODAY)

    assert result["topics"] == ["MODA", "MODA_URBANA"]
    assert result["observations"] == dict(planned=8, created=8, existing=0, total=8)
    assert result["collector"] == dict(enabled=False, settings_written=True)
    assert result["producer_window"] == dict(from_date="2026-10-10", to_date="2026-10-16")

    repository = SQLiteTrendIntelligenceRepository(db, readonly=True)
    domain = repository.get_domain_by_code(F.DOMAIN_CODE)
    assert domain.is_active and domain.metadata["marker"] == "SYNTHETIC_SANDBOX"
    source = repository.get_source_by_code(F.SOURCE_CODE)
    assert (source.source_type, source.collection_mode, source.provider, source.base_url) == (
        "SOCIAL", "SELENIUM", "SYNTHETIC_SANDBOX", None)
    assert source.configuration["catalog_only"] is True
    topics = repository.list_topics_for_domain(domain.id, active_only=True)
    assert sorted(t.topic_key for t in topics) == ["MODA", "MODA_URBANA"]
    for topic in topics:
        assert len(repository.list_topic_aliases(topic.id, active_only=True)) == 2

    counts = _counts(db)
    assert counts["ti_observations"] == 8
    assert counts["ti_observation_domains"] == 8
    # Sin clasificación, señales, snapshots ni ejecuciones fingidas.
    for table in ("ti_observation_topics", "ti_signals", "ti_trend_snapshots",
                  "ti_aggregate_signals", "ti_temporal_metrics", "ti_collector_runs", "ti_trends"):
        assert counts.get(table, 0) == 0, table
    assert counts["users"] == 1
    assert _settings(db) == F.COLLECTOR_SETTINGS


def test_seed_is_idempotent_also_on_later_days(tmp_path, connect_spy):
    db = _synthetic_db(tmp_path)
    F.seed(SERVICES, db, today=TODAY)
    before = _counts(db)
    again = F.seed(SERVICES, db, today=TODAY)
    later = F.seed(SERVICES, db, today=TODAY + timedelta(days=3))
    assert _counts(db) == before
    for result in (again, later):
        assert result["observations"] == dict(planned=8, created=0, existing=8, total=8)
        assert result["collector"]["settings_written"] is False
        # La ventana refleja lo realmente almacenado, no el día de reejecución.
        assert result["producer_window"] == dict(from_date="2026-10-10", to_date="2026-10-16")


def test_collector_contract_stays_disabled_and_cannot_be_enabled(tmp_path, connect_spy):
    from backend.services.instagram_collector_configuration_service import (
        InstagramCollectorConfigurationService, InvalidInstagramConfiguration,
    )
    from backend.services.instagram_collector_control_service import _CandidateLookup

    db = _synthetic_db(tmp_path)
    F.seed(SERVICES, db, today=TODAY)
    lookup = SQLiteTrendIntelligenceReadOnlyLookup(db)
    assert InstagramCollectorConfigurationService(lookup).load().status == "DISABLED"

    candidate = dict(F.COLLECTOR_SETTINGS, enabled=True, profile_key="sandbox",
                     headless=True, accounts=[dict(account="ficticia", limit=1)])
    with pytest.raises(InvalidInstagramConfiguration, match="not Instagram"):
        InstagramCollectorConfigurationService(_CandidateLookup(lookup, candidate)).load()


def test_dashboard_selects_synthetic_domain_without_fake_snapshots(tmp_path, connect_spy):
    from backend.services.trend_intelligence_dashboard_service import (
        STATUS_EMPTY, STATUS_NO_DOMAIN, TrendIntelligenceDashboardService,
    )

    db = _synthetic_db(tmp_path)

    def dashboard():
        return TrendIntelligenceDashboardService(
            settings=SQLiteTrendIntelligenceReadOnlyLookup(db),
            trends=TrendIntelligenceService(SQLiteTrendIntelligenceRepository(db, readonly=True)),
            store_unavailable_errors=(ReadOnlyStoreUnavailable,),
        ).state()

    assert dashboard().status == STATUS_NO_DOMAIN
    F.seed(SERVICES, db, today=TODAY)
    state = dashboard()
    assert (state.status, state.domain_code) == (STATUS_EMPTY, F.DOMAIN_CODE)


def test_hashtags_classify_on_temporary_copy_only(tmp_path, connect_spy):
    """Clasificación (fase 1 del productor) sobre una BD de tmp_path, nunca ventanas."""
    from backend.trend_intelligence.producer import create_trend_producer

    db = _synthetic_db(tmp_path)
    F.seed(SERVICES, db, today=TODAY)
    expected = {
        o.id: o.metadata["expected_topic"]
        for o, _ in SQLiteTrendIntelligenceRepository(db, readonly=True).list_domain_observations(
            SQLiteTrendIntelligenceRepository(db, readonly=True).get_domain_by_code(F.DOMAIN_CODE).id,
        )
    }
    result = create_trend_producer(db).classify_pending(F.DOMAIN_CODE)
    assert (result.status, result.classified, result.unmatched, result.ambiguous) == ("OK", 8, 0, 0)
    assert {o.observation_id: o.topic_key for o in result.outcomes} == expected
    assert _counts(db)["ti_trend_snapshots"] == 0


def test_preview_never_writes(tmp_path, connect_spy):
    db = _synthetic_db(tmp_path)
    before = _digest(db)
    result = F.preview(SERVICES, db, today=TODAY)
    assert result["observations"] == dict(planned=8, created=0, existing=0, total=0)
    assert result["producer_window"] == dict(from_date="2026-10-10", to_date="2026-10-16")
    assert _digest(db) == before
    assert _settings(db) is None


# ============================================================
# run / CLI
# ============================================================

@pytest.fixture
def wired(monkeypatch, tmp_path):
    db = _synthetic_db(tmp_path)
    target = F.Target(dest=tmp_path / "sandbox", worktree=tmp_path / "sandbox" / "crm",
                      sha=SHA, db_path=db, username=USERNAME)
    verified = []
    monkeypatch.setattr(F, "validate_target", lambda dest, repo_root=None: target)
    monkeypatch.setattr(F, "import_services", lambda value: SERVICES)
    monkeypatch.setattr(L, "verify_worktree",
                        lambda worktree, sha, *, expect_db: verified.append((worktree, sha, expect_db)))
    return SimpleNamespace(db=db, target=target, verified=verified)


def test_run_preview_reports_without_writing(wired):
    before = _digest(wired.db)
    report = F.run("x", execute=False, today=TODAY)
    assert report["status"] == "PREVIEW" and report["execute"] is False
    assert report["synthetic"] is True and report["producer_run"] == "NOT_EXECUTED"
    assert report["collector_started"] is False
    assert wired.verified == []
    assert _digest(wired.db) == before


def test_run_execute_reverifies_worktree_and_hides_credentials(wired):
    report = F.run("x", execute=True, today=TODAY)
    assert report["status"] == "SEEDED"
    assert wired.verified == [(wired.target.worktree, SHA, True)]
    assert report["db_path"] == str(wired.db)
    text = json.dumps(report).lower()
    assert USERNAME not in text and "password" not in text and "contrasena" not in text


def test_main_without_execute_never_seeds(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(F, "run", lambda dest, *, execute: calls.append(execute) or F._base_report("PREVIEW"))
    assert F.main(["--dest", "C:/x"]) == 0
    assert calls == [False]
    assert json.loads(capsys.readouterr().out)["status"] == "PREVIEW"


def test_main_rejects_free_db_path(capsys):
    with pytest.raises(SystemExit) as exc:
        F.main(["--dest", "C:/x", "--db-path", "C:/x/quesada.db", "--execute"])
    assert exc.value.code == 2


def test_main_blocked_json_fail_closed(monkeypatch, capsys):
    def refuse(dest, *, execute):
        raise L.SandboxError("DEST_OUTSIDE_TEMP")

    monkeypatch.setattr(F, "run", refuse)
    assert F.main(["--dest", "C:/x", "--execute"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "BLOCKED" and report["error"] == "DEST_OUTSIDE_TEMP"
    assert report["synthetic"] is True and report["execute"] is True


def test_main_hides_unexpected_error_details(monkeypatch, capsys):
    def boom(dest, *, execute):
        raise RuntimeError("C:/secreto/ruta password=1234")

    monkeypatch.setattr(F, "run", boom)
    assert F.main(["--dest", "C:/x"]) == 2
    out = capsys.readouterr().out
    assert "secreto" not in out and "1234" not in out
    assert json.loads(out)["error"] == "UNEXPECTED:RuntimeError"


# ============================================================
# Contrato estático
# ============================================================

def test_fixture_has_no_sql_env_browser_or_network():
    source = FIXTURE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"argparse", "dataclasses", "datetime", "importlib", "json",
                        "pathlib", "re", "sys"}, imported
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    for forbidden in ("environ", "getenv", "Popen", "subprocess", "connect", "executescript",
                      "execute_sql", "launch", "classify_pending", "process_windows",
                      "create_trend_producer", "save_trend_snapshot", "create_signal"):
        assert forbidden not in names, forbidden


def _code_strings(tree):
    """Literales fuera del docstring del módulo."""
    docstring = ast.get_docstring(tree, clean=False)
    return " ".join(
        node.value.upper() for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value != docstring
    )


def test_fixture_code_strings_have_no_sql():
    tree = ast.parse(FIXTURE_PATH.read_text(encoding="utf-8"))
    strings = _code_strings(tree)
    for keyword in ("INSERT ", "UPDATE ", "DELETE ", "CREATE TABLE", "DROP ", "ALTER ", "SELECT "):
        assert keyword not in strings, keyword
