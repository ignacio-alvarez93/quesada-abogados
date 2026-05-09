# 📄 RESOLUCIÓN 012

## Gobierno del código, ramas Git y protección de estabilidad del ERP

### ERP Quesada Abogados

**Fecha:** 09/05/2026
**Estado:** APROBADA
**Autoridad:** Dirección del Proyecto

---

# 1. Objeto de la resolución

La presente resolución establece el modelo oficial de control de versiones, organización de ramas y metodología de integración del código fuente del ERP Quesada Abogados.

El objetivo es garantizar:

```text
estabilidad,
trazabilidad,
seguridad,
aislamiento de cambios,
y crecimiento controlado del sistema.
```

---

# 2. Estado actual del proyecto

Se declara que el ERP ha superado la fase inicial de arranque técnico.

El sistema ya dispone de:

```text
Arquitectura modular
Backend estructurado
Frontend Flet operativo
Servicios independientes
Base de datos segmentada
Automatización inicial
Sistema documental Box Watch
Módulos económicos
Sistema de expedientes
Presentación asistida
```

El proyecto deja de considerarse un repositorio experimental simple.

A partir de este momento:

```text
Toda modificación podrá afectar
a múltiples módulos críticos del sistema.
```

---

# 3. Riesgo identificado

Se identifica como riesgo principal:

```text
Modificar directamente la rama principal (main)
sin aislamiento de cambios.
```

Dado el tamaño y complejidad alcanzados por el ERP, trabajar directamente sobre `main` puede provocar:

```text
Inestabilidad general
Introducción de errores críticos
Pérdida de trazabilidad
Mezcla de funcionalidades
Dificultad de reversión
Conflictos entre desarrollos
Riesgo de corrupción operativa
```

---

# 4. Principio rector

Se establece como norma fundamental:

```text
La rama main representa siempre
la versión estable del ERP.
```

Por tanto:

```text
main NO será utilizada
para desarrollo directo.
```

---

# 5. Arquitectura oficial de ramas

A partir de esta resolución, el proyecto utilizará obligatoriamente la siguiente estructura:

```text
main
develop
feature/*
hotfix/*
```

---

# 6. Rama main

## Finalidad

La rama `main` representa:

```text
Sistema estable
Código validado
Versión segura
Estado operativo del ERP
```

---

## Restricciones

Queda prohibido:

```text
Desarrollar directamente en main
Experimentar en main
Subir código sin validar
Realizar pruebas destructivas
```

---

# 7. Rama develop

## Finalidad

La rama `develop` será:

```text
Rama principal de integración
Entorno de desarrollo general
Base para nuevas funcionalidades
```

---

## Función

Las funcionalidades completas y verificadas se integrarán primero en `develop`.

Posteriormente podrán pasar a `main`.

---

# 8. Ramas feature/*

## Finalidad

Las ramas `feature/*` se utilizarán para:

```text
Nuevas funcionalidades
Cambios estructurales
Mejoras operativas
Refactorizaciones
Nuevos módulos
```

---

## Ejemplos válidos

```text
feature/clientes
feature/economia
feature/box-watch
feature/presentacion-asistida
feature/conciliacion
feature/autocomplete-clientes
```

---

## Ventajas

El uso de `feature/*` permite:

```text
Aislar desarrollos
Evitar romper el sistema principal
Eliminar experimentos fallidos
Mantener historial limpio
Reducir riesgo operativo
```

---

# 9. Ramas hotfix/*

## Finalidad

Las ramas `hotfix/*` se utilizarán exclusivamente para:

```text
Corrección urgente de errores
Errores críticos en producción
Fallos funcionales de main
```

---

## Ejemplos válidos

```text
hotfix/login
hotfix/clientes-no-guardan
hotfix/error-expedientes
hotfix/presentacion-mercurio
```

---

## Principio operativo

El arreglo deberá:

```text
Aislarse
Probarse
Validarse
Integrarse posteriormente en main
```

---

# 10. Flujo oficial de trabajo

## Nuevas funcionalidades

```text
main
↓
develop
↓
feature/*
↓
develop
↓
main
```

---

## Corrección urgente

```text
main
↓
hotfix/*
↓
main
↓
develop
```

---

# 11. Prohibición de experimentación en ramas estables

Queda prohibido realizar:

```text
Pruebas agresivas
Refactorizaciones masivas
Automatizaciones no verificadas
Cambios destructivos
```

directamente sobre:

```text
main
develop
```

---

# 12. Protección psicológica y operativa

Se reconoce expresamente que el uso de ramas aisladas permite:

```text
Trabajar sin miedo
Reducir bloqueos técnicos
Eliminar desarrollos fallidos
Probar nuevas ideas
```

sin comprometer la estabilidad del ERP.

---

# 13. Relación con la metodología del proyecto

La presente resolución desarrolla y amplía los principios aprobados en:

```text
Resolución 001 — metodología de trabajo
```

y resulta coherente con:

```text
Arquitectura modular
Separación de responsabilidades
Escalabilidad
Control de versiones
Robustez operativa
```



---

# 14. Consecuencia inmediata

A partir de esta resolución:

```text
Toda nueva funcionalidad deberá desarrollarse en feature/*
Toda corrección crítica deberá desarrollarse en hotfix/*
main se considerará rama protegida
```

---

# 15. Objetivo estratégico

El objetivo de este modelo es permitir que el ERP:

```text
crezca sin perder estabilidad,
escale sin caos,
y evolucione sin comprometer el trabajo del despacho.
```

---

# 16. Ubicación del documento

```text
docs/resolutions/012_gobierno_codigo_y_ramas_git.md
```

---

# 17. Commit recomendado

```text
Add resolution 012 git branching and code governance
```

---

# 🔒 Cierre

Queda aprobado el sistema oficial de gobierno del código y estructura de ramas del ERP Quesada Abogados.

Todo desarrollo futuro deberá respetar esta metodología como mecanismo obligatorio de estabilidad, control y crecimiento del sistema.
