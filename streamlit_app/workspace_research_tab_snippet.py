
# Add this import near the top of streamlit_app/pages/2_Workspace.py
from api_research import research_predecessors, seed_research_leads

# Add a new tab name in the tabs() call:
# "Research"

# Then add a block like this for the new tab:
with tab_research:
    st.subheader("Research")
    st.caption("Find predecessor awards in USAspending and related opportunity history in SAM.gov.")

    if st.button("Run Research", use_container_width=True):
        research = research_predecessors(int(opp_id))
        st.session_state["research_data"] = research

    research = st.session_state.get("research_data", {})

    if research:
        ctx = research.get("research_context", {})
        st.write("**Context used**")
        st.json(ctx)

        st.write("**Likely Vendors**")
        vendors = research.get("likely_vendors", [])
        if vendors:
            vendors_df = pd.DataFrame(vendors)
            st.dataframe(vendors_df, width="stretch", hide_index=True)

            if st.button("Seed Top Vendors to Leads", type="primary", use_container_width=True):
                result = seed_research_leads(int(opp_id), vendors)
                st.success(f"Created {result.get('created', 0)} and updated {result.get('updated', 0)} vendor leads.")
        else:
            st.info("No likely vendors found from research.")

        st.write("**Historical Awards**")
        awards = research.get("historical_awards", [])
        if awards:
            st.dataframe(pd.DataFrame(awards), width="stretch", hide_index=True)
        else:
            st.caption("No matching historical awards returned.")

        st.write("**Related SAM Opportunities**")
        sam_rows = research.get("sam_related_opportunities", [])
        if sam_rows:
            st.dataframe(pd.DataFrame(sam_rows), width="stretch", hide_index=True)
        elif research.get("sam_enabled"):
            st.caption("SAM search is enabled, but no related opportunities were returned.")
        else:
            st.caption("SAM search is disabled because SAM_API_KEY is not configured.")
