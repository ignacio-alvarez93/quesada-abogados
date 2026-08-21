# RESOLUCIÓN SOBRE QUESADA CHROME COMPANION — QCC

**Proyecto:** Quesada Abogados ERP
**Fecha:** 21 de agosto de 2026
**Estado de referencia:** rama `develop`
**Naturaleza:** Resolución técnica y funcional vinculante
**Ámbito:** Chrome, extensiones, automatización asistida, SeleniumBase/CDP, Mercurio, ICP Plus, futuras sedes electrónicas, Centro de Actividades Administrativas, Expedientes y Trazabilidad
**Nombre oficial:** **Quesada Chrome Companion**
**Acrónimo oficial:** **QCC**

---

# I. OBJETO

La presente resolución aprueba la creación de **Quesada Chrome Companion (QCC)** como extensión oficial de Chrome integrada en el ecosistema Quesada Abogados ERP.

QCC constituirá la interfaz operativa contextual del ERP cuando el usuario se encuentre trabajando dentro del navegador, especialmente durante:

* presentaciones administrativas;
* automatizaciones asistidas;
* tramitaciones en sedes electrónicas;
* carga de formularios;
* aportación documental;
* consultas administrativas;
* ejecución de actividades del CAA;
* supervisión de automatizaciones.

Su primera aplicación será la modernización de la **Presentación Asistida**, sustituyendo progresivamente la ventana CMD visible por un panel lateral integrado en Chrome.

---

# II. DEFINICIÓN OFICIAL

Se define:

> **Quesada Chrome Companion es la interfaz contextual del ERP Quesada Abogados dentro del navegador Chrome.**

QCC no será:

* un segundo CRM;
* una segunda base de datos;
* un backend paralelo;
* un nuevo motor Selenium;
* una automatización independiente;
* una sustitución del ERP Flet.

QCC será:

```text
ERP Quesada Abogados
        ↓
contexto operativo
        ↓
Chrome
        ↓
Quesada Chrome Companion
```

Su función será acompañar al usuario mientras trabaja sobre una sede electrónica o mientras una automatización del ERP ejecuta una actividad en Chrome.

---

# III. PRINCIPIO GENERAL

Se adopta como principio rector:

> **El CRM gobierna.
> El runtime ejecuta.
> Chrome muestra la sede.
> QCC explica, contextualiza y permite supervisar la actividad.**

La extensión no deberá convertirse en fuente independiente de estado de negocio.

La autoridad continuará perteneciendo a los dominios del ERP.

---

# IV. RELACIÓN ENTRE EL CRM Y QCC

Se establece la siguiente separación:

## ERP Flet

Será la interfaz principal para:

* Clientes;
* Expedientes;
* Económico;
* Comunicaciones;
* Documentación;
* CAA;
* Notificaciones;
* Reporting;
* configuración;
* gestión general del despacho.

## QCC

Será la interfaz contextual cuando el trabajo se esté desarrollando dentro de Chrome.

Mostrará exclusivamente la información necesaria para la actividad actual.

Ejemplo:

```text
ERP Flet
→ visión global

QCC
→ visión contextual de la actividad que se está ejecutando
```

---

# V. ARQUITECTURA GENERAL

La arquitectura objetivo será:

```text
┌────────────────────────────────────────────┐
│                  CHROME                    │
│                                            │
│ ┌──────────────────────┐ ┌───────────────┐ │
│ │                      │ │      QCC      │ │
│ │ MERCURIO / ICP PLUS  │ │  SIDE PANEL   │ │
│ │ UGE / SEDE / DEHÚ    │ │               │ │
│ │                      │ │ Cliente       │ │
│ │ Web administrativa   │ │ Expediente    │ │
│ │                      │ │ Estado        │ │
│ │                      │ │ Progreso      │ │
│ │                      │ │ Eventos       │ │
│ │                      │ │ Acciones      │ │
│ └──────────────────────┘ └───────────────┘ │
└────────────────────────────────────────────┘
                       │
                       │ canal local
                       ▼
┌────────────────────────────────────────────┐
│           QUESADA BACKEND PYTHON           │
│                                            │
│ QCC Bridge / Gateway                       │
│ Presentation Runtime                       │
│ CAA / TASK                                 │
│ Expedientes                                │
│ Trazabilidad                               │
│ Documental                                 │
│ SeleniumBase / Browser Runtime             │
└────────────────────────────────────────────┘
```

