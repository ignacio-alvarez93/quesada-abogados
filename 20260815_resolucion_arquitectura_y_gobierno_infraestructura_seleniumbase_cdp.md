# RESOLUCIÓN SOBRE ARQUITECTURA, GOBIERNO E INFRAESTRUCTURA COMÚN DE AUTOMATIZACIÓN SELENIUMBASE / CDP

**Proyecto:** Quesada Abogados ERP  
**Fecha:** 15 de agosto de 2026  
**Estado de referencia:** rama `feature/client-communications-whatsapp`  
**Naturaleza:** Resolución técnica vinculante  
**Ámbito:** Automatización de navegador, SeleniumBase, Chrome DevTools Protocol, sesiones persistentes, perfiles de navegador, runtimes, conectores, concurrencia, ciclo de vida, observabilidad, testing y protección de automatizaciones existentes  
**Versiones de referencia de la investigación:** Python 3.11, SeleniumBase 4.47.1, Windows, Flet 0.84.0  
**Automatizaciones expresamente protegidas:** WhatsApp, Mercurio y desarrollos existentes que utilicen SeleniumBase/CDP  
**Estado de la infraestructura común:** diseño aprobado; implementación incremental pendiente  
**Principio rector:** construir infraestructura común sin reescribir, degradar ni romper automatizaciones productivas ya consolidadas

---

# I. OBJETO

La presente resolución establece la arquitectura obligatoria y las reglas de gobierno que deberán regir toda automatización de navegador desarrollada o mantenida dentro de Quesada Abogados ERP.

La resolución nace como consecuencia de la evolución técnica experimentada durante el desarrollo del módulo de Comunicaciones y, especialmente, de la integración de WhatsApp Web mediante SeleniumBase y Chrome DevTools Protocol.

La investigación realizada ha demostrado que el navegador no puede seguir siendo tratado como un recurso auxiliar creado y destruido libremente por cada funcionalidad.

Una sesión de automatización moderna puede implicar simultáneamente:

- proceso Chrome;
- perfil persistente;
- wrapper SeleniumBase;
- Browser CDP;
- conexiones WebSocket;
- páginas y tabs;
- event loops;
- tareas asyncio;
- listeners;
- threads;
- procesos auxiliares;
- estado de autenticación;
- estado funcional del proveedor;
- ownership del navegador;
- lifecycle de aplicación;
- watchers;
- serialización de operaciones;
- recursos cuya destrucción puede afectar al cierre completo del proceso Python.

Por tanto, la automatización de navegador pasa a considerarse **infraestructura transversal de primer nivel del ERP**.

Se establece el siguiente principio:

> SeleniumBase/CDP no será una implementación privada de cada módulo. Será una infraestructura común gobernada por contratos explícitos de sesión, ownership, ejecución, observabilidad y ciclo de vida.

---

# II. FINALIDAD DE LA RESOLUCIÓN

La presente resolución persigue simultáneamente los siguientes objetivos:

1. crear una infraestructura común y robusta para SeleniumBase/CDP;

2. proteger las automatizaciones actualmente funcionales;

3. evitar que cada nuevo módulo cree su propia arquitectura de navegador;

4. eliminar progresivamente duplicaciones técnicas;

5. garantizar que WhatsApp y Mercurio puedan evolucionar sin ser reescritos innecesariamente;

6. proporcionar una base reutilizable para DEHú y futuras automatizaciones;

7. evitar interferencias con el trabajo manual del usuario;

8. definir ownership inequívoco de navegador, perfil, worker, threads y lifecycle;

9. establecer contratos de cierre seguros;

10. aumentar la capacidad de diagnóstico de problemas de Chrome, CDP, WebSocket, subprocess y asyncio;

11. impedir que detalles internos de SeleniumBase se propaguen por todo el ERP;

12. permitir futuras sustituciones o actualizaciones de SeleniumBase sin reescribir los casos de uso;

13. proteger las automatizaciones frente a regresiones;

14. establecer contratos compatibles con procesos de larga duración;

15. preparar la infraestructura para un ERP multiusuario y para futuras ejecuciones distribuidas cuando proceda.

---

# III. DECLARACIÓN DE INFRAESTRUCTURA TRANSVERSAL

Se declara que la automatización de navegador constituye un dominio técnico transversal del ERP.

Su arquitectura objetivo será conceptualmente:

`Caso de uso`
→ `Application Service`
→ `Runtime específico`
→ `Connector específico`
→ `Browser Runtime / Session Infrastructure`
→ `SeleniumBase / CDP`
→ `Chrome`

Ejemplos:

`WhatsApp`
→ `WhatsAppRuntimeService`
→ `WhatsAppConnector`
→ `BrowserSession`
→ `SeleniumBase CDP`

`Mercurio`
→ `Mercurio Service / Runtime`
→ `Mercurio Connector`
→ `BrowserSession`
→ `SeleniumBase CDP`

`DEHú`
→ `DEHU Service / Runtime`
→ `DEHU Connector`
→ `BrowserSession`
→ `SeleniumBase CDP`

La capa común no deberá absorber reglas específicas de WhatsApp, Mercurio o DEHú.

La infraestructura común conocerá:

- creación de navegador;
- configuración;
- perfil;
- ownership;
- ejecución serializada;
- lifecycle;
- estado técnico;
- health;
- errores técnicos;
- políticas de retry;
- timeouts;
- cierre;
- telemetría técnica.

Los conectores conocerán:

- DOM específico;
- selectores;
- semántica del proveedor;
- navegación;
- acciones;
- lectura;
- parsing;
- identidad;
- reglas de interacción específicas.

Los servicios conocerán:

- casos de uso del ERP;
- reglas de negocio;
- persistencia;
- estados de dominio;
- coordinación con otras áreas.

---

# IV. PRINCIPIO DE NO REGRESIÓN

La creación de la nueva infraestructura no autoriza una reescritura general de automatizaciones existentes.

Queda establecido expresamente:

> La infraestructura común deberá introducirse mediante evolución incremental, compatibilidad y adapters, nunca mediante una sustitución masiva de código funcional.

Se prohíbe realizar como primera fase:

- una reescritura completa de WhatsApp;
- una reescritura completa de Mercurio;
- una sustitución global de todos los accesos SeleniumBase;
- cambios simultáneos de comportamiento funcional y arquitectura;
- refactorizaciones masivas sin tests de equivalencia;
- eliminación de mecanismos existentes antes de demostrar paridad.

El principio será:

`infraestructura nueva`
→ `compatibilidad`
→ `integración controlada`
→ `tests`
→ `smoke real`
→ `migración gradual`
→ `retirada de código antiguo cuando resulte segura`.

---

# V. PROTECCIÓN EXPRESA DEL MÓDULO WHATSAPP

El módulo WhatsApp se considera una implementación avanzada y no deberá utilizarse como terreno para experimentar refactorizaciones globales.

Quedan protegidos los siguientes principios arquitectónicos ya consolidados:

- un único runtime persistente durante la sesión ERP;
- un único navegador WhatsApp;
- perfil persistente independiente;
- inicio perezoso;
- SeleniumBase/CDP;
- operación sin dependencia del foco de escritorio;
- worker único serializado;
- watchers que no acceden directamente al browser;
- separación entre runtime, connector y servicios;
- persistencia fuera del connector;
- observación pasiva;
- navegación explícita;
- verificación fuerte de identidad antes de operaciones sensibles;
- watcher de chat activo;
- watcher de llamadas;
- observación de llamadas;
- adapter de dominio;
- reconciliación;
- sincronización incremental;
- conservación del estado de WhatsApp Web;
- independencia entre vista actualmente mostrada por Flet y funcionamiento del runtime.

