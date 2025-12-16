"""
Alpaca Whale Alert - Monitor for Large Trades

This script demonstrates:
1. Fetching historical trades to see individual trade data
2. Real-time streaming to alert on large ("whale") trades

Trade data includes:
- price: The trade price
- size: Number of shares traded (this is what we filter for whales!)
- exchange: The exchange where the trade occurred
- timestamp: When the trade happened
- conditions: Trade condition codes (e.g., regular, odd lot, etc.)
- tape: The tape (A=NYSE, B=NYSE Arca/regional, C=NASDAQ)
- id: Unique trade ID
"""

import os
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

API_KEY = os.getenv('APCA-API-KEY-ID')
API_SECRET = os.getenv('APCA-API-SECRET-KEY')

# =============================================================================
# CONFIGURATION - Edit these to customize your whale alerts!
# =============================================================================

# Symbols to monitor/scan
SYMBOLS_HISTORICAL = ['AAPL', 'TSLA', 'SPY']           # For historical trades demo
SYMBOLS_WHALE_FINDER = ['AAPL','TSLA', 'SPY', 'NVDA', 'MSFT']  # For whale finder
SYMBOLS_LIVE_STREAM = ['AAPL', 'TSLA', 'NVDA', 'SPY', 'QQQ', 'MSFT', 'AMZN', 'META', 'GOOGL']  # For live alerts

# Whale thresholds - a trade is a "whale" if it meets EITHER condition
MIN_SHARES_WHALE_FINDER = 5000      # Minimum shares for whale finder
MIN_VALUE_WHALE_FINDER = 1000000     # Minimum dollar value for whale finder ($)

MIN_SHARES_LIVE = 5000              # Minimum shares for live alerts
MIN_VALUE_LIVE = 1000000             # Minimum dollar value for live alerts ($)

# Time range for historical lookback
LOOKBACK_HOURS_TRADES = 5           # Hours to look back for historical trades demo
LOOKBACK_DAYS_WHALE_FINDER = 5      # Days to look back for whale finder

# =============================================================================

# Alpaca SDK imports
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockTradesRequest, StockQuotesRequest, StockLatestQuoteRequest
from alpaca.data.live import StockDataStream


def infer_trade_direction(trade_price: float, bid: float, ask: float) -> dict:
    """
    Infer trade direction using the Quote Rule (Lee-Ready algorithm simplified).
    
    Compares trade price to the bid/ask spread to determine if the trade
    was likely initiated by a buyer or seller.
    
    Returns:
        dict with 'direction', 'confidence', 'emoji', and 'description'
    """
    if bid is None or ask is None or bid == 0 or ask == 0:
        return {
            'direction': 'UNKNOWN',
            'confidence': 0,
            'emoji': '⚪',
            'description': 'No quote data available'
        }
    
    mid_price = (bid + ask) / 2
    spread = ask - bid
    
    # Handle zero spread (locked market)
    if spread == 0:
        return {
            'direction': 'NEUTRAL',
            'confidence': 50,
            'emoji': '⚪',
            'description': 'Market locked (bid = ask)'
        }
    
    # Calculate where the trade occurred within the spread
    # 0 = at bid, 1 = at ask, 0.5 = at midpoint
    position_in_spread = (trade_price - bid) / spread
    
    # Clamp to handle trades outside the spread
    position_in_spread = max(0, min(1, position_in_spread))
    
    if trade_price >= ask:
        # Trade at or above ask - strong buy signal
        return {
            'direction': 'BUY',
            'confidence': 95,
            'emoji': '🟢',
            'description': 'Trade AT/ABOVE ASK → Aggressive BUY (buyer lifted offer)'
        }
    elif trade_price <= bid:
        # Trade at or below bid - strong sell signal
        return {
            'direction': 'SELL',
            'confidence': 95,
            'emoji': '🔴',
            'description': 'Trade AT/BELOW BID → Aggressive SELL (seller hit bid)'
        }
    elif position_in_spread > 0.7:
        # Trade closer to ask
        confidence = int(50 + (position_in_spread - 0.5) * 90)
        return {
            'direction': 'BUY',
            'confidence': confidence,
            'emoji': '🟢',
            'description': f'Trade near ASK ({position_in_spread:.0%} of spread) → Likely BUY'
        }
    elif position_in_spread < 0.3:
        # Trade closer to bid
        confidence = int(50 + (0.5 - position_in_spread) * 90)
        return {
            'direction': 'SELL',
            'confidence': confidence,
            'emoji': '🔴',
            'description': f'Trade near BID ({position_in_spread:.0%} of spread) → Likely SELL'
        }
    else:
        # Trade near midpoint - uncertain
        return {
            'direction': 'NEUTRAL',
            'confidence': 50,
            'emoji': '⚪',
            'description': f'Trade at MIDPOINT ({position_in_spread:.0%} of spread) → Direction unclear'
        }