---

# VI. TECNOLOGÍA DE LA EXTENSIÓN

QCC se desarrollará como extensión Chrome basada en:

```text
Manifest V3
Chrome Side Panel
HTML
CSS
JavaScript
```

La interfaz principal utilizará el panel lateral nativo de Chrome.

La V1 deberá evitar introducir frameworks JavaScript innecesarios.

Se priorizarán:

* simplicidad;
* rapidez;
* robustez;
* bajo consumo;
* facilidad de mantenimiento;
* independencia respecto del frontend Flet.

La incorporación futura de un framework deberá justificarse por necesidad real.

---

# VII. PRINCIPIO DE NO INTERFERENCIA CON EL DOM

Se establece como regla fundamental:

> **QCC no modificará el DOM de Mercurio ni de otras sedes electrónicas salvo que una funcionalidad futura sea expresamente diseñada, justificada y aprobada para ello.**

La V1 deberá operar como panel independiente.

Por tanto:

```text
SeleniumBase / runtime
→ controla la sede

QCC
→ muestra información del runtime
```

No existirán dos motores compitiendo por controlar la misma página.

---

# VIII. SELENIUMBASE Y QCC

QCC no accederá directamente a SeleniumBase.

Queda prohibida una arquitectura:

```text
QCC
→ SeleniumBase
→ Chrome
```

La arquitectura obligatoria será:

```text
QCC
        ↓
QCC Bridge
        ↓
Application / Runtime
        ↓
Connector
        ↓
Browser Runtime
        ↓
SeleniumBase / Chrome
```

QCC será consumidor del estado generado por los runtimes.

---

# IX. QCC BRIDGE

Se aprueba la creación de una capa de comunicación local denominada provisionalmente:

```text
QCC Bridge
```

Su misión será comunicar:

```text
Extensión Chrome
↔
Backend Quesada Abogados
```

El primer diseño deberá priorizar un canal local mediante:

```text
HTTP localhost
y/o
WebSocket localhost
```

El contrato deberá diseñarse de forma que pueda sustituirse posteriormente el transporte sin modificar la semántica del sistema.

QCC Bridge no contendrá lógica jurídica.

Será infraestructura de comunicación.

---

# X. PROHIBICIÓN DE ACCESO DIRECTO A LA BASE DE DATOS

Queda expresamente prohibido:

```text
QCC
→ SQLite
```

```text
QCC
→ PostgreSQL
```

```text
QCC
→ Supabase
```

La extensión nunca accederá directamente a las tablas operativas del ERP.

Toda lectura o mutación deberá pasar por servicios backend.

La migración futura de SQLite a PostgreSQL/Supabase no deberá exigir modificaciones sustanciales en QCC.

---

# XI. CONTRATO DE EVENTOS

Se aprueba la creación de un protocolo genérico de eventos operativos.

Entre otros:

```text
presentation.started

presentation.context_loaded

presentation.step_started

presentation.step_completed

presentation.progress_changed

presentation.document_upload_started

presentation.document_uploaded

presentation.waiting_user

presentation.user_action_detected

presentation.warning

presentation.error

presentation.completed

presentation.cancelled
```

Los nombres definitivos podrán evolucionar durante la implementación.

La semántica deberá mantenerse independiente de Mercurio.

---

# XII. EVENTO GENÉRICO

Los eventos deberán transportar únicamente la información necesaria.

Ejemplo conceptual:

```json
{
  "event": "presentation.step_changed",
  "expedient_id": 1842,
  "procedure": "REAGRUPACION_FAMILIAR_INICIAL",
  "step": "UPLOAD_DOCUMENTS",
  "progress": 68,
  "message": "Adjuntando certificado de matrimonio"
}
```

No deberán transmitirse indiscriminadamente:

* contraseñas;
* cookies;
* certificados;
* tokens;
* datos internos del navegador;
* HTML completo;
* DOM completo;
* secretos;
* información personal innecesaria.

---

# XIII. ESTADO CANÓNICO

QCC no será autoridad del estado de una presentación.

El estado canónico residirá en:

```text
Presentation Runtime
/
CAA-TASK
/
Expediente
/
Trazabilidad
```

según corresponda.

QCC será una proyección visual.

Se aplicará el mismo principio arquitectónico utilizado en otras áreas:

```text
dominio
→ evento
→ proyección
```

y nunca:

```text
panel visual
→ fuente de verdad
```

---

# XIV. PRESENTATION SESSION

Se aprueba conceptualmente la entidad o contrato:

```text
Presentation Session
```

que permitirá identificar una ejecución concreta.

Deberá poder contener:

```text
session_id
expedient_id
client_id
procedure
provider
runtime
started_at
status
current_step
progress
requires_user_action
last_event
```

La implementación definitiva deberá decidir qué información es persistente y cuál pertenece exclusivamente al runtime.

---

# XV. PRIMER CASO DE USO — PRESENTACIÓN ASISTIDA

La primera funcionalidad productiva de QCC será:

```text
QCC PRESENTATION COMPANION
```

Su finalidad será acompañar la presentación asistida de un expediente.

La V1 deberá poder mostrar:

```text
Cliente
Expediente
Procedimiento
Sede
Estado de conexión
Estado de automatización
Paso actual
Progreso
Últimos eventos
Documentos procesados
Warnings
Errores
Necesidad de intervención humana
Resultado final
```

---

# XVI. INTERFAZ OBJETIVO DE PRESENTACIÓN

La interfaz conceptual será:

```text
QUESADA ABOGADOS

JUAN PÉREZ
EXP-2026-01842
Reagrupación Familiar · Inicial

● CONECTADO

Presentación asistida

✓ Sesión iniciada
✓ Procedimiento seleccionado
✓ Datos del reagrupante
✓ Datos del familiar
✓ Domicilio
● Documentación
○ Revisión
○ Firma
○ Presentación

Progreso
━━━━━━━━━━━━━━░░░ 68 %

PASO ACTUAL
Adjuntando certificado de matrimonio

DOCUMENTOS
✓ Pasaporte
✓ Empadronamiento
✓ Medios económicos
→ Certificado de matrimonio
○ Vivienda

INTERVENCIÓN HUMANA
Mercurio está preparado para continuar.

ACTIVIDAD
22:57:03 NIE completado
22:57:04 Provincia seleccionada
22:57:06 EX02 cargado
22:57:11 Documento aportado
```

Este diseño servirá como referencia funcional y no como contrato visual rígido.

---

# XVII. INTERVENCIÓN HUMANA

QCC deberá representar expresamente los momentos en los que el sistema requiere intervención humana.

Estados posibles:

```text
AUTOMATING
WAITING_USER
USER_ACTION_DETECTED
RESUMING
COMPLETED
ERROR
```

o equivalentes.

Se mantiene el principio:

> **La automatización asiste y el profesional conserva el control.**

Cuando una sede requiera una actuación manual, QCC deberá explicarla claramente.

Ejemplo:

```text
Todo preparado.

Continúe manualmente en Mercurio.

QCC detectará automáticamente el cambio de pantalla.
```

---

# XVIII. ACCIONES SENSIBLES

QCC no deberá convertir automáticamente una acción sensible en una acción autónoma simplemente porque exista un botón en el panel.

Se consideran sensibles, entre otras:

* presentación definitiva;
* firma;
* envío;
* aceptación de declaraciones;
* actuaciones irreversibles;
* operaciones con efectos jurídicos.

