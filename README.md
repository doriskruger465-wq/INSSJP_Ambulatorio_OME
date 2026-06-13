# Consolidación Ambulatorio · INSSJP

App en **Streamlit** con base de datos **PostgreSQL en Railway** que ejecuta el
pipeline de consolidación de prestaciones de INSSJP (PAMI): cruce de usuarios,
valorización, atribución de centros y control de integridad.

---

## Inputs (5) y output (1)

| # | Documento | Rol |
|---|-----------|-----|
| 1 | Excel de prestaciones de INSSJP | Mensual — siempre se sube |
| 2 | Base usuarios_INSSJP | Referencia — puede vivir en la BD |
| 3 | Base Valores_INSSJP | Referencia — puede vivir en la BD |
| 4 | Atribución Clínica Pueyrredón | Referencia — puede vivir en la BD |
| 5 | Parámetros resto de centros | Referencia — puede vivir en la BD |

**Output:** `consolidado_INSSJP_<fecha>.xlsx` con tres hojas: `Consolidado`,
`Sin_Atribucion` y `Control`.

Las 4 tablas de referencia se guardan en PostgreSQL la primera vez que se suben.
En los meses siguientes alcanza con subir solo el documento de prestaciones; las
referencias se reutilizan desde la base (y se pueden actualizar subiéndolas de
nuevo en cualquier momento).

---

## Lógica del pipeline

**Fase 1 — Datos faltantes y valorización**
- Cruza `U.ACEPTO` con *Base usuarios* → agrega `CUENTA`, `NOMBRE DEL PROFESIONAL` y `TIPO`.
- Divide `PRÁCTICA` en el número y la `DESCRIPCION PRÁCTICA` (texto tras el guion medio).
- Cruza el número de práctica con *Base Valores* (`CÓDIGO DE PRÁCTICA`) → `Importe facturado`.
- Guarda el **total original valorizado** (referencia del control final).

**Fase 2 — Atribución de centros**
- `Tipo = P` → pasa directo al consolidado con su cuenta e importe completo.
- `Tipo = C` → se abre en porciones %P / %C:
  - **Clínica Pueyrredón** (`cuenta = C1623`): match por `NRO. ORDEN`.
  - **Resto de centros** (`cuenta ≠ C1623`): match por clave `Cuenta_Práctica`.
  - Cada fila genera hasta dos: importe × %P (→ `CUENTA P`) e importe × %C (→ `CUENTA C`),
    con `CUENTA ASIGNADA` e `IMPORTE FACTURADO A IMPORTAR`.

**Fase 3 — Codigo_Debitos**
- Columna `Codigo_Debitos = NRO. BENEFICIO/GP + PRÁCTICA`.

**Fase 4 — Control de integridad**
- `total_importado + total_sin_atribucion` debe igualar `total_original_valorizado`.
- Las filas `Tipo C` sin coincidencia van a la hoja `Sin_Atribucion` con estatus
  **"Atribución no encontrada"** (no se descartan en silencio).

El reconocimiento de encabezados es tolerante a acentos, mayúsculas, puntos y
espacios, con respaldo por similitud difusa (`rapidfuzz`), así que los nombres de
columna no tienen que coincidir carácter por carácter.

---

## Despliegue en Railway

1. Subí el repo a GitHub y en Railway: **New Project → Deploy from GitHub repo**.
2. Agregá el plugin **PostgreSQL** (`New → Database → PostgreSQL`). Railway crea
   la variable `DATABASE_URL` y la inyecta automáticamente; el código la normaliza
   (`postgres://` → `postgresql://`) y crea las tablas en el primer arranque.
3. Railway detecta `requirements.txt` y `Procfile`/`railway.json` y levanta el
   `startCommand` con `$PORT`. No hace falta configurar nada más.

Sin `DATABASE_URL` la app corre igual en **modo sin estado** (se suben los 5
archivos en cada ejecución).

### Local

```bash
pip install -r requirements.txt
cp .env.example .env          # opcional: completá DATABASE_URL para persistir
streamlit run app.py
```

---

## Estructura

```
app.py             UI Streamlit (diseño azul minimalista)
processor.py       Pipeline de 4 fases
column_mapping.py  Normalización y resolución difusa de encabezados
db.py              PostgreSQL (referencias + historial de corridas)
.streamlit/config.toml   Tema azul
Procfile / railway.json  Arranque en Railway
test_pipeline.py   Prueba con datos sintéticos
```
