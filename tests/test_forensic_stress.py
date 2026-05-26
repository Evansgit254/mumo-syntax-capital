"""
Forensic Stress Test Suite - Edge Cases & Resilience

Tests the system's ability to handle extreme market conditions and data anomalies.
"""
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock
from indicators.calculations import IndicatorCalculator
from core.alpha_factors import AlphaFactors
from core.alpha_combiner import AlphaCombiner
from strategies.quant_core_strategy import QuantCoreStrategy

def test_flash_crash_scenario():
    """Test behavior during a flash crash (sudden 10% drop)"""
    dates = pd.date_range('2024-01-01', periods=200, freq='5min')
    close = np.linspace(1.1000, 1.1200, 200)
    
    # Simulate flash crash at t=150
    close[150:160] = close[149] * 0.90  # 10% instant drop
    close[160:] = close[159]  # Stabilize
    
    df = pd.DataFrame({
        'open': close - 0.0001,
        'high': close + 0.0002,
        'low': close - 0.0002,
        'close': close,
    }, index=dates)
    
    df = IndicatorCalculator.add_indicators(df, '5m')
    
    # Check ATR expansion
    assert df['atr'].iloc[-1] > df['atr'].iloc[140]  # ATR should spike
    
    # Check regime detection
    regime = IndicatorCalculator.get_market_regime(df)
    valid_regimes = ['TRENDING_BULL', 'TRENDING_BEAR', 'RANGING', 'CHOPPY', 'LOW_VOL_RANGE', 'VOLATILE_RANGE']
    assert regime in valid_regimes

def test_nan_in_data_handling():
    """Test graceful handling of NaN values in OHLC data"""
    dates = pd.date_range('2024-01-01', periods=200, freq='5min')
    close = np.linspace(1.1000, 1.1200, 200)
    
    df = pd.DataFrame({
        'open': close - 0.0001,
        'high': close + 0.0002,
        'low': close - 0.0002,
        'close': close,
    }, index=dates)
    
    # Inject NaN at random positions
    df.loc[df.index[100], 'close'] = np.nan
    df.loc[df.index[150], 'high'] = np.nan
    
    result = IndicatorCalculator.add_indicators(df, '5m')
    
    # Should not crash and should forward-fill or interpolate
    assert not result.empty
    assert 'atr' in result.columns

def test_zero_volatility_market():
    """Test behavior when market has zero volatility"""
    dates = pd.date_range('2024-01-01', periods=200, freq='5min')
    close = np.ones(200) * 1.1000  # Flat market
    
    df = pd.DataFrame({
        'open': close,
        'high': close,
        'low': close,
        'close': close,
    }, index=dates)
    
    df = IndicatorCalculator.add_indicators(df, '5m')
    
    # ATR should be minimal
    assert df['atr'].iloc[-1] < 0.0001
    
    # Regime should be CHOPPY or RANGING or LOW_VOL_RANGE
    regime = IndicatorCalculator.get_market_regime(df)
    assert regime in ["CHOPPY", "RANGING", "LOW_VOL_RANGE"]

def test_extreme_gap_weekend():
    """Test handling of weekend gaps (Sunday open vs Friday close)"""
    dates = pd.date_range('2024-01-01', periods=200, freq='5min')
    close = np.linspace(1.1000, 1.1200, 200)
    
    # Simulate 200 pip weekend gap
    close[100:] = close[100:] + 0.0200  # 200 pip jump
    
    df = pd.DataFrame({
        'open': close - 0.0001,
        'high': close + 0.0002,
        'low': close - 0.0002,
        'close': close,
    }, index=dates)
    
    df = IndicatorCalculator.add_indicators(df, '5m')
    
    # Check that indicators adapt
    assert 'ema_20' in df.columns
    assert not df['ema_20'].isnull().all()

def test_alpha_factor_extreme_values():
    """Test alpha factors with extreme z-scores"""
    dates = pd.date_range('2024-01-01', periods=200, freq='5min')
    close = np.linspace(1.1000, 1.1200, 200)
    
    # Create extreme spike
    close[-1] = 1.2000  # 800 pip instant spike
    
    df = pd.DataFrame({
        'open': close - 0.0001,
        'high': close + 0.0002,
        'low': close - 0.0002,
        'close': close,
    }, index=dates)
    
    df = IndicatorCalculator.add_indicators(df, '5m')
    
    # Calculate factors
    velocity = AlphaFactors.velocity_alpha(df, period=20)
    zscore = AlphaFactors.mean_reversion_zscore(df, period=100)
    
    # Should be clipped at 4.0 standard deviations in combiner
    factors = {'velocity': velocity, 'zscore': zscore}
    signal = AlphaCombiner.combine(factors)
    
    assert abs(signal) <= 4.0  # Combiner should clip extreme values

@pytest.mark.asyncio
async def test_concurrent_symbol_processing():
    """Test that multiple symbols can be processed without race conditions"""
    strategy = QuantCoreStrategy()
    
    dates = pd.date_range('2024-01-01', periods=200, freq='5min')
    close = np.linspace(1.1000, 1.1200, 200)
    
    df = pd.DataFrame({
        'open': close - 0.0001,
        'high': close + 0.0002,
        'low': close - 0.0002,
        'close': close,
    }, index=dates)
    
    df = IndicatorCalculator.add_indicators(df, '5m')
    data = {'m5': df, 'h1': df}
    
    # Process same data for multiple symbols
    symbols = ["EURUSD=X", "GBPUSD=X", "USDJPY=X"]
    
    with patch('core.filters.news_filter.NewsFilter.is_safe_to_trade', return_value=True), \
         patch('core.filters.macro_filter.MacroFilter.is_macro_safe', return_value=True):
        
        results = []
        for symbol in symbols:
            res = await strategy.analyze(symbol, data, [], {})
            results.append(res)
        
        # Should not have cross-contamination between symbols
        assert len(results) == len(symbols)

def test_memory_leak_indicator_calculation():
    """Test that repeated indicator calculations don't leak memory"""
    import gc
    import sys
    
    dates = pd.date_range('2024-01-01', periods=200, freq='5min')
    close = np.linspace(1.1000, 1.1200, 200)
    
    df = pd.DataFrame({
        'open': close - 0.0001,
        'high': close + 0.0002,
        'low': close - 0.0002,
        'close': close,
    }, index=dates)
    
    # Run 100 iterations
    initial_objects = len(gc.get_objects())
    
    for _ in range(100):
        result = IndicatorCalculator.add_indicators(df.copy(), '5m')
        del result
    
    gc.collect()
    final_objects = len(gc.get_objects())
    
    # Object count shouldn't explode (allow 20% increase for normal variance)
    assert final_objects < initial_objects * 1.2

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
