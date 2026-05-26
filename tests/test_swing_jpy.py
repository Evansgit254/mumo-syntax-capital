import pytest
import pandas as pd
import numpy as np
from strategies.swing_quant_strategy import SwingQuantStrategy
from unittest.mock import patch, MagicMock

@pytest.fixture
def jpy_data():
    df = pd.DataFrame({
        'close': [150.0] * 200,
        'high': [150.5] * 200,
        'low': [149.5] * 200,
        'atr': [0.5] * 200
    })
    return {'h1': df}

@pytest.mark.asyncio
async def test_swing_strategy_jpy_selectivity(jpy_data):
    strategy = SwingQuantStrategy()
    market_context = {'macro_bias': {'global': 'BULLISH'}}
    
    # Mock Indicators to return a regime and alpha factors
    # velocity=2.0 ensures alpha_signal > 0.90 JPY threshold (0.4*2.0 + 0.5*0.5 + 0.05*0.5 + 0.05*0.5 = 1.10)
    with patch('indicators.calculations.IndicatorCalculator.get_market_regime', return_value='TRENDING'), \
         patch('core.alpha_factors.AlphaFactors.velocity_alpha', return_value=2.0), \
         patch('core.alpha_factors.AlphaFactors.mean_reversion_zscore', return_value=0.5), \
         patch('core.alpha_factors.AlphaFactors.momentum_alpha', return_value=0.5), \
         patch('core.alpha_factors.AlphaFactors.volatility_regime_alpha', return_value=0.5), \
         patch('core.alpha_combiner.AlphaCombiner.calculate_quality_score', return_value=8.0), \
         patch('core.filters.macro_filter.MacroFilter.is_macro_safe', return_value=True), \
         patch('core.filters.risk_manager.RiskManager.calculate_lot_size', return_value={'lot_size': 0.01}), \
         patch('core.filters.risk_manager.RiskManager.calculate_optimal_rr', return_value={'tp1_rr': 1.5, 'tp2_rr': 2.5, 'tp3_rr': 3.5, 'is_friction_heavy': False}):
             
        # JPY threshold is 0.90. alpha_signal will be high if factors are high.
        res = await strategy.analyze('USDJPY', jpy_data, [], market_context)
        
        # Verify it uses JPY logic (tighter threshold/multiplier)
        assert res is not None
        assert res['direction'] == 'BUY'
        # sl_distance = atr * 2.5 = 0.5 * 2.5 = 1.25. sl = 150 - 1.25 = 148.75
        assert res['sl'] == 148.75

@pytest.mark.asyncio
async def test_swing_strategy_news_unsafe(jpy_data):
    strategy = SwingQuantStrategy()
    news = [{'impact': 'High', 'currency': 'USD'}]
    
    with patch('core.filters.news_filter.NewsFilter.is_safe_to_trade', return_value=False):
        res = await strategy.analyze('EURUSD', jpy_data, news, {})
        assert res is None

@pytest.mark.asyncio
async def test_swing_strategy_low_quality(jpy_data):
    strategy = SwingQuantStrategy()
    with patch('core.alpha_combiner.AlphaCombiner.calculate_quality_score', return_value=3.0):
        res = await strategy.analyze('EURUSD', jpy_data, [], {})
        assert res is None
