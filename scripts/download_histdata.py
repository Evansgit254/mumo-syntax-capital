"""
HistData.com M1 Download Helper & Post-Download Processor
==========================================================
Downloads free M1 forex data from HistData.com for multi-year stress testing.

Usage:
    # Step 1: Open download pages in browser (you click download on each)
    python scripts/download_histdata.py --open-browser

    # Step 2: After downloading ZIPs to ~/Downloads, process them
    python scripts/download_histdata.py --process

    # Step 3: Verify what's loaded
    python scripts/download_histdata.py --verify

Configuration:
    Edit SYMBOLS and YEARS below to control what gets downloaded.
"""

import os
import sys
import glob
import zipfile
import shutil
import webbrowser
import time
import argparse
import pandas as pd
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────

# Symbols to download (HistData names)
SYMBOLS = {
    "EURUSD": "EURUSD",
    "GBPUSD": "GBPUSD",
    "USDJPY": "USDJPY",
    "AUDUSD": "AUDUSD",
    "NZDUSD": "NZDUSD",
    "GBPJPY": "GBPJPY",
    "XAUUSD": "XAUUSD",   # Gold
}

# Folder mapping (HistData name → local Dukascopy folder)
HISTDATA_TO_FOLDER = {
    "EURUSD": "EURUSD",
    "GBPUSD": "GBPUSD",
    "USDJPY": "USDJPY",
    "AUDUSD": "AUDUSD",
    "NZDUSD": "NZDUSD",
    "GBPJPY": "GBPJPY",
    "XAUUSD": "GOLD",
}

# Years to download (2022-2025 = 4-year stress test)
YEARS = [2022, 2023, 2024, 2025]

# Paths
DUKASCOPY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "dukascopy")
DOWNLOADS_DIR = os.path.expanduser("~/Downloads")


def download_programmatic():
    """Programmatically downloads HistData.com ZIP files for each symbol/year."""
    import requests
    from bs4 import BeautifulSoup

    print("=" * 70)
    print("HISTDATA.COM AUTOMATED DOWNLOADER")
    print("=" * 70)
    print(f"\nStarting automated download of {len(SYMBOLS) * len(YEARS)} files to {DOWNLOADS_DIR}...")
    
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    })

    base_url = "https://www.histdata.com/download-free-forex-historical-data/?/metatrader/1-minute-bar-quotes"
    post_url = "https://www.histdata.com/get.php"

    success_count = 0
    fail_count = 0

    for symbol in SYMBOLS:
        for year in YEARS:
            page_url = f"{base_url}/{symbol.lower()}/{year}"
            print(f"\n🌐 Requesting page: {symbol} {year}...")
            
            try:
                # 1. Fetch the page to get the CSRF token (tk)
                session.headers.update({'Referer': base_url})
                r = session.get(page_url, timeout=15)
                if r.status_code != 200:
                    print(f"   ❌ Failed to load page (HTTP {r.status_code})")
                    fail_count += 1
                    continue
                
                soup = BeautifulSoup(r.text, 'html.parser')
                form = soup.find('form', id='file_down')
                if not form:
                    print("   ❌ Download form not found on the page.")
                    fail_count += 1
                    continue
                
                # 2. Extract hidden input values
                data = {}
                for inp in form.find_all('input'):
                    data[inp.get('name')] = inp.get('value')
                
                # 3. Post to get.php to start the file transfer
                session.headers.update({'Referer': page_url})
                down_r = session.post(post_url, data=data, stream=True, timeout=30)
                
                if down_r.status_code != 200:
                    print(f"   ❌ Download request failed (HTTP {down_r.status_code})")
                    fail_count += 1
                    continue
                
                # Get filename from headers or default it
                disp = down_r.headers.get('Content-Disposition', '')
                filename = f"HISTDATA_COM_MT_{symbol}_M1{year}.zip"
                if 'filename=' in disp:
                    filename = disp.split('filename=')[1].strip('\"\'')
                
                filepath = os.path.join(DOWNLOADS_DIR, filename)
                
                print(f"   💾 Downloading {filename}...")
                with open(filepath, 'wb') as f:
                    for chunk in down_r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            
                print(f"   ✅ Done: {os.path.getsize(filepath) / 1024 / 1024:.2f} MB saved.")
                success_count += 1
                
                # Sleep a second to respect rate limits
                time.sleep(1.0)
                
            except Exception as e:
                print(f"   ❌ Error: {e}")
                fail_count += 1

    print("\n" + "=" * 70)
    print(f"DOWNLOAD COMPLETE: {success_count} succeeded, {fail_count} failed.")
    print("=" * 70)
    if success_count > 0:
        print("\nNext step: Run the processor to extract and format files:")
        print("   python scripts/download_histdata.py --process")


