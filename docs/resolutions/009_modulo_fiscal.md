# 📄 RESOLUCIÓN 009

## Módulo fiscal y control de coherencia tributaria

### ERP Quesada Abogados

**Fecha:** 25/04/2026
**Estado:** APROBADA
**Autoridad:** Dirección del Proyecto

---

## 1. Objeto de la resolución

La presente resolución define el módulo fiscal del ERP, orientado al control y verificación de las obligaciones tributarias del despacho.

El sistema NO sustituirá a la asesoría fiscal.

El sistema actuará como:

```text
Sistema de control y validación interna de la realidad fiscal del despacho
```

---

## 2. Régimen fiscal del despacho

Se establece que el despacho opera bajo la figura de:

```text
Autónomo
```

Por tanto, el sistema deberá contemplar:

* IVA (modelo 303)
* IRPF (modelo 130)
* Retenciones (modelo 111)
* Resúmenes anuales (390, 190)

---

## 3. Principio fundamental

El módulo fiscal deberá garantizar:

```text
Que lo declarado a Hacienda coincida con la realidad económica del ERP
```

Y detectar cualquier desviación.

---

## 4. Fuentes de datos

El sistema fiscal se alimentará de:

```text
Cobros registrados en el ERP
Facturas emitidas
Movimientos bancarios conciliados
Ingresos de efectivo controlados
Datos proporcionados por la asesoría
```

---

## 5. Registro de declaraciones fiscales

El sistema deberá permitir registrar:

```text
Tipo de modelo (303, 130, 111, 390, etc.)
Periodo (trimestre / anual)
Fecha de presentación
Importe declarado
Resultado (a pagar / a devolver)
Documento adjunto (PDF)
Observaciones
```

---

## 6. Cálculo interno del ERP

El ERP deberá poder calcular automáticamente:

```text
Base imponible total
IVA repercutido
Ingresos reales conciliados
Ingresos en efectivo ingresados en banco
Facturación emitida
```

---

## 7. Comparación fiscal

El sistema deberá comparar:

```text
Datos declarados por la asesoría
VS
Datos calculados por el ERP
```

Resultado esperado:

```text
Coincidente
Diferencia leve
Diferencia significativa
Error crítico
```

---

## 8. Control del IVA

El sistema deberá verificar:

```text
IVA declarado
IVA generado por facturas
IVA derivado de cobros reales
```

Y detectar:

```text
Facturas no declaradas
Cobros no facturados
Descuadres de IVA
```

---

## 9. Control de ingresos

El sistema deberá cruzar:

```text
Cobros ERP
Movimientos bancarios conciliados
Efectivo ingresado
Declaraciones fiscales
```

---

## 10. Reglas de coherencia

Se establecen reglas obligatorias:

### 10.1 Banco

```text
Solo se considera ingreso válido el dinero conciliado
```

---

### 10.2 Efectivo

```text
Solo se considera válido el efectivo ingresado en banco
```

---

### 10.3 Facturación

```text
No todo cobro implica factura
Pero toda factura debe tener base real
```

---

## 11. Alertas fiscales

El sistema deberá generar alertas como:

```text
IVA declarado inferior al calculado
Ingresos no declarados
Facturación incoherente
Diferencias entre ERP y asesoría
Cobros sin reflejo fiscal
Efectivo no ingresado
```

---

## 12. Panel fiscal

El ERP deberá incluir un panel donde se visualice:

```text
Ingresos totales por periodo
IVA calculado
IVA declarado
Diferencias
Estado fiscal
Alertas activas
```

---

## 13. Relación con Holded

El módulo fiscal deberá ser coherente con la estrategia definida:

* Holded es sistema contable oficial
* ERP controla lógica y coherencia

El sistema deberá permitir contrastar:

```text
Facturas exportadas a Holded
VS
Declaraciones fiscales
```

---

## 14. Objetivo del módulo

El objetivo NO es hacer contabilidad.

El objetivo es:

```text
Evitar errores fiscales
Detectar incoherencias
Controlar ingresos reales
Verificar el trabajo de la asesoría
```

---

## 15. Prioridad de implementación

Este módulo NO es prioritario en fase inicial.

Se desarrollará cuando:

```text
Módulo de cobros esté estable
Conciliación funcione correctamente
Facturación esté operativa
```

---

## 16. Consecuencia para el sistema

A partir de esta resolución, el ERP deberá contemplar:

```text
Entidad declaraciones_fiscales
Sistema de cálculo interno
Motor de comparación
Sistema de alertas fiscales
Panel de control fiscal
```

---

## 17. Criterio rector

El sistema deberá poder responder siempre:

```text
¿Estamos declarando correctamente?
¿Coincide lo declarado con lo cobrado?
¿Hay riesgo fiscal?
```

---

## 18. Ubicación del documento

```text
docs/resolutions/009_modulo_fiscal.md
```

---

## 19. Commit recomendado

```text
Add resolution 009 fiscal control module
```

---

## 🔒 Cierre

Queda aprobado el módulo fiscal del ERP Quesada Abogados.

Este módulo permitirá al despacho tener control real sobre su situación tributaria y evitar errores, incoherencias o riesgos fiscales.
