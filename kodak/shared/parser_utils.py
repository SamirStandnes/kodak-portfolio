import logging
import uuid
from typing import Dict, Any, List, Tuple

import pandas as pd

from kodak.shared.utils import clean_num as _clean_num, load_config

logger = logging.getLogger(__name__)

# --- Constants ---
config = load_config()
BASE_CURRENCY = config.get('base_currency', 'NOK')

# Valid transaction types
VALID_TRANSACTION_TYPES = {
    'BUY', 'SELL', 'DIVIDEND', 'DEPOSIT', 'WITHDRAWAL',
    'INTEREST', 'FEE', 'TAX', 'TRANSFER_IN', 'TRANSFER_OUT',
    'CURRENCY_EXCHANGE', 'ADJUSTMENT', 'OTHER',
    'CFD',  # derivative position: cash P&L only, never a share quantity
    # Broker-specific types that get mapped
    'TILDELING INNLEGG RE', 'BYTTE INNLEGG VP', 'BYTTE UTTAK VP',
    'EMISJON INNLEGG VP', 'INNLØSN. UTTAK VP', 'UTSKILLING FISJON IN',
    'INNSKUDD KONTANTER', 'TILBAKEBET. FOND AVG', 'SLETTING UTTAK VP',
}

# Standard Schema Contract
def create_empty_transaction() -> Dict[str, Any]:
    """Returns a dictionary with all required keys initialized to safe defaults."""
    return {
        'external_id': str(uuid.uuid4()),
        'account_external_id': None,
        'isin': None,
        'symbol': None,
        'date': None,
        'type': 'OTHER',
        'quantity': 0.0,
        'price': 0.0,
        'amount': 0.0,        # Asset Currency
        'currency': BASE_CURRENCY,
        'amount_local': 0.0,  # Base Currency
        'exchange_rate': 1.0,
        'description': '',
        'source_file': '',
        'fee': 0.0,
        'fee_currency': BASE_CURRENCY,
        'fee_local': 0.0,
        # Broker-side record of truth; leave None when the export has no such field
        'broker_id': None,          # broker's own unique transaction id
        'balance_after': None,      # broker cash balance after this row
        'balance_currency': None,   # currency of balance_after
    }

def clean_num(val) -> float:
    """Wrapper for shared clean_num."""
    return _clean_num(val)


def validate_transaction(txn: Dict[str, Any], row_index: int = 0) -> List[str]:
    """
    Validates a single transaction dictionary against the schema requirements.

    Args:
        txn: Transaction dictionary to validate
        row_index: Row number for error messages

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    # Required fields that must have values
    required_fields = ['date', 'type', 'account_external_id']
    for field in required_fields:
        if not txn.get(field):
            errors.append(f"Row {row_index}: Missing required field '{field}'")

    # Validate date format (should be YYYY-MM-DD or similar)
    date_val = txn.get('date')
    if date_val:
        date_str = str(date_val).split(' ')[0]
        if len(date_str) < 8 or '-' not in date_str:
            errors.append(f"Row {row_index}: Invalid date format '{date_val}' (expected YYYY-MM-DD)")

    # Validate transaction type
    txn_type = txn.get('type', '')
    if txn_type and txn_type not in VALID_TRANSACTION_TYPES:
        errors.append(f"Row {row_index}: Unknown transaction type '{txn_type}'")

    # Validate numeric fields
    numeric_fields = ['quantity', 'price', 'amount', 'amount_local', 'exchange_rate', 'fee', 'fee_local']
    for field in numeric_fields:
        val = txn.get(field)
        if val is not None and not isinstance(val, (int, float)):
            errors.append(f"Row {row_index}: Field '{field}' must be numeric, got {type(val).__name__}")

    # Validate currency codes (should be 3 uppercase letters)
    currency_fields = ['currency', 'fee_currency']
    for field in currency_fields:
        val = txn.get(field)
        if val and (not isinstance(val, str) or len(val) != 3):
            errors.append(f"Row {row_index}: Field '{field}' should be 3-letter currency code, got '{val}'")

    # Validate ISIN format if present (12 characters, starts with 2 letters)
    isin = txn.get('isin')
    if isin and isinstance(isin, str) and len(isin) > 0:
        if len(isin) != 12 or not isin[:2].isalpha():
            logger.debug(f"Row {row_index}: Non-standard ISIN format '{isin}'")

    return errors


def validate_parser_output(transactions: List[Dict[str, Any]], parser_name: str = "unknown") -> Tuple[bool, List[str]]:
    """
    Validates the complete output of a parser.

    Args:
        transactions: List of transaction dictionaries from a parser
        parser_name: Name of the parser for error messages

    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    all_errors = []

    if not isinstance(transactions, list):
        return False, [f"Parser '{parser_name}' must return a list, got {type(transactions).__name__}"]

    if len(transactions) == 0:
        logger.warning(f"Parser '{parser_name}' returned empty list")
        return True, []

    for i, txn in enumerate(transactions):
        if not isinstance(txn, dict):
            all_errors.append(f"Row {i}: Expected dict, got {type(txn).__name__}")
            continue

        row_errors = validate_transaction(txn, i)
        all_errors.extend(row_errors)

        # Stop after 10 errors to avoid noise
        if len(all_errors) >= 10:
            all_errors.append(f"... stopping after 10 errors (total rows: {len(transactions)})")
            break

    is_valid = len(all_errors) == 0
    if is_valid:
        logger.info(f"Parser '{parser_name}' output validated: {len(transactions)} transactions OK")
    else:
        logger.warning(f"Parser '{parser_name}' validation failed: {len(all_errors)} errors")

    return is_valid, all_errors
