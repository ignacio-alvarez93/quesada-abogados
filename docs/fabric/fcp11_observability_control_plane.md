# FCP-11 · Fabric Observability Control Plane

Estado: **candidato a cierre** (WO-08/08). Este documento no certifica ni autoriza nada:
el cierre lo decide Dirección tras Runner SUCCESS, auditoría y CI verde.

## 1. Qué es

Plano de control **solo de observación** sobre el estado que ya escriben Runner y Director.
Lee, compone y presenta; nunca ejecuta, reintenta, reanuda, pausa, cancela, autoriza,
toca Git, procesos ni recursos. Director y Runner conservan toda la autoridad.

| WO | Módulo | Función |
|----|--------|---------|
| 01 | `scripts/ai/fabric_control_plane_contract.py` | Contrato, vocabularios, condiciones (`PRESENT/MISSING/CORRUPT/UNAVAILABLE`), flags de autoridad cero |
| 02 | `scripts/ai/fabric_control_plane_snapshot.py` | Snapshot de pipelines/workers desde `runner_pipeline` (pipeline.json, pipeline_result.json, worker.json, result.json) |
| 03 | `scripts/ai/fabric_control_plane_evidence.py` | Evidencia por intento sellada contra el snapshot |
| 04 | `scripts/ai/fabric_control_plane_history.py` | Página del ledger nativo `runner_factory_ledger` correlacionada con el snapshot |
| 05 | `scripts/ai/fabric_control_plane_resources.py` | Proveedores / cuota / coste desde FCP-10 (sin inventar datos) |
| 06 | `scripts/ai/fabric_control_plane_attention.py` | HUMAN ATTENTION: clases y prioridad (SAFETY > PROCESS > EVIDENCE > FAILURE > AUTH > QUOTA > WAITING > UNKNOWN > CLEAR) |
| 07 | `scripts/ai/fabric_control_plane_gateway.py`, `fabric_control_plane_cli.py` | Gateway de lectura único (allowlist, saneado, límites) y CLI |
| 08 | `frontend/views/fabric_control_plane_view.py` | Vista Flet «Sistema › Control operativo Fabric» |

Flujo: ficheros de estado + ledger → proyecciones FCP-11 → gateway → (CLI | vista Flet).
La vista y la CLI consumen **solo** el gateway; ninguna lee ficheros, SQL ni red.

## 2. Instalación y uso

Sin dependencias nuevas, sin `.env`, sin servicios ni procesos en segundo plano.

CLI (desde la raíz del repo):

```
python -m scripts.ai.fabric_control_plane_cli --query summary ^
    --allowed-root <repo>\runtime\claude_runner ^
    --state-root <repo>\runtime\claude_runner\pipelines ^
    --observed-at-utc 2026-11-03T12:00:00Z [--format text]
```

Consultas: `summary`, `pipelines`, `worker`, `activity` (requiere `--factory-root`),
`attention`, `resources` (opcional `--report-file`). Salida 0 = respondido (ADVISORY),
1 = rechazado, 2 = error de uso; los errores son `error: <CODE>: <texto fijo>`.

Vista Flet: menú lateral **Sistema › Control operativo Fabric**. Usa la disposición por
defecto del Runner (`runtime/claude_runner` como raíz permitida, `runtime/claude_runner/pipelines`
como state root). Si no existe, muestra «Las fuentes del Runner no están disponibles».
Lee al abrir la vista y al pulsar **Actualizar**; no hay polling, temporizador ni watcher.

## 3. Qué muestra la vista

- Resumen: condición de la raíz, clase de atención global, actor y origen, recuentos.
- Pipelines y workers: ciclo de vida, outcome del Runner, outcome de `result.json`,
  acuerdo entre ficheros y clase/razón de atención.
- HUMAN ATTENTION: elementos no CLEAR por prioridad.
- Actuaciones gobernadas (pausar, cancelar, reanudar, reintentar): **No autorizada**.
  No existen botones efectivos: requieren un gateway gobernado aprobado y decisión
  explícita de Dirección (fuera de FCP-11).
