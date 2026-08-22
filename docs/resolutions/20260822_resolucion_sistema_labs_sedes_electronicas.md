RESOLUCIÓN SOBRE EL SISTEMA LABS DE SEDES ELECTRÓNICAS

Proyecto: Quesada Abogados ERP
Fecha: 22 de agosto de 2026
Estado de referencia: rama develop, integración 70ef6fb
Naturaleza: Resolución técnica, arquitectónica y funcional vinculante
Ámbito: Mercurio, ICP Plus, DEHú, UGE, Policía Nacional, Guardia Civil, Registro Electrónico y cualquier otra sede, portal o aplicación web administrativa automatizada o asistida por Quesada Abogados ERP
Nombre oficial: Sistema LABS de Sedes Electrónicas

I. OBJETO

La presente resolución aprueba la creación del Sistema LABS de Sedes Electrónicas como infraestructura permanente de desarrollo, pruebas, validación y regresión de Quesada Abogados ERP.

Se establece como principio obligatorio:

Toda sede electrónica que vaya a ser automatizada por Quesada Abogados deberá disponer previamente de un LAB propio que reproduzca su funcionamiento.

El LAB no tendrá la consideración de una simple colección de fixtures, páginas HTML aisladas o mocks de tests.

Será un entorno de trabajo navegable y funcional, destinado a reproducir el comportamiento de la sede electrónica necesario para que el ERP pueda ejecutar contra él los mismos recorridos que posteriormente ejecutará contra la sede real.

II. PRINCIPIO DE CLON PREVIO A LA AUTOMATIZACIÓN

Queda establecido el siguiente orden obligatorio:

SEDE ELECTRÓNICA REAL
        ↓
observación y arquitectura
        ↓
CONTRATO DE LA SEDE
        ↓
LAB DE LA SEDE
        ↓
automatización
        ↓
tests contra LAB
        ↓
uso productivo

Por tanto:

No deberá desarrollarse primero una automatización y posteriormente intentar simular la sede.

La metodología correcta será:

primero comprender la sede, después clonarla en LAB y finalmente desarrollar la automatización contra dicho LAB.

Esta regla será aplicable a cada nueva sede electrónica que se incorpore al ecosistema.

III. NATURALEZA DEL LAB

Cada LAB deberá reproducir con la máxima fidelidad posible el contrato observable y operativo de la sede real.

Esto comprenderá, cuando exista:

URLs y rutas;
pantallas;
formularios;
estructura DOM;
identificadores;
nombres de controles;
selectores;
botones;
enlaces;
inputs;
selects;
opciones de selects;
checkboxes;
radios;
áreas de texto;
tablas;
iframes;
controles dinámicos;
uploads;
eventos JavaScript;
validaciones;
mensajes de error;
estados habilitado/deshabilitado;
campos obligatorios;
navegación;
transiciones;
peticiones HTTP relevantes;
respuestas;
cambios DOM producidos por acciones;
comportamiento asíncrono;
estados de carga;
límites;
reglas documentales;
códigos;
errores reproducibles;
comportamiento final observable por Chrome.

El objetivo será que, desde la perspectiva del:

Presentation Runtime
SeleniumBase / CDP
QCC
DOM Reader
Automation Connector
usuario

el LAB se comporte como la sede real dentro del alcance reproducido.

IV. CONCEPTO DE EXACTITUD

La expresión “clon de la sede electrónica” se entenderá en el proyecto como:

Reproducción exacta del funcionamiento observable y relevante para la interacción, automatización, navegación y validación del ERP.

No será necesario reconstruir elementos internos de la Administración que no sean observables ni necesarios para nuestro contrato, como:

bases de datos internas ministeriales;
sistemas internos de registro;
infraestructura de red gubernamental;
servicios internos no accesibles;
algoritmos privados;
sistemas de autenticación reales;
autoridades de certificación;
infraestructura interna de firma.

Dichos componentes se reproducirán mediante equivalentes locales cuando formen parte del flujo observable.

Ejemplo:

FIRMA REAL
    ↓
LAB
    ↓
FIRMA_SIMULADA

o:

REGISTRO ADMINISTRATIVO REAL
    ↓
LAB
    ↓
REGISTRO_SIMULADO
    ↓
