# RESOLUCIÓN DE EVOLUCIÓN DEL GOBIERNO DOCUMENTAL DE BOX Y COPIA BIDIRECCIONAL CONTROLADA

**Fecha:** 05/10/2026
**Proyecto:** Quesada Abogados
**Estado:** APROBADA POR DIRECCIÓN
**Ámbito:** Box Drive, Bandeja Documental, expedientes, importación/exportación documental, trazabilidad e integridad.

---

## I. OBJETO

La presente resolución resuelve la divergencia entre:

- `011_sistema_documental_box_vigilancia.md`, que estableció originalmente que el ERP solo observa Box y no lo manipula;
- `016_sistema_trabajo.md`, que posteriormente introdujo operaciones explícitas de copia documental hacia expediente/Box.

La Dirección determina que la prohibición absoluta original debe evolucionar para permitir un flujo documental útil y seguro.

La arquitectura aprobada pasa a permitir **copias bidireccionales controladas entre ERP y Box**, manteniendo prohibidas por defecto las operaciones destructivas o de reorganización sobre documentos existentes en Box.

---

## II. DOC-001 · MODIFICACIÓN PARCIAL

`DOC-001` pasa a **MODIFICADA PARCIALMENTE**.

Se conserva su finalidad:

- proteger la integridad de Box;
- impedir automatizaciones destructivas;
- evitar movimientos o reorganizaciones accidentales;
- mantener trazabilidad;
- impedir que el ERP actúe libremente sobre Box.

Queda modificada únicamente la prohibición absoluta de escritura.

A partir de esta resolución, el ERP podrá crear **copias nuevas controladas** dentro de Box cuando exista una operación documental autorizada.

---

## III. DOC-003 · COPIA BIDIRECCIONAL CONTROLADA ERP ↔ BOX

Se aprueba:

`DOC-003 · Copia Bidireccional Controlada ERP ↔ Box`

Se permiten los siguientes flujos ordinarios:

```text
DOWNLOADS
   ↓
BANDEJA DOCUMENTAL
   ↓
EXPEDIENTE / DESTINO BOX
```

y:

```text
BOX
   ↓
BANDEJA DOCUMENTAL
   ↓
ÁREA LOCAL AUTORIZADA / DOWNLOADS / PROCESAMIENTO
```

La Bandeja Documental actúa como capa de entrada, inspección, clasificación, trazabilidad y preparación de operaciones documentales.

---

## IV. OPERACIONES PERMITIDAS

El ERP podrá:

- detectar documentos en carpetas locales autorizadas, incluida Downloads cuando exista configuración;
- incorporarlos a la Bandeja Documental;
- calcular hash;
- extraer metadata;
- clasificar;
- detectar duplicados;
- relacionarlos con cliente/expediente;
- seleccionar destino;
- crear una copia nueva dentro del expediente correspondiente en Box;
- copiar documentos desde Box hacia Bandeja o almacenamiento local autorizado;
- generar previews, OCR, texto extraído o artefactos derivados;
- registrar origen, destino, hash, timestamp y resultado;
- verificar que la copia realizada coincide con el origen.

---

## V. OPERACIONES NO AUTORIZADAS POR DEFECTO

La autorización de copia no implica autorización general para manipular Box.

El ERP no podrá, salvo resolución posterior o política específica expresamente aprobada:

- eliminar archivos existentes de Box;
- mover archivos existentes entre carpetas Box;
- renombrar archivos existentes de Box;
- reorganizar automáticamente estructuras de carpetas;
- sobrescribir silenciosamente un archivo existente;
- sustituir el original;
- vaciar carpetas;
- sincronizar bidireccionalmente de forma indiscriminada.

Regla:

```text
CREAR COPIA NUEVA CONTROLADA     → SÍ
MODIFICAR OBJETO EXISTENTE       → NO, salvo autorización expresa
DESTRUIR / MOVER / REORGANIZAR   → NO, salvo autorización expresa
```

---

## VI. BANDEJA DOCUMENTAL COMO STAGING

La Bandeja Documental no será una segunda fuente documental canónica.

Su función será:

```text
ENTRADA
→ INSPECCIÓN
→ CLASIFICACIÓN
→ DEDUPE
→ ASOCIACIÓN
→ PROPUESTA / SELECCIÓN DE DESTINO
→ COPIA
→ VERIFICACIÓN
→ REGISTRO
```

El documento podrá permanecer temporalmente en staging para procesamiento.

Una vez completado el flujo, el sistema deberá conocer:

- origen;
- destino;
- expediente;
- hash;
- estado;
- resultado de verificación.

---

## VII. DESCARGAS → BANDEJA → BOX

Se aprueba expresamente el siguiente flujo:

1. un documento entra en Downloads u otra carpeta de ingestión autorizada;
2. el ERP lo detecta o el usuario lo incorpora a Bandeja;
3. Bandeja clasifica o solicita clasificación;
4. se determina expediente y carpeta destino;
5. se realiza copia hacia Box;
6. se calcula/verifica hash o mecanismo equivalente;
7. se registra la operación;
8. solo después de validación podrá aplicarse una política local de archivo/eliminación del original fuera de Box.

