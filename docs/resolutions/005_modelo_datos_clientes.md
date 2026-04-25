# 📄 RESOLUCIÓN 005

## Modelo de datos — Módulo Clientes

### ERP Quesada Abogados

**Fecha:** 25/04/2026
**Estado:** APROBADA
**Autoridad:** Dirección del Proyecto

---

## 1. Objeto de la resolución

La presente resolución define el modelo funcional inicial del módulo **Clientes** del ERP Quesada Abogados.

Este módulo será uno de los pilares principales del sistema junto con Expedientes y Cobros.

---

## 2. Concepto de cliente

A efectos del ERP, se considerará cliente a toda persona física o jurídica que:

* solicite asesoramiento;
* contrate servicios del despacho;
* tenga uno o varios expedientes;
* esté vinculada a una actuación de extranjería;
* deba constar en formularios, escritos o documentos administrativos.

---

## 3. Datos mínimos obligatorios del cliente

El módulo Clientes deberá contemplar, como mínimo, los siguientes campos:

```text
Nombre
Primer apellido
Segundo apellido
Nacionalidad
NIE
Pasaporte
DNI
Fecha de nacimiento
Localidad de nacimiento
País de nacimiento
Nombre del padre
Nombre de la madre
Estado civil
Teléfono
Email
Domicilio en España
Localidad
Código postal
Provincia
Número
Piso
Observaciones
```

---

## 4. Datos internos del despacho

Además de los datos personales, cada cliente deberá permitir registrar información interna:

```text
Estado del cliente
Fecha de alta
Origen del cliente
Responsable interno
Observaciones internas
Fecha de última actualización
Activo / archivado
```

Estados iniciales posibles:

```text
Asesoramiento inicial
Pendiente de documentación
Documentación entregada
Expediente abierto
En tramitación
Archivado
```

---

## 5. Relación con expedientes

Un cliente podrá tener:

```text
Uno o varios expedientes
```

Cada expediente deberá estar vinculado, como mínimo, a un cliente principal.

---

## 6. Contactos vinculados al cliente

Cada cliente podrá tener contactos relacionados.

Estos contactos podrán ser:

```text
Hijo menor
Padre
Madre
Cónyuge
Pareja
Hermano/a
Representante
Empresa
Otro contacto relacionado
```

---

## 7. Clientes menores de edad

El sistema deberá permitir registrar menores de edad vinculados a un cliente principal.

Ejemplos:

```text
Padre cliente principal → hijo menor vinculado
Madre cliente principal → hijo menor vinculado
Menor con expediente propio → representante vinculado
```

---

## 8. Empresas vinculadas

El sistema deberá permitir que un cliente esté vinculado a una o varias empresas.

Las empresas podrán ser relevantes en procedimientos como:

```text
Arraigo social
Arraigo laboral
Autorizaciones de trabajo
Renovaciones
Contrataciones
Reagrupaciones con medios económicos
```

La relación cliente-empresa deberá ser flexible.

---

## 9. Tipos de relación cliente-contacto

Las relaciones deberán ser configurables y no cerradas.

Ejemplos:

```text
Cliente → hijo menor
Cliente → padre
Cliente → madre
Cliente → cónyuge
Cliente → empresa empleadora
Cliente → representante
Cliente → familiar comunitario
```

---

## 10. Principio de diseño

El cliente no será una ficha aislada.

El cliente será el centro de una red de información formada por:

```text
Datos personales
Expedientes
Cobros
Contactos familiares
Empresas
Documentación
Historial de actuaciones
```

---

## 11. Consecuencia para la base de datos

El modelo de datos deberá contemplar, al menos, las siguientes entidades futuras:

```text
clientes
cliente_contactos
empresas
cliente_empresas
expedientes
cobros
```

La relación entre clientes y contactos deberá permitir relaciones múltiples.

La relación entre clientes y empresas también deberá permitir múltiples vinculaciones.

---

## 12. Prioridad inicial

En la primera fase se desarrollará:

```text
Ficha básica de cliente
Alta manual de cliente
Listado de clientes
Búsqueda de cliente
Vinculación futura con expedientes
```

Posteriormente se ampliará con:

```text
Contactos vinculados
Empresas vinculadas
Importación desde HubSpot
Historial completo
```

---

## 13. Criterio rector

El módulo Clientes deberá diseñarse para evitar duplicidades, pérdida de información y datos incompletos.

El sistema deberá permitir identificar claramente a una persona aunque tenga varios documentos, varios expedientes o varias relaciones familiares.

---

## 14. Ubicación del documento

```text
docs/resolutions/005_modelo_datos_clientes.md
```

---

## 15. Commit recomendado

```text
Add resolution 005 client data model
```

---

## 🔒 Cierre

Queda aprobado el modelo funcional inicial del módulo Clientes.

Todo desarrollo posterior del ERP deberá respetar esta estructura como base mínima ampliable.
