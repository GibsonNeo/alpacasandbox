"""
Options Whale Alert - Monitor for Large Options Trades

This script finds "whale" options trades using industry-standard tiered thresholds
based on moneyness, ticker liquidity, and volume vs open interest.

Classification Tiers:
- NOTABLE: Worth watching, smaller but significant
- UNUSUAL: Notable activity, real money
- WHALE: Significant institutional-sized trade  
- STRONG WHALE: Large conviction bet
- HEADLINE WHALE: $1M+ trade, major institutional activity

Thresholds adjust by:
1. Moneyness (OTM/ATM/ITM) - different $ thresholds
2. Ticker size (mega cap vs small cap)
3. Volume vs Open Interest ratio
4. Days to expiration (short-dated = more aggressive)

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

# Lookback period
LOOKBACK_DAYS = 5

# Sweep detection
SWEEP_TIME_WINDOW = 60          # Seconds - trades within this window may be a sweep
SWEEP_MIN_LEGS = 3              # Minimum number of trades to qualify as sweep

# =============================================================================
# TIERED THRESHOLDS BY MONEYNESS
# These are industry-standard thresholds used by options flow trackers
# =============================================================================

# OTM Options (most common in "unusual" feeds - lottery tickets)
OTM_THRESHOLDS = {
    'notable': 10000,           # $10K - notable if volume spike
    'unusual': 50000,           # $50K - "real" unusual
    'whale': 100000,            # $100K - whale for liquid names
    'strong_whale': 250000,     # $250K - strong whale
    'headline': 1000000,        # $1M+ - headline whale
}

# ATM Options (higher delta, higher premium per contract)
ATM_THRESHOLDS = {
    'notable': 25000,           # $25K - notable
    'unusual': 100000,          # $100K - "this matters" 
    'whale': 250000,            # $250K - whale starting point
    'strong_whale': 500000,     # $500K - serious whale
    'headline': 2000000,        # $2M+ - headline whale
}

# ITM Options (stock replacement, hedging, structured flow)
ITM_THRESHOLDS = {
    'notable': 50000,           # $50K - meaningful (lower contract counts)
    'unusual': 250000,          # $250K - large
    'whale': 500000,            # $500K - whale starting point
    'strong_whale': 1000000,    # $1M - serious whale
    'headline': 5000000,        # $5M+ - headline (common on mega caps)
}

# Ticker size adjustments (multiply thresholds by these factors)
# Mega caps like SPY, QQQ, AAPL need higher thresholds
TICKER_SIZE = {
    'SPY': 'mega',    # Index ETF - very liquid
    'QQQ': 'mega',    # Index ETF - very liquid
    'IWM': 'mega',    # Index ETF
    'AAPL': 'mega',   # Mega cap
    'MSFT': 'mega',   # Mega cap
    'GOOGL': 'mega',  # Mega cap
    'AMZN': 'mega',   # Mega cap
    'NVDA': 'large',  # Large cap, very active options
    'TSLA': 'large',  # Large cap, very active options
    'META': 'large',  # Large cap
    'AMD': 'mid',     # Mid cap, less liquid
    # Default for unlisted tickers is 'mid'
}

TICKER_MULTIPLIERS = {
    'mega': 2.0,      # 2x thresholds for mega caps
    'large': 1.5,     # 1.5x for large caps
    'mid': 1.0,       # Standard thresholds
    'small': 0.5,     # Half thresholds for small caps
}

# Volume vs Open Interest thresholds (flag unusual activity)
VOL_OI_UNUSUAL = 0.05    # Trade is 5%+ of open interest = unusual
VOL_OI_WHALE = 0.20      # Trade is 20%+ of open interest = whale-level significance

# =============================================================================


def get_thresholds_for_trade(itm_status: str, underlying: str) -> dict:
    """Get the appropriate thresholds based on moneyness and ticker size."""
    # Select base thresholds by moneyness
    if itm_status == 'OTM':
        base = OTM_THRESHOLDS.copy()
    elif itm_status == 'ATM':
        base = ATM_THRESHOLDS.copy()
    else:  # ITM
        base = ITM_THRESHOLDS.copy()
    
    # Apply ticker size multiplier
    ticker_size = TICKER_SIZE.get(underlying, 'mid')
    multiplier = TICKER_MULTIPLIERS[ticker_size]
    
    return {k: v * multiplier for k, v in base.items()}


def classify_trade(premium: float, itm_status: str, underlying: str, 
                   vol_oi_ratio: float = None, dte: int = None) -> dict:
    """
    Classify a trade using tiered thresholds.
    
    Returns dict with:
    - tier: 'noise', 'notable', 'unusual', 'whale', 'strong_whale', 'headline'
    - emoji: Visual indicator
    - label: Human readable label
    - flags: List of notable attributes
    """
    thresholds = get_thresholds_for_trade(itm_status, underlying)
    
    # Determine tier based on premium
    if premium >= thresholds['headline']:
        tier = 'headline'
        emoji = '🔥'
        label = 'HEADLINE WHALE'
    elif premium >= thresholds['strong_whale']:
        tier = 'strong_whale'
        emoji = '🐋'
        label = 'STRONG WHALE'
    elif premium >= thresholds['whale']:
        tier = 'whale'
        emoji = '💰'
        label = 'WHALE'
    elif premium >= thresholds['unusual']:
        tier = 'unusual'
        emoji = '👀'
        label = 'UNUSUAL'
    elif premium >= thresholds['notable']:
        tier = 'notable'
        emoji = '📊'
        label = 'NOTABLE'
    else:
        tier = 'noise'
        emoji = ''
        label = ''
    
    # Build flags for special conditions
    flags = []
    
    # Volume vs OI flag
    if vol_oi_ratio is not None:
        if vol_oi_ratio >= VOL_OI_WHALE:
            flags.append(f'🎯 {vol_oi_ratio:.0%} of OI')
        elif vol_oi_ratio >= VOL_OI_UNUSUAL:
            flags.append(f'📈 {vol_oi_ratio:.0%} of OI')
    
    # Short DTE flag (more aggressive)
    if dte is not None and dte <= 7 and dte > 1:
        flags.append(f'⚡ {dte}DTE')
    
    # Zero DTE flag (expiring today/tomorrow)
    if dte is not None and dte <= 1:
        flags.append('🎰 0DTE')
    
    return {
        'tier': tier,
        'emoji': emoji,
        'label': label,
        'flags': flags,
        'thresholds': thresholds
    }


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
                        min_tier: str = 'unusual') -> list:
    """
    Find whale options trades across multiple underlyings.
    
    Args:
        underlyings: List of stock symbols to scan
        start_date: Start of time range
        min_tier: Minimum tier to include ('notable', 'unusual', 'whale', 'strong_whale', 'headline')
    
    Returns list of whale trades with analysis.
    """
    tier_order = ['noise', 'notable', 'unusual', 'whale', 'strong_whale', 'headline']
    min_tier_idx = tier_order.index(min_tier) if min_tier in tier_order else 0
    
    all_whales = []
    
    for underlying in underlyings:
        print(f"   Scanning {underlying} options...", end=" ", flush=True)
        
        try:
            # Get option chain to find active contracts
            chain = get_option_chain(underlying, limit=500)
            
            if not chain:
                print("no chain data")
                continue
            
            # Extract open interest from chain for vol/OI calculations
            chain_oi = {}
            for symbol, snap in chain.items():
                if 'latestQuote' in snap:
                    # Note: Alpaca doesn't provide OI directly, so we estimate from quote size
                    # In a real system, you'd get this from a separate OI endpoint
                    chain_oi[symbol] = snap.get('latestQuote', {}).get('bs', 0) + snap.get('latestQuote', {}).get('as', 0)
            
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
                        itm_status = 'ATM'  # Default if no stock price
                        moneyness = 0
                    
                    # Estimate vol/OI ratio (if we have OI data)
                    oi = chain_oi.get(contract_symbol, 0)
                    vol_oi_ratio = size / oi if oi > 0 else None
                    
                    # Classify the trade
                    classification = classify_trade(
                        premium_value, itm_status, underlying, vol_oi_ratio, dte
                    )
                    
                    # Check if meets minimum tier
                    tier_idx = tier_order.index(classification['tier'])
                    if tier_idx < min_tier_idx:
                        continue
                    
                    whale_count += 1
                    
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
                        'sentiment_emoji': sentiment_emoji,
                        'tier': classification['tier'],
                        'tier_emoji': classification['emoji'],
                        'tier_label': classification['label'],
                        'flags': classification['flags'],
                        'vol_oi_ratio': vol_oi_ratio
                    })
            
            print(f"found {whale_count} trades")
            
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
    
    print(f"\n🐋 Found {len(whales)} notable options trades!")
    
    # =================================================================
    # TIER BREAKDOWN
    # =================================================================
    tier_counts = defaultdict(lambda: {'count': 0, 'premium': 0})
    for w in whales:
        tier_counts[w['tier']]['count'] += 1
        tier_counts[w['tier']]['premium'] += w['premium_value']
    
    print("\n" + "=" * 100)
    print("📊 TRADE CLASSIFICATION BREAKDOWN")
    print("=" * 100)
    
    tier_display = [
        ('headline', '🔥 HEADLINE WHALE', '$1M+ (adjusted by ticker/moneyness)'),
        ('strong_whale', '🐋 STRONG WHALE', '$250K-$1M'),
        ('whale', '💰 WHALE', '$100K-$250K'),
        ('unusual', '👀 UNUSUAL', '$50K-$100K'),
        ('notable', '📊 NOTABLE', '$10K-$50K'),
    ]
    
    for tier, label, desc in tier_display:
        if tier in tier_counts:
            data = tier_counts[tier]
            print(f"   {label:<25} {data['count']:>6} trades  |  ${data['premium']:>15,.0f}  ({desc})")
    
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
    print(f"   🟢 CALLS (Bullish): {len(calls):>6} trades  |  ${call_premium:>15,.2f} premium")
    print(f"   🔴 PUTS (Bearish):  {len(puts):>6} trades  |  ${put_premium:>15,.2f} premium")
    
    if call_premium > put_premium:
        ratio = call_premium / put_premium if put_premium > 0 else float('inf')
        print(f"\n   ➡️  Net sentiment: BULLISH 🟢 (${call_premium - put_premium:,.0f} more in calls)")
        print(f"       Call/Put Premium Ratio: {ratio:.2f}x")
    elif put_premium > call_premium:
        ratio = put_premium / call_premium if call_premium > 0 else float('inf')
        print(f"\n   ➡️  Net sentiment: BEARISH 🔴 (${put_premium - call_premium:,.0f} more in puts)")
        print(f"       Put/Call Premium Ratio: {ratio:.2f}x")
    else:
        print(f"\n   ➡️  Net sentiment: NEUTRAL ⚪")
    
    # =================================================================
    # WHALE+ ONLY SENTIMENT (strong_whale and headline)
    # =================================================================
    big_whales = [w for w in whales if w['tier'] in ('strong_whale', 'headline')]
    if big_whales:
        big_calls = [w for w in big_whales if w['type'] == 'CALL']
        big_puts = [w for w in big_whales if w['type'] == 'PUT']
        big_call_prem = sum(w['premium_value'] for w in big_calls)
        big_put_prem = sum(w['premium_value'] for w in big_puts)
        
        print(f"\n   🐋 BIG WHALE ($250K+) SENTIMENT:")
        print(f"      🟢 {len(big_calls)} calls (${big_call_prem:,.0f})  vs  🔴 {len(big_puts)} puts (${big_put_prem:,.0f})")
        if big_call_prem > big_put_prem:
            print(f"      ➡️  Big money is BULLISH 🟢")
        elif big_put_prem > big_call_prem:
            print(f"      ➡️  Big money is BEARISH 🔴")
    
    # =================================================================
    # SUMMARY BY UNDERLYING
    # =================================================================
    print("\n" + "=" * 100)
    print("📊 FLOW BY UNDERLYING (sorted by total activity)")
    print("=" * 100)
    print(f"{'Ticker':<8} {'Size':<6} {'🟢 Calls':>8} {'Call $':>14} {'🔴 Puts':>8} {'Put $':>14} {'Net Flow':>16} {'Sentiment':<12}")
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
        ticker_size = TICKER_SIZE.get(underlying, 'mid')
        
        print(f"{underlying:<8} {ticker_size:<6} {data['calls']:>8} ${data['call_prem']:>12,.0f} {data['puts']:>8} ${data['put_prem']:>12,.0f} {net_str:>16} {sentiment:<12}")
    
    # =================================================================
    # EXPIRATION ANALYSIS
    # =================================================================
    print("\n" + "=" * 100)
    print("📅 EXPIRATION ANALYSIS")
    print("=" * 100)
    
    # Group by DTE buckets
    dte_buckets = {'0DTE': [], '1-2 days': [], '3-7 days': [], '8-30 days': [], '31-90 days': [], '90+ days': []}
    for w in whales:
        dte = w['dte']
        if dte is None:
            continue
        elif dte <= 0:
            dte_buckets['0DTE'].append(w)
        elif dte <= 2:
            dte_buckets['1-2 days'].append(w)
        elif dte <= 7:
            dte_buckets['3-7 days'].append(w)
        elif dte <= 30:
            dte_buckets['8-30 days'].append(w)
        elif dte <= 90:
            dte_buckets['31-90 days'].append(w)
        else:
            dte_buckets['90+ days'].append(w)
    
    print(f"   🎰 0DTE (expiring today):  {len(dte_buckets['0DTE']):>5} trades  |  ${sum(w['premium_value'] for w in dte_buckets['0DTE']):>14,.0f}  ← YOLO BETS")
    print(f"   ⚡ 1-2 days:               {len(dte_buckets['1-2 days']):>5} trades  |  ${sum(w['premium_value'] for w in dte_buckets['1-2 days']):>14,.0f}  ← Very aggressive")
    print(f"   🔥 3-7 days:               {len(dte_buckets['3-7 days']):>5} trades  |  ${sum(w['premium_value'] for w in dte_buckets['3-7 days']):>14,.0f}  ← Short-term")
    print(f"   📆 8-30 days:              {len(dte_buckets['8-30 days']):>5} trades  |  ${sum(w['premium_value'] for w in dte_buckets['8-30 days']):>14,.0f}  ← Near-term")
    print(f"   📅 31-90 days:             {len(dte_buckets['31-90 days']):>5} trades  |  ${sum(w['premium_value'] for w in dte_buckets['31-90 days']):>14,.0f}  ← Medium-term")
    print(f"   🗓️  90+ days:               {len(dte_buckets['90+ days']):>5} trades  |  ${sum(w['premium_value'] for w in dte_buckets['90+ days']):>14,.0f}  ← LEAPS")
    
    # =================================================================
    # MONEYNESS ANALYSIS  
    # =================================================================
    print("\n" + "=" * 100)
    print("💰 MONEYNESS ANALYSIS")
    print("=" * 100)
    
    itm = [w for w in whales if w['itm_status'] == 'ITM']
    atm = [w for w in whales if w['itm_status'] == 'ATM']
    otm = [w for w in whales if w['itm_status'] == 'OTM']
    
    print(f"   💵 ITM (In The Money):   {len(itm):>5} trades  |  ${sum(w['premium_value'] for w in itm):>14,.0f}  ← Higher conviction, stock replacement")
    print(f"   🎯 ATM (At The Money):   {len(atm):>5} trades  |  ${sum(w['premium_value'] for w in atm):>14,.0f}  ← Balanced risk/reward")
    print(f"   🎰 OTM (Out The Money):  {len(otm):>5} trades  |  ${sum(w['premium_value'] for w in otm):>14,.0f}  ← Lottery tickets, higher leverage")


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
        flags_str = ' '.join(w['flags']) if w['flags'] else ''
        
        print(f"\n#{i} {w['tier_emoji']} {w['tier_label']} - {w['sentiment_emoji']} {w['underlying']} ${w['strike']:.0f} {w['type']} exp {w['expiration']}")
        print(f"   Contract:  {w['contract']}")
        print(f"   Size:      {w['contracts']:,} contracts")
        print(f"   Price:     ${w['price']:.2f} per contract")
        print(f"   Premium:   ${w['premium_value']:,.2f}")
        print(f"   Notional:  ${w['notional_value']:,.2f} (controls this much stock)")
        print(f"   DTE:       {dte_str}")
        print(f"   Stock:     ${w['stock_price']:.2f} ({w['itm_status']}, {abs(w['moneyness']):.1f}% {'ITM' if w['moneyness'] > 0 else 'OTM'})")
        print(f"   Sentiment: {w['sentiment']} {w['sentiment_emoji']}")
        if flags_str:
            print(f"   Flags:     {flags_str}")
        print(f"   Time:      {w['timestamp']}")
    
    # =================================================================
    # TOP 20 TABLE
    # =================================================================
    print("\n" + "=" * 145)
    print(f"🐋 TOP {top_n} OPTIONS WHALE TRADES")
    print("=" * 145)
    print(f"{'#':<3} {'Tier':<6} {'Dir':<4} {'Ticker':<6} {'Strike':>8} {'Type':<5} {'Exp':<12} {'DTE':>4} {'Contracts':>10} {'Price':>8} {'Premium':>14} {'ITM':>4} {'Flags':<15}")
    print("-" * 145)
    
    for i, w in enumerate(whales[:top_n], 1):
        dte_str = str(w['dte']) if w['dte'] is not None else "?"
        flags_str = ' '.join(w['flags'][:2]) if w['flags'] else ''  # Show first 2 flags
        print(f"{i:<3} {w['tier_emoji']:<6} {w['sentiment_emoji']:<4} {w['underlying']:<6} ${w['strike']:>6,.0f} {w['type']:<5} {w['expiration']:<12} {dte_str:>4} {w['contracts']:>10,} ${w['price']:>6.2f} ${w['premium_value']:>12,.0f} {w['itm_status']:>4} {flags_str:<15}")


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


def print_methodology():
    """Print the methodology explanation."""
    print("\n" + "=" * 100)
    print("📐 METHODOLOGY & THRESHOLDS")
    print("=" * 100)
    print("""
   PREMIUM CALCULATION:
   Premium = Option Price × 100 × Contracts
   (A $0.20 OTM option needs 5,000 contracts = $100K, while $8 ITM needs 125 = $100K)

   TIERED THRESHOLDS (adjusted by moneyness):
   
   OTM (Out The Money) - Lottery tickets, high leverage:
      Notable: $10K+  |  Unusual: $50K+  |  Whale: $100K+  |  Strong: $250K+  |  Headline: $1M+
   
   ATM (At The Money) - Balanced risk/reward:
      Notable: $25K+  |  Unusual: $100K+ |  Whale: $250K+  |  Strong: $500K+  |  Headline: $2M+
   
   ITM (In The Money) - Stock replacement, hedging:
      Notable: $50K+  |  Unusual: $250K+ |  Whale: $500K+  |  Strong: $1M+    |  Headline: $5M+

   TICKER SIZE MULTIPLIERS (applied to above thresholds):
      Mega (SPY, QQQ, AAPL, MSFT, GOOGL, AMZN): 2x thresholds (very liquid)
      Large (TSLA, NVDA, META):                 1.5x thresholds
      Mid (AMD, etc):                           1x thresholds (standard)
      Small caps:                               0.5x thresholds (less liquid)

   SPECIAL FLAGS:
      🎯 X% of OI  = Trade is significant % of Open Interest (unusual activity)
      ⚡ XDTE      = Short-dated option (aggressive bet)
      🎰 0DTE      = Expiring today (YOLO bet)

   SENTIMENT:
      🟢 CALLS = Bullish bet (profit if stock UP)
      🔴 PUTS = Bearish bet (profit if stock DOWN)
      
   WHY THIS MATTERS:
      - A $50K OTM trade can be more significant than a $500K ITM trade
      - Mega caps see $1M+ flow routinely; same trade on small cap is huge
      - Short DTE = more aggressive conviction (time decay working against you)
      - Volume vs OI shows if someone is making a NEW bet vs closing existing
