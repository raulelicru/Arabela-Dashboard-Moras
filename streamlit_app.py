import base64
import io
import json
import pathlib

import streamlit as st
import streamlit.components.v1 as components

from auth import get_supabase, require_auth, is_admin, logout
from database import (
    upload_cartera_file,
    upload_domicilios_file,
    get_latest_cartera,
    get_latest_domicilios,
    list_uploads,
    delete_upload,
)
from indicadores_mora import read_excel_safe, _render_indicadores_results

st.set_page_config(page_title="Dashboard Cobranza Mora Arabela", layout="wide")

# ── Autenticación ────────────────────────────────────────────────────────────
sb = get_supabase()
require_auth(sb)

# ── Header ───────────────────────────────────────────────────────────────────
logo_path = pathlib.Path(__file__).parent / "logo_crz.png"
h1, h2, h3 = st.columns([1, 9, 2])
with h1:
    st.image(str(logo_path), width=64)
with h2:
    st.caption("CONSULTORES CRZ")
    st.header("Dashboard Cobranza Mora Arabela")
with h3:
    role = st.session_state.get("role", "user")
    badge = "👑 Admin" if role == "admin" else "👤 Usuario"
    st.caption(badge)
    st.caption(st.session_state["user"]["email"])
    if st.button("Cerrar sesión", key="logout"):
        logout(sb)

st.divider()

# ── Gestión de archivos (solo Admin) ─────────────────────────────────────────
if is_admin():
    st.markdown("### Gestión de Archivos")
    col1, col2 = st.columns(2)

    with col1:
        with st.container(border=True):
            st.markdown("**📁 Domicilios — Arabela**")
            st.caption("Normaliza y clasifica los domicilios de tu cartera de cobranza.")
            dom_file = st.file_uploader(
                "Archivo .xlsx", type=["xlsx"], key="dom_uploader",
                label_visibility="collapsed",
            )
            if dom_file:
                if st.button("⬆️ Subir a Supabase", key="btn_dom", use_container_width=True):
                    with st.spinner("Subiendo..."):
                        rec = upload_domicilios_file(sb, st.session_state["user"]["id"], dom_file)
                    if rec:
                        st.success(f"✅ Subido: {rec['filename']}")
                        st.rerun()

            dom_uploads = list_uploads(sb, "domicilios_uploads")
            if dom_uploads:
                st.markdown("**Archivos activos:**")
                for u in dom_uploads:
                    c1, c2 = st.columns([4, 1])
                    c1.caption(f"📄 {u['filename']} · {u['uploaded_at'][:10]}")
                    if c2.button("🗑️", key=f"del_dom_{u['id']}", help="Eliminar"):
                        delete_upload(sb, "domicilios_uploads", u["id"])
                        st.rerun()

    with col2:
        with st.container(border=True):
            st.markdown("**📊 Cartera General — Indicadores de Mora**")
            st.caption("Calcula KPIs de recuperación, gestión y cobranza por segmento.")
            cart_file = st.file_uploader(
                "Archivo .xlsx / .xls", type=["xlsx", "xls"], key="cart_uploader",
                label_visibility="collapsed",
            )
            if cart_file:
                if st.button("⬆️ Subir a Supabase", key="btn_cart", use_container_width=True):
                    with st.spinner("Subiendo..."):
                        rec = upload_cartera_file(sb, st.session_state["user"]["id"], cart_file)
                    if rec:
                        st.success(f"✅ Subido: {rec['filename']}")
                        st.rerun()

            cart_uploads = list_uploads(sb, "cartera_uploads")
            if cart_uploads:
                st.markdown("**Archivos activos:**")
                for u in cart_uploads:
                    c1, c2 = st.columns([4, 1])
                    c1.caption(f"📄 {u['filename']} · {u['uploaded_at'][:10]}")
                    if c2.button("🗑️", key=f"del_cart_{u['id']}", help="Eliminar"):
                        delete_upload(sb, "cartera_uploads", u["id"])
                        st.rerun()

    st.divider()

# ── Dashboard Arabela ────────────────────────────────────────────────────────
with st.spinner("Cargando datos de domicilios..."):
    dom_data = get_latest_domicilios(sb)

if dom_data:
    file_bytes, meta = dom_data
    html = (
        pathlib.Path(__file__).parent
        .joinpath("arabela_analyzer.html")
        .read_text(encoding="utf-8")
    )
    b64 = base64.b64encode(file_bytes).decode()
    inject = """
<script>
(function(){
  try {
    var b64 = %s;
    var bc = atob(b64), bn = new Array(bc.length);
    for (var i = 0; i < bc.length; i++) { bn[i] = bc.charCodeAt(i); }
    var file = new File([new Uint8Array(bn)], %s,
      {type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
    if (typeof processExcelFile === 'function') { processExcelFile(file); }
  } catch(e) { console.error('Arabela auto-load:', e); }
})();
</script>
""" % (json.dumps(b64), json.dumps(meta["filename"]))
    html = html.replace("</body>", inject + "</body>", 1)
    st.caption(f"📁 Domicilios: **{meta['filename']}** · cargado el {meta['uploaded_at'][:10]}")
    components.html(html, height=1400, scrolling=True)
else:
    msg = (
        "Sube un archivo de domicilios en la sección de gestión de arriba."
        if is_admin()
        else "El administrador aún no ha cargado datos de domicilios."
    )
    st.info(f"📁 {msg}")

st.divider()

# ── Dashboard Indicadores de Mora ─────────────────────────────────────────────
with st.spinner("Cargando datos de cartera..."):
    cart_data = get_latest_cartera(sb)

if cart_data:
    file_bytes, meta = cart_data
    df = read_excel_safe(io.BytesIO(file_bytes))
    st.session_state["ind_df"] = df
    st.session_state["ind_file_name"] = meta["filename"]
    st.caption(f"📊 Cartera: **{meta['filename']}** · cargado el {meta['uploaded_at'][:10]}")
else:
    st.session_state.pop("ind_df", None)
    st.session_state.pop("ind_file_name", None)

_render_indicadores_results()
