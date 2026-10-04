# 00_MASTER_INDEX.md — ÍNDICE MAESTRO CANÓNICO DEL PROYECTO QUESADA ABOGADOS

**Proyecto:** Quesada Abogados CRM  
**Naturaleza del documento:** Índice Maestro, Mapa de Trazabilidad y Registro Canónico de Decisiones Aprobadas  
**Estado:** APROBADO POR DIRECCIÓN  
**Base documental:** Corpus canónico de 33 fuentes del proyecto.  
**Protocolo de consolidación:** `000_PROTOCOLO_CONSOLIDACION_NOTEBOOKLM.md`, exclusivamente metadocumental y sin autoridad normativa sobre el proyecto.

---

# 1. MAPA DE LAS 6 FUENTES MAESTRAS

El cuerpo normativo consolidado del proyecto se estructura inicialmente en seis fuentes maestras temáticas.

| Fuente Maestra | Ámbito | Contenido principal |
|---|---|---|
| `01_GOBIERNO_DESARROLLO_FABRIC.md` | Gobierno, desarrollo y Fabric | `GOV`, `DEV`, `GIT`, `FAB`, `SEC`; Dirección Técnica, metodología, ramas, worktrees, Work Orders, tests, deuda técnica, seguridad y evolución de Fabric. |
| `02_ARQUITECTURA_ERP_DATOS.md` | Arquitectura ERP y datos | `ARCH`, `DATA`, `UI`; capas, repositorio, modelos funcionales, persistencia, PostgreSQL/Supabase, frontend Flet y componentes reutilizables. |
| `03_DOCUMENTAL_KNOWLEDGE_OPERACIONES.md` | Documental, Knowledge y operaciones | `DOC`, `KNOW`, `OPS`; Box, clasificación documental, flujo circular, supervisión humana de IA, clientes, hojas de encargo, TASK y CAA. |
| `04_QCC_BROWSER_AUTOMATION.md` | Browser Runtime, SeleniumBase y QCC | `WEB`, `QCC`; SeleniumBase/CDP, ownership, runtime, DOM First, QCC, Bridge y política QCC V1. |
| `05_AUTO_TWIN_SITE_ARCHITECTURE.md` | Site Architecture y AUTO TWIN | `SITE`, `TWIN`; contratos de sede, geometría JIT, HUMAN_ONLY, LABS, AUTO TWIN, REAL ↔ TWIN y aislamiento. |
| `06_ESTADO_ROADMAP_ECOSISTEMA.md` | Estado y roadmap | Estado técnico transversal, auditorías, deuda, métricas, FCP, UWT, mejoras QCC y planificación operativa histórica. |

---

# 2. REGISTRO CANÓNICO DE DECISIONES

## Gobierno, desarrollo, Git, Fabric y seguridad

| ID | Decisión | Estado | Fuente primaria | Fuente maestra |
|---|---|---|---|---|
| `GOV-001` | Modelo de Dirección Técnica Tripartita y Separación de Roles | VIGENTE | `20260912_resolucion_modelo_direccion_tecnica_y_ejecucion_claude.md` | `01` |
| `DEV-001` | Formato Inicial de Entregas por Reemplazo Completo de Archivos | MODIFICADA | `001_metodologia_trabajo.md` | `01` |
| `DEV-002` | Metodología Oficial QA-DEV-001 de Diagnóstico Incremental y Parches Bash | VIGENTE | `016_sistema_trabajo.md` | `01` |
| `DEV-003` | Blindaje del Código mediante Suites de Tests, Clean-Install y Dataset Contractual | VIGENTE | `20260809_resolucion_blindaje_codigo_auditorias_y_tests_robustos.md` | `01` |
| `DEV-004` | Prevención de Deuda Técnica y Boy Scout Rule Controlada | VIGENTE | `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` | `01` |
| `GIT-001` | Política Oficial de Ramas Git y Protección de la Rama Estable | VIGENTE | `012_gobierno_codigo_y_ramas_git.md` | `01` |
| `GIT-002` | Desarrollo por Tuberías Continuas, Worktrees Paralelos y Regla CLAUDE CLOSED | VIGENTE | `20260914_resolucion_sistema_hibrido_tuberias_worktrees_claude.md` | `01` |
| `FAB-001` | Work Orders como Unidad Canónica de Especificación y Trabajo | VIGENTE | `20260912_resolucion_modelo_direccion_tecnica_y_ejecucion_claude.md` | `01` |
| `SEC-001` | Prohibición de Versionar Secretos, Credenciales y Certificados en Git | VIGENTE | `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` | `01` |

