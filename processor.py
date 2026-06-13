"""
processor.py
------------
Implementa el pipeline del prompt "Ambulatorio INSSJP" en 4 fases:

  FASE 1  Cruce de usuarios + split de PRÁCTICA + valorización.
  FASE 2  Atribución de centros Tipo "C":
            - Clínica Pueyrredón (cuenta C1623)  -> match por NRO. ORDEN
            - Resto de centros (cuenta != C1623) -> match por Cuenta_Práctica
          Apertura de cada fila en porción %P y porción %C.
  FASE 3  Columna Codigo_Debitos = NRO. BENEFICIO/GP + PRÁCTICA.
  FASE 4  Control de integridad y reporte de "Atribución no encontrada".

Diseñado para no descartar filas en silencio: todo lo que no atribuye queda
en un reporte aparte con su estatus.
"""

from __future__ import annotations
import pandas as pd
import numpy as np
from dataclasses import dataclass, field

from column_mapping import resolve_columns, normalize

CUENTA_PUEYRREDON = "C1623"


# ----------------------------------------------------------------------------- #
#  Resultado del pipeline
# ----------------------------------------------------------------------------- #
@dataclass
class ResultadoPipeline:
    consolidado: pd.DataFrame                       # salida principal
    sin_atribucion: pd.DataFrame                    # reporte aparte
    control: dict                                   # totales de integridad
    logs: list = field(default_factory=list)        # trazas legibles

    def log(self, msg: str):
        self.logs.append(msg)


# ----------------------------------------------------------------------------- #
#  Utilidades
# ----------------------------------------------------------------------------- #
def _pct(x) -> float:
    """Normaliza un porcentaje a fracción 0-1. Acepta 50, '50%', 0.5, '0,5'."""
    if pd.isna(x):
        return np.nan
    if isinstance(x, str):
        x = x.replace("%", "").replace(",", ".").strip()
        if x == "":
            return np.nan
    try:
        v = float(x)
    except (TypeError, ValueError):
        return np.nan
    return v / 100.0 if v > 1 else v


def _codigo(x) -> str:
    """Limpia un código a string entero: 607137.0 -> '607137', 'SU12' -> 'SU12'."""
    if pd.isna(x):
        return ""
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    s = str(x).strip()
    import re as _re
    if _re.fullmatch(r"\d+\.0+", s):
        s = s.split(".")[0]
    return s


def _clave_cuenta_practica(cuenta, practica_num) -> str:
    return f"{normalize(cuenta)}_{_codigo(practica_num)}"


def _split_practica(serie: pd.Series):
    """Separa 'PRÁCTICA' en (número, descripción) usando el primer guion medio."""
    num, desc = [], []
    for val in serie.fillna("").astype(str):
        if "-" in val:
            izq, der = val.split("-", 1)
        else:
            izq, der = val, ""
        num.append(izq.strip())
        desc.append(der.strip())
    return pd.Series(num, index=serie.index), pd.Series(desc, index=serie.index)


