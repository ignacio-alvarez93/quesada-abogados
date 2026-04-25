# 📄 RESOLUCIÓN 003 (ACTUALIZADA)

## Ecosistema tecnológico e integraciones

### ERP Quesada Abogados

**Fecha:** 25/04/2026
**Estado:** APROBADA (ACTUALIZADA)
**Autoridad:** Dirección del Proyecto

---

## 1. Objeto de la resolución

La presente resolución define el ecosistema tecnológico del despacho y establece cómo el ERP se integrará con las herramientas existentes.

El ERP actuará como sistema central, pero sin sustituir inicialmente las plataformas actuales.

---

## 2. Herramientas actuales del despacho

El despacho utiliza:

* HubSpot → CRM y captación de clientes
* Holded → facturación y contabilidad
* Gmail → comunicación
* IONOS → infraestructura
* WhatsApp → comunicación directa

---

## 3. Principio de integración

```text id="c8k2m9"
El ERP centraliza la gestión operativa,
pero intercambia información con herramientas externas mediante procesos simples y controlados.
```

---

## 4. Integración con HubSpot

Se establece que:

### 4.1 Entrada de clientes

Los clientes podrán entrar en el ERP mediante:

* Importación desde HubSpot (exportación CSV)
* Inserción manual dentro del ERP

---

### 4.2 Estrategia

* HubSpot seguirá siendo herramienta comercial
* El ERP será herramienta operativa

👉 No se realizará integración por API en fases iniciales

---

### 4.3 Objetivo

```text id="h0h9n2"
Convertir leads de HubSpot en clientes operativos dentro del ERP.
```

---

## 5. Integración con Holded

Se establece que:

### 5.1 Salida de facturación

El ERP generará datos de facturación que serán exportados en formato:

```text id="7y1b5r"
CSV
```

Estos archivos serán importados manualmente en Holded.

---

### 5.2 Estrategia

* Holded seguirá siendo el sistema contable oficial
* El ERP gestionará la lógica de cobros y expedientes

---

### 5.3 Objetivo

```text id="q4xk8d"
Separar la gestión jurídica de la contable,
manteniendo compatibilidad entre sistemas.
```

---

## 6. Ventajas del modelo adoptado

Este enfoque permite:

* evitar integraciones complejas al inicio
* reducir errores técnicos
* mantener control total del sistema
* facilitar implementación rápida
* permitir evolución futura hacia APIs

---

## 7. Automatización

Se mantiene como línea estratégica:

* automatización de procesos administrativos
* interacción con plataformas externas

---

## 8. Tecnología de automatización

Se aprueba el uso de:

* SeleniumBase
* `sb_cdp.Chrome`

Para:

* control de navegador
* automatización de tareas
* interacción con formularios
* gestión de procesos repetitivos

---

## 9. Principios de automatización

* supervisión humana obligatoria
* control de errores
* seguridad en credenciales
* procesos reproducibles

---

## 10. Arquitectura derivada

Se deberán contemplar módulos:

```text id="ypsm3c"
Importación de clientes (HubSpot CSV)
Exportación de facturación (Holded CSV)
Automatización
Integraciones futuras
```

---

## 11. Evolución futura

En fases posteriores se podrá:

* integrar API de HubSpot
* integrar API de Holded
* automatizar importaciones/exportaciones
* sincronizar datos en tiempo real

---

## 12. Ubicación del documento

```text id="3nfh6u"
docs/resolutions/003_ecosistema_tecnologico.md
```

---

## 13. Commit recomendado

```text id="5n0zru"
Update resolution 003 integration strategy HubSpot Holded CSV
```

---

## 🔒 Cierre

Queda aprobada la presente actualización como base de integración tecnológica del ERP.

El sistema se desarrollará bajo un modelo práctico, controlado y escalable, priorizando simplicidad operativa sobre complejidad técnica.
