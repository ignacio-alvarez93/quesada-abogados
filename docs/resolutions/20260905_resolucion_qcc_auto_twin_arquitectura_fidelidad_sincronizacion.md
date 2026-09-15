# RESOLUCIÓN AUTO TWIN

## Arquitectura, fidelidad, descubrimiento y sincronización continua mediante QCC

**Fecha:** 04/09/2026
**Proyecto:** Quesada Abogados · Quesada Chrome Companion (QCC)
**Estado:** RESUELTO / ARQUITECTURA APROBADA

---

## 1. Objeto

Se aprueba la creación de **AUTO TWIN** como capacidad estructural de **Quesada Chrome Companion (QCC)** destinada a construir, mantener, actualizar, versionar y validar réplicas locales de sedes electrónicas y otras aplicaciones web observadas por QCC.

AUTO TWIN sustituirá progresivamente la reconstrucción manual pantalla por pantalla.

Su objetivo no será únicamente disponer de una simulación funcional de una sede, sino alcanzar una **fidelidad máxima visual, geométrica, estructural e interactiva**, de forma que el TWIN pueda utilizarse para:

* desarrollo de automatizaciones;
* regresión ante cambios de las sedes;
* validación de selectores;
* validación de navegación;
* pruebas SeleniumBase;
* pruebas de interacción humana asistida;
* pruebas y automatizaciones basadas en geometría;
* soporte a interacciones mediante ratón/teclado o PyAutoGUI cuando resulte necesario.

---

# 2. Principio de fidelidad

AUTO TWIN adopta como objetivo una **fidelidad práctica del 100 % respecto del REAL dentro de un entorno de render controlado**.

Por tanto, no se considerará suficiente que el TWIN:

* tenga los mismos campos;
* presente textos equivalentes;
* permita completar el mismo flujo;
* o resulte visualmente parecido.

Deberá reproducir, en la medida técnicamente observable:

* DOM;
* estructura jerárquica;
* CSS;
* assets;
* fuentes;
* colores;
* dimensiones;
* márgenes;
* paddings;
* posiciones;
* distribución;
* scroll;
* visibility;
* overlays;
* iframes;
* shadow DOM cuando exista;
* viewport;
* `devicePixelRatio`;
* tamaño interior y exterior de ventana;
* estados interactivos;
* controles;
* catálogos;
* dependencias entre catálogos;
* validaciones visibles;
* transiciones;
* comportamiento funcional observable.

La fidelidad geométrica tendrá especial prioridad debido a la posible utilización futura de automatizaciones basadas en coordenadas físicas.

---

# 3. Perfil de render oficial

La equivalencia visual y geométrica será evaluada respecto de un **QCC Rendering Profile** controlado.

El perfil deberá registrar como mínimo:

* versión del navegador;
* tamaño de ventana;
* `innerWidth`;
* `innerHeight`;
* `clientWidth`;
* `clientHeight`;
* `outerWidth`;
* `outerHeight`;
* zoom;
* `devicePixelRatio`;
* escala del sistema operativo;
* posición de la ventana;
* scroll X/Y;
* fuentes disponibles;
* configuración relevante del navegador.

El TWIN no estará obligado a producir identidad pixel-perfect en cualquier ordenador o configuración arbitraria.

Sí deberá producirla respecto del perfil de render sobre el que se haya generado y validado.

---

# 4. AUTO TWIN como capacidad propia de QCC

AUTO TWIN pertenecerá funcionalmente a QCC.

En:

**QCC → Gestión**

se incorporará una sección específica:

**AUTO TWINS**

con funciones como:

* Construir TWIN;
* Abrir TWIN;
* Estado;
* Sincronización;
* Estados conocidos;
* Nuevas pantallas detectadas;
* Catálogos;
* Dependencias;
* Revisiones;
* Cambios detectados;
* Validación REAL ↔ TWIN;
* Historial;
* Errores de sincronización.

La orden:

**Construir TWIN**

no significará únicamente capturar la página visible.

Significará declarar el sitio, flujo o ámbito correspondiente como **TWIN gestionado por QCC**.

Desde ese momento, QCC deberá continuar aprendiendo las nuevas pantallas y estados observados dentro de dicho ámbito.

---