## Arquitectura, datos y frontend

| ID | Decisión | Estado | Fuente primaria | Fuente maestra |
|---|---|---|---|---|
| `ARCH-001` | Separación Estricta de Capas | VIGENTE | `001_metodologia_trabajo.md` | `02` |
| `ARCH-002` | Estructura Física del Repositorio | VIGENTE | `013_estructura_repositorio.md` | `02` |
| `ARCH-003` | Prohibición de Rutas Absolutas Personales | VIGENTE | `001_metodologia_trabajo.md` | `02` |
| `ARCH-004` | Arquitectura Híbrida Cloud / Agentes Locales | VIGENTE | `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` | `02` |
| `DATA-001` | Modelo Funcional de Clientes y Red de Contactos | VIGENTE | `005_modelo_datos_clientes.md` | `02` |
| `DATA-002` | Motor Funcional de Expedientes, Catálogo y Estados | VIGENTE | `006_modelo_datos_expedientes.md` | `02` |
| `DATA-003` | Modelo Económico, Fraccionamiento de Pago y Consultas Descontables | MODIFICADA | `007_modelo_datos_economico_cobros.md` | `02` |
| `DATA-004` | Regla FACTURABLE ≠ FACTURAR | VIGENTE | `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` | `02` |
| `DATA-005` | Conciliación Económica Previa a la Facturación | VIGENTE | `008_conciliacion_economica.md` | `02` |
| `DATA-006` | Módulo Fiscal Interno de Coherencia Tributaria | VIGENTE | `009_modulo_fiscal.md` | `02` |
| `DATA-007` | Migración Selectiva y Etiquetado Obligatorio de Datos Legacy | VIGENTE | `010_legacy_migracion_reconstruccion.md` | `02` |
| `DATA-008` | Centralización de la Persistencia y Desacoplamiento de SQLite | VIGENTE | `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` | `02` |
| `DATA-009` | Una Sola Fuente Canónica de Verdad por Dominio | VIGENTE | `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` | `02` |
| `DATA-010` | Transición a PostgreSQL/Supabase mediante Baseline Limpio y Gates Obligatorios | VIGENTE | `20260809_resolucion_estado_actual_proyecto_y_hoja_ruta_supabase.md` | `02` |
| `UI-001` | Flet como Tecnología Oficial y Prohibición de SQL en Presentación | VIGENTE | `004_frontend_flet.md` | `02` |
| `UI-002` | Obligatoriedad del Catálogo Reutilizable `frontend/components/` | VIGENTE | `017_componentes_sistema.md` | `02` |
| `UI-003` | Prohibición de `ft.Container(expand=True)` como Separador Visual | VIGENTE | `017_componentes_sistema.md` | `02` |

## Documental, Knowledge y operaciones

| ID | Decisión | Estado | Fuente primaria | Fuente maestra |
|---|---|---|---|---|
| `DOC-001` | El ERP SOLO observa Box, NUNCA manipula Box | VIGENTE | `011_sistema_documental_box_vigilancia.md` | `03` |
| `DOC-002` | Clasificación Documental de Extranjería e Invalidez de Resguardos | VIGENTE | `014_resolucion_box_extranjeria_v1.md` | `03` |
| `KNOW-001` | Flujo Circular Operativo del Cliente y Generación de Conocimiento | VIGENTE | `015_flujo_circular_cliente.md` | `03` |
| `KNOW-002` | Supervisión Jurídica Humana Obligatoria sobre Criterios de IA | VIGENTE | `015_flujo_circular_cliente.md` | `03` |
| `OPS-001` | Flujo Operativo del Cliente y Hojas de Encargo | VIGENTE | `002_funcionamiento_negocio.md` | `03` |
| `OPS-002` | Integración de Herramientas Externas mediante CSV | VIGENTE | `003_ecosistema_tecnologico.md` | `03` |
| `OPS-003` | TASK como Unidad Canónica de Trabajo y CAA como Centro Operativo | VIGENTE | `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` | `03` |

