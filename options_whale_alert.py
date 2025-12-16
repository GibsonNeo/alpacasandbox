"""
Options Whale Alert - Monitor for Large Options Trades

This script finds "whale" options trades - large premium bets that can signal
institutional activity or unusual market conviction.

Features:
1. Big premium detection ($100K+ options trades)
2. Call vs Put analysis (bullish vs bearish sentiment)
3. ITM vs OTM analysis (conviction level)
4. Notional exposure calculation
5. Sweep detection (aggressive buying across strikes)
6. Summary by underlying and sentiment

Option Symbol Format: AAPL251219C00275000
- AAPL = underlying
- 251219 = expiration (Dec 19, 2025)
- C = Call (P = Put)
- 00275000 = strike price $275.00 (divide by 1000)
"""

import os
import re
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from collections import defaultdict

# Load environment variables
load_dotenv()

API_KEY = os.getenv('APCA-API-KEY-ID')
API_SECRET = os.getenv('APCA-API-SECRET-KEY')

# =============================================================================
# CONFIGURATION - Edit these to customize your options whale alerts!
# =============================================================================

# Underlying stocks to scan for options activity
UNDERLYINGS = ['AAPL', 'TSLA', 'NVDA', 'SPY', 'QQQ', 'MSFT', 'AMZN', 'META', 'AMD', 'GOOGL']

# Whale thresholds
MIN_PREMIUM_VALUE = 50000       # Minimum premium paid ($) to qualify as whale
MIN_CONTRACTS = 100             # Minimum contracts to qualify as whale
MIN_NOTIONAL_VALUE = 500000     # Minimum notional exposure ($) to qualify

# Lookback period
LOOKBACK_DAYS = 1               # Days to look back for trades

# Sweep detection
SWEEP_TIME_WINDOW = 60          # Seconds - trades within this window may be a sweep
SWEEP_MIN_LEGS = 3              # Minimum number of trades to qualify as sweep

# =============================================================================


def parse_option_symbol(symbol: str) -> dict:
    """
    Parse an OCC option symbol into its components.
    
    Format: AAPL251219C00275000
    - Underlying: AAPL
    - Expiration: 2025-12-19
    - Type: C (Call) or P (Put)
    - Strike: $275.00
    """
    # OCC format: up to 6 char underlying + 6 digit date + C/P + 8 digit strike
    pattern = r'^([A-Z]{1,6})(\d{6})([CP])(\d{8})$'
    match = re.match(pattern, symbol)
    
    if not match:
        return None
    
    underlying, date_str, opt_type, strike_str = match.groups()
    
    # Parse expiration date (YYMMDD)
    try:
        expiration = datetime.strptime(date_str, '%y%m%d')
    except:
        expiration = None
    
    # Parse strike (divide by 1000, last 3 digits are decimals)
    strike = int(strike_str) / 1000
    
    return {
        'underlying': underlying,
        'expiration': expiration,
        'expiration_str': expiration.strftime('%Y-%m-%d') if expiration else date_str,
        'type': 'CALL' if opt_type == 'C' else 'PUT',
        'type_code': opt_type,
        'strike': strike,
        'symbol': symbol
    }


def get_option_chain(underlying: str, limit: int = 100) -> dict:
    """Fetch the option chain for an underlying stock."""
    headers = {
        'APCA-API-KEY-ID': API_KEY,
        'APCA-API-SECRET-KEY': API_SECRET
    }
    
    url = f'https://data.alpaca.markets/v1beta1/options/snapshots/{underlying}'
    params = {'feed': 'indicative', 'limit': limit}
    
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code == 200:
        return response.json().get('snapshots', {})
    else:
        print(f"Error fetching option chain for {underlying}: {response.status_code}")
        return {}


