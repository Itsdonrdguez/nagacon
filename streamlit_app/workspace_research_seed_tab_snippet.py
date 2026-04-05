
# Add these imports near the top of your Workspace page
from api_research import usaspending_research, usaspending_seed_leads

# Add this inside your workspace page where opp_id is already available
st.subheader("Research")

research_col1, research_col2 = st.columns(2)

with research_col1:
    if st.button("Run USAspending Research", use_container_width=True):
        st.session_state["usaspending_research"] = usaspending_research(int(opp_id))

with research_col2:
    if st.button("Seed Research Vendors to Leads", use_container_width=True):
        seeded = usaspending_seed_leads(int(opp_id))
        st.session_state["usaspending_seed_result"] = seeded
        st.success(f"Seeded {seeded['seeded_count']} vendor leads")
        st.rerun()

research_data = st.session_state.get("usaspending_research")
seed_result = st.session_state.get("usaspending_seed_result")

if seed_result:
    st.caption(
        f"Created: {seed_result['created']} | Updated: {seed_result['updated']} | Seeded: {seed_result['seeded_count']}"
    )

if research_data:
    st.markdown("### Likely Vendors")
    st.dataframe(research_data.get("likely_vendors", []), use_container_width=True)

    st.markdown("### Similar Awards")
    st.dataframe(research_data.get("awards", []), use_container_width=True)
