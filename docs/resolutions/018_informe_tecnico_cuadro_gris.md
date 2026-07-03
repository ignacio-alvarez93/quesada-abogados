# Informe técnico: motivos de aparición del “cuadro gris” en Documentos/Box y forma correcta de corregirlo

## 1. Contexto

En las últimas refactorizaciones visuales del CRM se ha detectado un problema recurrente: al seleccionar documentos, cards o elementos de listado aparece un “cuadro gris”, “hueco grande” o fondo no deseado alrededor del elemento. Este problema afecta especialmente a vistas con tarjetas documentales, bandejas, grupos documentales, elementos Box, colas de presentación y listados con checkbox.

La causa no está en backend ni en la base de datos. Es un problema de composición visual Flet: uso inadecuado de `selected`, `selectable`, `expand=True`, contenedores manuales y scroll aplicado a la columna equivocada.

La resolución oficial de componentes ya establece que los documentos visibles deben representarse con `document_file_card(...)`, que el checkbox corresponde a selección masiva, el menú `⋮` a acciones individuales, `bulk_action_bar(...)` a acciones sobre seleccionados, y `document_viewer_modal(...)` al visor documental. También prohíbe volver a crear tarjetas documentales manuales salvo justificación expresa.

## 2. Causa principal: `selected=True` usado sin `selectable=True`

El caso más habitual aparece al usar `document_file_card(...)` marcando el card como seleccionado, pero sin activar su modo seleccionable.

El componente `document_file_card` tiene un comportamiento visual pensado para dos casos distintos:

```python
bgcolor="#EFF8FF" if (selected and not selectable) else "#FFFFFF"
```

Es decir:

```text
selected=True + selectable=False  => fondo azul/gris de resaltado del card
selected=True + selectable=True   => fondo blanco normal con checkbox marcado
```

Por tanto, si un desarrollador pasa `selected=True` pero no pasa `selectable=True`, el componente interpreta que el card debe resaltarse visualmente. En algunas composiciones, especialmente dentro de columnas con `expand=True`, ese fondo puede percibirse como un “cuadro gris” o bloque sobredimensionado.

### Corrección correcta

Para documentos seleccionables con checkbox:

```python
document_file_card(
    name=...,
    selected=is_selected,
    selectable=True,
    checkbox_value=is_selected,
    on_select=lambda e: toggle_selection(document_id),
    ...
)
```

No debe usarse solo:

```python
document_file_card(
    name=...,
    selected=is_selected,
)
```

porque eso activa el resaltado de fondo del card.

## 3. Segunda causa: tarjetas documentales manuales con `ft.Container`

Antes de la refactorización se detectaron varios bloques manuales de este tipo en Documentos/Box:

```python
ft.Container(
    bgcolor="#F8FAFC",
    border=ft.border.all(1, Q_BORDER),
    border_radius=10,
    padding=8,
    content=ft.Row(...)
)
```

Estos bloques generan inconsistencias porque cada vista decide por su cuenta el fondo, borde, padding, alto, selección y acciones. En grupos documentales ya se sustituyó un bloque manual por `document_file_card(...)`, reduciendo una tarjeta manual de `ft.Container` a una tarjeta documental estándar.

### Corrección correcta

Cualquier documento visible en:

```text
- Bandeja documental
- Grupos documentales
- Documentos de Box
- Documentos vinculados a expediente
- Documentos en “PARA PRESENTAR”
- Documentos de diagnóstico
```

debe ir con:

```python
document_file_card(...)
```

No debe crearse una tarjeta manual con `ft.Container`, salvo caso excepcional y justificado.

## 4. Tercera causa: `expand=True` usado como separador o dentro de toolbars compactas

La resolución de componentes advierte expresamente que `ft.Container(expand=True)` no debe usarse como separador visual dentro de barras compactas, cabeceras, filas de acciones o toolbars, porque ya se ha detectado que puede provocar cuadros grises o huecos gigantes en composiciones Flet.

El uso correcto de `expand=True` debe limitarse a:

```text
- áreas principales de contenido;
- columnas scrollables;
- contenedores raíz;
- paneles que deben ocupar el espacio restante.
```

No debe usarse para “empujar” botones, chips o menús dentro de una fila.

### Patrón problemático

```python
ft.Row(
    controls=[
        ft.Text("Documento"),
        ft.Container(expand=True),
        secondary_button("Ver", ...),
    ]
)
```

### Patrón recomendado

```python
ft.Row(
    controls=[
        ft.Text("Documento", expand=True),
        secondary_button("Ver", ...),
    ],
    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    wrap=True,
)
```

O mejor todavía, si se trata de documentos:

```python
document_file_card(
    name=...,
    action_groups=[{"items": [...]}],
)
```

## 5. Cuarta causa: scroll aplicado a toda la página en vez de solo a la lista de cards

Otro origen de “bloques grises” o sensación de layout roto aparece cuando se aplica:

```python
scroll=ft.ScrollMode.AUTO
```

a la columna raíz de la vista. En ese caso hacen scroll la cabecera, chips, paginación, barra de selección y cards. Esto produce una sensación visual inestable y puede generar espacios raros cuando Flet recalcula alturas.

En la cola de presentación se corrigió moviendo el scroll desde la columna raíz a la columna interna de cards. El patrón correcto es:

```python
return ft.Column(
    controls=[
        header,
        filters,
        pagination,
        ft.Container(
            expand=True,
            content=ft.Column(
                controls=cards_controls,
                spacing=8,
                expand=True,
                scroll=ft.ScrollMode.AUTO,
            ),
        ),
    ],
    expand=True,
)
```

No:

```python
return ft.Column(
    controls=[header, filters, pagination, *cards],
    expand=True,
    scroll=ft.ScrollMode.AUTO,
)
```

La resolución oficial permite `expand=True` cuando se usa en columnas scrollables o áreas principales, pero no como separador visual.

## 6. Quinta causa: acciones por fila como botones visibles en vez de menú `⋮`

En Documentos/Box, cuando cada card muestra varios botones visibles:

```text
Ver
Abrir externo
Quitar
Copiar
Vincular
```

la fila puede crecer demasiado, romper el ancho, envolver mal y generar bloques visuales grandes.

El patrón documental oficial es:

```text
Checkbox = selección masiva
⋮ = acciones individuales
bulk_action_bar = acciones sobre seleccionados
```

Por tanto, acciones individuales como “Ver”, “Abrir externo”, “Quitar”, “Copiar a Box” o “Vincular a expediente” deben preferentemente ir en `action_groups` del `document_file_card`, no como tres o cuatro botones debajo del card.

### Patrón recomendado

```python
document_file_card(
    name=...,
    path=...,
    selected=is_selected,
    selectable=True,
    checkbox_value=is_selected,
    on_select=lambda e: toggle_selection(document_id),
    action_groups=[
        {
            "items": [
                {"label": "Ver", "on_click": lambda e: preview_document(document_id)},
                {"label": "Abrir externo", "on_click": lambda e: open_external(document_id)},
                {"label": "Quitar", "on_click": lambda e: remove_document(document_id), "danger": True},
            ]
        }
    ],
)
```

Esto coloca las acciones en el menú `⋮` y evita que el card gane altura innecesaria.

## 7. Sexta causa: selección visual duplicada

Hay que evitar mezclar dos sistemas de selección visual al mismo tiempo:

```text
1. Checkbox marcado.
2. Fondo del card cambiado.
3. Fila externa resaltada.
4. Container padre con bgcolor distinto.
```

En documentos, el estándar debe ser:

```text
checkbox marcado = seleccionado
bulk_action_bar visible = hay selección
card con fondo blanco = sin cuadro gris
```

Por tanto, si el documento es seleccionable, el card debería recibir:

```python
selected=is_selected
selectable=True
checkbox_value=is_selected
```

y no debería envolverse además en otro `ft.Container(bgcolor="#F2F4F7")` o similar.

## 8. Cómo localizar el problema con grep

Antes de tocar Documentos/Box, el técnico debería ejecutar:

```bash
grep -RIn "document_file_card(" frontend/views/document_inbox_view.py frontend/views/expedients_view.py frontend/views/box_watch_view.py
```

Después:

```bash
grep -RIn "selected=.*selectable\|selectable=.*selected" frontend/views/document_inbox_view.py frontend/views/expedients_view.py frontend/views/box_watch_view.py
```

Y para localizar contenedores manuales sospechosos:

```bash
grep -RIn "bgcolor=\"#F8FAFC\"\|bgcolor=\"#F2F4F7\"\|bgcolor=\"#EFF8FF\"\|ft.Container(" frontend/views/document_inbox_view.py frontend/views/expedients_view.py frontend/views/box_watch_view.py
```

Para localizar uso peligroso de `expand=True`:

```bash
grep -RIn "ft.Container(expand=True)\|expand=True" frontend/views/document_inbox_view.py frontend/views/expedients_view.py frontend/views/box_watch_view.py
```

La resolución oficial ya exige revisar imports de componentes y usos manuales de `ft.Container`, `ft.IconButton`, `ft.AlertDialog`, `ft.ElevatedButton`, `ft.OutlinedButton` y `ft.TextButton` antes de modificar vistas grandes como `document_inbox_view.py`, `expedients_view.py` o `box_watch_view.py`.