def get_option_trades(symbols: list, start_date: datetime, end_date: datetime = None) -> dict:
    """Fetch historical trades for option contracts."""
    headers = {
        'APCA-API-KEY-ID': API_KEY,
        'APCA-API-SECRET-KEY': API_SECRET
    }
    
    url = 'https://data.alpaca.markets/v1beta1/options/trades'
    
    params = {
        'symbols': ','.join(symbols[:100]),  # API limit of 100 symbols
        'start': start_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'limit': 10000,
        'sort': 'desc'
    }
    
    if end_date:
        params['end'] = end_date.strftime('%Y-%m-%dT%H:%M:%SZ')
    
    all_trades = {}
    
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code == 200:
        data = response.json()
        all_trades = data.get('trades', {})
    else:
        print(f"Error fetching trades: {response.status_code} - {response.text}")
    
    return all_trades


def get_stock_price(symbol: str) -> float:
    """Get current stock price for notional calculations."""
    headers = {
        'APCA-API-KEY-ID': API_KEY,
        'APCA-API-SECRET-KEY': API_SECRET
    }
    
    url = f'https://data.alpaca.markets/v2/stocks/{symbol}/trades/latest'
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        return response.json().get('trade', {}).get('p', 0)
    return 0


def find_options_whales(underlyings: list, start_date: datetime, 
                        min_premium: float = 50000, 
                        min_contracts: int = 100,
                        min_notional: float = 500000) -> list:
    """
    Find whale options trades across multiple underlyings.
    
    Returns list of whale trades with analysis.
    """
    all_whales = []
    
    for underlying in underlyings:
        print(f"   Scanning {underlying} options...", end=" ", flush=True)
        
        try:
            # Get option chain to find active contracts
            chain = get_option_chain(underlying, limit=500)
            
            if not chain:
                print("no chain data")
                continue
            
            # Get contracts that have had trades
            contracts = list(chain.keys())
            
            if not contracts:
                print("no contracts")
                continue
            
            # Fetch trades for these contracts (in batches of 100)
            contract_trades = {}
            for i in range(0, len(contracts), 100):
                batch = contracts[i:i+100]
                trades = get_option_trades(batch, start_date)
                contract_trades.update(trades)
            
            # Get current stock price for ITM/OTM analysis
            stock_price = get_stock_price(underlying)
            
            # Analyze each trade
            whale_count = 0
            for contract_symbol, trades in contract_trades.items():
                parsed = parse_option_symbol(contract_symbol)
                if not parsed:
                    continue
                
                for trade in trades:
                    size = trade.get('s', 0)
                    price = trade.get('p', 0)
                    timestamp = trade.get('t', '')
                    exchange = trade.get('x', '')
                    
                    # Calculate values
                    premium_value = size * price * 100  # Options are 100 shares
                    notional_value = size * parsed['strike'] * 100
                    
                    # Check if it's a whale
                    is_whale = False
                    if premium_value >= min_premium:
                        is_whale = True
                    if size >= min_contracts:
                        is_whale = True
                    if notional_value >= min_notional:
                        is_whale = True
                    
                    if is_whale:
                        whale_count += 1
                        
                        # Calculate days to expiration
                        if parsed['expiration']:
                            dte = (parsed['expiration'] - datetime.now()).days
                        else:
                            dte = None
                        
                        # Determine ITM/OTM/ATM
                        if stock_price > 0:
                            if parsed['type'] == 'CALL':
                                moneyness = (stock_price - parsed['strike']) / stock_price * 100
                                if moneyness > 2:
                                    itm_status = 'ITM'
                                elif moneyness < -2:
                                    itm_status = 'OTM'
                                else:
                                    itm_status = 'ATM'
                            else:  # PUT
                                moneyness = (parsed['strike'] - stock_price) / stock_price * 100
                                if moneyness > 2:
                                    itm_status = 'ITM'
                                elif moneyness < -2:
                                    itm_status = 'OTM'
                                else:
                                    itm_status = 'ATM'
                        else:
                            itm_status = 'N/A'
                            moneyness = 0
                        
                        # Sentiment
                        if parsed['type'] == 'CALL':
                            sentiment = 'BULLISH'
                            sentiment_emoji = '🟢'
                        else:
                            sentiment = 'BEARISH'
                            sentiment_emoji = '🔴'
                        
                        all_whales.append({
                            'underlying': underlying,
                            'contract': contract_symbol,
                            'type': parsed['type'],
                            'strike': parsed['strike'],
                            'expiration': parsed['expiration_str'],
                            'dte': dte,
                            'timestamp': timestamp,
                            'contracts': size,
                            'price': price,
                            'premium_value': premium_value,
                            'notional_value': notional_value,
                            'exchange': exchange,
                            'stock_price': stock_price,
                            'itm_status': itm_status,
                            'moneyness': moneyness,
                            'sentiment': sentiment,
                            'sentiment_emoji': sentiment_emoji
                        })
            
            print(f"found {whale_count} whale trades")
            
        except Exception as e:
            print(f"error: {e}")
    
    # Sort by premium value
    all_whales.sort(key=lambda x: x['premium_value'], reverse=True)
    return all_whales