def open_browser_downloads():
    """Opens HistData.com download pages in the browser for each symbol/year."""
    base_url = "https://www.histdata.com/download-free-forex-historical-data/?/metatrader/1-minute-bar-quotes"

    urls = []
    for symbol in SYMBOLS:
        for year in YEARS:
            url = f"{base_url}/{symbol.lower()}/{year}"
            urls.append((symbol, year, url))

    print("=" * 70)
    print("HISTDATA.COM BROWSER DOWNLOAD FALLBACK")
    print("=" * 70)
    print(f"\nOpening {len(urls)} download pages in your browser.")
    print("For each page:")
    print("  1. Scroll down to the download button")
    print("  2. Click 'Download' — it will save a ZIP to ~/Downloads")
    print("  3. Wait for the download to complete before clicking the next tab")
    print()

    for symbol, year, url in urls:
        print(f"  Opening: {symbol} {year} → {url}")
        webbrowser.open(url)
        time.sleep(1.5)  # Avoid overwhelming the browser

    print(f"\n✅ Opened {len(urls)} tabs. Download each ZIP, then run:")
    print(f"   python scripts/download_histdata.py --process")


def process_downloads():
    """
    Finds HistData ZIP files in ~/Downloads, extracts the M1 CSVs,
    and moves them into data/dukascopy/<SYMBOL>/ with correct naming.
    """
    print("=" * 70)
    print("POST-DOWNLOAD PROCESSOR")
    print("=" * 70)

    # Find HistData ZIPs in Downloads folder
    # HistData naming: HISTDATA_COM_MT_<SYMBOL>_M1<YEAR>.zip
    # or: DAT_MT_<SYMBOL>_M1_<YEAR>.zip (inside the zip)
    zip_patterns = [
        os.path.join(DOWNLOADS_DIR, "HISTDATA_COM_MT_*_M1*.zip"),
        os.path.join(DOWNLOADS_DIR, "HISTDATA_COM_ASCII_*_M1*.zip"),
        os.path.join(DOWNLOADS_DIR, "DAT_MT_*_M1_*.zip"),
        os.path.join(DOWNLOADS_DIR, "DAT_ASCII_*_M1_*.zip"),
    ]

    zip_files = []
    for pattern in zip_patterns:
        zip_files.extend(glob.glob(pattern))

    if not zip_files:
        print(f"\n❌ No HistData ZIP files found in {DOWNLOADS_DIR}")
        print("   Expected filenames like: HISTDATA_COM_MT_EURUSD_M12022.zip")
        print("   Run --open-browser first and download the files.")
        return

    print(f"\nFound {len(zip_files)} ZIP files to process:\n")

    processed = 0
    for zip_path in sorted(zip_files):
        zip_name = os.path.basename(zip_path)
        print(f"  📦 {zip_name}")

        # Detect symbol from filename
        detected_symbol = None
        for sym in SYMBOLS:
            if sym in zip_name.upper():
                detected_symbol = sym
                break

        if not detected_symbol:
            print(f"     ⚠️  Could not detect symbol, skipping")
            continue

        # Detect year
        detected_year = None
        for year in range(2000, 2030):
            if str(year) in zip_name:
                detected_year = year
                break

        if not detected_year:
            print(f"     ⚠️  Could not detect year, skipping")
            continue

        # Create target directory
        folder_name = HISTDATA_TO_FOLDER.get(detected_symbol, detected_symbol)
        target_dir = os.path.join(DUKASCOPY_DIR, folder_name)
        os.makedirs(target_dir, exist_ok=True)

        # Extract ZIP
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                csv_files = [f for f in zf.namelist() if f.lower().endswith('.csv')]
                if not csv_files:
                    print(f"     ⚠️  No CSV found inside ZIP")
                    continue

                for csv_name in csv_files:
                    # Extract to target directory with standardized name
                    target_name = f"DAT_MT_{detected_symbol}_M1_{detected_year}.csv"
                    target_path = os.path.join(target_dir, target_name)

                    # Extract the CSV content
                    with zf.open(csv_name) as source:
                        content = source.read()

                    # Check if it's semicolon-separated (ASCII format) and convert
                    first_line = content.decode('utf-8', errors='ignore').split('\n')[0]
                    if ';' in first_line and ',' not in first_line:
                        # Convert ASCII format (semicolon) to MT format (comma)
                        text = content.decode('utf-8', errors='ignore')
                        # ASCII: 20220103 170000;1.13700;1.13700;1.13700;1.13700;0
                        # MT:    2022.01.03,17:00,1.13700,1.13700,1.13700,1.13700,0
                        converted_lines = []
                        for line in text.strip().split('\n'):
                            line = line.strip()
                            if not line:
                                continue
                            parts = line.split(';')
                            if len(parts) >= 6:
                                dt_str = parts[0].strip()
                                # Parse: 20220103 170000 → 2022.01.03,17:00
                                if len(dt_str) >= 15:
                                    date_part = f"{dt_str[0:4]}.{dt_str[4:6]}.{dt_str[6:8]}"
                                    time_part = f"{dt_str[9:11]}:{dt_str[11:13]}"
                                    converted = f"{date_part},{time_part},{parts[1]},{parts[2]},{parts[3]},{parts[4]},{parts[5]}"
                                    converted_lines.append(converted)
                        content = ('\n'.join(converted_lines) + '\n').encode('utf-8')

                    with open(target_path, 'wb') as f:
                        f.write(content)

                    # Verify the file
                    line_count = content.count(b'\n')
                    size_mb = len(content) / 1024 / 1024
                    print(f"     ✅ → {target_path}")
                    print(f"        {line_count:,} bars, {size_mb:.1f} MB")
                    processed += 1

        except zipfile.BadZipFile:
            print(f"     ❌ Corrupt ZIP file")
        except Exception as e:
            print(f"     ❌ Error: {e}")

    print(f"\n{'=' * 70}")
    print(f"✅ Processed {processed} files")
    print(f"\nNext: Run --verify to check the data, then run your backtest:")
    print(f"   python scripts/download_histdata.py --verify")


