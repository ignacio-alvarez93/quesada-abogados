# WO-DV28-P2 · Piloto mono-equipo: preparación segura del archivado Box desde el visor

**Rama:** `feature/dv28-p2-mono-equipo` (worktree `quesada-dv28-p2-mono-equipo`), sobre `de3cf50`.
Sin tocar `main`, `develop`, CRM canónico, `database/quesada.db`, migraciones, Box Drive ni `.env`.
**Box REAL: NO activado.** Ninguna clave real generada ni enrolada. Ninguna concesión en la BD real.

> **Evidencia de ejecución: PENDIENTE.** Ni la sesión P2 ni la de FIX1 tuvieron terminal (solo lectura/escritura
> de ficheros): el ejecutor no ha lanzado pytest, `compileall` ni `git diff --check` y no ha hecho commit. No hay
> resultados de tests ni recuento de skips propios; **no se declara `RUNNER_ACCEPTANCE`** ni H3 certificado. Los
> resultados válidos son los del Runner con los 7 comandos de aceptación.
>
> **FIX1 (WO-DV28-P2-FIX1):** aplicada la corrección de fixture del §6, autorizada expresamente para
> `ArchiveBase`. El run fallido `fdb-20261112t045215948552-1c3b2f10` no deja en este worktree la salida concreta de
> los tests: que §6 fuera la **única** causa del `ACCEPTANCE_FAILED` sigue sin demostrarse hasta el próximo run.

## 1. Diagnóstico

### Traza (sin cambios de diseño DV26/DV27)

`ArchiveForm` → `prepare_archive` (H1 + **estación**, solo lectura) → consentimiento sobre la huella →
`execute_archive` → `_authorize` (H1) → **`_station_denied`** (estación) → `_intent_store` (H2) → nueva revisión →
por documento `_execute_one` → `_governed_copy` → `intents.run_intent(... governed_box_copy(copy=certified_copy))` →
`certified_copy`: H1 → **estación** → única llamada a `document_inbox_service.copy_inbox_item_to_expedient_box`
(P3B1: COPY → VERIFY → REGISTER).

### Identidad de equipo reutilizable

No existe en el CRM. Las autoridades de host de `scripts/ai/runner_*_host_authority.py` son del Runner (otro
dominio, otro modelo de amenaza) y no se reutilizan. Se crea `backend/services/document_viewer_archive_host_policy.py`
(ruta autorizada nº 5). Permisos (H1), claims (H2) y la copia P3B1 se reutilizan sin duplicar.

### Estado de H3 heredado

Los `ContainmentTests` de DV28-P1 **nunca se han ejecutado** (P1 tampoco tenía terminal) y esta sesión tampoco
puede ejecutarlos. No hay evidencia de defecto que justifique tocar `document_inbox_service.py`: **no se ha
modificado**. H3 sigue **no certificado**.

## 2. Arquitectura efectiva (E1)

Autorización de cada copia = **sesión autenticada** ∧ **`document.box_copy` vigente** (H1) ∧ **estación enrolada y
verificada** ∧ **autoridad única/claims** (H2) ∧ **revisión y consentimiento vigentes** ∧ **H3** (prevención P3B1),
y por encima las compuertas de código (cerradas).

| Punto | H1 permiso | Estación (P2) | H2 solicitud |
|---|---|---|---|
| `prepare_archive` | `authorized`/`permission_message` | `station_verified`/`station_message`/`station_fingerprint` | — |
| Confirmar (`execute_archive`) | `_authorize`; revisión sin permiso ⇒ `PERMISSION_CHANGED` | `_station_denied`: denegada ⇒ su motivo; otra huella o revisión sin estación ⇒ `STATION_CHANGED` | `_intent_store` |
| Justo antes de COPY (`certified_copy`, con la solicitud tomada) | `PERMISSION_REVOKED` | `STATION_LOST` (perdida, distinta o error) | solicitud `rejected`, nada escrito, reintentable con `fence + 1` |

### `document_viewer_archive_host_policy`

- `verify_station(*, db_path)` → `StationDecision(outcome, reason, message, fingerprint, station_id)`;
  nunca lanza ni escribe. Solo recibe la ruta de la base de solicitudes: **no hay parámetro para el actor ni la UI**.
- Resultados: `ALLOWED | NOT_ENROLLED | UNVERIFIED | NOT_THIS_WORKSTATION | ERROR`.
- Ancla `ENROLLED_STATION` (`StationEnrollment`: `station_id`, `key_name`, `public_key` SEC1 P-256, quién/cuándo,
  `require_hardware=True`, `allow_remote_session=False`). **None en el código.**
