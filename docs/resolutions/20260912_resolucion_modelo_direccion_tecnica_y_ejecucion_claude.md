# RESOLUCIÓN SOBRE EL MODELO DE DIRECCIÓN TÉCNICA, GOBIERNO DEL PROYECTO Y EJECUCIÓN DE CÓDIGO MEDIANTE CLAUDE

**Proyecto:** Quesada Abogados ERP / QCC / AUTO TWIN
**Fecha:** 12 de septiembre de 2026
**Estado:** APROBADA
**Naturaleza:** Resolución metodológica, técnica y de gobierno vinculante
**Ámbito:** Todo el desarrollo presente y futuro de Quesada Abogados
**Principio rector:** cambio de ejecutor técnico sin cambio de arquitectura, metodología ni autoridad del proyecto

---

# I. OBJETO

La presente resolución establece un nuevo modelo operativo para el desarrollo de código de Quesada Abogados como consecuencia del crecimiento, profundidad y complejidad alcanzados por el proyecto.

A partir de esta resolución se adopta una separación expresa entre:

```text
DIRECCIÓN TÉCNICA Y ARQUITECTÓNICA
                ↓
ESPECIFICACIÓN DEL TRABAJO
                ↓
EJECUCIÓN SOBRE EL REPOSITORIO
                ↓
EVIDENCIA Y TESTS
                ↓
REVISIÓN TÉCNICA
                ↓
SIGUIENTE DECISIÓN
```

El objetivo es trasladar progresivamente la ejecución material del código a Claude, conservando en el sistema actual de dirección del proyecto:

* estrategia;
* arquitectura;
* diseño funcional;
* decisiones técnicas;
* contratos;
* criterios de aceptación;
* interpretación de resultados;
* secuenciación del desarrollo;
* gobierno del proyecto.

---

# II. PRINCIPIO FUNDAMENTAL

Se establece:

> **El cambio a Claude afecta al ejecutor del código, no a los principios, arquitectura, decisiones ni metodología del proyecto.**

Por tanto:

```text
NO se reinicia el proyecto.
NO se redefine la arquitectura.
NO se sustituyen las resoluciones anteriores.
NO se abandonan los contratos existentes.
NO se autoriza una reescritura general.
```

El proyecto continuará exactamente desde el estado técnico alcanzado.

---

# III. CONTINUIDAD NORMATIVA

Todas las resoluciones técnicas, funcionales, metodológicas y arquitectónicas aprobadas anteriormente continúan plenamente vigentes.

La presente resolución:

```text
NO DEROGA
NO SUSTITUYE
NO REINICIA
```

las decisiones anteriores.

Se limita a establecer una nueva distribución de responsabilidades en la ejecución del desarrollo.

En caso de conflicto entre una propuesta del ejecutor y una resolución existente:

```text
RESOLUCIÓN APROBADA
        >
PROPUESTA DEL EJECUTOR
```

---

# IV. MODELO DE TRABAJO APROBADO

Se adopta el siguiente modelo:

```text
QUESADA ABOGADOS
       │
       ▼
DIRECCIÓN DEL PROYECTO
       │
       ▼
CHATGPT
Dirección técnica / arquitectura
       │
       ▼
WORK ORDER / ESPECIFICACIÓN
       │
       ▼
CLAUDE
Ejecución sobre código real
       │
       ▼
TESTS + DIAGNÓSTICO + EVIDENCIA
       │
       ▼
CHATGPT
Revisión e interpretación
       │
       ▼
DIRECCIÓN DEL PROYECTO
```

---

# V. FUNCIÓN DE LA DIRECCIÓN DEL PROYECTO

La Dirección de Quesada Abogados mantiene la autoridad última sobre:

* objetivos;
* prioridades;
* decisiones funcionales;
* aprobación de arquitectura;
* criterios jurídicos;
* nivel de automatización;
* aceptación de riesgos;
* integraciones;
* política de datos;
* cambios estructurales;
* entrada en producción.

