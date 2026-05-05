# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize database (first-time setup)
python -m kodak.setup.initialize_database

# Run tests
pytest tests/ -v

# Run single test file
pytest tests/test_calculations.py -v

# Run single test
pytest tests/test_calculations.py::TestXirr::test_simple_100_percent_return -v

# Launch dashboard
streamlit run kodak/dashboard/Home.py

# Add new transactions (PowerShell workflow)
.\workflows\add_transactions.ps1

# Refresh market prices only
.\workflows\refresh_market_data.ps1
```

## Architecture Overview

**Pattern:** ELT (Extract, Load, Transform). Raw broker data is loaded into a ledger (`transactions` table), and metrics (holdings, XIRR, P&L) are calculated on-demand at runtime—never pre-computed.

### Data Flow

1. **Ingest** → User drops CSV/Excel in `data/new_raw_transactions/<broker>/`
2. **Parse** → `kodak/pipeline/ingest.py` auto-loads `kodak/pipeline/parsers/<broker>.py`
3. **Stage** → Deduplicated rows go to `transactions_staging` for user review
4. **Commit** → `kodak/pipeline/review_commit.py` moves staged data to permanent `transactions` table
5. **Enrich** → `fetch_prices.py` and `enrich_fx.py` pull market data from Yahoo Finance
6. **Report** → `kodak/shared/calculations.py` computes holdings, cost basis, XIRR

### Key Modules

- **`kodak/shared/calculations.py`** - Core math: XIRR, cost basis, holdings, split adjustments
- **`kodak/shared/db.py`** - SQLite connection management with context managers
- **`kodak/shared/parser_utils.py`** - Transaction validation, `create_empty_transaction()` template
- **`kodak/shared/market_data.py`** - Yahoo Finance integration

### Currency Handling

The system is currency-agnostic. Base currency is set in `config.yaml`:
- `amount` = value in **asset's trading currency** (e.g., USD for Apple)
- `amount_local` = value in **base currency** (e.g., NOK)
- `exchange_rate` = conversion factor (`amount_local / amount`)

Never hardcode currency strings. Always use `load_config().get('base_currency')`.

### Transaction Types

Defined in `config.yaml` under `transaction_types`. Three categories:
- `inflow`: BUY, DEPOSIT, TRANSFER_IN, plus broker-specific variants
- `outflow`: SELL, WITHDRAWAL, TRANSFER_OUT, plus broker-specific variants
- `external_flows`: Cash movements used for XIRR calculation

### Adding a New Parser

1. Create `kodak/pipeline/parsers/<broker>.py`
2. Import `create_empty_transaction` from `parser_utils` and `clean_num` from `utils`
3. Implement `def parse(file_path) -> List[Dict]`
4. Test with `python -m kodak.maintenance.test_parser <broker> path/to/sample.csv`

Parsers must set `currency` to the **asset's** currency, not the settlement currency. Back-calculate `amount` from `amount_local` if needed.

## Heroku Deployment

The same codebase runs both locally (SQLite) and on Heroku (PostgreSQL). Detection is automatic via the `DATABASE_URL` environment variable.

### How It Works

1. **`kodak/dashboard/common.py`** detects `DATABASE_URL` at import time
2. If present, it imports `heroku/setup_adapters.py` which monkey-patches `sys.modules`:
   - `kodak.shared.db` → `heroku/db_adapter.py` (PostgreSQL via psycopg2)
   - `kodak.shared.utils` → `heroku/config_adapter.py` (env vars instead of config.yaml)
3. All downstream imports get the adapter versions automatically
4. `heroku/sql_compat.py` translates SQLite SQL → PostgreSQL (strftime→TO_CHAR, ? → %s, etc.)

### Key Files

- **`heroku/setup_adapters.py`** — Module patching (must load before any kodak imports)
- **`heroku/db_adapter.py`** — PostgreSQL connection adapter (same API as `kodak/shared/db.py`)
- **`heroku/config_adapter.py`** — Config from env vars (replaces `config.yaml`)
- **`heroku/sql_compat.py`** — SQL translation layer (301 lines)
- **`heroku/scripts/migrate_db.py`** — One-way SQLite → PostgreSQL migration
- **`heroku/scripts/update_prices.py`** — Daily price updater (Heroku Scheduler)

### Heroku-Only Features

- **Password auth**: `DASHBOARD_PASSWORD` env var → login screen on all pages

### Entry Point

```
Procfile: web: streamlit run kodak/dashboard/Home.py --server.port=$PORT ...
```

Both local and Heroku use the same entry point (`kodak/dashboard/Home.py`) and modular pages (`kodak/dashboard/pages/`). The old monolithic `heroku/app.py` is deprecated.

### Environment Variables (Heroku)

```bash
heroku config:set DATABASE_URL=<auto-set by Heroku Postgres addon>
heroku config:set DASHBOARD_PASSWORD=<your password>
heroku config:set BASE_CURRENCY=NOK
```

## Code Conventions

- Use `logging` module, not `print()` for debug output
- Use `with get_db_connection() as conn:` for database access
- Validate parser output with `validate_parser_output()` before returning
- Type hints on public functions in shared modules
