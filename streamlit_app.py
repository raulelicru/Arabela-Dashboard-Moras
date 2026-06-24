import base64
import json
import pathlib

import streamlit as st
import streamlit.components.v1 as components

from indicadores_mora import _banner, _indicadores_uploader, _render_indicadores_results

st.set_page_config(page_title="Arabela Cobranza", layout="wide")

# ── Header con logo ─────────────────────────────────────────────────────────
logo_path = pathlib.Path(__file__).parent / "logo_crz.png"
hcol1, hcol2 = st.columns([1, 11])
with hcol1:
    st.image(str(logo_path), width=64)
with hcol2:
    st.markdown("**CONSULTORES CRZ**  \nArabela Cobranza — Análisis de Domicilios e Indicadores de Mora")

st.divider()

# ── Sección de carga ────────────────────────────────────────────────────────
st.markdown("### Sube tus archivos Excel")
st.caption("Cada sección usa un archivo distinto según lo que necesites analizar.")

col1, col2 = st.columns(2)

with col1:
    with st.container(border=True):
        st.markdown("**📁 Domicilios — Arabela**")
        st.caption("Normaliza y clasifica los domicilios de tu cartera de cobranza.")
        arabela_file = st.file_uploader(
            "Archivo .xlsx",
            type=["xlsx"],
            key="arabela_uploader",
            label_visibility="collapsed",
        )

with col2:
    with st.container(border=True):
        st.markdown("**📊 Cartera General — Indicadores de Mora**")
        st.caption("Calcula KPIs de recuperación, gestión y cobranza por segmento.")
        _indicadores_uploader()

st.divider()

# ── Dashboard Arabela (iframe auto-carga el archivo vía JS) ─────────────────
if arabela_file is not None:
    html = (
        pathlib.Path(__file__)
        .parent.joinpath("arabela_analyzer.html")
        .read_text(encoding="utf-8")
    )
    b64 = base64.b64encode(arabela_file.getvalue()).decode()
    inject = """
<script>
(function(){
  try {
    var b64 = %s;
    var byteChars = atob(b64);
    var byteNumbers = new Array(byteChars.length);
    for (var i = 0; i < byteChars.length; i++) { byteNumbers[i] = byteChars.charCodeAt(i); }
    var byteArray = new Uint8Array(byteNumbers);
    var file = new File([byteArray], %s, {type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
    if (typeof processExcelFile === 'function') { processExcelFile(file); }
  } catch (err) { console.error('Error auto-cargando archivo Arabela:', err); }
})();
</script>
""" % (
        json.dumps(b64),
        json.dumps(arabela_file.name),
    )
    html = html.replace("</body>", inject + "</body>", 1)
    components.html(html, height=1400, scrolling=True)
else:
    st.info("Sube el archivo de domicilios en la caja de la izquierda para ver el dashboard de Arabela.")

st.divider()

# ── Dashboard Indicadores de Mora ────────────────────────────────────────────
_banner("📊", "Indicadores de Mora", "Dashboard de cobranza y recuperación de cartera")
_render_indicadores_results()
