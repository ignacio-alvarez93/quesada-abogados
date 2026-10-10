# `04_QCC_BROWSER_AUTOMATION.md` — FUENTE MAESTRA DE AUTOMATIZACIÓN WEB, CDP Y QUESADA CHROME COMPANION (QCC)

**Proyecto:** Quesada Abogados CRM
**Naturaleza del Documento:** Fuente Maestra Consolidada 04 de 06
**Estado:** APROBADO POR DIRECCIÓN
**Trazabilidad:** Construido a partir del Registro Canónico Aprobado (`00_MASTER_INDEX.md`).
**FUENTES NORMATIVAS BASE:** `20260815_resolucion_arquitectura_y_gobierno_infraestructura_seleniumbase_cdp.md`, `20260821_resolucion_quesada_chrome_companion_qcc.md`, `20261005_resolucion_qcc_v2_augmentacion_dom_teaching_mode.md`, `20261010_resolucion_modelo_integral_automatizaciones_administrativas.md`, `20261010_resolucion_panel_qcc_obligatorio_contexto_operativo_automatizaciones_administrativas.md`.
**ANTECEDENTES TÉCNICOS:** `003_ecosistema_tecnologico.md` (integración inicial de automatizaciones).
**FUENTES INFORMATIVAS NO NORMATIVAS:** `QCC_15_mejoras_futuras.txt`, `30 mejorasQCC.txt`, `AMPLIACIONQCC.txt` (estado de implementación, roadmap y propuestas futuras).

---

## SECCIÓN I: MARCO GENERAL Y ALCANCE

La presente Fuente Maestra consolida de forma unificada las decisiones normativas aprobadas sobre la infraestructura común de automatización web mediante SeleniumBase y Chrome DevTools Protocol (CDP), la arquitectura de ejecución en segundo plano, las reglas de aislamiento de runtimes y la institución y evolución de Quesada Chrome Companion (QCC) como interfaz contextual del navegador conectada al ERP mediante QCC Bridge, incluyendo QCC V2, augmentación controlada del DOM y Teaching Mode gobernado.

La Fuente Maestra no crea autoridad normativa por sí misma. Consolida las decisiones normativas aprobadas contenidas en las fuentes originales del proyecto Quesada Abogados CRM, preservando la separación estricta entre el frontend de usuario (Flet), el runtime de automatización (SeleniumBase/CDP) y la interfaz contextual de supervisión en Chrome (QCC).

---

## SECCIÓN II: DECISIONES NORMATIVAS APROBADAS (WEB, QCC)

### 1. AUTOMATIZACIÓN WEB Y SELENIUMBASE (`WEB`)

#### `WEB-001` · Infraestructura Común de Automatización SeleniumBase / CDP
* **Estado:** VIGENTE
* **Decisión vigente:** SeleniumBase / CDP pasa a considerarse infraestructura transversal de primer nivel del ERP y no una implementación privada de cada módulo. Toda nueva automatización de navegador deberá diseñarse sobre la infraestructura común cuando esta permita resolver el caso de uso.

  La infraestructura deberá gobernar contratos explícitos de sesión, ownership, ejecución, observabilidad y ciclo de vida. Toda sesión de navegador debe tener un propietario técnico inequívoco y un único punto de control. Las operaciones concurrentes sobre una misma sesión deberán serializarse cuando corresponda. Los perfiles persistentes podrán utilizarse cuando el flujo requiera conservar autenticación o contexto.
* **Origen / Fuente primaria:** `20260815_resolucion_arquitectura_y_gobierno_infraestructura_seleniumbase_cdp.md` (Sec. I, VII, IX, X, XV, XVI, XVII y XXXI).
* **Justificación documentada:** Evitar arquitecturas de navegador duplicadas, colisiones de concurrencia y ciclos de vida ambiguos, preservando las automatizaciones existentes.
* **Invariantes:**
  - Toda sesión debe tener ownership técnico definido.
  - Una sesión persistente debe tener un único punto de control.
  - Los consumidores no obtienen por sí solos derecho de acceso directo al browser.
  - La creación física de SeleniumBase/Chrome debe concentrarse progresivamente en infraestructura común.
