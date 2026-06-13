import pandas as pd
from processor import ejecutar_pipeline

# --- 1) Prestaciones (origen INSSJP) ---
prestaciones = pd.DataFrame({
    "U.ACEPTO":          ["A001", "A002", "A003", "A004", "A005"],
    "PRÁCTICA":          ["420101 - Consulta médica", "330200 - Radiografía simple",
                          "420101 - Consulta médica", "990000 - Práctica inexistente",
                          "330200 - Radiografía simple"],
    "NRO. ORDEN":        ["O-100", "O-101", "O-102", "O-103", "O-104"],
    "NRO. BENEFICIO/GP": ["B1", "B2", "B3", "B4", "B5"],
})

# --- 2) Base usuarios ---
usuarios = pd.DataFrame({
    "U.ACEPTO":             ["A001", "A002", "A003", "A004", "A005"],
    "CUENTA":               ["P900", "C1623", "C2000", "C1623", "P900"],
    "NOMBRE DEL PROFESIONAL":["Dr. Pérez", "Clínica Pueyrredón", "Centro Sur",
                              "Clínica Pueyrredón", "Dr. Pérez"],
    "TIPO":                 ["P", "C", "C", "C", "P"],
})

# --- 3) Base valores ---
valores = pd.DataFrame({
    "CÓDIGO DE PRÁCTICA": ["420101", "330200"],
    "VALOR":              [1000.0, 2000.0],
})

# --- 4) Atribución Clínica Pueyrredón (match por NRO. ORDEN) ---
pueyrredon = pd.DataFrame({
    "NRO. ORDEN": ["O-101", "O-103"],
    "%P":         [60, 70],
    "CUENTA P":   ["P-PUEY-PROF", "P-PUEY-PROF"],
    "%C":         [40, 30],
    "CUENTA C":   ["C-PUEY-INST", "C-PUEY-INST"],
})

# --- 5) Parámetros resto de centros (match por Cuenta_Práctica) ---
parametros = pd.DataFrame({
    "CUENTA_PRÁCTICA": ["C2000_330200"],
    "%P":              [50],
    "CUENTA P":        ["P-SUR-PROF"],
    "%C":              [50],
    "CUENTA C":        ["C-SUR-INST"],
})
# Nota: A003 (cuenta C2000, práctica 420101) NO está en parámetros -> sin atribución.

res = ejecutar_pipeline(prestaciones, usuarios, valores, pueyrredon, parametros)

print("\n===== LOGS =====")
for l in res.logs:
    print(" -", l)

print("\n===== CONSOLIDADO =====")
cols = ["U.ACEPTO", "PRÁCTICA_NUM", "TIPO", "CUENTA", "Importe facturado",
        "CUENTA ASIGNADA", "IMPORTE FACTURADO A IMPORTAR", "ORIGEN ATRIBUCION",
        "Codigo_Debitos"]
print(res.consolidado[[c for c in cols if c in res.consolidado.columns]].to_string(index=False))

print("\n===== SIN ATRIBUCIÓN =====")
print(res.sin_atribucion.to_string(index=False) if not res.sin_atribucion.empty else "(vacío)")

print("\n===== CONTROL =====")
for k, v in res.control.items():
    print(f"  {k}: {v}")
