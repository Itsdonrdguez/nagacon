from __future__ import annotations

import pandas as pd
import streamlit as st

from api_opportunities import list_opportunities, run_dibbs_scraper, run_sam_scraper
from api_scrapers import run_all_state_local, run_state_local_scraper

st.set_page_config(page_title="Opportunities - NagaCon", layout="wide")
st.title("Opportunities")

if "workspace_id" not in st.session_state:
    st.session_state["workspace_id"] = None


def _open_workspace(opp_id: int):
    st.session_state["workspace_id"] = int(opp_id)
    st.switch_page("pages/2_Workspace.py")


def _badge_for_source(source: str) -> str:
    src = (source or "").upper()
    if src == "SAM":
        return "🟦 SAM"
    if src == "DIBBS":
        return "🟩 DIBBS"
    return f"⬜ {source or 'Unknown'}"


def _render_clickable_table(df: pd.DataFrame):
    header = st.columns([0.6, 1.0, 1.7, 3.2, 2.0, 1.0, 0.9])
    header[0].markdown("**ID**")
    header[1].markdown("**Source**")
    header[2].markdown("**Solicitation #**")
    header[3].markdown("**Display Title**")
    header[4].markdown("**Agency**")
    header[5].markdown("**Status**")
    header[6].markdown("**Due**")

    for idx, (_, r) in enumerate(df.iterrows()):
        opp_id = int(r["id"])
        sol = r.get("solicitation_number") or "NO-SOL"
        title = r.get("display_title") or r.get("title") or ""
        agency = r.get("agency") or ""
        source = r.get("source") or ""
        status = r.get("status") or ""
        due = r.get("due_at") or ""

        row_cols = st.columns([0.6, 1.0, 1.7, 3.2, 2.0, 1.0, 0.9])
        row_cols[0].write(opp_id)
        row_cols[1].markdown(_badge_for_source(source))
        if row_cols[2].button(sol, key=f"open_workspace_{opp_id}_{idx}", use_container_width=True):
            _open_workspace(opp_id)
        row_cols[3].write(title)
        row_cols[4].write(agency)
        row_cols[5].write(status)
        row_cols[6].write(str(due)[:10] if due else "—")


toolbar1, toolbar2, toolbar3 = st.columns([1.2, 1.2, 2.6])

with toolbar1:
    search_text = st.text_input("Search", value="", placeholder="display title / solicitation / agency")

with toolbar2:
    source_filter = st.selectbox("Source", ["All", "SAM", "DIBBS", "eva", "maryland", "dc"], index=0)

with toolbar3:
    c1, c2, c3, c4 = st.columns([1, 1, 1.2, 1.5])
    with c1:
        if st.button("Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    with c2:
        with st.popover("Ingest SAM"):
            sam_limit = st.number_input("Limit", min_value=1, max_value=200, value=10, step=1, key="sam_limit")
            sam_q = st.text_input("Keyword / q", value="", key="sam_q")
            if st.button("Run SAM scraper", use_container_width=True):
                out = run_sam_scraper(limit=int(sam_limit), q=sam_q or None)
                st.session_state["last_ingest_result"] = out
                st.cache_data.clear()
                st.rerun()
    with c3:
        with st.popover("Ingest DIBBS"):
            dibbs_pages = st.number_input("Max pages", min_value=1, max_value=10, value=1, step=1, key="dibbs_pages")
            dibbs_fsc = st.text_input("FSC filter (optional)", value="", key="dibbs_fsc", placeholder="6520")
            if st.button("Run DIBBS scraper", use_container_width=True):
                out = run_dibbs_scraper(max_pages=int(dibbs_pages), fsc=dibbs_fsc or None)
                st.session_state["last_ingest_result"] = out
                st.cache_data.clear()
                st.rerun()
    with c4:
        with st.popover("Ingest State / Local"):
            sl_pages = st.number_input("Max pages", min_value=1, max_value=10, value=1, step=1, key="state_local_pages")
            if st.button("Run eVA", use_container_width=True):
                out = run_state_local_scraper("eva", {"max_pages": int(sl_pages)})
                st.session_state["last_ingest_result"] = out
                st.cache_data.clear()
                st.rerun()
            if st.button("Run Maryland", use_container_width=True):
                out = run_state_local_scraper("maryland", {"max_pages": int(sl_pages)})
                st.session_state["last_ingest_result"] = out
                st.cache_data.clear()
                st.rerun()
            if st.button("Run DC", use_container_width=True):
                out = run_state_local_scraper("dc", {"max_pages": int(sl_pages)})
                st.session_state["last_ingest_result"] = out
                st.cache_data.clear()
                st.rerun()
            if st.button("Run All", type="primary", use_container_width=True):
                out = run_all_state_local({"max_pages": int(sl_pages)})
                st.session_state["last_ingest_result"] = out
                st.cache_data.clear()
                st.rerun()

if "last_ingest_result" in st.session_state:
    with st.expander("Last ingest result", expanded=False):
        st.json(st.session_state["last_ingest_result"])

rows = list_opportunities(limit=200, offset=0) or []
df = pd.DataFrame(rows)

if df.empty:
    st.info("No opportunities loaded yet. Run a scraper to populate the board.")
    st.stop()

if source_filter != "All":
    df = df[df["source"].astype(str).str.upper() == source_filter.upper()]

if search_text:
    q = search_text.strip().lower()
    mask = (
        df.get("display_title", df.get("title", "")).astype(str).str.lower().str.contains(q, na=False)
        | df.get("solicitation_number", "").astype(str).str.lower().str.contains(q, na=False)
        | df.get("agency", "").astype(str).str.lower().str.contains(q, na=False)
    )
    df = df[mask]

df = df.sort_values(by=["id"], ascending=False)
_render_clickable_table(df)
