"""
Piloto real Instagram sobre el sandbox CRM sellado: preparación, inspección
y un ÚNICO disparo del controller CRM existente.

VERSIÓN DE DESARROLLO (WO TI-4C.3E1). Fail-closed. Solo opera sobre la BD
del sandbox creado por scripts/dev/crm_it_sandbox_launcher.py --prepare y
SOLO cuando se ejecuta desde el checkout temporal sellado (<DEST>/crm).
El sandbox debe ser NUEVO: una BD con la fixture sintética (TI-4C.3D),
observaciones, señales o catálogos ajenos nunca se convierte en piloto.

--dest DIR
    Estado/preflight: revalida sello, checkout, rutas de BD y estado del
    piloto con lecturas; nunca escribe ni abre navegador.

--dest DIR --configure --account HANDLE --topic-key TOPIC --hashtag TAG
    Valida TODO antes de escribir y registra, con los servicios existentes,
    dominio PILOT_INSTAGRAM, fuente SOCIAL/SELENIUM/instagram, un topic con
    su hashtag como alias y IT_INSTAGRAM_COLLECTOR_V1 con enabled=false,
    una sola cuenta pública, limit=5, headless=false y un profile_key
    aleatorio nuevo. Idempotente con los mismos argumentos. Nunca recoge.

--dest DIR --collect --ack-real-web-read
    Una sola ejecución de InstagramCollectorControlService.execute(): crea
    un marcador de intento único (O_EXCL) antes de cualquier red, arma
    enabled=true solo durante la ejecución y lo desarma en finally. Sin
    reintentos: un marcador presente (error, bloqueo o caída) impide
    cualquier nueva recogida en este DEST.

--dest DIR --disarm
    Solo seguridad: fuerza enabled=false si quedó a true tras una caída.
    Sin navegador ni red.

Salida: un único JSON redactado (sin cuenta, captions, URLs, rutas,
contraseñas ni cookies). Nunca llama al productor de tendencias.

Perfil SeleniumBase: lo resuelve el runtime existente
(instagram_browser._resolve_instagram_profile) en
~/.quesada_browser_profiles/<profile_key>, FUERA de DEST; aquí solo se
comprueba que el profile_key nuevo no exista. El perfil nace vacío y sin
sesión: no existe API segura para autenticarlo y este CLI no la crea. Si
Instagram exige login/challenge, el resultado es BLOCKED y el intento queda
consumido. Retirar el perfil a mano al cerrar el piloto; nunca incluirlo
en entregables.

Uso (Git Bash, tras integrar este código; <SHA> posterior a la integración):

    python scripts/dev/crm_it_sandbox_launcher.py --prepare \\
        --dest "$TEMP/quesada-ig-pilot-01" --sha <SHA>
    cd "<DEST>/crm"
    python -E -B scripts/dev/ti_instagram_real_pilot.py --dest "<DEST>"
    python -E -B scripts/dev/ti_instagram_real_pilot.py --dest "<DEST>" \\
        --configure --account <cuenta_publica> --topic-key <TOPIC> --hashtag <tag>
    python -E -B scripts/dev/ti_instagram_real_pilot.py --dest "<DEST>" \\
        --collect --ack-real-web-read

El productor (trend_producer_run.py) se ejecuta aparte, por el operador,
no antes de producer_not_before_utc y solo si status=SUCCESS.
"""

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import importlib.util
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = Path(__file__).resolve().parent / "ti_it_sandbox_fixture.py"