La eliminación del archivo local de origen no forma parte automática de la copia y deberá gobernarse separadamente.

---

## VIII. BOX → BANDEJA / LOCAL

También se permite:

```text
BOX
→ copia de lectura
→ BANDEJA / ÁREA TEMPORAL / DOWNLOADS
```

para:

- revisión;
- OCR;
- transformación;
- envío;
- preparación de escrito;
- análisis;
- indexación;
- Knowledge;
- otras funciones autorizadas.

La copia hacia fuera de Box **no eliminará ni alterará el original en Box**.

---

## IX. NO USAR “MOVER” COMO OPERACIÓN ORDINARIA

Cuando el objetivo funcional pueda alcanzarse mediante copia + verificación, se preferirá:

```text
COPY
→ VERIFY
→ REGISTER
```

frente a:

```text
MOVE
```

Esto reduce riesgo de pérdida documental.

Especialmente:

- desde Box hacia fuera: copiar, no mover;
- dentro de Box: no mover automáticamente por defecto;
- hacia Box: crear copia nueva en destino, sin modificar el origen.

---

## X. DESTINOS BOX AUTORIZADOS

Toda copia ERP → Box deberá tener un destino determinado de forma gobernada.

El sistema deberá conocer, cuando proceda:

- expediente;
- raíz Box del expediente;
- subcarpeta seleccionada;
- ruta final prevista;
- nombre final;
- política de colisión.

No se realizarán escrituras arbitrarias fuera de raíces autorizadas.

---

## XI. COLISIONES Y DEDUPLICACIÓN

Antes de escribir en Box, el ERP deberá comprobar, cuando resulte técnicamente posible:

- existencia previa;
- hash;
- nombre;
- tamaño;
- metadata relevante.

Ante una colisión no debe sobrescribir silenciosamente.

Opciones posibles:

- reutilizar documento idéntico;
- cancelar;
- generar nombre seguro/versionado;
- solicitar decisión humana.

---

## XII. TRAZABILIDAD

Toda operación de copia deberá poder registrar:

- `source_type`;
- origen;
- destino;
- expediente;
- documento;
- hash antes/después cuando proceda;
- tamaño;
- timestamp;
- usuario/worker/origen de la acción;
- resultado;
- error;
- política aplicada.

La trazabilidad deberá permitir reconstruir qué ocurrió sin depender de memoria humana.

---

## XIII. DOCUMENTOS GENERADOS POR ERP

Los documentos generados por ERP —DOCX, PDF, formularios, informes o escritos— podrán:

- registrarse;
- revisarse;
- asociarse al expediente;
- copiarse a Box mediante el mismo canal gobernado de `DOC-003`.

No requieren una excepción arquitectónica independiente.

La escritura continúa sujeta a:

- destino autorizado;
- deduplicación;
- no sobrescritura silenciosa;
- trazabilidad;
- verificación.

---

## XIV. OPERACIÓN HUMANA

Las personas autorizadas continúan pudiendo operar directamente sobre Box mediante sus herramientas ordinarias.

El ERP podrá detectar posteriormente:

- archivos nuevos;
- movimientos;
- renombrados;
- eliminaciones;
- cambios de estructura;

y actualizar sus referencias o alertar cuando proceda.

---

## XV. WATCHDOG / LISTENER DE BOX

Se establece como objetivo funcional del sistema documental disponer de un **Watchdog / Listener gobernado** sobre las raíces y carpetas Box autorizadas.

Su función será exclusivamente observar y registrar cambios, no ejecutarlos.

El Listener deberá poder detectar, cuando la infraestructura utilizada lo permita:

- creación de archivos;
- modificación de archivos;
- creación de carpetas;
- movimientos;
- renombrados;
- eliminaciones;
- cambios de ruta;
- otros eventos documentales relevantes.

El flujo de referencia será:

```text
BOX
→ EVENTO
→ WATCHDOG / LISTENER
→ EVENT LEDGER
→ RECONCILIACIÓN
→ CLASIFICACIÓN
→ ACTUALIZACIÓN ERP / BANDEJA
→ ALERTA / TASK / ACCIÓN POSTERIOR
```

### Reglas del Listener

El Watchdog / Listener:

- será pasivo respecto de Box;
- no moverá, eliminará, renombrará ni sobrescribirá documentos;
- no convertirá un evento aislado en verdad definitiva sin validación suficiente;
- deberá ser idempotente;
- deberá tolerar eventos duplicados;
- deberá agrupar o aplicar *debounce* cuando múltiples eventos pertenezcan a una misma operación;
- deberá poder reconciliar el estado observado con el estado real del directorio;
- deberá registrar timestamps, ruta, tipo de evento y contexto suficiente;
- deberá poder disparar clasificación, indexación, actualización documental, alertas o TASK cuando corresponda.

### Estabilidad del archivo

