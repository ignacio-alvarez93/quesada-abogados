# WO-DV28-CIERRE · Visor → Bandeja → Box

**Rama:** `fix/dv28-cierre-visor-bandeja` (worktree propio, base `48a1198`).
**Gate real:** `EXECUTION_ENABLED = False`, `H3_WRITE_CONTAINMENT_VERIFIED = False`. **Box REAL NO habilitado.**

> **Evidencia de ejecución: PENDIENTE DEL RUNNER.** Sesión sin terminal: no se ha ejecutado pytest,
> `compileall` ni `git diff --check`, y no se ha creado commit. Los tests se escribieron leyendo el código real.

**Objetivo:** un solo motor de copia y dos puntos de entrada, Bandeja y visor.

## Diagnóstico

- Bandeja (`frontend/views/document_inbox_view.py::copy_to_box`) llama a
  `document_inbox_service.copy_inbox_item_to_expedient_box(item, expedient_id=, subfolder=, target_filename=)`.
- El visor ya llamaba a la misma función, pero envuelta en dos capas DV27 que Bandeja no usa:
  - **H1**: `document_viewer_archive_permission_service.authorize_archive`, con `APPROVED_CONTRACT = None` ⇒ siempre DENIED.
  - **H2**: `document_viewer_archive_repository.run_intent`. Exigía una tabla migrada (`document_viewer_archive_intents`)
    y `SINGLE_HOST_APPROVED`/`MULTI_HOST_GUARANTEE`, ambos False.
- Con el gate abierto, esas capas seguían bloqueando la copia (`PERMISSION_PENDING`, `INTENTS_UNAVAILABLE`,
  `MULTI_HOST_PENDING`).

## Cambio

`backend/services/document_viewer_box_archive_service.py` (único archivo de producción tocado):

- Se eliminan las importaciones y usos de `permission` e `intents`, además de `_authorize`, `_shared_authority`,
  `_intent_store`, `_governed_copy`, `SINGLE_HOST_APPROVED` y los mensajes y códigos asociados.
- `_certified_copy` hace **la única** llamada a `copy_inbox_item_to_expedient_box(item, expedient_id=, subfolder=,
  nomenclature_key=)` y traduce la respuesta:
  - `BoxCopyIncomplete` ⇒ `incomplete` y el lote se detiene. El archivo se conserva.
  - `ValueError`/`BoxCopyRejected`/`FileNotFoundError` ⇒ `rejected`. No se escribió nada.
  - Cualquier otro error ⇒ `failed` y el lote se detiene.
  - Éxito ⇒ `_confirmed` (sin cambios).
- `_confirmed`: un resultado `already_copied` del motor (otra operación lo registró antes) ⇒ `rejected` con
  `ALREADY_COPIED`, en vez de `failed`.
- `execution_blocker()` depende solo de `EXECUTION_ENABLED is True`. `activation_blockers()` solo devuelve
  `TOCTOU_PREVENTION_PENDING` mientras no exista la prueba real supervisada con Box Drive.
- No cambian `document_inbox_service.py`, el diálogo, el planificador P3A ni la vista de Bandeja.

**Se conserva en el visor:**

- Sesión verificada (usuario activo de la BD).
- Documento de Bandeja ya vinculado al mismo cliente y expediente.
- Carpeta existente revisada y nomenclatura del catálogo.
- Nombre proyectado y huella (`fingerprint`), con consentimiento explícito sobre esa huella.
- Caducidad de la revisión (15 min).
- Revisión completa al ejecutar.
- Revalidación por documento justo antes de su copia.
- Rechazo de rutas no autorizadas.
- Ante el doble clic: lock del plan, token consumido y claim por ítem en memoria, más el lock por ítem del motor.
- Resultado por documento comprobado contra la respuesta real del motor.

**Garantías del motor (sin cambios):**

- COPY → VERIFY → REGISTER.
- Creación exclusiva `xb`, sin sobrescribir ni borrar.
- Fijación H3 de carpetas en Windows.
- REGISTER con CAS.
- Original intacto.

## Tests

- **Nuevo:** `scripts/tests/test_dv28_viewer_reuse.py`
  - `EntryPointTests`: una llamada al motor por punto de entrada, ninguna en el diálogo; gate cerrado; sin capas DV27.
  - `ViewerReuseTests`:
    - PDF y JPG: nombre, carpeta y extensión; original intacto.
    - Archivo preexistente intacto (`_2`).
    - Consentimiento obligatorio y repetición de solicitud.
    - Fallo de escritura (parcial conservado, lote detenido, reintento con `_2`).
    - Fallo de registro (copia conservada; una revisión nueva la registra una vez, sin archivo nuevo).
    - Error inesperado ⇒ `failed`.
    - Gate cerrado ⇒ nada escrito.
    - Validación de documento, expediente y carpeta.
    - Copia hecha desde Bandeja ⇒ el visor la rechaza como ya copiada.
  - `BandejaButtonTests`: el botón real de Bandeja copia PDF y JPG una vez, con el gate del visor cerrado.