- Estados explícitos: READY, EMPTY (raíz MISSING o sin pipelines) y ERROR (código fijo).
  La ausencia de evidencia es UNKNOWN/MISSING/UNAVAILABLE, nunca SUCCESS.
- Si las tres lecturas observan revisiones distintas del snapshot, avisa de inconsistencia.

## 4. Coste de lectura

Cada **Actualizar** hace 3 consultas al gateway (`summary`, `pipelines`, `attention`);
cada una relee snapshot + evidencia + atención del state root. Límites heredados:
32 pipelines, 32 workers por pipeline, 8 intentos por worker, ledger ≤ 256 KiB,
respuesta ≤ `MAX_RESPONSE_BYTES`, página ≤ 50 en la vista. Lo omitido se cuenta y se
indica («hay más…»); nunca se trunca en silencio. Coste nulo en reposo.

## 5. Modelo de amenazas

| Amenaza | Mitigación |
|---------|------------|
| Path traversal, UNC, streams, NUL, URL | `admit_path` (FCP-10D-01) y raíces permitidas explícitas; rechazo antes de abrir |
| Enlaces / junctions | Raíces deben ser su propio realpath; ruta comprobada escrita y resuelta; junction interna → `LINK_REFUSED` |
| JSON corrupto / duplicado / no UTF-8 | Proyecciones reportan `CORRUPT` sin lanzar; atención nunca CLEAR |
| TOCTOU | Lectura con verificación de cambio (`SOURCE_CHANGED_DURING_READ`); revisiones por fuente; aviso de inconsistencia en la vista |
| IDs maliciosos | `valid_id` del contrato; error de uso |
| Fuga de secretos / rutas | Allowlist de campos, `_sanitize` (secreto/ruta → `[REDACTED]`, ASCII, longitud), vista sin rutas; errores con texto fijo |
| Escalada de autoridad | Flags de autoridad cero en todas las respuestas; la vista rechaza cualquier flag a True; sin handlers de actuación |
| DoS por tamaño | Límites de bytes, páginas y recuentos; respuesta sobredimensionada → rechazo |
| Ejecución en UI | Sin SQL, ficheros, red, procesos, reloj periódico ni tareas en segundo plano en la vista |

## 6. Limitaciones

- `activity`, `worker` y `resources` solo por CLI/gateway; la vista se limita a resumen,
  pipelines/workers y atención.
- Las advisories FCP-6 / C02 no se consolidan en el gateway (atención las marca ABSENT).
- Consultas consecutivas pueden observar escrituras distintas del Runner (comparar `sources`).
- `frontend/views/__init__.py` importa vistas Flet de forma ansiosa; los tests cargan la
  vista por ruta para funcionar en CI sin Flet (hallazgo, no modificado: fuera de alcance).

## 7. Tests y CI

Job `fcp11-control-plane` en `.github/workflows/fabric-ci.yml`: `py_compile` y 10 suites
`scripts.tests.test_fabric_control_plane_*` (contract, snapshot, evidence, history, resources,
attention, gateway, cli, view, integration) con mínimos por suite, total ≥ 300, sin skips,
xfails ni unexpected successes. Flet no se instala en CI: la vista usa un stub aislado y
`app/main.py` / `sidebar.py` se verifican por AST.

## 8. Criterios de cierre FCP-11

1. Runner SUCCESS de WO-01..WO-08 con checkpoint y worktree limpio.
2. CI verde: job FCP-11 y todos los jobs previos sin relajar.
3. `git diff --check` y `py_compile` limpios.
4. Auditoría independiente (distinta de Runner SUCCESS y de CI) sin hallazgos bloqueantes.
5. Decisión explícita de Dirección. Cualquier actuación (pausa/cancelación/reanudación)
   requiere una campaña nueva con gateway gobernado; no forma parte de FCP-11.
