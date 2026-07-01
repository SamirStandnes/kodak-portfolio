# add_transactions.ps1
# Full pipeline to ingest, commit, and enrich new transactions.

param([switch]$y)

$ErrorActionPreference = "Stop"
Write-Host "--- Kodak Portfolio: Add Transactions ---" -ForegroundColor Cyan

# 1. Ingest
Write-Host "`n[1/8] Ingesting files from data/new_raw_transactions/{nordnet,saxo}..." -ForegroundColor Yellow
python -m kodak.pipeline.ingest

# 2. Check Staging
$StagingCount = python -c "from kodak.shared.db import execute_scalar; print(execute_scalar('SELECT COUNT(*) FROM transactions_staging') or 0)"

if ($StagingCount -eq 0) {
    Write-Host "`n[INFO] No new transactions found to process." -ForegroundColor Green
    exit
}

Write-Host "`n[2/8] Found $StagingCount transactions in staging." -ForegroundColor Cyan

if ($y) {
    $confirmation = 'y'
} else {
    $confirmation = Read-Host "Do you want to review and COMMIT these transactions now? (y/n)"
}

if ($confirmation -eq 'y') {
    # 3. Commit
    if ($y) {
        python -m kodak.pipeline.review_commit --yes
    } else {
        python -m kodak.pipeline.review_commit
    }

    # 4. Map & Enrich
    Write-Host "`n[3/8] Updating ISIN and Account Maps..." -ForegroundColor Yellow
    python -m kodak.pipeline.map_accounts
    python -m kodak.pipeline.map_isins

    Write-Host "`n[4/8] Fetching Latest Market Prices..." -ForegroundColor Yellow
    python -m kodak.pipeline.fetch_prices

    Write-Host "`n[5/8] Enriching Historical FX Rates..." -ForegroundColor Yellow
    python -m kodak.pipeline.enrich_fx

    Write-Host "`n[6/8] Exporting performance and holdings data..." -ForegroundColor Yellow
    python -m kodak.cli.performance_report --json data/performance.json
    python -m kodak.cli.analyze_portfolio --json data/holdings.json

    # 7. Sync holdings/performance to oceanview (samirstandnes.com/portfolio) and deploy
    # Keep this before the cloud dashboard push so the public portfolio page is updated
    # even if the database migration is slow or fails.
    Write-Host "`n[7/8] Syncing to oceanview (samirstandnes.com)..." -ForegroundColor Yellow
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
                $CommitMsg = "Update portfolio data from Kodak ($(Get-Date -Format 'd MMM yyyy'))"
                git commit -m $CommitMsg
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

    # 8. Push to hosted Kodak dashboard (Streamlit Cloud + Neon)
    Write-Host "`n[8/8] Pushing to hosted Kodak dashboard..." -ForegroundColor Yellow
    $DeployScript = Join-Path $PSScriptRoot "deploy_data.ps1"
    if (-not (Test-Path $DeployScript)) {
        Write-Host "[WARN] deploy_data.ps1 not found - skipping dashboard database push." -ForegroundColor Yellow
    } else {
        & $DeployScript
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] Hosted dashboard database updated." -ForegroundColor Green
        } else {
            Write-Host "[ERROR] Dashboard database push failed. Oceanview was already synced." -ForegroundColor Red
        }
    }

    Write-Host "`n[SUCCESS] Portfolio updated successfully!" -ForegroundColor Green
} else {
    Write-Host "`n[ABORTED] Transactions remain in staging. Run 'python -m kodak.pipeline.review_commit' later." -ForegroundColor Red
}
