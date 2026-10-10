# 00_MASTER_INDEX.md — ÍNDICE MAESTRO CANÓNICO DEL PROYECTO QUESADA ABOGADOS

**Proyecto:** Quesada Abogados CRM
**Naturaleza del documento:** Índice Maestro, Mapa de Trazabilidad y Registro Canónico de Decisiones Aprobadas
**Estado:** APROBADO POR DIRECCIÓN
**Base documental:** Corpus canónico de 42 fuentes del proyecto.
**Protocolo de consolidación:** `000_PROTOCOLO_CONSOLIDACION_NOTEBOOKLM.md`, exclusivamente metadocumental y sin autoridad normativa sobre el proyecto.

---

# 1. MAPA DE LAS 6 FUENTES MAESTRAS

El cuerpo normativo consolidado del proyecto se estructura inicialmente en seis fuentes maestras temáticas.

| Fuente Maestra | Ámbito | Contenido principal |
|---|---|---|
| `01_GOBIERNO_DESARROLLO_FABRIC.md` | Gobierno, desarrollo y Fabric | `GOV`, `DEV`, `GIT`, `FAB`, `SEC`; Dirección Técnica, metodología, ramas, worktrees, Work Orders, tests, deuda técnica, seguridad y evolución de Fabric. |
| `02_ARQUITECTURA_ERP_DATOS.md` | Arquitectura ERP y datos | `ARCH`, `DATA`, `UI`; capas, repositorio, `ProcedureContract`, modelos funcionales, persistencia, PostgreSQL/Supabase, frontend Flet y componentes reutilizables. |
| `03_DOCUMENTAL_KNOWLEDGE_OPERACIONES.md` | Documental, Knowledge y operaciones | `DOC`, `KNOW`, `OPS`; Box, clasificación documental, Target Presentation Folder, flujo circular, supervisión humana de IA, clientes, hojas de encargo, TASK y CAA. |
| `04_QCC_BROWSER_AUTOMATION.md` | Browser Runtime, SeleniumBase y QCC | `WEB`, `QCC`; SeleniumBase/CDP, ownership, runtime, DOM First, QCC, Bridge, contexto operativo de presentación y cierre integral de automatizaciones administrativas. |
| `05_AUTO_TWIN_SITE_ARCHITECTURE.md` | Site Architecture y AUTO TWIN | `SITE`, `TWIN`; contratos de sede, Discovery, reconciliación con `ProcedureContract`, geometría JIT, HUMAN_ONLY, LABS, AUTO TWIN, REAL ↔ TWIN y certificación progresiva. |
| `06_ESTADO_ROADMAP_ECOSISTEMA.md` | Estado y roadmap | Estado técnico transversal, auditorías, deuda, métricas, FCP, UWT, mejoras QCC y planificación operativa histórica. |

---

# 2. REGISTRO CANÓNICO DE DECISIONES

## Gobierno, desarrollo, Git, Fabric y seguridad

