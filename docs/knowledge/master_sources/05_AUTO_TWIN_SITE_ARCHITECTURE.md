# `05_AUTO_TWIN_SITE_ARCHITECTURE.md` — FUENTE MAESTRA DE SITE ARCHITECTURE, SISTEMA LABS Y AUTO TWIN

**Proyecto:** Quesada Abogados CRM
**Naturaleza del Documento:** Fuente Maestra Consolidada 05 de 06
**Estado:** APROBADO POR DIRECCIÓN
**Trazabilidad:** Construido a partir del Registro Canónico Aprobado (`00_MASTER_INDEX.md`).
**FUENTES NORMATIVAS BASE:** `20260822_resolucion_qcc_site_architecture_dom_geometry_interaction.md`, `20260822_resolucion_sistema_labs_sedes_electronicas.md`, `20260905_resolucion_qcc_auto_twin_arquitectura_fidelidad_sincronizacion.md`, `20261005_resolucion_runtime_twin_gobernado_preproduccion.md`.
**FUENTES INFORMATIVAS NO NORMATIVAS:** `AMPLIACIONQCC.txt` (Programa UWT-1..12), `30 mejorasQCC.txt` (métricas de avance de Twins/LABs).

---

## SECCIÓN I: MARCO GENERAL Y ALCANCE

La presente Fuente Maestra consolida de forma unificada las decisiones normativas aprobadas sobre **QCC Site Architecture** (contratos estructurales, geométricos y semánticos de sedes electrónicas), el **Sistema LABS** (entornos locales gobernados) y la capacidad **AUTO TWIN** (construcción, sincronización y materialización automática de réplicas de sedes públicas).

La Fuente Maestra no crea autoridad normativa por sí misma. Consolida las decisiones normativas aprobadas contenidas en las fuentes originales del proyecto Quesada Abogados CRM, preservando el principio de aislamiento estricto entre entornos reales y locales, el recálculo geométrico *Just-In-Time* (JIT), la clasificación obligatoria de políticas `HUMAN_ONLY` y el flujo de promoción validada REAL ↔ TWIN.

---

## SECCIÓN II: DECISIONES NORMATIVAS APROBADAS (SITE, TWIN)

### 1. SITE ARCHITECTURE Y CONTRATOS DE SEDE (`SITE`)

#### `SITE-001` · QCC Site Architecture y Contratos de Sede
* **Estado:** VIGENTE
* **Decisión vigente:** Se aprueba QCC Site Architecture como evolución oficial de la infraestructura de Arquitectura DOM. La captura deja de limitarse a HTML/DOM puro y evoluciona hacia un contrato compuesto por identidad de página, estructura DOM, semántica, selectores, geometría, visibilidad, estados, interacciones, transiciones, JavaScript relevante, observables de red y metadata diagnóstica.

  La identidad funcional de una pantalla no depende exclusivamente de su URL. El contrato puede incorporar, entre otros, `url`, `origin`, `pathname`, `query`, `title`, `provider`, `site`, `procedure`, `flow`, `page_type` y `page_signature`.

  QCC Site Architecture es la infraestructura principal de adquisición del contrato REAL utilizado por LABS/AUTO TWIN. Las capturas pueden proceder tanto de Chrome gobernado mediante SeleniumBase/CDP como de Chrome normal mediante QCC, debiendo converger hacia un esquema canónico común.
* **Origen / Fuente primaria:** `20260822_resolucion_qcc_site_architecture_dom_geometry_interaction.md` (Sec. III a VI, XXXI a XLIV y LXXV).
* **Justificación documentada:** Disponer de una representación estructural, semántica, geométrica e interactiva suficientemente rica para comprender, comparar, reproducir y automatizar sedes electrónicas.
* **Invariantes:**
  - DOM es una capa del contrato, no el contrato completo.
  - El Site Contract debe poder versionarse y compararse.
  - Las capturas reales con datos personales son artefactos sensibles y deben sanitizarse antes de convertirse en fixtures versionados.
  - La capa genérica de Site Architecture permanece separada de la semántica específica de cada proveedor.
