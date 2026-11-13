# DV29-WO-04 · Cierre integral herramientas JPG/PNG + regresiones PDF/DV28

**Rama:** `feature/dv29-herramientas-jpg-png` (worktree `quesada-dv29-herramientas-imagen`), sobre los checkpoints
WO-01 `e263e95` (motor), WO-02 `3a6e676` (UI), WO-03 `4e9cd71` + `9f43bc6` (imágenes → PDF multipágina).
**Box REAL:** `EXECUTION_ENABLED = False`, `H3_WRITE_CONTAINMENT_VERIFIED = False`
(`backend/services/document_viewer_box_archive_service.py`). DV29 no importa ni llama a ningún servicio de Box.

> **Evidencia de ejecución: PENDIENTE DEL RUNNER.** Esta auditoría se hizo en una sesión sin terminal: no se ha
> ejecutado pytest, `compileall`, `git diff origin/develop` ni `git diff --check`, y no se ha creado commit.
> El éxito de WO-01..03 se ha asumido por sus checkpoints en la rama, no por su evidencia del Runner. Todas las
> pruebas DV29 son sintéticas (imágenes generadas en `TemporaryDirectory`, Bandeja falsa en memoria): **el CRM real
> no se ha probado.**

## Las 7 operaciones

| # | Operación (UI) | Servicio → motor | Registro en Bandeja | Salida |
|---|---|---|---|---|
| 1 | Rotar (90/180/270, horario) | `run_image_tool("rotate")` → `rotate_image` | `image_rotate` | `storage/document_tools/images/` |
| 2 | Recortar (px, bordes exclusivos) | `run_image_tool("crop")` → copia orientada temporal → `crop_image` | `image_crop` | `.../images/` |
| 3 | Redimensionar (proporcional, LANCZOS) | `run_image_tool("resize")` → `resize_image` | `image_resize` | `.../images/` |
| 4 | Optimizar (JPG calidad 30–95; PNG sin pérdida) | `run_image_tool("optimize")` → `optimize_image` | `image_optimize` | `.../images/`; si no reduce, no se crea nada |
| 5 | Convertir JPG ↔ PNG | `run_image_tool("convert")` → `convert_image_format` | `image_convert` | `.../images/` |
| 6 | Convertir a PDF (1 página) | `run_image_tool("to_pdf")` → copia orientada/aplanada → `image_to_pdf` | `image_to_pdf` | `.../converted/` |
| 7 | Imágenes a PDF (2–30, orden confirmado) | `run_images_to_pdf` → copias orientadas/aplanadas → `images_to_pdf` | `images_to_pdf` | `.../converted/` |

Rutas de código:

- `backend/services/document_tools/image_tools_service.py` (motores; bloque «JPG/PNG editing (DV29)»).
- `backend/services/document_tools/document_viewer_image_tools_service.py` (scopes, revalidación, registro).
- `frontend/components/document_viewer_image_tools.py` (barras, formularios, `ViewerImageTools`).
- `frontend/components/pdf_tools_toolbar_adapter.py` (`with_image_tools`, `bind_selection`, `tools_kind`).
- `frontend/components/document_viewer_modal.py` (título del grupo «Herramientas de imagen», proveedor de selección).
- `frontend/views/document_inbox_view.py`, `frontend/views/expedients_view.py` (cableado de las dos vistas).

Contexto de origen: Bandeja (ítem registrado, ruta = `stored_path`, SHA-256 registrado, estados `discarded`,
`duplicate` y `error` bloqueados) y Expedientes (archivo dentro de la carpeta documental, solo lectura). Todo
derivado se registra en Bandeja con estado `pending`; desde expediente lleva `provenance` (ruta relativa y SHA-256
de cada origen). **Ningún derivado se archiva en Box automáticamente.**

## Auditoría WO-04

### Regresión negativa (revisión de código + tests existentes)

