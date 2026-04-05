# ===================== Attachments / PDFs =====================
st.subheader("Attachments / PDFs")

try:
    from api_files import files_list, files_download_pdfs, files_download
    from pdf_preview import render_pdf_bytes
except Exception:
    files_list = files_download_pdfs = files_download = None  # type: ignore
    render_pdf_bytes = None  # type: ignore

if files_list is None:
    st.warning("Files module not found. Make sure streamlit_app/api_files.py exists (Step 8F).")
else:
    c1, c2 = st.columns([1, 3])

    with c1:
        if st.button("Download PDFs from Opportunity", width="stretch"):
            out = files_download_pdfs(int(opp_id))
            st.success(
                f"Downloaded {out.get('created', 0)} file(s). "
                f"Found PDF links: {out.get('found_links', 0)}. "
                f"Detail URL: {out.get('detail_url') or 'n/a'}"
            )

    with c2:
        st.caption("Downloads DIBBS attachments (from solicitation detail page when possible) and always generates a Snapshot PDF.")

    fl = files_list(int(opp_id))
    if not fl:
        st.info("No PDFs downloaded yet.")
    else:
        snapshots = [f for f in fl if (f.get("file_type") or "").upper() == "PDF_SNAPSHOT"]
        attachments = [f for f in fl if (f.get("file_type") or "").upper() != "PDF_SNAPSHOT"]

        def _render_row(f: dict, icon: str, label: str):
            cols = st.columns([4, 1, 1])
            with cols[0]:
                st.write(f"{icon} **{label}** — {f.get('filename')}")
            with cols[1]:
                data = files_download(int(f["id"]))
                st.download_button(
                    "Download",
                    data=data,
                    file_name=f.get("filename") or "file.pdf",
                    mime="application/pdf",
                    key=f"dl_{f['id']}",
                    width="stretch",
                )
            with cols[2]:
                if render_pdf_bytes is None:
                    st.caption("No preview")
                else:
                    if st.button("Preview", key=f"pv_{f['id']}", width="stretch"):
                        st.session_state["preview_file_id"] = int(f["id"])

        if snapshots:
            st.markdown("### 📄 Snapshot PDFs")
            for f in snapshots:
                _render_row(f, "📄", "Snapshot")

        if attachments:
            st.markdown("### 📎 Attachment PDFs")
            for f in attachments:
                _render_row(f, "📎", "Attachment")

        pid = st.session_state.get("preview_file_id")
        if pid:
            fsel = next((x for x in fl if int(x.get("id")) == int(pid)), None)
            if fsel:
                st.markdown("---")
                st.markdown(f"## Preview: {fsel.get('filename')}")
                try:
                    pdf_bytes = files_download(int(pid))
                    render_pdf_bytes(pdf_bytes, height=820)
                except Exception as e:
                    st.error(f"Preview failed: {e}")

                if st.button("Close preview", key="close_preview", width="content"):
                    st.session_state["preview_file_id"] = None

st.divider()
# ===================== end Attachments / PDFs =====================