# 5. Perfil SeleniumBase específico de descubrimiento

Se creará un perfil persistente de Chrome específico:

**TWIN DISCOVERY**

gestionado mediante SeleniumBase y QCC.

Este navegador tendrá como funciones principales:

* descubrimiento de nuevas sedes;
* construcción inicial de Twins;
* exploración profunda;
* extracción de arquitectura;
* captura DOM;
* captura HTML/MHTML;
* captura CSS y assets;
* captura visual;
* captura geométrica;
* descubrimiento de estados;
* aprendizaje de transiciones;
* exploración segura de catálogos;
* descubrimiento de dependencias entre catálogos;
* comprobación de estados dinámicos;
* validación de revisiones;
* diagnóstico de cambios;
* comparación REAL ↔ TWIN.

El perfil será persistente para poder conservar:

* sesiones;
* certificados cuando proceda;
* cookies;
* configuración;
* entorno de render;
* historial operativo necesario.

---

# 6. Modos del perfil TWIN DISCOVERY

El navegador podrá operar al menos en dos modos.

## DISCOVERY PASSIVE

QCC observa mientras el usuario navega.

No realiza experimentación activa.

Apto para:

* sedes desconocidas;
* primeras visitas;
* páginas sensibles.

## DISCOVERY ACTIVE

QCC podrá ejecutar exploraciones previamente clasificadas como seguras.

Ejemplos:

* expandir tabs;
* abrir accordions;
* realizar scroll;
* inspeccionar dropdowns;
* seleccionar opciones puramente catalogales;
* explorar dependencias entre selects;
* observar mutaciones;
* repetir estados sin efectos administrativos.

Toda exploración activa permanecerá subordinada a las políticas de interacción de QCC.

---

# 7. Los navegadores REAL también actualizarán AUTO TWIN

AUTO TWIN no dependerá exclusivamente del perfil `TWIN DISCOVERY`.

Los perfiles utilizados diariamente para trabajar con sedes electrónicas actuarán como una **red distribuida de observación**.

Por tanto:

```text
mercuro_assisted_01
mercuro_assisted_02
uge_assisted
dehu_assisted
...
        ↓
       QCC
        ↓
AUTO TWIN CHANGE DETECTION
```

Cada navegador deberá publicar al Bridge, cuando proceda:

* browser/profile identity;
* sitio;
* URL;
* route;
* estado reconocido;
* fingerprint funcional;
* fingerprint estructural;
* geometría;
* viewport;
* evidencias visuales;
* catálogos;
* acciones observadas;
* mutaciones relevantes;
* capture ID.

De esta forma, el uso cotidiano del despacho se convierte simultáneamente en un mecanismo de vigilancia de las sedes.

---

# 8. División de responsabilidades entre perfiles

## Navegadores de presentación REAL

Deberán:

* observar siempre;
* capturar estados conocidos;
* detectar cambios;
* registrar nuevas pantallas;
* detectar cambios DOM;
* detectar cambios geométricos;
* detectar cambios CSS/visual;
* detectar cambios de catálogos;
* registrar evidencia de acciones humanas;
* alimentar el sistema de revisiones.

No deberán efectuar exploraciones activas que puedan interferir con un expediente real.

---

## Perfil TWIN DISCOVERY

Además de todo lo anterior podrá:

* explorar;
* recorrer;
* comparar;
* repetir estados;
* profundizar;
* probar dependencias seguras;
* construir;
* regenerar;
* validar.

---

# 9. Principio de seguridad

La existencia de AUTO TWIN no altera las políticas de interacción segura de las sedes.

Una acción seguirá siendo:

* `AUTOMATION_ALLOWED`;
* `OBSERVATION_ONLY`;
* `HUMAN_ONLY`;

independientemente del objetivo de descubrimiento.

En Mercurio, particularmente, acciones sensibles como:

* Continuar;
* Adjuntar;
* Firmar;
* Registrar;
* Presentar;

permanecerán HUMAN_ONLY cuando así lo determine la política correspondiente.

AUTO TWIN nunca podrá utilizar el modo de descubrimiento para eludir esa gobernanza.

---

# 10. Descubrimiento automático de estados

Cuando QCC encuentre una pantalla o estado desconocido dentro de un sitio gestionado:

```text
UNKNOWN STATE
    ↓
AUTO DISCOVERY
```

deberá iniciar automáticamente la adquisición necesaria.

La captura incluirá:

* DOM;
* HTML;
* MHTML cuando proceda;
* screenshot;
* geometry;
* viewport;
* acciones;
* controles;
* formularios;
* frames;
* catálogos;
* elementos dinámicos;
* assets;
* contexto;
* fingerprint;
* relaciones de navegación.

Se creará un nuevo estado dentro del TWIN.

---

# 11. Catálogos

Los catálogos formarán parte integral del contrato AUTO TWIN.

Cuando aparezca un estado nuevo, QCC deberá descubrir automáticamente todos los catálogos cuya exploración pueda realizarse de forma segura.

Ejemplos:

* país;
* nacionalidad;
* provincia;
* municipio;
* estado civil;
* tipo de vía;
* tipo documental;
* procedimiento;
* opciones radio;
* listas dinámicas;
* autocompletados.

---

# 12. Catálogos dependientes

QCC deberá detectar también dependencias.

Ejemplo:

```text
PROVINCIA
   ↓
MUNICIPIO
```

o:

```text
PAÍS
 ↓
REGIÓN
 ↓
PROVINCIA
 ↓
MUNICIPIO
```

La dependencia se determinará mediante observación segura de mutaciones:

```text
cambio control A
       ↓
observación
       ↓
cambia catálogo B
       ↓
A → B
```

Las relaciones deberán persistirse como un **Catalog Dependency Graph**.

---

# 13. Registro canónico de catálogos

Los catálogos no deberán duplicarse innecesariamente por pantalla.

Se buscará identidad canónica.

Por ejemplo:

```text
MERCURIO.PROVINCIA_ES
MERCURIO.NACIONALIDAD
MERCURIO.MUNICIPIO_ES
```

Los diferentes estados podrán referenciar el mismo catálogo.

Los catálogos dependientes conservarán además su contexto.

Ejemplo:

```text
MUNICIPIO_ES
depends_on = PROVINCIA_ES
parent_value = 28
```

---

# 14. Versionado de catálogos

Los catálogos también tendrán revisiones.

Un cambio como:

* nueva opción;
* opción eliminada;
* cambio de código;
* cambio de etiqueta;
* cambio de dependencia;
* cambio de endpoint;
* cambio del mecanismo de carga;

generará una nueva revisión.

---

# 15. Detección continua de cambios REAL

Todo TWIN gestionado permanecerá sujeto a vigilancia.

Cada observación REAL deberá poder comparar el estado actual contra su baseline.

Las dimensiones principales del cambio serán:

```text
FUNCTIONAL
DOM
CSS
GEOMETRY
VISUAL
CATALOG
INTERACTION
NAVIGATION
```

No todo cambio del DOM implicará una modificación del TWIN.

Antes del fingerprint se aplicará normalización para evitar falsos positivos derivados de:

* tokens;
* timestamps;
* identificadores de sesión;
* IDs efímeros;
* valores dinámicos irrelevantes;
* analytics;
* estados transitorios.

---

# 16. Estados de cambio

La detección podrá clasificar eventos como:

```text
NO_CHANGE
CHANGE_SUSPECTED
CHANGE_CONFIRMED
REBUILD_REQUIRED
VALIDATION_REQUIRED
```

Un cambio observado por un único browser puede comenzar como:

```text
CHANGE_SUSPECTED
```

Si vuelve a observarse de manera estable o desde otra instancia:

```text
CHANGE_CONFIRMED
```

QCC podrá entonces activar automáticamente reconstrucción y validación.

---

# 17. Revisión candidata

Un TWIN validado nunca será sobrescrito ciegamente.

Ante un cambio REAL:

```text
TWIN r17
    ↓
REAL cambia
    ↓
TWIN r18 candidate
```

Se conservará `r17` hasta que `r18` pase la validación.

---

# 18. Validación REAL ↔ TWIN

La revisión candidata deberá superar, según aplicabilidad:

* DOM comparison;
* structural comparison;
* geometry comparison;
* computed-style comparison;
* screenshot/pixel comparison;
* action inventory comparison;
* catalog comparison;
* navigation comparison;
* interaction regression;
* state recognition;
* viewport/render contract.

