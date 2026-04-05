from __future__ import annotations

import json
import streamlit as st

from api_files import files_download_pdfs
from api_workspace import (
    workspace_export_zip,
    workspace_generate_checklist,
    workspace_generate_email,
    workspace_generate_vendors,
    workspace_summary,
    workspace_parse,
)

st.set_page_config(page_title="Workspace - NagaCon", layout="wide")

query_opp_id = st.query_params.get("opp_id")
if query_opp_id:
    try:
        st.session_state["workspace_id"] = int(query_opp_id)
    except Exception:
        pass

opp_id = st.session_state.get("workspace_id")
st.title("Opportunity Workspace")

if not opp_id:
    st.warning("No opportunity selected. Go back to Opportunities.")
    st.page_link("pages/1_Opportunities.py", label="Back to Opportunities", icon="⬅️")
    st.stop()


def _refresh_workspace() -> dict:
    data = workspace_summary(int(opp_id))
    st.session_state["workspace_summary"] = data
    return data


def _source_badge(source: str) -> str:
    src = (source or "").upper()
    if src == "SAM":
        return "🟦 SAM"
    if src == "DIBBS":
        return "🟩 DIBBS"
    return f"⬜ {source or 'Unknown'}"


data = st.session_state.get("workspace_summary") or _refresh_workspace()
opp = data["opportunity"]
analysis = data.get("analysis", {})
vendor_matches = data.get("vendor_matches", [])
ui_hints = data.get("ui_hints", {})
actions = data.get("actions", [])

top = st.columns([2.5, 1.2, 1.2, 1.2])
top[0].markdown(f"### {_source_badge(opp.get('source'))}  {opp.get('display_title') or opp.get('title')}")
top[1].metric("Solicitation", opp.get("solicitation_number") or "—")
top[2].metric("FSC", opp.get("fsc") or "—")
top[3].metric("NAICS", opp.get("naics") or "—")

meta1, meta2, meta3 = st.columns([2,1,1.5])
meta1.write(f"**Agency:** {opp.get('agency') or ''}")
meta2.write(f"**Posted:** {str(opp.get('posted_at') or '')[:10]}")
meta3.write(f"**Due:** {str(opp.get('due_at') or '')[:19]}")

st.caption(f"Raw title: {opp.get('raw_title') or opp.get('title') or ''}")
if opp.get("url"):
    st.link_button("Open Source Notice", opp["url"], use_container_width=False)

left, right = st.columns([1.4, 1.0])

with left:
    st.subheader("Opportunity Summary")
    st.write(opp.get("summary") or opp.get("description") or "No summary available yet.")

    st.subheader("Analysis")
    c1, c2, c3 = st.columns(3)
    c1.metric("Priority", analysis.get("priority_score", 0))
    c2.metric("Fit", analysis.get("fit_score", 0))
    c3.metric("Risk Flags", len(analysis.get("risk_flags", []) or []))
    if analysis.get("ai_summary"):
        st.info(analysis["ai_summary"])

    st.subheader("Source-uniform title rule")
    st.code(opp.get("source_uniform_title") or opp.get("display_title") or opp.get("title") or "")

with right:
    st.subheader("Actions")
    if st.button("Parse Opportunity", use_container_width=True):
        workspace_parse(int(opp_id))
        _refresh_workspace()
        st.success("Opportunity parsed.")
    if st.button("Generate Checklist", use_container_width=True):
        workspace_generate_checklist(int(opp_id))
        _refresh_workspace()
        st.success("Checklist generated.")
    if st.button("Generate Vendor Shortlist", use_container_width=True):
        workspace_generate_vendors(int(opp_id))
        _refresh_workspace()
        st.success("Vendor shortlist generated.")
    if st.button("Generate Quote Email", use_container_width=True):
        workspace_generate_email(int(opp_id))
        _refresh_workspace()
        st.success("Quote email generated.")
    if st.button("Download PDFs / Snapshot", use_container_width=True):
        out = files_download_pdfs(int(opp_id))
        st.json(out)
    if st.button("Build Export ZIP", type="primary", use_container_width=True):
        st.session_state["workspace_zip"] = workspace_export_zip(int(opp_id))
        st.success("Export ready.")

    if "workspace_zip" in st.session_state:
        st.download_button(
            "Download Workspace ZIP",
            data=st.session_state["workspace_zip"],
            file_name=f"nagacon_workspace_{opp_id}.zip",
            mime="application/zip",
            use_container_width=True,
        )

st.divider()
vendors_col, actions_col = st.columns([1.2, 1.2])

with vendors_col:
    st.subheader("Vendor Matches")
    if vendor_matches:
        st.json(vendor_matches)
    else:
        st.info(ui_hints.get("empty_vendors_message") or "No vendor matches yet.")

with actions_col:
    st.subheader("Recommended Next Actions")
    if actions:
        for action in actions:
            st.write(f"• {action}")
    else:
        st.info("No suggested actions yet.")
