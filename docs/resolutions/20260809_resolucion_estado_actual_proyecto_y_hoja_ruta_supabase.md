# RESOLUCIÓN SOBRE EL ESTADO ACTUAL DEL PROYECTO Y HOJA DE RUTA HACIA POSTGRESQL / SUPABASE

**Proyecto:** Quesada Abogados ERP
**Fecha:** 9 de agosto de 2026
**Estado de referencia:** rama `develop`
**Naturaleza:** Resolución técnica y funcional de arquitectura
**Ámbito:** Estado global del ERP, prioridades de desarrollo y momento de migración a PostgreSQL / Supabase

---

# I. OBJETO DE LA RESOLUCIÓN

La presente resolución tiene por objeto fijar formalmente el estado actual del proyecto Quesada Abogados ERP después de la auditoría global realizada sobre:

- arquitectura general;
- persistencia;
- clientes;
- expedientes;
- sistema documental;
- módulo económico;
- operaciones;
- Calendar y TASK;
- notificaciones y DEHú;
- comunicaciones;
- Reporting;
- Knowledge;
- infraestructura;
- seguridad;
- integraciones;
- preparación para PostgreSQL / Supabase.

La resolución determina asimismo qué desarrollos deben realizarse antes de iniciar la migración a PostgreSQL y qué desarrollos quedan expresamente fuera de dicha ruta crítica.

---

# II. CONCLUSIÓN GENERAL

Se declara que Quesada Abogados ERP ha superado la fase de prototipo y dispone actualmente de un núcleo funcional y arquitectónico suficientemente desarrollado para comenzar a preparar su transición desde SQLite hacia una arquitectura centralizada basada en PostgreSQL.

No obstante, se considera prematuro iniciar inmediatamente la migración a PostgreSQL / Supabase.

Antes deberán estabilizarse determinados dominios transversales y eliminarse los principales acoplamientos técnicos con SQLite.

Del mismo modo, se declara expresamente que NO será necesario finalizar todas las familias jurídicas, Reporting, Knowledge ni todas las futuras integraciones antes de realizar dicha migración.

---

# III. VALORACIÓN GLOBAL

A fecha de esta resolución se adoptan las siguientes estimaciones:

| Dimensión | Estado estimado |
|---|---:|
| Avance funcional global del ERP | ≈ 81 % |
| Madurez técnica global | ≈ 82 % |
| Motor de Expedientes | ≈ 90 % |
| Cobertura jurídica configurada | ≈ 35–40 % |
| Preparación arquitectónica para PostgreSQL / Supabase | ≈ 66 % |
| Implementación PostgreSQL efectiva | 0 % |

Estos porcentajes deberán interpretarse como indicadores de madurez y no como estimaciones lineales del tiempo restante.

La diferencia entre la elevada madurez del motor de Expedientes y la menor cobertura jurídica se considera deliberada y correcta: el sistema dispone ya de motores reutilizables sobre los que pueden incorporarse progresivamente nuevos procedimientos.

---

# IV. ESTADO POR DOMINIOS

## 1. Clientes

El módulo de Clientes se considera funcionalmente maduro.

Dispone, entre otros elementos, de:

- identidad;
- datos de contacto;
- situación administrativa;
- autorización actual;
- histórico de autorizaciones;
- trayectoria administrativa;
- relaciones familiares;
- relaciones con empresas;
- participación múltiple en expedientes;
- integración con expedientes y trazabilidad.

Madurez estimada:

**≈ 82 %**

La principal deuda no es funcional sino técnica: existen accesos SQL directos desde determinadas vistas Flet y mutaciones de schema que deberán trasladarse al backend/migraciones antes de PostgreSQL.

---

## 2. Expedientes

El motor de Expedientes se considera uno de los componentes más maduros del proyecto.

Actualmente dispone de:

- familias;
- tipos;
- subtipos;
- clientes y roles;
- datos específicos;
- requisitos documentales;
- formularios;
- trazabilidad;
- snapshots;
- trayectoria;
- relaciones entre expedientes;
- reglas de derivación;
- transiciones de autorizaciones;
- integración con Calendar;
- integración con Notificaciones;
- presentación asistida;
- continuidad entre procedimientos.

Madurez estimada del motor:

**≈ 90 %**

Cobertura jurídica configurada:

**≈ 35–40 %**

