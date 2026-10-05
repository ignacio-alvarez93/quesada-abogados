# RESOLUCIÓN DE EVOLUCIÓN DEL RUNTIME TWIN GOBERNADO DE PREPRODUCCIÓN

**Fecha:** 05/10/2026
**Proyecto:** Quesada Abogados
**Estado:** APROBADA POR DIRECCIÓN
**Ámbito:** QCC, AUTO TWIN, SeleniumBase/CDP, runtime local, preproducción, aislamiento y promoción.

---

## I. OBJETO

La presente resolución formaliza una evolución operativa ya consolidada en el proyecto:

> **el TWIN local se ejecuta como entorno de preproducción dentro de un runtime SeleniumBase gobernado y no en el Chrome personal ordinario del usuario.**

La resolución no sustituye ni deroga las decisiones existentes sobre Site Architecture, LABS o AUTO TWIN.

Desarrolla específicamente:

- `TWIN-003` · Capacidad AUTO TWIN y Fidelidad en Rendering Profile.
- `TWIN-004` · Aislamiento de Producción, Datos Ficticios y Guardas Localhost.
- `TWIN-005` · Validación Obligatoria REAL ↔ TWIN para Promoción de Revisiones.

---

## II. TWIN-006 · RUNTIME TWIN GOBERNADO DE PREPRODUCCIÓN

Se aprueba:

`TWIN-006 · Runtime TWIN Gobernado de Preproducción`

Todo TWIN local destinado a desarrollo, prueba, validación, navegación, interacción o ejecución de automatizaciones deberá abrirse o reutilizarse dentro de un **runtime SeleniumBase gobernado**.

El navegador TWIN es un entorno técnico controlado del proyecto y no una pestaña del navegador personal ordinario del usuario.

---

## III. SEPARACIÓN ENTRE REAL Y TWIN

Se establecen dos contextos conceptualmente distintos:

### A. OBSERVACIÓN REAL

Las sedes y aplicaciones reales pueden ser observadas, según la arquitectura vigente, mediante:

- SeleniumBase/CDP gobernado;
- Chrome normal autorizado mediante QCC;
- otros puntos de observación expresamente aprobados.

La observación REAL puede alimentar:

- Site Architecture;
- detección de cambios;
- Candidate Revisions;
- evidencia;
- actualización de contratos.

La observación REAL no convierte ese navegador en runtime TWIN.

### B. RUNTIME TWIN

El TWIN local se ejecuta exclusivamente como entorno local controlado mediante SeleniumBase.

Su finalidad es:

- preproducción;
- desarrollo;
- navegación local;
- validación;
- regresión;
- ensayo de automatizaciones;
- reproducción de estados;
- comprobación REAL ↔ TWIN.

---

## IV. PRINCIPIO DE PREPRODUCCIÓN

El TWIN constituye la **preproducción funcional de las automatizaciones web**.

Su criterio principal de calidad es la **fidelidad funcional suficiente para reproducir el comportamiento relevante del REAL**, no la eliminación máxima de información.

Antes de promover una automatización o revisión hacia interacción REAL, deberá probarse contra el TWIN cuando exista un equivalente suficiente.

El flujo objetivo será:

```text
CONTRATO REAL / SITE ARCHITECTURE
        ↓
CANDIDATE REVISION
        ↓
MATERIALIZACIÓN TWIN
        ↓
RUNTIME TWIN SELENIUMBASE
        ↓
AUTOMATIZACIÓN / TESTS / REGRESIÓN
        ↓
VALIDACIÓN REAL ↔ TWIN
        ↓
PROMOCIÓN
        ↓
REAL
```

El TWIN no autoriza por sí mismo una actuación en REAL.

---

## V. ARQUITECTURA DE GOBIERNO

El flujo de responsabilidad queda establecido como:

```text
CRM / DIRECCIÓN FUNCIONAL
        ↓ gobierna
RUNTIME / SERVICE
        ↓ ejecuta
SELENIUMBASE / CDP
        ↓ controla
CHROME TWIN
        ↓ muestra
QCC
        ↓ contextualiza / observa / asiste
USUARIO
```

QCC no sustituye al runtime.

Chrome no decide el ciclo de vida.

SeleniumBase/Runtime controla:

- creación;
- reutilización;
- ownership;
- sesión;
- cierre;
- navegación gobernada;
- evidencia técnica.

---

## VI. APERTURA Y REUTILIZACIÓN

Cuando el usuario acceda a un TWIN desde QCC o desde el CRM:

1. el sistema deberá resolver qué TWIN y revisión corresponden;
2. comprobar si existe un runtime gobernado compatible;
3. reutilizarlo si cumple contrato de ownership, sesión y revisión;
4. crear uno nuevo cuando no exista runtime válido;
5. abrir el TWIN dentro del Chrome SeleniumBase correspondiente.