| ID | Decisión | Estado | Fuente primaria | Fuente maestra |
|---|---|---|---|---|
| `GOV-001` | Modelo de Dirección Técnica Tripartita y Separación de Roles | MODIFICADA PARCIALMENTE | `20260912_resolucion_modelo_direccion_tecnica_y_ejecucion_claude.md` | `01` |
| `GOV-002` | Modelo de Ejecución Multiproveedor bajo Dirección Técnica Única | VIGENTE | `20261005_resolucion_fabric_multiproveedor_orquestacion_y_cierre_provider_neutral.md` | `01` |
| `DEV-001` | Formato Inicial de Entregas por Reemplazo Completo de Archivos | MODIFICADA | `001_metodologia_trabajo.md` | `01` |
| `DEV-002` | Metodología Oficial QA-DEV-001 de Diagnóstico Incremental y Parches Bash | VIGENTE | `016_sistema_trabajo.md` | `01` |
| `DEV-003` | Blindaje del Código mediante Suites de Tests, Clean-Install y Dataset Contractual | VIGENTE | `20260809_resolucion_blindaje_codigo_auditorias_y_tests_robustos.md` | `01` |
| `DEV-004` | Prevención de Deuda Técnica y Boy Scout Rule Controlada | VIGENTE | `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` | `01` |
| `GIT-001` | Política Oficial de Ramas Git y Protección de la Rama Estable | VIGENTE | `012_gobierno_codigo_y_ramas_git.md` | `01` |
| `GIT-002` | Desarrollo por Tuberías Continuas, Worktrees Paralelos y Regla CLAUDE CLOSED | MODIFICADA | `20260914_resolucion_sistema_hibrido_tuberias_worktrees_claude.md` | `01` |
| `GIT-003` | Cierre Provider-Neutral, Ownership y Paralelización Segura | VIGENTE | `20261005_resolucion_fabric_multiproveedor_orquestacion_y_cierre_provider_neutral.md` | `01` |
| `FAB-001` | Work Orders como Unidad Canónica de Especificación y Trabajo | MODIFICADA PARCIALMENTE | `20260912_resolucion_modelo_direccion_tecnica_y_ejecucion_claude.md` | `01` |
| `FAB-002` | Fabric como Orquestador Principal y Provider-Neutral | VIGENTE | `20261005_resolucion_fabric_multiproveedor_orquestacion_y_cierre_provider_neutral.md` | `01` |
| `SEC-001` | Prohibición de Versionar Secretos, Credenciales y Certificados en Git | VIGENTE | `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` | `01` |

## Arquitectura, datos y frontend

| ID | Decisión | Estado | Fuente primaria | Fuente maestra |
|---|---|---|---|---|
| `ARCH-001` | Separación Estricta de Capas | VIGENTE | `001_metodologia_trabajo.md` | `02` |
| `ARCH-002` | Estructura Física del Repositorio | VIGENTE | `013_estructura_repositorio.md` | `02` |
| `ARCH-003` | Prohibición de Rutas Absolutas Personales | VIGENTE | `001_metodologia_trabajo.md` | `02` |
| `ARCH-004` | Arquitectura Híbrida Cloud / Agentes Locales | VIGENTE | `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` | `02` |
| `ARCH-005` | `ProcedureContract` como Definición Canónica Integral del Procedimiento Administrativo | VIGENTE | `20261010_resolucion_modelo_integral_automatizaciones_administrativas.md` | `02` |
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
| `DOC-001` | El ERP SOLO observa Box, NUNCA manipula Box | MODIFICADA PARCIALMENTE | `011_sistema_documental_box_vigilancia.md` | `03` |
| `DOC-002` | Clasificación Documental de Extranjería e Invalidez de Resguardos | VIGENTE | `014_resolucion_box_extranjeria_v1.md` | `03` |
| `DOC-003` | Copia Bidireccional Controlada ERP ↔ Box y Watchdog/Listener Documental | VIGENTE | `20261005_resolucion_box_copia_bidireccional_controlada.md` | `03` |
| `DOC-004` | Motor Documental Semántico: Nomenclaturas, Roles, Grupos, Readiness, Snapshots y Eventos | VIGENTE | `20260801_resolucion_sistema_nomenclaturas_y_hoja_ruta.md` | `03` |
| `DOC-005` | Transición Legacy → Semántico mediante Activación Progresiva y Pilotos | VIGENTE | `20260801_resolucion_sistema_nomenclaturas_y_hoja_ruta.md` | `03` |
| `DOC-006` | Target Presentation Folder como Selección Documental Canónica de una Presentación | VIGENTE | `20261010_resolucion_panel_qcc_obligatorio_contexto_operativo_automatizaciones_administrativas.md` | `03` |
| `KNOW-001` | Flujo Circular Operativo del Cliente y Generación de Conocimiento | MODIFICADA | `015_flujo_circular_cliente.md` | `03` |
| `KNOW-002` | Supervisión Jurídica Humana Obligatoria sobre Criterios de IA | VIGENTE | `015_flujo_circular_cliente.md` | `03` |
| `KNOW-003` | Knowledge Nativo como Plataforma de Conocimiento del Ecosistema Quesada Abogados | VIGENTE | `20261005_resolucion_knowledge_nativo_y_gobierno_de_conocimiento.md` | `03` |
| `KNOW-004` | Flujo Circular del Cliente V2 y Aprendizaje Multibucle | VIGENTE | `20261007_resolucion_flujo_circular_cliente_v2_y_gobierno_omnicanal_leads.md` | `03` |
| `OPS-001` | Flujo Operativo del Cliente y Hojas de Encargo | VIGENTE | `002_funcionamiento_negocio.md` | `03` |
| `OPS-002` | Integración de Herramientas Externas mediante CSV | MODIFICADA PARCIALMENTE | `003_ecosistema_tecnologico.md` | `03` |
| `OPS-003` | TASK como Unidad Canónica de Trabajo y CAA como Centro Operativo | VIGENTE | `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md` | `03` |
| `OPS-004` | Enrutamiento de Eventos de Dominio a Notificaciones, Calendar y CAA | VIGENTE | `20260801_resolucion_sistema_nomenclaturas_y_hoja_ruta.md` | `03` |
| `OPS-005` | Lead Omnicanal como Unidad Canónica del Ciclo Comercial | VIGENTE | `20261007_resolucion_flujo_circular_cliente_v2_y_gobierno_omnicanal_leads.md` | `03` |
| `OPS-006` | Lifecycle Comercial y Conversión Lead → Cliente → Expediente | VIGENTE | `20261007_resolucion_flujo_circular_cliente_v2_y_gobierno_omnicanal_leads.md` | `03` |

