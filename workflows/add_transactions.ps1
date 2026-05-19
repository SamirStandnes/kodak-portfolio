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

    # 7. Push to Heroku (Kodak dashboard at kodak-portfolio.herokuapp.com)
    Write-Host "`n[7/8] Pushing to Kodak Heroku dashboard..." -ForegroundColor Yellow
    $EnvFile = Join-Path $PSScriptRoot "..\.env"
    if (-not (Test-Path $EnvFile)) {
        Write-Host "[WARN] No .env found at $EnvFile — skipping Heroku push. Website will show stale data." -ForegroundColor Yellow
    } else {
        # Load DATABASE_URL from .env (line format: KEY=value)
        $DatabaseUrl = (Get-Content $EnvFile | Where-Object { $_ -match '^DATABASE_URL=' } | Select-Object -First 1) -replace '^DATABASE_URL=', ''
        if (-not $DatabaseUrl) {
            Write-Host "[WARN] DATABASE_URL not in .env — skipping Heroku push." -ForegroundColor Yellow
        } else {
            $env:DATABASE_URL = $DatabaseUrl
            python -m heroku.scripts.migrate_db --sqlite database/portfolio.db
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[OK] Heroku DB updated. Website cache regenerates within 5 min (or restart dyno for instant refresh)." -ForegroundColor Green
                # Try to restart dyno if heroku CLI is authenticated (optional, non-blocking)
                if (Get-Command heroku -ErrorAction SilentlyContinue) {
                    heroku restart -a kodak-portfolio 2>$null
                    if ($LASTEXITCODE -eq 0) {
                        Write-Host "[OK] Heroku dyno restarted — website refreshes immediately on next visit." -ForegroundColor Green
                    }
                }
            } else {
                Write-Host "[ERROR] Heroku migration failed. Website will show stale data." -ForegroundColor Red
            }
        }
    }

    # 8. Sync holdings/performance to oceanview (samirstandnes.com/portfolio) and deploy
    Write-Host "`n[8/8] Syncing to oceanview (samirstandnes.com)..." -ForegroundColor Yellow
    $OceanviewDir = "C:\Users\Samir\oceanview"
    if (-not (Test-Path $OceanviewDir)) {
        Write-Host "[WARN] oceanview repo not found at $OceanviewDir — skipping website sync." -ForegroundColor Yellow
    } else {
        Copy-Item "data\holdings.json" "$OceanviewDir\data\holdings.json" -Force
        Copy-Item "data\performance.json" "$OceanviewDir\data\performance.json" -Force
        Push-Location $OceanviewDir
        try {
            $Changed = git status --porcelain data/holdings.json data/performance.json 2>$null
            if (-not $Changed) {
                Write-Host "[OK] Holdings/performance unchanged — nothing to deploy." -ForegroundColor Green
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

    Write-Host "`n[SUCCESS] Portfolio updated successfully!" -ForegroundColor Green
} else {
    Write-Host "`n[ABORTED] Transactions remain in staging. Run 'python -m kodak.pipeline.review_commit' later." -ForegroundColor Red
}
