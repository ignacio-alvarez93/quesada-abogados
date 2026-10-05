# RESOLUCIÓN DE EVOLUCIÓN DE KNOWLEDGE NATIVO Y GOBIERNO DEL CONOCIMIENTO

**Fecha:** 05/10/2026
**Proyecto:** Quesada Abogados
**Estado:** APROBADA POR DIRECCIÓN
**Ámbito:** Knowledge, conocimiento jurídico/documental, fuentes, IA, trazabilidad y aprendizaje operativo.

---

## I. OBJETO

La presente resolución formaliza la evolución del modelo de Knowledge del proyecto Quesada Abogados desde un esquema inicial en el que NotebookLM podía actuar como capa externa de análisis hacia un **módulo Knowledge propio, nativo e integrado en el ecosistema Quesada Abogados**.

La resolución modifica parcialmente:

- `KNOW-001` · Flujo Circular Operativo del Cliente y Generación de Conocimiento.

Y mantiene íntegramente:

- `KNOW-002` · Supervisión Jurídica Humana Obligatoria sobre Criterios de IA.

---

## II. PRINCIPIO GENERAL

Knowledge pasa a ser una capacidad propia del ERP/ecosistema Quesada Abogados.

Su función será convertir de forma gobernada:

```text
FUENTES JURÍDICAS / DOCUMENTALES
+
EXPERIENCIA OPERATIVA
+
EXPEDIENTES CERRADOS ANONIMIZADOS
+
CRITERIOS HUMANOS VALIDADOS
        ↓
CONOCIMIENTO TRAZABLE
        ↓
CONSULTA / ANÁLISIS / ASISTENCIA
        ↓
SUPERVISIÓN JURÍDICA HUMANA
```

Knowledge no sustituye:

- al expediente;
- a la fuente jurídica original;
- al profesional responsable;
- al ERP como fuente estructurada de verdad;
- a los documentos originales de soporte.

---

## III. KNOW-003 · KNOWLEDGE NATIVO COMO PLATAFORMA DE CONOCIMIENTO

Se aprueba:

`KNOW-003 · Knowledge Nativo como Plataforma de Conocimiento del Ecosistema Quesada Abogados`

Knowledge será un módulo propio con capacidad progresiva para:

- ingerir y registrar fuentes;
- conservar procedencia y trazabilidad;
- indexar y consultar conocimiento;
- relacionar normativa, criterios, documentos y experiencia;
- reutilizar conocimiento derivado de expedientes anonimizados;
- asistir a usuarios mediante modelos de IA;
- distinguir entre fuente, criterio validado e inferencia;
- devolver evidencia y referencias suficientes para revisión humana.

El módulo deberá diseñarse de forma desacoplada del proveedor de IA utilizado.

---

## IV. EFECTO SOBRE KNOW-001

`KNOW-001` pasa a **MODIFICADA**.

Se mantienen plenamente:

- el flujo circular de aprendizaje;
- la conversión de experiencia operativa en conocimiento reutilizable;
- la anonimización previa de expedientes/documentos cuando proceda;
- la extracción de hechos y criterios;
- la validación humana;
- la retroalimentación hacia futuros expedientes y operaciones.

Queda sustituida como arquitectura operativa la dependencia de NotebookLM como destino ordinario del conocimiento.

NotebookLM podrá seguir utilizándose excepcionalmente como herramienta externa de análisis o apoyo documental, pero:

- no será requisito de funcionamiento;
- no será repositorio canónico;
- no será fuente de verdad;
- no gobernará el modelo de datos de Knowledge;
- no será dependencia necesaria del runtime del ERP.

---

## V. FUENTES Y AUTORIDAD

Knowledge deberá distinguir al menos entre:

1. **Fuente primaria / oficial**
   - normativa;
   - resoluciones;
   - jurisprudencia;
   - documentos administrativos;
   - publicaciones oficiales;
   - documentación original del expediente.

