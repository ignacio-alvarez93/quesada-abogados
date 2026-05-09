# 📄 RESOLUCIÓN 013

## Estructura del repositorio y separación de capas operativas

### ERP Quesada Abogados

**Fecha:** 09/05/2026
**Estado:** APROBADA
**Autoridad:** Dirección del Proyecto

---

## 1. Objeto

La presente resolución aprueba la nueva estructura del repositorio del ERP Quesada Abogados.

El objetivo es garantizar:

```text
orden,
mantenibilidad,
separación de responsabilidades,
control técnico,
y crecimiento modular del sistema.
```

---

## 2. Principio general

El repositorio no será tratado como un conjunto de scripts aislados.

Será tratado como:

```text
plataforma ERP modular empresarial
```

Por tanto, cada archivo deberá ubicarse según su función real.

---

## 3. Estructura principal aprobada

```text
quesada-abogados/
│
├── app/
├── backend/
├── database/
├── frontend/
├── docs/
├── scripts/
├── tools/
├── requirements.txt
├── README.md
└── .gitignore
```

---

## 4. Carpeta app/

La carpeta `app/` contendrá únicamente:

```text
puntos de entrada principales
lanzadores operativos esenciales
arranque del ERP
```

No deberá utilizarse como almacén de scripts temporales.

---

## 5. Carpeta backend/

La carpeta `backend/` contendrá:

```text
servicios
lógica de negocio
validadores
procesos internos
```

El frontend no accederá directamente a base de datos, sino a través del backend.

---

## 6. Carpeta database/

La carpeta `database/` contendrá:

```text
conexión SQLite
schemas SQL
migraciones controladas
datos maestros
seeds estructurales
```

No deberá subirse la base de datos local operativa si contiene datos reales.

---

## 7. Carpeta frontend/

La carpeta `frontend/` contendrá:

```text
views
components
layouts
```

La interfaz se organizará conforme a la arquitectura Flet aprobada.

---

## 8. Carpeta docs/

La carpeta `docs/` contendrá:

```text
resoluciones
documentación técnica
criterios de desarrollo
informes aprobados
```

Las resoluciones serán fuente normativa del proyecto.

---

## 9. Carpeta scripts/

La carpeta `scripts/` queda aprobada como ubicación de scripts auxiliares técnicos.

Estructura:

```text
scripts/
├── automation/
├── diagnostics/
├── fixes/
├── maintenance/
├── patches/
├── seeds/
└── tests/
```

Uso:

```text
diagnóstico
parches
correcciones históricas
mantenimiento
cargas de prueba
tests auxiliares
automatizaciones no principales
```

---

## 10. Carpeta tools/

La carpeta `tools/` queda reservada para herramientas operativas reales del despacho.

Estructura inicial:

```text
tools/
├── admin/
├── automation/
└── imports/
```

No todo script será una herramienta.
Solo pasarán a `tools/` aquellos componentes que tengan uso operativo estable.

---

## 11. Criterio Mercurio

El archivo:

```text
app/run_presentacion_asistida.py
```

se mantiene temporalmente en `app/` por considerarse lanzador operativo crítico.

No se moverá hasta revisar imports, rutas, dependencias y modo oficial de ejecución.

El archivo duplicado:

```text
app/run_presentacion_asistida_.py
```

queda eliminado por estar huérfano y no referenciado.

---

## 12. Relación con Git

Esta estructura se desarrollará mediante ramas:

```text
main
develop
feature/*
hotfix/*
```

Los cambios estructurales deberán realizarse en ramas `feature/*`.

---

## 13. Consecuencia inmediata

A partir de esta resolución:

```text
app/ no será usado como carpeta de scripts temporales
scripts/ centralizará scripts técnicos auxiliares
tools/ centralizará herramientas operativas consolidadas
docs/ mantendrá la fuente normativa
backend/ y frontend/ mantendrán separación estricta
```

---

## 14. Ubicación del documento

```text
docs/resolutions/013_estructura_repositorio.md
```

---

## 15. Commit recomendado

```text
Add resolution 013 repository structure
```

---

# 🔒 Cierre

Queda aprobada la nueva estructura del repositorio del ERP Quesada Abogados.

Todo desarrollo futuro deberá respetar esta organización como base técnica del proyecto.
