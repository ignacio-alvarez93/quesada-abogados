# RESOLUCIÓN SOBRE EL SISTEMA HÍBRIDO DE DESARROLLO POR TUBERÍAS, WORKTREES PARALELOS Y CIERRE DE MÓDULOS MEDIANTE CLAUDE

**Proyecto:** Quesada Abogados ERP / QCC / AUTO TWIN
**Fecha:** 14 de septiembre de 2026
**Estado:** APROBADA
**Naturaleza:** Resolución metodológica y de gobierno vinculante
**Ámbito:** Todo el desarrollo presente y futuro del proyecto

---

# I. OBJETO

Se aprueba un nuevo sistema híbrido de desarrollo destinado a aumentar simultáneamente:

* velocidad de ejecución;
* paralelización;
* robustez;
* aislamiento entre desarrollos;
* aprovechamiento del tiempo de Claude;
* continuidad del avance técnico.

El sistema combinará:

```text
CLAUDE
→ ejecución profunda
→ auditoría
→ robustecimiento
→ tests
→ cierre de módulos
```

con:

```text
CHATGPT + DIRECCIÓN DEL PROYECTO
→ diseño
→ arquitectura
→ decisiones
→ especificación

+

GIT BASH / MÉTODO INCREMENTAL
→ apertura de nuevos frentes
→ diagnóstico
→ construcción inicial
→ commits controlados
```

mediante distintos `git worktree`.

---

# II. PRINCIPIO FUNDAMENTAL

Se establece el siguiente modelo:

```text
CLAUDE CIERRA EL MÓDULO N
          │
          │ en paralelo
          ▼
NOSOTROS ABRIMOS EL MÓDULO N+1
EN OTRO WORKTREE
          │
          ▼
CLAUDE TERMINA N
          │
          ▼
CLAUDE RECIBE N+1
          │
          ▼
AUDITA + ROBUSTECE + COMPLETA + CIERRA N+1
          │
          │ mientras tanto
          ▼
NOSOTROS ABRIMOS N+2
```

El desarrollo pasa así a funcionar como una:

# TUBERÍA CONTINUA DE MÓDULOS

---

# III. LOS DOS CARRILES DE DESARROLLO

## CARRIL A — CLAUDE

Claude trabajará sobre el módulo que se encuentre en fase de consolidación.

Será responsable de:

* inspeccionar el código real;
* completar implementaciones;
* corregir defectos;
* revisar arquitectura;
* localizar deuda técnica;
* ejecutar tests;
* añadir regresiones;
* auditar contratos;
* revisar integración;
* robustecer errores;
* eliminar provisionalidades cuando proceda;
* comprobar diffs;
* preparar el módulo para su cierre.

Claude será el:

```text
CERRADOR TÉCNICO DE MÓDULOS
```

---

## CARRIL B — INCUBACIÓN PARALELA

Mientras Claude trabaja, se podrá crear otro `worktree` sobre una rama independiente para iniciar un módulo distinto.

En este carril se utilizará la metodología histórica del proyecto:

```text
Git Bash
grep
sed
diagnóstico
scripts
parches quirúrgicos
py_compile
pytest
git diff
commits pequeños
```

Este carril tendrá como finalidad:

```text
abrir terreno nuevo
```

y no competir con Claude sobre terreno ya consolidado.

---

# IV. PRINCIPIO DE DESACOPLAMIENTO

Los dos carriles solo podrán trabajar simultáneamente cuando sus desarrollos estén suficientemente desacoplados.

Ejemplo válido:

```text
CLAUDE
→ AUTO TWIN

WORKTREE PARALELO
→ KNOWLEDGE
```

Ejemplo inválido:

```text
CLAUDE
→ AUTO TWIN navigation

WORKTREE PARALELO
→ modificar el mismo resolver de navegación
```

No deberán modificarse simultáneamente:

* los mismos archivos;
* los mismos servicios;
* los mismos contratos;
* el mismo schema;
* las mismas migraciones;
* infraestructura transversal compartida;
* una misma fuente canónica de verdad.

