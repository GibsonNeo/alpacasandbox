"""
Alpaca Market Data - Fetch Historical Daily Data

This script demonstrates how to fetch historical daily bar data from Alpaca Markets API.
It supports both stock and crypto data.
"""

import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get credentials from environment
# These match the standard Alpaca API key header names
API_KEY = os.getenv('APCA-API-KEY-ID')
API_SECRET = os.getenv('APCA-API-SECRET-KEY')

# =============================================================================
# CONFIGURATION - Edit these to customize your historical data fetch!
# =============================================================================

# Stock symbols to fetch (requires API keys)
STOCK_SYMBOLS = ['AAPL', 'MSFT', 'GOOGL']

# Crypto symbols to fetch (no API keys required)
CRYPTO_SYMBOLS = ['BTC/USD', 'ETH/USD']

# Date range - how many days of historical data to fetch
LOOKBACK_DAYS = 30

# Price adjustment type for stocks:
#   - 'RAW'      : No adjustments (actual trading prices)
#   - 'SPLIT'    : Adjust for stock splits only
#   - 'DIVIDEND' : Adjust for dividends only
#   - 'ALL'      : All adjustments (splits + dividends + spin-offs) - recommended for backtesting
ADJUSTMENT_TYPE = 'ALL'

# What data to fetch
FETCH_STOCKS = True     # Set to False to skip stock data
FETCH_CRYPTO = False     # Set to False to skip crypto data

# =============================================================================

# Alpaca SDK imports
from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import Adjustment


def fetch_stock_daily_bars(
    symbols: list[str], 
    start_date: datetime, 
    end_date: datetime,
    adjustment: Adjustment = Adjustment.ALL
):
    """
    Fetch historical daily bar data for stocks.
    
    Args:
        symbols: List of stock symbols (e.g., ['AAPL', 'MSFT'])
        start_date: Start date for the data range
        end_date: End date for the data range
        adjustment: Price/volume adjustment type. Options:
            - Adjustment.RAW: No adjustments
            - Adjustment.SPLIT: Adjust for stock splits only
            - Adjustment.DIVIDEND: Adjust for dividends only
            - Adjustment.ALL: Adjust for splits, dividends, and spin-offs (recommended)
    
    Returns:
        DataFrame with OHLCV data
    """
    # Initialize the stock historical data client with API credentials
    client = StockHistoricalDataClient(API_KEY, API_SECRET)
    
    # Create request parameters
    request_params = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start_date,
        end=end_date,
        adjustment=adjustment
    )
    
    # Fetch the bars
    bars = client.get_stock_bars(request_params)
    
    # Return as DataFrame
    return bars.df


def fetch_crypto_daily_bars(symbols: list[str], start_date: datetime, end_date: datetime):
    """
    Fetch historical daily bar data for crypto.
    Note: Crypto data does NOT require API keys.
    
    Args:
        symbols: List of crypto symbols (e.g., ['BTC/USD', 'ETH/USD'])
        start_date: Start date for the data range
        end_date: End date for the data range
    
    Returns:
        DataFrame with OHLCV data
    """
    # Crypto client doesn't require API keys
    client = CryptoHistoricalDataClient()
    
    # Create request parameters
    request_params = CryptoBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start_date,
        end=end_date
    )
    
    # Fetch the bars
    bars = client.get_crypto_bars(request_params)
    
    # Return as DataFrame
    return bars.df


def main():
    """Main function to demonstrate fetching historical data."""
    
    # Map string config to Adjustment enum
    adjustment_map = {
        'RAW': Adjustment.RAW,
        'SPLIT': Adjustment.SPLIT,
        'DIVIDEND': Adjustment.DIVIDEND,
        'ALL': Adjustment.ALL
    }
    adjustment = adjustment_map.get(ADJUSTMENT_TYPE.upper(), Adjustment.ALL)
    
    # Define date range based on config
    end_date = datetime.now()
    start_date = end_date - timedelta(days=LOOKBACK_DAYS)
    
    print("=" * 60)
    print("Alpaca Historical Market Data Fetcher")
    print("=" * 60)
    print(f"\nDate Range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    print(f"Lookback: {LOOKBACK_DAYS} days")
    
    # --- Fetch Stock Data ---
    if FETCH_STOCKS:
        print("\n" + "-" * 40)
        print("STOCK DATA (requires API keys)")
        print("-" * 40)
        
        if API_KEY and API_SECRET and API_KEY != 'your_client_id_here':
            try:
                print(f"\nFetching daily bars for: {STOCK_SYMBOLS}")
                print(f"Adjustment type: {ADJUSTMENT_TYPE}")
                
                stock_df = fetch_stock_daily_bars(
                    STOCK_SYMBOLS, 
                    start_date, 
                    end_date,
                    adjustment=adjustment
                )
                
                print(f"\nStock Data Shape: {stock_df.shape}")
                
                # Show data for each symbol
                print("\nStock Data by Symbol:")
                for symbol in STOCK_SYMBOLS:
                    if symbol in stock_df.index.get_level_values('symbol'):
                        symbol_data = stock_df.loc[symbol]
                        print(f"\n--- {symbol} (last 5 days) ---")
                        print(symbol_data.tail(5))
                
                # Show summary statistics
                print("\nSummary Statistics (all symbols):")
                print(stock_df.describe())
                
            except Exception as e:
                print(f"\nError fetching stock data: {e}")
                print("Make sure your API credentials are valid.")
        else:
            print("\nSkipping stock data - API credentials not configured.")
            print("Please update your .env file with valid credentials.")
    
    # --- Fetch Crypto Data ---
    if FETCH_CRYPTO:
        print("\n" + "-" * 40)
        print("CRYPTO DATA (no API keys required)")
        print("-" * 40)
        
        try:
            print(f"\nFetching daily bars for: {CRYPTO_SYMBOLS}")
            
            crypto_df = fetch_crypto_daily_bars(CRYPTO_SYMBOLS, start_date, end_date)
            
            print(f"\nCrypto Data Shape: {crypto_df.shape}")
            
            # Show data for each symbol
            print("\nCrypto Data by Symbol:")
            for symbol in CRYPTO_SYMBOLS:
                if symbol in crypto_df.index.get_level_values('symbol'):
                    symbol_data = crypto_df.loc[symbol]
                    print(f"\n--- {symbol} (last 5 days) ---")
                    print(symbol_data.tail(5))
            
        except Exception as e:
            print(f"\nError fetching crypto data: {e}")
    
    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
