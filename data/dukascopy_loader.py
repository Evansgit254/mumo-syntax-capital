"""
Dukascopy Historical Data Loader
=================================
Reads M1 CSV files downloaded from Dukascopy's free data portal:
    https://www.dukascopy.com/swiss/english/marketwatch/historical/

How to Download:
  1. Go to the URL above
  2. Select a symbol (e.g. EUR/USD), select M1 timeframe
  3. Pick your date range (can go back to 2003)
  4. Click Download → CSV
  5. Save to data/dukascopy/<SYMBOL>/<filename.csv>
     e.g. data/dukascopy/EURUSD/EURUSD_Candlestick_1_M_BID_01.01.2024-31.12.2024.csv

Dukascopy CSV format (GMT):
    Gmt time,Open,High,Low,Close,Volume
    03.01.2022 00:00:00.000,1.13518,1.13521,1.13510,1.13519,45.87

This loader:
  - Reads and cleans the Dukascopy M1 format
  - Resamples to M5, M15, M30, H1 on request
  - Maps Dukascopy symbol names to yfinance ticker format
  - Returns a standard OHLCV DataFrame ready for IndicatorCalculator
"""

import os
import glob
import pandas as pd
from datetime import datetime, timezone
from threading import RLock
from typing import Optional

# ── Symbol Mapping ─────────────────────────────────────────────────────────────
# Maps common Dukascopy naming variants to our yfinance-compatible tickers
DUKASCOPY_TO_YFINANCE = {
    # Dukascopy name   : yfinance ticker
    "EURUSD":           "EURUSD=X",
    "EUR_USD":          "EURUSD=X",
    "GBPUSD":           "GBPUSD=X",
    "GBP_USD":          "GBPUSD=X",
    "USDJPY":           "USDJPY=X",
    "USD_JPY":          "USDJPY=X",
    "AUDUSD":           "AUDUSD=X",
    "AUD_USD":          "AUDUSD=X",
    "NZDUSD":           "NZDUSD=X",
    "NZD_USD":          "NZDUSD=X",
    "GBPJPY":           "GBPJPY=X",
    "GBP_JPY":          "GBPJPY=X",
    "USDCAD":           "USDCAD=X",
    "USD_CAD":          "USDCAD=X",
    "XAUUSD":           "GC=F",       # Gold spot → Gold futures
    "XAU_USD":          "GC=F",
    "GOLD":             "GC=F",
    "XTIUSD":           "CL=F",       # WTI Oil → Crude Oil futures
    "XTI_USD":          "CL=F",
    "USOIL":            "CL=F",
    "DXY":              "DX-Y.NYB",   # US Dollar Index
}

# The reverse: yfinance ticker → expected Dukascopy folder name
YFINANCE_TO_DUKASCOPY = {v: k for k, v in DUKASCOPY_TO_YFINANCE.items()}