def _load_fixture():
    spec = importlib.util.spec_from_file_location("ti_it_sandbox_fixture", FIXTURE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FX = _load_fixture()
L = FX.L
SandboxError = L.SandboxError

WORK_ORDER = "TI-4C.3E1"
PILOT_MARKER = "REAL_PILOT"

DOMAIN_CODE = "PILOT_INSTAGRAM"
SOURCE_CODE = "PILOT_INSTAGRAM_SOCIAL"
SOURCE_TYPE = "SOCIAL"
SOURCE_COLLECTION_MODE = "SELENIUM"
SOURCE_PROVIDER = "instagram"
SOURCE_BASE_URL = "https://www.instagram.com/"

ACCOUNT_LIMIT = 5
HEADLESS = False

METADATA = dict(marker=PILOT_MARKER, work_order=WORK_ORDER, real=True)

# Mismo root que instagram_browser._resolve_instagram_profile.
PROFILES_DIRNAME = ".quesada_browser_profiles"
PROFILE_PREFIX = "it_pilot_ig_"
PROFILE_KEY_PATTERN = re.compile(r"it_pilot_ig_[0-9a-f]{16}")
PROFILE_KEY_ATTEMPTS = 8

# Usuario de Instagram: [a-z0-9_.], 1-30, sin punto inicial/final ni "..".
ACCOUNT_PATTERN = re.compile(r"(?!\.)(?!.*\.\.)(?!.*\.$)[a-z0-9_.]{1,30}")
TOPIC_KEY_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{1,47}")
HASHTAG_PATTERN = re.compile(r"(?=.*[a-z])[a-z0-9_]{2,50}")

LOCK_NAME = "ti_instagram_pilot.lock"
ATTEMPT_NAME = "ti_instagram_pilot_attempt.json"
RESULT_NAME = "ti_instagram_pilot_result.json"

CLEANUP_TIMEOUT_SECONDS = 120

# Tablas que deben estar vacías antes de configurar y de recoger.
ACTIVITY_TABLES = (
    "ti_observations",
    "ti_observation_domains",
    "ti_observation_topics",
    "ti_signals",
    "ti_aggregate_signals",
    "ti_temporal_metrics",
    "ti_temporal_baselines",
    "ti_trends",
    "ti_trend_evidence",
    "ti_trend_snapshots",
    "ti_collector_runs",
)
PILOT_REQUIRED_TABLES = ACTIVITY_TABLES + ("ti_topic_aliases", "ti_topic_domains")

SETTINGS_KEYS = {
    "enabled", "domain_code", "source_code", "profile_key", "headless", "accounts", "pilot",
}
RESULT_KEYS = ("status", "created", "duplicates", "total", "cleanup", "collector_enabled")

MODULES = (
    "database.connection",
    "backend.services.config_service",
    "backend.repositories.sqlite_trend_intelligence_repository",
    "backend.repositories.instagram_collector_settings_repository",
    "backend.trend_intelligence.models",
    "backend.trend_intelligence.service",
    "backend.automation.browser_profiles",
    "backend.services.instagram_collector_configuration_service",
    "backend.services.instagram_collector_control_service",
)


# ============================================================
# Plan
# ============================================================

@dataclass(frozen=True)
class Plan:
    account: str
    topic_key: str
    hashtag: str


def build_plan(accounts, topic_key, hashtag):
    """Valida los argumentos de --configure; nunca toca disco ni red."""
    accounts = [a for a in (accounts or []) if a is not None]
    if len(accounts) != 1:
        raise SandboxError("ACCOUNT_EXACTLY_ONE_REQUIRED")
    account = str(accounts[0]).strip()
    account = account[1:] if account.startswith("@") else account
    account = account.lower()
    if not ACCOUNT_PATTERN.fullmatch(account):
        raise SandboxError("ACCOUNT_INVALID")

    topic_key = str(topic_key or "").strip().upper()
    if not TOPIC_KEY_PATTERN.fullmatch(topic_key):
        raise SandboxError("TOPIC_KEY_INVALID")

    hashtag = str(hashtag or "").strip()
    hashtag = hashtag[1:] if hashtag.startswith("#") else hashtag
    hashtag = hashtag.lower()
    if not HASHTAG_PATTERN.fullmatch(hashtag):
        raise SandboxError("HASHTAG_INVALID")
    return Plan(account=account, topic_key=topic_key, hashtag=hashtag)


def build_settings(plan, profile_key, *, enabled=False):
    return dict(
        enabled=enabled,
        domain_code=DOMAIN_CODE,
        source_code=SOURCE_CODE,
        profile_key=profile_key,
        headless=HEADLESS,
        accounts=[dict(account=plan.account, limit=ACCOUNT_LIMIT)],
        pilot=dict(marker=PILOT_MARKER, work_order=WORK_ORDER,
                   topic_key=plan.topic_key, hashtag=plan.hashtag),
    )


def parse_settings(raw, *, normalize_profile_key):
    """IT_INSTAGRAM_COLLECTOR_V1 exacto del piloto -> (plan, profile_key, enabled)."""
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        raise SandboxError("SETTINGS_INVALID:JSON") from None
    if not isinstance(value, dict) or set(value) != SETTINGS_KEYS:
        raise SandboxError("SETTINGS_INVALID:KEYS")
    pilot = value["pilot"]
    if not isinstance(pilot, dict) or pilot.get("marker") != PILOT_MARKER:
        raise SandboxError("SETTINGS_INVALID:NOT_PILOT")
    accounts = value["accounts"]
    if not isinstance(accounts, list) or len(accounts) != 1 or not isinstance(accounts[0], dict):
        raise SandboxError("SETTINGS_INVALID:ACCOUNTS")
    limit = accounts[0].get("limit")
    if type(limit) is not int or limit != ACCOUNT_LIMIT:
        raise SandboxError("SETTINGS_INVALID:LIMIT")
    enabled = value["enabled"]
    if type(enabled) is not bool:
        raise SandboxError("SETTINGS_INVALID:ENABLED")
    profile_key = value["profile_key"]
    if not isinstance(profile_key, str) or not PROFILE_KEY_PATTERN.fullmatch(profile_key):
        raise SandboxError("SETTINGS_INVALID:PROFILE_KEY")
    try:
        if normalize_profile_key(profile_key) != profile_key:
            raise ValueError
    except (TypeError, ValueError):
        raise SandboxError("SETTINGS_INVALID:PROFILE_KEY") from None
    account = accounts[0].get("account")
    if not isinstance(account, str) or not ACCOUNT_PATTERN.fullmatch(account):
        raise SandboxError("SETTINGS_INVALID:ACCOUNT")
    try:
        plan = build_plan([account], pilot.get("topic_key"), pilot.get("hashtag"))
    except SandboxError:
        raise SandboxError("SETTINGS_INVALID:PILOT") from None
    if (
        plan.topic_key != pilot.get("topic_key")
        or plan.hashtag != pilot.get("hashtag")
        or value != build_settings(plan, profile_key, enabled=enabled)
    ):
        # Fuente, dominio, headless o cualquier campo distinto del plan.
        raise SandboxError("SETTINGS_INVALID:MISMATCH")
    return plan, profile_key, enabled


# ============================================================
# Barreras y servicios
# ============================================================

@dataclass(frozen=True)
class Services:
    trend_service: type
    repository: type
    settings_repository: type
    readonly_lookup: type
    readonly_connection: object
    source_model: type
    domain_model: type
    configuration_service: type
    control_service: type
    runtime_factory: object
    normalize_profile_key: object


def validate(dest, *, repo_root=REPO_ROOT, cwd=None):
    """Sello, checkout sellado, cwd, BD del sello y usuario ficticio (TI-4C.3D)."""
    target = FX.validate_target(dest, repo_root=repo_root, cwd=cwd)
    if not L._same_path(target.db_path, target.worktree / L.DB_RELATIVE):
        raise SandboxError("SEAL_DB_PATH_MISMATCH")
    if not L._is_within(target.dest, L.temp_root()):
        raise SandboxError("DEST_OUTSIDE_TEMP")
    return target


def import_services(target):
    """Servicios del checkout sellado; toda DB_PATH efectiva debe ser la del sello."""
    _, loaded = L._import_from_worktree(target.worktree, MODULES)
    repository = loaded["backend.repositories.sqlite_trend_intelligence_repository"]
    connection = loaded["database.connection"]
    for value in (connection.DB_PATH, repository.DEFAULT_DB_PATH,
                  loaded["backend.services.config_service"].DB_PATH):
        if not L._same_path(Path(value).resolve(), target.db_path):
            raise SandboxError("EFFECTIVE_DB_PATH_MISMATCH")
    models = loaded["backend.trend_intelligence.models"]
    configuration = loaded["backend.services.instagram_collector_configuration_service"]
    return Services(
        trend_service=loaded["backend.trend_intelligence.service"].TrendIntelligenceService,
        repository=repository.SQLiteTrendIntelligenceRepository,
        settings_repository=loaded[
            "backend.repositories.instagram_collector_settings_repository"
        ].SQLiteInstagramCollectorSettingsRepository,
        readonly_lookup=repository.SQLiteTrendIntelligenceReadOnlyLookup,
        readonly_connection=connection.get_readonly_connection,
        source_model=models.TrendSource,
        domain_model=models.TrendDomain,
        configuration_service=configuration.InstagramCollectorConfigurationService,
        control_service=loaded[
            "backend.services.instagram_collector_control_service"
        ].InstagramCollectorControlService,
        # Usa config_service.DB_PATH, ya comprobada arriba.
        runtime_factory=configuration.create_crm_instagram_runtime,
        normalize_profile_key=loaded["backend.automation.browser_profiles"].normalize_browser_profile_key,
    )


def profiles_root():
    return Path.home() / PROFILES_DIRNAME


def check_profile_slot(root, profile_key, *, must_be_new):
    """Solo lexists/lstat del perfil concreto; nunca lista ni lee perfiles."""
    root = Path(root)
    if os.path.lexists(root) and L._is_link_or_reparse(root):
        raise SandboxError("PROFILES_ROOT_LINK_OR_REPARSE")
    path = root / profile_key
    if os.path.lexists(path):
        if must_be_new:
            return False
        if L._is_link_or_reparse(path) or not path.is_dir():
            raise SandboxError("PROFILE_LINK_OR_INVALID")
    return True


def new_profile_key(services, root, *, token=secrets.token_hex):
    for _ in range(PROFILE_KEY_ATTEMPTS):
        key = PROFILE_PREFIX + token(8)
        if not PROFILE_KEY_PATTERN.fullmatch(key) or services.normalize_profile_key(key) != key:
            raise SandboxError("PROFILE_KEY_INVALID")
        if check_profile_slot(root, key, must_be_new=True):
            return key
    raise SandboxError("PROFILE_KEY_COLLISION")


# ============================================================
# Estado de la BD (solo lecturas)
# ============================================================

def _expected_source(services):
    return services.source_model(
        id=None, code=SOURCE_CODE, name="Instagram (piloto real)", source_type=SOURCE_TYPE,
        provider=SOURCE_PROVIDER, base_url=SOURCE_BASE_URL,
        collection_mode=SOURCE_COLLECTION_MODE, configuration=dict(METADATA),
    )


def _expected_domain(services):
    return services.domain_model(
        id=None, code=DOMAIN_CODE, name="Piloto Instagram (real)",
        description="Primera recogida real y autorizada de un perfil público.",
        metadata=dict(METADATA),
    )


def _read_rows(services, db_path):
    """Lecturas mode=ro/query_only con nombres de tabla fijos de este módulo."""
    conn = services.readonly_connection(db_path)
    try:
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ACTIVITY_TABLES}
        return dict(
            counts=counts,
            source_codes=[r[0] for r in conn.execute("SELECT code FROM ti_sources ORDER BY id")],
            topic_keys=[r[0] for r in conn.execute("SELECT topic_key FROM ti_topics ORDER BY id")],
            observation_source_ids=[r[0] for r in conn.execute(
                "SELECT DISTINCT source_id FROM ti_observations ORDER BY source_id"
            )],
            aliases=conn.execute("SELECT COUNT(*) FROM ti_topic_aliases").fetchone()[0],
        )
    finally:
        conn.close()


