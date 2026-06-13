"""
app.py
------
Interfaz Streamlit para el pipeline "Ambulatorio INSSJP".

5 inputs:
  1. Prestaciones INSSJP (mensual, siempre se sube)
  2. Base usuarios_INSSJP        (referencia · puede vivir en la BD)
  3. Base Valores_INSSJP         (referencia · puede vivir en la BD)
  4. Atribución Clínica Pueyrredón (referencia · puede vivir en la BD)
  5. Parámetros resto de centros   (referencia · puede vivir en la BD)

1 output:
  Excel consolidado (hojas: Consolidado, Sin_Atribucion, Control).
"""

import io
import datetime as dt
import pandas as pd
import streamlit as st

from processor import ejecutar_pipeline
from db import DB

# ----------------------------------------------------------------------------- #
#  Configuración general
# ----------------------------------------------------------------------------- #
st.set_page_config(page_title="Ambulatorio INSSJP", page_icon="🔷", layout="wide")

AZUL        = "#2E6FBE"
AZUL_OSCURO = "#1E4E8C"
AZUL_CLARO  = "#EAF1FA"

st.markdown(f"""
<style>
    .stApp {{ background:#FFFFFF; }}
    h1, h2, h3, h4 {{ color:{AZUL_OSCURO}; font-weight:700; letter-spacing:-.01em; }}
    .block-container {{ padding-top:2.2rem; max-width:1150px; }}
    /* tarjetas */
    .card {{
        background:{AZUL_CLARO}; border:1px solid #D4E2F4; border-radius:12px;
        padding:1.1rem 1.3rem; margin-bottom:.6rem;
    }}
    .pill {{
        display:inline-block; padding:.15rem .6rem; border-radius:999px;
        font-size:.78rem; font-weight:600;
    }}
    .pill-ok  {{ background:#DCEBFB; color:{AZUL_OSCURO}; }}
    .pill-off {{ background:#F1F3F6; color:#6B7280; }}
    /* botones */
    .stButton>button, .stDownloadButton>button {{
        background:{AZUL}; color:#fff; border:none; border-radius:9px;
        font-weight:600; padding:.55rem 1.1rem;
    }}
    .stButton>button:hover, .stDownloadButton>button:hover {{ background:{AZUL_OSCURO}; }}
    /* métricas más nítidas */
    [data-testid="stMetricValue"] {{ color:{AZUL_OSCURO}; font-weight:700; }}
    [data-testid="stMetricLabel"] {{ color:#4B5563; }}
    .subtle {{ color:#5B6B7E; font-size:.9rem; }}
    hr {{ border-color:#E3EBF5; }}
</style>
""", unsafe_allow_html=True)

db = DB()

# ----------------------------------------------------------------------------- #
#  Helpers
# ----------------------------------------------------------------------------- #
def leer_excel(archivo):
    if archivo is None:
        return None
    nombre = archivo.name.lower()
    if nombre.endswith(".csv"):
        return pd.read_csv(archivo)
    return pd.read_excel(archivo)


def obtener_referencia(clave, archivo_subido, etiqueta):
    """Prioriza archivo recién subido; si no, usa el guardado en la BD."""
    if archivo_subido is not None:
        df = leer_excel(archivo_subido)
        db.guardar_referencia(clave, df, archivo_subido.name)
        return df, f"{etiqueta}: subido y guardado ({len(df)} filas)"
    df = db.cargar_referencia(clave)
    if df is not None:
        return df, f"{etiqueta}: cargado desde la base ({len(df)} filas)"
    return None, f"{etiqueta}: falta"


def exportar_excel(res) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as xl:
        res.consolidado.to_excel(xl, sheet_name="Consolidado", index=False)
        (res.sin_atribucion if not res.sin_atribucion.empty
         else pd.DataFrame({"Sin registros": []})).to_excel(
            xl, sheet_name="Sin_Atribucion", index=False)
        pd.DataFrame(
            [{"Concepto": k, "Valor": v} for k, v in res.control.items()]
        ).to_excel(xl, sheet_name="Control", index=False)
    return buffer.getvalue()


# ----------------------------------------------------------------------------- #
#  Sidebar — estado de la base y referencias
# ----------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown("### Base de datos")
    if db.activa:
        st.markdown('<span class="pill pill-ok">Railway · conectada</span>',
                    unsafe_allow_html=True)
        info = db.info_referencias()
        st.markdown("#### Referencias guardadas")
        nombres = {
            "usuarios": "Base usuarios",
            "valores": "Base valores",
            "pueyrredon": "Atrib. Pueyrredón",
            "parametros": "Parámetros centros",
        }
        for clave, etiqueta in nombres.items():
            if clave in info:
                m = info[clave]
                st.markdown(
                    f'<div class="card" style="padding:.6rem .8rem;margin-bottom:.4rem">'
                    f'<b>{etiqueta}</b><br><span class="subtle">'
                    f'{m["filas"]} filas · {m["actualizado"]:%Y-%m-%d %H:%M}</span></div>',
                    unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="subtle">{etiqueta}: —</div>',
                            unsafe_allow_html=True)
    else:
        st.markdown('<span class="pill pill-off">Modo sin estado</span>',
                    unsafe_allow_html=True)
        st.caption("Definí DATABASE_URL para persistir las tablas de referencia "
                   "y el historial.")

    if db.activa:
        st.markdown("---")
        st.markdown("#### Historial")
        h = db.historial(8)
        if not h.empty:
            st.dataframe(h[["Fecha", "Dif.", "Cuadra"]], hide_index=True,
                         use_container_width=True)
        else:
            st.caption("Sin corridas registradas.")


