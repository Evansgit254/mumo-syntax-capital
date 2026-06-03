import yfinance as yf
import pandas as pd
try:
    from curl_cffi import requests as requests_cffi
except ImportError:
    import requests as requests_cffi
from typing import Dict, Optional
from config.config import SYMBOLS, NARRATIVE_TF, STRUCTURE_TF, ENTRY_TF, INSTITUTIONAL_TF
from indicators.calculations import IndicatorCalculator
import warnings
import logging
from datetime import timedelta

# Suppress noisy warnings
warnings.simplefilter(action='ignore', category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

class DataFetcher:
    _session = None

    @staticmethod
    def _get_provider() -> str:
        """Fetch current data provider from database."""
        from config.config import DB_CLIENTS
        import sqlite3
        try:
            conn = sqlite3.connect(DB_CLIENTS)
            row = conn.execute("SELECT value FROM system_config WHERE key = 'data_provider'").fetchone()
            conn.close()
            return row[0] if row and row[0] else "yfinance"
        except:
            return "yfinance"

    @staticmethod
    def _get_session():
        if DataFetcher._session is None:
            try:
                from curl_cffi import requests as curl_requests
                # impersonate="chrome" is critical for bypassing Yahoo Finance anti-scraping
                DataFetcher._session = curl_requests.Session(impersonate="chrome")
            except ImportError:
                import requests
                DataFetcher._session = requests.Session()
                # Set common headers for standard requests to mimic a browser
                DataFetcher._session.headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                })
        return DataFetcher._session
    @staticmethod
    def fetch_data(symbol: str, timeframe: str, period: str = "5d") -> Optional[pd.DataFrame]:
        """
        Fetch historical data for a symbol with exponential backoff.
        """
        import time
        max_retries = 3
        backoff = 2
        
        for attempt in range(max_retries):
            try:
                session = DataFetcher._get_session()
                # download is often more robust for session-based access
                df = yf.download(
                    tickers=symbol,
                    period=period,
                    interval=timeframe,
                    session=session,
                    progress=False,
                    auto_adjust=True,
                    threads=False
                )
                
                if df is None or df.empty:
                    if attempt < max_retries - 1:
                        time.sleep(backoff ** attempt)
                        continue
                    return None
                
                # Flatten MultiIndex columns if necessary
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                
                df = df.rename(columns={
                    'Open': 'open',
                    'High': 'high',
                    'Low': 'low',
                    'Close': 'close',
                    'Volume': 'volume'
                })
                # Check for empty index before conversion
                if df.index is None or len(df.index) == 0:
                    return None
                    
                # Handle timezone conversion safely
                if df.index.tz is None:
                    df.index = df.index.tz_localize("UTC")
                else:
                    df.index = df.index.tz_convert("UTC")
                    
                return DataFetcher._drop_incomplete_bar(df, timeframe)
            except Exception as e:
                # Silent retry
                if attempt < max_retries - 1:
                    time.sleep(backoff ** attempt)
                    continue
                return None
        return None

    @staticmethod
    def fetch_range(symbol: str, timeframe: str, start: str, end: str) -> Optional[pd.DataFrame]:
        """
        Fetch historical data for a symbol within a date range with retries.
        """
        import time
        max_retries = 3
        backoff = 2
        
        for attempt in range(max_retries):
            try:
                session = DataFetcher._get_session()
                df = yf.download(
                    tickers=symbol,
                    start=start,
                    end=end,
                    interval=timeframe,
                    session=session,
                    progress=False,
                    auto_adjust=True,
                    threads=False
                )
                
                if df is None or df.empty:
                    if attempt < max_retries - 1:
                        time.sleep(backoff ** attempt)
                        continue
                    return None
                
                # Flatten MultiIndex columns if necessary
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                
                df = df.rename(columns={
                    'Open': 'open',
                    'High': 'high',
                    'Low': 'low', 
                    'Close': 'close', 
                    'Volume': 'volume'
                })
                if df.index is None or len(df.index) == 0:
                    return None
                    
                # Handle timezone conversion safely
                if df.index.tz is None:
                    df.index = df.index.tz_localize("UTC")
                else:
                    df.index = df.index.tz_convert("UTC")
                    
                return DataFetcher._drop_incomplete_bar(df, timeframe)
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(backoff ** attempt)
                    continue
                return None
        return None

    @staticmethod
    async def fetch_data_async(symbol: str, timeframe: str, period: str = "5d") -> Optional[pd.DataFrame]:
        """Asynchronous fetch with intelligent provider routing (MT5 vs yfinance)."""
        import asyncio
        provider = DataFetcher._get_provider()

        # 1. Attempt MT5 Broker Fetch if selected
        if provider == "mt5" and not any(m in symbol for m in ["DXY", "DX-Y", "TNX", "^TNX"]):
            try:
                from core.trade_executor import get_executor
                executor = get_executor()
                # Map period to limit (approximate)
                limit_map = {"5d": 500, "10d": 1000, "25d": 2500, "3mo": 5000, "6mo": 9999}
                limit = limit_map.get(period, 500)
                
                broker_data = await asyncio.wait_for(
                    executor.get_historical_data(symbol, timeframe, limit),
                    timeout=10.0
                )
                if broker_data:
                    df = pd.DataFrame(broker_data)
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
                    df = df.set_index('timestamp')
                    if df.index.tz is None:
                        df.index = df.index.tz_localize("UTC")
                    else:
                        df.index = df.index.tz_convert("UTC")
                    return DataFetcher._drop_incomplete_bar(df, timeframe)
            except asyncio.TimeoutError:
                print(f"⚠️  MT5 fetch TIMED OUT for {symbol}, falling back to yfinance.")
                logging.debug(f"MT5 fetch timed out for {symbol}, falling back.")
            except Exception as e:
                print(f"⚠️  MT5 fetch failed for {symbol}: {e}. Falling back to yfinance.")
                logging.debug(f"MT5 fetch failed for {symbol}, falling back to yfinance: {e}")

        # 2. Fallback to yfinance (Thread-safe)
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, DataFetcher.fetch_data, symbol, timeframe, period),
                timeout=120
            )
        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            logging.warning(f"Async fetch timed out/cancelled for {symbol} {timeframe}: {e}")
            return None

    @staticmethod
    async def fetch_range_async(symbol: str, timeframe: str, start: str, end: str) -> Optional[pd.DataFrame]:
        """Asynchronous wrapper for fetch_range using threads."""
        import asyncio
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, DataFetcher.fetch_range, symbol, timeframe, start, end),
                timeout=120
            )
        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            logging.warning(f"Async fetch_range timed out/cancelled for {symbol} {timeframe}: {e}")
            return None

    @staticmethod
    def _drop_incomplete_bar(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        """Avoid scoring/executing against the currently forming candle."""
        if df is None or df.empty:
            return df
        tf = str(timeframe).lower()
        interval_map = {
            "1m": timedelta(minutes=1),
            "5m": timedelta(minutes=5),
            "15m": timedelta(minutes=15),
            "30m": timedelta(minutes=30),
            "1h": timedelta(hours=1),
            "60m": timedelta(hours=1),
            "4h": timedelta(hours=4),
            "1d": timedelta(days=1),
        }
        interval = interval_map.get(tf)
        if not interval:
            return df
        try:
            last_ts = df.index[-1]
            now = pd.Timestamp.utcnow()
            if last_ts.tz is None:
                last_ts = last_ts.tz_localize("UTC")
            else:
                last_ts = last_ts.tz_convert("UTC")
            if now < last_ts + interval:
                return df.iloc[:-1]
        except Exception:
            return df
        return df

    @staticmethod
    async def get_latest_data(symbols: list = SYMBOLS) -> Dict[str, Dict[str, pd.DataFrame]]:
        """
        Fetches multi-timeframe data for all symbols concurrently.
        """
        from config.config import DXY_SYMBOL, TNX_SYMBOL
        import asyncio
        
        results = {}
        
        # 1. Prepare Fetch Tasks
        tasks = []
        task_info = []

        # Macro Narrative
        tasks.append(DataFetcher.fetch_data_async(DXY_SYMBOL, "1h", period="10d"))
        task_info.append(('DXY', 'h1'))
        
        tasks.append(DataFetcher.fetch_data_async(TNX_SYMBOL, "1h", period="10d"))
        task_info.append(('^TNX', 'h1'))
        
        # Macro Daily (D1) for Bias
        tasks.append(DataFetcher.fetch_data_async(DXY_SYMBOL, "1d", period="3mo"))
        task_info.append(('DXY', 'd1'))
        
        tasks.append(DataFetcher.fetch_data_async(TNX_SYMBOL, "1d", period="3mo"))
        task_info.append(('^TNX', 'd1'))

        for symbol in symbols:
            # Add specific timeframe tasks with sufficient lookback for 200-period EMAs
            # Narrative (1H) - H1 needs > 200 rows. (Forex is 24/5, so 20d = ~240 rows)
            tasks.append(DataFetcher.fetch_data_async(symbol, NARRATIVE_TF, period="3mo"))
            task_info.append((symbol, 'h1'))
            # Structure (15M)
            tasks.append(DataFetcher.fetch_data_async(symbol, STRUCTURE_TF, period="25d"))
            task_info.append((symbol, 'm15'))
            # Entry (5M) - M5 or M15 needs plenty of data
            tasks.append(DataFetcher.fetch_data_async(symbol, ENTRY_TF, period="10d"))
            task_info.append((symbol, 'm5'))
            # Institutional (4H) - Additional context
            tasks.append(DataFetcher.fetch_data_async(symbol, INSTITUTIONAL_TF, period="3mo"))
            task_info.append((symbol, 'h4'))
            # Daily Bias (D1)
            tasks.append(DataFetcher.fetch_data_async(symbol, "1d", period="6mo"))
            task_info.append((symbol, 'd1'))

        # 2. Execute Tasks Concurrently
        fetched_dfs = await asyncio.gather(*tasks)

        # 3. Organize Results
        for (symbol, tf), df in zip(task_info, fetched_dfs):
            if df is None or df.empty:
                continue
            
            if symbol == 'DXY':
                key = 'DXY' if tf == 'h1' else f'DXY_{tf}'
                results[key] = IndicatorCalculator.add_indicators(df, tf)
                continue
                
            if symbol == '^TNX':
                key = '^TNX' if tf == 'h1' else f'^TNX_{tf}'
                results[key] = IndicatorCalculator.add_indicators(df, tf)
                continue

            if symbol not in results:
                results[symbol] = {}
            results[symbol][tf] = df

        # 4. Final Verification (Ensure all TFs present)
        final_results = {}
        if 'DXY' in results:
            final_results['DXY'] = results['DXY']
            
        if '^TNX' in results:
            final_results['^TNX'] = results['^TNX']
            
        for symbol in symbols:
            s_data = results.get(symbol, {})
            # Ensure d1 is also present
            if 'h1' in s_data and 'm15' in s_data and 'm5' in s_data and 'h4' in s_data and 'd1' in s_data:
                final_results[symbol] = s_data
                
        return final_results