Cualquier automatización futura de estas acciones deberá aprobarse de forma específica.

---

# XIX. LOGS TÉCNICOS

QCC sustituirá progresivamente la necesidad de visualizar una consola CMD, pero no eliminará el logging técnico.

Se distinguirán:

## Log operativo

Visible en QCC.

Ejemplo:

```text
Documento aportado correctamente.
```

## Log técnico

Conservado por backend.

Ejemplo:

```text
selector
attempt
elapsed_ms
URL
connector
runtime
exception
traceback
```

La desaparición de CMD como interfaz no supondrá pérdida de capacidad diagnóstica.

---

# XX. CMD Y WORKERS

El objetivo de arquitectura será que los procesos técnicos de automatización puedan ejecutarse sin necesidad de mantener una ventana CMD visible al usuario.

El escritorio objetivo será:

```text
ERP Flet
+
Chrome con QCC
```

Los workers seguirán existiendo cuando sean necesarios, pero quedarán tratados como infraestructura interna.

---

# XXI. PROVEEDORES

QCC deberá ser agnóstico respecto de la sede.

Se establece el concepto:

```text
provider
```

Inicialmente podrá incluir:

```text
MERCURIO
ICP_PLUS
```

y posteriormente:

```text
UGE
DEHU
POLICIA
REGISTRO_CIVIL
CONSULAR
OTRAS_SEDES
```

La extensión no deberá contener lógica jurídica específica de cada proveedor salvo información puramente visual.

---

# XXII. MERCURIO

Mercurio será el primer gran candidato para integración QCC.

La introducción de QCC no deberá alterar inicialmente:

* mappers;
* formularios;
* carga documental;
* datos específicos;
* SeleniumBase;
* conectores;
* lógica de navegación;
* Trazabilidad;
* justificantes;
* comportamiento funcional ya consolidado.

La primera integración será:

```text
Mercurio existente
+
emisión de eventos QCC
```

y no:

```text
reescritura de Mercurio para QCC
```

---

# XXIII. ICP PLUS

QCC deberá diseñarse desde el inicio para poder representar ejecuciones de ICP Plus.

El panel podrá mostrar:

* provincia;
* oficina;
* trámite;
* estado;
* fase actual;
* ejecución programada;
* resultado;
* intervención requerida;
* incidencias.

La arquitectura no deberá asumir que todas las automatizaciones se ejecutan mediante SeleniumBase.

QCC consumirá eventos del runtime independientemente de la tecnología de automatización utilizada.

---

# XXIV. CAA

En fases posteriores QCC deberá integrarse con el Centro de Actividades Administrativas.

El modelo objetivo será:

```text
TASK
↓
CAA
↓
runtime especializado
↓
Chrome
↓
QCC
```

QCC mostrará la ejecución de la TASK, pero no creará una unidad paralela de trabajo.

---

# XXV. CONTEXTO DEL EXPEDIENTE

QCC podrá mostrar progresivamente información contextual del expediente.

Ejemplos:

```text
cliente
expediente
tipo
subtipo
responsable
documentos
checklist
observaciones
estado documental
estado administrativo
TASK actual
```

Los datos serán obtenidos exclusivamente mediante backend.

---

# XXVI. DOCUMENTACIÓN

La integración documental futura podrá permitir mostrar:

```text
documentos previstos
documentos aportados
documentos omitidos
documentos pendientes
documentos con error
```

QCC no deberá convertirse en almacenamiento documental.

Box y el sistema documental continuarán siendo las fuentes correspondientes.

---

# XXVII. TRAZABILIDAD

Los hitos relevantes de una automatización podrán generar eventos de Trazabilidad cuando tengan significado de dominio.

No todo evento visual de QCC deberá convertirse en trazabilidad.

Ejemplo:

```text
campo rellenado
→ evento técnico

expediente presentado
→ evento de dominio / Trazabilidad
```

La distinción deberá conservarse.

---

