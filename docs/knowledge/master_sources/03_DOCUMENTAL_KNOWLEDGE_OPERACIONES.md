# `03_DOCUMENTAL_KNOWLEDGE_OPERACIONES.md` — FUENTE MAESTRA DE SISTEMA DOCUMENTAL, KNOWLEDGE Y OPERACIONES DE NEGOCIO

**Proyecto:** Quesada Abogados CRM
**Naturaleza del Documento:** Fuente Maestra Consolidada 03 de 06
**Estado:** APROBADO POR DIRECCIÓN
**Trazabilidad:** Construido a partir del Registro Canónico Aprobado (`00_MASTER_INDEX.md`).
**FUENTES NORMATIVAS BASE:** `002_funcionamiento_negocio.md`, `003_ecosistema_tecnologico.md`, `011_sistema_documental_box_vigilancia.md`, `014_resolucion_box_extranjeria_v1.md`, `015_flujo_circular_cliente.md`, `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md`.
**FUENTES INFORMATIVAS NO NORMATIVAS:** `20260809_resolucion_estado_actual_proyecto_y_hoja_ruta_supabase.md` (secciones de estado de tareas, vigilancia documental y knowledge).

---

## SECCIÓN I: MARCO GENERAL Y ALCANCE

La presente Fuente Maestra consolida de forma unificada las decisiones normativas aprobadas sobre el Sistema Documental en Box Drive, las reglas de clasificación documental en extranjería, el flujo circular operativo del cliente, la integración con la base de conocimiento (Knowledge), la supervisión jurídica humana sobre herramientas de IA, las operaciones de negocio del despacho y la unificación de tareas mediante la entidad canónica `TASK` y el Centro de Actividades Administrativas (CAA).

La Fuente Maestra no crea autoridad normativa por sí misma. Consolida las decisiones normativas aprobadas contenidas en las fuentes originales del proyecto Quesada Abogados CRM, garantizando la observancia estricta del invariante de observancia sobre Box Drive, la validez probatoria de los documentos administrativos, el rigor jurídico en el uso de IA y la centralización de la gestión operativa del despacho.

---

## SECCIÓN II: DECISIONES NORMATIVAS APROBADAS (DOC, KNOW, OPS)

### 1. SISTEMA DOCUMENTAL Y BOX DRIVE (`DOC`)

#### `DOC-001` · Invariante Estructural: "El ERP SOLO observa Box, NUNCA manipula Box"
* **Estado:** VIGENTE
* **Decisión vigente:** La relación ordinaria del ERP con Box Drive se rige por la norma absoluta establecida en `011_sistema_documental_box_vigilancia.md`:

  `El ERP NO manipula Box`
  `El ERP SOLO observa Box`

  El acceso permitido es de lectura para detección de cambios, listado de archivos y verificación de existencia. Queda prohibido que el ERP mueva, modifique, elimine, renombre, reorganice o escriba dentro de Box, así como la sincronización activa desde el ERP.
* **Origen / Fuente primaria:** `011_sistema_documental_box_vigilancia.md` (Sec. 3, 4, 5 y 11).
* **Justificación documentada:** Proteger la integridad y seguridad del repositorio documental del despacho y evitar daños o pérdidas causados por automatizaciones.
* **Invariantes:**
  - La seguridad de Box prevalece sobre cualquier automatización del ERP.
  - El ERP no debe disponer ordinariamente de permisos de escritura sobre Box.
  - La vigilancia documental es una operación de lectura/observación.
* **Evolución y modificaciones:** `014_resolucion_box_extranjeria_v1.md` desarrolla reglas de interpretación documental sobre la estructura observada. `016_sistema_trabajo.md` introduce posteriormente reglas de copia explícita y trazada hacia expediente; esta formulación presenta una tensión documental con la prohibición absoluta de escritura de `011` y se registra como divergencia sin resolver en la Sección III.
* **Relaciones relevantes:** Conecta con `ARCH-004` (Arquitectura híbrida local) y `DOC-002` (Clasificación documental en extranjería).

