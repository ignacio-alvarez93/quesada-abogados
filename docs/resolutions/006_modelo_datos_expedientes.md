# 📄 RESOLUCIÓN 006

## Modelo de datos — Módulo Expedientes

### ERP Quesada Abogados

**Fecha:** 25/04/2026
**Estado:** APROBADA
**Autoridad:** Dirección del Proyecto

---

## 1. Objeto de la resolución

La presente resolución define el modelo funcional inicial del módulo **Expedientes** del ERP Quesada Abogados.

El expediente será la unidad principal de trabajo jurídico-administrativo del despacho.

---

## 2. Concepto de expediente

A efectos del ERP, se considerará expediente todo asunto jurídico, administrativo o judicial vinculado a un cliente.

Un expediente podrá corresponder a:

* autorización de residencia;
* renovación;
* arraigo;
* reagrupación familiar;
* nacionalidad;
* recurso administrativo;
* procedimiento judicial;
* subsanación;
* cita posterior;
* visado;
* cualquier actuación de extranjería.

---

## 3. Relación con clientes

Todo expediente deberá estar vinculado a un cliente principal.

Un cliente podrá tener uno o varios expedientes.

Un expediente podrá tener también personas relacionadas, tales como:

```text
Cónyuge
Hijo menor
Padre
Madre
Familiar comunitario
Empresa
Representante
Otro interesado
```

---

## 4. Campos mínimos del expediente

El módulo Expedientes deberá contemplar, como mínimo, los siguientes campos:

```text
Número interno de expediente
Cliente principal
Tipo de expediente
Subtipo de autorización
Procedimiento
Fecha de apertura
Fecha de cierre
Responsable interno
Estado documental
Estado administrativo
Fecha de presentación
Número de registro
Órgano de presentación
Provincia
Observaciones
Prioridad
Fecha de última actualización
Activo / archivado
```

---

## 5. Tipología de expedientes

El sistema deberá permitir clasificar expedientes según listados oficiales y categorías internas del despacho.

Categorías iniciales:

```text
Residencia inicial
Renovación
Arraigo
Reagrupación familiar
Residencia de familiar de ciudadano de la Unión
Nacionalidad
Estancia por estudios
Autorización de trabajo
Modificación
Larga duración
Recurso administrativo
Recurso contencioso-administrativo
Juicio
Subsanación
Cita de huellas
Visado
Otro
```

La lista deberá ser ampliable.

---

## 6. Catálogo oficial de autorizaciones

El ERP deberá permitir incorporar, mantener y ampliar un catálogo de autorizaciones basado en fuentes oficiales.

El sistema deberá poder registrar, entre otras:

```text
Autorización de estancia por estudios
Autorización de residencia no lucrativa
Reagrupación familiar
Residencia y trabajo por cuenta ajena
Residencia y trabajo por cuenta propia
Arraigo social
Arraigo familiar
Arraigo sociolaboral
Arraigo socioformativo
Arraigo de segunda oportunidad
Razones humanitarias
Residencia de menores
Larga duración nacional
Larga duración UE
Tarjeta de familiar de ciudadano de la Unión
Certificado de registro de ciudadano de la Unión
Profesionales altamente cualificados
Investigadores
Traslado intraempresarial
Teletrabajadores internacionales
Emprendedores
Familiares de autorizaciones UGE
```

Este catálogo no deberá estar cerrado en código. Deberá poder ampliarse.

---

## 7. Estado documental del expediente

Antes de la presentación, el expediente podrá encontrarse en los siguientes estados documentales:

```text
Pendiente de escanear
Incompleto
Completo
```

Definición:

* **Pendiente de escanear:** existe carpeta física o documentación recibida, pero no está digitalizada.
* **Incompleto:** el expediente tiene documentación, pero falta información o documentos necesarios.
* **Completo:** el expediente tiene documentación suficiente para preparar o realizar la presentación.

---

## 8. Estado administrativo del expediente

Una vez presentado, el expediente podrá encontrarse en los siguientes estados administrativos:

```text
Presentado
Admitido
Pendiente en trámite
En trámite requerido
Resuelto favorable
Resuelto denegado
Archivado
Inadmitido
```

Definición:

* **Presentado:** se ha realizado la presentación telemática o presencial.
* **Admitido:** la Administración ha admitido el expediente.
* **Pendiente en trámite:** el expediente continúa en estudio.
* **En trámite requerido:** existe requerimiento o petición de documentación.
* **Resuelto favorable:** el expediente ha sido concedido.
* **Resuelto denegado:** el expediente ha sido denegado.
* **Archivado:** el expediente ha sido archivado.
* **Inadmitido:** el expediente no ha sido admitido y concluye salvo nueva estrategia.

---

## 9. Flujo principal de estados

El flujo ordinario será:

```text
Pendiente de escanear
↓
Incompleto
↓
Completo
↓
Presentado
↓
Admitido
↓
Pendiente en trámite
↓
En trámite requerido / Resuelto favorable / Resuelto denegado / Archivado
```

Si el expediente resulta inadmitido:

```text
Presentado
↓
Inadmitido
↓
Concluido
```

---

## 10. Expediente resuelto favorable

Cuando un expediente sea **resuelto favorable**, el sistema deberá permitir abrir o vincular una fase posterior.

Fases posteriores posibles:

```text
Cita de toma de huellas
Solicitud de visado
Recogida de tarjeta
Seguimiento posterior
Nuevo expediente derivado
```

---

## 11. Requerimientos

Si el expediente entra en estado **En trámite requerido**, el sistema deberá permitir registrar:

```text
Fecha del requerimiento
Fecha límite para contestar
Documentación requerida
Responsable de respuesta
Estado de respuesta
Fecha de presentación de la respuesta
Observaciones
```

---

## 12. Datos de presentación

Cuando un expediente sea presentado, deberán registrarse:

```text
Fecha de presentación
Medio de presentación
Número de registro
Justificante
Órgano administrativo
Provincia
Usuario responsable
Observaciones de presentación
```

---

## 13. Datos de resolución

Cuando exista resolución, deberán registrarse:

```text
Fecha de resolución
Sentido de la resolución
Fecha de notificación
Documento de resolución
Resultado
Observaciones
```

---

## 14. Trazabilidad

Todo expediente deberá permitir conocer:

```text
Quién lo creó
Cuándo se creó
Quién lo modificó
Cuándo se modificó
Estado anterior
Estado nuevo
Observaciones del cambio
```

---

## 15. Principio de diseño

El expediente no será solo una ficha.

El expediente será un flujo vivo compuesto por:

```text
Cliente
Tipo de autorización
Documentación
Estado documental
Estado administrativo
Presentación
Requerimientos
Resolución
Fase posterior
Cobros
Historial
```

---

## 16. Consecuencia para la base de datos

El modelo de datos deberá contemplar, al menos, las siguientes entidades futuras:

```text
expedientes
tipos_expediente
autorizaciones
expediente_personas
expediente_estados
expediente_requerimientos
expediente_presentaciones
expediente_resoluciones
expediente_historial
clientes
cobros
```

---

## 17. Prioridad inicial

En la primera fase se desarrollará:

```text
Alta de expediente
Vinculación con cliente
Tipo de expediente
Estado documental
Estado administrativo
Listado de expedientes
Búsqueda de expedientes
Cambio de estado
Observaciones
```

Posteriormente se ampliará con:

```text
Catálogo completo de autorizaciones
Requerimientos
Presentaciones
Resoluciones
Citas de huellas
Visados
Historial avanzado
Automatización
```

---

## 18. Ubicación del documento

```text
docs/resolutions/006_modelo_datos_expedientes.md
```

---

## 19. Commit recomendado

```text
Add resolution 006 case file data model
```

---

## 🔒 Cierre

Queda aprobado el modelo funcional inicial del módulo Expedientes.

Todo desarrollo posterior deberá respetar este flujo como base mínima ampliable.

El expediente será el eje operativo del despacho junto con Clientes y Cobros.