- Proveedor `PROOF_PROVIDER` (`StationProofProvider.prove(key_name, message) -> StationProof`). **None en el código.**
  `WindowsCngProofProvider` (implementado, no instalado): abre una clave de **máquina** existente del
  *Microsoft Platform Crypto Provider* (TPM), lee `Export Policy` e `Impl Type`, exporta **solo** `ECCPUBLICBLOB`
  y firma con `NCryptSignHash`. Nunca crea, importa, exporta la privada ni borra (comprobado por AST).
- Verificación: reto aleatorio de 32 bytes por comprobación, con separación de dominio
  (`quesada-crm/dv28-p2/archive-station-proof/v1`, `station_id`, `key_name`); ECDSA P-256/SHA-256 verificada en
  Python puro contra el ancla (no contra la clave que presenta el proveedor). Comprobado con el vector RFC 6979 A.2.5.
  FIX1: el vector del test (clave privada, `Ux`/`Uy`, `r`/`s` de SHA-256 sobre «sample») se ha cotejado a mano con
  RFC 6979 A.2.5 y coincide; el test además deriva la clave pública de la privada con la propia aritmética de curva
  y exige el rechazo de firmas alteradas. Esto es revisión, **no ejecución**. No hay biblioteca criptográfica
  auditada entre las dependencias aprobadas (ningún `requirements*.txt` incluye `cryptography`/`ecdsa`): añadirla
  queda fuera de alcance, así que se mantiene el verificador de solo-verificación (datos públicos), sin cambio de
  contrato. Decisión pendiente: sustituirlo por `cryptography` antes de P3.
- FIX1, auditoría `WindowsCngProofProvider` (lectura de código, sin ejecutar): constantes CNG correctas
  (`NCRYPT_MACHINE_KEY_FLAG` 0x20, `NCRYPT_SILENT_FLAG` 0x40, `NTE_BAD_KEYSET`/`NTE_NOT_FOUND`, `ECS1`,
  `SM_REMOTESESSION`); `argtypes` con `NCRYPT_HANDLE` como `ULONG_PTR` y `SECURITY_STATUS` como `long` con máscara;
  los dos handles se liberan en `finally` solo si se abrieron; cualquier error de API ⇒ `StationProofError` ⇒
  `ERROR`/denegado. Sin defectos encontrados; la prueba real solo abre una clave inexistente aleatoria.
- Deniega: sin ancla o ancla con forma de dict (`NOT_ENROLLED`); clave ausente en el equipo (`NOT_ENROLLED`); sin
  proveedor (`UNVERIFIED`); otra clave pública (`NOT_THIS_WORKSTATION`, PC de casa); firma inválida o reproducida
  (`UNVERIFIED`, configuración copiada / replay); clave exportable o no hardware (`UNVERIFIED`, copiable); sesión
  remota (`NOT_THIS_WORKSTATION`); base de solicitudes no local —UNC, unidad de red, extraíble, RAM— comprobada
  **antes** de resolver la ruta (`NOT_THIS_WORKSTATION`); cualquier excepción o valor que no sea exactamente
  `True`/`False` donde se espera (`ERROR`/denegado).
- Trazas: solo una huella de 12 hex del SHA-256 de la clave pública; nunca la clave ni datos del equipo.
- **No usa** `COMPUTERNAME`, hostname, IP, usuario, variables de entorno, `MachineGuid`, rutas ni nada del actor
  (AST: sin `environ`, `getenv`, `gethostname`, `getnode`, `socket`, `platform`, `winreg`…).
- Separada del dominio: no importa `database`, `sqlite3` ni el repositorio. Un servicio central futuro puede
  verificar la misma prueba con la misma ancla (portable al proveedor).
- `SINGLE_HOST_APPROVED` y `APPROVED_CONTRACT` **no** conceden la estación (AST en `_station`/`_station_denied`).
- `activation_blockers()` no cambia (3 códigos): la estación es una propiedad del equipo en tiempo de ejecución y se
  exige en cada ejecución, aunque las compuertas de código se abrieran.

**Diálogo:** solo mensajes de bloqueo. Si la revisión no tiene permiso **o** estación verificada, muestra el motivo
y no deja marcar el consentimiento. No importa la política de estación (AST).

### Autoridad mono-equipo (H2) — restricción documentada

- Una sola autoridad transaccional: la `quesada.db` local **del PC del despacho**. Varias instancias del CRM en ese
  mismo equipo sobre esa misma base quedan coordinadas por el claim/fencing persistente.
