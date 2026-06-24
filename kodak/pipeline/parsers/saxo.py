import logging
import os
import re
from typing import List, Dict, Any

import pandas as pd

from kodak.shared.utils import clean_num, load_config
from kodak.shared.parser_utils import create_empty_transaction

logger = logging.getLogger(__name__)

# --- Configuration ---
config = load_config()
BASE_CURRENCY = config.get('base_currency', 'NOK')

def parse(file_path: str) -> List[Dict[str, Any]]:
    """Dispatch on file type. Saxo offers two relevant exports:
      - 'Transactions' report (.xlsx) -> trade-level detail, handled by _parse_excel
      - 'Transaction and balance report' (.pdf) -> cash ledger, handled by _parse_pdf
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.pdf':
        return _parse_pdf(file_path)
    return _parse_excel(file_path)


def _parse_excel(file_path: str) -> List[Dict[str, Any]]:
    try:
        xl = pd.ExcelFile(file_path)
        sheet = 'Transactions' if 'Transactions' in xl.sheet_names else 'Transaksjoner'
        df = pd.read_excel(xl, sheet_name=sheet)
        xl.close()
    except Exception as e:
        logger.error(f'Error reading Saxo file {file_path}: {e}')
        return []
        
    col_map = {
        'Kunde-ID': 'AccountID', 'Client ID': 'AccountID',
        'Handelsdato': 'TradeDate', 'Trade Date': 'TradeDate',
        'Valuteringsdato': 'SettlementDate', 'Value Date': 'SettlementDate',
        'Instrument ISIN': 'ISIN',
        'Instrumentsymbol': 'Symbol', 'Instrument Symbol': 'Symbol',
        'Hendelse': 'Event', 'Event': 'Event',
        'Bokført beløp': 'Amount', 'Booked Amount': 'Amount',
        'Omregningskurs': 'FXRate', 'Conversion Rate': 'FXRate',
        'Type': 'SaxoType'
    }

    existing_cols = {c: col_map[c] for c in df.columns if c in col_map}
    df = df.rename(columns=existing_cols)
    
    if 'Symbol' not in df.columns and 'Instrument' in df.columns:
        df = df.rename(columns={'Instrument': 'Symbol'})

    df = df.dropna(subset=['AccountID', 'TradeDate'])
    
    trade_pattern = re.compile(r'(?P<action>Kjøp|Salg|Selg|Buy|Sell)\s+(?P<quantity>[-]?[\d,. ]+)\s+@\s+(?P<price>[\d,. ]+)\s+(?P<currency>\w+)', re.IGNORECASE)

    results = []
    
    for _, row in df.iterrows():
        text = str(row['Event'])
        match = trade_pattern.search(text)
        
        amt_local = clean_num(row['Amount'])
        fx_rate = clean_num(row['FXRate']) if 'FXRate' in row and pd.notna(row['FXRate']) else 1.0
        
        # Use Helper to init standard dict
        item = create_empty_transaction()
        
        # Populate known fields
        item.update({
            'account_external_id': str(row['AccountID']),
            'isin': row['ISIN'] if 'ISIN' in row else None,
            'symbol': row['Symbol'] if 'Symbol' in row else None,
            'date': row['TradeDate'],
            'amount': amt_local,       # Default to local
            'amount_local': amt_local,
            'exchange_rate': fx_rate,
            'description': text,
            'source_file': os.path.basename(file_path),
        })
        
        if match:
            data = match.groupdict()
            action = data['action'].lower()
            qty = float(data['quantity'].replace(',', '').replace(' ', ''))
            price = float(data['price'].replace(',', '').replace(' ', ''))
            raw_curr = data['currency'].upper()
            
            item['price'] = price
            item['currency'] = raw_curr
            
            # Recalculate raw amount if we have a valid rate
            if fx_rate > 0 and fx_rate != 1.0:
                item['amount'] = amt_local / fx_rate
            
            if action in ['kjøp', 'buy']:
                item['type'] = 'BUY'
                item['quantity'] = abs(qty)
            else:
                item['type'] = 'SELL'
                item['quantity'] = -abs(qty)

        else:
            saxo_type = str(row['SaxoType']).lower() if 'SaxoType' in row else ''
            if 'utbytte' in text.lower() or 'dividend' in text.lower(): item['type'] = 'DIVIDEND'
            elif 'innskudd' in text.lower() or 'deposit' in text.lower(): item['type'] = 'DEPOSIT'
            elif 'uttak' in text.lower() or 'withdrawal' in text.lower(): item['type'] = 'WITHDRAWAL'
            elif 'gebyr' in text.lower() or 'fee' in text.lower(): item['type'] = 'FEE'
            elif 'interest' in text.lower(): item['type'] = 'INTEREST'
            else: item['type'] = 'ADJUSTMENT'

        results.append(item)

    return results


# --- PDF: "Transaction and balance report" (Transaksjons- og saldorapport) ---
#
# Used when Saxo only offers a PDF export. We parse the "Transaksjoner" section,
# which carries both cash events (dividends, distributions, custody fees,
# interest, deposits, withdrawals) AND trade-level rows (Kjøp/Salg with qty,
# price and booked amount). The holdings/closed-positions sections are ignored
# (they restate trades and would create duplicates).
#
# Two robustness concerns this parser handles, because Saxo PDFs vary by locale
# and by what is still held:
#   * Locale: dates come English-capitalised ("01-Dec-2025") or Norwegian
#     lower-case ("01-des-2025", incl. "mai"/"okt"/"des"), and numbers come
#     US-style ("2,538.89") or Norwegian ("2 538,89"). Detected per document.
#   * Missing ISIN: fully-closed positions appear in the transaction list but no
#     longer carry an ISIN anywhere in the PDF. We resolve those via _PDF_KNOWN.
#
# Dedup note: existing DB trade rows store the booked amount in NOK (currency
# NOK, amount == amount_local). We MATCH that convention here so the dedup hash
# (date|account|type|isin|amount) lines up and re-imported trades are skipped.

_PDF_MONTHS = {
    'jan': '01', 'feb': '02', 'mar': '03', 'mars': '03', 'apr': '04',
    'may': '05', 'mai': '05', 'jun': '06', 'jul': '07', 'aug': '08',
    'sep': '09', 'oct': '10', 'okt': '10', 'nov': '11', 'dec': '12', 'des': '12',
}

# Saxo event text -> our canonical type. Order matters (most specific first).
_PDF_EVENTS = [
    ('Utbytte i\nkontanter', 'DIVIDEND'), ('Utbytte i kontanter', 'DIVIDEND'),
    ('Cash dividend', 'DIVIDEND'),
    ('Kapitalutdeling', 'ADJUSTMENT'), ('Capital Distribution', 'ADJUSTMENT'),
    ('Depotgebyr', 'FEE'), ('Custody Fee', 'FEE'),
    ('Uttak', 'WITHDRAWAL'), ('Withdrawal', 'WITHDRAWAL'),
    ('Innskudd', 'DEPOSIT'), ('Deposit', 'DEPOSIT'),
    ('Rente', 'INTEREST'), ('Interest', 'INTEREST'),
]

# A record starts: <trade date> <value date> <Handels-ID|-> <Kontant|Aksje|...>
_PDF_RECORD = re.compile(
    r'^(\d{2}-[A-Za-zÆØÅæøå]{3,4}-\d{4})\s+\d{2}-[A-Za-zÆØÅæøå]{3,4}-\d{4}\s+'
    r'(?:-|\d+)\s+(Kontant|Aksje|Cash|Stock)\b', re.IGNORECASE
)
# Product keyword that separates the header (dates, Handels-ID) from the columns.
_PDF_PRODUCT = re.compile(r'\b(Kontant|Aksje|Cash|Stock)\b')
# Trade event text, e.g. "Kjøp 60 @ 59,71 USD" / "Buy 100 @ 36.90 SGD".
_PDF_TRADE = re.compile(
    r'(Kjøp|Kjøpt|Kjop|Salg|Selg|Solgt|Buy|Bought|Sell|Sold)\s+'
    r'([-\d  .,]+?)\s*@\s*([\d  .,]+?)\s+([A-Z]{3})', re.IGNORECASE
)
_PDF_BUY = {'kjøp', 'kjøpt', 'kjop', 'buy', 'bought'}
# Section/page furniture that terminates an open record. Kept specific so it
# never collides with record data ("Åpne/lukke" header vs "Åpnes" data value).
_PDF_STOP = ('Transaksjoner', 'Transactions', 'Bokf', 'Booking', 'Handelsdato',
             'Trade Date', 'Rapporteringsperiode', 'Reporting period', 'Saxo Bank',
             'Konto(er)', 'Account(s)', 'Generert', 'Generated', 'Valuta', 'Currency',
             'WISCO', 'Samir', '/ T', 'Åpne/lukke', 'Åpningsdato', 'Open/close',
             'Instrumentval', 'Produkt', 'Product', 'Valuteringsd', 'Value date',
             'sum ', 'sum-', ':')
# Instrument name -> ISIN from the holdings section, e.g.
# "DBS Group Holdings Ltd. (ISIN: SG1L01001701)".
_PDF_ISIN = re.compile(r'([A-Za-zÆØÅæøå][\w .,&/()Ææøå-]+?)\s*\(ISIN:\s*([A-Z0-9]{12})\)')
# Fallback for instruments that no longer carry an ISIN in the PDF (fully sold).
# Extend as the portfolio grows; keys are matched as substrings of the row text.
_PDF_KNOWN = {
    'Floor & Decor': 'US3397501012',
    'DBS Group Holdings': 'SG1L01001701',
    'Ping AN Insurance': 'CNE1000003X6',
    'Metaplanet': 'JP3481200008',
}


def _pdf_iso_date(d: str) -> str:
    dd, mon, yy = d.split('-')
    return f"{yy}-{_PDF_MONTHS[mon.lower()]}-{dd}"


def _pdf_detect_locale(text: str) -> str:
    """Norwegian uses comma decimals (', 86'), US uses period decimals ('.86')."""
    no = len(re.findall(r'\d,\d{2}\b', text))
    en = len(re.findall(r'\d\.\d{2}\b', text))
    return 'no' if no > en else 'en'


def _pdf_num(tok: str, loc: str) -> float:
    s = tok.replace(' ', '').replace(' ', '')
    if loc == 'no':
        s = s.replace('.', '').replace(',', '.')
    else:
        s = s.replace(',', '')
    return float(s)


def _pdf_numbers(s: str, loc: str) -> List[float]:
    if loc == 'no':
        pat = re.compile(r'-?\d{1,3}(?:[  ]\d{3})*(?:,\d+)?')
    else:
        pat = re.compile(r'-?\d{1,3}(?:,\d{3})*(?:\.\d+)?')
    out = []
    for m in pat.finditer(s):
        try:
            out.append(_pdf_num(m.group(), loc))
        except ValueError:
            pass
    return out


def _pdf_account_id(file_path: str, full_text: str):
    """Prefer the account id embedded in the filename, e.g.
    'TransactionBalance_19269921_...'; fall back to the header line."""
    m = re.search(r'_(\d{6,})_', os.path.basename(file_path))
    if m:
        return m.group(1)
    m = re.search(r'-\s*(\d{6,})\b', full_text)
    return m.group(1) if m else None


def _parse_pdf(file_path: str) -> List[Dict[str, Any]]:
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        lines = []
        for page in reader.pages:
            lines += (page.extract_text() or '').split('\n')
    except Exception as e:
        logger.error(f'Error reading Saxo PDF {file_path}: {e}')
        return []

    full_text = '\n'.join(lines)
    loc = _pdf_detect_locale(full_text)
    account_id = _pdf_account_id(file_path, full_text)

    # Instrument name -> ISIN, from holdings section + known fallbacks.
    isin_map = {}
    for name, isin in _PDF_ISIN.findall(re.sub(r'\s+', ' ', full_text)):
        isin_map[' '.join(name.split()[:3])] = isin
    isin_map.update(_PDF_KNOWN)

    def lookup_isin(text: str):
        norm = ' '.join(text.split())
        for key, isin in isin_map.items():
            if key and key in norm:
                return isin
        return None

    # Group lines into records (a record may wrap across several lines).
    records, current = [], None
    for ln in lines:
        if _PDF_RECORD.match(ln):
            if current:
                records.append(current)
            current = [ln]
        elif current is not None:
            if ln.startswith(_PDF_STOP):
                records.append(current)
                current = None
            else:
                current.append(ln)
    if current:
        records.append(current)

    results = []
    for rec in records:
        flat = ' '.join(rec)
        m = _PDF_RECORD.match(rec[0])
        date = _pdf_iso_date(m.group(1))

        # Drop the header (dates + Handels-ID) by cutting at the product keyword,
        # so only "<instrument> <currency> <event> <columns...>" remains.
        pm = _PDF_PRODUCT.search(flat)
        body = flat[pm.end():] if pm else flat

        nums = _pdf_numbers(body, loc)
        if len(nums) < 3:
            continue  # not a real ledger line
        amount = round(nums[-3], 2)  # "Bokført beløp" is always 3rd-from-last
        isin = lookup_isin(body)

        item = create_empty_transaction()
        item.update({
            'account_external_id': account_id,
            'isin': isin,
            'date': date,
            'amount': amount,
            'amount_local': amount,
            'currency': BASE_CURRENCY,   # matches existing DB convention (NOK)
            'exchange_rate': 1.0,
            'description': ' '.join(flat.split()),
            'source_file': os.path.basename(file_path),
        })

        trade = _PDF_TRADE.search(body)
        if trade:
            action, qty_s, price_s, _curr = trade.groups()
            qty = abs(_pdf_num(qty_s, loc))
            is_buy = action.lower() in _PDF_BUY
            item['type'] = 'BUY' if is_buy else 'SELL'
            item['quantity'] = qty if is_buy else -qty
            item['price'] = _pdf_num(price_s, loc)
            # Omregningskurs (FX rate) is read from the END of the row, not the
            # start: the leading "Kjøp 1000 @ 41,40" restatement tokenizes
            # unreliably in NO locale (space-as-thousands is ambiguous), but the
            # numeric tail is stable. Column order is
            #   ... Kurs Omregningskurs [Realisert G/T] Bokført Bokf.kost Sum.kost
            # A BUY has no Realisert G/T ("-"), so FX is 4th-from-last; a SELL
            # carries a Realisert G/T value, pushing FX to 5th-from-last.
            fx_idx = -4 if is_buy else -5
            if len(nums) >= abs(fx_idx):
                fx = nums[fx_idx]
                if 0 < fx < 1000:           # sane FX rate, not an amount
                    item['exchange_rate'] = fx
                else:
                    logger.warning(
                        "Saxo PDF: implausible FX %.4f for %s %s — left at 1.0",
                        fx, item['date'], item['description'][:60])
            if not isin:
                # A trade whose instrument is fully sold has no ISIN in the PDF
                # and isn't in _PDF_KNOWN. Without an ISIN the dedup hash can't
                # match an existing row, so flag it rather than risk a duplicate.
                logger.warning(
                    "Saxo PDF trade without resolved ISIN (add to _PDF_KNOWN): "
                    "%s %s — %s", item['date'], item['type'], item['description'][:80]
                )
        else:
            txn_type = 'ADJUSTMENT'
            for needle, mapped in _PDF_EVENTS:
                if needle in '\n'.join(rec) or needle.replace('\n', ' ') in flat:
                    txn_type = mapped
                    break
            item['type'] = txn_type

        results.append(item)

    return results
