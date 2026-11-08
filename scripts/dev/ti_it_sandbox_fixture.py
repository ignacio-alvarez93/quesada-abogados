"""
Fixture sintética de catálogo y observaciones IT para el sandbox CRM.

VERSIÓN DE DESARROLLO (WO TI-4C.3D). Fail-closed. Solo opera sobre la BD
sintética generada por scripts/dev/crm_it_sandbox_launcher.py --prepare y
SOLO cuando se ejecuta desde el checkout temporal sellado (<DEST>/crm).

--dest DIR             Revalida sello, worktree y BD y muestra un preview
                       JSON sin escrituras (modo por defecto).
--dest DIR --execute   Además siembra, con los servicios existentes:
                       dominio SANDBOX_MARKETING, fuente SOCIAL/SELENIUM
                       solo de catálogo, topics MODA y MODA_URBANA con
                       aliases y 8 observaciones SYNTHETIC_SANDBOX en días
                       UTC completos anteriores a hoy. Idempotente.

Nunca acepta una --db-path libre, no lee .env ni credenciales, no abre
navegador ni red, no arranca el Collector ni el productor y no crea
señales ni snapshots: solo el productor real puede calcularlos después.

La configuración IT_INSTAGRAM_COLLECTOR_V1 se guarda con enabled=false,
domain_code sintético, source_code ficticio y sin profile_key. Habilitarla
desde la UI falla cerrado: la fuente sintética no es una fuente Instagram
válida para el contrato del Collector y no hay perfil gobernado.

Uso por fases (Git Bash; sustituir <SHA>, <DEST> y las fechas del informe):

    # 0) Tras integrar este código, preparar un sandbox nuevo a ese SHA.
    python scripts/dev/crm_it_sandbox_launcher.py --prepare \\
        --dest "$TEMP/quesada-it-synth-01" --sha <SHA>

    # 1) Desde el checkout sellado: preview sin escrituras.
    cd "<DEST>/crm"
    python -E -B scripts/dev/ti_it_sandbox_fixture.py --dest "<DEST>"

    # 2) Siembra explícita (idempotente).
    python -E -B scripts/dev/ti_it_sandbox_fixture.py --dest "<DEST>" --execute

    # 3) SOLO el operador, tras auditoría independiente, sobre el MISMO
    #    fichero comprobado y desde el mismo checkout sellado:
    python -E -B scripts/trend_producer_run.py \\
        --db-path "<DEST>/crm/database/quesada.db" \\
        --domain-code SANDBOX_MARKETING --topic MODA --topic MODA_URBANA \\
        --from-date <producer_window.from_date> \\
        --to-date <producer_window.to_date> \\
        --execute --allow-operational-db

    # 4) Ver IT / Tendencias en el CRM sandbox.
    python scripts/dev/crm_it_sandbox_launcher.py --launch --dest "<DEST>"

--allow-operational-db: trend_producer_run.py trata como operativa toda
base llamada quesada.db. La BD sintética comparte ese nombre porque todas
las rutas del CRM la derivan así; el flag NO desactiva el guard, es la
confirmación explícita del operador de que --db-path es exactamente la BD
sintética validada aquí (ruta absoluta bajo <DEST>). Nunca debe usarse con
otra ruta.
"""

import argparse
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_PATH = Path(__file__).resolve().parent / "crm_it_sandbox_launcher.py"


