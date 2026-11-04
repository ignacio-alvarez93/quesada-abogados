# FCP-12 · Fabric Self-Dogfood & Closure

Estado: **code complete (WO-01..06) + corrección V3 en curso; NO `READY_FOR_HOST_AUDIT`**.
Este documento no certifica, no autoriza ni declara FCP-12 cerrado. La salida máxima posible
es `READY_FOR_HOST_AUDIT`, y hoy **no** se alcanza: F01/F02 V2 quedaron `BLOCKED` (ver §4).
El cierre exige Runner SUCCESS de las 6 WO, auditorías F01/F02 `PASS`, CI host verde en un
PR comprobado en GitHub (todavía **no ejecutado**) y la autorización humana FCP-3 existente.
**No hay merge automático.**

## 1. Qué es

FCP-12 usa Fabric para construirse a sí mismo (self-dogfood) y define cuándo un intento de
ese tipo puede *pedir* revisión humana. No reescribe Fabric: reutiliza Runner
(`claude_runner`, `runner_pipeline`, `runner_factory_ledger`), Director
(`fabric_director._classify_completion_mode`), FCP-8 (validación), FCP-10D (lecturas
acotadas) y FCP-11 (contrato, inventario de evidencia, snapshot).

| WO | Módulo | Función |
|----|--------|---------|
| 01 | `scripts/ai/fabric_self_dogfood_contract.py` | Contrato de cierre: identidad controller/target, lineage, completion Runner, evidencia requerida, rutas protegidas. Máximo: `REVIEW_REQUESTABLE` |
| 02 | `scripts/ai/fabric_self_dogfood_guardrails.py` | Aislamiento controller detached / worktree feature: HEAD, rama, ruta canónica, scopes, deriva. Máximo: `ISOLATION_HOLDS` |
| 03 | `scripts/ai/fabric_self_dogfood_evidence.py` | Lector read-only de la evidencia REAL del Runner (state root + ledger). Máximo: `CORROBORATED` |
| 04 | `scripts/ai/fabric_self_dogfood_recovery.py` | Clasificación de fallos y handoff humano → Director. Nunca recupera solo |
| 05 | `scripts/ai/fabric_self_dogfood_certification.py` | Composición evidencia + guardrails + cierre + auditorías. Máximo: `READY_FOR_HOST_AUDIT` |
| 06 | `scripts/ai/fabric_self_dogfood_cli.py` | CLI read-only `status` / `evidence` / `readiness` sobre fuentes locales del Runner |

Ningún módulo escribe, ejecuta proveedores, invoca Git ni red. Todos llevan flags de
autoridad cero (`certified`, `promotion_allowed`, `merging_allowed`, `human_approval_granted`,
`host_ci_verified`, `closure_complete`, … siempre `false`).

## 2. `RUNNER SUCCESS` ≠ certificación

Tres ejes separados que nunca se fusionan:

| Eje | Fuente | Qué significa |
|-----|--------|---------------|
| `runner_state` | lo que el Runner **registró** (`worker.json`) | el Runner aceptó el intento; nada más |
| `evidence_verdict` | FCP-12A-03 | la evidencia persistida corrobora un checkpoint SUCCESS en el HEAD observado |
| certificación end-to-end | FCP-12A-05 + CI host + FCP-3 + auditoría final | **nunca** la produce la CLI |

La CLI fija `runner_success_is_certification: false` y `end_to_end_certified: false` en
toda respuesta. Las palabras del proveedor (`stdout.txt`, `stderr.txt`, `prompt.txt`, su
`work_status`) **nunca** son fuente de estado: un `stdout` que diga «RUNNER SUCCESS -
CERTIFIED» no cambia nada (probado).

## 3. CLI read-only

```powershell
python -m scripts.ai.fabric_self_dogfood_cli `
    --query status|evidence|readiness `
    --state-root <RUNTIME>\state --factory-root <RUNTIME>\factory `
    --pipeline-id <PIPELINE_ID> --worker-id <WORKER_ID> `
    --observed-target-head <SHA_40_o_64> [--max-file-bytes N] [--format json|text]
```

* `--observed-target-head` lo aporta quien llama, capturado con Git gobernado
  (p. ej. `git -C <target> rev-parse HEAD` fuera de la CLI). La CLI no ejecuta Git.
