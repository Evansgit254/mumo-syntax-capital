import pytest
import pandas as pd
import numpy as np
from datetime import datetime
from strategies.crt_strategy import CRTStrategy
from unittest.mock import patch, MagicMock

# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def base_h1_data():
    """300-bar H1 dataframe with indicators."""
    from indicators.calculations import IndicatorCalculator
    dates = pd.date_range(end=datetime(2025, 1, 1, 12, 0), periods=300, freq='h')
    df = pd.DataFrame({
        'open':      [1.1000] * 300,
        'high':      [1.1015] * 300,
        'low':       [1.0985] * 300,
        'close':     [1.1000] * 300,
    }, index=dates)
    return IndicatorCalculator.add_indicators(df, 'h1')


@pytest.fixture
def base_m5_data():
    """300-bar M5 dataframe with indicators."""
    from indicators.calculations import IndicatorCalculator
    dates = pd.date_range(end=datetime(2025, 1, 1, 12, 0), periods=300, freq='5min')
    df = pd.DataFrame({
        'open':  [1.1000] * 300,
        'high':  [1.1005] * 300,
        'low':   [1.0995] * 300,
        'close': [1.1000] * 300,
    }, index=dates)
    return IndicatorCalculator.add_indicators(df, "5m")


@pytest.fixture
def base_m15_data():
    """300-bar M15 dataframe with indicators."""
    from indicators.calculations import IndicatorCalculator
    dates = pd.date_range(end=datetime(2025, 1, 1, 12, 0), periods=300, freq='15min')
    df = pd.DataFrame({
        'open':  [1.1000] * 300,
        'high':  [1.1005] * 300,
        'low':   [1.0995] * 300,
        'close': [1.1000] * 300,
    }, index=dates)
    return IndicatorCalculator.add_indicators(df, "15m")

@pytest.fixture
def base_d1_data():
    """
    300-bar D1 dataframe. Bullish by default: close > open, close > ema_200 (1.0900).
    """
    dates = pd.date_range(end=datetime(2025, 1, 1), periods=300, freq='D')
    df = pd.DataFrame({
        'open':      [1.0950] * 300,
        'high':      [1.1010] * 300,
        'low':       [1.0940] * 300,
        'close':     [1.1000] * 300,   # close > open → bullish day
        'ema_200':   [1.0900] * 300,   # close > ema → bullish D1 bias
        'atr':       [0.0080] * 300,
    }, index=dates)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS: build valid CRT sweep+MSS fixtures
# ─────────────────────────────────────────────────────────────────────────────
# Reference candle = df_h1.iloc[-2] (last closed H1).
# In base_h1_data: all bars default to open=1.1000, high=1.1015, low=1.0985
# → range = 0.0030, ATR = 0.0013, ratio = 2.31 (valid: 0.40–2.5×ATR)
# ref_eq = 1.1000
#
# Valid BULLISH geometry (range=0.0030, ATR=0.0013):
#   sweep extreme: 1.0981 (depth=0.0004 = 0.31 ATR ≥ 0.10 ATR ✓)
#   MSS candle: close=1.0992 > ref_low + 10%*range = 1.0985+0.0003 = 1.0988 ✓
#   sl = max(1.0981-0.00013, 1.0992-0.00104) = max(1.09797, 1.09816) = 1.09816
#   risk = 1.0992 - 1.0982 ≈ 0.0010
#   reward_tp1 = ref_high - entry = 1.1015 - 1.0992 = 0.0023
#   rr = 0.0023 / 0.0010 = 2.3 ≥ 1.5 ✓  quality_score = 7.66 ≥ 7.0 ✓
#
# Valid BEARISH geometry:
#   sweep extreme: 1.1019 (depth=0.0004 = 0.31 ATR ≥ 0.10 ATR ✓)
#   MSS candle: close=1.1008 < ref_high - 10%*range = 1.1015-0.0003 = 1.1012 ✓
#   sl = min(1.1019+0.00013, 1.1008+0.00104) = min(1.10203, 1.10184) = 1.10184
#   risk ≈ 0.0010
#   reward_tp1 = entry - ref_low = 1.1008 - 1.0985 = 0.0023 ✓


