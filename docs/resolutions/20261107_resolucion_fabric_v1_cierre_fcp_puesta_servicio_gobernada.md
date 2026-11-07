# RESOLUCIÓN DE DIRECCIÓN

## FABRIC SOFTWARE FACTORY V1 — CIERRE DEL PROGRAMA FCP-1…FCP-12, PUESTA EN SERVICIO GOBERNADA Y RÉGIMEN DE EVOLUCIÓN POST-FCP

**Proyecto:** Quesada Abogados
**Fecha:** 7 de noviembre de 2026
**Estado:** APROBADA POR DIRECCIÓN
**Identificador canónico:** `FAB-003`
**Fuente técnica principal:** `INF-FABRIC-V1-20261107`
**Naturaleza:** Resolución normativa de consolidación, reconocimiento técnico, régimen operativo y evolución de Fabric Software Factory V1.

---

# I. OBJETO

La presente resolución tiene por objeto:

1. reconocer formalmente el cierre técnico del programa `FCP-1…FCP-12`;
2. reconocer el cierre de la campaña correctiva P0 posterior;
3. establecer Fabric Software Factory V1 como infraestructura operativa de desarrollo gobernado del proyecto;
4. fijar los límites de su autonomía;
5. preservar el modelo multiproveedor, la separación de autoridad y los controles Git, Runner, tests y evidencia;
6. establecer el régimen de evolución posterior a FCP;
7. orientar dicha evolución a una reducción sistemática de intervención manual, corta/pega, relanzamientos y transporte humano de contexto y evidencia.

Esta resolución desarrolla `FAB-002` y no la sustituye.

---

# II. ANTECEDENTES Y ESTADO TÉCNICO RECONOCIDO

Dirección reconoce como estado técnico acreditado a fecha de 7 de noviembre de 2026:

- ejecución e integración de `FCP-1` a `FCP-12`;
- integración de FCP-11 mediante PR #35;
- integración de FCP-12 mediante PR #36;
- cierre e integración de la campaña correctiva P0 mediante PR #37;
- baseline técnica de referencia del cierre:

`e7f27e02b9063f049717796899acf566e0af4efa`

sobre rama `develop`;

- ejecución satisfactoria de los workflows y suites expresamente acreditados en el informe técnico de cierre;
- existencia de capacidades integradas de Work Orders, Director/Runner, Git/worktrees, pipelines/DAG, recuperación, provider routing, validación/evidencia, scheduler/paralelismo, recursos/cuotas, observabilidad/control plane y self-dogfood.

La baseline indicada constituye una referencia histórica del cierre Fabric V1 y no inmoviliza futuras revisiones, commits o evoluciones de `develop`.

---

# III. DECISIÓN `FAB-003`

## `FAB-003` · Fabric Software Factory V1 como Fábrica de Desarrollo Gobernada en Servicio

### Estado

**VIGENTE**

### Decisión

Fabric Software Factory V1 queda reconocida como infraestructura propia, integrada y operativa de fábrica de software para campañas de desarrollo gobernadas del ecosistema Quesada Abogados.

Cuando una tarea de desarrollo resulte compatible con sus capacidades y políticas, Fabric deberá utilizarse como vía ordinaria de orquestación técnica conforme a `FAB-002`.

Fabric podrá, dentro de las capacidades implementadas y del alcance autorizado:

- recibir Work Orders;
- planificar trabajos;
- construir pipelines y DAG;
- seleccionar o enrutar proveedores conforme a política;
- ejecutar mediante Runner;
- gestionar ramas y worktrees gobernados;
- supervisar procesos;
- recopilar estados y evidencias;
- ejecutar validaciones y acceptance commands;
- bloquear propagación ante resultados no aceptados;
- conservar y recuperar trabajo parcial cuando se satisfagan los controles aplicables;
- coordinar ejecución serial o paralela segura;
- observar recursos y cuotas;
- preparar promoción e integración;
- proyectar información mediante su Control Plane;
- utilizar sus propias capacidades en procesos de self-dogfood bajo gobierno.

La afirmación de éxito de un proveedor nunca sustituye la validación del host, Runner, tests, evidencia o criterios de aceptación aplicables.

---

# IV. CIERRE DEL FABRIC CLOSURE PROGRAM

Se declara:

```text
FCP-1   Canonical Base & Integration Manager        CLOSED
FCP-2   Semantic Reconciliation Pipeline            CLOSED
FCP-3   Autonomous Promotion                        CLOSED
FCP-4   Worktree Lifecycle Manager                  CLOSED
FCP-5   Pipeline / DAG Engine                       CLOSED
FCP-6   Failure / Retry Intelligence                CLOSED
FCP-7   Provider Router                             CLOSED
FCP-8   Validation & Evidence Engine                CLOSED
FCP-9   Scheduler & Parallel Execution              CLOSED
FCP-10  Resource / Quota Manager                    CLOSED
FCP-11  Observability / Control Plane               CLOSED
FCP-12  Self-Dogfood & Closure                      CLOSED
```

`CLOSED` significa que la fase del programa ha sido ejecutada e integrada dentro del alcance acreditado.

No significa que:

- toda combinación posible haya sido probada;
- no exista deuda técnica;
- no puedan aparecer defectos;
- la capacidad sea autónoma sin límites;
- se eliminen tests, supervisión o gates;
- la capacidad no pueda evolucionar posteriormente.

Las futuras modificaciones de estas capacidades serán evolución de Fabric, no reapertura automática del programa FCP.

---

# V. RECONOCIMIENTO DE LA CAMPAÑA P0

Se reconoce como **CERRADA** la campaña correctiva P0 derivada de la auditoría integral posterior a FCP-1…12.

Quedan reconocidos los tres frentes correctivos:

```text
P0-A       Host / Provider Boundary
P0-B-FIX1  Work Order Integrity / DAG
P0-C       Module Governance / Acceptance
```

La campaña acredita especialmente:

- comportamiento fail-closed ante acceptance fallida;
- no generación de checkpoint válido cuando la aceptación no se supera;
- no liberación indebida de nodos dependientes;
- conservación de trabajo parcial;
- recuperación gobernada mediante `resume_from`;
- verificación de procedencia, rama, HEAD, scope y proceso previo;
- protección frente a determinadas escrituras fuera de alcance;
- validación de integridad de Work Orders;
- tests adversariales de estados y aceptación;
- mantenimiento de CI independiente para las regresiones P0.

Las suites y workflows P0 deberán conservarse mientras protejan riesgos vigentes y no deberán eliminarse únicamente para conseguir CI verde.

---

# VI. MODELO DE AUTORIDAD

Permanece vigente el siguiente circuito institucional:

```text
DIRECCIÓN HUMANA
        ↓
CHATGPT / DIRECCIÓN TÉCNICA
        ↓
WORK ORDER
        ↓
FABRIC
        ↓
RUNNER
        ↓
PROVEEDOR
        ↓
CÓDIGO + TESTS + EVIDENCIA
        ↓
REVISIÓN
        ↓
INTEGRACIÓN AUTORIZADA
```

### Dirección Humana

Conserva autoridad final sobre:

- objetivos;
- prioridades;
- arquitectura definitiva;
- excepciones;
- aceptación de riesgo;
- cambios funcionales relevantes;
- autorizaciones de alto impacto;
- régimen de integración y producción.

### ChatGPT / Dirección Técnica

Conserva:

- visión global;
- arquitectura;
- contratos;
- Work Orders;
- criterios de aceptación;
- secuenciación;
- interpretación de evidencia;
- decisión técnica sobre siguientes pasos dentro de la autoridad delegada.

### Fabric

Orquesta y ejecuta políticas aprobadas.

Fabric no crea normas ni decide autónomamente arquitectura.

### Runner

Ejecuta de forma controlada.

Runner no posee autoridad arquitectónica.

### Proveedores

Claude, Codex y futuros proveedores son capacidades técnicas complementarias o intercambiables.

Ningún proveedor posee autoridad arquitectónica autónoma.

---

# VII. MULTIPROVEEDOR

Se reafirma íntegramente `GOV-002`.

La arquitectura de Fabric continuará siendo provider-neutral.

La selección de proveedor podrá evolucionar en función de:

- capacidad;
- especialización;
- calidad;
- disponibilidad;
- cuota;
- coste;
- velocidad;
- fiabilidad;
- contexto;
- herramientas;
- resultados históricos acreditados.

La indisponibilidad o agotamiento de un proveedor no convierte a dicho proveedor en dependencia arquitectónica del trabajo.

Fabric deberá favorecer progresivamente handoffs gobernados entre proveedores cuando existan:

- Work Order estable;
- estado verificable;
- checkpoint o trabajo parcial recuperable;
- alcance identificado;
- evidencias suficientes;
- ausencia de conflicto de ownership.

El cambio de proveedor no podrá utilizarse para eludir gates, permisos o acceptance.

---

# VIII. PARALELISMO Y OWNERSHIP

Se reafirma `GIT-003`.

