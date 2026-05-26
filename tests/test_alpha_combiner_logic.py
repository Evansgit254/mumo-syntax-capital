import pytest
from core.alpha_combiner import AlphaCombiner

def test_alpha_combiner_basic_buy():
    """Verify combined signals for strong buy scenario"""
    factors = {
        'velocity': 2.0,   # Strong bullish velocity
        'zscore': -2.5,    # Deep oversold (reversion BUY)
        'relative': 1.0    # Outperforming benchmark
    }
    
    signal = AlphaCombiner.combine(factors, regime="TRENDING_BULL")
    # With TRENDING_BULL weights: velocity=0.7, zscore=0.1
    # 2.0 * 0.7 + (-2.5) * 0.1 = 1.4 - 0.25 = 1.15
    assert signal > 1.0

def test_alpha_combiner_basic_sell():
    """Verify combined signals for strong sell scenario"""
    factors = {
        'velocity': -2.0,  # Strong bearish velocity
        'zscore': 2.5,     # Overbought (reversion SELL)
        'relative': -1.0   # Lagging benchmark
    }
    
    signal = AlphaCombiner.combine(factors, regime="TRENDING_BEAR")
    # Should be negative
    assert signal < -1.0

def test_alpha_combiner_normalization():
    """Verify normalization and score calculation"""
    factors = {'velocity': 5.0, 'zscore': 5.0, 'relative': 5.0} # Extreme
    
    # Check that quality score is bounded effectively (typically 0-10)
    # calculate_quality_score(factors, signal, base_boost)
    score = AlphaCombiner.calculate_quality_score(factors, 2.5)
    assert 0 <= score <= 10.0

def test_alpha_combiner_empty():
    """Verify handling of empty or missing factors"""
    factors = {}
    signal = AlphaCombiner.combine(factors)
    assert signal == 0.0
    
    score = AlphaCombiner.calculate_quality_score(factors, 0.0)
    assert score == 0.0
