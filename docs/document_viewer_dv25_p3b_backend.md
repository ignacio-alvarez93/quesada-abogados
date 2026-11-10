# WO-DV25-P3B1 · Servicio de copia Box gobernada (backend, sin UI)

Rama `feature/document-viewer-dv25-seleccion-nomenclatura`, base P3A `718160791b10`.
Resolución DOC-003: **COPY -> VERIFY -> REGISTER**. P3B1 endurece el servicio existente; el
visor **no** gana ningún botón de archivado físico (P3B2, tras certificar P3B1). La aprobación de
P3B1 no autoriza por sí sola operar sobre Box real.

## Diagnóstico de partida (código local)

| Pieza | Contrato real antes de P3B1 |
|---|---|
| `copy_inbox_item_to_expedient_box(item_id, expedient_id=None, subfolder="", target_filename="")` | Subcarpeta normalizada solo con `strip("/")`: `..`, unidades y rutas absolutas pasaban (`base / "C:/x"` sale de la raíz). `mkdir(parents=True)`. Nombre por `_safe_filename` (sanea en silencio, sin nombres de dispositivo). `_unique_destination` (`exists()`) + `shutil.copy2`: carrera TOCTOU que podía sobrescribir. Sin verificación de tamaño/hash. `copied_to_box` y `linked_document_path` se escribían en la misma conexión abierta durante la copia. |
| `_get_expedient_for_box(conn, id)` | Expediente existente con `box_folder_path` no vacío (se mantiene). |
| `link_inbox_item` | Vinculación lógica; no se toca. |
| Eventos | `document_inbox_events(item_id, event_type, event_at, message, metadata_json)` vía `_record_event`; sin cambios de esquema. |
| Callers | `document_inbox_view.copy_to_box` (posicional `item_id` + `expedient_id`, `subfolder`, `target_filename`; la subcarpeta puede llegar como `"."` para la raíz) y `copy_document_inbox_batch_to_expedient_box` (vista de grupos ×2). |
| P3A `document_viewer_filing_plan_service` | `clean_relative`, `_inside` (sin enlaces/uniones), `safe_stem`, `catalog_options` (solo lectura), serie de colisión `nombre_2…`. Contrato AST: sin `os`/`shutil`, sin escrituras, solo `get_expedient` de Bandeja. |
| Adaptador de escritura | No existe otro adaptador Box: la única ruta de escritura es este servicio. Se reutiliza el patrón de `import_file_to_inbox` (`open("xb")` + verificación), sin crear otra ruta. |

## Cambios (solo los 4 archivos autorizados)

| Archivo | Cambio |
|---|---|
| `backend/services/document_viewer_filing_plan_service.py` | Validadores puros reutilizados por la copia: `check_subfolder`, `check_filename`, `nomenclature_option`, `nomenclature_filename`. Sin E/S nueva, sin `os`/`shutil`, sin referencias a la copia: el contrato P3A se mantiene. `build_preview` no cambia. |
| `backend/services/document_inbox_service.py` | `copy_inbox_item_to_expedient_box` reescrita en fases; helpers `_authorized_box_root`, `_verified_inbox_source`, `_box_destination_folder`, `_create_box_copy`, `_stream_into`, `_verify_box_copy`, `_register_box_copy`, `_record_box_copy_failure`; excepciones `BoxCopyRejected(ValueError)` y `BoxCopyIncomplete(RuntimeError)`. El lote valida la subcarpeta antes de copiar. |
| `scripts/tests/test_document_viewer_dv25_box_hardening.py` | Suite P3B1 (nueva). |
| `docs/document_viewer_dv25_p3b_backend.md` | Este documento. |

Sin cambios de esquema ni migraciones. `_unique_destination` y `_safe_filename` siguen igual para
la importación a Bandeja.

## Qué protege

**Firma compatible**: los cuatro parámetros y sus valores por defecto no cambian; se añade solo
`nomenclature_key` (keyword-only). Devuelve el ítem (`get_inbox_item`) más la clave `box_copy` con la
traza. Los rechazos siguen siendo `ValueError`/`FileNotFoundError`, como antes.

