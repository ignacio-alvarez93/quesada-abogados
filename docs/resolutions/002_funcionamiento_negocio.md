# 📄 RESOLUCIÓN 002

## Funcionamiento operativo del negocio

### ERP Quesada Abogados

**Fecha:** 25/04/2026
**Estado:** APROBADA
**Autoridad:** Dirección del Proyecto

---

## 1. Objeto de la resolución

La presente resolución define el funcionamiento operativo real de **Quesada Abogados**, despacho especializado en Derecho de Extranjería.

Este documento servirá como base funcional para el diseño del ERP interno.

El sistema no deberá construirse únicamente como una aplicación informática, sino como una representación ordenada del funcionamiento diario del despacho.

---

## 2. Naturaleza del despacho

Quesada Abogados es un despacho de abogados especializado en materia de extranjería.

El despacho presta asesoramiento, tramitación administrativa, presentación telemática de expedientes, interposición de recursos y asistencia en procedimientos judiciales relacionados con extranjería.

El ERP deberá adaptarse a esta realidad profesional.

---

## 3. Flujo general del cliente

El ciclo ordinario de trabajo comienza cuando una persona acude al despacho.

El flujo general será el siguiente:

1. Entrada del cliente en el despacho.
2. Asesoramiento inicial en materia de extranjería.
3. Indicación de documentación necesaria.
4. El cliente recopila la documentación.
5. El cliente regresa al despacho para iniciar expediente.
6. Se recibe documentación física, por correo electrónico u otros medios.
7. Se firma la hoja de encargo profesional.
8. Se generan honorarios.
9. Se abre expediente.
10. Se escanea documentación.
11. Se prepara el expediente para presentación.
12. Se realiza presentación telemática, recurso o actuación judicial.
13. Se hace seguimiento hasta resolución o cierre.

---

## 4. Estados principales del cliente

A efectos del ERP, un cliente podrá encontrarse en distintos estados:

```text
Asesoramiento inicial
Pendiente de documentación
Documentación entregada
Expediente abierto
En tramitación
Presentado
Pendiente de resolución
Finalizado
Archivado
```

Estos estados deberán poder modificarse con el tiempo.

---

## 5. Inicio del expediente

Un expediente se considerará iniciado cuando el cliente entrega documentación suficiente y se activa el trabajo jurídico-administrativo del despacho.

El inicio del expediente implica:

* identificación del cliente;
* apertura de expediente;
* recepción de documentación;
* firma de hoja de encargo;
* generación de honorarios;
* asignación de responsable;
* preparación para escaneado y presentación.

---

## 6. Flujo documental inicial

Cuando el cliente deja documentación en el despacho, se seguirá el siguiente flujo obligatorio:

### 6.1. Escaneo inicial de documentos sensibles

Se escanearán de forma prioritaria:

* pasaporte;
* NIE;
* DNI;
* documentos identificativos;
* resoluciones administrativas;
* documentación sensible o esencial.

---

### 6.2. Apertura de carpeta física

Se abrirá una carpeta física del expediente.

En dicha carpeta se podrán incluir:

* notas internas;
* documentación original o copia;
* hoja de encargo;
* justificantes;
* instrucciones;
* incidencias;
* observaciones del abogado o personal administrativo.

---

### 6.3. Recepción de documentación

La documentación podrá recibirse por distintas vías:

```text
Presencial en papel
Correo electrónico
WhatsApp u otros medios digitales
Aportación posterior del cliente
Documentación ya existente en el despacho
```

El ERP deberá permitir registrar la existencia de documentos aunque inicialmente no estén digitalizados.

---

### 6.4. Firma de hoja de encargo

La firma de la hoja de encargo será un hito esencial del expediente.

Deberá quedar constancia de:

* fecha de firma;
* tipo de procedimiento;
* honorarios pactados;
* forma de pago;
* observaciones económicas;
* vinculación con cliente y expediente.

---

## 7. Cola de escaneado

Una vez abierta la carpeta física y recibida la documentación, el expediente pasará a la cola de escaneado.

La cola de escaneado permitirá controlar:

* expedientes pendientes de digitalizar;
* expedientes parcialmente escaneados;
* expedientes completamente escaneados;
* incidencias documentales;
* prioridad de escaneado.

Estados mínimos de escaneado:

```text
Pendiente de escaneado
En escaneado
Escaneado parcial
Escaneado completo
Incidencia documental
```

---

## 8. Paso al encargado de presentación

Cuando la carpeta haya sido escaneada, se trasladará al responsable encargado de la presentación.

El responsable deberá poder ver:

* cliente;
* tipo de expediente;
* documentación recibida;
* documentación pendiente;
* estado de escaneado;
* observaciones internas;
* fecha prevista de presentación;
* prioridad.

Estados mínimos de presentación:

```text
Pendiente de preparar
En preparación
Listo para presentar
Presentado
Subsanación requerida
Recurso necesario
Finalizado
```

---

## 9. Tipos de actuaciones del despacho

El ERP deberá contemplar, como mínimo, los siguientes tipos de actuaciones:

```text
Autorizaciones de residencia
Renovaciones
Arraigo social
Arraigo familiar
Arraigo laboral
Residencia por circunstancias excepcionales
Reagrupación familiar
Tarjeta de familiar comunitario
Nacionalidad española
Asilo y protección internacional
Recursos administrativos
Recursos contencioso-administrativos
Juicios
Subsanaciones
Aportación de documentación
Consultas jurídicas
```

Esta lista será ampliable.

---

## 10. Relación entre cliente, expediente y cobro

El sistema deberá respetar la siguiente lógica:

* Un cliente puede tener uno o varios expedientes.
* Un expediente pertenece a un cliente principal.
* Un expediente puede tener uno o varios cobros.
* Un cobro puede estar vinculado a un expediente.
* Un cliente puede tener historial económico global.

---

## 11. Principios funcionales del ERP

El ERP deberá permitir:

* saber en qué estado está cada cliente;
* saber qué documentación falta;
* saber quién gestiona cada expediente;
* saber qué expedientes están pendientes de escanear;
* saber qué expedientes están pendientes de presentar;
* saber qué expedientes ya han sido presentados;
* saber qué cobros están pendientes;
* consultar el historial de cada cliente;
* evitar pérdida de documentación;
* evitar expedientes sin seguimiento.

---

## 12. Prioridad operativa

El sistema deberá priorizar el control del despacho sobre la estética de la aplicación.

El primer objetivo no será crear una pantalla bonita, sino asegurar que ningún expediente quede sin control.

---

## 13. Consecuencia para el desarrollo

A partir de esta resolución, el ERP deberá construirse alrededor de los siguientes módulos iniciales:

```text
Clientes
Expedientes
Documentación
Escaneado
Presentaciones
Cobros
Seguimiento
```

Estos módulos serán la base funcional del sistema.

---

## 14. Ubicación del documento

Este archivo deberá guardarse en:

```text
docs/resolutions/002_funcionamiento_negocio.md
```

---

## 15. Commit recomendado

Una vez añadido este documento al repositorio, se recomienda realizar el siguiente commit:

```text
Add resolution 002 business workflow
```

---

## 🔒 Cierre

Queda aprobada esta resolución como base funcional del ERP Quesada Abogados.

Todo desarrollo posterior deberá respetar el funcionamiento operativo descrito en este documento.

El sistema deberá adaptarse al despacho, no el despacho al sistema.
