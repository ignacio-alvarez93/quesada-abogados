# `03_DOCUMENTAL_KNOWLEDGE_OPERACIONES.md` — FUENTE MAESTRA DE SISTEMA DOCUMENTAL, KNOWLEDGE Y OPERACIONES DE NEGOCIO

**Proyecto:** Quesada Abogados CRM
**Naturaleza del Documento:** Fuente Maestra Consolidada 03 de 06
**Estado:** APROBADO POR DIRECCIÓN
**Trazabilidad:** Construido a partir del Registro Canónico Aprobado (`00_MASTER_INDEX.md`).
**FUENTES NORMATIVAS BASE:** `002_funcionamiento_negocio.md`, `003_ecosistema_tecnologico.md`, `011_sistema_documental_box_vigilancia.md`, `014_resolucion_box_extranjeria_v1.md`, `015_flujo_circular_cliente.md`, `20260801_resolucion_sistema_nomenclaturas_y_hoja_ruta.md`, `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md`, `20261005_resolucion_knowledge_nativo_y_gobierno_de_conocimiento.md`, `20261005_resolucion_box_copia_bidireccional_controlada.md`, `20261007_resolucion_flujo_circular_cliente_v2_y_gobierno_omnicanal_leads.md`, `20261010_resolucion_modelo_integral_automatizaciones_administrativas.md`, `20261010_resolucion_panel_qcc_obligatorio_contexto_operativo_automatizaciones_administrativas.md`.
**FUENTES INFORMATIVAS NO NORMATIVAS:** `20260809_resolucion_estado_actual_proyecto_y_hoja_ruta_supabase.md` (secciones de estado de tareas, vigilancia documental y knowledge).

---

## SECCIÓN I: MARCO GENERAL Y ALCANCE

La presente Fuente Maestra consolida de forma unificada las decisiones normativas aprobadas sobre el Sistema Documental en Box Drive, las reglas de clasificación documental en extranjería, el motor documental semántico de nomenclaturas canónicas, roles, grupos, readiness, snapshots y eventos, el flujo circular operativo del cliente, la integración con la base de conocimiento (Knowledge), la supervisión jurídica humana sobre herramientas de IA, las operaciones de negocio del despacho y la unificación de tareas mediante la entidad canónica `TASK` y el Centro de Actividades Administrativas (CAA).

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


#### `DOC-004` · Motor Documental Semántico: Nomenclaturas, Roles, Grupos, Readiness, Snapshots y Eventos
* **Estado:** VIGENTE
* **Decisión vigente:** Se aprueba como base del sistema documental la arquitectura semántica formada por nomenclaturas canónicas, variantes, roles documentales, grupos de requisitos, opciones, reglas AND/OR, cardinalidad, equivalencias, obligatoriedad/opcionalidad, readiness, estados semánticos, snapshots, fingerprints y eventos idempotentes.
* **Origen / Fuente primaria:** `20260801_resolucion_sistema_nomenclaturas_y_hoja_ruta.md`.
* **Identidad documental:** La nomenclatura canónica es la identidad estable del tipo documental; los nombres reales de archivo son variantes o evidencias de detección.
* **Documento ≠ rol:** El tipo de documento y el rol de la persona a la que corresponde son dimensiones separadas. Un documento solo satisface el requisito correcto cuando su tipo, rol y contexto son compatibles.
* **Jerarquía funcional:** `familia → tipo → subtipo → relación/rol → grupos documentales → opciones documentales`.
* **Estado documental ≠ estado procesal:** Un expediente puede estar documentalmente completo y procesalmente pendiente, o presentado y documentalmente incompleto por un requerimiento posterior.
* **Eventos semánticos:** Un nuevo escaneo sin cambio real no genera un nuevo evento. Los cambios reales se detectan mediante snapshots/fingerprints y los eventos deberán ser idempotentes, trazables al scan/job y aislables por expediente.
* **Separación de responsabilidades:** Expediente gobierna tipo/subtipo/personas/estado procesal; Formularios gobierna formulario/mapeo/snapshot/presentación; Documental gobierna grupos/nomenclaturas/roles/faltantes/readiness/estado documental; Eventos registran cambios; Notificaciones decide qué eventos se muestran o derivan.
* **Protección de desarrollos existentes:** La evolución documental no debe alterar IDs/códigos/significados ya usados por tipos, subtipos, formularios, mappers, snapshots, presentación asistida, Mercurio, relaciones familiares, automatizaciones o pruebas.
* **Migraciones:** Se priorizan cambios aditivos (`CREATE TABLE`, `ADD COLUMN nullable`, índices y configuración). `DROP TABLE`, eliminación/reutilización de IDs, cambio semántico de campos o reescritura masiva requieren migración expresa y auditada.
* **Relación con `ProcedureContract`:** La resolución `20261010_resolucion_modelo_integral_automatizaciones_administrativas.md` incorpora `document_requirements` al contrato del procedimiento como proyección coordinada. Al no existir modificación expresa de `DOC-004`, el motor documental semántico conserva su autoridad sobre nomenclaturas, roles, grupos, opciones, readiness y estado documental; `ProcedureContract` debe referenciar o proyectar esos requisitos sin crear una fuente documental competidora.
* **Relaciones relevantes:** `DOC-002`, `DOC-003`, `DOC-005`, `OPS-004`, `DATA-002`, `DATA-009`, `ARCH-005`, `WEB-005`.