Fabric podrá coordinar trabajos paralelos exclusivamente cuando sean realmente desacoplados.

Continúan prohibidos:

- doble ownership no coordinado;
- modificación simultánea de archivos críticos;
- colisiones sobre contratos;
- colisiones sobre schemas o migraciones;
- colisiones sobre fuentes canónicas;
- modificación de worktrees propiedad de otros carriles;
- fusión automática de conflictos semánticos.

La capacidad técnica de ejecutar en paralelo no constituye autorización para paralelizar superficies incompatibles.

---

# IX. RÉGIMEN DE PUESTA EN SERVICIO

Se autoriza Fabric V1 para **puesta en servicio ampliada, progresiva y gobernada** en trabajos de desarrollo.

Su utilización ordinaria deberá mantener, según el riesgo y alcance:

- Work Order;
- permisos explícitos;
- scope;
- branch/worktree dedicado cuando proceda;
- aislamiento;
- tests;
- evidencia;
- CI;
- revisión;
- autorización humana cuando corresponda.

No se autoriza mediante esta resolución:

```text
AUTO-MERGE IRRESTRICTO
AUTOAPROBACIÓN
AUTOPROMOCIÓN DE ALTO IMPACTO
CAMBIO AUTÓNOMO DE ARQUITECTURA
ACCESO GENERAL A SECRETOS
ACCESO GENERAL A DATOS PERSONALES
EJECUCIÓN DESATENDIDA DE ALTO PRIVILEGIO
ELIMINACIÓN DE GATES HUMANOS DE RIESGO
```

`SUCCESS`, `READY`, CI verde o éxito declarado por el proveedor no equivalen por sí solos a autorización humana cuando esta sea requerida.

---

# X. GIT Y PROMOCIÓN

La baseline Fabric V1 queda integrada en `develop`.

La presente resolución no declara:

- integración en `main`;
- despliegue productivo general;
- certificación de producción sin restricciones.

Las promociones posteriores deberán continuar sometidas a la política Git vigente.

La rama estable no podrá ser modificada por atajos incompatibles con `GIT-001` y `GIT-003`.

---

# XI. SEGURIDAD

Permanece íntegramente vigente `SEC-001`.

Fabric no queda autorizado por defecto a exponer a proveedores:

- secretos;
- tokens;
- contraseñas;
- certificados;
- credenciales;
- datos de clientes;
- perfiles personales;
- entornos productivos privilegiados.

Las capacidades de automatización no reducen las obligaciones de aislamiento, mínimo privilegio y supervisión.

La autonomía aumenta en ejecución técnica, no en acceso indiscriminado.

---

# XII. RIESGOS RESIDUALES Y DEUDA P1

El cierre FCP y P0 no elimina toda deuda técnica.

Queda reconocida una cola post-V1 de revisión incremental que incluye, entre otras materias acreditadas:

- contabilización de capacidad y ocupación;
- límites de retry por cuotas y deadlines;
- robustez de rutas;
- normalización Git;
- alcance de determinados gates de self-dogfood;
- crecimiento y mantenimiento del ledger;
- actualización de documentación operativa histórica;
- ampliación de cobertura para combinaciones de proveedor, SO, concurrencia e interrupciones.

Estos elementos deberán resolverse mediante Work Orders independientes, priorizadas por impacto y evidencia.

No se autoriza una reescritura general de Fabric para abordar dicha deuda.

Aplicar:

```text
DIAGNOSTICAR
→ REUTILIZAR
→ CORREGIR
→ VALIDAR
→ TESTEAR
→ EVIDENCIA
→ CERRAR
```

---

# XIII. NUEVA ETAPA POST-FCP

Finalizado FCP-1…12, la evolución ordinaria de Fabric deja de organizarse necesariamente como continuación numérica del programa FCP.

No se crea automáticamente un `FCP-13`.

La etapa posterior deberá orientarse a **operacionalización, productividad, integración y explotación de las capacidades ya construidas**.

Principio rector:

> UTILIZAR Y CONECTAR LO YA CONSTRUIDO ANTES DE CREAR NUEVOS MOTORES.

Las prioridades deberán elegirse por impacto real sobre:

```text
REDUCCIÓN DE COPY/PASTE
REDUCCIÓN DE INTERVENCIÓN HUMANA MECÁNICA
REDUCCIÓN DE TRANSFERENCIA MANUAL DE CONTEXTO
REDUCCIÓN DE RELANZAMIENTOS
REDUCCIÓN DE GESTIÓN MANUAL DE WORKTREES
REDUCCIÓN DE REVISIÓN MANUAL REPETITIVA
MAYOR ENCADENAMIENTO AUTOMÁTICO
MAYOR REUTILIZACIÓN
MAYOR TRAZABILIDAD
```