Se establece expresamente que la falta de desarrollo profundo de todas las familias NO constituye impedimento para migrar a PostgreSQL.

Las nuevas familias deberán seguir desarrollándose mediante configuración, catálogos, requisitos, transiciones y reglas, evitando introducir lógica jurídica hardcodeada.

---

## 3. Sistema documental

El sistema documental se considera altamente desarrollado.

Incluye:

- Box Watch;
- inventario documental;
- Bandeja Documental;
- SHA256 y deduplicación;
- nomenclaturas;
- requisitos documentales agrupados;
- reglas AND/OR;
- roles documentales;
- estados semánticos;
- OCR;
- Document Intelligence;
- formularios;
- mappers;
- generación documental;
- vinculación documental con expedientes.

Madurez funcional estimada:

**≈ 87 %**

Se registra como deuda relevante la existencia de múltiples definiciones históricas superpuestas en `box_watch_service.py`.

Su futura consolidación deberá realizarse incrementalmente y con tests, sin reescritura completa.

Las referencias reales a Box, inventarios y metadatos documentales se consideran datos sensibles y no regenerables y deberán preservarse especialmente durante cualquier migración.

---

## 4. Económico

El módulo económico se considera funcionalmente avanzado.

Incluye:

- hojas de encargo;
- cobros;
- facturas;
- rectificativas;
- conciliación bancaria;
- Cashmatic;
- conciliación manual;
- gastos;
- suplidos;
- transferencias internas;
- fiscal;
- laboral;
- nóminas;
- exportaciones;
- reporting económico.

Madurez funcional estimada:

**≈ 83 %**

Se registra una deuda técnica relevante en `economic_view.py`, que todavía contiene SQL directo y lógica económica duplicada respecto del backend.

Se establece asimismo la siguiente regla funcional:

**FACTURABLE no equivale a FACTURAR.**

Un cobro marcado como facturable deberá quedar disponible para facturación, pero la creación de la factura deberá depender de una acción expresa del usuario.

La actual creación automática de factura desde `create_cobro()` y `update_cobro()` deberá ser corregida en una fase de estabilización.

---

## 5. Calendar

Calendar se declara funcionalmente cerrado para la versión actual.

Madurez:

**100 %**

Se mantiene el principio arquitectónico:

**Calendar es una proyección temporal y no una fuente de verdad del dominio.**

TASK representa trabajo.

ALERT representa información, fecha o vigilancia.

Las notificaciones programadas utilizan `scheduled_notifications`.

---

## 6. TASK

TASK dispone actualmente de:

- creación;
- modificación;
- inicio;
- finalización;
- cancelación;
- reapertura;
- archivo;
- prioridad;
- responsable;
- fechas;
- origen;
- source_key e idempotencia;
- integración con Calendar;
- notificaciones.

Madurez estimada:

**≈ 90 %**

Se considera pendiente una ampliación estructural:

`task_work_sessions`

que deberá permitir registrar:

- inicio;
- pausa;
- reanudación;
- finalización;
- duración efectiva;
- trabajador;
- origen de la sesión.

Esta capacidad será posteriormente la base del Reporting operativo.

---

# V. CENTRO DE ACTIVIDADES ADMINISTRATIVAS — CAA

Se resuelve que el Centro de Actividades Administrativas, CAA, será la evolución funcional de la actual Cola de Presentación.

No deberá mantenerse permanentemente una arquitectura basada en:

`Cola de Presentación + CAA + TASK`

como tres unidades de trabajo diferentes.

El modelo objetivo será:

`TASK = unidad canónica de trabajo`

`CAA = centro operativo de las TASK administrativas`

La actual Cola de Presentación será absorbida progresivamente por CAA.

La primera actividad administrativa que deberá soportar CAA será:

`PRESENTAR_EXPEDIENTE`

Posteriormente podrán incorporarse, entre otras:

- solicitar cita;
- solicitar documento;
- aportar documentación;
- contestar requerimiento;
- toma de huellas;
- recogida TIE;
- cita de jura;
- trámites consulares;
- solicitudes administrativas;
- otras actuaciones de ejecución.

Calendar y CAA deberán representar distintas interfaces sobre la misma TASK.

La finalización jurídica de una tarea de presentación deberá producirse cuando Trazabilidad confirme el hecho administrativo correspondiente, principalmente mediante el justificante de presentación y el cambio del expediente a PRESENTADO.