* `status`: registro del Runner (estado, intento, proveedor, base, checkpoint) + veredicto.
* `evidence`: `SelfDogfoodEvidence.to_dict()` íntegro (códigos, ids, commits, digests,
  recuentos; nunca rutas ni prosa del proveedor).
* `readiness`: `LOCAL_EVIDENCE_CORROBORATED` o `BLOCKED`. Incluso la mejor respuesta
  lista como pendientes `FCP12A02_ISOLATION_CONFIRMATION`, `FCP12A05_CERTIFICATION`,
  `HOST_CI_ON_PULL_REQUEST`, `FCP3_HUMAN_AUTHORIZATION`, `FINAL_HOST_AUDIT`, con
  `host_ci_status: UNKNOWN` y `human_authorization: NONE`.

**No existen flags de acción.** `--promote`, `--merge`, `--push` (y `--commit`,
`--checkout`, `--reset`, `--approve`, `--authorize`, `--certify`, `--close`, `--release`,
`--retry`, `--resume`, `--dispatch`, `--run`, `--execute`, `--write`, en cualquier
capitalización o con `=valor`) se rechazan **antes** de parsear, con exit 2, sin abrir
ningún fichero.

Códigos de salida: `0` evidencia CORROBORATED (consultivo: no certifica ni autoriza);
`1` respondido pero no corroborado (informe en stdout) o fallo interno (stdout vacío);
`2` uso inválido, flag de acción prohibido o petición rechazada por el lector (stdout
vacío). stderr solo lleva `error: <CODE>: <texto fijo>`: nunca rutas, ids ni tracebacks.

## 4. Receta de dogfood REAL de prueba

Cadena obligatoria; cada eslabón lo produce su dueño, nunca la palabra de un proveedor:

1. **WO** — Dirección redacta la work order con alcance exacto (`authorize_path`) en el
   manifiesto de campaña. El manifiesto queda fijado por `manifest_sha256` en `launch.json`.
2. **Pipeline Fabric** — Runner (`runner_pipeline`) se lanza desde un *controller* en HEAD
   detached estable (el commit FCP-11) contra un *worktree feature* aislado
   (`feature/fcp12-self-dogfood-v1`), con `no_push` / `no_merge`. FCP-12A-02 confirma el
   aislamiento con snapshots Git gobernados antes y después.
3. **Claude** — el proveedor trabaja **solo** dentro del worktree y del alcance de la WO.
   No hace commits, reset, checkout, stash, push ni PR.
4. **Checkpoint Runner** — con `completion_policy=RUNNER_ACCEPTANCE` el Runner ejecuta los
   comandos de aceptación, y solo si pasan crea el commit
   `runner-checkpoint(wip): <pipeline>/<worker> attempt=N provider=claude` con los
   pathspecs exactos del work product y registra `CHECKPOINT_CREATED` en el ledger.
5. **Lectura local** — el operador captura el HEAD del worktree con Git gobernado y consulta
   la CLI (`readiness`). Esperado: `LOCAL_EVIDENCE_CORROBORATED`, checkpoint = HEAD.
6. **Auditoría F01 (funcional) / F02 (seguridad)** — workers read-only, independientes,
   posteriores a las 6 WO. Su veredicto `SOURCE_AUDIT_VERDICT` alimenta FCP-12A-05 como
   `AuditRecord` ligado al commit; un auditor `PROVIDER`/`RUNNER` no cuenta como independiente.
7. **CI host** — un humano abre el PR hacia `develop` (o `main`); corre `fcp12-self-dogfood.yml`
   **además** de `fabric-ci.yml` y `fcp11-control-plane.yml` sin cambios. La CLI nunca lee
   CI: el resultado se verifica en GitHub, no se asume.
8. **Autorización humana FCP-3** — la promoción real exige la aprobación humana existente
   (`runner_promotion_*`). FCP-12 no crea autorizaciones nuevas ni permite eludirla.
   **NO hay merge automático.**

### Evidencia real observada (lectura, 2026-11-04)

Ejecución read-only de la CLI contra el state root / ledger reales del pipeline
`fcp12-self-dogfood-night-20261103-v1`, durante el intento 1 de WO-06 (HEAD del worktree
`e09e7aa`). Provenance: **REAL** (datos del Runner, no fixtures). Rutas omitidas por
privacidad.

