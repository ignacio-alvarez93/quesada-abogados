# `02_ARQUITECTURA_ERP_DATOS.md` — FUENTE MAESTRA DE ARQUITECTURA ERP, DATOS Y FRONTEND

**Proyecto:** Quesada Abogados CRM
**Naturaleza del Documento:** Fuente Maestra Consolidada 02 de 06
**Estado:** APROBADO POR DIRECCIÓN
**Trazabilidad:** Construido a partir del Registro Canónico Aprobado (`00_MASTER_INDEX.md`).
**FUENTES NORMATIVAS BASE:** `001_metodologia_trabajo.md`, `004_frontend_flet.md`, `005_modelo_datos_clientes.md`, `006_modelo_datos_expedientes.md`, `007_modelo_datos_economico_cobros.md`, `008_conciliacion_economica.md`, `009_modulo_fiscal.md`, `010_legacy_migracion_reconstruccion.md`, `013_estructura_repositorio.md`, `017_componentes_sistema.md`, `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md`, `20260809_resolucion_estado_actual_proyecto_y_hoja_ruta_supabase.md`, `20261010_resolucion_modelo_integral_automatizaciones_administrativas.md`, `20261010_resolucion_panel_qcc_obligatorio_contexto_operativo_automatizaciones_administrativas.md`.
**FUENTES INFORMATIVAS NO NORMATIVAS:** `018_informe_tecnico_cuadro_gris.md`, `20260809_resolucion_estado_actual_proyecto_y_hoja_ruta_supabase.md` (secciones de estado técnico, porcentajes de avance y métricas históricas).

---

## SECCIÓN I: MARCO GENERAL Y ALCANCE

La presente Fuente Maestra consolida de forma unificada las decisiones normativas aprobadas sobre Arquitectura General del ERP, Modelo de Datos, Persistencia, Módulos Funcionales (Clientes, Expedientes, Económico, Conciliación, Fiscal, Legacy) y Frontend UI (Flet y componentes reutilizables).

La Fuente Maestra no crea autoridad normativa por sí misma. Consolida las decisiones normativas aprobadas contenidas en las fuentes originales del proyecto Quesada Abogados CRM, preservando la jerarquía de capas, la centralización progresiva de la persistencia, la prohibición de lógica de datos en el frontend y el principio de una única fuente canónica de verdad por concepto.

---

## SECCIÓN II: DECISIONES NORMATIVAS APROBADAS (ARCH, DATA, UI)

### 1. ARQUITECTURA GENERAL DEL ERP (`ARCH`)

#### `ARCH-001` · Separación Estricta de Capas
* **Estado:** VIGENTE
* **Decisión vigente:** Desacoplamiento obligatorio de la arquitectura del ERP en 4 capas superpuestas e independientes:
  1. **Frontend / Presentación (Flet):** Responsable exclusivamente de la representación visual, la captura de datos de entrada, la navegación, la composición de componentes y la presentación de resultados o errores. No contiene reglas de negocio, lógica de persistencia ni consultas SQL.
  2. **Application / Services:** Coordinación de casos de uso del ERP, orquestación de flujos de trabajo, control de transacciones y comunicación entre presentación y dominio.
  3. **Dominio:** Lógica de negocio pura, cálculo de entidades, validaciones jurídicas, mappers y estados administrativos/documentales.
  4. **Persistencia / Infraestructura:** Acceso a datos, drivers de base de datos, consultas SQL/ORM, conexión centralizada y mappers de almacenamiento.
* **Origen / Fuente primaria:** `001_metodologia_trabajo.md` (Sec. 4.4) / `004_frontend_flet.md` (Sec. 5).
* **Justificación documentada:** Permitir la evolución del backend o el cambio futuro de la tecnología de frontend sin necesidad de reescribir la lógica de negocio ni las consultas a la base de datos, garantizando un sistema modular y escalable.
* **Invariantes:**
  - Queda estrictamente prohibido mezclar interfaz gráfica, lógica de negocio y acceso a la base de datos en el mismo módulo o archivo.
  - El frontend no condiciona ni limita la arquitectura del backend.
  - Las vistas UI nunca ejecutan consultas directas a la base de datos.
* **Evolución y modificaciones:** Desarrollada y profundizada por `013_estructura_repositorio.md` (Sec. 5) y `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` (Sec. II).
* **Relaciones relevantes:** Conecta directamente con `UI-001` (Prohibición de SQL en Flet) y `ARCH-002` (Estructura física del repositorio).

