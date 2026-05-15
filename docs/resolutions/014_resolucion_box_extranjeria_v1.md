# RESOLUCIÓN TÉCNICA INTERNA

## ESTRUCTURA DOCUMENTAL BOX – BLOQUE EXTRANJERÍA

### QUESADA ABOGADOS

---

# I. OBJETO

La presente resolución establece las reglas oficiales de clasificación documental, detección de estados y reporting automatizado para expedientes del bloque de EXTRANJERÍA dentro del ecosistema Box/ERP del despacho.

Estas reglas constituyen la fuente normativa para:

* Reporting operativo.
* Clasificación documental automática.
* Detección de estados procesales.
* KPIs y métricas.
* Automatización futura.
* IA documental y reconstrucción de expedientes.

---

# II. PRINCIPIOS GENERALES

## 1. Expediente raíz

Se considera expediente raíz la carpeta principal del cliente dentro de la ruta Box correspondiente.

Ejemplo:

```text
BOX/ARRAIGO SOCIOLABORAL/JUAN PEREZ
```

---

## 2. Justificantes válidos

El justificante oficial válido será exclusivamente documentación compatible con:

```text
justificante_23010047L_
```

o formatos equivalentes oficiales de presentación electrónica.

---

## 3. Exclusión de resguardos

Los documentos tipo:

```text
Resguardo_XXXX.pdf
```

NO constituyen justificante válido de:

* presentación,
* tasa,
* requerimiento,
* subsanación.

Los resguardos se consideran documentos auxiliares o accesos a notificaciones.

---

# III. PRESENTACIÓN DE EXPEDIENTES

## 1. Expediente presentado

Un expediente se considerará PRESENTADO únicamente cuando exista justificante válido:

### A) En carpeta raíz del cliente

o

### B) Dentro de carpetas compatibles:

```text
PARA PRESENTAR
PRESENTAR
PRESENTACION
```

---

## 2. Carpetas excluidas para presentación

NO podrán computar como presentación justificantes ubicados dentro de:

```text
TASA
REQ TASA
REQUERIMIENTO
REQ DOC
APORTAR
SUBSANAR
SUBIR
CONCESION
DENEGACION
ARCHIVO
```

---

# IV. TASAS

## 1. Expediente con tasa

Un expediente tendrá estado TASA cuando exista documentación o carpetas compatibles:

```text
TASA
REQ TASA
ADMISION Y TASA
```

---

## 2. Justificante de tasa válido

La tasa se considerará correctamente abonada cuando exista:

### A) Justificante válido oficial

y además

### B) Evidencia documental compatible con:

```text
TASA PAGADA
JUST_ABONO_TASA
TASA EMPRESA
```

---

## 3. Reglas de validación

La existencia de carpeta TASA sin justificante NO implica tasa válida.

Siempre deberá existir justificante oficial.

---

# V. REQUERIMIENTOS

## 1. Requerimiento detectado

Un expediente tendrá estado REQUERIMIENTO cuando exista justificante válido dentro de carpetas compatibles:

```text
REQ DOC
REQUERIMIENTO
REQ
```

---

## 2. Compatibilidad con tasa

Las carpetas:

```text
REQ DOC Y TASA
```

deberán computar simultáneamente como:

```text
✔ REQUERIMIENTO
✔ TASA
```

---

# VI. SUBSANACIONES

## 1. Subsanación detectada

Un expediente tendrá estado SUBSANACION cuando exista justificante válido dentro de carpetas compatibles:

```text
SUBSANAR
SUBIR
APORTAR
```

---

# VII. RESOLUCIONES

## 1. Concesión

Se considerará resolución favorable cuando existan carpetas compatibles:

```text
CONCESION
RES CONCESION
RESOLUCION DE CONCESION
```

---

## 2. Denegación

Se considerará resolución denegatoria cuando existan carpetas compatibles:

```text
DENEGACION
RES DENEGACION
```

---

## 3. Archivo / desistimiento

Se considerará expediente archivado cuando existan carpetas compatibles:

```text
DESISTIMIENTO
RES DESISTIMIENTO
ARCHIVO
```

---

# VIII. PRIORIDAD NORMATIVA

En caso de conflicto:

```text
DOCUMENTO + CONTEXTO DE RUTA
```

prevalecerá sobre:

```text
nombre aislado del archivo
```

---

# IX. EFECTOS

La presente resolución tendrá efecto inmediato sobre:

* Motor de reporting.
* Box Watch.
* Clasificador documental.
* KPIs internos.
* Futuras automatizaciones ERP.

---
