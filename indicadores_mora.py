"""Dashboard de Indicadores de Mora (cobranza / recuperación de cartera)."""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

COLORS = {
    "primary": "#1a3c6e", "accent": "#3b82f6", "success": "#10b981",
    "warning": "#f59e0b", "danger": "#ef4444", "purple": "#8b5cf6",
    "teal": "#06b6d4", "orange": "#f97316", "muted": "#94a3b8",
    "bg": "#ffffff", "grid": "#e5e7eb", "text": "#374151",
}
PLOTLY_LAYOUT = dict(
    paper_bgcolor=COLORS["bg"], plot_bgcolor="#f9fafb",
    font=dict(color=COLORS["text"], family="Inter, sans-serif", size=12),
    margin=dict(l=40, r=20, t=50, b=60), hovermode="x unified",
)
_AXIS_DEFAULTS = dict(gridcolor=COLORS["grid"], zeroline=False, showline=False)

INDICADORES_CSS = """
<style>
.chart-card { background:#fff; border:1px solid #e5e9f0; border-radius:14px;
  padding:1rem 1.2rem 0.5rem; box-shadow:0 2px 8px rgba(26,60,110,0.06);
  margin-bottom:1rem; transition:box-shadow .25s ease; }
.chart-card:hover { box-shadow:0 6px 24px rgba(26,60,110,0.13); }
.kpi-banner { background:linear-gradient(135deg,#1a3c6e 0%,#2563eb 100%);
  border-radius:14px; padding:1.2rem 1.8rem; color:#fff; margin-bottom:1.2rem; }
.kpi-banner h1 { color:#fff !important; font-size:1.4rem; margin:0; }
.kpi-banner p  { color:rgba(255,255,255,.75); margin:.2rem 0 0; font-size:.85rem; }
</style>
"""


def fmt_currency(val: float) -> str:
    if val >= 1_000_000:
        return f"${val/1_000_000:.2f}M"
    elif val >= 1_000:
        return f"${val/1_000:.1f}K"
    return f"${val:,.2f}"


_BOOL_COL_PATTERNS = ("si/no", "si_no", "sino", " si ", " no ", "s/n")


def _find_col(df: pd.DataFrame, candidates: list, skip_bool: bool = False) -> str | None:
    lower_cols = {c.lower(): c for c in df.columns}

    def _is_bool_col(key: str) -> bool:
        return skip_bool and any(p in key for p in _BOOL_COL_PATTERNS)

    # 1. Exact match
    for cand in candidates:
        if cand in lower_cols and not _is_bool_col(cand):
            return lower_cols[cand]
    # 2. Starts-with match
    for cand in candidates:
        for key, real in lower_cols.items():
            if key.startswith(cand) and not _is_bool_col(key):
                return real
    # 3. Substring match
    for cand in candidates:
        for key, real in lower_cols.items():
            if cand in key and not _is_bool_col(key):
                return real
    return None


def read_excel_safe(file) -> pd.DataFrame:
    xl = pd.ExcelFile(file)
    if len(xl.sheet_names) == 1:
        df = xl.parse(xl.sheet_names[0])
    else:
        best, best_rows = xl.sheet_names[0], 0
        for sheet in xl.sheet_names:
            try:
                tmp = xl.parse(sheet)
                if len(tmp) > best_rows:
                    best, best_rows = sheet, len(tmp)
            except Exception:
                pass
        df = xl.parse(best)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _color_pct(v: float) -> str:
    if v >= 70:
        return COLORS["success"]
    elif v >= 40:
        return COLORS["warning"]
    return COLORS["danger"]


def _chart_card(fig):
    st.markdown("<div class='chart-card'>", unsafe_allow_html=True)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown("</div>", unsafe_allow_html=True)


def _banner(icon: str, title: str, subtitle: str):
    st.markdown(
        f"<div class='kpi-banner'><h1>{icon} {title}</h1><p>{subtitle}</p></div>",
        unsafe_allow_html=True,
    )


