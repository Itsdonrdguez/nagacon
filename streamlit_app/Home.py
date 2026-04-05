import streamlit as st

st.set_page_config(page_title="NagaCon", layout="wide")

st.title("NagaCon")
st.write("MVP dashboard. Use the **Opportunities** page to browse, then open a workspace.")
st.page_link("pages/1_Opportunities.py", label="Go to Opportunities", icon="📋")