#### `ARCH-002` · Estructura Física del Repositorio
* **Estado:** VIGENTE
* **Decisión vigente:** Organización obligatoria del repositorio en carpetas con responsabilidad única y acotada:
  - **`app/`:** Puntos de entrada principales y lanzadores operativos esenciales (`main.py`, `run_presentacion_asistida.py`). No se utiliza como almacén de scripts temporales.
  - **`backend/`:** Servicios de aplicación (`services/`), validadores (`validators/`) y lógica de negocio.
  - **`database/`:** Conexión centralizada (`connection.py`), esquemas SQL (`schema.sql`), migraciones versionadas y datos maestros.
  - **`frontend/`:** Vistas principales (`views/`), componentes reutilizables (`components/`) y estructuras de interfaz (`layouts/`).
  - **`docs/`:** Resoluciones normativas (`resolutions/`), informes técnicos e índices maestros del proyecto.
  - **`scripts/`:** Herramientas auxiliares técnicas de desarrollo (diagnósticos, parches, pruebas sintéticas, semillas).
  - **`tools/`:** Herramientas operativas consolidadas de uso estable por el despacho (`admin/`, `automation/`, `imports/`).
* **Origen / Fuente primaria:** `013_estructura_repositorio.md` (Sec. 3 a 10).
* **Justificación documentada:** Tratar el repositorio como una plataforma ERP modular empresarial, evitando la dispersión de archivos temporales y garantizando que cada componente o script tenga una ubicación clara según su función real.
* **Invariantes:**
  - `app/` no se utiliza para guardar scripts temporales de prueba.
  - `docs/` alberga la autoridad normativa histórica del proyecto.
  - Los scripts de desarrollo (`scripts/`) permanecen separados de las herramientas operativas estables del despacho (`tools/`).
* **Evolución y modificaciones:** Desarrolla y formaliza la estructura inicial básica planteada en `001_metodologia_trabajo.md` (Sec. 5).
* **Relaciones relevantes:** Conecta con `ARCH-001` (Separación de capas) y `SEC-001` (Seguridad en Git).

#### `ARCH-003` · Prohibición de Rutas Absolutas Personales
* **Estado:** VIGENTE
* **Decisión vigente:** Queda estrictamente prohibido incluir rutas absolutas locales de máquina (ejemplos tipo `C:\Users\Nacho\...`) como identidad canónica de recursos en el código fuente, configuraciones o registros de la base de datos.

  Todos los recursos, archivos, carpetas y configuraciones deben referenciarse mediante rutas relativas a la raíz del proyecto, identificadores lógicos externos, raíces configurables en infraestructura o variables de entorno.
* **Origen / Fuente primaria:** `001_metodologia_trabajo.md` (Sec. 4.1).
* **Justificación documentada:** Garantizar la portabilidad del ERP entre diferentes ordenadores, desarrolladores y entornos operativos sin provocar errores por falta de archivos o rutas inexistentes.
* **Invariantes:**
  - La ruta física concreta de un recurso es una propiedad del agente o entorno local, no una identidad lógica de la entidad en la base de datos.
* **Evolución y modificaciones:** Reafirmada e integrada en la normativa de gobierno de código por `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` (Sec. XXIII).
* **Relaciones relevantes:** Conecta con `DOC-001` (Vigilancia de Box Drive) y `ARCH-004` (Arquitectura híbrida).

#### `ARCH-004` · Arquitectura Híbrida Cloud / Agentes Locales
* **Estado:** VIGENTE
* **Decisión vigente:** Definición estructural del ERP como un sistema híbrido que distingue dos tipos de componentes según sus requisitos de ejecución:
  - **Componentes Cloud-capable:** Procesos que pueden ejecutarse de forma centralizada en servidores o infraestructura Cloud (PostgreSQL/Supabase, sincronización de correos Gmail/IONOS, notificaciones programadas en outbox, Telegram, procesamiento DEHú no dependiente de certificado digital).
  - **Componentes Local-required (Agente local / Desktop):** Procesos que requieren ejecutarse en el entorno de escritorio del usuario (acceso a carpetas locales de Box Drive, automatización asistida Mercurio/Sedes con certificado digital local, OCR local, generación de documentos Word/PDF en filesystem local).
* **Origen / Fuente primaria:** `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` (Sec. XXIV).
* **Justificación documentada:** Adaptarse a los requisitos técnicos de las sedes electrónicas públicas españolas (que exigen certificado local de usuario) sin renunciar a la centralización de datos y servicios en la nube.
* **Invariantes:**
  - No intentar cloudificar de forma prematura automatizaciones o procesos estrictamente dependientes de certificados o archivos del escritorio local.
  - No introducir dependencias innecesarias del escritorio en procesos que puedan ser ejecutados centralmente en servidores.
* **Evolución y modificaciones:** Desarrollada por `20260809_resolucion_estado_actual_proyecto_y_hoja_ruta_supabase.md` (Sec. XVII).
* **Relaciones relevantes:** Conecta directamente con `DATA-010` (Transición a PostgreSQL) y `WEB-001` (Automation Runtime).