La nueva infraestructura deberá inicialmente adaptarse a estos contratos.

No se modificará el comportamiento funcional de WhatsApp simplemente para acomodar una abstracción común.

Si una abstracción común no puede representar correctamente una necesidad de WhatsApp, deberá ampliarse la abstracción, no degradarse WhatsApp.

---

# VI. PROTECCIÓN EXPRESA DE MERCURIO

Mercurio constituye una automatización jurídica crítica para la presentación de expedientes.

La introducción de infraestructura común no deberá alterar de forma no controlada:

- navegación;
- autenticación;
- uso de certificado;
- preparación documental;
- formularios;
- presentación;
- aportación documental;
- comprobaciones;
- generación de justificantes;
- comportamiento actual de sesiones;
- compatibilidad con los flujos ya desarrollados.

Se aplicará el siguiente principio:

> Mercurio será integrado progresivamente en la infraestructura común mediante adapters o sustituciones locales de infraestructura, manteniendo intacta su semántica funcional.

No se realizará una reescritura conjunta de:

`automatización Mercurio`
+
`infraestructura browser`
+
`lógica de expedientes`

en una misma fase.

Cada transición deberá poder compararse con el comportamiento anterior.

---

# VII. PROTECCIÓN DE FUTURAS AUTOMATIZACIONES

Toda nueva automatización de navegador posterior a esta resolución deberá diseñarse desde el inicio sobre la infraestructura común.

Entre ellas podrán encontrarse:

- DEHú;
- sedes electrónicas;
- Policía;
- Registro Civil;
- plataformas consulares;
- certificados;
- portales administrativos;
- consultas de expedientes;
- portales de proveedores;
- automatizaciones internas.

No deberán crearse nuevos wrappers particulares de Chrome si la infraestructura común permite resolver el caso de uso.

---

# VIII. PROHIBICIÓN DE SELENIUMBASE EN FRONTEND

Queda expresamente prohibido importar o utilizar SeleniumBase directamente desde:

- `frontend/views/`;
- `frontend/components/`;
- `frontend/layouts/`.

También queda prohibido desde frontend acceder directamente a:

- browser;
- driver;
- tabs;
- WebSocket;
- event loops;
- CDP;
- `evaluate()`;
- `execute_script()`;
- selectores Selenium;
- procesos Chrome;
- perfiles físicos.

Las vistas podrán solicitar operaciones mediante servicios o runtimes.

Ejemplo correcto:

`communications_view`
→ `WhatsAppRuntimeService`
→ `WhatsAppConnector`
→ infraestructura browser.

Ejemplo prohibido:

`communications_view`
→ `browser.evaluate(...)`.

---

# IX. PRINCIPIO DE OWNERSHIP EXPLÍCITO

Toda sesión de navegador deberá tener un propietario técnico inequívoco.

Se deberá poder responder en cualquier momento:

- quién crea la sesión;
- quién conserva la referencia;
- qué runtime es propietario;
- qué perfil utiliza;
- qué hilo ejecuta las operaciones;
- qué módulo puede solicitar acciones;
- quién puede detener watchers;
- quién puede cerrar la sesión;
- qué ocurre cuando el ERP se cierra;
- qué ocurre cuando falla Chrome;
- qué ocurre cuando el browser desaparece;
- qué ocurre cuando el usuario cierra manualmente una ventana;
- qué ocurre cuando se pierde la sesión.

No se admitirán sesiones sin ownership definido.

---

# X. PRINCIPIO DE UNA SESIÓN, UN CONTROLADOR

Una sesión persistente de navegador deberá tener un único punto de control.

La existencia de:

- UI;
- watcher;
- timer;
- callback;
- job;
- thread;
- proceso;
- servicio;

no autoriza a cada consumidor a acceder directamente al browser.

El patrón obligatorio será:

`consumidores`
→ `Runtime`
→ `worker/serialización`
→ `Connector`
→ `BrowserSession`.

En una misma sesión persistente no deberán existir múltiples threads actuando concurrentemente sobre SeleniumBase/CDP salvo que se diseñe y demuestre explícitamente su seguridad.

---

# XI. SERIALIZACIÓN DE OPERACIONES

Para sesiones persistentes, las operaciones de navegador deberán serializarse salvo evidencia técnica que justifique otra estrategia.

Se adopta como referencia positiva el patrón desarrollado en WhatsApp:

`ThreadPoolExecutor(max_workers=1)`
→ worker propietario
→ ejecución serializada
→ reentrancia controlada.

Los watchers:

- podrán observar;
- podrán solicitar trabajo;
- podrán generar callbacks;

pero no tocarán directamente el objeto browser.

Esto evita:

- carreras de navegación;
- clicks simultáneos;
- cambios de tab inesperados;
- errores de identidad;
- corrupción de estado;
- interacciones concurrentes sobre el mismo WebSocket;
- dependencia del orden de ejecución del sistema operativo.

---

# XII. TIPOS DE SESIÓN

La infraestructura deberá distinguir al menos conceptualmente entre:

## A. Sesión efímera

Creada para una operación limitada.

Ejemplos:

- determinada presentación administrativa;
- consulta aislada;
- tarea automatizada de corta duración.

Características:

- lifecycle acotado;
- creación explícita;
- trabajo;
- cierre;
- menor necesidad de watchers.

## B. Sesión persistente

Debe permanecer viva durante períodos largos.

Ejemplo principal:

- WhatsApp Web.

Características:

- perfil persistente;
- autenticación conservada;
- watchers;
- estado técnico;
- recuperación;
- runtime duradero;
- cierre coordinado con la sesión ERP.

## C. Sesión asistida

Puede necesitar participación humana.

Ejemplos:

- certificado;
- CAPTCHA;
- QR;
- confirmación;
- selección puntual.

La infraestructura no deberá confundir una espera humana con un fallo técnico.

---

# XIII. PERFILES DE NAVEGADOR

Los perfiles persistentes se consideran recursos de infraestructura.

Cada perfil deberá tener una identidad lógica mediante `profile_key` o mecanismo equivalente.

Deberá evitarse que el resto del ERP conozca rutas físicas innecesariamente.

La infraestructura común será responsable de resolver:

`profile_key`
→ directorio físico.

Los perfiles deberán permitir identificar:

- finalidad;
- proveedor;
- entorno;
- persistencia;
- owner;
- compatibilidad;
- requisitos especiales.

Ejemplo actual:

`whatsapp_dev`

corresponde al entorno de desarrollo de WhatsApp.

La futura migración hacia el perfil del despacho no deberá requerir modificar la lógica de negocio.

---

# XIV. BLOQUEO Y USO CONCURRENTE DE PERFILES

No deberá asumirse que un mismo perfil de Chrome puede ser utilizado simultáneamente por múltiples procesos.

La infraestructura deberá prever mecanismos para detectar o impedir:

- apertura simultánea incompatible;
- perfiles bloqueados;
- corrupción de preferencias;
- dos runtimes controlando la misma sesión;
- diferentes procesos Python utilizando el mismo directorio.

Cuando resulte necesario compartir autenticación deberá diseñarse una estrategia explícita, no abrir el mismo perfil desde dos procesos arbitrariamente.

