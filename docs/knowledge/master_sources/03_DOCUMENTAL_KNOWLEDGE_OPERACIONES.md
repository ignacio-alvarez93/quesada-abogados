# `03_DOCUMENTAL_KNOWLEDGE_OPERACIONES.md` — FUENTE MAESTRA DE SISTEMA DOCUMENTAL, KNOWLEDGE Y OPERACIONES DE NEGOCIO

**Proyecto:** Quesada Abogados CRM
**Naturaleza del Documento:** Fuente Maestra Consolidada 03 de 06
**Estado:** APROBADO POR DIRECCIÓN
**Trazabilidad:** Construido a partir del Registro Canónico Aprobado (`00_MASTER_INDEX.md`).
**FUENTES NORMATIVAS BASE:** `002_funcionamiento_negocio.md`, `003_ecosistema_tecnologico.md`, `011_sistema_documental_box_vigilancia.md`, `014_resolucion_box_extranjeria_v1.md`, `015_flujo_circular_cliente.md`, `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md`, `20261005_resolucion_knowledge_nativo_y_gobierno_de_conocimiento.md`, `20261005_resolucion_box_copia_bidireccional_controlada.md`.
**FUENTES INFORMATIVAS NO NORMATIVAS:** `20260809_resolucion_estado_actual_proyecto_y_hoja_ruta_supabase.md` (secciones de estado de tareas, vigilancia documental y knowledge).

---

## SECCIÓN I: MARCO GENERAL Y ALCANCE

La presente Fuente Maestra consolida de forma unificada las decisiones normativas aprobadas sobre el Sistema Documental en Box Drive, las reglas de clasificación documental en extranjería, el flujo circular operativo del cliente, la integración con la base de conocimiento (Knowledge), la supervisión jurídica humana sobre herramientas de IA, las operaciones de negocio del despacho y la unificación de tareas mediante la entidad canónica `TASK` y el Centro de Actividades Administrativas (CAA).

La Fuente Maestra no crea autoridad normativa por sí misma. Consolida las decisiones normativas aprobadas contenidas en las fuentes originales del proyecto Quesada Abogados CRM, garantizando la integridad de Box Drive, el gobierno de copias documentales controladas, la vigilancia y reconciliación de cambios, la validez probatoria de los documentos administrativos, el rigor jurídico en el uso de IA y la centralización de la gestión operativa del despacho.

---

## SECCIÓN II: DECISIONES NORMATIVAS APROBADAS (DOC, KNOW, OPS)

### 1. SISTEMA DOCUMENTAL Y BOX DRIVE (`DOC`)

#### `DOC-001` · Invariante Histórico de No Manipulación Libre de Box
* **Estado:** MODIFICADA PARCIALMENTE
* **Decisión vigente:** Se conserva la finalidad de `011_sistema_documental_box_vigilancia.md`: Box debe quedar protegido frente a automatizaciones destructivas o de reorganización indiscriminada.
* **Origen / Fuente primaria:** `011_sistema_documental_box_vigilancia.md`.
* **Parte modificada:** La prohibición absoluta de escritura queda sustituida por `DOC-003`, que permite crear copias nuevas controladas y trazables ERP ↔ Box.
* **Invariantes conservados:**
  - no eliminación automática de objetos existentes por defecto;
  - no movimiento automático dentro de Box por defecto;
  - no renombrado automático de objetos existentes por defecto;
  - no sobrescritura silenciosa;
  - no reorganización indiscriminada;
  - integridad, trazabilidad y mínima capacidad necesaria.
* **Evolución y modificaciones:** Modificada parcialmente por `20261005_resolucion_box_copia_bidireccional_controlada.md` → `DOC-003`.
* **Relaciones relevantes:** `DOC-002`, `DOC-003`, `ARCH-004`.

#### `DOC-002` · Clasificación Documental de Extranjería e Invalidez de Resguardos
* **Estado:** VIGENTE
* **Decisión vigente:** Se mantienen las reglas oficiales de clasificación documental y detección de estados para expedientes de Extranjería observados en Box:
  - `Resguardo_XXXX.pdf` no constituye por sí mismo justificante oficial válido;
  - PRESENTADO exige justificante oficial válido en contexto compatible;
  - TASA requiere evidencia compatible y no se acredita solo por carpeta;
  - REQUERIMIENTO y SUBSANACIÓN/APORTACIÓN dependen de documento válido y contexto de ruta;
  - resoluciones se clasifican por contexto compatible;
  - `DOCUMENTO + CONTEXTO DE RUTA` prevalece sobre nombre aislado.
