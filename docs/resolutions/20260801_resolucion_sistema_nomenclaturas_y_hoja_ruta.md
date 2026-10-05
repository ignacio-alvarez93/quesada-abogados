# RESOLUCIÓN INTERNA SOBRE EL SISTEMA DE NOMENCLATURAS DOCUMENTALES Y LA HOJA DE RUTA PARA SU DESARROLLO

## I. Objeto de la resolución

La presente resolución tiene por objeto:

1. Determinar el estado actual del sistema de nomenclaturas documentales del CRM de Quesada Abogados.
2. Fijar los principios que deberán regir su evolución.
3. Proteger los desarrollos ya existentes en materia de expedientes, formularios, snapshots, presentación asistida, trazabilidad y Box.
4. Establecer la hoja de ruta para el desarrollo de familias documentales, nuevos tipos de expediente y su futura conexión con los módulos de Notificaciones, Calendario y Centro de Actividades Administrativas.
5. Regular el proceso de activación progresiva del motor documental semántico.

---

# II. Antecedentes

## Primero. Sistema documental anterior

El sistema anterior de nomenclaturas permitía principalmente:

* identificar documentos mediante su nombre;
* asociar archivos a nomenclaturas conocidas;
* clasificar documentos encontrados en Box;
* vincular documentos con expedientes;
* mostrar documentación existente o pendiente;
* alimentar parcialmente los flujos documentales del CRM.

Su funcionamiento se apoyaba principalmente en:

* nombres de archivos;
* palabras clave;
* rutas de Box;
* nomenclaturas previamente configuradas;
* asociaciones directas entre tipos de expediente y documentos.

Este sistema resultaba adecuado para inventariar y localizar documentación, pero presentaba limitaciones para determinar:

* a qué persona correspondía un documento;
* qué función cumplía dentro del expediente;
* qué requisito concreto satisfacía;
* si existían documentos alternativos válidos;
* si un expediente estaba documentalmente completo;
* si un cambio detectado debía generar un evento o notificación.

## Segundo. Desarrollo del sistema actual

El sistema actual ha incorporado una arquitectura documental semántica compuesta, entre otros elementos, por:

* catálogo de nomenclaturas canónicas;
* normalización de variantes documentales;
* grupos de requisitos documentales;
* opciones documentales;
* reglas de cumplimiento AND y OR;
* cardinalidad;
* documentos obligatorios y opcionales;
* equivalencias documentales;
* roles documentales;
* inferencia controlada de roles;
* diagnóstico de cumplimiento;
* readiness documental;
* separación entre estado documental y estado procesal;
* comparación entre motor legacy y motor semántico;
* snapshots documentales;
* fingerprints de diagnóstico;
* eventos semánticos idempotentes;
* integración controlada con Box Watch;
* feature flags para activación progresiva.

## Tercero. Integración en la rama principal

La infraestructura correspondiente a familias documentales, requisitos agrupados, nomenclaturas canónicas, estados semánticos y eventos documentales ha sido integrada en la rama `develop`.

La integración se ha realizado conservando desactivados por defecto:

```text
DOCUMENT_STATE_ENGINE_MODE
DOCUMENT_SEMANTIC_SCAN_EVENTS_ENABLED
```

Por tanto, el CRM mantiene actualmente el funcionamiento operativo anterior, sin que el nuevo motor semántico haya sustituido todavía al sistema legacy.

## Cuarto. Desarrollos que deben protegerse

Existen desarrollos funcionales previos que forman parte del núcleo operativo del CRM y que no deben verse alterados por la evolución del sistema documental, entre ellos:

* Reagrupación Familiar;
* Residencia No Lucrativa;
* otros tipos y subtipos existentes;
* EX01;
* EX02;
* EX32;
* mapeo de formularios;
* snapshots de formularios;
* relaciones familiares;
* datos específicos de expedientes;
* presentación asistida;
* automatización Mercurio;
* trazabilidad;
* Box Watch;
* bandeja documental;
* cola de presentación y futuro Centro de Actividades Administrativas.

---

# III. Valoración del sistema actual

## Primero. Cambio de naturaleza del sistema

Se considera que el sistema ha evolucionado desde un modelo de clasificación documental hacia un modelo de interpretación documental.

El sistema anterior podía determinar:

```text
“Existe un archivo que parece ser un pasaporte.”
```

El sistema actual está preparado para determinar:

```text
“Existe un pasaporte correspondiente al cónyuge,
que satisface la opción documental exigida
en el grupo de identidad del familiar.”
```