* **Evolución y modificaciones:** Desarrolla la estrategia inicial de automatización aprobada en `003_ecosistema_tecnologico.md`.
* **Relaciones relevantes:** Conecta con `WEB-002`, `WEB-003` y `QCC-001`.

#### `WEB-002` · Prohibición de SeleniumBase en el Frontend
* **Estado:** VIGENTE
* **Decisión vigente:** Queda expresamente prohibido importar o utilizar SeleniumBase directamente desde `frontend/views/`, `frontend/components/` o `frontend/layouts/`.

  Desde frontend también queda prohibido acceder directamente a browser, driver, tabs, WebSocket, event loops, CDP, `evaluate()`, `execute_script()`, selectores Selenium, procesos Chrome o perfiles físicos. Las vistas podrán solicitar operaciones mediante servicios o runtimes.
* **Origen / Fuente primaria:** `20260815_resolucion_arquitectura_y_gobierno_infraestructura_seleniumbase_cdp.md` (Sec. VIII).
* **Justificación documentada:** Preservar la separación de capas y evitar que la interfaz Flet se convierta en propietaria o controladora directa del navegador.
* **Invariantes:**
  - El frontend solicita operaciones; no controla directamente el browser.
  - SeleniumBase/CDP permanece detrás de servicios, runtimes, connectors e infraestructura browser.
* **Evolución y modificaciones:** Reafirma la separación general de capas ya aprobada para el ERP.
* **Relaciones relevantes:** Conecta con `ARCH-001`, `UI-001` y `WEB-001`.

#### `WEB-003` · Principio *DOM First* y Fallback Gobernado
* **Estado:** VIGENTE
* **Decisión vigente:** Para automatización de interfaz se establece el siguiente orden de preferencia:
  1. DOM semántico estable.
  2. Atributos accesibles.
  3. `role`.
  4. `aria-label`.
  5. `data-testid` cuando resulte estable.
  6. Selectores estructurales suficientemente robustos.
  7. CDP.
  8. Internals del framework JavaScript únicamente cuando no exista alternativa razonable.

  La automatización basada exclusivamente en coordenadas, posición de pantalla, foco o secuencias globales de teclado deberá evitarse cuando exista un mecanismo DOM/CDP estable.

  PyAutoGUI no queda absolutamente prohibido, pero se considera fallback. Si se utiliza deberá documentarse por qué DOM/CDP no resuelve el caso, el riesgo de interferencia, las mitigaciones y el mecanismo de recuperación ante cambios de foco.
* **Origen / Fuente primaria:** `20260815_resolucion_arquitectura_y_gobierno_infraestructura_seleniumbase_cdp.md` (Sec. XIX, XX y XXI).
* **Justificación documentada:** Maximizar robustez y reducir dependencia de geometría, foco o interacción de escritorio cuando existen contratos estructurales más estables.
* **Invariantes:**
  - DOM/CDP tiene prioridad sobre automatización GUI cuando resulte técnicamente viable.
  - Los internals JavaScript son excepcionales, acotados y gobernados.
  - PyAutoGUI es fallback, no infraestructura principal.
* **Evolución y modificaciones:** Las reglas geométricas y de interacción visual se desarrollan posteriormente en la arquitectura de sede y pertenecen a la Fuente Maestra 05.
* **Relaciones relevantes:** Conecta con `WEB-001` y, posteriormente, con `SITE-002`.