def _is_pilot(metadata):
    return isinstance(metadata, dict) and metadata.get("marker") == PILOT_MARKER


def check_state(services, db_path, plan=None):
    """La BD solo puede contener el sandbox limpio y el catálogo de este piloto."""
    db_path = Path(db_path)
    report = L.inspect_database(db_path)
    if report["missing_tables"]:
        raise SandboxError("DB_SCHEMA_INCOMPLETE")
    repository = services.repository(db_path, readonly=True)
    if repository.missing_tables(PILOT_REQUIRED_TABLES):
        raise SandboxError("DB_SCHEMA_INCOMPLETE")
    if report["users"] != 1:
        raise SandboxError("DB_NOT_SANDBOX:USERS")

    raw = services.readonly_lookup(db_path).get_config(L.COLLECTOR_SETTINGS_KEY)
    settings = profile_key = enabled = None
    if raw is not None:
        try:
            stored_plan, profile_key, enabled = parse_settings(
                raw, normalize_profile_key=services.normalize_profile_key,
            )
        except SandboxError as exc:
            raise SandboxError(f"COLLECTOR_SETTINGS_FOREIGN:{str(exc).split(':')[-1]}") from None
        if plan is not None and stored_plan != plan:
            raise SandboxError("CONFIG_MISMATCH")
        plan = stored_plan
        settings = json.loads(raw)

    domains = {domain.code: domain for domain in repository.list_domains()}
    if set(domains) - {DOMAIN_CODE}:
        raise SandboxError("FOREIGN_DOMAIN_PRESENT")
    domain = domains.get(DOMAIN_CODE)
    if domain is not None and (domain.metadata != METADATA or not domain.is_active):
        raise SandboxError("DOMAIN_NOT_PILOT")

    rows = _read_rows(services, db_path)
    if set(rows["source_codes"]) - {SOURCE_CODE}:
        raise SandboxError("FOREIGN_SOURCE_PRESENT")
    source = repository.get_source_by_code(SOURCE_CODE)
    if source is not None:
        expected = _expected_source(services)
        if (
            source.source_type != expected.source_type
            or source.collection_mode != expected.collection_mode
            or source.provider != expected.provider
            or source.base_url != expected.base_url
            or source.configuration != METADATA
            or not source.is_active
        ):
            raise SandboxError("SOURCE_NOT_PILOT")
    if any(sid != getattr(source, "id", None) for sid in rows["observation_source_ids"]):
        raise SandboxError("FOREIGN_OBSERVATION_PRESENT")

    allowed_topics = {plan.topic_key} if plan is not None else None
    topic = None
    alias_texts = set()
    for key in rows["topic_keys"]:
        if allowed_topics is not None and key not in allowed_topics:
            raise SandboxError("FOREIGN_TOPIC_PRESENT")
        found = repository.get_topic_by_key(key)
        if not _is_pilot(found.metadata):
            raise SandboxError("FOREIGN_TOPIC_PRESENT")
        aliases = repository.list_topic_aliases(found.id, active_only=False)
        if any(not _is_pilot(alias.metadata) for alias in aliases):
            raise SandboxError("FOREIGN_ALIAS_PRESENT")
        alias_texts.update(alias.alias_text for alias in aliases)
        topic = found
    if len(rows["topic_keys"]) > 1:
        raise SandboxError("FOREIGN_TOPIC_PRESENT")
    if plan is not None and alias_texts - {plan.hashtag}:
        raise SandboxError("FOREIGN_ALIAS_PRESENT")
    if rows["aliases"] != len(alias_texts):
        raise SandboxError("FOREIGN_ALIAS_PRESENT")

    linked = False
    if topic is not None and domain is not None:
        linked = any(link.domain_id == domain.id for link in repository.list_topic_domains(topic.id))
    catalog_complete = bool(
        plan is not None and domain is not None and source is not None and topic is not None
        and alias_texts == {plan.hashtag} and linked
    )
    return dict(
        settings=settings, plan=plan, profile_key=profile_key, enabled=enabled,
        domain_present=domain is not None, source_present=source is not None,
        topic_present=topic is not None, catalog_complete=catalog_complete,
        counts=rows["counts"],
    )