* **Origen / Fuente primaria:** `014_resolucion_box_extranjeria_v1.md`.
* **Invariantes:** La copia bidireccional autorizada por `DOC-003` no altera estas reglas de interpretación documental.
* **Evolución y modificaciones:** Permanece vigente.
* **Relaciones relevantes:** `DATA-002`, `DOC-001`, `DOC-003`.

#### `DOC-003` · Copia Bidireccional Controlada ERP ↔ Box y Watchdog/Listener Documental
* **Estado:** VIGENTE
* **Decisión vigente:** El ERP puede realizar copias nuevas, controladas, verificadas y trazables entre almacenamiento local/Bandeja Documental y destinos Box autorizados, manteniendo prohibidas por defecto las operaciones destructivas sobre objetos existentes.
* **Origen / Fuente primaria:** `20261005_resolucion_box_copia_bidireccional_controlada.md`.
* **Flujos autorizados:**
  - `Downloads → Bandeja Documental → clasificación/dedupe → expediente → copia controlada a Box`;
  - `Box → Bandeja / área temporal / Downloads` para revisión, OCR, transformación, envío, indexación, Knowledge u otras funciones autorizadas;
  - documentos generados por ERP pueden copiarse a Box mediante el mismo canal gobernado.
* **Regla operativa:** `COPY → VERIFY → REGISTER`.
* **Operaciones no autorizadas por defecto:**
  - `delete`;
  - `move` de objetos existentes dentro de Box;
  - `rename` de objetos existentes;
  - sobrescritura silenciosa;
  - reorganización automática indiscriminada.
* **Staging:** La Bandeja Documental actúa como capa de entrada, inspección, clasificación, dedupe, asociación, selección de destino, copia, verificación y registro; no es una segunda fuente documental canónica.
* **Dedupe/colisiones:** Antes de escribir se comprobarán, cuando sea técnicamente posible, existencia, hash, nombre, tamaño y metadata. Una colisión no produce sobrescritura silenciosa.
* **Trazabilidad:** Las operaciones deben poder registrar origen, destino, expediente, hash, tamaño, timestamp, actor/worker, resultado, error y política aplicada cuando proceda.
* **Watchdog/Listener Box:** Las raíces/carpetas autorizadas serán observables mediante Listener pasivo para detectar creación, modificación, movimiento, renombrado, eliminación y cambios estructurales. El Listener observa y registra; no ejecuta esas operaciones.
* **Event Ledger y reconciliación:** Los eventos deberán ser idempotentes, tolerar duplicados/debounce y complementarse con escaneo/reconciliación periódica para recuperar eventos perdidos, cambios con ERP apagado y modificaciones desde otros equipos.
* **Estabilidad:** Un archivo en proceso de copia/sincronización no debe procesarse como definitivo hasta verificar estabilidad suficiente mediante tamaño, tiempo, reintentos, hash, locks, señales del conector u otro mecanismo equivalente.
* **Watchdog local:** El mismo patrón podrá observar Downloads y otras carpetas locales autorizadas para alimentar la Bandeja Documental.
* **Arquitectura:** `Frontend → Application/Document Service → Box Connector/Storage Adapter → Box`; no hay lógica Box directa en Flet.
* **Relación con Knowledge:** Knowledge puede consumir contenido/referencias autorizadas, pero no obtiene una vía propia de escritura a Box; cualquier copia pasa por el servicio documental gobernado por `DOC-003`.
* **Relaciones relevantes:** `DOC-001`, `DOC-002`, `KNOW-003`, `DATA-009`, `ARCH-001`.


---

### 2. KNOWLEDGE Y APRENDIZAJE OPERATIVO (`KNOW`)

#### `KNOW-001` · Flujo Circular Operativo del Cliente y Generación de Conocimiento
* **Estado:** MODIFICADA
* **Decisión vigente:** Se mantiene el flujo circular por el que la experiencia de captación, expediente, documentación, automatización, resolución y criterios internos se convierte en conocimiento reutilizable.
* **Origen / Fuente primaria:** `015_flujo_circular_cliente.md`.
* **Elementos que permanecen vigentes:**
  - anonimización previa cuando proceda;
  - extracción de hechos y criterios relevantes;
  - validación jurídica humana;
  - retroalimentación del conocimiento hacia futuros expedientes y operaciones.
