import logging
import yfinance as yf
import pandas as pd
from datetime import datetime
from typing import List, Dict, Tuple
from kodak.shared.db import get_connection, get_db_connection, execute_batch, execute_query

logger = logging.getLogger(__name__)

def get_latest_prices(instrument_ids: List[int]) -> Dict[int, Tuple[float, str]]:
    """
    Fetches latest price. Returns {id: (price, currency)}.
    """
    if not instrument_ids:
        return {}
    placeholders = ','.join(['?'] * len(instrument_ids))
    
    # Get Symbol AND Currency from Instruments
    query = f"SELECT id, symbol, currency FROM instruments WHERE id IN ({placeholders})"
    rows = execute_query(query, tuple(instrument_ids))
    
    id_map = {row['symbol']: {'id': row['id'], 'currency': row['currency']} for row in rows if row['symbol']}
    symbols = list(id_map.keys())
    
    if not symbols:
        return {}

    logger.info(f"Fetching prices for {len(symbols)} symbols...")
    try:
        data = yf.download(symbols, period="5d", progress=False, auto_adjust=False)['Close']
    except Exception as e:
        logger.error(f"Error fetching data: {e}")
        return {}

    results = {}
    
    # Helper to safe get
    def get_val(sym):
        if isinstance(data, pd.Series):
             return float(data.dropna().iloc[-1]) if not data.dropna().empty else 0.0
        if sym in data.columns:
             series = data[sym].dropna()
             if not series.empty:
                 return float(series.iloc[-1])
        return 0.0

    for symbol in symbols:
        price = get_val(symbol)
        if price > 0:
            meta = id_map[symbol]
            # Use the currency from our DB, as Yahoo doesn't reliably return it in simple download
            results[meta['id']] = (price, meta['currency'])

    return results

def store_prices(prices: Dict[int, Tuple[float, str]], date_str: str = None):
    if not date_str:
        date_str = datetime.now().strftime('%Y-%m-%d')
        
    data_to_insert = []
    for inst_id, (price, currency) in prices.items():
        data_to_insert.append((inst_id, date_str, price, currency, 'yfinance'))
        
    execute_batch('''
        INSERT OR REPLACE INTO market_prices (instrument_id, date, close, currency, source)
        VALUES (?, ?, ?, ?, ?)
    ''', data_to_insert)
    logger.info(f"Stored {len(data_to_insert)} prices.")

def get_exchange_rate(from_curr: str, to_curr: str) -> float:
    """
    Gets exchange rate with DB caching for performance.
    1. Checks database for recent rate (last 7 days)
    2. Falls back to Yahoo Finance if not found
    3. Stores fetched rate in database for future use
    """
    if not from_curr or not to_curr or from_curr == to_curr:
        return 1.0

    today = datetime.now().strftime('%Y-%m-%d')

    # 1. Try database first (recent rate within 7 days)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT rate, date FROM exchange_rates
            WHERE from_currency = ? AND to_currency = ?
            ORDER BY date DESC LIMIT 1
        """, (from_curr, to_curr))
        row = cursor.fetchone()

        if row:
            rate, rate_date = row
            # Use if from today or recent (within 7 days for weekends/holidays)
            days_old = (datetime.now() - datetime.strptime(rate_date, '%Y-%m-%d')).days
            if days_old <= 7 and rate > 0:
                logger.debug(f"Using cached rate {from_curr}/{to_curr}: {rate} (from {rate_date})")
                return float(rate)

    # 2. Fetch from Yahoo Finance
    pair = f"{from_curr}{to_curr}=X"
    try:
        ticker = yf.Ticker(pair)
        hist = ticker.history(period="1d")
        if not hist.empty:
            rate = float(hist['Close'].iloc[-1])
            # 3. Store in database for future use
            _store_exchange_rate(from_curr, to_curr, today, rate)
            return rate
    except Exception as e:
        logger.warning(f"Failed to fetch exchange rate for {pair}: {e}")

    logger.warning(f"Could not fetch rate for {pair}. Using 1.0")
    return 1.0


def _store_exchange_rate(from_curr: str, to_curr: str, date: str, rate: float):
    """Stores an exchange rate in the database."""
    try:
        with get_db_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO exchange_rates (from_currency, to_currency, date, rate)
                VALUES (?, ?, ?, ?)
            """, (from_curr, to_curr, date, rate))
            conn.commit()
            logger.debug(f"Stored rate {from_curr}/{to_curr} = {rate} for {date}")
    except Exception as e:
        logger.warning(f"Failed to store exchange rate: {e}")