## Automatización web y QCC

| ID | Decisión | Estado | Fuente primaria | Fuente maestra |
|---|---|---|---|---|
| `WEB-001` | Infraestructura Común de Automatización SeleniumBase / CDP | VIGENTE | `20260815_resolucion_arquitectura_y_gobierno_infraestructura_seleniumbase_cdp.md` | `04` |
| `WEB-002` | Prohibición de SeleniumBase en el Frontend | VIGENTE | `20260815_resolucion_arquitectura_y_gobierno_infraestructura_seleniumbase_cdp.md` | `04` |
| `WEB-003` | Principio DOM First y Fallback Gobernado | VIGENTE | `20260815_resolucion_arquitectura_y_gobierno_infraestructura_seleniumbase_cdp.md` | `04` |
| `WEB-004` | Prohibición de `os._exit()` en Producción y Aislamiento de Runtimes | VIGENTE | `20260815_resolucion_arquitectura_y_gobierno_infraestructura_seleniumbase_cdp.md` | `04` |
| `WEB-005` | Cierre Integral Obligatorio de Automatizaciones Administrativas | VIGENTE | `20261010_resolucion_modelo_integral_automatizaciones_administrativas.md` | `04` |
| `WEB-006` | Aportación Documental Manual Asistida por QCC en la Fase Actual | VIGENTE | `20261010_resolucion_panel_qcc_obligatorio_contexto_operativo_automatizaciones_administrativas.md` | `04` |
| `QCC-001` | Quesada Chrome Companion como Interfaz Contextual | VIGENTE | `20260821_resolucion_quesada_chrome_companion_qcc.md` | `04` |
| `QCC-002` | Arquitectura de Comunicación mediante QCC Bridge | VIGENTE | `20260821_resolucion_quesada_chrome_companion_qcc.md` | `04` |
| `QCC-003` | No Interferencia Directa con el DOM en QCC V1 | VIGENTE | `20260821_resolucion_quesada_chrome_companion_qcc.md` | `04` |
| `QCC-004` | Augmentación DOM Controlada, Reversible y Contextual | VIGENTE | `20261005_resolucion_qcc_v2_augmentacion_dom_teaching_mode.md` | `04` |
| `QCC-005` | Teaching Mode Gobernado para Adquisición de Contratos de Interacción | VIGENTE | `20261005_resolucion_qcc_v2_augmentacion_dom_teaching_mode.md` | `04` |
| `QCC-006` | Panel QCC Obligatorio y `QccPresentationContext` para Automatizaciones Administrativas | VIGENTE | `20261010_resolucion_panel_qcc_obligatorio_contexto_operativo_automatizaciones_administrativas.md` | `04` |