---

# VI. NOTIFICACIONES Y DEHÚ

El sistema de Notificaciones / DEHú se considera altamente desarrollado.

Madurez estimada:

**≈ 89 %**

Se mantiene la siguiente separación:

`notification_tracking`
= proyección operativa del estado de espera administrativa.

`DEHú`
= fuente de comunicaciones/notificaciones oficiales.

`Trazabilidad`
= autoridad sobre el significado jurídico del documento.

`Calendar`
= proyección temporal.

`scheduled_notifications`
= outbox para entrega futura por canales como Telegram.

El sistema ya permite representar fases como:

- presentado sin número;
- espera de admisión;
- espera de resolución;
- cierre favorable;
- cierre denegatorio.

DEHú no se considera un bloqueo estructural para PostgreSQL.

---

# VII. COMUNICACIONES

La plataforma de email se considera madura.

Actualmente existen:

- Gmail API;
- IONOS IMAP;
- normalización;
- parser RFC822;
- sincronización;
- deduplicación;
- procesamiento;
- vinculación con expedientes;
- procesamiento DEHú;
- almacenamiento de resultados de procesamiento.

Madurez de plataforma email:

**≈ 88 %**

Sin embargo, todavía no existe un dominio omnicanal completo para comunicaciones Cliente ↔ Despacho.

Antes de PostgreSQL deberá definirse únicamente el modelo mínimo común:

- communication_threads;
- communication_messages o communication_events;
- participantes;
- canal;
- cliente;
- expediente;
- identificadores externos de proveedor.

No será necesario implementar antes de PostgreSQL:

- WhatsApp completo;
- telefonía;
- UI final de comunicaciones;
- campañas;
- todas las integraciones futuras.

---

# VIII. REPORTING

Reporting dispone actualmente de una interfaz funcional y reporting principalmente documental/Box.

Los servicios especializados de Reporting para:

- Clientes;
- Expedientes;
- Económico;

se encuentran todavía prácticamente sin desarrollar.

Madurez aproximada:

**≈ 35 %**

Reporting avanzado queda expresamente fuera de la ruta crítica previa a PostgreSQL.

Su desarrollo deberá realizarse preferentemente después de:

- CAA;
- task_work_sessions;
- PostgreSQL.

De esta manera Reporting podrá explotar datos operativos reales y una base centralizada.

---

# IX. KNOWLEDGE

Se declara que el módulo Knowledge todavía no dispone de implementación software efectiva.

Madurez software:

**0 %**

Knowledge no constituye un retraso ni un bloqueo para PostgreSQL.

Su primera versión deberá desarrollarse después de estabilizar la infraestructura central.

La estrategia inicial recomendada será:

`Expediente cerrado`
→ `Knowledge Export`
→ `texto estructurado`
→ `fuente para NotebookLM`

NotebookLM será consumidor de conocimiento, nunca fuente de verdad del ERP.

No deberá diseñarse prematuramente un sistema propio de RAG, vectores o embeddings mientras no exista una necesidad real.

---

# X. PERSISTENCIA ACTUAL

La persistencia constituye actualmente la principal deuda arquitectónica transversal.

El proyecto contiene:

- servicios con `sqlite3.connect()` directo;
- servicios con `DEFAULT_DB_PATH`;
- servicios que utilizan `database.connection`;
- PRAGMA;
- `sqlite_master`;
- `lastrowid`;
- `BEGIN IMMEDIATE`;
- CREATE TABLE y ALTER TABLE ejecutados desde servicios;
- SQL directo en algunas vistas Flet.

Existe actualmente `database.connection`, pero todavía constituye únicamente una puerta común hacia SQLite y no una abstracción portable.

El proyecto contiene asimismo un bootstrap histórico compuesto por:

- `schema.sql`;
- múltiples archivos `*_schema.sql`;
- migraciones;
- funciones `ensure_schema`;
- alteraciones runtime.

Por ello no se considera conveniente trasladar literalmente toda la historia de migraciones SQLite a PostgreSQL.

---

# XI. BASELINE POSTGRESQL

La futura PostgreSQL V1 deberá comenzar mediante un baseline canónico nuevo.

Orientativamente:

- `001_baseline_schema.sql`
- `002_master_data.sql`
- `003_initial_configuration.sql`

