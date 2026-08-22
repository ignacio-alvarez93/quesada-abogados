RESOLUCIÓN SOBRE QCC SITE ARCHITECTURE — ARQUITECTURA DOM, GEOMETRÍA E INTERACCIÓN DE SEDES ELECTRÓNICAS

Proyecto: Quesada Abogados ERP
Fecha: 22 de agosto de 2026
Estado de referencia: rama develop, integración 70ef6fb
Naturaleza: Resolución técnica, arquitectónica y funcional vinculante
Ámbito: Quesada Chrome Companion, automatización de navegador, SeleniumBase/CDP, automatización GUI, Sistema LABS, Mercurio, ICP Plus, DEHú, UGE, Policía Nacional, Guardia Civil y cualquier otra sede electrónica o portal automatizado por Quesada Abogados ERP
Nombre oficial del sistema: QCC Site Architecture
Denominación funcional: Arquitectura DOM Extendida

I. OBJETO

La presente resolución aprueba la evolución de la actual infraestructura de inspección DOM de Quesada Chrome Companion hacia un sistema completo denominado:

QCC Site Architecture

Su finalidad será capturar, interpretar, normalizar y versionar la arquitectura observable de una aplicación web para convertirla en un contrato técnico reproducible de la sede.

La Arquitectura DOM dejará de ser únicamente una herramienta diagnóstica destinada a obtener HTML y elementos.

Pasará a responder a una pregunta mucho más amplia:

¿Cómo está construida esta pantalla, qué elementos contiene, qué significan, dónde están, cómo se puede interactuar con ellos y qué transformación observable produce cada interacción?

II. ANTECEDENTE TÉCNICO

Actualmente existe:

backend/automation/dom_inspector.py

como infraestructura genérica y agnóstica de consumidor.

Su contrato actual permite capturar:

documento principal
iframes accesibles
Shadow DOM abierto
inventario estructural
metadatos
DOM vivo

La infraestructura existente se considera válida y deberá evolucionar incrementalmente.

No se realizará una reescritura innecesaria.

El principio será:

DOM Inspector actual
        ↓
ampliación contractual
        ↓
QCC Site Architecture
III. CAMBIO DE NATURALEZA

La arquitectura actual responde fundamentalmente:

¿Qué DOM existe?

La arquitectura objetivo deberá responder:

¿Qué página es?
¿Qué estado representa?
¿Qué elementos existen?
¿Qué función tiene cada elemento?
¿Cómo se identifica?
¿Dónde se encuentra?
¿Es visible?
¿Es interactuable?
¿Cómo debe accionarse?
¿Qué ocurre al accionarlo?
¿Qué transición produce?
¿Cómo sé que la transición terminó?

Por tanto:

DOM

será solamente una de las capas del sistema.

IV. ARQUITECTURA OBJETIVO

QCC Site Architecture deberá representar como mínimo las siguientes capas:

SITE ARCHITECTURE
│
├── PAGE IDENTITY
│
├── DOM STRUCTURE
│
├── SEMANTIC LAYER
│
├── SELECTOR LAYER
│
├── GEOMETRY LAYER
│
├── VISIBILITY LAYER
│
├── INTERACTION LAYER
│
├── STATE LAYER
│
├── NAVIGATION / TRANSITION LAYER
│
├── JAVASCRIPT CONTRACT
│
├── NETWORK OBSERVABLE CONTRACT
│
└── DIAGNOSTIC METADATA

No todas las sedes necesitarán explotar inmediatamente todas las capas.

El esquema deberá permitirlas.

V. PAGE IDENTITY

Toda captura deberá poder identificar la pantalla observada.

Entre otros datos podrá contener:

url
origin
pathname
query
title
document.readyState
timestamp
provider
site
procedure
flow
page_type
page_signature

Ejemplo:

provider = MERCURIO
flow = PRESENTACION
procedure = EX02
page_type = DOCUMENTATION

