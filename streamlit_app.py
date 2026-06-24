import pathlib

import streamlit as st
import streamlit.components.v1 as components

from indicadores_mora import _render_indicadores_standalone

st.set_page_config(page_title="Arabela Cobranza", layout="wide")

html = pathlib.Path(__file__).parent.joinpath("arabela_analyzer.html").read_text(encoding="utf-8")
components.html(html, height=1400, scrolling=True)

st.divider()

_render_indicadores_standalone()