## Automatización web y QCC

| ID | Decisión | Estado | Fuente primaria | Fuente maestra |
|---|---|---|---|---|
| `WEB-001` | Infraestructura Común de Automatización SeleniumBase / CDP | VIGENTE | `20260815_resolucion_arquitectura_y_gobierno_infraestructura_seleniumbase_cdp.md` | `04` |
| `WEB-002` | Prohibición de SeleniumBase en el Frontend | VIGENTE | `20260815_resolucion_arquitectura_y_gobierno_infraestructura_seleniumbase_cdp.md` | `04` |
| `WEB-003` | Principio DOM First y Fallback Gobernado | VIGENTE | `20260815_resolucion_arquitectura_y_gobierno_infraestructura_seleniumbase_cdp.md` | `04` |
| `WEB-004` | Prohibición de `os._exit()` en Producción y Aislamiento de Runtimes | VIGENTE | `20260815_resolucion_arquitectura_y_gobierno_infraestructura_seleniumbase_cdp.md` | `04` |
| `QCC-001` | Quesada Chrome Companion como Interfaz Contextual | VIGENTE | `20260821_resolucion_quesada_chrome_companion_qcc.md` | `04` |
| `QCC-002` | Arquitectura de Comunicación mediante QCC Bridge | VIGENTE | `20260821_resolucion_quesada_chrome_companion_qcc.md` | `04` |
| `QCC-003` | No Interferencia Directa con el DOM en QCC V1 | VIGENTE | `20260821_resolucion_quesada_chrome_companion_qcc.md` | `04` |

## Site Architecture y AUTO TWIN

| ID | Decisión | Estado | Fuente primaria | Fuente maestra |
|---|---|---|---|---|
| `SITE-001` | QCC Site Architecture y Contratos de Sede | VIGENTE | `20260822_resolucion_qcc_site_architecture_dom_geometry_interaction.md` | `05` |
| `SITE-002` | Capa Geométrica JIT y Prohibición de Coordenadas Fijas | VIGENTE | `20260822_resolucion_qcc_site_architecture_dom_geometry_interaction.md` | `05` |
| `SITE-003` | Clasificación Estricta de Políticas HUMAN_ONLY | VIGENTE | `20260822_resolucion_qcc_site_architecture_dom_geometry_interaction.md` | `05` |
| `TWIN-001` | Institución del Sistema LABS de Sedes Electrónicas | VIGENTE | `20260822_resolucion_sistema_labs_sedes_electronicas.md` | `05` |
| `TWIN-002` | Método Manual Ordinario de Construcción de LABS | SUPERADA PARCIALMENTE | `20260822_resolucion_sistema_labs_sedes_electronicas.md` | `05` |
| `TWIN-003` | Capacidad AUTO TWIN y Fidelidad en Rendering Profile | VIGENTE | `20260905_resolucion_qcc_auto_twin_arquitectura_fidelidad_sincronizacion.md` | `05` |
| `TWIN-004` | Aislamiento de Producción, Datos Ficticios y Guardas Localhost | VIGENTE | `20260822_resolucion_sistema_labs_sedes_electronicas.md` | `05` |
| `TWIN-005` | Validación Obligatoria REAL ↔ TWIN para Promoción de Revisiones | VIGENTE | `20260905_resolucion_qcc_auto_twin_arquitectura_fidelidad_sincronizacion.md` | `05` |

---

# 3. CONTROL DEL REGISTRO

**TOTAL DECISIONES:** 48  
**VIGENTES:** 45  
**MODIFICADAS:** 2  
**SUPERADAS PARCIALMENTE:** 1  
**CON DUDA:** 0  

Comprobación:

`45 + 2 + 1 = 48`

---

# 4. MAPA FUENTE ORIGINAL NORMATIVA → DECISIONES