# =============================================================================
# PART 1: Historical Trades - See what trade data looks like
# =============================================================================

def fetch_historical_trades(symbols: list[str], start_date: datetime, end_date: datetime, limit: int = 1000):
    """
    Fetch historical trades for given symbols.
    
    Each trade includes:
    - price: Trade price
    - size: Number of shares (KEY for whale detection!)
    - exchange: Exchange code where trade occurred
    - timestamp: Trade timestamp
    - conditions: List of condition codes
    - tape: A, B, or C tape
    - id: Trade ID
    """
    client = StockHistoricalDataClient(API_KEY, API_SECRET)
    
    request_params = StockTradesRequest(
        symbol_or_symbols=symbols,
        start=start_date,
        end=end_date,
        limit=limit
    )
    
    trades = client.get_stock_trades(request_params)
    return trades


def find_large_trades(symbols: list[str], start_date: datetime, end_date: datetime, 
                      min_shares: int = 10000, min_value: float = None):
    """
    Find "whale" trades - trades with large share counts or dollar values.
    Includes direction inference based on bid/ask at time of trade.
    
    Args:
        symbols: List of stock symbols to scan
        start_date: Start of time range
        end_date: End of time range
        min_shares: Minimum number of shares to qualify as a whale trade
        min_value: Minimum dollar value (price * size) to qualify
    """
    client = StockHistoricalDataClient(API_KEY, API_SECRET)
    
    # Fetch trades
    trade_request = StockTradesRequest(
        symbol_or_symbols=symbols,
        start=start_date,
        end=end_date,
        limit=10000  # Get more trades to find whales
    )
    trades = client.get_stock_trades(trade_request)
    
    # Fetch quotes for the same time period to infer direction
    quote_request = StockQuotesRequest(
        symbol_or_symbols=symbols,
        start=start_date,
        end=end_date,
        limit=10000
    )
    
    try:
        quotes = client.get_stock_quotes(quote_request)
        quotes_available = True
    except Exception as e:
        print(f"Note: Could not fetch quotes for direction inference: {e}")
        quotes_available = False
        quotes = None
    
    whale_trades = []
    
    # Build a quote lookup for faster access (closest quote before each trade)
    quote_lookup = {}
    if quotes_available and quotes:
        for symbol in symbols:
            if symbol in quotes.data:
                quote_lookup[symbol] = list(quotes.data[symbol])
    
    def find_closest_quote(symbol: str, trade_time):
        """Find the most recent quote before the trade time."""
        if symbol not in quote_lookup:
            return None, None
        
        symbol_quotes = quote_lookup[symbol]
        closest_quote = None
        
        for quote in symbol_quotes:
            if quote.timestamp <= trade_time:
                closest_quote = quote
            else:
                break  # Quotes are sorted, so we can stop
        
        if closest_quote:
            return closest_quote.bid_price, closest_quote.ask_price
        return None, None
    
    # Iterate through trades
    for symbol in symbols:
        if symbol in trades.data:
            for trade in trades.data[symbol]:
                trade_value = trade.price * trade.size
                
                is_whale = False
                if min_shares and trade.size >= min_shares:
                    is_whale = True
                if min_value and trade_value >= min_value:
                    is_whale = True
                
                if is_whale:
                    # Get quote data for direction inference
                    bid, ask = find_closest_quote(symbol, trade.timestamp)
                    direction_info = infer_trade_direction(trade.price, bid, ask)
                    
                    whale_trades.append({
                        'symbol': symbol,
                        'timestamp': trade.timestamp,
                        'price': trade.price,
                        'size': trade.size,
                        'value': trade_value,
                        'exchange': trade.exchange,
                        'conditions': trade.conditions,
                        'tape': trade.tape,
                        'bid': bid,
                        'ask': ask,
                        'direction': direction_info['direction'],
                        'direction_confidence': direction_info['confidence'],
                        'direction_emoji': direction_info['emoji'],
                        'direction_desc': direction_info['description']
                    })
    
    # Sort by value descending
    whale_trades.sort(key=lambda x: x['value'], reverse=True)
    return whale_trades


