# ===================== Official PDF status helper =====================
# Put this inside your Attachments / PDFs area after `out = files_download_pdfs(...)` success,
# or render from a stored result if you keep it in session_state.

if "last_files_pull_result" in st.session_state:
    res = st.session_state["last_files_pull_result"]
    if res.get("official_pdf_saved"):
        st.success(f"Official DIBBS PDF captured: {res.get('official_pdf_filename')}")
    else:
        st.warning("Official DIBBS PDF auto-download blocked; fallback snapshot available.")
        if res.get("detail_url"):
            st.markdown(f"**Official PDF URL:** {res.get('detail_url')}")
        if res.get("official_pdf_error"):
            st.caption(f"Reason: {res.get('official_pdf_error')}")
        if res.get("debug_log_path"):
            st.caption(f"Debug log saved at: {res.get('debug_log_path')}")
