import asyncio
import pandas as pd
from datetime import datetime, timezone
try:
    from dukascopy_python import fetch as duka_fetch
except ImportError:
    duka_fetch = None

class DeepDataFetcher:
    @staticmethod
    async def fetch_range_async(symbol: str, timeframe: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Routes the fetch request based on the symbol.
        Timeframe expected: "5m", "15m", "1h", "1d"
        """
        # Convert yfinance format '5m' to minutes for crypto, and Dukascopy strings for forex
        if symbol == "BTC-USD":
            return await DeepDataFetcher._fetch_crypto_binance(symbol, timeframe, start_date, end_date)
        else:
            return await DeepDataFetcher._fetch_forex_dukascopy(symbol, timeframe, start_date, end_date)

    @staticmethod
    async def _fetch_crypto_binance(symbol: str, timeframe: str, start_date: str, end_date: str) -> pd.DataFrame:
        import ccxt
        exchange = ccxt.binance({
            'enableRateLimit': True,
        })
        
        # ccxt format mapping
        tf_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "1d": "1d"}
        ccxt_tf = tf_map.get(timeframe, timeframe)
        
        since_dt = datetime.strptime(start_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        since_ms = int(since_dt.timestamp() * 1000)
        
        end_dt = datetime.strptime(end_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        end_ms = int(end_dt.timestamp() * 1000)
        
        all_ohlcv = []
        
        # Async wrapper to prevent blocking the event loop
        def fetch_sync():
            nonlocal since_ms, end_ms
            local_ohlcv = []
            total_days = max(1, (end_dt - since_dt).days)
            while since_ms < end_ms:
                current_dt = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc)
                remaining_days = (end_dt - current_dt).days
                pct = max(0.0, min(100.0, ((total_days - remaining_days) / total_days) * 100))
                print(f"\r      [CCXT] Fetching BTC/USDT history: {pct:.1f}% ({current_dt.strftime('%Y-%m-%d')} → {end_date})", end="", flush=True)
                
                ohlcv = exchange.fetch_ohlcv('BTC/USDT', ccxt_tf, since=since_ms, limit=1000)
                if not len(ohlcv):
                    break
                
                # Filter out bars past end_ms
                ohlcv = [bar for bar in ohlcv if bar[0] <= end_ms]
                if not len(ohlcv):
                    break
                    
                local_ohlcv += ohlcv
                since_ms = ohlcv[-1][0] + 1  # Next bar
            print("\n      [CCXT] Fetch complete.", flush=True)
            return local_ohlcv

        # Run ccxt sync fetching in thread
        loop = asyncio.get_event_loop()
        all_ohlcv = await loop.run_in_executor(None, fetch_sync)
        
        if not all_ohlcv:
            return pd.DataFrame()
            
        df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('datetime', inplace=True)
        df.drop(columns=['timestamp'], inplace=True)
        return df

    @staticmethod
    async def _fetch_forex_dukascopy(symbol: str, timeframe: str, start_date: str, end_date: str) -> pd.DataFrame:
        # Route to local DukascopyLoader to read the M1 CSV files downloaded for this symbol
        from data.dukascopy_loader import DukascopyLoader
        
        # Map yfinance-style timeframes ('5m', '15m') to DukascopyLoader expectations ('5min', '15min')
        tf_map = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "1d": "1d"}
        loader_tf = tf_map.get(timeframe, timeframe)
        
        def load_sync():
            loader = DukascopyLoader()
            return loader.load(symbol, timeframe=loader_tf, start_date=start_date, end_date=end_date)

        loop = asyncio.get_running_loop()
        df = await loop.run_in_executor(None, load_sync)
        return df if df is not None else pd.DataFrame()