La identidad funcional no deberá depender exclusivamente de la URL.

Muchas sedes reutilizan URLs mientras modifican dinámicamente el contenido.

VI. DOM STRUCTURE

Se conservará y ampliará la captura del DOM vivo.

Deberán poder inventariarse:

document
forms
inputs
selects
options
buttons
links
tables
rows
cells
iframes
labels
textareas
checkboxes
radios
file inputs
hidden inputs
dialogs
menus
progress bars
tabs
custom controls
Shadow DOM

Cuando resulte relevante también deberá registrarse:

parent
children
siblings
ancestor path
form ownership
DOM depth
document/frame ownership

El objetivo no será almacenar datos indiscriminadamente, sino reconstruir estructura suficiente para comprender el contrato de la página.

VII. IFRAMES

Cada iframe accesible deberá tratarse como un documento identificado.

La arquitectura deberá registrar:

frame identity
src
name
id
parent frame
accessible / inaccessible
document structure
geometry

No deberá confundirse:

elemento del documento raíz

con:

elemento perteneciente a iframe

El selector de un elemento deberá conservar también su contexto de frame.

VIII. SHADOW DOM

Se mantendrá la capacidad de inspeccionar Shadow DOM abierto.

La arquitectura deberá poder representar:

shadow host
shadow root
elementos internos
ruta desde documento raíz

Un elemento dentro de Shadow DOM no deberá almacenarse como si perteneciera al árbol DOM ordinario.

IX. SEMANTIC LAYER

Esta será una de las ampliaciones más importantes.

Cada elemento relevante deberá poder tener una clasificación funcional.

Por ejemplo:

TEXT_INPUT
SELECT
CHECKBOX
RADIO
BUTTON
LINK
FILE_INPUT
UPLOAD_TRIGGER
SUBMIT
CONTINUE
BACK
CANCEL
SEARCH
DOCUMENT_TABLE
DOCUMENT_ROW
ERROR_MESSAGE
SUCCESS_MESSAGE
LOADING_INDICATOR

Además podrá incorporarse significado específico de proveedor cuando resulte útil:

MERCURIO_DOCUMENT_TYPE
MERCURIO_ATTACH_BUTTON
ICP_PROVINCE
ICP_OFFICE
ICP_PROCEDURE

La capa genérica deberá mantenerse separada de la semántica del proveedor.

X. TEXTO Y ACCESIBILIDAD

Para identificar semánticamente un elemento deberán capturarse cuando existan:

textContent
innerText
value
placeholder
title
aria-label
aria-labelledby
aria-describedby
role
name
alt
label asociado

Los atributos de accesibilidad tendrán especial importancia porque suelen proporcionar identificadores más estables que determinados selectores estructurales.

XI. SELECTOR LAYER

La Arquitectura DOM deberá generar y evaluar candidatos de localización.

Un elemento podrá tener varios selectores posibles:

id
name
CSS
aria
role
data-testid
label
text
DOM path
XPath cuando sea necesario

No existirá necesariamente un único selector absoluto.

El contrato podrá representar:

primary_selector
fallback_selectors
selector_confidence

Ejemplo conceptual:

primary:
#docAdjuntarAdjuntos

fallback:
select[name="docAdjuntarAdjuntos"]

semantic:
role=combobox + label="Tipo de documento"
XII. PRINCIPIO DE SELECTORES ROBUSTOS

La generación de selectores deberá priorizar estabilidad sobre brevedad.

Orden conceptual:

identidad semántica estable
↓
id estable
↓
name estable
↓
aria / role
↓
atributos específicos estables
↓
estructura
↓
posición

No se utilizarán como contrato principal selectores derivados únicamente de:

nth-child
posición accidental
clases dinámicas
hashes generados

cuando exista una identidad más estable.

XIII. GEOMETRY LAYER

Se aprueba la incorporación obligatoria de una capa geométrica.

Para cada elemento relevante deberá poder capturarse:

x
y
top
left
right
bottom
width
height
center_x
center_y

obtenidos mediante información equivalente a:

getBoundingClientRect()

La geometría será relativa inicialmente al viewport.

XIV. VIEWPORT

Toda captura geométrica deberá registrar también el contexto del viewport.

Entre otros:

window.innerWidth
window.innerHeight
document.documentElement.clientWidth
document.documentElement.clientHeight
scrollX
scrollY
devicePixelRatio

Sin este contexto, unas coordenadas no constituyen un contrato reproducible.

XV. GEOMETRÍA DE DOCUMENTO

Además de coordenadas de viewport, podrá calcularse la posición del elemento respecto del documento completo.

Conceptualmente:

document_x = rect.left + scrollX
document_y = rect.top + scrollY

Esto permitirá distinguir:

posición absoluta dentro de página

de:

posición actual visible en pantalla
XVI. GEOMETRÍA DE VENTANA CHROME

Cuando resulte técnicamente accesible deberán registrarse:

window.screenX
window.screenY
window.outerWidth
window.outerHeight
window.innerWidth
window.innerHeight
devicePixelRatio

Esta información permitirá conocer la relación:

DOM
↓
viewport
↓
ventana Chrome
↓
pantalla
XVII. SCREEN COORDINATE MODEL

Cuando una automatización requiera interacción GUI se deberá poder derivar una coordenada física de interacción.

Conceptualmente:

elemento DOM
↓
bounding rect
↓
viewport
↓
offset Chrome
↓
DPR / escala
↓
coordenada física

No deberá asumirse que:

DOM x/y
=
pantalla x/y
XVIII. PROHIBICIÓN DE COORDENADAS FIJAS

Queda establecido como principio:

Las coordenadas de pantalla no se considerarán identificadores permanentes de un elemento.

Queda desaconsejado:

click(827, 534)

como contrato estático.

Cuando sea necesario utilizar mouse o automatización de escritorio, el sistema deberá preferentemente:

localizar elemento en DOM
↓
obtener geometría actual
↓
recalcular coordenada
↓
validar
↓
hacer click
XIX. RECÁLCULO JUST-IN-TIME

Toda acción GUI basada en geometría deberá recalcular, inmediatamente antes de actuar:

posición
visibilidad
viewport
scroll
dimensiones

No deberá utilizar coordenadas obtenidas varios segundos antes si la página pudo cambiar.

Principio:

Locate → Validate → Recalculate → Act.

XX. VISIBILITY LAYER

La mera existencia de un elemento en DOM no significa que pueda utilizarse.

Para cada elemento relevante deberá poder conocerse:

display
visibility
opacity
hidden
disabled
aria-disabled
rect dimensions
inside viewport
covered / potentially covered
pointer-events

También deberá distinguirse:

EXISTS
VISIBLE
INTERACTABLE
XXI. INTERACTION LAYER

Cada elemento relevante podrá incorporar un contrato de interacción.

Ejemplos:

READ
TYPE
SELECT
CLICK_DOM
CLICK_CDP
CLICK_GUI
UPLOAD_FILE
SCROLL_INTO_VIEW
HOVER
KEYBOARD
HUMAN_ONLY

Un mismo elemento podrá permitir varias estrategias ordenadas.

Ejemplo:

preferred = DOM
fallback = GUI
XXII. ORDEN DE INTERACCIÓN

Se mantiene como criterio general:

DOM semántico
↓
SeleniumBase / CDP
↓
interacción navegador
↓
GUI mouse / keyboard

No obstante, la Arquitectura de Sitio deberá describir la capacidad disponible, no imponer una sola tecnología.

El LAB describe la sede.

El runtime decide cómo actuar.

Este principio es coherente con la arquitectura general de LABS ya aprobada.

XXIII. GUI FALLBACK GOBERNADO

La automatización mediante ratón o teclado quedará permitida cuando resulte necesaria o más robusta para un caso concreto.

