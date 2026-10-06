# RESOLUCIÓN SOBRE BLINDAJE DEL CÓDIGO MEDIANTE AUDITORÍAS, TESTS ROBUSTOS Y CONTROL DE REGRESIONES

**Proyecto:** Quesada Abogados ERP
**Fecha:** 9 de agosto de 2026
**Estado de referencia:** rama `develop`
**Naturaleza:** Resolución técnica vinculante
**Ámbito:** Calidad, estabilidad, auditoría, testing, regresiones, migraciones y protección del código consolidado

---

# I. OBJETO

La presente resolución establece la obligación de proteger y blindar progresivamente el código consolidado de Quesada Abogados ERP mediante:

- auditorías técnicas;
- tests unitarios;
- tests contractuales;
- tests de integración;
- tests end-to-end;
- pruebas de regresión;
- clean-install;
- comprobaciones de integridad;
- validación de migraciones;
- pruebas sobre bases de datos limpias;
- pruebas de compatibilidad entre motores de persistencia;
- revisión previa y posterior a refactorizaciones.

La finalidad de esta resolución es impedir que el crecimiento del ERP deteriore funcionalidades que ya han sido estabilizadas.

Se establece como principio general:

> Una funcionalidad no se considerará verdaderamente terminada cuando simplemente funcione, sino cuando exista evidencia suficiente de que continuará funcionando después de futuras modificaciones.

---

# II. PRINCIPIO DE BLINDAJE PROGRESIVO

Todo módulo que alcance un grado relevante de madurez deberá pasar progresivamente de:

`funcionalidad implementada`

a:

`funcionalidad implementada`
→ `auditada`
→ `testeada`
→ `regresión protegida`
→ `considerada contractual`

El grado de protección deberá aumentar conforme aumente:

- la criticidad;
- el uso;
- el número de dependencias;
- la dificultad de reconstrucción;
- el impacto económico;
- el impacto jurídico;
- el impacto documental;
- el riesgo de pérdida de datos.

---

# III. NINGÚN MÓDULO MADURO QUEDARÁ SIN CONTRATO

Cuando un módulo se considere estable o cerrado, deberán existir pruebas que documenten su comportamiento esperado.

Ejemplos:

- Calendar;
- TASK;
- Trazabilidad;
- Expedientes;
- Notificaciones;
- DEHú;
- Económico;
- Documental;
- Clientes;
- CAA;
- Comunicaciones;
- PostgreSQL.

Los tests deberán funcionar como contrato ejecutable del sistema.

Cuando posteriormente se modifique el código, el comportamiento contractual deberá mantenerse salvo decisión expresa de cambiarlo.

---

# IV. CLASIFICACIÓN DE TESTS

El proyecto distinguirá al menos los siguientes niveles.

## 1. Tests unitarios

Validarán funciones o reglas aisladas.

Ejemplos:

- normalización;
- cálculos;
- parsing;
- clasificación;
- funciones auxiliares;
- reglas específicas.

---

## 2. Tests de servicio

Validarán contratos completos de backend.

Ejemplos:

- crear TASK;
- completar TASK;
- crear factura;
- conciliar pago;
- crear autorización;
- reconciliar notification tracking;
- procesar email;
- derivar expediente.

---

## 3. Tests de integración

Validarán interacción entre distintos dominios.

Ejemplos:

`Trazabilidad`
→ `Notification Tracking`

`Trazabilidad`
→ `Calendar`

`Expediente`
→ `Autorización Cliente`

`Resolución`
→ `Derivación`

`CAA`
→ `TASK`
→ `Trazabilidad`

---

## 4. Tests end-to-end

Validarán secuencias funcionales completas.

Ejemplos:

`Reagrupación`
→ `presentación`
→ `notificación`
→ `resolución`
→ `visado`
→ `huellas`

o:

`Cobro`
→ `facturación explícita`
→ `aprobación`
→ `rectificativa`

---

## 5. Tests de regresión

Todo bug relevante corregido deberá, cuando resulte razonable, producir un test que impida su reaparición.

Se establece la regla:

> Bug corregido sin test de regresión = riesgo de repetir el mismo fallo.

---

# V. CLEAN-INSTALL OBLIGATORIO PARA DOMINIOS TRANSVERSALES

Todo módulo transversal deberá poder instalarse sobre una base limpia.

Especialmente:

- Calendar;
- TASK;
- CAA;
- Notificaciones;
- Comunicaciones;
- PostgreSQL baseline.

El proceso deberá validar:

`BD vacía`
→ `migraciones`
→ `schema completo`
→ `datos mínimos`
→ `tests`
→ `integridad`

No deberá dependerse de que la base histórica de desarrollo contenga accidentalmente columnas o tablas creadas anteriormente.

---

# VI. AUDITORÍAS PERIÓDICAS

Se establece la obligación de realizar auditorías técnicas periódicas.

No será necesario auditar todo el ERP en cada ocasión.

Las auditorías podrán ser:

## Auditoría global

Sobre todo el proyecto.

## Auditoría de módulo

Por ejemplo:

- Económico;
- Clientes;
- Documental;
- CAA;
- Comunicaciones.

## Auditoría previa a migración

Antes de:

- PostgreSQL;
- Supabase;
- cloud workers;
- grandes refactorizaciones.

## Auditoría posterior a migración

Para comprobar que la nueva arquitectura mantiene los contratos anteriores.

---

# VII. AUDITORÍA ANTES DE CONSIDERAR UN MÓDULO CERRADO

Un módulo no deberá declararse terminado sin revisar, cuando proceda:

- estructura de servicios;
- dependencias;
- SQL;
- transacciones;
- duplicaciones;
- código muerto;
- funciones redefinidas;
- errores de integridad;
- schema;
- migraciones;
- tests;
- frontend/backend separation;
- concurrencia;
- portabilidad PostgreSQL;
- comportamiento de errores.

La auditoría deberá buscar tanto fallos funcionales como deuda técnica.

---

# VIII. PROTECCIÓN ESPECIAL DE MÓDULOS CRÍTICOS

Se consideran especialmente críticos:

- persistencia;
- trazabilidad;
- económico;
- facturación;
- conciliación;
- documental;
- Box;
- CAA;
- Calendar;
- TASK;
- Notificaciones;
- autorizaciones;
- migraciones.

Estos módulos deberán disponer de mayor cobertura de tests que módulos puramente visuales.

---

# IX. FACTURACIÓN Y ECONÓMICO

Las operaciones económicas deberán quedar especialmente blindadas.

Deberán existir contratos para:

- creación de cobros;
- facturación;
- aprobación;
- congelación;
- rectificativas;
- cierres;
- numeración;
- IVA;
- IRPF;
- suplidos;
- conciliaciones;
- transferencias;
- reversión.

La regla:

`FACTURABLE ≠ FACTURAR`

deberá quedar protegida mediante tests.

Las operaciones económicas deberán validarse también frente a errores de concurrencia cuando llegue PostgreSQL.

---

# X. TRAZABILIDAD

Trazabilidad se considera una pieza central del ERP.

Toda modificación relevante deberá comprobar que no se rompen:

- estados administrativos;
- justificantes;
- resoluciones;
- requerimientos;
- admisiones;
- notas;
- Calendar;
- Notificaciones;
- derivaciones;
- autorizaciones;
- CAA.

Se favorecerán tests de integración frente a tests excesivamente aislados cuando una acción produzca efectos en varios dominios.

---

# XI. EXPEDIENTES Y DERIVACIONES

El motor de Expedientes deberá mantener pruebas contractuales para:

- familia;
- tipo;
- subtipo;
- relaciones;
- trayectoria;
- derivaciones;
- prevención de ciclos;
- aceptación de propuestas;
- autorizaciones resultantes;
- subexpedientes;
- continuidad entre procedimientos.

Cuando se añada una nueva familia jurídica no será obligatorio reproducir toda la suite general, pero deberá comprobarse que no rompe los contratos del motor común.

---

# XII. DOCUMENTAL

El sistema documental deberá proteger especialmente:

- deduplicación;
- SHA256;
- nomenclaturas;
- requisitos AND/OR;
- estados semánticos;
- roles;
- vinculación a expediente;
- targets;
- formularios;
- OCR;
- Box Watch.

Los cambios en Box Watch deberán realizarse con especial prudencia.

No se eliminará código aparentemente duplicado sin:

1. identificar la definición efectiva;
2. localizar call sites;
3. ejecutar tests;
4. realizar smoke funcional cuando corresponda.

---

# XIII. CAA Y TASK

Antes de considerar CAA estable deberán existir tests para:

- creación automática de TASK;
- idempotencia mediante `source_key`;
- inicio;
- pausa;
- reanudación;
- sesiones de trabajo;
- cancelación;
- completado;
- finalización desde Trazabilidad;
- interacción con Calendar;
- ausencia de duplicación de actividad.

Las `task_work_sessions` deberán disponer de tests específicos sobre duración efectiva.

---

# XIV. NOTIFICACIONES

Deberán protegerse mediante tests:

- generación de tracking;
- transición entre fases;
- fechas de espera;
- cierre favorable;
- cierre denegatorio;
- proyección sobre Calendar;
- idempotencia;
- scheduled notifications;
- entrega;
- reintentos;
- errores.

---

# XV. DEHÚ Y EMAIL

Los servicios de email y DEHú deberán mantener pruebas para:

- deduplicación;
- parsing;
- normalización;
- matching;
- clasificación;
- revisión;
- vinculación a expediente;
- idempotencia;
- reprocesamiento.

Cuando se ejecute en cloud deberán añadirse tests de concurrencia o idempotencia distribuida.

---

# XVI. COMUNICACIONES

Cuando se construya el modelo omnicanal deberán existir pruebas para:

- threads;
- participantes;
- mensajes;
- eventos;
- canales;
- cliente;
- expediente;
- identificadores externos;
- deduplicación.

Cada integración deberá respetar el modelo común.

---

# XVII. MIGRACIONES

Toda migración deberá considerarse código productivo.

Deberá comprobarse:

- ejecución sobre schema esperado;
- ejecución sobre base limpia cuando proceda;
- idempotencia cuando el diseño la requiera;
- constraints;
- índices;
- integridad;
- compatibilidad con datos existentes;
- rollback lógico o estrategia de recuperación cuando proceda.

No deberá confiarse en que una migración “parece correcta”.

---

# XVIII. POSTGRESQL

La futura migración a PostgreSQL deberá quedar especialmente blindada.

La suite contractual deberá ejecutarse temporalmente sobre:

`SQLite`

y:

`PostgreSQL`

Los tests duales deberán demostrar que el comportamiento funcional es equivalente.

La migración no se considerará terminada hasta validar:

- integridad;
- transacciones;
- concurrencia;
- numeración;
- derivaciones;
- notificaciones;
- CAA;
- económico;
- documentos;
- clientes;
- expedientes.

---

# XIX. DATASET CONTRACTUAL

Se creará un dataset ficticio reproducible que permita probar todo el flujo principal del ERP.

Deberá incluir, como mínimo:

`Cliente`
→ `Expediente`
→ `Documentos`
→ `Cobro`
→ `Trazabilidad`
→ `Presentación`
→ `Notification Tracking`
→ `Calendar / TASK`
→ `Resolución`
→ `Autorización`
→ `Derivación`
→ `Nuevo expediente`

El dataset deberá poder reconstruirse desde cero.

No deberá depender de datos manuales de la base histórica.

---

# XX. DATOS REALES Y SENSIBLES

Los tests automáticos no deberán destruir, modificar o regenerar accidentalmente:

- rutas reales de Box;
- inventarios reales;
- referencias documentales;
- documentos reales;
- información sensible no reproducible.

Los tests deberán utilizar:

- bases temporales;
- fixtures;
- datos ficticios;
- carpetas temporales;
- mocks cuando corresponda.

Las pruebas sobre recursos reales deberán ser explícitas y controladas.

---

# XXI. PRUEBAS DE INTEGRIDAD

Cuando proceda deberán ejecutarse:

- `PRAGMA integrity_check` en SQLite;
- `PRAGMA foreign_key_check` en SQLite;
- constraints equivalentes en PostgreSQL;
- comprobaciones de duplicados;
- comprobaciones de huérfanos;
- verificaciones de cardinalidad.

La integridad del dato formará parte del contrato del sistema.

---

# XXII. TESTS TEMPORALES

Los tests no deberán depender de:

- la hora actual sin control;
- el día actual sin fijación;
- estado externo impredecible;
- archivos personales;
- orden accidental de ejecución.

Cuando un test dependa del tiempo deberá:

- fijar una fecha;
- inyectar reloj;
- utilizar datos controlados.

---

# XXIII. TESTS DE RED Y PROVEEDORES

Las pruebas normales no deberán depender de tener conexión real con:

- Gmail;
- IONOS;
- Telegram;
- Box;
- Mercurio;
- DEHú;
- HubSpot.

