# `01_GOBIERNO_DESARROLLO_FABRIC.md` — FUENTE MAESTRA DE GOBIERNO, METODOLOGÍA DE DESARROLLO Y ORQUESTACIÓN FABRIC

**Proyecto:** Quesada Abogados CRM  
**Naturaleza del Documento:** Fuente Maestra Consolidada 01 de 06  
**Estado:** APROBADO POR DIRECCIÓN  
**Trazabilidad:** Construido a partir del Registro Canónico Aprobado (`00_MASTER_INDEX.md`).  
**FUENTES NORMATIVAS BASE:** `001_metodologia_trabajo.md`, `012_gobierno_codigo_y_ramas_git.md`, `016_sistema_trabajo.md`, `20260809_resolucion_blindaje_codigo_auditorias_y_tests_robustos.md`, `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md`, `20260912_resolucion_modelo_direccion_tecnica_y_ejecucion_claude.md`, `20260914_resolucion_sistema_hibrido_tuberias_worktrees_claude.md`.  
**FUENTES INFORMATIVAS NO NORMATIVAS:** `fabricroadmap.txt`, `hojaruta_4semseptiembre.txt`.

---

## SECCIÓN I: MARCO GENERAL Y ALCANCE

La presente Fuente Maestra consolida de forma exhaustiva y unificada todas las decisiones normativas, reglas de gobierno, políticas de desarrollo en Git, gestión de Work Orders, blindaje de tests, prevención de deuda técnica y seguridad de secretos en el proyecto Quesada Abogados CRM.

La Fuente Maestra no crea autoridad normativa por sí misma. Consolida las decisiones normativas aprobadas contenidas en las fuentes originales que regulan la interacción entre la Dirección del Proyecto, la Dirección Técnica/Arquitectura y el Ejecutor de código (Claude), garantizando la estabilidad del repositorio, la calidad del software y el control estricto sobre las modificaciones de código.

---

## SECCIÓN II: DECISIONES NORMATIVAS APROBADAS (GOV, DEV, GIT, FAB, SEC)

### 1. GOBIERNO DEL PROYECTO Y DIRECCIÓN TÉCNICA (`GOV`)

#### `GOV-001` · Modelo de Dirección Técnica Tripartita y Separación de Roles
* **Estado:** VIGENTE
* **Decisión vigente:** Separación explícita de responsabilidades en tres capas de gobierno:
  1. **Dirección del Proyecto (Quesada Abogados):** Estrategia, objetivos de negocio, aceptación de riesgos, prioridad funcional y autoridad final de decisión.
  2. **Dirección Técnica y Arquitectura (ChatGPT):** Visión global del sistema, especificación técnica de soluciones, diseño de arquitectura, definición de contratos, revisión de auditorías y redacción de Work Orders (WO).
  3. **Ejecutante de Código sobre Repositorio (Claude):** Inspección de código, generación de parches quirúrgicos, ejecución de pruebas sintéticas/E2E y aportación de evidencias de verificación.
  
  Ningún agente de IA posee autoridad arquitectónica autónoma ni puede modificar decisiones aprobadas o normas de gobierno por su propia iniciativa.
* **Origen / Fuente primaria:** `20260912_resolucion_modelo_direccion_tecnica_y_ejecucion_claude.md` (Sec. IV y VII).
* **Justificación documentada:** Responder al incremento de escala, profundidad y complejidad del ERP sin perder el control arquitectónico, la coherencia de dominio ni la supervisión humana directa sobre las decisiones críticas.
* **Invariantes:**
  - Claude no es autoridad arquitectónica ni puede reescribir código por preferencias de estilo.
  - Las propuestas del ejecutor no prevalecen sobre resoluciones o normas aprobadas.
  - El repositorio real en Git es la única fuente de verdad técnica.
* **Evolución y modificaciones:** Desarrollada y profundizada por `20260914_resolucion_sistema_hibrido_tuberias_worktrees_claude.md` (Carril A / Carril B).
* **Relaciones relevantes:** Conecta directamente con `FAB-001` (Work Orders como unidad de trabajo) y `GIT-002` (Worktrees y regla `CLAUDE CLOSED`).

---

### 2. METODOLOGÍA DE DESARROLLO Y CALIDAD DE CÓDIGO (`DEV`)

