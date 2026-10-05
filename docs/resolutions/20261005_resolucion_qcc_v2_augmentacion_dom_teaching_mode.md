# RESOLUCIÓN DE EVOLUCIÓN QCC V2, AUGMENTACIÓN CONTROLADA DEL DOM Y TEACHING MODE

**Fecha:** 05/10/2026
**Proyecto:** Quesada Abogados
**Estado:** APROBADA POR DIRECCIÓN
**Ámbito:** Quesada Chrome Companion (QCC), Chrome Extension, DOM augmentation, overlays, Teaching Mode, QCC Bridge, Site Architecture y automatización gobernada.

---

## I. OBJETO

La presente resolución formaliza la evolución de Quesada Chrome Companion desde su contrato V1 de observación contextual hacia un modelo V2 capaz de **aumentar visual y contextualmente páginas web** sin convertirse en un controlador alternativo del navegador ni alterar libremente la lógica nativa de los sitios.

Se formalizan dos capacidades:

- `QCC-004 · Augmentación DOM Controlada, Reversible y Contextual`
- `QCC-005 · Teaching Mode Gobernado para Adquisición de Contratos de Interacción`

La resolución desarrolla `QCC-001`, `QCC-002` y `QCC-003`, manteniendo la separación entre:

- contexto del ERP;
- presentación QCC;
- DOM nativo de la web;
- runtime de automatización;
- Site Architecture;
- decisiones humanas.

---

## II. RELACIÓN CON QCC-003

`QCC-003` permanece **VIGENTE** en su alcance original:

> QCC V1 no modifica directamente el DOM.

La propia decisión histórica establecía que una capacidad futura de modificación DOM requería diseño, justificación y aprobación expresa.

La presente resolución constituye esa aprobación para **QCC V2**, exclusivamente dentro del contrato definido aquí.

Por tanto:

```text
QCC V1
→ OBSERVACIÓN / SIDE PANEL
→ NO AUGMENTACIÓN DOM

QCC V2
→ OBSERVACIÓN
→ AUGMENTACIÓN CONTROLADA
→ TEACHING MODE GOBERNADO
```

No se autoriza modificación DOM arbitraria.

---

## III. QCC-004 · AUGMENTACIÓN DOM CONTROLADA, REVERSIBLE Y CONTEXTUAL

Se aprueba:

`QCC-004 · Augmentación DOM Controlada, Reversible y Contextual`

QCC V2 podrá incorporar información, controles QCC, overlays, badges, indicadores, tooltips, resaltados y capas contextuales sobre páginas autorizadas.

Ejemplos válidos:

- badge `LEAD`;
- estado `CLIENTE`;
- número de TASK pendientes;
- aviso de documento pendiente;
- estado de expediente;
- alerta de requerimiento;
- acceso contextual a acciones del CRM;
- ayudas visuales de navegación;
- resaltado de campos o controles;
- etiquetas internas sobre conversaciones de WhatsApp;
- información contextual sobre sedes electrónicas.

La augmentación debe mejorar la capacidad del usuario sin convertir la web externa en fuente canónica del ERP.

---

## IV. PRINCIPIO DE PROPIEDAD DEL DOM

Se distinguen dos espacios:

### A. DOM NATIVO

Pertenece a la aplicación o sede externa.

QCC no debe modificar libremente:

- valores de formularios;
- atributos funcionales;
- listeners nativos;
- scripts;
- validaciones;
- identificadores;
- estados internos;
- controles de firma;
- CAPTCHA;
- acciones irreversibles.

### B. DOM QCC

QCC podrá crear nodos, capas y estilos propios identificables y aislados.

La regla será:

```text
DOM NATIVO
→ OBSERVAR / ANCLAR

DOM QCC
→ CREAR / ACTUALIZAR / RETIRAR
```

La augmentación ordinaria debe escribir sobre elementos propiedad de QCC, no reconfigurar silenciosamente elementos nativos.

---

## V. OVERLAY-FIRST

Cuando sea técnicamente razonable se priorizará:

```text
OVERLAY / CAPA QCC
→ ANCLADA POR GEOMETRÍA / SITE ARCHITECTURE
```

frente a insertar contenido que cambie el layout nativo.

Ventajas:

- menor riesgo de interferencia;
- menor layout shift;
- retirada limpia;
- aislamiento visual;
- menor dependencia de internals del sitio.

Podrán utilizarse:

- Shadow DOM;
- contenedores QCC namespaced;
- atributos `data-qcc-*`;
- roots dedicados;
- estilos encapsulados;
- Geometry JIT.

La implementación concreta podrá evolucionar siempre que preserve el contrato.

---

## VI. AUGMENTACIÓN INLINE EXCEPCIONAL

Podrá existir augmentación inline cuando:

- aporte una ventaja funcional clara;
- el overlay no sea suficiente;
- exista adapter/site contract específico;
- no se altere la lógica nativa;
- exista test de regresión;
- pueda retirarse completamente;
- sea idempotente.

La augmentación inline no podrá asumirse como estrategia universal.

---

## VII. REVERSIBILIDAD

Toda augmentación QCC deberá ser reversible.

El sistema debe poder:

```text
INJECT
→ UPDATE
→ REMOVE
```

sin dejar efectos permanentes sobre la aplicación externa.

Al:

- cerrar QCC;
- deshabilitar la capacidad;
- cambiar de página;
- cambiar de sesión;
- perder contexto;
- detectar contrato incompatible;

los elementos QCC deberán poder retirarse o reconstruirse de forma segura.

---

## VIII. IDEMPOTENCIA

La misma capa contextual no podrá duplicarse indefinidamente por:

- MutationObserver;
- navegación SPA;
- refresh;
- reconexión Bridge;
- cambio de tab;
- repetición de eventos.

La operación:

```text
APPLY AUGMENTATION
```

deberá converger a un único estado visual esperado.

---

## IX. FAIL-OPEN

Un fallo de QCC no debe inutilizar la web externa.

Si:

- QCC Bridge cae;
- el backend no responde;
- el contexto no puede resolverse;
- falla un recognizer;
- existe una excepción de augmentación;

la página nativa debe seguir siendo utilizable.

La prioridad será:

```text
SITIO NATIVO FUNCIONAL
>
CAPA QCC
```

---

## X. FUENTE DE VERDAD

La información mostrada por QCC procede del backend autorizado.

QCC no convierte el DOM externo en fuente de verdad de:

- cliente;
- lead;
- expediente;
- TASK;
- cobro;
- documento;
- criterio jurídico;
- estado interno del CRM.

El DOM puede aportar señales y contexto observado.

La autoridad permanece en los servicios y dominios del ERP.

---

## XI. ACCIONES DESDE LA AUGMENTACIÓN

Un control QCC insertado en una web podrá generar una intención de usuario.

Ejemplo:

```text
[MARCAR COMO LEAD]
```

El flujo correcto será:

```text
USUARIO
→ CONTROL QCC
→ QCC
→ QCC BRIDGE
→ APPLICATION SERVICE
→ DOMINIO / PERSISTENCIA
```

No:

```text
CONTROL QCC
→ SQL DIRECTO
```

ni:

```text
CONTROL QCC
→ MUTACIÓN ARBITRARIA DEL SITIO
```

---

## XII. AUTOMATIZACIÓN Y AUGMENTACIÓN SON CAPACIDADES DISTINTAS

QCC V2 podrá contextualizar y asistir una acción.

La ejecución automatizada continúa gobernada por:

```text
Application / Runtime
→ Connector
→ Browser Runtime
→ SeleniumBase / CDP
```

QCC no se convierte en un segundo motor de automatización.

Si una acción sobre el sitio debe:

- rellenar campos;
- navegar;
- pulsar controles nativos;
- ejecutar una transición;
- leer estado avanzado;
- recuperar errores;

deberá utilizarse la infraestructura browser gobernada cuando proceda.

---

## XIII. POLÍTICAS DE INTERVENCIÓN POR SITIO

Cada Site Contract podrá declarar una política QCC.

Como mínimo podrán existir:

### `OBSERVE_ONLY`

QCC observa y muestra contexto sin inyectar elementos sobre la página.

### `AUGMENT_PRESENTATION`

QCC puede añadir capas visuales/contextuales propias.

### `ASSIST_INTERACTION`

QCC puede incorporar controles propios que soliciten acciones al backend/runtime.

### `RUNTIME_ONLY`

La interacción sobre la página queda reservada al runtime gobernado.

La política podrá definirse por:

- provider;
- site;
- procedure;
- page_type;
- state;
- interaction.

No toda web debe recibir el mismo nivel de intervención.

---

## XIV. HUMAN_ONLY

`SITE-003` permanece plenamente vigente.

Una capa QCC no podrá convertir en automatizable una operación clasificada como:

`HUMAN_ONLY`

Incluye, cuando corresponda:

- CAPTCHA;
- firma;
- presentación definitiva;
- confirmación jurídica;
- autorización irreversible.

QCC podrá:

- avisar;
- contextualizar;
- explicar;
- resaltar;

pero no eludir la política.

---

## XV. DATOS SENSIBLES

QCC deberá minimizar la información sensible mostrada o persistida en la capa de augmentación.

La augmentación no deberá:

- insertar secretos;
- exponer tokens;
- mostrar cookies;
- persistir contraseñas;
- capturar valores de autenticación innecesarios;
- convertir datos sensibles en atributos DOM accesibles sin necesidad.