def detect_sweeps(whales: list, time_window: int = 60, min_legs: int = 3) -> list:
    """
    Detect potential sweep orders - multiple rapid trades on same underlying.
    
    A sweep is when someone aggressively buys/sells across multiple strikes
    or exchanges in rapid succession, often to fill a large order quickly.
    """
    sweeps = []
    
    # Group by underlying
    by_underlying = defaultdict(list)
    for w in whales:
        by_underlying[w['underlying']].append(w)
    
    for underlying, trades in by_underlying.items():
        # Sort by timestamp
        trades.sort(key=lambda x: x['timestamp'])
        
        # Look for clusters of trades
        i = 0
        while i < len(trades):
            cluster = [trades[i]]
            
            # Parse timestamp of first trade
            try:
                t1 = datetime.fromisoformat(trades[i]['timestamp'].replace('Z', '+00:00'))
            except:
                i += 1
                continue
            
            # Find all trades within time window
            j = i + 1
            while j < len(trades):
                try:
                    t2 = datetime.fromisoformat(trades[j]['timestamp'].replace('Z', '+00:00'))
                    if (t2 - t1).total_seconds() <= time_window:
                        cluster.append(trades[j])
                        j += 1
                    else:
                        break
                except:
                    j += 1
                    break
            
            # Check if this cluster qualifies as a sweep
            if len(cluster) >= min_legs:
                # Calculate totals
                total_premium = sum(t['premium_value'] for t in cluster)
                total_contracts = sum(t['contracts'] for t in cluster)
                strikes = list(set(t['strike'] for t in cluster))
                types = list(set(t['type'] for t in cluster))
                
                sweeps.append({
                    'underlying': underlying,
                    'legs': len(cluster),
                    'trades': cluster,
                    'total_premium': total_premium,
                    'total_contracts': total_contracts,
                    'strikes': strikes,
                    'types': types,
                    'start_time': cluster[0]['timestamp'],
                    'end_time': cluster[-1]['timestamp'],
                    'sentiment': cluster[0]['sentiment'],
                    'sentiment_emoji': cluster[0]['sentiment_emoji']
                })
            
            i = j if j > i + 1 else i + 1
    
    # Sort by total premium
    sweeps.sort(key=lambda x: x['total_premium'], reverse=True)
    return sweeps


