# RESOLUCIÓN 20261010 — MODELO INTEGRAL OBLIGATORIO PARA AUTOMATIZACIONES ADMINISTRATIVAS

**Proyecto:** Quesada Abogados CRM
**Ámbito:** Automatizaciones · QCC · Site Architecture · AUTO TWIN · Formularios · Sedes electrónicas
**Estado:** APROBADA POR DIRECCIÓN
**Fecha:** 10 de octubre de 2026
**Carácter:** NORMATIVO

---

## I. OBJETO

Se establece como norma general del proyecto que la incorporación de una nueva automatización administrativa al CRM no podrá considerarse completada por la mera existencia de un script, flujo SeleniumBase o navegación automatizada sobre una sede electrónica.

Cada procedimiento automatizado deberá constituir una **unidad funcional integral**, gobernada por una única definición canónica y formada por los componentes establecidos en esta resolución.

Esta regla será aplicable, entre otras, a automatizaciones de:

- Mercurio.
- Red SARA.
- DEHú.
- Nacionalidad.
- UGE.
- Consulados.
- Registros electrónicos.
- Administraciones autonómicas o locales.
- Cualquier futura sede, portal o procedimiento administrativo integrado en el ecosistema.

---

# II. PRINCIPIO GENERAL

Toda automatización administrativa deberá construirse mediante el siguiente modelo:

```text
PROCEDIMIENTO ADMINISTRATIVO
        ↓
CONTRATO CANÓNICO DEL PROCEDIMIENTO
        ↓
┌───────────────────────────────────┐
│ 1. SUPERFICIE / FORMULARIO OFICIAL│
│ 2. FORMULARIO INTERNO CRM         │
│ 3. AUTOMATIZACIÓN DE LA SEDE      │
└───────────────────────────────────┘
        ↓
VALIDACIÓN / TESTS / EVIDENCIA
        ↓
AUTOMATIZACIÓN CERRADA
```

Los tres componentes forman una única capacidad funcional.

No deberán evolucionar como sistemas independientes ni mantener definiciones contradictorias de los mismos datos.

---

# III. COMPONENTE 1 — FORMULARIO O SUPERFICIE OFICIAL

Cada procedimiento deberá identificar y modelar su representación administrativa oficial.

Cuando exista formulario oficial descargable, deberá incorporarse:

- formulario PDF oficial;
- versión vigente;
- origen oficial;
- identificación del procedimiento;
- estructura de campos;
- campos obligatorios;
- reglas relevantes;
- mapper necesario para su cumplimentación.

Ejemplos:

```text
Mercurio EX01
→ formulario oficial EX-01

Mercurio EX02
→ formulario oficial EX-02
```

Cuando no exista un PDF o formulario descargable independiente, se considerará **Formulario/Superficie Oficial** el formulario electrónico de la propia sede.

Por tanto, la ausencia de PDF no exime de este componente.

La estructura administrativa oficial deberá igualmente estar modelada.

---

# IV. COMPONENTE 2 — FORMULARIO INTERNO DEL CRM

Todo procedimiento deberá disponer de una representación interna estructurada en el CRM para capturar, reutilizar, validar y preparar la información necesaria para su ejecución.

El formulario interno deberá:

- reutilizar información existente de cliente, expediente, empresa u otras entidades;
- evitar solicitar manualmente datos ya disponibles;
- distinguir datos canónicos de datos específicos del procedimiento;
- incluir validaciones;
- incluir obligatoriedad;
- incluir lógica condicional;
- representar bifurcaciones;
- preparar los datos necesarios para formularios oficiales y sedes electrónicas.

Ejemplo conceptual:

```text
CLIENTE
EXPEDIENTE
EMPRESA
OTROS DATOS CANÓNICOS
        ↓
FORMULARIO CRM DEL PROCEDIMIENTO
        ↓
PROCEDURE CONTRACT
```

El formulario interno no constituye una segunda fuente de verdad de los datos ya existentes en el CRM.

Actúa como composición y preparación del procedimiento.

---

# V. COMPONENTE 3 — AUTOMATIZACIÓN DE LA SEDE

Todo procedimiento deberá disponer de su correspondiente contrato de ejecución sobre la sede electrónica.

La automatización deberá contemplar, según proceda:

- entrada a la sede;
- navegación;
- autenticación;
- selección de procedimiento;
- selección de modelo;
- selección de supuesto;
- bifurcaciones;
- volcado de datos;
- carga documental;
- controles dinámicos;
- waits y readiness;
- validación del estado alcanzado;
- gestión de errores;
- recuperación segura;
- evidencias;
- puntos `HUMAN_ONLY`;
- acciones reversibles e irreversibles;
- resultado esperado.

La infraestructura ordinaria continuará siendo:

```text
CRM
→ Services / Application
→ QCC / Runtime
→ SeleniumBase / CDP
→ SEDE REAL
```

El frontend no controlará directamente SeleniumBase ni el navegador.

---

# VI. CONTRATO CANÓNICO DEL PROCEDIMIENTO