def verify_data():
    """Verifies all loaded Dukascopy data and reports coverage."""
    print("=" * 70)
    print("DATA VERIFICATION")
    print("=" * 70)

    # Add parent to path for imports
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from data.dukascopy_loader import DukascopyLoader

    loader = DukascopyLoader(base_dir=DUKASCOPY_DIR)
    available = loader.list_available_symbols()

    print(f"\nBase directory: {DUKASCOPY_DIR}")
    print(f"Available symbols: {len(available)}\n")

    total_bars = 0
    for sym in sorted(available):
        df = loader.load(sym, timeframe="5min")
        if df is not None and not df.empty:
            m1_df = loader._load_m1(sym)
            m1_count = len(m1_df) if m1_df is not None else 0
            total_bars += m1_count
            years_covered = sorted(set(df.index.year))
            print(f"  ✅ {sym:15s} | {m1_count:>10,} M1 bars | {len(df):>8,} M5 bars | "
                  f"[{df.index[0].strftime('%Y-%m-%d')} → {df.index[-1].strftime('%Y-%m-%d')}] | "
                  f"Years: {years_covered}")
        else:
            print(f"  ❌ {sym:15s} | No data loaded")

    print(f"\n  Total M1 bars across all symbols: {total_bars:,}")
    print(f"  Estimated disk usage: {total_bars * 50 / 1024 / 1024:.0f} MB")

    # Show folder contents
    print(f"\n{'=' * 70}")
    print("RAW FILE INVENTORY:")
    for folder in sorted(os.listdir(DUKASCOPY_DIR)):
        folder_path = os.path.join(DUKASCOPY_DIR, folder)
        if os.path.isdir(folder_path):
            csvs = sorted(glob.glob(os.path.join(folder_path, "*.csv")))
            if csvs:
                print(f"\n  {folder}/")
                for csv_path in csvs:
                    size = os.path.getsize(csv_path) / 1024 / 1024
                    print(f"    {os.path.basename(csv_path):50s} ({size:.1f} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HistData.com Download Helper for Mumo Syntax Capital")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--download", action="store_true",
                       help="Programmatically download all files automatically")
    group.add_argument("--open-browser", action="store_true",
                       help="Open HistData download pages in browser")
    group.add_argument("--process", action="store_true",
                       help="Process downloaded ZIPs from ~/Downloads into data/dukascopy/")
    group.add_argument("--verify", action="store_true",
                       help="Verify loaded data coverage")

    args = parser.parse_args()

    if args.download:
        download_programmatic()
    elif args.open_browser:
        open_browser_downloads()
    elif args.process:
        process_downloads()
    elif args.verify:
        verify_data()