#### `DEV-001` · Formato Inicial de Entregas por Reemplazo Completo de Archivos
* **Estado:** MODIFICADA
* **Decisión vigente:** Reemplazada en su operativa ordinaria principal por la norma `DEV-002` (Metodología QA-DEV-001). Inicialmente establecía que cada entrega de código debía incluir la ruta exacta, el nombre del archivo y el código fuente completo del archivo modificado para su copia y pegado manual por el usuario.
* **Origen / Fuente primaria:** `001_metodologia_trabajo.md` (Sec. 2 y 6).
* **Justificación documentada:** Disponer de un procedimiento estandarizado y ordenado de entrega de código durante las semanas iniciales de arranque del proyecto.
* **Invariantes:** Se mantiene con carácter permanente la obligación de documentar la ruta exacta, el nombre del archivo y la descripción funcional de cada cambio.
* **Evolución y modificaciones:** Modificada por `016_sistema_trabajo.md` (QA-DEV-001/2026) y `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md`, que prohibieron el reemplazo de archivos completos como norma ordinaria debido al riesgo de regresiones y sobrescritura de código.
* **Relaciones relevantes:** Antecedente histórico de la metodología de desarrollo del proyecto.

#### `DEV-002` · Metodología Oficial QA-DEV-001 de Diagnóstico Incremental y Parches Bash
* **Estado:** VIGENTE
* **Decisión vigente:** La sustitución de archivos completos queda prohibida como práctica ordinaria de desarrollo, quedando permitida **únicamente** cuando se trate de: (1) un archivo totalmente nuevo, (2) una plantilla generada, (3) un archivo pequeño bajo control total, o (4) cuando exista autorización técnica explícita.
  
  Flujo de trabajo obligatorio de 6 fases para cualquier modificación de código:
  1. **Fase 1 (Diagnóstico previo):** Inspección con `git status`, `grep` y `sed` para verificar el estado exacto del archivo antes de tocarlo.
  2. **Fase 2 (Parche quirúrgico Bash):** Generación de parches en `/tmp` modificando únicamente las líneas o funciones estrictamente necesarias.
  3. **Fase 3 (Verificación sintáctica):** Compilación previa con `py_compile` para descartar errores de sintaxis o identación antes de probar.
  4. **Fase 4 (Prueba funcional):** Ejecución de pruebas aisladas o invocación de `app.main` para verificar el comportamiento esperado.
  5. **Fase 5 (Inspección de diferencias):** Comprobación final mediante `git diff` para asegurar que no se introdujeron modificaciones no deseadas.
  6. **Fase 6 (Commit atómico):** Registro del cambio mediante commit pequeño, atómico y con mensaje descriptivo.
* **Origen / Fuente primaria:** `016_sistema_trabajo.md` (Resolución QA-DEV-001/2026, Sec. I, II y VI.2).
* **Justificación documentada:** Eliminar el riesgo de regresiones graves, prevenir la pérdida de cambios recientes en la rama activa y evitar que las IAs introduzcan versiones desactualizadas de archivos completos.
* **Invariantes:**
  - Prohibido parchear o modificar código a ciegas.
  - Validación de sintaxis con `py_compile` obligatoria antes de cualquier ejecución funcional.
  - Commits pequeños, atómicos y fácilmente reversibles.
* **Evolución y modificaciones:** Modifica `DEV-001`. Desarrollada y reafirmada por `20260809_gobierno_codigo`, `20260912_modelo_direccion_claude` y `20260914_tuberias_claude`.
* **Relaciones relevantes:** Base operativa obligatoria para las ejecuciones de Claude (`GOV-001`) y el carril de tuberías (`GIT-002`).

#### `DEV-003` · Blindaje del Código mediante Suites de Tests, Clean-Install y Dataset Contractual
* **Estado:** VIGENTE
* **Decisión vigente:** Ningún módulo maduro del ERP se considera cerrado ni listo para producción sin contar con pruebas contractuales de no regresión (unitarias, de servicio, de integración y E2E).
  
  Exigencias contractuales de blindaje:
  - **Pruebas Clean-Install:** Obligatoriedad de ejecutar pruebas sobre bases de datos totalmente limpias para verificar la creación e inicialización de esquemas en módulos transversales.
  - **Dataset Contractual Ficticio:** Creación y mantenimiento de un dataset ficticio E2E reproducible para validación de flujos completos.
  - **Prohibición de Manipulación:** Queda estrictamente prohibido modificar o debilitar los assertions de una suite de tests existente para simular la corrección de un error o enmascarar una regresión.