#### `WEB-004` · Prohibición de `os._exit()` en Producción y Aislamiento de Runtimes
* **Estado:** VIGENTE
* **Decisión vigente:** `os._exit()` queda prohibido como mecanismo normal de cierre del ERP o de sus automatizaciones productivas. Su uso se limita a probes aislados o herramientas extraordinarias de diagnóstico.

  Cuando exista riesgo de crash nativo, driver defectuoso, deadlock, subprocess huérfano, cierre no capturable, `0xC0000005` o segmentation fault, la investigación deberá realizarse preferentemente mediante subprocess aislado, capturando return code, stdout, stderr, timeout y marcadores relevantes.

  Todos los waits relevantes deberán disponer de timeout; quedan prohibidas las esperas infinitas no controladas.
* **Origen / Fuente primaria:** `20260815_resolucion_arquitectura_y_gobierno_infraestructura_seleniumbase_cdp.md` (Sec. XXVIII, XXXV, XXXVI y XXXVII).
* **Justificación documentada:** Evitar ocultar fallos nativos con terminaciones abruptas y permitir diferenciar excepciones Python, cierres normales, crashes, timeouts y deadlocks.
* **Invariantes:**
  - `os._exit()` no es una estrategia productiva de shutdown.
  - Los fallos nativos deben investigarse con aislamiento y evidencia.
  - No se introducen waits infinitos no gobernados.
* **Evolución y modificaciones:** La investigación de shutdown nativo CDP en Windows permanecía abierta en la resolución original.
* **Relaciones relevantes:** Conecta con `DEV-002` y `WEB-001`.


#### `WEB-005` · Cierre Integral Obligatorio de Automatizaciones Administrativas
* **Estado:** VIGENTE
* **Decisión vigente:** Una automatización administrativa no se considera completamente incorporada al CRM por la mera existencia de un script, navegación SeleniumBase o flujo ejecutable. Cada procedimiento debe constituir una unidad funcional integral coordinada mediante `ARCH-005` y disponer, como mínimo, de `OFFICIAL_SURFACE`, `CRM_FORM` y `SITE_AUTOMATION`.
* **Origen / Fuente primaria:** `20261010_resolucion_modelo_integral_automatizaciones_administrativas.md`.
* **Regla de cierre:** Los tres componentes obligatorios deben estar cerrados y coordinados; si cualquiera permanece incompleto, el procedimiento continúa `IN_PROGRESS`. La matriz de cobertura debe mantener visibilidad separada de las dimensiones Oficial, CRM, Automatización y Twin.
* **Cobertura de ramas:** Una automatización genérica no implica cobertura automática de todas las bifurcaciones. Las variantes y supuestos cubiertos deben declararse expresamente en el contrato.
* **Automatización de sede:** Debe contemplar, según proceda, navegación, autenticación, selección de procedimiento/modelo/supuesto, bifurcaciones, volcado de datos, carga documental, controles dinámicos, waits/readiness, validación de estado, errores, recuperación, evidencia, acciones reversibles/irreversibles y resultado esperado.
* **Tests y evidencia:** `CÓDIGO ≠ AUTOMATIZACIÓN TERMINADA`; el cierre exige contratos, tests, evidencia y validación. Se aplicarán según proceda tests unitarios, contractuales, mappings, replay, smoke, navegación, formulario, documental y regresión.
* **HUMAN_ONLY:** Firma, presentación definitiva, pago de tasas, registro documental y otras acciones con efectos jurídicos o irreversibles deben respetar `SITE-003` y los mecanismos de autorización aprobados.
* **Arquitectura:** Se mantiene `CRM → Services/Application → QCC/Runtime → SeleniumBase/CDP → SEDE REAL`. El frontend no controla directamente SeleniumBase ni el navegador.
* **Reutilización:** Antes de reconstruir una automatización existente debe aplicarse `AUDITAR → REUTILIZAR → CORREGIR → EXTENDER → TESTEAR`.
* **Relaciones relevantes:** `ARCH-005`, `WEB-001`, `WEB-002`, `QCC-002`, `SITE-003`, `SITE-004`, `TWIN-007`, `DEV-003`.