# ----------------------------------------------------------------------------- #
#  Encabezado
# ----------------------------------------------------------------------------- #
st.markdown(f"# Consolidación Ambulatorio · INSSJP")
st.markdown('<p class="subtle">Cruce de usuarios · valorización · atribución de '
            'centros · control de integridad.</p>', unsafe_allow_html=True)
st.markdown("<hr>", unsafe_allow_html=True)


# ----------------------------------------------------------------------------- #
#  Inputs
# ----------------------------------------------------------------------------- #
st.markdown("### 1 · Documento mensual de prestaciones")
f_prestaciones = st.file_uploader(
    "Excel de la página de INSSJP — detalle de prestaciones",
    type=["xlsx", "xls", "csv"], key="prest")

st.markdown("### 2 · Tablas de referencia")
st.caption("Si la base está conectada, podés dejarlas vacías para reutilizar las "
           "últimas guardadas. Subí un archivo solo cuando quieras actualizarlas.")

c1, c2 = st.columns(2)
with c1:
    f_usuarios = st.file_uploader("Base usuarios_INSSJP",
                                  type=["xlsx", "xls", "csv"], key="usu")
    f_pueyrredon = st.file_uploader("Atribución Clínica Pueyrredón (C1623)",
                                    type=["xlsx", "xls", "csv"], key="puey")
with c2:
    f_valores = st.file_uploader("Base Valores_INSSJP",
                                 type=["xlsx", "xls", "csv"], key="val")
    f_parametros = st.file_uploader("Parámetros resto de centros",
                                    type=["xlsx", "xls", "csv"], key="param")

st.markdown("<hr>", unsafe_allow_html=True)
ejecutar = st.button("▶  Ejecutar consolidación", type="primary")


# ----------------------------------------------------------------------------- #
#  Ejecución
# ----------------------------------------------------------------------------- #
if ejecutar:
    if f_prestaciones is None:
        st.error("Falta el documento mensual de prestaciones de INSSJP.")
        st.stop()

    prestaciones = leer_excel(f_prestaciones)

    usuarios,   m1 = obtener_referencia("usuarios",   f_usuarios,   "Usuarios")
    valores,    m2 = obtener_referencia("valores",    f_valores,    "Valores")
    pueyrredon, m3 = obtener_referencia("pueyrredon", f_pueyrredon, "Pueyrredón")
    parametros, m4 = obtener_referencia("parametros", f_parametros, "Parámetros")

    faltan = [m for m, df in
              [(m1, usuarios), (m2, valores), (m3, pueyrredon), (m4, parametros)]
              if df is None]
    if faltan:
        st.error("Faltan tablas de referencia (subilas o cargalas en la base):")
        for m in faltan:
            st.markdown(f"- {m}")
        st.stop()

    with st.spinner("Procesando las 4 fases…"):
        try:
            res = ejecutar_pipeline(prestaciones, usuarios, valores,
                                    pueyrredon, parametros)
        except Exception as e:
            st.error(f"Error durante el proceso: {e}")
            st.stop()

    db.registrar_corrida(f_prestaciones.name, res.control,
                         len(res.consolidado), len(res.sin_atribucion))

    # --- control de integridad ---
    st.markdown("### Resultado")
    ctrl = res.control
    a, b, c, d = st.columns(4)
    a.metric("Total original", f"${ctrl['total_original_valorizado']:,.2f}")
    b.metric("Total importado", f"${ctrl['total_importado']:,.2f}")
    c.metric("Sin atribución", f"${ctrl['total_sin_atribucion']:,.2f}")
    d.metric("Diferencia", f"${ctrl['diferencia']:,.2f}",
             delta="Cuadra ✓" if ctrl["cuadra"] else "Revisar ✗",
             delta_color="normal" if ctrl["cuadra"] else "inverse")

    if ctrl["cuadra"]:
        st.success("Control de integridad correcto: la salida cuadra con el "
                   "documento original valorizado.")
    else:
        st.warning("La salida no cuadra con el original. Revisá el reporte de "
                   "filas sin atribución.")

    # --- descarga ---
    fecha = dt.datetime.now().strftime("%Y%m%d_%H%M")
    st.download_button(
        "⬇  Descargar Excel consolidado",
        data=exportar_excel(res),
        file_name=f"consolidado_INSSJP_{fecha}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # --- detalle ---
    t1, t2, t3 = st.tabs(
        [f"Consolidado ({len(res.consolidado)})",
         f"Sin atribución ({len(res.sin_atribucion)})",
         "Trazas"])
    with t1:
        st.dataframe(res.consolidado, use_container_width=True, height=420)
    with t2:
        if res.sin_atribucion.empty:
            st.info("No quedaron filas sin atribución.")
        else:
            st.dataframe(res.sin_atribucion, use_container_width=True, height=420)
    with t3:
        for l in res.logs:
            st.markdown(f"- {l}")