---

# XV. FACTORÍA CENTRAL DE BROWSER

La creación física de SeleniumBase/Chrome deberá concentrarse progresivamente en infraestructura común.

La función actualmente existente:

`start_seleniumbase_chrome(...)`

constituye un punto de partida válido, pero deberá evolucionar hacia un contrato más rico.

La infraestructura futura deberá poder expresar, entre otros:

- `headless`;
- `profile_key`;
- `user_data_dir`;
- modo persistente/efímero;
- timeout;
- argumentos Chrome permitidos;
- metadata de sesión;
- identificación del consumidor;
- políticas de cierre;
- diagnósticos;
- health.

No se permitirá que cada connector componga arbitrariamente argumentos incompatibles de Chrome sin pasar por una política común.

---

# XVI. BROWSER SESSION COMO ABSTRACCIÓN

Se aprueba como dirección arquitectónica la creación progresiva de una abstracción equivalente a:

`BrowserSession`

Su objetivo no será ocultar absolutamente todas las capacidades de SeleniumBase.

Su objetivo será gobernar el lifecycle y ownership del recurso.

Conceptualmente podrá responsabilizarse de:

- crear;
- arrancar;
- identificar;
- exponer el wrapper autorizado;
- informar estado;
- registrar metadata;
- gestionar perfil;
- controlar ownership;
- detener;
- cerrar;
- recuperar;
- instrumentar;
- diagnosticar.

El nombre definitivo podrá variar durante la implementación.

La semántica es vinculante.

---

# XVII. BROWSER RUNTIME

Por encima de la sesión podrá existir una capa de runtime común encargada de:

- serialización;
- thread ownership;
- health;
- lifecycle;
- startup;
- shutdown;
- recuperación;
- callbacks técnicos;
- coordinación de watchers.

Esta capa no deberá conocer la semántica particular del proveedor.

Por ejemplo:

`BrowserRuntime`

no deberá saber qué significa:

- mensaje WhatsApp;
- requerimiento Mercurio;
- notificación DEHú.

Esas responsabilidades pertenecen a capas superiores.

---

# XVIII. CONNECTORS ESPECÍFICOS

Cada proveedor conservará su connector especializado.

El connector deberá conocer:

- URLs;
- selectores;
- DOM;
- navegación;
- acciones;
- lectura;
- parsing;
- particularidades del sitio.

Ejemplos:

`WhatsAppConnector`

`MercurioConnector`

`DEHUConnector`

La infraestructura común no deberá acabar convertida en un gigantesco `if provider == ...`.

---

# XIX. PRINCIPIO DOM FIRST

Para automatización de interfaz se establece el siguiente orden de preferencia:

1. DOM semántico estable;

2. atributos accesibles;

3. `role`;

4. `aria-label`;

5. `data-testid` cuando resulte estable;

6. selectores estructurales suficientemente robustos;

7. CDP;

8. internals del framework JavaScript únicamente cuando no exista alternativa razonable.

La automatización basada exclusivamente en:

- coordenadas;
- posición de pantalla;
- foco;
- secuencias de teclado globales;

deberá evitarse cuando exista un mecanismo CDP/DOM estable.

---

# XX. POLÍTICA SOBRE PYAUTOGUI Y AUTOMATIZACIÓN DE ESCRITORIO

PyAutoGUI no queda absolutamente prohibido.

No obstante, será considerado fallback.

El objetivo prioritario es:

> La automatización deberá permitir, siempre que técnicamente sea posible, que el usuario continúe utilizando su ordenador, ratón, teclado y ERP simultáneamente.

Orden preferido:

`DOM/CDP`
→ `SeleniumBase`
→ mecanismos específicos del navegador
→ automatización GUI únicamente cuando resulte imprescindible.

Si se utiliza PyAutoGUI deberá documentarse:

- por qué CDP no resuelve el caso;
- qué riesgo de interferencia existe;
- qué mitigaciones se aplican;
- cómo se recupera el sistema si cambia el foco.

---

# XXI. INTERNOS DE JAVASCRIPT Y REACT

La experiencia obtenida durante la investigación de WhatsApp demuestra que en determinados proveedores puede ser necesario leer internals JavaScript.

Su utilización deberá ser excepcional y controlada.

Se establecen las siguientes reglas:

- lectura acotada;
- búsqueda específica;
- no dumping indiscriminado;
- retorno de campos whitelisted;
- no extracción innecesaria de URLs;
- no extracción innecesaria de tokens;
- no persistencia de internals no necesarios;
- sanitización de diagnósticos;
- tests sobre el contrato consumido;
- fallback cuando el internal desaparezca.

El hecho de que un objeto sea accesible desde JavaScript no significa que deba incorporarse al dominio.

---

# XXII. PRIVACIDAD Y MINIMIZACIÓN DE DATOS

Las automatizaciones deberán aplicar minimización de datos.

Especial atención a:

- WhatsApp;
- correos;
- documentos;
- certificados;
- sedes administrativas;
- tokens;
- identificadores internos;
- URLs autenticadas;
- cookies;
- documentos jurídicos.

Los probes de diagnóstico deberán imprimir exclusivamente la información necesaria.

Queda prohibido introducir dumps globales de:

- árbol React;
- localStorage;
- sessionStorage;
- cookies;
- tokens;
- DOM completo;

salvo diagnóstico extraordinario, controlado y no persistido.

---

# XXIII. ACCIONES SENSIBLES

Las acciones capaces de provocar efectos externos deberán disponer de barreras adicionales.

Ejemplos:

- enviar mensaje;
- realizar llamada;
- presentar expediente;
- firmar;
- enviar formulario;
- descargar o subir documentación;
- aceptar/rechazar una acción irreversible.

Cuando exista riesgo de actuar sobre el destinatario incorrecto deberá realizarse verificación fuerte de identidad.

La infraestructura browser no sustituye esas reglas de negocio.

---

# XXIV. OBSERVACIÓN Y ACTUACIÓN

Se distinguirá expresamente entre:

`READ / OBSERVE`

y:

`ACT / MUTATE`.

Las operaciones pasivas deberán minimizar:

- navegación;
- clicks;
- alteración de unread;
- cambios de selección;
- modificaciones del estado remoto.

Los watchers tendrán comportamiento conservador.

Este principio resulta especialmente vinculante para WhatsApp.

---

# XXV. WATCHERS

Un watcher deberá:

- ser ligero;
- poder detenerse;
- no tocar browser directamente si existe runtime;
- capturar errores;
- sobrevivir a fallos recuperables;
- permitir inspección de `last_error`;
- no bloquear el frontend;
- no realizar loops agresivos;
- respetar serialización;
- detenerse antes del cierre de la sesión.

Los watchers no deberán convertirse en propietarios de browser.

---

# XXVI. ESTADO TÉCNICO DE SESIÓN

La infraestructura deberá disponer progresivamente de estados técnicos normalizados.

Podrán contemplarse conceptos como:

- `CREATED`;
- `STARTING`;
- `READY`;
- `NEEDS_USER_ACTION`;
- `DEGRADED`;
- `DISCONNECTED`;
- `FAILED`;
- `STOPPING`;
- `CLOSED`.

Los nombres definitivos se decidirán durante la implementación.

El objetivo es evitar depender de simples booleanos ambiguos como única fuente de estado.

---

# XXVII. HEALTH CHECKS