2. **Fuente secundaria / especializada**
   - doctrina;
   - publicaciones jurídicas;
   - cuadernos o artículos especializados;
   - materiales de formación;
   - otras fuentes aprobadas por Dirección.

3. **Criterio interno**
   - interpretación o criterio elaborado por el despacho;
   - validado por profesional responsable;
   - vinculado a sus fuentes de soporte.

4. **Conocimiento derivado de expediente**
   - hechos anonimizados;
   - incidencias;
   - estrategia utilizada;
   - resultado;
   - observaciones operativas;
   - lecciones reutilizables.

5. **Inferencia de IA**
   - salida generada por un modelo;
   - nunca fuente primaria;
   - nunca autoridad jurídica por sí misma.

La fuente original prevalece sobre cualquier resumen, embedding, índice, chunk, criterio derivado o respuesta generada.

---

## VI. TRAZABILIDAD Y PROVENANCE

Todo conocimiento incorporado deberá conservar, cuando proceda:

- identificador;
- tipo de fuente;
- origen;
- fecha;
- versión;
- ámbito;
- URL o referencia documental;
- hash o identificador del documento cuando sea útil;
- fecha de incorporación;
- estado de vigencia;
- relaciones con otras fuentes;
- fragmentos o referencias utilizadas;
- criterios internos derivados;
- validaciones humanas;
- historial de actualización.

Knowledge deberá poder responder no solo:

> ¿Cuál es la respuesta?

sino también:

> ¿En qué fuentes se apoya?

y, cuando proceda:

> ¿Qué parte es fuente y qué parte es inferencia?

---

## VII. KNOWLEDGE DOCUMENTAL

Knowledge podrá incorporar una capa documental propia.

Esta capa no sustituye al sistema documental operativo del ERP ni modifica `DOC-001`.

Su finalidad será permitir que documentos relevantes puedan:

- catalogarse;
- indexarse;
- relacionarse con materias;
- enlazarse con normativa;
- vincularse con criterios;
- recuperarse por contenido;
- participar en consultas asistidas;
- mantener procedencia y trazabilidad.

La existencia de Knowledge Documental no autoriza a manipular Box.

Cuando un documento proceda de Box, deberán respetarse las reglas documentales vigentes y la arquitectura de observación aprobada.

---

## VIII. CONOCIMIENTO PROCEDENTE DE CLIENTES Y EXPEDIENTES

El aprendizaje procedente de casos reales deberá aplicar privacidad por diseño.

Antes de incorporar contenido de un expediente a un corpus reutilizable o de utilizarlo con proveedores externos de IA, deberá:

- eliminar o minimizar datos identificativos cuando no sean necesarios;
- separar hechos jurídicamente relevantes de identidad personal;
- conservar la relación interna con el expediente únicamente cuando la arquitectura y permisos lo permitan;
- evitar que datos reales de clientes se conviertan en fixtures, ejemplos públicos o conocimiento compartido innecesariamente.

El objetivo es conservar el aprendizaje jurídico y operativo sin convertir Knowledge en una copia indiscriminada de información personal.

---

## IX. IA Y PROVEEDORES DE INFERENCIA

Los modelos de IA se consideran **proveedores de inferencia**, no repositorios canónicos de conocimiento.

Knowledge deberá abstraer, cuando sea razonable, el proveedor utilizado.

Podrán utilizarse OpenAI, otros modelos externos o futuros proveedores, siempre sujetos a:

- permisos;
- privacidad;
- coste;
- disponibilidad;
- calidad;
- trazabilidad;
- políticas del proyecto.

Cambiar de proveedor no deberá obligar a rediseñar el corpus ni perder conocimiento canónico.

El conocimiento pertenece al sistema; el proveedor realiza inferencia sobre el contexto autorizado.

---

## X. RESPUESTAS CON Y SIN FUENTES

Knowledge deberá diferenciar claramente:

### A. RESPUESTA FUNDAMENTADA
Existe evidencia suficiente en fuentes disponibles.

La respuesta deberá, cuando sea técnicamente viable:

- identificar las fuentes relevantes;
- conservar trazabilidad;
- diferenciar cita/evidencia de explicación generada.

### B. EVIDENCIA INSUFICIENTE
Las fuentes disponibles no permiten responder con suficiente fundamento.

El sistema no deberá inventar fuentes ni simular respaldo documental.

Podrá:

- indicar insuficiencia;
- solicitar otra fuente;
- proponer búsqueda/ingesta;
- o, si la política funcional lo permite, generar una **respuesta asistida no respaldada por el corpus**, claramente identificada como inferencia general del modelo.

Una respuesta asistida sin fuente nunca podrá presentarse como criterio jurídico validado.

---

## XI. SUPERVISIÓN JURÍDICA HUMANA

`KNOW-002` permanece **VIGENTE sin modificación**.

Todo criterio jurídico generado, sintetizado o sugerido mediante IA debe ser revisado y validado por profesional responsable antes de:

- incorporarse como criterio interno validado;
- utilizarse para una estrategia jurídica;
- generar un escrito definitivo;
- presentarse ante una Administración;
- comunicarse como conclusión jurídica definitiva al cliente cuando requiera juicio profesional.

La IA asiste.

La fuente soporta.

El profesional valida.

---

## XII. UNA FUENTE DE VERDAD POR CONCEPTO

Knowledge deberá respetar `DATA-009`.

No se crearán repositorios paralelos competidores para el mismo concepto.

Ejemplos:

- el expediente sigue perteneciendo al dominio Expedientes;
- el cliente sigue perteneciendo al dominio Clientes;
- el documento operativo sigue perteneciendo al sistema documental;
- Knowledge conserva referencias, índices, relaciones y conocimiento derivado, no copias autoritativas competidoras.

---

## XIII. ACTUALIZACIÓN Y VIGENCIA

Knowledge deberá poder representar que una fuente o criterio:

- está vigente;
- ha sido modificado;
- ha sido sustituido;
- ha sido derogado;
- está pendiente de revisión;
- tiene conflicto o incertidumbre.

La actualización de una fuente no debe destruir necesariamente su historia.

Cuando sea útil jurídicamente, deberá conservarse la trazabilidad temporal.

---

## XIV. ARQUITECTURA ABIERTA Y EVOLUCIÓN FUTURA

La presente resolución **no fija todavía**:

- motor vectorial concreto;
- proveedor de embeddings;
- base vectorial concreta;
- estrategia definitiva de chunking;
- tecnología RAG concreta;
- modelo LLM único;
- proveedor jurídico comercial obligatorio;
- UI definitiva del módulo.

Estas decisiones deberán tomarse cuando exista evidencia técnica suficiente y necesidad real.

El principio será:

```text
NECESIDAD REAL
→ CONTRATO
→ IMPLEMENTACIÓN
→ TESTS
→ EVIDENCIA
```

y no:

```text
TECNOLOGÍA DISPONIBLE
→ introducirla sin necesidad
```

---

## XV. DECISIONES CANÓNICAS RESULTANTES

Tras la aprobación de esta resolución:

- `KNOW-001` → **MODIFICADA**
- `KNOW-002` → **VIGENTE**
- `KNOW-003` → **VIGENTE**

No se modifican por esta resolución:

- `DOC-001`
- `DOC-002`
- `OPS-001`
- `OPS-002`
- `OPS-003`
- `DATA-009`

---

## XVI. PRINCIPIO FINAL

Knowledge deberá evolucionar hacia:

```text
FUENTE
→ TRAZABILIDAD
→ ESTRUCTURACIÓN
→ RECUPERACIÓN
→ INFERENCIA
→ EVIDENCIA
→ SUPERVISIÓN HUMANA
→ CONOCIMIENTO VALIDADO
```

El objetivo no es que la IA "sepa más".

El objetivo es que el despacho pueda **recuperar, verificar, reutilizar y mejorar su conocimiento con fuentes, trazabilidad y control profesional**.

---

**ESTADO FINAL:** APROBADA POR DIRECCIÓN