Ningún agente de IA tendrá autoridad autónoma sobre estas materias.

---

# VI. FUNCIÓN DE CHATGPT

ChatGPT actuará como:

```text
cerebro técnico y arquitectónico del desarrollo asistido
```

Sus funciones principales serán:

* mantener la visión global del proyecto;
* interpretar las resoluciones existentes;
* diseñar arquitectura;
* detectar implicaciones entre módulos;
* definir contratos;
* dividir desarrollos complejos en bloques;
* redactar Work Orders;
* establecer invariantes;
* definir criterios de aceptación;
* determinar tests necesarios;
* interpretar evidencias devueltas por Claude;
* detectar regresiones conceptuales;
* decidir el siguiente bloque de trabajo;
* proponer nuevas resoluciones cuando sea necesario;
* mantener coherencia entre ERP, QCC, AUTO TWIN, automatizaciones y demás dominios.

ChatGPT no perderá esta función por el hecho de que la ejecución material pase a Claude.

---

# VII. FUNCIÓN DE CLAUDE

Claude actuará principalmente como:

```text
ejecutor técnico sobre el repositorio
```

Entre sus funciones podrán encontrarse:

* inspeccionar el repositorio;
* ejecutar `grep`, búsquedas y diagnósticos;
* leer implementaciones existentes;
* localizar call sites;
* modificar código;
* crear migraciones cuando hayan sido autorizadas;
* crear y modificar tests;
* ejecutar suites;
* ejecutar scripts;
* ejecutar diagnósticos;
* comprobar compilación;
* revisar diffs;
* aplicar correcciones;
* ejecutar runtimes de prueba;
* crear commits autorizados;
* devolver evidencia técnica.

Claude trabajará sobre:

```text
el código real del repositorio
```

y no sobre reconstrucciones teóricas del mismo.

---

# VIII. CLAUDE NO SERÁ AUTORIDAD ARQUITECTÓNICA AUTÓNOMA

Claude no podrá modificar por iniciativa propia:

* arquitectura general;
* contratos aprobados;
* modelo de datos;
* autoridades de dominio;
* políticas HUMAN_ONLY;
* principios de persistencia;
* estructura de módulos;
* semántica de QCC;
* semántica de AUTO TWIN;
* gobierno de SeleniumBase;
* flujos jurídicos;
* política documental;
* política económica;
* política de seguridad.

Si durante la ejecución descubre que una especificación contradice el código real o resulta técnicamente inviable deberá:

```text
diagnosticar
        ↓
documentar
        ↓
aportar evidencia
        ↓
detener el cambio estructural
        ↓
elevar la decisión
```

No deberá solucionar una contradicción arquitectónica inventando una nueva arquitectura sin autorización.

---

# IX. WORK ORDER COMO UNIDAD DE TRABAJO

La unidad principal de comunicación entre dirección técnica y Claude será la:

```text
WORK ORDER
```

Cada Work Order deberá contener, cuando proceda:

* contexto;
* objetivo;
* estado conocido;
* archivos o áreas relevantes;
* contratos;
* invariantes;
* prohibiciones;
* fases de trabajo;
* diagnóstico requerido;
* tests;
* criterios de aceptación;
* formato de evidencia;
* política de commit.

Claude deberá ejecutar el objetivo definido y evitar ampliar innecesariamente el alcance.

---

# X. PRINCIPIO DE ALCANCE CONTROLADO

Cada Work Order deberá perseguir un objetivo concreto.

Se mantiene el principio ya aprobado:

```text
diagnosticar primero
modificar después
validar siempre
```

Quedan desaconsejadas órdenes genéricas como:

```text
"mejora AUTO TWIN"
"refactoriza QCC"
"optimiza Mercurio"
"arregla el ERP"
```

Se favorecerán órdenes como:

```text
"reconciliar un estado existente preservando su state_id"

"incorporar una transición determinada"

"extraer SQL de una vista concreta"

"añadir un contrato de regresión específico"
```

