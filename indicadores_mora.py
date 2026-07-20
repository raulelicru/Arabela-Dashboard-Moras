"""Dashboard de Indicadores de Mora (cobranza / recuperación de cartera)."""

import unicodedata
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from auth import is_admin


def _norm(s: str) -> str:
    """Lowercase + strip accents for fuzzy column matching."""
    return ''.join(
        c for c in unicodedata.normalize('NFD', s.lower())
        if unicodedata.category(c) != 'Mn'
    )

# ── Design system ────────────────────────────────────────────────────────────
# Categorical palette (8 slots, CVD-safe ordering from dataviz skill)
CAT_COLORS = [
    "#2a78d6",  # 1 blue
    "#1baf7a",  # 2 aqua-green
    "#e87ba4",  # 3 magenta-pink
    "#eb6834",  # 4 orange
    "#4a3aa7",  # 5 violet
    "#eda100",  # 6 amber
    "#e34948",  # 7 red
    "#008300",  # 8 green
]

COLORS = {
    "primary":   "#1e3a5f",
    "accent":    "#2a78d6",
    "success":   "#1baf7a",
    "warning":   "#eda100",
    "danger":    "#e34948",
    "purple":    "#4a3aa7",
    "pink":      "#e87ba4",
    "orange":    "#eb6834",
    "muted":     "#898781",
    "bg":        "#fcfcfb",
    "plot_bg":   "#f9f9f7",
    "grid":      "#e1e0d9",
    "text":      "#0b0b0b",
    "text2":     "#52514e",
}

_FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif"

_MARGIN_DEFAULT = dict(l=48, r=24, t=56, b=48)

PLOTLY_LAYOUT = dict(
    paper_bgcolor=COLORS["bg"],
    plot_bgcolor=COLORS["plot_bg"],
    font=dict(color=COLORS["text2"], family=_FONT, size=12),
    margin=_MARGIN_DEFAULT,
    hovermode="closest",
    hoverlabel=dict(
        bgcolor=COLORS["bg"], bordercolor=COLORS["grid"],
        font=dict(color=COLORS["text"], family=_FONT, size=12),
    ),
    colorway=CAT_COLORS,
)

def _layout(**overrides):
    """Return PLOTLY_LAYOUT with overrides merged (avoids duplicate-key TypeError)."""
    merged = dict(PLOTLY_LAYOUT)
    merged.update(overrides)
    return merged

_LEGEND_H = dict(
    orientation="h", yanchor="bottom", y=1.02,
    xanchor="right", x=1,
    font=dict(size=11, color=COLORS["text2"]),
    bgcolor="rgba(0,0,0,0)", borderwidth=0,
)

_AXIS_DEFAULTS = dict(
    gridcolor=COLORS["grid"],
    gridwidth=1,
    zeroline=False,
    showline=False,
    tickfont=dict(size=11, color=COLORS["muted"]),
    title_font=dict(size=12, color=COLORS["text2"]),
)

INDICADORES_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