* **Evolución y modificaciones:** AUTO TWIN utiliza Site Architecture como fuente canónica para materialización y sincronización.
* **Relaciones relevantes:** Conecta con `QCC-001`, `SITE-002`, `SITE-003` y `TWIN-003`.

#### `SITE-002` · Capa Geométrica JIT y Prohibición de Coordenadas Fijas
* **Estado:** VIGENTE
* **Decisión vigente:** Se incorpora obligatoriamente una capa geométrica que relaciona cada elemento relevante con su `boundingClientRect`, viewport, scroll y, cuando resulte técnicamente necesario para interacción GUI, con la ventana Chrome y las coordenadas físicas derivadas.

  Las coordenadas de pantalla no se consideran identificadores permanentes de un elemento ni deben utilizarse ordinariamente como contrato estático. Cuando sea necesario mouse o automatización de escritorio se seguirá, siempre que resulte técnicamente posible:

  `Locate → Validate → Recalculate → Act`

  Toda acción GUI basada en geometría debe recalcular inmediatamente antes de actuar la posición, visibilidad, viewport, scroll y dimensiones relevantes.
* **Origen / Fuente primaria:** `20260822_resolucion_qcc_site_architecture_dom_geometry_interaction.md` (Sec. XIII a XXIII y LXXV).
* **Justificación documentada:** Evitar que cambios de viewport, scroll, zoom, posición de ventana, escala o layout invaliden una interacción basada en geometría.
* **Invariantes:**
  - La geometría se captura inicialmente respecto del viewport junto con su contexto.
  - No se asume que coordenadas DOM equivalgan directamente a coordenadas físicas de pantalla.
  - Si una acción GUI necesita coordenadas físicas, estas deben derivarse del estado geométrico actual, no reutilizar valores rígidos antiguos.
* **Evolución y modificaciones:** Complementa `WEB-003` y alimenta la fidelidad geométrica de AUTO TWIN.
* **Relaciones relevantes:** Conecta con `WEB-003`, `SITE-001` y `TWIN-003`.

#### `SITE-003` · Clasificación Estricta de Políticas `HUMAN_ONLY`
* **Estado:** VIGENTE
* **Decisión vigente:** QCC Site Architecture puede clasificar acciones que deban permanecer bajo control humano mediante:

  `interaction_policy = HUMAN_ONLY`

  Entre los ejemplos expresamente contemplados se encuentran CAPTCHA, firma, presentación definitiva, confirmación jurídica y otras acciones irreversibles. La mera existencia de información DOM o geométrica no autoriza automatizar una acción clasificada como `HUMAN_ONLY`.

  AUTO TWIN mantiene estas políticas durante descubrimiento, actualización y aprendizaje: el modo de descubrimiento no puede utilizarse para eludir la gobernanza de interacción.
* **Origen / Fuente primaria:** `20260822_resolucion_qcc_site_architecture_dom_geometry_interaction.md` (Sec. XXI a XXIV), reafirmada por `20260905_resolucion_qcc_auto_twin_arquitectura_fidelidad_sincronizacion.md` (Sec. 9 y 31).
* **Justificación documentada:** Separar capacidad técnica de interacción de autorización funcional para ejecutar acciones sensibles o irreversibles.
* **Invariantes:**
  - Una acción marcada `HUMAN_ONLY` continúa requiriendo control humano aunque exista selector, geometría o capacidad técnica para automatizarla.
  - AUTO TWIN no puede reclasificar por sí solo una acción para saltarse esa política.
* **Evolución y modificaciones:** Reafirmada por AUTO TWIN sin alterar su significado.
* **Relaciones relevantes:** Conecta con `QCC-003`, `WEB-003` y `TWIN-003`.

---

### 2. SISTEMA LABS Y AUTO TWIN (`TWIN`)