Los tres componentes deberán converger progresivamente sobre un único contrato canónico del procedimiento.

Modelo conceptual:

```text
ProcedureContract
│
├── procedure_code
├── procedure_version
├── official_source
├── fields
├── validations
├── conditional_rules
├── branches
├── official_form_mapping
├── crm_mapping
├── site_mapping
├── document_requirements
├── navigation_contract
├── readiness_contract
├── human_only_gates
├── expected_outcomes
└── evidence_contract
```

Este contrato evitará mantener tres definiciones independientes del mismo concepto.

Ejemplo:

```text
fecha_nacimiento
```

no deberá definirse de forma contradictoria en:

```text
Formulario CRM
Formulario oficial
Automatización web
```

El contrato canónico gobernará sus distintas proyecciones.

---

# VII. PRINCIPIO DE REUTILIZACIÓN

Antes de desarrollar cualquiera de los tres componentes deberá auditarse lo ya existente.

Secuencia obligatoria:

```text
AUDITAR
→ REUTILIZAR
→ CORREGIR
→ EXTENDER
→ TESTEAR
```

Queda desaconsejado reconstruir una automatización ya existente cuando pueda ser reconciliada con la arquitectura vigente.

Esto será especialmente aplicable a procedimientos de Mercurio ya automatizados históricamente, como EX01, EX02 y otras capacidades existentes.

---

# VIII. DEFINICIÓN DE PROCEDIMIENTO COMPLETO

Un procedimiento no podrá declararse `CLOSED` mientras no estén cerrados sus tres componentes obligatorios.

Estado mínimo:

```text
OFFICIAL_SURFACE
CRM_FORM
SITE_AUTOMATION
```

Ejemplo:

```text
procedure_code = EX01

OFFICIAL_SURFACE = CLOSED
CRM_FORM = CLOSED
SITE_AUTOMATION = CLOSED

PROCEDURE_STATUS = CLOSED
```

Si cualquiera de ellos permanece incompleto:

```text
PROCEDURE_STATUS = IN_PROGRESS
```

---

# IX. MATRIZ DE COBERTURA

El proyecto deberá mantener progresivamente una matriz de cobertura por procedimiento.

Ejemplo:

| Procedimiento | Oficial | CRM | Automatización | Twin | Estado |
|---|---|---|---|---|---|
| EX01 | CLOSED | CLOSED | CLOSED | PARTIAL | IN_VALIDATION |
| EX02 | CLOSED | CLOSED | CLOSED | PARTIAL | IN_VALIDATION |
| EX03 | CLOSED | PARTIAL | NONE | NONE | IN_PROGRESS |
| Red SARA · trámite X | CLOSED | CLOSED | CLOSED | CLOSED | CLOSED |

La denominación concreta podrá evolucionar, pero deberá preservarse la visibilidad separada de cada dimensión.

---

# X. RELACIÓN CON DISCOVERY Y SITE ARCHITECTURE

Discovery no sustituye al contrato del procedimiento.

Discovery es fuente de evidencia REAL para:

- identificar estados;
- identificar campos;
- identificar selectores;
- identificar transiciones;
- identificar bifurcaciones;
- detectar cambios;
- registrar comportamiento dinámico;
- actualizar Site Architecture;
- reconciliar automatizaciones existentes.

Modelo:

```text
SEDE REAL
   ↓
DISCOVERY
   ↓
SITE ARCHITECTURE
   ↓
PROCEDURE CONTRACT
```

La información obtenida mediante Discovery deberá utilizarse prioritariamente para **reconciliar y actualizar** automatizaciones existentes antes de generar nuevas implementaciones.

---

# XI. RELACIÓN CON AUTO TWIN

AUTO TWIN permanece como infraestructura horizontal independiente destinada a reproducir y validar localmente las sedes observadas.

El desarrollo funcional de nuevos procedimientos no quedará necesariamente bloqueado hasta disponer de un Twin perfecto.

Podrá existir:

```text
AUTOMATIZACIÓN REAL
        +
TWIN PARCIAL
```

durante la fase de desarrollo.

No obstante, AUTO TWIN deberá utilizarse progresivamente como entorno de:

- preproducción;
- replay;
- tests;
- regresión;
- validación de contratos;
- validación de automatizaciones;
- detección de divergencias REAL ↔ TWIN.

Una automatización podrá desarrollarse previamente, pero su nivel de **certificación definitiva** aumentará cuando exista cobertura Twin suficiente.

---

# XII. DOS CARRILES PERMANENTES DE DESARROLLO

Se formalizan dos carriles paralelos.

## CARRIL A — QCC / AUTO TWIN

Objetivo:

**mejorar continuamente la fábrica de automatización.**

Incluye:

- Discovery;
- Site Architecture;
- fidelidad REAL ↔ TWIN;
- materialización;
- navegación;
- causal learning;
- readiness;
- comportamiento dinámico;
- replay;
- versionado;
- regresión;
- gestión de Twins.