Solo entonces podrá promocionarse:

```text
CANDIDATE
   ↓
VALIDATED
   ↓
ACTIVE
```

---

# 19. Fidelidad visual y geométrica

Para los elementos relevantes se perseguirá equivalencia exacta o tolerancia mínima técnicamente justificable.

La validación deberá poder comparar:

```text
x
y
width
height
center
visibility
scroll
z-order
```

además del render visual.

La tolerancia geométrica genérica actualmente existente en QCC no deberá utilizarse necesariamente como criterio final AUTO TWIN.

AUTO TWIN podrá tener un perfil específico de validación mucho más estricto, llegando a:

```text
0 px
```

cuando el entorno de render permita identidad exacta.

---

# 20. Validación visual

AUTO TWIN contará con comparación visual automatizada.

Se utilizarán:

* screenshots REAL;
* screenshots TWIN;
* máscaras de regiones dinámicas cuando proceda;
* comparación de píxeles;
* comparación de regiones;
* detección de desplazamientos;
* detección de diferencias cromáticas;
* validación estructural complementaria.

El objetivo será alcanzar reproducción prácticamente pixel-perfect.

---

# 21. Materialización

AUTO TWIN no reconstruirá visualmente una página “a ojo”.

El materializador deberá partir de la evidencia REAL.

Preferirá conservar o reproducir:

```text
DOM REAL
CSS REAL
ASSETS REAL
FONTS REAL
GEOMETRY REAL
```

transformando únicamente aquello necesario para ejecutar la réplica local.

---

# 22. JavaScript y comportamiento dinámico

No será requisito replicar internamente el backend remoto de la sede.

Sí será requisito reproducir el comportamiento observable necesario.

Ejemplos:

```text
select A
→ cambia select B

tab
→ aparece panel

campo inválido
→ mensaje

acción humana
→ nuevo estado
```

La implementación local podrá reproducir dicho comportamiento mediante lógica propia cuando copiar el JavaScript original no sea viable o deseable.

---

# 23. Site Architecture como fuente de verdad

El HTML generado del TWIN no será la fuente conceptual de verdad.

La arquitectura será:

```text
REAL
 ↓
QCC SITE ARCHITECTURE
 ↓
CANONICAL STATE
 ↓
AUTO TWIN MATERIALIZER
 ↓
TWIN
```

Las automatizaciones deberán apoyarse preferentemente en contratos de Site Architecture y no quedar acopladas al código generado del TWIN.

---

# 24. Aprendizaje del grafo de navegación

Mientras el usuario o SeleniumBase recorran una sede, QCC deberá aprender:

```text
STATE A
 -- action -->
STATE B
```

incluyendo:

* selector;
* acción;
* política;
* evidencia;
* before fingerprint;
* after fingerprint;
* route;
* contexto;
* confianza.

AUTO TWIN reproducirá el mismo grafo de estados.

---

# 25. Multi-browser

AUTO TWIN se diseñará desde su primera versión sobre la infraestructura multi-browser de QCC.

El Bridge será la fuente compartida.

Cada navegador aportará observaciones identificadas por:

* browser;
* profile;
* session;
* site;
* environment;
* state.

Esto permitirá combinar observaciones procedentes de múltiples navegadores sin acoplar AUTO TWIN a una instancia concreta.

---

# 26. Estado de un TWIN

Los estados de ciclo de vida serán, como mínimo:

```text
DISCOVERED
GENERATING
GENERATED
VALIDATING
VALIDATED
ACTIVE
OUTDATED
REBUILDING
FAILED_VALIDATION
```

QCC deberá mostrar este estado en Gestión.

---

# 27. Uso de las implementaciones manuales actuales

Los Twins construidos manualmente hasta la fecha no se eliminan.

Se utilizarán como:

* golden references;
* fixtures;
* contratos de regresión;
* banco de pruebas;
* base comparativa frente al generador automático.

EX01 será inicialmente el principal **Golden Twin** del sistema.

---

# 28. Estrategia de transición

Se adopta la siguiente secuencia:

```text
1. Mantener EX01 actual como referencia.
2. Construir infraestructura AUTO TWIN.
3. Regenerar EX01 automáticamente.
4. Comparar REAL / MANUAL / AUTO.
5. Alcanzar paridad.
6. Utilizar EX02 como primera construcción desde cero.
7. Eliminar progresivamente construcción manual ordinaria.
8. Mantener manual overrides únicamente como excepción.
```

---

# 29. Overrides

AUTO TWIN podrá admitir correcciones excepcionales cuando exista alguna particularidad no reproducible automáticamente.

Los overrides:

* estarán versionados;
* tendrán ámbito limitado;
* estarán documentados;
* no sustituirán el motor de generación;
* deberán reutilizarse en revisiones futuras cuando continúen siendo aplicables.

---

# 30. Principio operativo final

A partir de la implantación de AUTO TWIN, el ciclo deseado será:

```text
QCC
 ↓
Gestión
 ↓
Construir TWIN
 ↓
usuario navega por la sede
 ↓
QCC descubre
 ↓
QCC captura
 ↓
QCC aprende
 ↓
AUTO TWIN construye
 ↓
REAL ↔ TWIN valida
 ↓
TWIN ACTIVE
```

A partir de entonces:

```text
uso diario de la sede
 ↓
QCC observa
 ↓
¿cambio?
 ├── NO → nada
 └── SÍ
       ↓
   nueva revisión
       ↓
   regeneración
       ↓
   validación
       ↓
   promoción
```

---

# 31. Resolución

Se resuelve:

1. **AUTO TWIN será una capacidad propia de QCC.**
2. Su gestión principal estará disponible desde **QCC → Gestión → AUTO TWINS**.
3. Se establece como objetivo una **fidelidad práctica del 100 % visual, geométrica, estructural e interactiva dentro de un Rendering Profile controlado**.
4. Se creará un **perfil Chrome persistente SeleniumBase específico TWIN DISCOVERY**.
5. Dicho perfil tendrá capacidad de descubrimiento pasivo y activo gobernado.
6. Los navegadores utilizados diariamente para presentaciones REAL **también serán fuentes de vigilancia y actualización de los Twins**.
7. AUTO TWIN se apoyará desde el inicio en la arquitectura multi-browser y el Bridge compartido de QCC.
8. Las pantallas desconocidas deberán activar descubrimiento automático.
9. Los catálogos deberán extraerse automáticamente cuando resulte seguro.
10. Las dependencias entre catálogos deberán descubrirse, persistirse y versionarse.
11. Los cambios REAL deberán producir revisiones candidatas, nunca sobrescritura directa del último TWIN validado.
12. Una revisión solo pasará a `ACTIVE` tras superar validación REAL ↔ TWIN.
13. Las políticas `HUMAN_ONLY` continuarán siendo vinculantes durante descubrimiento y actualización.
14. Site Architecture será la fuente canónica del sistema.
15. Los Twins manuales existentes se conservarán como Golden References y regresión.
16. EX01 servirá como caso de referencia para validar el motor.
17. EX02 será el primer procedimiento que deberá intentarse construir automáticamente desde cero.
18. La construcción manual dejará de ser el mecanismo ordinario y quedará reservada para excepciones y overrides puntuales.

---

## Resultado arquitectónico

```text
                         QCC
                          │
            ┌─────────────┴─────────────┐
            │                           │
      MULTI-BROWSER                GESTIÓN
            │                           │
 ┌──────────┼──────────┐          AUTO TWINS
 │          │          │                │
REAL     REAL      DISCOVERY             │
01       02       SeleniumBase           │
 │          │          │                 │
 └──────────┴──────────┴─────────────────┘
                     │
                   BRIDGE
                     │
              SITE ARCHITECTURE
                     │
       ┌─────────────┼──────────────┐
       │             │              │
      DOM         GEOMETRY       CATALOGS
       │             │              │
       └─────────────┼──────────────┘
                     │
              CHANGE DETECTOR
                     │
               REVISION STORE
                     │
              TWIN MATERIALIZER
                     │
              REAL ↔ TWIN VALIDATOR
                     │
               PIXEL / GEOMETRY
                     │
                  ACTIVE
```

**AUTO TWIN queda aprobado como una de las capacidades nucleares de QCC y como mecanismo futuro ordinario para construcción, mantenimiento y vigilancia de LABS/TWINS de sedes electrónicas.**
