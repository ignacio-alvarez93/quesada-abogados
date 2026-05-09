"""
Clasificador documental conservador para Vigilancia Box.

Objetivo:
- Normalizar nombres caóticos de carpetas y archivos.
- Clasificar sin tocar Box.
- No inventar: si no hay confianza suficiente devuelve OTROS / SIN CLASIFICAR.

Este módulo NO:
- borra archivos
- mueve archivos
- renombra archivos
- modifica Box
"""

import re
import unicodedata


FOLDER_CATEGORY_PRESENTACION = "PRESENTACION"
FOLDER_CATEGORY_APORTACION = "APORTACION"
FOLDER_CATEGORY_REQUERIMIENTO = "REQUERIMIENTO"
FOLDER_CATEGORY_RESOLUCION = "RESOLUCION"
FOLDER_CATEGORY_RESOLUCION_FAVORABLE = "RESOLUCION_FAVORABLE"
FOLDER_CATEGORY_RESOLUCION_DENEGADA = "RESOLUCION_DENEGADA"
FOLDER_CATEGORY_POLICIALES = "POLICIALES"
FOLDER_CATEGORY_ESCRITOS = "ESCRITOS"
FOLDER_CATEGORY_CONCESION = "CONCESION"
FOLDER_CATEGORY_OTROS = "OTROS"

DOC_SIN_CLASIFICAR = "SIN CLASIFICAR"