número ficticio
    ↓
justificante ficticio

Desde el punto de vista del ERP, el contrato deberá ser equivalente.

V. UN LAB POR SEDE ELECTRÓNICA

Cada sede electrónica tendrá un espacio LAB propio.

Conceptualmente:

SITE LABS
│
├── mercurio/
├── icp_plus/
├── dehu/
├── uge/
├── policia/
├── guardia_civil/
├── registro_electronico/
├── consulados/
└── futuras_sedes/

No deberá construirse un único LAB genérico que mezcle contratos de sedes diferentes.

Cada sede tendrá:

su contrato;
sus pantallas;
sus flujos;
sus fixtures;
sus escenarios;
sus tests;
su evolución;
su versión.
VI. MERCURIO: UN LAB POR MODELO EX

En Mercurio no existirá un único formulario genérico para todos los procedimientos.

Se establece:

Cada modelo EX con funcionamiento propio tendrá su LAB específico.

Por ejemplo:

MERCURIO LAB
│
├── EX01
├── EX02
├── EX03
├── EX04
├── EX07
├── EX10
├── EX11
├── EX17
├── EX18
├── EX19
├── EX20
├── EX23
├── EX24
├── EX26
├── EX30
├── EX32
└── futuros EX

La relación exacta se ampliará según los trámites que gestione Quesada Abogados.

Cada LAB EX deberá reproducir las pantallas y decisiones correspondientes al modelo concreto.

Ejemplo:

LAB EX01
   ↓
selección territorial
   ↓
tipo de solicitud
   ↓
datos extranjero
   ↓
datos representante
   ↓
domicilio
   ↓
datos específicos EX01
   ↓
revisión
   ↓
documentación

Mientras:

LAB EX32
   ↓
sus propios datos
   ↓
sus propios campos
   ↓
sus propias opciones
   ↓
sus propias reglas
   ↓
documentación

No se asumirá que dos modelos EX tienen idéntico contrato por compartir Mercurio.

VII. COMPONENTES COMUNES REUTILIZABLES

La existencia de un LAB por EX no implicará duplicar componentes comunes.

Se distinguirá entre:

CONTRATO ESPECÍFICO DEL PROCEDIMIENTO
               +
COMPONENTES COMUNES DE MERCURIO

Ejemplo:

EX01 LAB ─┐
EX02 LAB ─┤
EX10 LAB ─┤
EX32 LAB ─┘
          ↓
MERCURIO DOCUMENT LAB

Los componentes compartidos podrán incluir:

subida documental;
Plupload;
tabla de adjuntos;
validaciones comunes;
revisión;
navegación común;
infraestructura de sesión simulada;
errores comunes;
registro simulado;
justificante simulado.

Cada EX deberá acoplar estos componentes en el punto exacto del flujo en que corresponda.

VIII. LAB DOCUMENTAL MERCURIO

Se reconoce como primer componente real del futuro sistema el laboratorio documental ya construido en:

tools/mercurio_lab/

y validado mediante los hitos:

f072722
40703f0
fbbe828

El LAB documental ha demostrado el contrato:

Plupload real
→ input mOxie dinámico
→ send_file()
→ FilesAdded
→ multipart
→ FileUploaded
→ tabla de adjuntos
→ lectura D2
→ confirmación D4

Este componente no deberá desecharse.

Se convertirá progresivamente en el módulo documental común de Mercurio LAB y se acoplará a cada LAB EX.

IX. ARQUITECTURA OBJETIVO MERCURIO

La arquitectura objetivo será:

MERCURIO LAB
│
├── runtime común
│
├── session engine
│
├── navigation engine
│
├── validation engine
│
├── scenarios
│
│
├── procedures/
│   ├── EX01/
│   ├── EX02/
│   ├── EX03/
│   ├── EX10/
│   ├── EX17/
│   ├── EX32/
│   └── ...
│
└── shared/
    ├── documentation/
    ├── uploads/
    ├── review/
    ├── errors/
    └── fake_registry/

La implementación física podrá evolucionar, pero deberá conservar esta separación conceptual.

X. FLUJO COMPLETO DE UN LAB

Un LAB deberá permitir, cuando el flujo real lo permita, recorrer el procedimiento completo:

INICIO
↓
selección trámite
↓
formularios
↓
validaciones
↓
pantallas intermedias
↓
revisión
↓
documentación
↓
firma simulada
↓
registro simulado
↓
justificante simulado
↓
FIN

No deberá quedarse limitado a una pantalla si el objetivo del ERP es automatizar el recorrido completo.

XI. INTEGRACIÓN CON EL CRM

Los LABS no servirán únicamente para probar Selenium.

Deberán permitir probar el ciclo completo del ERP.

Ejemplo objetivo:

crear cliente ficticio
        ↓
crear expediente ficticio
        ↓
aplicar tipo/subtipo
        ↓
aplicar requisitos documentales
        ↓
marcar preparado
        ↓
crear actividad CAA
        ↓
iniciar Presentación Asistida
        ↓
MERCURIO LAB EX01
        ↓
recorrer formulario
        ↓
LAB DOCUMENTACIÓN
        ↓
registro simulado
        ↓
justificante simulado
        ↓
retorno al ERP
        ↓
actualización expediente
        ↓
cierre actividad CAA
        ↓
creación siguiente actividad
        ↓
validación trazabilidad completa

Por tanto, los LABS serán también entornos E2E del negocio.

XII. TRAZABILIDAD

El sistema deberá poder comprobar automáticamente que cada evento producido durante una presentación simulada se refleja correctamente en el ERP.

Ejemplo:

PRESENTATION_QUEUED
PRESENTATION_STARTED
FORM_STARTED
FORM_COMPLETED
DOCUMENT_STAGED
DOCUMENT_UPLOADED
DOCUMENTATION_COMPLETE
PRESENTATION_READY
PRESENTATION_REGISTERED_SIMULATED
RECEIPT_GENERATED_SIMULATED
PRESENTATION_COMPLETED

Los nombres concretos pertenecerán al modelo de dominio correspondiente.

La finalidad será validar:

estados;
transiciones;
eventos;
relaciones;
tareas;
documentos;
justificantes;
fechas;
trazabilidad;
retorno al expediente.
XIII. DATOS DE LOS LABS

Los LABS utilizarán exclusivamente:

personas ficticias;
NIE ficticios;
pasaportes ficticios;
direcciones ficticias;
expedientes ficticios;
PDFs sintéticos;
documentos generados específicamente para tests.

Queda prohibido introducir innecesariamente en fixtures versionados:

datos reales de clientes;
NIE reales;
pasaportes reales;
correos reales;
teléfonos reales;
documentos administrativos reales con información personal.

Las capturas procedentes de una sede real deberán ser sanitizadas antes de convertirse en fixtures permanentes.

XIV. AISLAMIENTO DE PRODUCCIÓN

Todo LAB deberá estar diseñado para que no pueda producir accidentalmente una actuación administrativa real.

Se utilizarán preferentemente:

127.0.0.1
localhost

Los tests E2E deberán incluir guardas que impidan ejecutarse contra hosts productivos.

Ejemplo:

LAB_LOCALHOST_GUARD

Un LAB nunca deberá:

presentar solicitudes reales;
firmar solicitudes reales;
registrar escritos reales;
reservar citas reales;
modificar expedientes administrativos reales.
XV. PRESENTACIÓN SIMULADA

Cuando sea necesario probar un procedimiento completo, el LAB podrá incorporar un sistema de registro ficticio.

Ejemplo:

LAB-2026-000001

y generar:

justificante_lab.pdf

La respuesta podrá reproducir la estructura observable de la sede real, pero deberá quedar inequívocamente marcada como:

SIMULADO
LAB
NO VÁLIDO ADMINISTRATIVAMENTE
XVI. ESCENARIOS DE ERROR

Cada LAB deberá permitir reproducir no solo el happy path sino los principales errores de la sede.

Ejemplos:

normal
documento_faltante
documento_duplicado
archivo_invalido
archivo_demasiado_grande
upload_error
timeout
sesion_caducada
validation_error
server_error
transicion_inesperada
dom_changed

Cuando una incidencia real sea relevante para nuestra automatización deberá intentarse reproducir posteriormente en LAB.

Así un fallo real observado una vez podrá convertirse en un test repetible.

