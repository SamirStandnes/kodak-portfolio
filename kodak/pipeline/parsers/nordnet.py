import logging
import os
import uuid
from typing import List, Dict, Any

import pandas as pd

from kodak.shared.utils import clean_num, load_config

logger = logging.getLogger(__name__)

# --- Configuration ---
config = load_config()
BASE_CURRENCY = config.get('base_currency', 'NOK')

def parse(file_path: str) -> List[Dict[str, Any]]:
    try:
        df = pd.read_csv(file_path, sep='\t', encoding='utf-16')
    except Exception as e:
        logger.error(f'Error reading Nordnet file {file_path}: {e}')
        return []

    # Clean columns
    df['Beløp_Clean'] = df['Beløp'].apply(clean_num)
    df['Kurtasje_Clean'] = df['Kurtasje'].apply(clean_num)
    df['Kjøpsverdi_Clean'] = df['Kjøpsverdi'].apply(clean_num)
    df['Kurs_Clean'] = df['Kurs'].apply(clean_num)
    df['Antall_Clean'] = df['Antall'].apply(clean_num)
    
    # Clean Fee Rate if present
    if 'Valutakurs' in df.columns:
        df['Valutakurs_Clean'] = df['Valutakurs'].apply(clean_num)
    else:
        df['Valutakurs_Clean'] = 0.0

    results = []
    
    for _, row in df.iterrows():
        # 1. Classification
        t_type = str(row['Transaksjonstype']).upper()
        text = str(row['Transaksjonstekst']).upper() if pd.notna(row['Transaksjonstekst']) else ''
        
        std_type = t_type
        if 'INTERNAL' in text:
            if 'INNSKUDD' in t_type: std_type = 'TRANSFER_IN'
            elif 'UTTAK' in t_type: std_type = 'TRANSFER_OUT'
        elif 'OVERFØRING' in t_type and 'INNSKUD' in t_type: std_type = 'DEPOSIT'
        elif 'ÖNSKAR TECKNA' in text: std_type = 'ADJUSTMENT'
        else:
            mapping = {
                'KJØPT': 'BUY', 'SALG': 'SELL', 'UTBYTTE': 'DIVIDEND',
                'INNSKUDD': 'DEPOSIT', 'UTTAK': 'WITHDRAWAL',
                'UTTAK INTERNT': 'WITHDRAWAL', 'UTTAK INTERNET': 'WITHDRAWAL',
                'DEBETRENTE': 'INTEREST', 'INNLØSN. UTTAK VP': 'SELL', 
                'AVG KORR': 'ADJUSTMENT', 'ERSTATNING': 'DEPOSIT',
                'SALG VALUTA': 'CURRENCY_EXCHANGE', 'KJØP VALUTA': 'CURRENCY_EXCHANGE', 
                'AVGIFT': 'FEE', 'PLATTFORMAVGIFT': 'FEE',
                'OVERFØRING VIA TRUSTLY': 'DEPOSIT'
            }
            if t_type in mapping: std_type = mapping[t_type]
            elif 'RENTE' in t_type: std_type = 'INTEREST'
            elif 'SKATT' in t_type: std_type = 'TAX'

        # 2. Correct Column Swapping
        v1 = row['Valuta.1'] if pd.notna(row['Valuta.1']) else BASE_CURRENCY
        v2 = row['Valuta.2'] if pd.notna(row['Valuta.2']) else BASE_CURRENCY
        a1 = row['Beløp_Clean']
        a2 = row['Kjøpsverdi_Clean']
        
        exchange_rate = clean_num(row['Vekslingskurs'])

        if v1 == BASE_CURRENCY and v2 != BASE_CURRENCY:
            # Auto-FX: Settled in Base (e.g. NOK), Asset is Foreign (e.g. USD)
            amount_local = a1
            currency = v2 
            # Back-calculate raw amount
            amount = a1 / exchange_rate if exchange_rate != 0 else a1
        elif v1 != BASE_CURRENCY and v2 == BASE_CURRENCY:
            amount = a1
            currency = v1
            amount_local = a2
        else:
            amount = a1
            currency = v1
            amount_local = a2 if a2 != 0 else a1

        # 3. Sign Logic
        if std_type not in ['CURRENCY_EXCHANGE', 'INTEREST', 'FEE', 'TAX']:
            outflow_types = ['BUY', 'WITHDRAWAL', 'TRANSFER_OUT']
            inflow_types = ['SELL', 'DEPOSIT', 'TRANSFER_IN', 'DIVIDEND']
            
            if std_type in outflow_types:
                amount_local = -abs(amount_local)
                amount = -abs(amount)
            elif std_type in inflow_types:
                amount_local = abs(amount_local)
                amount = abs(amount)

        # Quantity logic
        qty = row['Antall_Clean']
        if std_type == 'SELL' or 'UTTAK' in t_type:
            qty = -abs(qty)
        else:
            qty = abs(qty)

        # Fix for zero amount_local if rate exists
        if amount_local == 0 and amount != 0 and exchange_rate != 0:
            amount_local = amount * exchange_rate
            
        # Fee Logic
        fee_raw = clean_num(row['Kurtasje_Clean'])
        fee_currency = row.get('Valuta.4', BASE_CURRENCY)
        if pd.isna(fee_currency): fee_currency = BASE_CURRENCY
        
        fee_local = 0.0
        if fee_currency == BASE_CURRENCY:
            fee_local = fee_raw
        elif fee_raw != 0:
            fee_rate = row.get('Valutakurs_Clean', 0.0)
            if fee_rate != 0:
                fee_local = fee_raw * fee_rate
            elif exchange_rate != 0:
                fee_local = fee_raw * exchange_rate

        item = {
            'external_id': str(uuid.uuid4()),
            'account_external_id': str(row['Portefølje']),
            'isin': str(row['ISIN']) if pd.notna(row['ISIN']) else None,
            'symbol': str(row['Verdipapir']) if pd.notna(row['Verdipapir']) else None,
            'date': row['Handelsdag'],
            'type': std_type,
            'quantity': qty,
            'price': row['Kurs_Clean'],
            'amount': amount,
            'currency': currency,
            'amount_local': amount_local,
            'exchange_rate': exchange_rate,
            'description': text,
            'source_file': os.path.basename(file_path),
            'fee': fee_raw,
            'fee_currency': fee_currency,
            'fee_local': fee_local
        }
        results.append(item)
        
    return results