#### `WEB-006` · Aportación Documental Manual Asistida por QCC en la Fase Actual
* **Estado:** VIGENTE
* **Decisión vigente:** En la fase actual, la selección y carga efectiva de archivos en la sede electrónica permanece bajo intervención humana. QCC prepara y contextualiza; el usuario aporta.
* **Origen / Fuente primaria:** `20261010_resolucion_panel_qcc_obligatorio_contexto_operativo_automatizaciones_administrativas.md`.
* **Capacidades permitidas:** El sistema puede identificar documentos, mostrarlos, validar su existencia, ordenarlos para presentación, mostrar su estado, proporcionar sus rutas, copiar rutas al portapapeles y asistir al usuario durante la presentación.
* **Límite vigente:** QCC y la automatización no seleccionan ni cargan automáticamente los archivos en la sede en esta fase.
* **Evolución futura:** Esta resolución no prohíbe permanentemente la carga documental automática. Una futura automatización requerirá resolución, diseño y validación específicos sobre selección, orden, requisito ↔ documento, límites de tamaño, formatos, errores, confirmación, trazabilidad y controles `HUMAN_ONLY` cuando procedan.
* **Compatibilidad:** Desarrolla `WEB-005`: el `SITE_AUTOMATION` debe contemplar la fase documental, pero actualmente su ejecución efectiva de carga es manual asistida.
* **Relaciones relevantes:** `WEB-005`, `QCC-006`, `DOC-006`, `SITE-003`, `ARCH-005`.


---

### 2. QUESADA CHROME COMPANION (`QCC`)

#### `QCC-001` · Quesada Chrome Companion (QCC) como Interfaz Contextual
* **Estado:** VIGENTE
* **Decisión vigente:** Se aprueba Quesada Chrome Companion (QCC) como interfaz contextual del ERP dentro de Chrome. QCC se desarrolla como extensión Chrome Manifest V3 y utiliza inicialmente Chrome Side Panel.

  QCC acompaña el trabajo realizado en el navegador mostrando contexto y estado operativo, pero no sustituye al ERP principal ni se convierte en un segundo CRM, backend, base de datos o autoridad jurídica.
* **Origen / Fuente primaria:** `20260821_resolucion_quesada_chrome_companion_qcc.md` (Sec. VI, XLVII, L, LVI, LVII y LVIII).
* **Justificación documentada:** Integrar en Chrome el contexto del expediente y el estado de la automatización sin obligar al usuario a interpretar una consola técnica.
* **Invariantes:**
  - Flet continúa siendo la interfaz principal del ERP.
  - QCC es una interfaz contextual, no una fuente de verdad.
  - QCC no sustituye al runtime ni al backend.
* **Evolución y modificaciones:** Las capacidades posteriores de Site Architecture y AUTO TWIN se gobiernan en resoluciones independientes y se consolidan en la Fuente Maestra 05.
* **Relaciones relevantes:** Conecta con `QCC-002`, `QCC-003` y `WEB-001`.

#### `QCC-002` · Arquitectura de Comunicación mediante QCC Bridge
* **Estado:** VIGENTE
* **Decisión vigente:** QCC se comunica con el backend mediante una capa local denominada `QCC Bridge`.

  La arquitectura obligatoria preserva la secuencia:

  `QCC → QCC Bridge → Application / Runtime → Connector → Browser Runtime → SeleniumBase / Chrome`

  QCC no accede directamente a SeleniumBase ni a las tablas operativas del ERP. QCC Bridge es infraestructura de comunicación y no contiene lógica jurídica.

  El primer diseño debe priorizar HTTP localhost y/o WebSocket localhost, pero el contrato debe permitir sustituir posteriormente el transporte sin cambiar la semántica del sistema.

  El protocolo adopta el patrón `SNAPSHOT + EVENT STREAM`: al abrir o reconectar QCC se obtiene el estado actual y posteriormente se consumen eventos, evitando depender únicamente de eventos ocurridos mientras la extensión estaba desconectada.