| Garantía | Dónde se cumple | Test |
|---|---|---|
| Original byte-idéntico | Motores solo leen; `run_image_tool`/`run_images_to_pdf` recalculan SHA-256 tras escribir | `tearDown` de las tres suites compara SHA-256 de todos los archivos |
| Derivado separado y sin sobrescritura | `_derived_output` + `_write_exclusive` (`xb`); nombre con timestamp + uuid | `SafetyTests.test_existing_files_are_never_overwritten`, `test_exclusive_write_refuses_an_existing_path` |
| Path / symlinks / contención | `expedient_image_scope` resuelve (sigue symlinks) y exige `_is_inside_root`; Bandeja exige ruta = `stored_path` resuelto; derivado debe quedar bajo `DOCUMENT_TOOLS_ROOT` | `test_expedient_scope_rejects_paths_outside_the_folder`, `test_inbox_scope_requires_registered_matching_processable_item` |
| Formatos falsos/corruptos/animados/vacíos | `open_editable_image`: extensión ↔ contenido real, `n_frames`, decodificación completa | `test_unsupported_corrupt_or_oversized_files_are_refused` |
| Dimensiones excesivas | 40 MB, 12 000 px/lado, 40 Mpx, comprobado en cabecera antes de `load()` y otra vez en el resultado | ídem + `test_invalid_parameters_are_reported_without_outputs` |
| Salida y registro | Fallo de registro ⇒ `ImageToolRegistrationError` con la ruta pendiente de revisión | `test_registration_failure_is_visible_and_keeps_the_derivative`, `test_registration_error_names_the_unregistered_pdf` |
| Doble click / reentrada | Formularios: `_busy` + `outcome`; `open` reutiliza el formulario abierto; multipágina: token de revisión consumido (`_claim`) | `test_double_click_and_double_submit_create_at_most_one_copy`, `test_double_click_double_submit_and_replay_create_one_copy` |
| Selección y orden | Orden = permutación exacta de las fuentes revisadas; reordenar retira el consentimiento | `test_order_must_be_the_reviewed_sources`, `test_order_pages_alpha_and_exif_in_both_contexts` |
| Mezcla de contextos | Misma vinculación cliente/expediente en Bandeja; mismo expediente en Expedientes; PDF o GIF/BMP en la selección ⇒ comando deshabilitado con motivo | `test_foreign_invalid_and_mixed_sources`, `test_incompatible_links_are_reported_from_the_viewer` |
| Callback de toolbar obsoleto | `invoke` re-resuelve documento/selección y compara con la identidad capturada | `test_stale_command_after_the_selection_changes_is_inert`, `test_queue_switches_toolbar_and_stale_commands_are_inert` |
| Pérdida de sesión/preview | El formulario conserva el scope y `run_*` lo reconstruye y compara SHA-256 antes de escribir | `test_source_is_revalidated_when_the_form_runs`, `test_sources_changed_between_review_and_confirmation` |

### Defecto corregido

- **Archivo parcial tras fallo de escritura en Recortar y Convertir a PDF.** `crop_image` e `image_to_pdf` (motores
  previos reutilizados por las operaciones 2 y 6) no borraban la salida si `save` fallaba a mitad, y el usuario
  veía «No se pudo completar» con un archivo huérfano en `storage/document_tools`. Ahora eliminan la salida
  parcial, igual que ya hacía `images_to_pdf`. Cambio mínimo en `image_tools_service.py` (sin refactor).
  Test nuevo: `SafetyTests.test_partial_crop_or_pdf_write_leaves_no_derivative` (Bandeja y Expedientes × recorte y
  PDF; ningún archivo escrito ni registrado). Las rutas de Bandeja existentes que usan estos motores
  (`crop_inbox_image`, `convert_inbox_image_to_pdf`) solo ganan esta limpieza.

### PDF y visor existente

- Las 7 herramientas PDF no cambian de lógica: `_PdfToolbar.__call__` solo delega en la barra de imagen cuando
  `handles(path)` (extensiones de imagen del visor); para PDF y otros formatos el flujo es el anterior.
  `PDF_ACTIONS`, etiquetas, `DATA_PREFIX=""` y tipos de factoría quedan cubiertos por
  `test_pdf_keeps_its_seven_tools_labels_icons_and_title` y `test_factories_keep_their_pdf_contract_types`.
- Cola, comparador, notas, vinculación: la selección del comparador se lee de `LinkController.selected` sin
  modificarla; el plegado de herramientas es el mismo (`test_fold_toggle_names_the_active_tools`).
- DV28 Box: sin cambios en `document_viewer_box_archive_service.py` ni en `document_inbox_service.py`; los
  derivados entran en Bandeja como `pending` y solo se archivarían por la acción manual existente.

## Configuración

- Dependencias: `Pillow>=10.0.0` (obligatoria; sin ella los 7 comandos aparecen deshabilitados con motivo),
  `pypdf>=6.0.0` (comprobación de páginas del PDF multipágina; si falta, se omite esa comprobación), `flet`.
- Límites: `MAX_EDITABLE_IMAGE_BYTES` 40 MB, `MAX_IMAGE_SIDE` 12 000 px, `MAX_EDITABLE_IMAGE_PIXELS` 40 Mpx,
  calidad JPG 30–95 (defecto 80), derivados JPG a calidad 95, fondo de aplanado `#FFFFFF`, 2–30 imágenes por PDF.
- Sin variables de entorno nuevas. `QUESADA_VIEWER_BOX_COPY_ENABLED` no interviene en DV29.

## Comandos para el Runner

