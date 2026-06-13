"""
column_mapping.py
-----------------
Resolución robusta de nombres de columnas para los 5 documentos de input.

Los archivos de INSSJP llegan con encabezados inconsistentes (acentos, mayúsculas,
puntos, espacios dobles). Este módulo normaliza y mapea cada campo lógico contra
una lista de candidatos, con respaldo por similitud difusa (rapidfuzz).
"""

from __future__ import annotations
import unicodedata
import re
from rapidfuzz import process, fuzz


# ----------------------------------------------------------------------------- #
#  Normalización
# ----------------------------------------------------------------------------- #
def normalize(text) -> str:
    """Mayúsculas, sin acentos, sin puntuación redundante, espacios colapsados."""
    if text is None:
        return ""
    s = str(text)
    # quitar acentos
    s = "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )
    s = s.upper()
    s = s.replace("Ñ", "N")
    # unificar separadores
    s = re.sub(r"[._]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


# ----------------------------------------------------------------------------- #
#  Catálogo de campos lógicos por documento
# ----------------------------------------------------------------------------- #
# Cada entrada: campo_lógico -> lista de encabezados candidatos (en lenguaje natural)
SCHEMAS = {
    "prestaciones": {
        "u_acepto":      ["U.ACEPTO", "U ACEPTO", "UACEPTO", "U_ACEPTO"],
        "practica":      ["PRÁCTICA", "PRACTICA"],
        "nro_orden":     ["NRO. ORDEN", "NRO ORDEN", "NUMERO DE ORDEN", "N ORDEN", "ORDEN"],
        "nro_beneficio": ["NRO. BENEFICIO/GP", "NRO BENEFICIO/GP", "NRO. BENEFICIO",
                          "BENEFICIO/GP", "NRO BENEFICIO GP", "NRO BENEFICIO"],
    },
    "usuarios": {
        "u_acepto":           ["U.ACEPTO", "U ACEPTO", "UACEPTO", "U_ACEPTO"],
        "cuenta":             ["CUENTA", "NRO CUENTA", "CUENTA ASIGNADA"],
        "nombre_profesional": ["NOMBRE DEL PROFESIONAL", "NOMBRE PROFESIONAL",
                               "PROFESIONAL", "NOMBRE", "RAZON SOCIAL"],
        "tipo":               ["TIPO"],
    },
    "valores": {
        "codigo_practica": ["CÓDIGO DE PRÁCTICA", "CODIGO DE PRACTICA", "CODIGO PRACTICA",
                            "CÓDIGO PRÁCTICA", "COD PRACTICA", "CODIGO"],
        "valor":           ["VALOR", "IMPORTE", "PRECIO", "VALOR PRESTACION", "ARANCEL"],
    },
    "pueyrredon": {
        "nro_orden": ["NRO. ORDEN", "NRO ORDEN", "NUMERO DE ORDEN", "N ORDEN", "ORDEN"],
        "pct_p":     ["%P", "% P", "PORCENTAJE P", "PORC P"],
        "cuenta_p":  ["CUENTA P", "CUENTAP"],
        "pct_c":     ["%C", "% C", "PORCENTAJE C", "PORC C"],
        "cuenta_c":  ["CUENTA C", "CUENTAC"],
    },
    "parametros": {
        "cuenta":       ["CUENTA"],
        "cod_practica": ["COD PRACTICA", "CÓDIGO DE PRÁCTICA", "CODIGO PRACTICA",
                         "COD PRÁCTICA", "CODIGO DE PRACTICA"],
        "pct_p":        ["% PRO", "PORCENTAJE PROFESIONAL", "% PROFESIONAL", "%P"],
        "cuenta_p":     ["CUENTA P", "CUENTAP"],
        "pct_c":        ["% CENTRO", "PORCENTAJE CENTRO", "%C"],
        "cuenta_c":     ["CUENTA C", "CUENTAC"],
    },
}

# Campos que pueden faltar sin abortar el proceso
OPTIONAL_FIELDS = {
    "prestaciones": {"nro_beneficio"},
    "usuarios": set(),
    "valores": set(),
    "pueyrredon": set(),
    "parametros": set(),
}

FUZZY_THRESHOLD = 82  # 0-100; por debajo no se acepta el match difuso


def resolve_columns(df_columns, doc_key: str) -> tuple[dict, list]:
    """
    Devuelve (mapeo, faltantes).
      mapeo:     {campo_lógico: nombre_real_en_df}
      faltantes: [campos_lógicos_no_encontrados_y_obligatorios]
    """
    schema = SCHEMAS[doc_key]
    optional = OPTIONAL_FIELDS.get(doc_key, set())

    norm_to_real = {}
    for col in df_columns:
        norm_to_real.setdefault(normalize(col), col)
    norm_cols = list(norm_to_real.keys())

    mapeo, faltantes = {}, []

    for field, candidates in schema.items():
        found = None
        # 1) match exacto normalizado
        for cand in candidates:
            ncand = normalize(cand)
            if ncand in norm_to_real:
                found = norm_to_real[ncand]
                break
        # 2) match por token contenido (p. ej. "VALOR" dentro de
        #    "VALOR PATAGONIA SUR UGLS 17-28-33")
        if found is None:
            for cand in candidates:
                ncand = normalize(cand)
                if len(ncand) < 4:
                    continue
                for ncol in norm_cols:
                    if f" {ncand} " in f" {ncol} ":
                        found = norm_to_real[ncol]
                        break
                if found is not None:
                    break
        # 3) match difuso si no hubo nada
        if found is None and norm_cols:
            best_score, best_col = 0, None
            for cand in candidates:
                match = process.extractOne(
                    normalize(cand), norm_cols, scorer=fuzz.ratio
                )
                if match and match[1] > best_score:
                    best_score, best_col = match[1], match[0]
            if best_col is not None and best_score >= FUZZY_THRESHOLD:
                found = norm_to_real[best_col]

        if found is not None:
            mapeo[field] = found
        elif field not in optional:
            faltantes.append(field)

    return mapeo, faltantes