* **Origen / Fuente primaria:** `20260821_resolucion_quesada_chrome_companion_qcc.md` (Sec. VIII, IX, X, XI, XII, XLIII y XLIV).
* **Justificación documentada:** Separar la extensión de Chrome del backend, del runtime y de la persistencia, manteniendo un protocolo provider-neutral y tolerante a reconexiones.
* **Invariantes:**
  - QCC no controla directamente SeleniumBase.
  - QCC no accede directamente a SQLite, PostgreSQL o Supabase.
  - Toda lectura o mutación operativa pasa por servicios backend.
  - QCC Bridge no contiene lógica jurídica.
  - El transporte es sustituible; la semántica del contrato debe permanecer estable.
* **Evolución y modificaciones:** Define la arquitectura de comunicación oficial entre QCC y backend.
* **Relaciones relevantes:** Conecta con `ARCH-001`, `WEB-001` y `QCC-001`.

#### `QCC-003` · No Interferencia Directa con el DOM en V1
* **Estado:** VIGENTE
* **Decisión vigente:** QCC no modificará el DOM de Mercurio ni de otras sedes electrónicas salvo que una funcionalidad futura sea expresamente diseñada, justificada y aprobada para ello.

  QCC V1 opera como panel independiente:

  `SeleniumBase / runtime → controla la sede`

  `QCC → muestra información del runtime`

  Por tanto, la no interferencia directa con el DOM es una regla vinculante para QCC V1 y para cualquier versión que no haya recibido una aprobación posterior específica que autorice otra capacidad.
* **Origen / Fuente primaria:** `20260821_resolucion_quesada_chrome_companion_qcc.md` (Sec. VII, XLVII y LVIII).
* **Justificación documentada:** Evitar dos motores compitiendo por controlar la misma página y reducir riesgo de conflicto con scripts, validaciones y firmas de las sedes.
* **Invariantes:**
  - QCC V1 no modifica directamente el DOM de las sedes.
  - Una capacidad futura de modificación DOM requiere diseño, justificación y aprobación expresa.
  - QCC no se convierte por ello en controlador alternativo del browser.
* **Evolución y modificaciones:** `20261005_resolucion_qcc_v2_augmentacion_dom_teaching_mode.md` formaliza QCC V2 mediante `QCC-004` y `QCC-005`; `QCC-003` permanece vigente para QCC V1 y para cualquier contexto no cubierto por la política V2 autorizada.
* **Relaciones relevantes:** Conecta con `QCC-001`, `QCC-002` y las futuras decisiones de Site Architecture.


#### `QCC-004` · Augmentación DOM Controlada, Reversible y Contextual
* **Estado:** VIGENTE
* **Decisión vigente:** QCC V2 puede añadir información, controles QCC, overlays, badges, indicadores, tooltips, resaltados y capas contextuales sobre páginas autorizadas sin convertirse en controlador alternativo del navegador ni en fuente de verdad del ERP.
* **Origen / Fuente primaria:** `20261005_resolucion_qcc_v2_augmentacion_dom_teaching_mode.md`.
* **Ownership DOM:** DOM nativo → observar/anclar; DOM QCC → crear/actualizar/retirar.
* **Estrategia:** `overlay-first`; la augmentación inline es excepcional, reversible, idempotente, testeada y gobernada por adapter/site contract.
* **Políticas por sitio:** `OBSERVE_ONLY`, `AUGMENT_PRESENTATION`, `ASSIST_INTERACTION`, `RUNTIME_ONLY`.
* **Acciones QCC:** `QCC → Bridge → Application Service → Domain/Persistence`; no SQL directo ni mutación arbitraria del sitio.
* **Separación:** Augmentación y automatización son capacidades distintas; la interacción nativa sigue bajo Application/Runtime → Connector → SeleniumBase/CDP cuando corresponda.
* **Fail-open:** Fallos de QCC/Bridge/recognizer/augmentación no deben inutilizar el sitio nativo.
* **Reversibilidad e idempotencia:** `INJECT → UPDATE → REMOVE`, sin duplicados por SPA, MutationObserver, refresh, reconexión o cambio de tab.
* **HUMAN_ONLY:** `SITE-003` permanece vinculante.
* **Seguridad:** No se insertan secretos, tokens, cookies, contraseñas ni valores de autenticación innecesarios.
* **Performance:** Eventos, scopes acotados y Geometry JIT; evitar rescans permanentes, timers agresivos y observers globales sin filtro.
* **Kill switch:** Desactivación global, por sitio o por feature sin impedir el uso nativo.
* **Ejemplos:** WhatsApp puede mostrar badges de lead/cliente/TASK/expediente; sedes electrónicas pueden mostrar contexto, ayudas, alertas y políticas sin ocultar ni alterar información oficial.
* **Relaciones relevantes:** `QCC-001`, `QCC-002`, `QCC-003`, `WEB-001`, `SITE-001`, `SITE-003`.