def require_empty_activity(state):
    for table, count in state["counts"].items():
        if count:
            raise SandboxError(f"DB_NOT_EMPTY:{table}")


class _CandidateLookup:
    """Settings candidatos (no guardados) sobre fuente/dominio dados."""

    def __init__(self, value, *, source_lookup, domain_lookup):
        self._value = value
        self._source, self._domain = source_lookup, domain_lookup

    def get_config(self, key, default=None):
        return json.dumps(self._value) if key == L.COLLECTOR_SETTINGS_KEY else default

    def get_source_by_code(self, code):
        return self._source(code)

    def get_domain_by_code(self, code):
        return self._domain(code)


def validate_enable_candidate(services, settings, *, source_lookup, domain_lookup):
    """El contrato real del Collector debe aceptar estos settings armados."""
    candidate = dict(settings, enabled=True)
    lookup = _CandidateLookup(candidate, source_lookup=source_lookup, domain_lookup=domain_lookup)
    try:
        startup = services.configuration_service(lookup).load()
    except ValueError:
        raise SandboxError("COLLECTOR_CONTRACT_REJECTED") from None
    config = startup.config
    if (
        startup.status != "IDLE"
        or startup.domain_code != DOMAIN_CODE
        or config.source_code != SOURCE_CODE
        or config.profile_key != settings["profile_key"]
        or config.headless is not HEADLESS
        or len(config.targets) != 1
        or config.targets[0].limit != ACCOUNT_LIMIT
        or config.targets[0].account != settings["accounts"][0]["account"]
    ):
        raise SandboxError("COLLECTOR_CONTRACT_REJECTED")


