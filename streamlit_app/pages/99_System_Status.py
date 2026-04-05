import pandas as pd
import requests
import streamlit as st

BASE_URL = "http://127.0.0.1:8000"


def safe_json(resp):
    try:
        return resp.json()
    except Exception:
        return None


def api_get(path: str):
    url = f"{BASE_URL}{path}"
    try:
        r = requests.get(url, timeout=12)
        return {"ok": r.ok, "status": r.status_code, "json": safe_json(r), "text": r.text[:500], "url": url}
    except Exception as e:
        return {"ok": False, "status": "ERR", "json": None, "text": str(e), "url": url}


def api_post(path: str, payload=None):
    url = f"{BASE_URL}{path}"
    try:
        r = requests.post(url, json=payload, timeout=30)
        return {"ok": r.ok, "status": r.status_code, "json": safe_json(r), "text": r.text[:500], "url": url}
    except Exception as e:
        return {"ok": False, "status": "ERR", "json": None, "text": str(e), "url": url}


st.set_page_config(page_title="System Status", layout="wide")
st.title("System Status")

health = api_get("/api/health/")
checks = ((health.get("json") or {}).get("checks") or {})
st.subheader("Health")
if checks:
    st.dataframe(pd.DataFrame([{"check": k, "result": v} for k, v in checks.items()]), use_container_width=True, hide_index=True)
else:
    st.code(health["text"] or "No health payload")

st.subheader("Scraper diagnostics")
col1, col2 = st.columns(2)
with col1:
    if st.button("Test SAM route", use_container_width=True):
        st.session_state["sam_diag"] = api_post("/api/scrapers/sam/run", {"limit": 5})
with col2:
    if st.button("Test DIBBS route", use_container_width=True):
        st.session_state["dibbs_diag"] = api_post("/api/scrapers/dibbs/run", {"max_pages": 1, "fsc": "6520"})

sam = st.session_state.get("sam_diag")
dibbs = st.session_state.get("dibbs_diag")
rows = []
if sam:
    rows.append({"scraper": "SAM", "status": sam["status"], "ok": sam["ok"], "detail": (sam["json"] or {}).get("detail", sam["text"])})
if dibbs:
    rows.append({"scraper": "DIBBS", "status": dibbs["status"], "ok": dibbs["ok"], "detail": (dibbs["json"] or {}).get("detail", dibbs["text"])})
if rows:
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
else:
    st.caption("Click a test button to run route checks.")

st.subheader("Quick workspace jump")
opp_id = st.number_input("Opportunity ID", min_value=1, value=49, step=1)
st.markdown(f"[Go to workspace](/Workspace?opp_id={opp_id})")

st.subheader("Latest opportunities")
opps = api_get("/api/opportunities?limit=25&offset=0")
data = opps.get("json") or []
if isinstance(data, list) and data:
    df = pd.DataFrame(data)
    rows_html = []
    for _, r in df.iterrows():
        oid = int(r["id"])
        sol = r.get("solicitation_number") or "NO-SOL"
        rows_html.append(f"<tr><td><a href='/Workspace?opp_id={oid}' target='_self'>{sol}</a></td><td>{r.get('title','')}</td><td>{r.get('agency','')}</td><td>{r.get('status','')}</td></tr>")
    st.markdown("<table style='width:100%; border-collapse:collapse;'><thead><tr><th style='text-align:left;'>Solicitation #</th><th style='text-align:left;'>Title</th><th style='text-align:left;'>Agency</th><th style='text-align:left;'>Status</th></tr></thead><tbody>" + ''.join(rows_html) + "</tbody></table>", unsafe_allow_html=True)
else:
    st.code(opps["text"] or "No opportunities returned")
