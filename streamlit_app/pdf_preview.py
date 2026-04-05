import base64
import streamlit.components.v1 as components


def render_pdf_bytes(pdf_bytes: bytes, height: int = 720) -> None:
    """Inline PDF preview via iframe using base64 data URI."""
    b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    html = f'<iframe src="data:application/pdf;base64,{b64}" width="100%" height="{height}" type="application/pdf"></iframe>'
    components.html(html, height=height, scrolling=True)