- Otra base local (otro puesto, una copia de la BD) **no** es autoridad de coordinación: el piloto **no** ofrece
  exclusión global. Lo que impide la segunda copia desde otro equipo es la **estación**, no la base.
- SQLite en recurso de red: rechazado por la política (`AUTHORITY_NOT_LOCAL`).
- `SINGLE_HOST_APPROVED` sigue `False` y `MULTI_HOST_GUARANTEE` sigue `False`: esta WO no equivale a aprobar el modo
  mono-equipo.

## 3. Pruebas (E2) — escritas, NO ejecutadas

`scripts/tests/test_dv28_p2_single_host.py`:

| Clase | Qué prueba |
|---|---|
| `GateTests` | 5 compuertas OFF + `ENROLLED_STATION`/`PROOF_PROVIDER` None (AST); fail-closed por defecto; firma de `verify_station` solo `db_path`; sin fuentes spoofables; APIs CNG solo abrir/leer/exportar pública/firmar; sin rutas propias; UI sin acceso a la política; estación en revisión, confirmación y antes de COPY, en ese orden respecto de H1/H2 |
| `StationPolicyTests` | Vector RFC 6979; firmas/claves malformadas; variables de entorno falsificadas ⇒ `NOT_ENROLLED`; estación legítima ⇒ `ALLOWED` con reto nuevo; PC de casa, configuración copiada, replay, clave ausente, error del proveedor, respuesta extraña ⇒ denegado; exportable/software/remota (también con valores «truthy») ⇒ denegado; ancla inválida ⇒ `ERROR`; autoridad UNC/red/extraíble/RAM ⇒ denegado; proveedor CNG real: abre una clave inexistente aleatoria (solo lectura) ⇒ nunca `ALLOWED` |
| `ViewerStationTests` | Estación + permiso + misma BD ⇒ una copia, 3 verificaciones; usuario con permiso en equipo no autorizado (7 variantes, con «claims» de estación en el actor) ⇒ nada; revisión sin estación o con otra estación ⇒ `STATION_CHANGED`; pérdida/cambio/error/PC de casa justo antes de COPY ⇒ `STATION_LOST`, Box intacto, solicitud `rejected`, reintento ⇒ una copia; actor falsificado + permiso revocado + solicitud repetida ⇒ una sola copia; 4 revisiones concurrentes ⇒ 1 copia; diálogo muestra el bloqueo y no toma el consentimiento |
| `ProcessStationTests` | 4 procesos reales, misma BD temporal, estación legítima ⇒ 1 `done`, 1 archivo, sin `_2`, 1 evento, 1 solicitud `registered`; PC de casa con configuración copiada (y con BD copiada) ⇒ `refused`, 0 archivos; dos BD independientes ⇒ cada una «gana» (no hay exclusión global) y `MULTI_HOST_AUTHORITY_PENDING` sigue |
| `SandboxStationFixtureTests` | FIX1: ejecuta un test real de `ArchiveBase`: durante el test la estación sintética está instalada (`ALLOWED`) y un test negativo puede sustituirla (`UNVERIFIED`); al terminar, `ENROLLED_STATION`/`PROOF_PROVIDER` vuelven a None y `verify_station` deniega (`NOT_ENROLLED`) |
| `H3EvidenceTests` | En Windows ejecuta `ContainmentTests` y exige 7 ejecutados, **0 skips**, 0 xfail, 0 fallos; fuera de Windows **falla** (no hay evidencia H3), no se salta |

Endurecimientos: `test_dv28_box_activation.GateTests` comprueba también `ENROLLED_STATION`/`PROOF_PROVIDER` None y
que la política no usa SQLite. FIX1: `SyntheticStation` (clave P-256 aleatoria en memoria, solo sandbox) vive ahora en
`test_document_viewer_dv25_box_from_viewer.py` y `ArchiveBase.setUp` la instala con `self.patch` (restaurada por
`addCleanup`); `test_dv27_box_copy_activation` la reexporta (`dv27.SyntheticStation`) y `ActivationBase` ya no la
instala por segunda vez. Así DV25/DV27/DV28/P2 ejercitan la guardia real.

### Resultados exactos de tests y skips

**No disponibles** (sin terminal). A rellenar por el Runner con la salida de los 7 comandos de aceptación.
`H3EvidenceTests` es el control de 0 skips: si `ContainmentTests` tiene un skip o fallo, falla.

## 4. Matriz de cobertura

