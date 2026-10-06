# RESOLUCIÓN DE GOBIERNO DE CÓDIGO Y PREVENCIÓN DE DEUDA TÉCNICA

**Proyecto:** Quesada Abogados ERP
**Fecha:** 9 de agosto de 2026
**Estado de referencia:** rama `develop`
**Naturaleza:** Resolución técnica vinculante para el desarrollo futuro
**Ámbito:** Arquitectura, persistencia, frontend, backend, migraciones, tests, Git y control de deuda técnica

---

# I. OBJETO

La presente resolución establece las reglas técnicas obligatorias que deberán respetarse en todo desarrollo futuro de Quesada Abogados ERP.

Su finalidad es impedir la incorporación de nuevas malas prácticas o deuda técnica semejante a la detectada durante la auditoría global del proyecto.

Esta resolución será aplicable a:

- nuevas funcionalidades;
- ampliaciones de módulos existentes;
- nuevas familias de expedientes;
- CAA;
- Calendar y TASK;
- Comunicaciones;
- Económico;
- Documental;
- Reporting;
- Knowledge;
- PostgreSQL / Supabase;
- refactorizaciones;
- migraciones;
- automatizaciones;
- scripts productivos.

El principio rector será:

> Toda funcionalidad nueva deberá mejorar o mantener la arquitectura existente. Ninguna funcionalidad nueva podrá justificar la introducción deliberada de deuda técnica ya identificada por la auditoría.

---

# II. PRINCIPIO DE SEPARACIÓN DE RESPONSABILIDADES

Se establece como regla obligatoria la separación:

`Frontend`
→ `Application / Service`
→ `Dominio`
→ `Persistencia`

El frontend será responsable exclusivamente de:

- representación visual;
- captura de datos;
- interacción con el usuario;
- navegación;
- composición de componentes;
- presentación de errores y resultados.

El frontend NO será responsable de:

- persistencia;
- SQL;
- reglas de negocio;
- transacciones;
- evolución de schema;
- conciliaciones;
- derivaciones;
- estados administrativos;
- cálculos jurídicos;
- cálculos fiscales;
- reglas documentales.

---

# III. PROHIBICIÓN DE SQL EN FLET

Queda expresamente prohibido introducir nuevo SQL directo en:

- `frontend/views/`;
- `frontend/components/`;
- `frontend/layouts/`;
- cualquier otro código perteneciente a la capa de presentación.

Por tanto, queda prohibido desde Flet utilizar directamente:

- `sqlite3.connect`;
- `psycopg.connect`;
- clientes Supabase para persistencia de negocio;
- `SELECT`;
- `INSERT`;
- `UPDATE`;
- `DELETE`;
- `CREATE TABLE`;
- `ALTER TABLE`;
- `PRAGMA`;
- `sqlite_master`;
- consultas de agregación económica;
- modificaciones directas del estado de entidades.

Una vista que necesite información deberá solicitarla a un servicio backend.

Ejemplo correcto:

`economic_view`
→ `payment_reconciliation_service`
→ persistencia.

Ejemplo prohibido:

`economic_view`
→ `UPDATE eco_cobros ...`

El cambio futuro a PostgreSQL no deberá exigir modificar las vistas para cambiar consultas SQL.

---

# IV. PROHIBICIÓN DE EVOLUCIÓN DE SCHEMA DESDE FRONTEND

Queda absolutamente prohibido ejecutar desde frontend:

- `CREATE TABLE`;
- `ALTER TABLE`;
- creación de índices;
- comprobaciones mediante `PRAGMA table_info`;
- inspección de `sqlite_master`;
- cualquier modificación estructural de la base de datos.

La apertura de una pantalla nunca podrá provocar una migración de schema.

El schema deberá evolucionar exclusivamente mediante migraciones controladas.

---

# V. MIGRACIONES COMO ÚNICA AUTORIDAD DEL SCHEMA

A partir de la futura estabilización pre-PostgreSQL se establece el objetivo de que:

`schema`
→ sea gobernado por migraciones versionadas.

Los servicios productivos no deberán depender de ejecutar:

- `CREATE TABLE IF NOT EXISTS`;
- `ALTER TABLE`;
- reparaciones estructurales;
- creación dinámica de columnas.

