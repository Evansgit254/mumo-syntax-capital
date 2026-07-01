import pytest
import pandas as pd
import os
from data.dukascopy_loader import DukascopyLoader

@pytest.fixture
def temp_duka_dir(tmp_path):
    # Create a structure: tmp_path/EURUSD/data.csv
    eurusd_dir = tmp_path / "EURUSD"
    eurusd_dir.mkdir()
    
    # Standard format CSV
    csv_content = "Gmt time,Open,High,Low,Close,Volume\n" \
                  "01.01.2024 00:00:00.000,1.1000,1.1010,1.0990,1.1005,100.0\n" \
                  "01.01.2024 00:01:00.000,1.1005,1.1015,1.1000,1.1010,120.0\n"
    csv_file = eurusd_dir / "EURUSD_M1.csv"
    csv_file.write_text(csv_content)
    
    # Local time format CSV
    gbpusd_dir = tmp_path / "GBPUSD"
    gbpusd_dir.mkdir()
    csv_local = "Local time,Open,High,Low,Close,Volume\n" \
                "01.01.2024 00:00:00.000,1.2000,1.2010,1.1990,1.2005,50.0\n"
    (gbpusd_dir / "GBPUSD_M1.csv").write_text(csv_local)

    # Date/Time format
    usdjpy_dir = tmp_path / "USDJPY"
    usdjpy_dir.mkdir()
    csv_dt = "Date,Time,Open,High,Low,Close,Volume\n" \
             "2024-01-01,00:00:00,140.0,140.5,139.5,140.2,1000\n"
    (usdjpy_dir / "USDJPY_M1.csv").write_text(csv_dt)
    
    return str(tmp_path)

def test_dukascopy_loader_init(temp_duka_dir):
    loader = DukascopyLoader(base_dir=temp_duka_dir)
    assert loader.base_dir == temp_duka_dir

def test_dukascopy_loader_list_symbols(temp_duka_dir):
    loader = DukascopyLoader(base_dir=temp_duka_dir)
    symbols = loader.list_available_symbols()
    assert "EURUSD=X" in symbols
    assert "GBPUSD=X" in symbols
    assert "USDJPY=X" in symbols

def test_dukascopy_loader_load_standard(temp_duka_dir):
    loader = DukascopyLoader(base_dir=temp_duka_dir)
    df = loader.load("EURUSD=X", timeframe="1min")
    assert df is not None
    assert len(df) == 2
    assert df.iloc[0]['open'] == 1.1000
    assert df.index.tzinfo is not None 

def test_dukascopy_loader_load_local_time(temp_duka_dir):
    loader = DukascopyLoader(base_dir=temp_duka_dir)
    df = loader.load("GBPUSD=X", timeframe="1min")
    assert df is not None
    assert df.iloc[0]['close'] == 1.2005

def test_dukascopy_loader_load_date_time(temp_duka_dir):
    loader = DukascopyLoader(base_dir=temp_duka_dir)
    df = loader.load("USDJPY=X", timeframe="1min")
    assert df is not None
    assert df.iloc[0]['high'] == 140.5

def test_dukascopy_loader_filters(temp_duka_dir):
    loader = DukascopyLoader(base_dir=temp_duka_dir)
    df = loader.load("EURUSD=X", timeframe="1min", start_date="2024-01-01", end_date="2024-01-01")
    assert len(df) == 2
    
    df_none = loader.load("EURUSD=X", start_date="2025-01-01")
    assert df_none is None

def test_dukascopy_loader_resample(temp_duka_dir):
    loader = DukascopyLoader(base_dir=temp_duka_dir)
    df = loader.load("EURUSD=X", timeframe="5min")
    assert len(df) == 1
    assert df.iloc[0]['open'] == 1.1000
    assert df.iloc[0]['high'] == 1.1015
    assert df.iloc[0]['volume'] == 220.0

def test_dukascopy_loader_reuses_m1_cache_for_multiple_timeframes(temp_duka_dir, monkeypatch):
    loader = DukascopyLoader(base_dir=temp_duka_dir)
    parse_count = 0
    original_parse = loader._parse_csv

    def counting_parse(path):
        nonlocal parse_count
        parse_count += 1
        return original_parse(path)

    monkeypatch.setattr(loader, "_parse_csv", counting_parse)

    assert loader.load("EURUSD=X", timeframe="1min") is not None
    assert loader.load("EURUSD=X", timeframe="5min") is not None
    assert parse_count == 1

def test_dukascopy_loader_load_for_event(temp_duka_dir):
    loader = DukascopyLoader(base_dir=temp_duka_dir)
    df = loader.load_for_event("EURUSD=X", "2024-01-01", 0, timeframe="1min", bars_before=0, bars_after=1)
    assert df is not None
    assert len(df) >= 1

def test_dukascopy_loader_no_folder(temp_duka_dir):
    loader = DukascopyLoader(base_dir=temp_duka_dir)
    assert loader.load("NONEXISTENT") is None

def test_dukascopy_loader_empty_dir(tmp_path):
    loader = DukascopyLoader(base_dir=str(tmp_path))
    assert loader.list_available_symbols() == []

def test_dukascopy_loader_malformed_csv(tmp_path):
    bad_dir = tmp_path / "BAD"
    bad_dir.mkdir()
    (bad_dir / "bad.csv").write_text("not,a,csv\nline1,line2")
    loader = DukascopyLoader(base_dir=str(tmp_path))
    assert loader.load("BAD") is None