def get_historical_prices_by_date(symbols: List[str], target_date: str) -> Dict[str, float]:
    """
    Fetches closing prices for a list of symbols on or before a specific date.
    Returns {symbol: price}.
    """
    if not symbols:
        return {}
        
    # Fetch a small window around the date to handle weekends/holidays
    # Look back 5 days
    end_dt = pd.Timestamp(target_date) + pd.Timedelta(days=1)
    start_dt = end_dt - pd.Timedelta(days=7)
    
    logger.info(f"Fetching historical prices for {len(symbols)} symbols around {target_date}...")

    try:
        # We use auto_adjust=False to avoid Dividend adjustments which undervalue the asset.
        # We rely on DB transactions (BYTTE) or manual splits for quantity adjustments.
        df = yf.download(symbols, start=start_dt, end=end_dt, progress=False, group_by='ticker', auto_adjust=False)
    except Exception as e:
        logger.error(f"Error fetching historical data: {e}")
        return {}
        
    results = {}
    
    for sym in symbols:
        try:
            # Extract data for this symbol
            if len(symbols) > 1:
                if sym not in df.columns:
                    continue
                data = df[sym]['Close']
            else:
                data = df['Close']
                
            # Find last available price
            valid_data = data.dropna()
            if not valid_data.empty:
                results[sym] = float(valid_data.iloc[-1])
        except Exception as e:
            logger.debug(f"Could not extract price for {sym}: {e}")
    return results

def get_split_history(symbols: List[str]) -> Dict[str, pd.Series]:
    """
    Fetches split history for a list of symbols.
    Returns {symbol: Series of splits}.
    """
    if not symbols:
        return {}
        
    logger.info(f"Fetching split history for {len(symbols)} symbols...")
    results = {}
    
    for sym in symbols:
        try:
            ticker = yf.Ticker(sym)
            splits = ticker.splits
            if not splits.empty:
                results[sym] = splits
        except Exception as e:
            logger.debug(f"Could not fetch split history for {sym}: {e}")

    return results


def get_forward_dividends(symbols: List[str]) -> Dict[str, Dict]:
    """
    Fetches forward (indicated) annual dividend info from Yahoo Finance.

    Returns {symbol: {'dividend_rate': float, 'dividend_yield': float, 'currency': str}}
    - dividend_rate: Annual dividend per share
    - dividend_yield: Dividend yield as decimal (e.g., 0.025 for 2.5%)
    - currency: Currency of the dividend

    Returns empty dict for symbols where data is unavailable.
    """
    if not symbols:
        return {}

    logger.info(f"Fetching forward dividend data for {len(symbols)} symbols...")
    results = {}

    for sym in symbols:
        try:
            ticker = yf.Ticker(sym)
            info = ticker.info

            dividend_rate = info.get('dividendRate')
            dividend_yield = info.get('dividendYield')
            currency = info.get('currency')

            # Only include if we have a valid dividend rate
            if dividend_rate and dividend_rate > 0:
                results[sym] = {
                    'dividend_rate': float(dividend_rate),
                    'dividend_yield': float(dividend_yield) if dividend_yield else None,
                    'currency': currency
                }
                logger.debug(f"{sym}: Forward dividend = {dividend_rate} {currency}")
            else:
                logger.debug(f"{sym}: No forward dividend data available")

        except Exception as e:
            logger.debug(f"Could not fetch dividend info for {sym}: {e}")

    return results