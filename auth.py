"""Autenticación con Supabase Auth y control de roles."""
import pathlib
import streamlit as st
from supabase import create_client, Client


def get_supabase() -> Client:
    """Crea (o reutiliza) el cliente Supabase en session_state."""
    if "supabase" not in st.session_state:
        url = None
        key = None
        try:
            url = st.secrets["SUPABASE_URL"]
            key = st.secrets["SUPABASE_ANON_KEY"]
        except Exception:
            try:
                from dotenv import load_dotenv
                import os
                load_dotenv()
                url = os.environ["SUPABASE_URL"]
                key = os.environ["SUPABASE_ANON_KEY"]
            except KeyError:
                pass

        if not url or not key:
            st.error(
                "⚠️ Configura **SUPABASE_URL** y **SUPABASE_ANON_KEY** "
                "en `.env` (local) o en *Secrets* de Streamlit Cloud."
            )
            st.stop()

        try:
            st.session_state.supabase = create_client(url, key)
        except Exception as e:
            st.error(f"⚠️ No se pudo conectar con Supabase: {e}")
            st.stop()

    sb: Client = st.session_state.supabase

    # Restaurar sesión en cada rerun si hay tokens guardados
    if st.session_state.get("_access_token") and st.session_state.get("_refresh_token"):
        try:
            sb.auth.set_session(
                st.session_state["_access_token"],
                st.session_state["_refresh_token"],
            )
        except Exception:
            _clear_session()

    return sb


def _clear_session():
    for k in ("_access_token", "_refresh_token", "user", "role",
              "_cartera_cache", "_domicilios_cache"):
        st.session_state.pop(k, None)


def is_authenticated() -> bool:
    return bool(st.session_state.get("user"))


def is_admin() -> bool:
    return st.session_state.get("role") == "admin"


def login(sb: Client, email: str, password: str) -> bool:
    try:
        resp = sb.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state["_access_token"] = resp.session.access_token
        st.session_state["_refresh_token"] = resp.session.refresh_token
        st.session_state["user"] = {"id": resp.user.id, "email": resp.user.email}

        profile = (
            sb.table("profiles")
            .select("role")
            .eq("id", resp.user.id)
            .execute()
        )
        st.session_state["role"] = (
            profile.data[0]["role"] if profile.data else "user"
        )
        return True
    except Exception:
        st.error("❌ Correo o contraseña incorrectos.")
        return False


def logout(sb: Client):
    try:
        sb.auth.sign_out()
    except Exception:
        pass
    _clear_session()
    st.rerun()


def require_auth(sb: Client):
    """Muestra la pantalla de login y detiene la app si el usuario no está autenticado."""
    if not is_authenticated():
        _show_login_page(sb)
        st.stop()


_USERS = {
    "Raul Elizalde":          "raulelicru@gmail.com",
    "Ángeles Cruz":           "angeleselicru@gmail.com",
    "Claudia Vallejo":        "claudia.vallejo@cgconsultoresjuridicos.mx",
    "Patty Cruz":             "pattycruzguzman@gmail.com",
    "Lourdes Martinez":       "lourdes.martinez@arabela.com",
    "Eduardo Perez":          "eduardo.perez@arabela.com",
    "Jenifer Cravioto":       "jenifer.cravioto@arabela.com",
}


def _show_login_page(sb: Client):
    logo_path = pathlib.Path(__file__).parent / "logo_crz.png"

    _, col, _ = st.columns([1, 1.8, 1])
    with col:
        if logo_path.exists():
            st.image(str(logo_path), width=80)
        st.markdown("#### Dashboard Cobranza Mora Arabela")
        st.caption("CONSULTORES CRZ — Selecciona tu nombre e ingresa tu contraseña")
        st.divider()

        with st.form("login_form"):
            name = st.selectbox("¿Quién eres?", list(_USERS.keys()))
            password = st.text_input("Contraseña", type="password", placeholder="••••••••")
            submitted = st.form_submit_button(
                "Iniciar sesión", use_container_width=True, type="primary"
            )

        if submitted:
            if not password:
                st.warning("Ingresa tu contraseña.")
            else:
                with st.spinner("Verificando..."):
                    if login(sb, _USERS[name], password):
                        st.rerun()
