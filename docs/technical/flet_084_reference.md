# Flet Reference - Versión 0.84.0

## Información general

- Versión: 0.84.0
- Tipo: Desktop App
- Fuente: Referencia generada localmente desde la librería instalada
- Proyecto: Quesada Abogados ERP

---

## Principios de uso

- No asumir APIs de versiones anteriores o posteriores
- Validar siempre contra esta referencia
- Separar UI (Flet) de lógica (backend)
- No usar patrones legacy (overlay manual, etc.)

---

## Controles verificados

---

### Image

Uso correcto:

```python
ft.Image(
    src="captura.png",
    width=140
)

if __name__ == "__main__":
    main()