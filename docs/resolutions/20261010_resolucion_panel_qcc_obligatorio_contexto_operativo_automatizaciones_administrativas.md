# RESOLUCIÓN 20261010 — PANEL QCC OBLIGATORIO DE CONTEXTO OPERATIVO EN AUTOMATIZACIONES ADMINISTRATIVAS

**Proyecto:** Quesada Abogados CRM
**Ámbito:** QCC · Automatizaciones · Presentaciones administrativas · Expedientes · Documentación
**Estado:** APROBADA POR DIRECCIÓN
**Fecha:** 10 de octubre de 2026
**Carácter:** NORMATIVO

---

# I. OBJETO

Se establece como obligatorio que toda automatización administrativa lanzada desde el CRM y ejecutada mediante QCC disponga de un **Panel QCC contextual** que acompañe al usuario durante la ejecución.

El Panel QCC constituirá la superficie operativa donde se mostrará la información necesaria para identificar inequívocamente:

- para qué cliente se está trabajando;
- qué expediente se está presentando;
- qué subexpediente concreto está siendo ejecutado;
- qué documentación ha sido preparada para dicha presentación.

El objetivo es que el usuario pueda supervisar la automatización sin tener que abandonar la sede electrónica ni buscar manualmente la información dentro del CRM.

---

# II. PRINCIPIO GENERAL

Toda automatización administrativa lanzada desde el CRM deberá ejecutarse bajo el siguiente modelo:

```text
CRM
 ↓
EXPEDIENTE / SUBEXPEDIENTE
 ↓
QCC
 ├── CONTEXTO DEL CLIENTE
 ├── CONTEXTO DEL EXPEDIENTE
 ├── CONTEXTO DEL SUBEXPEDIENTE
 └── DOCUMENTACIÓN TARGET
 ↓
SEDE ELECTRÓNICA
```

El navegador ejecutará la automatización.

QCC aportará permanentemente el contexto operativo necesario para que el usuario conozca **qué está presentando y con qué documentación**.

---

# III. IDENTIFICACIÓN OBLIGATORIA DEL CLIENTE

Cuando se lance una automatización, el Panel QCC deberá mostrar obligatoriamente el **nombre del cliente** asociado a la presentación.

Ejemplo:

```text
CLIENTE
Nguyen Van A
```

El cliente mostrado deberá proceder de la fuente canónica correspondiente del CRM.

No deberá inferirse a partir del contenido visible en la sede electrónica cuando exista una relación explícita desde CRM.

---

# IV. IDENTIFICACIÓN OBLIGATORIA DEL EXPEDIENTE

El Panel QCC deberá mostrar el **expediente principal** desde el que se ha lanzado la automatización.

Deberá mostrarse información suficiente para identificarlo inequívocamente.

Ejemplo conceptual:

```text
EXPEDIENTE
EXTRANJERÍA · RENOVACIÓN
EXP-2026-00451
```

La denominación visual concreta podrá evolucionar, pero deberá mantenerse siempre la identificación del expediente.

---

# V. IDENTIFICACIÓN OBLIGATORIA DEL SUBEXPEDIENTE

Cuando la automatización corresponda a un subexpediente, procedimiento derivado, presentación específica o unidad operativa inferior al expediente principal, el Panel QCC deberá mostrar también el **subexpediente**.

Ejemplo:

```text
EXPEDIENTE
Residencia

SUBEXPEDIENTE
EX01 · Renovación Titular
```

El subexpediente será especialmente importante cuando un mismo expediente pueda generar varias actuaciones administrativas.

Modelo:

```text
CLIENTE
  ↓
EXPEDIENTE
  ↓
SUBEXPEDIENTE
  ↓
AUTOMATIZACIÓN
```

La automatización deberá conocer el subexpediente desde el que ha sido lanzada.

---

# VI. DOCUMENTACIÓN TARGET DE PRESENTACIÓN

El Panel QCC deberá mostrar obligatoriamente la documentación existente en la **carpeta Target de Presentación** correspondiente al subexpediente ejecutado.

Conceptualmente:

```text
TARGET_PRESENTATION_FOLDER
        ↓
DOCUMENTOS PREPARADOS
        ↓
PANEL QCC
```

La carpeta Target de Presentación constituye la selección documental preparada para la actuación administrativa concreta.

El Panel no deberá mostrar indistintamente toda la documentación disponible del cliente o expediente.

Deberá mostrar la documentación correspondiente al **target de esa presentación**.

---

# VII. LISTADO DOCUMENTAL OBLIGATORIO

Los documentos disponibles en la carpeta Target deberán mostrarse mediante una lista operativa.

Ejemplo:

```text
DOCUMENTACIÓN PARA PRESENTAR

✓ Pasaporte.pdf
  [Copiar ruta]

✓ Certificado_empadronamiento.pdf
  [Copiar ruta]

✓ Antecedentes_penales.pdf
  [Copiar ruta]

✓ EX01_firmado.pdf
  [Copiar ruta]
```