Cuando un archivo se esté copiando o sincronizando, el Listener no deberá procesarlo como documento definitivo hasta que exista evidencia suficiente de que la escritura ha finalizado.

Podrán utilizarse, según implementación:

- estabilidad de tamaño;
- estabilidad temporal;
- reintentos;
- hash;
- locks;
- señales del conector;
- otros mecanismos equivalentes.

### Reconciliación

El Listener no será la única fuente de verdad del estado físico de Box.

Deberá existir capacidad de:

```text
EVENTOS
+
ESCANEO / RECONCILIACIÓN PERIÓDICA
=
ESTADO DOCUMENTAL CONFIABLE
```

Esto permite recuperar:

- eventos perdidos;
- cambios ocurridos con el ERP detenido;
- modificaciones realizadas desde otros equipos;
- inconsistencias de sincronización;
- renombrados o movimientos difíciles de inferir únicamente mediante eventos.

### Relación con Bandeja Documental

Un cambio detectado en Box podrá:

- crear o actualizar una entrada documental;
- refrescar metadata;
- recalcular hash cuando proceda;
- ejecutar clasificación;
- actualizar la relación con expediente;
- generar alerta;
- crear una TASK;
- marcar una referencia como movida o eliminada;
- provocar una reconciliación.

El Listener no debe crear ruido operativo innecesario. Los eventos deberán traducirse a cambios semánticos útiles para el ERP.

---

## XVI. WATCHDOG DE CARPETAS LOCALES DE INGESTIÓN

El mismo patrón podrá utilizarse para carpetas locales autorizadas, incluyendo Downloads cuando se configure como origen de ingestión.

Ejemplo:

```text
DOWNLOADS
→ WATCHDOG LOCAL
→ BANDEJA DOCUMENTAL
→ CLASIFICACIÓN
→ EXPEDIENTE
→ COPIA CONTROLADA A BOX
```

Los Watchdogs de Box y de carpetas locales deberán compartir, cuando resulte razonable, contratos comunes de:

- eventos;
- deduplicación;
- estabilidad;
- trazabilidad;
- clasificación;
- errores;
- reintentos;
- observabilidad.

---

## XVII. SEGURIDAD Y PERMISOS

La capacidad de copia ERP → Box deberá utilizar el mínimo permiso necesario.

La infraestructura deberá evitar que una capacidad de `create/upload` se transforme accidentalmente en capacidad indiscriminada de:

- delete;
- move;
- rename;
- overwrite;
- reorganize.

Cuando la API o integración no permita granularidad suficiente, la aplicación deberá imponer esas restricciones en su capa de servicio y tests.

---

## XVIII. ARQUITECTURA

La operación documental deberá respetar:

```text
Frontend
   ↓
Application / Document Service
   ↓
Box Connector / Storage Adapter
   ↓
Box
```

Queda prohibido:

- lógica Box directa en Flet;
- llamadas de escritura desde vistas;
- SQL directo desde frontend;
- duplicación de reglas de copia en múltiples capas.

Una única capa de servicio gobernará las operaciones documentales.

La arquitectura podrá incorporar servicios especializados reutilizables como:

```text
DocumentWatchService
DocumentIngestionService
DocumentTransferService
DocumentReconciliationService
BoxConnector / StorageAdapter
```

Los nombres concretos son orientativos; el contrato de responsabilidades es lo relevante.

---

## XIX. RELACIÓN CON KNOWLEDGE

Knowledge podrá consumir referencias, copias técnicas o contenido autorizado procedente del sistema documental.

`KNOW-003` no convierte Knowledge en propietario del documento.

Box y el sistema documental conservan su responsabilidad documental.

Knowledge conserva:

- índices;
- relaciones;
- fragmentos;
- embeddings cuando proceda;
- metadata;
- trazabilidad;
- conocimiento derivado.

---

## XX. EFECTO SOBRE DECISIONES CANÓNICAS

Tras la aprobación:

- `DOC-001` → **MODIFICADA PARCIALMENTE**
- `DOC-002` → **VIGENTE**
- `DOC-003` → **VIGENTE**

La divergencia documental `011 ↔ 016` queda resuelta.

La parte de `016` que permite copia documental queda validada **solo dentro del contrato controlado definido por DOC-003**.

`DOC-003` incluye además como objetivo funcional la observación continua mediante Watchdog / Listener gobernado de Box y de carpetas locales de ingestión, con reconciliación e idempotencia.

---

## XXI. PRINCIPIO FINAL

La regla canónica pasa a ser:

```text
BOX NO ES SOLO LECTURA

ERP ↔ BOX
PUEDE COPIAR DE FORMA CONTROLADA Y TRAZABLE

PERO

ERP NO PUEDE MODIFICAR DE FORMA LIBRE
LOS OBJETOS EXISTENTES EN BOX
```

Objetivo:

> **FLUJO DOCUMENTAL FUNCIONAL SIN SACRIFICAR INTEGRIDAD, TRAZABILIDAD NI CONTROL.**

---

**ESTADO FINAL:** APROBADA POR DIRECCIÓN
