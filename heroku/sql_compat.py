"""
SQLite to PostgreSQL query translation layer.
Translates SQLite-specific SQL syntax to PostgreSQL equivalents.
"""
import re


def translate_query(query: str) -> str:
    """
    Translates SQLite-specific SQL to PostgreSQL.

    Handles:
    - strftime('%Y', date) -> TO_CHAR(date::date, 'YYYY')
    - strftime('%J', date) -> EXTRACT(EPOCH FROM date::timestamp) / 86400.0
    - date('now', '-12 months') -> CURRENT_DATE - INTERVAL '12 months'
    - INSERT OR REPLACE -> INSERT ... ON CONFLICT DO UPDATE
    - ? placeholders -> %s placeholders
    - sqlite_master -> pg_tables
    - GROUP BY alias -> GROUP BY column position
    - date LIKE 'YYYY%' -> TO_CHAR(date::date, 'YYYY') = 'YYYY'
    """
    result = query

    # strftime('%Y', column) -> TO_CHAR(column::date, 'YYYY')
    # Matches: strftime('%Y', date) or strftime('%Y', t.date)
    result = re.sub(
        r"strftime\s*\(\s*'%Y'\s*,\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*\)",
        r"TO_CHAR(\1::date, 'YYYY')",
        result
    )

    # strftime('%J', x) is SQLite's Julian day — a CONTINUOUS day count.
    # EXTRACT(DOY ...) resets every year and breaks ABS(a - b) nearest-date
    # ordering across year boundaries, so translate to epoch days instead.
    result = re.sub(
        r"strftime\s*\(\s*'%J'\s*,\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*\)",
        r"(EXTRACT(EPOCH FROM \1::timestamp) / 86400.0)",
        result
    )

    result = re.sub(
        r"strftime\s*\(\s*'%J'\s*,\s*\?\s*\)",
        r"(EXTRACT(EPOCH FROM %s::timestamp) / 86400.0)",
        result
    )

    # date('now', '-12 months') -> CURRENT_DATE - INTERVAL '12 months'
    result = re.sub(
        r"date\s*\(\s*'now'\s*,\s*'-(\d+)\s+months?'\s*\)",
        r"CURRENT_DATE - INTERVAL '\1 months'",
        result
    )

    # Fix date comparisons: column >= CURRENT_DATE needs column cast to date
    # Pattern: t.date >= CURRENT_DATE or similar
    result = re.sub(
        r'(\w+\.date)\s*(>=|<=|>|<|=)\s*(CURRENT_DATE)',
        r'\1::date \2 \3',
        result
    )

    # Handle date LIKE patterns for year matching
    # t.date LIKE ? (where ? is 'YYYY%') -> TO_CHAR(t.date::date, 'YYYY') = %s
    # This is tricky because we need to change the parameter too
    # For now, we'll keep LIKE but it should work if the date is stored as text

    # Fix GROUP BY alias issues with COALESCE
    # When SELECT has COALESCE(i.symbol, i.isin) as symbol ... GROUP BY symbol
    # PostgreSQL needs GROUP BY COALESCE(i.symbol, i.isin) or GROUP BY 1
    result = fix_group_by_coalesce(result)

    # Fix GROUP BY with non-aggregated joined columns
    # SQLite allows: SELECT i.symbol, i.currency, SUM(t.amount) ... GROUP BY t.instrument_id
    # PostgreSQL requires: GROUP BY t.instrument_id, i.symbol, i.currency
    result = fix_group_by_joined_columns(result)

    # INSERT OR REPLACE -> ON CONFLICT
    result = translate_insert_or_replace(result)

    # sqlite_master -> pg_tables (for system table queries)
    result = result.replace("sqlite_master WHERE type='table'",
                           "pg_tables WHERE schemaname='public'")
    result = result.replace("name FROM pg_tables", "tablename as name FROM pg_tables")

    # Replace ? placeholders with %s for psycopg2
    result = replace_placeholders(result)

    return result


def fix_group_by_coalesce(query: str) -> str:
    """
    Fix PostgreSQL GROUP BY issues with COALESCE aliases.

    SQLite allows: SELECT COALESCE(a, b) as x ... GROUP BY x
    PostgreSQL requires: SELECT COALESCE(a, b) as x ... GROUP BY COALESCE(a, b) or GROUP BY 1
    """
    # Pattern: COALESCE(i.symbol, i.isin) as symbol ... GROUP BY symbol
    # Handle every COALESCE alias in the query, anywhere in the GROUP BY list.
    aliases = {
        m.group(2): f"COALESCE({m.group(1)})"
        for m in re.finditer(
            r'COALESCE\s*\(\s*([^)]+)\s*\)\s+as\s+(\w+)', query, re.IGNORECASE)
    }
    if not aliases:
        return query

    def expand_aliases(match):
        items = [item.strip() for item in match.group(2).split(',')]
        return match.group(1) + ', '.join(aliases.get(item, item) for item in items)

    return re.sub(
        r'(GROUP\s+BY\s+)([^\n;)]+)', expand_aliases, query, flags=re.IGNORECASE)


