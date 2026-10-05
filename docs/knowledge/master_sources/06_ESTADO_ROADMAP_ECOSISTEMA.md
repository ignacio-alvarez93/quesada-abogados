# `06_ESTADO_ROADMAP_ECOSISTEMA.md` — FUENTE MAESTRA DE ESTADO TÉCNICO, ROADMAPS Y EVOLUCIÓN DEL ECOSISTEMA

**Proyecto:** Quesada Abogados CRM
**Naturaleza del Documento:** Fuente Maestra Consolidada 06 de 06 — **EXCLUSIVAMENTE INFORMATIVA Y NO NORMATIVA**
**Estado:** APROBADO POR DIRECCIÓN
**Trazabilidad:** Construido a partir del Registro Canónico Aprobado (`00_MASTER_INDEX.md`) y fundado en las fuentes informativas del proyecto: `20260809_resolucion_estado_actual_proyecto_y_hoja_ruta_supabase.md` (secciones de estado, porcentajes y diagnóstico histórico), `fabricroadmap.txt`, `hojaruta_4semseptiembre.txt`, `30 mejorasQCC.txt`, `QCC_15_mejoras_futuras.txt` y `AMPLIACIONQCC.txt`.

---

## SECCIÓN I: ALCANCE Y NATURALEZA NO NORMATIVA

La presente Fuente Maestra posee un carácter **ESTRICTAMENTE INFORMATIVO, DIAGNÓSTICO Y DE HOJA DE RUTA**.

1. **Ausencia de Autoridad Normativa:** Este documento no crea autoridad normativa por sí mismo, no contiene decisiones vinculantes, no crea nuevos identificadores canónicos (`GOV`, `DEV`, `GIT`, `FAB`, `SEC`, `ARCH`, `DATA`, `UI`, `DOC`, `KNOW`, `OPS`, `WEB`, `QCC`, `SITE`, `TWIN`) ni altera ninguna de las 54 decisiones normativas aprobadas en el Registro Canónico (`00_MASTER_INDEX.md`).
2. **Propósito:** Consolidar el inventario de estado técnico, las métricas históricas de madurez, los diagnósticos de componentes, los programas de desarrollo futuro (Fabric Closure Program, Universal Web Twin, catálogos de mejoras QCC) y las divergencias documentales detectadas entre la normativa histórica y la evolución del código.
3. **Interpretación:** Ninguna cifra, porcentaje, fase de roadmap o diagnóstico técnico contenido en esta Fuente Maestra puede interpretarse como una regla de arquitectura ni como una obligación de desarrollo.

---

## SECCIÓN II: ESTADO HISTÓRICO DOCUMENTADO DEL ERP

*(Fuente principal: `20260809_resolucion_estado_actual_proyecto_y_hoja_ruta_supabase.md`)*

### 1. Métricas Globales de Madurez (Auditoría fechada el 9 de agosto de 2026)
Las siguientes cifras reflejan el diagnóstico técnico realizado en la auditoría formal del **9 de agosto de 2026** y no deben ser presentadas como cifras actuales dinámicas sin una nueva auditoría:

- **Avance funcional global del ERP:** ~81 %.
- **Madurez técnica global del backend y gobierno:** ~82 %.
- **Motor general de Expedientes:** ~90 % (con cobertura jurídica configurada de ~35–40 %).
- **Preparación arquitectónica para PostgreSQL / Supabase:** ~66 %.
- **Implementación efectiva realizada en PostgreSQL:** 0 %.

### 2. Desglose Histórico por Dominios Funcionales (9 de agosto de 2026)
- **Clientes (`005`):** ~82 % de madurez.
- **Sistema Documental (`011`, `014`):** ~87 % (Box Watcher, Bandeja de entrada, clasificación).
- **Económico y Cobros (`007`, `008`):** ~83 % (Hojas de encargo, conciliación bancaria).
- **Calendar (`20260809_gobierno_codigo`):** 100 % (cerrado funcionalmente como proyección temporal).
- **TASK (`20260809_gobierno_codigo`):** ~90 % (pendiente estructura `task_work_sessions`).
- **Notificaciones / DEHú:** ~89 % (outbox y conectores).
- **Plataforma Email:** ~88 % (sincronización Gmail/IONOS).
- **Reporting:** ~35 % (prioridad pospuesta tras la migración a PostgreSQL).
- **Knowledge (`015`):** 0 % (desarrollo previsto tras la estabilización central).