class DukascopyLoader:
    """
    Loads historical M1 OHLCV data from Dukascopy CSV files,
    resamples to any standard timeframe, and returns pandas DataFrames
    compatible with the rest of the SMC signal system.

    Usage:
        loader = DukascopyLoader(base_dir="data/dukascopy")

        # Load M5 data for EURUSD
        df = loader.load("EURUSD=X", timeframe="5min")

        # Load M30 data for Gold
        df = loader.load("GC=F", timeframe="30min")
    """

    TIMEFRAME_RESAMPLE = {
        "1min":  "1min",
        "5min":  "5min",
        "15min": "15min",
        "30min": "30min",
        "1h":    "1h",
        "4h":    "4h",
        "1d":    "1D",
        # yfinance-style aliases
        "5m":    "5min",
        "15m":   "15min",
        "30m":   "30min",
        "1h":    "1h",
    }
    _m1_cache: dict[tuple, pd.DataFrame] = {}
    _cache_lock = RLock()

    def __init__(self, base_dir: str = "data/dukascopy"):
        """
        Args:
            base_dir: Root directory where Dukascopy CSVs are stored.
                      Expects structure: base_dir/<SYMBOL>/*.csv
        """
        self.base_dir = base_dir

    def load(
        self,
        symbol: str,
        timeframe: str = "5min",
        start_date: Optional[str] = None,
        end_date:   Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Load data for a given symbol and resample to the requested timeframe.

        Args:
            symbol:     yfinance-style ticker (e.g. "EURUSD=X", "GC=F")
            timeframe:  Target timeframe ("5min", "15min", "30min", "1h", etc.)
            start_date: Optional filter "YYYY-MM-DD"
            end_date:   Optional filter "YYYY-MM-DD"

        Returns:
            DataFrame with columns [open, high, low, close, volume]
            indexed by UTC datetime, or None if no data found.
        """
        m1_df = self._load_m1(symbol)
        if m1_df is None or m1_df.empty:
            return None

        # Date range filter
        if start_date:
            m1_df = m1_df[m1_df.index >= pd.Timestamp(start_date, tz="UTC")]
        if end_date:
            m1_df = m1_df[m1_df.index <= pd.Timestamp(end_date + " 23:59", tz="UTC")]

        if m1_df.empty:
            return None

        # Resample to target timeframe
        rule = self.TIMEFRAME_RESAMPLE.get(timeframe, timeframe)
        return self._resample(m1_df, rule)

    def load_for_event(
        self,
        symbol:        str,
        event_date:    str,
        event_hour_utc: int,
        timeframe:     str = "5min",
        bars_before:   int = 3,
        bars_after:    int = 12,
    ) -> Optional[pd.DataFrame]:
        """
        Load a slice of data centred around a specific news event.
        Fetches an event-centered price window for historical research.

        Args:
            symbol:         yfinance-style ticker
            event_date:     "YYYY-MM-DD"
            event_hour_utc: UTC hour of the event (e.g. 13 for 13:30 release)
            timeframe:      Candle timeframe for analysis
            bars_before:    Number of bars before event to include
            bars_after:     Number of bars after event to include

        Returns:
            Sliced DataFrame or None.
        """
        from datetime import timedelta

        event_dt = pd.Timestamp(event_date, tz="UTC").replace(hour=event_hour_utc)

        # Load the full day ±1 day to ensure we capture the event window
        start = (event_dt - pd.Timedelta(hours=2)).strftime("%Y-%m-%d")
        end   = (event_dt + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

        df = self.load(symbol, timeframe=timeframe, start_date=start, end_date=end)
        if df is None or df.empty:
            return None

        # Determine bar width in minutes
        bar_minutes = self._timeframe_minutes(timeframe)

        # Slice around event
        window_start = event_dt - pd.Timedelta(minutes=bars_before * bar_minutes)
        window_end   = event_dt + pd.Timedelta(minutes=bars_after  * bar_minutes)

        sliced = df[(df.index >= window_start) & (df.index <= window_end)]
        return sliced if len(sliced) >= bars_after else None

    def list_available_symbols(self) -> list:
        """Returns a list of yfinance-style symbols available in base_dir."""
        if not os.path.isdir(self.base_dir):
            return []
        folders = [d for d in os.listdir(self.base_dir)
                   if os.path.isdir(os.path.join(self.base_dir, d))]
        result = []
        for folder in folders:
            yf_ticker = DUKASCOPY_TO_YFINANCE.get(folder.upper(), folder)
            result.append(yf_ticker)
        return result

    # ── Internal ───────────────────────────────────────────────────────────────

    def _load_m1(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        Finds and loads all M1 CSV files for the given symbol.
        Multiple CSV files (e.g. year-by-year) are combined and sorted.
        """
        folder = self._find_folder(symbol)
        if folder is None:
            return None

        csv_paths = sorted(glob.glob(os.path.join(folder, "*.csv")))
        if not csv_paths:
            return None

        signature = self._csv_signature(csv_paths)
        cache_key = (os.path.abspath(folder), signature)
        with self._cache_lock:
            cached = self._m1_cache.get(cache_key)
        if cached is not None:
            return cached

        parquet_path = os.path.join(folder, "_m1_cache.parquet")
        parquet_df = self._load_parquet_cache(parquet_path, signature)
        if parquet_df is not None:
            with self._cache_lock:
                self._m1_cache[cache_key] = parquet_df
            return parquet_df

        frames = []
        for path in csv_paths:
            df = self._parse_csv(path)
            if df is not None and not df.empty:
                frames.append(df)

        if not frames:
            return None

        combined = pd.concat(frames)
        combined.sort_index(inplace=True)
        combined = combined[~combined.index.duplicated(keep='first')]
        self._write_parquet_cache(parquet_path, combined, signature)
        with self._cache_lock:
            self._m1_cache[cache_key] = combined
        return combined

    def _csv_signature(self, csv_paths: list[str]) -> tuple:
        """Builds a cheap freshness signature for cache invalidation."""
        return tuple(
            (os.path.abspath(path), os.path.getsize(path), os.path.getmtime(path))
            for path in csv_paths
        )

    def _load_parquet_cache(self, parquet_path: str, signature: tuple) -> Optional[pd.DataFrame]:
        """Loads a local M1 Parquet cache when it is fresher than the CSV source set."""
        if not os.path.exists(parquet_path):
            return None
        latest_csv_mtime = max(item[2] for item in signature)
        if os.path.getmtime(parquet_path) < latest_csv_mtime:
            return None
        try:
            df = pd.read_parquet(parquet_path)
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index, utc=True)
            elif df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            return df
        except Exception:
            return None

    def _write_parquet_cache(self, parquet_path: str, df: pd.DataFrame, signature: tuple) -> None:
        """Writes a best-effort Parquet cache; CSV remains the source of truth."""
        if not signature:
            return
        try:
            df.to_parquet(parquet_path)
        except Exception:
            return

    def _find_folder(self, symbol: str) -> Optional[str]:
        """Finds the folder for a given symbol (yfinance or Dukascopy name)."""
        if not os.path.isdir(self.base_dir):
            return None

        # Try yfinance → Dukascopy name mapping
        duka_name = YFINANCE_TO_DUKASCOPY.get(symbol, symbol)
        # Also try the raw symbol with slashes and special chars stripped
        candidates = [
            symbol,
            symbol.replace("=X", "").replace("=", "").replace("-", ""),
            duka_name,
            symbol.upper(),
            duka_name.upper(),
        ]

        for name in candidates:
            path = os.path.join(self.base_dir, name)
            if os.path.isdir(path):
                return path

        return None

    def _parse_csv(self, path: str) -> Optional[pd.DataFrame]:
        """
        Parses a single Dukascopy M1 CSV file into a standard OHLCV DataFrame.

        Handles two common Dukascopy formats:
          1. "Gmt time,Open,High,Low,Close,Volume"   (standard)
          2. "Date,Time,Open,High,Low,Close,Volume"  (older export)
        """
        try:
            # Peek at header to detect format
            with open(path, 'r') as f:
                first_line = f.readline().strip().lower()

            if "gmt time" in first_line:
                df = pd.read_csv(path, parse_dates=["Gmt time"],
                                 date_format="%d.%m.%Y %H:%M:%S.%f")
                df.rename(columns={"Gmt time": "datetime"}, inplace=True)

            elif "local time" in first_line:
                df = pd.read_csv(path, parse_dates=["Local time"],
                                 date_format="%d.%m.%Y %H:%M:%S.%f")
                df.rename(columns={"Local time": "datetime"}, inplace=True)

            elif "date" in first_line and "time" in first_line:
                df = pd.read_csv(path)
                df["datetime"] = pd.to_datetime(
                    df["Date"].astype(str) + " " + df["Time"].astype(str)
                )
                df.drop(columns=["Date", "Time"], errors='ignore', inplace=True)

            elif "," in first_line and len(first_line.split(",")) >= 6 and not any(c.isalpha() for c in first_line.replace(".","").replace(":","").replace(",","")):
                # No-header MetaTrader format: 2024.01.01,17:00,1.104270,...
                df = pd.read_csv(path, header=None, names=["date", "time", "open", "high", "low", "close", "volume"])
                df["datetime"] = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str))
                df.drop(columns=["date", "time"], inplace=True)

            elif ";" in first_line and len(first_line.split(";")) >= 6 and not any(c.isalpha() for c in first_line.replace(".","").replace(":","").replace(";","").replace(" ","")):
                # HistData ASCII semicolon format: 20220103 170000;1.13700;1.13700;1.13700;1.13700;0
                df = pd.read_csv(path, sep=";", header=None, names=["datetime", "open", "high", "low", "close", "volume"])
                df["datetime"] = pd.to_datetime(df["datetime"].astype(str).str.strip(), format="%Y%m%d %H%M%S")

            else:
                # Try generic parse with first column as datetime
                df = pd.read_csv(path, parse_dates=[0])
                df.rename(columns={df.columns[0]: "datetime"}, inplace=True)

            # Normalize column names to lowercase
            df.columns = [c.lower().strip() for c in df.columns]
            df.rename(columns={
                "open":   "open",
                "high":   "high",
                "low":    "low",
                "close":  "close",
                "volume": "volume",
            }, inplace=True)

            # Set UTC-aware datetime index
            df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors='coerce')
            df.dropna(subset=["datetime"], inplace=True)
            df.set_index("datetime", inplace=True)

            # Keep only OHLCV
            keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
            df = df[keep]

            # Ensure numeric
            for col in keep:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df.dropna(subset=["open", "high", "low", "close"], inplace=True)

            return df

        except Exception as e:
            print(f"  ⚠️  Failed to parse {path}: {e}")
            return None

    def _resample(self, df: pd.DataFrame, rule: str) -> pd.DataFrame:
        """Resamples M1 OHLCV data to a coarser timeframe."""
        agg = {
            "open":   "first",
            "high":   "max",
            "low":    "min",
            "close":  "last",
        }
        if "volume" in df.columns:
            agg["volume"] = "sum"

        resampled = df.resample(rule).agg(agg)
        resampled.dropna(subset=["open", "close"], inplace=True)
        return resampled

    def _timeframe_minutes(self, timeframe: str) -> int:
        """Returns the number of minutes in a timeframe string."""
        mapping = {
            "1min": 1, "5min": 5, "15min": 15, "30min": 30,
            "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240,
        }
        return mapping.get(timeframe, 5)


# ── Quick Verification CLI ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    loader = DukascopyLoader(base_dir="data/dukascopy")
    available = loader.list_available_symbols()

    print("=" * 60)
    print("DUKASCOPY DATA LOADER — VERIFICATION")
    print("=" * 60)
    print(f"Base directory : data/dukascopy/")
    print(f"Available symbols: {available or 'NONE FOUND'}")
    print()

    if not available:
        print("📂 No data found. Please download CSV files from:")
        print("   https://www.dukascopy.com/swiss/english/marketwatch/historical/")
        print()
        print("   Expected directory structure:")
        print("   data/dukascopy/")
        print("   ├── EURUSD/")
        print("   │   └── EURUSD_Candlestick_1_M_BID_01.01.2024-31.12.2024.csv")
        print("   ├── GBPUSD/")
        print("   └── XAUUSD/")
        sys.exit(0)

    # Test load for each available symbol
    for sym in available:
        df = loader.load(sym, timeframe="5min")
        if df is not None and not df.empty:
            print(f"  ✅ {sym:15s} → {len(df):,} M5 bars  "
                  f"[{df.index[0].date()} → {df.index[-1].date()}]")
        else:
            print(f"  ❌ {sym:15s} → load failed")