XVII. QCC COMO HERRAMIENTA DE CONSTRUCCIÓN DE LABS

Quesada Chrome Companion será una herramienta central para la construcción de los LABS.

El proceso será:

SEDE REAL
↓
QCC
↓
Arquitectura de la pantalla
↓
normalización
↓
sanitización
↓
Site Contract
↓
LAB

QCC permitirá reducir el trabajo manual necesario para reconstruir las sedes.

La resolución específica relativa a la ampliación de QCC Site Architecture determinará el contenido completo de dichas capturas.

XVIII. CAPTURA PASIVA DE LA SEDE REAL

Siempre que sea posible, la información necesaria para construir o actualizar un LAB se obtendrá mediante observación pasiva durante usos reales de la sede.

Se priorizará:

uso administrativo real
        +
captura pasiva QCC

frente a:

presentaciones ficticias contra producción

No deberán generarse actuaciones administrativas reales únicamente para probar automatizaciones cuando el comportamiento pueda ser reproducido en LAB.

XIX. DESARROLLO CONTRA LAB

Una vez disponible un LAB suficientemente fiel:

La automatización deberá desarrollarse y depurarse principalmente contra el LAB.

Ejemplo:

Automation
    ↓
Mercurio EX01 LAB

y no:

Automation en desarrollo
    ↓
Mercurio producción
    ↓
prueba y error

La sede pública dejará de ser el entorno ordinario de testing.

XX. PRIMER USO REAL

Superar el LAB será el criterio técnico de aceptación previo al uso productivo.

No se establece como requisito una presentación administrativa ficticia o de prueba en la sede real.

La primera utilización real de una automatización podrá ser una actuación ordinaria del despacho.

Las protecciones del runtime deberán detener el proceso ante divergencias relevantes del contrato esperado.

XXI. DETECCIÓN DE CAMBIOS

Los contratos LAB deberán poder compararse con capturas posteriores de la sede real.

Flujo objetivo:

SITE CONTRACT v1
        ↓
nueva captura QCC
        ↓
CONTRACT DIFF
        ↓
sin cambios
    o
cambio detectado
        ↓
actualizar LAB
        ↓
suite regresión

Esto permitirá detectar:

selectores eliminados;
controles nuevos;
cambios de IDs;
nuevas opciones;
modificación de tablas;
nuevas pantallas;
cambios de navegación;
modificaciones de reglas documentales.
XXII. VERSIONADO

Los LABS formarán parte del repositorio del proyecto.

Se versionarán:

código propio;
contratos;
fixtures sintéticos;
escenarios;
configuraciones;
tests;
documentación.

Los recursos de terceros estarán sometidos a su licencia.

Cuando resulte conveniente usar exactamente un asset proporcionado por la sede pero no deba versionarse, se gobernará mediante:

exclusión Git;
URL de origen;
hash;
tamaño esperado;
procedimiento reproducible de instalación.

El precedente de plupload.full.min.js se considera válido.

XXIII. TESTS OBLIGATORIOS

Cada LAB podrá disponer de varias capas:

contract tests
↓
unit tests
↓
browser tests
↓
LAB E2E
↓
CRM + LAB E2E
↓
traceability tests

Una automatización de sede no se considerará robusta únicamente porque consiga completar manualmente un recorrido.

Deberá existir cobertura repetible.

XXIV. FIDELIDAD VISUAL Y GEOMÉTRICA

Cuando una automatización dependa únicamente del DOM, la fidelidad prioritaria será contractual y funcional.

Cuando exista:

automatización mediante ratón;
teclado;
interacción GUI;
elementos inaccesibles mediante DOM;
ventanas auxiliares;
controles dependientes de posición;

el LAB deberá reproducir también de forma suficiente:

disposición;
tamaño;
posición relativa;
viewport;
scroll;
geometría de los controles.

La futura resolución QCC Site Architecture establecerá el sistema de captura geométrica.

XXV. RELACIÓN CON SELENIUMBASE, CDP Y GUI

Los LABS serán independientes del método concreto de interacción.

Una misma sede clonada deberá poder utilizarse para validar:

DOM
CDP
SeleniumBase
mouse
keyboard
otros runtimes futuros

El LAB describe la sede.

El runtime describe cómo interactuamos con ella.