Las sesiones persistentes deberán permitir inspección técnica sin alterar el estado funcional.

Un health check podrá informar:

- proceso vivo;
- browser disponible;
- conexión CDP;
- página accesible;
- sesión autenticada;
- provider ready;
- worker operativo;
- watcher operativo;
- último error;
- último éxito.

Un health check no deberá provocar una acción funcional.

---

# XXVIII. TIMEOUTS

Todos los waits relevantes deberán tener timeout.

Queda prohibido introducir esperas infinitas no controladas.

Los timeouts deberán distinguir, cuando proceda:

- startup;
- login;
- navegación;
- elemento;
- provider ready;
- operación;
- shutdown;
- callback;
- watcher.

Los valores no deberán dispersarse arbitrariamente si representan políticas comunes.

---

# XXIX. RETRIES

Los retries deberán aplicarse únicamente a operaciones que sean técnicamente repetibles.

No deberá reintentarse ciegamente:

- envío de mensajes;
- submit;
- clicks con efectos;
- presentación;
- llamadas;
- acciones que puedan haberse completado antes de perder la confirmación.

Las operaciones con efectos externos deberán aplicar:

- idempotencia;
- verificación postacción;
- estado del proveedor;
- identificadores externos;

cuando resulte posible.

---

# XXX. PRINCIPIO DE NO DOBLE ACCIÓN

Cuando una operación sensible pueda haber sido ejecutada, la ausencia de confirmación no autorizará automáticamente una segunda ejecución.

Ejemplo general:

`click`
→ resultado desconocido

NO implica:

`click otra vez`.

Este principio ya es especialmente relevante para mensajería y deberá aplicarse a cualquier automatización administrativa.

---

# XXXI. THREAD OWNERSHIP

Cada runtime deberá definir qué thread puede operar sobre SeleniumBase.

En sesiones serializadas:

- el frontend solicita;
- el runtime agenda;
- el worker ejecuta;
- el connector actúa.

Se evitará ejecutar una parte de una operación desde un thread y continuarla desde otro si los objetos internos están ligados a un thread/event loop determinado.

---

# XXXII. ASYNCIO Y EVENT LOOPS

Se declara expresamente que los event loops internos de SeleniumBase/CDP son detalles delicados de infraestructura.

Queda prohibido asumir que:

`browser.loop`

es necesariamente el único event loop relacionado con una sesión.

La investigación realizada sobre SeleniumBase 4.47.1 en Windows ha demostrado la existencia de recursos de una sesión asociados a distintos `ProactorEventLoop`.

Por tanto:

- no se ejecutarán coroutines internas sobre un loop supuesto;
- no se utilizará `run_until_complete()` sobre Futures cuyo owner no haya sido identificado;
- no se cerrarán loops internos arbitrariamente;
- no se cambiará el event loop global para reparar síntomas sin comprender ownership;
- no se manipularán internals asyncio desde connectors funcionales.

Toda manipulación de loops deberá permanecer encapsulada en infraestructura y protegida por tests específicos.

---

# XXXIII. HALLAZGO SOBRE `sb_cdp.Chrome`

A fecha de esta resolución, SeleniumBase 4.47.1 implementa `sb_cdp.Chrome` mediante una composición que incluye:

- `cdp_util.start_sync(...)`;
- un `Browser` CDP interno;
- creación adicional de `asyncio.new_event_loop()`;
- `Page`;
- `Connection`;
- WebSocket;
- listeners;
- tasks.

Este conocimiento se considera específico de versión.

No deberá convertirse en dependencia general del dominio.

---

# XXXIV. HALLAZGO SOBRE `Browser.stop()` Y `quit()`

En la versión investigada:

`Browser.quit()`
→ `Browser.stop()`.

Por tanto:

> Sustituir `stop()` por `quit()` no constituye por sí mismo una estrategia de shutdown diferente.

`Browser.stop()` realiza operaciones que incluyen:

- cierre asíncrono de conexión;
- terminación del proceso navegador;
- manipulación de registros internos.

Su retorno no deberá interpretarse automáticamente como prueba de que todo el runtime CDP ha sido completamente destruido.

---

# XXXV. HALLAZGO SOBRE SHUTDOWN EN WINDOWS

Durante la investigación del módulo WhatsApp se ha reproducido de forma aislada:

`0xC0000005`

durante la finalización normal de procesos Python que han utilizado `sb_cdp.Chrome`.

La investigación ha demostrado hasta el momento:

- `driver.stop()` puede retornar correctamente;
- el proceso puede continuar ejecutando Python después de `stop()`;
- el crash puede ocurrir posteriormente;
- eliminar el Browser del registro interno de SeleniumBase no elimina necesariamente el fallo;
- eliminar callbacks `atexit` Python no elimina necesariamente el fallo;
- `gc.collect()` puede finalizar correctamente y el fallo producirse después;
- drenar las tareas del loop conocido no elimina necesariamente el fallo;
- cerrar el loop conocido no elimina necesariamente el fallo;
- existen recursos relacionados con una sesión asociados a distintos event loops;
- `os._exit(0)` evita la finalización normal, pero no constituye solución productiva.

Se declara:

**INVESTIGACIÓN DE SHUTDOWN NATIVO CDP EN WINDOWS: ABIERTA.**

No deberá ocultarse mediante hacks productivos hasta disponer de un contrato suficientemente robusto.

---

# XXXVI. PROHIBICIÓN DE `os._exit()` COMO SOLUCIÓN PRODUCTIVA

Aunque `os._exit()` pueda resultar útil para diagnóstico, queda prohibido utilizarlo como cierre normal del ERP.

Puede evitar:

- `finally`;
- flushes;
- callbacks;
- cierres de recursos;
- transacciones pendientes;
- cleanup de librerías.

Su utilización quedará limitada a probes aislados o herramientas extraordinarias de diagnóstico.

---

# XXXVII. SUBPROCESS COMO HERRAMIENTA DE AISLAMIENTO

Cuando exista riesgo de:

- crash nativo;
- driver defectuoso;
- deadlock;
- subprocess huérfano;
- cierre no capturable;
- `0xC0000005`;
- segmentation fault;

la investigación deberá realizarse preferentemente mediante subprocess aislado.

La prueba deberá capturar:

- return code;
- stdout;
- stderr;
- timeout;
- marcadores antes/después de operaciones relevantes.

Esto permite diferenciar:

- excepción Python;
- cierre normal;
- crash nativo;
- timeout;
- deadlock.

---

# XXXVIII. OBSERVABILIDAD TÉCNICA

La infraestructura común deberá disponer progresivamente de diagnósticos estructurados.

Como mínimo deberá poder conocerse:

- `session_id`;
- provider/consumer;
- profile key;
- estado;
- started_at;
- worker;
- último éxito;
- último error;
- operación actual;
- watcher activo;
- browser disponible;
- cierre solicitado;
- cierre completado.

Los diagnósticos no deberán contener datos personales innecesarios.

---

# XXXIX. IDENTIFICADOR DE SESIÓN

Se recomienda introducir un identificador lógico de sesión independiente del PID de Chrome.

Ejemplo conceptual:

`browser_session_id`.

Servirá para:

- logs;
- correlación;
- debugging;
- health;
- lifecycle;
- tests;
- futuras ejecuciones paralelas.

No deberá confundirse con:

- PID;
- profile;
- user;
- provider session id.

---

# XL. MODELO DE ERRORES

