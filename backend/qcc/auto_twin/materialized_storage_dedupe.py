"""Deduplicación física (hardlinks) de revisiones materializadas AUTO TWIN.

Contrato:

- el layout público matrev-*/ NO cambia; cada revisión sigue siendo
  lógicamente completa e inmutable;
- dos rutas comparten inode solo si su contenido completo es idéntico
  y está probado con SHA-256 (nunca por nombre, ruta o tamaño);
- es una optimización: si un hardlink falla, el archivo normal se
  conserva y la materialización continúa;
- el reemplazo es atómico (link temporal + os.replace) y falla cerrado;
- nunca borra archivos lógicos ni revisiones;
- solo usa primitivas de filesystem de Python (sin mklink/fsutil).

Modelo de shards: un SHA-256 mapea a una lista de inodes canónicos
("shards"), cada uno con un máximo seguro de hardlinks
(``AUTO_TWIN_STORAGE_HARDLINK_TARGET_MAX``, por debajo del techo real del
filesystem). Un canónico con ``st_nlink >= cap`` está saturado: se
conserva intacto y el siguiente archivo idéntico pasa a ser un nuevo
shard. La rotación ocurre ANTES de llamar a ``os.link``; un fallo
inesperado de ``os.link`` por debajo del cap nunca se interpreta como
saturación.

Auditoría de inmutabilidad: ningún código de producción escribe dentro de
un matrev-* ya publicado (el builder escribe solo en staging y publica con
os.rename; el store solo agrega manifest.json en la primera escritura).
``manifest.json`` se excluye igualmente de la deduplicación.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat as _stat
import uuid


AUTO_TWIN_STORAGE_DEDUPE_MIN_BYTES = 16 * 1024

AUTO_TWIN_STORAGE_DEDUPE_SEED_REVISIONS = 4

# Techo real observado: 1024 links por inode. Se usa un objetivo
# conservador por debajo.
AUTO_TWIN_STORAGE_HARDLINK_TARGET_MAX = 1000

_SEED_MAX_INODES_PER_KEY = 16

_REVISION_DIR_RE = re.compile(
    r"^matrev-[0-9a-f]{24}$"
)

_EXCLUDED_ROOT_FILES = frozenset({
    "manifest.json",
})

_TEMP_PREFIX = ".dedupe-"

_CHUNK = 1024 * 1024


class StorageDedupeError(Exception):
    """Verificación o link fallido; el destino quedó sin modificar."""


def sha256_file(path) -> str:
    digest = hashlib.sha256()

    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


def _same_file(a, b) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def is_revision_directory_name(name) -> bool:
    return bool(
        _REVISION_DIR_RE.fullmatch(
            str(name)
        )
    )


def list_revision_directories(twin_root) -> list:
    """Solo directorios reales matrev-* con manifest.json."""

    root = Path(twin_root)

    if not root.is_dir():
        return []

    result = []

    for entry in sorted(
        root.iterdir(),
        key=lambda item: item.name,
    ):
        if not is_revision_directory_name(
            entry.name
        ):
            continue

        if entry.is_symlink() or not entry.is_dir():
            continue

        if not (entry / "manifest.json").is_file():
            continue

        result.append(entry)

    return result


def replace_with_hardlink(
    canonical,
    destination,
    expected_sha256,
    *,
    verify_canonical=True,
    verify_link_hash=True,
    link_cap=None,
) -> str:
    """Reemplaza ``destination`` por un hardlink a ``canonical``.

    Devuelve ``"linked"`` o ``"already_linked"``. Lanza
    ``StorageDedupeError`` sin modificar el destino si algo falla antes
    del reemplazo.
    """

    canonical = Path(canonical)
    destination = Path(destination)

    if canonical.is_symlink() or destination.is_symlink():
        raise StorageDedupeError("SYMLINK_REFUSED")

    if not canonical.is_file() or not destination.is_file():
        raise StorageDedupeError("NOT_REGULAR_FILE")

    if _same_file(canonical, destination):
        return "already_linked"

    if link_cap is not None:
        try:
            canonical_nlink = canonical.stat().st_nlink
        except OSError as error:
            raise StorageDedupeError(
                "CANONICAL_STAT_FAILED:" + type(error).__name__
            ) from error

        if canonical_nlink >= link_cap:
            raise StorageDedupeError("CANONICAL_AT_SAFE_CAP")

    try:
        if (
            verify_canonical
            and sha256_file(canonical) != expected_sha256
        ):
            raise StorageDedupeError("CANONICAL_HASH_MISMATCH")

        if sha256_file(destination) != expected_sha256:
            raise StorageDedupeError("DESTINATION_HASH_MISMATCH")
    except OSError as error:
        raise StorageDedupeError(
            "HASH_READ_FAILED:" + type(error).__name__
        ) from error

    temporary = destination.with_name(
        _TEMP_PREFIX
        + uuid.uuid4().hex
        + ".tmp"
    )

    try:
        try:
            os.link(canonical, temporary)
        except OSError as error:
            raise StorageDedupeError(
                "LINK_FAILED:" + type(error).__name__
            ) from error

        if not _same_file(temporary, canonical):
            raise StorageDedupeError("TEMP_LINK_NOT_SAMEFILE")

        if (
            verify_link_hash
            and sha256_file(temporary) != expected_sha256
        ):
            raise StorageDedupeError("TEMP_LINK_HASH_MISMATCH")

        try:
            os.replace(temporary, destination)
        except OSError as error:
            raise StorageDedupeError(
                "REPLACE_FAILED:" + type(error).__name__
            ) from error

    finally:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass

    if not _same_file(destination, canonical):
        raise StorageDedupeError("POST_REPLACE_NOT_SAMEFILE")

    if (
        verify_link_hash
        and sha256_file(destination) != expected_sha256
    ):
        raise StorageDedupeError("POST_REPLACE_HASH_MISMATCH")

    return "linked"


# ----------------------------------------------------------------------
# Future revisions: dedupe staged revision before publication
# ----------------------------------------------------------------------

def _seed_index(
    twin_root,
    *,
    seed_revisions,
    min_bytes,
) -> dict:
    """Índice acotado (sha256, size) -> [rutas de inodes distintos], desde
    las N revisiones publicadas más recientes. No escanea todo el
    historial. Una clave puede tener varios canónicos (shards)."""

    revisions = list_revision_directories(twin_root)

    revisions.sort(
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )

    index = {}
    seen_inodes = {}

    for revision in revisions[:max(0, int(seed_revisions))]:
        try:
            manifest = json.loads(
                (revision / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, ValueError):
            continue

        for item in manifest.get("artifact_manifest") or ():
            try:
                key = (
                    str(item["sha256"]),
                    int(item["size_bytes"]),
                )
                relative = str(item["path"])
            except (KeyError, TypeError, ValueError):
                continue

            if key[1] < min_bytes:
                continue

            paths = index.setdefault(key, [])
            inodes = seen_inodes.setdefault(key, set())

            if len(paths) >= _SEED_MAX_INODES_PER_KEY:
                continue

            path = revision / relative

            try:
                info = path.stat()
            except OSError:
                continue

            identity = (info.st_dev, info.st_ino)

            if identity in inodes:
                continue

            inodes.add(identity)
            paths.append(path)

    return index


def _nlink(path):
    try:
        return Path(path).stat().st_nlink
    except OSError:
        return None


def dedupe_staged_revision(
    staging,
    *,
    twin_root,
    artifact_manifest,
    min_bytes=AUTO_TWIN_STORAGE_DEDUPE_MIN_BYTES,
    seed_revisions=AUTO_TWIN_STORAGE_DEDUPE_SEED_REVISIONS,
    link_cap=AUTO_TWIN_STORAGE_HARDLINK_TARGET_MAX,
) -> dict:
    """Optimización best-effort sobre un staging aún no publicado.

    Nunca lanza. ``artifact_manifest`` provee sha256/size ya calculados
    del staging; todo candidato se re-verifica antes de enlazar. Si todos
    los canónicos conocidos están saturados (``st_nlink >= link_cap``) la
    copia normal del staging pasa a ser un nuevo shard canónico.
    """

    stats = {
        "linked": 0,
        "linked_bytes": 0,
        "failed": 0,
        "considered": 0,
        "new_shards": 0,
    }

    try:
        staging = Path(staging)

        external = _seed_index(
            twin_root,
            seed_revisions=seed_revisions,
            min_bytes=min_bytes,
        )

        # key -> [[canonical path, canonical verified], ...]
        canonicals = {}

        for item in artifact_manifest:
            try:
                size = int(item["size_bytes"])
                sha = str(item["sha256"])
                relative = str(item["path"])
            except (KeyError, TypeError, ValueError):
                continue

            if size < min_bytes or relative in _EXCLUDED_ROOT_FILES:
                continue

            stats["considered"] += 1

            key = (sha, size)
            destination = staging / relative

            try:
                if key not in canonicals:
                    canonicals[key] = [
                        [candidate, False]
                        for candidate in external.get(key, ())
                    ]

                entries = canonicals[key]

                if any(entry[0] == destination for entry in entries):
                    continue

                chosen = None

                for entry in list(entries):
                    nlink = _nlink(entry[0])

                    if nlink is None:
                        entries.remove(entry)
                        continue

                    if nlink >= link_cap:
                        continue

                    chosen = entry
                    break

                if chosen is None:
                    # Todos saturados (o ninguno): esta copia es un shard.
                    entries.append([destination, True])
                    stats["new_shards"] += 1
                    continue

                try:
                    outcome = replace_with_hardlink(
                        chosen[0],
                        destination,
                        sha,
                        verify_canonical=not chosen[1],
                        verify_link_hash=False,
                        link_cap=link_cap,
                    )
                except StorageDedupeError:
                    if chosen[1] is False:
                        # candidato externo inválido: descartarlo.
                        entries.remove(chosen)

                        if not entries:
                            entries.append([destination, True])

                    raise

                chosen[1] = True

                if outcome == "linked":
                    stats["linked"] += 1
                    stats["linked_bytes"] += size

            except Exception:
                stats["failed"] += 1

    except Exception:
        stats["failed"] += 1

    return stats


# ----------------------------------------------------------------------
# Historical migrator
# ----------------------------------------------------------------------

def _iter_revision_files(revision):
    for current, directories, files in os.walk(revision):
        directories.sort()

        for name in sorted(files):
            path = Path(current) / name

            if name.startswith(_TEMP_PREFIX):
                continue

            if path.parent == revision and name in _EXCLUDED_ROOT_FILES:
                yield path, None
                continue

            yield path, path.lstat()


def plan_hash_shards(groups, link_cap) -> tuple:
    """Plan de shards para un mismo SHA-256 (función pura).

    ``groups``: lista de ``(inode, paths, nlink)``. Devuelve
    ``(moves, shard_count)`` donde ``moves`` es una lista de
    ``(canonical_path, group_paths, fully_freed)``.

    Los grupos con ``nlink >= link_cap`` están saturados: válidos, sin
    tocar, cada uno es un shard. Los demás se agrupan en shards nuevos
    hasta ``link_cap``; nunca se crean copias físicas adicionales.
    """

    saturated = [g for g in groups if g[2] >= link_cap]
    pending = sorted(
        (g for g in groups if g[2] < link_cap),
        key=lambda g: (-g[2], str(g[1][0])),
    )

    moves = []
    shard_count = len(saturated)

    while pending:
        canonical = pending.pop(0)
        shard_count += 1

        room = link_cap - canonical[2]
        rest = []

        for group in pending:
            if len(group[1]) <= room:
                room -= len(group[1])
                moves.append((
                    canonical[1][0],
                    group[1],
                    group[2] <= len(group[1]),
                ))
            else:
                rest.append(group)

        pending = rest

    return moves, shard_count


def plan_twin_root(
    twin_root,
    *,
    min_bytes=AUTO_TWIN_STORAGE_DEDUPE_MIN_BYTES,
    link_cap=AUTO_TWIN_STORAGE_HARDLINK_TARGET_MAX,
) -> dict:
    """Solo lectura. Calcula qué duplicados físicos pueden enlazarse."""

    root = Path(twin_root).resolve()

    if not root.is_dir():
        raise ValueError("QCC_AUTO_TWIN_STORAGE_ROOT_INVALID")

    revisions = list_revision_directories(root)

    files = []  # (path, size, dev, ino, nlink, eligible)

    for revision in revisions:
        for path, info in _iter_revision_files(revision):
            if info is None:
                continue

            if not _stat.S_ISREG(info.st_mode):
                continue

            files.append((
                path,
                info.st_size,
                info.st_dev,
                info.st_ino,
                info.st_nlink,
            ))

    logical_bytes = sum(item[1] for item in files)

    # Un inode físico se cuenta una sola vez.
    inode_size = {}

    for path, size, dev, ino, _nlink in files:
        inode_size[(dev, ino)] = size

    physical_bytes = sum(inode_size.values())

    # Solo puede haber duplicado si otro inode tiene el mismo tamaño.
    by_size = {}

    for path, size, dev, ino, nlink in files:
        if size >= min_bytes:
            by_size.setdefault(size, {}).setdefault(
                (dev, ino), []
            ).append((path, nlink))

    candidates = {
        size: inodes
        for size, inodes in by_size.items()
        if len(inodes) > 1
    }

    by_hash = {}
    hash_errors = []

    for size, inodes in candidates.items():
        for inode, paths in inodes.items():
            paths.sort(key=lambda item: str(item[0]))

            try:
                digest = sha256_file(paths[0][0])
            except OSError as error:
                hash_errors.append(
                    (str(paths[0][0]), type(error).__name__)
                )
                continue

            by_hash.setdefault((digest, size), []).append(
                (inode, [p for p, _ in paths], paths[0][1])
            )

    operations = []
    duplicate_bytes_inodes = 0
    shards_by_hash = {}

    for (digest, size), inode_groups in by_hash.items():
        if len(inode_groups) < 2:
            continue

        moves, shard_count = plan_hash_shards(
            inode_groups,
            link_cap,
        )

        shards_by_hash[digest] = shard_count

        for canonical, paths, freed in moves:
            if freed:
                duplicate_bytes_inodes += size

            for path in paths:
                operations.append({
                    "canonical": canonical,
                    "destination": path,
                    "sha256": digest,
                    "size_bytes": size,
                })

    operations.sort(key=lambda item: str(item["destination"]))

    savings = duplicate_bytes_inodes
    unique_bytes = physical_bytes - savings

    return {
        "root": root,
        "revision_count": len(revisions),
        "file_count": len(files),
        "min_bytes": min_bytes,
        "logical_bytes": logical_bytes,
        "current_physical_bytes": physical_bytes,
        "unique_content_bytes": unique_bytes,
        "duplicate_bytes": logical_bytes - unique_bytes,
        "files_dedupable": len(operations),
        "expected_physical_savings": savings,
        "estimated_post_migration_bytes": unique_bytes,
        "already_shared_files": sum(
            1 for item in files if item[4] > 1
        ),
        "hash_errors": hash_errors,
        "link_cap": link_cap,
        "shards_by_hash": shards_by_hash,
        "hash_groups": {
            digest: [(len(g[1]), g[2]) for g in groups]
            for (digest, _size), groups in by_hash.items()
        },
        "operations": operations,
    }


def apply_plan(plan, *, stop_on_failure=True) -> dict:
    """Aplica el plan. Falla cerrado: al primer fallo se detiene."""

    root = Path(plan["root"])

    linked = 0
    skipped_already = 0
    failures = []

    for operation in plan["operations"]:
        destination = Path(operation["destination"])
        canonical = Path(operation["canonical"])

        # Solo dentro del root indicado.
        try:
            destination.resolve().relative_to(root)
            canonical.resolve().relative_to(root)
        except ValueError:
            failures.append((str(destination), "OUTSIDE_ROOT"))
            break

        try:
            outcome = replace_with_hardlink(
                canonical,
                destination,
                operation["sha256"],
                link_cap=plan.get("link_cap"),
            )
        except StorageDedupeError as error:
            failures.append((str(destination), str(error)))

            if stop_on_failure:
                break

            continue

        if outcome == "linked":
            linked += 1
        else:
            skipped_already += 1

    return {
        "linked": linked,
        "already_linked": skipped_already,
        "failures": failures,
        "ok": not failures,
    }