## Site Architecture y AUTO TWIN

| ID | Decisión | Estado | Fuente primaria | Fuente maestra |
|---|---|---|---|---|
| `SITE-001` | QCC Site Architecture y Contratos de Sede | VIGENTE | `20260822_resolucion_qcc_site_architecture_dom_geometry_interaction.md` | `05` |
| `SITE-002` | Capa Geométrica JIT y Prohibición de Coordenadas Fijas | VIGENTE | `20260822_resolucion_qcc_site_architecture_dom_geometry_interaction.md` | `05` |
| `SITE-003` | Clasificación Estricta de Políticas HUMAN_ONLY | VIGENTE | `20260822_resolucion_qcc_site_architecture_dom_geometry_interaction.md` | `05` |
| `SITE-004` | Discovery y Site Architecture como Capa de Evidencia y Reconciliación del Procedimiento | VIGENTE | `20261010_resolucion_modelo_integral_automatizaciones_administrativas.md` | `05` |
| `TWIN-001` | Institución del Sistema LABS de Sedes Electrónicas | VIGENTE | `20260822_resolucion_sistema_labs_sedes_electronicas.md` | `05` |
| `TWIN-002` | Método Manual Ordinario de Construcción de LABS | SUPERADA PARCIALMENTE | `20260822_resolucion_sistema_labs_sedes_electronicas.md` | `05` |
| `TWIN-003` | Capacidad AUTO TWIN y Fidelidad en Rendering Profile | VIGENTE | `20260905_resolucion_qcc_auto_twin_arquitectura_fidelidad_sincronizacion.md` | `05` |
| `TWIN-004` | Aislamiento de Producción, Datos Ficticios y Guardas Localhost | VIGENTE | `20260822_resolucion_sistema_labs_sedes_electronicas.md` | `05` |
| `TWIN-005` | Validación Obligatoria REAL ↔ TWIN para Promoción de Revisiones | VIGENTE | `20260905_resolucion_qcc_auto_twin_arquitectura_fidelidad_sincronizacion.md` | `05` |
| `TWIN-006` | Runtime TWIN Gobernado de Preproducción | VIGENTE | `20261005_resolucion_runtime_twin_gobernado_preproduccion.md` | `05` |
| `TWIN-007` | AUTO TWIN como Infraestructura Horizontal de Certificación Progresiva | VIGENTE | `20261010_resolucion_modelo_integral_automatizaciones_administrativas.md` | `05` |

---

# 3. CONTROL DEL REGISTRO

**TOTAL DECISIONES:** 69
**VIGENTES:** 60
**MODIFICADAS:** 8
**SUPERADAS PARCIALMENTE:** 1
**CON DUDA:** 0

Comprobación:

`60 + 8 + 1 = 69`

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
28. `20261005_resolucion_fabric_multiproveedor_orquestacion_y_cierre_provider_neutral.md` → `GOV-002`, `GIT-003`, `FAB-002`
29. `20261005_resolucion_knowledge_nativo_y_gobierno_de_conocimiento.md` → `KNOW-003` y modifica `KNOW-001`
30. `20261005_resolucion_runtime_twin_gobernado_preproduccion.md` → `TWIN-006`
31. `20261005_resolucion_box_copia_bidireccional_controlada.md` → `DOC-003` y modifica parcialmente `DOC-001`
32. `20261005_resolucion_qcc_v2_augmentacion_dom_teaching_mode.md` → `QCC-004`, `QCC-005`
33. `20260801_resolucion_sistema_nomenclaturas_y_hoja_ruta.md` → `DOC-004`, `DOC-005`, `OPS-004`
34. `20261007_resolucion_flujo_circular_cliente_v2_y_gobierno_omnicanal_leads.md` → `KNOW-004`, `OPS-005`, `OPS-006`; modifica/amplía `KNOW-001`, modifica parcialmente `OPS-002` y complementa `OPS-001`
35. `20261010_resolucion_modelo_integral_automatizaciones_administrativas.md` → `ARCH-005`, `WEB-005`, `SITE-004`, `TWIN-007`; desarrolla y reafirma `ARCH-001`, `DATA-009`, `UI-001`, `WEB-001`, `WEB-002`, `SITE-001`, `SITE-003`, `TWIN-001`, `TWIN-003`, `TWIN-005` y `TWIN-006`
36. `20261010_resolucion_panel_qcc_obligatorio_contexto_operativo_automatizaciones_administrativas.md` → `DOC-006`, `WEB-006`, `QCC-006`; complementa `ARCH-005`, desarrolla `WEB-005`, `QCC-001`, `QCC-002`, `QCC-004`, `DOC-003`, `DOC-004` y `TWIN-007`

---

# 5. MAPA DECISIÓN → FUENTE Y EVOLUCIÓN

## Gobierno y desarrollo

- `GOV-001` → Primaria: `20260912_resolucion_modelo_direccion_tecnica_y_ejecucion_claude.md` → modificada parcialmente por `20261005_resolucion_fabric_multiproveedor_orquestacion_y_cierre_provider_neutral.md`.
- `GOV-002` → `20261005_resolucion_fabric_multiproveedor_orquestacion_y_cierre_provider_neutral.md`.
- `DEV-001` → Primaria: `001_metodologia_trabajo.md` → modificada por `016_sistema_trabajo.md`.
- `DEV-002` → Primaria: `016_sistema_trabajo.md` → desarrollada posteriormente por resoluciones de gobierno, dirección técnica y tuberías.
- `DEV-003` → Primaria: `20260809_resolucion_blindaje_codigo_auditorias_y_tests_robustos.md`.
- `DEV-004` → Primaria: `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md`.
- `GIT-001` → Primaria: `012_gobierno_codigo_y_ramas_git.md`.
- `GIT-002` → Primaria: `20260914_resolucion_sistema_hibrido_tuberias_worktrees_claude.md` → modificada por `20261005_resolucion_fabric_multiproveedor_orquestacion_y_cierre_provider_neutral.md`.
- `GIT-003` → `20261005_resolucion_fabric_multiproveedor_orquestacion_y_cierre_provider_neutral.md`.
- `FAB-001` → Primaria: `20260912_resolucion_modelo_direccion_tecnica_y_ejecucion_claude.md` → modificada parcialmente por `20261005_resolucion_fabric_multiproveedor_orquestacion_y_cierre_provider_neutral.md`.
- `FAB-002` → `20261005_resolucion_fabric_multiproveedor_orquestacion_y_cierre_provider_neutral.md`.
- `SEC-001` → Primaria: `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md`.

## Arquitectura, datos y frontend

- `ARCH-001` → `001_metodologia_trabajo.md` / `004_frontend_flet.md`, desarrollada posteriormente por `013` y resolución de gobierno de código.
- `ARCH-002` → `013_estructura_repositorio.md`.
- `ARCH-003` → `001_metodologia_trabajo.md`.
- `ARCH-004` → `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md`.
- `ARCH-005` → `20261010_resolucion_modelo_integral_automatizaciones_administrativas.md`.
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

