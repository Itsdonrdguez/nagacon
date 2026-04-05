from __future__ import annotations

import pandas as pd
import streamlit as st

from api_analytics import get_analytics_summary

st.set_page_config(page_title="Analytics - NagaCon", layout="wide")
st.title("Analytics Dashboard")

summary = get_analytics_summary()

c1, c2, c3 = st.columns(3)
c1.metric("Total Opportunities", summary.get("total_opportunities", 0))
c2.metric("Due Soon (7 days)", summary.get("due_soon_7_days", 0))
c3.metric("Weighted Pipeline Value", f'${summary.get("weighted_pipeline_value", 0):,.2f}')

c4, c5, c6 = st.columns(3)
c4.metric("Active Pipeline Items", summary.get("active_pipeline_items", 0))
c5.metric("Quote Scenarios", summary.get("quote_scenarios", 0))
c6.metric("Past Performance Records", summary.get("past_performance_count", 0))

c7 = st.columns(1)[0]
c7.metric("Matching Past Perf NAICS", summary.get("matching_past_perf_naics", 0))

st.subheader("Pipeline Stage Counts")
stage_counts = summary.get("pipeline_stage_counts", {})
if stage_counts:
    stage_df = pd.DataFrame(
        [{"stage": k, "count": v} for k, v in stage_counts.items()]
    ).set_index("stage")
    st.bar_chart(stage_df)
    st.dataframe(stage_df.reset_index(), use_container_width=True, hide_index=True)
else:
    st.info("No pipeline data yet.")
