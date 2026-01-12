import requests
import polars as pl
from sqlalchemy import create_engine, text
from io import StringIO
import re
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SymbolMaster:
    def __init__(self, db_url: str = 'sqlite:///data/symbols.db'):
        self.db_url = db_url
        self.engine = create_engine(db_url)
        # Ensure watchlist table exists
        self._ensure_watchlist_table()

    def _ensure_watchlist_table(self):
        """Create a simple watchlist table if it doesn't already exist."""
        try:
            with self.engine.begin() as conn:
                conn.execute(text(
                    """
                    CREATE TABLE IF NOT EXISTS watchlist (
                        symbol TEXT PRIMARY KEY,
                        description TEXT,
                        exchange TEXT,
                        original_type TEXT,
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                    """
                ))
        except Exception as e:
            logger.error(f"Failed to ensure watchlist table: {e}")

    def url_to_table_name(self, url: str) -> str:
        # Extracts the file name and converts to table name, e.g. NSE_FO.csv -> nse_fo_symbols
        match = re.search(r'/([A-Za-z0-9_]+)\\.csv$', url)
        if not match:
            match = re.search(r'/([A-Za-z0-9_]+)\.csv$', url)
        if match:
            return match.group(1).lower() + '_symbols'
        return 'symbols'

    def clear_table(self, table_name: str):
        # Drop the table if exists
        with self.engine.connect() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))

    def fetch_and_save(self, url: str):
        table_name = self.url_to_table_name(url)
        # Download CSV
        response = requests.get(url)
        response.raise_for_status()
        csv_data = StringIO(response.text)
        # Read the CSV with no header using polars
        # polars.read_csv can accept a file-like object
        df = pl.read_csv(csv_data, has_header=False)
        headers = [
            "fytoken", "symbol_details", "exchange_instrument_type", "minimum_lot_size", "tick_size",
            "isin", "trading_session", "last_update_date", "expiry_date", "symbol_ticker", "exchange",
            "segment", "scrip_code", "underlying_symbol", "underlying_scrip_code", "strike_price",
            "option_type", "underlying_fytoken", "reserved_column", "reserved_column_1", "reserved_column_2"
        ]
        # Normalize columns: rename existing columns to expected headers and add missing columns as nulls
        existing_cols = df.columns
        num_existing = len(existing_cols)

        # If there are more columns in CSV than expected, truncate extras
        if num_existing > len(headers):
            df = df.select(existing_cols[:len(headers)])
            existing_cols = df.columns
            num_existing = len(existing_cols)

        # Rename existing columns to target header names
        rename_map = {existing_cols[i]: headers[i] for i in range(min(num_existing, len(headers)))}
        if rename_map:
            df = df.rename(rename_map)

        # Add missing headers as null columns
        for h in headers[num_existing:]:
            df = df.with_columns(pl.lit(None).alias(h))

        # Ensure final column order
        df = df.select(headers)

        # Clear old data and create new table with TEXT columns
        self.clear_table(table_name)
        rows = df.to_dicts()
        cols_quoted = [f'"{c}"' for c in headers]
        create_sql = f"CREATE TABLE IF NOT EXISTS {table_name} ({', '.join([f'\"{c}\" TEXT' for c in headers])})"
        insert_sql = f"INSERT INTO {table_name} ({', '.join(cols_quoted)}) VALUES ({', '.join([f':{c}' for c in headers])})"
        try:
            with self.engine.begin() as conn:
                conn.execute(text(create_sql))
                if rows:
                    # Ensure values are serializable (convert polars-specific types)
                    clean_rows = []
                    for r in rows:
                        cr = {k: (None if v is None else (v.item() if hasattr(v, 'item') else v)) for k, v in r.items()}
                        clean_rows.append(cr)
                    conn.execute(text(insert_sql), clean_rows)
        except Exception as e:
            logger.error(f"Failed to write symbols to DB via SQLAlchemy: {e}")
        logger.info(f"Symbol Master - {table_name} Updated")
        
        # Close the StringIO object
        csv_data.close()

    def process_all(self, urls):
        for url in urls:
            self.fetch_and_save(url)
    

    def _fetch_symbols(self, query: str, params: tuple = ()) -> list:
        """Helper to fetch symbols safely from the database."""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(query), params)
                symbols = [row[0] for row in result.fetchall()]
                return symbols
        except Exception as e:
            logger.error(f"DB fetch error: {e}")
            return []

    def get_symbols(self, table_name: str = 'nse_fo_symbols', limit: int = 10) -> list:
        """Get symbols from the database."""
        query = "SELECT symbol_ticker FROM {} LIMIT :limit".format(table_name)
        return self._fetch_symbols(query, {"limit": limit})

    def search_symbols(self, search_term: str, table_name: str = 'nse_fo_symbols', limit: int = 10) -> list:
        """Search for symbols containing the search term(s)."""
        terms = search_term.split()
        if not terms:
            return []
            
        conditions = []
        params = {"limit": limit}
        for i, term in enumerate(terms):
            conditions.append("symbol_ticker LIKE :term{}".format(i))
            params["term{}".format(i)] = "%{}%".format(term)
            
        where_clause = " AND ".join(conditions)
        query = "SELECT symbol_ticker FROM {} WHERE {} LIMIT :limit".format(table_name, where_clause)
        return self._fetch_symbols(query, params)
    
    def get_equity_symbols(self, limit: int = 10) -> list:
        """Get equity symbols (symbols ending with -EQ) from nse_cm_symbols or all tables."""
        query = "SELECT symbol_ticker FROM nse_cm_symbols WHERE symbol_ticker LIKE :eq LIMIT :limit"
        symbols = self._fetch_symbols(query, {"eq": "% -EQ", "limit": limit})
        if symbols:
            return symbols
        # Fallback: search all tables
        try:
            with self.engine.connect() as conn:
                tables_query = "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%symbols'"
                tables_result = conn.execute(text(tables_query))
                tables = [row[0] for row in tables_result.fetchall()]
                all_symbols = []
                for table in tables:
                    q = f"SELECT symbol_ticker FROM {table} WHERE symbol_ticker LIKE :eq LIMIT :limit"
                    table_symbols = self._fetch_symbols(q, {"eq": "% -EQ", "limit": max(1, limit // len(tables))})
                    all_symbols.extend(table_symbols)
                    if len(all_symbols) >= limit:
                        break
                return all_symbols[:limit]
        except Exception as e:
            logger.error(f"Could not fetch equity symbols: {e}")
            return []
    
    def get_fno_symbols(self, limit: int = 10) -> list:
        """Get F&O symbols from nse_fo_symbols table."""
        # Use a cached result if we've fetched a larger number previously
        if hasattr(self, '_cached_fno_symbols') and len(self._cached_fno_symbols) >= limit:
            return self._cached_fno_symbols[:limit]
            
        query = "SELECT symbol_ticker FROM nse_fo_symbols LIMIT :limit"
        symbols = self._fetch_symbols(query, {"limit": limit})
        
        # Cache the results if this is a larger fetch
        if limit > 100:
            self._cached_fno_symbols = symbols
            
        return symbols

    def _format_expiry_date(self, expiry_timestamp):
        """Convert expiry timestamp to human readable date format."""
        try:
            if not expiry_timestamp or expiry_timestamp == '':
                return ''
            
            # Convert timestamp to datetime
            if isinstance(expiry_timestamp, str) and expiry_timestamp.isdigit():
                timestamp = int(expiry_timestamp)
            elif isinstance(expiry_timestamp, (int, float)):
                timestamp = int(expiry_timestamp)
            else:
                return str(expiry_timestamp)
            
            # Convert from seconds or milliseconds to datetime
            if timestamp > 1e10:  # If timestamp is in milliseconds
                timestamp = timestamp / 1000
                
            dt = datetime.fromtimestamp(timestamp)
            return dt.strftime('%d-%b-%Y')  # Format: 25-Jul-2025
        except Exception as e:
            logger.debug(f"Error formatting expiry date {expiry_timestamp}: {e}")
            return str(expiry_timestamp)

    def get_expiry_dates(self, limit: int = 20) -> list:
        """Get unique expiry dates from F&O symbols with human readable format."""
        try:
            with self.engine.connect() as conn:
                query = """
                SELECT DISTINCT expiry_date 
                FROM nse_fo_symbols 
                WHERE expiry_date IS NOT NULL 
                AND expiry_date != '' 
                ORDER BY expiry_date 
                LIMIT :limit
                """
                result = conn.execute(text(query), {"limit": limit})
                expiry_dates = []
                for row in result.fetchall():
                    formatted_date = self._format_expiry_date(row[0])
                    if formatted_date:
                        expiry_dates.append({
                            'original': row[0],
                            'formatted': formatted_date
                        })
                return expiry_dates
        except Exception as e:
            logger.error(f"DB fetch error for expiry dates: {e}")
            return []

    def search_symbols_by_expiry(self, expiry_date: str, limit: int = 20) -> list:
        """Search for symbols with a specific expiry date."""
        try:
            with self.engine.connect() as conn:
                query = """
                SELECT symbol_ticker, expiry_date, underlying_symbol, option_type, strike_price
                FROM nse_fo_symbols 
                WHERE expiry_date = :expiry_date 
                LIMIT :limit
                """
                result = conn.execute(text(query), {"expiry_date": expiry_date, "limit": limit})
                symbols_data = []
                for row in result.fetchall():
                    symbols_data.append({
                        'symbol': row[0],
                        'expiry_date': self._format_expiry_date(row[1]),
                        'expiry_timestamp': row[1],
                        'underlying_symbol': row[2] or '',
                        'option_type': row[3] or '',
                        'strike_price': row[4] or ''
                    })
                return symbols_data
        except Exception as e:
            logger.error(f"DB fetch error for expiry search: {e}")
            return []

    def search_symbols_by_strike_price(self, strike_price: str, limit: int = 50) -> list:
        """Search for symbols with a specific strike price."""
        try:
            with self.engine.connect() as conn:
                query = """
                SELECT symbol_ticker, expiry_date, underlying_symbol, option_type, strike_price
                FROM nse_fo_symbols 
                WHERE strike_price LIKE :strike_price 
                ORDER BY expiry_date, underlying_symbol, option_type
                LIMIT :limit
                """
                result = conn.execute(text(query), {"strike_price": f"%{strike_price}%", "limit": limit})
                symbols_data = []
                for row in result.fetchall():
                    symbols_data.append({
                        'symbol': row[0],
                        'expiry_date': self._format_expiry_date(row[1]),
                        'expiry_timestamp': row[1],
                        'underlying_symbol': row[2] or '',
                        'option_type': row[3] or '',
                        'strike_price': row[4] or ''
                    })
                return symbols_data
        except Exception as e:
            logger.error(f"DB fetch error for strike price search: {e}")
            return []

    def search_symbols_with_expiry_info(self, search_term: str, table_name: str = 'nse_fo_symbols', limit: int = 10) -> list:
        """Search for symbols with expiry information included, supporting multi-term search."""
        terms = search_term.split()
        if not terms:
            return []
            
        conditions = []
        params = {"limit": limit}
        for i, term in enumerate(terms):
            conditions.append("symbol_ticker LIKE :term{}".format(i))
            params["term{}".format(i)] = "%{}%".format(term)
            
        where_clause = " AND ".join(conditions)
        
        try:
            with self.engine.connect() as conn:
                query = """
                SELECT symbol_ticker, expiry_date, underlying_symbol, option_type, strike_price
                FROM {} 
                WHERE {} 
                LIMIT :limit
                """.format(table_name, where_clause)
                result = conn.execute(text(query), params)
                symbols_data = []
                for row in result.fetchall():
                    symbols_data.append({
                        'symbol': row[0],
                        'expiry_date': self._format_expiry_date(row[1]),
                        'expiry_timestamp': row[1],
                        'underlying_symbol': row[2] or '',
                        'option_type': row[3] or '',
                        'strike_price': row[4] or ''
                    })
                return symbols_data
        except Exception as e:
            logger.error(f"DB fetch error for symbols with expiry info: {e}")
            return []
    
    def list_available_tables(self):
        """List all available symbol tables in the database"""
        try:
            with self.engine.connect() as conn:
                query = "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%symbols'"
                result = conn.execute(text(query))
                tables = [row[0] for row in result.fetchall()]
                return tables
        except Exception as e:
            logger.error(f"Could not list tables: {e}")
            return []

    # ----------------------- WATCHLIST METHODS -----------------------
    def add_to_watchlist(self, symbol: str, description: str = '', exchange: str = 'NSE', original_type: str = '') -> bool:
        """Add a symbol to the watchlist. Returns True if inserted or already exists."""
        if not symbol:
            return False
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text("INSERT OR IGNORE INTO watchlist(symbol, description, exchange, original_type) VALUES(:symbol, :description, :exchange, :original_type)"),
                    {"symbol": symbol, "description": description or f"{exchange}:{symbol}", "exchange": exchange or 'NSE', "original_type": original_type or ''}
                )
            return True
        except Exception as e:
            logger.error(f"Failed to add to watchlist: {e}")
            return False

    def remove_from_watchlist(self, symbol: str) -> bool:
        if not symbol:
            return False
        try:
            with self.engine.begin() as conn:
                res = conn.execute(text("DELETE FROM watchlist WHERE symbol = :symbol"), {"symbol": symbol})
                # sqlite returns rowcount
                return getattr(res, 'rowcount', 0) > 0
        except Exception as e:
            logger.error(f"Failed to remove from watchlist: {e}")
            return False

    def is_in_watchlist(self, symbol: str) -> bool:
        if not symbol:
            return False
        try:
            with self.engine.connect() as conn:
                res = conn.execute(text("SELECT 1 FROM watchlist WHERE symbol = :symbol LIMIT 1"), {"symbol": symbol})
                return res.first() is not None
        except Exception as e:
            logger.error(f"Failed to check watchlist: {e}")
            return False

    def get_watchlist(self, query: str | None = None, limit: int = 200) -> list:
        try:
            with self.engine.connect() as conn:
                if query and len(query) >= 1:
                    res = conn.execute(
                        text("SELECT symbol, description, exchange, original_type FROM watchlist WHERE symbol LIKE :q OR description LIKE :q ORDER BY created_at DESC LIMIT :limit"),
                        {"q": f"%{query}%", "limit": limit}
                    )
                else:
                    res = conn.execute(
                        text("SELECT symbol, description, exchange, original_type FROM watchlist ORDER BY created_at DESC LIMIT :limit"),
                        {"limit": limit}
                    )
                rows = res.fetchall()
                return [
                    {
                        "symbol": r[0],
                        "description": r[1] or f"{r[2] or 'NSE'}:{r[0]}",
                        "exchange": r[2] or 'NSE',
                        "type": "Watchlist",
                        "original_type": r[3] or ''
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.error(f"Failed to fetch watchlist: {e}")
            return []

    def _format_strike_price(self, strike_price):
        """Format strike price as integer if it's a whole number."""
        try:
            if not strike_price:
                return ''
            price_float = float(strike_price)
            return int(price_float) if price_float.is_integer() else strike_price
        except (ValueError, TypeError):
            return strike_price

    def _build_fno_description(self, symbol_data):
        """Build description for F&O symbols."""
        description_parts = []
        if symbol_data.get('underlying_symbol'):
            description_parts.append(f"{symbol_data['underlying_symbol']}")
        
        strike_price = symbol_data.get('strike_price')
        # Skip placeholder strike prices (0, -1) - handle as string or int
        try:
            is_placeholder = strike_price is None or str(strike_price).strip() in ['', '0', '-1', '0.0', '-1.0']
        except:
            is_placeholder = True

        if not is_placeholder:
            formatted_strike = self._format_strike_price(strike_price)
            description_parts.append(f"{formatted_strike}")
            
        opt_type = symbol_data.get('option_type')
        # Skip placeholder option types (XX)
        if opt_type and str(opt_type).strip() not in ['XX', 'None', '', 'nan']:
            description_parts.append(f"{opt_type}")
        
        # If it's a future (XX or no strike), add "FUT"
        if (not opt_type or str(opt_type).strip() == 'XX') and is_placeholder:
            description_parts.append("FUT")
            
        return " | ".join(description_parts) if description_parts else f"NSE:{symbol_data.get('symbol', '')}"

    def unified_symbol_search(self, query: str = '', category: str = 'All', limit: int = 20):
        """
        Unified search method that handles all symbol search logic.
        
        Args:
            query: Search query string
            category: Category to search in ('All', 'Stock', 'F&O', 'Exp-Date')
            limit: Maximum number of results to return
            
        Returns:
            List of dictionaries containing search results
        """
        try:
            results = []
            
            # Handle Watchlist category
            if category == 'Watchlist':
                wl = self.get_watchlist(query=query, limit=limit)
                # Add watchlisted flag
                for item in wl:
                    item["watchlisted"] = True
                return wl

            # Handle Exp-Date category
            if category == 'Exp-Date':
                if not query or len(query) < 2:
                    # Return available expiry dates
                    expiry_dates = self.get_expiry_dates(limit=limit)
                    for exp_date in expiry_dates:
                        results.append({
                            "symbol": exp_date['formatted'],
                            "description": f"Expiry Date: {exp_date['formatted']}",
                            "exchange": "NSE",
                            "type": "Exp-Date",
                            "expiry_date": exp_date['formatted'],
                            "expiry_timestamp": exp_date['original']
                        })
                else:
                    # Check if query is numeric (strike price search)
                    if query.isdigit():
                        symbols_by_strike = self.search_symbols_by_strike_price(query, limit=limit)
                        for symbol_data in symbols_by_strike:
                            results.append({
                                "symbol": symbol_data['symbol'],
                                "description": self._build_fno_description(symbol_data),
                                "exchange": symbol_data['expiry_date'],
                                "type": "F&O",
                                "expiry_date": symbol_data['expiry_date'],
                                "underlying_symbol": symbol_data['underlying_symbol'],
                                "strike_price": symbol_data['strike_price']
                            })
                    else:
                        # Search by expiry date pattern
                        expiry_dates = self.get_expiry_dates(limit=100)
                        matching_timestamp = None
                        for exp_date in expiry_dates:
                            if query.lower() in exp_date['formatted'].lower():
                                matching_timestamp = exp_date['original']
                                break
                        
                        if matching_timestamp:
                            symbols_by_expiry = self.search_symbols_by_expiry(matching_timestamp, limit=limit)
                            for symbol_data in symbols_by_expiry:
                                results.append({
                                    "symbol": symbol_data['symbol'],
                                    "description": self._build_fno_description(symbol_data),
                                    "exchange": symbol_data['expiry_date'],
                                    "type": "F&O",
                                    "expiry_date": symbol_data['expiry_date'],
                                    "underlying_symbol": symbol_data['underlying_symbol']
                                })
                        else:
                            # Search for matching expiry date strings
                            matching_dates = [date for date in expiry_dates if query.lower() in date['formatted'].lower()]
                            for exp_date in matching_dates[:10]:
                                results.append({
                                    "symbol": exp_date['formatted'],
                                    "description": f"Expiry Date: {exp_date['formatted']}",
                                    "exchange": "NSE",
                                    "type": "Exp-Date",
                                    "expiry_date": exp_date['formatted'],
                                    "expiry_timestamp": exp_date['original']
                                })
            
            # Handle other categories
            elif category in ['Stock', 'F&O', 'All']:
                if not query or len(query) < 2:
                    return results
                
                # Preload watchlist set for flagging
                try:
                    with self.engine.connect() as conn:
                        wlrows = conn.execute(text("SELECT symbol FROM watchlist")).fetchall()
                        wlset = {r[0] for r in wlrows}
                except Exception:
                    wlset = set()

                # Determine table to search
                if category == 'Stock':
                    # Search only stocks
                    symbols = self.search_symbols(query, table_name='nse_cm_symbols', limit=limit)
                    for symbol in symbols:
                        results.append({
                            "symbol": symbol,
                            "description": f"NSE:{symbol}",
                            "exchange": "NSE",
                            "type": "Stock",
                            "watchlisted": symbol in wlset
                        })
                
                elif category == 'F&O':
                    # Search only F&O symbols with enhanced info
                    symbols_data = self.search_symbols_with_expiry_info(query, table_name='nse_fo_symbols', limit=limit)
                    for symbol_data in symbols_data:
                        results.append({
                            "symbol": symbol_data['symbol'],
                            "description": self._build_fno_description(symbol_data),
                            "exchange": symbol_data['expiry_date'] or 'NSE',
                            "type": "F&O",
                            "expiry_date": symbol_data['expiry_date'],
                            "underlying_symbol": symbol_data['underlying_symbol'],
                            "watchlisted": symbol_data['symbol'] in wlset
                        })
                
                elif category == 'All':
                    # Search both tables
                    symbols_fo_data = self.search_symbols_with_expiry_info(query, table_name='nse_fo_symbols', limit=limit//2)
                    symbols_cm = self.search_symbols(query, table_name='nse_cm_symbols', limit=limit//2)
                    
                    # Preload watchlist set already loaded above
                    # Add F&O results
                    for symbol_data in symbols_fo_data:
                        results.append({
                            "symbol": symbol_data['symbol'],
                            "description": self._build_fno_description(symbol_data),
                            "exchange": symbol_data['expiry_date'] or 'NSE',
                            "type": "F&O",
                            "expiry_date": symbol_data['expiry_date'],
                            "underlying_symbol": symbol_data['underlying_symbol'],
                            "watchlisted": symbol_data['symbol'] in wlset
                        })
                    
                    # Add Stock results (avoid duplicates)
                    for symbol in symbols_cm:
                        if not any(r['symbol'] == symbol for r in results):
                            results.append({
                                "symbol": symbol,
                                "description": f"NSE:{symbol}",
                                "exchange": "NSE",
                                "type": "Stock",
                                "watchlisted": symbol in wlset
                            })
                    
                    # Limit total results
                    results = results[:limit]
            
            return results
            
        except Exception as e:
            logger.error(f"Error in unified symbol search: {str(e)}")
            return []

if __name__ == "__main__":
    urls = [
        "https://public.fyers.in/sym_details/NSE_CM.csv",  # NSE Capital Market (Equity)
        "https://public.fyers.in/sym_details/NSE_FO.csv",  # NSE Futures & Options
        "https://public.fyers.in/sym_details/NSE_CD.csv",  # NSE Currency Derivatives
        # Add more links as needed
    ]
    ticker = SymbolMaster()
    ticker.process_all(urls)