# =============================================================================
# PART 2: Real-Time Whale Alerts via WebSocket Streaming
# =============================================================================

class WhaleAlertStream:
    """
    Real-time whale alert monitor using WebSocket streaming.
    
    Monitors trades across multiple symbols and alerts when large trades occur.
    Includes direction inference based on real-time quote data.
    """
    
    def __init__(self, api_key: str, api_secret: str, 
                 min_shares: int = 10000, 
                 min_value: float = 500000):
        """
        Initialize the whale alert stream.
        
        Args:
            api_key: Alpaca API key
            api_secret: Alpaca API secret
            min_shares: Alert when trade >= this many shares
            min_value: Alert when trade value >= this dollar amount
        """
        self.stream = StockDataStream(api_key, api_secret)
        self.min_shares = min_shares
        self.min_value = min_value
        self.trade_count = 0
        self.whale_count = 0
        
        # Store latest quotes for direction inference
        self.latest_quotes = {}
    
    async def handle_quote(self, quote):
        """Store the latest quote for each symbol."""
        self.latest_quotes[quote.symbol] = {
            'bid': quote.bid_price,
            'ask': quote.ask_price,
            'timestamp': quote.timestamp
        }
    
    async def handle_trade(self, trade):
        """
        Handler for incoming trades - checks if it's a whale trade.
        """
        self.trade_count += 1
        
        trade_value = trade.price * trade.size
        
        is_whale = False
        reason = []
        
        if trade.size >= self.min_shares:
            is_whale = True
            reason.append(f"SIZE: {trade.size:,} shares")
        
        if trade_value >= self.min_value:
            is_whale = True
            reason.append(f"VALUE: ${trade_value:,.2f}")
        
        if is_whale:
            self.whale_count += 1
            
            # Get direction inference from latest quote
            quote_data = self.latest_quotes.get(trade.symbol, {})
            bid = quote_data.get('bid')
            ask = quote_data.get('ask')
            direction_info = infer_trade_direction(trade.price, bid, ask)
            
            self._print_whale_alert(trade, trade_value, reason, bid, ask, direction_info)
    
    def _print_whale_alert(self, trade, value, reasons, bid, ask, direction_info):
        """Print a formatted whale alert to the console."""
        print("\n" + "🐋" * 20)
        print(f"🚨 WHALE ALERT! 🚨")
        print("🐋" * 20)
        print(f"  Symbol:    {trade.symbol}")
        print(f"  Price:     ${trade.price:,.2f}")
        print(f"  Size:      {trade.size:,} shares")
        print(f"  Value:     ${value:,.2f}")
        print(f"  Exchange:  {trade.exchange}")
        print(f"  Time:      {trade.timestamp}")
        print(f"  Trigger:   {', '.join(reasons)}")
        print()
        print(f"  📊 DIRECTION INFERENCE:")
        if bid and ask:
            print(f"     Bid: ${bid:,.2f}  |  Ask: ${ask:,.2f}  |  Spread: ${ask-bid:.2f}")
        print(f"     {direction_info['emoji']} {direction_info['direction']} ({direction_info['confidence']}% confidence)")
        print(f"     {direction_info['description']}")
        print()
        print(f"  [Whale #{self.whale_count} | Total trades seen: {self.trade_count:,}]")
        print("🐋" * 20 + "\n")
    
    def subscribe(self, symbols: list[str]):
        """
        Subscribe to trades AND quotes for the given symbols.
        
        Args:
            symbols: List of symbols to monitor (e.g., ['AAPL', 'TSLA', 'SPY'])
                     Use ['*'] to subscribe to ALL symbols (requires appropriate subscription)
        """
        # Subscribe to both trades and quotes
        self.stream.subscribe_trades(self.handle_trade, *symbols)
        self.stream.subscribe_quotes(self.handle_quote, *symbols)
    
    def run(self):
        """Start the streaming connection."""
        print("\n" + "=" * 60)
        print("🐋 WHALE ALERT MONITOR STARTED 🐋")
        print("=" * 60)
        print(f"Thresholds:")
        print(f"  - Min shares: {self.min_shares:,}")
        print(f"  - Min value:  ${self.min_value:,.2f}")
        print("=" * 60)
        print("Listening for trades... (Press Ctrl+C to stop)\n")
        
        self.stream.run()