#### `DOC-005` · Transición Legacy → Semántico mediante Activación Progresiva y Pilotos
* **Estado:** VIGENTE
* **Decisión vigente:** El motor legacy continúa como comportamiento predeterminado hasta que cada combinación de familia/tipo/subtipo haya sido configurada, probada y autorizada. El motor semántico adquiere autoridad de forma progresiva, nunca mediante activación general inmediata.
* **Origen / Fuente primaria:** `20260801_resolucion_sistema_nomenclaturas_y_hoja_ruta.md`.
* **Fases de activación:** legacy + diagnóstico semántico en sombra → `SEMANTIC_ELIGIBLE` por tipo/subtipo autorizado → validación de diferencias/readiness/regresiones → activación posterior de eventos semánticos Box.
* **Flags:** `DOCUMENT_STATE_ENGINE_MODE=SEMANTIC_ELIGIBLE` y `DOCUMENT_SEMANTIC_SCAN_EVENTS_ENABLED=1` no se activan globalmente sin validación previa.
* **Pilotos aprobados:** Familia `RESIDENCIA`; primer piloto `REAGRUPACIÓN FAMILIAR · INICIAL`; después `RESIDENCIA NO LUCRATIVA · INICIAL` y `RESIDENCIA NO LUCRATIVA · RENOVACIÓN`.
* **Compatibilidad obligatoria:** Deben protegerse Reagrupación Familiar, No Lucrativa, EX01, EX02, EX32, presentación asistida, snapshots, mappers y relaciones familiares.
* **Lectura durante piloto:** El motor semántico puede leer expediente, relaciones, clientes, inventario, rutas, nomenclaturas y documentos detectados; solo escribe diagnósticos, snapshots y eventos semánticos. No modifica expedientes, clientes, formularios, snapshots de formularios, presentación asistida, relaciones familiares ni cola de presentación.
* **Criterio de integración:** familia/tipo/subtipo estables, roles, grupos, opciones, nomenclaturas, reglas, readiness, comparación legacy/semántico, ausencia de regresiones, tests, feature flag autorizado, eventos revisados y notificaciones definidas cuando proceda.
* **Relaciones relevantes:** `DOC-004`, `OPS-004`, `DATA-002`, `OPS-003`.


#### `DOC-006` · Target Presentation Folder como Selección Documental Canónica de una Presentación
* **Estado:** VIGENTE
* **Decisión vigente:** Para cada actuación administrativa concreta podrá existir una `Target Presentation Folder` que represente la selección documental preparada para el subexpediente o presentación que se va a ejecutar. QCC debe proyectar únicamente los documentos de ese target y no toda la documentación disponible del cliente o expediente.
* **Origen / Fuente primaria:** `20261010_resolucion_panel_qcc_obligatorio_contexto_operativo_automatizaciones_administrativas.md`.
* **Contenido mínimo proyectable:** cada documento target debe poder identificar `document_id`, nombre de archivo, disponibilidad y una ubicación/ruta válida para su acceso; el Panel QCC debe ofrecer una acción individual `COPIAR RUTA`.
* **Autoridad documental:** La ruta física o lógica debe proceder de la autoridad documental correspondiente y no ser reconstruida artificialmente por el frontend. La ruta física local no se convierte por ello en identidad canónica del documento y se mantiene `ARCH-003`.
* **Separación de responsabilidades:** `Target Presentation Folder` es la selección documental de una actuación concreta. No sustituye el motor semántico de `DOC-004`, no convierte QCC en repositorio documental y no crea una segunda fuente de verdad.
* **Carpeta completa:** La acción de copiar la ruta de la carpeta de presentación es recomendable, pero no sustituye el botón obligatorio de ruta individual de cada documento.
* **Relaciones relevantes:** `DOC-003`, `DOC-004`, `DATA-009`, `ARCH-003`, `ARCH-005`, `QCC-006`, `WEB-006`.


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
* **Ampliación V2:** El flujo deja de representarse únicamente como círculo lineal y pasa a un modelo multibucle y longitudinal que conecta adquisición, Lead omnicanal, lifecycle comercial, Cliente, Expediente, operación, resultado, Knowledge, contenido y nuevas necesidades.
* **Evolución y modificaciones:** Modificada por `20261005_resolucion_knowledge_nativo_y_gobierno_de_conocimiento.md` → `KNOW-003`; ampliada por `20261007_resolucion_flujo_circular_cliente_v2_y_gobierno_omnicanal_leads.md` → `KNOW-004`.
* **Relaciones relevantes:** `KNOW-002`, `KNOW-003`, `KNOW-004`, `DATA-009`, `OPS-001`, `OPS-005`, `OPS-006`.

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