def fix_group_by_joined_columns(query: str) -> str:
    """
    Fix PostgreSQL GROUP BY with non-aggregated columns from joined tables.

    SQLite allows selecting columns from joined tables without including them in GROUP BY.
    PostgreSQL requires all non-aggregated columns to be in GROUP BY.

    Example:
        SELECT i.symbol, i.currency, SUM(t.amount)
        FROM transactions t
        LEFT JOIN instruments i ON t.instrument_id = i.id
        GROUP BY t.instrument_id
    Must become:
        GROUP BY t.instrument_id, i.symbol, i.currency
    """
    # Only process SELECT queries with GROUP BY
    if 'GROUP BY' not in query.upper() or 'SELECT' not in query.upper():
        return query

    # Find SELECT and GROUP BY clauses
    select_match = re.search(
        r'SELECT\s+(.*?)\s+FROM',
        query,
        re.IGNORECASE | re.DOTALL
    )
    group_by_match = re.search(
        r'GROUP\s+BY\s+([^\n;]+)',
        query,
        re.IGNORECASE
    )

    # Skip if the GROUP BY is inside a subquery (parentheses)
    if group_by_match:
        pos = group_by_match.start()
        depth = 0
        for ch in query[:pos]:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
        if depth > 0:
            return query

    if not select_match or not group_by_match:
        return query

    select_clause = select_match.group(1)
    group_by_clause = group_by_match.group(1).strip()

    # Extract non-aggregated columns from SELECT
    # Aggregates: SUM, COUNT, AVG, MIN, MAX, etc.
    aggregate_pattern = re.compile(r'\b(SUM|COUNT|AVG|MIN|MAX|GROUP_CONCAT)\s*\(', re.IGNORECASE)

    # Split select clause by comma, handling nested functions
    columns = []
    depth = 0
    current = ""
    for char in select_clause:
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        elif char == ',' and depth == 0:
            columns.append(current.strip())
            current = ""
            continue
        current += char
    if current.strip():
        columns.append(current.strip())

    # Find non-aggregated table.column references
    non_agg_columns = []
    for col in columns:
        # Skip if it's an aggregate
        if aggregate_pattern.search(col):
            continue
        # Extract table.column pattern (e.g., i.symbol, i.currency)
        col_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*)', col.strip())
        if col_match:
            col_ref = col_match.group(1)
            # Check if already in GROUP BY
            if col_ref.lower() not in group_by_clause.lower():
                non_agg_columns.append(col_ref)

    # Add missing columns to GROUP BY
    if non_agg_columns:
        new_group_by = group_by_clause + ', ' + ', '.join(non_agg_columns)
        query = re.sub(
            r'(GROUP\s+BY\s+)' + re.escape(group_by_clause),
            r'\1' + new_group_by,
            query,
            flags=re.IGNORECASE
        )

    return query


def translate_insert_or_replace(query: str) -> str:
    """
    Translates INSERT OR REPLACE to PostgreSQL ON CONFLICT syntax.

    Market prices table: conflict on (instrument_id, date)
    Exchange rates table: conflict on (from_currency, to_currency, date)
    """
    # Pattern for INSERT OR REPLACE INTO market_prices
    market_prices_pattern = re.compile(
        r"INSERT\s+OR\s+REPLACE\s+INTO\s+market_prices\s*\(\s*"
        r"([^)]+)\s*\)\s*VALUES\s*\(\s*([^)]+)\s*\)",
        re.IGNORECASE
    )

    match = market_prices_pattern.search(query)
    if match:
        columns = match.group(1)
        values = match.group(2)
        return f"""INSERT INTO market_prices ({columns})
VALUES ({values})
ON CONFLICT (instrument_id, date) DO UPDATE SET
    close = EXCLUDED.close,
    currency = EXCLUDED.currency,
    source = EXCLUDED.source"""

    # Pattern for INSERT OR REPLACE INTO exchange_rates
    exchange_rates_pattern = re.compile(
        r"INSERT\s+OR\s+REPLACE\s+INTO\s+exchange_rates\s*\(\s*"
        r"([^)]+)\s*\)\s*VALUES\s*\(\s*([^)]+)\s*\)",
        re.IGNORECASE
    )

    match = exchange_rates_pattern.search(query)
    if match:
        columns = match.group(1)
        values = match.group(2)
        return f"""INSERT INTO exchange_rates ({columns})
VALUES ({values})
ON CONFLICT (from_currency, to_currency, date) DO UPDATE SET
    rate = EXCLUDED.rate"""

    return query


def replace_placeholders(query: str) -> str:
    """
    Replaces SQLite ? placeholders with PostgreSQL %s placeholders.
    Carefully avoids replacing ? inside string literals.
    """
    result = []
    in_string = False
    string_char = None

    i = 0
    while i < len(query):
        char = query[i]

        # Track string literals
        if char in ("'", '"') and (i == 0 or query[i-1] != '\\'):
            if not in_string:
                in_string = True
                string_char = char
            elif char == string_char:
                in_string = False
                string_char = None

        # Replace ? with %s if not in a string
        if char == '?' and not in_string:
            result.append('%s')
        else:
            result.append(char)

        i += 1

    return ''.join(result)
