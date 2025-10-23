# Binance ALMA Supertrend Trading Bot (SQLite Version)

This is an automated, asynchronous trading bot for the Binance exchange. It executes trades based on the ALMA Supertrend strategy, uses a local SQLite database for persistent state management, and sends real-time notifications via Telegram.

The bot is designed to run on a schedule (e.g., daily cron job) and process signals based on 1-day kline data.

## Key Features

- **Automated Trading**: Executes market BUY and SELL orders on Binance (USDT pairs).
- **Trading Strategy**: Implements the ALMA (Arnaud Legoux Moving Average) Supertrend strategy.
- **Database Persistence**: Uses SQLite to track active markets, trade history, signals, and portfolio snapshots.
- **Real-time Notifications**: Sends detailed trade execution and error alerts via Telegram.
- **Dual-Channel Alerts**: Uses separate Telegram bots/chats for regular notifications and critical errors.
- **Dry Run Mode**: Includes a `DRY_RUN` flag for testing the strategy and logic without risking real funds.
- **Asynchronous**: Built with asyncio for efficient, non-blocking operation.
- **Resilient**: Includes error handling and quantity rounding to comply with Binance filters (LOT_SIZE, NOTIONAL).

## How It Works

The bot follows a clear, sequential logic on each run:

1. **Initialize**: The bot starts, sets up logging, and connects to the SQLite database.
2. **Fetch Markets**: It queries the markets table in the database to get a list of all active symbols to trade.
3. **Process Symbols**: For each active symbol:
   - It fetches the latest 1-day kline data from Binance.
   - It calculates the ALMA Supertrend values using the `AlmaTrend` module.
   - It identifies the current trend (`BULL/BEAR`) and crossover signals (`LONG_CROSS/SHORT_CROSS`).
   - The current trend is updated in the markets table for monitoring.
4. **Execute Signals**: 
   - **On LONG_CROSS (Buy Signal)**:
     - It checks the available USDT balance.
     - Places a market BUY order (or simulates it if `DRY_RUN` is True).
     - The order details are recorded in the trades table.
     - A "BUY" notification is sent to Telegram.
   - **On SHORT_CROSS (Sell Signal)**:
     - It checks the available balance of the base asset (e.g., BTC for BTCUSDT).
     - Places a market SELL order (or simulates it).
     - The order details are recorded in the trades table.
     - A "SELL" notification is sent to Telegram.
5. **Final Report**: After processing all symbols, it updates the portfolio value for all assets and saves a new entry in the `portfolio_snapshots` table to track historical performance.

## Core Components

- **trading_bot.py**: The main executable script. Contains the core application logic.
  - `Config`: A class to centralize all configuration (paths, API settings, strategy parameters).
  - `BinanceService`: A wrapper for the python-binance client to handle all API interactions (fetching data, placing orders, checking balances).
  - `TelegramService`: Manages sending messages to the main and error Telegram chats.
  - `TradingBot`: The main class that orchestrates the entire process.
- **database.py**: (Required) Contains the `TradingDatabase` class, which handles all SQLite operations (creating tables, adding trades, updating markets, etc.).
- **AlmaTrend.py**: (Required) Contains the `generateSupertrend` function, which takes kline data and strategy parameters to produce the trend signals.

## Database Schema

This bot relies on a SQLite database (defined in `Config.DATABASE_PATH`) to manage its state. The schema is initialized and managed by the `TradingDatabase` class in `database.py`.

### Tables:

```sql
CREATE TABLE markets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT UNIQUE NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    buy_all INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    trend TEXT
);

CREATE TABLE trades (
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
);

CREATE TABLE portfolio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset TEXT UNIQUE NOT NULL,
    free REAL NOT NULL DEFAULT 0,
    locked REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL DEFAULT 0,
    usd_value REAL NOT NULL DEFAULT 0,
    current_price REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE portfolio_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    total_value REAL NOT NULL,
    usdt_balance REAL NOT NULL,
    crypto_value REAL NOT NULL,
    snapshot_date TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key TEXT UNIQUE NOTKEY,
    description TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_used_at TEXT
);

CREATE TABLE bot_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    direction TEXT NOT NULL,
    signal_price REAL NOT NULL,
    current_price REAL NOT NULL,
    supertrend_value REAL NOT NULL,
    is_processed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE tradable_pairs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT UNIQUE NOT NULL,
    base_asset TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    last_updated TEXT NOT NULL
);
CREATE INDEX idx_trades_symbol ON trades(symbol);
CREATE INDEX idx_trades_date ON trades(trade_date);
CREATE INDEX idx_signals_symbol ON signals(symbol);
CREATE INDEX idx_signals_processed ON signals(is_processed);
CREATE INDEX idx_tradable_pairs_symbol ON tradable_pairs(symbol);
```
## Configuration

All setup is handled in the `Config` class in `trading_bot.py` and external credential files.

### 1. Main Configuration

Inside `trading_bot.py`, adjust the `Config` class:

- **DRY_RUN**: Set to `True` for testing (no real trades) or `False` for live trading.
- **DATABASE_PATH**: The file path for your SQLite database.
- **BASE_DIR**: The root directory for your credential files.
- **ALMA_FACTOR**, **ALMA_SD_LEN**, etc.: Adjust these parameters to fine-tune the trading strategy.

### 2. File-Based Credentials

The bot reads credentials from files to keep them separate from the code. By default, it looks in `YOUR_PATH/READ/`.

- **Binance API**: (CredentialsTRADING)
  - API Key: `<YOUR_BINANCE_API_KEY>`
  - API Secret: `<YOUR_BINANCE_API_SECRET>`

- **Telegram Bots**: (TOKEN/telegram)
  - Main Bot Name: `<YOUR_MAIN_BOT_TOKEN>`
  - Error Bot Name: `<YOUR_ERROR_BOT_TOKEN>`

- **Telegram Chat IDs**: (TOKEN/telegramchat)
  - Error Chat Name: `<YOUR_ERROR_CHAT_ID>`
  - Main Chat Name: `<YOUR_MAIN_CHAT_ID>`

### 3. Database Setup (Crucial!)

Before you can run the bot, you must initialize the database and populate the `markets` table with the symbols you want to trade.

Example:

```sql
-- You must manually insert the markets you want to trade
INSERT INTO markets (symbol, is_active, quantity, buy_all, current_trend)
VALUES ('BTCUSDT', 1, 100, 1, 'NEUTRAL'),
       ('ETHUSDT', 1, 100, 1, 'NEUTRAL'),
       ('BNBUSDT', 0, 50, 0, 'NEUTRAL');
```
## Installation

1. Clone this repository or place the files on your server.
   
   ```bash
   git clone <repository-url>
   cd <repository-folder>
        ```
2.  Install the required Python libraries:
```python
pip install numpy python-telegram-bot python-binance
```
3.  Ensure your custom local modules (`AlmaTrend.py` and `database.py`) are in the same directory as `trading_bot.py`.

## Usage
1. Complete all steps in the **Configuration** section.
2. **Crucially**, ensure your SQLite database is created and the `markets` table is populated with at least one active symbol.
3. Run the bot:
```python
python trading_bot.py
```
4. Since the bot uses 1-day klines, it is intended to be run once per day. You can set this up as a **cron job** on a Linux server.
   
   **Example cron job (runs every day at 00:05):**
   ```cron
   5 0 * * * /usr/bin/python3 YOUR_PATH/trading_bot.py >> YOUR_PATH/LOG/cron.log 2>&1
   ```
## ⚠️Disclaimer
**This is not financial advice.** Trading cryptocurrencies is highly speculative and carries a significant risk of loss. This software is provided "as-is" without warranty of any kind.

**Use this bot at your own risk.** The authors and contributors are not responsible for any financial losses you may incur. Always start with `DRY_RUN = True` and paper trading before committing real funds.