La información contextual deberá limitarse a la necesaria para la función.

---

## XVI. WHATSAPP COMO EJEMPLO DE AUGMENTACIÓN

QCC podrá añadir sobre WhatsApp Web información interna del CRM, por ejemplo:

```text
CHAT
├── CLIENTE
├── LEAD CUALIFICADO
├── 1 TASK PENDIENTE
├── EXPEDIENTE EN TRÁMITE
└── DOCUMENTO PENDIENTE
```

Esos badges pertenecen a QCC.

No modifican el significado nativo del chat ni la base de datos de WhatsApp.

Una acción como:

```text
CREAR LEAD
```

deberá ejecutar una operación del backend del ERP a través de QCC Bridge.

---

## XVII. SEDES ELECTRÓNICAS COMO EJEMPLO DE AUGMENTACIÓN

En sedes electrónicas QCC podrá mostrar:

- contexto del expediente;
- estado del trámite;
- documentación pendiente;
- instrucciones;
- diferencias REAL ↔ TWIN;
- alertas;
- ayudas de navegación;
- acciones disponibles;
- políticas HUMAN_ONLY.

La capa QCC no deberá ocultar ni modificar silenciosamente:

- botones nativos;
- textos jurídicamente relevantes;
- valores de campos;
- mensajes de error;
- avisos oficiales.

---

## XVIII. QCC-005 · TEACHING MODE GOBERNADO

Se aprueba:

`QCC-005 · Teaching Mode Gobernado para Adquisición de Contratos de Interacción`

Teaching Mode permite que un usuario enseñe al sistema:

- qué elemento es relevante;
- qué función cumple;
- qué acción representa;
- qué estado previo existe;
- qué resultado se espera;
- qué transición produce;
- qué relación mantiene con el expediente o procedimiento.

El objetivo no es grabar macros opacas.

El objetivo es generar **evidencia estructurada para Site Architecture y automatización gobernada**.

---

## XIX. CAPTURA DE TEACHING MODE

Teaching Mode podrá capturar:

- selector candidato;
- atributos accesibles;
- role;
- texto relevante;
- geometría;
- viewport;
- page signature;
- site/provider;
- procedure/flow;
- page_type;
- estado previo;
- acción enseñada;
- estado esperado;
- transición candidata;
- screenshots diagnósticos cuando proceda;
- evidencia DOM;
- observables de red permitidos;
- metadata de sesión.

No debe depender únicamente de coordenadas.

---

## XX. TEACHING MODE NO PROMUEVE AUTOMÁTICAMENTE

Una enseñanza genera:

```text
CANDIDATE KNOWLEDGE / CANDIDATE CONTRACT
```

No:

```text
PRODUCTION RULE
```

La promoción deberá pasar por:

- normalización;
- validación;
- comparación;
- tests;
- políticas;
- revisión cuando proceda;
- integración en Site Architecture.

---

## XXI. TEACHING MODE Y HUMAN_ONLY

Teaching Mode puede observar que una acción existe.

No puede usar esa observación para eliminar una política `HUMAN_ONLY`.

Ejemplo:

```text
USUARIO ENSEÑA BOTÓN "FIRMAR"
```

puede producir:

```text
action = FIRMA
policy = HUMAN_ONLY
```

pero no:

```text
action = FIRMA
policy = AUTO
```

por decisión autónoma del sistema.

---

## XXII. PRIVACIDAD EN TEACHING MODE

Teaching Mode deberá evitar persistir valores sensibles innecesarios.

Por defecto no deben incorporarse a contratos versionados:

- contraseñas;
- tokens;
- cookies;
- códigos MFA;
- secretos;
- certificados privados;
- valores personales que no sean necesarios para reproducir el contrato.

Cuando un valor sea funcionalmente necesario, deberá aplicarse el mismo principio establecido para AUTO TWIN:

```text
CONSERVAR ESTRUCTURA / SEMÁNTICA / DEPENDENCIA NECESARIA
→ MINIMIZAR IDENTIDAD
→ NO ROMPER FIDELIDAD FUNCIONAL
```

---

## XXIII. ARQUITECTURA QCC V2

La arquitectura general queda:

```text
ERP / SERVICES / DOMAIN
        ↑ ↓
     QCC BRIDGE
        ↑ ↓
QCC CONTEXT ENGINE
        ↓
SITE RECOGNITION
        ↓
AUGMENTATION POLICY
        ↓
QCC PRESENTATION LAYER
        ↓
CHROME PAGE
```

Para automatización:

```text
QCC / USER INTENT
        ↓
QCC BRIDGE
        ↓
APPLICATION / RUNTIME
        ↓
SELENIUMBASE / CDP
        ↓
SITE
```