La infraestructura deberá distinguir al menos conceptualmente:

## Error técnico recuperable

Ejemplo:

- elemento temporalmente ausente;
- provider cargando;
- timeout recuperable.

## Error de sesión

Ejemplo:

- sesión no autenticada;
- browser desconectado.

## Error de navegación

Ejemplo:

- página inesperada;
- selector desaparecido.

## Error de identidad

Ejemplo:

- destinatario no verificable.

## Error de provider

Ejemplo:

- servicio remoto no disponible.

## Error de infraestructura

Ejemplo:

- browser no arrancable;
- profile bloqueado;
- CDP roto.

## Error nativo

Ejemplo:

- proceso terminado;
- access violation;
- crash Chrome.

Los errores de infraestructura no deberán convertirse arbitrariamente en estados jurídicos o de negocio.

---

# XLI. CAPA DE COMPATIBILIDAD

Durante la transición se permitirá una capa de compatibilidad.

Esta capa deberá permitir que código existente continúe utilizando contratos antiguos mientras la infraestructura común empieza a gobernar:

- creación;
- lifecycle;
- perfil;
- ownership;
- health.

La capa de compatibilidad será temporal y deberá estar documentada.

No se utilizará como excusa para mantener indefinidamente dos arquitecturas completas.

---

# XLII. MIGRACIÓN DE WHATSAPP

La migración de WhatsApp hacia infraestructura común deberá realizarse por fases.

Orden recomendado:

1. inventariar todos los contratos actuales;

2. crear tests contractuales antes de tocar integración;

3. introducir infraestructura común debajo del connector;

4. conservar `WhatsAppRuntimeService`;

5. conservar worker único;

6. conservar watchers actuales;

7. conservar métodos públicos;

8. realizar pruebas unitarias;

9. realizar smoke real;

10. comparar comportamiento;

11. únicamente después retirar infraestructura duplicada.

No deberá cambiarse simultáneamente:

- runtime;
- observer;
- sync;
- llamadas;
- mensajes;
- identidad;
- lifecycle browser.

---

# XLIII. MIGRACIÓN DE MERCURIO

Mercurio deberá migrarse de forma todavía más conservadora por su impacto jurídico.

Fases recomendadas:

1. inventario exacto de puntos de creación de browser;

2. inventario de perfil/certificado;

3. caracterización de lifecycle actual;

4. tests de presentación asistida existentes;

5. creación de adapter hacia BrowserSession;

6. mantener lógica Mercurio intacta;

7. sustituir exclusivamente infraestructura de creación/session;

8. smoke controlado;

9. ampliar gradualmente el uso del runtime común.

No se deberán modificar requisitos jurídicos o formularios como parte de una refactorización de infraestructura SeleniumBase.

---

# XLIV. DESARROLLO DE DEHÚ

Las futuras ampliaciones de DEHú deberán adoptar directamente la nueva infraestructura una vez estabilizada.

DEHú no deberá crear una tercera arquitectura distinta de:

- WhatsApp;
- Mercurio;
- BrowserSession común.

Podrá tener su connector y runtime específicos.

---

# XLV. API MÍNIMA OBJETIVO DE BROWSER SESSION

Sin fijar aún los nombres definitivos, la infraestructura deberá ser capaz de representar conceptualmente operaciones equivalentes a:

`start()`

`get_status()`

`is_alive()`

`get_browser()`

`run(...)`

`stop()`

`close()`

`health()`

`diagnostics()`

No todas ellas deberán exponerse públicamente a todos los consumidores.

El acceso directo al browser deberá quedar limitado a connectors autorizados.

---

# XLVI. API DE RUNTIME

Un runtime podrá exponer conceptualmente:

`start()`

`ensure_ready()`

`run_serialized(...)`

`stop_watchers()`

`close_session()`

`shutdown()`

La separación entre:

`close_session`

y:

`shutdown`

deberá valorarse especialmente para sesiones persistentes.

Una operación de cierre del provider no es necesariamente equivalente a destruir todo el runtime Python.

---

# XLVII. SEPARACIÓN ENTRE DETACH, CLOSE Y KILL

La infraestructura deberá diferenciar semánticamente:

## DETACH

Dejar de controlar una sesión.

## CLOSE

Solicitar cierre ordenado.

## KILL

Forzar terminación.

No deberán utilizarse indistintamente.

En particular:

> Terminar Chrome por la fuerza no deberá considerarse automáticamente un shutdown limpio.

---

# XLVIII. RECUPERACIÓN

Una sesión persistente deberá poder definir estrategias de recuperación.

Ejemplos:

- reconnect;
- recreate browser;
- reload provider;
- solicitar login;
- marcar degraded;
- deshabilitar temporalmente watcher.

La recuperación no deberá provocar automáticamente operaciones de negocio repetidas.

---

# XLIX. NO REPLAY AUTOMÁTICO DE ACCIONES SENSIBLES

Tras una caída del navegador no deberá reproducirse automáticamente una acción externa cuyo resultado sea incierto.

Ejemplo:

`submit`
→ browser crash
→ resultado desconocido

NO autoriza:

`nuevo submit`.

Deberá realizarse reconciliación antes de reintentar cuando resulte posible.

---

# L. CONFIGURACIÓN

La configuración de navegador deberá separarse del código funcional.

Podrá incluir:

- profile keys;
- headless;
- timeouts;
- paths;
- flags;
- environment;
- provider options.

No deberán hardcodearse configuraciones sensibles en múltiples connectors.

---

# LI. SEGURIDAD DE CERTIFICADOS

Los certificados digitales utilizados por automatizaciones deberán tratarse como recursos sensibles.

La infraestructura común no deberá:

- duplicarlos;
- exportarlos;
- imprimir sus secretos;
- registrar PIN;
- registrar contraseñas;
- trasladarlos arbitrariamente.

Las automatizaciones jurídicas deberán aplicar mínimo acceso necesario.

---

# LII. LOGGING

Los logs de automatización deberán ser útiles para reconstruir:

`qué se intentó`
→ `qué se observó`
→ `qué se ejecutó`
→ `qué respondió el provider`
→ `qué resultado produjo`.

Sin embargo, no deberán registrar indiscriminadamente:

- documentos completos;
- conversaciones completas;
- tokens;
- cookies;
- credenciales;
- certificados;
- secretos.

---

# LIII. SCREENSHOTS Y EVIDENCIAS

Las capturas podrán utilizarse para diagnóstico cuando resulten necesarias.

Deberán diferenciarse:

- evidencia temporal de desarrollo;
- evidencia administrativa;
- documento real;
- log técnico.

No deberán mezclarse en un mismo sistema sin clasificación.

---

# LIV. TESTS UNITARIOS

La infraestructura común deberá disponer de tests para:

- configuración;
- profile resolution;
- lifecycle;
- estados;
- ownership;
- serialización;
- timeouts;
- retries;
- errores;
- shutdown lógico;
- adapters.

Los tests unitarios no sustituyen las pruebas reales de browser.

---

# LV. TESTS CONTRACTUALES

Deberán existir tests que congelen contratos utilizados por:

- WhatsApp;
- Mercurio;
- DEHú.

La finalidad será permitir refactorizar infraestructura sin modificar comportamiento.

Ejemplo:

`WhatsAppRuntimeService.start()`

deberá seguir comportándose igual aunque internamente cambie la creación del browser.

---

# LVI. TESTS DE INTEGRACIÓN

