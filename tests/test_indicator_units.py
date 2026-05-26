import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch
from indicators.calculations import IndicatorCalculator

def test_add_indicators_basic():
    dates = pd.date_range(start='2023-01-01', periods=50, freq='h')
    df = pd.DataFrame({
        'high': [100, 102, 101, 103, 105] * 10,
        'low': [98, 99, 97, 100, 101] * 10,
        'close': [99, 101, 98, 102, 104] * 10
    }, index=dates)
    result = IndicatorCalculator.add_indicators(df, timeframe="h1")
    assert 'rsi' in result.columns
    assert 'atr' in result.columns
    assert 'ema_20' in result.columns
    assert not result['rsi'].dropna().empty

def test_get_market_structure():
    df = pd.DataFrame({
        'high': [100, 110, 100, 120, 100] * 5,
        'low': [90, 100, 90, 110, 90] * 5,
        'close': [95, 105, 95, 115, 95] * 5
    })
    result = IndicatorCalculator.get_market_structure(df)
    assert 'fvg_bullish' in result.columns
    assert 'bos_buy' in result.columns

def test_calculate_adr():
    # Need enough data for resampling 'D'
    dates = pd.date_range(start='2023-01-01', periods=100, freq='h')
    df = pd.DataFrame({
        'high': np.random.random(100) + 100,
        'low': np.random.random(100) + 90,
        'close': np.random.random(100) + 95
    }, index=dates)
    adr = IndicatorCalculator.calculate_adr(df)
    assert isinstance(adr, pd.Series)
    assert len(adr) == 100

def test_calculate_h4_levels():
    df = pd.DataFrame({
        'high': [100, 110, 105, 115, 120] * 5,
        'low': [90, 100, 95, 110, 115] * 5,
        'close': [95, 105, 100, 112, 118] * 5
    })
    levels = IndicatorCalculator.calculate_h4_levels(df)
    assert 'h4_high' in levels
    assert 'h4_low' in levels

def test_add_indicators_h4():
    dates = pd.date_range(start='2023-01-01', periods=50, freq='h')
    df = pd.DataFrame({
        'high': [100, 102, 101, 103, 105] * 10,
        'low': [98, 99, 97, 100, 101] * 10,
        'close': [99, 101, 98, 102, 104] * 10
    }, index=dates)
    result = IndicatorCalculator.add_indicators(df, timeframe="h4")
    assert 'h4_high' in result.columns

def test_get_market_regime_choppy():
    df = pd.DataFrame({
        'atr': [1.0] * 60,
        'close': [100] * 60
    })
    # Mock calculate_ema_slope to return 0
    with patch('indicators.calculations.IndicatorCalculator.calculate_ema_slope', return_value=0.0):
        regime = IndicatorCalculator.get_market_regime(df)
        assert regime in ["CHOPPY", "RANGING", "LOW_VOL_RANGE"]