```
python -m pytest -q -rsx scripts/tests/test_dv29_image_tools_service.py scripts/tests/test_dv29_image_tools_ui.py scripts/tests/test_dv29_images_to_pdf_viewer.py
python -m pytest -q -rsx scripts/tests/test_document_viewer_dv23_close.py scripts/tests/test_document_viewer_dv23_pdf_tools.py scripts/tests/test_document_viewer_dv23_visual.py scripts/tests/test_document_viewer_dv24_linking.py scripts/tests/test_document_viewer_dv24_multidoc.py scripts/tests/test_document_viewer_dv24_notes.py scripts/tests/test_document_viewer_dv25_filing_plan.py scripts/tests/test_document_viewer_dv25_selection.py scripts/tests/test_document_viewer_dv25_toolbar.py scripts/tests/test_dv25_documental_smoke.py scripts/tests/test_dv26_link_visual.py
python -m pytest -q -rsx scripts/tests/test_dv28_viewer_reuse.py scripts/tests/test_dv28_box_copy_containment.py scripts/tests/test_dv27_box_copy_activation.py scripts/tests/test_document_viewer_dv25_box_from_viewer.py scripts/tests/test_document_viewer_dv25_box_hardening.py scripts/tests/test_document_viewer_dv25_security.py scripts/tests/test_dv25_bandeja_compat.py
python -m pytest -q -rsx scripts/tests
python -m compileall -q backend frontend scripts/tests
git diff --check origin/develop...HEAD
git diff --stat origin/develop...HEAD
git status --porcelain
```

Scope esperado del diff frente a `origin/develop`: los seis archivos de código listados arriba, los tres tests
`test_dv29_*.py` y este documento. Cualquier otro archivo debe justificarse antes de promocionar.

## Smoke test canónico (manual, CRM real, sin Box)

Preparación: copia de la BD y de `storage/` de pruebas; gate Box cerrado (no definir
`QUESADA_VIEWER_BOX_COPY_ENABLED`). Material: un JPG de móvil con EXIF de rotación (foto vertical), un PNG con
transparencia, un JPG > 2 MB y un PDF. Anotar el SHA-256 de cada original (`Get-FileHash`).

1. **Bandeja**: importar los cuatro archivos y vincularlos al mismo cliente/expediente. Abrir el JPG en el visor.
   El grupo se titula «Herramientas de imagen» con 6 comandos; «Convertir a PNG» nombra el destino.
2. Rotar 90° derecha ⇒ mensaje con «Original intacto», nuevo `#id` en Bandeja; abrirlo: girado en sentido horario.
3. Recortar una zona ⇒ el recorte coincide con lo que se veía (orientación EXIF aplicada).
4. Redimensionar a ancho 800 ⇒ proporción conservada. Optimizar el JPG grande a calidad 60 ⇒ tamaño final menor;
   optimizar de nuevo el derivado ⇒ error visible «no reduce el tamaño», sin nuevo ítem.
5. Abrir el PNG: Convertir a JPG ⇒ fondo blanco donde había transparencia. Convertir a PDF ⇒ PDF de 1 página.
6. Abrir el PDF: siguen los 7 comandos PDF; ejecutar «Rotar páginas» en una página y comprobar el derivado.
7. Cola con JPG + PNG ⇒ «Comparador 4», marcar ambos ⇒ «Imágenes a PDF»: revisar orden, invertirlo (se desmarca
   la confirmación), confirmar y crear ⇒ PDF de 2 páginas en el orden elegido. Pulsar dos veces rápido «Crear PDF»
   ⇒ un único ítem nuevo.
8. Marcar también el PDF ⇒ «Imágenes a PDF» deshabilitado con motivo.
9. **Expedientes**: repetir 2, 5 y 7 con imágenes de la carpeta del expediente. La carpeta no cambia
   (mismo listado); los derivados aparecen en Bandeja con procedencia del expediente.
10. Notas, vinculación y plegado del visor funcionan igual antes y después de usar las herramientas.
11. Cierre: SHA-256 de todos los originales idénticos; ningún derivado nuevo en Box (carpetas Box sin cambios,
    ítems nuevos en estado `pending`).

## Riesgos no resueltos

1. **Sin ejecución en esta WO**: tests, compilación, `diff --check` y scope dependen del Runner. Si algo falla,
   la promoción queda detenida.
2. **Pruebas visuales/manuales requeridas** (no cubiertas por tests sintéticos): legibilidad de formularios a
   1366×768, orientación EXIF de fotos reales de móvil (incluidas 2/4/5/7, poco habituales), perfiles ICC/CMYK,
   PNG de 16 bits (Pillow puede saturar al pasar a JPG/PDF), aspecto del PDF en visores externos.
3. **Reintento tras error post-escritura en herramientas individuales**: si el derivado se escribió pero no se
   registró, el formulario permite reintentar y crearía otro derivado (el primero queda «pendiente de revisión»).
   Igual que las herramientas PDF; el multipágina sí lo impide con su token.
4. **Metadatos**: los derivados no conservan EXIF; se pierden fecha de captura y GPS. El perfil ICC se conserva
   en rotar, redimensionar, optimizar y convertir, pero no en recortar ni en los PDF (motores previos). Es
   intencionado para la orientación, pero debe aceptarse funcionalmente.
5. **Protección de doble ejecución solo de proceso** (lock del formulario y token en memoria), como en DV28.
6. **Deduplicación de Bandeja**: un derivado byte-idéntico a otro ya importado reutiliza el ítem existente
   (comportamiento previo de `import_file_to_inbox`).

Sin push, sin PR, sin merge: Dirección revisa y decide la promoción a `develop`.