#### `ARCH-005` · `ProcedureContract` como Definición Canónica Integral del Procedimiento Administrativo
* **Estado:** VIGENTE
* **Decisión vigente:** Cada procedimiento administrativo automatizado constituye una única capacidad funcional integral y debe converger progresivamente sobre un `ProcedureContract` canónico. Dicho contrato gobierna tres proyecciones coordinadas: (1) formulario/superficie oficial, (2) formulario/datos internos CRM y (3) automatización de la sede.
* **Origen / Fuente primaria:** `20261010_resolucion_modelo_integral_automatizaciones_administrativas.md`.
* **Superficie oficial:** Cuando exista formulario oficial descargable se modelan su versión, origen, estructura, obligatoriedad, reglas y mapping; cuando no exista PDF independiente, la superficie electrónica de la sede constituye el modelo oficial y debe igualmente quedar estructurada.
* **Formulario CRM:** Reutiliza datos canónicos de Cliente, Expediente, Empresa u otros dominios, evita pedir de nuevo información disponible, incorpora validaciones, obligatoriedad, lógica condicional y bifurcaciones, y prepara los datos específicos del procedimiento.
* **Contrato conceptual mínimo:** `procedure_code`, `procedure_version`, `official_source`, `fields`, `validations`, `conditional_rules`, `branches`, mappings oficial/CRM/sede, `document_requirements`, `navigation_contract`, `readiness_contract`, `human_only_gates`, `expected_outcomes` y `evidence_contract`.
* **Invariantes:**
  - `PERSONA/CLIENTE/EXPEDIENTE` y demás dominios canónicos no se duplican dentro del formulario del procedimiento;
  - el formulario CRM es composición/preparación, no una segunda fuente de verdad;
  - no deben mantenerse definiciones contradictorias del mismo dato entre formulario oficial, CRM y automatización;
  - cada concepto debe tender a una sola definición canónica proyectada hacia los tres componentes;
  - se mantienen `ARCH-001`, `DATA-009` y `UI-001`.
* **Cierre:** La condición de procedimiento/automatización cerrada se gobierna por `WEB-005`; la evidencia REAL y la reconciliación se gobiernan por `SITE-004`; la certificación progresiva mediante TWIN se gobierna por `TWIN-007`. Para automatizaciones administrativas lanzadas desde CRM, `QCC-006` añade la proyección operativa obligatoria `QccPresentationContext`, sin crear una fuente de verdad paralela.
* **Relaciones relevantes:** `ARCH-001`, `DATA-009`, `UI-001`, `DOC-004`, `DOC-006`, `WEB-005`, `QCC-006`, `SITE-004`, `TWIN-007`.


---

### 2. MODELO DE DATOS, PERSISTENCIA Y MÓDULOS DEL ERP (`DATA`)

#### `DATA-001` · Modelo Funcional de Clientes y Red de Contactos
* **Estado:** VIGENTE
* **Decisión vigente:** El cliente es la entidad central del ERP y representa el núcleo de una red de información interconectada.

  Campos mínimos obligatorios: Nombre, primer apellido, segundo apellido, nacionalidad, NIE, pasaporte, DNI, fecha de nacimiento, localidad/país de nacimiento, filiación (nombre de padre y madre), estado civil, teléfono, email, domicilio en España (localidad, código postal, provincia, número, piso) y observaciones.

  Estructura de la Red de Información:
  - **Relaciones con Contactos (Familiares/Representantes):** Relación flexible $N:M$ con tipos configurables (hijo menor, padre, madre, cónyuge, representante, familiar comunitario).
  - **Relaciones con Empresas:** Vinculación flexible $N:M$ para procedimientos de arraigo, autorizaciones de trabajo y reagrupación con medios económicos.
  - **Múltiple participación:** Un cliente puede tener uno o varios expedientes, ser cliente principal en unos y contacto/familiar en otros.
* **Origen / Fuente primaria:** `005_modelo_datos_clientes.md` (Sec. 2, 3, 5, 8, 9, 10).
* **Justificación documentada:** Evitar fichas aisladas, duplicidades, pérdida de información y datos incompletos cuando una persona participa en múltiples trámites o representa a familiares.
* **Invariantes:**
  - El cliente se diseña para evitar duplicidades de persona física aunque varíen sus documentos.
  - Las relaciones cliente-contacto y cliente-empresa deben permitir cardinalidades múltiples ($N:M$).
* **Evolución y modificaciones:** Fundamentada en la operativa real de negocio fijada en `002_funcionamiento_negocio.md` (Sec. 4 y 10).
* **Relaciones relevantes:** Conecta con `DATA-002` (Expedientes) y `OPS-001` (Flujo operativo de negocio).

#### `DATA-002` · Motor Funcional de Expedientes, Catálogo y Estados
* **Estado:** VIGENTE
* **Decisión vigente:** El expediente es la unidad principal de trabajo jurídico-administrativo del despacho. Dispone de un catálogo configurable de autorizaciones (no cerrado en código) y dos dimensiones de estado independientes:

  1. **Estado Documental (Previo a presentación):** `Pendiente de escanear`, `Incompleto`, `Completo`.
  2. **Estado Administrativo (Procesal):** `Presentado`, `Admitido`, `Pendiente en trámite`, `En trámite requerido`, `Resuelto favorable`, `Resuelto denegado`, `Archivado`, `Inadmitido`.

  *Aclaración sobre `Concluido`:* aparece en la resolución original como resultado o estado terminal del flujo `Presentado → Inadmitido → Concluido`, no como miembro del catálogo inicial de estados administrativos.

  Todo expediente requiere vinculación obligatoria a un cliente principal, asignación de responsable interno, tipo/subtipo, provincia, fecha de apertura y registro obligatorio de trazabilidad de cambios (usuario, fecha, estado anterior, estado nuevo, observaciones).