Las integraciones deberán disponer de contratos mockeables o pruebas aisladas.

Los smoke tests contra servicios reales deberán ser explícitos.

---

# XXIV. AUDITORÍA DESPUÉS DE GRANDES CAMBIOS

Será obligatoria una revisión específica después de:

- migración PostgreSQL;
- refactor económico;
- CAA;
- cambio de Box Watch;
- cambio del motor documental;
- cambio de Trazabilidad;
- nueva arquitectura de Comunicaciones.

La finalidad será detectar regresiones o nueva deuda antes de continuar ampliando el ERP.

---

# XXV. TESTS ANTES DE COMMIT

Todo commit deberá ejecutar como mínimo las pruebas directamente afectadas.

Un commit no deberá considerarse válido si:

- el código no compila;
- fallan tests afectados;
- `git diff --check` detecta problemas;
- introduce regresiones conocidas.

---

# XXVI. TESTS ANTES DE MERGE

Antes de integrar una feature relevante a `develop` deberán ejecutarse:

- tests específicos de la feature;
- tests de integración relacionados;
- regresión de los dominios afectados;
- clean-install cuando exista;
- compilación;
- `git diff --check`;
- revisión del estado Git.

Las features transversales deberán exigir una regresión más amplia.

---

# XXVII. TESTS ANTES DE RELEASE / BETA

Antes de una beta deberá ejecutarse una suite global.

La suite deberá cubrir como mínimo:

- Clientes;
- Expedientes;
- Trazabilidad;
- Documental;
- Económico;
- Calendar;
- TASK;
- CAA;
- Notificaciones;
- comunicaciones críticas;
- migraciones;
- integridad.

---

# XXVIII. BUGS EN PRODUCCIÓN

Cuando aparezca un bug relevante se seguirá:

`reproducir`
→ `crear test que falle`
→ `corregir`
→ `verificar que el test pasa`
→ `ejecutar regresión`
→ `commit`

Siempre que resulte técnicamente razonable.

---

# XXIX. PROHIBICIÓN DE ARREGLAR TESTS ROMPIENDO EL CONTRATO

Cuando un test válido falle después de un cambio, no deberá modificarse el test únicamente para que vuelva a pasar.

Primero deberá determinarse:

1. si el comportamiento nuevo es correcto;
2. si el contrato anterior debe cambiar;
3. si existe una regresión.

Solo después se modificará el test si existe una decisión funcional consciente.

---

# XXX. TESTS COMO DOCUMENTACIÓN

Los tests deberán utilizar nombres y escenarios comprensibles.

Un desarrollador futuro deberá poder entender mediante ellos:

- qué comportamiento se espera;
- qué reglas son importantes;
- qué errores ya ocurrieron;
- qué contratos no deben romperse.

Los tests forman parte de la documentación técnica del proyecto.

---

# XXXI. COBERTURA

No se establece inicialmente un porcentaje universal obligatorio de cobertura de líneas.

La cobertura cuantitativa no sustituye la calidad del test.

Se priorizará cobertura de:

- contratos;
- invariantes;
- transacciones;
- flujos críticos;
- errores conocidos;
- efectos laterales.

Un módulo con 100 % de cobertura superficial puede estar menos protegido que otro con tests contractuales robustos.

---

# XXXII. BLINDAJE POR CAPAS

El objetivo será que los módulos maduros alcancen progresivamente cuatro niveles:

## NIVEL 1 — FUNCIONAL

La funcionalidad funciona.

## NIVEL 2 — CONTRACTUAL

Existen tests de servicio.

## NIVEL 3 — INTEGRADO

Existen tests de interacción con otros dominios.

## NIVEL 4 — BLINDADO

Existen:

- regresión;
- clean-install;
- integridad;
- casos de error;
- tests E2E cuando proceda.

Los dominios críticos deberán aspirar al NIVEL 4.

---

# XXXIII. REGISTRO DE DEUDA DETECTADA

Las auditorías deberán producir hallazgos identificables.

Ejemplos:

`CLIENT-01`

`ECON-01`

`DOC-01`

`OPS-01`

`INFRA-01`

Cada hallazgo deberá indicar:

- descripción;
- gravedad;
- impacto;
- momento recomendado de corrección;
- condición de cierre.

Esto permitirá distinguir entre:

- deuda conocida;
- deuda nueva;
- deuda resuelta.

---

