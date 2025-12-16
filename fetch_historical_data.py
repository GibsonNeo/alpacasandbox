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
    
    # Define date range (last 30 days)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    print("=" * 60)
    print("Alpaca Historical Market Data Fetcher")
    print("=" * 60)
    print(f"\nDate Range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    
    # --- Fetch Stock Data ---
    print("\n" + "-" * 40)
    print("STOCK DATA (requires API keys)")
    print("-" * 40)
    
    if API_KEY and API_SECRET and API_KEY != 'your_client_id_here':
        try:
            stock_symbols = ['AAPL', 'MSFT', 'GOOGL']
            print(f"\nFetching daily bars for: {stock_symbols}")
            
            # Fetch with ALL adjustments (splits + dividends + spin-offs)
            print("\n>>> Using Adjustment.ALL (recommended for backtesting)")
            print("    Adjusts for: stock splits, dividends, and spin-offs")
            stock_df = fetch_stock_daily_bars(
                stock_symbols, 
                start_date, 
                end_date,
                adjustment=Adjustment.ALL
            )
            
            print(f"\nStock Data Shape: {stock_df.shape}")
            print("\nStock Data (first 10 rows):")
            print(stock_df.head(10))
            
            # Show summary statistics
            print("\nSummary Statistics:")
            print(stock_df.describe())
            
            # Demonstrate different adjustment options
            print("\n" + "-" * 40)
            print("ADJUSTMENT OPTIONS COMPARISON")
            print("-" * 40)
            print("""
Available adjustment options:
  - Adjustment.RAW      : No adjustments (actual trading prices)
  - Adjustment.SPLIT    : Adjust for stock splits only
  - Adjustment.DIVIDEND : Adjust for dividends only  
  - Adjustment.ALL      : All adjustments (splits + dividends + spin-offs)

For backtesting/analysis: Use Adjustment.ALL
For seeing actual traded prices: Use Adjustment.RAW
""")
            
        except Exception as e:
            print(f"\nError fetching stock data: {e}")
            print("Make sure your API credentials are valid.")
    else:
        print("\nSkipping stock data - API credentials not configured.")
        print("Please update your .env file with valid credentials.")
    
    # --- Fetch Crypto Data ---
    print("\n" + "-" * 40)
    print("CRYPTO DATA (no API keys required)")
    print("-" * 40)
    
    try:
        crypto_symbols = ['BTC/USD', 'ETH/USD']
        print(f"\nFetching daily bars for: {crypto_symbols}")
        
        crypto_df = fetch_crypto_daily_bars(crypto_symbols, start_date, end_date)
        
        print(f"\nCrypto Data Shape: {crypto_df.shape}")
        print("\nCrypto Data (first 10 rows):")
        print(crypto_df.head(10))
        
    except Exception as e:
        print(f"\nError fetching crypto data: {e}")
    
    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
