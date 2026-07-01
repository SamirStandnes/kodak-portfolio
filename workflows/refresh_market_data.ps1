# refresh_market_data.ps1
# Quick update for market prices and metadata only (no new transactions).

$ErrorActionPreference = "Stop"
Write-Host "--- Kodak Portfolio: Refresh Market Data ---" -ForegroundColor Cyan

# 1. Map ISINs (Ensure metadata is up to date)
Write-Host "`n[1/4] Checking for missing ISIN mappings..." -ForegroundColor Yellow
python -m kodak.pipeline.map_isins

# 2. Fetch Prices
Write-Host "`n[2/4] Fetching latest market prices..." -ForegroundColor Yellow
python -m kodak.pipeline.fetch_prices

# 3. Export Performance & Holdings JSON
Write-Host "`n[3/4] Exporting performance and holdings data..." -ForegroundColor Yellow
python -m kodak.cli.performance_report --json data/performance.json
if ($LASTEXITCODE -ne 0) { throw "performance_report export failed (exit $LASTEXITCODE) - aborting before stale-data sync." }
# Retry analyze_portfolio once: it occasionally dies on a transient python subprocess/alias error,
# which previously left a stale holdings.json to sync silently.
python -m kodak.cli.analyze_portfolio --json data/holdings.json
if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARN] analyze_portfolio failed (exit $LASTEXITCODE) - retrying once..." -ForegroundColor Yellow
    python -m kodak.cli.analyze_portfolio --json data/holdings.json
    if ($LASTEXITCODE -ne 0) { throw "analyze_portfolio (holdings.json) export failed twice (exit $LASTEXITCODE) - aborting before stale-data sync." }
}

# 4. Sync to oceanview (samirstandnes.com/portfolio) and deploy
Write-Host "`n[4/4] Syncing to oceanview (samirstandnes.com)..." -ForegroundColor Yellow
$OceanviewDir = "C:\Users\Samir\oceanview"
if (-not (Test-Path $OceanviewDir)) {
    Write-Host "[WARN] oceanview repo not found at $OceanviewDir - skipping website sync." -ForegroundColor Yellow
} else {
    Copy-Item "data\holdings.json" "$OceanviewDir\data\holdings.json" -Force
    Copy-Item "data\performance.json" "$OceanviewDir\data\performance.json" -Force
    Push-Location $OceanviewDir
    try {
        $Changed = git status --porcelain data/holdings.json data/performance.json 2>$null
        if (-not $Changed) {
            Write-Host "[OK] Holdings/performance unchanged - nothing to deploy." -ForegroundColor Green
        } else {
            git add data/holdings.json data/performance.json
            git commit -m "Update portfolio data from Kodak ($(Get-Date -Format 'd MMM yyyy'))"
            git push origin main
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[OK] Pushed to oceanview. samirstandnes.com/portfolio auto-deploys in ~1-2 min." -ForegroundColor Green
            } else {
                Write-Host "[ERROR] Git push failed. Sync the changes manually." -ForegroundColor Red
            }
        }
    } finally {
        Pop-Location
    }
}

Write-Host "`n[SUCCESS] Market data refreshed." -ForegroundColor Green