- `DOC-001` → `011_sistema_documental_box_vigilancia.md` → modificada parcialmente por `20261005_resolucion_box_copia_bidireccional_controlada.md`.
- `DOC-002` → `014_resolucion_box_extranjeria_v1.md`; permanece vigente.
- `DOC-003` → `20261005_resolucion_box_copia_bidireccional_controlada.md`.
- `DOC-004` → `20260801_resolucion_sistema_nomenclaturas_y_hoja_ruta.md`.
- `DOC-005` → `20260801_resolucion_sistema_nomenclaturas_y_hoja_ruta.md`.
- `DOC-006` → `20261010_resolucion_panel_qcc_obligatorio_contexto_operativo_automatizaciones_administrativas.md`.
- `KNOW-001` → `015_flujo_circular_cliente.md` → modificada por `20261005_resolucion_knowledge_nativo_y_gobierno_de_conocimiento.md` y ampliada por `20261007_resolucion_flujo_circular_cliente_v2_y_gobierno_omnicanal_leads.md`.
- `KNOW-002` → `015_flujo_circular_cliente.md`; permanece vigente sin modificación.
- `KNOW-003` → `20261005_resolucion_knowledge_nativo_y_gobierno_de_conocimiento.md`.
- `KNOW-004` → `20261007_resolucion_flujo_circular_cliente_v2_y_gobierno_omnicanal_leads.md`.
- `OPS-001` → `002_funcionamiento_negocio.md` → complementada por `20261007_resolucion_flujo_circular_cliente_v2_y_gobierno_omnicanal_leads.md`.
- `OPS-002` → `003_ecosistema_tecnologico.md` → modificada parcialmente por `20261007_resolucion_flujo_circular_cliente_v2_y_gobierno_omnicanal_leads.md` mediante `OPS-005`.
- `OPS-003` → `20260809_resolucion_gobierno_codigo_y_prevencion_deuda_tecnica.md`.
- `OPS-004` → `20260801_resolucion_sistema_nomenclaturas_y_hoja_ruta.md`.
- `OPS-005` → `20261007_resolucion_flujo_circular_cliente_v2_y_gobierno_omnicanal_leads.md`.
- `OPS-006` → `20261007_resolucion_flujo_circular_cliente_v2_y_gobierno_omnicanal_leads.md`.

## Browser / QCC

- `WEB-001` → `20260815_resolucion_arquitectura_y_gobierno_infraestructura_seleniumbase_cdp.md`.
- `WEB-002` → misma resolución.
- `WEB-003` → misma resolución, desarrollada por Site Architecture.
- `WEB-004` → misma resolución.
- `WEB-005` → `20261010_resolucion_modelo_integral_automatizaciones_administrativas.md`.
- `WEB-006` → `20261010_resolucion_panel_qcc_obligatorio_contexto_operativo_automatizaciones_administrativas.md`.
- `QCC-001` → `20260821_resolucion_quesada_chrome_companion_qcc.md`.
- `QCC-002` → misma resolución.
- `QCC-003` → misma resolución y limitado expresamente al alcance QCC V1.
- `QCC-004` → `20261005_resolucion_qcc_v2_augmentacion_dom_teaching_mode.md`.
- `QCC-005` → `20261005_resolucion_qcc_v2_augmentacion_dom_teaching_mode.md`.
- `QCC-006` → `20261010_resolucion_panel_qcc_obligatorio_contexto_operativo_automatizaciones_administrativas.md`.

## Site Architecture / AUTO TWIN

- `SITE-001` → `20260822_resolucion_qcc_site_architecture_dom_geometry_interaction.md`.
- `SITE-002` → misma resolución.
- `SITE-003` → misma resolución.
- `SITE-004` → `20261010_resolucion_modelo_integral_automatizaciones_administrativas.md`.
- `TWIN-001` → `20260822_resolucion_sistema_labs_sedes_electronicas.md`.
- `TWIN-002` → misma resolución, superada parcialmente por `20260905_resolucion_qcc_auto_twin_arquitectura_fidelidad_sincronizacion.md`.
- `TWIN-003` → `20260905_resolucion_qcc_auto_twin_arquitectura_fidelidad_sincronizacion.md`.
- `TWIN-004` → `20260822_resolucion_sistema_labs_sedes_electronicas.md`, reafirmada por AUTO TWIN.
- `TWIN-005` → `20260905_resolucion_qcc_auto_twin_arquitectura_fidelidad_sincronizacion.md`.
- `TWIN-006` → `20261005_resolucion_runtime_twin_gobernado_preproduccion.md`.
- `TWIN-007` → `20261010_resolucion_modelo_integral_automatizaciones_administrativas.md`.