""")


def demo_options_whale_finder(min_tier: str = 'unusual'):
    """Main demo function for options whale finder."""
    print("\n" + "=" * 60)
    print("OPTIONS WHALE FINDER")
    print("=" * 60)
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=LOOKBACK_DAYS)
    
    print(f"\nSearching for options whale trades...")
    print(f"Underlyings: {UNDERLYINGS}")
    print(f"Time range: {start_date.strftime('%Y-%m-%d %H:%M')} to {end_date.strftime('%Y-%m-%d %H:%M')}")
    print(f"Minimum tier: {min_tier.upper()}")
    print(f"\nThresholds adjust by moneyness (OTM/ATM/ITM) and ticker size (mega/large/mid)")
    
    # Find whale trades
    whales = find_options_whales(UNDERLYINGS, start_date, min_tier=min_tier)
    
    # Print summary
    print_whale_summary(whales)
    
    # Detect sweeps
    sweeps = detect_sweeps(whales, SWEEP_TIME_WINDOW, SWEEP_MIN_LEGS)
    print_sweeps(sweeps)
    
    # Print top trades
    print_top_trades(whales, top_n=20)
    
    # Print methodology
    print_methodology()


def main():
    """Main menu."""
    print("\n" + "🐋" * 25)
    print("   OPTIONS WHALE ALERT SYSTEM")
    print("   Using Tiered Thresholds by Moneyness & Ticker Size")
    print("🐋" * 25)
    
    print("""
Choose a scan mode:

1. Whale Hunt     - Only WHALE+ trades ($100K-$500K+ depending on moneyness/ticker)
2. Unusual Scan   - Include UNUSUAL activity ($50K-$250K+)
3. Full Scan      - Include all NOTABLE trades ($10K-$50K+)
4. Headline Only  - Only HEADLINE trades ($1M-$5M+)

Enter choice (1-4): """, end="")
    
    try:
        choice = input().strip()
    except:
        choice = "2"  # Default
    
    tier_map = {
        '1': 'whale',
        '2': 'unusual',
        '3': 'notable',
        '4': 'headline'
    }
    
    min_tier = tier_map.get(choice, 'unusual')
    
    demo_options_whale_finder(min_tier=min_tier)
    
    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