*Nota de desambiguación:* Los 6 Gates de transición a PostgreSQL/Supabase descritos en dicha resolución forman parte de la decisión normativa aprobada **`DATA-010`** (Fuente Maestra `02_ARQUITECTURA_ERP_DATOS.md`) y no se duplican aquí como roadmap opcional.

---

## SECCIÓN III: ESTADO Y EVOLUCIÓN DOCUMENTADA DE FABRIC / RUNNER

*(Fuentes: `fabricroadmap.txt`, `hojaruta_4semseptiembre.txt`)*

### 1. Estado de la Herramienta Interna Fabric
- **Avance técnico acumulado:** ~75–80 % de madurez técnica estimada en el documento de roadmap tras el cierre del bloque `FDB`.
- **Función operativa:** Herramienta interna de desarrollo diseñada para la gestión automatizada de *worktrees*, ejecución de *Work Orders* y aislamiento de entornos.

### 2. Registro de Congelaciones y Cierre de Módulos por Claude (Septiembre 2026)
- **Módulo Social Media V1:** Declarado cerrado y congelado formalmente por Claude en el commit `cabe90e` (`FORMAL_CLOSURE=CLOSED`).
- **Módulo State-Aware + Safe Recovery:** Declarado cerrado y congelado formalmente por Claude en el commit `2c0f73c` (`FORMAL_CLOSURE=CLOSED`).

### 3. Diagnóstico Técnico en Runner V2.0 y Plan Hardening V2.1
- **Diagnóstico del fallo en V2.0:** Detección del error `EXECUTOR_EXCEPTION` producido por la ausencia del archivo de control `git_before.txt` tras retornos exitosos del ejecutor Claude.
- **Hardening V2.1:**
  - Separación explícita entre los estados `WORK_SUCCESS` (ejecución técnica completada) y `EVIDENCE_COMPLETE` (verificación de pruebas sintéticas).
  - Implementación de un *ledger* persistente de eventos para prevenir falsos *timeouts* de ejecución.

---

## SECCIÓN IV: ESTADO Y EVOLUCIÓN DOCUMENTADA DE QCC / SITE ARCHITECTURE / AUTO TWIN

*(Fuentes: `QCC_15_mejoras_futuras.txt`, `30 mejorasQCC.txt`, `AMPLIACIONQCC.txt`, `20260905_resolucion_qcc_auto_twin_arquitectura_fidelidad_sincronizacion.md`)*

### 1. Evolución Histórica de Propuestas QCC
- **Catálogo de 15 Mejoras Futuras (25/08/2026):** Documento inicial de prospección funcional (`QCC_15_mejoras_futuras.txt`) que planteaba prioridades para Self-Healing, Contract Watcher y Geometry JIT.
- **Catálogo de 30 Mejoras QCC (Posterior a agosto de 2026):** Ampliación propuesta (`30 mejorasQCC.txt`) que registra capacidades del kernel ya consolidadas (301 tests de extensión pasando, 1998 tests de suite global) frente a capacidades en evaluación (marcadas con ⚪ NUEVO).
- **Visión Universal Web Twin (`AMPLIACIONQCC.txt`):** Documento de análisis que estima la capacidad de contexto de QCC al ~91–92 % funcional y ~97 % en potencia arquitectónica, diagnosticando el defecto de transición al entrar en nuevas pantallas en Mercurio EX02 (`X → acción → B provisional`).

### 2. Estado de Materialización de Réplicas LABS / TWIN (Instantánea Diagnóstica)
- **Mercurio (Extranjería):** EX01 (Golden Reference manual), EX00, EX02, EX03, EX04, EX10 en diversos grados de captura y sincronización de estados (`revision_id`).
- **Otras Sedes Operativas:** Pruebas de concepto y capturas en Red SARA, DEHú y Nacionalidad por Residencia.