#### `TWIN-001` · Institución del Sistema LABS de Sedes Electrónicas
* **Estado:** VIGENTE
* **Decisión vigente:** Se instituye el Sistema LABS como infraestructura obligatoria y permanente para automatizaciones de sedes electrónicas. Cada sede automatizada debe disponer de su propio entorno LAB suficiente para reproducir el recorrido automatizado.

  Un LAB es un entorno local navegable que reproduce con la máxima fidelidad posible el contrato observable y operativo de la sede real dentro del alcance necesario para el ERP. En Mercurio, cada modelo EX con funcionamiento propio debe disponer de su LAB específico, reutilizando componentes comunes cuando corresponda.

  El desarrollo y las pruebas ordinarias deben realizarse contra LAB cuando exista un equivalente suficiente. Las excepciones a disponer de LAB para una automatización definitiva deben ser técnicas, justificadas, temporales y documentadas.
* **Origen / Fuente primaria:** `20260822_resolucion_sistema_labs_sedes_electronicas.md` (Sec. II a VII, X, XXVIII a XXXI).
* **Justificación documentada:** Sustituir la prueba y error sobre sedes reales por desarrollo local reproducible, regresión controlada y validación E2E.
* **Invariantes:**
  - Cada sede mantiene su contrato, flujos, fixtures, escenarios, tests, evolución y versión.
  - En Mercurio no se asume que dos modelos EX compartan idéntico contrato.
  - Un LAB no es un mock estático: debe poder reproducir el comportamiento observable requerido por el flujo.
* **Evolución y modificaciones:** El mecanismo ordinario de construcción manual de LABS es sustituido progresivamente por AUTO TWIN.
* **Relaciones relevantes:** Conecta con `TWIN-002`, `TWIN-003` y `TWIN-004`.

#### `TWIN-002` · Sustitución del Método Manual por AUTO TWIN
* **Estado:** SUPERADA PARCIALMENTE
* **Decisión vigente:** La construcción manual pantalla por pantalla deja de ser el mecanismo ordinario de construcción de LABS/Twins y es sustituida progresivamente por AUTO TWIN.

  La construcción manual permanece como mecanismo excepcional para particularidades no reproducibles automáticamente, `overrides` puntuales y conservación de Twins manuales como Golden References, fixtures, contratos de regresión y base comparativa del generador automático.
* **Origen / Fuente primaria:** `20260822_resolucion_sistema_labs_sedes_electronicas.md`, modificada parcialmente por `20260905_resolucion_qcc_auto_twin_arquitectura_fidelidad_sincronizacion.md` (Sec. 27 a 31).
* **Justificación documentada:** Escalar la construcción y mantenimiento de réplicas sin depender de reconstrucción manual ordinaria.
* **Invariantes:**
  - Los overrides son excepcionales, versionados, documentados y de ámbito limitado.
  - Los Twins manuales existentes no se eliminan: se conservan como referencias y regresión.
  - El mecanismo automático no elimina la posibilidad de intervención manual justificada.
* **Evolución y modificaciones:** `TWIN-003` constituye la decisión modificadora que provoca su estado `SUPERADA PARCIALMENTE`.
* **Relaciones relevantes:** Conecta con `TWIN-001` y `TWIN-003`.

#### `TWIN-003` · Capacidad AUTO TWIN y Fidelidad en Rendering Profile
* **Estado:** VIGENTE
* **Decisión vigente:** AUTO TWIN es una capacidad estructural propia de QCC destinada a construir, mantener, actualizar, versionar y validar réplicas locales de sedes electrónicas y otras aplicaciones web observadas por QCC.

  AUTO TWIN adopta como **objetivo** una fidelidad práctica del 100 % visual, geométrica, estructural e interactiva respecto del REAL dentro de un **QCC Rendering Profile** controlado. No se exige identidad pixel-perfect en cualquier ordenador o configuración arbitraria; la equivalencia se evalúa respecto del perfil de render sobre el que el TWIN haya sido generado y validado.

  El materializador parte de evidencia REAL y de Site Architecture, que actúa como fuente conceptual canónica. El código HTML generado por el TWIN no es la fuente de verdad.

  Se aprueba un perfil Chrome persistente `TWIN DISCOVERY`, gestionado mediante SeleniumBase y QCC, para descubrimiento, construcción, exploración segura, captura y validación. AUTO TWIN no depende exclusivamente de ese perfil: los navegadores REAL utilizados diariamente también pueden actuar como red distribuida de observación y detección de cambios.