Cada elemento deberá permitir identificar claramente:

- nombre del archivo;
- existencia/disponibilidad;
- ubicación correspondiente;
- acción para copiar su ruta.

La interfaz podrá incorporar posteriormente más metadatos, pero estos elementos constituyen el mínimo obligatorio.

---

# VIII. BOTÓN OBLIGATORIO «COPIAR RUTA»

Cada documento de la lista deberá disponer de una acción:

```text
[COPIAR RUTA]
```

Su función será copiar al portapapeles la ruta física o lógica válida para acceder al documento.

Ejemplo:

```text
Pasaporte.pdf
[COPIAR RUTA]
```

Al ejecutarse:

```text
clipboard =
<ruta del documento>
```

Esto permitirá que el usuario pueda utilizar inmediatamente dicha ruta durante la interacción manual con la sede electrónica.

La ruta deberá proceder de la autoridad documental correspondiente y no ser reconstruida artificialmente por el frontend.

---

# IX. RUTA DE LA CARPETA TARGET

Además de las rutas individuales de los archivos, el Panel QCC podrá disponer de una acción de nivel superior:

```text
CARPETA DE PRESENTACIÓN
[Copiar ruta de carpeta]
```

Esta capacidad se considera recomendable para facilitar operaciones manuales sobre el conjunto documental.

No sustituye a los botones individuales de cada documento.

---

# X. NO AUTOMATIZACIÓN DE LA SUBIDA DOCUMENTAL EN ESTA FASE

Se establece expresamente que, **por el momento, la subida de documentación a las sedes electrónicas NO será automatizada**.

El sistema podrá:

- identificar documentos;
- mostrar documentos;
- validar su existencia;
- ordenar su presentación;
- mostrar su estado;
- proporcionar sus rutas;
- copiar rutas al portapapeles;
- asistir al usuario mediante QCC.

Pero la selección y carga efectiva de archivos en la sede continuará siendo realizada manualmente por el usuario.

Modelo vigente:

```text
QCC
 ↓
MUESTRA DOCUMENTO
 ↓
COPIAR RUTA
 ↓
USUARIO
 ↓
SELECCIÓN MANUAL DEL ARCHIVO
 ↓
SEDE ELECTRÓNICA
```

---

# XI. HUMAN-IN-THE-LOOP DOCUMENTAL

La aportación documental queda, en esta fase, bajo supervisión humana explícita.

QCC deberá reducir el trabajo manual necesario, pero no sustituir todavía la decisión ni la acción física de seleccionar los archivos.

Principio:

```text
QCC PREPARA Y CONTEXTUALIZA
USUARIO APORTA
```

Esto permite mantener control humano mientras se estabilizan:

- contratos documentales;
- Target Presentation Folder;
- clasificación documental;
- requisitos por procedimiento;
- fidelidad de los Twins;
- automatizaciones de sede.

---

# XII. ARQUITECTURA DEL PANEL

El Panel QCC deberá actuar como proyección de información del CRM.

No deberá convertirse en una nueva fuente de verdad.

Modelo:

```text
CRM
│
├── Cliente
├── Expediente
├── Subexpediente
└── Target Presentation Folder
        ↓
QCC PRESENTATION CONTEXT
        ↓
PANEL QCC
```

QCC consume y presenta contexto.

No crea entidades paralelas ni duplica información de negocio.

---

# XIII. CONTRATO DE CONTEXTO DE PRESENTACIÓN

Toda automatización administrativa deberá disponer progresivamente de un contrato equivalente a:

```text
QccPresentationContext
│
├── client
│   ├── client_id
│   └── display_name
│
├── expediente
│   ├── expediente_id
│   └── display_name
│
├── subexpediente
│   ├── subexpediente_id
│   ├── procedure_code
│   └── display_name
│
└── target_documents[]
    ├── document_id
    ├── filename
    ├── path
    └── availability
```

La denominación técnica exacta podrá evolucionar durante la implementación.

El contrato funcional definido por esta resolución deberá preservarse.

---

# XIV. APERTURA DE UNA AUTOMATIZACIÓN

El lanzamiento de una automatización deberá seguir conceptualmente:

```text
CRM
 ↓
seleccionar expediente
 ↓
seleccionar subexpediente
 ↓
lanzar automatización
 ↓
crear Presentation Context
 ↓
abrir/reutilizar Runtime SeleniumBase
 ↓
abrir Panel QCC
 ↓
ejecutar sede
```

Por tanto, una automatización no deberá arrancar como una sesión de navegador sin contexto.

---

# XV. CONTEXTO MÍNIMO OBLIGATORIO

Se establece como contrato mínimo obligatorio:

```text
CLIENTE
EXPEDIENTE
SUBEXPEDIENTE
DOCUMENTACIÓN TARGET
```

Si una automatización requiere estos elementos y alguno no puede resolverse, deberá evitarse mostrar silenciosamente información incorrecta.

El sistema deberá distinguir entre:

- información disponible;
- información no configurada;
- documentación inexistente;
- errores de resolución.

---

# XVI. RELACIÓN CON EL MODELO INTEGRAL DE AUTOMATIZACIONES

La presente resolución complementa el modelo aprobado de automatizaciones administrativas:

```text
PROCEDIMIENTO
 ↓
CONTRATO CANÓNICO
 ↓
1 · FORMULARIO / MODELO OFICIAL
2 · FORMULARIO / DATOS CRM
3 · AUTOMATIZACIÓN DE SEDE
```

QCC añade la capa operativa contextual:

```text
PROCEDIMIENTO
      ↓
CRM
      ↓
QCC PRESENTATION CONTEXT
      ↓
┌──────────────────────────┐
│ CLIENTE                  │
│ EXPEDIENTE               │
│ SUBEXPEDIENTE            │
│ DOCUMENTACIÓN TARGET     │
└──────────────────────────┘
      ↓
AUTOMATIZACIÓN
```

---

# XVII. RELACIÓN CON AUTO TWIN

El mismo contrato contextual deberá poder acompañar posteriormente la ejecución en:

```text
REAL
```

y:

```text
TWIN
```

sin alterar la fuente de verdad del CRM.

El Twin podrá utilizar documentación ficticia o segura para sus pruebas cuando corresponda, respetando las reglas de aislamiento aprobadas.

---

# XVIII. EVOLUCIÓN FUTURA DE LA APORTACIÓN DOCUMENTAL

La presente resolución **no prohíbe permanentemente** automatizar la subida documental.

Establece únicamente que dicha capacidad queda fuera del alcance actual.

Una futura automatización documental requerirá resolución, diseño y validación específicos sobre:

- selección correcta de archivos;
- orden documental;
- requisitos de cada sede;
- límites de tamaño;
- formatos permitidos;
- clasificación;
- correspondencia requisito ↔ documento;
- errores de carga;
- confirmación de aportación;
- trazabilidad;
- controles HUMAN_ONLY cuando procedan.

Hasta entonces:

> **LA APORTACIÓN EFECTIVA DE DOCUMENTOS SERÁ MANUAL.**

---

# XIX. CRITERIOS DE ACEPTACIÓN DEL PANEL QCC

Una automatización no podrá considerarse plenamente integrada con QCC si durante su ejecución el Panel no permite visualizar, como mínimo:

```text
1. CLIENTE
2. EXPEDIENTE
3. SUBEXPEDIENTE
4. DOCUMENTACIÓN TARGET
5. COPIAR RUTA DE CADA DOCUMENTO
```

La funcionalidad deberá ser usable sin abandonar el contexto de la sede electrónica.

---

# XX. REGLA DE CIERRE

A partir de la aprobación de esta resolución:

> **TODA AUTOMATIZACIÓN ADMINISTRATIVA LANZADA DESDE EL CRM DEBERÁ ABRIRSE CON UN CONTEXTO QCC QUE IDENTIFIQUE CLIENTE, EXPEDIENTE, SUBEXPEDIENTE Y DOCUMENTACIÓN TARGET DE PRESENTACIÓN.**

Asimismo:

> **CADA DOCUMENTO TARGET DEBERÁ DISPONER DE UNA ACCIÓN PARA COPIAR SU RUTA.**

Y, durante la fase actual:

> **QCC ASISTIRÁ EN LA APORTACIÓN DOCUMENTAL, PERO NO SUBIRÁ AUTOMÁTICAMENTE LOS ARCHIVOS A LA SEDE ELECTRÓNICA.**

---

# XXI. RESOLUCIÓN FINAL

Se aprueba como arquitectura operativa obligatoria:

```text
CRM
 ↓
CLIENTE
 ↓
EXPEDIENTE
 ↓
SUBEXPEDIENTE
 ↓
TARGET PRESENTATION FOLDER
 ↓
QCC PANEL
 ├── nombre cliente
 ├── expediente
 ├── subexpediente
 └── documentos
       └── [COPIAR RUTA]
 ↓
SELENIUMBASE / QCC
 ↓
SEDE ELECTRÓNICA
 ↓
APORTACIÓN DOCUMENTAL MANUAL
```

Esta regla será aplicable a:

- Mercurio;
- Red SARA;
- DEHú;
- Nacionalidad;
- UGE;
- consulados;
- registros electrónicos;
- cualquier futura automatización administrativa integrada con QCC.

**ESTADO DE LA RESOLUCIÓN: APROBADA POR DIRECCIÓN.**