* **Origen / Fuente primaria:** `20260809_resolucion_blindaje_codigo_auditorias_y_tests_robustos.md` (Sec. I, III y V).
* **Justificación documentada:** Garantizar que la expansión de nuevas funcionalidades no deteriore los módulos ya estabilizados ni reabra fallos previamente corregidos.
* **Invariantes:**
  - Queda estrictamente prohibido usar datos reales o identificativos de clientes en tests automáticos.
  - Todo bug relevante corregido deberá, cuando resulte razonable, producir un test de regresión que impida su reaparición.
* **Evolución y modificaciones:** Desarrollada por `20260809_gobierno_codigo` y `20260912_modelo_direccion_claude`.
* **Relaciones relevantes:** Fundamenta el criterio de congelación `CLAUDE CLOSED` (`GIT-002`) y la prevención de deuda técnica (`DEV-004`).

#### `DEV-004` · Prevención de Deuda Técnica y *Boy Scout Rule* Controlada
* **Estado:** VIGENTE
* **Decisión vigente:** Prohibición explícita de introducir nueva deuda técnica de forma consciente en las soluciones presentadas para acelerar plazos de entrega.
  
  Aplicación de la ***Boy Scout Rule* Controlada**: Al modificar un archivo o módulo que presente deuda técnica conocida (identificada en las auditorías de código), el desarrollador o ejecutor debe corregir o mejorar dicha deuda concreta sin ampliar desproporcionadamente el perímetro asignado en la tarea.
* **Origen / Fuente primaria:** `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` (Sec. I y IV).
* **Justificación documentada:** Mantener la sostenibilidad arquitectónica del repositorio y evitar que la acumulación de parches desorganice los servicios centrales del ERP.
* **Invariantes:**
  - La urgencia o velocidad de entrega no justifica degradar la calidad arquitectónica.
  - La corrección funcional de un bug no justifica introducir una regresión estructural.
* **Evolución y modificaciones:** Complementada por `20260809_blindaje_codigo`.
* **Relaciones relevantes:** Aplica transversalmente sobre la refactorización de servicios de aplicación, persistencia y vistas.

---

### 3. CONTROL DE VERSIONES, WORKTREES Y TUBERÍAS (`GIT`)

#### `GIT-001` · Política Oficial de Ramas Git y Protección de la Rama Estable
* **Estado:** VIGENTE
* **Decisión vigente:** La rama `main` representa la versión estable y operativa en producción del ERP Quesada Abogados y queda blindada contra desarrollo directo, pruebas o experimentos.
  
  Estructura de ramas obligatoria:
  - **`main`:** Producción / Estable. Solo recibe integraciones verificadas.
  - **`develop`:** Integración general y staging de funcionalidades consolidadas.
  - **`feature/*`:** Ramas de trabajo aisladas para la construcción de nuevas características.
  - **`hotfix/*`:** Ramas urgentes para la corrección inmediata de errores en producción.
* **Origen / Fuente primaria:** `012_gobierno_codigo_y_ramas_git.md` (Sec. 1, 2 y 3).
* **Justificación documentada:** Prevenir colisiones de código, inestabilidad en producción y corrupción del repositorio de código.
* **Invariantes:**
  - Prohibido realizar commits o desarrollos directos sobre la rama `main`.
  - Prohibido el uso indiscriminado de `git add .` cuando existan archivos locales, temporales o confidenciales en el workspace.
  - Prohibido incluir credenciales, claves o variables de entorno en commits (`SEC-001`).
* **Evolución y modificaciones:** Desarrollada y ampliada por `016`, `20260809_gobierno_codigo` y `20260914_tuberias_claude`.
* **Relaciones relevantes:** Base de gestión del repositorio complementada por `GIT-002` (Worktrees y Tuberías).

#### `GIT-002` · Desarrollo por Tuberías Continuas, Worktrees Paralelos y Regla `CLAUDE CLOSED`
* **Estado:** VIGENTE
* **Decisión vigente:** Organización del desarrollo del sistema en dos carriles operativos paralelos y desacoplados mediante el uso de `git worktree`:
  
  - **Carril A (Cierre y Consolidación por Claude):** Claude trabaja en un worktree exclusivo sobre el Módulo $N$ realizando auditorías, refactorizaciones quirúrgicas, creación de tests contractuales y certificación final.
  - **Carril B (Incubación Manual Desacoplada):** Desarrollo o incubación paralela en un worktree independiente sobre el Módulo $N+1$ en componentes con etiqueta "verde" (sin solapamiento de código).
  
  **Regla de Cierre (`CLAUDE CLOSED`):** Todo módulo o componente que complete su fase de consolidación debe ser auditado y cerrado formalmente por Claude, marcándose con el estado `FORMAL_CLOSURE=CLOSED`.
  
  **Regla de No Reapertura:** Queda estrictamente prohibido reabrir o modificar mediante el carril de incubación manual cualquier módulo que haya alcanzado el estado `CLAUDE CLOSED`. Cualquier evolución posterior sobre un módulo cerrado debe ser tramitada exclusivamente mediante nueva Work Order dirigida a Claude.