#### `QCC-005` · Teaching Mode Gobernado para Adquisición de Contratos de Interacción
* **Estado:** VIGENTE
* **Decisión vigente:** Teaching Mode permite enseñar elementos, funciones, acciones, estados previos, resultados esperados y transiciones para producir evidencia estructurada destinada a Site Architecture y automatización gobernada.
* **Origen / Fuente primaria:** `20261005_resolucion_qcc_v2_augmentacion_dom_teaching_mode.md`.
* **Salida:** `CANDIDATE KNOWLEDGE / CANDIDATE CONTRACT`, nunca `PRODUCTION RULE` automática.
* **Captura:** Selectores candidatos, atributos accesibles, role, texto, geometría, viewport, page signature, site/provider, procedure/flow, page_type, estado previo, acción, estado esperado, transición candidata, evidencia DOM y observables autorizados.
* **DOM First:** Respeta `WEB-003` y `SITE-002`; no depende solo de coordenadas.
* **Promoción:** Normalización, validación, comparación, tests, políticas y revisión cuando corresponda antes de integrar en Site Architecture.
* **HUMAN_ONLY:** Puede identificar una acción sensible, pero no degradar su política.
* **Privacidad:** No persiste secretos o datos personales innecesarios; conserva estructura/semántica/dependencia funcional minimizando identidad sin romper fidelidad.
* **Relaciones relevantes:** `QCC-004`, `WEB-003`, `SITE-001`, `SITE-002`, `SITE-003`, `TWIN-003`.

