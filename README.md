# Kodak Portfolio Tracker 📈

A robust, multi-currency investment portfolio tracking system with a serverless-ready architecture.

## ⚙️ Configuration

Project Kodak is designed to be currency-agnostic. You can configure your global settings in `config.yaml`:

```yaml
# The base currency for all reporting (e.g., NOK, USD, EUR)
base_currency: NOK
```

This setting affects:
- The default currency for new accounts.
- The target currency for all performance reports and charts.
- Automatic FX rate enrichment.

---

## 🚀 Key Features

*   **Plugin-Based Ingestion:** Add support for new brokers just by dropping a Python script into the `parsers/` folder.
*   **Multi-Currency Engine:** Automatic historical FX rate enrichment using Yahoo Finance.
*   **Deep Performance Analysis:** Tracks Realized/Unrealized Gains, Dividend yields, Interest expenses, and FX P&L.
*   **Staging Workflow:** Review and verify transactions before they hit your master database.
*   **Modern Dashboard:** Interactive UI built with Streamlit and Plotly.
*   **Cloud Ready:** Deploy to Heroku for mobile/web access with PostgreSQL backend.

---

## ☁️ Cloud Deployment (Optional)

Want to access your portfolio from your phone? Deploy the dashboard to Heroku:

1. Create a Heroku app with PostgreSQL addon
2. Set `DASHBOARD_PASSWORD` environment variable
3. Connect your GitHub repo for auto-deploy
4. Migrate your local data: `python -m heroku.scripts.migrate_db`

**See:** [Heroku Deployment Guide](heroku/README.md) for full instructions.

---

## 🛠 Setup

For a detailed, step-by-step walkthrough from scratch, see our **[Getting Started Guide](docs/GETTING_STARTED.md)**.

### 1. Prerequisites
Ensure you have **Python 3.9+** installed.

### 2. Installation
Clone the repository and install dependencies:
```bash
git clone https://github.com/SamirStandnes/kodak-portfolio.git
cd kodak-portfolio
pip install -r requirements.txt
```

### 3. Initialize Database
Create your local SQLite database and structure:
```bash
python -m kodak.setup.initialize_database
```

---

## 📂 Project Structure

```text
├── kodak/                     <-- Main package
│   ├── shared/                <-- Core utilities (db, calculations, market_data)
│   ├── pipeline/              <-- Data ingestion & enrichment
│   │   └── parsers/           <-- Broker plugins (nordnet, saxo, etc.)
│   ├── cli/                   <-- Terminal analysis tools
│   ├── dashboard/             <-- Streamlit UI (local)
│   ├── setup/                 <-- Database initialization
│   └── maintenance/           <-- Helper scripts
├── heroku/                    <-- Cloud deployment (Heroku/PostgreSQL)
│   └── scripts/               <-- Migration & price update scripts
├── data/
│   ├── new_raw_transactions/  <-- Place broker exports here
│   └── reference/             <-- ISIN and Account mappings
├── tests/                     <-- Unit tests
├── workflows/                 <-- PowerShell automation scripts
└── database/                  <-- SQLite storage and backups
```

---

## 🔄 Daily Workflow

### Adding New Transactions
1.  **Export:** Download your transaction history from your broker (e.g., Nordnet CSV or Saxo Excel).
2.  **Place:** Move the files to the matching folder in `data/new_raw_transactions/`.
3.  **Run Pipeline:** 
    ```powershell
    .\workflows\add_transactions.ps1
    ```
    *This will ingest files, ask for confirmation to commit to the DB, and then automatically fetch prices and FX rates.*

### Refreshing Prices (No new trades)
To see how your portfolio is doing today without adding new data:
```powershell
.\workflows\refresh_market_data.ps1
```

### Deploying Data to Cloud (Heroku)
To sync your latest local transactions and prices to the Heroku dashboard:
```powershell
.\workflows\deploy_data.ps1
```

### Automate Daily Updates (Optional)
Set up a scheduled task to refresh prices automatically:

**Windows (Task Scheduler):**
1. Open Task Scheduler → Create Basic Task
2. Trigger: "When I log on" or "Daily"
3. Action: Start a program
   - Program: `powershell.exe`
   - Arguments: `-ExecutionPolicy Bypass -File "C:\path\to\kodak-portfolio\workflows\refresh_market_data.ps1"`

**Mac/Linux (cron):**
```bash
# Make script executable (one-time)
chmod +x workflows/refresh_market_data.sh

# Edit crontab
crontab -e

# Add line to run daily at 8am
0 8 * * * /path/to/kodak-portfolio/workflows/refresh_market_data.sh
```

### Launching the Dashboard
```bash
streamlit run kodak/dashboard/Home.py
```

## 📊 Terminal Analysis Tools

Prefer the command line? Use these scripts for quick insights:
- **Portfolio Summary:** `python -m kodak.cli.analyze_portfolio` (Current Value & Unrealized Gains)
- **Yearly Performance:** `python -m kodak.cli.analyze_performance_realized` (Realized Gains, Dividends, & Cash Flow)
- **FX Analysis:** `python -m kodak.cli.analyze_fx` (Currency P&L)
- **Dividends/Fees/Interest:** Check `kodak/cli/` for more specialized tools.

---

## 🧩 Adding a New Broker (Plugin System)

Project Kodak is designed to be infinitely extensible. To add a new broker (e.g., "Robinhood"):

1.  **Create Folder:** `data/new_raw_transactions/robinhood/`
2.  **Inspect Sample:** Run our helper to see the file structure:
    ```bash
    python -m kodak.maintenance.inspect_file path/to/sample.csv
    ```
3.  **Create Parser:** Create `kodak/pipeline/parsers/robinhood.py`.
4.  **Implement:** Define a `parse(file_path)` function that returns the standard transaction schema.

*(Tip: You can paste the output of the inspection tool into an AI like ChatGPT/Claude to have it write the parser for you in seconds!)*

---

## 🧪 Testing

Run the test suite to verify everything works:
```bash
pytest tests/ -v
```

---

## 🤝 Contributing

Contributions are welcome! Please see our [Contributing Guide](CONTRIBUTING.md) for:
- Development setup
- Code style guidelines
- How to add new broker parsers
- Areas where help is needed

---

## ⚖️ License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---
👀 **Curious about what's next?** Check out our [ROADMAP](docs/ROADMAP.md)!