#### `DOC-002` · Clasificación Documental de Extranjería e Invalidez de Resguardos
* **Estado:** VIGENTE
* **Decisión vigente:** Se aprueban reglas oficiales de clasificación documental y detección de estados para expedientes de Extranjería observados en Box:
  - Los archivos tipo `Resguardo_XXXX.pdf` NO constituyen justificante válido de presentación, tasa, requerimiento ni subsanación.
  - Un expediente se considera **PRESENTADO** únicamente cuando exista justificante oficial válido en la raíz del expediente o en carpetas compatibles como `PARA PRESENTAR`, `PRESENTAR` o `PRESENTACION`.
  - No computan como presentación justificantes ubicados en contextos de tasa, requerimiento, aportación, subsanación, concesión, denegación o archivo.
  - La **TASA** exige evidencia compatible con tasa y justificante oficial; una carpeta `TASA` por sí sola no acredita el abono.
  - Existe **REQUERIMIENTO** cuando haya justificante válido en carpetas compatibles como `REQ DOC`, `REQUERIMIENTO` o `REQ`; `REQ DOC Y TASA` puede computar simultáneamente como requerimiento y tasa.
  - Existe **SUBSANACIÓN/APORTACIÓN** cuando haya justificante válido en contextos `SUBSANAR`, `SUBIR` o `APORTAR`.
  - Las resoluciones se clasifican por contexto compatible de concesión, denegación o archivo/desistimiento.
  - En caso de conflicto, `DOCUMENTO + CONTEXTO DE RUTA` prevalece sobre el nombre aislado del archivo.
* **Origen / Fuente primaria:** `014_resolucion_box_extranjeria_v1.md` (Sec. II a VIII).
* **Justificación documentada:** Evitar falsos positivos en reporting, estados procesales, tasas, requerimientos y resoluciones.
* **Invariantes:**
  - Un resguardo no equivale a justificante oficial.
  - La existencia de una carpeta no basta cuando la regla exige justificante oficial.
  - El contexto de ruta forma parte de la interpretación documental.
* **Evolución y modificaciones:** Desarrolla operativamente `DOC-001` sin modificar su regla de gobierno sobre lectura/escritura.
* **Relaciones relevantes:** Conecta con `DATA-002` (Estados de expedientes) y `DOC-001` (Vigilancia de Box).

---

### 2. KNOWLEDGE Y APRENDIZAJE OPERATIVO (`KNOW`)

#### `KNOW-001` · Flujo Circular Operativo del Cliente y Generación de Conocimiento
* **Estado:** VIGENTE
* **Decisión vigente:** Se adopta un flujo circular de aprendizaje operativo continuo en el que captación, expediente, documentación, automatización, resolución, inteligencia jurídica, generación de contenido y nueva captación forman un único ecosistema.

  Cuando exista resolución, el expediente y la resolución se anonimizan, se consolidan notas operativas y se extraen hechos relevantes. El expediente anonimizado **podrá** enviarse a NotebookLM junto con resolución, normativa y observaciones internas para generar criterios asistidos. Los criterios posteriormente validados **podrán** incorporarse a la base interna de conocimiento jurídico.
* **Origen / Fuente primaria:** `015_flujo_circular_cliente.md` (Sec. I, IX, X, XII, XIII y XIV).
* **Justificación documentada:** Convertir la experiencia operativa del despacho en conocimiento reutilizable sin convertir la IA en fuente jurídica autónoma.
* **Invariantes:**
  - La anonimización precede al uso del expediente o resolución en el flujo de conocimiento asistido.
  - NotebookLM es una capa de análisis; no sustituye las fuentes operativas del ERP.
  - La incorporación a NotebookLM o a la base de conocimiento se expresa como posibilidad gobernada, no como obligación automática para todo expediente.
* **Evolución y modificaciones:** Compatible con la regla posterior de gobierno que define Knowledge como consumidor de la información estructurada del ERP.
* **Relaciones relevantes:** Conecta con `KNOW-002`, `DATA-009` y `OPS-001`.

