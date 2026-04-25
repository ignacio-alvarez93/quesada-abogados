# 📄 RESOLUCIÓN 010

## Gestión de datos legacy y reconstrucción histórica

### ERP Quesada Abogados

**Fecha:** 25/04/2026
**Estado:** APROBADA
**Autoridad:** Dirección del Proyecto

---

## 1. Objeto de la resolución

La presente resolución establece las normas para la gestión, migración y reconstrucción de datos históricos (legacy) del despacho.

El objetivo es:

```text
Incorporar información histórica útil
sin comprometer la fiabilidad del ERP
```

---

## 2. Principio fundamental

El ERP se basa en datos fiables.

Por tanto:

```text
El histórico no se importa automáticamente,
se valida, se selecciona y se reconstruye.
```

---

## 3. Alcance del legacy

Se considera legacy:

```text
Recibos anteriores al ERP
Datos en Excel históricos
Documentación en papel
Facturación anterior
Declaraciones fiscales anteriores
```

Periodo relevante:

```text
Desde inicio de actividad (2020) hasta entrada en producción del ERP
```

---

## 4. Estrategia general

Se aprueba un modelo de:

```text
Migración selectiva + reconstrucción controlada
```

---

## 5. Clasificación de datos legacy

Todo dato histórico deberá clasificarse en:

### 5.1 Datos FIABLES

Cumplen al menos dos condiciones:

```text
Cliente identificado
Importe claro
Relación con banco o cashmatic
Recibo físico verificable
```

👉 Estos datos podrán ser reconstruidos

---

### 5.2 Datos DUDOSOS

```text
Información incompleta
Descuadres parciales
Falta de trazabilidad completa
```

👉 Requieren revisión manual
👉 No se procesan automáticamente

---

### 5.3 Datos NO FIABLES

```text
Sin cliente identificado
Sin soporte documental
No conciliables
```

👉 No se incorporan al sistema

---

## 6. Reconstrucción histórica

Se autoriza la reconstrucción de datos legacy únicamente para datos fiables.

El proceso será:

```text
Recibo → Cobro → (opcional) Factura → Conciliación → Fiscal
```

---

## 7. Etiquetado obligatorio

Todo dato reconstruido deberá incluir:

```text
Origen: LEGACY
Tipo: RECONSTRUIDO
Año fiscal
Nivel de fiabilidad
Referencia de origen (Excel / papel / banco)
```

---

## 8. Trazabilidad

Todo dato legacy deberá permitir responder:

```text
¿De dónde proviene?
¿Qué documento lo respalda?
¿Está conciliado?
¿Está vinculado a cliente?
```

---

## 9. Prohibiciones

Queda estrictamente prohibido:

```text
Inventar datos faltantes
Asignar clientes sin certeza
Forzar cuadrar al céntimo
Modificar declaraciones fiscales ya presentadas
Mezclar datos legacy con datos operativos actuales
```

---

## 10. Conciliación obligatoria

Todo dato reconstruido deberá validarse contra:

```text
Movimientos bancarios
Cashmatic
Recibos físicos
Datos fiscales declarados
```

---

## 11. Relación con fiscalidad

El objetivo NO es rehacer la fiscalidad histórica.

El objetivo es:

```text
Aproximar la realidad histórica
y detectar diferencias con lo declarado
```

---

## 12. Gestión de diferencias

Las diferencias deberán registrarse como:

```text
Ajuste histórico
Motivo
Importe
Año
Observaciones
```

Nunca se ocultarán ni corregirán artificialmente.

---

## 13. Facturas reconstruidas

Se permite generar facturas a partir de datos fiables.

Condiciones:

```text
Marcadas como RECONSTRUIDAS
No sustituyen documentos oficiales originales
No alteran fiscalidad histórica declarada
```

---

## 14. Modelo de cierre por ejercicio

Cada año deberá poder cerrarse con:

```text
Total reconstruido
Total declarado
Diferencia
Nivel de fiabilidad
Estado: abierto / validado / cerrado
```

---

## 15. Separación de sistemas

Se establecen dos capas:

### 🟢 Sistema operativo (ERP actual)

```text
Datos fiables
Operativa diaria
Control económico real
```

---

### 🟡 Sistema legacy

```text
Datos históricos
Reconstrucción
Consulta y análisis
```

---

## 16. Uso del papel antiguo

Los documentos físicos no se digitalizarán masivamente.

Solo se incorporarán cuando:

```text
Sea necesario para reconstrucción
Exista relevancia económica
Exista necesidad operativa o legal
```

---

## 17. Prioridad de implementación

El sistema legacy se desarrollará en paralelo, pero sin bloquear:

```text
Clientes
Expedientes
Cobros actuales
Conciliación
```

---

## 18. Objetivo estratégico

El objetivo del módulo legacy es:

```text
Recuperar el máximo valor del pasado
sin comprometer el futuro del sistema
```

---

## 19. Ubicación del documento

```text
docs/resolutions/010_legacy_migracion_reconstruccion.md
```

---

## 20. Commit recomendado

```text
Add resolution 010 legacy data migration and reconstruction
```

---

## 🔒 Cierre

Queda aprobado el modelo de gestión de datos legacy del ERP Quesada Abogados.

Toda migración histórica deberá cumplir estas normas para garantizar la fiabilidad, trazabilidad y coherencia del sistema.