---

# XI. CONSERVACIÓN DEL DESARROLLO INCREMENTAL

Se mantiene plenamente vigente la metodología de:

* diagnóstico previo;
* inspección del código existente;
* cambios quirúrgicos;
* pequeños bloques;
* pruebas progresivas;
* commits atómicos.

El uso de Claude no autoriza:

```text
reescrituras generales
reemplazo indiscriminado de archivos
refactorizaciones masivas
cambios simultáneos no relacionados
```

La capacidad de Claude para modificar grandes cantidades de código no constituye por sí misma una justificación para hacerlo.

---

# XII. REPOSITORIO COMO FUENTE TÉCNICA DE VERDAD

Git continuará siendo la fuente oficial del código.

La ejecución deberá realizarse sobre:

```text
rama real
+
working tree real
+
código real
+
tests reales
```

No se aceptará como evidencia suficiente una solución teórica que no haya sido contrastada contra el repositorio.

---

# XIII. GOBIERNO DE RAMAS

Continúan vigentes:

```text
main
develop
feature/*
hotfix/*
```

`main` seguirá representando el estado estable.

`develop` seguirá siendo rama de integración.

El desarrollo ordinario continuará realizándose sobre:

```text
feature/*
```

Claude no deberá desarrollar directamente sobre `main`.

Tampoco realizará merges a `develop` o `main` salvo autorización expresa.

---

# XIV. COMMITS

Los commits continuarán siendo:

* pequeños;
* coherentes;
* funcionales;
* reversibles;
* descriptivos;
* asociados a un objetivo concreto.

No se commiteará:

* código que no compile;
* suites rotas;
* experimentos;
* archivos temporales;
* cambios accidentales;
* refactorizaciones no solicitadas.

---

# XV. TESTS COMO CONTRATO

La transferencia de ejecución a Claude incrementa, y no reduce, la importancia de los tests.

Se mantiene el principio:

> **Una funcionalidad no está cerrada simplemente porque funcione una vez. Debe existir evidencia suficiente de que seguirá funcionando.**

Claude deberá ejecutar los tests correspondientes y devolver su resultado.

Cuando proceda deberán incluirse:

* unitarios;
* servicio;
* integración;
* contractuales;
* regresión;
* E2E;
* clean-install;
* smoke controlado.

---

# XVI. BUG CORREGIDO, REGRESIÓN PROTEGIDA

Cuando Claude corrija un defecto relevante deberá evaluarse la creación de un test de regresión.

Se mantiene:

```text
BUG
 ↓
DIAGNÓSTICO
 ↓
FIX
 ↓
TEST DE REGRESIÓN
```

cuando resulte técnicamente razonable.

---

# XVII. NO ADAPTAR LOS TESTS PARA OCULTAR ERRORES

Claude no deberá modificar un test contractual simplemente para conseguir una suite verde.

Si un test existente contradice el nuevo comportamiento deberá determinarse primero si:

```text
ha cambiado legítimamente el contrato
```

o si:

```text
el nuevo código ha introducido una regresión.
```

Ante duda deberá elevarse la decisión.

---

# XVIII. SEPARACIÓN FRONTEND / BACKEND

Continúa plenamente vigente la prohibición de introducir SQL, persistencia o lógica de negocio nueva en Flet.

La arquitectura seguirá siendo:

```text
Frontend
   ↓
Application / Services
   ↓
Dominio
   ↓
Persistencia
```

Claude deberá respetar esta separación en cualquier código nuevo.

---

# XIX. PERSISTENCIA Y POSTGRESQL

Continúan vigentes las reglas establecidas para la evolución hacia PostgreSQL.

No se introducirá nuevo acoplamiento a SQLite innecesario.

Se mantendrán:

* persistencia centralizada;
* migraciones gobernadas;
* ausencia de SQL nuevo en frontend;
* ausencia de evolución de schema desde vistas;
* operaciones transaccionales;
* separación de dominio e infraestructura.

