# 📄 RESOLUCIÓN 001

## Metodología de trabajo y principios técnicos

### ERP Quesada Abogados

**Fecha:** 25/04/2026
**Estado:** APROBADA
**Autoridad:** Dirección del Proyecto

---

## 1. Objeto de la resolución

La presente resolución establece el **modo oficial de trabajo** para el desarrollo del ERP interno de Quesada Abogados.

Este documento constituye el **pilar técnico y organizativo del proyecto**.

---

## 2. Sistema de trabajo

El desarrollo se realizará mediante:

* GitHub como repositorio central
* Desarrollo por módulos
* Entregas estructuradas

Cada entrega de código deberá incluir obligatoriamente:

* Ruta exacta del archivo
* Nombre del archivo
* Código completo
* Explicación breve de su función

El usuario implementará el código manualmente mediante copia y pegado en su entorno local.

---

## 3. Tecnologías aprobadas

```text
Lenguaje: Python
Base de datos: SQLite 3
Frontend: Flet
Control de versiones: GitHub
```

---

## 4. Principios técnicos obligatorios

### 4.1. Prohibición de rutas absolutas

Queda prohibido el uso de rutas locales del sistema como:

```text
C:/Users/...
```

Se utilizarán exclusivamente rutas relativas al proyecto.

---

### 4.2. Prioridad: robustez sobre velocidad

El desarrollo priorizará:

* claridad del código
* control de errores
* validaciones
* organización estructural
* mantenibilidad

La eficiencia será secundaria frente a la fiabilidad.

---

### 4.3. Arquitectura modular y escalable

El sistema deberá permitir:

* añadir nuevos módulos
* modificar módulos existentes
* sustituir el frontend
* ampliar la base de datos
* integrar servicios externos

---

### 4.4. Separación de responsabilidades

Queda estrictamente prohibido mezclar:

* interfaz gráfica
* lógica de negocio
* acceso a base de datos
* configuración

Cada capa deberá estar correctamente separada.

---

## 5. Estructura inicial del proyecto

```text
quesada-abogados/
│
├── app/
│   └── main.py
│
├── backend/
│   ├── services/
│   └── validators/
│
├── database/
│   ├── connection.py
│   └── schema.sql
│
├── frontend/
│   ├── views/
│   └── components/
│
├── docs/
│   └── resolutions/
│
├── requirements.txt
└── README.md
```

---

## 6. Regla de entrega de código

Todo código deberá presentarse en el siguiente formato:

```text
RUTA:
backend/services/example_service.py

CÓDIGO:
[contenido completo del archivo]

FUNCIÓN:
Descripción breve
```

No se aceptarán fragmentos incompletos o sin estructura.

---

## 7. Control de versiones

GitHub será la única fuente válida del proyecto.

Toda modificación deberá subirse mediante commit.

Mensaje recomendado para esta resolución:

```text
Add resolution 001 project methodology
```

---

## 8. Ubicación del documento

Este archivo deberá guardarse en:

```text
docs/resolutions/001_metodologia_trabajo.md
```

---

## 9. Principio rector del proyecto

El objetivo del desarrollo es construir un sistema:

```text
robusto,
ordenado,
mantenible,
escalable,
portable,
y preparado para crecer.
```

---

## 🔒 Cierre

Queda aprobada esta resolución como base obligatoria de trabajo para todo el desarrollo del ERP Quesada Abogados.
