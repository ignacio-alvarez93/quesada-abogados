# RESOLUCIÓN DE EVOLUCIÓN DEL SISTEMA DE DIRECCIÓN TÉCNICA, FABRIC Y EJECUCIÓN MULTIPROVEEDOR

**Fecha:** 05/10/2026
**Proyecto:** Quesada Abogados
**Estado:** APROBADA POR DIRECCIÓN
**Ámbito:** Gobierno técnico, Fabric, Work Orders, proveedores, Runner, worktrees, cierre e integración.

---

## I. OBJETO

La presente resolución formaliza la evolución del modelo de desarrollo del proyecto Quesada Abogados desde una ejecución centrada específicamente en Claude hacia una arquitectura **multiproveedor, provider-neutral y gobernada mediante Fabric**.

No se altera la autoridad de la Dirección del Proyecto ni la función de ChatGPT como Dirección Técnica y Arquitectónica.

La evolución afecta parcialmente a:

- `GOV-001` · Modelo de Dirección Técnica Tripartita y Separación de Roles.
- `GIT-002` · Desarrollo por Tuberías Continuas, Worktrees Paralelos y regla `CLAUDE CLOSED`.
- `FAB-001` · Work Orders como Unidad Canónica de Especificación y Trabajo.

---

## II. PRINCIPIO DE GOBIERNO

Se mantiene la siguiente jerarquía:

```text
DIRECCIÓN DEL PROYECTO
        ↓
CHATGPT
Dirección Técnica / Arquitectura
        ↓
WORK ORDER
        ↓
FABRIC
        ↓
RUNNER / WORKER
        ↓
PROVEEDOR SELECCIONADO
        ↓
CÓDIGO + TESTS + EVIDENCIA
        ↓
AUDITORÍA / PROMOCIÓN / INTEGRACIÓN
```

La Dirección del Proyecto conserva la autoridad final sobre estrategia, prioridades, decisiones funcionales, aceptación de riesgos y decisiones arquitectónicas finales.

ChatGPT conserva la Dirección Técnica y Arquitectónica: visión global, contratos, arquitectura, Work Orders, criterios de aceptación, interpretación de evidencia, decisión de siguientes pasos y coordinación de Fabric, Runner y proveedores.

Ningún proveedor de IA adquiere autoridad arquitectónica autónoma.

---

## III. GOV-002 · MODELO DE EJECUCIÓN MULTIPROVEEDOR

Se aprueba `GOV-002 · Modelo de Ejecución Multiproveedor bajo Dirección Técnica Única`.

Claude deja de ser el ejecutor normativamente exclusivo del proyecto.

Fabric podrá utilizar Claude, Codex, otros proveedores presentes o futuros, workers especializados o combinaciones de proveedores por fases.

La selección se realizará según calidad, especialización, velocidad, coste, contexto disponible, herramientas, fiabilidad, cuota/disponibilidad e historial de resultados.

La arquitectura del proyecto no se adaptará al proveedor. El proveedor deberá adaptarse a contratos, Work Orders, restricciones, tests, evidencias, gobierno y arquitectura aprobada.

### Efecto sobre GOV-001

`GOV-001` pasa a **MODIFICADA PARCIALMENTE**.

Se mantienen plenamente Dirección Humana, ChatGPT como Dirección Técnica, separación entre dirección y ejecución y prohibición de autonomía arquitectónica del ejecutor.

Se sustituye únicamente la identificación de Claude como ejecutor técnico único por la capa multiproveedor gobernada por Fabric.

---

## IV. FAB-002 · FABRIC COMO VÍA NORMAL DE EJECUCIÓN

Se aprueba `FAB-002 · Fabric como Orquestador Principal y Provider-Neutral`.

Cuando Fabric esté disponible y una tarea pueda ejecutarse mediante él, Fabric será la vía normal de ejecución asistida del proyecto.

Fabric deberá ser capaz, progresivamente y según su estado de implementación, de recibir objetivos y Work Orders, resolver repositorio/rama/base, crear o reutilizar worktrees, asignar ownership, seleccionar proveedor, ejecutar, supervisar, recuperar resultados, lanzar tests, validar evidencia, clasificar fallos, reintentar o cambiar proveedor cuando proceda, reconciliar drift, promover resultados, limpiar recursos y encadenar fases.

Fabric no sustituye la Dirección Técnica. Ejecuta decisiones ya tomadas y devuelve evidencia para revisión.

---

## V. FAB-001 · EVOLUCIÓN DE LAS WORK ORDERS

`FAB-001` permanece como principio estructural, pero pasa a **MODIFICADA PARCIALMENTE** en su redacción específica de proveedor.

La Work Order continúa siendo la unidad principal de especificación, comunicación, alcance, contratos, ejecución, aceptación y evidencia.

Las Work Orders deberán ser **provider-neutral siempre que sea posible**.

Una WO no deberá depender innecesariamente de instrucciones exclusivas de Claude, Codex u otro proveedor.