| | Código | Pruebas sintéticas | Ejecutado | Box Drive real | Producción |
|---|---|---|---|---|---|
| H1 permiso | Sí (P1) | Sí (P1 + P2) | **No** | No | No (`APPROVED_CONTRACT = None`) |
| H2 claims, mismo equipo | Sí (P3B3/P1) | Sí (hilos y procesos, P1 + P2) | **No** | No | No (`SINGLE_HOST_APPROVED = False`) |
| H2 multi-equipo | No existe | Probado que NO hay exclusión | **No** | No | No (`MULTI_HOST_GUARANTEE = False`) |
| H3 contención | Sí (P1, cadena de handles) | Sí (`ContainmentTests` + control 0 skips) | **No** | No | No (`H3_WRITE_CONTAINMENT_VERIFIED = False`) |
| Estación | Sí (P2, sin enrolar) | Sí (P2) | **No** | — | No (`ENROLLED_STATION = None`) |

**Windows TEMP verificado ≠ Box Drive REAL verificado ≠ operativo para producción.** Hoy ninguno de los tres.

## 5. Límites de amenaza

- Un administrador local del PC del despacho controla ese equipo, su TPM y el código: puede usar la clave o
  cambiar compuertas. La política impide que **otro** equipo archive (PC de casa, host desconocido, clon de disco sin
  ese TPM, copia de la configuración o de la BD); no protege contra quien ya administra el despacho.
- Integridad del código asumida: el ancla vive en código revisado. Quien edite el código de su propio equipo puede
  cambiar cualquier compuerta; por eso Box real exige además las compuertas y la aprobación humana.
- Una clave CNG **software** no exportable viaja con un clon de disco (DPAPI de máquina): por eso
  `require_hardware=True` por defecto. Si el despacho no tiene TPM utilizable, la estación queda `UNVERIFIED`; relajarlo
  sería una decisión expresa de Dirección con este riesgo aceptado por escrito.
- La detección de sesión remota (`SM_REMOTESESSION`) es defensa adicional, no frontera.
- La verificación ECDSA en Python puro no es de tiempo constante; solo maneja datos públicos (clave pública, firma).
- No hay exclusión entre equipos distintos ni entre bases distintas: el piloto **no** es multi-equipo.

## 6. Contrato heredado de sandbox (resuelto en FIX1)

`p3b2.ArchiveBase.setUp` abría `EXECUTION_ENABLED`, instalaba `SandboxContract` y `SINGLE_HOST_APPROVED` en el
sandbox, pero no conocía la estación: con la guardia fail-closed, sus tests que esperan copia recibían
`STATION_NOT_ENROLLED` (`ExecutionTests`, `ViewerDialogTests` y los heredados por `ViewerSafetyTests` de
`test_document_viewer_dv25_security.py`). Derivar la estación de `SINGLE_HOST_APPROVED`/`APPROVED_CONTRACT`, del
entorno o de una ruta sigue prohibido y no se ha hecho.

**Corrección FIX1** (autorizada para `ArchiveBase`): `SyntheticStation` se define junto a `ArchiveBase` y
`ArchiveBase.setUp` la instala al final, vía `self.patch` (deshecha por `addCleanup` al acabar cada test), sobre la BD y
el Box del `TemporaryDirectory`. Se descartó el import diferido de DV27 dentro de `setUp`: sin `__init__.py`, pytest
importa el fichero DV25 por su nombre base y DV27 lo reimporta como `scripts.tests.…`; un import a mitad de test
podía crear una segunda copia del módulo DV25 con `REAL_COPY` capturado ya parcheado. Ningún assert eliminado ni
test antiguo reescrito; la estación se sigue verificando criptográficamente (firma real del reto) en cada punto.

## 7. Decisiones pendientes (Dirección)

1. Aceptar o no el requisito TPM (`require_hardware=True`) para el PC del despacho.
2. Quién custodia y revisa el ancla pública en código y quién aprueba su instalación.
3. Sustituir el verificador ECDSA en Python puro por una biblioteca auditada (nueva dependencia) antes de P3.
4. Autorización de la etapa P3 (runbook §8), incluida la carpeta de ensayo de Box Drive.

## 8. Runbook P3 — **NO EJECUTABLE AUTOMÁTICAMENTE**

Cada paso lo ejecuta una persona autorizada, con aprobación previa por escrito y registro de evidencia. Ningún
script del repositorio lo hace. Si un paso falla: parar, no improvisar, conservar evidencia.

1. **Copia de seguridad y rollback.** Copia de `quesada.db` (CRM cerrado), SHA-256 de la copia, restauración probada
   en un equipo de prueba y procedimiento de vuelta atrás escrito.