# ----------------------------------------------------------------------------- #
#  FASE 1
# ----------------------------------------------------------------------------- #
def fase1(prestaciones, usuarios, valores, res: ResultadoPipeline):
    mp, falt = resolve_columns(prestaciones.columns, "prestaciones")
    mu, faltu = resolve_columns(usuarios.columns, "usuarios")
    mv, faltv = resolve_columns(valores.columns, "valores")
    for nombre, falta in [("Prestaciones", falt), ("Usuarios", faltu), ("Valores", faltv)]:
        if falta:
            raise ValueError(f"En el archivo de {nombre} faltan columnas: {falta}")

    df = prestaciones.copy()

    # 1.a  Cruce con base de usuarios por U.ACEPTO -> cuenta, profesional, tipo
    u = usuarios[[mu["u_acepto"], mu["cuenta"], mu["nombre_profesional"], mu["tipo"]]].copy()
    u.columns = ["_uacepto_key", "CUENTA", "NOMBRE DEL PROFESIONAL", "TIPO"]
    u["_uacepto_key"] = u["_uacepto_key"].map(normalize)
    u = u.drop_duplicates("_uacepto_key")

    df["_uacepto_key"] = df[mp["u_acepto"]].map(normalize)
    df = df.merge(u, on="_uacepto_key", how="left")
    sin_usuario = df["CUENTA"].isna().sum()
    res.log(f"Fase 1 · cruce usuarios: {len(df)} filas, {sin_usuario} sin equivalencia U.ACEPTO.")

    # 1.b  Split de PRÁCTICA
    df["PRÁCTICA_NUM"], df["DESCRIPCION PRÁCTICA"] = _split_practica(df[mp["practica"]])

    # 1.c  Valorización contra Base_Valores
    v = valores[[mv["codigo_practica"], mv["valor"]]].copy()
    v.columns = ["_cod_key", "Importe facturado"]
    v["_cod_key"] = v["_cod_key"].map(_codigo)
    v = v.drop_duplicates("_cod_key")
    df["_cod_key"] = df["PRÁCTICA_NUM"].map(_codigo)
    df = df.merge(v, on="_cod_key", how="left")
    df["Importe facturado"] = df["Importe facturado"].round(2)
    sin_valor = df["Importe facturado"].isna().sum()
    res.log(f"Fase 1 · valorización: {sin_valor} prácticas sin valor en Base_Valores.")

    # total original valorizado (antes de cualquier atribución)
    res.control["total_original_valorizado"] = float(
        df["Importe facturado"].fillna(0).sum()
    )

    df.drop(columns=["_uacepto_key", "_cod_key"], inplace=True, errors="ignore")
    return df, mp


def construir_fila_salida(fila, cuenta_asignada, importe_importar, origen):
    """Genera un dict de fila para el consolidado conservando datos de origen."""
    d = fila.to_dict()
    d["CUENTA ASIGNADA"] = cuenta_asignada
    d["IMPORTE FACTURADO A IMPORTAR"] = importe_importar
    d["ORIGEN ATRIBUCION"] = origen
    return d


# ----------------------------------------------------------------------------- #
#  FASE 2 — atribución
# ----------------------------------------------------------------------------- #
def _aperturar(fila, pct_p, cuenta_p, pct_c, cuenta_c, origen):
    """Devuelve 1-2 filas abiertas según los porcentajes presentes.

    Cuando %P + %C = 100%, la porción C se calcula por resto para que ambas
    sumen exactamente el importe original (sin deriva de redondeo)."""
    base = round(float(fila.get("Importe facturado") or 0), 2)
    has_p = (not pd.isna(pct_p)) and pct_p > 0
    has_c = (not pd.isna(pct_c)) and pct_c > 0
    filas = []
    if has_p and has_c:
        p_amt = round(base * pct_p, 2)
        if abs((pct_p + pct_c) - 1.0) <= 1e-4:
            c_amt = round(base - p_amt, 2)        # resto → suma exacta
        else:
            c_amt = round(base * pct_c, 2)        # %s no suman 100% → se respeta tal cual
        filas.append(construir_fila_salida(fila, cuenta_p, p_amt, origen))
        filas.append(construir_fila_salida(fila, cuenta_c, c_amt, origen))
    elif has_p:
        filas.append(construir_fila_salida(fila, cuenta_p, base, origen))
    elif has_c:
        filas.append(construir_fila_salida(fila, cuenta_c, base, origen))
    return filas


