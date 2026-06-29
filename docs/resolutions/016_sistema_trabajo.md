# RESOLUCIÓN INTERNA QA-DEV-001/2026

## Metodología oficial de desarrollo asistido mediante diagnóstico incremental, grep, sed y parches Bash

**Entidad:** Quesada Abogados
**Proyecto:** CRM / ERP interno de extranjería, documentación, expedientes, Box, presentación asistida y automatización operativa
**Fecha:** 29 de junio de 2026
**Ámbito:** Desarrollo, mantenimiento, depuración y ampliación del sistema CRM/ERP interno
**Carácter:** Resolución metodológica oficial del proyecto

---

## I. Objeto de la resolución

La presente resolución establece como metodología oficial de trabajo del proyecto CRM/ERP de Quesada Abogados el desarrollo incremental basado en diagnóstico mediante consola, uso de comandos `grep`, `sed`, scripts Bash, parches quirúrgicos, validación por compilación, prueba funcional, commits atómicos y control estricto de ramas Git.

Esta metodología se adopta tras comprobar que el envío y sustitución de archivos completos puede provocar regresiones, pérdida de cambios recientes, sobrescritura con versiones antiguas y dificultad para localizar errores en módulos extensos. En cambio, el trabajo mediante búsquedas dirigidas, extracción de fragmentos concretos y aplicación de parches localizados permite mantener el contexto real del repositorio y avanzar con mayor seguridad.

---

## II. Principio rector

El principio rector del desarrollo será:

**No sustituir archivos completos salvo necesidad justificada. Diagnosticar primero, modificar después, validar siempre y commitear únicamente estados funcionales.**

El sistema CRM de Quesada Abogados está creciendo en módulos, servicios, vistas, integraciones y automatizaciones. Por ello, la eficiencia ya no depende de trabajar con grandes bloques de código, sino de actuar con precisión sobre el punto exacto del sistema que debe cambiarse.

---

## III. Motivos de adopción

Se declara que el método basado en `grep`, `sed` y parches Bash es el más eficiente para el estado actual del proyecto por los siguientes motivos:

1. **Evita trabajar sobre versiones antiguas.**
   Al inspeccionar directamente el repositorio local mediante consola, se trabaja siempre sobre el código real que existe en la rama actual.

2. **Reduce regresiones.**
   Los cambios son quirúrgicos y localizados, por lo que se minimiza el riesgo de romper funcionalidades ya estables.

3. **Permite diagnosticar antes de modificar.**
   El uso de `grep`, `sed`, `git diff`, `git status` y `py_compile` permite saber qué existe, dónde está, cómo se llama y qué firma tiene cada función antes de tocarla.

4. **Facilita la trazabilidad.**
   Cada mejora queda vinculada a un parche, una validación y un commit concreto.

5. **Acelera el desarrollo asistido por IA.**
   La IA no necesita reconstruir archivos completos ni inferir estructuras; puede operar sobre fragmentos exactos aportados por la terminal.

6. **Mejora el control del usuario/desarrollador.**
   El responsable del proyecto puede ver cada comando, cada cambio y cada resultado antes de consolidarlo.

7. **Permite escalar el proyecto por módulos.**
   Esta metodología es especialmente adecuada para un CRM compuesto por clientes, expedientes, documentos, Box, presentación asistida, fiscalidad, comunicaciones, watchdogs y futuras integraciones.

---

## IV. Herramientas oficiales de diagnóstico

Se establecen como herramientas básicas de diagnóstico las siguientes:

### 1. `git status`

Uso obligatorio antes y después de cada bloque de trabajo.

Permite saber:

* Rama actual.
* Archivos modificados.
* Si existen cambios pendientes.
* Si el árbol está limpio antes de iniciar un nuevo parche.

Ejemplo:

```bash
git status
```

---

### 2. `grep`

Herramienta principal para localizar funciones, clases, imports, llamadas, servicios y referencias cruzadas.

Ejemplos:

```bash
grep -R "def copy_to_box" -n frontend backend
grep -R "AppAutocomplete" -n frontend/views frontend/components
grep -R "box_folder_path" -n backend/services frontend/views
```

Uso recomendado:

* Buscar definiciones: `def nombre_funcion`.
* Buscar llamadas: `nombre_funcion(`.
* Buscar campos de base de datos: `box_folder_path`, `client_id`, `expedient_id`.
* Buscar componentes UI: `AppAutocomplete`, `AlertDialog`, `Container`.
* Buscar imports existentes antes de añadir nuevos.

---

### 3. `sed`

Herramienta oficial para extraer fragmentos concretos sin enviar archivos completos.

Ejemplos:

```bash
sed -n '780,825p' frontend/views/document_inbox_view.py
sed -n '900,970p' backend/services/document_inbox_service.py
sed -n '1,80p' frontend/components/app_autocomplete.py
```

Uso recomendado:

* Ver una función completa.
* Ver imports iniciales.
* Ver una zona de error indicada por traceback.
* Ver el bloque exacto donde se insertará un parche.

---

### 4. `python -m py_compile`