.chart-card {
  background: #fcfcfb;
  border: 1px solid #e1e0d9;
  border-radius: 16px;
  padding: 1.1rem 1.4rem 0.6rem;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06), 0 4px 16px rgba(30,58,95,0.06);
  margin-bottom: 1rem;
  transition: box-shadow .2s ease, transform .2s ease;
}
.chart-card:hover {
  box-shadow: 0 4px 20px rgba(30,58,95,0.14);
  transform: translateY(-1px);
}
.kpi-banner {
  background: linear-gradient(135deg, #1e3a5f 0%, #2a78d6 60%, #1baf7a 100%);
  border-radius: 16px;
  padding: 1.3rem 1.8rem;
  color: #fff;
  margin-bottom: 1.3rem;
  box-shadow: 0 4px 20px rgba(30,58,95,0.2);
}
.kpi-banner h1 { color: #fff !important; font-size: 1.35rem; font-weight: 700; margin: 0; letter-spacing: -0.01em; }
.kpi-banner p  { color: rgba(255,255,255,.78); margin: .25rem 0 0; font-size: .84rem; }
.section-title {
  font-size: 1rem;
  font-weight: 600;
  color: #1e3a5f;
  border-left: 3px solid #2a78d6;
  padding: .25rem 0 .25rem .75rem;
  margin: 1.4rem 0 .9rem;
  letter-spacing: -.01em;
}
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
    norm_cols  = {_norm(c): c for c in df.columns}

    def _is_bool_col(key: str) -> bool:
        return skip_bool and any(p in key for p in _BOOL_COL_PATTERNS)

    for cand in candidates:
        nc = _norm(cand)
        # 1. Exact match (accent-normalized)
        if nc in norm_cols and not _is_bool_col(_norm(norm_cols[nc])):
            return norm_cols[nc]
    for cand in candidates:
        nc = _norm(cand)
        # 2. Starts-with match
        for nk, real in norm_cols.items():
            if nk.startswith(nc) and not _is_bool_col(nk):
                return real
    for cand in candidates:
        nc = _norm(cand)
        # 3. Substring match
        for nk, real in norm_cols.items():
            if nc in nk and not _is_bool_col(nk):
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


def _pie_fig(labels, values, title, colors=None, hole=0.44):
    """Donut chart with consistent professional styling."""
    pal = colors or CAT_COLORS
    fig = go.Figure(go.Pie(
        labels=labels, values=values,
        marker=dict(colors=pal, line=dict(color=COLORS["bg"], width=2.5)),
        hole=hole,
        textinfo="label+percent",
        textposition="outside",
        textfont=dict(size=11, color=COLORS["text2"]),
        insidetextorientation="radial",
    ))
    fig.update_layout(
        **PLOTLY_LAYOUT,
        title=dict(text=title, font=dict(size=14, color=COLORS["primary"], weight=600)),
        legend=dict(orientation="h", yanchor="top", y=-0.08, xanchor="center", x=0.5,
                    font=dict(size=10, color=COLORS["text2"])),
    )
    return fig


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


def _section(title: str):
    st.markdown(f"<div class='section-title'>{title}</div>", unsafe_allow_html=True)


COLUMN_CANDIDATES = {
    "campania":      ["campaniasaldo", "campaña de trab", "campania", "campaña", "anio"],
    "division":      ["division", "división"],
    "ruta":          ["ruta"],
    "zona":          ["zona"],
    "region":        ["region", "región"],
    "estado":        ["estado", "entidad federativa", "entidad"],
    "municipio":     ["municipio", "ciudad", "alcaldia"],
    "colonia":       ["colonia"],
    "no_dama":       ["nodama", "dama"],
    "segmento":      ["morosidad", "mora", "segmento"],
    "saldo":         ["saldodama", "saldo"],
    "pago":          ["montopago", "pagomonto", "importe pago", "monto cobrado", "cobrado", "recuperado", "pago"],
    "visita":        ["vistas gestor", "visitas gestor", "gestion", "visita"],
    "promesa":       ["dictaminacion de llamada", "dictam llamada", "dictaminacion llamada"],
    "contacto":      ["estatus de llamada", "estatus llamada", "estatusllamada"],
    "dictaminacion": ["dictaminacion", "dictam"],
    "situacion_cie": ["descsituacioncie", "descsituacion cie", "desc situacion cie", "situacioncie"],
    "situacion":     ["descsituacion", "situacion", "estatus"],
}

COLUMN_LABELS = {
    "campania":      "Campaña",
    "division":      "División",
    "ruta":          "Ruta",
    "zona":          "Zona",
    "region":        "Región",
    "estado":        "Estado",
    "municipio":     "Municipio",
    "colonia":       "Colonia",
    "no_dama":       "Número de Dama",
    "segmento":      "Segmento Mora",
    "saldo":         "Saldo Asignado",
    "pago":          "Pago Aplicado",
    "visita":        "Visita / Resultado",
    "promesa":       "Dictam. Llamada (Col. AM)",
    "contacto":      "Estatus Llamada (Col. AN)",
    "dictaminacion": "Dictaminación",
    "situacion_cie": "Situación Entrega (Col. AB)",
    "situacion":     "Situación Domicilio",
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
    if is_admin():
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
    if "__pago__" in df.columns:
        agg["Pagado"] = ("__pago__", "sum")
    g = df.groupby(col).agg(**agg).reset_index().rename(columns={col: col_key})
    if "Pagado" not in g.columns:
        g["Pagado"] = 0
    g["PctRec"] = np.where(g["Asignado"] > 0, g["Pagado"] / g["Asignado"] * 100, 0)
    if top_n:
        g = g.sort_values("Cuentas", ascending=False).head(top_n)
    return g


def _grp2(df: pd.DataFrame, col1_key: str, col2_key: str, cols: dict) -> pd.DataFrame | None:
    col1 = cols.get(col1_key)
    col2 = cols.get(col2_key)
    if not col1 or not col2 or col1 not in df.columns or col2 not in df.columns:
        return None
    g = df.groupby([col1, col2]).agg(
        Cuentas=(col1, "count"),
        Asignado=("__saldo__", "sum"),
    ).reset_index()
    if "__pago__" in df.columns:
        pg = df.groupby([col1, col2])["__pago__"].sum().reset_index()
        g = g.merge(pg, on=[col1, col2]).rename(columns={"__pago__": "Pagado"})
    else:
        g["Pagado"] = 0
    g = g.rename(columns={col1: col1_key, col2: col2_key})
    g["PctRec"] = np.where(g["Asignado"] > 0, g["Pagado"] / g["Asignado"] * 100, 0)
    return g


def _grp_contacto(df: pd.DataFrame, col_key: str, cols: dict) -> pd.DataFrame | None:
    col = cols.get(col_key)
    contacto_col = cols.get("contacto")
    if not col or not contacto_col or col not in df.columns or contacto_col not in df.columns:
        return None
    df2 = df[[col, contacto_col]].copy()
    df2["_ct"] = df2[contacto_col].astype(str).str.strip().str.upper().eq("CONTACTO").astype(int)
    g = df2.groupby(col).agg(Total=(col, "count"), Contacto=("_ct", "sum")).reset_index()
    g.columns = [col_key, "Total", "Contacto"]
    g["NoContacto"] = g["Total"] - g["Contacto"]
    g["PctContacto"] = np.where(g["Total"] > 0, g["Contacto"] / g["Total"] * 100, 0)
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
        "Gestionada",
        "Gestionada - Llamada",
    ]
    return pd.Series(np.select(conditions, choices, default="Sin Gestión"), index=df.index)


def _hbar(g, x_col, y_col, title, x_title="", color_fn=None, height_per_row=32):
    color_fn = color_fn or (lambda v: COLORS["accent"])
    colors = [color_fn(v) for v in g[x_col]]
    max_x = g[x_col].max() if len(g) else 1
    fig = go.Figure(go.Bar(
        x=g[x_col], y=g[y_col].astype(str), orientation="h",
        marker=dict(color=colors, line=dict(width=0)),
        text=[f"{v:.1f}%" if "Pct" in x_col or "pct" in x_col.lower() else f"{v:,}"
              for v in g[x_col]],
        textposition="outside",
        textfont=dict(size=11, color=COLORS["text2"]),
    ))
    fig.update_layout(
        **PLOTLY_LAYOUT, title=dict(text=title, font=dict(size=14, color=COLORS["primary"], weight=600)),
        xaxis=dict(**_AXIS_DEFAULTS, title=x_title, range=[0, max(max_x * 1.38, 1)]),
        yaxis=dict(**_AXIS_DEFAULTS, type="category"),
        height=max(300, len(g) * height_per_row + 100),
        bargap=0.28,
    )
    return fig


CAMP_COLORS = CAT_COLORS[:4]


def _last4_camps(df: pd.DataFrame, cols: dict) -> list:
    """Retorna las últimas 4 campañas disponibles (orden descendente)."""
    camp_col = cols.get("campania")
    if not camp_col or camp_col not in df.columns:
        return []
    vals = df[camp_col].dropna().astype(str).unique().tolist()
    try:
        srt = sorted(vals, key=lambda x: float(x) if x.replace(".", "").isdigit() else x, reverse=True)
    except Exception:
        srt = sorted(vals, reverse=True)
    return srt[:4]


def _grp_camp(df: pd.DataFrame, col_key: str, cols: dict, last4: list) -> pd.DataFrame | None:
    """Agrupa por col_key × Campaña para las últimas 4."""
    camp_col = cols.get("campania")
    col = cols.get(col_key)
    if not camp_col or not col or camp_col not in df.columns or col not in df.columns or not last4:
        return None
    df2 = df[df[camp_col].astype(str).isin(last4)].copy()
    g = df2.groupby([col, camp_col]).agg(
        Cuentas=(col, "count"),
        Asignado=("__saldo__", "sum"),
        Pagado=("__pago__", "sum"),
    ).reset_index()
    g.columns = [col_key, "Campaña", "Cuentas", "Asignado", "Pagado"]
    g["PctRec"] = np.where(g["Asignado"] > 0, g["Pagado"] / g["Asignado"] * 100, 0)
    return g


def _df_excel(df_show: pd.DataFrame, filename: str, btn_label: str = "📥 Descargar Excel",
              df_base: pd.DataFrame = None, base_label: str = None, base_filename: str = None,
              show_table: bool = True):
    """Muestra dataframe + botón de descarga Excel. Si se pasa df_base, agrega botón de base/detalle."""
    import io
    if show_table:
        st.dataframe(df_show, use_container_width=True, hide_index=True)
    buf = io.BytesIO()
    df_show.to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)

    buf2 = None
    if df_base is not None:
        try:
            _df_safe = df_base.copy()
            for col in _df_safe.select_dtypes(include=["datetimetz"]).columns:
                _df_safe[col] = _df_safe[col].dt.tz_localize(None)
            buf2 = io.BytesIO()
            _df_safe.to_excel(buf2, index=False, engine="openpyxl")
            buf2.seek(0)
        except Exception:
            buf2 = None

    if buf2 is not None:
        _base_label = base_label or f"📋 Base completa ({len(df_base):,} reg.)"
        _base_file  = base_filename or ("base_" + filename)
        c1, c2 = st.columns(2)
        with c1:
            st.download_button(
                label=btn_label,
                data=buf,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"dl_{filename}",
            )
        with c2:
            st.download_button(
                label=_base_label,
                data=buf2,
                file_name=_base_file,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"dl_base_{filename}",
            )
    else:
        st.download_button(
            label=btn_label,
            data=buf,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"dl_{filename}",
        )


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
    df["__pago__"] = _to_num(df[cols["pago"]]) if cols.get("pago") else 0.0

    def _pagaron(d: pd.DataFrame) -> pd.DataFrame:
        """Filas con pago > 0 (se recalcula sobre el df pasado para respetar filtros activos)."""
        return d[d["__pago__"] > 0].copy()

    # ── Filtro global de Campaña ──────────────────────────────────────────────
    camp_col = cols.get("campania")
    if camp_col and camp_col in df.columns:
        raw_camps = df[camp_col].dropna().astype(str).unique().tolist()
        def _camp_key(x):
            return (0, float(x)) if x.replace(".", "").isdigit() else (1, x)

        all_camps = sorted(raw_camps, key=_camp_key)
        default4 = sorted(raw_camps, key=_camp_key, reverse=True)[:4]
        with st.container():
            sel = st.multiselect(
                "🗓️ Campaña (Col. O) — filtra todo el dashboard",
                options=all_camps,
                default=default4,
                key="camp_filter_global",
            )
        if sel:
            df = df[df[camp_col].astype(str).isin(sel)]
            st.caption(f"Campañas activas: **{', '.join(sorted(sel, key=_camp_key))}** — {len(df):,} registros")

    # Últimas 4 campañas del universo actual (post-filtro)
    last4 = _last4_camps(df, cols)
    camp_col_real = cols.get("campania")

    total_cuentas = len(df)
    saldo_asignado = df["__saldo__"].sum()
    saldo_recuperado = df["__pago__"].sum()
    pct_recuperacion = (saldo_recuperado / saldo_asignado * 100) if saldo_asignado > 0 else 0.0

    cuentas_recuperadas = int((df["__pago__"] > 0).sum())
    pct_cuentas_rec = (cuentas_recuperadas / total_cuentas * 100) if total_cuentas else 0.0

    visita_col = cols.get("visita")
    if visita_col:
        _EXCLUIR = {"", "nan", "none", "0", "0.0", "sin gestion", "sin visita",
                    "no visita", "no contacto", "sin contacto", "no gestion"}
        _vis = df[visita_col].fillna("").astype(str).str.strip().str.lower()
        visitas_realizadas = int((~_vis.isin(_EXCLUIR)).sum())
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
        df[contacto_col].astype(str).str.strip().str.upper().eq("CONTACTO").sum()
    ) if contacto_col else 0
    pct_contacto = (contacto_efectivo / total_cuentas * 100) if total_cuentas else 0.0

    df["__estatus__"] = _derive_estatus(df, cols)

    seg_colors = {
        "Inactiva": COLORS["muted"], "Mora 1": COLORS["warning"],
        "Mora 2": COLORS["orange"], "Mora 3": COLORS["danger"],
    }

    # ── Dos pestañas principales ───────────────────────────────────────────────
    main_tabs = st.tabs(["🏢 Gestión Moras", "📍 Direcciones"])

    # ══════════════════════════════════════════════════════════════════════════
    # GESTIÓN MORAS
    # ══════════════════════════════════════════════════════════════════════════
    with main_tabs[0]:
        sub = st.tabs(["📋 Ejecutivo", "📊 Por Segmento", "📞 Gestión Damas", "📋 Dictaminación", "⚠️ Alertas"])

        # ── Ejecutivo ─────────────────────────────────────────────────────────
        with sub[0]:
            _banner("📋", "Recuperación", "Visión general de la cartera y su recuperación")

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

            _section("Recuperación por Ámbito Geográfico")
            c1, c2, c3 = st.columns(3)
            for widget, key, title, fname in [
                (c1, "region",   "% Recuperación por Región",         "recuperacion_por_region.xlsx"),
                (c2, "ruta",     "% Recuperación por Ruta (Top 15)",  "recuperacion_por_ruta.xlsx"),
                (c3, "division", "% Recuperación por División",       "recuperacion_por_division.xlsx"),
            ]:
                with widget:
                    g = _grp(df, key, cols, top_n=15 if key == "ruta" else None)
                    if g is None:
                        st.info(f"Sin columna de {key.title()}.")
                    else:
                        g = g.sort_values("PctRec")
                        _chart_card(_hbar(g, "PctRec", key, title, "% Recuperación",
                                         color_fn=_color_pct))
                        tbl_geo = g[[key, "Cuentas", "Asignado", "Pagado", "PctRec"]].copy()
                        tbl_geo["Asignado"] = tbl_geo["Asignado"].apply(fmt_currency)
                        tbl_geo["Pagado"]   = tbl_geo["Pagado"].apply(fmt_currency)
                        tbl_geo["PctRec"]   = tbl_geo["PctRec"].apply(lambda v: f"{v:.1f}%")
                        tbl_geo.columns = [key.title(), "Cuentas", "Asignado", "Recuperado", "% Recuperación"]
                        if key == "region":
                            _pag = _pagaron(df)
                            _df_excel(tbl_geo.sort_values("% Recuperación", ascending=False), fname,
                                      df_base=_pag,
                                      base_label=f"✅ Cuentas que pagaron ({len(_pag):,} reg.)",
                                      base_filename=f"pagaron_{fname}")
                        else:
                            _df_excel(tbl_geo.sort_values("% Recuperación", ascending=False), fname,
                                      show_table=False)

            _section("Tendencia por Campaña")
            g = _grp(df, "campania", cols)
            if g is not None:
                g["campania"] = pd.to_numeric(g["campania"], errors="coerce").fillna(g["campania"])
                g = g.sort_values("campania", key=lambda c: c.astype(str))
                try:
                    g = g[pd.to_numeric(g["campania"], errors="coerce") >= 9]
                except Exception:
                    g = g.tail(5)
                if len(g):
                    fig = go.Figure(go.Scatter(
                        x=g["campania"].astype(str), y=g["PctRec"], mode="lines+markers",
                        line=dict(color=CAT_COLORS[0], width=2.5),
                        marker=dict(size=9, color=CAT_COLORS[0],
                                    line=dict(color=COLORS["bg"], width=2)),
                        text=[f"{v:.1f}%" for v in g["PctRec"]], textposition="top center",
                        textfont=dict(size=11, color=COLORS["text2"]),
                        fill="tozeroy", fillcolor=f"rgba(42,120,214,0.08)",
                    ))
                    fig.update_layout(
                        **PLOTLY_LAYOUT, title=dict(text="Tendencia de % Recuperación por Campaña", font=dict(size=14, color=COLORS["primary"], weight=600)),
                        xaxis=dict(**_AXIS_DEFAULTS, title=dict(text="Campaña", font=dict(size=14, color=COLORS["primary"], weight=600)), type="category"),
                        yaxis=dict(**_AXIS_DEFAULTS, title="% Recuperación"),
                    )
                    _chart_card(fig)

            g_all_camp = _grp(df, "campania", cols)
            if g_all_camp is not None:
                g_all_camp = g_all_camp.sort_values("campania", key=lambda c: c.astype(str))
                tabla_camp = g_all_camp[["campania", "Cuentas", "Asignado", "Pagado", "PctRec"]].copy()
                tabla_camp["Asignado"] = tabla_camp["Asignado"].apply(fmt_currency)
                tabla_camp["Pagado"]   = tabla_camp["Pagado"].apply(fmt_currency)
                tabla_camp["PctRec"]   = tabla_camp["PctRec"].apply(lambda v: f"{v:.1f}%")
                tabla_camp.columns = ["Campaña", "Cuentas", "Asignado", "Recuperado", "% Recuperación"]
                _df_excel(tabla_camp, "recuperacion_por_campana.xlsx", show_table=False)

            if last4 and camp_col_real:
                _section("📅 Comparativo — Últimas 4 Campañas")
                # Datos por campaña para gráfica y descarga
                rows = []
                _camp_labels, _asignados, _recuperados, _pct_contactos = [], [], [], []
                for c in reversed(last4):
                    dfc = df[df[camp_col_real].astype(str) == c]
                    n   = len(dfc)
                    sal = dfc["__saldo__"].sum()
                    pag = dfc["__pago__"].sum()
                    pct = pag / sal * 100 if sal > 0 else 0
                    rec = int((dfc["__pago__"] > 0).sum())
                    cont = int(dfc[contacto_col].astype(str).str.strip().str.upper().eq("CONTACTO").sum()) if contacto_col else 0
                    pct_cont = cont / n * 100 if n > 0 else 0
                    rows.append({"Campaña": c, "Cuentas": f"{n:,}",
                                 "Saldo Asignado": fmt_currency(sal), "Recuperado": fmt_currency(pag),
                                 "% Recuperación": f"{pct:.1f}%", "Ctas. Rec.": f"{rec:,}",
                                 "Contacto": f"{cont:,}", "% Contacto": f"{pct_cont:.1f}%"})
                    _camp_labels.append(str(c))
                    _asignados.append(sal)
                    _recuperados.append(pag)
                    _pct_contactos.append(pct_cont)

                if _camp_labels:
                    fig6 = go.Figure()
                    fig6.add_trace(go.Bar(
                        name="Monto Asignado", x=_camp_labels, y=_asignados,
                        marker_color=CAT_COLORS[0],
                        text=[fmt_currency(v) for v in _asignados], textposition="outside",
                        yaxis="y1",
                    ))
                    fig6.add_trace(go.Bar(
                        name="Monto Recuperado", x=_camp_labels, y=_recuperados,
                        marker_color=COLORS["success"],
                        text=[fmt_currency(v) for v in _recuperados], textposition="outside",
                        yaxis="y1",
                    ))
                    fig6.add_trace(go.Scatter(
                        name="% Contacto", x=_camp_labels, y=_pct_contactos,
                        mode="lines+markers+text",
                        line=dict(color=COLORS["warning"], width=2.5),
                        marker=dict(size=9, color=COLORS["warning"],
                                    line=dict(color=COLORS["bg"], width=2)),
                        text=[f"{v:.1f}%" for v in _pct_contactos], textposition="top center",
                        textfont=dict(size=11, color=COLORS["warning"]),
                        yaxis="y2",
                    ))
                    fig6.update_layout(
                        **PLOTLY_LAYOUT,
                        barmode="group",
                        title=dict(text="Monto Asignado vs Recuperado y % Contacto — Últimas 4 Campañas",
                                   font=dict(size=14, color=COLORS["primary"], weight=600)),
                        xaxis=dict(**_AXIS_DEFAULTS, title=dict(text="Campaña",
                                   font=dict(size=14, color=COLORS["primary"], weight=600)), type="category"),
                        yaxis=dict(**_AXIS_DEFAULTS, title="Monto ($)"),
                        yaxis2=dict(title="% Contacto", overlaying="y", side="right",
                                    showgrid=False, ticksuffix="%",
                                    titlefont=dict(color=COLORS["warning"]),
                                    tickfont=dict(color=COLORS["warning"])),
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    )
                    _chart_card(fig6)
                _df_excel(pd.DataFrame(rows), "kpis_ultimas4_campanas.xlsx", show_table=False)

        # ── Por Segmento ──────────────────────────────────────────────────────
        with sub[1]:
            _banner("📊", "Por Segmento de Mora", "Desempeño de recuperación por nivel de morosidad")
            g_seg = _grp(df, "segmento", cols)
            if g_seg is None:
                st.info("Configura la columna de Segmento Mora para ver esta sección.")
            else:
                met_cols = st.columns(max(len(g_seg), 1))
                for mc, (_, row) in zip(met_cols, g_seg.iterrows()):
                    mc.metric(str(row["segmento"]), f"{int(row['Cuentas']):,}",
                              delta=f"{row['PctRec']:.1f}%")

                _section("Recuperación por Segmento")
                c1, c2 = st.columns(2)
                with c1:
                    fig = go.Figure(go.Bar(
                        x=g_seg["segmento"], y=g_seg["PctRec"],
                        marker_color=[seg_colors.get(str(s), COLORS["accent"]) for s in g_seg["segmento"]],
                        text=[f"{v:.1f}%" for v in g_seg["PctRec"]], textposition="outside",
                    ))
                    fig.update_layout(
                        **PLOTLY_LAYOUT, title=dict(text="% Recuperación por Segmento", font=dict(size=14, color=COLORS["primary"], weight=600)),
                        xaxis=dict(**_AXIS_DEFAULTS, title="Segmento"),
                        yaxis=dict(**_AXIS_DEFAULTS, title="% Recuperación"),
                    )
                    _chart_card(fig)
                with c2:
                    fig = go.Figure()
                    fig.add_bar(name="Asignado", x=g_seg["segmento"], y=g_seg["Asignado"],
                                marker_color=CAT_COLORS[0],
                                text=[fmt_currency(v) for v in g_seg["Asignado"]],
                                textposition="outside")
                    fig.add_bar(name="Recuperado", x=g_seg["segmento"], y=g_seg["Pagado"],
                                marker_color=COLORS["success"],
                                text=[fmt_currency(v) for v in g_seg["Pagado"]],
                                textposition="outside")
                    fig.update_layout(
                        **PLOTLY_LAYOUT, barmode="group",
                        title=dict(text="Asignado vs Recuperado por Segmento", font=dict(size=14, color=COLORS["primary"], weight=600)),
                        xaxis=dict(**_AXIS_DEFAULTS, title="Segmento"),
                        yaxis=dict(**_AXIS_DEFAULTS, title="Monto ($)"),
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    )
                    _chart_card(fig)

                _section("Recuperación por Segmento × Geografía")
                g2r = _grp2(df, "segmento", "ruta", cols)
                if g2r is not None:
                    fig = px.bar(g2r, x="ruta", y="PctRec", color="segmento", barmode="group",
                                 color_discrete_map=seg_colors,
                                 text=g2r["PctRec"].map(lambda v: f"{v:.1f}%"),
                                 labels={"PctRec": "% Recuperación", "ruta": "Ruta", "segmento": "Segmento"},
                                 title="% Recuperación por Segmento por Ruta")
                    fig.update_traces(textposition="outside")
                    fig.update_layout(**PLOTLY_LAYOUT,
                                      xaxis=dict(**_AXIS_DEFAULTS, title="Ruta"),
                                      yaxis=dict(**_AXIS_DEFAULTS, title="% Recuperación"),
                                      legend=dict(title=dict(text="Segmento", font=dict(size=14, color=COLORS["primary"], weight=600)), orientation="h",
                                                  yanchor="bottom", y=1.02, xanchor="right", x=1))
                    _chart_card(fig)

                g2d = _grp2(df, "segmento", "division", cols)
                if g2d is not None:
                    fig = px.bar(g2d, x="division", y="PctRec", color="segmento", barmode="group",
                                 color_discrete_map=seg_colors,
                                 text=g2d["PctRec"].map(lambda v: f"{v:.1f}%"),
                                 labels={"PctRec": "% Recuperación", "division": "División", "segmento": "Segmento"},
                                 title="% Recuperación por Segmento por División")
                    fig.update_traces(textposition="outside")
                    fig.update_layout(**PLOTLY_LAYOUT,
                                      xaxis=dict(**_AXIS_DEFAULTS, title="División"),
                                      yaxis=dict(**_AXIS_DEFAULTS, title="% Recuperación"),
                                      legend=dict(title=dict(text="Segmento", font=dict(size=14, color=COLORS["primary"], weight=600)), orientation="h",
                                                  yanchor="bottom", y=1.02, xanchor="right", x=1))
                    _chart_card(fig)

                _section("Tabla por Segmento")
                tabla_seg = g_seg[["segmento", "Cuentas", "Asignado", "Pagado", "PctRec"]].copy()
                tabla_seg["Asignado"] = tabla_seg["Asignado"].apply(fmt_currency)
                tabla_seg["Pagado"]   = tabla_seg["Pagado"].apply(fmt_currency)
                tabla_seg["PctRec"]   = tabla_seg["PctRec"].apply(lambda v: f"{v:.1f}%")
                tabla_seg.columns = ["Segmento", "Cuentas", "Asignado", "Recuperado", "% Recuperación"]
                _df_excel(tabla_seg, "recuperacion_por_segmento.xlsx")

                _section("Recuperación por Zona — todas las zonas")
                g_zona = _grp(df, "zona", cols)
                if g_zona is not None:
                    g_zona = g_zona.sort_values("PctRec", ascending=False)
                    tabla = g_zona[["zona", "Cuentas", "Asignado", "Pagado", "PctRec"]].copy()
                    tabla["Asignado"] = tabla["Asignado"].apply(fmt_currency)
                    tabla["Pagado"]   = tabla["Pagado"].apply(fmt_currency)
                    tabla["PctRec"]   = tabla["PctRec"].apply(lambda v: f"{v:.1f}%")
                    tabla.columns = ["Zona", "Cuentas", "Asignado", "Recuperado", "% Recuperación"]
                    _df_excel(tabla, "recuperacion_por_zona.xlsx")

                if last4 and camp_col_real:
                    _section("📅 Comparativo — Recuperación por Segmento × Últimas 4 Campañas")
                    g_sc = _grp_camp(df, "segmento", cols, last4)
                    if g_sc is not None:
                        camp_order = list(reversed(last4))
                        color_map = {c: CAMP_COLORS[i % 4] for i, c in enumerate(camp_order)}
                        fig = px.bar(g_sc, x="segmento", y="PctRec", color="Campaña",
                                     barmode="group",
                                     color_discrete_map=color_map,
                                     text=g_sc["PctRec"].map(lambda v: f"{v:.1f}%"),
                                     category_orders={"Campaña": camp_order},
                                     labels={"PctRec": "% Recuperación", "segmento": "Segmento"},
                                     title="% Recuperación por Segmento — Últimas 4 Campañas")
                        fig.update_traces(textposition="outside")
                        fig.update_layout(**PLOTLY_LAYOUT,
                                          xaxis=dict(**_AXIS_DEFAULTS, title="Segmento"),
                                          yaxis=dict(**_AXIS_DEFAULTS, title="% Recuperación"),
                                          legend=dict(title=dict(text="Campaña", font=dict(size=14, color=COLORS["primary"], weight=600)), orientation="h",
                                                      yanchor="bottom", y=1.02, xanchor="right", x=1))
                        _chart_card(fig)

                    g_dc = _grp_camp(df, "division", cols, last4)
                    if g_dc is not None:
                        fig = px.bar(g_dc, x="division", y="PctRec", color="Campaña",
                                     barmode="group",
                                     color_discrete_map=color_map,
                                     text=g_dc["PctRec"].map(lambda v: f"{v:.1f}%"),
                                     category_orders={"Campaña": camp_order},
                                     labels={"PctRec": "% Recuperación", "division": "División"},
                                     title="% Recuperación por División — Últimas 4 Campañas")
                        fig.update_traces(textposition="outside")
                        fig.update_layout(**PLOTLY_LAYOUT,
                                          xaxis=dict(**_AXIS_DEFAULTS, title="División"),
                                          yaxis=dict(**_AXIS_DEFAULTS, title="% Recuperación"),
                                          legend=dict(title=dict(text="Campaña", font=dict(size=14, color=COLORS["primary"], weight=600)), orientation="h",
                                                      yanchor="bottom", y=1.02, xanchor="right", x=1))
                        _chart_card(fig)

                    g_rc = _grp_camp(df, "ruta", cols, last4)
                    if g_rc is not None:
                        tbl_rc = g_rc.pivot_table(index="ruta", columns="Campaña", values="PctRec", fill_value=0).reset_index()
                        tbl_rc.columns.name = None
                        for c in last4:
                            if c in tbl_rc.columns:
                                tbl_rc[c] = tbl_rc[c].apply(lambda v: f"{v:.1f}%")
                        _df_excel(tbl_rc, "recuperacion_segmento_campana.xlsx")

        # ── Gestión Damas ─────────────────────────────────────────────────────
        with sub[2]:
            _banner("📞", "Gestión de Damas", "Análisis de contacto y no contacto por segmento y geografía")
            if not contacto_col:
                st.info("Configura la columna Estatus de Llamada (Col. AN) para ver esta sección.")
            else:
                estatus_upper = df[contacto_col].astype(str).str.strip().str.upper()
                n_contacto    = int(estatus_upper.eq("CONTACTO").sum())
                n_no_contacto = int(estatus_upper.eq("NO CONTACTO").sum())
                n_otros       = total_cuentas - n_contacto - n_no_contacto

                m1, m2, m3 = st.columns(3)
                m1.metric("Contacto",    f"{n_contacto:,}",    delta=f"{n_contacto/total_cuentas*100:.1f}%")
                m2.metric("No Contacto", f"{n_no_contacto:,}", delta=f"{n_no_contacto/total_cuentas*100:.1f}%")
                m3.metric("Sin Estatus", f"{n_otros:,}",       delta=f"{n_otros/total_cuentas*100:.1f}%")

                _section("Contacto General")
                c1, c2 = st.columns(2)
                with c1:
                    labels_c = ["Contacto", "No Contacto", "Sin Estatus"]
                    values_c = [n_contacto, n_no_contacto, n_otros]
                    colors_c = [COLORS["success"], COLORS["danger"], COLORS["muted"]]
                    pairs = [(l, v, c) for l, v, c in zip(labels_c, values_c, colors_c) if v > 0]
                    if pairs:
                        ls, vs, cs = zip(*pairs)
                        fig = go.Figure(go.Pie(
                            labels=ls, values=vs,
                            marker=dict(colors=cs, line=dict(color=COLORS["bg"], width=2)),
                            hole=0.45, textinfo="label+percent+value",
                            textposition="outside",
                            textfont=dict(size=11, color=COLORS["text2"]),
                        ))
                        fig.update_layout(**PLOTLY_LAYOUT, title=dict(text="Distribución de Contacto General", font=dict(size=14, color=COLORS["primary"], weight=600)),
                                          legend=dict(orientation="h", yanchor="top", y=-0.08))
                        _chart_card(fig)

                with c2:
                    g_c_seg = _grp_contacto(df, "segmento", cols)
                    if g_c_seg is not None:
                        fig = go.Figure()
                        fig.add_bar(name="Contacto", x=g_c_seg["segmento"], y=g_c_seg["Contacto"],
                                    marker_color=COLORS["success"],
                                    text=g_c_seg["Contacto"].map(lambda v: f"{v:,}"),
                                    textposition="outside")
                        fig.add_bar(name="No Contacto", x=g_c_seg["segmento"], y=g_c_seg["NoContacto"],
                                    marker_color=COLORS["danger"],
                                    text=g_c_seg["NoContacto"].map(lambda v: f"{v:,}"),
                                    textposition="outside")
                        fig.update_layout(
                            **PLOTLY_LAYOUT, barmode="group",
                            title=dict(text="Contacto vs No Contacto por Segmento", font=dict(size=14, color=COLORS["primary"], weight=600)),
                            xaxis=dict(**_AXIS_DEFAULTS, title="Segmento"),
                            yaxis=dict(**_AXIS_DEFAULTS, title="Cuentas"),
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                        )
                        _chart_card(fig)

                _section("Contacto por Geografía")
                c1, c2 = st.columns(2)
                with c1:
                    g_c_ruta = _grp_contacto(df, "ruta", cols)
                    if g_c_ruta is not None:
                        g_c_ruta = g_c_ruta.sort_values("PctContacto")
                        _chart_card(_hbar(g_c_ruta, "PctContacto", "ruta",
                                          "% Contacto por Ruta", "% Contacto",
                                          color_fn=_color_pct))
                    else:
                        st.info("Sin columna de Ruta.")
                with c2:
                    g_c_div = _grp_contacto(df, "division", cols)
                    if g_c_div is not None:
                        g_c_div = g_c_div.sort_values("PctContacto", ascending=False)
                        fig = go.Figure(go.Bar(
                            x=g_c_div["division"].astype(str), y=g_c_div["PctContacto"],
                            marker_color=[_color_pct(v) for v in g_c_div["PctContacto"]],
                            text=[f"{v:.1f}%" for v in g_c_div["PctContacto"]],
                            textposition="outside",
                        ))
                        fig.update_layout(
                            **PLOTLY_LAYOUT, title=dict(text="% Contacto por División", font=dict(size=14, color=COLORS["primary"], weight=600)),
                            xaxis=dict(**_AXIS_DEFAULTS, title="División"),
                            yaxis=dict(**_AXIS_DEFAULTS, title="% Contacto"),
                        )
                        _chart_card(fig)
                    else:
                        st.info("Sin columna de División.")

                _section("Contacto por Zona — todas las zonas")
                g_c_zona = _grp_contacto(df, "zona", cols)
                if g_c_zona is not None:
                    g_c_zona = g_c_zona.sort_values("PctContacto", ascending=False)
                    tabla = g_c_zona[["zona", "Total", "Contacto", "NoContacto", "PctContacto"]].copy()
                    tabla["PctContacto"] = tabla["PctContacto"].apply(lambda v: f"{v:.1f}%")
                    tabla.columns = ["Zona", "Total", "Contacto", "No Contacto", "% Contacto"]
                    _df_excel(tabla, "contacto_por_zona.xlsx", df_base=df)

                if last4 and camp_col_real:
                    _section("📅 Comparativo — Contactación × Últimas 4 Campañas")
                    # % Contacto por campaña
                    rows_ct = []
                    for c in reversed(last4):
                        dfc = df[df[camp_col_real].astype(str) == c]
                        n   = len(dfc)
                        ct  = int(dfc[contacto_col].astype(str).str.strip().str.upper().eq("CONTACTO").sum())
                        nct = n - ct
                        pct = ct / n * 100 if n > 0 else 0
                        rows_ct.append({"Campaña": c, "Total": f"{n:,}", "Contacto": f"{ct:,}",
                                        "No Contacto": f"{nct:,}", "% Contacto": f"{pct:.1f}%"})
                    tbl_ct = pd.DataFrame(rows_ct)
                    _df_excel(tbl_ct, "contacto_ultimas4_campanas.xlsx", df_base=df)

                    fig_ct = go.Figure()
                    for i, c in enumerate(reversed(last4)):
                        dfc = df[df[camp_col_real].astype(str) == c]
                        n   = len(dfc)
                        ct  = int(dfc[contacto_col].astype(str).str.strip().str.upper().eq("CONTACTO").sum())
                        pct = ct / n * 100 if n > 0 else 0
                        fig_ct.add_bar(name=f"Campaña {c}", x=[c], y=[pct],
                                       marker_color=CAMP_COLORS[i % 4],
                                       text=[f"{pct:.1f}%"], textposition="outside")
                    fig_ct.update_layout(**PLOTLY_LAYOUT,
                                         title=dict(text="% Contacto por Campaña — Últimas 4", font=dict(size=14, color=COLORS["primary"], weight=600)),
                                         xaxis=dict(**_AXIS_DEFAULTS, title=dict(text="Campaña", font=dict(size=14, color=COLORS["primary"], weight=600)), type="category"),
                                         yaxis=dict(**_AXIS_DEFAULTS, title="% Contacto"),
                                         showlegend=False)
                    _chart_card(fig_ct)

                    g_ct_seg = _grp_camp(df, "segmento", cols, last4)
                    if g_ct_seg is not None:
                        # Recalcular para contacto
                        dfc2 = df[df[camp_col_real].astype(str).isin(last4)].copy()
                        dfc2["_ct"] = dfc2[contacto_col].astype(str).str.strip().str.upper().eq("CONTACTO").astype(int)
                        seg_col_r = cols.get("segmento")
                        if seg_col_r:
                            gc2 = dfc2.groupby([seg_col_r, camp_col_real]).agg(
                                Total=(seg_col_r, "count"), Contacto=("_ct", "sum")).reset_index()
                            gc2.columns = ["segmento", "Campaña", "Total", "Contacto"]
                            gc2["PctContacto"] = np.where(gc2["Total"] > 0, gc2["Contacto"] / gc2["Total"] * 100, 0)
                            camp_order2 = list(reversed(last4))
                            color_map2 = {c: CAMP_COLORS[i % 4] for i, c in enumerate(camp_order2)}
                            fig2 = px.bar(gc2, x="segmento", y="PctContacto", color="Campaña",
                                          barmode="group",
                                          color_discrete_map=color_map2,
                                          text=gc2["PctContacto"].map(lambda v: f"{v:.1f}%"),
                                          category_orders={"Campaña": camp_order2},
                                          labels={"PctContacto": "% Contacto", "segmento": "Segmento"},
                                          title="% Contacto por Segmento — Últimas 4 Campañas")
                            fig2.update_traces(textposition="outside")
                            fig2.update_layout(**PLOTLY_LAYOUT,
                                               xaxis=dict(**_AXIS_DEFAULTS, title="Segmento"),
                                               yaxis=dict(**_AXIS_DEFAULTS, title="% Contacto"),
                                               legend=dict(title=dict(text="Campaña", font=dict(size=14, color=COLORS["primary"], weight=600)), orientation="h",
                                                           yanchor="bottom", y=1.02, xanchor="right", x=1))
                            _chart_card(fig2)

        # ── Dictaminación ─────────────────────────────────────────────────────
        with sub[3]:
            _banner("📋", "Dictaminación y Visitas", "Resultados de llamadas (Col. AM) y visitas de gestor (Col. AO)")

            # Col AM: "Dictaminacion de llamada" — usar promesa o dictaminacion como fallback
            dictam_col = cols.get("promesa") or cols.get("dictaminacion")
            visita_col_real = cols.get("visita")

            if not dictam_col and not visita_col_real:
                st.info("No se detectó la columna de Dictaminación (Col. AM) ni Visitas Gestor (Col. AO). "
                        "Usa el panel ⚙️ Ajustar columnas para asignarlas manualmente.")

            if dictam_col:
                raw_d = df[dictam_col].fillna("Sin Dictaminación").astype(str).str.strip()
                raw_d = raw_d[~raw_d.str.lower().isin(["nan", "none", ""])]
                all_counts = raw_d.value_counts()
                top5_vals  = all_counts.head(5).index.tolist()

                _section("Distribución de Dictaminaciones")
                c1, c2 = st.columns(2)
                with c1:
                    top10_d = all_counts.head(10).sort_values()
                    fig = go.Figure(go.Bar(
                        x=top10_d.values, y=top10_d.index, orientation="h",
                        marker_color=CAT_COLORS[0],
                        text=[f"{v:,}" for v in top10_d.values], textposition="outside",
                    ))
                    fig.update_layout(
                        **PLOTLY_LAYOUT, title=dict(text="Top 10 Dictaminaciones de Llamada", font=dict(size=14, color=COLORS["primary"], weight=600)),
                        xaxis=dict(**_AXIS_DEFAULTS, title=dict(text="Cuentas", font=dict(size=14, color=COLORS["primary"], weight=600)),
                                   range=[0, top10_d.max() * 1.4]),
                        yaxis=dict(**_AXIS_DEFAULTS),
                        height=max(300, len(top10_d) * 32 + 90),
                    )
                    _chart_card(fig)
                with c2:
                    top6 = all_counts.head(6)
                    otros = all_counts[6:].sum()
                    if otros > 0:
                        top6 = pd.concat([top6, pd.Series({"Otros": otros})])
                    _chart_card(_pie_fig(top6.index.tolist(), top6.values.tolist(),
                                         "Distribución General de Dictaminaciones"))

                # Tabla completa de dictaminaciones
                tbl_dict = all_counts.reset_index()
                tbl_dict.columns = ["Dictaminación", "Cuentas"]
                tbl_dict["% del Total"] = (tbl_dict["Cuentas"] / len(df) * 100).apply(lambda v: f"{v:.1f}%")
                _df_excel(tbl_dict, "dictaminaciones_completo.xlsx", df_base=df)

                def _dictam_geo_chart(geo_key, title, max_geo=15):
                    geo_col = cols.get(geo_key)
                    if not geo_col or geo_col not in df.columns:
                        st.info(f"Sin columna de {geo_key.title()}.")
                        return
                    df2 = df[[dictam_col, geo_col]].copy()
                    df2["__d__"] = df2[dictam_col].fillna("Sin Dictaminación").astype(str).str.strip()
                    df2["__g__"] = df2[geo_col].astype(str)
                    df2 = df2[df2["__d__"].isin(top5_vals)]

                    # Top geos by volume
                    top_geos = (
                        df2.groupby("__g__").size()
                        .sort_values(ascending=False)
                        .head(max_geo).index.tolist()
                    )
                    df2 = df2[df2["__g__"].isin(top_geos)]

                    cross = df2.groupby(["__g__", "__d__"]).size().reset_index(name="Cuentas")
                    if cross.empty:
                        st.info("Sin datos suficientes.")
                        return

                    # Pivot: geos × dictaminaciones
                    piv = cross.pivot_table(
                        index="__g__", columns="__d__", values="Cuentas", fill_value=0
                    )
                    # Sort rows by total (highest at top)
                    piv = piv.loc[piv.sum(axis=1).sort_values(ascending=True).index]

                    z_vals = piv.values.tolist()
                    y_labels = [f"{geo_key[:3].upper()}-{g}" for g in piv.index.tolist()]
                    x_labels = piv.columns.tolist()

                    # Annotation text
                    annots = []
                    for ri, row in enumerate(z_vals):
                        for ci, val in enumerate(row):
                            annots.append(dict(
                                x=x_labels[ci], y=y_labels[ri],
                                text=str(int(val)) if val > 0 else "",
                                font=dict(size=10, color="#ffffff" if val > (piv.values.max() * 0.45) else COLORS["text2"]),
                                showarrow=False,
                            ))

                    fig = go.Figure(go.Heatmap(
                        z=z_vals,
                        x=x_labels,
                        y=y_labels,
                        colorscale=[
                            [0.0,  "#f0efec"],
                            [0.15, "#cde2fb"],
                            [0.4,  "#86b6ef"],
                            [0.7,  "#2a78d6"],
                            [1.0,  "#1e3a5f"],
                        ],
                        showscale=True,
                        colorbar=dict(
                            title=dict(text="Cuentas", font=dict(size=11, color=COLORS["text2"])),
                            tickfont=dict(size=10, color=COLORS["muted"]),
                            thickness=12, len=0.8,
                        ),
                        hovertemplate="<b>%{y}</b><br>%{x}<br>Cuentas: <b>%{z}</b><extra></extra>",
                        xgap=2, ygap=2,
                    ))
                    fig.update_layout(_layout(
                        title=dict(text=title, font=dict(size=14, color=COLORS["primary"], weight=600)),
                        xaxis=dict(
                            tickfont=dict(size=10, color=COLORS["text2"]),
                            side="bottom", tickangle=-30,
                            showgrid=False, zeroline=False, showline=False,
                        ),
                        yaxis=dict(
                            type="category",
                            tickfont=dict(size=10, color=COLORS["text2"]),
                            showgrid=False, zeroline=False, showline=False,
                            autorange="reversed",
                        ),
                        annotations=annots,
                        height=max(320, len(top_geos) * 34 + 120),
                        margin=dict(l=90, r=80, t=60, b=90),
                    ))
                    _chart_card(fig)

                    # Tabla pivot descargable
                    piv_dl = piv.copy().reset_index()
                    piv_dl.columns.name = None
                    piv_dl = piv_dl.rename(columns={"__g__": geo_key.title()})
                    piv_dl["Total"] = piv_dl.iloc[:, 1:].sum(axis=1)
                    piv_dl = piv_dl.sort_values("Total", ascending=False)
                    _df_excel(piv_dl, f"dictam_{geo_key}.xlsx", df_base=df)

                _section("Dictaminaciones por Geografía (Top 5 resultados)")
                c1, c2 = st.columns(2)
                with c1:
                    _dictam_geo_chart("ruta", "Dictaminaciones por Ruta")
                with c2:
                    _dictam_geo_chart("division", "Dictaminaciones por División")

                _dictam_geo_chart("zona", "Dictaminaciones por Zona")

            _section("Resultados de Visitas de Gestor")
            if visita_col_real:
                vis_vals = df[visita_col_real].fillna("").astype(str).str.strip()
                visited  = ~vis_vals.str.lower().isin(["", "nan", "none", "0", "0.0"])
                total_vis = int(visited.sum())
                if total_vis > 0:
                    vc  = vis_vals[visited].value_counts()
                    vp  = (vc / total_vis * 100).round(1)
                    vdf = pd.DataFrame({"Resultado": vc.index, "Cuentas": vc.values,
                                        "Pct": vp.values}).head(15)
                    vdf = vdf.sort_values("Cuentas")
                    fig = go.Figure(go.Bar(
                        x=vdf["Pct"], y=vdf["Resultado"], orientation="h",
                        marker_color=CAT_COLORS[1],
                        text=[f"{p:.1f}%  ({c:,})" for p, c in zip(vdf["Pct"], vdf["Cuentas"])],
                        textposition="outside",
                    ))
                    fig.update_layout(
                        **PLOTLY_LAYOUT,
                        title=f"Resultados de Visitas — % del total ({total_vis:,} visitas)",
                        xaxis=dict(**_AXIS_DEFAULTS, title=dict(text="% del Total de Visitas", font=dict(size=14, color=COLORS["primary"], weight=600)),
                                   range=[0, min(vdf["Pct"].max() * 1.45, 100)]),
                        yaxis=dict(**_AXIS_DEFAULTS),
                        height=max(300, len(vdf) * 30 + 90),
                    )
                    _chart_card(fig)
                else:
                    st.info("No se encontraron visitas registradas.")
            else:
                st.info("Configura la columna Visitas Gestor (Col. AO) para ver este gráfico.")

            if last4 and camp_col_real and dictam_col:
                _section("📅 Comparativo — Dictaminaciones × Últimas 4 Campañas")
                rows_d = []
                for c in reversed(last4):
                    dfc = df[df[camp_col_real].astype(str) == c]
                    top3 = dfc[dictam_col].fillna("").astype(str).str.strip().value_counts().head(3)
                    row = {"Campaña": c, "Total Cuentas": f"{len(dfc):,}"}
                    for j, (k, v) in enumerate(top3.items()):
                        row[f"#{j+1} Dictaminación"] = k
                        row[f"#{j+1} Cuentas"] = f"{v:,}"
                    rows_d.append(row)
                _df_excel(pd.DataFrame(rows_d), "dictaminacion_ultimas4_campanas.xlsx", df_base=df)

        # ── Alertas ───────────────────────────────────────────────────────────
        with sub[4]:
            _banner("⚠️", "Alertas", "Unidades con recuperación por debajo del umbral")
            umbral = st.slider("Umbral de % de recuperación", 0, 100, 30, step=5)
            any_alert = False
            for col_key, label, fn in [
                ("zona",     "Zona",    st.error),
                ("ruta",     "Ruta",    st.warning),
                ("region",   "Región",  st.warning),
                ("division", "División", st.warning),
            ]:
                g = _grp(df, col_key, cols)
                if g is None:
                    continue
                bajo = g[g["PctRec"] < umbral].sort_values("PctRec")
                if len(bajo):
                    any_alert = True
                    fn(f"{len(bajo)} unidad(es) de **{label}** por debajo del {umbral}%")
                    tabla = bajo[[col_key, "Cuentas", "Asignado", "Pagado", "PctRec"]].copy()
                    tabla["Asignado"] = tabla["Asignado"].apply(fmt_currency)
                    tabla["Pagado"]   = tabla["Pagado"].apply(fmt_currency)
                    tabla["PctRec"]   = tabla["PctRec"].apply(lambda v: f"{v:.1f}%")
                    tabla.columns = [label, "Cuentas", "Asignado", "Recuperado", "% Recuperación"]
                    _df_excel(tabla, f"alertas_{col_key}.xlsx", df_base=df)
            if not any_alert:
                st.success(f"✅ Todas las unidades superan el {umbral}% de recuperación.")

    # ══════════════════════════════════════════════════════════════════════════
    # DIRECCIONES
    # ══════════════════════════════════════════════════════════════════════════
    with main_tabs[1]:
        dir_sub = st.tabs(["🏠 Domicilios", "📦 Distribución", "👥 Visitas"])

        # ── helpers locales reutilizables para las dos subpestañas ────────────
        def _geo_cat_chart(df_in, cat_col, geo_key, top_n, chart_title, geo_label="", max_geo=10):
            """Horizontal stacked bar: top_n categorías × top max_geo unidades geográficas."""
            geo_col = cols.get(geo_key)
            if not geo_col or geo_col not in df_in.columns:
                st.info(f"Sin columna de {geo_key.title()}.")
                return
            geo_label = geo_label or geo_key.title()

            # Top categorías
            top_cats = (
                df_in[cat_col].fillna("Sin Info").astype(str).str.strip()
                .value_counts().head(top_n).index.tolist()
            )
            # Top unidades geográficas por volumen total
            top_geos = (
                df_in[geo_col].astype(str).value_counts()
                .head(max_geo).index.tolist()
            )

            df2 = df_in.copy()
            df2["__geo__"] = df2[geo_col].astype(str)
            df2["__cat__"] = df2[cat_col].fillna("Sin Info").astype(str).str.strip()
            df2 = df2[df2["__geo__"].isin(top_geos) & df2["__cat__"].isin(top_cats)]

            cross = df2.groupby(["__geo__", "__cat__"]).size().reset_index(name="Cuentas")
            cross.columns = [geo_key, "Categoria", "Cuentas"]
            if cross.empty:
                st.info("Sin datos suficientes.")
                return

            # Ordenar geos de mayor a menor total
            geo_order = (
                cross.groupby(geo_key)["Cuentas"].sum()
                .sort_values().index.tolist()
            )

            fig = px.bar(
                cross, x="Cuentas", y=geo_key, color="Categoria",
                barmode="stack", text="Cuentas",
                orientation="h",
                category_orders={geo_key: geo_order},
                color_discrete_sequence=CAT_COLORS,
                labels={geo_key: geo_label, "Cuentas": "Cuentas", "Categoria": "Resultado"},
            )
            fig.update_traces(textposition="inside", textfont=dict(size=10, color="#ffffff"))
            fig.update_layout(
                **PLOTLY_LAYOUT,
                title=dict(text=chart_title, font=dict(size=14, color=COLORS["primary"], weight=600)),
                xaxis=dict(**_AXIS_DEFAULTS, title="Cuentas"),
                yaxis=dict(
                    type="category",
                    categoryorder="array",
                    categoryarray=geo_order,
                    gridcolor=COLORS["grid"],
                    zeroline=False,
                    showline=False,
                    tickfont=dict(size=12, color=COLORS["text2"]),
                ),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                            font=dict(size=10, color=COLORS["text2"])),
                height=max(380, len(geo_order) * 46 + 110),
                bargap=0.22,
            )
            _chart_card(fig)

            # Tabla pivot descargable
            pivot = cross.pivot_table(
                index=geo_key, columns="Categoria", values="Cuentas", fill_value=0
            ).reset_index()
            pivot.columns.name = None
            pivot["Total"] = pivot.iloc[:, 1:].sum(axis=1)
            pivot = pivot.sort_values("Total", ascending=False)
            safe = chart_title[:30].replace(" ", "_").lower()
            _df_excel(pivot, f"{geo_key}_{safe}.xlsx", df_base=df_in)

        def _camp_cat_section(df_in, cat_col, file_prefix, top_n=3):
            """Tabla + gráfica comparativa de últimas 4 campañas para col. categórica."""
            if not last4 or not camp_col_real or cat_col not in df_in.columns:
                return
            _section("📅 Comparativo — Últimas 4 Campañas")
            top_cats = (
                df_in[cat_col].fillna("Sin Info").astype(str).str.strip()
                .value_counts().head(top_n).index.tolist()
            )
            rows = []
            for c in reversed(last4):
                dfc = df_in[df_in[camp_col_real].astype(str) == c]
                n   = len(dfc)
                row = {"Campaña": c, "Total": f"{n:,}"}
                sc  = dfc[cat_col].fillna("Sin Info").astype(str).str.strip().value_counts()
                for cat in top_cats:
                    cnt = sc.get(cat, 0)
                    row[cat] = f"{cnt:,}  ({cnt/n*100:.1f}%)" if n > 0 else "0"
                rows.append(row)
            _df_excel(pd.DataFrame(rows), f"{file_prefix}_ultimas4_campanas.xlsx", df_base=df_in)

            df4 = df_in[df_in[camp_col_real].astype(str).isin(last4)].copy()
            df4["__cat__"] = df4[cat_col].fillna("Sin Info").astype(str).str.strip()
            df4 = df4[df4["__cat__"].isin(top_cats)]
            cross4 = df4.groupby([camp_col_real, "__cat__"]).size().reset_index(name="Cuentas")
            cross4.columns = ["Campaña", "Categoria", "Cuentas"]
            if len(cross4):
                camp_order_d = list(reversed(last4))
                color_map_d  = {c: CAMP_COLORS[i % 4] for i, c in enumerate(camp_order_d)}
                fig = px.bar(
                    cross4, x="Campaña", y="Cuentas", color="Categoria",
                    barmode="group", text="Cuentas",
                    category_orders={"Campaña": camp_order_d},
                    labels={"Campaña": "Campaña", "Cuentas": "Cuentas", "Categoria": "Resultado"},
                    title=f"Top {top_n} Resultados — Últimas 4 Campañas",
                )
                fig.update_traces(textposition="outside")
                fig.update_layout(
                    **PLOTLY_LAYOUT,
                    xaxis=dict(**_AXIS_DEFAULTS, title=dict(text="Campaña", font=dict(size=14, color=COLORS["primary"], weight=600)), type="category"),
                    yaxis=dict(**_AXIS_DEFAULTS, title="Cuentas"),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                _chart_card(fig)

        # ── Domicilios (Col Z — DescSituacion) ───────────────────────────────
        with dir_sub[0]:
            _banner("🏠", "Domicilios", "Calidad y estatus de los domicilios de la cartera asignada")
            situacion_col = cols.get("situacion")

            if not situacion_col:
                st.info("No se detectó una columna de situación de domicilio. "
                        "Verifica que exista una columna 'DescSituacion', 'Situacion' o 'Estatus'.")
            else:
                sit_raw_z   = df[situacion_col].fillna("Sin Información").astype(str).str.strip()
                sit_cnt_z   = sit_raw_z.value_counts()
                total_dom_z = len(df)

                top4_z = sit_cnt_z.head(4)
                mcs_z  = st.columns(min(len(top4_z), 4))
                for mc, (lbl, cnt) in zip(mcs_z, top4_z.items()):
                    mc.metric(lbl, f"{cnt:,}", delta=f"{cnt/total_dom_z*100:.1f}%")

                _section("Distribución de Situación de Domicilio")
                c1, c2 = st.columns(2)
                with c1:
                    top6_z  = sit_cnt_z.head(6)
                    otros_z = sit_cnt_z[6:].sum()
                    if otros_z > 0:
                        top6_z = pd.concat([top6_z, pd.Series({"Otros": otros_z})])
                    _chart_card(_pie_fig(top6_z.index.tolist(), top6_z.values.tolist(),
                                         "Distribución de Situación de Domicilio"))
                with c2:
                    bar_z = sit_cnt_z.head(10).sort_values()
                    fig = go.Figure(go.Bar(
                        x=bar_z.values, y=bar_z.index, orientation="h",
                        marker_color=CAT_COLORS[0],
                        text=[f"{v:,}  ({v/total_dom_z*100:.1f}%)" for v in bar_z.values],
                        textposition="outside",
                    ))
                    fig.update_layout(
                        **PLOTLY_LAYOUT, title=dict(text="Top 10 Situaciones de Domicilio", font=dict(size=14, color=COLORS["primary"], weight=600)),
                        xaxis=dict(**_AXIS_DEFAULTS, title=dict(text="Cuentas", font=dict(size=14, color=COLORS["primary"], weight=600)),
                                   range=[0, bar_z.max() * 1.5]),
                        yaxis=dict(**_AXIS_DEFAULTS),
                        height=max(280, len(bar_z) * 30 + 90),
                    )
                    _chart_card(fig)

                _section("Situación de Domicilio por Segmento y Geografía")
                seg_col_z = cols.get("segmento")
                if seg_col_z and seg_col_z in df.columns:
                    top5_z = sit_cnt_z.head(5).index.tolist()
                    cross_z = df[df[situacion_col].isin(top5_z)].groupby(
                        [situacion_col, seg_col_z]).size().reset_index(name="Cuentas")
                    cross_z.columns = ["Situacion", "Segmento", "Cuentas"]
                    if len(cross_z):
                        fig = px.bar(cross_z, x="Situacion", y="Cuentas", color="Segmento",
                                     barmode="group", text="Cuentas",
                                     labels={"Situacion": "Situación", "Cuentas": "Cuentas"},
                                     title="Top 5 Situaciones de Domicilio por Segmento de Mora")
                        fig.update_traces(textposition="outside")
                        fig.update_layout(**PLOTLY_LAYOUT,
                                          xaxis=dict(**_AXIS_DEFAULTS, title="Situación"),
                                          yaxis=dict(**_AXIS_DEFAULTS, title="Cuentas"),
                                          legend=dict(title=dict(text="Segmento", font=dict(size=14, color=COLORS["primary"], weight=600)), orientation="h",
                                                      yanchor="bottom", y=1.02, xanchor="right", x=1))
                        _chart_card(fig)

                div_col_z = cols.get("division")
                if div_col_z and div_col_z in df.columns:
                    top3_z = sit_cnt_z.head(3).index.tolist()
                    cross_dz = df[df[situacion_col].isin(top3_z)].groupby(
                        [situacion_col, div_col_z]).size().reset_index(name="Cuentas")
                    cross_dz.columns = ["Situacion", "Division", "Cuentas"]
                    if len(cross_dz):
                        fig = px.bar(cross_dz, x="Division", y="Cuentas", color="Situacion",
                                     barmode="group", text="Cuentas",
                                     labels={"Division": "División", "Cuentas": "Cuentas"},
                                     title="Top 3 Situaciones de Domicilio por División")
                        fig.update_traces(textposition="outside")
                        fig.update_layout(**PLOTLY_LAYOUT,
                                          xaxis=dict(**_AXIS_DEFAULTS, title="División"),
                                          yaxis=dict(**_AXIS_DEFAULTS, title="Cuentas"),
                                          legend=dict(title=dict(text="Situación", font=dict(size=14, color=COLORS["primary"], weight=600)), orientation="h",
                                                      yanchor="bottom", y=1.02, xanchor="right", x=1))
                        _chart_card(fig)

                _section("Resumen de Situación de Domicilio")
                tabla_z = sit_cnt_z.reset_index()
                tabla_z.columns = ["Situación", "Cuentas"]
                tabla_z["% del Total"] = (tabla_z["Cuentas"] / total_dom_z * 100).apply(lambda v: f"{v:.1f}%")
                _df_excel(tabla_z, "situacion_domicilio.xlsx", df_base=df,
                          base_label=f"📋 Cartera completa ({len(df):,} reg.)",
                          base_filename="cartera_domicilios.xlsx")

                if last4 and camp_col_real:
                    _section("📅 Comparativo — Situación de Domicilio × Últimas 4 Campañas")
                    top3_z2 = sit_cnt_z.head(3).index.tolist()
                    rows_z = []
                    for c in reversed(last4):
                        dfc = df[df[camp_col_real].astype(str) == c]
                        n   = len(dfc)
                        row = {"Campaña": c, "Total": f"{n:,}"}
                        sc  = dfc[situacion_col].fillna("Sin Info").astype(str).str.strip().value_counts()
                        for sit in top3_z2:
                            cnt = sc.get(sit, 0)
                            row[sit] = f"{cnt:,}  ({cnt/n*100:.1f}%)" if n > 0 else "0"
                        rows_z.append(row)
                    _df_excel(pd.DataFrame(rows_z), "direcciones_ultimas4_campanas.xlsx", df_base=df,
                              base_label=f"📋 Cartera completa ({len(df):,} reg.)",
                              base_filename="cartera_domicilios_ultimas4.xlsx")

                    cross_cz = df[df[camp_col_real].astype(str).isin(last4)].copy()
                    cross_cz = cross_cz[cross_cz[situacion_col].isin(top3_z2)]
                    cross_cz = cross_cz.groupby([situacion_col, camp_col_real]).size().reset_index(name="Cuentas")
                    cross_cz.columns = ["Situacion", "Campaña", "Cuentas"]
                    if len(cross_cz):
                        camp_ord_z  = list(reversed(last4))
                        color_map_z = {c: CAMP_COLORS[i % 4] for i, c in enumerate(camp_ord_z)}
                        fig = px.bar(cross_cz, x="Situacion", y="Cuentas", color="Campaña",
                                     barmode="group", text="Cuentas",
                                     color_discrete_map=color_map_z,
                                     category_orders={"Campaña": camp_ord_z},
                                     labels={"Situacion": "Situación", "Cuentas": "Cuentas"},
                                     title="Top 3 Situaciones de Domicilio — Últimas 4 Campañas")
                        fig.update_traces(textposition="outside")
                        fig.update_layout(**PLOTLY_LAYOUT,
                                          xaxis=dict(**_AXIS_DEFAULTS, title="Situación"),
                                          yaxis=dict(**_AXIS_DEFAULTS, title="Cuentas"),
                                          legend=dict(title=dict(text="Campaña", font=dict(size=14, color=COLORS["primary"], weight=600)), orientation="h",
                                                      yanchor="bottom", y=1.02, xanchor="right", x=1))
                        _chart_card(fig)

        # ── Distribución (Col AB — DescSituacionCie) ──────────────────────────
        with dir_sub[1]:
            _banner("📦", "Distribución", "Situación de entrega de pedidos — Col. AB (DescSituacionCie)")
            sit_cie_col = cols.get("situacion_cie")

            if not sit_cie_col:
                st.info(
                    "No se detectó la columna DescSituacionCie (Col. AB). "
                    "Usa el panel ⚙️ Ajustar columnas para asignarla manualmente."
                )
            else:
                sit_raw    = df[sit_cie_col].fillna("Sin Información").astype(str).str.strip()
                sit_counts = sit_raw.value_counts()
                total_dom  = len(df)

                # KPI tarjetas
                top4_sit = sit_counts.head(4)
                mcs = st.columns(min(len(top4_sit), 4))
                for mc, (lbl, cnt) in zip(mcs, top4_sit.items()):
                    mc.metric(lbl, f"{cnt:,}", delta=f"{cnt/total_dom*100:.1f}%")

                _section("Distribución de Situación de Entrega")
                c1, c2 = st.columns(2)
                with c1:
                    top6 = sit_counts.head(6)
                    otros = sit_counts[6:].sum()
                    if otros > 0:
                        top6 = pd.concat([top6, pd.Series({"Otros": otros})])
                    _chart_card(_pie_fig(top6.index.tolist(), top6.values.tolist(),
                                         "Participación por Situación de Entrega"))
                with c2:
                    bar_d = sit_counts.head(10).sort_values()
                    fig = go.Figure(go.Bar(
                        x=bar_d.values, y=bar_d.index, orientation="h",
                        marker=dict(color=CAT_COLORS[0], line=dict(width=0)),
                        text=[f"{v:,}  ({v/total_dom*100:.1f}%)" for v in bar_d.values],
                        textposition="outside",
                        textfont=dict(size=11, color=COLORS["text2"]),
                    ))
                    fig.update_layout(
                        **PLOTLY_LAYOUT, title=dict(text="Ranking de Situaciones de Entrega (Top 10)", font=dict(size=14, color=COLORS["primary"], weight=600)),
                        xaxis=dict(**_AXIS_DEFAULTS, title=dict(text="Pedidos", font=dict(size=14, color=COLORS["primary"], weight=600)),
                                   range=[0, bar_d.max() * 1.5]),
                        yaxis=dict(**_AXIS_DEFAULTS),
                        height=max(300, len(bar_d) * 32 + 90),
                    )
                    _chart_card(fig)

                _section("Concentración — Tabla Completa de Situaciones")
                tabla_sit = sit_counts.reset_index()
                tabla_sit.columns = ["Situación de Entrega", "Pedidos"]
                tabla_sit["% del Total"] = (tabla_sit["Pedidos"] / total_dom * 100).apply(lambda v: f"{v:.1f}%")
                st.dataframe(tabla_sit, use_container_width=True, hide_index=True)
                fecha_hoy = pd.Timestamp.today().strftime("%Y%m%d")
                _df_excel(df.copy(), f"detalle_situaciones_entrega_{fecha_hoy}.xlsx",
                          btn_label=f"📥 Descargar detalle completo ({len(df):,} registros)")

                _section("Top 10 Zonas — Entregado por Gerente")
                zona_col_d = cols.get("zona")
                if zona_col_d and zona_col_d in df.columns:
                    _gerente_mask = df[sit_cie_col].fillna("").astype(str).str.upper().str.contains("GERENTE", na=False)
                    # Total asignadas por zona (denominador del %)
                    _total_zona = df.groupby(zona_col_d).size().reset_index(name="Total Asignadas")
                    g_ger = (
                        df[_gerente_mask]
                        .groupby(zona_col_d)
                        .size()
                        .reset_index(name="Pedidos")
                        .merge(_total_zona, on=zona_col_d, how="left")
                        .sort_values("Pedidos", ascending=False)
                        .head(10)
                        .sort_values("Pedidos")
                    )
                    g_ger["Pct"] = np.where(
                        g_ger["Total Asignadas"] > 0,
                        g_ger["Pedidos"] / g_ger["Total Asignadas"] * 100,
                        0,
                    )
                    if len(g_ger):
                        total_ger = int(_gerente_mask.sum())
                        # Forzar etiquetas como string para eje categórico
                        g_ger["Zona_str"] = "Zona " + g_ger[zona_col_d].astype(str)
                        fig = go.Figure(go.Bar(
                            x=g_ger["Pedidos"],
                            y=g_ger["Zona_str"],
                            orientation="h",
                            marker_color=CAT_COLORS[0],
                            text=[f"{ped:,}  ({pct:.1f}%)" for ped, pct in zip(g_ger["Pedidos"], g_ger["Pct"])],
                            textposition="outside",
                        ))
                        fig.update_layout(
                            **PLOTLY_LAYOUT,
                            title=f"Top 10 Zonas — Entregado por Gerente ({total_ger:,} pedidos)",
                            xaxis=dict(**_AXIS_DEFAULTS, title=dict(text="Pedidos", font=dict(size=14, color=COLORS["primary"], weight=600)),
                                       range=[0, g_ger["Pedidos"].max() * 1.45]),
                            yaxis=dict(
                                type="category",
                                categoryorder="array",
                                categoryarray=g_ger["Zona_str"].tolist(),
                                gridcolor=COLORS["grid"],
                                zeroline=False,
                                showline=False,
                                tickfont=dict(size=13),
                            ),
                            height=max(380, len(g_ger) * 46 + 90),
                            bargap=0.3,
                        )
                        _chart_card(fig)

                        # Tabla completa de TODAS las zonas
                        total_por_zona = (
                            df.groupby(zona_col_d)
                            .size()
                            .reset_index(name="Total Asignadas")
                        )
                        gerente_por_zona = (
                            df[_gerente_mask]
                            .groupby(zona_col_d)
                            .size()
                            .reset_index(name="Entregado Gerente")
                            .sort_values("Entregado Gerente", ascending=False)
                        )
                        todas_zonas = total_por_zona.merge(gerente_por_zona, on=zona_col_d, how="left")
                        todas_zonas["Entregado Gerente"] = todas_zonas["Entregado Gerente"].fillna(0).astype(int)
                        todas_zonas = todas_zonas.sort_values("Entregado Gerente", ascending=False)
                        todas_zonas = todas_zonas.rename(columns={zona_col_d: "Zona"})
                        todas_zonas["% Entrega Gerente"] = np.where(
                            todas_zonas["Total Asignadas"] > 0,
                            todas_zonas["Entregado Gerente"] / todas_zonas["Total Asignadas"] * 100,
                            0,
                        ).round(1)
                        todas_zonas["% Entrega Gerente"] = todas_zonas["% Entrega Gerente"].apply(lambda v: f"{v:.1f}%")
                        _ger_base = df[_gerente_mask].copy()
                        _df_excel(todas_zonas, "todas_zonas_gerente.xlsx",
                                  df_base=_ger_base,
                                  base_label=f"🚚 Entregadas por Gerente ({len(_ger_base):,} reg.)",
                                  base_filename="cartera_entregada_gerente.xlsx")
                    else:
                        st.info("No se encontraron registros con 'ENTREGADO POR GERENTE' en la columna AB.")
                else:
                    st.info("Sin columna de Zona.")

                _section("Situación de Entrega por Geografía (Top 10)")
                c1, c2 = st.columns(2)
                with c1:
                    _geo_cat_chart(df, sit_cie_col, "division", 5,
                                   "Top 5 Situaciones por División", "División")
                with c2:
                    _geo_cat_chart(df, sit_cie_col, "ruta", 5,
                                   "Top 10 Rutas — Top 5 Situaciones", "Ruta", max_geo=10)

                if camp_col_real and camp_col_real in df.columns:
                    _section("Tendencia de Distribución por Campaña")
                    top3_s = sit_counts.head(3).index.tolist()
                    df_tr = df.copy()
                    df_tr["__cat__"] = df_tr[sit_cie_col].fillna("Sin Info").astype(str).str.strip()
                    df_tr = df_tr[df_tr["__cat__"].isin(top3_s)]
                    tr_g = df_tr.groupby([camp_col_real, "__cat__"]).size().reset_index(name="Pedidos")
                    tr_g.columns = ["Campaña", "Situación", "Pedidos"]
                    if len(tr_g):
                        tr_g = tr_g.sort_values("Campaña", key=lambda c: c.astype(str))
                        fig = px.bar(
                            tr_g, x="Campaña", y="Pedidos", color="Situación",
                            barmode="group", text="Pedidos",
                            color_discrete_sequence=CAT_COLORS,
                            labels={"Campaña": "Campaña", "Pedidos": "Pedidos"},
                        )
                        fig.update_traces(textposition="outside", textfont=dict(size=11))
                        fig.update_layout(
                            **PLOTLY_LAYOUT,
                            title=dict(text="Tendencia de Distribución por Campaña (Top 3 situaciones)", font=dict(size=14, color=COLORS["primary"], weight=600)),
                            xaxis=dict(**_AXIS_DEFAULTS, title="Campaña", type="category"),
                            yaxis=dict(**_AXIS_DEFAULTS, title="Pedidos"),
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                        )
                        _chart_card(fig)
                        # Pivot descargable: situaciones x campaña
                        tr_pivot = tr_g.pivot_table(
                            index="Campaña", columns="Situación", values="Pedidos", fill_value=0
                        ).reset_index()
                        tr_pivot.columns.name = None
                        tr_pivot["Total"] = tr_pivot.iloc[:, 1:].sum(axis=1)
                        _df_excel(tr_pivot, "tendencia_distribucion_campana.xlsx", df_base=df,
                                  base_label=f"📋 Cartera completa ({len(df):,} reg.)",
                                  base_filename="cartera_distribucion_campana.xlsx")

                _camp_cat_section(df, sit_cie_col, "distribucion_entrega")

                # ── Descarga cartera completa por situación ───────────────────
                _section("Descargar Cartera por Situación de Entrega")
                sit_unicas = sit_counts.index.tolist()
                cols_dl = st.columns(min(len(sit_unicas), 4))
                for i, sit_lbl in enumerate(sit_unicas):
                    col_idx = i % 4
                    msk_sit = df[sit_cie_col].fillna("").astype(str).str.strip() == sit_lbl
                    cartera_sit = df[msk_sit].copy()
                    safe_lbl = sit_lbl[:25].replace(" ", "_").lower()
                    with cols_dl[col_idx]:
                        _df_excel(cartera_sit, f"cartera_{safe_lbl}.xlsx",
                                  btn_label=f"📥 {sit_lbl[:30]} ({int(msk_sit.sum()):,})")

        # ── Visitas (Col AO) ──────────────────────────────────────────────────
        with dir_sub[2]:
            _banner("👥", "Visitas", "Resultados de visitas en campo — Col. AO")
            visita_col_dir = cols.get("visita")

            if not visita_col_dir:
                st.info(
                    "No se detectó la columna de Visitas (Col. AO). "
                    "Usa el panel ⚙️ Ajustar columnas para asignarla manualmente."
                )
            else:
                _EXCLUIR_VIS = {"", "nan", "none", "0", "0.0", "sin gestion", "sin visita",
                                "no visita", "no contacto", "sin contacto", "no gestion"}
                vis_raw     = df[visita_col_dir].fillna("").astype(str).str.strip()
                visited_msk = ~vis_raw.str.lower().isin(_EXCLUIR_VIS)
                vis_counts  = vis_raw[visited_msk].value_counts()
                total_vis   = int(visited_msk.sum())
                total_dom_v = len(df)

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Total Registros", f"{total_dom_v:,}")
                m2.metric("Visitas Realizadas", f"{total_vis:,}")
                m3.metric("% con Visita", f"{total_vis/total_dom_v*100:.1f}%" if total_dom_v else "0%")
                top1_lbl = vis_counts.index[0][:28] if len(vis_counts) else "—"
                top1_cnt = int(vis_counts.iloc[0]) if len(vis_counts) else 0
                m4.metric("Resultado más frecuente", top1_lbl, delta=f"{top1_cnt:,}")

                if total_vis == 0:
                    st.info("No se encontraron visitas registradas.")
                else:
                    _section("Distribución de Resultados de Visita")
                    c1, c2 = st.columns(2)
                    with c1:
                        top6v = vis_counts.head(6)
                        otros_v = vis_counts[6:].sum()
                        if otros_v > 0:
                            top6v = pd.concat([top6v, pd.Series({"Otros": otros_v})])
                        _chart_card(_pie_fig(top6v.index.tolist(), top6v.values.tolist(),
                                             "Participación por Resultado de Visita"))
                    with c2:
                        bar_v = vis_counts.head(10).sort_values()
                        fig = go.Figure(go.Bar(
                            x=bar_v.values, y=bar_v.index, orientation="h",
                            marker=dict(color=CAT_COLORS[1], line=dict(width=0)),
                            text=[f"{v:,}  ({v/total_vis*100:.1f}%)" for v in bar_v.values],
                            textposition="outside",
                            textfont=dict(size=11, color=COLORS["text2"]),
                        ))
                        fig.update_layout(
                            **PLOTLY_LAYOUT, title=dict(text="Ranking de Resultados de Visita (Top 10)", font=dict(size=14, color=COLORS["primary"], weight=600)),
                            xaxis=dict(**_AXIS_DEFAULTS, title=dict(text="Visitas", font=dict(size=14, color=COLORS["primary"], weight=600)),
                                       range=[0, bar_v.max() * 1.5]),
                            yaxis=dict(**_AXIS_DEFAULTS),
                            height=max(300, len(bar_v) * 32 + 90),
                        )
                        _chart_card(fig)

                    _section("Resumen Completo de Resultados de Visita")
                    tabla_vis = vis_counts.reset_index()
                    tabla_vis.columns = ["Resultado", "Visitas"]
                    tabla_vis["% del Total Visitas"] = (tabla_vis["Visitas"] / total_vis * 100).apply(lambda v: f"{v:.1f}%")
                    tabla_vis["% del Total Registros"] = (tabla_vis["Visitas"] / total_dom_v * 100).apply(lambda v: f"{v:.1f}%")
                    _vis_base = df[visited_msk].copy()
                    _df_excel(tabla_vis, "visitas_resultado.xlsx",
                              df_base=_vis_base,
                              base_label=f"👣 Cuentas con visita ({len(_vis_base):,} reg.)",
                              base_filename="cartera_con_visita.xlsx")

                    _section("Resultados de Visita por Geografía (Top 5)")
                    c1, c2 = st.columns(2)
                    with c1:
                        _geo_cat_chart(df[visited_msk], visita_col_dir, "division", 5,
                                       "Top 5 Resultados por División", "División")
                    with c2:
                        _geo_cat_chart(df[visited_msk], visita_col_dir, "zona", 5,
                                       "Top 10 Zonas — Top 5 Resultados", "Zona", max_geo=10)

                    _geo_cat_chart(df[visited_msk], visita_col_dir, "ruta", 5,
                                   "Top 10 Rutas — Top 5 Resultados", "Ruta", max_geo=10)

                    # ── Top 10 Zonas con Domicilio No Localizado ──────────────
                    _section("Top 10 Zonas — Domicilio No Localizado")
                    zona_col_vis = cols.get("zona")
                    if zona_col_vis and zona_col_vis in df.columns:
                        _no_loc_mask = (
                            df[visita_col_dir].fillna("").astype(str).str.upper()
                            .str.contains("NO LOCALIZ|NO LOCALIZADO|DOMICILIO NO", na=False)
                        )
                        g_noloc = (
                            df[_no_loc_mask]
                            .groupby(zona_col_vis)
                            .size()
                            .reset_index(name="Sin Localizar")
                        )
                        tot_zona_vis = df.groupby(zona_col_vis).size().reset_index(name="Total Asignadas")
                        g_noloc = (
                            g_noloc.merge(tot_zona_vis, on=zona_col_vis, how="left")
                            .sort_values("Sin Localizar", ascending=False)
                            .head(10)
                            .sort_values("Sin Localizar")
                        )
                        g_noloc["Pct"] = np.where(
                            g_noloc["Total Asignadas"] > 0,
                            g_noloc["Sin Localizar"] / g_noloc["Total Asignadas"] * 100,
                            0,
                        )
                        if len(g_noloc):
                            g_noloc["Zona_str"] = "Zona " + g_noloc[zona_col_vis].astype(str)
                            fig = go.Figure(go.Bar(
                                x=g_noloc["Sin Localizar"],
                                y=g_noloc["Zona_str"],
                                orientation="h",
                                marker_color=COLORS["danger"],
                                text=[f"{v:,}  ({p:.1f}%)" for v, p in zip(g_noloc["Sin Localizar"], g_noloc["Pct"])],
                                textposition="outside",
                            ))
                            fig.update_layout(
                                **PLOTLY_LAYOUT,
                                title=dict(text="Top 10 Zonas con Domicilio No Localizado (% sobre asignadas)", font=dict(size=14, color=COLORS["primary"], weight=600)),
                                xaxis=dict(**_AXIS_DEFAULTS, title=dict(text="Cuentas sin localizar", font=dict(size=14, color=COLORS["primary"], weight=600)),
                                           range=[0, g_noloc["Sin Localizar"].max() * 1.45]),
                                yaxis=dict(
                                    type="category",
                                    categoryorder="array",
                                    categoryarray=g_noloc["Zona_str"].tolist(),
                                    gridcolor=COLORS["grid"],
                                    zeroline=False, showline=False,
                                    tickfont=dict(size=13),
                                ),
                                height=max(380, len(g_noloc) * 46 + 90),
                                bargap=0.3,
                            )
                            _chart_card(fig)

                            tbl_noloc = g_noloc[["Zona_str", "Sin Localizar", "Total Asignadas", "Pct"]].copy()
                            tbl_noloc["Pct"] = tbl_noloc["Pct"].apply(lambda v: f"{v:.1f}%")
                            tbl_noloc.columns = ["Zona", "Domicilio No Localizado", "Total Asignadas", "% No Localizado"]
                            _noloc_base = df[_no_loc_mask].copy()
                            _df_excel(tbl_noloc.sort_values("Domicilio No Localizado", ascending=False),
                                      "zonas_domicilio_no_localizado.xlsx",
                                      df_base=_noloc_base,
                                      base_label=f"❌ Cuentas no localizadas ({len(_noloc_base):,} reg.)",
                                      base_filename="cartera_no_localizada.xlsx")
                        else:
                            st.info("No se encontraron registros de 'Domicilio No Localizado' en Col. AO.")
                    else:
                        st.info("Sin columna de Zona.")

                    if camp_col_real and camp_col_real in df.columns:
                        _section("Tendencia de Visitas por Campaña")
                        top3_v = vis_counts.head(3).index.tolist()
                        df_tv = df[visited_msk].copy()
                        df_tv["__cat__"] = df_tv[visita_col_dir].astype(str).str.strip()
                        df_tv = df_tv[df_tv["__cat__"].isin(top3_v)]
                        tv_g = df_tv.groupby([camp_col_real, "__cat__"]).size().reset_index(name="Visitas")
                        tv_g.columns = ["Campaña", "Resultado", "Visitas"]
                        if len(tv_g):
                            tv_g = tv_g.sort_values("Campaña", key=lambda c: c.astype(str))
                            fig = px.bar(
                                tv_g, x="Campaña", y="Visitas", color="Resultado",
                                barmode="group", text="Visitas",
                                color_discrete_sequence=CAT_COLORS,
                                labels={"Campaña": "Campaña", "Visitas": "Visitas"},
                            )
                            fig.update_traces(textposition="outside", textfont=dict(size=11))
                            fig.update_layout(
                                **PLOTLY_LAYOUT,
                                title=dict(text="Tendencia de Visitas por Campaña (Top 3 resultados)", font=dict(size=14, color=COLORS["primary"], weight=600)),
                                xaxis=dict(**_AXIS_DEFAULTS, title="Campaña", type="category"),
                                yaxis=dict(**_AXIS_DEFAULTS, title="Visitas"),
                                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                            )
                            _chart_card(fig)

                    _camp_cat_section(df[visited_msk], visita_col_dir, "visitas")


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
    tab_indicadores(df)