def print_whale_summary(whales: list):
    """Print summary analysis of whale trades."""
    
    if not whales:
        print("\nNo whale trades found with current thresholds.")
        return
    
    print(f"\n🐋 Found {len(whales)} whale options trades!")
    
    # =================================================================
    # SENTIMENT SUMMARY
    # =================================================================
    calls = [w for w in whales if w['type'] == 'CALL']
    puts = [w for w in whales if w['type'] == 'PUT']
    
    call_premium = sum(w['premium_value'] for w in calls)
    put_premium = sum(w['premium_value'] for w in puts)
    
    print("\n" + "=" * 100)
    print("📊 OPTIONS FLOW SENTIMENT")
    print("=" * 100)
    print(f"   🟢 CALLS (Bullish): {len(calls):>4} trades  |  ${call_premium:>15,.2f} premium")
    print(f"   🔴 PUTS (Bearish):  {len(puts):>4} trades  |  ${put_premium:>15,.2f} premium")
    
    if call_premium > put_premium:
        ratio = call_premium / put_premium if put_premium > 0 else float('inf')
        print(f"\n   ➡️  Net sentiment: BULLISH 🟢 (${call_premium - put_premium:,.2f} more in calls)")
        print(f"       Call/Put Premium Ratio: {ratio:.2f}x")
    elif put_premium > call_premium:
        ratio = put_premium / call_premium if call_premium > 0 else float('inf')
        print(f"\n   ➡️  Net sentiment: BEARISH 🔴 (${put_premium - call_premium:,.2f} more in puts)")
        print(f"       Put/Call Premium Ratio: {ratio:.2f}x")
    else:
        print(f"\n   ➡️  Net sentiment: NEUTRAL ⚪")
    
    # =================================================================
    # SUMMARY BY UNDERLYING
    # =================================================================
    print("\n" + "=" * 100)
    print("📊 FLOW BY UNDERLYING")
    print("=" * 100)
    print(f"{'Ticker':<8} {'🟢 Calls':>8} {'Call Premium':>16} {'🔴 Puts':>8} {'Put Premium':>16} {'Net Flow':>18} {'Sentiment':<12}")
    print("-" * 100)
    
    by_underlying = defaultdict(lambda: {'calls': 0, 'puts': 0, 'call_prem': 0, 'put_prem': 0})
    for w in whales:
        u = w['underlying']
        if w['type'] == 'CALL':
            by_underlying[u]['calls'] += 1
            by_underlying[u]['call_prem'] += w['premium_value']
        else:
            by_underlying[u]['puts'] += 1
            by_underlying[u]['put_prem'] += w['premium_value']
    
    for underlying in sorted(by_underlying.keys(), key=lambda x: by_underlying[x]['call_prem'] + by_underlying[x]['put_prem'], reverse=True):
        data = by_underlying[underlying]
        net = data['call_prem'] - data['put_prem']
        net_str = f"+${net:,.0f}" if net >= 0 else f"-${abs(net):,.0f}"
        sentiment = "🟢 BULLISH" if net > 0 else "🔴 BEARISH" if net < 0 else "⚪ NEUTRAL"
        
        print(f"{underlying:<8} {data['calls']:>8} ${data['call_prem']:>14,.0f} {data['puts']:>8} ${data['put_prem']:>14,.0f} {net_str:>18} {sentiment:<12}")
    
    # =================================================================
    # EXPIRATION ANALYSIS
    # =================================================================
    print("\n" + "=" * 100)
    print("📅 EXPIRATION ANALYSIS")
    print("=" * 100)
    
    # Group by DTE buckets
    dte_buckets = {'0-7 days': [], '8-30 days': [], '31-90 days': [], '90+ days': []}
    for w in whales:
        dte = w['dte']
        if dte is None:
            continue
        elif dte <= 7:
            dte_buckets['0-7 days'].append(w)
        elif dte <= 30:
            dte_buckets['8-30 days'].append(w)
        elif dte <= 90:
            dte_buckets['31-90 days'].append(w)
        else:
            dte_buckets['90+ days'].append(w)
    
    print(f"   ⚡ Short-term (0-7 days):   {len(dte_buckets['0-7 days']):>3} trades  |  ${sum(w['premium_value'] for w in dte_buckets['0-7 days']):>12,.0f}  (AGGRESSIVE BETS)")
    print(f"   📆 Near-term (8-30 days):  {len(dte_buckets['8-30 days']):>3} trades  |  ${sum(w['premium_value'] for w in dte_buckets['8-30 days']):>12,.0f}")
    print(f"   📅 Medium-term (31-90):    {len(dte_buckets['31-90 days']):>3} trades  |  ${sum(w['premium_value'] for w in dte_buckets['31-90 days']):>12,.0f}")
    print(f"   🗓️  Long-term (90+ days):   {len(dte_buckets['90+ days']):>3} trades  |  ${sum(w['premium_value'] for w in dte_buckets['90+ days']):>12,.0f}  (LEAPS)")
    
    # =================================================================
    # ITM/OTM ANALYSIS  
    # =================================================================
    print("\n" + "=" * 100)
    print("💰 MONEYNESS ANALYSIS")
    print("=" * 100)
    
    itm = [w for w in whales if w['itm_status'] == 'ITM']
    atm = [w for w in whales if w['itm_status'] == 'ATM']
    otm = [w for w in whales if w['itm_status'] == 'OTM']
    
    print(f"   💵 ITM (In The Money):   {len(itm):>3} trades  |  ${sum(w['premium_value'] for w in itm):>12,.0f}  (Higher conviction)")
    print(f"   🎯 ATM (At The Money):   {len(atm):>3} trades  |  ${sum(w['premium_value'] for w in atm):>12,.0f}  (Balanced risk/reward)")
    print(f"   🎰 OTM (Out The Money):  {len(otm):>3} trades  |  ${sum(w['premium_value'] for w in otm):>12,.0f}  (Lottery tickets)")