# ============================================================
# Ficheros de control en DEST
# ============================================================

def _write_exclusive(path, payload):
    """O_EXCL: nunca sobrescribe ni sigue un fichero existente."""
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True)


@contextmanager
def instance_lock(dest):
    path = Path(dest) / LOCK_NAME
    try:
        _write_exclusive(path, dict(pid=os.getpid(), work_order=WORK_ORDER))
    except FileExistsError:
        raise SandboxError("PILOT_LOCKED") from None
    try:
        yield
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def attempt_used(dest):
    return os.path.lexists(Path(dest) / ATTEMPT_NAME)


def read_result(dest):
    """Solo las claves redactadas de nuestro propio fichero de resultado."""
    path = Path(dest) / RESULT_NAME
    if not path.is_file() or L._is_link_or_reparse(path):
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return dict(status="UNREADABLE")
    if not isinstance(value, dict):
        return dict(status="UNREADABLE")
    return {key: value.get(key) for key in RESULT_KEYS}


# ============================================================
# Modos
# ============================================================

def status(target, services):
    state = check_state(services, target.db_path)
    return dict(
        status=("NOT_CONFIGURED" if state["settings"] is None
                else "ARMED" if state["enabled"] else "CONFIGURED"),
        collector_configured=state["settings"] is not None,
        collector_enabled=bool(state["enabled"]),
        catalog_complete=state["catalog_complete"],
        counts=state["counts"],
        attempt_used=attempt_used(target.dest),
        lock_present=os.path.lexists(Path(target.dest) / LOCK_NAME),
        last_result=read_result(target.dest),
    )