---

# V. CONCEPTO DE MÓDULO VERDE

El carril paralelo deberá priorizar:

```text
MÓDULOS VERDES
```

Se considerará módulo verde aquel que:

* sea nuevo;
* tenga límites de dominio claros;
* tenga poca dependencia del módulo activo de Claude;
* pueda construirse mediante interfaces existentes;
* no necesite modificar contratos todavía inestables;
* no requiera código no integrado de la rama de Claude.

Ejemplos potenciales:

```text
Knowledge
Immigration Trends
Reporting especializado
nuevas integraciones aisladas
nuevos consumidores de APIs
nuevos servicios desacoplados
```

siempre que su situación concreta cumpla el requisito de aislamiento.

---

# VI. WORKTREE COMO FRONTERA FÍSICA

Cada carril deberá disponer de:

```text
rama propia
+
worktree propio
+
working tree propio
```

Ejemplo conceptual:

```text
quesada-abogados/
→ feature/qcc-auto-twin
→ CLAUDE

quesada-abogados-knowledge/
→ feature/knowledge-v1
→ DESARROLLO PARALELO
```

No se utilizará el mismo working tree para los dos trabajos.

---

# VII. BASE DEL WORKTREE PARALELO

El nuevo frente paralelo deberá partir de una base común ya consolidada.

Preferentemente:

```text
develop
```

o del commit de integración expresamente aprobado.

El módulo paralelo no deberá depender de cambios que:

```text
solo existan todavía
en la rama activa de Claude
```

Si existe esa dependencia:

```text
NO ESTÁ SUFICIENTEMENTE DESACOPLADO
```

y deberá posponerse o redefinirse.

---

# VIII. PROPIEDAD TEMPORAL DEL MÓDULO

Cada módulo tendrá un propietario operativo inequívoco.

Estados posibles:

```text
GREEN / INCUBATION
CLAUDE ACTIVE
CLAUDE CLOSED
```

## GREEN / INCUBATION

Puede ser desarrollado mediante:

```text
ChatGPT
+
Git Bash
+
parches incrementales
```

## CLAUDE ACTIVE

Desde el momento de entrega a Claude:

```text
se congela el carril manual
```

sobre ese módulo.

No habrá dos ejecutores modificándolo simultáneamente.

## CLAUDE CLOSED

El módulo se considera consolidado.

A partir de ese momento se aplica la regla de cierre permanente.

---

# IX. REGLA FUNDAMENTAL DE CIERRE

Se establece como norma vinculante:

> **Todo módulo deberá ser cerrado técnicamente por Claude.**

El trabajo realizado mediante Git Bash podrá:

* iniciar;
* diseñar;
* construir;
* experimentar;
* implementar una V0/V1;
* crear servicios;
* crear tests iniciales;
* avanzar funcionalmente.

Pero no otorgará por sí solo la consideración de:

```text
MÓDULO CERRADO
```

El cierre requerirá intervención de Claude.

---

# X. REGLA DE NO REAPERTURA MANUAL

Una vez un módulo haya sido:

```text
auditado
+
robustecido
+
validado
+
cerrado
```

por Claude:

# QUEDA PROHIBIDO REABRIRLO MEDIANTE EL CARRIL MANUAL.

Por tanto:

```text
MÓDULO CERRADO POR CLAUDE
        ↓
futura modificación
        ↓
CLAUDE
```

No volveremos posteriormente al modelo:

```text
ChatGPT
→ comandos Git Bash
→ parche directo
```

sobre dicho módulo.

---

# XI. SENTIDO DE LA REGLA DE NO REAPERTURA

La finalidad es evitar el ciclo:

```text
Claude consolida
      ↓
modificaciones manuales posteriores
      ↓
nueva deuda
      ↓
Claude tiene que volver a reconstruir contexto
      ↓
nuevo cierre
```

El sistema correcto será:

```text
INCUBACIÓN MANUAL
       ↓
CLAUDE
       ↓
CIERRE
       ↓
EVOLUCIÓN FUTURA CON CLAUDE
```