La infraestructura deberá probar:

`Runtime`
→ `Connector`
→ `BrowserSession`.

Deberán poder utilizar:

- fake browser;
- fake session;
- fake connector;
- clocks controlados;
- repositories temporales cuando proceda.

---

# LVII. TESTS REALES DE BROWSER

Determinados contratos no pueden validarse exclusivamente mediante fakes.

Se deberán prever smokes reales para:

- arranque;
- profile;
- navegación;
- sesión persistente;
- cierre;
- restart;
- pérdida de navegador.

Estos tests no necesariamente formarán parte de cada ejecución rápida de CI.

---

# LVIII. TESTS DE SUBPROCESS

Los contratos de lifecycle susceptibles de crash nativo deberán ejecutarse en procesos independientes.

El proceso padre deberá evaluar:

- `returncode == 0`;
- timeout;
- salida;
- presencia de marcadores;
- ausencia de crash.

Una prueba que mate todo el proceso principal no constituye una prueba automatizada útil.

---

# LIX. TESTS DE REGRESIÓN

Todo fallo relevante encontrado durante esta investigación deberá, cuando sea razonable, convertirse en test o probe reproducible.

Especialmente:

- cierre tardío mediante `atexit`;
- executor ya cerrado;
- shutdown CDP;
- profile ownership;
- múltiples event loops;
- futures ligados a loops diferentes;
- Browser registrado;
- crash nativo Windows.

---

# LX. PRUEBAS DE VERSIÓN

Toda actualización de SeleniumBase deberá considerarse un cambio de infraestructura.

Antes de integrarla deberán ejecutarse como mínimo:

- contratos de BrowserSession;
- WhatsApp;
- Mercurio;
- startup;
- profile;
- lifecycle;
- subprocess shutdown.

No se deberá actualizar SeleniumBase únicamente porque exista una versión nueva.

---

# LXI. PINNING DE VERSIONES

Mientras existan dependencias sobre internals CDP se recomienda fijar explícitamente la versión de SeleniumBase utilizada por el proyecto.

Las investigaciones deberán registrar:

- Python;
- SeleniumBase;
- Chrome;
- sistema operativo;

cuando sean relevantes.

---

# LXII. COMPATIBILIDAD POSTERIOR

La infraestructura común deberá reducir, no aumentar, la dependencia sobre una versión concreta de SeleniumBase.

Las capas superiores no deberán conocer:

- estructura interna de `Browser`;
- implementación interna de `Connection`;
- registros privados;
- propiedades privadas de CDP;

salvo adapters estrictamente encapsulados.

---

# LXIII. NO DEPENDENCIA DE FLET

La infraestructura SeleniumBase no deberá depender de Flet.

Flet podrá:

- solicitar acciones;
- mostrar estado;
- mostrar errores.

Pero el BrowserRuntime deberá poder utilizarse desde:

- scripts;
- tests;
- workers;
- jobs;
- CLI;
- futuras aplicaciones.

---

# LXIV. NO DEPENDENCIA DE SQLITE

La infraestructura de navegador no deberá depender de SQLite.

Podrá emitir:

- resultados;
- eventos;
- metadata;

que posteriormente los servicios persistan.

Esto facilita la futura migración PostgreSQL/Supabase.

---

# LXV. PROHIBICIÓN DE PERSISTENCIA DESDE CONNECTOR

Los connectors no deberán escribir directamente en:

- SQLite;
- PostgreSQL;
- Supabase.

Deberán devolver datos al servicio correspondiente.

Ejemplo correcto:

`WhatsAppConnector`
→ snapshot
→ service
→ repository.

---

# LXVI. EVENTOS

La infraestructura podrá evolucionar hacia eventos técnicos normalizados.

Ejemplos conceptuales:

`SESSION_STARTED`

`SESSION_READY`

`SESSION_DEGRADED`

`SESSION_LOST`

`SESSION_STOPPING`

`SESSION_CLOSED`

`BROWSER_CRASHED`

Estos eventos deberán representar infraestructura, no reglas de negocio.

---

# LXVII. TELEMETRÍA

En una fase posterior podrá incorporarse telemetría mínima:

- latencia de startup;
- operaciones;
- retries;
- errores;
- restarts;
- tiempo de sesión;
- crashes.

Su finalidad será detectar deterioro antes de que afecte al usuario.

---

# LXVIII. HEARTBEAT

Las sesiones persistentes podrán implementar heartbeat técnico.

El heartbeat deberá ser:

- barato;
- pasivo;
- no destructivo;
- respetuoso con el provider.

No deberá convertirse en polling agresivo.

---

# LXIX. PROCESS MANAGEMENT

La infraestructura deberá conocer los procesos que crea directamente cuando resulte necesario para lifecycle y diagnóstico.

No obstante, se evitará implementar un gestor general de procesos Chrome antes de disponer de necesidad real.

Se aplicará incrementalismo.

---

# LXX. CIERRE DEL ERP

El cierre de recursos de navegador deberá producirse durante lifecycle explícito de la aplicación cuando sea posible.

No se dependerá exclusivamente de `atexit` de la aplicación para iniciar operaciones complejas.

El lifecycle de Flet deberá utilizarse cuando proporcione un punto de cierre suficientemente temprano.

Los cierres tardíos del intérprete se consideran un último recurso, no la estrategia principal.

---

# LXXI. LOGOUT

El futuro logout del ERP deberá diferenciarse del cierre completo de la aplicación.

No se asumirá automáticamente que:

`logout`
=
`matar todas las sesiones browser`.

Cada sesión definirá su política.

---

# LXXII. DESCONEXIÓN DE FLET

Un `disconnect` de Flet no deberá destruir automáticamente sesiones persistentes sin analizar su significado.

Una desconexión de UI puede ser recuperable.

Por tanto:

- `on_close`;
- `on_disconnect`;
- `logout`;

deberán tratarse como eventos diferentes.

---

# LXXIII. EVITAR BIG-BANG REFACTOR

La nueva infraestructura se desarrollará siguiendo slices verticales pequeños.

Cada fase deberá:

1. tener objetivo limitado;

2. disponer de diagnóstico previo;

3. introducir pocas piezas;

4. añadir tests;

5. ejecutar regresión;

6. verificar WhatsApp;

7. verificar Mercurio cuando le afecte;

8. realizar commit atómico.

No se aprobará una rama de miles de líneas que sustituya simultáneamente toda la automatización.

---

# LXXIV. GOBIERNO DE GIT

Cada modificación relevante deberá realizarse mediante commits atómicos.

Ejemplos deseables:

`feat(automation): add browser session domain contract`

`feat(automation): centralize SeleniumBase session creation`

`test(automation): add browser lifecycle subprocess contract`

`refactor(whatsapp): adopt shared browser session factory`

`refactor(mercurio): adopt shared browser infrastructure`

No deberán mezclarse en un mismo commit:

- infraestructura;
- cambios jurídicos;
- cambios visuales;
- nuevas funcionalidades no relacionadas.

---

# LXXV. PROTECCIÓN DEL WORKTREE

Los probes y herramientas experimentales podrán mantenerse en:

`scripts/tools/`

mientras sean puramente diagnósticos.

No deberán incorporarse automáticamente a commits productivos.

Cuando una herramienta se convierta en contrato permanente deberá evaluarse expresamente su incorporación.

---

# LXXVI. NO REESCRITURA DE ARCHIVOS GRANDES SIN NECESIDAD