# =============================================================================
# MAIN - Demo both historical and real-time
# =============================================================================

def demo_historical_trades():
    """Demonstrate fetching historical trade data."""
    print("\n" + "=" * 60)
    print("HISTORICAL TRADES DEMO")
    print("=" * 60)
    
    # Fetch recent trades
    end_date = datetime.now()
    start_date = end_date - timedelta(hours=LOOKBACK_HOURS_TRADES)
    
    symbols = SYMBOLS_HISTORICAL
    
    print(f"\nFetching trades for {symbols}")
    print(f"Time range: {start_date.strftime('%Y-%m-%d %H:%M')} to {end_date.strftime('%Y-%m-%d %H:%M')}")
    
    try:
        trades = fetch_historical_trades(symbols, start_date, end_date, limit=100)
        
        # Show sample trades
        print("\n--- Sample Trades (first 10 per symbol) ---")
        for symbol in symbols:
            if symbol in trades.data:
                print(f"\n{symbol}:")
                for i, trade in enumerate(trades.data[symbol][:10]):
                    print(f"  {trade.timestamp} | ${trade.price:.2f} | {trade.size:,} shares | {trade.exchange}")
        
        # Convert to DataFrame for easier viewing
        df = trades.df
        print(f"\n--- Trade DataFrame ---")
        print(f"Total trades fetched: {len(df)}")
        print(f"\nColumns available: {list(df.columns)}")
        print(f"\nSample data:")
        print(df.head(20))
        
    except Exception as e:
        print(f"Error fetching trades: {e}")
        print("Note: Trade data might not be available outside market hours for recent times.")