def _load_launcher():
    spec = importlib.util.spec_from_file_location("crm_it_sandbox_launcher", LAUNCHER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


L = _load_launcher()
SandboxError = L.SandboxError

SYNTHETIC_MARKER = "SYNTHETIC_SANDBOX"
FIXTURE_ID = "TI-4C.3D"
SANDBOX_USER_PATTERN = re.compile(r"sandbox_[0-9a-f]{8}")

DOMAIN_CODE = "SANDBOX_MARKETING"
SOURCE_CODE = "SANDBOX_SYNTHETIC_SOCIAL"
SOURCE_TYPE = "SOCIAL"
SOURCE_COLLECTION_MODE = "SELENIUM"
SOURCE_PROVIDER = SYNTHETIC_MARKER

METADATA = dict(synthetic=True, marker=SYNTHETIC_MARKER, fixture=FIXTURE_ID)

# Valor exacto que la fixture admite en config_global: nunca enabled.
COLLECTOR_SETTINGS = dict(
    enabled=False,
    domain_code=DOMAIN_CODE,
    source_code=SOURCE_CODE,
    synthetic=True,
)

TOPICS = (
    dict(topic_key="MODA", name="Moda (sintético)", parent=None,
         aliases=("fashion", "tendencia_moda")),
    dict(topic_key="MODA_URBANA", name="Moda urbana (sintético)", parent="MODA",
         aliases=("streetwear", "moda_calle")),
)

# (días antes de la fecha de referencia, topic, hashtags). Cada observación
# resuelve exactamente un topic; "sandbox" no coincide con ninguno.
OBSERVATIONS = (
    (6, "MODA", ("moda", "sandbox")),
    (5, "MODA", ("fashion",)),
    (4, "MODA_URBANA", ("streetwear",)),
    (3, "MODA", ("tendencia_moda", "moda")),
    (2, "MODA_URBANA", ("moda_urbana",)),
    (2, "MODA_URBANA", ("moda_calle", "sandbox")),
    (1, "MODA_URBANA", ("streetwear", "moda_urbana")),
    (1, "MODA_URBANA", ("moda_calle",)),
)

DOMAIN_OBSERVATION_LIMIT = 200

MODULES = (
    "database.connection",
    "backend.repositories.sqlite_trend_intelligence_repository",
    "backend.repositories.instagram_collector_settings_repository",
    "backend.trend_intelligence.service",
)


# ============================================================
# Barreras
# ============================================================

@dataclass(frozen=True)
class Target:
    dest: Path
    worktree: Path
    sha: str
    db_path: Path
    username: str


def validate_target(dest, *, repo_root=REPO_ROOT, cwd=None):
    """Sello, checkout sellado, cwd y BD del sello; nunca escribe."""
    if not dest:
        raise SandboxError("DEST_REQUIRED")
    raw = Path(dest)
    if not raw.is_absolute():
        raise SandboxError("DEST_NOT_ABSOLUTE")

    repo_root = Path(repo_root).resolve()
    expected_worktree = raw.resolve() / L.WORKTREE_NAME
    if not L._same_path(repo_root, expected_worktree):
        raise SandboxError("NOT_RUNNING_FROM_SEALED_CHECKOUT")
    cwd = Path.cwd() if cwd is None else Path(cwd)
    if not L._same_path(cwd.resolve(), repo_root):
        raise SandboxError("CWD_NOT_SEALED_CHECKOUT")

    # TEMP, enlaces, solapes con checkouts, sello, HEAD desacoplado al SHA,
    # worktree limpio, BD existente y rutas efectivas (sondeo interno).
    dest, worktree = L.validate_launch(dest, repo_root=repo_root)
    seal = L.read_seal(dest)

    db_path = Path(seal["db_path"])
    if not L._same_path(db_path, worktree / L.DB_RELATIVE):
        raise SandboxError("SEAL_DB_PATH_MISMATCH")
    if not db_path.is_file() or L._is_link_or_reparse(db_path):
        raise SandboxError("SANDBOX_DB_MISSING")
    username = str(seal.get("username") or "")
    if not SANDBOX_USER_PATTERN.fullmatch(username):
        raise SandboxError("SEAL_USER_NOT_SYNTHETIC")

    return Target(dest=dest, worktree=worktree, sha=seal["sha"],
                  db_path=db_path, username=username)


@dataclass(frozen=True)
class Services:
    trend_service: type
    repository: type
    settings_repository: type
    readonly_lookup: type


def import_services(target):
    """Servicios existentes del checkout sellado; DB_PATH debe ser la del sello."""
    _, loaded = L._import_from_worktree(target.worktree, MODULES)
    connection = loaded["database.connection"]
    repository = loaded["backend.repositories.sqlite_trend_intelligence_repository"]
    for value in (connection.DB_PATH, repository.DEFAULT_DB_PATH):
        if not L._same_path(Path(value).resolve(), target.db_path):
            raise SandboxError("EFFECTIVE_DB_PATH_MISMATCH")
    return Services(
        trend_service=loaded["backend.trend_intelligence.service"].TrendIntelligenceService,
        repository=repository.SQLiteTrendIntelligenceRepository,
        settings_repository=loaded[
            "backend.repositories.instagram_collector_settings_repository"
        ].SQLiteInstagramCollectorSettingsRepository,
        readonly_lookup=repository.SQLiteTrendIntelligenceReadOnlyLookup,
    )


def _is_synthetic(metadata):
    return isinstance(metadata, dict) and metadata.get("marker") == SYNTHETIC_MARKER


def check_synthetic(services, db_path):
    """Lecturas mode=ro: la BD solo puede contener el sandbox y esta fixture."""
    db_path = Path(db_path)
    report = L.inspect_database(db_path)
    if report["missing_tables"]:
        raise SandboxError("DB_SCHEMA_INCOMPLETE")
    if report["users"] != 1:
        raise SandboxError("DB_NOT_SYNTHETIC:USERS")

    raw = services.readonly_lookup(db_path).get_config(L.COLLECTOR_SETTINGS_KEY)
    if raw is not None:
        try:
            settings = json.loads(raw)
        except ValueError:
            raise SandboxError("COLLECTOR_SETTINGS_NOT_SYNTHETIC") from None
        if settings != COLLECTOR_SETTINGS:
            raise SandboxError("COLLECTOR_SETTINGS_NOT_SYNTHETIC")

    repository = services.repository(db_path, readonly=True)
    domains = {domain.code: domain for domain in repository.list_domains()}
    if set(domains) - {DOMAIN_CODE}:
        raise SandboxError("FOREIGN_DOMAIN_PRESENT")
    domain = domains.get(DOMAIN_CODE)
    if domain is not None and not _is_synthetic(domain.metadata):
        raise SandboxError("DOMAIN_NOT_SYNTHETIC")

    source = repository.get_source_by_code(SOURCE_CODE)
    if source is not None:
        if (
            source.source_type != SOURCE_TYPE
            or source.collection_mode != SOURCE_COLLECTION_MODE
            or source.provider != SOURCE_PROVIDER
            or source.base_url is not None
            or not _is_synthetic(source.configuration)
        ):
            raise SandboxError("SOURCE_NOT_SYNTHETIC")
        # Ninguna recogida real ni simulada: el Collector nunca ha corrido.
        if repository.list_collector_runs(source.id):
            raise SandboxError("COLLECTOR_RUNS_PRESENT")

    observations = ()
    if domain is not None:
        observations = repository.list_domain_observations(
            domain.id, limit=DOMAIN_OBSERVATION_LIMIT,
        )
        planned = {external_id(index) for index in range(len(OBSERVATIONS))}
        for observation, _ in observations:
            if (
                observation.external_id not in planned
                or not _is_synthetic(observation.metadata)
                or source is None
                or observation.source_id != source.id
            ):
                raise SandboxError("FOREIGN_OBSERVATION_PRESENT")

    return dict(
        collector_settings_present=raw is not None,
        domain_present=domain is not None,
        observations_present=len(observations),
    )


# ============================================================
# Plan sintético
# ============================================================

def external_id(index):
    return f"{SYNTHETIC_MARKER}-{FIXTURE_ID}-{index + 1:03d}"


def build_observations(today):
    """Determinista respecto a la fecha UTC de referencia `today`."""
    if not isinstance(today, date) or isinstance(today, datetime):
        raise SandboxError("REFERENCE_DATE_INVALID")
    midnight = datetime.combine(today, time(0, 0), tzinfo=timezone.utc)
    planned = []
    for index, (days_ago, topic_key, hashtags) in enumerate(OBSERVATIONS):
        observed_at = midnight - timedelta(days=days_ago) + timedelta(hours=10, minutes=index)
        tags = " ".join(f"#{tag}" for tag in hashtags)
        planned.append(dict(
            external_id=external_id(index),
            observation_type="POST",
            body_text=f"[{SYNTHETIC_MARKER}] Publicación ficticia {index + 1} sin datos reales. {tags}",
            author=f"autor_ficticio_{index % 3 + 1}",
            published_at=observed_at,
            observed_at=observed_at,
            language="es",
            country="ES",
            metadata=dict(
                METADATA,
                hashtags=list(hashtags),
                expected_topic=topic_key,
                metrics=dict(like_count=10 * (index + 1), comment_count=index, view_count=None),
            ),
        ))
    return tuple(planned)


def _producer_window(observed):
    days = sorted({datetime.fromisoformat(value).astimezone(timezone.utc).date()
                   for value in observed})
    if not days:
        return None
    return dict(from_date=days[0].isoformat(),
                to_date=(days[-1] + timedelta(days=1)).isoformat())


# ============================================================
# Siembra
# ============================================================

def seed(services, db_path, *, today):
    """Solo servicios/repositorios existentes, sobre la BD existente (mode=rw)."""
    db_path = Path(db_path)
    planned = build_observations(today)
    state = check_synthetic(services, db_path)
    trends = services.trend_service(services.repository.existing(db_path))

    trends.create_domain(
        code=DOMAIN_CODE,
        name="Sandbox Marketing (sintético)",
        description="Dominio de demostración SYNTHETIC_SANDBOX; sin datos reales.",
        metadata=dict(METADATA),
    )
    trends.create_source(
        code=SOURCE_CODE,
        name="Fuente social ficticia (solo catálogo)",
        source_type=SOURCE_TYPE,
        provider=SOURCE_PROVIDER,
        base_url=None,
        collection_mode=SOURCE_COLLECTION_MODE,
        configuration=dict(METADATA, catalog_only=True),
    )
    aliases = 0
    for topic in TOPICS:
        trends.create_topic(
            topic_key=topic["topic_key"],
            name=topic["name"],
            category=SYNTHETIC_MARKER,
            parent_topic_key=topic["parent"],
            domain_codes=(DOMAIN_CODE,),
            metadata=dict(METADATA),
        )
        for alias in topic["aliases"]:
            trends.register_topic_alias(topic["topic_key"], alias, metadata=dict(METADATA))
            aliases += 1

    created, observed = 0, []
    for item in planned:
        observation, is_new = trends.record_observation(source_code=SOURCE_CODE, **item)
        # Vínculo de dominio sin topic: el productor clasificará por hashtags.
        trends.assign_observation_domain(
            observation.id, DOMAIN_CODE, detection_method=SYNTHETIC_MARKER,
        )
        created += int(is_new)
        observed.append(observation.observed_at)

    # Último paso: el dashboard solo apunta al dominio con el catálogo completo.
    settings_written = False
    if not state["collector_settings_present"]:
        services.settings_repository(db_path).save(
            L.COLLECTOR_SETTINGS_KEY, json.dumps(COLLECTOR_SETTINGS, sort_keys=True),
        )
        settings_written = True

    after = check_synthetic(services, db_path)
    return dict(
        topics=[topic["topic_key"] for topic in TOPICS],
        aliases=aliases,
        observations=dict(planned=len(planned), created=created,
                          existing=len(planned) - created, total=after["observations_present"]),
        collector=dict(enabled=False, settings_written=settings_written),
        producer_window=_producer_window(observed),
    )


def preview(services, db_path, *, today):
    state = check_synthetic(services, db_path)
    planned = build_observations(today)
    return dict(
        topics=[topic["topic_key"] for topic in TOPICS],
        aliases=sum(len(topic["aliases"]) for topic in TOPICS),
        observations=dict(planned=len(planned), created=0, existing=state["observations_present"],
                          total=state["observations_present"]),
        collector=dict(enabled=False, settings_written=False),
        producer_window=_producer_window(item["observed_at"].isoformat() for item in planned),
    )


# ============================================================
# CLI
# ============================================================

def _base_report(status):
    return dict(status=status, synthetic=True, marker=SYNTHETIC_MARKER, fixture=FIXTURE_ID,
                domain_code=DOMAIN_CODE, source_code=SOURCE_CODE,
                producer_run="NOT_EXECUTED", collector_started=False)


def run(dest, *, execute, repo_root=REPO_ROOT, today=None):
    today = today or datetime.now(timezone.utc).date()
    target = validate_target(dest, repo_root=repo_root)
    services = import_services(target)
    if execute:
        result = seed(services, target.db_path, today=today)
        # Tras escribir: mismo SHA, desacoplado, limpio y sin ficheros nuevos.
        L.verify_worktree(target.worktree, target.sha, expect_db=True)
    else:
        result = preview(services, target.db_path, today=today)
    report = _base_report("SEEDED" if execute else "PREVIEW")
    report.update(result, execute=bool(execute), reference_date=today.isoformat(),
                  sha=target.sha, dest=str(target.dest), worktree=str(target.worktree),
                  db_path=str(target.db_path))
    return report


def build_parser():
    parser = argparse.ArgumentParser(
        description="Fixture sintética IT para el sandbox CRM (fail-closed, preview por defecto).",
    )
    parser.add_argument("--dest", help="Directorio del sandbox sellado (absoluto, bajo TEMP)")
    parser.add_argument("--execute", action="store_true",
                        help="Escribe la fixture; sin él solo se valida y previsualiza")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        report = run(args.dest, execute=args.execute)
        code = 0
    except SandboxError as exc:
        report = _base_report("BLOCKED")
        report.update(execute=bool(args.execute), error=str(exc)[:400])
        code = 2
    except Exception as exc:
        # Sin mensaje: podría arrastrar rutas o valores no auditados.
        report = _base_report("BLOCKED")
        report.update(execute=bool(args.execute), error=f"UNEXPECTED:{type(exc).__name__}")
        code = 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
