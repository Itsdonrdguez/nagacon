param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [int]$OpportunityId = 49
)

$ErrorActionPreference = "Continue"

function Test-Endpoint {
    param(
        [string]$Name,
        [string]$Method,
        [string]$Url,
        [object]$Body = $null
    )

    Write-Host ""
    Write-Host "=== $Name ===" -ForegroundColor Cyan
    Write-Host "$Method $Url" -ForegroundColor DarkGray

    try {
        if ($null -ne $Body) {
            $json = $Body | ConvertTo-Json -Depth 20
            $resp = Invoke-RestMethod -Uri $Url -Method $Method -ContentType "application/json" -Body $json
        } else {
            $resp = Invoke-RestMethod -Uri $Url -Method $Method
        }

        Write-Host "PASS" -ForegroundColor Green
        $resp | ConvertTo-Json -Depth 20
    }
    catch {
        $statusCode = $null
        $raw = $null

        try { $statusCode = $_.Exception.Response.StatusCode.value__ } catch {}
        try {
            $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            $raw = $reader.ReadToEnd()
        } catch {
            $raw = $_.Exception.Message
        }

        Write-Host "FAIL" -ForegroundColor Yellow
        if ($statusCode) { Write-Host "HTTP $statusCode" -ForegroundColor Yellow }
        if ($raw) { Write-Host $raw }
    }
}

Write-Host "NagaCon Backend Smoke Test" -ForegroundColor Magenta
Write-Host "Base URL: $BaseUrl"
Write-Host "Opportunity ID: $OpportunityId"

Test-Endpoint `
    -Name "Opportunities list" `
    -Method "GET" `
    -Url "$BaseUrl/api/opportunities?limit=5&offset=0"

Test-Endpoint `
    -Name "Opportunity detail" `
    -Method "GET" `
    -Url "$BaseUrl/api/opportunities/$OpportunityId"

Test-Endpoint `
    -Name "Workspace summary" `
    -Method "GET" `
    -Url "$BaseUrl/api/workspace/summary?opp_id=$OpportunityId"

$ingestBody = @(
    @{
        source = "manual_test"
        source_opportunity_id = "TEST-001"
        solicitation_number = "TEST-001"
        title = "Test Opportunity"
        agency = "Test Agency"
        posted_at = "2026-03-15"
        due_at = "2026-03-30"
        raw_payload = @{
            note = "manual ingest test"
        }
    }
)

Test-Endpoint `
    -Name "Manual ingest" `
    -Method "POST" `
    -Url "$BaseUrl/api/opportunities/ingest" `
    -Body $ingestBody

Test-Endpoint `
    -Name "SAM scraper (requires SAM_API_KEY)" `
    -Method "POST" `
    -Url "$BaseUrl/api/scrapers/sam/run" `
    -Body @{ limit = 5 }

Test-Endpoint `
    -Name "DIBBS scraper" `
    -Method "POST" `
    -Url "$BaseUrl/api/scrapers/dibbs/run" `
    -Body @{ fsc = "6515" }

Test-Endpoint `
    -Name "Pipeline route probe" `
    -Method "GET" `
    -Url "$BaseUrl/api/pipeline/1"

Test-Endpoint `
    -Name "Vendor discovery route probe" `
    -Method "POST" `
    -Url "$BaseUrl/api/vendors/opportunities/$OpportunityId/discover"

Test-Endpoint `
    -Name "Quotes route probe" `
    -Method "GET" `
    -Url "$BaseUrl/api/quotes/opportunities/$OpportunityId"

Test-Endpoint `
    -Name "Company profile route probe" `
    -Method "GET" `
    -Url "$BaseUrl/api/company/profile/1"

Test-Endpoint `
    -Name "Proposal agent route probe" `
    -Method "POST" `
    -Url "$BaseUrl/api/agents/opportunities/$OpportunityId/proposal-draft"

Test-Endpoint `
    -Name "Analytics route probe" `
    -Method "GET" `
    -Url "$BaseUrl/api/analytics/summary"

Test-Endpoint `
    -Name "Files route probe" `
    -Method "GET" `
    -Url "$BaseUrl/api/files"

Test-Endpoint `
    -Name "Document parse route probe" `
    -Method "POST" `
    -Url "$BaseUrl/api/documents/1/parse"

Write-Host ""
Write-Host "Smoke test finished." -ForegroundColor Magenta
Write-Host "PASS means the route exists and returned successfully." -ForegroundColor DarkGray
Write-Host "FAIL with 404 means the route is not mounted yet." -ForegroundColor DarkGray
Write-Host "FAIL with 500 means the route exists but backend logic/schema still needs work." -ForegroundColor DarkGray