Las funciones `ensure_schema()` existentes podrán mantenerse temporalmente por compatibilidad durante la transición, pero no deberán proliferar.

No se crearán nuevas funciones `ensure_schema()` salvo necesidad excepcional, documentada y aprobada.

Para PostgreSQL productivo:

> Ningún servicio de negocio deberá alterar el schema en runtime.

---

# VI. CENTRALIZACIÓN DE LA PERSISTENCIA

Queda prohibido seguir expandiendo el patrón:

`DEFAULT_DB_PATH = Path("database/quesada.db")`

por nuevos servicios.

También queda prohibido introducir nuevos:

`sqlite3.connect(...)`

dispersos por el dominio.

Todo nuevo desarrollo deberá utilizar la infraestructura común de persistencia definida por el proyecto.

La evolución objetivo será:

`database.connection`
→ configuración central
→ transacciones
→ adaptador SQLite / PostgreSQL
→ base de datos.

El conocimiento de la ubicación física de la base de datos deberá quedar concentrado en infraestructura.

---

# VII. PROHIBICIÓN DE ACOPLAR EL DOMINIO A SQLITE

No deberá introducirse nueva lógica de negocio dependiente directamente de características particulares de SQLite.

Deberán evitarse nuevos usos directos de:

- `PRAGMA`;
- `sqlite_master`;
- `INSERT OR IGNORE`;
- `lastrowid`;
- `BEGIN IMMEDIATE`;
- funciones SQL exclusivas de SQLite;
- rutas hardcodeadas de `quesada.db`.

Cuando una funcionalidad necesite una operación de este tipo deberá encapsularse en infraestructura o diseñarse mediante un contrato portable.

Ejemplos:

`table_exists()`

`column_exists()`

`insert_returning_id()`

`transaction()`

`upsert()`

La implementación podrá ser distinta para SQLite y PostgreSQL.

---

# VIII. REGLAS DE TRANSACCIONES

Toda operación que modifique varias entidades relacionadas deberá ejecutarse de forma atómica.

Especial atención tendrán:

- facturación;
- conciliación;
- rectificativas;
- numeración;
- autorizaciones;
- derivaciones;
- trazabilidad;
- presentación;
- CAA;
- TASK;
- suplidos;
- transferencias.

No se utilizarán locks específicos de SQLite como sustituto de una regla de dominio.

La migración a PostgreSQL deberá traducir la intención transaccional mediante:

- transacciones;
- constraints;
- `SELECT ... FOR UPDATE` cuando proceda;
- `ON CONFLICT`;
- actualizaciones atómicas;
- idempotencia;
- índices UNIQUE.

---

# IX. UNA SOLA FUENTE DE VERDAD

Cada concepto del ERP deberá tener una única fuente canónica de verdad.

Se prohíbe crear entidades paralelas que representen el mismo estado sin una relación explícita de autoridad.

Principios vigentes:

- Expediente / Trazabilidad = autoridad jurídica.
- Calendar = proyección temporal.
- TASK = trabajo.
- ALERT = información / vigilancia / fecha.
- `notification_tracking` = proyección administrativa.
- `scheduled_notifications` = outbox de entrega.
- CAA = centro operativo basado en TASK.
- Reporting = proyección.
- Knowledge = consumidor de información estructurada.

Cuando una proyección pueda reconstruirse desde la fuente canónica, no deberá convertirse en autoridad competidora.

---

# X. PROHIBICIÓN DE DUPLICACIÓN DE LÓGICA

No deberá implementarse una misma regla de negocio simultáneamente en:

- frontend y backend;
- dos servicios independientes;
- servicio nuevo y código legacy;
- SQLite y PostgreSQL mediante ramas divergentes de dominio.

Si una lógica ya existe en backend, el frontend deberá consumirla.

Ejemplo detectado y prohibido para el futuro:

`economic_view.py`
manteniendo una conciliación SQL propia mientras existe
`payment_reconciliation_service.py`.

Cuando una funcionalidad se migre a un servicio backend deberá eliminarse posteriormente el código antiguo una vez validado.

---

# XI. PROHIBICIÓN DE CÓDIGO MUERTO

No se conservará código legacy inaccesible después de:

- `return`;
- `raise`;
- redefiniciones posteriores;
- funciones sustituidas.