Validación mínima obligatoria tras cada parche Python.

Ejemplo:

```bash
python -m py_compile \
  frontend/views/document_inbox_view.py \
  backend/services/document_inbox_service.py \
  app/main.py
```

Esta validación evita consolidar errores de sintaxis, problemas de escape, imports rotos o fallos evidentes antes de arrancar la aplicación.

---

### 5. `python -m app.main`

Prueba funcional manual tras compilar.

Se utilizará para validar:

* Que la aplicación arranca.
* Que la vista modificada abre.
* Que no aparecen errores en eventos Flet.
* Que el comportamiento funcional coincide con el objetivo.

---

### 6. `git diff`

Herramienta recomendada antes del commit.

Ejemplo:

```bash
git diff -- frontend/views/document_inbox_view.py
```

Permite revisar el alcance real del parche y comprobar que no se han introducido modificaciones ajenas al objetivo.

---

## V. Sistema oficial de parches Bash

Se adopta como técnica preferente la creación de scripts temporales en `/tmp`, con nombre descriptivo y versión incremental.

Ejemplo:

```bash
cat > /tmp/patch_document_inbox_detail_autocomplete_v1.sh <<'BASH'
set -e

echo "== Descripción del parche =="

python - <<'PY'
from pathlib import Path

path = Path("frontend/views/document_inbox_view.py")
text = path.read_text(encoding="utf-8")

# modificación quirúrgica

path.write_text(text, encoding="utf-8")
print("OK")
PY

python -m py_compile frontend/views/document_inbox_view.py app/main.py

echo "== OK =="
BASH

bash /tmp/patch_document_inbox_detail_autocomplete_v1.sh
```

Todo parche deberá seguir, salvo causa justificada, esta estructura:

1. `set -e`.
2. Mensaje descriptivo.
3. Lectura del archivo con `Path`.
4. Búsqueda exacta del bloque.
5. Sustitución controlada.
6. Escritura en UTF-8.
7. `py_compile`.
8. Mensaje final OK.

---

## VI. Reglas de seguridad del parcheo

Se establecen las siguientes reglas obligatorias:

### 1. No parchear a ciegas

Antes de modificar una zona sensible, debe diagnosticarse con `grep` o `sed`.

### 2. No reemplazar archivos completos

Solo se reemplazará un archivo completo cuando:

* Sea un archivo nuevo.
* Sea una plantilla generada.
* Exista autorización expresa.
* El archivo sea pequeño y esté completamente bajo control.

### 3. Cada parche debe tener un único objetivo

Ejemplos correctos:

* “Añadir autocomplete de cliente”.
* “Corregir firma de AppAutocomplete”.
* “Listar directorios reales de Box”.
* “Hacer que copiar a Box use subdirectorio seleccionado”.

Ejemplos incorrectos:

* “Arreglar toda la bandeja documental”.
* “Rehacer la vista”.
* “Optimizar módulo documentos entero”.

### 4. Validar antes de continuar

No se debe aplicar un segundo parche grande si el primero no compila.

### 5. Ante error de interfaz, aislar

Si Flet muestra cuadro gris, error de `Control`, `AlertDialog`, `Tabs`, reutilización de controles o errores de evento, se deberá:

* Leer traceback.
* Localizar línea exacta.
* Revisar el bloque con `sed`.
* Corregir sin reestructurar todo el módulo.

### 6. No reutilizar controles Flet en varios sitios

En Flet, un mismo control no debe insertarse en varias zonas de la UI. Si una ficha, diálogo o pestaña necesita un control, debe crear su propia instancia.

### 7. Preferir wrappers propios en diálogos

Cuando una acción se reutiliza desde una ficha o diálogo, se recomienda crear un wrapper específico que ajuste el estado local antes de llamar a la acción principal.

---

## VII. Ciclo oficial de trabajo

Se declara como ciclo oficial el siguiente:

### Fase 1. Diagnóstico

```bash
git status
grep -R "termino" -n frontend backend
sed -n 'inicio,finp' archivo.py
```

Objetivo: entender el estado real del código.

---

### Fase 2. Parche quirúrgico

Crear script Bash versionado en `/tmp`.

Ejemplo:

```bash
/tmp/patch_modulo_objetivo_v1.sh
/tmp/patch_modulo_objetivo_v2.sh
/tmp/patch_modulo_objetivo_v3.sh
```

---

### Fase 3. Compilación

```bash
python -m py_compile archivo_modificado.py app/main.py
```

---

### Fase 4. Prueba funcional

```bash
python -m app.main
```

Validar manualmente la pantalla o flujo afectado.

---

### Fase 5. Commit atómico

Solo si funciona:

```bash
git status
git add archivo_modificado.py
git commit -m "feat/modulo: descripción concreta"
git push origin nombre-rama
git status
```

---

### Fase 6. Siguiente mejora

Una vez limpio el árbol, se aborda el siguiente comportamiento.

---

## VIII. Política de commits

Los commits deberán ser:

* Pequeños.
* Funcionales.
* Reversibles.
* Descriptivos.
* Asociados a una mejora concreta.