*Aclaración:* El recuento concreto de pantallas o estados materializados en un momento dado es un dato diagnóstico de estado y no constituye una norma permanente.

---

## SECCIÓN V: ROADMAPS DOCUMENTADOS DEL ECOSISTEMA

*(Los roadmaps integrados en esta sección constituyen planes de trabajo previstos y no decisiones normativas aprobadas).*

### 1. Fabric Closure Program (FCP)
Roadmap de 12 fases para la evolución y cierre de la herramienta interna Fabric (`fabricroadmap.txt`):
- `FCP-1`: Canonical Base & Integration Manager
- `FCP-2`: Semantic Reconciliation Pipeline
- `FCP-3`: Autonomous Promotion
- `FCP-4`: Worktree Lifecycle Manager
- `FCP-5`: Pipeline / DAG Engine
- `FCP-6`: Failure / Retry Intelligence
- `FCP-7`: Provider Router
- `FCP-8`: Validation & Evidence Engine
- `FCP-9`: Scheduler & Parallel Execution
- `FCP-10`: Resource / Quota Manager
- `FCP-11`: Observability / Control Plane
- `FCP-12`: Self-Dogfood & Closure

### 2. Universal Web Twin Program (UWT)

`AMPLIACIONQCC.txt` documenta un programa UWT estructurado en 12 fases (`UWT-1` a `UWT-12`) para extender QCC + AUTO TWIN desde la identificación de contexto y captura estructural hasta la exploración, sincronización, validación y certificación multi-site.

Los documentos de trabajo posteriores muestran que la nomenclatura interna y las subfases operativas han evolucionado durante la ejecución —por ejemplo, aparecen subdivisiones como `UWT-7A1`, `UWT-7A2` y trabajos de integración asociados—. Por ese motivo esta Fuente Maestra **no congela como canónico un título exacto para cada UWT-1..12**.

Los ejes técnicos documentados del programa incluyen, entre otros:

- intención de rama y aislamiento de contexto;
- captura DOM, sanitización y arquitectura estructural;
- captura visual/CSS y geometría;
- modelado semántico y contratos;
- materialización del TWIN local;
- construcción y aprendizaje del grafo de estados/transiciones;
- detección de mutaciones y diferencias;
- sincronización REAL ↔ TWIN;
- validación automatizada;
- exploración gobernada;
- robustez de selectores y self-healing;
- certificación y promoción multi-site.

La numeración concreta de subfases y su estado de ejecución debe consultarse en el documento operativo vigente de UWT y no interpretarse como arquitectura normativa.


### 3. Hoja de Ruta Operativa Coyuntural
Plan de trabajo coyuntural para la 4ª semana de septiembre de 2026 (`hojaruta_4semseptiembre.txt`):
- Subsanación de errores en Runner V2.0.
- Desacoplamiento de Worktrees por carril de ejecución.
- Suite de tests sintéticos para el Centro de Actividades Administrativas (CAA).

---

## SECCIÓN VI: DIVERGENCIAS ENTRE NORMATIVA HISTÓRICA Y REALIDAD TÉCNICA POSTERIOR

Las siguientes divergencias son **informativas**. No modifican por sí mismas las decisiones canónicas vigentes.

1. **Fabric multiprovider / multiworker — FORMALIZADO**
   - La evolución queda formalizada por `20261005_resolucion_fabric_multiproveedor_orquestacion_y_cierre_provider_neutral.md` mediante `GOV-002`, `GIT-003` y `FAB-002`.
   - `GOV-001`, `GIT-002` y `FAB-001` conservan trazabilidad histórica con sus estados modificados correspondientes.

2. **Knowledge nativo — FORMALIZADO**
   - La evolución queda formalizada por `20261005_resolucion_knowledge_nativo_y_gobierno_de_conocimiento.md` mediante `KNOW-003`.
   - `KNOW-001` pasa a MODIFICADA; `KNOW-002` permanece VIGENTE.
   - NotebookLM queda como herramienta externa auxiliar y no como repositorio canónico ni dependencia operativa de Knowledge.

