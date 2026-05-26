import pytest
import asyncio
import pandas as pd
from data.fetcher import DataFetcher
from data.news_fetcher import NewsFetcher
from config.config import SYMBOLS, DXY_SYMBOL

@pytest.mark.authentic
def test_yfinance_live_connection():
    """Verify that we can actually fetch live data from yfinance."""
    symbol = "EURUSD=X"
    df = DataFetcher.fetch_data(symbol, "1h", "2d")
    
    assert df is not None, f"Failed to fetch data for {symbol}"
    assert not df.empty, f"Received empty DataFrame for {symbol}"
    assert "close" in df.columns
    # Data Integrity Check: No NaN in latest bar
    latest_bar = df.iloc[-1]
    assert not pd.isna(latest_bar["close"]), "Latest close price is NaN"
    assert latest_bar["close"] > 0, "Price must be positive"

@pytest.mark.authentic
def test_news_fetcher_live():
    """Verify that the news fetcher can reach external sources."""
    fetcher = NewsFetcher()
    events = fetcher.fetch_news()
    
    # We expect at least some events or at least a valid list response
    assert isinstance(events, list)
    # Note: On weekends it might be empty, so we don't assert len > 0 
    # but we check if the fetcher itself didn't crash.

@pytest.mark.authentic
@pytest.mark.asyncio
async def test_get_latest_data_bundle():
    """Verify that the data bundle fetcher works with live data."""
    # We restrict to 1 symbol for speed
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("config.config.SYMBOLS", ["EURUSD=X"])
        data_bundle = await DataFetcher.get_latest_data()
        assert isinstance(data_bundle, dict)
        assert "EURUSD=X" in data_bundle
        assert isinstance(data_bundle["EURUSD=X"], dict)
        assert "d1" in data_bundle["EURUSD=X"]
        assert isinstance(data_bundle["EURUSD=X"]["d1"], pd.DataFrame)
        assert len(data_bundle["EURUSD=X"]) > 0
        assert not data_bundle["EURUSD=X"]["d1"].empty

@pytest.mark.authentic
def test_dxy_availability():
    """Verify DXY is fetchable as it is critical for macro filters."""
    df = DataFetcher.fetch_data(DXY_SYMBOL, "1h", "5d")
    assert df is not None and not df.empty, f"Critical Macro Asset {DXY_SYMBOL} is unavailable"
