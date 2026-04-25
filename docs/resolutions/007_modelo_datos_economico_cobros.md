# 📄 RESOLUCIÓN 007

## Modelo de datos — Módulo Económico y Cobros

### ERP Quesada Abogados

**Fecha:** 25/04/2026
**Estado:** APROBADA
**Autoridad:** Dirección del Proyecto

---

## 1. Objeto de la resolución

La presente resolución define el modelo funcional inicial del módulo **Económico y Cobros** del ERP Quesada Abogados.

Este módulo deberá permitir controlar honorarios, hojas de encargo, pagos fraccionados, cobros, facturas, conciliación bancaria y gastos.

---

## 2. Principio fundamental

El sistema económico del despacho no se basará únicamente en facturas.

El control económico deberá partir de:

```text
Hoja de encargo
Expediente
Honorarios pactados
Pagos recibidos
Importe pendiente
Plazos de pago
Facturación
Conciliación bancaria
Gastos
```

---

## 3. Áreas del módulo económico

El módulo económico se dividirá inicialmente en cinco áreas:

```text
1. Hojas de encargo
2. Cobros
3. Facturas
4. Conciliación bancaria
5. Gastos
```

---

## 4. Hojas de encargo

La hoja de encargo será el documento económico-jurídico principal.

Marca el momento en que:

* se inicia formalmente el expediente;
* se pactan honorarios;
* se define el procedimiento;
* se vincula cliente, expediente e importe;
* nace la obligación de control económico.

Campos mínimos:

```text
Cliente
Expediente
Fecha de firma
Tipo de procedimiento
Honorarios pactados
Descuento aplicado
Importe final
Forma de pago pactada
Número de plazos
Fecha máxima de pago
Observaciones económicas
Documento asociado
Estado
```

Estados posibles:

```text
Pendiente de firma
Firmada
Cancelada
Archivada
```

---

## 5. Plazo máximo de fraccionamiento

Como regla general de dirección:

```text
El plazo máximo ordinario de fraccionamiento de un expediente será de 3 meses.
```

El sistema deberá detectar expedientes con pagos pendientes fuera de plazo.

---

## 6. Pagos fraccionados

El sistema deberá permitir que un expediente se pague en varios plazos.

Cada plazo deberá poder tener:

```text
Expediente
Hoja de encargo
Importe previsto
Fecha prevista de pago
Importe pagado
Fecha real de pago
Estado del plazo
Observaciones
```

Estados posibles:

```text
Pendiente
Pagado parcial
Pagado
Vencido
Cancelado
```

---

## 7. Detección de impagos

El ERP deberá identificar automáticamente:

```text
Clientes con plazos vencidos
Expedientes con pagos pendientes
Expedientes sin pagos recientes
Expedientes que superan 3 meses sin completar pago
Clientes con deuda acumulada
```

Esto será una prioridad funcional del módulo.

---

## 8. Consultas previas

El sistema deberá contemplar consultas previas pagadas.

Ejemplo:

```text
Consulta previa: 50 euros
```

Cuando posteriormente el cliente inicia expediente, el sistema deberá permitir:

```text
Descontar la consulta previa del importe del trámite
```

Aunque hayan pasado varios meses.

Campos mínimos para consultas previas:

```text
Cliente
Fecha de consulta
Importe pagado
Forma de pago
Profesional responsable
Descontable: sí/no
Expediente vinculado posteriormente
Fecha de aplicación del descuento
Observaciones
```

---

## 9. Cobros

El área de cobros registrará cada pago real recibido.

Un cobro podrá estar vinculado a:

```text
Cliente
Expediente
Hoja de encargo
Plazo
Factura
Consulta previa
```

Campos mínimos:

```text
Cliente
Expediente
Fecha de cobro
Importe
Forma de pago
Concepto
Recibo asociado
Factura asociada
Cuenta bancaria
Observaciones
Usuario que registra el cobro
```

