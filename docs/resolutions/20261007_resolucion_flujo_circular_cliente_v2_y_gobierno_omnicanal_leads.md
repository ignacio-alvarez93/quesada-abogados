# RESOLUCIÓN SOBRE FLUJO CIRCULAR DEL CLIENTE V2 Y GOBIERNO OMNICANAL DE LEADS

**Proyecto:** Quesada Abogados CRM
**Fecha:** 7 de octubre de 2026
**Naturaleza:** Resolución Operativa y Arquitectónica
**Estado:** APROBADA POR DIRECCIÓN
**Ámbito:** CRM, Leads, Clientes, Expedientes, Communications, QCC, Knowledge, Marketing y operaciones del despacho

## Decisiones creadas

- `OPS-005` · Lead Omnicanal como Unidad Canónica del Ciclo Comercial.
- `OPS-006` · Lifecycle Comercial y Conversión Lead → Cliente → Expediente.
- `KNOW-004` · Flujo Circular del Cliente V2 y Aprendizaje Multibucle.

## Decisiones afectadas

- `KNOW-001` · MODIFICADA / AMPLIADA.
- `OPS-002` · MODIFICADA PARCIALMENTE.
- `OPS-001` · COMPLEMENTADA.

---

# I. OBJETO

La presente resolución actualiza y amplía el modelo establecido en `015_flujo_circular_cliente.md`.

Permanecen vigentes sus principios esenciales de aprendizaje operativo continuo, generación de conocimiento a partir de la experiencia real, retroalimentación hacia futuros expedientes, generación de contenido y nuevos leads, supervisión humana, trazabilidad y anonimización/minimización cuando proceda.

La evolución funcional, tecnológica y comercial del ecosistema Quesada Abogados exige sustituir la representación de un único círculo lineal por un **modelo multibucle del ciclo de vida de la relación entre persona y despacho**.

---

# II. PRINCIPIO GENERAL DEL FLUJO CIRCULAR V2

La unidad estratégica del sistema no es exclusivamente un expediente individual.

El sistema debe representar la **relación longitudinal entre una persona y Quesada Abogados** a través de sucesivos ciclos comerciales, jurídicos, operativos y de conocimiento.

Una misma persona podrá contactar por múltiples canales, generar uno o varios Leads, contratar uno o varios servicios, mantener varios expedientes, generar nuevas necesidades jurídicas, volver a entrar en un ciclo comercial aun siendo ya cliente y producir experiencia reutilizable bajo las reglas de privacidad y validación aplicables.

---

# III. OPS-005 · LEAD OMNICANAL COMO UNIDAD CANÓNICA DEL CICLO COMERCIAL

## 1. Definición

`Lead` es la **unidad canónica del ciclo comercial asociado a una necesidad concreta y potencial de contratación de servicios de Quesada Abogados**.

El Lead no representa a la persona y no sustituye a Cliente, Contacto, Expediente, Communication ni TASK.

## 2. Naturaleza omnicanal

Un Lead podrá originarse, entre otros, mediante:

- WhatsApp;
- email;
- Instagram;
- Facebook;
- TikTok y otras redes sociales;
- HubSpot;
- formularios o página web;
- llamada telefónica;
- Telegram;
- cita presencial;
- recomendación;
- partner;
- campaña;
- captación manual;
- futuros canales autorizados.

El canal no determina la autoridad sobre el Lead.

## 3. Autoridad canónica

**El CRM Quesada Abogados constituye la autoridad canónica del Lead.**

WhatsApp, email, redes sociales, HubSpot, web, partners y otros sistemas son canales, fuentes, herramientas o integraciones; no constituyen fuentes de verdad competidoras del Lead.

Se reafirma `DATA-009`: una sola fuente canónica por concepto.

---

# IV. MODIFICACIÓN PARCIAL DE OPS-002 · HUBSPOT

HubSpot podrá continuar como canal de captación, herramienta comercial externa, origen de Leads, sistema auxiliar de marketing, fuente de datos o integración.

Cuando exista el dominio Lead nativo del CRM, **HubSpot no será la autoridad canónica del Lead**.

La integración podrá evolucionar desde CSV hacia API, webhook, sincronización u otros mecanismos autorizados sin que esta resolución obligue a implantar una tecnología concreta.

La función de Holded definida en `OPS-002` no queda modificada.

---

# V. PERSONA, LEAD Y CLIENTE

Se establece la separación conceptual:

`PERSONA ≠ LEAD ≠ CLIENTE`

- **Persona:** identidad con la que el despacho interactúa.
- **Lead:** necesidad comercial concreta susceptible de contratación.
- **Cliente:** relación adquirida cuando se contrata un servicio o trámite conforme a la operativa del despacho.

Una persona podrá mantener múltiples Leads simultáneos o sucesivos.

La condición de Cliente no impide generar nuevos Leads.

---

# VI. DEDUPLICACIÓN OMNICANAL

La existencia de varios canales no genera automáticamente varios Leads.

Regla general:

`MISMA PERSONA + MISMA NECESIDAD COMERCIAL + LEAD ACTIVO = MISMO LEAD`

Las comunicaciones procedentes de distintos canales se relacionarán con el Lead sin fragmentar el ciclo comercial.

Una nueva necesidad comercial diferenciada podrá generar un nuevo Lead, incluso cuando la persona ya sea Cliente.

Los Leads históricos no se sobrescriben para representar ciclos comerciales posteriores.

---

# VII. CANAL Y FUENTE

El modelo debe distinguir:

- **Canal:** medio de interacción, por ejemplo WhatsApp, email, Instagram o teléfono.
- **Fuente:** origen comercial o contextual, por ejemplo campaña, recomendación, partner, contenido orgánico o formulario.

La presente resolución no fija todavía un modelo definitivo de First Touch, Last Touch, scoring, CAC o ROI.

---

# VIII. OPS-006 · LIFECYCLE COMERCIAL DEL LEAD

Se aprueban inicialmente los estados mínimos:

- `OPEN`
- `QUALIFIED`
- `CONVERTED`
- `LOST`

## OPEN

Existe una manifestación identificable de interés comercial o una cita relacionada con un potencial servicio.

## QUALIFIED

El Lead ha abonado una consulta profesional.

`QUALIFIED` es un hito comercial útil, pero **no constituye una fase obligatoria para la conversión**.

## CONVERTED

El Lead ha contratado el servicio o trámite objeto del ciclo comercial.

La conversión podrá producir creación o vinculación de Cliente, Hoja de Encargo, honorarios y Expediente cuando corresponda.

## LOST

El ciclo comercial se cierra sin contratación. El Lead se conserva históricamente.

## Transiciones mínimas aprobadas

- `OPEN → QUALIFIED`
- `OPEN → CONVERTED`
- `OPEN → LOST`
- `QUALIFIED → CONVERTED`
- `QUALIFIED → LOST`

Se reconoce expresamente como flujo ordinario válido:

`OPEN → CONVERTED`

sin paso previo por `QUALIFIED`.

---

# IX. HITOS HISTÓRICOS

Además del estado actual, el sistema deberá poder conservar hitos relevantes, entre ellos cuando proceda:

- `created_at`
- `qualified_at`
- `converted_at`
- `lost_at`

Un Lead convertido directamente podrá tener `qualified_at = NULL`.

La historia no deberá reconstruirse únicamente a partir del estado actual cuando exista evidencia estructurada disponible.

---

# X. CONVERSIÓN LEAD → CLIENTE → EXPEDIENTE

La conversión no transforma destructivamente una entidad en otra.

El modelo conceptual es:

`LEAD CONVERTED → PERSONA → CLIENTE existente o nuevo → EXPEDIENTE cuando corresponda`

El Lead convertido permanece como historial comercial.

Una persona que ya sea Cliente puede generar un nuevo Lead y, si lo contrata, un nuevo Expediente sin crear una identidad de Cliente duplicada.

---

# XI. QCC, WHATSAPP Y OTRAS SUPERFICIES

QCC podrá actuar como superficie contextual de captación y operación sobre Leads de acuerdo con las capacidades autorizadas por las resoluciones QCC vigentes.

Podrá, mediante servicios backend autorizados, mostrar o iniciar acciones relacionadas con Lead, Cliente, Expediente y TASK.

El contrato permanece:

`QCC → Bridge → Application Service → Domain/Persistence`

QCC no constituye fuente de verdad del Lead y no accede directamente a la persistencia.

---

# XII. COMMUNICATIONS

WhatsApp, email, llamadas y futuros canales conservan su autoridad como comunicaciones.

El Lead se relaciona con Communications; no debe duplicar innecesariamente el contenido completo de dichas comunicaciones.

---

# XIII. TASK / CAA

Lead no sustituye al sistema de trabajo.

Cuando una necesidad comercial requiera actuación:

`LEAD → evento/necesidad → TASK → CAA`

`TASK` conserva su autoridad como unidad canónica de trabajo y CAA como centro operativo.

---

# XIV. KNOW-004 · FLUJO CIRCULAR DEL CLIENTE V2 Y APRENDIZAJE MULTIBUCLE

Se evoluciona el Flujo Circular V1 hacia un sistema de bucles conectados.

## A. Bucle de adquisición

`Knowledge / experiencia + IT / señales → contenido / campaña / difusión → canales → Leads`

Esta relación es conceptual y no obliga a acoplar técnicamente Knowledge, IT y Marketing. Cada motor conserva autonomía y contratos propios.

## B. Bucle comercial

`Canales → Lead OPEN → QUALIFIED opcional → CONVERTED → Cliente → Expediente`

La transición directa `OPEN → CONVERTED` es válida.

## C. Bucle jurídico-operativo

`Cliente → Expediente → Documentación → Readiness/validaciones → TASK/CAA → Automatización/QCC/operación humana → Presentación → Seguimiento → Resolución/Cierre`

Las autoridades canónicas existentes permanecen vigentes.

## D. Bucle de conocimiento

