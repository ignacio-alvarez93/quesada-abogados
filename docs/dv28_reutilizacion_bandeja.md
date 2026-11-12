# WO-DV28-SIMPLE · Archivar desde el visor con el motor Box de Bandeja

**Base:** `develop` @ `5c87594` · **Rama:** `fix/dv28-reutilizacion-bandeja` (worktree propio).
**Gate real:** `EXECUTION_ENABLED = False`, `H3_WRITE_CONTAINMENT_VERIFIED = False`. **Box REAL NO habilitado.**
`feature/dv28-p2-mono-equipo` queda intacta como referencia; no se fusiona ni se hace cherry-pick.

> **Evidencia de ejecución: PENDIENTE DEL RUNNER.** Sesión sin terminal: no se ha ejecutado pytest,
> `compileall`, `git diff --check` ni se ha creado commit. Tampoco se pudo leer DV28-P1 (fuera del worktree),
> así que el parche H3 **no** es una reutilización auditada de DV28-P1: se escribió aquí, sobre el código de `develop`.

## Diagnóstico (antes de tocar)

- Bandeja (`frontend/views/document_inbox_view.py::copy_to_box`) y el visor
  (`document_viewer_box_archive_service._governed_copy` → `certified_copy`) ya llaman al **mismo**
  `document_inbox_service.copy_inbox_item_to_expedient_box` (COPY → VERIFY → REGISTER). No existe una segunda
  vía física: no hacía falta crear ni eliminar ningún motor.
- El diálogo `frontend/components/document_viewer_archive_dialog.py` ya ofrece documentos de Bandeja, expediente
  vinculado, carpeta existente, nomenclatura, nombre proyectado, consentimiento y resultado por documento. Sin cambios.
- El destino nunca viene de la UI como ruta: sale de `expedientes.box_folder_path` + subcarpeta relativa validada
  (`_authorized_box_root`, `_box_subfolder`, `_box_destination_folder`). Sin cambios.
- **H3 reproducible en el motor compartido** (no solo en el visor): entre `_box_destination_folder` y `open("xb")`
  una carpeta puede sustituirse por una unión y el archivo se **crea fuera** de Box; VERIFY solo lo detecta después.
  Lo reproducían `test_document_viewer_dv25_security::test_toctou_swap_after_validation_is_detected_but_not_prevented`
  y `test_dv27_box_copy_activation::test_h3_folder_swap_is_only_detected_after_the_write`. Afectaba también a Bandeja.

## Cambio (único, localizado en el motor compartido)

`backend/services/document_inbox_service.py`:

- `_pinned_box_folder(root, folder)` envuelve **solo** `_create_box_copy` (COPY + VERIFY) en `_copy_inbox_item_to_box`.
  En Windows abre la raíz Box del expediente y cada carpeta hasta el destino con `CreateFileW`
  (`FILE_READ_ATTRIBUTES`, compartición lectura/escritura **sin `FILE_SHARE_DELETE`**,
  `FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT`). Mientras están abiertas no se pueden borrar,
  renombrar ni sustituir por una unión.
- Comprueba lo **abierto**, no el nombre: atributos y etiqueta reparse del handle con la política única existente
  (`_reparse_redirects`: los marcadores de nube siguen permitidos) y `GetFinalPathNameByHandleW` de la carpeta destino
  igual a la ruta esperada. Si algo no se puede fijar o no coincide: `BoxCopyRejected`, **nada creado**.
- Helpers: `_kernel32`, `_pin_directory`, `_pinned_final_path`. Solo abren, leen atributos y cierran handles.
- Fuera de Windows no hay fijación (la app es Windows); allí la salida se sigue detectando en VERIFY.

Sin cambios de firma, estados, eventos, trazas, nombres, colisiones, `copied_to_box` ni del flujo de Bandeja.
Un rechazo H3 se comporta como cualquier `BoxCopyRejected`: sin evento, sin cambio de estado; en el visor, la
solicitud DV27 queda `rejected` (no `needs_review`), porque no se escribió nada.

`backend/services/document_viewer_box_archive_service.py`: solo el comentario de `H3_WRITE_CONTAINMENT_VERIFIED`.

## Qué se evitó / reutilizó

| | |
|---|---|
| Reutilizado | Motor P3B1 completo, diálogo «Archivar en Box», planificador P3A, claims/idempotencia DV27 (sin ampliar), sandbox de tests P3B1/P3B2 |
| Evitado | Segundo motor de copia, TPM/CNG, registro de equipos, RBAC nuevo, migraciones, autoridad multi-host, cherry-pick de DV28-P1/P2, rutas desde la UI, cualquier borrado/reintento destructivo |
| Eliminado | Nada: no había duplicación de lógica de copia que quitar |

## Tests

Nuevos: `scripts/tests/test_dv28_box_copy_containment.py`

