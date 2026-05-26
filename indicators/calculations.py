import pandas as pd
import pandas_ta_classic as ta
from config.config import (
    EMA_FAST, EMA_SLOW, RSI_PERIOD, ATR_PERIOD, ATR_AVG_PERIOD, 
    EMA_TREND, ADR_PERIOD
)
from datetime import time

class IndicatorCalculator:
    @staticmethod
    def add_indicators(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        """
        Adds EMA, RSI, and ATR to the dataframe.
        """
        if df.empty:
            return df

        # Safety: flatten MultiIndex columns (yfinance can return these)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        # Deduplicate column names if present (can happen after flatten)
        if df.columns.duplicated().any():
            df = df.loc[:, ~df.columns.duplicated()]

        # Standardize column casing (V35.1 Recovery)
        df.columns = [c.lower() for c in df.columns]

        # EMAs
        df[f'ema_{EMA_FAST}'] = ta.ema(df['close'], length=EMA_FAST)
        df[f'ema_{EMA_SLOW}'] = ta.ema(df['close'], length=EMA_SLOW)
        
        df[f'ema_{EMA_TREND}'] = ta.ema(df['close'], length=EMA_TREND)
        df['ema_20'] = ta.ema(df['close'], length=20)
        df['ema_50'] = ta.ema(df['close'], length=50)
        df['ema_100'] = ta.ema(df['close'], length=100)
        df['ema_200'] = ta.ema(df['close'], length=200)  # For swing strategy mean reversion

        # RSI
        df['rsi'] = ta.rsi(df['close'], length=RSI_PERIOD)

        # ATR
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=ATR_PERIOD)
        
        # ADX (Average Directional Index) for trend strength
        # pandas_ta_classic: adx(high, low, close, length) -> returns DF with ADX, DIP, DIN
        adx_df = ta.adx(df['high'], df['low'], df['close'], length=14)
        if adx_df is not None:
            df['adx'] = adx_df['ADX_14']
            df['di_plus'] = adx_df['DMP_14']
            df['di_minus'] = adx_df['DMN_14']
        
        # ATR Average for volatility filter
        df['atr_avg'] = df['atr'].rolling(window=ATR_AVG_PERIOD).mean()
        df['atr_ma_20'] = df['atr'].rolling(window=20).mean() # Restored for Price Action
        
        # ADR (Average Daily Range) - Only for H1 as it's the anchor TF for daily range
        if timeframe == "h1":
            df['adr'] = IndicatorCalculator.calculate_adr(df)
            
        if timeframe == "h4":
            h4_lvls = IndicatorCalculator.calculate_h4_levels(df)
            df['h4_high'] = h4_lvls['h4_high']
            df['h4_low'] = h4_lvls['h4_low']
            
        # Z-Score (20-period) for Statistical Arbitrage strategy
        rolling_mean = df['close'].rolling(20).mean()
        rolling_std = df['close'].rolling(20).std()
        df['zscore_20'] = (df['close'] - rolling_mean) / rolling_std.replace(0, float('nan'))

        # Regime Detection
        ema_trend_col = f'ema_{EMA_TREND}'
        df['ema_slope'] = ((df[ema_trend_col] - df[ema_trend_col].shift(3)) / df[ema_trend_col].shift(3)) * 100
        df['vol_ratio'] = df['atr'] / df['atr'].rolling(50).mean()
        df['regime'] = "RANGING"
        df.loc[(df['vol_ratio'] > 1.2) & (df['ema_slope'].abs() > 0.05), 'regime'] = "TRENDING"
        df.loc[(df['vol_ratio'] < 0.8), 'regime'] = "CHOPPY"

        return df

    @staticmethod
    def get_market_structure(df: pd.DataFrame) -> pd.DataFrame:
        """
        Identify FVGs and BOS in a vectorized way using rolling windows.
        """
        # Bullish FVG: Low[0] > High[-2]
        is_bull_fvg = (df['low'] > df['high'].shift(2))
        df['fvg_bullish'] = is_bull_fvg.rolling(10).max().fillna(0).astype(bool)
        
        # Bearish FVG: High[0] < Low[-2]
        is_bear_fvg = (df['high'] < df['low'].shift(2))
        df['fvg_bearish'] = is_bear_fvg.rolling(10).max().fillna(0).astype(bool)
        
        # BOS (Break of Structure) - Simplified vectorized logic
        # Buy BOS: Close > High of last 10 bars (Rolling 12 for SMC match)
        is_bos_buy = (df['close'] > df['high'].shift(1).rolling(10).max())
        df['bos_buy'] = is_bos_buy.rolling(12).max().fillna(0).astype(bool)
        
        is_bos_sell = (df['close'] < df['low'].shift(1).rolling(10).min())
        df['bos_sell'] = is_bos_sell.rolling(12).max().fillna(0).astype(bool)
        
        return df

    @staticmethod
    def calculate_adr(h1_df: pd.DataFrame) -> pd.Series:
        """
        Calculates the Average Daily Range (High - Low) from H1 data in a vectorized way.
        """
        if h1_df.empty: return pd.Series(index=h1_df.index, data=0.0)
        
        # Calculate daily ranges
        daily_high = h1_df['high'].resample('D').max()
        daily_low = h1_df['low'].resample('D').min()
        daily_range = daily_high - daily_low
        
        # V19.2 SENIOR QUANT FIX: Shift(1) to avoid Look-Ahead Bias
        # Ensure 'today' only knows 'yesterday's' ADR.
        adr_ma = daily_range.shift(1).rolling(window=ADR_PERIOD).mean()
        
        # Reindex back to original timeframe for easy lookup
        return adr_ma.reindex(h1_df.index).ffill().fillna(0.0)


    @staticmethod
    def calculate_ema_slope(df: pd.DataFrame, ema_col: str) -> float:
        """
        Calculates the normalized velocity (slope) of an EMA.
        Returns % change over the last 3 bars.
        """
        if df.empty or ema_col not in df.columns: return 0.0
        
        subset = df[ema_col].tail(3)
        if len(subset) < 3: return 0.0
        
        start_val = subset.iloc[0]
        end_val = subset.iloc[-1]
        
        if start_val == 0: return 0.0
        
        # Normalized slope in % change
        slope = ((end_val - start_val) / start_val) * 100
        return round(slope, 4)

    @staticmethod
    def get_previous_candle_range(df: pd.DataFrame) -> dict:
        """
        Returns the high/low of the previous closed candle.
        """
        if df.empty or len(df) < 2: return None
        prev = df.iloc[-2]
        return {
            'high': prev['high'],
            'low': prev['low'],
            'close': prev['close'],
            'time': df.index[-2]
        }

    @staticmethod
    def calculate_h4_levels(df: pd.DataFrame) -> pd.DataFrame:
        """
        Pre-calculates H4 swing highs/lows for every bar vectorized.
        """
        if df.empty: return pd.DataFrame(index=df.index, data={'h4_high': 0, 'h4_low': 0})
        
        # Rolling min/max of last 10 candles
        res = pd.DataFrame(index=df.index)
        res['h4_high'] = df['high'].shift(1).rolling(10).max()
        res['h4_low'] = df['low'].shift(1).rolling(10).min()
        return res.ffill().fillna(0.0)


    @staticmethod
    def get_market_regime(df: pd.DataFrame) -> str:
        """
        Detects the current market regime based on volatility and trend.
        V35.0: Relays to Unified Core Registry.
        """
        from core.market_regime import detect_regime
        res = detect_regime(df)
        return res['regime']