`Expediente + documentación + actuaciones + incidencias + resultado + resolución → anonimización/minimización → extracción de experiencia → validación humana → Knowledge`

Knowledge podrá reutilizar esa experiencia para futuros expedientes, precedentes, checklists, criterios internos, operaciones, contenido y estrategia cuando exista contrato autorizado.

---

# XV. BUCLE LONGITUDINAL DEL CLIENTE

La resolución de un expediente no implica necesariamente el final de la relación con el cliente.

El sistema debe contemplar:

`CLIENTE → situación actual → EXPEDIENTE A → resolución → nueva situación → nueva necesidad → nuevo LEAD → EXPEDIENTE B → ...`

Pueden existir sucesivamente, entre otros, autorización inicial, renovación, modificación, reagrupación, larga duración, nacionalidad u otros procedimientos.

Cada ciclo conserva trazabilidad histórica.

---

# XVI. DEFINICIÓN OFICIAL DEL FLUJO CIRCULAR V2

El modelo operativo del despacho queda definido como un:

**ecosistema jurídico, comercial, documental y de conocimiento multibucle, trazable y autoalimentado.**

En él:

- la captación genera Leads;
- los Leads generan ciclos comerciales;
- las contrataciones generan o vinculan Clientes y Expedientes;
- los Expedientes generan trabajo, actuaciones y experiencia;
- la experiencia genera Knowledge;
- Knowledge mejora futuras operaciones;
- Knowledge y otras señales pueden alimentar contenido y estrategia;
- contenido y campañas pueden generar nuevos Leads;
- Clientes existentes pueden generar nuevas necesidades y nuevos Leads;
- el ciclo continúa preservando la historia longitudinal.

---

# XVII. FUENTES DE VERDAD

Se reafirma:

- Lead → dominio Lead / CRM.
- Cliente → Clientes.
- Expediente → Expedientes / Trazabilidad.
- Communication → Communications.
- TASK → TASK.
- CAA → proyección/centro operativo basado en TASK.
- Calendar → proyección temporal.
- Documental → motor documental autorizado.
- Knowledge → Knowledge.
- QCC → superficie contextual.
- HubSpot / WhatsApp / redes sociales / email → canales, fuentes o integraciones.

No se crearán fuentes paralelas de verdad sin contrato explícito.

---

# XVIII. PRIVACIDAD Y CONTROL HUMANO

El tratamiento del ciclo comercial y jurídico aplicará minimización, finalidad, trazabilidad, control de acceso y privacidad por diseño.

La experiencia de expedientes reales destinada a Knowledge aplicará anonimización/minimización conforme a las decisiones vigentes.

Se mantiene íntegramente `KNOW-002`: la IA asiste, la fuente soporta y el profesional valida los criterios jurídicos.

---

# XIX. MATERIAS NO RESUELTAS POR ESTA RESOLUCIÓN

No se aprueban todavía:

- entidad independiente `Opportunity`;
- scoring comercial avanzado;
- First Touch / Last Touch definitivo;
- atribución económica completa;
- CAC o ROI de campañas;
- automatización autónoma de campañas;
- comisiones de Partners;
- integración normativa de Philosophy;
- proveedor tecnológico único para Marketing;
- modelo definitivo de IA comercial.

Estas materias requerirán resolución posterior si procede.

---

# XX. RELACIÓN CON DECISIONES PREVIAS

## KNOW-001

Permanece vigente en sus principios esenciales y queda modificada/ampliada por:

- `KNOW-003`, respecto de Knowledge nativo y sustitución de NotebookLM como dependencia operativa;
- `KNOW-004`, respecto del Flujo Circular V2 multibucle y longitudinal.

## OPS-002

Pasa a **MODIFICADA PARCIALMENTE**.

HubSpot puede seguir como herramienta externa, pero el Lead nativo del CRM es la autoridad canónica cuando exista la funcionalidad.

Holded no queda afectado.

## OPS-001

Permanece VIGENTE y queda COMPLEMENTADA por el lifecycle comercial previo y por la relación Lead → Cliente → Expediente.

## DATA-009

Se reafirma íntegramente.

## QCC-004

Se mantiene vigente. Esta resolución define el dominio que QCC puede contextualizar; no amplía por sí misma las capacidades técnicas autorizadas de QCC.

---

# XXI. PRINCIPIO DE IMPLEMENTACIÓN

La aprobación funcional no implica implementación automática.

La ejecución deberá seguir la arquitectura y gobierno vigentes:

`Diagnóstico → Contratos → Modelo → Services/Application → Persistencia → UI/QCC/Conectores → Tests → Regresión → Evidencia → Cierre`

No se introducirá SQL directo en Flet o QCC, no se desarrollará directamente en `main` y se utilizará Fabric/Runner cuando corresponda.

---

# XXII. PRINCIPIO FINAL

Quesada Abogados debe aprender de cada relación, cada expediente y cada resultado; convertir ese aprendizaje en mejor servicio y mejor captación; y conservar una memoria operativa longitudinal, estructurada, trazable y reutilizable.
