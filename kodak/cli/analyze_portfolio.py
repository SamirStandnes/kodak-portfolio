import argparse
import json
import pandas as pd
from kodak.shared.db import get_connection, execute_query
from kodak.shared.market_data import get_latest_prices, get_exchange_rate
from kodak.shared.calculations import get_holdings, get_income_and_costs
from kodak.shared.utils import load_config
from rich.console import Console
from rich.table import Table

# --- CONFIG ---
config = load_config()
BASE_CURRENCY = config.get('base_currency', 'NOK')


def get_portfolio_data():
    """Get portfolio data for display or export."""
    df_holdings = get_holdings()
    if df_holdings.empty:
        return None, None

    # Get Latest Prices & Currencies
    price_rows = execute_query('''
        SELECT mp.instrument_id, mp.close, i.currency,
               i.sector, i.region, i.country, i.asset_class
        FROM market_prices mp
        JOIN instruments i ON mp.instrument_id = i.id
        WHERE (mp.instrument_id, mp.date) IN (
            SELECT instrument_id, MAX(date)
            FROM market_prices
            GROUP BY instrument_id
        )
    ''')

    price_map = {}
    for row in price_rows:
        price_map[row['instrument_id']] = {
            'price': row['close'],
            'currency': row['currency'],
            'sector': row['sector'],
            'region': row['region'],
            'country': row['country'],
            'asset_class': row['asset_class']
        }

    fx_cache = {}
    portfolio_data = []
    total_market_value = 0
    total_cost_basis = 0

    for _, row in df_holdings.iterrows():
        inst_id = row['instrument_id']
        market_data = price_map.get(inst_id)

        if not market_data:
            price_nok = 0
            price_raw = 0
            curr = 'UNK'
        else:
            price_raw = market_data['price']
            curr = market_data['currency']

        if curr == BASE_CURRENCY:
            price_nok = price_raw
        else:
            if curr not in fx_cache:
                fx_cache[curr] = get_exchange_rate(curr, BASE_CURRENCY)
            price_nok = price_raw * fx_cache[curr]

        market_value = row['quantity'] * price_nok
        cost_basis = row['cost_basis_local']
        gain_loss = market_value - cost_basis
        return_pct = (market_value / cost_basis - 1) * 100 if cost_basis > 0 else 0

        portfolio_data.append({
            'symbol': row['symbol'] or row['isin'],
            'quantity': row['quantity'],
            'avg_cost': cost_basis / row['quantity'] if row['quantity'] > 0 else 0,
            'price': price_raw,
            'currency': curr,
            'market_value': market_value,
            'gain_loss': gain_loss,
            'return_pct': return_pct,
            'sector': market_data.get('sector') if market_data else None,
            'region': market_data.get('region') if market_data else None,
            'country': market_data.get('country') if market_data else None,
            'asset_class': market_data.get('asset_class') if market_data else None
        })

        total_market_value += market_value
        total_cost_basis += cost_basis

    # Calculate weight percentages
    for item in portfolio_data:
        item['weight_pct'] = (item['market_value'] / total_market_value * 100) if total_market_value > 0 else 0

    # Calculate cash balance
    cash_balance_nok = pd.read_sql(
        "SELECT COALESCE(SUM(amount_local), 0) as total FROM transactions", get_connection()
    ).iloc[0]['total']

    summary = {
        'total_market_value': total_market_value,
        'total_cost_basis': total_cost_basis,
        'total_gain_loss': total_market_value - total_cost_basis,
        'cash_balance': cash_balance_nok,
        'net_worth': total_market_value + cash_balance_nok
    }

    return portfolio_data, summary