def _build_bullish_m5(m5_df):
    """Inject a valid bullish sweep+MSS into the last 3 M5 bars (positions -3, -2, -1)."""
    # candle -3: before the sweep. Top of candle 2 bars prior to MSS. Must be lower than FVG.
    m5_df.iloc[-3, m5_df.columns.get_loc('high')]  = 1.0985
    m5_df.iloc[-3, m5_df.columns.get_loc('low')]   = 1.0980
    m5_df.iloc[-3, m5_df.columns.get_loc('open')]  = 1.0982
    m5_df.iloc[-3, m5_df.columns.get_loc('close')] = 1.0981

    # sweep bar: low below ref_low (1.0985) by 0.0002 → sweep_depth=0.00020=0.154 ATR ≥ 0.10 ATR
    # sl = 1.0983 - 0.00013 = 1.09817, risk = 1.0992 - 1.09817 = 0.00103 ≤ 0.80*ATR=0.00104 ✓
    m5_df.iloc[-2, m5_df.columns.get_loc('low')]   = 1.0983   # sweep extreme
    m5_df.iloc[-2, m5_df.columns.get_loc('high')]  = 1.0993
    m5_df.iloc[-2, m5_df.columns.get_loc('open')]  = 1.0985
    m5_df.iloc[-2, m5_df.columns.get_loc('close')] = 1.0989
    
    # MSS candle: bullish, close > ref_low + 10% range = 1.0988
    # To form FVG, low > candle -3 high. 
    m5_df.iloc[-1, m5_df.columns.get_loc('low')]   = 1.0987
    m5_df.iloc[-1, m5_df.columns.get_loc('open')]  = 1.0988
    m5_df.iloc[-1, m5_df.columns.get_loc('close')] = 1.0992  # entry
    m5_df.iloc[-1, m5_df.columns.get_loc('high')]  = 1.0993
    return m5_df


def _build_bearish_m5(m5_df):
    """Inject a valid bearish sweep+MSS into the last 3 M5 bars (positions -3, -2, -1)."""
    # candle -3: before the sweep. Bottom of candle 2 bars prior to MSS. Must be higher than FVG.
    m5_df.iloc[-3, m5_df.columns.get_loc('low')]   = 1.1015
    m5_df.iloc[-3, m5_df.columns.get_loc('high')]  = 1.1020
    m5_df.iloc[-3, m5_df.columns.get_loc('open')]  = 1.1018
    m5_df.iloc[-3, m5_df.columns.get_loc('close')] = 1.1019

    # sweep bar: high above ref_high (1.1015) by 0.0002 → sweep_depth=0.00020=0.154 ATR ≥ 0.10 ATR
    # sl = 1.1017 + 0.00013 = 1.10183, risk = 1.10183 - 1.1008 = 0.00103 ≤ 0.80*ATR=0.00104 ✓
    m5_df.iloc[-2, m5_df.columns.get_loc('high')]  = 1.1017   # sweep extreme
    m5_df.iloc[-2, m5_df.columns.get_loc('low')]   = 1.1007
    m5_df.iloc[-2, m5_df.columns.get_loc('open')]  = 1.1011
    m5_df.iloc[-2, m5_df.columns.get_loc('close')] = 1.1013
    
    # MSS candle: bearish, close < ref_high - 10% range = 1.1012
    # To form FVG, high < candle -3 low.
    m5_df.iloc[-1, m5_df.columns.get_loc('high')]  = 1.1013
    m5_df.iloc[-1, m5_df.columns.get_loc('open')]  = 1.1012
    m5_df.iloc[-1, m5_df.columns.get_loc('close')] = 1.1008   # entry
    m5_df.iloc[-1, m5_df.columns.get_loc('low')]   = 1.1007
    return m5_df


# ─────────────────────────────────────────────────────────────────────────────
# TESTS
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crt_strategy_id():
    strat = CRTStrategy()
    assert strat.get_id() == "crt_h1"
    assert "Candle Range" in strat.get_name()


@pytest.mark.asyncio
async def test_crt_strategy_insufficient_data():
    strat = CRTStrategy()
    df_h1 = pd.DataFrame({'close': [1.1] * 5})
    df_m5 = pd.DataFrame({'close': [1.1] * 300})
    res = await strat.analyze("EURUSD", {'h1': df_h1, 'm5': df_m5}, [], {})
    assert res is None