No deberán mezclarse ambos conceptos.

XXVI. ESTADO DEL LAB DOCUMENTAL ACTUAL

Queda reconocido el trabajo existente como primera implementación oficial del Sistema LABS.

Actualmente se encuentra validado:

Mercurio Document LAB
        ↓
Plupload real
        ↓
send_file productivo
        ↓
multipart
        ↓
FileUploaded
        ↓
D2
        ↓
D4

Este LAB constituirá el componente documental sobre el que se construirán los futuros LAB EX.

XXVII. PRIMER PROCEDIMIENTO COMPLETO

Se establece como objetivo inicial construir un primer procedimiento Mercurio completo que demuestre toda la arquitectura.

El procedimiento deberá permitir:

CRM
↓
expediente ficticio
↓
CAA
↓
Presentation Runtime
↓
Mercurio LAB EX
↓
formularios
↓
LAB documental
↓
registro simulado
↓
retorno CRM
↓
trazabilidad completa

Una vez demostrado dicho patrón, los restantes EX podrán incorporarse de forma progresiva.

XXVIII. EXTENSIÓN A TODAS LAS SEDES

La metodología no quedará limitada a Mercurio.

Será aplicable a cada sede electrónica que Quesada Abogados automatice.

Por tanto:

Mercurio será la primera implantación completa del sistema, pero LABS será infraestructura transversal del ERP.

Cuando se incorpore una sede nueva:

Nueva sede
↓
arquitectura
↓
LAB propio
↓
tests
↓
automatización
XXIX. REGLA DE GOBIERNO

A partir de la entrada en vigor de esta resolución:

No se aprobará como arquitectura definitiva una nueva automatización de sede electrónica que carezca de un LAB asociado suficiente para reproducir el recorrido automatizado.

Las excepciones deberán ser:

técnicas;
justificadas;
temporales;
documentadas.

Nunca constituirán el patrón ordinario de desarrollo.

XXX. FINALIDAD ESTRATÉGICA

El Sistema LABS permitirá convertir el desarrollo de automatizaciones administrativas en un proceso reproducible.

La evolución perseguida será:

HOY

Sede real
→ investigar
→ automatizar
→ probar
→ corregir


OBJETIVO

Sede real
→ observar
→ capturar contrato
→ construir LAB
→ desarrollar en local
→ ejecutar regresión
→ usar en producción

Esto permitirá:

reducir riesgos;
reducir pruebas contra producción;
acelerar desarrollo;
probar errores difíciles de reproducir;
validar trazabilidad del ERP;
detectar cambios de las sedes;
reutilizar contratos;
introducir nuevos procedimientos con mayor rapidez;
mantener decenas de automatizaciones de forma gobernada.
XXXI. RESOLUCIÓN

Se acuerda:

Instituir el Sistema LABS de Sedes Electrónicas como infraestructura obligatoria y permanente de Quesada Abogados ERP.

Cada sede electrónica automatizada deberá disponer de su propio entorno LAB.

En Mercurio se construirá un LAB específico para cada modelo EX que se automatice, reproduciendo su recorrido particular.

El LAB documental Mercurio existente se convertirá en un componente común reutilizable y será acoplado a los diferentes LAB EX en la fase documental correspondiente.

Los LABS reproducirán con fidelidad el funcionamiento observable de las sedes y permitirán ejecutar contra ellos las automatizaciones productivas del ERP.

Los LABS deberán permitir progresivamente probar el ciclo completo desde la creación del expediente en el CRM hasta la presentación simulada y la validación final de su trazabilidad.

El desarrollo y las pruebas ordinarias se realizarán contra LAB; las sedes administrativas reales no serán utilizadas como bancos de pruebas cuando exista un LAB equivalente.

Esta sería la resolución base que yo dejaría vinculante. El concepto central queda exactamente como lo planteas: cada sede electrónica tiene su clon; Mercurio además se descompone por EX y comparte componentes reutilizables como el LAB documental.

El siguiente paso no sería todavía desarrollar nada: materializamos esta resolución en la rama docs/labs-qcc-site-architecture, la revisamos y la congelamos en un commit documental independiente. Después emitimos la segunda resolución de QCC Site Architecture / DOM + Geometry + Interaction.