def normalize_text(text):
    """
    Convierte texto a una forma comparable:
    - mayúsculas
    - sin acentos
    - sin símbolos problemáticos
    - espacios normalizados
    """
    raw = str(text or "").strip()
    raw = unicodedata.normalize("NFD", raw)
    raw = "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")
    raw = raw.upper()
    raw = raw.replace("_", " ").replace("-", " ").replace(".", " ")
    raw = re.sub(r"[^A-Z0-9Ñ ]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def _has_any(text, tokens):
    return any(token in text for token in tokens)


def _score_match(text, strong_tokens=None, weak_tokens=None):
    strong_tokens = strong_tokens or []
    weak_tokens = weak_tokens or []
    score = 0.0
    matched = []

    for token in strong_tokens:
        if token in text:
            score += 0.45
            matched.append(token)

    for token in weak_tokens:
        if token in text:
            score += 0.20
            matched.append(token)

    if score > 0.98:
        score = 0.98

    return score, matched


def classify_folder(name):
    """
    Clasifica una carpeta interna de expediente.

    Devuelve:
    {
        "categoria": "...",
        "confianza": 0.0-1.0,
        "motivo": "..."
    }
    """
    text = normalize_text(name)

    if not text:
        return {"categoria": FOLDER_CATEGORY_OTROS, "confianza": 0.0, "motivo": "Nombre vacío"}

    # Carpetas genéricas o accidentales.
    if text.startswith("NUEVA CARPETA"):
        return {"categoria": FOLDER_CATEGORY_OTROS, "confianza": 0.95, "motivo": "Carpeta genérica no clasificada"}

    # Carpetas reales detectadas en árboles Box Quesada.
    if _has_any(text, ["JUSTIFICANTE", "JUSTIFICANTES"]):
        return {"categoria": "JUSTIFICANTES", "confianza": 0.95, "motivo": "Carpeta de justificantes detectada"}

    if _has_any(text, ["REQ TASAS", "REQ TASA"]):
        return {"categoria": FOLDER_CATEGORY_REQUERIMIENTO, "confianza": 0.95, "motivo": "Carpeta de requerimiento de tasas detectada"}

    if _has_any(text, ["ABONO", "ABONOS"]):
        return {"categoria": "ABONOS", "confianza": 0.90, "motivo": "Carpeta de abonos detectada"}

    if text == "EMPRESA":
        return {"categoria": "EMPRESA", "confianza": 0.90, "motivo": "Carpeta de documentación de empresa"}

    # Requerimientos.
    score, matched = _score_match(
        text,
        strong_tokens=["REQ DOC", "REQUERIMIENTO", "REQUERIMIENTOS", "SUBSANACION", "SUBSANAR"],
        weak_tokens=["REQ", "DOC REQ"],
    )
    if score >= 0.45:
        return {"categoria": FOLDER_CATEGORY_REQUERIMIENTO, "confianza": score, "motivo": f"Coincidencias: {', '.join(matched)}"}

    # Resoluciones denegadas.
    score, matched = _score_match(
        text,
        strong_tokens=["DENEGACION", "DENEGADA", "RES DENEGACION", "RESOLUCION DENEGACION"],
        weak_tokens=["DENEGA"],
    )
    if score >= 0.45:
        return {"categoria": FOLDER_CATEGORY_RESOLUCION_DENEGADA, "confianza": score, "motivo": f"Coincidencias: {', '.join(matched)}"}

    # Resoluciones favorables / concesiones.
    score, matched = _score_match(
        text,
        strong_tokens=[
            "RES CONCESION",
            "RES DE CONCESION",
            "RESOLUCION CONCESION",
            "CONCESION NACIONALIDAD",
            "CONCESION",
            "CONCEDIDO",
            "FAVORABLE",
        ],
        weak_tokens=["CONCESIO", "RESOLUCION", "RES"],
    )
    if score >= 0.45:
        if _has_any(text, ["CONCESION", "CONCESIO", "CONCEDIDO", "FAVORABLE"]):
            return {"categoria": FOLDER_CATEGORY_RESOLUCION_FAVORABLE, "confianza": score, "motivo": f"Coincidencias: {', '.join(matched)}"}
        return {"categoria": FOLDER_CATEGORY_RESOLUCION, "confianza": score, "motivo": f"Coincidencias: {', '.join(matched)}"}

    # Presentación.
    score, matched = _score_match(
        text,
        strong_tokens=["PARA PRESENTAR", "PRESENTAR", "PRESENTACION"],
        weak_tokens=["PATA PRESENTAR", "PRESENTAC", "PRESENT"],
    )
    if score >= 0.45:
        return {"categoria": FOLDER_CATEGORY_PRESENTACION, "confianza": score, "motivo": f"Coincidencias: {', '.join(matched)}"}

    # Aportaciones / adjuntos.
    score, matched = _score_match(
        text,
        strong_tokens=["APORTAR", "APORTACION", "ADJUNTAR", "PARA ADJUNTAR"],
        weak_tokens=["APORTRA", "ADJUN", "ANEXO"],
    )
    if score >= 0.45:
        return {"categoria": FOLDER_CATEGORY_APORTACION, "confianza": score, "motivo": f"Coincidencias: {', '.join(matched)}"}

    # Policiales.
    score, matched = _score_match(
        text,
        strong_tokens=["POLICIALES", "POLICIA", "ACCESO POLICIALES", "CANCELACION POLICIALES"],
        weak_tokens=["CNP", "PENALES POLICIALES"],
    )
    if score >= 0.45:
        return {"categoria": FOLDER_CATEGORY_POLICIALES, "confianza": score, "motivo": f"Coincidencias: {', '.join(matched)}"}

    # Escritos.
    score, matched = _score_match(
        text,
        strong_tokens=["ESCRITO", "ESCRITO AGILIZACION", "AGILIZACION"],
        weak_tokens=["RECURSO", "ALEGACIONES"],
    )
    if score >= 0.45:
        return {"categoria": FOLDER_CATEGORY_ESCRITOS, "confianza": score, "motivo": f"Coincidencias: {', '.join(matched)}"}

    return {"categoria": FOLDER_CATEGORY_OTROS, "confianza": 0.20, "motivo": "Sin patrón de fase documental"}


def classify_file(filename):
    """
    Clasifica un archivo por nombre.

    Devuelve:
    {
        "tipo_documento": "...",
        "confianza": 0.0-1.0,
        "motivo": "..."
    }
    """
    text = normalize_text(filename)

    if not text:
        return {"tipo_documento": DOC_SIN_CLASIFICAR, "confianza": 0.0, "motivo": "Nombre vacío"}

    # Reglas reales Quesada: se aplican antes de patterns para evitar falsos negativos.
    if re.search(r"\bJUSTIFICANTE\s+23010047L\s+\d+", text):
        return {"tipo_documento": "JUSTIFICANTE_PRESENTACION", "confianza": 0.98, "motivo": "Patrón real justificante_23010047L_fecha"}

    if re.search(r"\bFORMULARIO\s+EX\d+", text):
        return {"tipo_documento": "FORMULARIO_EXTRANJERIA", "confianza": 0.95, "motivo": "Formulario oficial EX detectado"}

    if re.search(r"\bEX\d{2}\b", text):
        return {"tipo_documento": "FORMULARIO_EXTRANJERIA", "confianza": 0.90, "motivo": "Código formulario EX detectado"}

    if _has_any(text, ["JUST ABONO TASA", "JUTS ABONO TASA", "JUSTIFICANTE ABONO TASA", "JUSTIFICANTE PAGO TASA", "PAGO TASA", "COBRO TASA", "PAGOTASA", "ABONO TASA"]):
        return {"tipo_documento": "JUSTIFICANTE_TASA", "confianza": 0.95, "motivo": "Justificante/abono de tasa detectado"}

    if _has_any(text, ["REQ TASAS", "REQ TASA", "REQUERIMIENTO TASAS", "REQUERIMIENTO TASA"]):
        return {"tipo_documento": "REQUERIMIENTO_TASA", "confianza": 0.95, "motivo": "Requerimiento de tasa detectado"}

    if _has_any(text, ["CERT AEAT", "CERTIFICADO AEAT"]):
        return {"tipo_documento": "CERTIFICADO_AEAT", "confianza": 0.95, "motivo": "Certificado AEAT detectado"}

    if _has_any(text, ["CERT TGSS", "CERTIFICADO TGSS"]):
        return {"tipo_documento": "CERTIFICADO_TGSS", "confianza": 0.95, "motivo": "Certificado TGSS detectado"}

    patterns = [
        ("HOJA_ENCARGO", ["HOJA DE ENCARGO", "HOJA ENCARGO", "HOJA ENCARGO FIRMADA", "HOJA DE CARGO"], ["ENCARGO"]),
        ("JUSTIFICANTE_PRESENTACION", ["JUSTIFICANTE PRESENTACION", "JUSTIFICANTE DE PRESENTACION", "JUSTIFICANTE SOLICITUD", "JUSTIFICANTE ANEXO", "JUSTF SOL", "RESGUARDO", "RESG PENADOS"], ["REGISTRO", "ANEXO"]),
        ("RESOLUCION_DENEGADA", ["DENEGACION", "DENEGADA", "RES DENEGACION"], ["DENEGA"]),
        ("RESOLUCION_FAVORABLE", ["RES CONCESION", "RESOLUCION CONCESION", "CONCESION", "FAVORABLE"], ["CONCESIO", "CONCEDIDO"]),
        ("REQUERIMIENTO_TASA", ["REQ TASAS", "REQ TASA", "REQUERIMIENTO TASA", "REQUERIMIENTO TASAS"], []),
        ("REQUERIMIENTO", ["REQUERIMIENTO", "REQ DOC", "SUBSANACION", "SUBSANAR"], ["REQ"]),
        ("PASAPORTE", ["PASAPORTE", "PASSPORT", "PASAP"], ["PASAPORTE ANTERIOR", "PASAPORTE VENCIDO"]),
        ("NIE", ["NIE", "TIE", "TARJETA"], ["NIE ACTUAL", "RENOV NIE"]),
        ("DNI", ["DNI", "CEDULA"], ["DOCUMENTO IDENTIDAD"]),
        ("JUSTIFICANTE_TASA", ["JUST ABONO TASA", "JUTS ABONO TASA", "ABONO TASA", "JUSTIFICANTE TASA", "JUSTIFICANTE PAGO", "PAGO TASA", "TASA PAGADA", "PAGOTASA"], []),
        ("TASA", ["TASA", "FORMULARIO PAGO TASAS", "FORMULARIO 790", "FORMULARIO PAGO TASA", "790", "052", "062", "012", "790012"], ["PAYMENT", "PAGO"]),
        ("EMPADRONAMIENTO", ["EMPADRONAMIENTO", "PADRON", "PADRON HISTORICO", "PADRON COLECTIVO", "PADRON HCO", "PADRON CONJUNTO", "CERTIFICADO DE EMPADRONAMIENTO"], ["OVD 55", "GESTIONES PADRONALES"]),
        ("ANTECEDENTES_ESPANA", ["REGISTROPENADOS", "REGISTRO CENTRAL PENADOS"], ["PENALES ESPANA"]),
        ("ANTECEDENTES", ["ANTECEDENTES", "PENALES", "AAPP"], ["POLICIALES"]),
        ("ACTA_NACIMIENTO", ["ACTA NACIMIENTO", "ACTA NAC", "ACTANAC", "CERTIFICADO NACIMIENTO"], ["NACIMIENTO"]),
        ("ACTA_MATRIMONIO", ["ACTA MATRIMONIO", "ACTA MAT", "CERTIFICADO MATRIMONIO"], ["MATRIMONIO"]),
        ("CCSE", ["CCSE"], []),
        ("DELE", ["DELE"], []),
        ("CONTRATO_TRABAJO", ["CONTRATO TRABAJO", "CONTRATO", "PRECONTRATO", "CONTRATO ALQUILER"], []),
        ("NOMINAS", ["NOMINA", "NOMINAS"], []),
        ("DEMANDA_EMPLEO", ["DEMANDA EMPLEO"], []),
        ("PRUEBAS_PERMANENCIA", ["PRUEBAS PERMANENCIA", "PRUEBAS DE PERMANENCIA", "PRUEBAS", "PRUEBA", "PERMANENCIA"], []),
        ("VULNERABILIDAD", ["VULNERABILIDAD", "VULNERABLIDAD", "CERT VULNERABILIDAD", "INF VULNERABILIDAD", "INFORME MEDICO"], []),
        ("MATRICULA", ["CERT MATRICULA", "RESGUARDO MATRICULA", "MATRICULA", "CERTIF ESCOLAR", "ESCOLARIZACION", "CERT ACADE"], []),
        ("IRPF", ["IRPF", "DECLARACION RENTA", "MODELO 100", "RENTA"], []),
        ("PODER", ["PODER", "DESIGNACION", "DESIGNACION DE REPRESENTANTE", "DESIG", "DESIGNA REPRE", "DESIG REPRES"], ["REPRESENTANTE"]),
        ("NOTAS_CARPETA", ["NOTAS CARPETA", "NOTAS", "NOTS"], []),
        ("RESUMEN_EXPEDIENTE", ["RESUMEN EXPEDIENTE"], []),
        ("VIDA_LABORAL", ["VIDA LABORAL", "VIDA LAB"], []),
        ("LIBRO_FAMILIA", ["LIBRO FAMILIA", "LIBRO FAM"], []),
        ("FIRMA", ["FIRMA"], []),
        ("CARPETA_EXPEDIENTE", ["CARPETA"], []),
    ]

    best = {"tipo_documento": DOC_SIN_CLASIFICAR, "confianza": 0.0, "motivo": "Sin patrón documental"}
    for tipo, strong, weak in patterns:
        score, matched = _score_match(text, strong_tokens=strong, weak_tokens=weak)
        if score > best["confianza"]:
            best = {
                "tipo_documento": tipo,
                "confianza": score,
                "motivo": f"Coincidencias: {', '.join(matched)}" if matched else "Sin coincidencias",
            }

    if best["confianza"] < 0.45:
        return {"tipo_documento": DOC_SIN_CLASIFICAR, "confianza": best["confianza"], "motivo": best["motivo"]}

    return best


def detect_expedient_state(folder_categories, file_types=None):
    """
    Detecta estado documental básico a partir de categorías de carpetas y tipos de documentos.

    Devuelve:
    {
        "estado": "...",
        "confianza": 0.0-1.0,
        "motivo": "..."
    }
    """
    categories = {str(x or "").upper() for x in (folder_categories or [])}
    docs = {str(x or "").upper() for x in (file_types or [])}

    if FOLDER_CATEGORY_RESOLUCION_DENEGADA in categories or "RESOLUCION_DENEGADA" in docs:
        return {"estado": "RESUELTO_DENEGADO", "confianza": 0.90, "motivo": "Existe resolución denegatoria"}

    if FOLDER_CATEGORY_RESOLUCION_FAVORABLE in categories or "RESOLUCION_FAVORABLE" in docs:
        return {"estado": "RESUELTO_FAVORABLE", "confianza": 0.90, "motivo": "Existe concesión/resolución favorable"}

    if FOLDER_CATEGORY_REQUERIMIENTO in categories or "REQUERIMIENTO" in docs:
        return {"estado": "REQUERIDO", "confianza": 0.85, "motivo": "Existe requerimiento o subsanación"}

    if FOLDER_CATEGORY_APORTACION in categories:
        return {"estado": "PENDIENTE_APORTACION", "confianza": 0.75, "motivo": "Existe carpeta de aportación/adjuncción"}

    if FOLDER_CATEGORY_PRESENTACION in categories or "JUSTIFICANTE_PRESENTACION" in docs:
        return {"estado": "PREPARADO_O_PRESENTADO", "confianza": 0.65, "motivo": "Existe fase de presentación o justificante"}

    if docs:
        return {"estado": "EN_PREPARACION", "confianza": 0.45, "motivo": "Existen documentos inventariados"}

    return {"estado": "SIN_CLASIFICAR", "confianza": 0.20, "motivo": "Sin señales suficientes"}