#### `KNOW-002` · Supervisión Jurídica Humana Obligatoria sobre Criterios de IA
* **Estado:** VIGENTE
* **Decisión vigente:** Todo criterio generado mediante IA deberá revisarse, validarse y consolidarse manualmente. Queda prohibido utilizar criterios de IA sin supervisión jurídica humana.
* **Origen / Fuente primaria:** `015_flujo_circular_cliente.md` (Sec. XI).
* **Justificación documentada:** Mantener el control jurídico humano sobre los criterios utilizados en la tramitación y evitar que una salida automática de IA se convierta por sí misma en decisión jurídica.
* **Invariantes:**
  - La IA asiste; la supervisión jurídica humana valida.
  - Un criterio de IA no adquiere autoridad por el mero hecho de haber sido generado.
* **Evolución y modificaciones:** La resolución posterior de gobierno de agosto de 2026 define Knowledge y NotebookLM como capas consumidoras/de análisis, coherente con esta separación de autoridad.
* **Relaciones relevantes:** Conecta con `KNOW-001` y `DATA-009`.

---

### 3. OPERACIONES Y NEGOCIO DEL DESPACHO (`OPS`)

#### `OPS-001` · Flujo Operativo del Cliente y Hojas de Encargo
* **Estado:** VIGENTE
* **Decisión vigente:** El flujo ordinario del despacho comprende asesoramiento inicial, indicación y recepción de documentación, firma de Hoja de Encargo, generación de honorarios, apertura de expediente, escaneado, preparación, presentación/actuación jurídica y seguimiento hasta resolución o cierre.

  El inicio del expediente implica identificación del cliente, apertura, recepción documental, firma de Hoja de Encargo, generación de honorarios, asignación de responsable y preparación para escaneado/presentación. Los documentos sensibles —pasaporte, NIE, DNI, documentos identificativos, resoluciones y documentación esencial— se escanean de forma prioritaria. Se abre una carpeta física del expediente y se mantiene una cola de escaneado y posterior preparación/presentación.
* **Origen / Fuente primaria:** `002_funcionamiento_negocio.md` (Sec. 3, 5, 6, 7, 8, 9 y 10).
* **Justificación documentada:** Hacer que el ERP represente el funcionamiento real del despacho y sus hitos operativos.
* **Invariantes:**
  - La firma de la Hoja de Encargo es un hito esencial del expediente.
  - El ERP debe poder registrar documentación aunque inicialmente no esté digitalizada.
  - El flujo operativo debe permitir seguimiento desde la entrada del cliente hasta resolución o cierre.
* **Evolución y modificaciones:** Sirve de base funcional a los modelos posteriores de Clientes, Expedientes y Económico; las antiguas colas operativas evolucionan después hacia TASK/CAA.
* **Relaciones relevantes:** Conecta con `DATA-001`, `DATA-002`, `DATA-003` y `OPS-003`.

#### `OPS-002` · Integración de Herramientas Externas mediante CSV
* **Estado:** VIGENTE
* **Decisión vigente:** Se adopta una estrategia inicial de integración simple y controlada:
  - **HubSpot:** continúa como herramienta comercial; los clientes pueden entrar al ERP mediante exportación/importación CSV o inserción manual. No se adopta API directa en las fases iniciales.
  - **Holded:** continúa como sistema contable oficial; el ERP genera datos de facturación exportados en CSV para importación manual en Holded.
  - La evolución futura podrá incorporar APIs o sincronización más avanzada, pero no forma parte de la decisión inicial.
* **Origen / Fuente primaria:** `003_ecosistema_tecnologico.md` (Sec. 3, 4, 5, 6 y 11).
* **Justificación documentada:** Priorizar simplicidad operativa, reducir complejidad técnica inicial y mantener separadas la gestión jurídica/operativa y la contabilidad.
* **Invariantes:**
  - El ERP es la herramienta operativa; HubSpot mantiene la función comercial en esta resolución.
  - Holded mantiene la función de sistema contable oficial en esta resolución.
  - El intercambio inicial aprobado para HubSpot/Holded se basa en CSV.