Las posteriores modificaciones deberán continuar mediante migraciones versionadas.

El baseline deberá representar el modelo vigente y válido del ERP, no toda la historia técnica que condujo hasta él.

Los servicios productivos no deberán crear o alterar tablas dinámicamente.

---

# XII. ESTRATEGIA DE MIGRACIÓN DE DATOS

No deberá realizarse:

`dump completo de quesada.db → PostgreSQL`

La estrategia será selectiva:

`SQLite actual`
→ `clasificación`
→ `modelo canónico`
→ `validación`
→ `PostgreSQL limpio`

No deberán migrarse automáticamente:

- tablas backup;
- tablas legacy sustituidas;
- `task_notifications` si continúa obsoleta;
- artefactos históricos no canónicos;
- datos ficticios que no aporten valor.

Deberán preservarse expresamente:

- referencias reales de Box;
- inventarios;
- metadatos documentales;
- rutas lógicas;
- referencias no regenerables.

El dataset destinado a PostgreSQL deberá finalizar sin violaciones referenciales.

---

# XIII. GATES OBLIGATORIOS PREVIOS A POSTGRESQL

Se establecen los siguientes gates:

## GATE 1 — CAA V1

Desarrollar CAA como evolución de la Cola de Presentación basada en TASK.

## GATE 2 — TASK WORK SESSIONS

Crear el modelo de sesiones de trabajo y cronometraje efectivo.

## GATE 3 — COMUNICACIONES V1

Definir el modelo mínimo omnicanal de comunicaciones.

## GATE 4 — FRONTEND SIN SQL DE NEGOCIO

Eliminar SQL directo de las vistas Flet, especialmente:

- `clients_view.py`;
- `client_detail_view.py`;
- `expedients_view.py`;
- `economic_view.py`.

## GATE 5 — PERSISTENCIA CENTRALIZADA

Centralizar:

- configuración de conexión;
- transacciones;
- introspección de schema;
- inserciones con retorno de ID;
- diferencias de dialecto;
- reglas de concurrencia.

## GATE 6 — BASELINE Y DATASET CONTRACTUAL

Crear:

- baseline PostgreSQL limpio;
- master data;
- dataset ficticio E2E;
- tests contractuales;
- integridad referencial completa.

---

# XIV. ELEMENTOS QUE NO BLOQUEAN POSTGRESQL

Quedan expresamente fuera de los requisitos previos:

- finalización de todas las familias jurídicas;
- desarrollo completo de Extranjería;
- UGE completo;
- Asilo completo;
- Registro Civil completo;
- Policía Nacional completo;
- Guardia Civil completa;
- Knowledge;
- NotebookLM;
- Reporting avanzado;
- WhatsApp completo;
- telefonía;
- OCR totalmente explotado;
- HubSpot avanzado;
- fiscal como software contable autónomo.

Estas capacidades podrán desarrollarse posteriormente sobre PostgreSQL.

---

# XV. ESTRATEGIA TÉCNICA POSTGRESQL

No se recomienda una migración simultánea a un ORM completo.

La arquitectura objetivo será inicialmente:

`Flet`
→ `backend services`
→ `capa común de persistencia`
→ `driver PostgreSQL`
→ `PostgreSQL / Supabase`

Se recomienda mantener SQL explícito donde resulte conveniente, introduciendo una frontera común de persistencia.

No deberá sustituirse la dispersión actual de `sqlite3` por una nueva dispersión de llamadas al cliente Supabase.

Supabase será infraestructura.

El backend del ERP continuará siendo la autoridad sobre la lógica de negocio.

---

# XVI. ESTRATEGIA DE TRANSICIÓN

La migración no deberá realizarse mediante un cambio Big Bang.

Se recomienda soportar temporalmente:

`DB_BACKEND=sqlite`

y:

`DB_BACKEND=postgres`

La suite contractual deberá poder ejecutarse sobre ambos motores durante la transición.

El orden recomendado de portabilidad es:

1. Calendar / TASK.
2. Clientes.
3. Expedientes.
4. Notification Tracking.
5. Email / DEHú.
6. Documental central.
7. Económico.
8. Box Watch.

Calendar/TASK será el candidato piloto por su reciente estabilización, clean-install y cobertura de tests.

Económico deberá migrarse más tarde por sus necesidades de concurrencia, numeración y conciliación.