COLUMN_CANDIDATES = {
    "campania": ["campaniasaldo", "campaña de trab", "campania", "campaña", "anio"],
    "division": ["division", "división"],
    "ruta": ["ruta"],
    "zona": ["zona"],
    "region": ["region", "región"],
    "no_dama": ["nodama", "dama"],
    "segmento": ["morosidad", "mora", "segmento"],
    "saldo": ["saldodama", "saldo"],
    "pago": ["montopago", "pagomonto", "importe pago", "monto cobrado", "cobrado", "recuperado", "pago"],
    "visita": ["vistas gestor", "visitas gestor", "gestion", "visita"],
    "promesa": ["dictaminacion de llamada", "dictam llamada", "dictaminacion llamada"],
    "contacto": ["estatus de llamada", "estatus llamada", "estatusllamada"],
    "dictaminacion": ["dictaminacion", "dictam"],
    "situacion": ["descsituacion", "situacion", "estatus"],
}

COLUMN_LABELS = {
    "campania": "Campaña",
    "division": "División",
    "ruta": "Ruta",
    "zona": "Zona",
    "region": "Región",
    "no_dama": "Número de Dama",
    "segmento": "Segmento Mora",
    "saldo": "Saldo Asignado",
    "pago": "Pago Aplicado",
    "visita": "Visita / Resultado",
    "promesa": "Promesas (Dictam. Llamada)",
    "contacto": "Contacto Efectivo (Estatus)",
    "dictaminacion": "Dictaminación",
    "situacion": "Situación",
}

NINGUNA = "(ninguna)"


def _detect_columns(df: pd.DataFrame) -> dict:
    result = {}
    for key, cands in COLUMN_CANDIDATES.items():
        result[key] = _find_col(df, cands, skip_bool=(key == "pago"))
    return result


def _column_picker(df: pd.DataFrame, detected: dict) -> dict:
    cols = dict(detected)
    options = [NINGUNA] + list(df.columns)
    with st.expander("⚙️ Ajustar columnas — Cartera General"):
        keys = list(COLUMN_CANDIDATES.keys())
        grid_cols = st.columns(4)
        for i, key in enumerate(keys):
            target = grid_cols[i % 4]
            current = cols.get(key)
            index = options.index(current) if current in options else 0
            picked = target.selectbox(COLUMN_LABELS[key], options, index=index, key=f"ind_col_{key}")
            cols[key] = None if picked == NINGUNA else picked
    return cols


def _grp(df: pd.DataFrame, col_key: str, cols: dict, top_n: int | None = None) -> pd.DataFrame | None:
    col = cols.get(col_key)
    if not col or col not in df.columns:
        return None
    agg = {"Cuentas": (col, "count"), "Asignado": ("__saldo__", "sum")}
    if cols.get("pago") and "__pago__" in df.columns:
        agg["Pagado"] = ("__pago__", "sum")
    g = df.groupby(col).agg(**agg).reset_index().rename(columns={col: col_key})
    if "Pagado" in g.columns:
        g["PctRec"] = np.where(g["Asignado"] > 0, g["Pagado"] / g["Asignado"] * 100, 0)
    else:
        g["Pagado"] = 0
        g["PctRec"] = 0
    if top_n:
        g = g.sort_values("Cuentas", ascending=False).head(top_n)
    return g


def _derive_estatus(df: pd.DataFrame, cols: dict) -> pd.Series:
    visita = df[cols["visita"]].astype(str).str.upper() if cols.get("visita") else pd.Series([""] * len(df))
    dictam = df[cols["dictaminacion"]].astype(str) if cols.get("dictaminacion") else pd.Series([""] * len(df))

    if not cols.get("pago"):
        if cols.get("situacion") and cols["situacion"] in df.columns:
            return df[cols["situacion"]].astype(str)
        return pd.Series(["Sin Gestión"] * len(df))

    pago = df["__pago__"]
    conditions = [
        pago > 0,
        visita.str.contains("PROMESA", na=False),
        visita.str.contains("PAGO", na=False),
        visita.str.strip().replace("NAN", "") != "",
        dictam.astype(str).str.strip().replace("nan", "") != "",
    ]
    choices = [
        "Recuperada",
        "Promesa de Pago",
        "Pago Cobrador/Porteador",
        "Gestionada - Visita",
        "Gestionada - Llamada",
    ]
    return pd.Series(np.select(conditions, choices, default="Sin Gestión"), index=df.index)


