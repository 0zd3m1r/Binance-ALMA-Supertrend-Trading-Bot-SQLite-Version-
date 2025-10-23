#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
This script performs automated trading on the Binance exchange
based on a specific strategy (ALMA Supertrend) and sends notifications via Telegram.

IMPORTANT: This version uses an SQLite database.
"""

import logging
import math
import sys
import time
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

import numpy as np
import telegram
from binance.client import Client
from binance.exceptions import BinanceAPIException

# Local modules
try:
    import AlmaTrend
    from database import TradingDatabase
except ImportError as e:
    print(f"Error: Required module not found: {e}")
    print("Please ensure 'AlmaTrend.py' and 'database.py' files are present.")
    sys.exit(1)


# --- Configuration ---

class Config:
    """Collects all configurations in one place"""
    # Directories
    BASE_DIR = Path('./READ')
    TOKEN_DIR = BASE_DIR / 'TOKEN'
    LOG_DIR = Path('./LOG')
    
    # File paths
    CREDENTIALS_FILE = BASE_DIR / 'CredentialsTRADING'
    TG_TOKEN_FILE = TOKEN_DIR / 'telegram'
    TG_CHAT_ID_FILE = TOKEN_DIR / 'telegramchat'
    BTC_TREND_FILE = BASE_DIR / 'BTCTrendLongTerm'
    
    # Database
    DATABASE_PATH = './trading_bot.db'
    
    # Bot Mode
    DRY_RUN = True  # True = Test, False = Live (Default should be True for GitHub)
    
    # API Parameters
    KLINES_INTERVAL = '1d'
    KLINES_LIMIT = 750
    MIN_KLINES_REQUIRED = 100
    
    # ALMA Supertrend Parameters
    ALMA_FACTOR = 1.8
    ALMA_SD_LEN = 20
    ALMA_LEN = 5
    ALMA_SIGMA = 2.75
    ALMA_OFFSET = 0.85
    
    # Emojis
    FIRE_EMOJI = '🔥'
    SELL_EMOJI = '😈'
    BULL_EMOJI = '🐂'
    BEAR_EMOJI = '🐻'
    WARNING_EMOJI = '⚠️'
    ERROR_EMOJI = '❌'
    SEPARATOR = "-" * 50


# --- Helper Functions ---

def setup_logging():
    """Configure logging settings"""
    Config.LOG_DIR.mkdir(exist_ok=True)
    log_file = Config.LOG_DIR / 'trading_bot_sqlite.log'
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )

def read_file_lines(filepath: Path) -> List[str]:
    """Read file lines"""
    try:
        with open(filepath, 'r') as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        logging.error(f"File not found: {filepath}")
        return []

def round_quantity(quantity: float, step_size: float) -> float:
    """Round quantity according to Binance LOT_SIZE filter"""
    if step_size <= 0:
        return quantity
    
    precision = abs(int(round(math.log10(step_size)))) if step_size < 1 else 0
    factor = 1 / step_size
    floored_quantity = math.floor(quantity * factor) / factor
    
    return round(floored_quantity, precision)


# --- Service Classes ---

class BinanceService:
    """Binance API management"""
    def __init__(self, api_key: str, api_secret: str, dry_run: bool = True):
        self.client = Client(api_key, api_secret)
        self.symbol_info_cache: Dict[str, Any] = {}
        self.dry_run = dry_run
        mode = "DRY RUN (TEST MODE)" if self.dry_run else "LIVE (REAL MODE)"
        logging.info(f"Binance initialized. MODE: {mode}")

    @staticmethod
    def from_file(filepath: Path, dry_run: bool) -> Optional['BinanceService']:
        lines = read_file_lines(filepath)
        if len(lines) < 4:
            logging.error(f"Credentials missing: {filepath}")
            return None
        return BinanceService(api_key=lines[1], api_secret=lines[3], dry_run=dry_run)

    def get_klines(self, symbol: str) -> List[Any]:
        return self.client.get_klines(
            symbol=symbol,
            interval=Config.KLINES_INTERVAL,
            limit=Config.KLINES_LIMIT
        )

    def get_current_price(self, symbol: str) -> Optional[float]:
        try:
            ticker = self.client.get_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            logging.error(f"{symbol} price error: {e}")
            return None

    def get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        if symbol not in self.symbol_info_cache:
            try:
                self.symbol_info_cache[symbol] = self.client.get_symbol_info(symbol)
            except Exception as e:
                logging.error(f"{symbol} symbol info error: {e}")
                return None
        return self.symbol_info_cache[symbol]

    def get_filter_value(self, symbol: str, filter_type: str, key: str) -> Optional[float]:
        info = self.get_symbol_info(symbol)
        if not info:
            return None
        for f in info['filters']:
            if f['filterType'] == filter_type:
                return float(f[key])
        return None

    def get_asset_balance(self, asset: str) -> tuple:
        """Return asset balance (free, locked)"""
        try:
            balance = self.client.get_asset_balance(asset=asset)
            return float(balance['free']), float(balance['locked'])
        except Exception as e:
            logging.error(f"{asset} balance error: {e}")
            return 0.0, 0.0

    def place_market_order(self, side: str, symbol: str, quantity: float) -> Optional[Dict[str, Any]]:
        if self.dry_run:
            logging.info(f"[DRY RUN] SIMULATED: {side} {quantity} {symbol}")
            return {
                'symbol': symbol,
                'orderId': int(time.time() * 1000),
                'side': side,
                'type': 'MARKET',
                'status': 'FILLED_DRY_RUN',
                'executedQty': str(quantity)
            }
            
        try:
            logging.info(f"ORDER: {side} {quantity} {symbol}")
            if side == Client.SIDE_BUY:
                order = self.client.order_market_buy(symbol=symbol, quantity=quantity)
            elif side == Client.SIDE_SELL:
                order = self.client.order_market_sell(symbol=symbol, quantity=quantity)
            else:
                raise ValueError("Invalid side")
            logging.info(f"ORDER SUCCESSFUL: {order}")
            return order
        except Exception as e:
            logging.error(f"{symbol} order error: {e}")
            return None


class TelegramService:
    """Telegram notifications"""
    def __init__(self, tokens: List[str], chat_ids: List[str]):
        if len(tokens) < 4 or len(chat_ids) < 3:
            raise ValueError("Telegram information missing")
        self.bot = telegram.Bot(token=tokens[1])
        self.error_bot = telegram.Bot(token=tokens[3])
        self.main_chat_id = chat_ids[2]
        self.error_chat_id = chat_ids[0]
        logging.info("Telegram service initialized")

    @staticmethod
    def from_files(token_path: Path, chat_id_path: Path) -> Optional['TelegramService']:
        tokens = read_file_lines(token_path)
        chat_ids = read_file_lines(chat_id_path)
        if not tokens or not chat_ids:
            logging.error("Could not read Telegram files")
            return None
        return TelegramService(tokens, chat_ids)

    async def send_message(self, text: str):
        try:
            await self.bot.send_message(chat_id=self.main_chat_id, text=text, parse_mode='HTML')
        except Exception as e:
            logging.error(f"Telegram message error: {e}")

    async def send_error(self, message: str, symbol: str = "N/A"):
        full_message = (
            f"{Config.ERROR_EMOJI} <b>ERROR</b>\n"
            f"<b>Symbol:</b> {symbol}\n"
            f"<b>Message:</b> {message}"
        )
        try:
            await self.error_bot.send_message(chat_id=self.error_chat_id, text=full_message, parse_mode='HTML')
        except Exception as e:
            logging.error(f"Failed to send Telegram error message: {e}")


# --- Main Bot Class ---

class TradingBot:
    """Main trading bot class - SQLite integrated"""
    def __init__(self, binance: BinanceService, telegram: TelegramService, db: TradingDatabase):
        self.binance = binance
        self.telegram = telegram
        self.db = db
        self.total_crypto_value = 0.0
        self.traded_value_adjustment = 0.0
        self.dry_run = binance.dry_run
        self.trade_prefix = "[DRY RUN] " if self.dry_run else ""

    async def run(self):
        """Main bot loop"""
        logging.info("Trading bot starting (SQLite)...")
        
        # Get active markets from Database
        markets = self.db.get_markets(active_only=True)
        
        if not markets:
            logging.warning("No active markets to process!")
            return

        logging.info(f"{len(markets)} markets will be processed")

        for i, market in enumerate(markets):
            logging.info(f"[{i+1}/{len(markets)}] Processing: {market['symbol']}")
            await self.process_symbol(market)
            await asyncio.sleep(1.5)

        await self.finalize_report()
        logging.info("Trading bot loop completed")

    async def process_symbol(self, market: Dict[str, Any]):
        """Process a single symbol"""
        symbol = market['symbol']
        main_quantity = market['quantity']
        buy_all_if_insufficient = market['buyAll']
        
        try:
            # Get klines data
            klines = self.binance.get_klines(symbol)
            if len(klines) < Config.MIN_KLINES_REQUIRED:
                logging.warning(f"{symbol} insufficient klines: {len(klines)}")
                return

            # Price data
            close = np.array([float(k[4]) for k in klines])
            high = np.array([float(k[2]) for k in klines])
            low = np.array([float(k[3]) for k in klines])

            # Current price
            current_price = self.binance.get_current_price(symbol)
            if not current_price:
                logging.error(f"{symbol} could not get current price")
                return
            
            # Update portfolio
            await self._update_portfolio_value(symbol, current_price)

            # Calculate Supertrend
            supertrend_values = AlmaTrend.generateSupertrend(
                close, high, low,
                Config.ALMA_SD_LEN, Config.ALMA_LEN, Config.ALMA_OFFSET, 
                Config.ALMA_SIGMA, Config.ALMA_FACTOR
            )

            prev_supertrend = float(supertrend_values[-2])
            prev_prev_supertrend = float(supertrend_values[-3])
            prev_close = close[-2]
            prev_prev_close = close[-3]

            # Signal detection
            is_long_cross = prev_prev_supertrend > prev_prev_close and prev_supertrend < prev_close
            is_short_cross = prev_prev_supertrend < prev_prev_close and prev_supertrend > prev_close
            is_bull_trend = prev_supertrend < prev_close and prev_prev_supertrend < prev_prev_close
            is_bear_trend = prev_supertrend > prev_close and prev_prev_supertrend > prev_close

            # Determine current trend and save to database
            current_trend = "NEUTRAL" # Default
            if is_long_cross or is_bull_trend:
                current_trend = "BULL"
            elif is_short_cross or is_bear_trend:
                current_trend = "BEAR"

            try:
                # database.py now supports the 'trend' argument
                self.db.update_market(symbol, trend=current_trend)
                logging.info(f"{symbol} trend updated: {current_trend}")
            except Exception as e:
                # Log if an unexpected error occurs
                logging.warning(f"{symbol} trend could not be updated: {e}")
                await self.telegram.send_error(f"Could not update trend for '{symbol}'. Error: {e}", symbol=symbol)

            if is_long_cross:
                # LONG signal - BUY
                signal_id = self.db.add_signal(symbol, 'LONG_CROSS', 'BUY', 
                                              prev_supertrend, current_price, prev_supertrend)
                await self._handle_long_cross(symbol, main_quantity, buy_all_if_insufficient, current_price)
                if signal_id > 0:
                    self.db.mark_signal_processed(signal_id)
                    
                if symbol == 'BTCUSDT':
                    with open(Config.BTC_TREND_FILE, 'w') as f:
                        f.write(Config.BULL_EMOJI)
                        
            elif is_short_cross:
                # SHORT signal - SELL
                signal_id = self.db.add_signal(symbol, 'SHORT_CROSS', 'SELL',
                                              prev_supertrend, current_price, prev_supertrend)
                await self._handle_short_cross(symbol, current_price)
                if signal_id > 0:
                    self.db.mark_signal_processed(signal_id)
                    
                if symbol == 'BTCUSDT':
                    with open(Config.BTC_TREND_FILE, 'w') as f:
                        f.write(Config.BEAR_EMOJI)
                        
            elif is_bull_trend:
                logging.info(f"{symbol}: BULL trend - waiting for SHORT %{100*(close[-1]/supertrend_values[-1] - 1):.2f}")
                if symbol == 'BTCUSDT':
                    with open(Config.BTC_TREND_FILE, 'w') as f:
                        f.write(Config.BULL_EMOJI)
                        
            elif is_bear_trend:
                logging.info(f"{symbol}: BEAR trend - waiting for LONG %{100*(close[-1]/supertrend_values[-1] - 1):.2f}")
                if symbol == 'BTCUSDT':
                    with open(Config.BTC_TREND_FILE, 'w') as f:
                        f.write(Config.BEAR_EMOJI)

        except Exception as e:
            error_line = sys.exc_info()[-1].tb_lineno
            logging.error(f"{symbol} processing error (line {error_line}): {e}")
            await self.telegram.send_error(f"Error: {e}\nLine: {error_line}", symbol=symbol)

    async def _update_portfolio_value(self, symbol: str, current_price: float):
        """Save portfolio value to database"""
        asset = symbol.replace("USDT", "")
        free, locked = self.binance.get_asset_balance(asset)
        usdt_value = (free + locked) * current_price
        self.total_crypto_value += usdt_value
        
        # Save to Database
        self.db.update_portfolio(asset, free, locked, current_price, usdt_value)

    async def _handle_long_cross(self, symbol: str, main_quantity: int, buy_all: bool, price: float):
        """LONG CROSS - Buy operation"""
        logging.info(f"{symbol} LONG CROSS - Buy signal (Price: {price})")
        
        usdt_free, usdt_locked = self.binance.get_asset_balance('USDT')
        usdt_balance = usdt_free
        quantity_to_buy_usdt = 0
        
        if usdt_balance >= main_quantity and main_quantity > 0:
            quantity_to_buy_usdt = main_quantity
        elif buy_all and 10 < usdt_balance < main_quantity:
            quantity_to_buy_usdt = usdt_balance
            msg = f"{self.trade_prefix}{Config.WARNING_EMOJI} #{symbol} insufficient balance, using all: ${usdt_balance:.2f}"
            await self.telegram.send_message(msg)
        
        if quantity_to_buy_usdt > 0:
            step_size = self.binance.get_filter_value(symbol, 'LOT_SIZE', 'stepSize')
            if step_size is None:
                return
            
            quantity = round_quantity(quantity_to_buy_usdt / price, step_size)
            order = self.binance.place_market_order(Client.SIDE_BUY, symbol, quantity)
            
            if order:
                usdt_equivalent = float(price * quantity)
                self.traded_value_adjustment += usdt_equivalent
                
                # Save to Database - trade_date is automatically current time
                order_id = order.get('orderId', str(int(time.time()*1000)))
                status = 'FILLED' if not self.dry_run else 'FILLED_DRY_RUN'
                self.db.add_trade(
                    symbol=symbol, 
                    side='BUY', 
                    quantity=quantity, 
                    price=price, 
                    value=usdt_equivalent, 
                    order_id=str(order_id), 
                    status=status, 
                    is_dry_run=self.dry_run
                    # no trade_date parameter - uses current time automatically
                )
                
                await self.telegram.send_message(
                    f"{self.trade_prefix}{Config.FIRE_EMOJI} #{symbol} BUY\n"
                    f"<b>Amount:</b> {quantity}\n"
                    f"<b>Price:</b> ${price:.2f}\n"
                    f"<b>Total:</b> ${usdt_equivalent:.2f}"
                )
        else:
            msg = f"{Config.WARNING_EMOJI} #{symbol} insufficient balance for buy\n<b>Balance:</b> ${usdt_balance:.2f}"
            await self.telegram.send_message(msg)

    async def _handle_short_cross(self, symbol: str, price: float):
        """SHORT CROSS - Sell operation"""
        logging.info(f"{symbol} SHORT CROSS - Sell signal (Price: {price})")
        
        asset = symbol.replace("USDT", "")
        asset_free, asset_locked = self.binance.get_asset_balance(asset)
        asset_balance = asset_free
        
        min_notional = self.binance.get_filter_value(symbol, 'NOTIONAL', 'minNotional')
        if min_notional is None:
            return

        usdt_value = asset_balance * price

        if usdt_value >= min_notional:
            step_size = self.binance.get_filter_value(symbol, 'LOT_SIZE', 'stepSize')
            if step_size is None:
                return

            quantity_to_sell = round_quantity(asset_balance, step_size)
            
            # This check is a bit complex, ensuring we don't sell dust
            if quantity_to_sell * price < min_notional and asset_balance > quantity_to_sell:
                # Try again by rounding down one step_size unit
                quantity_to_sell = round_quantity(asset_balance - step_size, step_size)

            if quantity_to_sell > 0:
                order = self.binance.place_market_order(Client.SIDE_SELL, symbol, quantity_to_sell)
                
                if order:
                    self.traded_value_adjustment -= usdt_value
                    
                    # Save to Database - trade_date is automatically current time
                    order_id = order.get('orderId', str(int(time.time()*1000)))
                    status = 'FILLED' if not self.dry_run else 'FILLED_DRY_RUN'
                    self.db.add_trade(
                        symbol=symbol, 
                        side='SELL', 
                        quantity=quantity_to_sell, 
                        price=price, 
                        value=usdt_value,
                        order_id=str(order_id), 
                        status=status, 
                        is_dry_run=self.dry_run
                        # no trade_date parameter - uses current time automatically
                    )
                    
                    await self.telegram.send_message(
                        f"{self.trade_prefix}{Config.SELL_EMOJI} #{symbol} SELL\n"
                        f"<b>Amount:</b> {quantity_to_sell}\n"
                        f"<b>Price:</b> ${price:.2f}\n"
                        f"<b>Total:</b> ${usdt_value:.2f}"
                    )
                    
                    # Update market quantity (after sell)
                    if not self.dry_run:
                        self.db.update_market(symbol, quantity=int(usdt_value))
        else:
            msg = f"{Config.WARNING_EMOJI} #{symbol} insufficient balance for sell\n<b>Value:</b> ${usdt_value:.2f}"
            await self.telegram.send_message(msg)

    async def finalize_report(self):
        """Final report and portfolio snapshot"""
        usdt_free, usdt_locked = self.binance.get_asset_balance('USDT')
        final_usdt_balance = usdt_free + usdt_locked
        
        # Add USDT to portfolio as well
        self.db.update_portfolio('USDT', usdt_free, usdt_locked, 1.0, final_usdt_balance)
        
        total_portfolio_value = final_usdt_balance + self.total_crypto_value + self.traded_value_adjustment
        
        # Add portfolio snapshot
        self.db.add_portfolio_snapshot(total_portfolio_value, final_usdt_balance, self.total_crypto_value)
        
        await self.telegram.send_message(f"💰 USDT BALANCE: ${final_usdt_balance:.2f}")
        await self.telegram.send_message(f"📊 TOTAL PORTFOLIO: ${total_portfolio_value:.2f}")
        
        logging.info(f"Total Portfolio Value: ${total_portfolio_value:.2f}")


# --- Main Execution ---

async def main():
    """Main entry point"""
    is_dry_run = Config.DRY_RUN
    
    setup_logging()
    logging.info("=" * 60)
    logging.info("Trading Bot Starting (SQLite Version)")
    logging.info("=" * 60)
    
    # Initialize Database
    try:
        db = TradingDatabase(Config.DATABASE_PATH)
        logging.info("✓ Database connection successful")
    except Exception as e:
        logging.error(f"✗ Database error: {e}")
        sys.exit(1)
    
    # Binance service
    binance_service = BinanceService.from_file(Config.CREDENTIALS_FILE, dry_run=is_dry_run)
    if not binance_service:
        sys.exit(1)

    # Telegram service
    telegram_service = TelegramService.from_files(Config.TG_TOKEN_FILE, Config.TG_CHAT_ID_FILE)
    if not telegram_service:
        sys.exit(1)

    # Start bot
    bot = TradingBot(binance_service, telegram_service, db)
    await bot.run()
    
    logging.info("=" * 60)
    logging.info("Bot finished successfully")
    logging.info("=" * 60)


if __name__ == '__main__':
    asyncio.run(main())