def print_top_trades(whales: list, top_n: int = 20):
    """Print the top whale trades."""
    
    if not whales:
        return
    
    # =================================================================
    # TOP 5 DETAILED
    # =================================================================
    print("\n" + "=" * 100)
    print(f"🐋 TOP 5 OPTIONS WHALE TRADES (Detailed)")
    print("=" * 100)
    
    for i, w in enumerate(whales[:5], 1):
        dte_str = f"{w['dte']} days" if w['dte'] is not None else "N/A"
        
        print(f"\n#{i} {w['sentiment_emoji']} {w['underlying']} {w['strike']} {w['type']} exp {w['expiration']}")
        print(f"   Contract:  {w['contract']}")
        print(f"   Size:      {w['contracts']:,} contracts")
        print(f"   Price:     ${w['price']:.2f} per contract")
        print(f"   Premium:   ${w['premium_value']:,.2f}")
        print(f"   Notional:  ${w['notional_value']:,.2f} (controls this much stock)")
        print(f"   DTE:       {dte_str}")
        print(f"   Stock:     ${w['stock_price']:.2f} ({w['itm_status']}, {w['moneyness']:.1f}% from strike)")
        print(f"   Sentiment: {w['sentiment']} {w['sentiment_emoji']}")
        print(f"   Time:      {w['timestamp']}")
    
    # =================================================================
    # TOP 20 TABLE
    # =================================================================
    print("\n" + "=" * 140)
    print(f"🐋 TOP {top_n} OPTIONS WHALE TRADES")
    print("=" * 140)
    print(f"{'#':<3} {'Dir':<4} {'Ticker':<6} {'Strike':>8} {'Type':<5} {'Exp':<12} {'DTE':>5} {'Contracts':>10} {'Price':>8} {'Premium':>14} {'ITM':>5}")
    print("-" * 140)
    
    for i, w in enumerate(whales[:top_n], 1):
        dte_str = str(w['dte']) if w['dte'] is not None else "N/A"
        print(f"{i:<3} {w['sentiment_emoji']:<4} {w['underlying']:<6} ${w['strike']:>6,.0f} {w['type']:<5} {w['expiration']:<12} {dte_str:>5} {w['contracts']:>10,} ${w['price']:>6.2f} ${w['premium_value']:>12,.0f} {w['itm_status']:>5}")


