# WO-DV24-P2 · Notas persistentes por documento y actividad contextual

Rama `feature/document-viewer-dv24-multidoc-notas-20261109`, sobre el cierre de P1.
Referencia visual: `docs/design/visor_dv24_comparador_referencia.png` (panel lateral derecho «Notas y actividad»).

## Diagnóstico de partida

- No existía persistencia reutilizable de notas por documento: `expediente_notas` es por expediente y
  su `autor` es texto libre; `document_inbox_items.notes` es el campo descriptivo del ítem de Bandeja.
  Se crea una tabla propia, sin tocar ninguna de las dos.
- Identidad autenticada real: `app/main.py` guarda en `current_user["value"]` el `{"id", "username"}`
  devuelto por `auth_service.authenticate_user` tras el login. Las vistas no lo recibían.
- Permisos: `users` solo tiene `is_active`; el CRM **no tiene roles ni ACL por documento**
  (ver «Bloqueo elevado»).
- Los servicios del repositorio aplican su propia migración idempotente con `executescript`
  (p. ej. `document_semantic_event_repository`); se sigue el mismo patrón.

## Cambios

| Archivo | Cambio |
|---|---|
| `database/migrations/20261109_01_create_document_viewer_notes.sql` (nuevo) | Única migración: `CREATE TABLE IF NOT EXISTS document_viewer_notes` + un índice. Aditiva, idempotente, sin `ALTER/DROP/UPDATE/INSERT/PRAGMA`. |
| `backend/repositories/document_viewer_notes_repository.py` (nuevo) | Toda la SQL: aplicar migración, leer `users`, listar/contar/insertar notas. Abre solo bases existentes (`get_existing_connection`, `mode=rw`); errores SQLite → `NotesStorageError`. |
| `backend/services/document_viewer_notes_service.py` (nuevo) | Identidad documental, actor verificado, validación del texto, idempotencia por `request_id`, actividad en solo lectura. Sin `sqlite3`. |
| `frontend/components/document_viewer_notes_panel.py` (nuevo) | `ViewerNotes` (contexto que inyecta la vista) y `NotesController` (panel plegable del documento activo, carga en segundo plano). Sin SQL. |
| `frontend/components/document_viewer_modal.py` | Parámetro keyword-only `notes=None`. Con `notes`, el lienzo y el panel van en una fila (modo único y comparador); el mosaico descuenta el ancho del panel. Sin `notes`, shell idéntico a DV23/P1. |
| `frontend/views/document_inbox_view.py` | `current_user=None`; `state["viewer_notes"]`; `inbox_viewer_options` añade `notes` con los pares (ruta, ID de ítem) de la cola o del ítem abierto. Sin consultas nuevas ni cambios Box. |
| `frontend/views/expedients_view.py` | `current_user=None`; `state["viewer_notes"]`; `show_document_preview` pasa `notes=`. Sin cambios Box. |
| `app/main.py` | Solo `current_user=current_user.get("value")` al construir `expedients_view(...)` y `document_inbox_view(...)`. |
| `scripts/tests/test_document_viewer_dv24_notes.py` (nuevo) | Suite P2. |
| `scripts/tests/test_document_viewer_dv24_multidoc.py`, `..._integrations.py`, `..._foundation.py` | Contratos fijados: firma con `notes` (keyword-only, `None`) y llamadas exactas de Expedientes con `notes=None`. Ningún otro cambio. |

## Identidad documental

Resuelta siempre en el servicio; la UI solo aporta una petición (`{"inbox_item_id", "path"}` o `{"expediente_id", "path"}`).

- **Bandeja** → `inbox:<id>`. El ítem se lee con `document_inbox_service.get_inbox_item` y la ruta pedida,
  canonicalizada (`resolve(strict=True)`), debe coincidir con su `stored_path` o `linked_document_path`
  vigentes. Otro archivo, un PDF no registrado, un ítem inexistente o una ruta relativa → error.
- **Expediente** → `expedient:<id>:<ruta relativa normalizada>`. Raíz de
  `document_viewer_service.get_expediente_document_root`; se rechaza cualquier componente `..`, se
  resuelven symlinks/junctions y la ruta final debe quedar bajo la raíz; mismos filtros que el listado
  (sin ocultos `.`/`~`, extensión de `DOCUMENT_EXTENSIONS`). Cada nota guarda `content_sha256`: tras
  reemplazar el archivo, sus notas anteriores no se muestran como propias (se informa del número), y una
  nota escrita viendo la versión anterior se rechaza (`expected_sha256`).