| Worker | HEAD observado | Exit | Readiness | Razones |
|--------|----------------|------|-----------|---------|
| wo01_contract | `7662952` | 0 | LOCAL_EVIDENCE_CORROBORATED | — |
| wo02_guardrails | `90cac89` | 0 | LOCAL_EVIDENCE_CORROBORATED | — |
| wo03_evidence | `f4ba462` | 0 | LOCAL_EVIDENCE_CORROBORATED | — |
| wo04_recovery | `1252a81` | 0 | LOCAL_EVIDENCE_CORROBORATED | — |
| wo05_certification | `e09e7aa` | 0 | LOCAL_EVIDENCE_CORROBORATED | — |
| wo05_certification | `1252a81` (obsoleto) | 1 | BLOCKED | `TARGET_HEAD_MISMATCH` |
| wo06_cli_ci_docs | `e09e7aa` | 1 | BLOCKED | `RUNNING`: sin resultado ni checkpoint todavía |
| f01 / f02 audits | `e09e7aa` | 1 | BLOCKED | `EVIDENCE_MISSING` (en `WAITING_DEPENDENCY`) |

Cada checkpoint corroborado coincide con el `checkpoint_commit` de `pipeline_result.json`
y con el commit `runner-checkpoint(wip)` del historial. Esto demuestra la cadena 1–5 para
WO-01..05; **no** demuestra 6–8, que siguen pendientes. WO-06 solo puede corroborarse
después de que el Runner cree su checkpoint (lo hizo en V2, abajo).

### Historial V1 → V2 → V3

| | V1 | V2 | V3 |
|---|---|---|---|
| Pipeline | `fcp12-self-dogfood-night-20261103-v1` | `fcp12-self-dogfood-wo06-core-skip-20261104-v2` | `fcp12-self-dogfood-audit-hardening-20261104-v3` |
| Rama | `feature/fcp12-self-dogfood-v1` | `fix/fcp12-wo06-core-skip-v2` | `fix/fcp12-self-dogfood-audit-hardening-v3` |
| Worktree | `quesada-fcp12-self-dogfood-v1` | `quesada-fcp12-wo06-core-skip-v2` | `quesada-fcp12-audit-hardening-v3` |
| Base | `9628c3f` (FCP-11) | `e09e7aa` (checkpoint WO-05 V1) | `a8adf29` (checkpoint WO-06 V2) |
| Resultado | WO-01..05 checkpoint; WO-06 sin checkpoint | WO-06 checkpoint; F01/F02 **BLOCKED** | corrección separada (WO-07), pendiente de aceptación Runner |

**V1.** WO-01..05 obtuvieron checkpoint Runner (`7662952` → `e09e7aa`). WO-06 no: el gate
core V1 rechazaba *cualquier* skip, y la suite core contiene una omisión legítima de
plataforma en sistemas de ficheros case-insensitive (fallo de especificación del gate, no
del código).

**V2 (recuperación WO-06).**

* Rama `fix/fcp12-wo06-core-skip-v2`, worktree nuevo y limpio
  `quesada-fcp12-wo06-core-skip-v2`, sobre `e09e7aa`.
* Importación controlada de un **snapshot fijado por SHA-256**: las 4 fuentes de WO-06
  (CLI, tests CLI, este documento, `fcp12-self-dogfood.yml`) se copiaron solo tras
  verificar branch/HEAD/limpieza, el digest SHA-256 de cada fichero fuente y de cada
  destino, y que ningún otro fichero cambiaba. `launch.json` fija `manifest_sha256` y
  `snapshot_sha256`.
* **Gate core condicionado exacto**: la única omisión tolerada es
  `test_runner_reconciliation.CaseCollisionTests.test_head_adds_ascii_case_variant_of_unchanged_path`
  con motivo `needs a case-sensitive filesystem for both names`, y solo si el host es
  realmente case-insensitive; cualquier otro skip, xfail o éxito inesperado falla.
* **Checkpoint final V2**: `a8adf29c003080bf257b09ffbe83b5abd5bee28d`
  (`runner-checkpoint(wip): fcp12-self-dogfood-wo06-core-skip-20261104-v2/wo06_cli_ci_docs attempt=1 provider=claude`,
  padre `e09e7aa`).
