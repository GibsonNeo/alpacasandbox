# Alpaca Market Data Sandbox 🦙📊

A collection of Python scripts for fetching and analyzing market data using the [Alpaca Markets API](https://alpaca.markets/).

## Features

- **Historical OHLCV Data** - Fetch daily/weekly/monthly bars for stocks and crypto
- **Whale Alert System** - Detect large trades with buy/sell direction inference
- **Real-time Streaming** - Monitor trades live during market hours
- **Split & Dividend Adjustments** - Get accurate historical prices for backtesting

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API Keys

Get your API keys from the [Alpaca Dashboard](https://app.alpaca.markets/brokerage/dashboard/overview).

Create a `.env` file:

```bash
export APCA-API-KEY-ID=your_api_key_here
export APCA-API-SECRET-KEY=your_secret_key_here
```

### 3. Run the Scripts

```bash
# Fetch historical OHLCV data
python fetch_historical_data.py

# Run whale alert system
python whale_alert.py
```

---

## 📁 Scripts

### `fetch_historical_data.py`

Fetches historical daily bar data (OHLCV) for stocks and crypto.

**Features:**
- Stocks: Requires API keys
- Crypto: No API keys needed!
- Adjustable for splits, dividends, and spin-offs

**Usage:**
```bash
python fetch_historical_data.py
```

**Key Functions:**
```python
from fetch_historical_data import fetch_stock_daily_bars, fetch_crypto_daily_bars
from alpaca.data.enums import Adjustment

# Fetch adjusted stock data (recommended for backtesting)
df = fetch_stock_daily_bars(
    symbols=['AAPL', 'MSFT', 'GOOGL'],
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 12, 31),
    adjustment=Adjustment.ALL  # Adjust for splits + dividends + spin-offs
)

# Fetch crypto data (no API keys needed)
df = fetch_crypto_daily_bars(
    symbols=['BTC/USD', 'ETH/USD'],
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 12, 31)
)
```

---

### `whale_alert.py`

Detects large ("whale") trades and infers buy/sell direction using bid/ask data.

**Features:**
- Historical whale trade finder (scans each ticker individually)
- **Direction summary by ticker** - See bullish/bearish sentiment per symbol
- **Top 5 & Top 20** whale trades across all tickers combined
- Real-time streaming alerts (market hours)
- Direction inference with confidence scoring
- Net sentiment analysis (bullish/bearish)

**Usage:**
```bash
python whale_alert.py
```

**Menu Options:**
1. **Historical Trades** - See raw trade-by-trade data
2. **Whale Finder** - Scan all tickers for large trades with per-ticker breakdown
3. **Live Whale Alerts** - Real-time monitoring (market hours only)
4. **Run All Demos** - Options 1 & 2

---

## 📊 Data Fields

### Bar Data (OHLCV)

| Field | Description |
|-------|-------------|
| `open` | Opening price |
| `high` | Highest price |
| `low` | Lowest price |
| `close` | Closing price |
| `volume` | Total shares/units traded |
| `trade_count` | Number of individual trades |
| `vwap` | Volume-weighted average price |

### Trade Data

| Field | Description |
|-------|-------------|
| `price` | Trade execution price |
| `size` | Number of shares traded |
| `exchange` | Exchange code (D=FINRA ADF, Q=NASDAQ, P=NYSE Arca, etc.) |
| `timestamp` | Precise trade timestamp |
| `conditions` | Trade condition codes |
| `tape` | A=NYSE, B=Regional, C=NASDAQ |

---

## 🔧 Configuration Options

### Whale Alert Settings

The whale alert script has easy-to-configure variables at the top of `whale_alert.py`:

```python
# ============================================================================
# CONFIGURATION - Edit these variables to customize behavior
# ============================================================================

# Symbols to monitor for each mode
SYMBOLS_HISTORICAL = ["AAPL", "TSLA", "NVDA"]    # Historical trades demo
SYMBOLS_WHALE_FINDER = ["AAPL", "TSLA", "NVDA", "SPY", "QQQ", "AMD", "MSFT", "GOOGL", "AMZN", "META"]
SYMBOLS_LIVE_STREAM = ["AAPL", "TSLA", "NVDA", "SPY", "QQQ", "AMD"]

# Whale detection thresholds
MIN_SHARES_WHALE_FINDER = 5000   # Minimum shares for whale finder
MIN_VALUE_WHALE_FINDER = 100000  # Minimum $ value for whale finder
MIN_SHARES_LIVE = 5000           # Minimum shares for live alerts
MIN_VALUE_LIVE = 250000          # Minimum $ value for live alerts

# Lookback periods
LOOKBACK_HOURS_TRADES = 1        # Hours of historical trades to fetch
LOOKBACK_DAYS_WHALE_FINDER = 1   # Days to scan for whale finder
```

Simply edit these values to change which tickers to monitor and adjust the whale detection thresholds.

---

### Price Adjustments (for historical bars)

| Adjustment | Description | Use Case |
|------------|-------------|----------|
| `Adjustment.RAW` | No adjustments | See actual historical prices |
| `Adjustment.SPLIT` | Stock splits only | When you only care about splits |
| `Adjustment.DIVIDEND` | Dividends only | When you only care about dividends |
| `Adjustment.ALL` | All adjustments | **Recommended for backtesting** |

```python
from alpaca.data.enums import Adjustment

# For backtesting - use ALL adjustments
df = fetch_stock_daily_bars(symbols, start, end, adjustment=Adjustment.ALL)

# For seeing actual traded prices
df = fetch_stock_daily_bars(symbols, start, end, adjustment=Adjustment.RAW)
```

### Timeframes

| Timeframe | Format | Example |
|-----------|--------|---------|
| Minutes | `[1-59]Min` | `5Min`, `15Min` |
| Hours | `[1-23]Hour` | `1Hour`, `4Hour` |
| Day | `1Day` | Daily bars |
| Week | `1Week` | Weekly bars |
| Month | `[1,2,3,4,6,12]Month` | `1Month`, `3Month` |

### Data Feeds

| Feed | Description | Subscription |
|------|-------------|--------------|
| `sip` | All US exchanges (100% market coverage) | Paid |
| `iex` | Investors Exchange only (~2.5% coverage) | **Free** |
| `boats` | Blue Ocean ATS (overnight trading) | Paid |
| `otc` | Over-the-counter exchanges | Paid |

---

## 🐋 Whale Alert: Direction Inference

Since trade data doesn't include buy/sell direction, we infer it using the **Quote Rule** (simplified Lee-Ready algorithm):

### How It Works

Compare the trade price to the bid/ask spread at the time of the trade:

| Trade Position | Inferred Direction | Confidence |
|----------------|-------------------|------------|
| At or above ASK | **BUY** (aggressive buyer) | 95% |
| At or below BID | **SELL** (aggressive seller) | 95% |
| 70-99% of spread (near ask) | Likely BUY | 50-95% |
| 1-30% of spread (near bid) | Likely SELL | 50-95% |
| 30-70% of spread (midpoint) | Neutral/Unclear | 50% |

### Example Output

**Direction Summary by Ticker:**
```
====================================================================================================
📊 DIRECTION SUMMARY BY TICKER
====================================================================================================
Ticker   🟢 Buys Buy Value        🔴 Sells Sell Value        Net Flow           Sentiment   
----------------------------------------------------------------------------------------------------
AAPL          12      $2,345,678       8      $1,234,567       +$1,111,111       🟢 BULLISH  
TSLA           5        $987,654      15      $3,456,789       -$2,469,135       🔴 BEARISH  
SPY           20      $5,678,901      18      $4,567,890       +$1,111,011       🟢 BULLISH  
```

**Top 20 Whale Trades:**
```
#    Dir  Symbol       Price       Shares           Value        Bid        Ask  Conf  
----------------------------------------------------------------------------------------------------
1    🔴   AAPL      $178.28       37,689   $10,488,094.92    $178.92    $179.08  95%   
2    🟢   TSLA      $245.50       25,000    $6,137,500.00    $245.40    $245.55  95%   
...
```

**Detailed Top 5:**
```
#1 🔴 AAPL
   Price:     $278.28
   Size:      37,689 shares
   Value:     $10,488,094.92
   Quote:     Bid $278.92 | Ask $279.08
   Direction: SELL (95% confidence)
   Analysis:  Trade AT/BELOW BID → Aggressive SELL (seller hit bid)
```

---

## 📡 Real-Time Streaming

The whale alert system can monitor trades in real-time during market hours:

```python
from whale_alert import WhaleAlertStream

# Configure thresholds
whale_monitor = WhaleAlertStream(
    api_key=API_KEY,
    api_secret=API_SECRET,
    min_shares=5000,      # Alert on trades >= 5,000 shares
    min_value=250000      # OR trades >= $250,000
)

# Subscribe to symbols
whale_monitor.subscribe(['AAPL', 'TSLA', 'NVDA', 'SPY', 'QQQ'])

# Start monitoring (blocks until Ctrl+C)
whale_monitor.run()
```

**Note:** Real-time streaming only works during market hours (9:30 AM - 4:00 PM ET, Mon-Fri).

---

## 🗂️ Other Alpaca Data Available

Beyond bars and trades, Alpaca offers:

| Data Type | Description |
|-----------|-------------|
| **Quotes** | Bid/ask prices and sizes |
| **Snapshots** | Latest trade, quote, and bars combined |
| **Auctions** | Opening/closing auction data |
| **News** | Market news with sentiment |
| **Corporate Actions** | Splits, dividends, spin-offs |
| **Options** | Options bars, trades, quotes |
| **Crypto** | Crypto bars, trades, quotes (free!) |
| **Forex** | Currency exchange rates |

---

## 📚 Resources

- [Alpaca Documentation](https://docs.alpaca.markets/)
- [Market Data API Reference](https://docs.alpaca.markets/reference/stockbars)
- [alpaca-py SDK GitHub](https://github.com/alpacahq/alpaca-py)
- [Alpaca Community Slack](https://alpaca.markets/slack)

---

## ⚠️ Disclaimer

This code is for educational purposes only. It is not financial advice. Always do your own research before making investment decisions. Past performance does not guarantee future results.

---

## 📄 License

MIT License - feel free to use and modify as needed.
