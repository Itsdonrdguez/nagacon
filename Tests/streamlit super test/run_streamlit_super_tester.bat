@echo off
setlocal
python streamlit_super_tester.py --base-url http://127.0.0.1:8000 --streamlit-url http://127.0.0.1:8501 --run-ingest --browser
endlocal
