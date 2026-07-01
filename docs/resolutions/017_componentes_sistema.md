## 1. Objeto

La presente resolución establece la obligatoriedad de utilizar los componentes UI reutilizables existentes en el CRM Quesada Abogados antes de crear nuevos bloques visuales manuales en vistas Flet.

Esta resolución nace como consecuencia directa del diagnóstico del ecosistema `frontend/components`, donde se ha constatado que ya existe una base funcional de componentes reutilizables, pero también una deuda creciente derivada de:

- duplicación de bloques visuales;
- creación manual de botones, contenedores, diálogos y barras de acciones;
- refactorizaciones repetidas sobre patrones ya resueltos;
- riesgo de inconsistencias visuales;
- errores de layout derivados de usos inadecuados de `expand=True`;
- existencia de componentes antiguos o no adoptados.

La finalidad de esta resolución es evitar que el CRM vuelva a necesitar refactorizaciones masivas por no haber usado los componentes existentes desde el primer desarrollo.

---

## 2. Principio general obligatorio

A partir de esta resolución:

> Ningún desarrollo nuevo de interfaz Flet deberá implementar manualmente un patrón visual que ya exista como componente reutilizable en `frontend/components`.

Antes de escribir UI nueva en una vista, el desarrollador deberá comprobar si existe un componente aplicable.

El orden correcto de decisión será:

```text
1. Reutilizar componente existente.
2. Extender componente existente si la necesidad es compatible.
3. Crear nuevo componente reusable si el patrón se repetirá.
4. Solo escribir UI manual si es un caso excepcional, local y no reutilizable.

Queda prohibido crear bloques manuales repetidos de ft.Container, ft.Row, ft.IconButton, ft.ElevatedButton, ft.AlertDialog o tarjetas documentales cuando ya exista un componente equivalente.

3. Componentes existentes del sistema
3.1. Componentes base

Los siguientes componentes forman parte de la base UI obligatoria:

frontend/components/app_action_row.py
frontend/components/app_alert.py
frontend/components/app_autocomplete.py
frontend/components/app_badge.py
frontend/components/app_button.py
frontend/components/app_card.py
frontend/components/app_detail_section.py
frontend/components/app_dialog.py
frontend/components/app_dropdown.py
frontend/components/app_empty_state.py
frontend/components/app_filter_bar.py
frontend/components/app_loader.py
frontend/components/app_table.py
frontend/components/app_text_field.py

Uso obligatorio:

botones;
inputs;
dropdowns;
alertas;
estados vacíos;
tablas;
badges;
filas de acciones;
formularios base.
3.2. Componentes funcionales o de dominio
frontend/components/bulk_action_bar.py
frontend/components/client_context_panel.py
frontend/components/config_section_card.py
frontend/components/document_file_card.py
frontend/components/document_rule_row.py
frontend/components/document_viewer_modal.py
frontend/components/economic_badge.py
frontend/components/expedient_status_badge.py
frontend/components/settings_sidebar.py
frontend/components/traceability_badge.py

Uso obligatorio cuando corresponda al dominio funcional.

Especialmente:

document_file_card.py para documentos.
bulk_action_bar.py para acciones masivas.
document_viewer_modal.py para visor documental.
client_context_panel.py para contexto de cliente.
config_section_card.py para secciones de configuración.
settings_sidebar.py para navegación lateral de settings.
3.3. Componentes de listing
frontend/components/listing/card_item.py
frontend/components/listing/compact_pagination_bar.py
frontend/components/listing/counter_chips.py
frontend/components/listing/pagination_bar.py
frontend/components/listing/status_chip.py

Uso obligatorio:

paginación compacta;
chips de estado;
contadores por estado;
tarjetas genéricas de listado cuando sigan vigentes.
4. Componentes declarados estándar
4.1. Botones

Todo botón estándar deberá usar:

primary_button(...)
secondary_button(...)
danger_button(...)

Queda prohibido crear nuevos botones manuales con:

ft.ElevatedButton(...)
ft.OutlinedButton(...)
ft.TextButton(...)

salvo dentro de un componente reutilizable o en casos justificados.

Las vistas que todavía tengan helpers locales, como _primary_button o _secondary_button, deberán migrarse progresivamente a app_button.py.

Prioridad de migración:

1. companies_view.py
2. company_detail_view.py
3. reporting_view.py
4.2. Inputs y formularios

Todo campo de texto estándar deberá usar:

text_input(...)
required_text_input(...)
multiline_input(...)

Todo selector simple deberá usar:

select_input(...)

Todo autocomplete deberá usar:

AppAutocomplete(...)

Queda desaconsejado crear ft.TextField manuales salvo cuando se trate de una necesidad técnica no cubierta por el componente base.

4.3. Estados vacíos

Todo estado vacío deberá usar:

empty_state(...)

No deberán escribirse textos sueltos o contenedores manuales para representar listas sin resultados si el caso encaja en empty_state.

4.4. Alertas

Todo mensaje de éxito o error deberá usar:

success_alert(...)
error_alert(...)

No deberán crearse contenedores manuales de alerta salvo que se esté desarrollando un nuevo componente de alerta reutilizable.

4.5. Tablas

Las tablas estándar deberán usar:

app_table(...)

Si una tabla necesita selección, acciones por fila, paginación o filtros, deberá valorarse extender app_table antes de escribir una tabla manual.

5. Regla documental obligatoria

Todo elemento documental visible en UI deberá representarse preferentemente con:

document_file_card(...)

Esto incluye:

documentos importados;
documentos de la bandeja documental;
documentos dentro de grupos documentales;
archivos de Box;
documentos vinculados a expedientes;
documentos en colas de presentación;
documentos administrativos;
documentos de diagnóstico.

Regla visual oficial:

Documento visible = document_file_card
Checkbox = selección masiva
⋮ = acciones individuales
bulk_action_bar = acciones sobre seleccionados
document_viewer_modal = visor documental

Queda prohibido volver a crear tarjetas documentales manuales salvo justificación expresa.

6. Regla de acciones masivas

Toda barra de acciones sobre elementos seleccionados deberá usar:

bulk_action_bar(...)

No deberán escribirse manualmente filas con:

ft.Text("Seleccionados: ...")
ft.IconButton(...)
ft.IconButton(...)

El patrón oficial será:

bulk_action_bar(
    title="...",
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

La paginación no deberá incluirse dentro de bulk_action_bar.

7. Regla de paginación

La paginación compacta deberá usar:

compact_pagination_bar(...)

La paginación no forma parte de la barra de acciones masivas.

Separación obligatoria:

bulk_action_bar = acciones sobre selección
compact_pagination_bar = navegación de páginas
counter_chips = contadores por estado
list_panel_header = futuro componente para cabecera completa
8. Regla de estados y contadores

Los estados deberán representarse con:

status_chip(...)

Los contadores por estado deberán representarse con:

counter_chips(...)

Queda desaconsejado crear chips manuales de estado con ft.Container salvo que el estado sea completamente específico y no reutilizable.

9. Regla de paneles y contenedores

El diagnóstico ha detectado una repetición masiva del patrón:

ft.Container(
    bgcolor="#FFFFFF",
    border=ft.border.all(1, Q_BORDER),
    border_radius=...,
    padding=...,
    content=...
)

Hasta que exista un componente específico, deberá evitarse seguir multiplicando este patrón.

Se declara prioritaria la creación de:

frontend/components/panel_container.py

Objetivo del futuro componente:

panel_container(
    content=...,
    title=None,
    subtitle=None,
    actions=None,
    padding=10,
    compact=False,
)

Una vez creado, su uso será obligatorio para paneles, secciones y tarjetas estructurales.

10. Regla sobre expand=True

Queda establecida la siguiente regla de layout:

No se utilizará ft.Container(expand=True) como separador visual dentro de barras compactas, cabeceras, filas de acciones o toolbars.

Motivo:

Ya se ha detectado que este patrón puede provocar cuadros grises o huecos gigantes en determinadas composiciones Flet.

Alternativas recomendadas:

wrap=True
spacing=...
alignment=...
MainAxisAlignment.SPACE_BETWEEN
componentes específicos de toolbar

expand=True solo deberá usarse cuando exista una razón estructural clara:

áreas principales de contenido;
columnas scrollables;
contenedores raíz;
paneles que deben ocupar el espacio restante.
11. Componentes a revisar
11.1. document_rule_row.py

El diagnóstico detecta que no tiene usos externos reales.

Decisión:

no crear nuevas dependencias sin revisar su finalidad;
decidir si debe integrarse en Settings/documentos requeridos;
si no tiene utilidad real, mover a legacy o eliminar.
11.2. card_item.py

El diagnóstico indica que está importado, pero no aparece usado como llamada real activa en las vistas actuales.

Decisión:

revisar si queda como componente legacy;
eliminar importaciones sobrantes;
no usarlo para documentos, porque el estándar documental es document_file_card.
11.3. pagination_bar.py

Existe junto a compact_pagination_bar.py.

Decisión:

mantenerlo solo si cubre un caso distinto;
usar compact_pagination_bar como estándar actual para listados compactos.
12. Obligación antes de crear nuevo componente

Antes de crear un componente nuevo, el desarrollador deberá responder:

1. ¿Existe ya un componente que cubra el caso?
2. ¿Puede ampliarse uno existente sin romper usos actuales?
3. ¿El patrón se repetirá en dos o más vistas?
4. ¿Tiene sentido como componente de dominio o como componente base?
5. ¿Qué vistas lo adoptarán inmediatamente?

No se aprobarán componentes nuevos que no tengan:

nombre claro;
API mínima;
primer uso real;
justificación de reutilización;
ubicación correcta dentro de frontend/components.
13. Obligación antes de tocar una vista existente

Antes de modificar una vista grande, especialmente:

clients_view.py
client_detail_view.py
companies_view.py
company_detail_view.py
document_inbox_view.py
expedients_view.py
settings_view.py
box_watch_view.py
reporting_view.py
economic_view.py

el desarrollador deberá comprobar:

grep -n "from frontend.components" frontend/views/NOMBRE_VISTA.py
grep -n "ft.Container\|ft.IconButton\|ft.AlertDialog\|ft.ElevatedButton\|ft.OutlinedButton\|ft.TextButton" frontend/views/NOMBRE_VISTA.py

Si el cambio introduce un patrón ya existente como componente, deberá usarse el componente.

14. Prohibiciones expresas

Queda prohibido, salvo justificación:

1. Crear nuevas tarjetas documentales manuales.
2. Crear barras de acciones masivas manuales.
3. Crear botones manuales si existen primary_button/secondary_button/danger_button.
4. Crear inputs manuales si existen text_input/required_text_input/multiline_input.
5. Crear estados vacíos manuales si existe empty_state.
6. Crear chips de estado manuales si existe status_chip.
7. Crear paginaciones manuales si existe compact_pagination_bar.
8. Usar ft.Container(expand=True) como separador visual.
9. Duplicar helpers locales de botón o input en vistas nuevas.
10. Añadir componentes nuevos sin revisar primero el inventario.
15. Flujo obligatorio de desarrollo UI

Todo desarrollo UI seguirá este flujo:

1. Revisar componentes existentes.
2. Elegir componente estándar.
3. Adaptar la vista mediante parche quirúrgico.
4. Ejecutar py_compile.
5. Ejecutar app.
6. Revisar visualmente.
7. Commit pequeño.
8. Merge a develop solo tras validación.

Comandos mínimos:

python -m py_compile \
  frontend/components/*.py \
  frontend/views/VISTA_AFECTADA.py \
  app/main.py

python -m app.main
16. Inventario oficial resumido
Uso obligatorio inmediato
app_button.py
app_text_field.py
app_dropdown.py
app_alert.py
app_empty_state.py
app_table.py
app_autocomplete.py
document_file_card.py
bulk_action_bar.py
document_viewer_modal.py
compact_pagination_bar.py
counter_chips.py
status_chip.py
Uso recomendado / en expansión
app_action_row.py
app_badge.py
app_card.py
app_detail_section.py
app_dialog.py
app_filter_bar.py
app_loader.py
client_context_panel.py
config_section_card.py
economic_badge.py
expedient_status_badge.py
settings_sidebar.py
traceability_badge.py
Pendientes de revisión
document_rule_row.py
listing/card_item.py
listing/pagination_bar.py
Pendientes de creación prioritaria
panel_container.py
list_panel_header.py
confirm_dialog.py
form_section.py
section_toolbar.py
17. Criterio de aceptación de futuras refactorizaciones

Una refactorización UI se considerará correcta si:

1. Reduce código manual repetido.
2. No cambia lógica de negocio.
3. Mantiene comportamiento anterior.
4. Usa componentes existentes.
5. Mejora coherencia visual.
6. Reduce riesgo de layout.
7. Deja la vista más fácil de mantener.

No se considerará correcta si:

1. Reescribe archivos completos sin necesidad.
2. Introduce versiones antiguas.
3. Duplica componentes existentes.
4. Rompe flujos funcionales.
5. Cambia la lógica mientras solo pretendía cambiar UI.
18. Decisión oficial

Desde esta resolución, el sistema de componentes de frontend/components pasa a tener carácter obligatorio para el desarrollo UI del CRM Quesada Abogados.

Toda nueva pantalla, módulo, diálogo, listado o tarjeta deberá construirse usando los componentes existentes cuando corresponda.

La creación manual de UI queda limitada a casos excepcionales, justificados y preferentemente temporales.

Esta resolución deberá ser utilizada como fuente de conocimiento del proyecto y como instrucción para cualquier chat o desarrollador encargado de widgets, vistas o refactorizaciones frontend.

MD

python -m py_compile app/main.py

git status


## Commit

```bash
git add docs/resolutions/017_obligatoriedad_componentes_ui.md
git commit -m "docs(ui): resolver obligatoriedad de componentes reutilizables"
git push origin analysis/ui-components-diagnostic
git status