# XXXIV. PROHIBICIÓN DE EXPANSIÓN INSEGURA

No deberá ampliarse masivamente un módulo cuya base presente fallos estructurales graves sin antes estabilizarla.

Ejemplo:

No deberán añadirse numerosas funcionalidades económicas nuevas si la lógica crítica sigue duplicada entre frontend y backend.

El objetivo será evitar multiplicar la deuda por expansión.

---

# XXXV. AUDITORÍA COMO GATE

Las auditorías podrán convertirse en gates formales.

Por ejemplo:

`CAA desarrollado`
→ `auditoría CAA`
→ `tests robustos`
→ `cerrado`

o:

`PostgreSQL migrado`
→ `auditoría post-migración`
→ `suite global`
→ `switch definitivo`

---

# XXXVI. PRINCIPIO DE NO CONFIAR EN LA MEMORIA HUMANA

La estabilidad del proyecto no deberá depender de recordar manualmente:

- qué funciones no tocar;
- qué bug ocurrió;
- qué transición era especial;
- qué combinación de estados era válida.

Todo comportamiento importante deberá quedar expresado mediante:

- código;
- constraints;
- tests;
- migraciones;
- documentación.

---

# XXXVII. AUTOMATIZACIÓN DE QA

A medida que el proyecto madure se deberá favorecer la automatización de:

- compilación;
- tests;
- `git diff --check`;
- clean-install;
- integridad;
- migraciones;
- suites contractuales.

En el futuro podrá evaluarse integración continua en GitHub Actions u otro sistema equivalente.

No será obligatorio introducir CI inmediatamente si el flujo local sigue siendo suficiente, pero la suite deberá diseñarse para poder automatizarse.

---

# XXXVIII. RELACIÓN CON QA-DEV-001

Se ratifica la metodología:

`grep`
→ `sed / inspección`
→ `patch`
→ `compile`
→ `test`
→ `diff`
→ `commit`

La presente resolución amplía QA-DEV-001:

Un cambio no deberá considerarse terminado únicamente cuando pase su test inmediato.

También deberá evaluarse qué regresión relacionada debe ejecutarse.

---

# XXXIX. OBLIGACIÓN DE EXPLICAR EL BLINDAJE

Cada fase técnica relevante deberá informar:

1. qué se ha implementado;
2. qué tests se han añadido;
3. qué contratos quedan protegidos;
4. qué regresión se ha ejecutado;
5. qué riesgos quedan sin cubrir;
6. porcentaje estimado de avance.

Cada commit seguirá indicando:

- qué se hizo;
- por qué;
- qué problema resuelve;
- qué queda pendiente.

---

# XL. RESOLUCIÓN FINAL

Se establece como norma obligatoria para Quesada Abogados ERP:

1. Todo código crítico deberá blindarse mediante tests.
2. Los módulos maduros deberán someterse a auditorías.
3. Los bugs relevantes deberán generar tests de regresión.
4. Los dominios transversales deberán disponer de clean-install.
5. Las migraciones deberán probarse como código productivo.
6. PostgreSQL deberá validarse mediante tests duales durante la transición.
7. Las integraciones deberán ser testeables sin depender obligatoriamente de servicios reales.
8. Los datos reales y sensibles no deberán utilizarse destructivamente en tests.
9. Los tests deberán proteger comportamiento, no detalles accidentales.
10. Ningún test válido deberá modificarse solo para ocultar una regresión.
11. Los módulos críticos deberán aspirar al máximo nivel de blindaje.
12. Las auditorías deberán producir deuda identificable y trazable.
13. No se deberá expandir masivamente sobre una base estructuralmente inestable.
14. Los tests y auditorías actuarán como gates para cerrar fases.
15. La estabilidad deberá residir en contratos ejecutables y no en memoria humana.
16. Toda gran migración deberá ir seguida de auditoría y regresión.
17. Toda release o beta deberá ejecutar una suite global.
18. QA-DEV-001 continuará siendo metodología obligatoria.
19. Cada desarrollo deberá indicar explícitamente qué parte del sistema queda protegida.
20. El principio general del proyecto será:

> CÓDIGO IMPLEMENTADO → CÓDIGO TESTEADO → CÓDIGO AUDITADO → CÓDIGO BLINDADO.

**Estado de la resolución:** APROBADA COMO NORMA DE ASEGURAMIENTO DE CALIDAD Y BLINDAJE DEL CÓDIGO.