---

# 6. DECISIONES MODIFICADAS O SUPERADAS

## DOC-001 → MODIFICADA PARCIALMENTE

**Origen:** `011_sistema_documental_box_vigilancia.md`
**Modificada por:** `20261005_resolucion_box_copia_bidireccional_controlada.md` → `DOC-003`

Se mantiene la finalidad de proteger la integridad de Box y continúan prohibidas por defecto las operaciones destructivas o de reorganización sobre objetos existentes.

Queda sustituida la prohibición absoluta de escritura: el ERP puede crear copias nuevas controladas y trazables ERP ↔ Box mediante el servicio documental gobernado, con deduplicación, verificación y destinos autorizados.

No quedan autorizados por defecto `delete`, `move`, `rename`, sobrescritura silenciosa ni reorganización automática de Box.

---

## KNOW-001 → MODIFICADA

**Origen:** `015_flujo_circular_cliente.md`
**Modificada por:** `20261005_resolucion_knowledge_nativo_y_gobierno_de_conocimiento.md` → `KNOW-003`; ampliada por `20261007_resolucion_flujo_circular_cliente_v2_y_gobierno_omnicanal_leads.md` → `KNOW-004`.

Se mantienen el aprendizaje continuo, la anonimización/minimización, la extracción de hechos y criterios, la validación humana y la reutilización del conocimiento.

Queda sustituida la dependencia operativa de NotebookLM por Knowledge nativo. Además, el flujo circular evoluciona desde un círculo lineal hacia un modelo multibucle y longitudinal que conecta captación, Lead omnicanal, lifecycle comercial, Cliente, Expediente, operación, resultado, Knowledge, contenido y nuevas necesidades.

---

## OPS-002 → MODIFICADA PARCIALMENTE

**Origen:** `003_ecosistema_tecnologico.md`
**Modificada por:** `20261007_resolucion_flujo_circular_cliente_v2_y_gobierno_omnicanal_leads.md` → `OPS-005`

Se mantiene HubSpot como herramienta externa de captación/comercial e integración y se mantiene íntegramente la función contable de Holded.

Queda modificada la autoridad comercial: cuando exista el dominio Lead nativo del CRM, Quesada Abogados CRM es la autoridad canónica del Lead; HubSpot pasa a ser canal, fuente, herramienta o integración y no una fuente de verdad competidora.

---

## GOV-001 → MODIFICADA PARCIALMENTE

**Origen:** `20260912_resolucion_modelo_direccion_tecnica_y_ejecucion_claude.md`
**Modificada por:** `20261005_resolucion_fabric_multiproveedor_orquestacion_y_cierre_provider_neutral.md` → `GOV-002`

Se mantienen Dirección Humana, ChatGPT como Dirección Técnica y la separación entre dirección y ejecución.

Se sustituye la identificación de Claude como ejecutor técnico único por una capa multiproveedor gobernada mediante Fabric.

---

## GIT-002 → MODIFICADA

**Origen:** `20260914_resolucion_sistema_hibrido_tuberias_worktrees_claude.md`
**Modificada por:** `20261005_resolucion_fabric_multiproveedor_orquestacion_y_cierre_provider_neutral.md` → `GIT-003`

Se conservan worktrees desacoplados, ownership, prevención de colisiones y prohibición de reapertura manual ad hoc.

`CLAUDE CLOSED` conserva valor histórico, pero el cierre futuro pasa a ser provider-neutral y basado en tests, evidencia, auditoría y promoción gobernada.

---