- Dos documentos con el mismo nombre tienen identidades distintas (ID de ítem o ruta relativa).
- Sin identidad fiable, el panel muestra el error y no ofrece formulario; el servicio no escribe.

## Modelo persistente

`document_viewer_notes`: `document_kind` (`inbox`/`expedient`), `document_ref`, `inbox_item_id`,
`expediente_id`, `relative_path`, `content_sha256`, `size_bytes`, `body` (1–4000), `author_user_id`,
`author_username`, `status` (`active`/`archived`), `request_id` (`UNIQUE`), `created_at` (UTC ISO-8601
del servidor). `CHECK` de coherencia por tipo. Índice `(document_ref, content_sha256, id)`.

- Lectura: notas `active` del `document_ref` (en expedientes, de la revisión actual), más reciente primero.
- Inserción: `INSERT ... ON CONFLICT(request_id) DO NOTHING` y relectura por `request_id`. Si ese
  `request_id` pertenece a otro documento, autor o texto → error.

## Actor y permisos

- El autor sale de la sesión autenticada que inyecta `app/main.py`; el servicio lo verifica en `users`
  (existe, `is_active = 1`, mismo `username` si se aporta) y guarda el nombre de la base, no el de la UI.
- Autorizado = usuario activo + documento resuelto dentro de su ámbito (ítem existente / archivo bajo la
  raíz del expediente). No hay bypass ni permisos inventados.
- Texto: CRLF/CR → LF, recortado; vacío, > 4000 o con caracteres de control (salvo `\n`, `\t`) → error.
  Se muestra con `ft.Text` plano (seleccionable), nunca como markup.
- Doble envío: el botón se desactiva («Enviando…») y se ignoran clics mientras hay un envío; cada borrador
  lleva un `request_id`, que se conserva para reintentar tras un error (un alta ya hecha no se duplica)
  y se renueva al editar el texto.

## Actividad

- Bandeja: `get_inbox_events(item_id)` en lectura, tal cual (fecha, tipo, mensaje). La «Descripción de
  Bandeja» (`notes` del ítem) se muestra aparte, en solo lectura.
- Expediente: únicamente la fecha de modificación del archivo (sistema de archivos). No hay otra fuente.
- Añadir una nota no crea eventos ni cambia estado, cliente, expediente, `notes` del ítem, bytes,
  hashes ni fechas del documento, ni toca Box. Un fallo al leer la actividad no oculta las notas.

## UX

Panel a la derecha (296 px en pantallas compactas, 340 px en el resto), plegable a un riel de 52 px; al
plegar, el mosaico recalcula los tiles. Muestra nombre e identidad del documento activo, notas (autor,
fecha local), formulario `Añadir nota` con `Cancelar`/`Enviar`, mensajes de éxito/error y actividad.
Carga bajo demanda en un hilo; las publicaciones pasan por el lock del visor y se descartan al cerrar.
Cambiar de documento, tile, grupo o modo muestra el estado propio de ese documento.

## Pruebas

`python -m pytest -q scripts/tests/test_document_viewer_dv24_notes.py scripts/tests/test_document_viewer_dv24_multidoc.py scripts/tests/test_document_viewer_dv23_close.py scripts/tests/test_document_viewer_dv23_pdf_tools.py scripts/tests/test_document_viewer_integrations.py`

La suite P2 usa PDFs y SQLite temporales; redirige `database.connection.DB_PATH` a un archivo que
debe seguir sin existir; falsea `get_inbox_item`/`get_inbox_events` y hace fallar cualquier mutación de
Bandeja/Box; comprueba al terminar bytes y `mtime` de todos los documentos, ítems y eventos.

## Bloqueo elevado

El CRM no tiene contrato de permisos por usuario/documento (`users` sin roles). P2 aplica la única regla
disponible (usuario autenticado y activo) y no crea un sistema de permisos propio. Si Dirección Técnica
necesita ACL por expediente/documento, requiere una decisión y un contrato fuera de este alcance.

## Riesgos y deuda

- `get_inbox_events`/`get_inbox_item` llaman a `ensure_document_inbox_schema()` (comportamiento existente).
- El primer uso aplica la migración sobre la base operativa desde el servicio (patrón del repositorio).
- El SHA-256 se calcula al cargar y al guardar: coste lineal con el tamaño del archivo, fuera del hilo de UI.
- El smoke en Flet real (aspecto, plegado, reinicio del CRM) queda pendiente de aceptación humana; no
  forma parte de los tests automáticos.
