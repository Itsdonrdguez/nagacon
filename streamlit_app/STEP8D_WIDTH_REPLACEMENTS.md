# Streamlit deprecation: use_container_width -> width

Streamlit warns:
`use_container_width` will be removed after 2025-12-31.

Replace:
- `use_container_width=True`  -> `width="stretch"`
- `use_container_width=False` -> `width="content"`

Examples:
- `st.button(..., width="stretch")`
- `st.download_button(..., width="stretch")`