De este modo cada módulo atraviesa una frontera de madurez.

---

# XII. CHATGPT CONSERVA LA DIRECCIÓN TÉCNICA

El cierre por Claude no convierte a Claude en autoridad arquitectónica.

La estructura continuará siendo:

```text
DIRECCIÓN DEL PROYECTO
        ↓
CHATGPT
dirección técnica
arquitectura
contratos
Work Orders
criterios de aceptación
        ↓
CLAUDE
ejecución
        ↓
evidencia
        ↓
CHATGPT
revisión / siguiente decisión
```

Por tanto:

```text
CLAUDE CIERRA EL CÓDIGO

CHATGPT DIRIGE SU EVOLUCIÓN
```

---

# XIII. ENTREGA DEL MÓDULO A CLAUDE

Cuando Claude quede libre y vaya a asumir el módulo iniciado en paralelo, se realizará un:

```text
HANDOFF
```

El handoff deberá proporcionar, cuando proceda:

* objetivo del módulo;
* arquitectura aprobada;
* rama;
* worktree;
* commits realizados;
* estado funcional;
* tests existentes;
* decisiones adoptadas;
* contratos;
* invariantes;
* deuda conocida;
* provisionalidades;
* TODO pendientes;
* puntos que Claude debe auditar;
* criterio de cierre.

Claude no deberá reconstruir innecesariamente desde cero lo que ya se haya desarrollado.

---

# XIV. FUNCIÓN DE CLAUDE DESPUÉS DEL HANDOFF

Claude deberá asumir el código existente como punto de partida.

Su misión no será necesariamente reescribirlo.

La secuencia será:

```text
INSPECCIONAR
↓
ENTENDER
↓
AUDITAR
↓
EJECUTAR TESTS
↓
IDENTIFICAR DEUDA
↓
CORREGIR
↓
COMPLETAR
↓
ROBUSTECER
↓
REGRESIÓN
↓
CIERRE
```

Se mantiene el principio:

```text
EVOLUCIÓN INCREMENTAL
>
REESCRITURA
```

---

# XV. CRITERIO DE CIERRE DE UN MÓDULO

Claude podrá considerar un módulo técnicamente preparado para cierre cuando exista evidencia suficiente de:

1. arquitectura coherente;
2. separación de responsabilidades;
3. ausencia de deuda crítica conocida;
4. contratos definidos;
5. tests relevantes verdes;
6. regresiones protegidas;
7. compilación correcta;
8. integración controlada;
9. ausencia de archivos accidentales;
10. `git diff` revisado;
11. documentación relevante actualizada;
12. comportamiento funcional verificado.

El nivel concreto dependerá de la criticidad del módulo.

---

# XVI. MERGE NO EQUIVALE AUTOMÁTICAMENTE A CIERRE

Que una rama haya sido integrada no significa necesariamente que el módulo esté cerrado.

Se distinguirá:

```text
MERGED
```

de:

```text
CLAUDE CLOSED
```

Un módulo podrá integrarse provisionalmente por razones técnicas y continuar abierto.

La condición que activa la prohibición de reapertura manual será:

```text
CLAUDE CLOSED
```

---

# XVII. ARCHIVOS TRANSVERSALES

Se prestará especial atención a archivos compartidos como:

* configuración global;
* infraestructura de persistencia;
* modelos transversales;
* contratos QCC;
* Browser Runtime;
* Bridge;
* utilidades comunes;
* schemas;
* migraciones;
* componentes compartidos.

El carril de incubación no deberá modificar infraestructura transversal utilizada simultáneamente por Claude salvo decisión específica.

Si aparece una necesidad transversal:

```text
SE DETIENE ESA PARTE
```

y se eleva a dirección técnica.

---

# XVIII. MIGRACIONES Y BASE DE DATOS

Dos worktrees no deberán crear migraciones incompatibles de forma independiente.

Cuando ambos frentes necesiten modificar schema:

* deberá existir coordinación explícita;
* se reservarán rangos o secuencias;
* se evitarán nombres/versiones incompatibles;
* se comprobará el orden de aplicación;
* Claude deberá revisar la integración final.