1. `001_metodologia_trabajo.md` → `DEV-001`, `ARCH-001`, `ARCH-003`
2. `002_funcionamiento_negocio.md` → `OPS-001`
3. `003_ecosistema_tecnologico.md` → `OPS-002`
4. `004_frontend_flet.md` → `UI-001`
5. `005_modelo_datos_clientes.md` → `DATA-001`
6. `006_modelo_datos_expedientes.md` → `DATA-002`
7. `007_modelo_datos_economico_cobros.md` → `DATA-003`
8. `008_conciliacion_economica.md` → `DATA-005`
9. `009_modulo_fiscal.md` → `DATA-006`
10. `010_legacy_migracion_reconstruccion.md` → `DATA-007`
11. `011_sistema_documental_box_vigilancia.md` → `DOC-001`
12. `012_gobierno_codigo_y_ramas_git.md` → `GIT-001`
13. `013_estructura_repositorio.md` → `ARCH-002`
14. `014_resolucion_box_extranjeria_v1.md` → `DOC-002`
15. `015_flujo_circular_cliente.md` → `KNOW-001`, `KNOW-002`
16. `016_sistema_trabajo.md` → `DEV-002`
17. `017_componentes_sistema.md` → `UI-002`, `UI-003`
18. `20260809_resolucion_blindaje_codigo_auditorias_y_tests_robustos.md` → `DEV-003`
19. `20260809_resolucion_estado_actual_proyecto_y_hoja_ruta_supabase.md` → `DATA-010`
20. `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` → `DEV-004`, `SEC-001`, `ARCH-004`, `DATA-004`, `DATA-008`, `DATA-009`, `OPS-003`
21. `20260815_resolucion_arquitectura_y_gobierno_infraestructura_seleniumbase_cdp.md` → `WEB-001`, `WEB-002`, `WEB-003`, `WEB-004`
22. `20260821_resolucion_quesada_chrome_companion_qcc.md` → `QCC-001`, `QCC-002`, `QCC-003`
23. `20260822_resolucion_qcc_site_architecture_dom_geometry_interaction.md` → `SITE-001`, `SITE-002`, `SITE-003`
24. `20260822_resolucion_sistema_labs_sedes_electronicas.md` → `TWIN-001`, `TWIN-002`, `TWIN-004`
25. `20260905_resolucion_qcc_auto_twin_arquitectura_fidelidad_sincronizacion.md` → `TWIN-003`, `TWIN-005`
26. `20260912_resolucion_modelo_direccion_tecnica_y_ejecucion_claude.md` → `GOV-001`, `FAB-001`
27. `20260914_resolucion_sistema_hibrido_tuberias_worktrees_claude.md` → `GIT-002`

---

# 5. MAPA DECISIÓN → FUENTE Y EVOLUCIÓN

## Gobierno y desarrollo

- `GOV-001` → Primaria: `20260912_resolucion_modelo_direccion_tecnica_y_ejecucion_claude.md` → desarrollada por `20260914_resolucion_sistema_hibrido_tuberias_worktrees_claude.md`.
- `DEV-001` → Primaria: `001_metodologia_trabajo.md` → modificada por `016_sistema_trabajo.md`.
- `DEV-002` → Primaria: `016_sistema_trabajo.md` → desarrollada posteriormente por resoluciones de gobierno, dirección técnica y tuberías.
- `DEV-003` → Primaria: `20260809_resolucion_blindaje_codigo_auditorias_y_tests_robustos.md`.
- `DEV-004` → Primaria: `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md`.
- `GIT-001` → Primaria: `012_gobierno_codigo_y_ramas_git.md`.
- `GIT-002` → Primaria: `20260914_resolucion_sistema_hibrido_tuberias_worktrees_claude.md`.
- `FAB-001` → Primaria: `20260912_resolucion_modelo_direccion_tecnica_y_ejecucion_claude.md`.
- `SEC-001` → Primaria: `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md`.

## Arquitectura, datos y frontend