* **Evolución y modificaciones:** La propia resolución deja abierta una evolución posterior hacia APIs y sincronización en tiempo real.
* **Relaciones relevantes:** Conecta con `DATA-006` y `DATA-005`.

#### `OPS-003` · TASK como Unidad Canónica de Trabajo y CAA como Centro Operativo
* **Estado:** VIGENTE
* **Decisión vigente:** Se establece:

  `TASK = unidad canónica de trabajo`

  `CAA = interfaz / centro operativo de las TASK administrativas`

  No deben existir unidades de trabajo independientes competidoras para una misma actividad. Calendar y CAA deben operar sobre la misma `TASK`. Los motores especializados —Mercurio, citas, trámites consulares y otros ejecutores— realizan la actividad, pero no constituyen fuentes alternativas de estado.

  La Cola de Presentación debe ser absorbida progresivamente por CAA. La primera actividad administrativa de CAA es `PRESENTAR_EXPEDIENTE`, pudiendo incorporarse después otras actuaciones administrativas.
* **Origen / Fuente primaria:** `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md`; desarrollada funcionalmente por `20260809_resolucion_estado_actual_proyecto_y_hoja_ruta_supabase.md`.
* **Justificación documentada:** Unificar la gestión del trabajo y evitar modelos paralelos de actividad.
* **Invariantes:**
  - `TASK` es la fuente canónica de trabajo.
  - CAA es interfaz/centro operativo, no una segunda unidad de trabajo.
  - Calendar es una proyección y no una fuente canónica de actividad.
* **Evolución y modificaciones:** CAA V1 forma parte de los gates previos a PostgreSQL y evoluciona la antigua Cola de Presentación.
* **Relaciones relevantes:** Conecta con `DATA-009`, `DATA-010` y `DATA-002`.

---

## SECCIÓN III: INFORMACIÓN TÉCNICA NO NORMATIVA

*(Los contenidos integrados en esta sección poseen carácter estrictamente informativo, diagnóstico o de estado de implementación. No constituyen normas de obligado cumplimiento ni alteran el cuerpo de decisiones aprobadas).*

### 1. ESTADO TÉCNICO DE LA GESTIÓN OPERATIVA Y TAREAS (NO NORMATIVO)
*(Fuente: `20260809_resolucion_estado_actual_proyecto_y_hoja_ruta_supabase.md`, Sec. III, IV y V)*

- **Madurez técnica de los módulos operativos:**
  - Módulo de Clientes y Redes: ~82% funcional.
  - Sistema Documental (Vigilancia de Box, Bandeja de Entrada, OCR): ~87% de desarrollo completado.
  - Calendar: 100% cerrado como proyección visual.
  - TASK y Centro de Actividades Administrativas (CAA): ~90% de madurez técnica, con la estructura de cronometraje `task_work_sessions` en fase de integración.
- **Vigilancia documental y procesamiento de resoluciones:**
  - Despliegue del motor de escaneo pasivo de Box Drive en segundo plano.
  - Integración del lector de justificantes de presentación y detección de requerimientos para actualización automática de la cola en el CAA.

---

### 2. DIVERGENCIA DOCUMENTAL–OPERATIVA (NO NORMATIVO)

Se identifica una divergencia documental que esta Fuente Maestra **no resuelve por sí sola**:

- `011_sistema_documental_box_vigilancia.md` establece como norma absoluta que el ERP solo observa Box y no escribe, mueve, renombra, reorganiza ni sincroniza activamente.
- `016_sistema_trabajo.md` establece posteriormente que la Bandeja Documental “observa, copia, clasifica y registra” y que la “copia a expediente debe ser explícita”, con ruta destino registrada.

Hasta que exista una resolución específica que delimite la relación entre ambas reglas, `DOC-001` conserva su estado **VIGENTE** conforme al Registro Canónico aprobado y la tensión queda registrada para decisión futura de Dirección.

---

> ESTADO: 03_DOCUMENTAL_KNOWLEDGE_OPERACIONES — APROBADO POR DIRECCIÓN