Pero deberá existir, siempre que sea técnicamente posible:

element identity
+
geometry
+
state validation

antes de la acción.

Esto permitirá utilizar:

mouse
keyboard
PyAutoGUI
otras tecnologías GUI

sin reducir toda la automatización a coordenadas rígidas.

XXIV. HUMAN-ONLY

La arquitectura podrá clasificar acciones que deban quedar bajo control humano.

Ejemplos:

CAPTCHA
firma
presentación definitiva
confirmación jurídica
acción irreversible

La existencia de información DOM o geométrica no autorizará su automatización.

El contrato podrá declarar:

interaction_policy = HUMAN_ONLY
XXV. STATE LAYER

La Arquitectura DOM deberá poder representar el estado observable de los controles.

Ejemplos:

checked
selected
value
disabled
readonly
expanded
collapsed
active
required
valid
invalid
loading

En selects:

selected option
available options
option values
option labels

En tablas:

row count
column structure
row identity
XXVI. FORM CONTRACT

Los formularios deberán poder reconstruirse como contratos.

Ejemplo:

FORM
│
├── field NIE
│   ├── required
│   ├── maxlength
│   ├── selector
│   └── validation
│
├── field Nacionalidad
│   ├── select
│   └── options
│
└── Continuar

Esto permitirá comparar:

formulario real
VS
formulario LAB
XXVII. VALIDACIONES

Cuando sean observables deberán capturarse:

required
pattern
min
max
minlength
maxlength
accept
disabled conditions
validation messages
custom errors

También podrán registrarse reglas inferidas mediante experimentación controlada en LAB.

No deberán inventarse reglas no observadas.

XXVIII. JAVASCRIPT CONTRACT

QCC Site Architecture podrá registrar funciones, listeners o comportamientos JavaScript cuando sean relevantes para la interacción.

Ejemplos:

onclick
onchange
onsubmit
funciones globales invocadas
event listeners observables

No será necesario copiar indiscriminadamente todo el JavaScript de una sede.

Se capturará lo necesario para reproducir el comportamiento observable.

XXIX. EVENT CONTRACT

Cuando una acción produzca cambios observables deberá poder describirse:

acción
↓
evento
↓
mutación DOM
↓
estado resultante

Ejemplo Mercurio:

send_file
↓
FilesAdded
↓
fileDocumentoAdjuntos cambia
↓
archivo preparado

o:

ADJUNTAR
↓
POST uploadDocumento
↓
FileUploaded
↓
fila añadida a tabla

El laboratorio documental ya demuestra precisamente este tipo de contrato observable.

XXX. NAVIGATION / TRANSITION LAYER

La Arquitectura Site deberá poder representar transiciones entre pantallas.

Ejemplo:

PAGE A
   │
   ├── acción CONTINUAR
   ↓
PAGE B

Cada transición podrá incluir:

source_page
trigger
expected_url
expected_dom_signature
expected_elements
timeout
target_page

Esto será esencial para construir los LAB completos.

XXXI. PAGE SIGNATURE

Cada pantalla deberá poder generar una firma estructural que permita reconocerla sin depender de un solo selector.

Ejemplo conceptual:

URL parcial
+
elementos obligatorios
+
formulario
+
botones
+
estructura

Esto permitirá detectar:

SCREEN_MATCH
SCREEN_CHANGED
SCREEN_UNKNOWN
XXXII. CONTRACT DIFF

Dos capturas compatibles deberán poder compararse.

El sistema deberá detectar, entre otros:

element added
element removed
id changed
selector changed
option added
option removed
field became required
button disabled
table changed
navigation changed
geometry changed

No todos los cambios tendrán la misma importancia.

XXXIII. CLASIFICACIÓN DE CAMBIOS

Conceptualmente deberán distinguirse:

COSMETIC
NON_BREAKING
CONTRACT_CHANGE
BREAKING
UNKNOWN

Ejemplo:

cambio de color
→ COSMETIC