sin sacrificar:

```text
ROBUSTEZ
CONTROL
SEGURIDAD
EVIDENCIA
TESTS
OWNERSHIP
AUTORIDAD HUMANA
```

---

# XIV. OBJETIVO DE INTERACCIÓN CHATGPT ↔ FABRIC

Se establece como dirección evolutiva prioritaria reducir progresivamente el uso del usuario como transportista manual entre Dirección Técnica y Fabric.

El modelo actual deberá evolucionar desde:

```text
CHATGPT
→ usuario copia
→ Git Bash / CLI
→ usuario copia resultado
→ CHATGPT
```

hacia:

```text
DIRECCIÓN HUMANA
        ↓
CHATGPT
        ↓
FABRIC
        ↓
RUNNER
        ↓
PROVEEDOR
        ↓
TESTS + EVIDENCIA
        ↓
FABRIC
        ↓
CHATGPT
```

Git Bash, PowerShell y CLI deberán conservarse como herramientas válidas de:

- diagnóstico;
- recuperación;
- bootstrap;
- emergencia;
- inspección;
- administración técnica;

pero deberán dejar progresivamente de ser el canal ordinario obligatorio para transportar instrucciones y resultados entre los componentes de la fábrica.

Antes de crear nuevas APIs, plugins, conectores, registros o motores se deberá auditar y reutilizar la infraestructura ya existente de:

- Control Plane;
- gateways;
- Director;
- Runner;
- Work Orders;
- ledger;
- evidencia;
- scheduler;
- Provider Router;
- Resource/Quota Manager;
- pipelines/DAG.

---

# XV. MEMORIA OPERATIVA Y TRAZABILIDAD

Se reconoce como objetivo de evolución que Fabric permita consultar de forma estructurada la historia operacional de su trabajo.

La trazabilidad deberá poder relacionar progresivamente:

```text
WORK ORDER
    ↓
PIPELINE / JOB
    ↓
ATTEMPT
    ↓
PROVIDER
    ↓
RUNNER
    ↓
WORKTREE
    ↓
EXECUTION
    ↓
TESTS
    ↓
EVIDENCE
    ↓
CHECKPOINT / COMMIT
    ↓
PROMOTION / CLOSURE
```

Antes de introducir persistencia nueva deberá auditarse la infraestructura existente de ledger, checkpoints, estados, historial y evidencias.

Se mantiene la separación conceptual:

```text
Git
= fuente de verdad del código

Resoluciones
= fuente de verdad normativa

Fabric / ledger
= trazabilidad operacional

Artifacts / evidence
= prueba técnica de ejecución
```

No se duplicará innecesariamente el repositorio Git dentro de una persistencia Fabric.

---

# XVI. FÁBRICA GENERALISTA Y FÁBRICAS ESPECIALIZADAS

Fabric V1 queda reconocida como infraestructura reutilizable de desarrollo y no como componente exclusivo del ERP Quesada Abogados.

Podrá utilizarse para construir otros productos o fábricas especializadas cuando existan:

- objetivo definido;
- arquitectura;
- Work Orders;
- toolchain;
- runners;
- permisos;
- tests;
- criterios de aceptación;
- decisión de Dirección cuando proceda.

La presente resolución no declara implementadas por el mero hecho de existir Fabric:

- Reporting Factory;
- Knowledge Factory;
- Documentation Factory;
- Publication Factory;
- aplicaciones móviles;
- gestores financieros;
- otras fábricas o productos futuros.

Cada uno requerirá su propio desarrollo y gobierno.

---

# XVII. MÉTRICAS

No se eleva a norma ningún porcentaje de potencia, madurez, autonomía o productividad.

Sí quedan reconocidos como hechos históricos del cierre:

```text
FCP-1…FCP-12: COMPLETADOS E INTEGRADOS
P0: CERRADO
PR #37: INTEGRADA
CI P0: VERDE EN LOS RUNS ACREDITADOS
BASELINE HISTÓRICA: e7f27e02b9063f049717796899acf566e0af4efa
```

Las futuras métricas de:

- throughput;
- coste;
- duración;
- defectos;
- retry rate;
- éxito por proveedor;
- intervención humana;
- reducción de copy/paste;

deberán obtenerse de explotación real y no estimarse como hechos.

---

# XVIII. RELACIÓN CON DECISIONES EXISTENTES