def configure(target, services, plan, *, profiles=None, token=secrets.token_hex):
    """Catálogo + settings enabled=false. Nunca crea runtime ni navegador."""
    db_path = Path(target.db_path)
    profiles = profiles_root() if profiles is None else Path(profiles)
    with instance_lock(target.dest):
        if attempt_used(target.dest):
            raise SandboxError("ATTEMPT_ALREADY_USED")
        state = check_state(services, db_path, plan)
        require_empty_activity(state)

        if state["settings"] is not None:
            if state["enabled"]:
                raise SandboxError("ARMED_STATE_UNEXPECTED")
            if not state["catalog_complete"]:
                raise SandboxError("CATALOG_INCOMPLETE")
            return dict(status="ALREADY_CONFIGURED", settings_written=False,
                        collector_enabled=False, catalog_complete=True)

        # Validación completa ANTES de escribir: perfil nuevo y contrato real.
        profile_key = new_profile_key(services, profiles, token=token)
        settings = build_settings(plan, profile_key)
        source, domain = _expected_source(services), _expected_domain(services)
        validate_enable_candidate(
            services, settings,
            source_lookup=lambda code: source if code == SOURCE_CODE else None,
            domain_lookup=lambda code: domain if code == DOMAIN_CODE else None,
        )

        trends = services.trend_service(services.repository.existing(db_path))
        trends.create_domain(code=domain.code, name=domain.name,
                             description=domain.description, metadata=dict(METADATA))
        trends.create_source(code=source.code, name=source.name, source_type=source.source_type,
                             provider=source.provider, base_url=source.base_url,
                             collection_mode=source.collection_mode,
                             configuration=dict(METADATA))
        trends.create_topic(topic_key=plan.topic_key, name=plan.topic_key, category=PILOT_MARKER,
                            domain_codes=(DOMAIN_CODE,), metadata=dict(METADATA))
        trends.register_topic_alias(plan.topic_key, plan.hashtag, metadata=dict(METADATA))

        # Revalida contra lo persistido y, como último paso, guarda enabled=false.
        lookup = services.readonly_lookup(db_path)
        validate_enable_candidate(services, settings, source_lookup=lookup.get_source_by_code,
                                  domain_lookup=lookup.get_domain_by_code)
        services.settings_repository(db_path).save(
            L.COLLECTOR_SETTINGS_KEY, json.dumps(settings, sort_keys=True),
        )

        after = check_state(services, db_path, plan)
        if not after["catalog_complete"] or after["enabled"] is not False:
            raise SandboxError("CONFIGURE_VERIFY_FAILED")
        L.verify_worktree(target.worktree, target.sha, expect_db=True)
        return dict(status="CONFIGURED", settings_written=True,
                    collector_enabled=False, catalog_complete=True)


def disarm_settings(services, db_path, baseline=None):
    """Devuelve enabled tras forzar false; solo sobre settings del piloto."""
    db_path = Path(db_path)
    raw = services.readonly_lookup(db_path).get_config(L.COLLECTOR_SETTINGS_KEY)
    if baseline is None:
        if raw is None:
            return False
        plan, profile_key, _ = parse_settings(raw, normalize_profile_key=services.normalize_profile_key)
        baseline = build_settings(plan, profile_key, enabled=False)
    if baseline.get("enabled") is not False:
        raise SandboxError("DISARM_BASELINE_INVALID")
    current = None
    if raw is not None:
        try:
            current = json.loads(raw)
        except ValueError:
            current = None
    if current != baseline:
        services.settings_repository(db_path).save(
            L.COLLECTOR_SETTINGS_KEY, json.dumps(baseline, sort_keys=True),
        )
    stored = json.loads(services.readonly_lookup(db_path).get_config(L.COLLECTOR_SETTINGS_KEY))
    return stored.get("enabled") is not False