* **Origen / Fuente primaria:** `20260914_resolucion_sistema_hibrido_tuberias_worktrees_claude.md` (Sec. I, III, IX y X).
* **Justificación documentada:** Eliminar los tiempos muertos en el flujo de desarrollo, permitiendo avanzar en la incubación de nuevas características sin interferir con el proceso de congelación, auditoría y blindaje del módulo previo.
* **Invariantes:**
  - Los dos carriles no pueden modificar de forma simultánea los mismos archivos, servicios o esquemas de base de datos.
  - Los módulos cerrados bajo la etiqueta `CLAUDE CLOSED` no se reabren manualmente.
* **Evolución y modificaciones:** Desarrolla y profundiza `GOV-001` (Dirección Tripartita) y `GIT-001` (Ramas Git).
* **Relaciones relevantes:** Regula el flujo de trabajo entre la Dirección Técnica (ChatGPT) y el Ejecutor (Claude).

---

### 4. UNIDAD DE TRABAJO Y EJECUCIÓN (`FAB`)

#### `FAB-001` · Work Orders como Unidad Canónica de Especificación y Trabajo
* **Estado:** VIGENTE
* **Decisión vigente:** La unidad principal de comunicación, especificación y trabajo para cualquier desarrollo, modificación o corrección en el proyecto es la **Work Order (WO)** emitida formalmente por la Dirección Técnica.
  
  Cada Work Order deberá contener, cuando proceda:
  - contexto;
  - objetivo;
  - estado conocido;
  - archivos o áreas relevantes;
  - contratos;
  - invariantes;
  - prohibiciones;
  - fases de trabajo;
  - diagnóstico requerido;
  - tests;
  - criterios de aceptación;
  - formato de evidencia;
  - política de commit.
* **Origen / Fuente primaria:** `20260912_resolucion_modelo_direccion_tecnica_y_ejecucion_claude.md` (Sec. V, VI y VII).
* **Justificación documentada:** Prevenir instrucciones ambiguas, evitar iniciativas autónomas no supervisadas y garantizar que el ejecutor trabaje sobre un perímetro acotado y totalmente auditable.
* **Invariantes:**
  - Claude debe detenerse, documentar el hallazgo y solicitar orientación ante cualquier imprevisto, contradicción o bloqueo, sin ampliar unilateralmente el alcance de la WO.
* **Evolución y modificaciones:** Desarrollada por `20260914_resolucion_sistema_hibrido_tuberias_worktrees_claude.md`.
* **Relaciones relevantes:** Conecta directamente con `GOV-001` (Separación de roles) y `DEV-002` (Metodología de parches).

---

### 5. SEGURIDAD Y PROTECCIÓN DE SECRETOS (`SEC`)

#### `SEC-001` · Prohibición de Versionar Secretos, Credenciales y Certificados en Git
* **Estado:** VIGENTE
* **Decisión vigente:** Queda estrictamente prohibido incluir en commits, staged files o versionar en Git archivos `.env`, `.env.local`, tokens de acceso, contraseñas, certificados digitales (pfx/p12), OAuth secrets o claves privadas de APIs.
  
  Los secretos y variables de entorno sensibles deben suministrarse exclusivamente mediante almacenamiento local ignorado por Git o variables de entorno del sistema operativo.
* **Origen / Fuente primaria:** `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` (Sec. XXII) y `012_gobierno_codigo_y_ramas_git.md` (Sec. 4).
* **Justificación documentada:** Proteger la seguridad del despacho, garantizar la confidencialidad de los datos de clientes y prevenir la filtración accidental de credenciales en el repositorio.
* **Invariantes:**
  - Uso obligatorio y mantenimiento estricto del archivo `.gitignore` en la raíz del proyecto.
  - Prohibida la inclusión de certificados digitales reales o claves de producción en el árbol del repositorio Git.
* **Evolución y modificaciones:** Complementa `GIT-001` (Protección de la rama estable).
* **Relaciones relevantes:** Invariante transversal de seguridad aplicable a todos los módulos y componentes del ERP.

---

## SECCIÓN III: INFORMACIÓN TÉCNICA NO NORMATIVA