---

# XX. UNA SOLA FUENTE DE VERDAD

Claude deberá respetar las autoridades ya establecidas en cada dominio.

Entre otras:

```text
Expediente / Trazabilidad
= autoridad jurídica

TASK
= unidad de trabajo

Calendar
= proyección temporal

CAA
= centro operativo sobre TASK

notification_tracking
= proyección administrativa

scheduled_notifications
= outbox

Reporting
= proyección

Knowledge
= consumidor

QCC
= proyección contextual del runtime

AUTO TWIN
= representación gobernada de la sede observada
```

No podrán introducirse fuentes de verdad paralelas sin decisión arquitectónica expresa.

---

# XXI. AUTOMATIZACIÓN DE NAVEGADOR

Continúa vigente la arquitectura común SeleniumBase/CDP.

Claude deberá preservar:

```text
caso de uso
→ runtime
→ connector
→ browser infrastructure
→ SeleniumBase/CDP
```

No se permitirá SeleniumBase directo desde frontend.

No se crearán wrappers privados innecesarios si existe infraestructura común.

---

# XXII. OWNERSHIP Y CONCURRENCIA

Continúan vigentes:

* ownership explícito de navegador;
* perfil;
* runtime;
* worker;
* sesión;
* ciclo de vida;
* serialización de operaciones cuando corresponda.

Los watchers no deberán acceder concurrentemente al navegador de forma no gobernada.

---

# XXIII. QCC

Quesada Chrome Companion continúa siendo:

```text
interfaz contextual del ERP dentro de Chrome
```

No es:

* backend;
* segundo CRM;
* base de datos;
* autoridad jurídica;
* sustituto del runtime.

Claude deberá preservar esta separación.

---

# XXIV. QCC BRIDGE

El Bridge continuará actuando como capa de comunicación.

No deberá incorporar lógica jurídica o convertirse en fuente de verdad.

Sus contratos deberán mantenerse provider-neutral cuando así hayan sido diseñados.

---

# XXV. LABS

Se mantiene el principio:

```text
REAL
 ↓
observación
 ↓
contrato
 ↓
LAB / TWIN
 ↓
automatización
 ↓
tests
 ↓
REAL
```

Claude no deberá sustituir el LAB o TWIN por mocks simplificados cuando el contrato exija comportamiento navegable o fidelidad funcional.

---

# XXVI. AUTO TWIN

AUTO TWIN continúa siendo una capacidad propia de QCC destinada a construir y mantener réplicas gobernadas de sedes observadas.

Se mantienen como principios:

* descubrimiento continuo;
* estados funcionales;
* arquitectura DOM;
* geometría;
* navegación;
* catálogos;
* revisiones;
* sincronización REAL ↔ TWIN;
* validación;
* fingerprints;
* evidencia;
* versionado.

El cambio de ejecutor de código no modifica ninguno de estos contratos.

---

# XXVII. FIDELIDAD DEL TWIN

Se mantiene como objetivo la máxima fidelidad práctica dentro del entorno de render controlado.

Claude no podrá degradar el TWIN a:

```text
mock funcional simplificado
```

si el contrato aprobado exige:

* fidelidad visual;
* geometría;
* CSS;
* DOM;
* controles;
* navegación;
* estados;
* comportamiento observable.

---

# XXVIII. NAVEGADOR DEL TWIN

El navegador local del Twin continuará ejecutándose dentro de una instancia SeleniumBase gobernada.

No deberá abrirse el Twin operativo en una pestaña ordinaria del Chrome personal del usuario.

El entorno Twin será el entorno de preproducción para automatizaciones de sede.

---

# XXIX. OBSERVACIÓN Y DESCUBRIMIENTO

Se mantiene la diferenciación entre:

```text
REAL profiles
→ observación

TWIN DISCOVERY
→ observación + descubrimiento gobernado
```

Los perfiles reales no deberán efectuar experimentaciones activas capaces de interferir con expedientes administrativos.

---