La diferencia no es únicamente terminológica. Supone pasar de una clasificación de archivos a una evaluación del cumplimiento documental del expediente.

## Segundo. Catálogo canónico

El catálogo canónico permite unificar múltiples formas de denominar el mismo documento.

Por ejemplo, expresiones como:

```text
PASAPORTE
COPIA DE PASAPORTE
PASAPORTE COMPLETO
DOCUMENTO DE VIAJE
```

pueden resolverse hacia una nomenclatura documental común.

La nomenclatura canónica se convierte así en la identidad estable del documento, mientras que los nombres reales de archivo actúan como variantes o evidencias de detección.

## Tercero. Separación entre documento y rol

Se considera esencial la separación entre:

```text
tipo de documento
```

y:

```text
rol de la persona a la que corresponde
```

Un pasaporte del titular no cumple necesariamente el mismo requisito que un pasaporte del cónyuge, hijo, ascendiente o representante.

El sistema actual permite modelar combinaciones como:

```text
PASAPORTE + TITULAR
PASAPORTE + CÓNYUGE
PASAPORTE + HIJO
PASAPORTE + REPRESENTANTE
```

## Cuarto. Grupos documentales

La principal mejora estructural consiste en la creación de grupos documentales.

Los requisitos dejan de representarse como una lista plana y pasan a organizarse mediante reglas.

Ejemplo:

```text
GRUPO: ACREDITACIÓN DEL VÍNCULO FAMILIAR

Se cumple con:

- certificado de matrimonio, si existe relación conyugal;
- certificado de nacimiento, si existe relación de filiación;
- documentación equivalente admitida;
- combinación de documentos cuando la regla lo exija.
```

Esto permite expresar correctamente:

* alternativas;
* acumulación de requisitos;
* obligatoriedad;
* condicionalidad;
* roles;
* documentos equivalentes;
* documentación complementaria.

## Quinto. Familias, tipos y subtipos

La arquitectura actual permite organizar los procedimientos mediante la jerarquía:

```text
familia
→ tipo
→ subtipo
→ relación o rol
→ grupos documentales
→ opciones documentales
```

Esta estructura resuelve errores conceptuales anteriores, como confundir una relación familiar con un subtipo procedimental.

En particular, se considera correcta la normalización de Reagrupación Familiar conforme al siguiente esquema:

```text
Familia: RESIDENCIA
Tipo: REAGRUPACIÓN FAMILIAR
Subtipo: INICIAL o RENOVACIÓN
Relación: CÓNYUGE, HIJO, ASCENDIENTE u otra
```

## Sexto. Estado documental y estado procesal

Se considera correcto mantener separados:

```text
estado documental
```

y:

```text
estado procesal
```

Un expediente puede estar:

```text
documentalmente completo
```

y, al mismo tiempo:

```text
pendiente de presentación
```

o puede encontrarse:

```text
presentado
```

pero:

```text
documentalmente incompleto por un requerimiento posterior
```

La separación entre ambas dimensiones será esencial para Notificaciones, Calendario, Trazabilidad y Centro de Actividades Administrativas.

## Séptimo. Snapshots y eventos

El sistema actual permite conservar una fotografía del diagnóstico documental de cada expediente.

Mediante fingerprints puede determinarse si el diagnóstico ha cambiado realmente.

Por tanto:

* un nuevo escaneo sin cambios no genera un nuevo evento;
* un cambio real de estado sí puede generar un evento;
* los eventos son idempotentes;
* puede conocerse el escaneo y job de Box que originó el cambio;
* los errores de un expediente pueden aislarse mediante transacciones parciales.

## Octavo. Valoración final

Se valora el sistema actual como técnicamente preparado para iniciar un piloto controlado.

No obstante, se considera que todavía no procede su activación general, puesto que el catálogo de familias, tipos, subtipos, roles y grupos documentales debe completarse y validarse antes de que el motor semántico pueda adquirir autoridad operativa.

---

# IV. Principios rectores del desarrollo

## Primero. Principio de conservación

Todo desarrollo futuro deberá respetar y conservar el comportamiento de los módulos existentes.

Las nuevas familias documentales no sustituirán directamente:

* tipos de expediente actuales;
* subtipos actuales;
* mapeos de formularios;
* snapshots;
* presentación asistida;
* datos de Mercurio;
* relaciones familiares;
* automatizaciones existentes.

## Segundo. Principio de extensión compatible

El nuevo sistema se añadirá como una capa complementaria.