Formato recomendado:

```text
feat(documentos): añadir autocompletes en ficha documental
fix(documentos): corregir copia a subdirectorio Box
refactor(expedientes): aislar visor documental compartido
fix(mercurio): mapear piso del familiar
```

No se recomienda commitear:

* Estados que no compilan.
* Cambios mezclados de varios módulos.
* Pruebas temporales.
* Código comentado sin justificar.
* Cambios de formato masivo no solicitados.

---

## IX. Política de ramas

Se mantendrá el uso de ramas específicas por funcionalidad o corrección.

Ejemplos:

```text
feature/document-inbox-v10-traceability
fix/mercurio-ex01-familiar-piso
feature/ex01-renovacion-titular-specific-data
```

La rama `develop` se reservará para integrar estados funcionales ya probados.

No se trabajará directamente sobre `main` salvo decisión expresa.

---

## X. Gestión de errores

Ante un error, se actuará conforme a este protocolo:

### 1. Leer el traceback completo

Identificar:

* Archivo.
* Línea.
* Función.
* Tipo de error.
* Evento que lo dispara.

### 2. Extraer zona exacta

```bash
sed -n 'linea_inicio,linea_finp' archivo.py
```

### 3. Corregir solo la causa

No rediseñar el módulo entero si el error es local.

### 4. Compilar

```bash
python -m py_compile archivo.py
```

### 5. Probar

```bash
python -m app.main
```

### 6. Confirmar o revertir

Si el parche empeora la situación:

```bash
git restore archivo.py
```

o, si ya existe commit:

```bash
git revert commit_id
```

---

## XI. Criterio especial para módulos grandes

En módulos extensos como:

* `document_inbox_view.py`
* `expedients_view.py`
* `settings_view.py`
* `mercurio_mapper_service.py`
* `presentation_assistant_service.py`
* `box_watch_service.py`

queda prohibido modificar el archivo entero sin diagnóstico previo.

La forma correcta será:

```bash
grep -n "funcion_objetivo" archivo.py
sed -n 'inicio,finp' archivo.py
```

Y después parche sobre bloque exacto.

---

## XII. Criterio especial para la Bandeja Documental

En la Bandeja Documental se aplican reglas adicionales:

1. No mover ni borrar archivos originales de Box.
2. La bandeja observa, copia, clasifica y registra.
3. Las fichas documentales deben tener controles propios.
4. Las acciones de ficha no deben romper la lista principal.
5. La trazabilidad debe preservarse.
6. Los documentos copiados deben registrar ruta destino.
7. Cualquier automatización debe poder auditarse.

---

## XIII. Criterio especial para Box

El sistema Box debe respetar estos principios:

1. Box es fuente documental operativa.
2. El CRM no debe destruir estructura existente.
3. La copia a expediente debe ser explícita.
4. Si existe directorio seleccionado, debe usarse ese directorio.
5. Si no existe directorio seleccionado, se usará la raíz del expediente.
6. Toda ruta destino deberá quedar registrada.
7. El sistema debe tolerar carpetas antiguas, nombres manuales y estructuras no homogéneas.

---

## XIV. Ventajas estratégicas para Quesada Abogados

Esta metodología permitirá:

* Avanzar con rapidez sin romper módulos estables.
* Delegar tareas a chats especializados sin perder contexto técnico.
* Crear informes claros entre chats de trabajo.
* Mantener historial Git comprensible.
* Facilitar auditoría de decisiones técnicas.
* Reducir dependencia de memoria conversacional.
* Convertir el repositorio en la fuente real de verdad.
* Escalar el CRM hacia módulos más complejos: comunicaciones, fiscal, knowledge, watchdogs, presentación asistida, Telegram, Box y DEHú.

---

## XV. Decisión final

Quesada Abogados adopta oficialmente el método de desarrollo incremental mediante:

```text
grep → sed → diagnóstico → parche Bash → py_compile → prueba funcional → commit → push
```

como estándar preferente para continuar el desarrollo del CRM/ERP interno.

Esta resolución será incorporada como fuente del proyecto y deberá ser tenida en cuenta en futuros chats técnicos, informes de continuidad, módulos especializados y decisiones de arquitectura.

---

## XVI. Fórmula operativa resumida

Para cualquier mejora futura, el flujo estándar será:

```bash
git status

grep -R "objetivo" -n frontend backend database

sed -n 'inicio,finp' archivo.py

cat > /tmp/patch_nombre_v1.sh <<'BASH'
set -e
python - <<'PY'
from pathlib import Path
path = Path("archivo.py")
text = path.read_text(encoding="utf-8")
# cambio quirúrgico
path.write_text(text, encoding="utf-8")
PY
python -m py_compile archivo.py app/main.py
BASH

bash /tmp/patch_nombre_v1.sh

python -m app.main

git diff -- archivo.py

git add archivo.py
git commit -m "feat/modulo: cambio concreto"
git push origin rama_actual
git status
```

---

**Se aprueba esta resolución como metodología oficial interna del proyecto CRM/ERP de Quesada Abogados.**