Cuando una implementación nueva reemplace a otra:

1. se validará mediante tests;
2. se comprobarán call sites;
3. se retirará la implementación antigua;
4. se realizará un commit atómico.

No se dejará código antiguo “por si acaso” dentro de módulos productivos.

Git será el sistema de conservación del historial.

---

# XII. PROHIBICIÓN DE REDEFINICIONES ACCIDENTALES

Queda prohibido mantener múltiples funciones top-level con el mismo nombre dentro de un mismo módulo.

La auditoría detectó este patrón en `box_watch_service.py`.

Toda redefinición deberá considerarse deuda técnica.

Antes de añadir una función nueva deberá buscarse si ya existe una implementación equivalente.

---

# XIII. SERVICIOS DE TAMAÑO EXCESIVO

No se fija un número máximo rígido de líneas por fichero.

Sin embargo, cuando un servicio acumule múltiples responsabilidades claramente diferenciadas deberá evaluarse su división.

Ejemplos identificados:

- `economic_service.py`;
- `expedient_traceability_service.py`;
- `box_watch_service.py`;
- `document_inbox_service.py`.

La división deberá realizarse de forma progresiva y basada en contratos funcionales.

Queda prohibida la reescritura completa de un servicio maduro salvo justificación excepcional.

---

# XIV. REUTILIZACIÓN DE SERVICIOS Y COMPONENTES

Antes de crear:

- un servicio;
- una vista;
- un componente;
- una función de persistencia;
- un mapper;
- una utilidad;

deberá comprobarse si ya existe una capacidad equivalente.

El proyecto deberá favorecer:

- servicios reutilizables;
- componentes Flet reutilizables;
- bloques de mapper reutilizables;
- catálogos configurables;
- reglas declarativas.

Se evitará copiar y pegar lógica existente.

---

# XV. LÓGICA JURÍDICA CONFIGURABLE

Las nuevas familias y procedimientos deberán desarrollarse prioritariamente mediante:

- familias;
- tipos;
- subtipos;
- catálogos;
- requisitos;
- grupos AND/OR;
- formularios;
- mappers;
- transiciones;
- reglas de derivación;
- configuración.

Se evitará introducir reglas jurídicas específicas hardcodeadas en frontend o servicios generales cuando puedan expresarse como configuración.

El motor de Expedientes deberá mantenerse genérico.

---

# XVI. CONTROL HUMANO

Las automatizaciones no deberán convertir propuestas o detecciones automáticas en hechos jurídicos definitivos cuando sea necesaria revisión humana.

Ejemplos:

- clasificación DEHú;
- derivaciones;
- OCR;
- datos extraídos;
- cambios administrativos;
- comunicaciones;
- documentos.

La automatización deberá diferenciar:

`detectado`
→ `propuesto`
→ `revisado`
→ `confirmado`

cuando el riesgo funcional así lo requiera.

---

# XVII. REGLA ECONÓMICA DE FACTURACIÓN

Se establece expresamente:

`FACTURABLE ≠ FACTURADO`

Marcar un cobro como facturable significa únicamente que puede ser incluido en una factura.

La creación de una factura requerirá acción expresa del usuario salvo que en el futuro se apruebe formalmente otra política.

No se introducirá automatización que facture por inferencia implícita.

---

# XVIII. CAA Y TASK

CAA será la evolución de la actual Cola de Presentación.

Se establece:

`TASK = unidad canónica de trabajo`

`CAA = interfaz/centro de actividades administrativas`

No deberán crearse dos unidades de trabajo independientes para una misma actividad.

Calendar y CAA deberán operar sobre la misma TASK.

Los motores especializados —Mercurio, citas, trámites consulares, etc.— serán ejecutores de la actividad y no fuentes alternativas de estado.

---

# XIX. CALENDAR

Calendar seguirá siendo una proyección.

Queda prohibido convertir Calendar en fuente canónica de:

- estado de expediente;
- estado administrativo;
- presentación;
- notificación;
- actividad.

Las acciones realizadas desde Calendar deberán modificar el dominio correspondiente a través de application services.

---

# XX. REPORTING

Reporting será únicamente consumidor/agregador de los dominios.

No se crearán estados de negocio nuevos dentro de Reporting.