La relación será:

```text
expediente existente
→ familia documental
→ configuración semántica
```

y no:

```text
familia documental
→ sustitución del expediente existente
```

## Tercero. Principio de identificadores estables

No deberán modificarse, eliminarse ni reutilizarse los IDs, códigos o significados de tipos y subtipos que ya sean utilizados por:

* formularios;
* mappers;
* snapshots;
* presentación asistida;
* datos existentes;
* automatizaciones;
* pruebas.

Las familias documentales deberán enlazarse con los registros existentes mediante relaciones aditivas.

## Cuarto. Principio de separación de responsabilidades

Se mantendrán separadas las siguientes capas:

### Capa de expediente

Responsable de:

* tipo;
* subtipo;
* datos específicos;
* personas relacionadas;
* estado procesal.

### Capa de formularios

Responsable de:

* formulario aplicable;
* mapeo de campos;
* snapshot;
* generación y presentación asistida.

### Capa documental

Responsable de:

* grupos documentales;
* nomenclaturas;
* roles;
* documentos faltantes;
* readiness;
* estado documental.

### Capa de eventos

Responsable de:

* registrar cambios relevantes;
* evitar duplicados;
* conservar trazabilidad.

### Capa de notificaciones

Responsable de:

* decidir qué eventos requieren aviso;
* mostrar la notificación;
* derivar actuaciones a Calendario o CAA.

## Quinto. Principio de lectura durante el piloto

Durante la primera fase de activación, el motor documental será de lectura respecto al expediente.

Podrá leer:

* tipo y subtipo;
* relaciones familiares;
* datos de clientes;
* inventario documental;
* rutas;
* nomenclaturas;
* documentos detectados.

Solo podrá escribir en:

* diagnósticos semánticos;
* snapshots semánticos;
* eventos semánticos.

No podrá modificar:

* expedientes;
* clientes;
* formularios;
* snapshots de formularios;
* presentación asistida;
* relaciones familiares;
* cola de presentación.

## Sexto. Principio de migraciones aditivas

Las modificaciones de base de datos deberán ser preferentemente:

```text
CREATE TABLE
ADD COLUMN nullable
CREATE INDEX
INSERT de configuración
```

Deberán evitarse, salvo migración expresa y auditada:

```text
DROP TABLE
eliminación de columnas
reutilización de IDs
cambio de significado de campos
reescritura masiva de datos históricos
```

## Séptimo. Principio de activación progresiva

El motor semántico no se activará para toda una familia simultáneamente.

La activación se realizará por combinación de:

```text
familia
+ tipo
+ subtipo
```

Por ejemplo:

```text
RESIDENCIA
→ REAGRUPACIÓN FAMILIAR
→ INICIAL
```

podrá ser elegible, mientras otros tipos continúan en legacy.

---

# V. Resolución

## Primero. Aprobación del sistema actual

Se aprueba la arquitectura actual de nomenclaturas canónicas, grupos documentales, roles, readiness, estados semánticos, snapshots y eventos como base del futuro sistema documental del CRM.

## Segundo. Conservación del motor legacy

Se acuerda mantener el motor legacy como comportamiento predeterminado hasta que cada tipo o subtipo haya sido configurado, probado y autorizado expresamente.

## Tercero. No activación general inmediata

Se acuerda no activar todavía de forma general:

```text
DOCUMENT_STATE_ENGINE_MODE=SEMANTIC_ELIGIBLE
DOCUMENT_SEMANTIC_SCAN_EVENTS_ENABLED=1
```

La activación deberá producirse de forma gradual y diferenciada.

## Cuarto. Desarrollo prioritario de familias documentales

Se acuerda iniciar el desarrollo funcional de familias documentales.

La primera familia será:

```text
RESIDENCIA
```

Esta familia actuará como agrupación superior de los tipos existentes, sin sustituirlos ni modificar sus IDs.

## Quinto. Protección de expedientes ya desarrollados

Antes de ampliar la familia Residencia, deberán crearse pruebas de compatibilidad para los procedimientos ya desarrollados, especialmente:

* Reagrupación Familiar;
* Residencia No Lucrativa;
* EX01;
* EX02;
* EX32;
* presentación asistida;
* snapshots;
* mappers;
* relaciones familiares.

Estas pruebas deberán garantizar que la incorporación de familias documentales no altera sus resultados actuales.

## Sexto. Primer expediente piloto

Se acuerda utilizar como primer expediente piloto:

```text
REAGRUPACIÓN FAMILIAR · INICIAL
```

Por ser un procedimiento que permite validar:

* múltiples roles;
* relaciones familiares;
* documentos extranjeros;
* alternativas;
* identidad de varias personas;
* medios económicos;
* vivienda;
* vínculo familiar;
* reutilización del sistema EX02;
* conexión futura con Notificaciones.

## Séptimo. Segundo expediente piloto

Una vez estabilizado el primero, se continuará con:

```text
RESIDENCIA NO LUCRATIVA · INICIAL
```

y posteriormente:

```text
RESIDENCIA NO LUCRATIVA · RENOVACIÓN
```

Su configuración documental deberá realizarse sin alterar el mapper EX01 ni los snapshots ya existentes.

## Octavo. Desarrollo posterior de nuevos expedientes

Una vez validados los procedimientos existentes, podrán incorporarse nuevos tipos de expediente dentro de la familia Residencia.

La creación de cada nuevo tipo deberá incluir:

* código;
* denominación;
* familia;
* subtipo;
* roles;
* formulario aplicable;
* tasa;
* canal de presentación;
* grupos documentales;
* opciones;
* reglas;
* eventos procesales;
* acciones posteriores.

## Noveno. Activación del motor semántico

La activación seguirá este orden:

### Fase de diagnóstico en sombra

```text
legacy activo
+
diagnóstico semántico calculado
```

El resultado semántico se utilizará exclusivamente para comparación.

### Fase semántica elegible

Se activará:

```text
DOCUMENT_STATE_ENGINE_MODE=SEMANTIC_ELIGIBLE
```

únicamente para los tipos y subtipos autorizados.

### Fase de eventos Box

Solo después de validar el diagnóstico se activará:

```text
DOCUMENT_SEMANTIC_SCAN_EVENTS_ENABLED=1
```

Los primeros eventos deberán ser técnicos y revisables.

## Décimo. Retorno al módulo de Notificaciones

Se acuerda retomar el desarrollo del módulo de Notificaciones una vez estén estabilizados:

* familias;
* tipos;
* subtipos;
* grupos documentales;
* roles;
* readiness;
* eventos semánticos.

Las notificaciones deberán originarse en eventos de dominio y no directamente en la existencia de archivos.

El flujo aprobado será:

```text
documento o acción
→ cambio de estado
→ evento de dominio
→ política de notificación
→ notificación visible
→ calendario o CAA, cuando proceda
```

## Undécimo. Integración con Trazabilidad

La Trazabilidad continuará siendo la fuente principal de eventos procesales, entre ellos:

* presentación;
* requerimiento;
* concesión;
* denegación;
* archivo;
* desistimiento;
* nota con fecha;
* anexado de tasa;
* anexado de resolución.

El motor documental será la fuente de eventos documentales, entre ellos:

* documentación completada;
* documentación incompleta;
* documento ambiguo;
* requisito satisfecho;
* requisito perdido;
* diagnóstico disponible;
* diagnóstico no disponible.

## Duodécimo. Integración con Calendario y CAA

Se establece la siguiente regla:

```text
evento informativo
→ Notificaciones

evento con fecha
→ Calendario

evento que exige actuación
→ Centro de Actividades Administrativas

evento con actuación y plazo
→ CAA + Calendario + Notificación
```

---

# VI. Hoja de ruta aprobada

## Fase 1. Protección y auditoría

Objetivo: congelar el comportamiento actual.

Actuaciones:

1. Inventariar tipos y subtipos existentes.
2. Identificar formularios asociados.
3. Identificar mappers.
4. Identificar snapshots.
5. Identificar presentación asistida.
6. Crear pruebas de compatibilidad.
7. Documentar contratos funcionales.

Resultado:

```text
ningún cambio documental podrá romper
el comportamiento actual de los expedientes.
```

## Fase 2. Catálogo funcional de la familia Residencia

Objetivo: organizar los procedimientos existentes.

Actuaciones:

1. Crear o completar la familia Residencia.
2. Vincular tipos existentes.
3. Mantener IDs y códigos.
4. Diferenciar tipo, subtipo y relación.
5. Clasificar procedimientos iniciales, renovaciones y modificaciones.

Resultado:

```text
familia Residencia operativa como capa organizativa.
```

## Fase 3. Reagrupación Familiar inicial

Objetivo: primer expediente semántico completo.

Actuaciones:

1. Definir roles.
2. Definir grupos documentales.
3. Definir opciones.
4. Vincular nomenclaturas.
5. Configurar reglas condicionales.
6. Crear pruebas.
7. Comparar legacy y semántico.
8. Mantener EX02 intacto.

Resultado:

```text
Reagrupación Familiar continúa funcionando igual
y añade diagnóstico documental semántico.
```

## Fase 4. Residencia No Lucrativa

Objetivo: validar reutilización de grupos comunes.

Grupos previsibles:

* identidad;
* medios económicos;
* seguro médico;
* antecedentes;
* domicilio;
* tasas;
* representación.

Resultado:

```text
No Lucrativa mantiene EX01 y presentación asistida,
pero obtiene diagnóstico documental estructurado.
```

## Fase 5. Nuevos tipos de expediente

Objetivo: ampliar progresivamente la familia Residencia.

Orden recomendado:

1. Renovación de Reagrupación Familiar.
2. Familiar de ciudadano español.
3. Arraigos.
4. Modificaciones.
5. Larga duración.
6. Estudiantes.
7. Protección temporal.
8. Otros procedimientos.

## Fase 6. Activación semántica controlada

Objetivo: dar autoridad progresiva al nuevo motor.

Actuaciones:

1. Activación por tipo/subtipo.
2. Comparación con legacy.
3. Revisión de diferencias.
4. Corrección de falsos positivos.
5. Resolución de ambigüedades.
6. Validación del readiness.
7. Autorización expresa.

## Fase 7. Eventos automáticos de Box

Objetivo: detectar cambios reales.

Actuaciones:

1. Crear snapshots iniciales.
2. Evitar eventos masivos iniciales.
3. Activar fingerprints.
4. Registrar cambios.
5. Supervisar errores.
6. Mantener aislamiento por expediente.

## Fase 8. Notificaciones

Objetivo: transformar eventos fiables en avisos útiles.

Primeras reglas recomendadas:

* expediente presentado → espera de notificación;
* expediente concedido → cierre de espera;
* expediente denegado → aviso prioritario;
* documentación completa → propuesta de envío al CAA;
* documentación incompleta → alerta;
* ambigüedad de rol → revisión documental;
* requerimiento → plazo;
* tasa anexada → recordatorio;
* nota con fecha → calendario.

## Fase 9. Calendario y Centro de Actividades Administrativas

Objetivo: convertir información en trabajo ejecutable.

Ejemplos:

```text
concesión
→ solicitud de cita de huellas

concesión de nacionalidad
→ solicitud de cita de jura

requerimiento
→ tarea con vencimiento

tasa
→ tarea de aportación a diez días
```

---

# VII. Criterios para considerar finalizada cada incorporación

Un tipo o subtipo no podrá considerarse plenamente integrado hasta que cumpla:

1. Familia correctamente asignada.
2. Tipo y subtipo estables.
3. Roles definidos.
4. Grupos documentales definidos.
5. Opciones y alternativas configuradas.
6. Nomenclaturas canónicas vinculadas.
7. Reglas condicionales verificadas.
8. Readiness comprensible.
9. Comparación legacy/semántico revisada.
10. Formularios sin regresiones.
11. Presentación asistida sin regresiones.
12. Pruebas superadas.
13. Feature flag autorizado.
14. Eventos revisados.
15. Notificaciones definidas, cuando proceda.

---

# VIII. Conclusión

El sistema actual de nomenclaturas constituye una base sólida para evolucionar hacia un sistema experto documental.

No procede una sustitución inmediata del sistema anterior, sino una transición progresiva basada en:

```text
conservación
→ extensión compatible
→ pruebas
→ diagnóstico en sombra
→ activación por expediente
→ eventos
→ notificaciones
→ calendario y CAA
```

La prioridad inmediata no es activar todo el motor semántico, sino desarrollar correctamente las familias documentales y proteger los expedientes ya existentes.

La secuencia aprobada es:

```text
1. Proteger Reagrupación Familiar y No Lucrativa.
2. Completar la familia Residencia.
3. Configurar Reagrupación Familiar inicial.
4. Configurar No Lucrativa.
5. Incorporar nuevos expedientes.
6. Activar el diagnóstico semántico en piloto.
7. Activar eventos Box.
8. Retomar Notificaciones.
9. Integrar Calendario y CAA.
```

En consecuencia, el sistema documental actual se declara:

```text
TÉCNICAMENTE APROBADO,
OPERATIVAMENTE EN MODO LEGACY,
Y PREPARADO PARA DESPLIEGUE SEMÁNTICO PROGRESIVO.
```