# XXVIII. SEGURIDAD

QCC deberá seguir el principio de mínimo privilegio.

La extensión deberá solicitar únicamente los permisos estrictamente necesarios.

Se evitará solicitar acceso global a todas las páginas de Internet si no es necesario.

Los permisos sobre hosts deberán limitarse progresivamente a:

* localhost del bridge;
* sedes específicamente soportadas cuando una funcionalidad lo requiera.

No se almacenarán secretos en:

```text
localStorage
chrome.storage
JavaScript
manifest
repositorio
```

cuando puedan ser evitados.

---

# XXIX. AUTENTICACIÓN DEL BRIDGE

QCC Bridge no deberá confiar únicamente en que la conexión procede de `localhost`.

Antes de una versión productiva se deberá implementar un mecanismo de autenticación o emparejamiento local.

El objetivo será evitar que otra página o proceso local pueda ejecutar operaciones del ERP mediante el bridge.

---

# XXX. DISPONIBILIDAD DEL BRIDGE

QCC deberá poder diferenciar:

```text
CRM OFFLINE
BRIDGE OFFLINE
RUNTIME OFFLINE
CONNECTED
AUTOMATING
WAITING USER
ERROR
```

La ausencia del ERP no deberá provocar errores indefinidos en la extensión.

---

# XXXI. PRINCIPIO DE DEGRADACIÓN SEGURA

Si QCC falla:

```text
Mercurio
SeleniumBase
ERP
```

no deberán quedar necesariamente inutilizados.

La V1 deberá diseñarse de manera que QCC sea una capa adicional de supervisión.

La automatización existente deberá conservar, cuando resulte técnicamente razonable, capacidad de diagnóstico independiente.

---

# XXXII. ESTRUCTURA DEL REPOSITORIO

Se aprueba como ubicación inicial:

```text
chrome_extension/
└── qcc/
    ├── manifest.json
    ├── background/
    ├── sidepanel/
    ├── assets/
    ├── js/
    └── css/
```

Y en backend:

```text
backend/
├── qcc/
│   ├── bridge/
│   ├── contracts/
│   └── events/
```

La estructura definitiva podrá simplificarse durante la primera implementación.

Se priorizará separación clara entre:

```text
extensión
bridge
contratos
runtime
dominio
```

---

# XXXIII. NO DUPLICACIÓN DEL FRONTEND FLET

No deberán copiarse masivamente vistas Flet dentro de QCC.

QCC tendrá su propio sistema visual adaptado a un panel estrecho.

El hecho de que exista:

```text
clients_view.py
```

no implica crear:

```text
clients_view.js
```

El modelo correcto será:

```text
Backend común
      ↑        ↑
     Flet     QCC
```

Dos interfaces.

Una misma autoridad de negocio.

---

# XXXIV. IDENTIDAD VISUAL

QCC deberá mantener coherencia con la identidad visual del ERP.

Se favorecerán:

* tipografía clara;
* estructura compacta;
* densidad operativa;
* jerarquía visual;
* estados mediante iconos/chips;
* colores coherentes;
* reducción de ruido.

El panel deberá estar diseñado específicamente para utilizarse simultáneamente con una sede electrónica.

---

# XXXV. ESTADOS DE COLOR

La interfaz deberá reservar significados visuales consistentes.

Orientativamente:

```text
verde
→ completado / correcto

azul
→ activo / ejecutando

ámbar
→ intervención / warning

rojo
→ error

gris
→ pendiente / inactivo
```

La implementación deberá respetar accesibilidad y legibilidad.

---

# XXXVI. ACCIONES DESDE QCC

La V1 será prioritariamente de observación y control ligero.

Podrá incorporar acciones seguras como:

```text
abrir expediente en CRM
reintentar operación técnica segura
cancelar actividad si el runtime lo permite
copiar referencia
abrir log
confirmar una revisión
```

Las acciones de dominio deberán ejecutarse siempre mediante backend/application services.

---