1. **Raíz autorizada** = `box_folder_path` del expediente: absoluta, local (rechaza UNC `\\` y
   `\\?\`), existente, carpeta, no enlace ni unión (`lstat`: `S_ISLNK` o reparse point que no sea un
   marcador de la Cloud Files API `0x9000xxxA`); se usa resuelta.
2. **Subcarpeta** (`check_subfolder`, en servicio también para el lote): relativa POSIX; rechaza `..`,
   `.` como componente, `//`, absolutas, unidades (`C:`), UNC, NUL/controles, reservados de Windows
   (`<>:"/\|?*`), dispositivos (`CON`, `NUL`, `COM1`, `LPT¹`, `CONIN$`…), espacio/punto final,
   >8 niveles o >200 caracteres. Compatibilidad: `""`, `"."` y espacios exteriores = raíz; se
   ignoran separadores finales. Cada componente existente debe ser carpeta real dentro de la raíz
   (`_inside` de P3A + comprobación de reparse); los que faltan se crean **de uno en uno** (comportamiento
   legacy) y se revalidan; un enlace no se atraviesa nunca (nada se crea a través de él).
3. **Origen**: archivo regular bajo `INBOX_ROOT`, no enlace; si el ítem tiene `sha256` registrado, debe
   coincidir. Nunca se renombra ni modifica.
4. **Nombre** (`check_filename`): se valida, no se sanea en silencio. Rechaza rutas, reservados,
   controles, dispositivos, punto/espacio final, nombres ocultos (`.x`), >200 caracteres y extensión
   distinta de la del origen; sin extensión se añade la real. Con `nomenclature_key` el nombre es el de
   P3A (`safe_stem(nombre rol)` + extensión real) y la clave debe ser del catálogo de ESE expediente.
5. **Colisiones**: `open("xb")` (creación exclusiva, sin `exists()` previo); ocupado → `nombre_2`,
   `nombre_3`… (misma serie que la preview P3A), máx. 500. Un ocupante **idéntico** (tamaño + SHA-256)
   se reutiliza (`reused_identical`) en vez de duplicarlo. Nunca se sobrescribe.
6. **Copia y verificación**: por bloques de 1 MiB con hash en streaming, `flush` + `fsync`; estabilidad
   del origen (tamaño y `mtime_ns` antes/durante/después, hash previo = hash copiado); relectura del
   destino (tamaño + SHA-256) y comprobación de que el archivo resuelto sigue en la carpeta destino.
7. **Registro** solo tras verificar: `BEGIN IMMEDIATE`, comprobación de que nadie registró otra copia
   desde la lectura (no se pisa), `UPDATE` + evento `copied_to_box` en la misma transacción.
8. **Idempotencia**: un ítem `copied_to_box` cuya copia registrada sigue intacta no se copia de nuevo
   (`already_copied`); si la copia registrada difiere → rechazo para revisión; si desapareció → se permite
   una copia nueva. Bloqueo por ítem dentro del proceso para dobles clics.
9. **Cliente**: si el ítem ya tiene cliente y no es el del expediente → rechazo.

### Traza (evento `copied_to_box`)

`expedient_id`, `client_id`, `source_path`, `source_size_bytes`, `source_sha256`, `box_root`,
`subfolder`, `created_folders`, `target_filename`, `nomenclature_key/code`, `rol_documental`,
`requested_filename`, `final_filename`, `destination_path`, `destination_size_bytes`,
`destination_sha256`, `collision_decision` (`none`/`renamed`/`reused_identical`), `verified_at`,
`registered_at`, `result`. Los fallos posteriores a escribir dejan `copy_to_box_failed` con
`result = failed_write|failed_verify|failed_register`, sin tocar estado ni rutas del ítem.

### Errores y recuperación

| Error | Estado | Recuperación |
|---|---|---|
| `BoxCopyRejected` / `ValueError` / `FileNotFoundError` | Nada nuevo en Box (salvo subcarpetas creadas si el rechazo es posterior, p. ej. serie agotada) ni en BD. | Corregir la entrada. |
| `BoxCopyIncomplete(stage="write")` | Archivo parcial en `written_path`, sin registrar; evento de fallo. | Revisión humana del parcial (no se borra). Reintentar crea `nombre_2` (el parcial no es idéntico). |
| `BoxCopyIncomplete(stage="verify")` | Archivo no verificado, sin registrar; evento de fallo. | Revisión humana. |
| `BoxCopyIncomplete(stage="register")` | Copia **verificada** en Box, BD sin cambios (rollback). Evento de fallo si la BD responde. | Reintentar la misma copia: reutiliza el archivo idéntico y lo registra una sola vez. |

No hay transacción atómica BD+filesystem: el diseño garantiza que la BD nunca afirma una copia que
no esté verificada y que todo archivo sin registrar queda identificado (`written_path`, evento).

## Pruebas

`scripts/tests/test_document_viewer_dv25_box_hardening.py`: TemporaryDirectory, SQLite temporal
(`connection.DB_PATH` redirigido y comprobado en cada conexión; el `quesada.db` habitual no cambia),
Bandeja (`INBOX_*`) y Box sintéticos. Guardas: cualquier `remove/unlink/rename/replace/rmdir/symlink`
o `shutil.move/rmtree/copy*` falla; toda apertura en escritura o `mkdir` fuera del sandbox falla; en
Box el servicio solo abre con `xb`; los archivos previos de Box y los originales de Bandeja se comparan
byte a byte. Matriz: subcarpeta interna/nueva/legacy, `..`, absolutas, unidades, UNC, `\\?\`, enlace o
unión (symlink si hay privilegio; si no, junction NTFS) dentro de la raíz y como raíz, clasificación
de reparse points, nombres Windows peligrosos, extensión incoherente, nomenclatura P3A, colisiones,
carpeta homónima, serie agotada, concurrencia (6 ítems mismo nombre, mismo ítem ×2), 0 bytes, 8 MiB y
límites de bloque, fallo de escritura a mitad, fallo de `fsync`, fallo de verificación, origen que cambia,
hash registrado distinto, fallo de registro + reintento, BD caída, registro concurrente, orden
copy→verify→register, idempotencia, firma/callers (AST de la vista) y lote. Sin `skip` ni `xfail`.

Regresión a ejecutar por Fabric Runner: P3A (`test_document_viewer_dv25_filing_plan`), P2/P1
(`test_document_viewer_dv25_toolbar`, `test_document_viewer_dv25_selection`), DV24 (`*_dv24_*`) y DV23.

## Límites conocidos

- **TOCTOU residual en carpetas**: entre validar la carpeta y crear el archivo, otro proceso con acceso
  local podría sustituir una carpeta por una unión. Se detecta después (destino resuelto fuera de la
  carpeta → `verify`, sin registrar), pero el archivo ya creado queda donde apunte la unión. Python en
  Windows no ofrece `openat`/handles de directorio para cerrarlo del todo.
- **Box Drive real no verificado**: la política admite marcadores Cloud Files y rechaza cualquier otro
  reparse point. Antes de P3B2 hay que comprobar en el equipo real que la raíz Box del expediente pasa
  `_authorized_box_root` (si Box Drive usara otra etiqueta, la copia se rechazaría explícitamente).
- **Cambio de comportamiento legacy (intencionado)**: Bandeja ya no sanea en silencio nombres con `/` u
  otros reservados ni acepta subcarpetas fuera de la raíz o con mayúsculas distintas de las reales
  (`_inside` compara la ruta resuelta); un ítem ya copiado no se copia otra vez a otra carpeta; raíces en
  red/UNC o enlazadas se rechazan. Todos son errores explícitos, sin escritura.
- La concurrencia entre procesos se resuelve con `xb` + comprobación en el registro; dos procesos
  sobre el mismo ítem pueden dejar una copia extra sin registrar (`stage="register"`, trazada).
- La reutilización de idénticos registra como copia un archivo previo con el mismo contenido de la serie.
- El lote sigue sin ser atómico (por ítem), como antes.