def demo_whale_finder():
    """Demonstrate finding whale trades in historical data - loops through all tickers."""
    print("\n" + "=" * 60)
    print("WHALE FINDER - Historical Large Trades")
    print("=" * 60)
    
    # Look back further to find whale trades
    end_date = datetime.now()
    start_date = end_date - timedelta(days=LOOKBACK_DAYS_WHALE_FINDER)
    
    symbols = SYMBOLS_WHALE_FINDER
    
    # Use thresholds from config
    MIN_SHARES = MIN_SHARES_WHALE_FINDER
    MIN_VALUE = MIN_VALUE_WHALE_FINDER
    
    print(f"\nSearching for whale trades...")
    print(f"Symbols: {symbols}")
    print(f"Time range: {start_date.strftime('%Y-%m-%d %H:%M')} to {end_date.strftime('%Y-%m-%d %H:%M')}")
    print(f"Whale threshold: >= {MIN_SHARES:,} shares OR >= ${MIN_VALUE:,.0f} value")
    
    # Collect all whales from all tickers
    all_whales = []
    whales_by_ticker = {}
    
    try:
        # Loop through each ticker individually
        for symbol in symbols:
            print(f"\n   Scanning {symbol}...", end=" ", flush=True)
            
            try:
                ticker_whales = find_large_trades(
                    [symbol],  # One ticker at a time
                    start_date, 
                    end_date, 
                    min_shares=MIN_SHARES, 
                    min_value=MIN_VALUE
                )
                
                whales_by_ticker[symbol] = ticker_whales
                all_whales.extend(ticker_whales)
                print(f"found {len(ticker_whales)} whale trades")
                
            except Exception as e:
                print(f"error: {e}")
                whales_by_ticker[symbol] = []
        
        # Sort all whales by value
        all_whales.sort(key=lambda x: x['value'], reverse=True)
        
        if all_whales:
            print(f"\n🐋 Found {len(all_whales)} whale trades across all tickers!")
            
            # =================================================================
            # DIRECTION SUMMARY BY TICKER
            # =================================================================
            print("\n" + "=" * 100)
            print("📊 DIRECTION SUMMARY BY TICKER")
            print("=" * 100)
            print(f"{'Ticker':<8} {'🟢 Buys':>8} {'Buy Value':>16} {'🔴 Sells':>8} {'Sell Value':>16} {'Net Flow':>18} {'Sentiment':<12}")
            print("-" * 100)
            
            ticker_summaries = []
            for symbol in symbols:
                ticker_whales = whales_by_ticker.get(symbol, [])
                if not ticker_whales:
                    continue
                    
                buys = [w for w in ticker_whales if w['direction'] == 'BUY']
                sells = [w for w in ticker_whales if w['direction'] == 'SELL']
                
                buy_value = sum(w['value'] for w in buys)
                sell_value = sum(w['value'] for w in sells)
                net_flow = buy_value - sell_value
                
                # High confidence only
                hc_buys = [w for w in buys if w['direction_confidence'] >= 80]
                hc_sells = [w for w in sells if w['direction_confidence'] >= 80]
                hc_buy_value = sum(w['value'] for w in hc_buys)
                hc_sell_value = sum(w['value'] for w in hc_sells)
                hc_net = hc_buy_value - hc_sell_value
                
                if hc_net > 0:
                    sentiment = "🟢 BULLISH"
                elif hc_net < 0:
                    sentiment = "🔴 BEARISH"
                else:
                    sentiment = "⚪ NEUTRAL"
                
                ticker_summaries.append({
                    'symbol': symbol,
                    'buy_count': len(buys),
                    'sell_count': len(sells),
                    'buy_value': buy_value,
                    'sell_value': sell_value,
                    'net_flow': net_flow,
                    'hc_net': hc_net,
                    'sentiment': sentiment
                })
                
                net_str = f"+${net_flow:,.0f}" if net_flow >= 0 else f"-${abs(net_flow):,.0f}"
                print(f"{symbol:<8} {len(buys):>8} ${buy_value:>14,.0f} {len(sells):>8} ${sell_value:>14,.0f} {net_str:>18} {sentiment:<12}")
            
            # =================================================================
            # OVERALL DIRECTION SUMMARY
            # =================================================================
            buys = [w for w in all_whales if w['direction'] == 'BUY']
            sells = [w for w in all_whales if w['direction'] == 'SELL']
            neutral = [w for w in all_whales if w['direction'] in ('NEUTRAL', 'UNKNOWN')]
            
            buy_value = sum(w['value'] for w in buys)
            sell_value = sum(w['value'] for w in sells)
            
            avg_buy_conf = sum(w['direction_confidence'] for w in buys) / len(buys) if buys else 0
            avg_sell_conf = sum(w['direction_confidence'] for w in sells) / len(sells) if sells else 0
            
            high_conf_buys = [w for w in buys if w['direction_confidence'] >= 80]
            high_conf_sells = [w for w in sells if w['direction_confidence'] >= 80]
            high_conf_buy_value = sum(w['value'] for w in high_conf_buys)
            high_conf_sell_value = sum(w['value'] for w in high_conf_sells)
            
            print("\n" + "=" * 100)
            print("📊 OVERALL DIRECTION SUMMARY (All Tickers Combined)")
            print("=" * 100)
            print(f"   🟢 Likely BUYS:  {len(buys):>4} trades  |  ${buy_value:>15,.2f} total value  |  Avg confidence: {avg_buy_conf:.0f}%")
            print(f"   🔴 Likely SELLS: {len(sells):>4} trades  |  ${sell_value:>15,.2f} total value  |  Avg confidence: {avg_sell_conf:.0f}%")
            print(f"   ⚪ Neutral/Unknown: {len(neutral)} trades")
            
            print(f"\n   🎯 HIGH CONFIDENCE trades (≥80% confidence):")
            print(f"      🟢 Strong BUYS:  {len(high_conf_buys):>3} trades  |  ${high_conf_buy_value:>15,.2f}")
            print(f"      🔴 Strong SELLS: {len(high_conf_sells):>3} trades  |  ${high_conf_sell_value:>15,.2f}")
            
            if high_conf_buy_value > high_conf_sell_value:
                net_diff = high_conf_buy_value - high_conf_sell_value
                print(f"\n   ➡️  Net sentiment (high-conf): BULLISH 🟢 (${net_diff:,.2f} more buying)")
            elif high_conf_sell_value > high_conf_buy_value:
                net_diff = high_conf_sell_value - high_conf_buy_value
                print(f"\n   ➡️  Net sentiment (high-conf): BEARISH 🔴 (${net_diff:,.2f} more selling)")
            else:
                print(f"\n   ➡️  Net sentiment (high-conf): NEUTRAL ⚪")
            
            # =================================================================
            # DARK POOL ANALYSIS 🌑
            # =================================================================
            dark_pool_whales = [w for w in all_whales if w['exchange'] == 'D']
            lit_exchange_whales = [w for w in all_whales if w['exchange'] != 'D']
            
            if dark_pool_whales:
                dp_buys = [w for w in dark_pool_whales if w['direction'] == 'BUY']
                dp_sells = [w for w in dark_pool_whales if w['direction'] == 'SELL']
                dp_buy_value = sum(w['value'] for w in dp_buys)
                dp_sell_value = sum(w['value'] for w in dp_sells)
                dp_total_value = sum(w['value'] for w in dark_pool_whales)
                lit_total_value = sum(w['value'] for w in lit_exchange_whales)
                
                print("\n" + "=" * 100)
                print("🌑 DARK POOL ANALYSIS (Exchange D = FINRA ADF / Off-Exchange)")
                print("=" * 100)
                print(f"   Dark pool trades are typically INSTITUTIONAL block trades!")
                print(f"   They execute off-exchange to minimize market impact.\n")
                
                print(f"   🌑 DARK POOL:     {len(dark_pool_whales):>3} trades  |  ${dp_total_value:>15,.2f}  ({dp_total_value/(dp_total_value+lit_total_value)*100:.1f}% of whale volume)")
                print(f"   💡 LIT EXCHANGES: {len(lit_exchange_whales):>3} trades  |  ${lit_total_value:>15,.2f}  ({lit_total_value/(dp_total_value+lit_total_value)*100:.1f}% of whale volume)")
                
                print(f"\n   🌑 Dark Pool Direction:")
                print(f"      🟢 Institutional BUYS:  {len(dp_buys):>3} trades  |  ${dp_buy_value:>15,.2f}")
                print(f"      🔴 Institutional SELLS: {len(dp_sells):>3} trades  |  ${dp_sell_value:>15,.2f}")
                
                if dp_buy_value > dp_sell_value:
                    dp_net = dp_buy_value - dp_sell_value
                    print(f"\n   ➡️  Dark Pool sentiment: BULLISH 🟢 (${dp_net:,.2f} net institutional buying)")
                elif dp_sell_value > dp_buy_value:
                    dp_net = dp_sell_value - dp_buy_value
                    print(f"\n   ➡️  Dark Pool sentiment: BEARISH 🔴 (${dp_net:,.2f} net institutional selling)")
                else:
                    print(f"\n   ➡️  Dark Pool sentiment: NEUTRAL ⚪")
                
                # Dark pool trades by ticker
                dp_by_ticker = {}
                for w in dark_pool_whales:
                    sym = w['symbol']
                    if sym not in dp_by_ticker:
                        dp_by_ticker[sym] = {'buys': 0, 'sells': 0, 'buy_val': 0, 'sell_val': 0}
                    if w['direction'] == 'BUY':
                        dp_by_ticker[sym]['buys'] += 1
                        dp_by_ticker[sym]['buy_val'] += w['value']
                    elif w['direction'] == 'SELL':
                        dp_by_ticker[sym]['sells'] += 1
                        dp_by_ticker[sym]['sell_val'] += w['value']
                
                print(f"\n   🌑 Dark Pool by Ticker:")
                for sym, data in sorted(dp_by_ticker.items(), key=lambda x: x[1]['buy_val']+x[1]['sell_val'], reverse=True):
                    net = data['buy_val'] - data['sell_val']
                    emoji = "🟢" if net > 0 else "🔴" if net < 0 else "⚪"
                    net_str = f"+${net:,.0f}" if net >= 0 else f"-${abs(net):,.0f}"
                    print(f"      {sym:<6} {emoji} {data['buys']} buys (${data['buy_val']:>12,.0f}) | {data['sells']} sells (${data['sell_val']:>12,.0f}) | Net: {net_str}")
            
            # =================================================================
            # TOP 5 WHALE TRADES (DETAILED)
            # =================================================================
            print("\n" + "=" * 100)
            print("🐋 TOP 5 WHALE TRADES BY VALUE (Detailed)")
            print("=" * 100)
            
            # Exchange name lookup
            exchange_names = {
                'A': 'NYSE American', 'B': 'NASDAQ BX', 'C': 'NSX', 'D': '🌑 DARK POOL',
                'H': 'MIAX', 'J': 'Cboe EDGA', 'K': 'Cboe EDGX', 'M': 'CHX',
                'N': 'NYSE', 'P': 'NYSE Arca', 'Q': 'NASDAQ', 'U': 'MEMX',
                'V': 'IEX', 'W': 'CBOE', 'X': 'NASDAQ PSX', 'Y': 'Cboe BYX', 'Z': 'Cboe BZX',
            }
            
            for i, whale in enumerate(all_whales[:5], 1):
                is_dark_pool = whale['exchange'] == 'D'
                dp_marker = " 🌑 DARK POOL - INSTITUTIONAL" if is_dark_pool else ""
                
                print(f"\n#{i} {whale['direction_emoji']} {whale['symbol']}{dp_marker}")
                print(f"   Price:     ${whale['price']:,.2f}")
                print(f"   Size:      {whale['size']:,} shares")
                print(f"   Value:     ${whale['value']:,.2f}")
                print(f"   Time:      {whale['timestamp']}")
                ex_name = exchange_names.get(whale['exchange'], whale['exchange'])
                print(f"   Exchange:  {whale['exchange']} ({ex_name})")
                if whale['bid'] and whale['ask']:
                    print(f"   Quote:     Bid ${whale['bid']:,.2f} | Ask ${whale['ask']:,.2f}")
                print(f"   Direction: {whale['direction']} ({whale['direction_confidence']}% confidence)")
                print(f"   Analysis:  {whale['direction_desc']}")
            
            # =================================================================
            # TOP 20 WHALE TRADES (TABLE)
            # =================================================================
            print("\n" + "=" * 130)
            print("🐋 TOP 20 WHALE TRADES BY VALUE (🌑 = Dark Pool / Institutional)")
            print("=" * 130)
            print(f"{'#':<4} {'Pool':<5} {'Dir':<4} {'Symbol':<8} {'Price':>12} {'Shares':>12} {'Value':>15} {'Bid':>10} {'Ask':>10} {'Conf':<6}")
            print("-" * 130)
            
            for i, whale in enumerate(all_whales[:20], 1):
                bid_str = f"${whale['bid']:,.2f}" if whale['bid'] else "N/A"
                ask_str = f"${whale['ask']:,.2f}" if whale['ask'] else "N/A"
                conf_str = f"{whale['direction_confidence']}%"
                pool_marker = "🌑" if whale['exchange'] == 'D' else "  "
                
                print(f"{i:<4} {pool_marker:<5} {whale['direction_emoji']:<4} {whale['symbol']:<8} "
                      f"${whale['price']:>10,.2f} {whale['size']:>11,} "
                      f"${whale['value']:>14,.2f} {bid_str:>10} {ask_str:>10} {conf_str:<6}")
            
            # =================================================================
            # CONFIDENCE METHODOLOGY
            # =================================================================
            print(f"\n   📐 Confidence Calculation Method:")
            print(f"      • Trade at/above ASK  → 95% BUY  (aggressive buyer paid up)")
            print(f"      • Trade at/below BID  → 95% SELL (aggressive seller hit bid)")
            print(f"      • Trade near ASK (70-99% of spread) → 50-95% BUY")
            print(f"      • Trade near BID (1-30% of spread)  → 50-95% SELL")
            print(f"      • Trade at midpoint (30-70%)        → 50% NEUTRAL")
            
        else:
            print("\nNo whale trades found with current thresholds.")
            print("Try lowering MIN_SHARES or MIN_VALUE, or extending the time range.")
            
    except Exception as e:
        print(f"Error finding whales: {e}")
        import traceback
        traceback.print_exc()