@pytest.mark.asyncio
async def test_crt_strategy_bullish_signal(base_h1_data, base_m5_data, base_m15_data, base_d1_data):
    strat = CRTStrategy()
    base_m5_data = _build_bullish_m5(base_m5_data)
    data = {'h1': base_h1_data, 'm5': base_m5_data, 'm15': base_m15_data, 'd1': base_d1_data}

    with patch('strategies.crt_strategy.MacroFilter.is_macro_safe', return_value=True), \
         patch('strategies.crt_strategy.RiskManager.calculate_lot_size', return_value={'lot_size': 0.1}), \
         patch('strategies.crt_strategy.AlphaCombiner.calculate_quality_score', return_value=8.0):
        res = await strat.analyze("EURUSD", data, [], {})
        assert res is not None
        assert res['direction'] == "BUY"
        assert res['tp1'] > res['entry_price']  # TP1 above entry for BUY
        assert res['sl'] < res['entry_price']


@pytest.mark.asyncio
async def test_crt_strategy_bearish_signal(base_h1_data, base_m5_data, base_m15_data, base_d1_data):
    strat = CRTStrategy()

    # For SELL: D1 must be bearish
    base_d1_data.iloc[-1, base_d1_data.columns.get_loc('close')] = 1.0850  # below ema_200=1.0900
    base_d1_data.iloc[-1, base_d1_data.columns.get_loc('open')]  = 1.0900  # bearish day
    # EMA slope: must be declining
    base_h1_data.iloc[-1, base_h1_data.columns.get_loc('ema_200')] = 1.1020
    base_h1_data.iloc[-6, base_h1_data.columns.get_loc('ema_200')] = 1.1021
    base_m5_data = _build_bearish_m5(base_m5_data)
    data = {'h1': base_h1_data, 'm5': base_m5_data, 'm15': base_m15_data, 'd1': base_d1_data}

    with patch('strategies.crt_strategy.MacroFilter.is_macro_safe', return_value=True), \
         patch('strategies.crt_strategy.RiskManager.calculate_lot_size', return_value={'lot_size': 0.1}), \
         patch('strategies.crt_strategy.AlphaCombiner.calculate_quality_score', return_value=8.0):
        res = await strat.analyze("EURUSD", data, [], {})
        assert res is not None
        assert res['direction'] == "SELL"
        assert res['tp1'] < res['entry_price']  # TP1 below entry for SELL
        assert res['sl'] > res['entry_price']


@pytest.mark.asyncio
async def test_daily_bias_blocks_countertrend_sell(base_h1_data, base_m5_data, base_m15_data, base_d1_data):
    """SELL signal must be rejected when D1 bias is bullish."""
    strat = CRTStrategy()
    # D1 is bullish (default fixture)
    base_m5_data = _build_bearish_m5(base_m5_data)
    # EMA slope declining for H1 to not block via that gate
    base_h1_data.iloc[-1, base_h1_data.columns.get_loc('ema_200')] = 1.1020
    base_h1_data.iloc[-6, base_h1_data.columns.get_loc('ema_200')] = 1.1021
    data = {'h1': base_h1_data, 'm5': base_m5_data, 'm15': base_m15_data, 'd1': base_d1_data}

    with patch('strategies.crt_strategy.MacroFilter.is_macro_safe', return_value=True), \
         patch('strategies.crt_strategy.RiskManager.calculate_lot_size', return_value={'lot_size': 0.1}):
        res = await strat.analyze("EURUSD", data, [], {})
        # SELL goes against bullish D1 bias → must be None
        assert res is None


@pytest.mark.asyncio
async def test_daily_bias_blocks_countertrend_buy(base_h1_data, base_m5_data, base_m15_data, base_d1_data):
    """BUY signal must be rejected when D1 bias is bearish."""
    strat = CRTStrategy()
    # Set D1 to bearish
    base_d1_data.iloc[-1, base_d1_data.columns.get_loc('close')] = 1.0850
    base_d1_data.iloc[-1, base_d1_data.columns.get_loc('open')]  = 1.0900
    base_m5_data = _build_bullish_m5(base_m5_data)
    data = {'h1': base_h1_data, 'm5': base_m5_data, 'm15': base_m15_data, 'd1': base_d1_data}

    with patch('strategies.crt_strategy.MacroFilter.is_macro_safe', return_value=True), \
         patch('strategies.crt_strategy.RiskManager.calculate_lot_size', return_value={'lot_size': 0.1}):
        res = await strat.analyze("EURUSD", data, [], {})
        # BUY goes against bearish D1 bias → must be None
        assert res is None