* **Origen / Fuente primaria:** `20260905_resolucion_qcc_auto_twin_arquitectura_fidelidad_sincronizacion.md` (Sec. 1 a 9, 20 a 31).
* **Justificación documentada:** Disponer de réplicas suficientemente fieles para desarrollo, regresión, validación de selectores, navegación, geometría e interacción sin utilizar la sede real como banco ordinario de pruebas.
* **Invariantes:**
  - La fidelidad del 100 % es un objetivo práctico dentro de un Rendering Profile controlado y respecto de lo técnicamente observable.
  - `TWIN DISCOVERY` es un perfil persistente gobernado mediante SeleniumBase/QCC.
  - Los navegadores REAL pueden observar y alimentar revisiones, pero no deben realizar exploraciones activas que interfieran con expedientes reales.
  - Site Architecture es la fuente canónica para la materialización.
  - Las políticas `HUMAN_ONLY` siguen siendo vinculantes durante descubrimiento y actualización.
* **Evolución y modificaciones:** Sustituye la construcción manual ordinaria de `TWIN-002` y desarrolla el Sistema LABS.
* **Relaciones relevantes:** Conecta con `SITE-001`, `SITE-002`, `SITE-003`, `WEB-001` y `TWIN-005`.

#### `TWIN-004` · Aislamiento de Producción, Datos Ficticios y Guardas Localhost
* **Estado:** VIGENTE
* **Decisión vigente:** Los LABS utilizan exclusivamente personas, identificadores, expedientes y documentos ficticios o sintéticos para sus escenarios de prueba. Las capturas procedentes de sedes reales deben sanitizarse antes de convertirse en fixtures permanentes.

  Todo LAB debe diseñarse para que no pueda producir accidentalmente una actuación administrativa real. Se utilizarán preferentemente `127.0.0.1` / `localhost`, y los tests E2E deben incorporar guardas que impidan ejecutarse contra hosts productivos. `LAB_LOCALHOST_GUARD` figura en la resolución como ejemplo del contrato de seguridad esperado.

  Un LAB nunca debe presentar solicitudes reales, firmar solicitudes reales, registrar escritos reales, reservar citas reales ni modificar expedientes administrativos reales.
* **Origen / Fuente primaria:** `20260822_resolucion_sistema_labs_sedes_electronicas.md` (Sec. XIII a XV), mantenida por la arquitectura AUTO TWIN.
* **Justificación documentada:** Impedir que pruebas, fixtures o simulaciones locales produzcan efectos administrativos reales o expongan datos personales.
* **Invariantes:**
  - Los fixtures permanentes no incorporan innecesariamente datos personales reales.
  - Las capturas reales deben sanitizarse antes de versionarse como fixture.
  - Los tests E2E deben impedir la ejecución contra hosts productivos.
  - El entorno de prueba no puede producir efectos administrativos reales.
* **Evolución y modificaciones:** AUTO TWIN mantiene estos principios de aislamiento al sustituir el mecanismo ordinario de construcción.
* **Relaciones relevantes:** Conecta con `SEC-001`, `DEV-003` y `TWIN-003`.