#### `KNOW-004` · Flujo Circular del Cliente V2 y Aprendizaje Multibucle
* **Estado:** VIGENTE
* **Decisión vigente:** El flujo circular evoluciona a un ecosistema jurídico, comercial, documental y de conocimiento multibucle, trazable y autoalimentado. La unidad estratégica es la relación longitudinal persona ↔ despacho, no únicamente un expediente aislado.
* **Origen / Fuente primaria:** `20261007_resolucion_flujo_circular_cliente_v2_y_gobierno_omnicanal_leads.md`.
* **Bucles aprobados:** adquisición; comercial; jurídico-operativo; conocimiento; y longitudinal.
* **Invariantes:** `OPEN → CONVERTED` es válido sin pasar por `QUALIFIED`; Knowledge, IT y Marketing no quedan técnicamente acoplados; cada dominio conserva su autoridad canónica; la resolución de un expediente no implica el fin de la relación; privacidad y supervisión humana siguen vinculantes.
* **Materias no aprobadas:** `Opportunity`, scoring avanzado, atribución First/Last Touch definitiva, CAC/ROI, comisiones de Partners, Philosophy como capa normativa o proveedor de IA comercial único.
* **Relaciones relevantes:** `KNOW-001`, `KNOW-002`, `KNOW-003`, `OPS-005`, `OPS-006`, `DATA-009`, `QCC-004`.

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
* **Evolución y modificaciones:** Sirve de base funcional a los modelos posteriores de Clientes, Expedientes y Económico; las antiguas colas operativas evolucionan después hacia TASK/CAA. Queda complementada por `20261007_resolucion_flujo_circular_cliente_v2_y_gobierno_omnicanal_leads.md`, que formaliza el lifecycle comercial previo y la relación Lead → Cliente → Expediente.
* **Relaciones relevantes:** Conecta con `DATA-001`, `DATA-002`, `DATA-003` y `OPS-003`.

#### `OPS-002` · Integración de Herramientas Externas mediante CSV
* **Estado:** MODIFICADA PARCIALMENTE
* **Decisión vigente:** HubSpot puede continuar como canal de captación, herramienta comercial externa, origen de Leads, sistema auxiliar de marketing o integración. Holded continúa como sistema contable oficial y no queda modificado. CSV sigue siendo un mecanismo válido; APIs, webhooks o sincronización avanzada podrán incorporarse mediante contratos posteriores.
* **Parte modificada:** Cuando exista el dominio Lead nativo del CRM, Quesada Abogados CRM es la autoridad canónica del Lead. HubSpot no constituye una fuente de verdad competidora.
* **Origen / Fuente primaria:** `003_ecosistema_tecnologico.md`.
* **Modificada por:** `20261007_resolucion_flujo_circular_cliente_v2_y_gobierno_omnicanal_leads.md` → `OPS-005`.
* **Relaciones relevantes:** `OPS-005`, `OPS-006`, `DATA-005`, `DATA-006`, `DATA-009`.

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

#### `OPS-004` · Enrutamiento de Eventos de Dominio a Notificaciones, Calendar y CAA
* **Estado:** VIGENTE
* **Decisión vigente:** Las notificaciones y tareas no deben originarse directamente por la mera existencia de un archivo. Deben derivar de un cambio de estado reconocido y de un evento de dominio.
* **Origen / Fuente primaria:** `20260801_resolucion_sistema_nomenclaturas_y_hoja_ruta.md`.
* **Flujo aprobado:** `documento o acción → cambio de estado → evento de dominio → política de notificación → notificación visible → Calendar o CAA cuando proceda`.
* **Autoridad de eventos:** Trazabilidad conserva los eventos procesales; el motor documental produce los eventos documentales.
* **Enrutamiento:** evento informativo → Notificaciones; evento con fecha → Calendar; evento que exige actuación → CAA; evento con actuación y plazo → CAA + Calendar + Notificación.
* **Invariante:** Notificaciones, Calendar y CAA consumen/proyectan eventos y trabajo canónico; no sustituyen la fuente de verdad documental o procesal.
* **Relaciones relevantes:** `DOC-004`, `DOC-005`, `OPS-003`, `DATA-009`.

