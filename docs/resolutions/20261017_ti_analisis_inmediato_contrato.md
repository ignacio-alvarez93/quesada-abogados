# RESOLUCIÓN SOBRE LA EXCEPCIÓN DE CLASIFICACIÓN INMEDIATA POST-RECOGIDA EN TREND INTELLIGENCE

**Proyecto:** Quesada Abogados ERP / Trend Intelligence
**Fecha:** 17 de octubre de 2026
**Estado:** APROBADA — evolución de contrato aprobada por Dirección mediante petición del usuario (WO TI-4C.3E3-G1)
**Naturaleza:** Evolución excepcional, explícita y restringida del contrato TI-4C.1
**Implantación:** NO implantada todavía. Esta resolución solo fija el contrato, el guard y el lock compartido; el servicio se implementará en la WO E3A2.

---

# I. OBJETO

El contrato TI-4C.1 prohibía cualquier hook del productor de Trend Intelligence
(`backend/trend_intelligence/producer.py`) fuera de su propio módulo y de la
composición manual del CLI `scripts/trend_producer_run.py`.

La Dirección autoriza una **única excepción**: la clasificación inmediata de los
posts recién recogidos (`classify_pending`) desde un servicio de aplicación
dedicado, una vez concluida correctamente la recogida.

# II. ALCANCE DE LA EXCEPCIÓN

Se permite **exclusivamente**:

* Un único archivo: `backend/services/trend_post_collection_service.py` (aún no existe).
* Una única fase: `classify_pending`, preferiblemente con el productor inyectado
  (factoría o instancia) y, como máximo, componiéndolo con `create_trend_producer`.
* Condiciones previas obligatorias: navegador cerrado/liberado y recogida
  confirmada como correcta. Si no se cumplen, el servicio no clasifica.
* Exclusión mutua obligatoria con el CLI mediante el mismo lock OS por store:
  `backend/trend_intelligence/process_lock.py` (mismo directorio por usuario,
  misma clave SHA-256 de la ruta canónica, mismo fichero; `BUSY` no bloqueante,
  cualquier otro error falla cerrado).

# III. LO QUE SIGUE PROHIBIDO

* `process_windows` / `process_window` / `run_once` / `TrendProducerRunService`
  o el pipeline automático desde el servicio post-recogida o desde cualquier
  ruta distinta del CLI manual.
* Snapshots intradía o provisionales presentados como definitivos.
* Trigger directo desde frontend, `app`, Collector
  (`instagram_collector_control_service.py`), QCC, Fabric, schedulers o
  imports dinámicos/disfrazados (`importlib`, `__import__`, `exec`, strings partidas, `getattr` dinámico).
* Que cualquier módulo invoque al servicio post-recogida mientras la allowlist
  de llamadores (`POST_COLLECTION_CALLERS`) esté vacía. E3A2 deberá ampliarla
  de forma explícita y nominal.

# IV. CONSOLIDACIÓN DIARIA

La consolidación por ventanas (snapshots) se mantiene **solo sobre días UTC
completos y cerrados** (`window_to` ≤ ahora). El día UTC en curso nunca se
consolida. La clasificación inmediata no altera esta regla: clasificar un post
no produce analytics ni snapshots.

# V. SEPARACIÓN DE RESPONSABILIDADES

```text
COLLECTOR  → recoge y persiste posts; no conoce el productor.
ANALYSIS   → clasificación (excepción post-recogida gobernada) y
             consolidación diaria de días cerrados (CLI manual).
DASHBOARD  → solo lectura de snapshots definitivos.
```

El Collector no importa ni invoca el productor; la orquestación post-recogida
residirá en el servicio de aplicación autorizado y se inyectará de forma
controlada en E3A2.

# VI. GARANTÍAS TÉCNICAS (TI-4C.3E3-G1)

* `scripts/tests/test_trend_intelligence_producer.py`: guard de allowlist
  estricta (`PRODUCER_ALLOWLIST` = productor, CLI y la ruta autorizada) con
  fuentes positivas y negativas; el servicio autorizado solo puede clasificar.
* `backend/trend_intelligence/process_lock.py`: implementación única del lock,
  usada por el CLI mediante alias de compatibilidad.
* `scripts/tests/test_trend_process_lock.py`: interoperabilidad CLI/backend,
  `BUSY` en mismo store, distinto store no bloquea, liberación al morir el
  proceso y fallo cerrado.
* Los pins de inmutabilidad por `git diff` se sustituyen por tests semánticos
  equivalentes o más fuertes.
