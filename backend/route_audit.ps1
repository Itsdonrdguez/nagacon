param(
    [string]$BackendRoot = ".",
    [string]$BaseUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Continue"

function Write-Section($title) {
    Write-Host ""
    Write-Host ("=" * 80) -ForegroundColor DarkGray
    Write-Host $title -ForegroundColor Cyan
    Write-Host ("=" * 80) -ForegroundColor DarkGray
}

function Test-Url {
    param(
        [string]$Name,
        [string]$Method,
        [string]$Url,
        [object]$Body = $null
    )

    try {
        if ($null -ne $Body) {
            $json = $Body | ConvertTo-Json -Depth 20
            $resp = Invoke-WebRequest -Uri $Url -Method $Method -ContentType "application/json" -Body $json -UseBasicParsing
        } else {
            $resp = Invoke-WebRequest -Uri $Url -Method $Method -UseBasicParsing
        }

        return [PSCustomObject]@{
            name = $Name
            method = $Method
            url = $Url
            status = $resp.StatusCode
            ok = $true
        }
    }
    catch {
        $status = $null
        try { $status = $_.Exception.Response.StatusCode.value__ } catch {}

        return [PSCustomObject]@{
            name = $Name
            method = $Method
            url = $Url
            status = $status
            ok = $false
        }
    }
}

Write-Section "1) main.py include_router inventory"
$main = Join-Path $BackendRoot "app\main.py"
if (Test-Path $main) {
    Get-Content $main | Select-String -Pattern "include_router|from app\.api|from app\.api\.routes" | ForEach-Object {
        $_.Line
    }
} else {
    Write-Host "Could not find $main" -ForegroundColor Yellow
}

Write-Section "2) API file inventory"
$apiRoot = Join-Path $BackendRoot "app\api"
if (Test-Path $apiRoot) {
    Get-ChildItem $apiRoot -Recurse -File | ForEach-Object {
        $_.FullName.Replace((Resolve-Path $BackendRoot).Path + "\", "")
    }
} else {
    Write-Host "Could not find $apiRoot" -ForegroundColor Yellow
}

Write-Section "3) Route decorator inventory"
if (Test-Path $apiRoot) {
    Get-ChildItem $apiRoot -Recurse -File -Include *.py | ForEach-Object {
        $file = $_.FullName
        $matches = Select-String -Path $file -Pattern '@router\.(get|post|patch|put|delete)\('
        if ($matches) {
            Write-Host ""
            Write-Host ($file.Replace((Resolve-Path $BackendRoot).Path + "\", "")) -ForegroundColor Green
            $matches | ForEach-Object { $_.Line.Trim() }
        }
    }
}

Write-Section "4) Route probe results"
$checks = @(
    @{ name="opportunities list"; method="GET"; url="$BaseUrl/api/opportunities?limit=5&offset=0" },
    @{ name="opportunity detail"; method="GET"; url="$BaseUrl/api/opportunities/49" },
    @{ name="workspace summary"; method="GET"; url="$BaseUrl/api/workspace/summary?opp_id=49" },
    @{ name="opportunities ingest"; method="POST"; url="$BaseUrl/api/opportunities/ingest"; body=@(@{source="manual_test";source_opportunity_id="AUDIT-001";solicitation_number="AUDIT-001";title="Audit Test Opportunity";agency="Audit Agency";posted_at="2026-03-15";due_at="2026-03-30";raw_payload=@{note="audit"}}) },
    @{ name="sam scraper"; method="POST"; url="$BaseUrl/api/scrapers/sam/run"; body=@{limit=1} },
    @{ name="dibbs scraper"; method="POST"; url="$BaseUrl/api/scrapers/dibbs/run"; body=@{fsc="6515"} },
    @{ name="pipeline"; method="GET"; url="$BaseUrl/api/pipeline/1" },
    @{ name="vendor discovery"; method="POST"; url="$BaseUrl/api/vendors/opportunities/49/discover" },
    @{ name="quotes"; method="GET"; url="$BaseUrl/api/quotes/opportunities/49" },
    @{ name="company profile"; method="GET"; url="$BaseUrl/api/company/profile/1" },
    @{ name="proposal draft"; method="POST"; url="$BaseUrl/api/agents/opportunities/49/proposal-draft" },
    @{ name="analytics"; method="GET"; url="$BaseUrl/api/analytics/summary" },
    @{ name="files"; method="GET"; url="$BaseUrl/api/files" },
    @{ name="document parse"; method="POST"; url="$BaseUrl/api/documents/1/parse" }
)

$results = foreach ($c in $checks) {
    Test-Url -Name $c.name -Method $c.method -Url $c.url -Body $c.body
}

$results | Format-Table -AutoSize

Write-Section "5) Suggested interpretation"
foreach ($r in $results) {
    if ($null -eq $r.status) {
        $statusText = "ERR"
    } else {
        $statusText = [string]$r.status
    }

    $meaning = switch ($r.status) {
        200 { "mounted and working" }
        201 { "mounted and working" }
        400 { "mounted but needs input/config" }
        401 { "mounted but auth/config blocked" }
        404 { "not mounted or wrong route path" }
        422 { "mounted but request body/query shape is wrong" }
        500 { "mounted but backend logic/schema failed" }
        502 { "mounted but upstream scraper failed" }
        default {
            if ($null -eq $r.status) { "could not connect / request failed before HTTP response" }
            else { "status needs review" }
        }
    }

    Write-Host ("{0,-24} {1,-5} {2}" -f $r.name, $statusText, $meaning)
}

Write-Section "6) Next action checklist"
@(
    "Open app\main.py and compare include_router lines to the 404 routes above.",
    "For each 404 route, check whether the route file exists under app\api or app\api\routes.",
    "If the file exists, import its router in main.py and include_router(..., prefix='/api').",
    "If the file does not exist, mark it as planned/not implemented yet.",
    "For 422 routes, inspect the request model in the endpoint signature and update the client body shape.",
    "For 500 routes, inspect traceback and fix schema/model mismatches.",
    "For 502 routes, inspect external scraper response and parser assumptions."
) | ForEach-Object { Write-Host ("- " + $_) }