# XXXVII. COMUNICACIÓN INTERNA DE LA EXTENSIÓN

La extensión podrá utilizar los mecanismos de mensajería internos de Chrome para comunicar:

```text
Side Panel
↔
Service Worker
↔
otros contextos de la propia extensión
```

Los detalles internos no deberán filtrarse al backend.

El backend deberá recibir un contrato QCC independiente de la arquitectura interna de Chrome.

---

# XXXVIII. API INTERNA QCC

Se deberá definir una API mínima versionable.

Ejemplo conceptual:

```text
GET /qcc/health

GET /qcc/context

GET /qcc/session/{id}

POST /qcc/session/{id}/action

WS /qcc/events
```

Las rutas definitivas se aprobarán durante la implementación.

La API deberá permanecer pequeña.

---

# XXXIX. VERSIONADO DEL PROTOCOLO

El protocolo QCC deberá disponer desde una fase temprana de una versión.

Ejemplo:

```text
qcc_protocol_version = 1
```

Esto permitirá evolucionar backend y extensión de forma controlada.

---

# XL. TESTING

QCC deberá adoptar el sistema de blindaje del proyecto.

Se crearán progresivamente:

## Tests de contratos

* serialización de eventos;
* estados;
* contexto;
* versiones del protocolo.

## Tests de backend

* QCC Bridge;
* sesiones;
* health;
* autorización de acciones;
* idempotencia.

## Tests de extensión

* recepción de eventos;
* actualización del panel;
* reconexión;
* estados offline;
* errores.

## Tests de integración

```text
runtime
→ QCC event
→ bridge
→ side panel
```

No deberán necesitarse sedes reales para la mayoría de tests.

---

# XLI. SMOKE REAL

Cada integración con una sede deberá disponer de un smoke explícito y controlado.

Para Mercurio:

```text
abrir sesión
→ ejecutar flujo asistido
→ emitir eventos
→ comprobar QCC
→ comprobar ausencia de regresión
```

La introducción de QCC no deberá convertir pruebas ordinarias en pruebas dependientes de Internet.

---

# XLII. OBSERVABILIDAD

QCC deberá permitir diagnosticar:

```text
bridge conectado
runtime conectado
provider
session_id
último evento
último heartbeat
último error
estado de reconexión
```

No deberá ser necesario abrir herramientas de desarrollo para conocer el estado básico del sistema.

---

# XLIII. RECONEXIÓN

La extensión deberá tolerar:

* reinicio del ERP;
* reinicio del bridge;
* recarga del panel;
* cierre y reapertura del Side Panel;
* navegación entre pestañas;
* pérdida temporal de conexión.

Tras reconectar deberá solicitar el snapshot actual de estado.

No deberá depender únicamente de eventos que ocurrieron mientras estaba desconectada.

---

# XLIV. SNAPSHOT + EVENTOS

Se adopta el patrón:

```text
SNAPSHOT
+
EVENT STREAM
```

Al abrir QCC:

```text
GET current state
```

Después:

```text
subscribe events
```

Esto evitará inconsistencias por eventos perdidos.

---

# XLV. MULTIPLICIDAD DE PESTAÑAS

La arquitectura deberá prever que puedan existir varias pestañas de Chrome.

QCC deberá saber a qué sesión corresponde la actividad mostrada.

No se asumirá permanentemente:

```text
1 Chrome
=
1 tab
=
1 presentación
```

aunque la primera V1 pueda trabajar inicialmente con una única presentación activa.

---

# XLVI. SESIONES SIMULTÁNEAS

La V1 podrá limitar la ejecución a:

```text
1 presentación asistida activa
```

si ello aumenta la robustez.

La arquitectura del protocolo no deberá impedir soportar posteriormente varias sesiones.

---

# XLVII. PRIMERA VERSIÓN — QCC V1

Se aprueba como alcance inicial:

```text
Manifest V3
Side Panel
QCC Bridge localhost
Health
Conexión/reconexión
Presentation Session
Snapshot
Event Stream
Cliente
Expediente
Procedimiento
Provider
Paso actual
Progreso
Timeline reciente
WAITING_USER
WARNING
ERROR
COMPLETED
```

Quedan fuera inicialmente:

* replicación completa del CRM;
* edición integral del cliente;
* edición integral del expediente;
* comunicaciones completas;
* documentos complejos;
* múltiples automatizaciones simultáneas;
* modificación del DOM;
* Native Messaging;
* publicación en Chrome Web Store.

---

# XLVIII. QCC V2

Una segunda fase podrá incorporar:

```text
checklist documental
documentos aportados
contexto ampliado del expediente
acciones seguras
CAA/TASK
observaciones
errores recuperables
diagnóstico avanzado
```

---

# XLIX. QCC V3

Una fase posterior podrá convertir QCC en una verdadera consola contextual del ERP dentro del navegador.

Podrá incorporar:

```text
Expediente
Documentos
CAA
Trazabilidad
Comunicaciones
Notificaciones
automatizaciones disponibles
acciones contextuales
```

Siempre sin sustituir el ERP principal.

---

# L. QCC COMO PLATAFORMA TRANSVERSAL

Se establece que QCC deberá diseñarse como infraestructura reutilizable.

El objetivo futuro será:

```text
Mercurio ───────┐
ICP Plus ───────┤
UGE ────────────┤
DEHú ───────────┤
Policía ────────┤
Registro Civil ─┤
Consulados ─────┤
otras sedes ────┘
        ↓
 Presentation / Automation Runtime
        ↓
       QCC
```

Cada automatización deberá emitir contratos comunes siempre que resulte posible.

---

# LI. RELACIÓN CON LA INFRAESTRUCTURA DE NAVEGADOR

QCC respetará la infraestructura común de automatización.

Se mantiene:

```text
Caso de uso
→ Application Service
→ Runtime específico
→ Connector específico
→ Browser Runtime
→ SeleniumBase / CDP / tecnología correspondiente
→ Chrome
```

QCC se conectará por encima de estas capas.

No será un nuevo controlador del browser.

---

# LII. PRINCIPIO DE INDEPENDENCIA TECNOLÓGICA

Aunque SeleniumBase sea actualmente una infraestructura fundamental del proyecto, QCC no deberá depender directamente de sus APIs.

Esto permitirá utilizar QCC también con automatizaciones basadas en:

* Chrome normal;
* CDP;
* eventos de escritorio;
* APIs;
* otros motores futuros.

El contrato será:

```text
runtime
→ eventos QCC
```

no:

```text
SeleniumBase
→ eventos QCC
```

---

# LIII. GOBIERNO DEL DESARROLLO

QCC se desarrollará mediante rama específica.

Se aprueba inicialmente:

```text
feature/qcc-chrome-companion
```

No deberá desarrollarse directamente sobre `develop`.

La metodología será:

```text
diagnóstico
→ contrato
→ implementación mínima
→ tests
→ smoke
→ commit
→ siguiente bloque
```

---

# LIV. PRIMER ORDEN DE DESARROLLO

Se establece la siguiente secuencia:

## QCC-0 — Resolución y rama

* aprobar resolución;
* crear rama;
* definir estructura.

## QCC-1 — Extension Shell

* `manifest.json`;
* Side Panel;
* UI básica;
* estado offline.

## QCC-2 — Bridge

* backend localhost;
* health;
* autenticación inicial;
* CORS/origin policy adecuada.

## QCC-3 — Protocol

* snapshot;
* eventos;
* versionado;
* contratos Python/JS.

## QCC-4 — Presentation Mock

* simulador de presentación;
* pasos;
* progreso;
* WAITING_USER;
* ERROR;
* COMPLETED.

## QCC-5 — Mercurio Adapter

* emisión de eventos desde presentación asistida existente;
* sin modificar su comportamiento.

## QCC-6 — Eliminación visual de CMD

