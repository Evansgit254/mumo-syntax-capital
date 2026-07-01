import asyncio
import argparse
from datetime import datetime, timedelta
from core.backtest_engine import BacktestEngine
from version import get_system_banner

async def main():
    parser = argparse.ArgumentParser(description="Pure Quant Research Backtest Engine")
    parser.add_argument("--recent", action="store_true", 
                       help="Backtest last 30 days (where M5 data exists, CRT gets full representation)")
    parser.add_argument("--days", type=int, default=30,
                       help="Number of days to backtest (default: 30)")
    parser.add_argument("--start", type=str, default=None,
                       help="Custom start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None,
                       help="Custom end date (YYYY-MM-DD)")
    parser.add_argument("--symbols", type=str, default=None,
                       help="Comma-separated symbols to backtest (e.g. EURUSD=X,GBPUSD=X)")
    args = parser.parse_args()

    if args.start and args.end:
        start_date = args.start
        end_date = args.end
    elif args.recent:
        # V36.0: Default to last X days where ALL data (including M5) is available
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=args.days)).strftime('%Y-%m-%d')
    else:
        # Standard: backtest the specified number of days
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=args.days)).strftime('%Y-%m-%d')
    
    print(get_system_banner())
    print(f"🕵️  STARTING INSTITUTIONAL BACKTEST")
    print(f"📅 Range: {start_date} to {end_date}")
    
    target_symbols = None
    if args.symbols:
        target_symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        print(f"🎯 Symbols: {', '.join(target_symbols)}")
    else:
        from config.config import SYMBOLS
        target_symbols = SYMBOLS
        print(f"🎯 Symbols: All Configured ({len(target_symbols)})")

    active_models = "CRT + Advanced Pattern"
    print(f"⚙️  Alpha Core: {active_models}")
    print("=" * 50)
    
    engine = BacktestEngine(start_date, end_date, symbols=target_symbols)
    
    def progress_bar(p, message=None):
        cols = 40
        done = int(p * cols)
        bar = "█" * done + "░" * (cols - done)
        suffix = f" - {message}" if message else ""
        print(f"\r🚀 Progress: |{bar}| {p*100:.1f}%{suffix}", end="", flush=True)

    results = await engine.run(progress_callback=progress_bar)
    
    print("\n" + "=" * 50)
    print("📊 BACKTEST RESULTS SUMMARY")
    print("=" * 50)
    if "error" in results:
        print(f"❌ Error: {results['error']}")
        return

    print(f"✅ Total Trades: {results['total_trades']}")
    print(f"📈 Win Rate:    {results['win_rate']:.1f}%")
    print(f"💰 Net Profit:  {results['net_pips']:.1f}R")
    print("=" * 50)
    print(f"📂 Results saved to database/backtest_results.db (Run ID: {results['run_id']})")

if __name__ == "__main__":
    asyncio.run(main())
