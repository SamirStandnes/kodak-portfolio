"""
Environment-based configuration adapter for Heroku deployment.
Provides the same interface as kodak/shared/utils.load_config() but uses environment variables.
"""
import os
import logging
import hashlib
import pandas as pd
from typing import Optional, Union, Dict, Any


def load_config() -> Dict[str, Any]:
    """
    Loads configuration from environment variables.
    Provides the same interface as kodak/shared/utils.load_config()
    """
    # Base currency from environment or default
    base_currency = os.environ.get('BASE_CURRENCY', 'NOK')

    # Transaction types - these are hardcoded since they rarely change
    # and don't need to be configurable per-environment
    transaction_types = {
        'inflow': [
            'BUY',
            'DEPOSIT',
            'TRANSFER_IN',
            'TILDELING INNLEGG RE',
            'BYTTE INNLEGG VP',
            'EMISJON INNLEGG VP',
            'UTSKILLING FISJON IN',
        ],
        'outflow': [
            'SELL',
            'WITHDRAWAL',
            'TRANSFER_OUT',
            'BYTTE UTTAK VP',
            'INNLØSN. UTTAK VP',
        ],
        'external_flows': [
            'DEPOSIT',
            'WITHDRAWAL',
            'TRANSFER_IN',
            'TRANSFER_OUT',
            'OVERFØRING VIA TRUSTLY',
        ]
    }

    return {
        'base_currency': base_currency,
        'data_dir': 'data',
        'reference_dir': 'data/reference',
        'isin_map_file': 'isin_map.csv',
        'accounts_map_file': 'accounts_map.csv',
        'transaction_types': transaction_types,
    }


def setup_logging(script_name: str) -> str:
    """Configures logging for Heroku (console only, no file logging)."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler()
        ]
    )
    return f"{script_name}.log"


def clean_num(val: Union[str, float, int, None]) -> float:
    """Converts various number formats to float safely."""
    if pd.isna(val) or val == '':
        return 0.0
    if isinstance(val, (float, int)):
        return float(val)
    val = str(val).replace(' ', '').replace(',', '.')
    try:
        return float(val)
    except ValueError:
        return 0.0


def generate_txn_hash(date: str, account_id: str, type: str, symbol: str, amount: float) -> str:
    """Generates a stable hash to identify duplicate transactions."""
    date_str = str(date).split(' ')[0]
    amt_str = f"{amount:.2f}"

    raw_str = f"{date_str}|{account_id}|{type}|{symbol}|{amt_str}"
    return hashlib.md5(raw_str.encode()).hexdigest()


def format_local(val: Union[float, int], decimals: int = 0) -> str:
    """Formats a number using Norwegian style (space for thousands, comma for decimal)."""
    if pd.isna(val):
        return "0"

    formatted = f"{val:,.{decimals}f}"
    return formatted.replace(",", " ").replace(".", ",")