## FAB-001 → MODIFICADA PARCIALMENTE

**Origen:** `20260912_resolucion_modelo_direccion_tecnica_y_ejecucion_claude.md`
**Modificada por:** `20261005_resolucion_fabric_multiproveedor_orquestacion_y_cierre_provider_neutral.md` → `FAB-002`

La Work Order continúa siendo la unidad principal de especificación y trabajo.

Se elimina su dependencia innecesaria de un proveedor concreto y se integra como contrato provider-neutral ejecutable mediante Fabric/Runner.

---

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

# 9. CONFLICTOS Y EVOLUCIONES DOCUMENTALES

La evolución Fabric multiproveedor queda formalmente resuelta por `20261005_resolucion_fabric_multiproveedor_orquestacion_y_cierre_provider_neutral.md` mediante `GOV-002`, `GIT-003` y `FAB-002`.

Las incompatibilidades históricas ya resueltas o modeladas incluyen:

- `DEV-001` → `DEV-002`
- `DATA-003` → `DATA-004`
- `TWIN-002` → `TWIN-003`
- `GOV-001` → `GOV-002`
- `GIT-002` → `GIT-003`
- `FAB-001` → `FAB-002`

La evolución de Knowledge hacia módulo nativo queda formalmente resuelta por `20261005_resolucion_knowledge_nativo_y_gobierno_de_conocimiento.md` mediante `KNOW-003`, modificando `KNOW-001` y manteniendo `KNOW-002` vigente.

La evolución del Flujo Circular del Cliente V2 y del gobierno omnicanal de Leads queda formalizada por `20261007_resolucion_flujo_circular_cliente_v2_y_gobierno_omnicanal_leads.md` mediante `KNOW-004`, `OPS-005` y `OPS-006`; amplía `KNOW-001`, modifica parcialmente `OPS-002` y complementa `OPS-001`.

El runtime TWIN local de preproducción queda formalmente gobernado por `20261005_resolucion_runtime_twin_gobernado_preproduccion.md` mediante `TWIN-006`, manteniendo vigentes `TWIN-003`, `TWIN-004` y `TWIN-005`.

La evolución QCC V2 queda formalmente resuelta por `20261005_resolucion_qcc_v2_augmentacion_dom_teaching_mode.md` mediante `QCC-004` y `QCC-005`. `QCC-003` permanece vigente para QCC V1; QCC V2 queda autorizado únicamente dentro del contrato de augmentación controlada, reversible, fail-open y Teaching Mode gobernado.

La divergencia documental Box `011 ↔ 016` queda resuelta por `20261005_resolucion_box_copia_bidireccional_controlada.md` mediante `DOC-003`: `DOC-001` pasa a MODIFICADA PARCIALMENTE, se autoriza copia bidireccional controlada ERP ↔ Box y se mantienen prohibidas por defecto las operaciones destructivas sobre objetos existentes.

---

# 10. FUENTES MAESTRAS

## Aprobadas

- `00_MASTER_INDEX.md`
- `01_GOBIERNO_DESARROLLO_FABRIC.md`
- `02_ARQUITECTURA_ERP_DATOS.md`
- `03_DOCUMENTAL_KNOWLEDGE_OPERACIONES.md`
- `04_QCC_BROWSER_AUTOMATION.md`
- `05_AUTO_TWIN_SITE_ARCHITECTURE.md`
- `06_ESTADO_ROADMAP_ECOSISTEMA.md`

El protocolo `000_PROTOCOLO_CONSOLIDACION_NOTEBOOKLM.md` permanece como documento metadocumental de gobierno de consolidación.

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
**DECISIONES CANÓNICAS:** 69
**DIVERGENCIAS DOCUMENTALES ABIERTAS:** 0
**FUENTES MAESTRAS TEMÁTICAS:** 6
**PROTOCOLO METADOCUMENTAL:** 1

Este índice constituye el mapa operativo de trazabilidad del corpus consolidado de Quesada Abogados.