def print_sweeps(sweeps: list):
    """Print detected sweep orders."""
    
    if not sweeps:
        print("\n" + "=" * 100)
        print("🌊 SWEEP DETECTION")
        print("=" * 100)
        print("   No sweep orders detected with current thresholds.")
        return
    
    print("\n" + "=" * 100)
    print(f"🌊 SWEEP DETECTION - {len(sweeps)} potential sweeps found!")
    print("=" * 100)
    print("   Sweeps = rapid consecutive trades, often filling large orders aggressively")
    
    for i, sweep in enumerate(sweeps[:10], 1):
        types_str = '/'.join(sweep['types'])
        strikes_str = ', '.join([f"${s:.0f}" for s in sorted(sweep['strikes'])])
        
        print(f"\n   #{i} {sweep['sentiment_emoji']} {sweep['underlying']} - {sweep['legs']} legs")
        print(f"      Total Premium: ${sweep['total_premium']:,.2f}")
        print(f"      Total Contracts: {sweep['total_contracts']:,}")
        print(f"      Types: {types_str}")
        print(f"      Strikes: {strikes_str}")
        print(f"      Time: {sweep['start_time'][:19]} → {sweep['end_time'][:19]}")


def demo_options_whale_finder():
    """Main demo function for options whale finder."""
    print("\n" + "=" * 60)
    print("OPTIONS WHALE FINDER")
    print("=" * 60)
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=LOOKBACK_DAYS)
    
    print(f"\nSearching for options whale trades...")
    print(f"Underlyings: {UNDERLYINGS}")
    print(f"Time range: {start_date.strftime('%Y-%m-%d %H:%M')} to {end_date.strftime('%Y-%m-%d %H:%M')}")
    print(f"Thresholds: >= {MIN_CONTRACTS:,} contracts OR >= ${MIN_PREMIUM_VALUE:,.0f} premium OR >= ${MIN_NOTIONAL_VALUE:,.0f} notional")
    
    # Find whale trades
    whales = find_options_whales(
        UNDERLYINGS,
        start_date,
        min_premium=MIN_PREMIUM_VALUE,
        min_contracts=MIN_CONTRACTS,
        min_notional=MIN_NOTIONAL_VALUE
    )
    
    # Print summary
    print_whale_summary(whales)
    
    # Detect sweeps
    sweeps = detect_sweeps(whales, SWEEP_TIME_WINDOW, SWEEP_MIN_LEGS)
    print_sweeps(sweeps)
    
    # Print top trades
    print_top_trades(whales, top_n=20)
    
    # =================================================================
    # METHODOLOGY
    # =================================================================
    print("\n" + "=" * 100)
    print("📐 METHODOLOGY")
    print("=" * 100)
    print("""
   Premium Value = Contracts × Price × 100 (each contract = 100 shares)
   Notional Value = Contracts × Strike × 100 (total stock value controlled)
   
   🟢 CALLS = Bullish bet (profit if stock goes UP)
   🔴 PUTS = Bearish bet (profit if stock goes DOWN)
   
   ITM (In The Money) = Higher probability, more expensive, more conviction
   ATM (At The Money) = Balanced risk/reward
   OTM (Out The Money) = Lower probability, cheaper, "lottery ticket"
   
   Short DTE (0-7 days) = Very aggressive, time-sensitive bet
   Long DTE (90+ days) = LEAPS, longer-term thesis
   
   Sweeps = Multiple rapid trades, often institutional filling large orders
""")


def main():
    """Main menu."""
    print("\n" + "🐋" * 25)
    print("   OPTIONS WHALE ALERT SYSTEM")
    print("🐋" * 25)
    
    print("""
Choose an option:

1. Options Whale Finder - Find large options trades
2. Quick Scan (lower thresholds) - Find more trades

Enter choice (1-2): """, end="")
    
    try:
        choice = input().strip()
    except:
        choice = "1"
    
    if choice == "2":
        # Lower thresholds for more results
        global MIN_PREMIUM_VALUE, MIN_CONTRACTS, MIN_NOTIONAL_VALUE
        MIN_PREMIUM_VALUE = 25000
        MIN_CONTRACTS = 50
        MIN_NOTIONAL_VALUE = 250000
    
    demo_options_whale_finder()
    
    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