#### `TWIN-005` · Validación Obligatoria REAL ↔ TWIN para Promoción de Revisiones
* **Estado:** VIGENTE
* **Decisión vigente:** Los cambios detectados en REAL deben producir revisiones candidatas y nunca sobrescribir directamente el último TWIN validado.

  AUTO TWIN debe comparar REAL ↔ TWIN mediante validación visual, geométrica y estructural, complementada por comportamiento observable y navegación cuando corresponda. Una revisión candidata solo puede pasar a `ACTIVE` después de superar la validación prevista por el sistema.

  El flujo normativo de actualización es:

  `REAL cambia → Candidate Revision → regeneración/materialización → validación REAL ↔ TWIN → promoción → ACTIVE`
* **Origen / Fuente primaria:** `20260905_resolucion_qcc_auto_twin_arquitectura_fidelidad_sincronizacion.md` (Sec. 19 a 23, 26, 30 y 31).
* **Justificación documentada:** Evitar que observaciones incompletas, capturas corruptas o cambios parciales sustituyan automáticamente una réplica estable.
* **Invariantes:**
  - Un cambio REAL no sobrescribe directamente el TWIN activo.
  - Una revisión solo alcanza `ACTIVE` tras validación.
  - El TWIN se materializa desde evidencia REAL / Site Architecture, no por reconstrucción visual “a ojo”.
* **Evolución y modificaciones:** Define el gobierno de revisiones y promoción de AUTO TWIN.
* **Relaciones relevantes:** Conecta con `TWIN-003` y `SITE-001`.


#### `TWIN-006` · Runtime TWIN Gobernado de Preproducción
* **Estado:** VIGENTE
* **Decisión vigente:** Todo TWIN local destinado a desarrollo, prueba, validación, navegación, interacción o ejecución de automatizaciones debe abrirse o reutilizarse dentro de un runtime SeleniumBase gobernado. El navegador TWIN es un entorno técnico controlado de preproducción y no una pestaña del Chrome personal ordinario.
* **Origen / Fuente primaria:** `20261005_resolucion_runtime_twin_gobernado_preproduccion.md`.
* **Separación de contextos:**
  - la observación REAL puede proceder de SeleniumBase/CDP gobernado, Chrome normal autorizado mediante QCC u otros puntos aprobados;
  - el runtime TWIN local/preproducción se ejecuta mediante SeleniumBase gobernado;
  - observar REAL desde Chrome normal no convierte ese navegador en runtime TWIN.
* **Arquitectura:** `CRM / Dirección funcional → Runtime / Service → SeleniumBase / CDP → Chrome TWIN → QCC → Usuario`.
* **Ownership:** El runtime debe tener ownership identificable y gestionar de forma gobernada creación, reutilización, sesión, cierre, navegador asociado, revisión y evidencia.
* **Aislamiento:** El aislamiento exigido es de runtime, ownership, perfil, sesión y efectos; no implica eliminar indiscriminadamente información funcional necesaria.
* **Fidelidad funcional:** El TWIN debe conservar o modelar la información estructural, semántica, técnica y de estado necesaria para reproducir correctamente transiciones, validaciones y comportamiento REAL.
* **Minimización funcional:** Los datos personales se sustituyen, minimizan, sanitizan o pseudonimizan cuando ello no rompa la fidelidad. Queda prohibida una sanitización tan agresiva que impida reproducir estados o transiciones.
* **Ejemplo:** Si en Mercurio `selección de supuesto → Continuar → pantalla EX correspondiente` depende de valores, estado de formulario, atributos, parámetros, respuestas o relaciones observadas en REAL, AUTO TWIN debe conservar o modelar la información funcional suficiente para reproducir la transición.
* **Seguridad:** El runtime TWIN no produce efectos administrativos reales y mantiene las guardas de `TWIN-004`.
* **HUMAN_ONLY:** `SITE-003` permanece vinculante; disponer de TWIN no habilita CAPTCHA, firma, presentación definitiva, confirmación jurídica ni acciones irreversibles.
* **Promoción:** `TWIN-005` permanece vigente. El runtime TWIN gobernado es el entorno ordinario para pruebas locales y validación previa a promoción.
* **Relación con Discovery:** `TWIN DISCOVERY` sirve para adquisición/aprendizaje del REAL; el runtime TWIN sirve para ejecución local/preproducción. Pueden compartir infraestructura, pero son responsabilidades distintas.
* **Invariantes:**
  - Chrome personal no es runtime TWIN;
  - aislamiento de sesiones y efectos no equivale a eliminación de información funcional necesaria;
  - Site Architecture continúa siendo fuente conceptual canónica de materialización;
  - TWIN no autoriza por sí solo interacción REAL;
  - la resolución no autoriza QCC V2 ni augmentación activa del DOM.
