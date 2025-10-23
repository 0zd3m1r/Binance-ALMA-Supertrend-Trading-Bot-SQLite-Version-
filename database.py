#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Trading Bot Database Module
SQLite database management and all database operations
"""

import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from contextlib import contextmanager
import json

class TradingDatabase:
    """SQLite database management class"""
    
    def __init__(self, db_path: str = None):
        """
        Args:
            db_path: Database file path. If None, default is used.
        """
        if db_path is None:
            # Default to relative path for portability
            db_path = "./trading_bot.db"
        
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        logging.info(f"Database path: {self.db_path}")
        self._init_database()
    
    @contextmanager
    def get_connection(self):
        """Secure database connection with context manager"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row  # Dict-like access
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logging.error(f"Database error: {e}")
            raise
        finally:
            conn.close()

    # Helper function to add a column to an existing table
    def _check_and_add_column(self, cursor, table_name: str, column_name: str, column_type: str):
        """Adds a column to the table if it doesn't exist"""
        try:
            # Check for column existence
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [row['name'] for row in cursor.fetchall()]
            
            if column_name not in columns:
                logging.info(f"Adding column '{column_name}' to table '{table_name}'...")
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
                logging.info(f"Column '{column_name}' added.")
        except Exception as e:
            logging.error(f"Column addition error ({table_name}.{column_name}): {e}")
    # <<< END OF CHANGE >>>
    
    def _init_database(self):
        """Initialize/create the database tables"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Markets table - Markets to be traded
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS markets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT UNIQUE NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    buy_all INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    trend TEXT, 
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')
            
            # Trades table - Executed trades
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    value REAL NOT NULL,
                    order_id TEXT,
                    status TEXT NOT NULL,
                    is_dry_run INTEGER NOT NULL DEFAULT 0,
                    trade_date TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            ''')
            
            # Portfolio table - Current portfolio status
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS portfolio (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset TEXT UNIQUE NOT NULL,
                    free REAL NOT NULL DEFAULT 0,
                    locked REAL NOT NULL DEFAULT 0,
                    total REAL NOT NULL DEFAULT 0,
                    usd_value REAL NOT NULL DEFAULT 0,
                    current_price REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
            ''')
            
            # Portfolio History - Portfolio value history
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS portfolio_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    total_value REAL NOT NULL,
                    usdt_balance REAL NOT NULL,
                    crypto_value REAL NOT NULL,
                    snapshot_date TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            ''')
            
            # API Keys table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    api_key TEXT UNIQUE NOT NULL,
                    description TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT
                )
            ''')
            
            # Bot Config table - Bot settings
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bot_config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL,
                    description TEXT,
                    updated_at TEXT NOT NULL
                )
            ''')
            
            # Signals table - Trading signals
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    signal_price REAL NOT NULL,
                    current_price REAL NOT NULL,
                    supertrend_value REAL NOT NULL,
                    is_processed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            ''')
            
            # Indices
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(trade_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_processed ON signals(is_processed)')

            # Check existing 'markets' table and add 'trend' column
            self._check_and_add_column(cursor, 'markets', 'trend', 'TEXT')
            
            conn.commit()
            logging.info("Database tables created/verified successfully")
    
    # ============ MARKETS OPERATIONS ============
    
    def add_market(self, symbol: str, quantity: int, buy_all: bool = False) -> bool:
        """Add a new market"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                cursor.execute('''
                    INSERT INTO markets (symbol, quantity, buy_all, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (symbol, quantity, 1 if buy_all else 0, now, now))
                logging.info(f"Market added: {symbol}")
                return True
        except sqlite3.IntegrityError:
            logging.warning(f"Market already exists: {symbol}")
            return False
        except Exception as e:
            logging.error(f"Market addition error: {e}")
            return False
    
    def get_markets(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """Get all markets"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM markets'
            if active_only:
                query += ' WHERE is_active = 1'
            query += ' ORDER BY symbol'
            
            cursor.execute(query)
            rows = cursor.fetchall()
            
            return [{
                'id': row['id'],
                'symbol': row['symbol'],
                'quantity': row['quantity'],
                'buyAll': bool(row['buy_all']),
                'isActive': bool(row['is_active']),
                'trend': row['trend'], # Added
                'createdAt': row['created_at'],
                'updatedAt': row['updated_at']
            } for row in rows]
    
    def get_market(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get a single market"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM markets WHERE symbol = ?', (symbol,))
            row = cursor.fetchone()
            
            if row:
                return {
                    'id': row['id'],
                    'symbol': row['symbol'],
                    'quantity': row['quantity'],
                    'buyAll': bool(row['buy_all']),
                    'isActive': bool(row['is_active']),
                    'trend': row['trend']
                }
            return None
    
    def update_market(self, symbol: str, quantity: int = None, buy_all: bool = None, trend: str = None) -> bool:
        """Update a market"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                updates = []
                params = []
                
                if quantity is not None:
                    updates.append('quantity = ?')
                    params.append(quantity)
                
                if buy_all is not None:
                    updates.append('buy_all = ?')
                    params.append(1 if buy_all else 0)

                if trend is not None:
                    updates.append('trend = ?')
                    params.append(trend)

                if not updates: # If there's nothing to update
                    return True
                
                updates.append('updated_at = ?')
                params.append(datetime.now().isoformat())
                params.append(symbol)
                
                query = f"UPDATE markets SET {', '.join(updates)} WHERE symbol = ?"
                cursor.execute(query, params)
                
                if cursor.rowcount > 0:
                    logging.info(f"Market updated: {symbol}")
                    return True
                return False
        except Exception as e:
            logging.error(f"Market update error: {e}")
            return False
    
    def delete_market(self, symbol: str) -> bool:
        """Delete market (soft delete)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE markets SET is_active = 0, updated_at = ?
                    WHERE symbol = ?
                ''', (datetime.now().isoformat(), symbol))
                
                if cursor.rowcount > 0:
                    logging.info(f"Market deleted: {symbol}")
                    return True
                return False
        except Exception as e:
            logging.error(f"Market deletion error: {e}")
            return False
    
    # ============ TRADES OPERATIONS ============
    
    def add_trade(self, symbol: str, side: str, quantity: float, price: float, 
                  value: float, order_id: str = None, status: str = 'FILLED',
                  is_dry_run: bool = False, trade_date: str = None) -> int:
        """Add a new trade
        
        Args:
            trade_date: Optional. If not specified, current time is used.
                        Format: 'YYYY-MM-DD' or ISO timestamp
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                
                # If no custom date is given, use current time
                if trade_date is None:
                    trade_date = now
                # If only date is given (YYYY-MM-DD), convert to timestamp
                elif len(trade_date) == 10:  # YYYY-MM-DD format
                    trade_date = f"{trade_date}T00:00:00"
                
                cursor.execute('''
                    INSERT INTO trades (symbol, side, quantity, price, value, order_id, 
                                        status, is_dry_run, trade_date, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (symbol, side, quantity, price, value, order_id, status, 
                      1 if is_dry_run else 0, trade_date, now))
                
                trade_id = cursor.lastrowid
                logging.info(f"Trade saved: {symbol} {side} {value} ({trade_date})")
                return trade_id
        except Exception as e:
            logging.error(f"Trade addition error: {e}")
            return -1
    
    def get_trades(self, symbol: str = None, limit: int = 100, 
                   include_dry_run: bool = False) -> List[Dict[str, Any]]:
        """Get trade history"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            query = 'SELECT * FROM trades WHERE 1=1'
            params = []
            
            if symbol:
                query += ' AND symbol = ?'
                params.append(symbol)
            
            if not include_dry_run:
                query += ' AND is_dry_run = 0'
            
            query += ' ORDER BY trade_date DESC LIMIT ?'
            params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            return [{
                'id': row['id'],
                'symbol': row['symbol'],
                'side': row['side'],
                'quantity': row['quantity'],
                'price': row['price'],
                'value': row['value'],
                'orderId': row['order_id'],
                'status': row['status'],
                'isDryRun': bool(row['is_dry_run']),
                'date': row['trade_date']
            } for row in rows]
    
    def get_trade_stats(self, symbol: str = None) -> Dict[str, Any]:
        """Trade statistics"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            query = '''
                SELECT 
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN side = 'BUY' THEN 1 ELSE 0 END) as total_buys,
                    SUM(CASE WHEN side = 'SELL' THEN 1 ELSE 0 END) as total_sells,
                    SUM(CASE WHEN side = 'BUY' THEN value ELSE 0 END) as total_buy_value,
                    SUM(CASE WHEN side = 'SELL' THEN value ELSE 0 END) as total_sell_value
                FROM trades
                WHERE is_dry_run = 0
            '''
            
            params = []
            if symbol:
                query += ' AND symbol = ?'
                params.append(symbol)
            
            cursor.execute(query, params)
            row = cursor.fetchone()
            
            return {
                'totalTrades': row['total_trades'] or 0,
                'totalBuys': row['total_buys'] or 0,
                'totalSells': row['total_sells'] or 0,
                'totalBuyValue': row['total_buy_value'] or 0,
                'totalSellValue': row['total_sell_value'] or 0,
                'netValue': (row['total_sell_value'] or 0) - (row['total_buy_value'] or 0)
            }
    
    # ============ PORTFOLIO OPERATIONS ============
    
    def update_portfolio(self, asset: str, free: float, locked: float, 
                         current_price: float, usd_value: float) -> bool:
        """Update portfolio status"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                total = free + locked
                
                cursor.execute('''
                    INSERT INTO portfolio (asset, free, locked, total, usd_value, current_price, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(asset) DO UPDATE SET
                        free = excluded.free,
                        locked = excluded.locked,
                        total = excluded.total,
                        usd_value = excluded.usd_value,
                        current_price = excluded.current_price,
                        updated_at = excluded.updated_at
                ''', (asset, free, locked, total, usd_value, current_price, now))
                
                return True
        except Exception as e:
            logging.error(f"Portfolio update error: {e}")
            return False
    
    def get_portfolio(self) -> List[Dict[str, Any]]:
        """Get entire portfolio"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM portfolio 
                WHERE total > 0 OR usd_value > 0.01
                ORDER BY usd_value DESC
            ''')
            rows = cursor.fetchall()
            
            return [{
                'asset': row['asset'],
                'free': row['free'],
                'locked': row['locked'],
                'total': row['total'],
                'usdValue': row['usd_value'],
                'currentPrice': row['current_price'],
                'updatedAt': row['updated_at']
            } for row in rows]
    
    def add_portfolio_snapshot(self, total_value: float, usdt_balance: float, 
                               crypto_value: float) -> int:
        """Add portfolio value snapshot"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                today = datetime.now().strftime('%Y-%m-%d')
                
                # Check if a snapshot already exists for today
                cursor.execute('''
                    SELECT id FROM portfolio_history 
                    WHERE snapshot_date = ?
                ''', (today,))
                
                existing = cursor.fetchone()
                
                if existing:
                    # Update
                    cursor.execute('''
                        UPDATE portfolio_history 
                        SET total_value = ?, usdt_balance = ?, crypto_value = ?, created_at = ?
                        WHERE snapshot_date = ?
                    ''', (total_value, usdt_balance, crypto_value, now, today))
                    return existing['id']
                else:
                    # Add new
                    cursor.execute('''
                        INSERT INTO portfolio_history (total_value, usdt_balance, crypto_value, snapshot_date, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (total_value, usdt_balance, crypto_value, today, now))
                    return cursor.lastrowid
        except Exception as e:
            logging.error(f"Snapshot addition error: {e}")
            return -1
    
    def get_portfolio_history(self, days: int = 30) -> List[Dict[str, Any]]:
        """Portfolio value history"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM portfolio_history 
                ORDER BY snapshot_date DESC 
                LIMIT ?
            ''', (days,))
            rows = cursor.fetchall()
            
            # Return in chronological order for charting
            return [{
                'value': row['total_value'],
                'usdtBalance': row['usdt_balance'],
                'cryptoValue': row['crypto_value'],
                'date': row['snapshot_date']
            } for row in reversed(rows)]
    
    # ============ SIGNALS OPERATIONS ============
    
    def add_signal(self, symbol: str, signal_type: str, direction: str,
                   signal_price: float, current_price: float, supertrend_value: float) -> int:
        """Add a new signal"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                cursor.execute('''
                    INSERT INTO signals (symbol, signal_type, direction, signal_price, 
                                         current_price, supertrend_value, is_processed, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                ''', (symbol, signal_type, direction, signal_price, current_price, supertrend_value, now))
                return cursor.lastrowid
        except Exception as e:
            logging.error(f"Signal addition error: {e}")
            return -1
    
    def mark_signal_processed(self, signal_id: int) -> bool:
        """Mark signal as processed"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE signals SET is_processed = 1 WHERE id = ?', (signal_id,))
                return cursor.rowcount > 0
        except Exception as e:
            logging.error(f"Signal update error: {e}")
            return False
    
    # ============ API KEYS OPERATIONS ============
    
    def add_api_key(self, api_key: str, description: str = None) -> bool:
        """Add new API key"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                cursor.execute('''
                    INSERT INTO api_keys (api_key, description, created_at)
                    VALUES (?, ?, ?)
                ''', (api_key, description, now))
                return True
        except sqlite3.IntegrityError:
            return False
        except Exception as e:
            logging.error(f"API key addition error: {e}")
            return False
    
    def verify_api_key(self, api_key: str) -> bool:
        """Verify API key"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id FROM api_keys 
                WHERE api_key = ? AND is_active = 1
            ''', (api_key,))
            
            row = cursor.fetchone()
            if row:
                # Update last used time
                cursor.execute('''
                    UPDATE api_keys SET last_used_at = ? WHERE id = ?
                ''', (datetime.now().isoformat(), row['id']))
                return True
            return False
    
    def get_api_keys(self) -> List[Dict[str, Any]]:
        """Get all API keys"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM api_keys ORDER BY created_at DESC')
            rows = cursor.fetchall()
            
            return [{
                'id': row['id'],
                'apiKey': row['api_key'][:10] + '...',  # For security
                'description': row['description'],
                'isActive': bool(row['is_active']),
                'createdAt': row['created_at'],
                'lastUsedAt': row['last_used_at']
            } for row in rows]
    
    # ============ CONFIG OPERATIONS ============
    
    def set_config(self, key: str, value: Any, description: str = None) -> bool:
        """Save config value"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                value_str = json.dumps(value) if not isinstance(value, str) else value
                
                cursor.execute('''
                    INSERT INTO bot_config (key, value, description, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        description = excluded.description,
                        updated_at = excluded.updated_at
                ''', (key, value_str, description, now))
                return True
        except Exception as e:
            logging.error(f"Config save error: {e}")
            return False
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """Get config value"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM bot_config WHERE key = ?', (key,))
            row = cursor.fetchone()
            
            if row:
                try:
                    # Try to parse as JSON first
                    return json.loads(row['value'])
                except:
                    # Fallback to plain string
                    return row['value']
            return default
    
    # ============ HELPER FUNCTIONS ============
    
    def get_stats(self) -> Dict[str, Any]:
        """General statistics"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Market count
            cursor.execute('SELECT COUNT(*) as count FROM markets WHERE is_active = 1')
            market_count = cursor.fetchone()['count']
            
            # Trade count
            cursor.execute('SELECT COUNT(*) as count FROM trades WHERE is_dry_run = 0')
            trade_count = cursor.fetchone()['count']
            
            # Portfolio value
            cursor.execute('SELECT SUM(usd_value) as total FROM portfolio')
            portfolio_value = cursor.fetchone()['total'] or 0
            
            return {
                'totalMarkets': market_count,
                'totalTrades': trade_count,
                'portfolioValue': portfolio_value,
                'lastUpdate': datetime.now().isoformat()
            }
    
    def migrate_from_files(self, markets_file: str, history_file: str, balance_file: str):
        """Migrate data from old file-based system (migration)"""
        logging.info("Starting migration from file-based system...")
        
        # Markets migration
        try:
            with open(markets_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and '-' in line:
                        parts = line.split('-')
                        symbol = parts[0]
                        quantity = int(parts[1]) if len(parts) > 1 else 0
                        buy_all = parts[2].strip() == '1' if len(parts) > 2 else False
                        self.add_market(symbol, quantity, buy_all)
            logging.info("Markets migration complete")
        except Exception as e:
            logging.error(f"Markets migration error: {e}")
        
        # History migration
        try:
            with open(history_file, 'r') as f:
                for line in f:
                    parts = line.strip().split(';')
                    if len(parts) >= 3:
                        symbol = parts[0]
                        side_value = parts[1].split(':')
                        side = side_value[0]
                        value = float(side_value[1])
                        date = parts[2].split(':')[1] if ':' in parts[2] else parts[2]
                        
                        # Approximate price (since value/quantity is unknown)
                        self.add_trade(symbol, side, 0, 0, value, None, 'FILLED_MIGRATED', False)
            logging.info("History migration complete")
        except Exception as e:
            logging.error(f"History migration error: {e}")
        
        logging.info("Migration complete!")


# Test function
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("Trading Database Test")
    print("=" * 60)
    
    # Use relative path for testing
    db = TradingDatabase(db_path='./test_trading_bot.db')
    
    # Test: Add market
    db.add_market('BTCUSDT', 100, False)
    db.add_market('ETHUSDT', 50, True)
    
    # Test: List markets
    markets = db.get_markets()
    print(f"\nMarkets: {len(markets)} total")
    for m in markets:
        print(f"  - {m['symbol']}: {m['quantity']} USDT (Trend: {m['trend']})")
    
    # Test: Add trade
    db.add_trade('BTCUSDT', 'BUY', 0.001, 45000, 45, 'TEST123', 'FILLED', False)
    
    # Test: Statistics
    stats = db.get_stats()
    print(f"\nStatistics: {stats}")
    
    print("\n" + "=" * 60)
    print("Test complete!")