No deberá utilizarse `webbrowser.open()`, una pestaña arbitraria del Chrome personal ni mecanismos equivalentes como vía ordinaria de ejecución del TWIN.

---

## VII. OWNERSHIP Y SESIÓN

Todo runtime TWIN deberá tener ownership identificable.

Cuando proceda deberán poder conocerse:

- site/provider;
- twin/revision;
- profile/runtime;
- session id;
- proceso propietario;
- estado;
- timestamps relevantes;
- work/order o contexto de ejecución;
- origen de apertura;
- política de cierre/reutilización.

Dos procesos no deberán asumir simultáneamente ownership incompatible sobre el mismo runtime.

La reutilización deberá ser explícita y segura.

---

## VIII. AISLAMIENTO DE SESIONES, NO AISLAMIENTO FUNCIONAL

El Chrome personal ordinario del usuario no forma parte del contrato de ejecución del TWIN.

El aislamiento exigido por esta resolución es principalmente un **aislamiento de runtime, ownership, perfil, sesión y efectos**, no una obligación de eliminar indiscriminadamente toda la información observada en REAL.

Su finalidad es evitar:

- contaminación entre sesiones personales y de preproducción;
- interferencia de extensiones o pestañas no gobernadas;
- pérdida de trazabilidad;
- diferencias de perfil no controladas;
- ejecución accidental contra destinos REAL;
- confusión entre navegador observado y navegador ejecutor.

Este aislamiento **no debe degradar la fidelidad funcional del TWIN**.

Cuando una transición, condición de navegación, selector, estado de formulario, respuesta del servidor, dato técnico, estructura DOM, parámetro o evidencia observada sea necesaria para reproducir correctamente el comportamiento REAL, podrá conservarse o modelarse de forma gobernada en el Site Contract, fixtures o estado del TWIN.

El principio será:

```text
AISLAR SESIONES Y EFECTOS
        ≠
ELIMINAR INFORMACIÓN FUNCIONAL NECESARIA
```

El usuario puede seguir utilizando su Chrome normal para trabajo ordinario y, cuando corresponda, QCC puede observarlo conforme a Site Architecture.

Esa capacidad de observación no modifica el aislamiento del runtime TWIN.

---

## IX. DATOS, FIDELIDAD FUNCIONAL Y MINIMIZACIÓN

`TWIN-004` permanece vigente, pero su aplicación deberá interpretarse conjuntamente con el objetivo de fidelidad funcional de `TWIN-003`.

El TWIN debe utilizar preferentemente datos ficticios, sintéticos, sanitizados o pseudonimizados **siempre que permitan reproducir fielmente el comportamiento observado**.

No se exige sustituir o eliminar información cuando hacerlo impida:

- construir correctamente una transición;
- reproducir un estado;
- activar una validación;
- conservar una relación entre controles;
- reproducir navegación condicional;
- reproducir un contrato de formulario;
- mantener una dependencia técnica necesaria;
- ejecutar una automatización de preproducción con fidelidad suficiente.

### Principio de minimización funcional

La regla será:

```text
CONSERVAR LO NECESARIO PARA REPRODUCIR EL COMPORTAMIENTO
        ↓
MINIMIZAR / SANITIZAR LO IDENTIFICATIVO O SENSIBLE
        ↓
NO CONSERVAR INFORMACIÓN PERSONAL INNECESARIA
```

Por tanto:

- los identificadores personales reales no se conservarán si pueden sustituirse sin afectar al comportamiento;
- los valores estructurales o técnicos necesarios para reproducir estados o transiciones sí podrán conservarse o modelarse;
- los datos reales observados durante Discovery podrán utilizarse transitoriamente para comprender el comportamiento, siempre bajo runtime gobernado y sin convertirse automáticamente en fixtures permanentes;
- los fixtures permanentes deberán minimizar datos personales, pero podrán preservar forma, formato, cardinalidad, dependencias, longitudes, relaciones o valores funcionalmente significativos;
- cuando una captura o evidencia REAL sea necesaria para construir correctamente el TWIN, deberá sanitizarse de forma que mantenga la semántica y comportamiento relevantes;
- queda prohibido aplicar una sanitización tan agresiva que rompa la lógica funcional del sitio reproducido.

### Ejemplo normativo

Si en Mercurio una transición como:

```text
selección de supuesto
→ Continuar
→ carga de pantalla EX correspondiente
```

depende de valores, estado de formulario, atributos, parámetros, respuestas o relaciones observadas en REAL, AUTO TWIN deberá conservar o modelar esa información funcional suficiente para reproducir la transición correcta.

El objetivo no es ocultar toda la información.

El objetivo es **evitar datos personales innecesarios sin destruir la fidelidad estructural, semántica, geométrica, interactiva y funcional del TWIN**.

### Prohibiciones

El runtime TWIN:

- no producirá efectos administrativos reales;
- no presentará solicitudes reales;
- no firmará;
- no registrará escritos reales;
- no reservará citas reales;
- no modificará expedientes administrativos reales.

El runtime deberá mantener guardas suficientes contra hosts productivos en pruebas E2E.

---

## X. HUMAN_ONLY

`SITE-003` permanece plenamente vigente.

La existencia de un TWIN o de capacidad técnica de interacción no habilita automáticamente:

- CAPTCHA;
- firma;
- presentación definitiva;
- confirmación jurídica;
- acciones irreversibles;
- otras acciones clasificadas `HUMAN_ONLY`.

El TWIN puede reproducir o ensayar la superficie observable, pero no puede degradar ni eludir la política de interacción.

---

## XI. VALIDACIÓN Y PROMOCIÓN

`TWIN-005` permanece plenamente vigente.

Una Candidate Revision solo podrá promocionarse a `ACTIVE` tras superar las validaciones previstas.

La validación deberá realizarse, según proceda, sobre:

- estructura;
- semántica;
- geometría;
- visual;
- navegación;
- interacción;
- transiciones;
- selectores;
- comportamiento observable.

El runtime TWIN gobernado es el entorno ordinario donde se ejecutan estas pruebas locales.

---

## XII. RELACIÓN CON TWIN DISCOVERY

`TWIN DISCOVERY` permanece como perfil persistente gobernado destinado a descubrimiento, captura y exploración segura.

La presente resolución distingue:

- **Discovery:** adquisición/aprendizaje del REAL.
- **Runtime TWIN:** ejecución local/preproducción de la réplica materializada.

Pueden compartir infraestructura SeleniumBase/QCC, pero representan responsabilidades distintas.

La existencia de un perfil Discovery no implica que toda ejecución TWIN deba realizarse necesariamente en el mismo proceso o perfil.

---

## XIII. OBSERVABILIDAD Y EVIDENCIA

El runtime deberá facilitar, progresivamente:

- logs;
- estado de sesión;
- navegador asociado;
- URL/origin local;
- revisión activa;
- eventos de navegación;
- screenshots diagnósticos cuando proceda;
- errores;
- resultados de tests;
- trazabilidad de promoción.

La evidencia debe permitir responder:

> qué TWIN se ejecutó, en qué revisión, en qué runtime y con qué resultado.

---

## XIV. AUTOMATIZACIONES

Las automatizaciones que posteriormente operarán sobre REAL deberán poder validarse primero, cuando exista cobertura suficiente, contra el TWIN.

El objetivo es reducir:

- prueba y error sobre sede real;
- riesgo administrativo;
- dependencia de disponibilidad externa;
- regresiones por cambios de interfaz;
- intervención manual de comprobación;

sin sacrificar la reproducción correcta de estados, validaciones y transiciones relevantes.

El TWIN no garantiza por sí solo que REAL no haya cambiado después de la última validación.

La promoción y ejecución REAL seguirán sujetas a contratos, guardas, recognizers, Site Architecture y políticas vigentes.

---

## XV. TECNOLOGÍA Y ACOPLAMIENTO

La decisión normativa es:

- runtime gobernado;
- SeleniumBase/CDP como infraestructura principal;
- aislamiento;
- ownership;
- preproducción;
- trazabilidad.

No se fija como norma permanente:

- puerto concreto;
- PID concreto;
- estructura exacta de carpetas;
- mecanismo IPC concreto;
- nombre de clase Python;
- interfaz gráfica concreta;
- implementación interna concreta del Runtime Manager.

Estas decisiones podrán evolucionar sin alterar `TWIN-006` mientras respeten su contrato.

---

## XVI. DECISIONES CANÓNICAS RESULTANTES

Tras la aprobación:

- `TWIN-003` → **VIGENTE**
- `TWIN-004` → **VIGENTE**
- `TWIN-005` → **VIGENTE**
- `TWIN-006` → **VIGENTE**

No se modifica el estado de:

- `SITE-001`
- `SITE-002`
- `SITE-003`
- `WEB-001`
- `WEB-002`
- `WEB-003`
- `WEB-004`
- `QCC-001`
- `QCC-002`
- `QCC-003`

La presente resolución no autoriza QCC V2 ni augmentación activa del DOM.

---

## XVII. PRINCIPIO FINAL

```text
REAL
→ OBSERVAR
→ MODELAR
→ MATERIALIZAR
→ TWIN LOCAL
→ SELENIUMBASE GOBERNADO
→ PROBAR
→ VALIDAR
→ PROMOVER
→ REAL
```

El navegador personal sirve para trabajo humano y, cuando proceda, observación autorizada.

El navegador TWIN sirve para preproducción gobernada.

El aislamiento protege sesiones, ownership y efectos; **no debe destruir la información funcional necesaria para que el TWIN se comporte como el REAL**.

No deben confundirse.

---

**ESTADO FINAL:** APROBADA POR DIRECCIÓN
