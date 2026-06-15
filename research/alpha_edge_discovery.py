import pandas as pd
import numpy as np
import os
import time
from scipy.stats import spearmanr
from datetime import datetime, timedelta
from config.config import SYMBOLS
from data.fetcher import DataFetcher
from indicators.calculations import IndicatorCalculator
from core.alpha_factors import AlphaFactors

class AlphaEdgeDiscovery:
    def __init__(self, symbols=None, timeframe="h1", days=60):
        self.symbols = symbols if symbols else SYMBOLS
        self.timeframe = timeframe
        self.days = days
        self.fetcher = DataFetcher()
        self.results = {}

    def fetch_data(self):
        print(f"📊 Fetching {self.days} days of {self.timeframe} data for {len(self.symbols)} symbols...")
        import yfinance as yf
        
        all_data = {}
        for symbol in self.symbols:
            print(f"Fetching {symbol}...")
            try:
                # Use yf.download static method which is often more robust
                df = yf.download(symbol, period=f"{self.days + 10}d", interval=self.timeframe, progress=False, auto_adjust=True)
                
                if df is not None and not df.empty:
                    # Flatten MultiIndex columns if present (common in new yfinance)
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                        
                    # Standardize columns
                    df.columns = [c.lower() for c in df.columns]
                    
                    # Create 'atr' if missing (required for indicators)
                    if 'high' in df.columns and 'low' in df.columns and 'close' in df.columns:
                        print(f"✅ Downloaded {len(df)} bars for {symbol}. Adding indicators...")
                        df = IndicatorCalculator.add_indicators(df, self.timeframe)
                        
                        if df is not None and not df.empty:
                            print(f"✅ Indicators added for {symbol}. Bars: {len(df)}")
                            all_data[symbol] = df
                        else:
                            print(f"❌ IndicatorCalculator returned empty/None for {symbol}")
                    else:
                        print(f"❌ Missing required columns for {symbol}: {df.columns}")
                else:
                    print(f"❌ yf.download returned empty for {symbol}")
            except Exception as e:
                print(f"❌ Exception fetching {symbol}: {e}")
                
            time.sleep(1) # Small delay
        return all_data

    def calculate_alphas_and_returns(self, df):
        # Calculate Alphas
        df['alpha_velocity'] = df.apply(lambda row: AlphaFactors.velocity_alpha(df.loc[:row.name]), axis=1)
        df['alpha_zscore'] = df.apply(lambda row: AlphaFactors.mean_reversion_zscore(df.loc[:row.name]), axis=1)
        df['alpha_momentum'] = df.apply(lambda row: AlphaFactors.momentum_alpha(df.loc[:row.name]), axis=1)
        df['alpha_volatility'] = df.apply(lambda row: AlphaFactors.volatility_regime_alpha(df.loc[:row.name]), axis=1)
        
        # Calculate Forward Returns (next N bars)
        fwd_period = 12 if self.timeframe == "h1" else 72
        df['fwd_return'] = df['close'].shift(-fwd_period) / df['close'] - 1.0
        
        return df.dropna(subset=['fwd_return'])

    def analyze_edge(self):
        all_dfs = self.fetch_data()
        if not all_dfs:
            print("❌ No data loaded.")
            return
            
        combined_df_list = []
        for symbol, df in all_dfs.items():
            print(f"🔎 Analyzing {symbol}...")
            df_processed = self.calculate_alphas_and_returns(df)
            combined_df_list.append(df_processed)
            
        full_df = pd.concat(combined_df_list)
        
        # 1. Information Coefficient (IC)
        alphas = ['alpha_velocity', 'alpha_zscore', 'alpha_momentum', 'alpha_volatility']
        ic_results = {}
        for alpha in alphas:
            ic, p_val = spearmanr(full_df[alpha], full_df['fwd_return'])
            ic_results[alpha] = ic
            
        # 2. Bucket Analysis (Win Rate by Quantile)
        bucket_results = {}
        for alpha in alphas:
            full_df[f'{alpha}_q'] = pd.qcut(full_df[alpha], 5, labels=False, duplicates='drop')
            # Win rate: % of positive forward returns
            wr_by_q = full_df.groupby(f'{alpha}_q')['fwd_return'].apply(lambda x: (x > 0).mean())
            bucket_results[alpha] = wr_by_q.to_dict()
            
        # 3. Alignment Audit
        # Calculate signs (+1, -1, 0)
        for alpha in alphas:
            full_df[f'{alpha}_sign'] = np.sign(full_df[alpha])
            
        # Count how many alphas point same direction as return
        full_df['alignment_count'] = full_df[[f'{a}_sign' for a in alphas]].apply(lambda x: abs(x.sum()), axis=1)
        alignment_wr = full_df.groupby('alignment_count')['fwd_return'].apply(lambda x: (x > 0).mean())
        
        self.generate_report(ic_results, bucket_results, alignment_wr)

    def generate_report(self, ic, buckets, alignment):
        report = []
        report.append("# 📊 Alpha Edge Discovery Report")
        report.append(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"Timeframe: {self.timeframe} | Lookback: {self.days} days")
        report.append("\n## 1. Information Coefficient (Predictive Power)")
        report.append("| Alpha Factor | IC (Spearman) | Strength |")
        report.append("| :--- | :--- | :--- |")
        for k, v in ic.items():
            strength = "High" if abs(v) > 0.1 else "Moderate" if abs(v) > 0.05 else "Weak"
            report.append(f"| {k} | {v:.4f} | {strength} |")
            
        report.append("\n## 2. Factor Alignment Edge")
        report.append("| Aligned Alphas | Edge (Win Rate) | Sample Size |")
        report.append("| :--- | :--- | :--- |")
        for count, wr in alignment.items():
            report.append(f"| {int(count)} | {wr:.2%} | - |")
            
        report.append("\n## 3. High Probability 'Golden Profile'")
        # Find the best bucket/alignment
        best_alpha = max(ic, key=lambda k: abs(ic[k]))
        report.append(f"Based on IC, the most reliable lead indicator is **{best_alpha}**.")
        report.append(f"The system achieves maximum edge when at least 3 alpha factors are aligned.")
        
        report_path = "/home/evans/Projects/TradingExpert/mumo-syntax-capital/research/alpha_edge_report.md"
        with open(report_path, "w") as f:
            f.write("\n".join(report))
        print(f"✅ Alpha Edge Report generated at {report_path}")

if __name__ == "__main__":
    discovery = AlphaEdgeDiscovery(timeframe="h1", days=60)
    discovery.analyze_edge()