Las modificaciones sobre automatizaciones consolidadas deberán ser quirúrgicas.

Se evitarán:

- reformat masivo;
- reorganización estética simultánea;
- renombrados globales;
- sustituciones completas sin necesidad.

La revisión Git deberá permitir identificar claramente el cambio técnico real.

---

# LXXVII. ROADMAP DE IMPLEMENTACIÓN

Se aprueba la siguiente hoja de ruta inicial.

## FASE SB-INFRA-0 — Inventario

Objetivo:

construir mapa completo del uso actual de SeleniumBase.

Incluye:

- creación de Chrome;
- perfiles;
- imports;
- connectors;
- runtimes;
- Mercurio;
- WhatsApp;
- DEHú;
- scripts;
- lifecycle;
- tests.

No modifica producción.

---

## FASE SB-INFRA-1 — Contratos puros

Crear contratos técnicos independientes de SeleniumBase concreto.

Objetivo:

definir:

- configuración;
- identidad de sesión;
- estados;
- resultado de health;
- errores;
- lifecycle.

Sin migrar aún automatizaciones.

---

## FASE SB-INFRA-2 — BrowserSession

Crear primera implementación común alrededor de la factoría actual.

Debe ser compatible con:

`start_seleniumbase_chrome()`.

No deberá cambiar todavía comportamiento de WhatsApp ni Mercurio.

---

## FASE SB-INFRA-3 — Lifecycle y ownership

Centralizar:

- ownership;
- worker;
- close;
- health;
- session metadata.

Incorporar tests subprocess.

El problema `0xC0000005` deberá seguir investigándose dentro de esta fase.

---

## FASE SB-INFRA-4 — Compatibilidad WhatsApp

Adaptar WhatsApp para consumir infraestructura común manteniendo:

- API;
- runtime;
- worker;
- watchers;
- mensajes;
- llamadas;
- profile;
- tests.

Smoke real obligatorio.

---

## FASE SB-INFRA-5 — Compatibilidad Mercurio

Inventariar y adaptar Mercurio de forma gradual.

No modificar lógica jurídica.

Smoke real de presentación asistida o escenario seguro equivalente.

---

## FASE SB-INFRA-6 — DEHú

Construir nuevas ampliaciones de DEHú directamente sobre la infraestructura estabilizada.

---

## FASE SB-INFRA-7 — Hardening

Añadir:

- health;
- recuperación;
- telemetría;
- contratos de versión;
- process diagnostics;
- robustez multi-sesión.

---

# LXXVIII. CRITERIOS DE ACEPTACIÓN DE SB-INFRA-1/2

La primera infraestructura no se considerará aceptable simplemente porque pueda abrir Chrome.

Deberá demostrar:

- compatibilidad con perfil persistente;
- ownership claro;
- ningún SQL;
- ninguna dependencia Flet;
- ningún conocimiento WhatsApp/Mercurio;
- testabilidad;
- cierre lógico;
- diagnósticos;
- posibilidad de integración incremental;
- mantenimiento del factory actual mientras sea necesario.

---

# LXXIX. CRITERIOS DE ACEPTACIÓN PARA WHATSAPP

La migración de WhatsApp no se considerará completada hasta demostrar como mínimo:

- sesión persistente;
- login;
- watcher activo;
- chat;
- sincronización;
- envío;
- recepción;
- llamada entrante;
- llamada saliente cuando esté implementada;
- identidad;
- cierre/restart según contrato;
- ausencia de regresiones.

Los tests existentes serán considerados contratos a preservar.

---

# LXXX. CRITERIOS DE ACEPTACIÓN PARA MERCURIO

La migración de Mercurio deberá demostrar:

- arranque;
- navegación;
- certificado;
- formularios;
- documentos;
- presentación;
- justificante;
- errores;
- cierre;

sin alterar el resultado funcional previo.

---

# LXXXI. ANTI-PATRONES PROHIBIDOS

Quedan identificados como anti-patrones:

- `sb_cdp.Chrome()` directamente desde frontend;
- creación arbitraria de browser en servicios de negocio;
- múltiples threads controlando una misma sesión;
- watcher accediendo directamente al browser;
- duplicación de profile paths;
- cerrar browser desde cualquier capa;
- asumir ownership implícito;
- asumir que `browser.loop` es el único loop;
- ejecutar Futures sobre loops desconocidos;
- cambiar `stop()` por `quit()` esperando semántica diferente sin comprobar versión;
- usar `os._exit()` en producción;
- capturar `Exception` esperando interceptar crashes nativos;
- hacer retry ciego de acciones sensibles;
- click doble tras resultado incierto;
- dump global de internals React;
- persistencia desde connector;
- SQL en frontend;
- acoplar BrowserRuntime a Flet;
- acoplar BrowserRuntime a SQLite;
- reescritura masiva de WhatsApp;
- reescritura masiva de Mercurio;
- cambiar lógica jurídica durante refactor de navegador;
- compartir perfiles entre procesos sin control;
- matar Chrome como sustituto de un lifecycle correctamente diseñado.

---

# LXXXII. DEUDA TÉCNICA CONOCIDA

A fecha de esta resolución se reconoce expresamente la siguiente deuda:

## 1. Shutdown de SeleniumBase/CDP en Windows

Existe una reproducción estable de `0xC0000005` durante la finalización normal de determinados procesos que han utilizado `sb_cdp.Chrome`.

Estado:

**ABIERTO / EN INVESTIGACIÓN.**

## 2. Infraestructura común incompleta

Actualmente existen piezas reutilizables, pero no una plataforma unificada completa.

Estado:

**PENDIENTE DE IMPLEMENTACIÓN.**

## 3. Contratos de versión

No existe todavía una suite transversal completa de compatibilidad SeleniumBase.

Estado:

**PENDIENTE.**

---

# LXXXIII. ELEMENTOS YA APROVECHABLES

La futura infraestructura no parte de cero.

Se consideran activos reutilizables:

- `backend/automation/browser_session.py`;
- `backend/automation/browser_actions.py`;
- patrones de connector existentes;
- `WhatsAppRuntimeService`;
- serialización mediante worker único;
- perfiles persistentes;
- tests de WhatsApp;
- smokes reales;
- probes subprocess;
- experiencia adquirida con Mercurio;
- experiencia adquirida con WhatsApp.

Por tanto:

> La nueva infraestructura será una consolidación y evolución del proyecto existente, no una reconstrucción desde cero.

---

# LXXXIV. PRINCIPIO DE ABSTRACCIÓN SUFICIENTE

Se evitará crear una plataforma excesivamente abstracta antes de disponer de casos reales.

La infraestructura común deberá extraerse de necesidades demostradas por:

- WhatsApp;
- Mercurio;
- DEHú.

No se desarrollará un framework genérico de automatización universal.

El objetivo es:

**infraestructura adecuada para Quesada Abogados ERP.**

---

# LXXXV. PRINCIPIO DE GENERALIZACIÓN POR EVIDENCIA

Una capacidad pasará a la infraestructura común cuando:

1. sea requerida por más de una automatización; o

2. represente claramente una responsabilidad técnica de lifecycle/ownership; o

3. su duplicación suponga riesgo; o

4. sea necesaria para observabilidad, seguridad o testing transversal.

No todo helper deberá promocionarse a infraestructura común.

---