Las métricas deberán derivarse de datos canónicos.

Reporting operativo avanzado deberá desarrollarse después de `task_work_sessions`.

---

# XXI. KNOWLEDGE

Knowledge será consumidor de la información del ERP.

Nunca sustituirá:

- Expedientes;
- Trazabilidad;
- Documental;
- Clientes;
- Base de datos.

NotebookLM o cualquier motor de IA deberá considerarse una capa de análisis.

No se diseñará prematuramente infraestructura RAG/vectorial sin necesidad funcional real.

---

# XXII. SECRETOS Y CREDENCIALES

Queda prohibido versionar:

- `.env`;
- `.env.local`;
- tokens;
- passwords;
- archivos OAuth;
- client secrets;
- certificados;
- credenciales API.

Los secretos deberán proporcionarse mediante:

- variables de entorno;
- secret storage;
- configuración local ignorada por Git.

Nunca deberán guardarse secretos en PostgreSQL como sustituto de un gestor de secretos.

---

# XXIII. RUTAS LOCALES

No se utilizarán rutas absolutas personales como identidad canónica de un recurso.

Ejemplo prohibido como dato lógico:

`C:\Users\Nacho\Box\...`

Deberán utilizarse:

- rutas relativas;
- identificadores externos;
- raíces configurables;
- referencias lógicas.

La ruta física será una propiedad del agente local.

---

# XXIV. CLOUD Y AGENTES LOCALES

El futuro sistema distinguirá:

## Cloud-capable

- PostgreSQL;
- scheduled notifications;
- Telegram;
- email sync;
- procesamiento email;
- procesamiento DEHú no dependiente de certificado.

## Local-required inicialmente

- Box Drive;
- Mercurio;
- certificado digital;
- OCR local;
- Word/PDF;
- filesystem.

No se introducirá dependencia innecesaria del escritorio en procesos que puedan ejecutarse centralmente.

Tampoco se intentará cloudificar prematuramente automatizaciones dependientes del entorno local.

---

# XXV. TESTS COMO CONTRATO

Toda modificación estructural deberá ir acompañada de pruebas adecuadas.

Especialmente:

- migraciones;
- transacciones;
- estados;
- derivaciones;
- conciliación;
- facturación;
- CAA;
- TASK;
- Calendar;
- Notificaciones;
- PostgreSQL.

Una refactorización no se considerará finalizada hasta demostrar que mantiene el comportamiento contractual.

Los tests deberán comprobar comportamiento, no detalles internos innecesarios.

---

# XXVI. CLEAN INSTALL

Todo nuevo dominio transversal deberá poder ser instalado sobre una base limpia.

Se evitará depender de:

- tablas preexistentes no documentadas;
- columnas creadas por una pantalla;
- estado accidental de la base de desarrollo.

PostgreSQL deberá disponer de un baseline reproducible.

---

# XXVII. COMPATIBILIDAD POSTGRESQL

Mientras continúe SQLite, todo nuevo desarrollo deberá evitar aumentar innecesariamente la deuda de portabilidad.

Antes de utilizar una característica SQLite-specific deberá preguntarse:

1. ¿es necesaria?
2. ¿puede encapsularse?
3. ¿cómo se implementará en PostgreSQL?

No se exigirá compatibilidad perfecta inmediata con PostgreSQL, pero queda prohibido aumentar deliberadamente el acoplamiento estructural.

---

# XXVIII. QA-DEV-001

Se ratifica como metodología obligatoria:

`grep`
→ `sed / inspección`
→ `patch`
→ `compile`
→ `test funcional`
→ `git diff`
→ `commit atómico`

No se sustituirán ficheros completos salvo:

- fichero nuevo;
- fichero pequeño;
- justificación técnica clara;
- autorización expresa.

Las modificaciones deberán ser quirúrgicas y revisables.

---

# XXIX. GIT

Se mantendrán las siguientes reglas:

- `main` = estable;
- `develop` = integración;
- `feature/*` = desarrollo;
- `fix/*` = correcciones;
- `hotfix/*` = urgencias.

No se trabajará directamente en `main`.

No se utilizará:

`git add .`

cuando existan archivos locales o sensibles.

Se añadirán explícitamente los archivos del commit.

