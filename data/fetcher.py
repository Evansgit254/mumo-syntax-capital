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

# Suppress noisy warnings
warnings.simplefilter(action='ignore', category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

class DataFetcher:
    _session = None

    @staticmethod
    def _get_session():
        if DataFetcher._session is None:
            # impersonate="chrome" is critical for bypassing Yahoo Finance anti-scraping
            if hasattr(requests_cffi, "Session"):
                try:
                    DataFetcher._session = requests_cffi.Session(impersonate="chrome")
                except TypeError:
                    # Fallback for standard requests if curl_cffi not present or older version
                    import requests
                    DataFetcher._session = requests.Session()
            else:
                DataFetcher._session = requests_cffi.Session()
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
                    
                return df
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
                    
                return df
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(backoff ** attempt)
                    continue
                return None
        return None

    @staticmethod
    async def fetch_data_async(symbol: str, timeframe: str, period: str = "5d") -> Optional[pd.DataFrame]:
        """Asynchronous wrapper for fetch_data using threads."""
        import asyncio
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
