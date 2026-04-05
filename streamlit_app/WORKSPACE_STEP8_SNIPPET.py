# ===================== Submission (Step 8) =====================
st.subheader("Submission")

try:
    from api_submissions import submission_get, submission_upsert
except Exception:
    submission_get = submission_upsert = None  # type: ignore

if submission_get is None:
    st.warning("Submission module not found. Make sure streamlit_app/api_submissions.py exists (Step 8).")
else:
    sub = submission_get(int(opp_id)) or {}
    status_choices = ["DRAFT", "SUBMITTED", "AWARDED", "LOST", "NO_BID"]

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        status_val = st.selectbox(
            "Status",
            status_choices,
            index=status_choices.index(sub.get("status", "DRAFT")) if sub.get("status", "DRAFT") in status_choices else 0,
        )
    with c2:
        submitted_unit_price = st.number_input(
            "Submitted Unit Price",
            value=float(sub.get("submitted_unit_price") or 0.0),
            min_value=0.0,
            step=0.01,
        )
    with c3:
        notes = st.text_input("Notes", value=sub.get("notes") or "")

    vendor_cage = sub.get("submitted_vendor_cage") or ""
    vendor_name = sub.get("submitted_vendor_name") or ""

    try:
        from api_vendors import vendors_get_quotes
        vlist = vendors_get_quotes(int(opp_id))
    except Exception:
        vlist = []

    options = [""] + [f"{v.get('cage','')} — {v.get('company_name') or ''}".strip() for v in vlist]
    default_opt = ""
    if vendor_cage:
        for opt in options:
            if opt.startswith(vendor_cage):
                default_opt = opt
                break

    sel = st.selectbox(
        "Submitted Vendor (optional)",
        options,
        index=options.index(default_opt) if default_opt in options else 0,
    )
    if sel and "—" in sel:
        vendor_cage = sel.split("—")[0].strip()
        vendor_name = sel.split("—", 1)[1].strip()

    if st.button("Save Submission", type="primary", use_container_width=True):
        payload = {
            "opportunity_id": int(opp_id),
            "status": status_val,
            "submitted_unit_price": submitted_unit_price if submitted_unit_price > 0 else None,
            "submitted_vendor_cage": vendor_cage or None,
            "submitted_vendor_name": vendor_name or None,
            "notes": notes or None,
        }
        out = submission_upsert(payload)
        st.success(f"Saved submission: {out.get('status')}")
        st.divider()

# ===================== Attachments / PDFs (Step 8) =====================
st.subheader("Attachments / PDFs")

try:
    from api_files import files_list, files_download_pdfs, files_download
except Exception:
    files_list = files_download_pdfs = files_download = None  # type: ignore

if files_list is None:
    st.warning("Files module not found. Make sure streamlit_app/api_files.py exists (Step 8).")
else:
    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button("Download PDFs from Opportunity", use_container_width=True):
            out = files_download_pdfs(int(opp_id))
            st.success(f"Downloaded {out.get('created', 0)} new PDF(s). Found links: {out.get('found_links', 0)}")
    with c2:
        st.caption("Pulls any PDF links found on the opportunity page (and Technical Documents if present).")

    fl = files_list(int(opp_id))
    if not fl:
        st.info("No PDFs downloaded yet.")
    else:
        for f in fl:
            cols = st.columns([3, 1])
            with cols[0]:
                st.write(f"📄 {f.get('filename')}")
            with cols[1]:
                data = files_download(int(f["id"]))
                st.download_button("Download", data=data, file_name=f.get("filename") or "file.pdf", mime="application/pdf", key=f"dl_{f['id']}")

st.divider()