def disarm(target, services):
    enabled = disarm_settings(services, target.db_path)
    return dict(status="DISARMED" if not enabled else "DISARM_FAILED", collector_enabled=enabled)


def producer_not_before(day):
    """Cierre del día UTC siguiente a la recogida."""
    return datetime.combine(day + timedelta(days=2), time(0, 0), tzinfo=timezone.utc).isoformat()


def collect(target, services, *, ack, profiles=None, clock=None):
    """Una única ejecución del controller CRM. Nunca reintenta."""
    if ack is not True:
        raise SandboxError("ACK_REAL_WEB_READ_REQUIRED")
    clock = clock or (lambda: datetime.now(timezone.utc))
    db_path = Path(target.db_path)
    profiles = profiles_root() if profiles is None else Path(profiles)

    with instance_lock(target.dest):
        if attempt_used(target.dest):
            raise SandboxError("ATTEMPT_ALREADY_USED")
        state = check_state(services, db_path)
        if state["settings"] is None:
            raise SandboxError("NOT_CONFIGURED")
        if state["enabled"] is not False:
            raise SandboxError("ARMED_STATE_UNEXPECTED")
        if not state["catalog_complete"]:
            raise SandboxError("CATALOG_INCOMPLETE")
        require_empty_activity(state)
        check_profile_slot(profiles, state["profile_key"], must_be_new=False)
        baseline = state["settings"]
        lookup = services.readonly_lookup(db_path)
        validate_enable_candidate(services, baseline, source_lookup=lookup.get_source_by_code,
                                  domain_lookup=lookup.get_domain_by_code)

        started = clock()
        # Antes de cualquier red: el intento queda consumido pase lo que pase.
        try:
            _write_exclusive(Path(target.dest) / ATTEMPT_NAME, dict(
                work_order=WORK_ORDER, started_at=started.isoformat(timespec="seconds"),
            ))
        except FileExistsError:
            raise SandboxError("ATTEMPT_ALREADY_USED") from None

        result = dict(status="NOT_STARTED", created=0, duplicates=0, total=0,
                      cleanup="NOT_REQUIRED", collection_started=False)
        control = services.control_service(
            lookup=lookup,
            repository=services.repository(db_path, readonly=True),
            save_setting=services.settings_repository(db_path).save,
            runtime_factory=services.runtime_factory,
        )
        enabled = True
        try:
            try:
                control.save(True, [state["plan"].account], ACCOUNT_LIMIT)
            except ValueError:
                result["status"] = "ARM_FAILED"
            else:
                result["collection_started"] = True
                future = control.execute()
                if future is None:
                    result["status"] = "ERROR"
                else:
                    future.result()
                    closing = control.close()
                    if closing is not None:
                        closing.result(timeout=CLEANUP_TIMEOUT_SECONDS)
                    current = control.state()
                    latest = current["latest"] or {}
                    result["status"] = latest.get("status") or "ERROR"
                    report = latest.get("result")
                    for key in ("created", "duplicates", "total"):
                        value = getattr(report, key, 0)
                        result[key] = value if type(value) is int else 0
                    if current["retained"]:
                        result["status"] = result["cleanup"] = "CLEANUP_REQUIRED"
                    elif result["status"] == "CLEANUP_REQUIRED":
                        # Retenido en la ejecución, liberado por close()/retry_cleanup.
                        result["cleanup"] = "RELEASED_ON_RETRY"
        except KeyboardInterrupt:
            result["status"] = "INTERRUPTED"
        except Exception as exc:
            result["status"] = "ERROR"
            result["error"] = f"UNEXPECTED:{type(exc).__name__}"
        finally:
            try:
                enabled = disarm_settings(services, db_path, baseline)
            except Exception:
                enabled = True
        result["collector_enabled"] = enabled
        if enabled:
            result["status"] = "DISARM_FAILED"

        try:
            L.verify_worktree(target.worktree, target.sha, expect_db=True)
            result["worktree_verified_after"] = True
        except SandboxError as exc:
            result["worktree_verified_after"] = False
            result["worktree_problem"] = str(exc).split(":")[0]

        try:
            _write_exclusive(Path(target.dest) / RESULT_NAME,
                             {key: result.get(key) for key in RESULT_KEYS})
            result["result_recorded"] = True
        except OSError:
            result["result_recorded"] = False
        result["producer_not_before_utc"] = (
            producer_not_before(started.astimezone(timezone.utc).date())
            if result["status"] == "SUCCESS" else None
        )
        return result


