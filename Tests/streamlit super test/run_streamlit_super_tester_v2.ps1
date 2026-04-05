param(
  [string]$BaseUrl = "http://127.0.0.1:8000",
  [string]$StreamlitUrl = "http://127.0.0.1:8501",
  [switch]$RunIngest,
  [switch]$Browser,
  [int]$MaxOpps = 3
)

python .\streamlit_super_tester_v2.py --base-url $BaseUrl --streamlit-url $StreamlitUrl --max-opps $MaxOpps $(if ($RunIngest) {"--run-ingest"}) $(if ($Browser) {"--browser"})
