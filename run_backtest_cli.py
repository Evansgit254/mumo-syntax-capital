import asyncio
from datetime import datetime, timedelta
from core.backtest_engine import BacktestEngine

async def main():
    # Set range for last 30 days (yfinance M5 limit is 60d)
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=14)).strftime('%Y-%m-%d')
    
    print(f"🕵️  STARTING INSTITUTIONAL BACKTEST")
    print(f"📅 Range: {start_date} to {end_date}")
    print(f"⚙️  Alpha Core: CRT Strategy + Regime Detection")
    print("=" * 50)
    
    engine = BacktestEngine(start_date, end_date)
    
    def progress_bar(p):
        cols = 40
        done = int(p * cols)
        bar = "█" * done + "░" * (cols - done)
        print(f"\r🚀 Progress: |{bar}| {p*100:.1f}%", end="")

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