*(Los contenidos integrados en esta sección poseen carácter estrictamente informativo, diagnóstico o de hoja de ruta. No constituyen normas de obligado cumplimiento ni decisiones de arquitectura).*

### 1. DIVERGENCIA DOCUMENTAL–OPERATIVA ABIERTA (NO NORMATIVO)

La implementación actual de Fabric ha evolucionado posteriormente hacia un modelo multiprovider y multiworker que todavía no dispone de resolución formal incorporada al corpus. Hasta realizar auditoría y nueva resolución, `GOV-001`, `GIT-002` y `FAB-001` conservan su vigencia documental histórica y no deben reinterpretarse automáticamente.

---

### 2. ESTADO TÉCNICO RELEVANTE (NO NORMATIVO)
*(Fuentes: `20260809_resolucion_estado_actual_proyecto_y_hoja_ruta_supabase.md`, `20260809_resolucion_blindaje_codigo_auditorias_y_tests_robustos.md`, `hojaruta_4semseptiembre.txt`)*

- **Métricas de madurez global (Auditoría de Agosto 2026):**
  - Avance funcional global del ERP: ~81%.
  - Madurez técnica del backend y gobierno de código: ~82%.
- **Cobertura de tests y blindaje contractual:**
  - Despliegue de suites de tests de servicio e integración sobre los módulos centrales.
  - Dataset E2E ficticio plenamente funcional y reproducible para pruebas de no regresión.
- **Estado de congelaciones de módulos (Septiembre 2026):**
  - Módulo **Social Media V1**: Congelado y cerrado formalmente por Claude en commit `cabe90e` (`FORMAL_CLOSURE=CLOSED`).
  - Módulo **State-Aware + Safe Recovery**: Congelado y cerrado formalmente por Claude en commit `2c0f73c` (`FORMAL_CLOSURE=CLOSED`).
- **Diagnóstico operativo en Runner V2.0:**
  - Detección de fallo tipo `EXECUTOR_EXCEPTION` por ausencia del archivo `git_before.txt` tras retornos exitosos del ejecutor Claude, requiriendo una fase de hardening en la versión V2.1.

---

### 3. ROADMAP FABRIC / FCP (FABRIC CLOSURE PROGRAM) (ROADMAP NO NORMATIVO)
*(Fuentes: `fabricroadmap.txt`, `hojaruta_4semseptiembre.txt`)*

Naturaleza del programa: El Fabric Closure Program (FCP) regula la hoja de ruta de la herramienta de software interna `Fabric` (orquestador de desarrollo y gestión automatizada de worktrees). No es una norma de arquitectura del ERP Quesada Abogados.

Mapeo de fases del roadmap FCP:

FCP-1 Canonical Base & Integration Manager  
FCP-2 Semantic Reconciliation Pipeline  
FCP-3 Autonomous Promotion  
FCP-4 Worktree Lifecycle Manager  
FCP-5 Pipeline / DAG Engine  
FCP-6 Failure / Retry Intelligence  
FCP-7 Provider Router  
FCP-8 Validation & Evidence Engine  
FCP-9 Scheduler & Parallel Execution  
FCP-10 Resource / Quota Manager  
FCP-11 Observability / Control Plane  
FCP-12 Self-Dogfood & Closure

Plan de trabajo inmediato (Runner V2.1 Hardening):
- Separación entre los estados `WORK_SUCCESS` (ejecución técnica finalizada) y `EVIDENCE_COMPLETE` (verificación de pruebas de soporte).
- Implementación de ledger persistente de eventos para prevención de timeouts falsos.

---

### 4. INFORMACIÓN OPERATIVA HISTÓRICA PERTINENTE (NO NORMATIVA)
*(Fuentes: `001_metodologia_trabajo.md`, `012_gobierno_codigo_y_ramas_git.md`, `016_sistema_trabajo.md`)*

- **Fase de arranque técnico (Abril 2026):** Definición de la estructura inicial de carpetas del proyecto y entregas mediante copias manuales de código (`001`).
- **Institucionalización de Git (Mayo 2026):** Transición desde el desarrollo sin control de versiones formal hacia la adopción oficial del flujo de ramas `main`, `develop`, `feature/*` y `hotfix/*` (`012`).
- **Adopción de QA-DEV-001 (Junio 2026):** Abandono de la sustitución masiva de archivos tras detectar sobrescrituras accidentales de código, imponiendo el protocolo quirúrgico por parches Bash (`016`).

---

> ESTADO: 01_GOBIERNO_DESARROLLO_FABRIC — APROBADO POR DIRECCIÓN
