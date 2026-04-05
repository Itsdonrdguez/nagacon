param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [int]$BatchSize = 200,
    [switch]$SkipIfLeadsExist
)

$ErrorActionPreference = "Stop"

function Get-AllOpportunities {
    param(
        [string]$BaseUrl,
        [int]$BatchSize
    )

    $all = @()
    $offset = 0

    while ($true) {
        $url = "$BaseUrl/api/opportunities?limit=$BatchSize&offset=$offset"
        Write-Host "Fetching opportunities: $url" -ForegroundColor Cyan
        $rows = Invoke-RestMethod -Uri $url -Method Get

        if (-not $rows) { break }

        $count = @($rows).Count
        $all += @($rows)

        if ($count -lt $BatchSize) { break }
        $offset += $BatchSize
    }

    return ,$all
}

function Get-LeadCount {
    param(
        [string]$BaseUrl,
        [int]$OpportunityId
    )

    $url = "$BaseUrl/api/vendors/leads?opportunity_id=$OpportunityId"
    try {
        $resp = Invoke-RestMethod -Uri $url -Method Get
        if ($resp -is [array]) {
            return @($resp).Count
        }
        if ($null -ne $resp.value) {
            return @($resp.value).Count
        }
        return 0
    }
    catch {
        Write-Warning "Could not check leads for opportunity $OpportunityId : $($_.Exception.Message)"
        return 0
    }
}

function Sync-Leads {
    param(
        [string]$BaseUrl,
        [int]$OpportunityId
    )

    $url = "$BaseUrl/api/vendors/leads/sync"
    $body = @{ opportunity_id = $OpportunityId } | ConvertTo-Json

    try {
        $resp = Invoke-RestMethod -Uri $url -Method Post -ContentType "application/json" -Body $body
        return @{
            ok = $true
            response = $resp
            error = $null
        }
    }
    catch {
        $message = $_.Exception.Message
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            $message = $_.ErrorDetails.Message
        }
        return @{
            ok = $false
            response = $null
            error = $message
        }
    }
}

Write-Host ""
Write-Host "=== NagaCon Vendor Extraction for All Opportunities ===" -ForegroundColor Green
Write-Host "Base URL: $BaseUrl"
Write-Host "Batch Size: $BatchSize"
Write-Host "Skip If Leads Exist: $SkipIfLeadsExist"
Write-Host ""

$opps = Get-AllOpportunities -BaseUrl $BaseUrl -BatchSize $BatchSize
$total = @($opps).Count

if ($total -eq 0) {
    Write-Host "No opportunities found." -ForegroundColor Yellow
    exit 0
}

Write-Host "Found $total opportunities." -ForegroundColor Green
Write-Host ""

$results = @()
$index = 0

foreach ($opp in $opps) {
    $index++
    $oppId = [int]$opp.id
    $sol = $opp.solicitation_number
    $title = $opp.title

    Write-Host ("[{0}/{1}] Opportunity {2} | {3} | {4}" -f $index, $total, $oppId, $sol, $title) -ForegroundColor White

    if ($SkipIfLeadsExist) {
        $existing = Get-LeadCount -BaseUrl $BaseUrl -OpportunityId $oppId
        if ($existing -gt 0) {
            Write-Host "  Skipped (already has $existing lead(s))" -ForegroundColor Yellow
            $results += [pscustomobject]@{
                opportunity_id = $oppId
                solicitation_number = $sol
                title = $title
                status = "skipped_existing"
                leads_before = $existing
                details = ""
            }
            continue
        }
    }

    $sync = Sync-Leads -BaseUrl $BaseUrl -OpportunityId $oppId

    if ($sync.ok) {
        Write-Host "  Sync OK" -ForegroundColor Green
        $results += [pscustomobject]@{
            opportunity_id = $oppId
            solicitation_number = $sol
            title = $title
            status = "ok"
            leads_before = ""
            details = ($sync.response | ConvertTo-Json -Depth 6 -Compress)
        }
    }
    else {
        Write-Host "  Sync FAILED: $($sync.error)" -ForegroundColor Red
        $results += [pscustomobject]@{
            opportunity_id = $oppId
            solicitation_number = $sol
            title = $title
            status = "failed"
            leads_before = ""
            details = $sync.error
        }
    }
}

$outCsv = Join-Path (Get-Location) "vendor_extract_results.csv"
$results | Export-Csv -Path $outCsv -NoTypeInformation -Encoding UTF8

Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Green
Write-Host ("Total opportunities: {0}" -f $total)
Write-Host ("Succeeded: {0}" -f (@($results | Where-Object { $_.status -eq "ok" }).Count))
Write-Host ("Skipped existing: {0}" -f (@($results | Where-Object { $_.status -eq "skipped_existing" }).Count))
Write-Host ("Failed: {0}" -f (@($results | Where-Object { $_.status -eq "failed" }).Count))
Write-Host ""
Write-Host "Saved results to: $outCsv" -ForegroundColor Cyan