nueva opción select
→ CONTRACT_CHANGE

desaparición de campo utilizado
→ BREAKING
XXXIV. RELACIÓN CON SISTEMA LABS

QCC Site Architecture será la principal infraestructura de adquisición del contrato real utilizado para construir los LABS.

Flujo oficial:

SEDE REAL
↓
QCC SITE ARCHITECTURE
↓
SITE CONTRACT
↓
sanitización
↓
LAB
↓
tests
↓
automatización

La Resolución LABS ya establece que QCC será la herramienta central para este proceso.

XXXV. CAPTURA POR PANTALLAS

Una captura aislada no será suficiente para describir una sede compleja.

El sistema deberá permitir construir:

SITE
└── FLOW
    ├── PAGE 01
    ├── PAGE 02
    ├── PAGE 03
    └── PAGE 04

Ejemplo:

MERCURIO
└── EX02_INITIAL
    ├── selección
    ├── datos solicitante
    ├── familiar
    ├── domicilio
    ├── revisión
    └── documentación
XXXVI. CAPTURA INCREMENTAL

No será necesario capturar toda una sede en una sola sesión.

La arquitectura permitirá:

captura página A
+
captura página B futura
+
captura página C futura
=
contrato acumulado

Esto permitirá construir Mercurio durante la actividad ordinaria del despacho.

XXXVII. CAPTURA PASIVA

Se priorizará que QCC capture la arquitectura mientras el usuario realiza una actuación real que ya debía realizarse.

La captura deberá ser:

read-only
fail-open
no interferente

QCC no deberá pulsar botones ni modificar una sede simplemente para inspeccionarla.

Esto mantiene el principio de no interferencia establecido para QCC y la prioridad de observación pasiva fijada por LABS.

XXXVIII. DOS VÍAS DE ADQUISICIÓN

QCC Site Architecture podrá obtener información por dos vías compatibles.

A. Browser Runtime
Python
→ SeleniumBase/CDP
→ DOM
B. QCC Native Capture
Chrome Extension
→ chrome.scripting
→ DOM

Ambas deberán converger progresivamente hacia un mismo esquema canónico.

No deberán mantenerse dos formatos incompatibles de arquitectura.

XXXIX. CHROME NORMAL

La capacidad de captura nativa deberá permitir inspeccionar una sede incluso cuando Chrome haya sido abierto manualmente y no exista SeleniumBase.

Esto permitirá:

Chrome manual
+
QCC
→ Site Architecture

QCC no deberá depender de que el navegador sea propiedad del runtime para poder observar una página autorizada.

XL. CHROME GOBERNADO

Cuando exista una sesión gobernada por Browser Runtime, el mismo contrato deberá poder obtenerse mediante:

BrowserSession
+
dom_inspector

La arquitectura no deberá depender del origen de la sesión.

XLI. ESQUEMA CANÓNICO

Se creará una versión explícita del contrato.

Ejemplo conceptual:

SITE_ARCHITECTURE_SCHEMA_VERSION = 1

La evolución del formato deberá ser versionada.

No deberán cambiarse silenciosamente los significados de los campos.

XLII. ARTEFACTOS

Una captura podrá generar:

metadata.json
site_architecture.json
page.html
documents/
frames/
selectors.json
geometry.json
interactions.json

La estructura física definitiva se determinará durante implementación.

La semántica deberá permanecer separada de la representación concreta.

XLIII. RAW VS NORMALIZED

Se distinguirán dos niveles:

RAW CAPTURE

y:

NORMALIZED SITE CONTRACT

La captura raw servirá para diagnóstico.

El contrato normalizado será la fuente para:

LABS
tests
diffs
automatizaciones

No deberá utilizarse un HTML bruto como único contrato de una sede.

XLIV. SANITIZACIÓN

Las capturas reales pueden contener:

NIE
nombres
direcciones
teléfonos
emails
números de expediente
documentos
datos personales

Por tanto:

Una captura real no será automáticamente apta para versionarse.

Antes de incorporarla como fixture deberá pasar por sanitización.

La resolución LABS ya establece expresamente que los fixtures permanentes deben utilizar datos ficticios y que las capturas de sedes reales deben sanitizarse.

XLV. POLÍTICA GIT

No deberán incorporarse automáticamente al repositorio:

raw DOM
capturas reales
HTML con PII
cookies
tokens
headers sensibles
certificados

Se versionarán:

contratos sanitizados
fixtures sintéticos
schemas
tests
reglas
XLVI. SCREENSHOTS

Una captura visual podrá utilizarse como artefacto complementario de diagnóstico cuando sea útil.

Pero:

screenshot ≠ site contract

La arquitectura deberá derivarse principalmente de datos estructurados.

XLVII. GEOMETRY DIFF

La geometría también podrá compararse.

Por ejemplo:

elemento desaparecido
elemento fuera de viewport
botón desplazado
layout reorganizado
dimensiones alteradas

No obstante, los cambios geométricos deberán diferenciarse de cambios funcionales.

Un desplazamiento visual de 10 px no deberá romper automáticamente una automatización DOM.

XLVIII. GEOMETRY TOLERANCE

Los contratos geométricos deberán admitir tolerancia.

No se deberán exigir valores exactos cuando existan variaciones legítimas por:

resolución
zoom
DPI
tamaño ventana
barra lateral
fuentes
Chrome

El contrato deberá modelar relación espacial cuando corresponda, no una captura fotográfica rígida.

XLIX. RESPONSIVE STATE

Cuando una sede cambie significativamente según tamaño de ventana, podrán existir variantes:

DESKTOP
COMPACT
MOBILE

Las automatizaciones del ERP deberán utilizar preferentemente una configuración de navegador controlada.

El LAB deberá reproducir la variante realmente utilizada.

L. SCROLL CONTRACT

Cuando un elemento requiera desplazamiento se registrará:

scroll container
document scroll
element visibility
target rect after scroll

No deberá asumirse que todos los elementos dependen del window.scrollY.

Puede existir scroll interno en:

modal
panel
div
iframe
LI. ELEMENT OCCLUSION

La evolución futura podrá comprobar si un punto interactivo está cubierto por otro elemento.

Esto será especialmente importante para GUI.

Conceptualmente podrá utilizarse información equivalente a:

document.elementFromPoint()

antes de una acción física.

LII. INTERACTION POINT

Cuando deba usarse GUI no será obligatorio utilizar siempre el centro geométrico.

Podrá calcularse un:

safe_interaction_point

situado dentro de la zona realmente interactiva y no cubierta.

LIII. TOOLTIP Y MENÚS DINÁMICOS

La arquitectura deberá poder representar elementos que solamente aparecen tras:

hover
click
focus

No deberá suponerse que todo el contrato está presente permanentemente en DOM.

LIV. CONTROLES NATIVOS FUERA DEL DOM

Se reconoce que existen elementos que pueden abandonar el DOM del sitio.

Ejemplos:

selector nativo de archivos
certificados
diálogos Chrome
ventanas del sistema

Estos elementos no podrán ser clonados exclusivamente mediante DOM.

La arquitectura deberá marcar el límite:

WEB CONTRACT
→ EXTERNAL UI BOUNDARY

y permitir que otro runtime específico gestione la siguiente fase.

LV. FILE INPUTS

Los input[type=file] dinámicos deberán identificarse aunque:

sean invisibles
sean generados dinámicamente
sean reemplazados
pertenezcan a librerías como Plupload

El trabajo D5 de Mercurio demuestra que esta información puede resultar crítica incluso cuando el control visual aparente es otro.

LVI. OBSERVACIÓN DE MUTACIONES

La evolución del sistema podrá incorporar observación mediante:

MutationObserver

para determinar:

qué cambia
cuándo cambia
qué acción lo produjo

Esto será útil para:

interfaces SPA;
uploads;
tablas dinámicas;
mensajes;
transiciones sin navegación.
LVII. DURACIÓN Y ASINCRONÍA

Los contratos podrán registrar:

action
→ pending state
→ completion signal

No se utilizarán tiempos fijos como única prueba de finalización cuando exista un indicador observable.

Principio:

esperar estado

preferentemente a:

sleep arbitrario
LVIII. NETWORK OBSERVABLE CONTRACT

Cuando resulte necesario para reproducir un LAB, podrán registrarse de forma controlada:

method
path
status
content type
observable request purpose
observable response effect

No será necesario ni conveniente capturar indiscriminadamente todo el tráfico.

No deberán almacenarse:

cookies
tokens
Authorization
datos personales innecesarios
LIX. SITE CONTRACT

El resultado final de Site Architecture no será simplemente un volcado.

Será un contrato conceptual:

SITE CONTRACT
│
├── identity
├── pages
├── elements
├── selectors
├── geometry
├── interactions
├── transitions
├── validations
└── scenarios

Este contrato será el puente entre:

sede real

y:

LAB
LX. AUTOMATION CONTRACT

La automatización podrá declarar qué partes del Site Contract utiliza.

Ejemplo:

requires:
- page DOCUMENTATION
- selector DOC_TYPE
- selector FILE_INPUT
- selector ATTACH_BUTTON
- transition FILE_UPLOADED

Esto permitirá saber si un cambio de sede afecta realmente a una automatización concreta.

LXI. FAIL-SAFE

Antes de una acción sensible, el runtime podrá validar el contrato mínimo esperado.

Ejemplo:

PAGE_MATCH
ELEMENT_MATCH
STATE_MATCH

Si existe una divergencia importante:

CONTRACT_MISMATCH

la automatización deberá detenerse de forma segura.

LXII. NO AUTOHEALING CIEGO

QCC Site Architecture podrá sugerir nuevos selectores cuando uno cambie.

Pero:

No deberá modificar automáticamente una automatización productiva basándose únicamente en una heurística.

El flujo correcto será:

selector roto
↓
candidate detected
↓
LAB
↓
tests
↓
validación
↓
actualización contractual
LXIII. RELACIÓN CON QCC

QCC será la interfaz desde la que progresivamente podrán ejecutarse operaciones como:

Capturar arquitectura
Ver arquitectura
Comparar captura
Identificar pantalla
Inspeccionar elemento
Exportar contrato

Estas herramientas no deberán mezclarse con el estado de negocio de las presentaciones.

QCC seguirá siendo una interfaz contextual del ERP, tal como establece su resolución general.

LXIV. MODO ARQUITECTURA

Se aprueba conceptualmente un futuro modo:

QCC
└── SITE ARCHITECTURE

con funciones como:

Capturar página
Identificar controles
Mostrar selectores
Mostrar geometry
Comparar versión
Guardar snapshot

Su implementación se realizará progresivamente.

LXV. MODO ELEMENT INSPECTOR

En fases posteriores podrá seleccionarse visualmente un elemento de la página y visualizar:

tag
id
name
role
aria
text
selectors
bounding rect
visibility
interaction
frame
shadow path

Esta funcionalidad tendrá finalidad diagnóstica y contractual.

LXVI. MERCURIO

Mercurio será el primer gran consumidor de Site Architecture.

El sistema permitirá construir progresivamente:

Mercurio
│
├── presentaciones EX
├── aportación documental
├── renovaciones
└── componentes compartidos

Cada pantalla observada podrá convertirse en una pieza del contrato de Mercurio LAB.

LXVII. ICP PLUS

ICP Plus también podrá aprovechar la arquitectura extendida.

Especial importancia tendrá:

DOM
+
geometry

cuando algún control necesite interacción mediante navegador normal, mouse o teclado.

La existencia de GUI no deberá implicar abandonar el conocimiento semántico del DOM.

LXVIII. OTRAS SEDES