Esta resolución:

### DESARROLLA

- `FAB-002`.

### REAFIRMA

- `GOV-001`;
- `GOV-002`;
- `GOV-003`;
- `DEV-002`;
- `DEV-003`;
- `DEV-004`;
- `GIT-001`;
- `GIT-003`;
- `FAB-001`;
- `FAB-002`;
- `SEC-001`.

### NO MODIFICA

la autoridad final de Dirección Humana ni concede autoridad arquitectónica autónoma a Fabric, Runner o proveedores.

### NO SUSTITUYE

los contratos particulares de ERP, QCC, AUTO TWIN, Knowledge, IT, Marketing u otros productos usuarios de Fabric.

---

# XIX. ACTUALIZACIÓN DOCUMENTAL OBLIGATORIA

Tras la incorporación de esta resolución al repositorio, deberán actualizarse:

## `00_MASTER_INDEX.md`

Añadir:

```text
FAB-003
Fabric Software Factory V1 — Cierre FCP, Puesta en Servicio Gobernada y Régimen Post-FCP
Estado: VIGENTE
Fuente primaria:
20261107_resolucion_fabric_v1_cierre_fcp_puesta_servicio_gobernada.md
Fuente maestra: 01
```

Actualizar asimismo:

- corpus de resoluciones;
- trazabilidad FAB;
- relaciones `FAB-002 → FAB-003`;
- recuentos documentales que procedan.

## `01_GOBIERNO_DESARROLLO_FABRIC.md`

Añadir `FAB-003` dentro de la sección normativa `FAB`.

Actualizar la sección técnica no normativa para reflejar:

- FCP-1…12 completados;
- P0 cerrado;
- Fabric V1 operativa bajo gobierno;
- inicio de etapa post-FCP.

No eliminar ni reescribir `FAB-002`.

## `06_ESTADO_ROADMAP_ECOSISTEMA.md`

Actualizar el estado Fabric:

```text
FCP-1…12 = COMPLETADO
P0 = CERRADO
FABRIC V1 = OPERATIVA PARA USO GOBERNADO
POST-FCP = OPERACIONALIZACIÓN / PRODUCTIVIDAD / AUTOMATIZACIÓN
```

Mover cualquier representación de FCP como trabajo futuro a contexto histórico.

Mantener esta sección como no normativa.

## Fuentes no afectadas directamente

No se requiere modificación normativa de:

```text
02_ARQUITECTURA_ERP_DATOS.md
03_DOCUMENTAL_KNOWLEDGE_OPERACIONES.md
04_QCC_BROWSER_AUTOMATION.md
05_AUTO_TWIN_SITE_ARCHITECTURE.md
```

salvo que una futura decisión específica requiera integrar Fabric con alguno de esos dominios.

---

# XX. PRINCIPIO FINAL

Fabric deja de considerarse principalmente un programa de construcción pendiente.

Desde esta resolución se considera:

> **UNA FÁBRICA DE SOFTWARE V1 OPERATIVA, GOBERNADA Y EVOLUTIVA.**

Su prioridad posterior será hacer efectivo todo el potencial de las capacidades ya construidas.

El objetivo permanente será:

```text
MÁS TRABAJO CORRECTO
+
MÁS TRABAJO PROBADO
+
MÁS TRABAJO INTEGRABLE
+
MÁS AUTOMATIZACIÓN
+
MÁS REUTILIZACIÓN

CON

MENOS COPY/PASTE
+
MENOS TRANSPORTE MANUAL
+
MENOS ESPERAS
+
MENOS INTERVENCIÓN MECÁNICA

SIN SACRIFICAR

CONTROL
+
ROBUSTEZ
+
SEGURIDAD
+
TRAZABILIDAD
+
AUTORIDAD HUMANA
```

---

# XXI. ESTADO FINAL

**RESOLUCIÓN:** APROBADA POR DIRECCIÓN
**DECISIÓN CANÓNICA:** `FAB-003`
**FABRIC SOFTWARE FACTORY V1:** RECONOCIDA
**FCP-1…FCP-12:** CERRADO
**CAMPAÑA P0:** CERRADA
**RÉGIMEN OPERATIVO:** AMPLIADO, PROGRESIVO Y GOBERNADO
**AUTONOMÍA IRRESTRICTA:** NO AUTORIZADA
**ETAPA SIGUIENTE:** OPERACIONALIZACIÓN, PRODUCTIVIDAD, AUTOMATIZACIÓN Y REDUCCIÓN DE INTERVENCIÓN MANUAL
