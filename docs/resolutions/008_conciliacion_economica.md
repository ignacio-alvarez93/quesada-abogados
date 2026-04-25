# 📄 RESOLUCIÓN 008

## Conciliación económica y control de cobros reales

### ERP Quesada Abogados

**Fecha:** 25/04/2026
**Estado:** APROBADA
**Autoridad:** Dirección del Proyecto

---

## 1. Objeto de la resolución

La presente resolución define el sistema real de conciliación económica del despacho.

El objetivo es asegurar que:

```text
Todo cobro tenga reflejo real en dinero
y todo dinero tenga origen identificado
```

---

## 2. Cuentas y sistemas utilizados

El despacho opera con los siguientes sistemas financieros:

### 2.1 Cuentas bancarias

```text
Banco Santander
ING
Caja Rural
```

---

### 2.2 Sistemas de caja

```text
Cashmatic
```

Funciones:

* registro de efectivo
* control de caja
* generación de movimientos
* exportación de datos (cashbook)

---

### 2.3 Pasarela de pago

```text
Stripe
```

---

## 3. Flujo real de cobro

### 3.1 Pago en efectivo

Cuando un cliente paga en efectivo:

1. Se genera un recibo en papel
2. Se registra la operación en Cashmatic
3. Se guarda como cobro en el ERP

---

### 3.2 Pago con tarjeta

Cuando un cliente paga con tarjeta:

1. Se realiza pago mediante datáfono
2. El dinero se registra en banco / pasarela
3. Se registra el cobro en el ERP

---

## 4. Importación de movimientos

El sistema deberá permitir cargar diariamente:

```text
CSV de bancos (Santander, ING, Caja Rural)
CSV de Cashmatic
```

Estos archivos serán la base de conciliación.

---

## 5. Conciliación obligatoria

El ERP deberá cruzar:

```text
Cobros registrados en el ERP
Recibos en papel
Movimientos bancarios
Movimientos de Cashmatic
```

---

## 6. Objetivo de la conciliación

El sistema deberá permitir:

```text
Saber de qué cliente es cada ingreso
Detectar cobros no registrados
Detectar movimientos sin asignar
Detectar errores humanos
Controlar dinero real vs sistema
```

---

## 7. Conciliación de efectivo

Regla fundamental:

```text
El efectivo registrado en Cashmatic
debe coincidir con el efectivo ingresado en banco.
```

Control:

* conciliación diaria → Cashmatic vs recibos
* conciliación periódica → efectivo vs ingreso bancario

---

## 8. Conciliación bancaria

El sistema deberá identificar:

```text
Transferencias
Pagos con tarjeta
Ingresos
Movimientos desconocidos
Duplicidades
```

Cada movimiento deberá poder asignarse a:

```text
Cliente
Expediente
Cobro
Factura
Otro concepto
```

---

## 9. Estados de conciliación

Todo movimiento deberá tener estado:

```text
Pendiente
Conciliado
Parcial
No identificado
Error
```

---

## 10. Regla de facturación

Se establece una norma crítica:

```text
NO todo lo cobrado se factura automáticamente
```

---

## 11. Criterio de facturación

Se facturará únicamente:

### 11.1 Cobros en banco

```text
Solo si están conciliados
```

---

### 11.2 Cobros en efectivo

```text
Solo si coinciden con el efectivo ingresado en banco
```

(ingresos agrupados trimestralmente)

---

## 12. Control del efectivo

El sistema deberá permitir:

```text
Total efectivo registrado
Total efectivo ingresado en banco
Diferencias
Descuadres
Alertas
```

---

## 13. Relación con recibos en papel

El ERP deberá permitir registrar:

```text
Número de recibo
Fecha
Importe
Cliente
Forma de pago
Usuario que lo emite
```

Y vincularlo con:

```text
Cobro en ERP
Movimiento en Cashmatic
Ingreso bancario posterior
```

---

## 14. Detección de errores

El sistema deberá detectar automáticamente:

```text
Cobros sin movimiento bancario
Movimientos sin cliente asignado
Recibos no registrados en sistema
Diferencias de efectivo
Ingresos duplicados
Pagos no conciliados
```

---

## 15. Prioridad operativa

El objetivo del módulo NO es contabilidad avanzada.

El objetivo es:

```text
No perder dinero
No tener descuadres
Saber quién ha pagado
Saber quién no ha pagado
```

---

## 16. Consecuencia para el sistema

A partir de esta resolución, el ERP deberá incluir:

```text
Importador de CSV bancarios
Importador de Cashmatic
Motor de conciliación
Gestión de recibos
Control de efectivo
Sistema de alertas
```

---

## 17. Criterio rector

El sistema económico deberá cumplir:

```text
Todo ingreso debe estar identificado
Todo cobro debe estar respaldado
Todo efectivo debe cuadrar
Toda factura debe tener base real
```

---

## 18. Ubicación del documento

```text
docs/resolutions/008_conciliacion_economica.md
```

---

## 19. Commit recomendado

```text
Add resolution 008 financial reconciliation system
```

---

## 🔒 Cierre

Queda aprobado el sistema de conciliación económica del ERP Quesada Abogados.

Este sistema será clave para garantizar el control real del dinero del despacho y evitar errores, pérdidas o incoherencias económicas.
