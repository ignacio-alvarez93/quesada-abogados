# 📄 RESOLUCIÓN 004

## Arquitectura de frontend y uso de Flet

### ERP Quesada Abogados

**Fecha:** 25/04/2026
**Estado:** APROBADA
**Autoridad:** Dirección del Proyecto

---

## 1. Objeto de la resolución

La presente resolución define la tecnología, arquitectura y criterios de desarrollo del frontend del ERP.

El frontend será la interfaz operativa del despacho y deberá reflejar el flujo real de trabajo definido en resoluciones anteriores.

---

## 2. Tecnología de frontend

Se establece como tecnología oficial:

* Flet

Referencias oficiales:

* https://flet.dev/
* https://flet.dev/docs/reference/

---

## 3. Principio de diseño del frontend

```text id="flet1"
El frontend no es decorativo,
es una herramienta de trabajo.
```

El sistema deberá priorizar:

* claridad visual
* rapidez de uso
* reducción de errores humanos
* acceso directo a la información

---

## 4. Arquitectura del frontend

El frontend se estructurará en:

```text id="flet2"
frontend/
│
├── views/        # Pantallas principales
├── components/   # Elementos reutilizables
└── layouts/      # Estructuras de interfaz (opcional)
```

---

## 5. Separación obligatoria

Se establece como norma:

* El frontend NO contendrá lógica de negocio
* El frontend NO accederá directamente a la base de datos
* El frontend solo interactuará con el backend

---

## 6. Estructura de vistas

El ERP deberá organizarse en vistas alineadas con el negocio:

```text id="flet3"
Clientes
Expedientes
Documentación
Escaneado
Presentaciones
Cobros
Seguimiento
```

Cada vista será independiente.

---

## 7. Componentes reutilizables

Se establece el uso obligatorio de componentes reutilizables.

Ejemplos:

* tablas de datos
* formularios
* botones de acción
* modales
* tarjetas de información
* listas de expedientes

---

## 8. Widgets personalizados

Se permite y se fomenta:

👉 creación de widgets personalizados en Flet

Esto permitirá:

* adaptar la interfaz al flujo del despacho
* reutilizar lógica visual
* mejorar consistencia
* acelerar desarrollo

Ejemplos futuros:

* widget de estado de expediente
* widget de cola de escaneado
* widget de control de cobros
* widget de timeline de expediente

---

## 9. Principios de diseño

El frontend deberá cumplir:

### 9.1. Funcionalidad sobre estética

* primero funciona
* después se mejora visualmente

---

### 9.2. Reducción de clics

* acceso rápido a acciones
* evitar navegación innecesaria

---

### 9.3. Visibilidad del estado

El usuario deberá ver claramente:

* estado del expediente
* tareas pendientes
* incidencias
* prioridades

---

### 9.4. Tolerancia a errores

* validaciones en formularios
* mensajes claros
* prevención de errores críticos

---

## 10. Escalabilidad del frontend

El sistema deberá permitir:

* añadir nuevas vistas
* modificar vistas existentes
* sustituir completamente Flet en el futuro

👉 Esto es clave: el frontend NO debe condicionar el backend

---

## 11. Ejecución del sistema

El ERP deberá poder ejecutarse:

* en local
* en distintos ordenadores
* sin dependencias de rutas absolutas

(En coherencia con Resolución 001)

---

## 12. Consecuencia para el desarrollo

A partir de esta resolución:

* toda interfaz se desarrollará en Flet
* toda pantalla será una vista
* todo elemento reutilizable será un componente
* se podrán crear widgets personalizados

---

## 13. Ubicación del documento

```text id="flet4"
docs/resolutions/004_frontend_flet.md
```

---

## 14. Commit recomendado

```text id="flet5"
Add resolution 004 frontend architecture Flet
```

---

## 🔒 Cierre

Queda aprobado Flet como tecnología oficial de frontend del ERP Quesada Abogados.

El sistema se desarrollará con un enfoque funcional, modular y escalable, priorizando la operativa real del despacho sobre cualquier criterio estético.