# XXX. POLÍTICAS DE INTERACCIÓN

Continúan vigentes las políticas:

```text
AUTOMATION_ALLOWED
OBSERVATION_ONLY
HUMAN_ONLY
```

Claude no podrá reclasificar una acción HUMAN_ONLY como automatizable simplemente para completar un test o flujo.

---

# XXXI. ACCIONES HUMAN_ONLY

Las acciones sensibles continuarán sometidas a control humano cuando así se haya establecido.

En particular, según el proveedor y contrato aplicable:

* continuar;
* adjuntar;
* firmar;
* registrar;
* presentar;
* CAPTCHA;
* confirmaciones jurídicas;
* actuaciones irreversibles.

La disponibilidad técnica para hacer clic no equivale a autorización arquitectónica para automatizarlo.

---

# XXXII. PRUEBAS MANUALES

Cuando una validación requiera intervención humana, Claude deberá indicar expresamente:

1. qué debe hacer el usuario;
2. en qué navegador;
3. en qué pantalla;
4. qué acción concreta debe realizar;
5. qué evidencia deberá aparecer después.

Siempre que el propio repositorio permita lanzar previamente mediante script:

* Discovery;
* Twin;
* Bridge;
* runtime;
* servidor local;

Claude deberá hacerlo o proporcionar el comando gobernado correspondiente, evitando trasladar innecesariamente trabajo técnico manual al usuario.

---

# XXXIII. NO ROBAR FOCO CUANDO NO SEA NECESARIO

Las automatizaciones deberán continuar respetando el principio de no interferencia con el trabajo del usuario.

Cuando una automatización pueda ejecutarse mediante SeleniumBase/CDP sin foco, esa será la opción preferente.

Las excepciones expresamente aprobadas mantendrán su arquitectura particular.

---

# XXXIV. DATOS SENSIBLES

El uso de Claude no autoriza a trasladar indiscriminadamente:

* bases de datos reales;
* NIE;
* pasaportes;
* credenciales;
* certificados;
* tokens;
* datos de clientes;
* documentos jurídicos reales;
* rutas sensibles;
* secretos.

Cuando el desarrollo pueda realizarse con:

* fixtures;
* IDs;
* hashes;
* datos ficticios;
* estructuras;
* logs sanitizados;

se utilizarán estos mecanismos.

---

# XXXV. SECRETOS

Continúa absolutamente prohibido versionar o introducir en prompts, scripts o commits:

* passwords;
* tokens;
* OAuth secrets;
* certificados privados;
* claves API;
* cookies;
* secretos de sesión.

Las credenciales seguirán tratándose mediante mecanismos externos al código.

---

# XXXVI. CLAUDE DEBERÁ LEER ANTES DE MODIFICAR

Antes de tocar un área compleja, Claude deberá investigar el estado real.

Como mínimo, cuando proceda:

```text
git status
git branch
grep / búsquedas
lectura de implementaciones
lectura de call sites
lectura de tests
git diff
```

No deberá inferir la estructura del proyecto si puede comprobarla.

---

# XXXVII. PREVENCIÓN DE DUPLICIDADES

Antes de crear:

* servicio;
* componente;
* helper;
* mapper;
* función;
* tabla;
* contrato;
* runtime;
* utilidad;

Claude deberá comprobar si ya existe una capacidad equivalente.

Se mantiene como objetivo evitar:

```text
misma función
+
nuevo nombre
+
nuevo código
```

sin necesidad real.

---

# XXXVIII. PROHIBICIÓN DE REESCRITURA POR ESTILO

Claude no deberá reescribir código estable únicamente porque considere que podría expresarse de forma más elegante.

La existencia de una implementación estilísticamente mejor no justifica el riesgo de regresión.

La prioridad seguirá siendo:

```text
robustez
>
claridad
>
mantenibilidad
>
elegancia
```

---

# XXXIX. DEUDA TÉCNICA

Si Claude detecta deuda técnica fuera del alcance de la Work Order deberá:

* identificarla;
* documentarla;
* explicar el riesgo;
* no ampliarla;
* no resolverla incidentalmente salvo que sea imprescindible.

Podrá proponerse una Work Order posterior específica.

---

# XL. HALLAZGOS NO PREVISTOS

Durante una ejecución puede descubrirse información que contradiga nuestras hipótesis previas.

Esto no deberá considerarse un fallo de Claude.

El procedimiento correcto será:

```text
hallazgo
 ↓
evidencia
 ↓
análisis
 ↓
nueva decisión
```

Se prohíbe ocultar el hallazgo adaptando silenciosamente el código.

---

# XLI. CRITERIOS DE ACEPTACIÓN

Cada bloque deberá disponer, cuando proceda, de criterios verificables.

Ejemplos:

```text
STATE_ID_PRESERVED=True

REGRESSION_SUITE=PASS

NO_DUPLICATE_STATE=True

PY_COMPILE=PASS

GIT_DIFF_CHECK=PASS
```

Los criterios deberán derivarse del contrato real del bloque.

---

# XLII. EVIDENCIA OBLIGATORIA

Claude deberá devolver evidencia suficiente para poder revisar el trabajo sin confiar únicamente en su descripción.

Según el caso:

* archivos modificados;
* diff resumido;
* revision IDs;
* fingerprints;
* filas relevantes;
* salida de tests;
* compilación;
* logs;
* capturas;
* rutas;
* resultados de materialización;
* estado Git.

---

# XLIII. ESTADO FINAL DE CADA WORK ORDER

La respuesta de Claude deberá distinguir entre:

```text
COMPLETADO
```

```text
PARCIALMENTE COMPLETADO
```

```text
BLOQUEADO POR HALLAZGO
```

```text
REQUIERE VALIDACIÓN HUMANA
```

No deberá declarar completado un bloque cuyo criterio de aceptación principal no haya sido demostrado.

---

# XLIV. CONTROL DE COMMITS

Un Work Order podrá autorizar:

```text
diagnóstico solamente
```

```text
modificación sin commit
```

o:

```text
modificación + commit
```

Claude deberá respetar la modalidad indicada.

En ausencia de autorización de merge:

```text
NO MERGE
```

---

# XLV. MERGE A DEVELOP

La finalización técnica de una Work Order no implica automáticamente su integración.

El flujo será:

```text
Claude ejecuta
       ↓
tests
       ↓
evidencia
       ↓
revisión arquitectónica
       ↓
aprobación
       ↓
merge
```

cuando proceda.

---

# XLVI. DOCUMENTACIÓN DEL PROYECTO

Se considera conveniente crear progresivamente dentro del repositorio una capa documental específica para el trabajo asistido por IA.

Podrá incluir:

```text
docs/ai/
```

y dentro de ella, por ejemplo:

```text
PROJECT_CONSTITUTION.md
CURRENT_STATE.md
WORK_ORDERS/
HANDOFFS/
```

Estos documentos no sustituirán las resoluciones.

Su función será facilitar a Claude el contexto operativo necesario para cada trabajo.

---

# XLVII. PROJECT CONSTITUTION

Podrá crearse un documento resumido que reúna los principios permanentes del proyecto.

Deberá remitir a las resoluciones originales cuando sea necesario.

Su función será evitar que cada sesión de ejecución tenga que reconstruir desde cero reglas como:

* ramas;
* tests;
* no SQL en frontend;
* control humano;
* SeleniumBase gobernado;
* no reescrituras;
* Twin gobernado;
* protección de datos;
* autoridad del dominio.

---

# XLVIII. CURRENT STATE

Podrá mantenerse un documento de estado vivo del desarrollo.

Este documento podrá contener:

* rama actual;
* bloque en curso;
* último estado cerrado;
* bloque pendiente;
* revisiones relevantes;
* tests conocidos;
* deuda detectada;
* siguiente objetivo.

Será operativo y no normativo.

---