# ============================================================
# CLI
# ============================================================

SAFE_ERROR = re.compile(r"[A-Za-z0-9_.:]{1,120}")


def _safe_error(exc):
    text = str(exc)
    return text if SAFE_ERROR.fullmatch(text) else text.split(":")[0][:80]


def _base_report(mode, status):
    return dict(work_order=WORK_ORDER, mode=mode, status=status, real_pilot=True,
                domain_code=DOMAIN_CODE, source_code=SOURCE_CODE,
                producer_run="NOT_EXECUTED")


def run(args, *, repo_root=REPO_ROOT, cwd=None, profiles=None):
    mode = mode_of(args)
    check_arguments(args, mode)
    if mode == "COLLECT" and not args.ack_real_web_read:
        raise SandboxError("ACK_REAL_WEB_READ_REQUIRED")
    plan = build_plan(args.account, args.topic_key, args.hashtag) if mode == "CONFIGURE" else None
    target = validate(args.dest, repo_root=repo_root, cwd=cwd)
    services = import_services(target)
    if mode == "CONFIGURE":
        result = configure(target, services, plan, profiles=profiles)
    elif mode == "COLLECT":
        result = collect(target, services, ack=args.ack_real_web_read, profiles=profiles)
    elif mode == "DISARM":
        result = disarm(target, services)
    else:
        result = status(target, services)
    report = _base_report(mode, result.pop("status"))
    report.update(result, sha=target.sha)
    report.setdefault("collector_enabled", False)
    return report


def mode_of(args):
    if args.configure:
        return "CONFIGURE"
    if args.collect:
        return "COLLECT"
    if args.disarm:
        return "DISARM"
    return "STATUS"


def check_arguments(args, mode):
    if not args.dest:
        raise SandboxError("DEST_REQUIRED")
    if mode != "CONFIGURE" and (args.account or args.topic_key or args.hashtag):
        raise SandboxError("CONFIGURE_ARGUMENTS_ONLY_WITH_CONFIGURE")
    if mode != "COLLECT" and args.ack_real_web_read:
        raise SandboxError("ACK_ONLY_WITH_COLLECT")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Piloto real Instagram (un perfil, máx. 5) sobre el sandbox CRM sellado.",
    )
    parser.add_argument("--dest", help="Directorio del sandbox sellado (absoluto, bajo TEMP)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--configure", action="store_true")
    mode.add_argument("--collect", action="store_true")
    mode.add_argument("--disarm", action="store_true")
    parser.add_argument("--account", action="append", help="Una única cuenta pública")
    parser.add_argument("--topic-key")
    parser.add_argument("--hashtag")
    parser.add_argument("--ack-real-web-read", action="store_true",
                        help="Autoriza la lectura web real en --collect")
    return parser


class _RedactingFormatter(logging.Formatter):
    """Logs del runtime sin mensajes ni trazas: pueden contener cuenta/URL."""

    def format(self, record):
        kind = record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else "-"
        return f"{record.levelname} {record.name} exc={kind}"


def _install_redacted_logging():
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_RedactingFormatter())
    logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)


def main(argv=None):
    args = build_parser().parse_args(argv)
    mode = mode_of(args)
    _install_redacted_logging()
    try:
        report = run(args)
        code = 0 if report["status"] in {
            "NOT_CONFIGURED", "CONFIGURED", "ARMED", "ALREADY_CONFIGURED", "DISARMED", "SUCCESS",
        } else 1
        if report.get("collector_enabled") is True and mode != "STATUS":
            code = 3
    except SandboxError as exc:
        report = _base_report(mode, "BLOCKED")
        report.update(error=_safe_error(exc), collector_enabled=None)
        code = 2
    except Exception as exc:
        # Sin mensaje: podría arrastrar rutas, cuentas o valores no auditados.
        report = _base_report(mode, "BLOCKED")
        report.update(error=f"UNEXPECTED:{type(exc).__name__}", collector_enabled=None)
        code = 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