#### `OPS-005` · Lead Omnicanal como Unidad Canónica del Ciclo Comercial
* **Estado:** VIGENTE
* **Decisión vigente:** `Lead` es la unidad canónica del ciclo comercial asociado a una necesidad concreta de servicio. El CRM Quesada Abogados es su autoridad canónica. WhatsApp, email, redes sociales, HubSpot, web, partners, recomendaciones y otros sistemas son canales, fuentes o integraciones.
* **Separación:** `Persona ≠ Lead ≠ Cliente`. Lead no sustituye a Contacto, Expediente, Communication ni TASK.
* **Omnicanalidad y deduplicación:** varios canales para la misma persona + misma necesidad comercial + Lead activo representan el mismo Lead; una necesidad diferente puede originar otro Lead.
* **Origen / Fuente primaria:** `20261007_resolucion_flujo_circular_cliente_v2_y_gobierno_omnicanal_leads.md`.
* **Relaciones relevantes:** `OPS-001`, `OPS-002`, `OPS-006`, `KNOW-004`, `DATA-009`, `QCC-004`.

#### `OPS-006` · Lifecycle Comercial y Conversión Lead → Cliente → Expediente
* **Estado:** VIGENTE
* **Decisión vigente:** Estados mínimos: `OPEN`, `QUALIFIED`, `CONVERTED`, `LOST`.
* **Transiciones:** `OPEN → QUALIFIED`, `OPEN → CONVERTED`, `OPEN → LOST`, `QUALIFIED → CONVERTED`, `QUALIFIED → LOST`.
* **Regla esencial:** `QUALIFIED` significa consulta pagada y es opcional; un Lead puede convertirse directamente desde `OPEN`.
* **Conversión:** conserva el Lead histórico y crea o vincula Cliente y Expediente cuando corresponda. Una persona ya Cliente puede generar nuevos Leads sin duplicar identidad.
* **Hitos:** `created_at`, `qualified_at`, `converted_at`, `lost_at` cuando proceda; `qualified_at` puede ser `NULL` en conversión directa.
* **Origen / Fuente primaria:** `20261007_resolucion_flujo_circular_cliente_v2_y_gobierno_omnicanal_leads.md`.
* **Relaciones relevantes:** `OPS-005`, `OPS-001`, `OPS-003`, `KNOW-004`, `DATA-001`, `DATA-002`, `DATA-009`.

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

### 2. ESTADO HISTÓRICO DEL MOTOR DOCUMENTAL SEMÁNTICO (NO NORMATIVO)

La resolución `20260801_resolucion_sistema_nomenclaturas_y_hoja_ruta.md` declaró el sistema documental semántico técnicamente aprobado, operativamente todavía en modo legacy y preparado para despliegue progresivo.

En ese estado ya existían nomenclaturas canónicas, roles, grupos, opciones, reglas AND/OR, cardinalidad, equivalencias, readiness, snapshots, fingerprints, eventos semánticos y feature flags, mientras `DOCUMENT_STATE_ENGINE_MODE` y `DOCUMENT_SEMANTIC_SCAN_EVENTS_ENABLED` permanecían desactivados por defecto.

La autoridad normativa de arquitectura y activación se conserva en `DOC-004`, `DOC-005` y `OPS-004`; esta sección registra únicamente el estado histórico descrito por la fuente.

---

### 3. EVOLUCIÓN DOCUMENTAL BOX FORMALIZADA

La divergencia `011 ↔ 016` queda resuelta por `20261005_resolucion_box_copia_bidireccional_controlada.md`.

La arquitectura vigente permite copias bidireccionales controladas ERP ↔ Box mediante `DOC-003`, mantiene `DOC-002` vigente y modifica parcialmente `DOC-001`.

El Watchdog/Listener de Box y carpetas locales de ingestión forma parte del contrato funcional aprobado de vigilancia, con eventos idempotentes, reconciliación periódica y procesamiento semántico útil para el ERP.

---

> ESTADO: 03_DOCUMENTAL_KNOWLEDGE_OPERACIONES — APROBADO POR DIRECCIÓN