En caso de duda, el módulo paralelo deberá evitar tocar schema compartido hasta la consolidación del otro frente.

---

# XIX. COMMITS DEL CARRIL PARALELO

Durante incubación se permitirán commits funcionales y pequeños.

Ejemplo:

```text
feat(knowledge): add BOE source registry
feat(knowledge): add ingestion service
test(knowledge): cover source normalization
```

Se evitarán commits gigantes del tipo:

```text
implement Knowledge
```

El historial deberá facilitar posteriormente a Claude entender la construcción del módulo.

---

# XX. NO SE EXIGE QUE CLAUDE RETOME INMEDIATAMENTE EL ÚLTIMO MÓDULO ABIERTO

La tubería no será rígida.

Cuando Claude cierre un módulo podrá asumir:

* el módulo que está desarrollándose en paralelo;
* otro módulo cerrado que requiera ampliación;
* una prioridad superior;
* un frente crítico;
* una auditoría.

La decisión pertenecerá a Dirección Técnica.

Por tanto:

```text
CLAUDE TERMINA A
```

no implica necesariamente:

```text
CLAUDE DEBE TOMAR B
```

si existe una prioridad superior.

---

# XXI. EL CARRIL MANUAL SIEMPRE AVANZA HACIA TERRENO NUEVO

La regla estratégica será:

```text
CLAUDE
→ profundidad

CARRIL PARALELO
→ frontera
```

Claude profundiza, endurece y cierra.

Nosotros abrimos nuevas superficies funcionales.

Esto evita duplicar esfuerzos.

---

# XXII. PIPELINE OBJETIVO

El funcionamiento ideal será:

```text
TIEMPO ──────────────────────────────────────────────►

CLAUDE:
[AUTO TWIN ███████████] [KNOWLEDGE █████████] [IT ███████]

PARALELO:
            [KNOWLEDGE ▒▒▒▒▒▒]
                                  [IT ▒▒▒▒▒▒]
                                                   [NUEVO ▒▒▒]
```

Donde:

```text
▒ = incubación
█ = consolidación/cierre Claude
```

El resultado esperado es mantener continuamente:

```text
1 módulo en profundidad
+
1 nuevo frente en preparación
```

---

# XXIII. EJEMPLO INMEDIATO

Aplicado al estado actual:

```text
CLAUDE
→ AUTO TWIN
```

simultáneamente:

```text
WORKTREE PARALELO
→ KNOWLEDGE
```

Cuando AUTO TWIN alcance su punto de cierre:

```text
Claude
→ puede asumir KNOWLEDGE
→ auditar
→ completar
→ robustecer
→ cerrar
```

Mientras:

```text
nuevo worktree paralelo
→ IMMIGRATION TRENDS
```

Posteriormente:

```text
Claude
→ Immigration Trends
```

mientras el carril paralelo abre otro dominio.

---

# XXIV. OBJETIVO DE PRODUCTIVIDAD

El sistema pretende eliminar tiempo técnico ocioso.

Mientras Claude realiza trabajo profundo durante una determinada ventana temporal, la Dirección Técnica puede utilizar esa misma ventana para:

* diseñar;
* investigar;
* establecer contratos;
* crear estructuras;
* construir primeras versiones;
* iniciar el siguiente módulo.

Por tanto:

```text
TIEMPO DE CLAUDE
+
TIEMPO DE DIRECCIÓN / GIT BASH
```

dejan de ser secuenciales y pasan a ejecutarse parcialmente en paralelo.

---

# XXV. OBJETIVO DE ROBUSTEZ

La mayor velocidad no deberá producir menor calidad.

Precisamente la separación permitirá:

```text
INCUBACIÓN
→ rápida y exploratoria

CLAUDE
→ consolidación y blindaje
```

Cada módulo tendrá dos etapas distintas:

```text
1. DESCUBRIMIENTO / CONSTRUCCIÓN

2. INDUSTRIALIZACIÓN / CIERRE
```

---