* **Origen / Fuente primaria:** `006_modelo_datos_expedientes.md` (Sec. 2, 3, 4, 7, 8, 9, 14).
* **Justificación documentada:** Desacoplar la madurez del motor general de expedientes del volumen de familias jurídicas configuradas y asegurar el seguimiento de cada trámite sin pérdida de control.
* **Invariantes:**
  - Los estados documentales y administrativos son independientes y no deben mezclarse ni sustituirse mutuamente.
  - Toda modificación de estado en un expediente debe registrar la trazabilidad correspondiente.
* **Evolución y modificaciones:** Desarrollada por `014_resolucion_box_extranjeria_v1.md` y `20260809_resolucion_estado_actual_proyecto_y_hoja_ruta_supabase.md` (Sec. IV.2).
* **Relaciones relevantes:** Conecta con `DATA-001` (Clientes), `DOC-002` (Clasificación documental) y `OPS-003` (TASK/CAA).

#### `DATA-003` · Modelo Económico, Fraccionamiento de Pago y Consultas Descontables
* **Estado:** MODIFICADA
* **Decisión vigente:** **Modificada parcialmente por `DATA-004`.**

  - **Contenido VIGENTE:** El control económico se fundamenta en la Hoja de Encargo (documento económico-jurídico principal que fija honorarios pactados, forma de pago y plazos). El plazo máximo ordinario de fraccionamiento de pago de un expediente es de 3 meses. El sistema deberá detectar expedientes con pagos pendientes fuera de plazo. Contempla la gestión de consultas previas pagadas, permitiendo descontar su importe del total del expediente cuando el cliente contrata posteriormente el trámite (incluso tras transcurrir varios meses). El módulo económico responde a tres preguntas: ¿cuánto se pactó?, ¿cuánto se cobró?, ¿cuánto queda pendiente?.
  - **Contenido MODIFICADO:** Se elimina la generación automática/implícita de facturas asociada a la creación o actualización de un cobro (`create_cobro` / `update_cobro`), la cual fue calificada como deuda técnica y modificada por la regla `DATA-004` ("FACTURABLE ≠ FACTURAR").
* **Origen / Fuente primaria:** `007_modelo_datos_economico_cobros.md` (Sec. 2, 4, 5, 8, 10, 16).
* **Justificación documentada:** Garantizar la rentabilidad del despacho, detectar automáticamente impagos o retrasos y evitar el endeudamiento excesivo de los clientes.
* **Invariantes:**
  - El plazo máximo ordinario de fraccionamiento de un expediente es de 3 meses. El sistema deberá detectar expedientes con pagos pendientes fuera de plazo.
  - Las consultas previas pagadas con carácter descontable deben poder aplicarse a la hoja de encargo posterior.
* **Evolución y modificaciones:** Modificada parcialmente en el mecanismo de emisión de facturas por `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` (Sec. XVII -> `DATA-004`).
* **Relaciones relevantes:** Conecta directamente con `DATA-004` (Facturación explícita) y `DATA-005` (Conciliación económica).

#### `DATA-004` · Regla "FACTURABLE ≠ FACTURAR" (Facturación Explícita)
* **Estado:** VIGENTE
* **Decisión vigente:** Marcar un cobro como facturable significa exclusivamente que reúne las condiciones legales y económicas para ser incluido en una factura.

  La creación y emisión de una factura requiere obligatoriamente una acción voluntaria y explícita del usuario en la interfaz o servicio. Queda expresamente prohibida la generación de facturas por inferencia implícita o mediante disparadores automáticos al registrar o actualizar un cobro.
* **Origen / Fuente primaria:** `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` (Sec. XVII).
* **Justificación documentada:** Corregir la deuda técnica derivada de la creación automática e implícita de facturas en `create_cobro()` y `update_cobro()` en `007_modelo_datos_economico_cobros.md`, evitando descuadres fiscales y facturaciones indebidas.
* **Invariantes:**
  - Ningún servicio backend debe emitir una factura automáticamente de forma implícita al insertar o modificar un cobro.
  - Toda factura emitida debe tener base real y responder a una decisión explícita.
* **Evolución y modificaciones:** Modifica parcialmente a `DATA-003`. Reafirmada en `20260809_resolucion_estado_actual_proyecto_y_hoja_ruta_supabase.md` (Sec. IV.4).
* **Relaciones relevantes:** Conecta con `DATA-003` (Modelo económico) y `DATA-005` (Conciliación).

#### `DATA-005` · Conciliación Económica Previa a la Facturación
* **Estado:** VIGENTE
* **Decisión vigente:** Se facturan exclusivamente cobros reales respaldados por dinero verificado e identificado.
  - **Cobros en banco (Santander, ING, Caja Rural, Stripe):** Se facturan únicamente si están previamente conciliados con el extracto bancario en CSV.
  - **Cobros en efectivo (Cashmatic / caja):** Se facturan únicamente si coinciden con el efectivo realmente ingresado en la cuenta bancaria (ingresos agrupados).