2. **Migraciones existentes autorizadas.** Aplicar `20261110_dv25_archive_claims.sql` y
   `20261111_dv28_box_permissions.sql` con el procedimiento aprobado (hoy `apply_schema` rechaza la base habitual por
   diseño). Comprobar esquema antes/después. Sin concesiones por defecto.
3. **Concesión explícita.** Insertar `document.box_copy` solo para los usuarios concretos aprobados, con
   `granted_by_user_id` ≠ usuario y motivo. Probar revocación en un usuario de prueba.
4. **Enrolamiento criptográfico del despacho (solo ese PC).** Con la cuenta de administración del despacho:
   crear en el *Microsoft Platform Crypto Provider* una clave ECDSA P-256 de **máquina**
   (`NCRYPT_MACHINE_KEY_FLAG`), `Export Policy = 0` (no exportable), con ACL que limite su uso a la cuenta/grupo del
   CRM; la clave privada nunca sale del TPM ni del equipo y nunca entra en el repositorio. Exportar solo la clave
   pública (`ECCPUBLICBLOB` → SEC1), anotar su huella (12 hex) y fecha. Revisar en un commit aprobado el
   `StationEnrollment` (ancla pública, quién, cuándo) y `PROOF_PROVIDER = WindowsCngProofProvider()`.
   **Revocación:** quitar el ancla del código (vuelve a `NOT_ENROLLED` en todos los equipos) y borrar la clave en el
   despacho con el procedimiento de administración; un reenrolamiento es una clave nueva y un commit nuevo.
   **Auditoría:** huella del ancla en el commit; las decisiones solo exponen la huella.
5. **Prueba de rechazo en casa.** En el PC de casa, con el mismo código y configuración copiada:
   `verify_station` ⇒ `NOT_ENROLLED`/`NOT_THIS_WORKSTATION`/`UNVERIFIED`, nunca `ALLOWED`; el diálogo muestra el
   bloqueo; ningún archivo ni solicitud nuevos.
6. **Prueba no destructiva en Box Drive.** En una carpeta de **ensayo** autorizada y previamente vacía, una copia inocua
   desde el despacho: tamaño y SHA-256 de origen y destino iguales, traza `containment`, ruta final de
   `GetFinalPathNameByHandleW` coherente con la revisada, original de Bandeja y contenido previo intactos. Solo
   entonces `H3_WRITE_CONTAINMENT_VERIFIED = True` en un commit aprobado.
7. **Aprobación humana para abrir compuertas.** `SINGLE_HOST_APPROVED`, `APPROVED_CONTRACT` y por último
   `EXECUTION_ENABLED`, cada uno con su commit, sus tests AST actualizados, Runner completo en Windows y aprobación
   escrita. `MULTI_HOST_GUARANTEE` sigue `False`.

## 9. Archivos

| Archivo | Cambio |
|---|---|
| `backend/services/document_viewer_archive_host_policy.py` | Nuevo: política de estación, verificación P-256, proveedor CNG/TPM (no instalado) |
| `backend/services/document_viewer_box_archive_service.py` | Estación en revisión, confirmación y antes de COPY; `STATION_CHANGED`/`STATION_LOST`; campos `station_*` en `ArchivePlan` |
| `frontend/components/document_viewer_archive_dialog.py` | Solo mensaje/bloqueo de estación |
| `scripts/tests/test_dv28_p2_single_host.py` | Nuevo |
| `scripts/tests/test_dv28_box_activation.py` | Gates de estación y política sin SQLite |
| `scripts/tests/test_dv27_box_copy_activation.py` | Fixture: reexporta `SyntheticStation` (FIX1: ya no la instala `ActivationBase`) |
| `scripts/tests/test_document_viewer_dv25_box_from_viewer.py` | FIX1: `SyntheticStation` + instalación en `ArchiveBase.setUp` (solo fixture) |
| `docs/dv28_p2_single_host.md` | Este documento |
| `docs/dv28_box_activation.md` | Estado P2 (anexo) |

Sin cambios: `document_viewer_archive_permission_service.py`, `document_viewer_archive_repository.py`,
`document_inbox_service.py`, migraciones, BD, `.env`.

## 10. Indicadores

- **P2 implementación y pruebas:** política mono-equipo integrada en el servicio y pruebas sintéticas escritas.
  Ejecución por el ejecutor: ninguna. Aceptación: no declarada; corrección del §6 aplicada, pendiente del Runner.
  No se da porcentaje: sin salida de tests no hay base para calcularlo.
- **Capacidad global de archivado desde el visor:** revisión disponible; copia real a Box **desactivada** (cinco
  compuertas cerradas, ninguna estación enrolada, H3 sin evidencia de Windows ni de Box Drive).