---

## XXIV. AISLAMIENTO DE ESTILOS Y NOMBRES

Los elementos QCC deberán evitar colisiones con estilos o identificadores nativos.

Se utilizarán mecanismos como:

- namespace;
- prefijos QCC;
- Shadow DOM cuando proceda;
- CSS encapsulado;
- roots dedicados;
- atributos propios.

QCC no debe depender de clases CSS genéricas capaces de contaminar la página.

---

## XXV. MUTATION OBSERVER Y SPA

QCC V2 podrá observar mutaciones y cambios de ruta para mantener la capa contextual.

Deberá controlar:

- duplicados;
- stale anchors;
- elementos desmontados;
- re-render;
- navegación SPA;
- virtualización de listas;
- cambios de página sin reload.

La observación continua no deberá provocar loops de mutación QCC ↔ sitio.

---

## XXVI. PERFORMANCE

La augmentación no deberá degradar materialmente:

- navegación;
- scroll;
- input;
- carga de páginas;
- uso normal de la aplicación.

Se deberán evitar:

- MutationObservers globales sin filtro;
- rescans completos permanentes;
- timers agresivos;
- inyecciones masivas innecesarias;
- cálculos geométricos continuos sin demanda.

Se priorizarán:

- observación incremental;
- Geometry JIT;
- caché invalidable;
- actualización por eventos;
- scopes acotados.

---

## XXVII. OBSERVABILIDAD

QCC V2 deberá poder registrar, cuando proceda:

- site/page reconocida;
- política aplicada;
- augmentations activas;
- anchor encontrado/no encontrado;
- razón de no augmentar;
- versión de contrato;
- eventos de Teaching Mode;
- errores;
- cleanup realizado.

La observabilidad no debe convertir el log en almacén de datos sensibles.

---

## XXVIII. TESTS

Antes de considerar cerrada una capacidad de augmentación deberán existir tests razonables sobre:

- idempotencia;
- cleanup;
- navegación SPA;
- reconexión Bridge;
- Bridge offline;
- pérdida de anchor;
- re-render;
- Shadow DOM/estilos cuando proceda;
- no alteración de valores nativos;
- no eliminación de controles nativos;
- política por sitio;
- HUMAN_ONLY;
- Teaching Mode;
- sanitización;
- regresión.

En sitios críticos se realizarán pruebas REAL ↔ TWIN cuando exista cobertura suficiente.

---

## XXIX. FAIL-SAFE / KILL SWITCH

QCC V2 deberá poder desactivar:

- augmentación global;
- augmentación por sitio;
- una feature concreta;
- Teaching Mode;

sin impedir el uso nativo de la web.

El kill switch podrá ser utilizado ante:

- incompatibilidad;
- cambio de sitio;
- regresión;
- riesgo de seguridad;
- rendimiento inaceptable.

---

## XXX. NO SE AUTORIZA

La presente resolución no autoriza:

- reescribir páginas completas;
- ocultar avisos oficiales;
- cambiar textos jurídicos nativos;
- alterar valores de formularios mediante la capa visual;
- interceptar firmas;
- eludir CAPTCHA;
- inyectar secretos;
- manipular el DOM sin ownership QCC;
- usar QCC como sustituto de SeleniumBase;
- usar Teaching Mode para promover reglas sin validación.

---

## XXXI. EFECTO SOBRE DECISIONES CANÓNICAS

Tras la aprobación:

- `QCC-001` → **VIGENTE**
- `QCC-002` → **VIGENTE**
- `QCC-003` → **VIGENTE** en su alcance QCC V1
- `QCC-004` → **VIGENTE**
- `QCC-005` → **VIGENTE**

No se modifica:

- `WEB-001`
- `WEB-002`
- `WEB-003`
- `WEB-004`
- `SITE-001`
- `SITE-002`
- `SITE-003`
- `TWIN-003`
- `TWIN-006`

---

## XXXII. PRINCIPIO FINAL

```text
QCC NO REEMPLAZA LA WEB
QCC LA AUMENTA

QCC NO REEMPLAZA EL ERP
QCC LO ACERCA AL CONTEXTO

QCC NO REEMPLAZA EL RUNTIME
QCC SOLICITA / CONTEXTUALIZA

TEACHING MODE NO CREA VERDAD
CREA EVIDENCIA CANDIDATA
```

Objetivo:

> **CONVERTIR LAS WEBS UTILIZADAS POR QUESADA ABOGADOS EN SUPERFICIES CONTEXTUALES MÁS ÚTILES, SIN PERDER CONTROL, TRAZABILIDAD, REVERSIBILIDAD NI FIDELIDAD FUNCIONAL.**

---

**ESTADO FINAL:** APROBADA POR DIRECCIÓN