# XLIX. HANDOFF ENTRE CHATGPT Y CLAUDE

El proceso ordinario será:

```text
1. Aquí se analiza el proyecto.

2. Aquí se decide el objetivo.

3. Aquí se redacta la Work Order.

4. Claude inspecciona el repositorio.

5. Claude ejecuta.

6. Claude devuelve evidencias.

7. Aquí se revisan técnicamente las evidencias.

8. Aquí se decide:
   - aceptar;
   - corregir;
   - ampliar diagnóstico;
   - revertir;
   - siguiente bloque.

9. Se emite nueva Work Order.
```

Este ciclo será la base del desarrollo futuro.

---

# L. CLAUDE COMO AMPLIACIÓN DE CAPACIDAD

El uso de Claude deberá entenderse como una ampliación de capacidad operativa.

Permitirá:

* trabajar sobre repositorios más grandes;
* inspeccionar más contexto;
* realizar cambios coordinados;
* ejecutar suites;
* diagnosticar dependencias;
* disminuir el trabajo manual de copiar/pegar código.

No supone delegar el control intelectual o arquitectónico del proyecto.

---

# LI. PRINCIPIO DE NO PÉRDIDA DE CONTEXTO

Una de las obligaciones fundamentales del nuevo modelo será evitar que el cambio de herramienta provoque pérdida de decisiones acumuladas.

Toda Work Order deberá partir de:

```text
estado actual real
+
resoluciones vigentes
+
contratos existentes
+
evidencia acumulada
```

y nunca de una interpretación del proyecto como si comenzara desde cero.

---

# LII. CAMBIO DE EJECUTOR, NO CAMBIO DE PROYECTO

Se establece expresamente como doctrina oficial:

> **Quesada Abogados no migra su arquitectura a Claude. Quesada Abogados incorpora Claude como ejecutor especializado dentro de una arquitectura y metodología ya existentes.**

El proyecto continúa siendo el mismo.

Sus objetivos continúan siendo los mismos.

Sus contratos continúan siendo los mismos.

Sus resoluciones continúan siendo vinculantes.

---

# LIII. APLICACIÓN INMEDIATA

La presente resolución tendrá efecto inmediato.

El bloque actual:

```text
QCC / AUTO TWIN / Mercurio
```

podrá utilizarse como primer desarrollo bajo el nuevo modelo.

La situación funcional y técnica alcanzada hasta este momento se considerará el punto inicial del nuevo sistema de ejecución.

No deberá repetirse investigación ya cerrada salvo que la evidencia del repositorio contradiga expresamente lo conocido.

---

# LIV. PRINCIPIO FINAL

A partir de esta resolución, el desarrollo de Quesada Abogados seguirá el siguiente modelo:

```text
PENSAR
        ↓
DISEÑAR
        ↓
ESPECIFICAR
        ↓
EJECUTAR
        ↓
DEMOSTRAR
        ↓
REVISAR
        ↓
CONSOLIDAR
```

con la siguiente distribución:

```text
Quesada Abogados
= autoridad y objetivos

ChatGPT
= cerebro técnico, arquitectura y dirección

Claude
= ejecución de código y evidencia

Git
= historia y fuente del código

Tests
= contrato ejecutable

Resoluciones
= autoridad normativa
```

---

# 🔒 CIERRE

Queda aprobado el nuevo modelo de desarrollo asistido mediante dirección técnica centralizada y ejecución de código mediante Claude.

Este cambio se adopta para responder al incremento de escala y complejidad del proyecto sin renunciar a ninguno de los principios técnicos, funcionales, metodológicos o arquitectónicos construidos hasta la fecha.

El incremento de capacidad de ejecución deberá producir:

```text
más velocidad
sin perder control,

más capacidad
sin perder arquitectura,

más automatización
sin perder supervisión,

y más complejidad
sin perder gobernanza.
```

**Toda resolución anterior continuará vigente salvo modificación o derogación expresa mediante resolución posterior.**