- **Adaptados** (solo los supuestos H1/H2 sustituidos):
  - `test_document_viewer_dv25_box_from_viewer.py::ArchiveBase` ya no instala contrato, ni migra la BD temporal, ni
    fija `SINGLE_HOST_APPROVED`. Sus tests de ejecución, revisión, diálogo y concurrencia quedan intactos.
  - `test_dv27_box_copy_activation.py`, reescrito. Cada garantía DV27 tiene equivalente:
    - Gate y precondiciones ⇒ `GateTests` (gate cerrado; H3 real pendiente; los módulos DV27 siguen sin conceder nada).
    - H1 ⇒ `SessionTests`: actor ausente, falsificado, desconocido o inactivo y claims del cliente ⇒ nada copiado.
    - H2 ⇒ `ReplayTests`: doble clic, nueva revisión y dos operaciones paralelas sin el guard del visor ⇒ una sola copia.
    - Caídas ⇒ `CrashTests`: antes, durante, entre VERIFY y REGISTER, y después. Nunca se borra ni sobrescribe, se
      registra una sola vez y la revisión interrumpida no se reejecuta.
    - Seguridad de destino y diálogo ⇒ sin cambios funcionales.
  - **Eliminados con su capa:** los tests de rechazo por contrato ausente, almacén sin migrar y `SINGLE_HOST_APPROVED`
    en el visor, y el de dos BD que no coordinan. Las pruebas de los propios módulos H1/H2 en
    `test_document_viewer_dv25_security.py` siguen intactas.

## Comandos para el Runner

```
python -m pytest -q -rsx scripts/tests/test_dv28_viewer_reuse.py scripts/tests/test_dv27_box_copy_activation.py scripts/tests/test_document_viewer_dv25_box_from_viewer.py
python -m pytest -q -rsx scripts/tests/test_dv28_box_copy_containment.py scripts/tests/test_document_viewer_dv25_box_hardening.py scripts/tests/test_dv25_bandeja_compat.py scripts/tests/test_document_viewer_dv25_security.py
python -m pytest -q -rsx scripts/tests/test_document_viewer_dv23_close.py scripts/tests/test_document_viewer_dv23_pdf_tools.py scripts/tests/test_document_viewer_dv23_visual.py scripts/tests/test_document_viewer_dv24_linking.py scripts/tests/test_document_viewer_dv24_multidoc.py scripts/tests/test_document_viewer_dv24_notes.py scripts/tests/test_document_viewer_dv25_filing_plan.py scripts/tests/test_document_viewer_dv25_selection.py scripts/tests/test_document_viewer_dv25_toolbar.py scripts/tests/test_dv25_documental_smoke.py scripts/tests/test_dv26_link_visual.py
python -m compileall -q backend/services/document_viewer_box_archive_service.py scripts/tests/test_dv28_viewer_reuse.py scripts/tests/test_dv27_box_copy_activation.py scripts/tests/test_document_viewer_dv25_box_from_viewer.py
git diff --check
git status --porcelain
```

## Riesgos pendientes

1. **Sin coordinación entre equipos.** La protección contra doble ejecución es solo de proceso (claim del visor y lock
   del motor). Si dos PCs archivan el mismo documento a la vez sobre la misma BD, el motor no sobrescribe (crea `_2`)
   y su CAS registra una sola copia. La otra queda como `incomplete`, conservada para revisión humana. Con una BD
   por PC no hay coordinación alguna. Usar solo el PC del despacho es un criterio de despliegue, no un aislamiento
   técnico.
2. **Sin solicitud persistente.** Tras una caída entre VERIFY y REGISTER, la siguiente revisión registra la copia
   existente (`reused_identical`) en lugar de enviarla a revisión. Es el comportamiento de Bandeja, sin archivos nuevos.
3. **Código DV27 sin uso desde el visor.** `document_viewer_archive_permission_service.py`,
   `document_viewer_archive_repository.py` y su migración siguen en el árbol. Retirarlos exige una WO aparte.
4. **Activación.** La prueba real con Box Drive (handles sin `FILE_SHARE_DELETE` y filtro de nube) sigue pendiente,
   igual que poner `H3_WRITE_CONTAINMENT_VERIFIED`/`EXECUTION_ENABLED = True` con autorización específica.
5. **Riesgos DV28-SIMPLE heredados** (rename de ancestros en NTFS, unidades de red mapeadas): siguen pendientes de
   confirmación por el Runner.