* **Origen / Fuente primaria:** `008_conciliacion_economica.md` (Sec. 1, 7, 10, 11).
* **Justificación documentada:** Asegurar que todo cobro registrado tenga un reflejo real en dinero y que todo dinero en cuenta bancaria tenga un origen identificado, evitando descuadres entre la contabilidad fiscal y los ingresos reales.
* **Invariantes:**
  - Todo ingreso debe estar identificado; todo cobro debe tener respaldo real.
  - Toda factura emitida debe poseer una base económica real previamente verificada.
* **Evolución y modificaciones:** Complementa las reglas de cobros de `007` y el módulo fiscal de `009`.
* **Relaciones relevantes:** Conecta con `DATA-004` (Facturación explícita) y `DATA-006` (Módulo fiscal).

#### `DATA-006` · Módulo Fiscal Interno de Coherencia Tributaria
* **Estado:** VIGENTE
* **Decisión vigente:** El módulo fiscal actúa como motor interno de verificación y control de coherencia tributaria para el régimen de autónomo (Modelos 303, 130, 111, 390, 190) comparando los datos calculados por el ERP (facturación, IVA repercutido, ingresos conciliados) con las declaraciones presentadas por la asesoría fiscal.

  El módulo NO sustituye a la asesoría fiscal ni constituye por sí mismo la contabilidad oficial del despacho.
* **Origen / Fuente primaria:** `009_modulo_fiscal.md` (Sec. 1, 2, 3, 7, 10, 14).
* **Justificación documentada:** Evitar errores tributarios, detectar incoherencias entre lo cobrado, lo facturado y lo declarado, y verificar internamente el trabajo de la asesoría antes de inspecciones.
* **Invariantes:**
  - Solo se considera ingreso válido a efectos del cálculo interno el dinero conciliado en banco o el efectivo realmente ingresado.
  - El módulo fiscal no sustituye a la contabilidad oficial.
* **Evolución y modificaciones:** Su desarrollo se pospone formalmente hasta la estabilización de los cobros y la conciliación bancaria (`20260809_resolucion_estado_actual_proyecto_y_hoja_ruta_supabase.md`).
* **Relaciones relevantes:** Conecta con `DATA-005` (Conciliación); Holded y la integración contable se gobiernan por `OPS-002 / 003_ecosistema_tecnologico.md`.

#### `DATA-007` · Migración Selectiva y Etiquetado Obligatorio de Datos Legacy
* **Estado:** VIGENTE
* **Decisión vigente:** Los datos históricos (recibos, excels y documentos anteriores al ERP desde 2020) no se importan masivamente ni de forma automática. Se someten a clasificación obligatoria en tres niveles:
  - **Fiables:** Cumplen al menos dos condiciones (cliente identificado, importe claro, relación con banco/Cashmatic o recibo físico verificable). Se autoriza su reconstrucción.
  - **Dudosos:** Información incompleta o descuadres parciales. Requieren revisión manual y no se procesan automáticamente.
  - **No Fiables:** Sin cliente identificado o sin soporte documental. No se incorporan al ERP.

  Todo dato reconstruido debe llevar el etiquetado obligatorio: `Origen: LEGACY`, `Tipo: RECONSTRUIDO`, año fiscal, nivel de fiabilidad y referencia de origen. Queda estrictamente prohibido inventar datos faltantes o alterar declaraciones fiscales presentadas.
* **Origen / Fuente primaria:** `010_legacy_migracion_reconstruccion.md` (Sec. 2, 5, 7, 9, 13, 15).
* **Justificación documentada:** Recuperar el máximo valor histórico del despacho sin comprometer la fiabilidad ni la coherencia del nuevo sistema operativo.
* **Invariantes:**
  - Prohibido inventar datos faltantes para forzar el cuadre.
  - Las facturas reconstruidas llevan marca explícita `RECONSTRUIDA` y no sustituyen documentos oficiales ni alteran declaraciones cerradas.
* **Evolución y modificaciones:** Mantiene una separación permanente entre el sistema operativo diario (ERP actual) y el sistema legacy de consulta e investigación.
* **Relaciones relevantes:** Conecta con `DATA-005` (Conciliación) y `DATA-010` (Baseline PostgreSQL).

#### `DATA-008` · Centralización de la Persistencia y Desacoplamiento de SQLite
* **Estado:** VIGENTE
* **Decisión vigente:** Queda prohibido seguir expandiendo en nuevos servicios el patrón `DEFAULT_DB_PATH = Path("database/quesada.db")` y queda prohibido introducir nuevos `sqlite3.connect(...)` dispersos por el dominio.

  Todo nuevo desarrollo deberá utilizar la infraestructura común de persistencia (`database.connection`). No deberá introducirse nueva lógica de negocio dependiente directamente de características particulares de SQLite. Deberán evitarse nuevos usos directos de `PRAGMA`, `sqlite_master`, `INSERT OR IGNORE`, `lastrowid`, `BEGIN IMMEDIATE`, funciones SQL exclusivas de SQLite y rutas hardcodeadas de `quesada.db`. Cuando una funcionalidad necesite una operación de este tipo, deberá encapsularse en infraestructura o diseñarse mediante un contrato portable. La implementación concreta podrá diferir entre SQLite y PostgreSQL.