def fase2(df, pueyrredon, parametros, res: ResultadoPipeline):
    mpu, faltpu = resolve_columns(pueyrredon.columns, "pueyrredon")
    mpa, faltpa = resolve_columns(parametros.columns, "parametros")
    if faltpu:
        raise ValueError(f"En Atribución Clínica Pueyrredón faltan columnas: {faltpu}")
    if faltpa:
        raise ValueError(f"En Parámetros resto de centros faltan columnas: {faltpa}")

    # --- Tipo P: pasan directo al consolidado (cuenta propia, importe completo) ---
    es_p = df["TIPO"].map(normalize) == "P"
    filas_p = [
        construir_fila_salida(f, f.get("CUENTA"), f.get("Importe facturado"), "Tipo P directo")
        for _, f in df[es_p].iterrows()
    ]
    res.log(f"Fase 2 · Tipo P: {len(filas_p)} filas trasladadas directo.")

    # --- Tipo C: requieren atribución ---
    es_c = df["TIPO"].map(normalize) == "C"
    df_c = df[es_c].copy()

    # --- Filas sin tipo P/C (U.ACEPTO sin equivalencia en usuarios) ---
    es_otro = ~(es_p | es_c)
    sin_tipo = []
    for _, f in df[es_otro].iterrows():
        d = f.to_dict()
        d["ESTATUS"] = "Tipo no identificado / U.ACEPTO sin equivalencia"
        d["CAMINO"] = "—"
        d["CLAVE BUSCADA"] = ""
        d["DIAGNÓSTICO"] = "U.ACEPTO sin equivalencia en Base usuarios"
        sin_tipo.append(d)
    if sin_tipo:
        res.log(f"Fase 2 · {len(sin_tipo)} filas sin TIPO P/C → reporte aparte.")

    # Índice de Pueyrredón por NRO. ORDEN
    pu = pueyrredon.copy()
    pu["_orden_key"] = pu[mpu["nro_orden"]].map(_codigo)
    pu = pu.drop_duplicates("_orden_key").set_index("_orden_key")

    # Índice de Parámetros por clave Cuenta + Cod practica
    pa = parametros.copy()
    pa["_clave"] = pa.apply(
        lambda r: _clave_cuenta_practica(r[mpa["cuenta"]], r[mpa["cod_practica"]]),
        axis=1,
    )
    pa = pa.drop_duplicates("_clave").set_index("_clave")

    # conjuntos para diagnosticar por qué una clave no cruza en resto de centros
    cuentas_param = {k.split("_", 1)[0] for k in pa.index}
    practs_param = {k.split("_", 1)[1] for k in pa.index if "_" in k}

    filas_c, sin_atrib = [], []

    for _, fila in df_c.iterrows():
        cuenta = normalize(fila.get("CUENTA"))
        es_puey = cuenta == normalize(CUENTA_PUEYRREDON)
        if es_puey:
            key = _codigo(fila.get("nro_orden_src"))
            tabla, idx, origen = pu, key, "Pueyrredón (NRO. ORDEN)"
            mref = mpu
        else:
            key = _clave_cuenta_practica(fila.get("CUENTA"), fila.get("PRÁCTICA_NUM"))
            tabla, idx, origen = pa, key, "Resto centros (Cuenta + PRÁCTICA)"
            mref = mpa

        if idx in tabla.index:
            ref = tabla.loc[idx]
            pct_p = _pct(ref[mref["pct_p"]])
            pct_c = _pct(ref[mref["pct_c"]])
            cuenta_p = ref[mref["cuenta_p"]]
            cuenta_c = ref[mref["cuenta_c"]]
            nuevas = _aperturar(fila, pct_p, cuenta_p, pct_c, cuenta_c, origen)
            if nuevas:
                filas_c.extend(nuevas)
            else:
                d = fila.to_dict()
                d["ESTATUS"] = "Atribución no encontrada"
                d["CAMINO"] = origen
                d["CLAVE BUSCADA"] = key
                d["DIAGNÓSTICO"] = "Coincide la clave pero sin %P/%C cargados"
                sin_atrib.append(d)
        else:
            d = fila.to_dict()
            d["ESTATUS"] = "Atribución no encontrada"
            d["CAMINO"] = origen
            d["CLAVE BUSCADA"] = key
            if es_puey:
                d["DIAGNÓSTICO"] = "NRO. ORDEN no está en Atribución Pueyrredón"
            else:
                cu = cuenta
                pr = _codigo(fila.get("PRÁCTICA_NUM"))
                if cu not in cuentas_param:
                    d["DIAGNÓSTICO"] = "Cuenta no está en Parámetros"
                elif pr not in practs_param:
                    d["DIAGNÓSTICO"] = "Práctica no está en Parámetros"
                else:
                    d["DIAGNÓSTICO"] = "Cuenta y práctica existen pero NO juntas"
            sin_atrib.append(d)

    res.log(f"Fase 2 · Tipo C: {len(filas_c)} filas abiertas, "
            f"{len(sin_atrib)} sin atribución.")

    consolidado = pd.DataFrame(filas_p + filas_c)
    sin_atribucion = pd.DataFrame(sin_atrib + sin_tipo)
    return consolidado, sin_atribucion


