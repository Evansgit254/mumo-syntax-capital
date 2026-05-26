import asyncio
from datetime import datetime
from config.config import SYMBOLS
from data.fetcher import DataFetcher
from indicators.calculations import IndicatorCalculator
from strategies.crt_strategy import CRTStrategy
from strategies.session_clock_strategy import SessionClockStrategy
from strategies.advanced_pattern_strategy import AdvancedPatternStrategy
from strategies.gold_quant_strategy import GoldQuantStrategy
from strategies.statistical_arbitrage_strategy import StatisticalArbitrageStrategy
from strategies.smc_liquidity_sweep import SMCLiquiditySweepStrategy
from strategies.anchored_poc_strategy import AnchoredPOCStrategy
from strategies.pre_news_quant_strategy import PreNewsQuantStrategy
from strategies.news_edge_strategy import NewsEdgeStrategy
from core.signal_formatter import SignalFormatter
from core.market_status import MarketStatus


def _is_strategy_enabled(key: str) -> bool:
    """Check system_config DB for strategy toggle. Defaults to True if not found."""
    import sqlite3
    from config.config import DB_CLIENTS
    try:
        conn = sqlite3.connect(DB_CLIENTS)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT value FROM system_config WHERE key = ?", (key,)
        ).fetchone()
        conn.close()
        if row:
            return row["value"].lower() == "true"
    except Exception:
        pass
    return True  # Fail-open: enable if DB check fails