* **F01/F02 V2: `BLOCKED` (NO PASS).** Que el Runner registre SUCCESS para un worker
  auditor solo significa que el auditor terminó; su veredicto fue `BLOCKED`. Hallazgo M1
  (seguridad, media): `PROTECTED_PATHS` no incluía el propio workflow FCP-12.
* **Host PRECHECK V2: 31/31 controles verificados** por el Host Audit: cadena de padres
  de los seis checkpoints, diff de 14 rutas respecto a `9628c3f`, workflows históricos
  intactos y aprobación Runner de los 10 comandos de aceptación con el skip de
  plataforma exacto. Es una verificación local del host, **no** CI de GitHub.

**Estados, sin mezclarlos:**

| Estado | ¿Alcanzado? |
|--------|-------------|
| *code complete* (WO-01..06 con checkpoint Runner) | sí, en `a8adf29` |
| `READY_FOR_HOST_AUDIT` (requiere además F01/F02 `PASS`) | **no**: F01/F02 V2 `BLOCKED` |
| CI GitHub en un PR | **no ejecutado** |
| Dogfood end-to-end (cadena 1–8) / autorización FCP-3 / promoción | **no** |

**V3 (WO-07, corrección separada).** Rama `fix/fcp12-self-dogfood-audit-hardening-v3`
sobre `a8adf29`. Corrige M1: `.github/workflows/fcp12-self-dogfood.yml` pasa a
`PROTECTED_PATHS`, y `is_protected_path` (FCP-12A-01) lo protege —junto con los
workflows FCP-10/11— frente a variantes de mayúsculas, separadores, `.`/`..`, barras
redundantes, sufijos de stream / puntos finales, directorios padre y globs amplios;
una ruta no resoluble cuenta como protegida (fail-closed). FCP-12A-02 lo aplica a
scopes (`SCOPE_TOO_BROAD`) y a rutas cambiadas (`PROTECTED_PATH_CHANGED`). El workflow
FCP-12 se dispara también en `main`. Como V3 modifica el propio gate, **no** es un work
product de self-dogfood apto para `REVIEW_REQUESTABLE` (FCP-12A-01 lo denegaría): es una
remediación dirigida por humanos que exige nuevas auditorías F01/F02, Host Audit y CI.
V3 **no** significa dogfood e2e ejecutado, ni CI verde, ni promoción aprobada.

## 5. CI: workflow separado

`.github/workflows/fcp12-self-dogfood.yml`, independiente:

* `pull_request` y `push` sobre `develop` y `main`; sin filtro de rutas (FCP-12 depende de
  módulos Runner/FCP-10/FCP-11 y debe reejecutarse ante cualquier cambio).
* `permissions: contents: read`; `persist-credentials: false`; Windows, Python 3.11.
* `py_compile` de los 6 módulos y 6 tests.
* Las 6 suites reales `test_fabric_self_dogfood_{contract,guardrails,evidence,recovery,certification,cli}`:
  falla (exit 2) si alguna suite tiene < 12 tests, el total < 90, hay skipped,
  expected failures o unexpected successes, o algún test falla.
* Comprueba que la CLI rechaza `--promote`, `--merge` y `--push` con exit 2.

**No** añade jobs ni steps a `fabric-ci.yml` (contratos de hash FCP-10) ni modifica
`fcp11-control-plane.yml`. Ambos, y desde V3 también `fcp12-self-dogfood.yml`, están en
`PROTECTED_PATHS` de FCP-12A-01: un work product que los toque (en cualquier grafía,
directorio padre o glob que los cubra) es `PROTECTED_PATH_CHANGED`, y un scope que los
autorice es `SCOPE_TOO_BROAD` en FCP-12A-02. Una WO de self-dogfood no puede debilitar su
propio gate.

Recuento local V3 (Python 3.11.1, Windows): `[40, 24, 22, 24, 23, 21]`, total 154,
0 skipped, 0 xfail. Es un resultado local, **no** CI host.

## 6. Tests de la CLI: provenance de fixtures

`scripts/tests/test_fabric_self_dogfood_cli.py` (21 tests) distingue explícitamente:

* `REAL_SHAPED_SYNTHETIC` — el `Fixture` de FCP-12A-03: árbol temporal con las formas
  exactas que escribe el Runner. Prueba el cableado, **no** una ejecución real.
