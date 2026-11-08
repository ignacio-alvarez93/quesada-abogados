"""
Trend Intelligence · lock OS entre procesos por store (TI-4C.3E3-G1).

Única implementación del lock que serializa las ejecuciones del productor
sobre un mismo store. Extraída sin cambios de semántica del CLI manual
(scripts/trend_producer_run.py, TI-4C.2B) para que un futuro servicio de
aplicación comparta EXACTAMENTE el mismo lock (mismo directorio, misma
clave, mismo fichero) y ambos se excluyan mutuamente.

- No bloqueante: si otro proceso lo mantiene se lanza ProcessLockBusy de
  inmediato; cualquier otro error (sin directorio por usuario, plataforma
  sin msvcrt/fcntl, E/S) se propaga y el llamador debe fallar cerrado.
- La clave es SHA-256 de os.path.normcase(str(db_path)): el llamador pasa
  la ruta canónica (Path.resolve()) del store.
- Fichero en un directorio local por usuario (Windows %LOCALAPPDATA%,
  POSIX $XDG_RUNTIME_DIR, si no $XDG_CACHE_HOME o ~/.cache); puede persistir
  sin efecto. El SO libera el lock al cerrar el handle o morir el proceso.
- Ámbito SAME_USER_SAME_HOST: otros usuarios, hosts o alias de ruta (hard
  links, unidades mapeadas) NO quedan cubiertos.

Sin SQL, sin SQLite y sin E/S del store; los backends msvcrt/fcntl se
importan de forma perezosa. Nunca importa scripts/.
"""

import errno
import hashlib
import os
from pathlib import Path


LOCK_SCOPE = "SAME_USER_SAME_HOST"
LOCK_BUSY_ERRNOS = frozenset({errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, errno.EDEADLK})
LOCK_SUBDIR = ("quesada-abogados", "locks", "trend-producer")


class ProcessLockBusy(Exception):
    """Another process holds the lock of this store."""


def lock_dir():
    """Per-user local runtime dir: never the repository nor the store's folder."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA", "")
    else:
        base = (os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("XDG_CACHE_HOME")
                or str(Path.home() / ".cache"))

    if not base.strip() or not Path(base).is_absolute():
        raise OSError("sin directorio local por usuario para el lock")

    return Path(base).joinpath(*LOCK_SUBDIR)


def lock_key(db_path):
    # Hashed name: no path (PII) on disk, no naming collisions.
    return hashlib.sha256(os.path.normcase(str(db_path)).encode("utf-8")).hexdigest()


def lock_file_path(db_path):
    """Lock file for one canonical store path; creates nothing."""
    return lock_dir() / f"{lock_key(db_path)}.lock"


def acquire_process_lock(db_path):
    """Non-blocking OS lock for one canonical store path -> release callable.

    Raises ProcessLockBusy if another process holds it; any other error must
    be treated as fail-closed by the caller. Opens no SQLite connection.
    """
    if os.name == "nt":
        import msvcrt

        def lock(fd):
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

        def unlock(fd):
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        def lock(fd):
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        def unlock(fd):
            fcntl.flock(fd, fcntl.LOCK_UN)

    path = lock_file_path(db_path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)

    try:
        lock(fd)
    except BaseException as error:
        os.close(fd)
        if isinstance(error, OSError) and error.errno in LOCK_BUSY_ERRNOS:
            raise ProcessLockBusy() from None
        raise

    def release():
        try:
            unlock(fd)
        except OSError:
            pass  # Closing the handle frees the lock anyway.
        finally:
            os.close(fd)

    return release