# XXVI. PROHIBICIÓN DE DOS CIERRES PARALELOS SOBRE EL MISMO DOMINIO

No existirán:

```text
Claude modificando módulo X
+
Git Bash modificando módulo X
```

simultáneamente.

El trabajo paralelo será:

```text
Claude → X
Git Bash → Y
```

con:

```text
X ∩ Y ≈ 0
```

en cuanto a superficie de código modificada.

---

# XXVII. RESOLUCIÓN DE CONFLICTOS ENTRE CARRILES

Si durante la incubación descubrimos que el módulo paralelo necesita modificar una pieza actualmente bajo Claude:

```text
NO SE MODIFICA ESA PIEZA
```

Se podrá:

* crear una interfaz provisional;
* aislar el consumidor;
* documentar la dependencia;
* dejar TODO controlado;
* esperar al cierre;
* entregar posteriormente la necesidad a Claude.

Nunca se resolverá editando simultáneamente el mismo núcleo.

---

# XXVIII. CLASIFICACIÓN OPERATIVA DE LOS MÓDULOS

A efectos de gobierno se utilizará conceptualmente:

### GREEN

```text
Nuevo / desacoplado
Disponible para incubación manual
```

### AMBER

```text
En handoff o bajo Claude
No tocar desde carril manual
```

### RED / CLOSED

```text
Cerrado por Claude
Solo Claude puede ejecutar cambios posteriores
```

El color representa la política de modificación, no la calidad del módulo.

---

# XXIX. EFECTO SOBRE LA METODOLOGÍA ANTERIOR

El método basado en Git Bash, `grep`, `sed`, scripts y parches:

```text
NO SE ELIMINA
```

pero cambia de función.

Antes era:

```text
método general de ejecución del proyecto
```

Ahora será principalmente:

```text
método de incubación de nuevos frentes
```

y herramienta de:

* diagnóstico;
* inspección;
* pruebas;
* apoyo a dirección técnica.

No será el método ordinario para modificar módulos cerrados.

---

# XXX. EFECTO SOBRE LA RESOLUCIÓN DE CLAUDE

La resolución de 12 de septiembre continúa vigente.

La presente resolución la amplía definiendo un segundo carril de trabajo.

Se mantiene:

```text
CHATGPT
= dirección técnica

CLAUDE
= ejecutor técnico principal
```

y se añade:

```text
GIT BASH / WORKTREE PARALELO
= incubador de nuevos módulos
```

---

# XXXI. PRINCIPIO RECTOR DEFINITIVO

El nuevo sistema de desarrollo de Quesada Abogados queda definido como:

> **Desarrollo híbrido por tuberías, con Claude como ejecutor de consolidación y cierre, y un worktree paralelo de incubación destinado a abrir de forma controlada el siguiente frente desacoplado.**

Su regla central será:

```text
NOSOTROS ABRIMOS.

CLAUDE PROFUNDIZA.

CLAUDE CIERRA.

LO CERRADO SOLO VUELVE A CLAUDE.

MIENTRAS CLAUDE CIERRA,
NOSOTROS YA ESTAMOS ABRIENDO LO SIGUIENTE.
```

---

# XXXII. ENTRADA EN VIGOR

La metodología entra en vigor inmediatamente.

A partir de este momento, todo nuevo desarrollo deberá clasificarse antes de comenzar como:

```text
CLAUDE ACTIVE

o

GREEN / PARALLEL INCUBATION
```

y deberá respetarse la propiedad del módulo hasta su siguiente transición.

---

# CIERRE

Queda aprobado el **Sistema Híbrido de Desarrollo por Tuberías y Worktrees Paralelos** como metodología oficial de ejecución del proyecto Quesada Abogados.

El objetivo no será únicamente desarrollar más rápido.

Será conseguir que:

```text
cada minuto de ejecución de Claude
coexista con avance real en el siguiente frente,

sin colisiones,
sin reabrir deuda consolidada,
sin sacrificar arquitectura,
y convirtiendo progresivamente
cada módulo terminado
en una pieza estable del sistema.
```