Box Watch deberá migrarse al final por su volumen, dependencia del filesystem local e historia técnica.

---

# XVII. ARQUITECTURA HÍBRIDA OBJETIVO

El futuro sistema será previsiblemente híbrido.

## PostgreSQL / Supabase

Centralizará:

- datos ERP;
- clientes;
- expedientes;
- TASK;
- Calendar;
- CAA;
- notificaciones;
- comunicaciones;
- económico;
- metadatos documentales;
- estado operativo.

## Cloud workers

Podrán ejecutar:

- scheduled notifications;
- Telegram;
- sincronización Gmail;
- procesamiento email;
- procesamiento DEHú basado en email;
- futuros jobs compatibles con cloud.

## Agente local / desktop

Continuará inicialmente ejecutando:

- Box Drive;
- Mercurio;
- automatizaciones con certificado digital;
- OCR local;
- Word/PDF;
- filesystem;
- otras automatizaciones dependientes del escritorio.

No se establece como objetivo inicial convertir Quesada Abogados ERP en una aplicación exclusivamente web o cloud.

---

# XVIII. ORDEN INMEDIATO DE DESARROLLO

Se fija el siguiente orden:

## FASE A
CAA V1.

## FASE B
`task_work_sessions`.

## FASE C
Modelo base de Comunicaciones.

## FASE D
Estabilización pre-PostgreSQL:

- eliminación SQL frontend;
- centralización de conexiones;
- eliminación de DDL runtime;
- revisión de transacciones;
- limpieza legacy;
- corrección de facturación automática;
- consolidación Box Watch.

## FASE E
Baseline PostgreSQL.

## FASE F
Tests duales SQLite/PostgreSQL.

## FASE G
Entorno Supabase de desarrollo.

## FASE H
Migración selectiva de dominios.

## FASE I
Switch principal a PostgreSQL.

## FASE J
Cloud workers.

---

# XIX. PRIORIDADES POSTERIORES A POSTGRESQL

Una vez estabilizado PostgreSQL / Supabase se continuará con:

- expansión masiva de familias jurídicas;
- Reporting avanzado;
- Knowledge;
- NotebookLM;
- nuevas automatizaciones;
- cloud workers adicionales;
- comunicación omnicanal avanzada;
- mejoras de OCR;
- nuevas integraciones.

---

# XX. RESOLUCIÓN FINAL

Se declara que Quesada Abogados ERP:

1. ha superado la fase de prototipo;
2. dispone de una arquitectura funcional amplia y coherente;
3. posee un motor de expedientes y trazabilidad altamente maduro;
4. tiene una infraestructura documental y operativa avanzada;
5. presenta una deuda técnica transversal principalmente concentrada en la persistencia SQLite;
6. no requiere finalizar toda la cobertura jurídica antes de migrar;
7. no requiere desarrollar Knowledge ni Reporting avanzado antes de migrar;
8. deberá cerrar CAA, sesiones de trabajo y modelo base de Comunicaciones antes del cambio de motor;
9. deberá realizar una fase específica de estabilización pre-PostgreSQL;
10. deberá migrar mediante baseline limpio, tests duales y transición progresiva;
11. deberá mantener una arquitectura híbrida cloud/local;
12. deberá utilizar PostgreSQL como base central y Supabase como plataforma de infraestructura, manteniendo el backend del ERP como responsable de la lógica de negocio.

Se establece como decisión arquitectónica vigente:

> Finalizar CAA V1, task_work_sessions y el modelo mínimo de Comunicaciones; ejecutar posteriormente la estabilización de persistencia; y, alcanzados dichos gates, iniciar la migración a PostgreSQL / Supabase antes de continuar con la expansión masiva de familias, Reporting avanzado y Knowledge.

---

# XXI. ESTADO DE AVANCE AL CIERRE DE LA AUDITORÍA

| Área | Estado |
|---|---:|
| Auditoría global | 100 % |
| ERP funcional | ≈ 81 % |
| Madurez técnica | ≈ 82 % |
| Motor Expedientes | ≈ 90 % |
| Cobertura jurídica | ≈ 35–40 % |
| Preparación Supabase | ≈ 66 % |
| Implementación PostgreSQL | 0 % |

**Estado de la resolución:** APROBADA COMO HOJA DE RUTA TÉCNICA Y FUNCIONAL DEL PROYECTO.