def export_holdings_json(output_path: str) -> None:
    """Export holdings data to JSON for external projects (e.g., oceanview)."""
    portfolio_data, summary = get_portfolio_data()

    if portfolio_data is None:
        print("No holdings found.")
        return

    # Sort by market value descending
    portfolio_data.sort(key=lambda x: x['market_value'], reverse=True)

    holdings = [
        {
            'symbol': h['symbol'],
            'sector': h['sector'],
            'region': h['region'],
            'country': h['country'],
            'asset_class': h['asset_class'],
            'quantity': round(h['quantity'], 2),
            'cost_basis': round(h['quantity'] * h['avg_cost'], 0),
            'market_value': round(h['market_value'], 0),
            'weight_pct': round(h['weight_pct'], 1),
            'return_pct': round(h['return_pct'], 1)
        }
        for h in portfolio_data
    ]

    output = {
        'holdings': holdings,
        'total_market_value': round(summary['total_market_value'], 0),
        'total_cost_basis': round(summary['total_cost_basis'], 0),
        'cash_balance': round(summary['cash_balance'], 0),
        'net_worth': round(summary['net_worth'], 0)
    }

    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"Holdings data exported to: {output_path}")


def analyze_portfolio():
    parser = argparse.ArgumentParser(description="Kodak Portfolio Analysis")
    parser.add_argument("--json", metavar="FILE", help="Export holdings data to JSON file")
    args = parser.parse_args()

    if args.json:
        export_holdings_json(args.json)
        return

    console = Console()

    portfolio_data, summary = get_portfolio_data()
    if portfolio_data is None:
        console.print("[yellow]No holdings found.[/yellow]")
        return

    # Sort by market value descending
    portfolio_data.sort(key=lambda x: x['market_value'], reverse=True)

    # Render Table
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Symbol")
    table.add_column("Qty", justify="right")
    table.add_column(f"Avg Cost ({BASE_CURRENCY})", justify="right")
    table.add_column("Price", justify="right")
    table.add_column("Curr", style="dim")
    table.add_column(f"Market Value ({BASE_CURRENCY})", justify="right", style="bold yellow")
    table.add_column("Gain/Loss", justify="right")
    table.add_column("Return %", justify="right")

    for row in portfolio_data:
        gl_style = "green" if row['gain_loss'] >= 0 else "red"
        ret_str = f"{row['return_pct']:.2f}%"
        if row['return_pct'] < -99:
            ret_str = "-100%"

        table.add_row(
            row['symbol'],
            f"{row['quantity']:,.2f}",
            f"{row['avg_cost']:,.2f}",
            f"{row['price']:,.2f}",
            row['currency'],
            f"{row['market_value']:,.0f}",
            f"[{gl_style}]{row['gain_loss']:,.0f}[/{gl_style}]",
            f"[{gl_style}]{ret_str}[/{gl_style}]"
        )

    console.print(table)

    # Summary Metrics
    income = get_income_and_costs()
    total_gl = summary['total_gain_loss']

    summary_table = Table(show_header=False, box=None)
    summary_table.add_row("Total Market Value", f"{summary['total_market_value']:,.0f} {BASE_CURRENCY}")
    summary_table.add_row("Total Cost Basis", f"{summary['total_cost_basis']:,.0f} {BASE_CURRENCY}")

    gl_color = "green" if total_gl >= 0 else "red"
    summary_table.add_row("Total Gain/Loss", f"[{gl_color}]{total_gl:,.0f} {BASE_CURRENCY}[/{gl_color}]")

    summary_table.add_row("Estimated Cash", f"{summary['cash_balance']:,.0f} {BASE_CURRENCY}")
    summary_table.add_row("Total Net Worth", f"{summary['net_worth']:,.0f} {BASE_CURRENCY}")

    summary_table.add_section()
    summary_table.add_row("Total Dividends", f"[green]{income['dividends']:,.0f} {BASE_CURRENCY}[/green]")
    summary_table.add_row("Total Interest", f"{income['interest']:,.0f} {BASE_CURRENCY}")
    summary_table.add_row("Total Fees", f"[red]{income['fees']:,.0f} {BASE_CURRENCY}[/red]")

    console.print("\n[bold]Summary Statistics[/bold]")
    console.print(summary_table)

if __name__ == "__main__":
    analyze_portfolio()