# LXXXVI. PRINCIPIO DE ESTABILIDAD SOBRE ELEGANCIA

Cuando exista conflicto entre:

- una arquitectura teóricamente más elegante;

y:

- preservar una automatización real ya funcional;

prevalecerá la estabilidad, salvo deuda crítica demostrada.

La migración podrá ser imperfecta temporalmente si permite mantener contratos.

---

# LXXXVII. PRINCIPIO DE EVIDENCIA REAL

Los problemas de navegador deberán resolverse mediante evidencia.

Se priorizarán:

- inspección del código instalado;
- introspección;
- tests;
- subprocess;
- return codes;
- smokes reales;
- observación de procesos;
- reproducción mínima.

Se evitarán cambios basados exclusivamente en suposiciones sobre SeleniumBase.

---

# LXXXVIII. PRINCIPIO DE AISLAMIENTO DE INTERNOS

Cuando resulte imprescindible acceder a un internal de SeleniumBase, dicho acceso deberá concentrarse en un adapter de infraestructura.

Ejemplo conceptual:

`SeleniumBaseSessionAdapter`

Será preferible modificar un adapter por cambio de versión que modificar:

- WhatsApp;
- Mercurio;
- DEhú;
- frontend;
- servicios.

---

# LXXXIX. FUTURA POSIBILIDAD DE CAMBIO DE MOTOR

La infraestructura deberá permitir que, en el futuro, una determinada automatización pueda utilizar otra tecnología sin modificar el dominio.

Esto no implica que actualmente se vaya a abandonar SeleniumBase.

Simplemente se establece la dirección:

`Connector`
→ contrato de sesión

en lugar de:

`Connector`
→ detalles globales del proceso SeleniumBase.

Podrían existir en el futuro adapters distintos si resultase necesario.

---

# XC. SELENIUMBASE COMO MOTOR PRINCIPAL ACTUAL

Se declara SeleniumBase/CDP como motor principal de automatización de navegador del proyecto en el estado actual.

La presente resolución no persigue sustituir SeleniumBase.

Persigue:

- gobernarlo;
- aislarlo;
- probarlo;
- reutilizarlo;
- hacerlo mantenible.

---

# XCI. CRITERIO PARA FUTURAS DECISIONES

Toda decisión sobre automatización deberá responder:

1. ¿Interfiere con el usuario?

2. ¿Tiene ownership definido?

3. ¿Respeta el runtime?

4. ¿Está serializada si comparte sesión?

5. ¿Puede repetirse de forma segura?

6. ¿Tiene timeout?

7. ¿Tiene diagnóstico?

8. ¿Protege datos?

9. ¿Puede probarse?

10. ¿Introduce deuda específica del provider en infraestructura común?

11. ¿Rompe WhatsApp?

12. ¿Rompe Mercurio?

Si alguna respuesta crítica es negativa deberá reconsiderarse el diseño.

---

# XCII. AUTORIDAD DE ESTA RESOLUCIÓN

La presente resolución tendrá carácter vinculante para todo nuevo desarrollo relacionado con navegador.

Cuando una implementación contradiga esta resolución deberán concurrir:

- razón técnica explícita;
- evidencia;
- alcance limitado;
- documentación;
- tests;
- aprobación consciente.

No se considerará suficiente:

“funciona”.

---

# XCIII. RESOLUCIÓN

Se aprueba formalmente la creación de una **infraestructura común de automatización SeleniumBase/CDP para Quesada Abogados ERP**.

Se establece que:

1. SeleniumBase/CDP será infraestructura transversal gobernada;

2. las automatizaciones no controlarán Chrome arbitrariamente;

3. WhatsApp y Mercurio quedan expresamente protegidos frente a reescrituras o regresiones;

4. la integración será incremental;

5. se introducirá ownership explícito de sesiones;

6. las sesiones persistentes utilizarán runtimes controlados;

7. las operaciones concurrentes serán serializadas cuando compartan navegador;

8. el frontend no accederá a SeleniumBase;

9. los connectors no persistirán datos;

10. los perfiles serán gestionados como recursos de infraestructura;

11. el lifecycle tendrá contratos explícitos;

12. los errores nativos se investigarán mediante procesos aislados;

13. no se utilizará `os._exit()` como solución productiva;

14. los internals SeleniumBase permanecerán encapsulados;

15. las actualizaciones de SeleniumBase requerirán regresión;

16. la infraestructura se construirá a partir de necesidades reales del ERP;

17. se preservará la compatibilidad con PostgreSQL/Supabase evitando acoplamientos innecesarios;

18. la estabilidad funcional prevalecerá sobre refactorizaciones estéticas;

19. la infraestructura común será introducida primero debajo de las automatizaciones actuales y no sobre ellas;

20. ninguna fase se considerará cerrada sin pruebas suficientes.

---

# XCIV. DECISIÓN INMEDIATA

A partir de la aprobación de esta resolución se autoriza iniciar:

**SB-INFRA-0 · Auditoría e inventario completo de SeleniumBase/CDP**

seguido de:

**SB-INFRA-1 · Contratos base de infraestructura**

y:

**SB-INFRA-2 · BrowserSession común**

antes de migrar progresivamente WhatsApp y Mercurio.

Se establece expresamente:

> No se comenzará la nueva infraestructura modificando WhatsApp ni Mercurio.

La primera fase deberá estudiar y construir la capa inferior común.

Solo cuando exista un contrato suficientemente probado comenzará la adopción por los módulos existentes.

---

# XCV. ESTADO DE REFERENCIA AL CIERRE DE LA RESOLUCIÓN

A 15 de agosto de 2026:

### WhatsApp

Arquitectura runtime:

**altamente desarrollada y funcional.**

Llamadas WhatsApp:

**integración realtime prácticamente completada.**

Persistencia real:

**probada.**

Watcher global:

**probado.**

Lifecycle Flet:

**mejorado mediante cierre explícito.**

Shutdown nativo SeleniumBase/CDP:

**investigación abierta.**

### Mercurio

Automatización existente:

**deberá preservarse y auditarse antes de cualquier integración estructural.**

### Infraestructura común SeleniumBase/CDP

Diseño conceptual:

**APROBADO.**

Implementación:

**PENDIENTE.**

### Próxima fase

**SB-INFRA-0 · Inventario integral y mapa de dependencias.**

---

# XCVI. PRINCIPIO FINAL

Quesada Abogados ERP no deberá evolucionar hacia una colección de automatizaciones independientes que casualmente utilicen SeleniumBase.

Deberá evolucionar hacia:

`un ERP`
→ `una plataforma común de automatización`
→ `múltiples connectors especializados`
→ `múltiples casos de uso`.

El objetivo no es abstraer por abstraer.

El objetivo es que:

- WhatsApp pueda funcionar durante toda la jornada;
- Mercurio pueda presentar expedientes con seguridad;
- DEHú pueda vigilar notificaciones;
- futuras sedes puedan incorporarse;
- el usuario pueda seguir trabajando;
- los errores puedan diagnosticarse;
- las sesiones puedan gobernarse;
- las actualizaciones puedan probarse;
- una modificación en SeleniumBase no obligue a reconstruir medio ERP.

Se adopta, por tanto, como principio arquitectónico permanente:

> **El navegador es infraestructura. El connector conoce el proveedor. El runtime gobierna la sesión. El servicio gobierna el caso de uso. El frontend únicamente solicita y representa.**

---

**FIN DE LA RESOLUCIÓN**