La arquitectura será agnóstica de proveedor.

Deberá ser reutilizable para:

DEHú
UGE
Policía
Guardia Civil
Registro Civil
consulados
registros electrónicos
portales futuros

No se creará un inspector diferente para cada sede.

LXIX. TESTS

La evolución deberá quedar protegida mediante:

schema tests
DOM capture tests
iframe tests
Shadow DOM tests
selector tests
geometry tests
visibility tests
normalization tests
diff tests
sanitization tests
LAB contract tests

No será necesario implementarlos todos en una sola fase.

LXX. COMPATIBILIDAD

Los contratos actuales de capture_dom_snapshot() no deberán romperse innecesariamente.

La evolución deberá ser:

aditiva
versionada
testeada

siempre que resulte técnicamente razonable.

LXXI. SEPARACIÓN DE RESPONSABILIDADES

Se mantendrá:

dom_inspector
→ adquisición

site architecture normalizer
→ normalización

site contract
→ modelo contractual

contract diff
→ comparación

LAB builder
→ consumidor

runtime
→ ejecución

No deberá crecer dom_inspector.py indefinidamente hasta convertirse en un módulo monolítico que haga todas estas funciones.

LXXII. PRINCIPIO DE NO ACOPLAMIENTO

QCC Site Architecture no deberá conocer:

Cliente
Expediente
Cobro
CAA
reglas jurídicas

salvo metadata contextual estrictamente necesaria para etiquetar una captura.

Su función es describir la aplicación web, no el negocio del despacho.

LXXIII. OBJETIVO FINAL

La arquitectura perseguida será:

              SEDE REAL
                  │
                  ▼
        QCC SITE ARCHITECTURE
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
    SITE CONTRACT       CONTRACT DIFF
        │
        ▼
       LAB
        │
        ▼
 AUTOMATION TESTS
        │
        ▼
 PRODUCTIVE RUNTIME

Y, para interacción GUI:

SITE CONTRACT
      ↓
element semantic identity
      ↓
current DOM
      ↓
current geometry
      ↓
safe interaction point
      ↓
mouse / keyboard
LXXIV. REGLA DE GOBIERNO

A partir de esta resolución:

La Arquitectura DOM no se considerará únicamente una herramienta para extraer HTML.

Deberá evolucionar hacia la representación estructural, semántica, geométrica e interactiva de las sedes electrónicas.

Y:

Toda nueva capacidad desarrollada para inspeccionar una sede deberá procurar alimentar el Site Contract común en lugar de crear formatos de diagnóstico aislados.

LXXV. RESOLUCIÓN

Se acuerda:

Aprobar QCC Site Architecture como evolución oficial de la actual infraestructura de Arquitectura DOM.

La captura deberá evolucionar desde DOM puro hacia un contrato compuesto por identidad de página, estructura DOM, semántica, selectores, geometría, visibilidad, estados, interacciones y transiciones.

La geometría deberá permitir relacionar elementos DOM con viewport, scroll, ventana y, cuando resulte necesario, coordenadas físicas de pantalla.

Las automatizaciones GUI deberán localizar y recalcular la geometría inmediatamente antes de actuar y no depender ordinariamente de coordenadas rígidas.

QCC Site Architecture deberá servir como infraestructura principal para construir y mantener los Site Contracts utilizados por el Sistema LABS.

Las capturas podrán realizarse tanto desde Chrome gobernado mediante SeleniumBase/CDP como desde Chrome normal mediante QCC, convergiendo ambos mecanismos hacia un esquema contractual común.

La observación será prioritariamente pasiva, sin modificar innecesariamente el DOM ni ejecutar actuaciones administrativas.

Las capturas reales con información personal deberán considerarse artefactos sensibles y no podrán convertirse directamente en fixtures versionados sin sanitización.

Mercurio será el primer gran caso de uso, pero la infraestructura será transversal a todas las futuras sedes electrónicas del ERP.