## CARRIL B — CAPACIDAD OPERATIVA DEL CRM

Objetivo:

**aumentar continuamente el número de procedimientos que el CRM puede ejecutar realmente.**

Para cada procedimiento:

```text
CONTRATO
→ OFICIAL
→ CRM
→ AUTOMATIZACIÓN
→ TESTS
→ EVIDENCIA
→ CIERRE
```

Ambos carriles deberán avanzar paralelamente siempre que sus modificaciones puedan aislarse mediante worktrees y Work Orders independientes.

---

# XIII. AUTOMATIZACIONES CON BIFURCACIONES

Cuando una sede agrupe múltiples variantes dentro de un mismo procedimiento, cada variante deberá quedar identificada dentro del contrato.

Ejemplo:

```text
EX01
│
├── EX01_RENOVACION_TITULAR
│      ├── gsup_28
│      └── datosForAut=130
│
└── EX01_RENOVACION_FAMILIAR
       └── datosForAut=131
```

La existencia de una automatización genérica EX01 no implica automáticamente cobertura de todas sus ramas.

La cobertura deberá declararse explícitamente.

---

# XIV. HUMAN_ONLY Y EFECTOS ADMINISTRATIVOS

Toda automatización deberá identificar expresamente las acciones que:

- producen efectos jurídicos;
- presentan definitivamente solicitudes;
- firman;
- pagan tasas;
- registran documentación;
- producen actuaciones administrativas irreversibles.

Cuando corresponda, dichas acciones quedarán gobernadas por políticas `HUMAN_ONLY`, autorización explícita u otros mecanismos aprobados.

El desarrollo, Discovery o Twin no deberán provocar efectos administrativos reales no autorizados.

---

# XV. TESTS Y EVIDENCIA

Una automatización no se considerará terminada únicamente porque pueda ejecutarse.

Deberá disponer, según proceda, de evidencia mediante:

- tests unitarios;
- tests de contrato;
- tests de mapping;
- replay;
- smoke tests;
- validación de navegación;
- validación de formulario;
- validación documental;
- evidencias estructuradas;
- regresiones de bugs relevantes.

Principio:

```text
CÓDIGO
≠
AUTOMATIZACIÓN TERMINADA

CÓDIGO
+ TESTS
+ EVIDENCIA
+ CONTRATOS
+ VALIDACIÓN
=
AUTOMATIZACIÓN CERRADA
```

---

# XVI. FUENTE ÚNICA DE VERDAD

Cada procedimiento deberá evolucionar hacia una única definición canónica.

Se prohíbe crear deliberadamente:

- un modelo de campos para el PDF;
- otro modelo incompatible para el CRM;
- otro modelo independiente para SeleniumBase;

cuando puedan ser proyecciones de un contrato común.

La arquitectura deberá tender a:

```text
                    ┌→ FORMULARIO OFICIAL
PROCEDURE CONTRACT ─┼→ FORMULARIO CRM
                    └→ AUTOMATIZACIÓN SEDE
```

---

# XVII. CRITERIO DE PRODUCTIVIDAD

La presente resolución no pretende aumentar burocracia ni duplicar trabajo.

Su objetivo es que cada procedimiento nuevo genere simultáneamente:

- capacidad documental;
- capacidad estructurada de datos;
- capacidad de automatización;
- conocimiento reutilizable;
- tests;
- contratos;
- infraestructura reutilizable para procedimientos posteriores.

Cada nuevo procedimiento deberá hacer más barato y rápido incorporar el siguiente.

---

# XVIII. REGLA DE CIERRE

A partir de la aprobación de esta resolución:

> **NINGUNA AUTOMATIZACIÓN ADMINISTRATIVA SE CONSIDERARÁ COMPLETAMENTE INCORPORADA AL CRM SI NO EXISTEN Y ESTÁN COORDINADOS SU MODELO OFICIAL, SU FORMULARIO/DATOS INTERNOS CRM Y SU AUTOMATIZACIÓN DE SEDE.**

AUTO TWIN y QCC actuarán transversalmente sobre dichas capacidades para aportar observación, aprendizaje, preproducción, validación y robustez.

---

## RESOLUCIÓN FINAL

Se aprueba como modelo obligatorio del ecosistema Quesada Abogados:

```text
PROCEDIMIENTO
      ↓
CONTRATO CANÓNICO
      ↓
────────────────────────────────
1 · MODELO / FORMULARIO OFICIAL
2 · FORMULARIO / DATOS CRM
3 · AUTOMATIZACIÓN DE SEDE
────────────────────────────────
      ↓
QCC + DISCOVERY + SITE ARCHITECTURE
      ↓
AUTO TWIN / TESTS / REGRESIÓN
      ↓
AUTOMATIZACIÓN CERTIFICADA
```

Este modelo será aplicable a **Mercurio, Red SARA, DEHú, Nacionalidad y cualquier nueva sede o procedimiento administrativo incorporado al CRM**.

**ESTADO DE LA RESOLUCIÓN: APROBADA POR DIRECCIÓN.**
