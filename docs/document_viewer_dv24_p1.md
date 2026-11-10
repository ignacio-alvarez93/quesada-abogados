# WO-DV24-P1 · Navegación entre documentos y comparador de hasta cuatro

Rama `feature/document-viewer-dv24-multidoc-notas-20261109` (base `origin/develop` con PR #42 DV23).
Referencia visual: `docs/design/visor_dv24_comparador_referencia.png` (solo referencia; el código no la importa).

## Diagnóstico de partida

- `open_document_viewer_modal(queue, queue_index)` ya generaba `Doc anterior` / `Doc siguiente`,
  pero solo en la fila de información, comprimidos junto a la ruta (30 px) y nunca en la barra
  visual (`dialog.actions`); sí figuraban en `layout.buttons`, de ahí la discrepancia entre el
  modelo y lo que se veía.
- La Bandeja no pasaba nunca una cola, y en Expedientes la previsualización por tarjeta tampoco
  (solo la apertura de seleccionados lo hacía).

## Cambios

| Archivo | Cambio |
|---|---|
| `frontend/components/document_viewer_multidoc.py` (nuevo) | `DocumentQueue` (orden, activo, grupos de 4 por posición), `QueueDocument.key` (referencia estable por documento), `Comparator`/`ComparatorTile` (una `DocumentPreviewSession(near_window=0)` por tile, como máximo 4), builders Flet de la franja de modo y del mosaico. |
| `frontend/components/document_viewer_modal.py` | Franja `Documento único` / `Comparador 4` con flechas de documento (o de grupo) e indicador, separada de página/zoom; modo comparador; `viewer_active_document()`; `_info_row` y `_toolbar_row` extraídos sin cambiar la estructura DV23. |
| `backend/services/document_preview_session.py` | `release()`: suelta la ventana y sus PNG sin cerrar la sesión (al entrar en el mosaico solo quedan vivas las sesiones de los tiles). |
| `frontend/views/document_inbox_view.py` | `inbox_viewer_options(..., queue_items, selected_ids)`: cola = lista visible (o la selección múltiple que incluya el ítem), en su orden; grupo = documentos del lote. La barra PDF resuelve el ítem por la ruta del documento activo. Sin consultas nuevas. |
| `frontend/views/expedients_view.py` | Las tres entradas por tarjeta pasan su listado como cola con su índice; las dos de seleccionados ya lo hacían. Sin cambios en operaciones Box. |
| `scripts/tests/test_document_viewer_dv24_multidoc.py` (nuevo) | Suite DV24 obligatoria. |
| `scripts/tests/test_document_viewer_integrations.py` | La tarjeta de Expedientes debe ahora abrir con `queue=<listado>, queue_index=1` (antes fijaba `queue=None`). |

## Comportamiento

- **Individual**: con cola de 2 o más aparece la franja; `Documento X de N` entre flechas visibles con
  motivo al deshabilitarse. Sin cola o con 1 documento el visor es idéntico al DV23.
  Un fallo al avanzar en la cola se muestra dentro del visor; la apertura sigue usando `on_error`.
- **Comparador 4**: grupo del documento activo (índices [0..3], [4..7], …), `Grupo X de Y`,
  `Grupo anterior` / `Grupo siguiente`. Una fila para 1–2 documentos, 2×2 para 3–4; los huecos se
  marcan como «Grupo incompleto». Cada tile: nombre, `Página X de Y`, zoom y controles propios; el
  activo, con borde de 2 px y casilla marcada. Errores, documentos sin ruta o tipos no soportados
  quedan dentro de su tile.
- **Herramientas PDF**: una sola vez, en la barra inferior, para el documento activo; se invalidan
  cuando cambia el shell (otro activo, página o grupo).
- **Cambio de modo**: conserva el documento activo, su página y el orden de la cola.
- **Recursos**: una página por documento en el mosaico; las sesiones de un grupo abandonado se cancelan
  y sus PNG se borran tras el refresco de la UI; al cerrar se liberan todas las sesiones y sus PNG.
  Las rutas siguen validadas por `document_viewer_service` con el `expediente_id` del visor.

## Continuidad P2/P3

`viewer_active_document(dialog)` y `ViewerLayout.document` devuelven el `QueueDocument` activo
(`index`, `path`, `name`, `key`). `key` es `inbox:<id>` en la Bandeja y `path:<ruta>` en
Expedientes; no depende de la posición en la cola. P1 no implementa notas ni vinculación,
ni crea migraciones u operaciones Box.

## Riesgos y deuda

- El render de los tiles es síncrono dentro del handler de Flet (como la ventana DV23): abrir un grupo
  renderiza hasta 4 páginas seguidas, cada una publicada al terminar. Los clics posteriores invalidan
  el trabajo pendiente, pero no interrumpen un render nativo en curso.
- Si un render nativo obsoleto escribe un PNG justo cuando se borra su directorio, el PNG puede
  quedar en su espacio de nombres `v2/<uuid>` (mismo riesgo aceptado en el cierre DV23).
- Cada publicación del mosaico reconstruye el shell y vuelve a llamar a la factoría PDF del activo
  (`ViewerPdfTools` cachea el scope por mtime/tamaño).
- Las herramientas no van dentro del tile activo como en la maqueta, sino en la barra inferior, para
  no salirse del presupuesto de píxeles DV23 a 1366×768. El panel lateral de información/notas de la
  maqueta corresponde a P2.
- La validación visual en Flet real y la captura quedan para la aceptación humana.