* **Origen / Fuente primaria:** `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` (Sec. VI y VII).
* **Justificación documentada:** Preparar la base de código para la migración a PostgreSQL/Supabase sin tener que reescribir los servicios de aplicación ni la lógica de dominio.
* **Invariantes:**
  - El conocimiento de la ubicación física de la base de datos se concentra en la capa de infraestructura.
  - Las operaciones multientidad deben ejecutarse mediante transacciones atómicas portables.
* **Evolución y modificaciones:** Complementada por `20260809_resolucion_estado_actual_proyecto_y_hoja_ruta_supabase.md` (Sec. X y XV).
* **Relaciones relevantes:** Conecta con `DATA-009` (Fuente de verdad) y `DATA-010` (Baseline PostgreSQL).

#### `DATA-009` · Una Sola Fuente Canónica de Verdad por Dominio
* **Estado:** VIGENTE
* **Decisión vigente:** Cada concepto o entidad del ERP debe tener una única autoridad canónica de verdad:
  - **Expediente / Trazabilidad:** Autoridad jurídica.
  - **TASK:** Unidad canónica de trabajo.
  - **Calendar:** Proyección temporal de TASK.
  - **CAA:** Centro operativo basado en TASK.
  - **ALERT:** Información / vigilancia / fecha.
  - **notification_tracking:** Proyección administrativa del estado de espera.
  - **scheduled_notifications:** Outbox de entrega (Telegram/email).
  - **Reporting:** Proyección / consumidor.
  - **Knowledge:** Consumidor de información estructurada.

  Se prohíbe crear entidades paralelas competidoras que representen el mismo estado sin una relación explícita de autoridad.
* **Origen / Fuente primaria:** `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` (Sec. IX y X).
* **Justificación documentada:** Impedir inconsistencias de estado y duplicidad de lógica de negocio entre servicios o entre frontend y backend.
* **Invariantes:**
  - Ninguna proyección puede convertirse en autoridad competidora de su fuente canónica.
  - Queda prohibido duplicar la misma regla de negocio en frontend y backend simultáneamente.
* **Evolución y modificaciones:** Reafirmada en `20260809_resolucion_estado_actual_proyecto_y_hoja_ruta_supabase.md` (Sec. V y VI).
* **Relaciones relevantes:** Conecta con `OPS-003` (TASK/CAA) y `ARCH-001` (Separación de capas).

#### `DATA-010` · Transición a PostgreSQL/Supabase mediante Baseline Limpio y Gates Obligatorios
* **Estado:** VIGENTE
* **Decisión vigente:** PostgreSQL V1 debe comenzar mediante un baseline canónico nuevo y limpio que represente el modelo vigente del ERP y no toda la historia técnica de SQLite. Las modificaciones posteriores deben continuar mediante migraciones versionadas.

  Los nombres indicados en la resolución (`001_baseline_schema.sql`, `002_master_data.sql`, `003_initial_configuration.sql`) tienen carácter orientativo.

  **Gates obligatorios previos a PostgreSQL:** la migración está normativamente condicionada al cumplimiento de:
  - **Gate 1:** CAA V1 (evolución de la Cola de Presentación basada en TASK).
  - **Gate 2:** `task_work_sessions` (cronometraje y sesiones de trabajo).
  - **Gate 3:** Comunicaciones V1 (modelo mínimo omnicanal).
  - **Gate 4:** Frontend sin SQL de negocio.
  - **Gate 5:** Persistencia centralizada en infraestructura.
  - **Gate 6:** Baseline PostgreSQL y dataset contractual E2E ficticio.
* **Origen / Fuente primaria:** `20260809_resolucion_estado_actual_proyecto_y_hoja_ruta_supabase.md` (Sec. XI, XII, XIII, XV).
* **Justificación documentada:** Garantizar que la migración a PostgreSQL/Supabase se realice sobre una base limpia, probada y libre de la deuda técnica histórica de SQLite.
* **Invariantes:**
  - La falta de desarrollo de todas las familias jurídicas NO bloquea la migración a PostgreSQL.
  - La migración de datos reales será selectiva y finalizará sin violaciones referenciales.
  - Supabase actúa como infraestructura; el backend del ERP mantiene la autoridad sobre la lógica de negocio.
  - Los Gates 1 a 6 son requisitos normativos obligatorios previos a habilitar PostgreSQL.
* **Evolución y modificaciones:** Desarrolla la estrategia de persistencia de `DATA-008`.
* **Relaciones relevantes:** Conecta con `DATA-008` (Centralización) y `ARCH-004` (Arquitectura híbrida).

