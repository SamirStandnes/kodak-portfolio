# Deploy Data to hosted Kodak dashboard
# This script migrates the local SQLite database to the hosted PostgreSQL database.

$ErrorActionPreference = "Stop"

# Get the project root directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

# Path to .env file
$envFile = Join-Path $projectRoot ".env"

# Load environment variables from .env
if (Test-Path $envFile) {
    Write-Host "Loading configuration from .env..." -ForegroundColor Cyan
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^([^=]+)=(.*)$') {
            $name = $matches[1]
            $value = $matches[2]
            Set-Content env:$name $value
        }
    }
} else {
    Write-Error "Could not find .env file at $envFile"
    exit 1
}

# Check if DATABASE_URL is set
if (-not $env:DATABASE_URL) {
    Write-Error "DATABASE_URL is not set in .env file."
    exit 1
}

# Run the migration
Write-Host "Starting migration to hosted PostgreSQL..." -ForegroundColor Cyan
Write-Host "Source: database/portfolio.db"
Write-Host "Destination: Hosted PostgreSQL"

python -m heroku.scripts.migrate_db --sqlite database/portfolio.db
$migrationExit = $LASTEXITCODE

if ($migrationExit -eq 0) {
    Write-Host "`nMigration completed successfully!" -ForegroundColor Green
} else {
    Write-Host "`nMigration failed (exit $migrationExit). Hosted database left unchanged." -ForegroundColor Red
}

# Propagate the exit code so add_transactions.ps1 can tell success from failure.
exit $migrationExit