* worker silencioso;
* logging a fichero/backend;
* QCC como interfaz operativa.

## QCC-7 — CAA Context

* TASK;
* expediente;
* actividad.

## QCC-8 — ICP Plus

* integración del runtime ICP Plus.

---

# LV. CRITERIO DE ACEPTACIÓN DE QCC V1

QCC V1 se considerará completado cuando pueda demostrarse:

```text
1. Chrome abre QCC en Side Panel.

2. QCC detecta si el backend está disponible.

3. QCC recibe el contexto de una presentación.

4. Muestra cliente y expediente.

5. Muestra procedimiento y provider.

6. Muestra el paso actual.

7. Muestra progreso.

8. Recibe eventos en tiempo real.

9. Representa WAITING_USER.

10. Representa WARNING.

11. Representa ERROR.

12. Representa COMPLETED.

13. Puede reconectarse.

14. No accede directamente a la base de datos.

15. No controla SeleniumBase.

16. No modifica el DOM de Mercurio.

17. Mercurio sigue funcionando sin regresión.

18. Existen tests del protocolo.

19. Existen tests del bridge.

20. Existe smoke real controlado.
```

---

# LVI. OBJETIVO OPERATIVO FINAL

El usuario no deberá necesitar interpretar una consola técnica para conocer el estado de una presentación.

La experiencia objetivo será:

```text
CRM
→ selecciono actividad

Chrome
→ abre sede

QCC
→ muestra contexto y progreso

automatización
→ trabaja

QCC
→ informa

usuario
→ interviene cuando corresponde

runtime
→ continúa

Trazabilidad
→ registra el resultado jurídico
```

---

# LVII. VISIÓN ESTRATÉGICA

QCC permitirá transformar Chrome en una extensión natural del ERP.

El navegador dejará de ser únicamente:

```text
el lugar donde Selenium hace clicks
```

y pasará a ser:

```text
el entorno operativo donde el profesional
puede ver simultáneamente

la sede administrativa
+
el contexto del expediente
+
el estado de la automatización.
```

---

# LVIII. DECISIÓN FINAL

Se aprueba oficialmente la creación de:

# QUESADA CHROME COMPANION — QCC

como interfaz contextual de Quesada Abogados ERP dentro de Chrome.

Se establecen como principios vinculantes:

1. QCC no será un segundo CRM.
2. Flet continuará siendo la interfaz principal del ERP.
3. QCC será la interfaz contextual del trabajo realizado dentro del navegador.
4. QCC utilizará inicialmente Chrome Side Panel.
5. QCC no accederá directamente a base de datos.
6. QCC no controlará directamente SeleniumBase.
7. QCC no modificará inicialmente el DOM de las sedes.
8. QCC se comunicará con backend mediante QCC Bridge.
9. El protocolo se basará en snapshot + eventos.
10. QCC será agnóstico respecto del proveedor.
11. Mercurio será el primer flujo de presentación asistida integrado.
12. La integración de Mercurio será aditiva y sin reescritura.
13. ICP Plus deberá poder utilizar posteriormente la misma infraestructura.
14. QCC podrá integrarse progresivamente con CAA/TASK.
15. Los logs técnicos continuarán existiendo aunque desaparezca la CMD visible.
16. QCC deberá tolerar desconexiones y reconectarse.
17. Se aplicará mínimo privilegio y minimización de datos.
18. Las acciones sensibles mantendrán control humano cuando corresponda.
19. QCC tendrá tests contractuales y de integración.
20. Todo desarrollo se realizará incrementalmente y protegido contra regresiones.

Se fija como objetivo estratégico:

> **Convertir Chrome en el entorno operativo contextual de Quesada Abogados cuando una actividad del ERP se desarrolla en una sede electrónica, manteniendo al ERP como autoridad, a los runtimes como ejecutores y al profesional como supervisor final.**

**Estado de la resolución:** APROBADA COMO ARQUITECTURA OFICIAL DE QUESADA CHROME COMPANION.
