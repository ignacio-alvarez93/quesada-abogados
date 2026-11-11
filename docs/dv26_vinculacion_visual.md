# DV26-UI1 · Composición visual de «Vincular a expediente»

Refactor **solo visual** de `LinkForm` (`frontend/components/document_viewer_link_dialog.py`).
El estado, los servicios (`document_viewer_link_service`, `document_viewer_filing_plan_service`),
los callbacks y los controles públicos son los de DV24/DV25. No se añade ninguna operación:
`Vincular` sigue siendo `link_service.execute_link(...)` con confirmación explícita y
«Vincular y archivar copia» sigue deshabilitado y sin handler.

## Estructura (árbol Flet, sin datos reales)

```
AlertDialog (data=LinkForm, bgcolor #F8FAFC, inset 16/12, radio 14)
├─ title: Text(título, visible=False)          ← título semántico DV24 (dialog.title.value)
├─ content: Container "link-shell" (ancho/alto de LinkLayout)
│  ├─ Container "link-header"  (degradado azul marino)
│  │    icono · título («Vincular a expediente» / «Vincular N documentos seleccionados»)
│  │    · LOGICAL_ONLY · chip «Documento activo» / «Lote · N documentos» · botón cerrar
│  ├─ Container (expand) → Column "link-body" (scroll interno)
│  │  ├─ "link-zones": Row (ventana ancha) o Column (estrecha)
│  │  │  ├─ izquierda: "documents-card" (document_column)
│  │  │  │            "destination-card" (client_select + expedient_select en fila o apilados)
│  │  │  └─ derecha:   "box-card"  «Archivo en Box (previsualización)» + chip
│  │  │               «Planificación / sin escritura», PREVIEW_ONLY, BOX_NO_WRITES,
│  │  │               "filing-box" (avisos reales, folder_select, nomenclature_selects)
│  │  ├─ "review-card"  (review_column, transfer, confirm, política de lote)
│  │  └─ "preview-card" «Vista previa de vinculación / archivo» → filing_column
│  │        └─ Row "filing-preview" (scroll horizontal) → DataTable
│  └─ Container "link-status-bar" (status + «Vincular y archivar copia: pendiente…»)
└─ actions: [cancel_button, archive_button (deshabilitado), submit_button (primario)]
```

Sin selección vinculable (p. ej. documentos de carpeta de expediente o sin usuario) solo se
muestran la cabecera, `documents-card`, la barra de estado y el pie, con altura reducida.

## Matriz de controles

| Control | Ubicación | Estado / regla |
|---|---|---|
| `document_column` | Documentos a vincular | una línea por documento (data = clave), nombre en 2 líneas, origen Bandeja/carpeta, estado y chip |
| `client_select`, `expedient_select` | Destino | `AppAutocomplete` sin texto libre; cambio ⇒ nueva revisión y confirmación |
| `folder_select`, `nomenclature_selects` | Box (previsualización) | solo con raíz Box disponible; catálogo, sin texto libre; ancho `box_field` |
| `review_column`, `transfer`, `confirm` | Revisión y confirmación | ancho completo (etiquetas largas); traslado con confirmación especial |
| `filing_column` / `filing-preview` | Vista previa | columnas Origen, Bandeja, Nomenclatura / rol, Subcarpeta, Nombre propuesto, Estado; orden de `self.preview` |
| `status` | Barra de estado fija | fuera del scroll, siempre visible |
| `cancel_button` | Pie | «Cancelar» / «Cerrar» tras resultado o sin selección; no escribe |
| `archive_button` | Pie | siempre `disabled`, `on_click=None`, tooltip `ARCHIVE_PENDING` |
| `submit_button` | Pie | primario; solo habilitado con confirmación vigente |

## Dimensiones (`LinkLayout` / `link_layout(ancho, alto)`)

- Ancho de contenido `min(1240, ventana − 32)`; alto `min(900, ventana − 24 − 80)`; el cuerpo
  hace scroll dentro y la barra de estado y las acciones quedan fuera del scroll.
- 1200×750: 1168×646, dos zonas (611 / 501 px), cliente y expediente en fila (282 px cada uno).
- 1920×1080: 1240×900.
- Por debajo de ~1030 px de ancho las zonas se apilan.

## Tests

`scripts/tests/test_dv26_link_visual.py` (fixtures sintéticas DV24/DV25: CRM SQLite temporal y
árbol Box sintético, escrituras de sistema de archivos vigiladas): presupuesto de dimensiones,
composición a 1200×750, tarjeta Box solo de planificación y tabla, aviso real sin Box, lote,
traslado, bloqueo tras resultado, ventana estrecha, formulario sin vinculables y alcance
(sin nuevas operaciones ni handler de archivado).

## Desviaciones conscientes respecto a la maqueta

- La cabecera va dentro del contenido; `dialog.title` se conserva oculto porque DV24 lo verifica.
- «Revisión y confirmación» ocupa el ancho completo bajo las dos zonas: las etiquetas de
  traslado y confirmación son largas y el `Checkbox` de Flet no las parte en varias líneas.
- La tabla vive en `filing_column` (contrato DV25 `filing-preview`), en una tarjeta de ancho
  completo con scroll horizontal.

## Pendiente

Smoke visual supervisado por Dirección a 1200×750 y 1920×1080 antes de PR/merge a `develop`.