#### `QCC-006` · Panel QCC Obligatorio y `QccPresentationContext` para Automatizaciones Administrativas
* **Estado:** VIGENTE
* **Decisión vigente:** Toda automatización administrativa lanzada desde el CRM y ejecutada mediante QCC debe abrirse con un Panel QCC contextual que permita identificar inequívocamente cliente, expediente, subexpediente y documentación target de la presentación.
* **Origen / Fuente primaria:** `20261010_resolucion_panel_qcc_obligatorio_contexto_operativo_automatizaciones_administrativas.md`.
* **Contexto mínimo obligatorio:** `CLIENTE`, `EXPEDIENTE`, `SUBEXPEDIENTE` y `DOCUMENTACIÓN TARGET`. Si alguno no puede resolverse, el sistema debe distinguir información disponible, no configurada, documentación inexistente y error de resolución; queda prohibido mostrar silenciosamente contexto incorrecto.
* **Contrato funcional:** La implementación debe preservar un contrato equivalente a `QccPresentationContext` con identidad/display del cliente, expediente y subexpediente (`procedure_code` cuando corresponda) y `target_documents[]` con `document_id`, `filename`, `path` y `availability`. La denominación técnica concreta puede evolucionar.
* **Panel documental:** Cada documento target debe mostrarse en lista operativa y disponer obligatoriamente de `COPIAR RUTA`. La acción de ruta de carpeta completa puede añadirse como ayuda de nivel superior, sin sustituir las rutas individuales.
* **Arquitectura y autoridad:** QCC consume y presenta contexto procedente del CRM y de la autoridad documental. No crea entidades paralelas, no duplica información de negocio y no reconstruye rutas por su cuenta. Se mantiene `QCC → Bridge → Application/Runtime`.
* **Secuencia de apertura:** `CRM → seleccionar expediente → seleccionar subexpediente → lanzar automatización → crear Presentation Context → abrir/reutilizar Runtime SeleniumBase → abrir Panel QCC → ejecutar sede`. Una automatización no debe arrancar como sesión de navegador sin contexto cuando el contrato lo exige.
* **REAL / TWIN:** El mismo contrato contextual debe poder acompañar ejecución REAL y TWIN sin alterar la fuente de verdad del CRM; en TWIN se mantienen aislamiento, datos ficticios/seguros y políticas vigentes.
* **Criterio de integración:** Una automatización no se considera plenamente integrada con QCC si el Panel no permite visualizar como mínimo cliente, expediente, subexpediente, documentación target y copiar la ruta de cada documento sin abandonar el contexto de la sede.
* **Relaciones relevantes:** `QCC-001`, `QCC-002`, `QCC-004`, `ARCH-005`, `DATA-009`, `DOC-006`, `WEB-005`, `WEB-006`, `TWIN-007`.


---

## SECCIÓN III: INFORMACIÓN TÉCNICA NO NORMATIVA

*(Los contenidos integrados en esta sección poseen carácter estrictamente informativo, diagnóstico, de propuesta o de hoja de ruta. No constituyen decisiones normativas aprobadas ni alteran el cuerpo de reglas del ERP).*

### 1. EVOLUCIÓN QCC V2 FORMALIZADA

La evolución de QCC hacia augmentación contextual del DOM y Teaching Mode queda formalizada por `20261005_resolucion_qcc_v2_augmentacion_dom_teaching_mode.md` mediante `QCC-004` y `QCC-005`.

`QCC-003` continúa vigente para QCC V1. QCC V2 solo puede intervenir dentro de las políticas expresamente aprobadas, con ownership QCC, reversibilidad, idempotencia, fail-open, kill switch, separación respecto del runtime y respeto de `HUMAN_ONLY`.

Las demás capacidades de roadmap no formalizadas continúan siendo informativas hasta resolución o contrato posterior.

---

### 2. ESTADO TÉCNICO Y COBERTURA EN AUTOMATIZACIÓN Y QCC (NO NORMATIVO)
*(Fuentes: `30 mejorasQCC.txt`, `QCC_15_mejoras_futuras.txt`)*

- **Estado de consolidación del kernel QCC (Tests de Extensión):**
  - Kernel consolidado con 301/301 tests de extensión pasando.
  - Cobertura de funcionalidades consolidadas: Selector Self-Healing gobernado (✅), Contract Watcher (✅), Navigation Graph (✅), Automation Readiness (✅).
- **Capacidades en desarrollo/integración:**
  - Geometry JIT (🟢), Network Observable Contract (🟢), Teaching Mode (⚪), Causal Interaction Graph (⚪), Flight Recorder (⚪).

---

### 3. ROADMAP Y PROPUESTAS FUTURAS DE QCC (ROADMAP NO NORMATIVO)
*(Fuentes: `QCC_15_mejoras_futuras.txt`, `30 mejorasQCC.txt`)*

- **Evolución prevista del companion:**
  - Expansión hacia un motor universal de comprensión de sedes web (*Universal Web Twin* / UWT) para la automatización de trámites complejos de extranjería.
  - Integración con el catálogo de 30 mejoras de QCC como guía de evolución técnica gradual.

---

> ESTADO: 04_QCC_BROWSER_AUTOMATION — APROBADO POR DIRECCIÓN