* **Parte modificada:** NotebookLM deja de ser destino operativo ordinario o dependencia de Knowledge. Puede utilizarse como herramienta externa auxiliar, pero no es repositorio canónico, fuente de verdad ni dependencia del runtime.
* **Evolución y modificaciones:** Modificada por `20261005_resolucion_knowledge_nativo_y_gobierno_de_conocimiento.md` → `KNOW-003`.
* **Relaciones relevantes:** `KNOW-002`, `KNOW-003`, `DATA-009`, `OPS-001`.

#### `KNOW-002` · Supervisión Jurídica Humana Obligatoria sobre Criterios de IA
* **Estado:** VIGENTE
* **Decisión vigente:** Todo criterio generado, sintetizado o sugerido mediante IA deberá revisarse, validarse y consolidarse por profesional responsable antes de adquirir valor como criterio jurídico interno o utilizarse en actuaciones que requieran juicio profesional.
* **Origen / Fuente primaria:** `015_flujo_circular_cliente.md` (Sec. XI).
* **Invariantes:**
  - la IA asiste;
  - la fuente soporta;
  - el profesional valida;
  - una salida de IA no adquiere autoridad jurídica por sí misma.
* **Evolución y modificaciones:** Reafirmada expresamente por `20261005_resolucion_knowledge_nativo_y_gobierno_de_conocimiento.md`; no se modifica.
* **Relaciones relevantes:** `KNOW-001`, `KNOW-003`, `DATA-009`.

#### `KNOW-003` · Knowledge Nativo como Plataforma de Conocimiento del Ecosistema Quesada Abogados
* **Estado:** VIGENTE
* **Decisión vigente:** Knowledge es un módulo propio y nativo del ecosistema Quesada Abogados. Debe ingerir y registrar fuentes, conservar procedencia y trazabilidad, relacionar normativa, criterios, documentos y experiencia, reutilizar conocimiento derivado de expedientes anonimizados y asistir mediante proveedores de IA sin convertirlos en repositorio canónico.
* **Origen / Fuente primaria:** `20261005_resolucion_knowledge_nativo_y_gobierno_de_conocimiento.md`.
* **Modelo de autoridad:**
  1. fuente primaria/oficial;
  2. fuente secundaria/especializada;
  3. criterio interno validado;
  4. conocimiento derivado de expediente anonimizado;
  5. inferencia de IA.
* **Invariantes:**
  - la fuente original prevalece sobre resúmenes, embeddings, índices, chunks o respuestas generadas;
  - Knowledge debe distinguir fuente, criterio validado e inferencia;
  - los modelos de IA son proveedores de inferencia y deben quedar desacoplados del corpus canónico;
  - cambiar de proveedor no debe obligar a rediseñar el conocimiento;
  - si las fuentes son insuficientes, el sistema no inventa respaldo documental;
  - una respuesta general de modelo sin respaldo suficiente debe identificarse como inferencia no fundamentada en el corpus;
  - Knowledge respeta `DATA-009`: referencia e indexa dominios existentes, no crea copias autoritativas competidoras;
  - Knowledge Documental no autoriza por sí mismo operaciones sobre Box; cualquier copia permitida debe pasar por el servicio documental gobernado por `DOC-003`.
* **Trazabilidad:** Cuando proceda se conservarán identificador, tipo, origen, fecha, versión, ámbito, referencia/URL, hash, vigencia, relaciones, fragmentos utilizados, validaciones humanas e historial de actualización.
* **Privacidad:** El aprendizaje procedente de expedientes reales aplicará anonimización/minimización y privacidad por diseño antes de incorporarse a corpus reutilizables o enviarse a proveedores externos cuando corresponda.
* **Tecnología:** La resolución no fija todavía motor vectorial, embeddings, base vectorial, chunking, RAG, proveedor LLM único ni UI definitiva. Estas decisiones se tomarán contra necesidad real, contratos, tests y evidencia.
* **Relaciones relevantes:** `KNOW-001`, `KNOW-002`, `DATA-009`, `DOC-001`.


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

### 2. EVOLUCIÓN DOCUMENTAL BOX FORMALIZADA

La divergencia `011 ↔ 016` queda resuelta por `20261005_resolucion_box_copia_bidireccional_controlada.md`.

La arquitectura vigente permite copias bidireccionales controladas ERP ↔ Box mediante `DOC-003`, mantiene `DOC-002` vigente y modifica parcialmente `DOC-001`.

El Watchdog/Listener de Box y carpetas locales de ingestión forma parte del contrato funcional aprobado de vigilancia, con eventos idempotentes, reconciliación periódica y procesamiento semántico útil para el ERP.

---

> ESTADO: 03_DOCUMENTAL_KNOWLEDGE_OPERACIONES — APROBADO POR DIRECCIÓN
