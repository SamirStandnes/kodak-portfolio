# Heroku Deployment for Kodak Portfolio

This directory contains the cloud-ready version of the Kodak portfolio dashboard for deployment on Heroku.

## Features

- PostgreSQL database (instead of SQLite)
- Password-protected dashboard
- Daily automatic price updates via Heroku Scheduler
- Read-only dashboard (no transaction import)

## Prerequisites

- Heroku CLI installed and logged in
- Local PostgreSQL for testing (optional)
- Python 3.11+

## Deployment Steps

### 1. Create Heroku App

```bash
# From project root
heroku create your-app-name
```

### 2. Add PostgreSQL

```bash
heroku addons:create heroku-postgresql:essential-0
```

### 3. Set Environment Variables

```bash
heroku config:set DASHBOARD_PASSWORD=your-secure-password
heroku config:set BASE_CURRENCY=NOK
```

### 4. Deploy

Option A: Deploy entire repo (simpler):
```bash
# Copy heroku requirements to root for Heroku buildpack
copy heroku\requirements.txt requirements-heroku.txt

# Create Procfile at root (or rename existing)
# web: streamlit run heroku/app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true

git push heroku main
```

Option B: Deploy using git subtree (cleaner):
```bash
# Create a deployment branch
git subtree split --prefix heroku -b heroku-deploy
git push heroku heroku-deploy:main
```

### 5. Migrate Data

You can now use the automated deployment script to sync your local data to Heroku:

```powershell
# This script uses the DATABASE_URL stored in your local .env file
.\workflows\deploy_data.ps1
```

Alternatively, run the migration script manually:
```bash
# Run migration
python -m heroku.scripts.migrate_db --sqlite database/portfolio.db --pg-url "your-database-url"
```

## Set Up Daily Price Updates

```bash
# Add Heroku Scheduler
heroku addons:create scheduler:standard

# Open scheduler dashboard
heroku addons:open scheduler
```

In the scheduler dashboard, add a new job:
- **Command:** `python heroku/scripts/update_prices.py`
- **Frequency:** Daily
- **Time:** 20:00 UTC (after markets close)

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes (auto) | PostgreSQL connection URL (set automatically by Heroku) |
| `DASHBOARD_PASSWORD` | Yes | Password to access the dashboard |
| `BASE_CURRENCY` | No | Base currency for reporting (default: NOK) |

## Local Testing

To test locally with PostgreSQL:

1. Install PostgreSQL and create a database
2. Set environment variables:
   ```bash
   set DATABASE_URL=postgresql://user:pass@localhost:5432/kodak
   set DASHBOARD_PASSWORD=test123
   set BASE_CURRENCY=NOK
   ```
3. Run migrations:
   ```bash
   python -m heroku.scripts.migrate_db --sqlite database/portfolio.db
   ```
4. Start the app:
   ```bash
   streamlit run heroku/app.py
   ```

## Updating Data

When you add new transactions locally:

1. Process transactions locally (using the main workflow)
2. Sync to Heroku using the automated script:
   ```powershell
   .\workflows\deploy_data.ps1
   ```
   *Note: This will overwrite all data in the Heroku database with your local data.*

## Files

- `app.py` - Main Streamlit application with authentication
- `db_adapter.py` - PostgreSQL database adapter
- `sql_compat.py` - SQLite to PostgreSQL SQL translation
- `config_adapter.py` - Environment-based configuration
- `setup_adapters.py` - Module patching setup
- `scripts/migrate_db.py` - Database migration script
- `scripts/update_prices.py` - Daily price update script
- `Procfile` - Heroku process definition
- `runtime.txt` - Python version specification
- `requirements.txt` - Python dependencies