* `HOSTILE_SYNTHETIC` — el mismo árbol manipulado: HEAD obsoleto, proveedor que dice
  SUCCESS sin aceptación Runner, worker FAILED, JSON corrupto, bytes no UTF-8 con secreto,
  ledger ausente, fichero sobre el límite, ledger con `MODULE_CERTIFIED`, raíces relativas /
  solapadas / con `..`.

Los tests nunca leen datos reales del Runner (son locales y privados). La evidencia real
está en la tabla del §4. Los mocks solo sirven para regresión (fallos internos, primitivas
de proceso/red prohibidas).

## 7. Seguridad y privacidad

* Lectura solo de los ficheros enumerados por FCP-12A-03 bajo las dos raíces, con
  rechazo de links / junctions / alias 8.3, identidad de descriptor y límite de tamaño.
  `prompt.txt`, `stdout.txt` y `stderr.txt` no se abren nunca.
* La salida solo contiene códigos enumerados, ids validados, commits, digests y recuentos.
  Nunca rutas, ramas, prosa del proveedor ni secretos; stderr no repite argumentos.
* Sin Git, procesos, red, reloj, entorno ni escrituras; `--help` no abre ningún fichero
  ni importa módulos hermanos (probado en subproceso).
* El workflow tiene permisos `contents: read` y no persiste credenciales.
* La CLI no puede conceder autorización: las garantías de la CLI se aplican al final del
  informe y ninguna garantía relajada del lector puede activarlas (probado).

## 8. Rollback

* Todo cambio FCP-12 vive en commits `runner-checkpoint(wip)` en ramas no protegidas;
  `develop` y `main` no se tocan:
  * V1 `feature/fcp12-self-dogfood-v1`: WO-01..05 (`7662952` … `e09e7aa`).
  * V2 `fix/fcp12-wo06-core-skip-v2`: WO-06, checkpoint final
    `a8adf29c003080bf257b09ffbe83b5abd5bee28d` sobre `e09e7aa`.
  * V3 `fix/fcp12-self-dogfood-audit-hardening-v3`: WO-07 sobre `a8adf29`; su checkpoint,
    si llega, lo crea el Runner solo tras la aceptación completa.
* Cada versión es un ancla: abandonar V3 (decisión humana) deja V2 en `a8adf29`;
  abandonar V2 deja V1 en `e09e7aa`.
* El controller detached permanece en el commit FCP-11 (`9628c3f`) y sigue siendo el
  ancla de rollback final: abandonar las ramas FCP-12 restaura el estado previo.
* FCP-12 no modifica módulos FCP-1..11 ni los workflows históricos (`fabric-ci.yml`,
  `fcp11-control-plane.yml`); V3 solo cambia el workflow propio de FCP-12. Revertir FCP-12
  equivale a no fusionar la rama o revertir su merge; no hay migraciones, SQL ni estado
  persistente propio.
* La CLI no tiene nada que revertir: no escribe.

## 9. Limitaciones

* La CLI no confirma aislamiento (FCP-12A-02) ni certifica (FCP-12A-05): ambos necesitan
  snapshots Git gobernados que la CLI no toma. Aparecen siempre como pendientes.
* Solo corrobora el modo `CHECKPOINT`; `SUCCESS_NOOP` y checkpoints de work product
  reanudado se rechazan (heredado de FCP-12A-03).
* Lecturas acotadas a `max_file_bytes` (≤ 256 KiB): un ledger o transcript mayor da
  `EVIDENCE_UNAVAILABLE`, nunca un muestreo.
* El HEAD observado es dato del llamante: si quien llama miente, la CLI solo puede
  comprobar que coincide con el checkpoint registrado, no cómo se obtuvo.
* Sin estado de CI host ni de autorización humana: `host_ci_status` es siempre `UNKNOWN`.
* Lectura puntual sin cache: un fichero reemplazado entre dos lecturas solo se detecta por
  las reglas cruzadas del lector.

## 10. Criterios de cierre FCP-12

FCP-12 **no** está cerrado hasta que se cumplan todos, verificados por su dueño:

1. Runner SUCCESS con checkpoint corroborado para WO-01..06 (CLI `readiness`).
2. F01 y F02 `SOURCE_AUDIT_VERDICT: PASS`.
3. `fcp12-self-dogfood.yml`, `fabric-ci.yml` y `fcp11-control-plane.yml` verdes en el PR,
   comprobados en GitHub.
4. Autorización humana FCP-3 existente y auditoría final host.