- `ARCH-001` → `001_metodologia_trabajo.md` / `004_frontend_flet.md`, desarrollada posteriormente por `013` y resolución de gobierno de código.
- `ARCH-002` → `013_estructura_repositorio.md`.
- `ARCH-003` → `001_metodologia_trabajo.md`.
- `ARCH-004` → `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md`.
- `DATA-001` → `005_modelo_datos_clientes.md`.
- `DATA-002` → `006_modelo_datos_expedientes.md`.
- `DATA-003` → `007_modelo_datos_economico_cobros.md`, modificada parcialmente por `DATA-004`.
- `DATA-004` → `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md`.
- `DATA-005` → `008_conciliacion_economica.md`.
- `DATA-006` → `009_modulo_fiscal.md`.
- `DATA-007` → `010_legacy_migracion_reconstruccion.md`.
- `DATA-008` → `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md`.
- `DATA-009` → `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md`.
- `DATA-010` → `20260809_resolucion_estado_actual_proyecto_y_hoja_ruta_supabase.md`.
- `UI-001` → `004_frontend_flet.md`.
- `UI-002` → `017_componentes_sistema.md`.
- `UI-003` → `017_componentes_sistema.md`.

## Documental y operaciones

- `DOC-001` → `011_sistema_documental_box_vigilancia.md`.
- `DOC-002` → `014_resolucion_box_extranjeria_v1.md`.
- `KNOW-001` → `015_flujo_circular_cliente.md`.
- `KNOW-002` → `015_flujo_circular_cliente.md`.
- `OPS-001` → `002_funcionamiento_negocio.md`.
- `OPS-002` → `003_ecosistema_tecnologico.md`.
- `OPS-003` → `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md`.

## Browser / QCC

- `WEB-001` → `20260815_resolucion_arquitectura_y_gobierno_infraestructura_seleniumbase_cdp.md`.
- `WEB-002` → misma resolución.
- `WEB-003` → misma resolución, desarrollada por Site Architecture.
- `WEB-004` → misma resolución.
- `QCC-001` → `20260821_resolucion_quesada_chrome_companion_qcc.md`.
- `QCC-002` → misma resolución.
- `QCC-003` → misma resolución y limitado expresamente al alcance QCC V1.

## Site Architecture / AUTO TWIN

- `SITE-001` → `20260822_resolucion_qcc_site_architecture_dom_geometry_interaction.md`.
- `SITE-002` → misma resolución.
- `SITE-003` → misma resolución.
- `TWIN-001` → `20260822_resolucion_sistema_labs_sedes_electronicas.md`.
- `TWIN-002` → misma resolución, superada parcialmente por `20260905_resolucion_qcc_auto_twin_arquitectura_fidelidad_sincronizacion.md`.
- `TWIN-003` → `20260905_resolucion_qcc_auto_twin_arquitectura_fidelidad_sincronizacion.md`.
- `TWIN-004` → `20260822_resolucion_sistema_labs_sedes_electronicas.md`, reafirmada por AUTO TWIN.
- `TWIN-005` → `20260905_resolucion_qcc_auto_twin_arquitectura_fidelidad_sincronizacion.md`.

---

# 6. DECISIONES MODIFICADAS O SUPERADAS

## DEV-001 → MODIFICADA

**Origen:** `001_metodologia_trabajo.md`  
**Modificada por:** `016_sistema_trabajo.md` → `DEV-002`

El reemplazo completo de archivos deja de ser la práctica ordinaria.

La metodología vigente pasa a diagnóstico incremental, modificaciones localizadas, validación y commits atómicos, conservándose únicamente las excepciones expresamente autorizadas.

---

## DATA-003 → MODIFICADA PARCIALMENTE

**Origen:** `007_modelo_datos_economico_cobros.md`  
**Modificada por:** `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` → `DATA-004`

Continúan vigentes el modelo económico, el fraccionamiento máximo ordinario y el descuento de consultas previas.

Queda eliminada la creación implícita de facturas.

---

## TWIN-002 → SUPERADA PARCIALMENTE

**Origen:** `20260822_resolucion_sistema_labs_sedes_electronicas.md`  
**Superada parcialmente por:** `20260905_resolucion_qcc_auto_twin_arquitectura_fidelidad_sincronizacion.md` → `TWIN-003`

