# add_transactions.ps1
# Full pipeline to ingest, commit, and enrich new transactions.

param([switch]$y)

$ErrorActionPreference = "Stop"
Write-Host "--- Kodak Portfolio: Add Transactions ---" -ForegroundColor Cyan

# 1. Ingest
Write-Host "`n[1/6] Ingesting files from data/new_raw_transactions/{nordnet,saxo}..." -ForegroundColor Yellow
python -m kodak.pipeline.ingest

# 2. Check Staging
$StagingCount = python -c "from kodak.shared.db import execute_scalar; print(execute_scalar('SELECT COUNT(*) FROM transactions_staging') or 0)"

if ($StagingCount -eq 0) {
    Write-Host "`n[INFO] No new transactions found to process." -ForegroundColor Green
    exit
}

Write-Host "`n[2/6] Found $StagingCount transactions in staging." -ForegroundColor Cyan

if ($y) {
    $confirmation = 'y'
} else {
    $confirmation = Read-Host "Do you want to review and COMMIT these transactions now? (y/n)"
}

if ($confirmation -eq 'y') {
    # 3. Commit
    python -m kodak.pipeline.review_commit

    # 4. Map & Enrich
    Write-Host "`n[3/6] Updating ISIN and Account Maps..." -ForegroundColor Yellow
    python -m kodak.pipeline.map_accounts
    python -m kodak.pipeline.map_isins

    Write-Host "`n[4/6] Fetching Latest Market Prices..." -ForegroundColor Yellow
    python -m kodak.pipeline.fetch_prices

    Write-Host "`n[5/6] Enriching Historical FX Rates..." -ForegroundColor Yellow
    python -m kodak.pipeline.enrich_fx

    Write-Host "`n[6/6] Exporting performance and holdings data..." -ForegroundColor Yellow
    python -m kodak.cli.performance_report --json data/performance.json
    python -m kodak.cli.analyze_portfolio --json data/holdings.json

    Write-Host "`n[SUCCESS] Portfolio updated successfully!" -ForegroundColor Green
} else {
    Write-Host "`n[ABORTED] Transactions remain in staging. Run 'python -m kodak.pipeline.review_commit' later." -ForegroundColor Red
}
