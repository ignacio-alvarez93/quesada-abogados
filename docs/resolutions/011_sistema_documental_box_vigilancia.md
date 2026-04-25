# 📄 RESOLUCIÓN 011

## Sistema documental y vigilancia de Box Drive

### ERP Quesada Abogados

**Fecha:** 25/04/2026
**Estado:** APROBADA
**Autoridad:** Dirección del Proyecto

---

## 1. Objeto de la resolución

La presente resolución define la relación entre el ERP y el sistema de gestión documental del despacho basado en Box Drive.

El objetivo es:

```text
Monitorizar la actividad documental
sin comprometer la seguridad ni la integridad de los datos
```

---

## 2. Sistema documental actual

El despacho utiliza:

```text
Box Drive (instalado en escritorio)
```

Como sistema principal de almacenamiento de:

* expedientes
* documentos escaneados
* justificantes
* resoluciones
* documentación sensible de clientes

---

## 3. Principio fundamental

Se establece como norma absoluta:

```text
El ERP NO manipula Box
El ERP SOLO observa Box
```

---

## 4. Prohibiciones absolutas

Queda estrictamente prohibido que el ERP:

```text
Mueva archivos
Modifique archivos
Elimine archivos
Renombre archivos
Reorganice carpetas
Escriba dentro de Box
Sincronice de forma activa
```

---

## 5. Nivel de acceso permitido

El ERP solo podrá tener:

```text
Acceso de lectura
```

Y únicamente para:

```text
Detección de cambios
Listado de archivos
Verificación de existencia
```

---

## 6. Módulo de vigilancia de Box

Se aprueba la creación de un módulo:

```text
Vigilancia de Box
```

Funciones:

```text
Detectar nuevas carpetas
Detectar nuevos archivos
Detectar cambios en estructura
Detectar eliminación de archivos
Detectar actividad reciente
```

---

## 7. Objetivos del módulo

El sistema deberá permitir:

```text
Saber qué expedientes tienen carpeta
Detectar documentos nuevos
Verificar que se ha escaneado documentación
Controlar actividad documental
Evitar pérdidas de información
```

---

## 8. Relación con expedientes

El ERP deberá poder vincular:

```text
Cliente
Expediente
Ruta de carpeta en Box
```

Y permitir comprobar:

```text
Si existe carpeta
Si tiene documentos
Última actualización
Número de archivos
```

---

## 9. Justificantes y documentos clave

El sistema deberá detectar especialmente:

```text
Justificantes de presentación
Resoluciones
Requerimientos
Documentos escaneados
```

---

## 10. Alertas documentales

El sistema deberá generar alertas como:

```text
Expediente sin carpeta en Box
Expediente sin documentos
Carpeta sin actividad reciente
Falta de justificante de presentación
Documentación incompleta
```

---

## 11. Seguridad

Se establece como prioridad absoluta:

```text
La seguridad de Box está por encima del ERP
```

Por tanto:

* el ERP no podrá tener permisos de escritura
* no se almacenarán credenciales inseguras
* no se automatizarán acciones sobre archivos
* no se realizarán procesos que puedan corromper datos

---

## 12. Riesgos controlados

El sistema deberá evitar:

```text
Acceso indebido a documentación sensible
Pérdida de archivos
Modificación accidental
Errores de sincronización
Dependencia del ERP para acceder a documentos
```

---

## 13. Arquitectura técnica

El módulo deberá implementarse mediante:

```text
Lectura de sistema de archivos (ruta local sincronizada)
Detección de cambios
Registro en base de datos
```

Nunca mediante:

```text
Manipulación directa de archivos
Automatización agresiva
```

---

## 14. Separación de sistemas

Se establece claramente:

```text
Box → almacenamiento documental
ERP → control y vigilancia
```

El ERP no sustituye ni interfiere con Box.

---

## 15. Evolución futura

En fases futuras se podrá:

```text
Integrar API oficial de Box
Mejorar detección de eventos
Automatizar notificaciones
Generar panel documental
```

Siempre respetando el principio de no intervención.

---

## 16. Consecuencia para el desarrollo

A partir de esta resolución:

* se crea módulo de vigilancia documental
* se vinculan expedientes con rutas de Box
* se desarrollan alertas documentales
* se registra actividad documental

---

## 17. Criterio rector

El sistema deberá cumplir:

```text
Ver todo lo que pasa en Box
Sin tocar absolutamente nada en Box
```

---

## 18. Ubicación del documento

```text
docs/resolutions/011_sistema_documental_box_vigilancia.md
```

---

## 19. Commit recomendado

```text
Add resolution 011 box document monitoring system
```

---

## 🔒 Cierre

Queda aprobado el modelo de integración documental con Box Drive.

El ERP actuará exclusivamente como sistema de vigilancia, garantizando el control documental sin comprometer la seguridad ni la integridad de la información del despacho.
