
import streamlit as st
import requests

API = "http://127.0.0.1:8000"

st.title("USAspending Research")

opp_id = st.number_input("Opportunity ID", step=1)

if st.button("Run Research"):
    r = requests.post(f"{API}/api/research/usaspending/opportunities/{opp_id}")
    data = r.json()

    st.subheader("Likely Vendors")
    st.dataframe(data["likely_vendors"])

    st.subheader("Similar Awards")
    st.dataframe(data["awards"])