`scripts/tools/` permanecerá fuera de commits salvo decisión expresa.

`.env.local` nunca será añadido.

---

# XXX. COMMITS

Cada commit deberá ser:

- atómico;
- comprensible;
- reversible;
- limitado a una finalidad principal.

Cada commit deberá poder explicarse mediante:

1. qué se ha hecho;
2. por qué se ha hecho;
3. qué problema resuelve;
4. qué queda pendiente.

No deberán mezclarse:

- refactor;
- feature;
- migración;
- limpieza;
- cambios UI;

sin una justificación funcional clara.

---

# XXXI. REGLA DE NO REGRESIÓN ARQUITECTÓNICA

Una nueva funcionalidad no será aceptable si:

- funciona;
- pasa tests;

pero introduce una mala práctica expresamente prohibida por esta resolución.

La corrección funcional no justifica regresión arquitectónica.

Ejemplo:

Una nueva función de CAA que funcione correctamente pero ejecute SQL desde Flet será considerada incorrecta.

---

# XXXII. REVISIÓN OBLIGATORIA ANTES DE COMMIT

Antes de cada commit deberá comprobarse, cuando corresponda:

- ausencia de SQL nuevo en frontend;
- ausencia de secretos;
- ausencia de rutas personales;
- ausencia de nuevos `sqlite3.connect` injustificados;
- ausencia de DDL runtime;
- ausencia de funciones duplicadas;
- ausencia de código muerto;
- compilación;
- tests afectados;
- `git diff --check`;
- `git status`.

---

# XXXIII. DEUDA TÉCNICA EXISTENTE

La presente resolución no obliga a corregir inmediatamente toda deuda histórica.

La estrategia será:

`NO AÑADIR DEUDA NUEVA`
+
`CORREGIR DEUDA EXISTENTE CUANDO SE TOQUE EL ÁREA`
+
`REALIZAR ESTABILIZACIÓN ESPECÍFICA PRE-POSTGRESQL`

Por tanto no se realizarán refactorizaciones indiscriminadas que pongan en riesgo módulos maduros.

Se aplicará el principio:

> Boy Scout Rule controlada: si se modifica un área con deuda conocida, deberá intentarse dejarla igual o ligeramente mejor, siempre que no amplíe de forma desproporcionada el alcance del cambio.

---

# XXXIV. EXCEPCIONES

Cualquier excepción a estas reglas deberá:

1. ser técnicamente necesaria;
2. documentarse;
3. indicar por qué no existe alternativa razonable;
4. definir cómo se eliminará posteriormente;
5. contar con aprobación expresa dentro del proceso de desarrollo.

Una solución temporal no deberá convertirse silenciosamente en arquitectura permanente.

---

# XXXV. RESOLUCIÓN FINAL

Se establece como norma obligatoria para todo desarrollo futuro de Quesada Abogados ERP:

1. Flet no contendrá SQL ni lógica de persistencia.
2. El schema no evolucionará desde frontend.
3. Las nuevas funcionalidades no introducirán conexiones SQLite dispersas.
4. Persistencia deberá centralizarse progresivamente.
5. Cada dominio tendrá una fuente canónica de verdad.
6. No se duplicará lógica entre frontend y backend.
7. No se mantendrá código muerto ni redefiniciones accidentales.
8. Las reglas jurídicas deberán ser configurables cuando sea posible.
9. Las automatizaciones conservarán revisión humana cuando proceda.
10. Calendar seguirá siendo proyección.
11. TASK será la unidad de trabajo y CAA su centro administrativo.
12. Reporting y Knowledge serán consumidores, no autoridades.
13. Los secretos nunca se versionarán.
14. Las rutas locales no serán identidades canónicas.
15. PostgreSQL deberá introducirse mediante una frontera común de persistencia.
16. Los cambios estructurales deberán disponer de tests.
17. QA-DEV-001 seguirá siendo metodología obligatoria.
18. Los commits serán atómicos y explícitos.
19. No se utilizará `git add .` como práctica ordinaria.
20. Ninguna funcionalidad se considerará correctamente implementada si introduce una regresión arquitectónica conocida.

**Estado de la resolución:** APROBADA COMO NORMA DE GOBIERNO DE CÓDIGO DEL PROYECTO.