---

### 3. FRONTEND Y COMPONENTES REUTILIZABLES (`UI`)

#### `UI-001` · Flet como Tecnología Oficial y Prohibición de SQL en Presentación
* **Estado:** VIGENTE
* **Decisión vigente:** Flet es la tecnología oficial de frontend del ERP. Queda expresamente prohibido ejecutar sentencias SQL (`SELECT`, `INSERT`, `UPDATE`, `DELETE`), sentencias DDL (`CREATE TABLE`, `ALTER TABLE`), comprobaciones de esquema (`PRAGMA`, `sqlite_master`), transacciones o conexiones a base de datos desde vistas (`frontend/views/`), componentes (`frontend/components/`) o layouts (`frontend/layouts/`).

  Toda vista o pantalla que necesite datos debe solicitarlo exclusivamente a un servicio backend.
* **Origen / Fuente primaria:** `004_frontend_flet.md` (Sec. 2 y 5) / `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` (Sec. III y IV).
* **Justificación documentada:** Preservar la separación estricta de capas, evitar que el cambio futuro de base de datos exija modificar la UI y prevenir fallos de layout o bloqueos de interfaz.
* **Invariantes:**
  - La apertura de una pantalla Flet nunca puede provocar una migración o modificación de esquema en la base de datos.
  - La UI es una herramienta funcional de trabajo, no un elemento decorativo.
* **Evolución y modificaciones:** Reafirmada por `017_componentes_sistema.md` y catalogada como Gate 4 obligatorio de migración a PostgreSQL.
* **Relaciones relevantes:** Conecta con `ARCH-001` (Separación de capas) y `UI-002` (Componentes reutilizables).

#### `UI-002` · Obligatoriedad del Catálogo Reutilizable `frontend/components/`
* **Estado:** VIGENTE
* **Decisión vigente:** Obligatoriedad de utilizar los componentes estandarizados de `frontend/components/` antes de crear nuevos bloques visuales manuales en vistas Flet.

  - **Orden de decisión obligatorio:** 1. Reutilizar componente existente -> 2. Extender existente si la necesidad es compatible -> 3. Crear nuevo componente reusable si el patrón se repetirá -> 4. Escribir UI manual solo si es un caso excepcional, local y no reutilizable.
  - **Regla de botones:** Los botones estándar deberán utilizar los componentes estándar existentes (`primary_button`, `secondary_button`, `danger_button`). Queda prohibido crear nuevos botones manuales con `ft.ElevatedButton`, `ft.OutlinedButton` o `ft.TextButton`, salvo dentro de un componente reutilizable o en casos justificados.
  - **Estándar documental oficial:** `document_file_card` (representación documental visible) + Checkbox (selección masiva) + Menú ⋮ (acciones individuales en `action_groups`) + `bulk_action_bar` (acciones sobre seleccionados) + `compact_pagination_bar` (navegación) + `document_viewer_modal` (visor).

  **Inventario oficial del sistema de componentes (`017_componentes_sistema.md`):**
  - **Uso obligatorio inmediato:** `app_button.py`, `app_text_field.py`, `app_dropdown.py`, `app_alert.py`, `app_empty_state.py`, `app_table.py`, `app_autocomplete.py`, `document_file_card.py`, `bulk_action_bar.py`, `document_viewer_modal.py`, `compact_pagination_bar.py`, `counter_chips.py`, `status_chip.py`.
  - **Uso recomendado / en expansión:** `app_action_row.py`, `app_badge.py`, `app_card.py`, `app_detail_section.py`, `app_dialog.py`, `app_filter_bar.py`, `app_loader.py`, `client_context_panel.py`, `config_section_card.py`, `economic_badge.py`, `expedient_status_badge.py`, `settings_sidebar.py`, `traceability_badge.py`.
  - **Pendientes de revisión:** `document_rule_row.py`, `listing/card_item.py`, `listing/pagination_bar.py`.
  - **Pendientes de creación prioritaria:** `panel_container.py`, `list_panel_header.py`, `confirm_dialog.py`, `form_section.py`, `section_toolbar.py`.
* **Origen / Fuente primaria:** `017_componentes_sistema.md` (Sec. 1, 2, 3, 4, 5, 6, 7, 16).
* **Justificación documentada:** Evitar la duplicación de bloques visuales, reducir la deuda técnica por componentes manuales y prevenir refactorizaciones masivas recurrentes.
* **Invariantes:**
  - Queda prohibido volver a crear tarjetas documentales o barras de acciones masivas manuales cuando exista el componente estándar.
  - Todo elemento documental visible debe representarse preferentemente mediante `document_file_card`.
  - No convertir componentes recomendados en obligatorios antes de su adopción oficial.
* **Evolución y modificaciones:** Desarrollada operativamente en `018_informe_tecnico_cuadro_gris.md` (sección no normativa) con pautas de selección y migración progresiva.
* **Relaciones relevantes:** Conecta con `UI-001` (Flet) y `UI-003` (Container expand).

