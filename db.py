"""
db.py
-----
Persistencia opcional en PostgreSQL (Railway).

Guarda las 4 tablas de referencia (usuarios, valores, atribución Pueyrredón,
parámetros resto de centros) para no tener que volver a subirlas cada mes, y
un historial de corridas con sus totales de control.

Si no hay DATABASE_URL, la app funciona igual en modo "sin estado": se suben
los 5 archivos en cada ejecución.
"""

from __future__ import annotations
import os
import json
import datetime as dt
import pandas as pd

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, Float, Boolean
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


# ----------------------------------------------------------------------------- #
#  Modelos
# ----------------------------------------------------------------------------- #
class TablaReferencia(Base):
    """Una fila por cada tabla de referencia (clave = nombre lógico)."""
    __tablename__ = "ref_tablas"
    clave        = Column(String(40), primary_key=True)   # usuarios | valores | ...
    nombre_archivo = Column(String(255))
    filas        = Column(Integer)
    actualizado  = Column(DateTime, default=dt.datetime.utcnow)
    datos_json   = Column(Text)                           # DataFrame orient='split'


class Corrida(Base):
    """Historial de ejecuciones del pipeline."""
    __tablename__ = "corridas"
    id                 = Column(Integer, primary_key=True, autoincrement=True)
    creado             = Column(DateTime, default=dt.datetime.utcnow)
    archivo_prestaciones = Column(String(255))
    total_original     = Column(Float)
    total_importado    = Column(Float)
    total_sin_atrib    = Column(Float)
    diferencia         = Column(Float)
    cuadra             = Column(Boolean)
    n_consolidado      = Column(Integer)
    n_sin_atribucion   = Column(Integer)


# ----------------------------------------------------------------------------- #
#  Conexión
# ----------------------------------------------------------------------------- #
def _normalizar_url(url: str) -> str:
    # Railway entrega 'postgres://'; SQLAlchemy requiere 'postgresql://'
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


class DB:
    def __init__(self, url: str | None = None):
        url = url or os.getenv("DATABASE_URL")
        self.activa = bool(url)
        if self.activa:
            self.engine = create_engine(_normalizar_url(url), pool_pre_ping=True)
            Base.metadata.create_all(self.engine)
            self.Session = sessionmaker(bind=self.engine)

    # --- tablas de referencia ---
    def guardar_referencia(self, clave: str, df: pd.DataFrame, nombre_archivo: str):
        if not self.activa:
            return
        payload = df.to_json(orient="split", force_ascii=False)
        with self.Session() as s:
            obj = s.get(TablaReferencia, clave) or TablaReferencia(clave=clave)
            obj.nombre_archivo = nombre_archivo
            obj.filas = len(df)
            obj.actualizado = dt.datetime.utcnow()
            obj.datos_json = payload
            s.merge(obj)
            s.commit()

    def cargar_referencia(self, clave: str) -> pd.DataFrame | None:
        if not self.activa:
            return None
        with self.Session() as s:
            obj = s.get(TablaReferencia, clave)
            if not obj:
                return None
            return pd.read_json(obj.datos_json, orient="split")

    def info_referencias(self) -> dict:
        """Metadatos de cada tabla guardada para mostrar en la UI."""
        if not self.activa:
            return {}
        with self.Session() as s:
            return {
                o.clave: {
                    "archivo": o.nombre_archivo,
                    "filas": o.filas,
                    "actualizado": o.actualizado,
                }
                for o in s.query(TablaReferencia).all()
            }

    # --- historial ---
    def registrar_corrida(self, archivo, control, n_cons, n_sin):
        if not self.activa:
            return
        with self.Session() as s:
            s.add(Corrida(
                archivo_prestaciones=archivo,
                total_original=control.get("total_original_valorizado"),
                total_importado=control.get("total_importado"),
                total_sin_atrib=control.get("total_sin_atribucion"),
                diferencia=control.get("diferencia"),
                cuadra=control.get("cuadra"),
                n_consolidado=n_cons,
                n_sin_atribucion=n_sin,
            ))
            s.commit()

    def historial(self, limite: int = 20) -> pd.DataFrame:
        if not self.activa:
            return pd.DataFrame()
        with self.Session() as s:
            filas = (
                s.query(Corrida).order_by(Corrida.creado.desc()).limit(limite).all()
            )
            return pd.DataFrame([{
                "Fecha": f.creado.strftime("%Y-%m-%d %H:%M"),
                "Archivo": f.archivo_prestaciones,
                "Original": f.total_original,
                "Importado": f.total_importado,
                "Sin atrib.": f.total_sin_atrib,
                "Dif.": f.diferencia,
                "Cuadra": "✓" if f.cuadra else "✗",
                "Filas": f.n_consolidado,
            } for f in filas])