Formas de pago iniciales:

```text
Efectivo
Transferencia
Tarjeta
Bizum
Otro
```

---

## 10. Facturas

No todos los cobros generan factura en el ERP.

El sistema deberá permitir:

```text
Cobros facturados
Cobros no facturados
Facturas emitidas
Facturas pendientes de exportar
Facturas exportadas a Holded
```

La facturación oficial podrá gestionarse en Holded, pero el ERP deberá generar datos exportables en CSV conforme a la estrategia tecnológica aprobada.

Campos mínimos de factura:

```text
Cliente
Expediente
Número interno
Fecha
Base imponible
IVA
IRPF si procede
Total factura
Estado
Exportada a Holded
Fecha de exportación
Observaciones
```

Estados posibles:

```text
Borrador
Emitida
Exportada a Holded
Anulada
```

---

## 11. Conciliación bancaria

El ERP deberá permitir conciliar cobros con movimientos bancarios.

Objetivos:

```text
Detectar pagos no registrados
Detectar cobros registrados no conciliados
Relacionar transferencias con clientes
Controlar ingresos reales
Evitar errores económicos
```

Campos mínimos de movimiento bancario:

```text
Fecha operación
Fecha valor
Concepto bancario
Importe
Cuenta bancaria
Referencia
Cliente identificado
Cobro asociado
Estado de conciliación
Observaciones
```

Estados de conciliación:

```text
Pendiente
Conciliado
Dudoso
No identificado
Ignorado
```

---

## 12. Gastos

El módulo económico también deberá registrar gastos del despacho.

Campos mínimos:

```text
Fecha
Proveedor
Concepto
Categoría
Importe
Forma de pago
Factura recibida
Expediente asociado si procede
Estado
Observaciones
```

Categorías iniciales:

```text
Tasas
Procurador
Traducciones
Mensajería
Material de oficina
Servicios externos
Software
Otros gastos
```

---

## 13. Relación con expedientes

Todo expediente deberá permitir ver:

```text
Honorarios pactados
Importe cobrado
Importe pendiente
Plazos vencidos
Consultas descontadas
Facturas vinculadas
Gastos asociados
Estado económico
```

Estados económicos del expediente:

```text
Sin hoja de encargo
Pendiente de pago
Pago parcial
Pagado
Vencido
Cancelado
```

---

## 14. Consecuencia para la base de datos

El modelo deberá contemplar, al menos, las siguientes entidades futuras:

```text
hojas_encargo
planes_pago
plazos_pago
cobros
consultas_previas
facturas
factura_lineas
movimientos_bancarios
conciliaciones
gastos
clientes
expedientes
```

---

## 15. Prioridad inicial

En la primera fase se desarrollará:

```text
Hoja de encargo
Honorarios del expediente
Registro de cobros
Importe pendiente
Detección de vencidos
Listado de clientes con deuda
```

Posteriormente se ampliará con:

```text
Facturas
Exportación CSV a Holded
Conciliación bancaria
Gastos
Consultas previas descontables
Informes económicos
```

---

## 16. Criterio rector

El módulo económico deberá responder siempre a tres preguntas:

```text
¿Cuánto se pactó?
¿Cuánto se ha cobrado?
¿Cuánto queda pendiente?
```

Y además deberá permitir detectar:

```text
Quién no está pagando
Desde cuándo no paga
Qué expediente tiene deuda
Qué pagos deben reclamarse
```

---

## 17. Ubicación del documento

```text
docs/resolutions/007_modelo_datos_economico_cobros.md
```

---

## 18. Commit recomendado

```text
Add resolution 007 economic and payments data model
```

---

## 🔒 Cierre

Queda aprobado el modelo funcional inicial del módulo Económico y Cobros.

Este módulo será esencial para controlar la rentabilidad, evitar impagos y vincular correctamente clientes, expedientes, honorarios y pagos.