# ----------------------------------------------------------------------------- #
#  FASE 3 — Codigo_Debitos
# ----------------------------------------------------------------------------- #
def fase3(consolidado, mp, res: ResultadoPipeline):
    col_ben = mp.get("nro_beneficio")
    if col_ben and col_ben in consolidado.columns:
        consolidado["Codigo_Debitos"] = (
            consolidado[col_ben].astype(str).str.strip()
            + consolidado["PRÁCTICA_NUM"].astype(str).str.strip()
        )
        res.log("Fase 3 · Codigo_Debitos generado (NRO. BENEFICIO/GP + PRÁCTICA).")
    else:
        consolidado["Codigo_Debitos"] = ""
        res.log("Fase 3 · sin columna NRO. BENEFICIO/GP; Codigo_Debitos quedó vacío.")
    return consolidado


# ----------------------------------------------------------------------------- #
#  FASE 4 — control de integridad
# ----------------------------------------------------------------------------- #
def fase4(consolidado, sin_atribucion, res: ResultadoPipeline):
    total_importado = float(
        consolidado.get("IMPORTE FACTURADO A IMPORTAR", pd.Series(dtype=float)).fillna(0).sum()
    )
    total_sin = float(
        sin_atribucion.get("Importe facturado", pd.Series(dtype=float)).fillna(0).sum()
    ) if not sin_atribucion.empty else 0.0

    original = res.control.get("total_original_valorizado", 0.0)
    res.control.update({
        "total_importado": round(total_importado, 2),
        "total_sin_atribucion": round(total_sin, 2),
        "total_original_valorizado": round(original, 2),
        "diferencia": round(original - (total_importado + total_sin), 2),
        "cuadra": abs(original - (total_importado + total_sin)) < 0.01,
    })
    estado = "OK ✓" if res.control["cuadra"] else "REVISAR ✗"
    res.log(f"Fase 4 · control: original={original:,.2f} | importado={total_importado:,.2f} "
            f"| sin atribución={total_sin:,.2f} | {estado}")
    return res


# ----------------------------------------------------------------------------- #
#  Orquestador
# ----------------------------------------------------------------------------- #
def ejecutar_pipeline(prestaciones, usuarios, valores, pueyrredon, parametros) -> ResultadoPipeline:
    res = ResultadoPipeline(
        consolidado=pd.DataFrame(), sin_atribucion=pd.DataFrame(), control={}
    )
    df, mp = fase1(prestaciones, usuarios, valores, res)

    # conservar NRO. ORDEN del origen con nombre estable para Fase 2
    if "nro_orden" in mp:
        df["nro_orden_src"] = df[mp["nro_orden"]]
    else:
        df["nro_orden_src"] = ""

    consolidado, sin_atribucion = fase2(df, pueyrredon, parametros, res)
    consolidado = fase3(consolidado, mp, res)
    fase4(consolidado, sin_atribucion, res)

    # limpiar columnas auxiliares de la salida
    consolidado = consolidado.drop(columns=["nro_orden_src"], errors="ignore")
    res.consolidado = consolidado
    res.sin_atribucion = sin_atribucion
    return res