## 9. Patrón estándar recomendado para Documentos/Box

Para cada documento:

```python
is_selected = document_id in selected_ids

return document_file_card(
    name=document.get("original_filename") or document.get("stored_filename") or "-",
    path=document.get("stored_path") or document.get("linked_document_path") or "",
    relative_path=document.get("relative_path") or "",
    folder=document.get("folder") or "",
    size_label=document.get("size_label") or "",
    modified_at=document.get("modified_at") or "",
    file_type=document.get("file_type") or "",
    selected=is_selected,
    selectable=True,
    checkbox_value=is_selected,
    on_select=lambda e, did=document_id: toggle_document_selection(did),
    extra_lines=[
        # líneas de estado, origen, expediente, grupo, etc.
    ],
    action_groups=[
        {
            "items": [
                {"label": "Ver", "on_click": lambda e, d=document: show_preview(d)},
                {"label": "Abrir externo", "on_click": lambda e, d=document: open_external(d)},
                {"label": "Copiar a Box", "on_click": lambda e, d=document: copy_to_box(d)},
                {"label": "Quitar", "on_click": lambda e, d=document: remove_document(d), "danger": True},
            ]
        }
    ],
    compact=False,
)
```

Para la barra superior de acciones masivas:

```python
bulk_action_bar(
    title="Documentos seleccionados",
    selected_count=len(selected_ids),
    on_clear=clear_selection,
    actions=[
        {
            "icon": ft.Icons.CHECK_CIRCLE_OUTLINE,
            "tooltip": "Marcar revisados",
            "on_click": mark_selected_reviewed,
        },
        {
            "icon": ft.Icons.DELETE_OUTLINE,
            "tooltip": "Descartar seleccionados",
            "on_click": discard_selected,
            "danger": True,
        },
    ],
)
```

Para paginación:

```python
compact_pagination_bar(
    page=current_page,
    page_size=page_size,
    total_items=total_items,
    on_page_change=set_page,
    label_prefix="Documentos",
)
```

## 10. Corrección mínima recomendada

Si aparece el cuadro gris en una vista documental, revisar en este orden:

1. Buscar `document_file_card(...)`.
2. Ver si recibe `selected=...`.
3. Si recibe `selected`, comprobar que también recibe:

   ```python
   selectable=True
   checkbox_value=...
   on_select=...
   ```
4. Eliminar wrappers externos tipo:

   ```python
   ft.Container(bgcolor="#F8FAFC" ...)
   ```

   si solo se usan para pintar el documento.
5. Mover acciones visibles a `action_groups`.
6. Sustituir filas manuales de seleccionados por `bulk_action_bar`.
7. Mover el scroll a la columna de cards, no a toda la página.
8. Evitar `ft.Container(expand=True)` como separador en toolbars.

## 11. Criterio de aceptación

La corrección se considera correcta si:

```text
- El documento se ve con document_file_card.
- El checkbox marca la selección.
- No aparece fondo gris/azul salvo que sea intencional.
- Las acciones individuales están en ⋮.
- Las acciones masivas están en bulk_action_bar.
- La paginación usa compact_pagination_bar.
- El scroll afecta solo a la lista de cards.
- No se toca backend.
- No se toca database.
- La vista compila y arranca.
```

Validación mínima:

```bash
python -m py_compile \
  frontend/components/document_file_card.py \
  frontend/components/bulk_action_bar.py \
  frontend/components/listing/compact_pagination_bar.py \
  frontend/views/document_inbox_view.py \
  frontend/views/expedients_view.py \
  app/main.py

python -m app.main

git diff -- frontend/views/document_inbox_view.py frontend/views/expedients_view.py
```

## 12. Conclusión

El “cuadro gris” no debe tratarse como un bug de datos ni de backend. Es un síntoma de layout y composición UI.

La causa más probable es una de estas:

```text
1. document_file_card con selected=True pero sin selectable=True.
2. Contenedores manuales documentales con bgcolor gris.
3. Uso de expand=True como separador visual.
4. Scroll aplicado a toda la vista.
5. Acciones visibles que ensanchan o elevan el card.
6. Selección visual duplicada entre checkbox, fondo del card y wrapper externo.
```

La solución oficial es consolidar el patrón documental:

```text
document_file_card + checkbox + menú ⋮ + bulk_action_bar + compact_pagination_bar + scroll solo en cards
```

Ese patrón ya está alineado con la resolución oficial de componentes reutilizables del CRM y debe aplicarse en Documentos/Box antes de seguir creando nuevos bloques visuales manuales.
