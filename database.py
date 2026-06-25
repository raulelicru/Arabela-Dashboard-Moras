"""Operaciones de base de datos y almacenamiento en Supabase."""
import re
import unicodedata
import uuid
import streamlit as st
from supabase import Client

BUCKET = "uploads"


def _safe_filename(name: str) -> str:
    """Elimina acentos, espacios y caracteres especiales para rutas de Storage."""
    name = unicodedata.normalize("NFD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name


# ── Storage ──────────────────────────────────────────────────────────────────

def _storage_upload(sb: Client, path: str, file_bytes: bytes) -> bool:
    try:
        sb.storage.from_(BUCKET).upload(
            path=path,
            file=file_bytes,
            file_options={
                "content-type": (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
                "upsert": False,
            },
        )
        return True
    except Exception as e:
        st.session_state["_upload_error"] = str(e)
        return False
        return False


def _storage_download(sb: Client, path: str) -> bytes | None:
    try:
        return sb.storage.from_(BUCKET).download(path)
    except Exception as e:
        st.error(f"Error al descargar archivo: {e}")
        return None


# ── Uploads (genérico) ────────────────────────────────────────────────────────

def _upload_file(sb: Client, table: str, prefix: str, user_id: str, uploaded_file) -> dict | None:
    upload_id = str(uuid.uuid4())
    safe_name = _safe_filename(uploaded_file.name)
    path = f"{prefix}/{upload_id}/{safe_name}"
    file_bytes = uploaded_file.getvalue()

    if not _storage_upload(sb, path, file_bytes):
        return None

    try:
        result = (
            sb.table(table)
            .insert({
                "id": upload_id,
                "uploaded_by": user_id,
                "filename": uploaded_file.name,
                "storage_path": path,
                "is_active": True,
            })
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        st.error(f"Error al registrar archivo en base de datos: {e}")
        return None


def upload_cartera_file(sb: Client, user_id: str, uploaded_file) -> dict | None:
    return _upload_file(sb, "cartera_uploads", "cartera", user_id, uploaded_file)


def upload_domicilios_file(sb: Client, user_id: str, uploaded_file) -> dict | None:
    return _upload_file(sb, "domicilios_uploads", "domicilios", user_id, uploaded_file)


# ── Fetch latest (con caché en session_state) ─────────────────────────────────

def _get_latest_cached(sb: Client, table: str, cache_key: str) -> tuple[bytes, dict] | None:
    try:
        result = (
            sb.table(table)
            .select("*")
            .eq("is_active", True)
            .order("uploaded_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            st.session_state.pop(cache_key, None)
            return None

        meta = result.data[0]
        cached = st.session_state.get(cache_key, {})

        if cached.get("upload_id") == meta["id"]:
            return cached["file_bytes"], meta

        file_bytes = _storage_download(sb, meta["storage_path"])
        if file_bytes is None:
            return None

        st.session_state[cache_key] = {"upload_id": meta["id"], "file_bytes": file_bytes}
        return file_bytes, meta
    except Exception as e:
        st.error(f"Error al obtener datos desde Supabase: {e}")
        return None


def get_latest_cartera(sb: Client) -> tuple[bytes, dict] | None:
    return _get_latest_cached(sb, "cartera_uploads", "_cartera_cache")


def get_latest_domicilios(sb: Client) -> tuple[bytes, dict] | None:
    return _get_latest_cached(sb, "domicilios_uploads", "_domicilios_cache")


# ── List & Delete ─────────────────────────────────────────────────────────────

def list_uploads(sb: Client, table: str) -> list:
    try:
        result = (
            sb.table(table)
            .select("id, filename, uploaded_at")
            .eq("is_active", True)
            .order("uploaded_at", desc=True)
            .execute()
        )
        return result.data or []
    except Exception as e:
        st.error(f"Error al listar archivos: {e}")
        return []


def delete_upload(sb: Client, table: str, upload_id: str) -> bool:
    try:
        sb.table(table).update({"is_active": False}).eq("id", upload_id).execute()
        cache_key = "_cartera_cache" if table == "cartera_uploads" else "_domicilios_cache"
        st.session_state.pop(cache_key, None)
        return True
    except Exception as e:
        st.session_state["_delete_error"] = str(e)
        return False