AUTO TWIN sustituye la construcción manual pantalla por pantalla como mecanismo ordinario.

La construcción manual permanece únicamente para:

- excepciones;
- overrides puntuales;
- Golden References cuando proceda.

---

# 7. PROTOCOLO METADOCUMENTAL

## `000_PROTOCOLO_CONSOLIDACION_NOTEBOOKLM.md`

**Tipo:** Protocolo de Gobierno del Cuaderno.

No pertenece al corpus normativo del proyecto.

No establece arquitectura, funcionalidad ni decisiones del ERP.

Su única función es gobernar el proceso de:

- análisis;
- consolidación;
- trazabilidad;
- control de supersesión;
- mantenimiento de las fuentes maestras.

---

# 8. DOCUMENTOS DEL PROYECTO SIN AUTORIDAD NORMATIVA PROPIA

## `018_informe_tecnico_cuadro_gris.md`

Tipo:

**INFORME TÉCNICO / DIAGNÓSTICO**

Aporta estado, diagnóstico e implementación.

---

## `QCC_15_mejoras_futuras.txt`

Tipo:

**PROPUESTA / ROADMAP**

Catálogo histórico inicial de 15 mejoras de QCC.

---

## `30 mejorasQCC.txt`

Tipo:

**ESTADO / ROADMAP / PROPUESTAS / IMPLEMENTACIÓN**

Catálogo evolutivo de capacidades QCC.

---

## `AMPLIACIONQCC.txt`

Tipo:

**ESTADO / ROADMAP / PROPUESTAS**

Programa Universal Web Twin (`UWT-1..12`).

---

## `fabricroadmap.txt`

Tipo:

**ESTADO / ROADMAP / PROPUESTAS**

Fabric Closure Program (`FCP-1..12`).

---

## `hojaruta_4semseptiembre.txt`

Tipo:

**DOCUMENTO OPERATIVO COYUNTURAL / ESTADO / ROADMAP**

Planificación operativa de la cuarta semana de septiembre de 2026.

---

# 9. CONFLICTOS DOCUMENTALES

**Ningún conflicto documental abierto identificado en el corpus actualmente consolidado.**

Las incompatibilidades históricas detectadas han quedado modeladas mediante:

- `DEV-001` → `DEV-002`
- `DATA-003` → `DATA-004`
- `TWIN-002` → `TWIN-003`

La ausencia de conflictos se refiere exclusivamente al corpus actualmente consolidado.

Una futura incorporación documental puede requerir una nueva auditoría.

---

# 10. FUENTES MAESTRAS

## Generadas / en proceso

- `00_MASTER_INDEX.md` → APROBADO

## Pendientes de validación o generación

1. `01_GOBIERNO_DESARROLLO_FABRIC.md`
2. `02_ARQUITECTURA_ERP_DATOS.md`
3. `03_DOCUMENTAL_KNOWLEDGE_OPERACIONES.md`
4. `04_QCC_BROWSER_AUTOMATION.md`
5. `05_AUTO_TWIN_SITE_ARCHITECTURE.md`
6. `06_ESTADO_ROADMAP_ECOSISTEMA.md`

---

# 11. REGLA DE ACTUALIZACIÓN

Cuando se apruebe una nueva resolución:

1. incorporar la resolución original al corpus canónico;
2. identificar decisiones nuevas o modificadas;
3. actualizar el Registro Canónico;
4. actualizar este índice;
5. actualizar únicamente las fuentes maestras afectadas;
6. conservar la historia de las decisiones modificadas o superadas;
7. no borrar la resolución original.

Las fuentes maestras son documentos vivos.

Las resoluciones originales permanecen como archivo normativo e histórico canónico.

---

# ESTADO FINAL

**00_MASTER_INDEX:** APROBADO  
**DECISIONES CANÓNICAS:** 48  
**CONFLICTOS ABIERTOS IDENTIFICADOS:** 0  
**FUENTES MAESTRAS TEMÁTICAS:** 6  
**PROTOCOLO METADOCUMENTAL:** 1  

Este índice constituye el mapa operativo de trazabilidad del corpus consolidado de Quesada Abogados.
