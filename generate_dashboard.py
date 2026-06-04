import sqlite3
import pandas as pd

def generate_dashboard(db_path, output_path, run_id=None):
    conn = sqlite3.connect(db_path)
    
    # Fetch the latest run_id if not specified
    if run_id is None:
        latest_run = pd.read_sql_query('SELECT id FROM backtest_runs ORDER BY id DESC LIMIT 1', conn)
        if latest_run.empty:
            print("❌ No backtest runs found in database.")
            return
        run_id = int(latest_run.iloc[0]['id'])
    
    # Run Summary
    run_query = f'SELECT * FROM backtest_runs WHERE id = {run_id}'
    run_df = pd.read_sql_query(run_query, conn)
    if run_df.empty:
        print(f"❌ Run ID {run_id} not found.")
        return
    run = run_df.iloc[0]
    
    # Strategy Performance
    strategy_perf = pd.read_sql_query(f'''
        SELECT strategy_name, 
               COUNT(*) as trades,
               SUM(CASE WHEN result_pips > 0 THEN 1 ELSE 0 END) as wins,
               SUM(result_pips) as net_r
        FROM backtest_signals 
        WHERE run_id = {run_id} AND result != 'BLOCKED'
        GROUP BY strategy_name
    ''', conn)
    strategy_perf['win_rate'] = (strategy_perf['wins'] / strategy_perf['trades'] * 100).round(1)
    
    # Symbol Performance
    symbol_perf = pd.read_sql_query(f'''
        SELECT symbol,
               COUNT(*) as trades,
               SUM(CASE WHEN result_pips > 0 THEN 1 ELSE 0 END) as wins,
               SUM(result_pips) as net_r
        FROM backtest_signals 
        WHERE run_id = {run_id} AND result != 'BLOCKED'
        GROUP BY symbol
        ORDER BY net_r DESC
    ''', conn)
    symbol_perf['win_rate'] = (symbol_perf['wins'] / symbol_perf['trades'] * 100).round(1)

    # Equity Curve Data
    equity_df = pd.read_sql_query(f'''
        SELECT timestamp, result_pips
        FROM backtest_signals 
        WHERE run_id = {run_id} AND result != 'BLOCKED' AND result != 'OPEN'
        ORDER BY timestamp
    ''', conn)
    equity_df['cumulative_r'] = equity_df['result_pips'].cumsum()

    # Calculate Drawdown
    equity_df['peak'] = equity_df['cumulative_r'].cummax()
    equity_df['drawdown'] = equity_df['cumulative_r'] - equity_df['peak']
    max_drawdown = abs(equity_df['drawdown'].min())
    
    # Prepare HTML Content
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Backtest Results - SMC Scalp Signals</title>
        <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
        <style>
            :root {{
                --bg-color: #0f172a;
                --card-bg: #1e293b;
                --text-main: #f8fafc;
                --text-muted: #94a3b8;
                --accent: #3b82f6;
                --success: #10b981;
                --danger: #ef4444;
            }}
            body {{
                font-family: 'Inter', system-ui, -apple-system, sans-serif;
                background-color: var(--bg-color);
                color: var(--text-main);
                margin: 0;
                padding: 20px;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
            }}
            .header {{
                text-align: center;
                margin-bottom: 40px;
            }}
            .header h1 {{
                font-size: 2.5rem;
                margin-bottom: 10px;
                background: linear-gradient(to right, #60a5fa, #3b82f6);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }}
            .summary-cards {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 20px;
                margin-bottom: 40px;
            }}
            .card {{
                background-color: var(--card-bg);
                padding: 20px;
                border-radius: 12px;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
                border: 1px solid #334155;
            }}
            .card h3 {{
                color: var(--text-muted);
                font-size: 0.875rem;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                margin-top: 0;
                margin-bottom: 10px;
            }}
            .card .value {{
                font-size: 2rem;
                font-weight: 700;
            }}
            .value.success {{ color: var(--success); }}
            .value.danger {{ color: var(--danger); }}
            
            .chart-container {{
                background-color: var(--card-bg);
                padding: 20px;
                border-radius: 12px;
                margin-bottom: 20px;
                border: 1px solid #334155;
            }}
            
            .tables-container {{
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 10px;
            }}
            th, td {{
                padding: 12px 15px;
                text-align: left;
                border-bottom: 1px solid #334155;
            }}
            th {{
                background-color: #0f172a;
                color: var(--text-muted);
                font-weight: 600;
            }}
            tr:hover {{
                background-color: #334155;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>SMC Scalp Signals - Backtest Results</h1>
                <p>Date Range: {run['start_date']} to {run['end_date']} | Run ID: {run['id']}</p>
            </div>

            <div class="summary-cards">
                <div class="card">
                    <h3>Total Trades</h3>
                    <div class="value">{run['total_trades']}</div>
                </div>
                <div class="card">
                    <h3>Win Rate</h3>
                    <div class="value {'success' if run['win_rate'] >= 50 else 'danger'}">{run['win_rate']:.1f}%</div>
                </div>
                <div class="card">
                    <h3>Net Profit</h3>
                    <div class="value {'success' if run['net_pips'] >= 0 else 'danger'}">{run['net_pips']:.1f} R</div>
                </div>
                <div class="card">
                    <h3>Max Drawdown</h3>
                    <div class="value danger">-{max_drawdown:.1f} R</div>
                </div>
            </div>

            <div class="chart-container">
                <div id="equityCurve"></div>
            </div>
            
            <div class="chart-container">
                <div id="drawdownCurve"></div>
            </div>

            <div class="tables-container">
                <div class="card">
                    <h3>Performance by Strategy</h3>
                    <table>
                        <thead>
                            <tr>
                                <th>Strategy</th>
                                <th>Trades</th>
                                <th>Win Rate</th>
                                <th>Net R</th>
                            </tr>
                        </thead>
                        <tbody>
                            {"".join(f"<tr><td>{row['strategy_name']}</td><td>{row['trades']}</td><td>{row['win_rate']}%</td><td class='{('success' if row['net_r'] >= 0 else 'danger')}'>{row['net_r']:.1f}</td></tr>" for _, row in strategy_perf.iterrows())}
                        </tbody>
                    </table>
                </div>

                <div class="card">
                    <h3>Performance by Symbol</h3>
                    <table>
                        <thead>
                            <tr>
                                <th>Symbol</th>
                                <th>Trades</th>
                                <th>Win Rate</th>
                                <th>Net R</th>
                            </tr>
                        </thead>
                        <tbody>
                            {"".join(f"<tr><td>{row['symbol']}</td><td>{row['trades']}</td><td>{row['win_rate']}%</td><td class='{('success' if row['net_r'] >= 0 else 'danger')}'>{row['net_r']:.1f}</td></tr>" for _, row in symbol_perf.iterrows())}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <script>
            // Equity Curve
            const equityData = [{{
                x: {equity_df['timestamp'].tolist()},
                y: {equity_df['cumulative_r'].tolist()},
                type: 'scatter',
                mode: 'lines',
                line: {{color: '#3b82f6', width: 2}},
                fill: 'tozeroy',
                fillcolor: 'rgba(59, 130, 246, 0.1)',
                name: 'Cumulative R'
            }}];
            
            const layout = {{
                title: 'Equity Curve (R-Multiples)',
                paper_bgcolor: 'rgba(0,0,0,0)',
                plot_bgcolor: 'rgba(0,0,0,0)',
                font: {{color: '#f8fafc'}},
                xaxis: {{gridcolor: '#334155', title: 'Time'}},
                yaxis: {{gridcolor: '#334155', title: 'Net R'}}
            }};
            
            Plotly.newPlot('equityCurve', equityData, layout);

            // Drawdown Curve
            const drawdownData = [{{
                x: {equity_df['timestamp'].tolist()},
                y: {equity_df['drawdown'].tolist()},
                type: 'scatter',
                mode: 'lines',
                line: {{color: '#ef4444', width: 2}},
                fill: 'tozeroy',
                fillcolor: 'rgba(239, 68, 68, 0.1)',
                name: 'Drawdown'
            }}];
            
            const ddLayout = {{
                title: 'Drawdown Profile (R-Multiples)',
                paper_bgcolor: 'rgba(0,0,0,0)',
                plot_bgcolor: 'rgba(0,0,0,0)',
                font: {{color: '#f8fafc'}},
                xaxis: {{gridcolor: '#334155', title: 'Time'}},
                yaxis: {{gridcolor: '#334155', title: 'Drawdown (R)'}}
            }};
            
            Plotly.newPlot('drawdownCurve', drawdownData, ddLayout);
        </script>
    </body>
    </html>
    """
    
    with open(output_path, 'w') as f:
        f.write(html_content)
    print(f"✅ Dashboard generated successfully at {output_path}")

if __name__ == "__main__":
    generate_dashboard('database/backtest_results.db', 'backtest_dashboard.html')
