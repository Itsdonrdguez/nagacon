$ErrorActionPreference = "Stop"

$backendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $backendRoot

$listenerLines = netstat -ano | Select-String ':8000'
$pids = @()

foreach ($line in $listenerLines) {
  $parts = ($line.ToString() -replace '\s+', ' ').Trim().Split(' ')
  if ($parts.Length -ge 5) {
    $pid = $parts[-1]
    if ($pid -match '^\d+$' -and $pids -notcontains $pid) {
      $pids += $pid
    }
  }
}

foreach ($pid in $pids) {
  try {
    Stop-Process -Id ([int]$pid) -Force -ErrorAction Stop
    Write-Host "Stopped process on port 8000: $pid"
  } catch {
    Write-Warning "Could not stop process $pid: $($_.Exception.Message)"
  }
}

Start-Sleep -Seconds 1

Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "run_server.py" -WorkingDirectory $backendRoot
Write-Host "Backend restart requested from $backendRoot"