* **Relaciones relevantes:** `SITE-001`, `SITE-003`, `WEB-001`, `TWIN-003`, `TWIN-004`, `TWIN-005`.
---

## SECCIÓN III: INFORMACIÓN TÉCNICA NO NORMATIVA

*(Los contenidos integrados en esta sección poseen carácter estrictamente informativo, diagnóstico, de porcentaje de avance o de hoja de ruta de desarrollo. No constituyen decisiones normativas aprobadas ni alteran las reglas del ERP).*

### 1. ESTADO TÉCNICO Y COBERTURA DE SEDES (NO NORMATIVO)

Esta Fuente Maestra no fija como estado actual permanente la materialización concreta de Mercurio, Red SARA, DEHú, Nacionalidad ni de modelos EX individuales.

Los documentos de roadmap y ejecución contienen estados, revisiones, porcentajes y secuencias de trabajo que pueden quedar obsoletos rápidamente. Por ello, esos datos deberán consultarse en el estado operativo vigente del proyecto y no se elevan a contrato normativo en esta Fuente Maestra.

Las referencias de la resolución AUTO TWIN a EX01 como Golden Twin inicial y EX02 como primera construcción automática desde cero se conservan únicamente como parte de la estrategia de transición aprobada en septiembre de 2026, no como descripción del estado técnico actual.

---

### 2. EVOLUCIÓN DEL RUNTIME TWIN FORMALIZADA

La evolución que separa observación REAL y runtime local TWIN queda formalizada por `20261005_resolucion_runtime_twin_gobernado_preproduccion.md` mediante `TWIN-006`.

La observación REAL puede seguir procediendo de navegadores ordinarios autorizados mediante QCC cuando corresponda, mientras que el TWIN local/preproducción se ejecuta dentro de un runtime SeleniumBase gobernado.

La resolución aclara además que aislamiento y minimización de datos no deben degradar la fidelidad funcional ni impedir construir correctamente estados, validaciones o transiciones.

---

### 3. ROADMAP AUTO TWIN Y EXTENSIÓN DE SEDES (ROADMAP NO NORMATIVO)
*(Fuente: `AMPLIACIONQCC.txt` — Programa Universal Web Twin UWT-1 a UWT-12)*

- **Naturaleza del programa:** El programa Universal Web Twin (UWT) define la hoja de ruta para la extensión progresiva de la capacidad AUTO TWIN a múltiples sedes administrativas. No es una norma de arquitectura del ERP Quesada Abogados.
- **Fases programadas del roadmap UWT:**
  - `UWT-1`: Branch Intent & Context Isolation.
  - `UWT-2`: DOM Capture & Structure Sanitization.
  - `UWT-3`: Visual & CSS Asset Mirroring.
  - `UWT-4`: Geometry & Viewport JIT Sync.
  - `UWT-5`: Form Input & Validation Emulation.
  - `UWT-6`: Multi-step Transition Graph.
  - `UWT-7`: Local HTTP Replica Materializer.
  - `UWT-8`: Localhost Safety Guard & Fictive Data Injection.
  - `UWT-9`: Differential Change Watcher.
  - `UWT-10`: Automated REAL ↔ TWIN Validation Suite.
  - `UWT-11`: Autonomous Exploration in Discovery Profile.
  - `UWT-12`: Multi-site Certification & Production Promotion.

---

> ESTADO: 05_AUTO_TWIN_SITE_ARCHITECTURE — APROBADO POR DIRECCIÓN