async def generate_signals():
    """
    Main signal generation engine.
    Runs both intraday (M5) and swing (H1) strategies concurrently.
    """
    print("=" * 60)
    print("🚀 DUAL-TIMEFRAME QUANT SIGNAL GENERATOR")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Symbols: {len(SYMBOLS)} pairs")
    print("=" * 60)
    
    from config.config import DXY_SYMBOL, TNX_SYMBOL, MULTI_CLIENT_MODE
    from data.news_fetcher import NewsFetcher
    from core.client_manager import ClientManager
    
    fetcher = DataFetcher()
    client_manager = ClientManager()
    crt_strategy = CRTStrategy()  # Replaces Swing (V28.0: CRT — Candle Range Theory)
    clock_strategy = SessionClockStrategy()
    advanced_strategy = AdvancedPatternStrategy()
    gold_strategy = GoldQuantStrategy()
    stat_arb_strategy = StatisticalArbitrageStrategy()
    smc_sweep_strategy = SMCLiquiditySweepStrategy()
    poc_edge_strategy = AnchoredPOCStrategy()
    pre_news_strategy = PreNewsQuantStrategy()
    news_edge_strategy = NewsEdgeStrategy()
    
    # Fetch macro context (DXY, TNX) for all symbols
    print("📊 Fetching macro context...")
    market_context = {}
    try:
        dxy_data = await fetcher.fetch_data_async(DXY_SYMBOL, "1h", period="60d")
        tnx_data = await fetcher.fetch_data_async(TNX_SYMBOL, "1h", period="60d")
        
        if not dxy_data.empty:
            market_context['DXY'] = IndicatorCalculator.add_indicators(dxy_data, "1h")
        if not tnx_data.empty:
            market_context['^TNX'] = IndicatorCalculator.add_indicators(tnx_data, "1h")
    except Exception as e:
        print(f"⚠️  Warning: Could not fetch macro context: {e}")
    
    # Fetch news events (optional, can be empty)
    news_events = []
    try:
        news_fetcher = NewsFetcher()
        news_events = news_fetcher.get_upcoming_events() if hasattr(news_fetcher, 'get_upcoming_events') else []
    except Exception as e:
        # News fetching is optional
        pass
    
    all_signals = []
    
    for symbol in SYMBOLS:
        try:
            # Fetch multi-timeframe data
            m5_data = await fetcher.fetch_data_async(symbol, "5m", period="5d")
            h1_data = await fetcher.fetch_data_async(symbol, "1h", period="30d")
            d1_data = await fetcher.fetch_data_async(symbol, "1d", period="365d")
            
            
            # V16.1: Market Status Check (Prevent stale data processing)
            if not MarketStatus.is_market_open(symbol):
                # Only log once per hour or if debug mode to avoid spam
                # For now, just skip silently or print if verbose
                # print(f"zzz Market Closed for {symbol}")
                continue

            if m5_data.empty or h1_data.empty or d1_data.empty:
                continue
                
            # Add indicators
            m5_df = IndicatorCalculator.add_indicators(m5_data, "5m")
            h1_df = IndicatorCalculator.add_indicators(h1_data, "1h")
            d1_df = IndicatorCalculator.add_indicators(d1_data, "1d")
            
            data_bundle = {
                'm5': m5_df,
                'h1': h1_df,
                'd1': d1_df
            }
            
            # V25.1: Gold-Specific Specialized Engine Bypass
            if symbol == "GC=F":
                gold_signal = await gold_strategy.analyze(symbol, data_bundle, news_events, market_context)
                if gold_signal:
                    all_signals.append(('GOLD_QUANT', gold_signal))
                continue  # Skip all forex strategies for GC=F
            
            # V28.0: CRT Strategy — ALWAYS ON (locked)
            crt_signal = await crt_strategy.analyze(symbol, data_bundle, news_events, market_context)
            if crt_signal:
                all_signals.append(('CRT', crt_signal))

            # V22.4: Session Clock (toggle: strategy_session_clock)
            if _is_strategy_enabled("strategy_session_clock"):
                clock_signal = await clock_strategy.analyze(symbol, data_bundle, news_events, market_context)
                if clock_signal:
                    all_signals.append(('SESSION_CLOCK', clock_signal))

            # V23: Advanced Patterns — ALWAYS ON (locked)
            advanced_signal = await advanced_strategy.analyze(symbol, data_bundle, news_events, market_context)
            if advanced_signal:
                all_signals.append(('ADVANCED', advanced_signal))
                
            # Statistical Arbitrage (toggle: strategy_stat_arb)
            if _is_strategy_enabled("strategy_stat_arb"):
                stat_arb_signal = await stat_arb_strategy.analyze(symbol, data_bundle, news_events, market_context)
                if stat_arb_signal:
                    all_signals.append(('STAT_ARB', stat_arb_signal))
                
            # SMC Liquidity Sweep (toggle: strategy_smc_sweep)
            if _is_strategy_enabled("strategy_smc_sweep"):
                smc_signal = await smc_sweep_strategy.analyze(symbol, data_bundle, news_events, market_context)
                if smc_signal:
                    all_signals.append(('SMC_SWEEP', smc_signal))
                
            # Anchored POC Edge (toggle: strategy_poc_edge)
            if _is_strategy_enabled("strategy_poc_edge"):
                poc_signal = await poc_edge_strategy.analyze(symbol, data_bundle, news_events, market_context)
                if poc_signal:
                    all_signals.append(('POC_EDGE', poc_signal))

            # Pre-News Quant (toggle: strategy_pre_news)
            if _is_strategy_enabled("strategy_pre_news"):
                pre_news_signal = await pre_news_strategy.analyze(symbol, data_bundle, news_events, market_context)
                if pre_news_signal:
                    all_signals.append(('PRE_NEWS', pre_news_signal))

            # News Edge (toggle: strategy_news_edge)
            if _is_strategy_enabled("strategy_news_edge"):
                news_edge_signal = await news_edge_strategy.analyze(symbol, data_bundle, news_events, market_context)
                if news_edge_signal:
                    all_signals.append(('NEWS_EDGE', news_edge_signal))

                
        except Exception as e:
            print(f"⚠️  Error processing {symbol}: {str(e)}")
            continue
    
    # Display all signals
    print(f"\n📊 Total Base Signals Generated: {len(all_signals)}")
    print("=" * 60)
    
    # V11.0: Multi-Client Delivery Logic
    if MULTI_CLIENT_MODE:
        clients = client_manager.get_all_active_clients()
        print(f"👥 Broadcasting to {len(clients)} active clients...")
        
        for client in clients:
            print(f"\n📱 Delivery for Client: {client['telegram_chat_id']} (Bal: ${client['account_balance']})")
            for signal_type, signal in all_signals:
                formatted = SignalFormatter.format_personalized_signal(signal, client)
                print(formatted)
    else:
        # Standard single-user mode
        for signal_type, signal in all_signals:
            formatted = SignalFormatter.format_signal(signal)
            print(formatted)
    
    return all_signals

if __name__ == "__main__":
    signals = asyncio.run(generate_signals())
    print(f"\n✅ Signal generation complete. Generated {len(signals)} total signals.")