@pytest.mark.asyncio
async def test_killzone_blocks_asian_session(base_h1_data, base_m5_data, base_m15_data, base_d1_data):
    """Signals outside London/NY killzones must be rejected."""
    strat = CRTStrategy()
    # Move timestamp to Asian session (hour=4, outside KZ)
    asian_dates = pd.date_range(end=datetime(2025, 1, 1, 4, 0), periods=300, freq='h')
    base_h1_data.index = asian_dates
    base_m5_data = _build_bullish_m5(base_m5_data)
    data = {'h1': base_h1_data, 'm5': base_m5_data, 'm15': base_m15_data, 'd1': base_d1_data}

    with patch('strategies.crt_strategy.MacroFilter.is_macro_safe', return_value=True), \
         patch('strategies.crt_strategy.RiskManager.calculate_lot_size', return_value={'lot_size': 0.1}):
        res = await strat.analyze("EURUSD", data, [], {})
        assert res is None   # Asian session → blocked


@pytest.mark.asyncio
async def test_killzone_allows_london_open(base_h1_data, base_m5_data, base_m15_data, base_d1_data):
    """Signals during London KZ (hour=8) must be allowed."""
    strat = CRTStrategy()
    london_dates = pd.date_range(end=datetime(2025, 1, 1, 8, 0), periods=300, freq='h')
    base_h1_data.index = london_dates
    base_m5_data.index = pd.date_range(end=datetime(2025, 1, 1, 8, 0), periods=300, freq='5min')
    base_m5_data = _build_bullish_m5(base_m5_data)
    data = {'h1': base_h1_data, 'm5': base_m5_data, 'm15': base_m15_data, 'd1': base_d1_data}

    with patch('strategies.crt_strategy.MacroFilter.is_macro_safe', return_value=True), \
         patch('strategies.crt_strategy.RiskManager.calculate_lot_size', return_value={'lot_size': 0.1}), \
         patch('strategies.crt_strategy.AlphaCombiner.calculate_quality_score', return_value=8.0):
        res = await strat.analyze("EURUSD", data, [], {})
        assert res is not None   # London KZ → allowed
        assert res['direction'] == "BUY"


@pytest.mark.asyncio
async def test_atr_range_filter(base_h1_data, base_m5_data, base_d1_data):
    """Ranges outside 0.40–2.5× ATR must be rejected."""
    strat = CRTStrategy()
    # Make ref candle (H1[-2]) range tiny: high=1.1001, low=1.0999 → range=0.0002
    # ATR=0.0013 → range < 0.40*ATR = 0.00052 → filtered
    base_h1_data.iloc[-2, base_h1_data.columns.get_loc('high')] = 1.1001
    base_h1_data.iloc[-2, base_h1_data.columns.get_loc('low')]  = 1.0999
    data = {'h1': base_h1_data, 'm5': base_m5_data, 'd1': base_d1_data}
    res = await strat.analyze("EURUSD", data, [], {})
    assert res is None


@pytest.mark.asyncio
async def test_macro_blocked(base_h1_data, base_m5_data, base_m15_data, base_d1_data):
    strat = CRTStrategy()
    base_m5_data = _build_bullish_m5(base_m5_data)
    data = {'h1': base_h1_data, 'm5': base_m5_data, 'm15': base_m15_data, 'd1': base_d1_data}
    with patch('strategies.crt_strategy.MacroFilter.is_macro_safe', return_value=False):
        res = await strat.analyze("EURUSD", data, [], {})
        assert res is None


@pytest.mark.asyncio
async def test_news_blocked(base_h1_data, base_m5_data, base_m15_data, base_d1_data):
    strat = CRTStrategy()
    base_m5_data = _build_bullish_m5(base_m5_data)
    data = {'h1': base_h1_data, 'm5': base_m5_data, 'm15': base_m15_data, 'd1': base_d1_data}
    with patch('strategies.crt_strategy.MacroFilter.is_macro_safe', return_value=True), \
         patch('strategies.crt_strategy.NewsFilter.is_safe_to_trade', return_value=False):
        res = await strat.analyze("EURUSD", data, ["NFP"], {})
        assert res is None


@pytest.mark.asyncio
async def test_exception_handling():
    strat = CRTStrategy()
    res = await strat.analyze("EURUSD", {}, [], {})
    assert res is None