3. **QCC V2 / Teaching Mode / aumento de páginas**
   - *Normativa histórica:* `QCC-003` limita la no interferencia DOM al alcance aprobado para QCC V1 y permite que una funcionalidad futura sea diseñada, justificada y aprobada expresamente.
   - *Realidad técnica posterior:* los roadmaps QCC incorporan Teaching Mode, inteligencia causal, capas visuales y propuestas de contextualización/intervención más profunda sobre las webs utilizadas.
   - *Tratamiento:* cualquier capacidad de modificación o augmentación activa del DOM debe quedar regulada mediante resolución posterior antes de convertirse en contrato productivo.

4. **Runtime local TWIN gobernado — FORMALIZADO**
   - La separación entre observación REAL y runtime local TWIN/preproducción queda formalizada por `20261005_resolucion_runtime_twin_gobernado_preproduccion.md` mediante `TWIN-006`.
   - El TWIN local se ejecuta mediante SeleniumBase gobernado; Chrome personal puede seguir siendo superficie humana y, cuando proceda, fuente de observación autorizada mediante QCC.
   - El aislamiento de sesión/runtime no debe degradar la fidelidad funcional ni eliminar información necesaria para reproducir estados y transiciones.

5. **Sistema documental Box — FORMALIZADO**
   - La divergencia `011 ↔ 016` queda resuelta por `20261005_resolucion_box_copia_bidireccional_controlada.md` mediante `DOC-003`.
   - `DOC-001` pasa a MODIFICADA PARCIALMENTE; se permiten copias nuevas controladas y trazables ERP ↔ Box.
   - Delete, move, rename, sobrescritura silenciosa y reorganización siguen prohibidos por defecto.
   - Watchdog/Listener pasivo, Event Ledger, estabilidad de archivos y reconciliación periódica quedan incorporados como objetivo funcional del sistema documental.

---

## SECCIÓN VII: MATERIAS CANDIDATAS A FUTURA RESOLUCIÓN FORMAL

Esta relación es **no normativa**. Identifica materias cuya realidad técnica o decisión de producto ha evolucionado y que deberían auditarse antes de dictar, en su caso, una resolución posterior:

1. **QCC V2 y augmentación del DOM:** Teaching Mode, overlays, inyección de contexto, aprendizaje de interacción y fronteras entre observación, asistencia y modificación.
2. **Cutover PostgreSQL/Supabase:** cuando los Gates de `DATA-010` estén acreditados, una resolución de puesta en producción podrá fijar baseline final, estrategia de migración, rollback, seguridad y fecha de autoridad de la nueva persistencia.

No se propone resolución nueva para una materia únicamente porque exista un roadmap o una idea; debe existir una decisión funcional/arquitectónica real que necesite autoridad y trazabilidad.

---

## SECCIÓN VIII: ELEMENTOS EXPLÍCITAMENTE NO CONVERTIDOS EN NORMA

En aplicación del Protocolo `000`, permanecen expresamente fuera del rango normativo:

- porcentajes de avance, potencia o madurez técnica, aunque se documenten históricamente;
- recuentos de tests, revisiones, pantallas, estados materializados o commits de trabajo;
- bugs, diagnósticos y planes coyunturales de hardening;
- fases y subfases FCP/UWT mientras solo pertenezcan a roadmap o ejecución;
- capacidades marcadas como propuestas futuras en `30 mejorasQCC.txt`;
- estimaciones temporales o de esfuerzo;
- la elección efectiva de Claude, Codex u otro proveedor en una ejecución concreta;
- estados de módulos o sedes que puedan cambiar con nuevas implementaciones;
- propuestas de futuras resoluciones contenidas en esta Fuente Maestra;
- cualquier evolución operativa descrita en la Sección VI que todavía carezca de una resolución posterior aprobada.

---

> ESTADO: 06_ESTADO_ROADMAP_ECOSISTEMA — APROBADO POR DIRECCIÓN
