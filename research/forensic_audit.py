import sqlite3
import pandas as pd
import numpy as np

def forensic_audit(run_id: int):
    conn = sqlite3.connect('database/backtest_results.db')
    query = f"SELECT * FROM backtest_signals WHERE run_id = {run_id}"
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    if df.empty:
        print(f"No results found for Run ID {run_id}")
        return

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['hour'] = df['timestamp'].dt.hour
    df['is_win'] = df['result'].isin(['TP1', 'TP2', 'TP3'])
    
    def summarize(group_col):
        summary = df.groupby(group_col).agg(
            trades=('id', 'count'),
            win_rate=('is_win', 'mean'),
            total_r=('result_pips', 'sum'),
            avg_r=('result_pips', 'mean'),
            std_r=('result_pips', 'std')
        ).reset_index()
        
        # Derived metrics
        summary['wr_pct'] = (summary['win_rate'] * 100).round(1)
        summary['profit_factor'] = (df[df['result_pips'] > 0].groupby(group_col)['result_pips'].sum() / 
                                   df[df['result_pips'] < 0].groupby(group_col)['result_pips'].sum().abs()).round(2)
        
        # Sharpe-like Expectancy: Mean / StdDev
        summary['expectancy'] = (summary['avg_r'] / summary['std_r']).round(2)
        return summary

    print(f"\n{'='*70}")
    print(f"🕵️  30-DAY INSTITUTIONAL EDGE ANALYSIS (RUN ID: {run_id})")
    print(f"{'='*70}")

    # 1. Macro Breakdown
    print("\n📊 STRATEGY ALPHA")
    print(summarize('strategy_name').to_string(index=False))

    print("\n🌍 SYMBOL ALPHA")
    print(summarize('symbol').sort_values(by='total_r', ascending=False).to_string(index=False))

    # 2. THE "HIDDEN EDGE" FINDER (Combinatorial Search)
    print("\n💎 HIDDEN EDGES (Strategy x Symbol Sweetspots)")
    edge_df = df.groupby(['strategy_name', 'symbol']).agg(
        trades=('id', 'count'),
        wr=('is_win', 'mean'),
        net_r=('result_pips', 'sum')
    ).reset_index()
    
    # Filter for high-confidence edges
    hidden_edges = edge_df[(edge_df['trades'] >= 5) & (edge_df['net_r'] > 2.0)].sort_values(by='net_r', ascending=False)
    print(hidden_edges.to_string(index=False))

    # 3. HOURLY VOLATILITY HARVEST
    print("\n🕒 HOURLY EDGE CLUSTERS")
    hour_df = summarize('hour')
    print(hour_df[['hour', 'trades', 'wr_pct', 'total_r', 'profit_factor']].to_string(index=False))

    # 4. Final Executive Summary
    total_trades = len(df)
    win_rate = df['is_win'].mean() * 100
    total_net_r = df['result_pips'].sum()
    
    print(f"\n{'*'*70}")
    print(f"📈 30-DAY PERFORMANCE: {total_net_r:.2f} R | Win Rate: {win_rate:.1f}% | Trades: {total_trades}")
    print(f"{'*'*70}")

if __name__ == "__main__":
    import sys
    run_id = int(sys.argv[1]) if len(sys.argv) > 1 else 23
    forensic_audit(run_id)