#### `UI-003` · Prohibición de `ft.Container(expand=True)` como Separador Visual
* **Estado:** VIGENTE
* **Decisión vigente:** Queda prohibido utilizar `ft.Container(expand=True)` como separador visual o espaciador dentro de barras compactas, cabeceras, filas de acciones o toolbars.

  `expand=True` solo se permite cuando exista una razón estructural clara: áreas principales de contenido, columnas scrollables, contenedores raíz o paneles que ocupan el espacio restante. Para espaciar elementos en toolbars se debe usar `alignment=MainAxisAlignment.SPACE_BETWEEN`, `spacing` o `wrap=True`.
* **Origen / Fuente primaria:** `017_componentes_sistema.md` (Sec. 10).
* **Justificación documentada:** Corregir el origen técnico de los "cuadros grises" y colapsos de layout producidos al recalcular Flet alturas o anchos en contenedores expandidos sin restricción dentro de filas compactas.
* **Invariantes:**
  - No utilizar `ft.Container(expand=True)` para empujar botones, chips o menús en filas de toolbars compactas.
* **Evolución y modificaciones:** Reafirmada e ilustrada con patrones técnicos en `018_informe_tecnico_cuadro_gris.md` (sección no normativa).
* **Relaciones relevantes:** Conecta directamente con `UI-002` (Componentes del sistema).

---

## SECCIÓN III: INFORMACIÓN TÉCNICA NO NORMATIVA

*(Los contenidos integrados en esta sección poseen carácter estrictamente informativo, diagnóstico, de porcentaje de avance o de guía de refactorización visual. No constituyen decisiones normativas aprobadas ni alteran el cuerpo de reglas del ERP).*

### 1. ESTADO TÉCNICO Y MÉTRICAS DE MADUREZ POR DOMINIO (NO NORMATIVO)
*(Fuente: `20260809_resolucion_estado_actual_proyecto_y_hoja_ruta_supabase.md`, Sec. III y IV)*

- **Métricas globales del sistema (Agosto 2026):**
  - Avance funcional global del ERP: ~81 %.
  - Madurez técnica global del backend: ~82 %.
  - Motor de Expedientes: ~90 % (con cobertura jurídica configurada en ~35–40 %).
  - Preparación arquitectónica para PostgreSQL / Supabase: ~66 %.
  - Implementación efectiva en PostgreSQL: 0 %.
- **Madurez funcional por dominios:**
  - Clientes: ~82 %.
  - Sistema Documental (Box Watch, Bandeja, OCR): ~87 %.
  - Económico (Hojas de encargo, cobros, conciliación): ~83 %.
  - Calendar: 100 % (funcionalmente cerrado como proyección).
  - TASK: ~90 % (pendiente estructura `task_work_sessions`).
  - Notificaciones / DEHú: ~89 %.
  - Plataforma Email: ~88 %.
  - Reporting: ~35 % (prioridad posterior a PostgreSQL).
  - Knowledge: 0 % (desarrollo previsto tras estabilización central).

---

### 2. DIAGNÓSTICO DE PANTALLAS UI Y PATRONES DE REFACTORIZACIÓN (NO NORMATIVO)
*(Fuentes: `017_componentes_sistema.md`, Sec. 4.1 y 11; `018_informe_tecnico_cuadro_gris.md`, Sec. 2 a 10)*

- **Causas identificadas del "cuadro gris" / layout roto en Flet:**
  1. Uso de `selected=True` sin `selectable=True` en `document_file_card` (provoca fondo azul/gris de resaltado en lugar del modo selección estándar).
  2. Creación manual de tarjetas documentales envolventes con `ft.Container(bgcolor="#F8FAFC")`.
  3. Uso de `ft.Container(expand=True)` como separador dentro de filas o toolbars compactas.
  4. Aplicación de `scroll=ft.ScrollMode.AUTO` en la columna raíz de la página en lugar de aplicarlo exclusivamente a la columna interna de tarjetas/cards.
  5. Despliegue de múltiples botones visibles por fila en lugar de agrupar las acciones individuales en el menú ⋮ (`action_groups`).
- **Prioridades de migración progresiva a componentes estándar:**
  - Migración de botones locales a `app_button.py`: `companies_view.py`, `company_detail_view.py`, `reporting_view.py`.
  - Componentes pendientes de revisión/limpieza: `document_rule_row.py` (mover a legacy o integrar), `listing/card_item.py` (sustituir por `document_file_card`), `listing/pagination_bar.py` (priorizar `compact_pagination_bar`).

---

### 3. DIVERGENCIA DOCUMENTAL–OPERATIVA (NO NORMATIVO)

Ninguna divergencia documental-operativa identificada en las decisiones de Arquitectura, Datos y Frontend UI del corpus actualmente consolidado. Las resoluciones históricas sobre modelos de datos (`005`, `006`, `007`) y frontend (`004`, `017`) concuerdan plenamente con las normas de gobierno de código de agosto de 2026.

---

> ESTADO: 02_ARQUITECTURA_ERP_DATOS — APROBADO POR DIRECCIÓN