| Clase | Plataforma | Qué prueba |
|---|---|---|
| `ScopeTests` | todas | Los helpers de fijación no usan primitivas destructivas ni `open`; solo `CreateFileW`, `GetFileInformationByHandleEx`, `GetFinalPathNameByHandleW`, `CloseHandle`; la fijación envuelve la única `_create_box_copy` |
| `ContainmentTests` | **Windows** (unión NTFS real) | Carpeta destino sustituida tras validar (vía Bandeja, `target_filename`) ⇒ rechazo sin escritura; carpeta intermedia recién creada sustituida ⇒ rechazo; durante la copia no se puede borrar/renombrar destino, intermedia, raíz **ni el padre de la raíz**; carpeta imposible de fijar ⇒ rechazo sin escritura |
| `EngineTests` | todas | La creación ocurre siempre con la fijación tomada; PDF y JPG conservan nombre y extensión, original intacto; colisión ⇒ `_2` sin sobrescribir; reintento ⇒ `already_copied`; fallo de escritura ⇒ parcial conservado y sin registrar, reintento con nombre nuevo; fallo de REGISTER ⇒ copia verificada conservada, reintento la registra (`own_unregistered_copy`); destinos fuera de raíz o por enlace ⇒ rechazo |

Modificados (contrato H3 invertido: de «se escapa y se detecta» a «no se escapa»):

- `test_document_viewer_dv25_security.py::DestinationSafetyTests`
  - `test_toctou_swap_after_validation_is_prevented_before_any_write` (Windows): `BoxCopyRejected`, nada fuera, sin eventos.
  - `test_toctou_swap_without_the_pin_is_still_detected_by_verify` (todas): con la fijación anulada, VERIFY sigue
    detectando la salida (`BoxCopyIncomplete`, `verify`), sin registrar ni borrar. Defensa en profundidad.
- `test_dv27_box_copy_activation.py::SafetyTests::test_h3_folder_swap_is_refused_before_any_write` (Windows): por el
  visor, `rejected`, nada fuera, sin eventos, solicitud `rejected`; `TOCTOU_PREVENTION_PENDING` sigue en los bloqueos.

**Skips nuevos:** 0 en Windows. Fuera de Windows: 6 (`ContainmentTests` ×4, los dos tests H3 de prevención),
todos con motivo «H3 prevention pins folders with Win32 handles (Windows only)». El Runner debe informar además del
recuento total de skipped/xfail de cada suite.

## Riesgos que el Runner debe confirmar

1. `test_pinned_folders_cannot_be_removed_or_renamed_during_the_copy` asume que NTFS rechaza renombrar un ancestro
   (no fijado) de una carpeta con handles abiertos. Si falla, **no relajar**: hay que fijar también los ancestros.
2. Raíces Box en unidad de red mapeada: la ruta final del handle sale como UNC y no coincide ⇒ se rechaza (coherente
   con la política existente de rutas de red, pero es un cambio visible para Bandeja si alguien usa una).
3. Box Drive (filtro de nube) con handles sin `FILE_SHARE_DELETE` durante segundos: solo validable en la prueba real
   supervisada.

## Comandos para el Runner

```
python -m pytest -q -rsx scripts/tests/test_dv28_box_copy_containment.py
python -m pytest -q -rsx scripts/tests/test_document_viewer_dv25_box_hardening.py scripts/tests/test_dv25_bandeja_compat.py scripts/tests/test_document_viewer_dv25_security.py scripts/tests/test_document_viewer_dv25_box_from_viewer.py scripts/tests/test_dv27_box_copy_activation.py
python -m pytest -q -rsx scripts/tests/test_document_viewer_dv23_close.py scripts/tests/test_document_viewer_dv23_pdf_tools.py scripts/tests/test_document_viewer_dv23_visual.py scripts/tests/test_document_viewer_dv24_linking.py scripts/tests/test_document_viewer_dv24_multidoc.py scripts/tests/test_document_viewer_dv24_notes.py scripts/tests/test_document_viewer_dv25_filing_plan.py scripts/tests/test_document_viewer_dv25_selection.py scripts/tests/test_document_viewer_dv25_toolbar.py scripts/tests/test_dv25_documental_smoke.py scripts/tests/test_dv26_link_visual.py
python -m compileall -q backend/services/document_inbox_service.py backend/services/document_viewer_box_archive_service.py scripts/tests/test_dv28_box_copy_containment.py
git diff --check
git status --porcelain
```

## Después del Runner verde

Checkpoint limpio → revisión de diff → PR a `develop` → prueba real supervisada (Windows + Box Drive) →
autorización independiente para poner `H3_WRITE_CONTAINMENT_VERIFIED = True`. La apertura de
`EXECUTION_ENABLED` sigue dependiendo además de `PERMISSION_CONTRACT_PENDING` y `MULTI_HOST_AUTHORITY_PENDING`
(DV27), que esta WO no toca. Que al principio solo se habilite en el PC del despacho es un criterio de despliegue,
no un mecanismo técnico: no impide el uso desde otro equipo.
