# `04_QCC_BROWSER_AUTOMATION.md` — FUENTE MAESTRA DE AUTOMATIZACIÓN WEB, CDP Y QUESADA CHROME COMPANION (QCC)

**Proyecto:** Quesada Abogados CRM
**Naturaleza del Documento:** Fuente Maestra Consolidada 04 de 06
**Estado:** APROBADO POR DIRECCIÓN
**Trazabilidad:** Construido a partir del Registro Canónico Aprobado (`00_MASTER_INDEX.md`).
**FUENTES NORMATIVAS BASE:** `20260815_resolucion_arquitectura_y_gobierno_infraestructura_seleniumbase_cdp.md`, `20260821_resolucion_quesada_chrome_companion_qcc.md`.
**ANTECEDENTES TÉCNICOS:** `003_ecosistema_tecnologico.md` (integración inicial de automatizaciones).
**FUENTES INFORMATIVAS NO NORMATIVAS:** `QCC_15_mejoras_futuras.txt`, `30 mejorasQCC.txt`, `AMPLIACIONQCC.txt` (estado de implementación, roadmap y propuestas futuras).

---

## SECCIÓN I: MARCO GENERAL Y ALCANCE

La presente Fuente Maestra consolida de forma unificada las decisiones normativas aprobadas sobre la infraestructura común de automatización web mediante SeleniumBase y Chrome DevTools Protocol (CDP), la arquitectura de ejecución en segundo plano, las reglas de aislamiento de runtimes y la institución de Quesada Chrome Companion (QCC) como interfaz contextual del navegador conectada al ERP mediante QCC Bridge.

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
* **Evolución y modificaciones:** Las propuestas posteriores de inyección o aumento visual del DOM no alteran esta decisión mientras no exista una resolución posterior que las formalice.
* **Relaciones relevantes:** Conecta con `QCC-001`, `QCC-002` y las futuras decisiones de Site Architecture.

---

## SECCIÓN III: INFORMACIÓN TÉCNICA NO NORMATIVA

*(Los contenidos integrados en esta sección poseen carácter estrictamente informativo, diagnóstico, de propuesta o de hoja de ruta. No constituyen decisiones normativas aprobadas ni alteran el cuerpo de reglas del ERP).*

### 1. DIVERGENCIA DOCUMENTAL–OPERATIVA (NO NORMATIVO)

La evolución técnica posterior contempla capacidades de QCC que exceden el alcance de QCC V1, incluyendo *Teaching Mode*, recopilación geométrica, Contract Watcher, capas visuales y propuestas de intervención/contextualización más profunda sobre páginas web.

Estas capacidades aparecen en documentos de roadmap o ejecución como `30 mejorasQCC.txt` y `AMPLIACIONQCC.txt`, pero no modifican por sí mismas `QCC-003`.

Hasta que una resolución posterior formalice expresamente una evolución del contrato de intervención de QCC sobre el DOM, `QCC-003` conserva su vigencia con el alcance aprobado para V1.

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