def tab_indicadores(df: pd.DataFrame):
    detected = _detect_columns(df)
    cols = _column_picker(df, detected)

    def _to_num(series):
        return pd.to_numeric(
            series.astype(str).str.replace(r"[$,\s]", "", regex=True).str.replace("nan", ""),
            errors="coerce",
        ).fillna(0)

    df = df.copy()
    df["__saldo__"] = _to_num(df[cols["saldo"]]) if cols.get("saldo") else 0.0
    if cols.get("pago"):
        df["__pago__"] = _to_num(df[cols["pago"]])

    with st.expander("🔍 Debug columnas detectadas", expanded=False):
        st.write("**Columnas mapeadas:**", cols)
        if cols.get("pago"):
            st.write(f"**Pago** (`{cols['pago']}`) — muestra:", df[cols["pago"]].dropna().head(10).tolist())
            st.write(f"**Pago sum numérico:**", _to_num(df[cols["pago"]]).sum())
            st.write(f"**__pago__ en df:**", "__pago__" in df.columns)
            if "__pago__" in df.columns:
                st.write(f"**__pago__ sum:**", df["__pago__"].sum())
        if cols.get("visita"):
            st.write(f"**Visita** (`{cols['visita']}`) — value_counts:")
            st.dataframe(df[cols["visita"]].fillna("(vacío)").value_counts().head(20).reset_index())
        if cols.get("contacto"):
            st.write(f"**Contacto** (`{cols['contacto']}`) — value_counts:")
            st.dataframe(df[cols["contacto"]].fillna("(vacío)").value_counts().head(20).reset_index())

    total_cuentas = len(df)
    saldo_asignado = df["__saldo__"].sum()
    saldo_recuperado = df["__pago__"].sum() if cols.get("pago") else 0.0
    pct_recuperacion = (saldo_recuperado / saldo_asignado * 100) if saldo_asignado > 0 else 0.0

    cuentas_recuperadas = int((df["__pago__"] > 0).sum()) if cols.get("pago") else 0
    pct_cuentas_rec = (cuentas_recuperadas / total_cuentas * 100) if total_cuentas else 0.0

    visita_col = cols.get("visita")
    if visita_col:
        _vis_raw = df[visita_col]
        _vis_str = _vis_raw.fillna("").astype(str).str.strip()
        visitas_realizadas = int(
            (_vis_raw.notna() & (_vis_str != "") & (_vis_str.str.lower() != "nan")).sum()
        )
    else:
        visitas_realizadas = 0
    pct_visitas = (visitas_realizadas / total_cuentas * 100) if total_cuentas else 0.0

    promesa_col = cols.get("promesa") or cols.get("dictaminacion")
    promesas = int(
        df[promesa_col].astype(str).str.upper().str.contains("PROMESA", na=False).sum()
    ) if promesa_col else 0
    pct_promesas = (promesas / total_cuentas * 100) if total_cuentas else 0.0

    contacto_col = cols.get("contacto")
    contacto_efectivo = int(
        df[contacto_col].astype(str).str.strip().replace("nan", "").ne("").sum()
    ) if contacto_col else visitas_realizadas + promesas
    pct_contacto = (contacto_efectivo / total_cuentas * 100) if total_cuentas else 0.0

    df["__estatus__"] = _derive_estatus(df, cols)

    sub_tabs = st.tabs(["📋 Ejecutivo", "📊 Por Segmento", "🗺️ Geográfico", "🚗 Gestión", "⚠️ Alertas"])

    with sub_tabs[0]:
        _banner("📋", "Resumen Ejecutivo", "Visión general de la cartera y su recuperación")
        r1 = st.columns(4)
        r1[0].metric("Cuentas Asignadas", f"{total_cuentas:,}")
        r1[1].metric("Saldo Asignado", fmt_currency(saldo_asignado))
        r1[2].metric("Saldo Recuperado", fmt_currency(saldo_recuperado), delta=f"{pct_recuperacion:.1f}%")
        r1[3].metric("% Recuperación", f"{pct_recuperacion:.1f}%")
        r2 = st.columns(4)
        r2[0].metric("Cuentas Recuperadas", f"{cuentas_recuperadas:,}", delta=f"{pct_cuentas_rec:.1f}%")
        r2[1].metric("Visitas Realizadas", f"{visitas_realizadas:,}", delta=f"{pct_visitas:.1f}%")
        r2[2].metric("Promesas de Pago", f"{promesas:,}", delta=f"{pct_promesas:.1f}%")
        r2[3].metric("Contacto Efectivo", f"{contacto_efectivo:,}", delta=f"{pct_contacto:.1f}%")

        c1, c2 = st.columns(2)
        with c1:
            g = _grp(df, "division", cols)
            if g is None:
                st.info("Configura la columna de División para ver este gráfico.")
            else:
                g = g.sort_values("PctRec")
                fig = go.Figure(go.Bar(
                    x=g["PctRec"], y=g["division"], orientation="h",
                    marker_color=[_color_pct(v) for v in g["PctRec"]],
                    text=[f"{v:.1f}%" for v in g["PctRec"]], textposition="outside",
                ))
                fig.update_layout(**PLOTLY_LAYOUT, title="% Recuperación por División",
                                   xaxis=dict(**_AXIS_DEFAULTS, title="% Recuperación",
                                              range=[0, max(g["PctRec"].max() * 1.3, 5)]),
                                   yaxis=dict(**_AXIS_DEFAULTS))
                _chart_card(fig)
        with c2:
            g = _grp(df, "campania", cols)
            if g is None:
                st.info("Configura la columna de Campaña para ver este gráfico.")
            else:
                g = g.sort_values("campania")
                fig = go.Figure(go.Scatter(
                    x=g["campania"].astype(str), y=g["PctRec"], mode="lines+markers",
                    line=dict(color=COLORS["primary"], width=3), marker=dict(size=8),
                ))
                fig.update_layout(**PLOTLY_LAYOUT, title="Tendencia de % Recuperación por Campaña",
                                   xaxis=dict(**_AXIS_DEFAULTS, title="Campaña", type="category"),
                                   yaxis=dict(**_AXIS_DEFAULTS, title="% Recuperación"))
                _chart_card(fig)

    with sub_tabs[1]:
        _banner("📊", "Por Segmento de Mora", "Desempeño de recuperación por nivel de morosidad")
        g = _grp(df, "segmento", cols)
        if g is None:
            st.info("Configura la columna de Segmento Mora para ver esta sección.")
        else:
            seg_colors = {
                "Inactiva": COLORS["muted"], "Mora 1": COLORS["warning"],
                "Mora 2": COLORS["orange"], "Mora 3": COLORS["danger"],
            }
            metric_cols = st.columns(len(g)) if len(g) else []
            for col_widget, (_, row) in zip(metric_cols, g.iterrows()):
                col_widget.metric(str(row["segmento"]), f"{int(row['Cuentas']):,}", delta=f"{row['PctRec']:.1f}%")

            c1, c2 = st.columns(2)
            with c1:
                fig = go.Figure(go.Bar(
                    x=g["segmento"], y=g["PctRec"],
                    marker_color=[seg_colors.get(str(s), COLORS["accent"]) for s in g["segmento"]],
                    text=[f"{v:.1f}%" for v in g["PctRec"]], textposition="outside",
                ))
                fig.update_layout(**PLOTLY_LAYOUT, title="% Recuperación por Segmento",
                                   xaxis=dict(**_AXIS_DEFAULTS), yaxis=dict(**_AXIS_DEFAULTS, title="% Recuperación"))
                _chart_card(fig)
            with c2:
                fig = go.Figure()
                fig.add_bar(name="Asignado", x=g["segmento"], y=g["Asignado"], marker_color=COLORS["accent"])
                fig.add_bar(name="Recuperado", x=g["segmento"], y=g["Pagado"], marker_color=COLORS["success"])
                fig.update_layout(**PLOTLY_LAYOUT, barmode="group", title="Asignado vs Recuperado por Segmento",
                                   xaxis=dict(**_AXIS_DEFAULTS), yaxis=dict(**_AXIS_DEFAULTS))
                _chart_card(fig)

            tabla = g[["segmento", "Cuentas", "Asignado", "Pagado", "PctRec"]].copy()
            tabla["Asignado"] = tabla["Asignado"].apply(fmt_currency)
            tabla["Pagado"] = tabla["Pagado"].apply(fmt_currency)
            tabla["PctRec"] = tabla["PctRec"].apply(lambda v: f"{v:.1f}%")
            tabla.columns = ["Segmento", "Cuentas", "Asignado", "Recuperado", "% Recuperación"]
            st.dataframe(tabla, use_container_width=True, hide_index=True)

    with sub_tabs[2]:
        _banner("🗺️", "Análisis Geográfico", "Recuperación por ruta, división y zona")
        c1, c2 = st.columns(2)
        with c1:
            g = _grp(df, "ruta", cols, top_n=15)
            if g is None:
                st.info("Configura la columna de Ruta para ver este gráfico.")
            else:
                g = g.sort_values("PctRec")
                fig = go.Figure(go.Bar(
                    x=g["PctRec"], y=g["ruta"], orientation="h",
                    marker_color=[_color_pct(v) for v in g["PctRec"]],
                ))
                fig.update_layout(**PLOTLY_LAYOUT, title="% Recuperación por Ruta (Top 15)",
                                   xaxis=dict(**_AXIS_DEFAULTS, title="% Recuperación"), yaxis=dict(**_AXIS_DEFAULTS))
                _chart_card(fig)
        with c2:
            g = _grp(df, "division", cols)
            if g is None:
                st.info("Configura la columna de División para ver este gráfico.")
            else:
                g = g.sort_values("PctRec", ascending=False)
                fig = go.Figure(go.Bar(
                    x=g["division"], y=g["PctRec"],
                    marker_color=[_color_pct(v) for v in g["PctRec"]],
                ))
                fig.update_layout(**PLOTLY_LAYOUT, title="% Recuperación por División",
                                   xaxis=dict(**_AXIS_DEFAULTS), yaxis=dict(**_AXIS_DEFAULTS, title="% Recuperación"))
                _chart_card(fig)

        g = _grp(df, "zona", cols)
        if g is None:
            st.info("Configura la columna de Zona para ver el Top/Bottom de zonas.")
        else:
            top10 = g.sort_values("PctRec", ascending=False).head(10)
            bottom10 = g.sort_values("PctRec", ascending=True).head(10)
            c1, c2 = st.columns(2)
            with c1:
                fig = go.Figure(go.Bar(
                    x=top10["PctRec"], y=top10["zona"], orientation="h",
                    marker_color=COLORS["success"],
                ))
                fig.update_layout(**PLOTLY_LAYOUT, title="Top 10 Zonas (% Recuperación)",
                                   xaxis=dict(**_AXIS_DEFAULTS), yaxis=dict(**_AXIS_DEFAULTS, autorange="reversed"))
                _chart_card(fig)
            with c2:
                fig = go.Figure(go.Bar(
                    x=bottom10["PctRec"], y=bottom10["zona"], orientation="h",
                    marker_color=COLORS["danger"],
                ))
                fig.update_layout(**PLOTLY_LAYOUT, title="Bottom 10 Zonas (% Recuperación)",
                                   xaxis=dict(**_AXIS_DEFAULTS), yaxis=dict(**_AXIS_DEFAULTS, autorange="reversed"))
                _chart_card(fig)

    with sub_tabs[3]:
        _banner("🚗", "Gestión de Cobranza", "Resultado de visitas, llamadas y dictaminaciones")
        c1, c2 = st.columns(2)
        with c1:
            counts = df["__estatus__"].value_counts().sort_values()
            fig = go.Figure(go.Bar(
                x=counts.values, y=counts.index, orientation="h",
                marker_color=COLORS["accent"],
                text=[f"{v:,}" for v in counts.values], textposition="outside",
            ))
            fig.update_layout(**PLOTLY_LAYOUT, title="Distribución de Estatus",
                              xaxis=dict(**_AXIS_DEFAULTS), yaxis=dict(**_AXIS_DEFAULTS))
            _chart_card(fig)
        with c2:
            if cols.get("dictaminacion"):
                counts = df[cols["dictaminacion"]].astype(str).value_counts().head(10).sort_values()
                fig = go.Figure(go.Bar(
                    x=counts.values, y=counts.index, orientation="h",
                    marker_color=COLORS["teal"],
                    text=[f"{v:,}" for v in counts.values], textposition="outside",
                ))
                fig.update_layout(**PLOTLY_LAYOUT, title="Dictaminación (Top 10)",
                                  xaxis=dict(**_AXIS_DEFAULTS), yaxis=dict(**_AXIS_DEFAULTS))
                _chart_card(fig)
            else:
                st.info("Configura la columna de Dictaminación para ver este gráfico.")

        if cols.get("visita"):
            counts = df[cols["visita"]].astype(str).value_counts().head(10).sort_values()
            fig = go.Figure(go.Bar(x=counts.values, y=counts.index, orientation="h",
                                    marker_color=COLORS["teal"]))
            fig.update_layout(**PLOTLY_LAYOUT, title="Resultado de Visitas (Top 10)",
                               xaxis=dict(**_AXIS_DEFAULTS), yaxis=dict(**_AXIS_DEFAULTS))
            _chart_card(fig)
        else:
            st.info("Configura la columna de Visita/Resultado para ver este gráfico.")

        g = _grp(df, "zona", cols)
        if g is None:
            st.info("Configura la columna de Zona para ver este gráfico.")
        else:
            g = g.sort_values("PctRec")
            fig = go.Figure(go.Bar(x=g["PctRec"], y=g["zona"], orientation="h",
                                    marker_color=[_color_pct(v) for v in g["PctRec"]]))
            fig.update_layout(**PLOTLY_LAYOUT, title="% Recuperación por Zona",
                               xaxis=dict(**_AXIS_DEFAULTS, title="% Recuperación"), yaxis=dict(**_AXIS_DEFAULTS))
            _chart_card(fig)

    with sub_tabs[4]:
        _banner("⚠️", "Alertas", "Unidades con recuperación por debajo del umbral")
        umbral = st.slider("Umbral de % de recuperación", 0, 100, 30, step=5)

        any_alert = False
        for col_key, label, fn in [
            ("zona", "Zona", st.error),
            ("ruta", "Ruta", st.warning),
            ("division", "División", st.warning),
        ]:
            g = _grp(df, col_key, cols)
            if g is None:
                continue
            bajo = g[g["PctRec"] < umbral].sort_values("PctRec")
            if len(bajo):
                any_alert = True
                fn(f"{len(bajo)} unidad(es) de **{label}** por debajo de {umbral}% de recuperación")
                tabla = bajo[[col_key, "Cuentas", "Asignado", "Pagado", "PctRec"]].copy()
                tabla["Asignado"] = tabla["Asignado"].apply(fmt_currency)
                tabla["Pagado"] = tabla["Pagado"].apply(fmt_currency)
                tabla["PctRec"] = tabla["PctRec"].apply(lambda v: f"{v:.1f}%")
                tabla.columns = [label, "Cuentas", "Asignado", "Recuperado", "% Recuperación"]
                st.dataframe(tabla, use_container_width=True, hide_index=True)

        if not any_alert:
            st.success(f"No hay unidades por debajo del {umbral}% de recuperación.")


def _indicadores_uploader():
    uploaded = st.file_uploader(
        "Archivo .xlsx / .xls", type=["xlsx", "xls"], key="ind_uploader", label_visibility="collapsed"
    )
    if uploaded is not None and st.session_state.get("ind_file_name") != uploaded.name:
        st.session_state["ind_df"] = read_excel_safe(uploaded)
        st.session_state["ind_file_name"] = uploaded.name


def _render_indicadores_results():
    st.markdown(INDICADORES_CSS, unsafe_allow_html=True)
    df = st.session_state.get("ind_df")
    if df is None:
        return
    _banner("📊", "Indicadores de Mora", "Dashboard de cobranza y recuperación de cartera")
    tab_indicadores(df)