def run_live_whale_alerts():
    """Start the real-time whale alert monitor."""
    print("\n" + "=" * 60)
    print("REAL-TIME WHALE ALERT MONITOR")
    print("=" * 60)
    
    # Use thresholds from config
    MIN_SHARES = MIN_SHARES_LIVE
    MIN_VALUE = MIN_VALUE_LIVE
    
    # Use symbols from config
    symbols = SYMBOLS_LIVE_STREAM
    
    print(f"\nMonitoring symbols: {symbols}")
    print(f"Whale thresholds: {MIN_SHARES:,} shares OR ${MIN_VALUE:,.0f}")
    print("\n⚠️  Note: Real-time streaming requires market hours!")
    print("    Market hours: 9:30 AM - 4:00 PM ET, Mon-Fri")
    
    whale_monitor = WhaleAlertStream(
        API_KEY, 
        API_SECRET,
        min_shares=MIN_SHARES,
        min_value=MIN_VALUE
    )
    
    whale_monitor.subscribe(symbols)
    whale_monitor.run()


def main():
    """Main menu for whale alert demos."""
    print("\n" + "🐋" * 25)
    print("   ALPACA WHALE ALERT SYSTEM")
    print("🐋" * 25)
    
    print("""
Choose a demo:

1. Historical Trades - See what trade data looks like
2. Whale Finder - Find large trades in recent history
3. Live Whale Alerts - Real-time monitoring (requires market hours)
4. Run All Demos (1 & 2, skip live)

Enter choice (1-4): """, end="")
    
    try:
        choice = input().strip()
    except:
        choice = "4"  # Default if running non-interactively
    
    if choice == "1":
        demo_historical_trades()
    elif choice == "2":
        demo_whale_finder()
    elif choice == "3":
        run_live_whale_alerts()
    elif choice == "4":
        demo_historical_trades()
        demo_whale_finder()
    else:
        print("Invalid choice. Running demos 1 & 2...")
        demo_historical_trades()
        demo_whale_finder()
    
    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
