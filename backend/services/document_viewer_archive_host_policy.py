"""
Política de estación para archivar en Box desde el visor (WO-DV28-P2, piloto mono-equipo).

Permiso de usuario (H1) != permiso de equipo. Esta puerta decide SOLO si el
proceso corre en la estación enrolada (el PC del despacho); no mira el actor,
la UI, ``COMPUTERNAME``, IP, hostname, usuario, variables de entorno ni
``MachineGuid``: todo eso se copia o se falsifica. La identidad es una prueba
criptográfica de posesión:

- Ancla (``ENROLLED_STATION``): clave pública revisada de la estación,
  instalada en código como ``APPROVED_CONTRACT`` (no es secreta). None =
  ninguna estación enrolada = NOT_ENROLLED para todos.
- Prueba (``PROOF_PROVIDER``): el sistema operativo firma un reto aleatorio
  con la clave privada de la estación. En Windows, ``WindowsCngProofProvider``
  abre (nunca crea) una clave de MÁQUINA no exportable del TPM (Microsoft
  Platform Crypto Provider). None = sin proveedor = UNVERIFIED.
- Verificación: ECDSA P-256/SHA-256 contra el ancla, aquí, en Python puro
  (sin dependencias); el proveedor no se verifica a sí mismo.

Resultado estructurado: ALLOWED | NOT_ENROLLED | UNVERIFIED |
NOT_THIS_WORKSTATION | ERROR. Cualquier duda, excepción o valor inesperado
deniega; nunca hay alternativa permisiva. Una clave exportable o no ligada a
hardware se considera copiable (UNVERIFIED). Una sesión remota se rechaza por
defecto (defensa adicional, no frontera). La base de datos de solicitudes
tiene que estar en un disco local fijo: SQLite en una carpeta de red no es
autoridad.

La autenticación de la estación está separada del dominio y de las
solicitudes (``document_viewer_archive_repository``): un servicio central
futuro puede verificar la misma prueba con la misma ancla.

Límites: un administrador local de la estación controla el equipo y el código;
esto impide que OTRO equipo (el PC de casa, un clon de disco sin el TPM, una
copia de la configuración) archive, no protege contra quien ya administra el
despacho. Ver docs/dv28_p2_single_host.md. En esta WO no hay ninguna estación
enrolada ni proveedor instalado: siempre NOT_ENROLLED.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


ALLOWED = "allowed"
NOT_ENROLLED = "not_enrolled"
UNVERIFIED = "unverified"
NOT_THIS_WORKSTATION = "not_this_workstation"
ERROR = "error"

# Motivos (código estable para trazas y tests; nunca contienen la clave ni datos del equipo).
NO_ENROLLMENT = "station_not_enrolled"
KEY_MISSING = "station_key_missing"
NO_PROVIDER = "station_proof_provider_missing"
OTHER_KEY = "station_other_key"
EXPORTABLE_KEY = "station_key_exportable"
SOFTWARE_KEY = "station_key_not_hardware"
BAD_SIGNATURE = "station_signature_invalid"
REMOTE_SESSION = "station_remote_session"
AUTHORITY_NOT_LOCAL = "station_authority_not_local"
PROVIDER_ERROR = "station_provider_error"
VERIFIED = "station_verified"

NOT_ENROLLED_MESSAGE = ("Este equipo no está enrolado como estación autorizada para archivar en Box "
                        "(STATION_NOT_ENROLLED). No se ha copiado nada.")
UNVERIFIED_MESSAGE = ("No se pudo verificar criptográficamente la estación de archivado "
                      "(STATION_UNVERIFIED). No se ha copiado nada.")
NOT_THIS_WORKSTATION_MESSAGE = ("Este equipo no es la estación autorizada para archivar en Box "
                                "(STATION_NOT_THIS_WORKSTATION). No se ha copiado nada.")
ERROR_MESSAGE = "No se pudo comprobar la estación de archivado: se deniega. No se ha copiado nada."

_MESSAGES = {NOT_ENROLLED: NOT_ENROLLED_MESSAGE, UNVERIFIED: UNVERIFIED_MESSAGE,
             NOT_THIS_WORKSTATION: NOT_THIS_WORKSTATION_MESSAGE, ERROR: ERROR_MESSAGE}

# Estación enrolada (``StationEnrollment``). None = ninguna = NOT_ENROLLED para todos.
ENROLLED_STATION = None
# Proveedor de prueba de posesión del sistema operativo. None = ninguno = UNVERIFIED.
PROOF_PROVIDER = None

# Separación de dominio del reto: una firma de otra aplicación no vale aquí.
CHALLENGE_CONTEXT = b"quesada-crm/dv28-p2/archive-station-proof/v1\x00"


class StationProofError(Exception):
    """El proveedor no pudo producir la prueba."""


class StationKeyMissing(StationProofError):
    """No existe la clave de la estación en este equipo."""


@dataclass(frozen=True)
class StationEnrollment:
    """Ancla pública de la estación; se instala en código tras el enrolamiento aprobado (P3)."""
    station_id: str          # etiqueta opaca (p. ej. "despacho-1"); no identifica por sí sola
    key_name: str            # nombre de la clave CNG de máquina
    public_key: bytes        # SEC1 sin comprimir, P-256 (65 bytes)
    enrolled_by: str = ""
    enrolled_at: str = ""
    require_hardware: bool = True
    allow_remote_session: bool = False


@dataclass(frozen=True)
class StationProof:
    """Lo que devuelve el proveedor: clave pública presentada, firma y propiedades de la clave."""
    public_key: bytes        # SEC1 sin comprimir
    signature: bytes         # r || s (64 bytes, big-endian), formato de CNG
    hardware: bool
    exportable: bool
    remote_session: bool


@runtime_checkable
class StationProofProvider(Protocol):
    """Adaptador del sistema operativo; nunca crea ni exporta la clave privada."""

    def prove(self, key_name, message): ...


@dataclass(frozen=True)
class StationDecision:
    outcome: str
    reason: str
    message: str
    # Huella corta de la clave verificada (no la clave ni datos del equipo); "" si no hay.
    fingerprint: str = ""
    station_id: str = ""

    @property
    def allowed(self):
        return self.outcome == ALLOWED


def _deny(outcome, reason):
    return StationDecision(outcome, reason, _MESSAGES[outcome])


def key_fingerprint(public_key):
    """12 hex del SHA-256 de la clave pública: suficiente para trazas, nunca la clave completa."""
    return hashlib.sha256(bytes(public_key)).hexdigest()[:12]


# ---------------------------------------------------------------------- ECDSA P-256 (verify only)

_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_A = _P - 3
_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
      0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)


def _add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    if p[0] == q[0]:
        if (p[1] + q[1]) % _P == 0:
            return None
        slope = (3 * p[0] * p[0] + _A) * pow(2 * p[1] % _P, -1, _P) % _P
    else:
        slope = (q[1] - p[1]) * pow((q[0] - p[0]) % _P, -1, _P) % _P
    x = (slope * slope - p[0] - q[0]) % _P
    return x, (slope * (p[0] - x) - p[1]) % _P


def _mul(k, point):
    result = None
    while k:
        if k & 1:
            result = _add(result, point)
        point = _add(point, point)
        k >>= 1
    return result


def _point(public_key):
    """Punto P-256 validado (en la curva) de una clave SEC1 sin comprimir."""
    if not isinstance(public_key, (bytes, bytearray)) or len(public_key) != 65 or public_key[0] != 4:
        raise StationProofError("Clave pública no válida.")
    x, y = int.from_bytes(public_key[1:33], "big"), int.from_bytes(public_key[33:], "big")
    if not (x < _P and y < _P) or (y * y - (x * x * x + _A * x + _B)) % _P:
        raise StationProofError("Clave pública no válida.")
    return x, y


def verify_signature(public_key, message, signature):
    """True solo si ``signature`` (r||s) es una firma ECDSA P-256/SHA-256 válida de ``message``."""
    point = _point(public_key)
    if not isinstance(signature, (bytes, bytearray)) or len(signature) != 64:
        return False
    r, s = int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
    if not (0 < r < _N and 0 < s < _N):
        return False
    digest = int.from_bytes(hashlib.sha256(bytes(message)).digest(), "big")
    inverse = pow(s, -1, _N)
    result = _add(_mul(digest * inverse % _N, _G), _mul(r * inverse % _N, point))
    return result is not None and result[0] % _N == r


# ---------------------------------------------------------------------- local authority


def _drive_type(root):
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    kernel32.GetDriveTypeW.restype = ctypes.c_uint
    return kernel32.GetDriveTypeW(root)


def local_authority(db_path):
    """La base de solicitudes está en un disco local fijo (nunca UNC ni unidad de red)."""
    if db_path is None:
        return False
    try:
        # UNC antes de resolver: nunca se consulta la red para decidir.
        if os.fspath(db_path).startswith(("\\\\", "//")):
            return False
        resolved = Path(db_path).resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    if str(resolved).startswith(("\\\\", "//")):
        return False
    if os.name != "nt":
        return True
    drive = resolved.drive
    if len(drive) != 2 or drive[1] != ":":
        return False
    try:
        return _drive_type(drive + "\\") == 3  # DRIVE_FIXED
    except Exception:
        return False


# ---------------------------------------------------------------------- decision


def challenge(enrollment, nonce):
    """Mensaje que firma la estación: contexto, estación, clave y reto aleatorio de esta comprobación."""
    return b"".join((CHALLENGE_CONTEXT, enrollment.station_id.encode("utf-8"), b"\x00",
                     enrollment.key_name.encode("utf-8"), b"\x00", nonce))


def verify_station(*, db_path):
    """Decisión de estación para archivar; nunca lanza ni escribe. ``db_path``: base de solicitudes."""
    try:
        return _verify(db_path)
    except Exception:
        return _deny(ERROR, PROVIDER_ERROR)


def _verify(db_path):
    enrollment = ENROLLED_STATION
    if not isinstance(enrollment, StationEnrollment):
        return _deny(NOT_ENROLLED, NO_ENROLLMENT)
    if not (isinstance(enrollment.station_id, str) and enrollment.station_id.strip()
            and isinstance(enrollment.key_name, str) and enrollment.key_name.strip()
            and "\x00" not in enrollment.station_id + enrollment.key_name):
        return _deny(ERROR, NO_ENROLLMENT)
    _point(enrollment.public_key)  # un ancla inválida es un error de configuración: ERROR
    if not local_authority(db_path):
        return _deny(NOT_THIS_WORKSTATION, AUTHORITY_NOT_LOCAL)
    provider = PROOF_PROVIDER
    if provider is None:
        return _deny(UNVERIFIED, NO_PROVIDER)
    message = challenge(enrollment, secrets.token_bytes(32))
    try:
        proof = provider.prove(enrollment.key_name, message)
    except StationKeyMissing:
        return _deny(NOT_ENROLLED, KEY_MISSING)
    except Exception:
        return _deny(ERROR, PROVIDER_ERROR)
    if not isinstance(proof, StationProof):
        return _deny(ERROR, PROVIDER_ERROR)
    if not isinstance(proof.public_key, (bytes, bytearray)) or bytes(proof.public_key) != bytes(
            enrollment.public_key):
        return _deny(NOT_THIS_WORKSTATION, OTHER_KEY)
    if proof.exportable is not False:
        return _deny(UNVERIFIED, EXPORTABLE_KEY)
    if enrollment.require_hardware is not False and proof.hardware is not True:
        return _deny(UNVERIFIED, SOFTWARE_KEY)
    if proof.remote_session is not False and enrollment.allow_remote_session is not True:
        return _deny(NOT_THIS_WORKSTATION, REMOTE_SESSION)
    if verify_signature(enrollment.public_key, message, proof.signature) is not True:
        return _deny(UNVERIFIED, BAD_SIGNATURE)
    return StationDecision(ALLOWED, VERIFIED, "", key_fingerprint(enrollment.public_key),
                           enrollment.station_id)


# ---------------------------------------------------------------------- Windows CNG / TPM provider


_NCRYPT_MACHINE_KEY_FLAG = 0x20
_NCRYPT_SILENT_FLAG = 0x40
_NCRYPT_IMPL_HARDWARE_FLAG = 0x1
_NCRYPT_ALLOW_ANY_EXPORT = 0x1 | 0x2  # NCRYPT_ALLOW_EXPORT_FLAG | NCRYPT_ALLOW_PLAINTEXT_EXPORT_FLAG
_KEY_MISSING_STATUS = {0x80090016, 0x80090011}  # NTE_BAD_KEYSET, NTE_NOT_FOUND
_ECS1 = 0x31534345  # BCRYPT_ECDSA_PUBLIC_P256_MAGIC
_SM_REMOTESESSION = 0x1000


class WindowsCngProofProvider:
    """Firma con una clave de MÁQUINA existente del TPM; nunca crea, importa ni exporta la privada.

    Lee de la clave: política de exportación, tipo de implementación (hardware) y
    clave pública (``ECCPUBLICBLOB``). Clave inexistente: ``StationKeyMissing``;
    cualquier otro fallo de la API: ``StationProofError``.
    """

    storage_provider = "Microsoft Platform Crypto Provider"

    def prove(self, key_name, message):
        if os.name != "nt":
            raise StationProofError("Sin proveedor criptográfico del sistema en esta plataforma.")
        if not isinstance(key_name, str) or not key_name.strip() or "\x00" in key_name:
            raise StationProofError("Nombre de clave no válido.")
        import ctypes
        from ctypes import wintypes

        ncrypt = ctypes.WinDLL("ncrypt.dll")
        handle = ctypes.c_size_t  # NCRYPT_HANDLE = ULONG_PTR
        dword_p = ctypes.POINTER(wintypes.DWORD)
        for name, argtypes in (
                ("NCryptOpenStorageProvider", [ctypes.POINTER(handle), wintypes.LPCWSTR, wintypes.DWORD]),
                ("NCryptOpenKey", [handle, ctypes.POINTER(handle), wintypes.LPCWSTR, wintypes.DWORD,
                                   wintypes.DWORD]),
                ("NCryptGetProperty", [handle, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD, dword_p,
                                       wintypes.DWORD]),
                ("NCryptExportKey", [handle, handle, wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p,
                                     wintypes.DWORD, dword_p, wintypes.DWORD]),
                ("NCryptSignHash", [handle, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                    wintypes.DWORD, dword_p, wintypes.DWORD]),
                ("NCryptFreeObject", [handle])):
            function = getattr(ncrypt, name)
            function.argtypes, function.restype = argtypes, ctypes.c_long

        def check(status, missing_is_key=False):
            code = status & 0xFFFFFFFF
            if code == 0:
                return
            if missing_is_key and code in _KEY_MISSING_STATUS:
                raise StationKeyMissing("La clave de la estación no existe en este equipo.")
            raise StationProofError(f"CNG 0x{code:08X}")

        def dword_property(key, name):
            value, size = wintypes.DWORD(0), wintypes.DWORD(0)
            check(ncrypt.NCryptGetProperty(key, name, ctypes.byref(value), ctypes.sizeof(value),
                                           ctypes.byref(size), _NCRYPT_SILENT_FLAG))
            if size.value != ctypes.sizeof(value):
                raise StationProofError("Propiedad de clave inesperada.")
            return value.value

        provider, key = handle(0), handle(0)
        try:
            check(ncrypt.NCryptOpenStorageProvider(ctypes.byref(provider), self.storage_provider, 0))
            check(ncrypt.NCryptOpenKey(provider, ctypes.byref(key), key_name, 0,
                                       _NCRYPT_MACHINE_KEY_FLAG | _NCRYPT_SILENT_FLAG), missing_is_key=True)
            export_policy = dword_property(key, "Export Policy")
            implementation = dword_property(key, "Impl Type")
            blob, size = ctypes.create_string_buffer(8 + 64), wintypes.DWORD(0)
            check(ncrypt.NCryptExportKey(key, 0, "ECCPUBLICBLOB", None, blob, len(blob), ctypes.byref(size), 0))
            magic, length = struct.unpack_from("<II", blob.raw, 0)
            if size.value != 8 + 64 or magic != _ECS1 or length != 32:
                raise StationProofError("La clave de la estación no es ECDSA P-256.")
            digest = hashlib.sha256(bytes(message)).digest()
            signature, size = ctypes.create_string_buffer(64), wintypes.DWORD(0)
            check(ncrypt.NCryptSignHash(key, None, digest, len(digest), signature, len(signature),
                                        ctypes.byref(size), _NCRYPT_SILENT_FLAG))
            if size.value != 64:
                raise StationProofError("Firma de tamaño inesperado.")
        finally:
            for opened in (key, provider):
                if opened.value:
                    ncrypt.NCryptFreeObject(opened)
        user32 = ctypes.WinDLL("user32")
        user32.GetSystemMetrics.argtypes, user32.GetSystemMetrics.restype = [ctypes.c_int], ctypes.c_int
        return StationProof(
            public_key=b"\x04" + blob.raw[8:8 + 64], signature=signature.raw[:64],
            hardware=bool(implementation & _NCRYPT_IMPL_HARDWARE_FLAG),
            exportable=bool(export_policy & _NCRYPT_ALLOW_ANY_EXPORT),
            remote_session=user32.GetSystemMetrics(_SM_REMOTESESSION) != 0)