Cuando una capacidad sea específica de un proveedor, deberá declararse explícitamente como restricción o adaptación de ejecución, sin alterar el contrato funcional de la WO.

Ante un hallazgo fuera de alcance, cualquier proveedor o worker deberá detener la ampliación unilateral del alcance, devolver evidencia estructurada y permitir a Fabric reintentar, escalar o devolver el conflicto a Dirección según política.

---

## VI. GIT-003 · CIERRE PROVIDER-NEUTRAL Y OWNERSHIP DE WORKTREES

Se aprueba `GIT-003 · Cierre Provider-Neutral, Ownership y Paralelización Segura`.

Se conserva el principio de desarrollo mediante worktrees y trabajos paralelos desacoplados.

Queda prohibido que dos trabajos independientes modifiquen simultáneamente los mismos archivos críticos, el mismo contrato, la misma migración, el mismo esquema, la misma fuente canónica o superficies con solapamiento material no coordinado.

Todo worktree o job deberá tener ownership identificable.

### Cierre

El estado de cierre deja de depender del proveedor concreto.

`CLAUDE CLOSED` deja de ser el contrato canónico de cierre para nuevos trabajos.

El cierre pasa a depender de un contrato de evidencia:

```text
IMPLEMENTACIÓN
    ↓
TESTS
    ↓
REGRESIÓN
    ↓
SCOPE / DIFF AUDIT
    ↓
EVIDENCIA
    ↓
REVISIÓN
    ↓
PROMOCIÓN / INTEGRACIÓN
    ↓
CLOSED
```

Un módulo cerrado no podrá ser reabierto mediante modificaciones manuales ad hoc.

Toda evolución posterior deberá entrar de nuevo mediante nueva Work Order, Fabric, worktree gobernado, proveedor seleccionado, tests y evidencia.

### Compatibilidad histórica

Los módulos históricamente marcados `CLAUDE CLOSED` conservan su condición de cierre.

La presente resolución no invalida cierres anteriores.

Únicamente sustituye el requisito de que el proveedor concreto Claude sea quien deba producir todos los cierres futuros.

### Efecto sobre GIT-002

`GIT-002` pasa a **MODIFICADA**.

Se conservan paralelización por worktrees, separación de superficies, prohibición de dos cierres paralelos sobre el mismo dominio y no reapertura manual de módulos cerrados.

Se sustituyen dependencia normativa de Claude, etiqueta `CLAUDE CLOSED` como único mecanismo futuro de cierre y obligación de dirigir toda evolución exclusivamente a Claude.

---

## VII. RUNNER

Runner se establece como capacidad de ejecución controlada de Fabric.

Runner podrá inspeccionar repositorios, ejecutar comandos, modificar código dentro del alcance autorizado, lanzar tests, ejecutar diagnósticos, gestionar procesos, recopilar evidencia y devolver resultados estructurados.

Runner no decide arquitectura ni amplía el alcance funcional. Ejecuta Work Orders y políticas de Fabric.

---

## VIII. MULTIWORKER Y PARALELIZACIÓN

Fabric podrá ejecutar varios workers o proveedores en paralelo cuando las superficies sean materialmente desacopladas.

La productividad se optimizará por trabajo correcto, probado e integrable terminado por unidad de tiempo.

La paralelización no justifica colisiones de archivos, doble ownership, cambios simultáneos en contratos incompatibles, migraciones concurrentes no coordinadas, reducción de tests ni integración sin evidencia.

---

## IX. RECUPERACIÓN Y FALLBACK

Los fallos deberán clasificarse para permitir, cuando resulte seguro: retry, resume, repair Work Order, cambio de proveedor, nuevo worker, quarantena de worktree o revisión humana.

Los conflictos arquitectónicos, funcionales o semánticos que impliquen una nueva decisión deberán volver a Dirección.

Fabric no podrá resolver autónomamente una decisión arquitectónica pendiente.

---

## X. EVOLUCIÓN FUTURA DE FABRIC Y REDUCCIÓN SISTEMÁTICA DE INTERVENCIÓN MANUAL

Fabric deberá evolucionar progresivamente para eliminar trabajo mecánico y repetitivo actualmente realizado por la Dirección o por el usuario.

Esta evolución constituye una dirección arquitectónica del producto interno Fabric, pero **no implica que todas estas capacidades estén ya implementadas** en la fecha de aprobación de la presente resolución.

El criterio de evolución será:

```text
PASO MANUAL REPETITIVO
        ↓
IDENTIFICACIÓN
        ↓
CONTRATO
        ↓
AUTOMATIZACIÓN SEGURA
        ↓
VALIDACIÓN
        ↓
INCORPORACIÓN A FABRIC
```

Fabric deberá reducir progresivamente, cuando resulte técnicamente seguro:

- copiar y pegar comandos entre ChatGPT, Git Bash, Runner y proveedores;
- copiar y pegar Work Orders o fragmentos de contexto entre herramientas;
- transferir manualmente resultados, logs, diffs y evidencias entre fases;
- localizar manualmente repositorios, ramas y worktrees;
- crear, reutilizar, bloquear, archivar o limpiar worktrees manualmente;
- decidir mecánicamente qué proveedor debe ejecutar una tarea cuando la política pueda resolverlo;
- relanzar manualmente trabajos tras timeouts, cuotas o fallos recuperables;
- ejecutar manualmente secuencias repetitivas de tests, regresiones y validaciones;
- revisar manualmente evidencias estructuradas que puedan validarse mediante contratos automáticos;
- realizar manualmente cherry-picks, reconciliaciones o promociones triviales cuando Fabric pueda demostrar que son seguras;
- encadenar manualmente fases dependientes de un mismo objetivo;
- repetir contexto ya conocido por Fabric, Runner o la Work Order;
- mantener múltiples terminales como mecanismo ordinario de supervisión cuando exista un Control Plane suficiente.

El objetivo evolutivo será pasar de:

```text
DIRECCIÓN
→ genera instrucciones
→ usuario copia
→ terminal
→ proveedor
→ usuario recupera resultado
→ copia evidencia
→ Dirección interpreta
→ nuevo comando
```

a:

```text
DIRECCIÓN
→ OBJETIVO / WORK ORDER
→ FABRIC
   → resuelve contexto
   → prepara ejecución
   → selecciona proveedor
   → ejecuta
   → supervisa
   → recupera
   → valida
   → prueba
   → reconcilia
   → integra
   → limpia
   → encadena siguiente fase
→ RESULTADO + EVIDENCIA
```

La automatización deberá priorizar primero pasos repetitivos, deterministas, de bajo riesgo y verificables automáticamente.

Permanecerán bajo control humano o de Dirección, salvo resolución expresa posterior:

- decisiones funcionales;
- decisiones arquitectónicas;
- aceptación de riesgos;
- conflictos semánticos no resolubles automáticamente;
- credenciales, MFA o intervención humana obligatoria;
- operaciones irreversibles o de alto impacto;
- cambios de contrato no previamente aprobados.

Fabric deberá medir su evolución no por número de funciones añadidas, sino por reducción real de:

- intervención manual;
- tiempo de espera;
- pasos mecánicos;
- repetición de contexto;
- errores de integración;
- reintentos manuales;
- trabajo administrativo del desarrollo.

El indicador rector será:

```text
TRABAJO CORRECTO, PROBADO E INTEGRABLE TERMINADO
------------------------------------------------
TIEMPO + INTERVENCIÓN HUMANA
```

La mejora futura de Fabric deberá perseguir que una proporción creciente del ciclo:

```text
IDEA
→ ESPECIFICACIÓN
→ EJECUCIÓN
→ TESTS
→ REVISIÓN
→ INTEGRACIÓN
```

pueda ser orquestada automáticamente sin transferir a Fabric autoridad sobre decisiones que corresponden a Dirección.

---

## XI. PRINCIPIO DE REUTILIZACIÓN Y APRENDIZAJE DE LA FÁBRICA

Fabric, Runner, Work Orders, pipelines, providers y herramientas internas constituyen también un producto interno sujeto a mejora continua.

Cuando aparezca repetidamente un paso manual, cuello de botella, pérdida de contexto, reconciliación repetitiva, validación mecánica o intervención humana automatizable, deberá valorarse su incorporación a Fabric.

Cada automatización interna deberá diseñarse para ser reutilizable en trabajos futuros y no únicamente para resolver una ejecución aislada.

El objetivo no es producir más código. El objetivo es producir más trabajo correcto, probado e integrable con menor intervención manual y sin pérdida de control.

---

## XII. DECISIONES CANÓNICAS RESULTANTES

Tras la aprobación de esta resolución:

- `GOV-001` → **MODIFICADA PARCIALMENTE**
- `GOV-002` → **VIGENTE**
- `GIT-002` → **MODIFICADA**
- `GIT-003` → **VIGENTE**
- `FAB-001` → **MODIFICADA PARCIALMENTE**
- `FAB-002` → **VIGENTE**

No se alteran `DEV-002`, `DEV-003`, `DEV-004`, `GIT-001` ni `SEC-001`.

---

## XIII. PRINCIPIO FINAL

```text
DIRECCIÓN HUMANA
+ CHATGPT
+ FABRIC
+ RUNNERS / WORKERS
+ PROVEEDORES
+ WORKTREES
+ PIPELINES
+ TESTS
+ EVIDENCIA
+ REUTILIZACIÓN
+ AUTOMATIZACIÓN
```

Objetivo:

> **MÁS TRABAJO CORRECTO TERMINADO, EN MENOS TIEMPO, CON MENOR INTERVENCIÓN MANUAL, SIN SACRIFICAR ROBUSTEZ NI CONTROL.**

---

**ESTADO FINAL:** APROBADA POR DIRECCIÓN
