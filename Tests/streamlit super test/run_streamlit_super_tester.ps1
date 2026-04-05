param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$StreamlitUrl = "http://127.0.0.1:8501",
    [switch]$Browser,
    [switch]$RunIngest
)

$cmd = @("python", "streamlit_super_tester.py", "--base-url", $BaseUrl, "--streamlit-url", $StreamlitUrl)
if ($Browser) { $cmd += "--browser" }
if ($RunIngest) { $cmd += "--run-ingest" }
& $cmd[0] $cmd[1..($cmd.Length-1)]
