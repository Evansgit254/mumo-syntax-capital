"""
Health Monitor for Signal Service
Tracks daily signal count, win rate trends, and service status.
"""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional
import subprocess


class HealthMonitor:
    """Monitor signal service health and performance metrics."""
    
    def __init__(self, signals_db_path: str = "database/signals.db"):
        self.signals_db = signals_db_path
        self.metrics_db = "monitoring/metrics.db"
        self._init_metrics_db()
    
    def _init_metrics_db(self):
        """Initialize metrics storage database."""
        Path("monitoring").mkdir(exist_ok=True)
        conn = sqlite3.connect(self.metrics_db)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_metrics (
                date TEXT PRIMARY KEY,
                total_signals INTEGER,
                win_count INTEGER,
                loss_count INTEGER,
                win_rate REAL,
                service_uptime_pct REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS service_health (
                timestamp TIMESTAMP PRIMARY KEY,
                is_running INTEGER,
                last_signal_time TEXT,
                uptime_seconds INTEGER
            )
        """)
        
        conn.commit()
        conn.close()
    
    def get_daily_signal_count(self, date: Optional[str] = None) -> int:
        """Get signal count for a specific date."""
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        try:
            conn = sqlite3.connect(self.signals_db)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT COUNT(*) FROM signals 
                WHERE DATE(timestamp) = ?
            """, (date,))
            
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except Exception as e:
            print(f"Error fetching signal count: {e}")
            return 0
    
    def get_win_rate(self, days: int = 1) -> Optional[float]:
        """Calculate win rate for the last N days."""
        try:
            conn = sqlite3.connect(self.signals_db)
            cursor = conn.cursor()
            
            cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            cursor.execute("""
                SELECT 
                    SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses
                FROM signals 
                WHERE DATE(timestamp) >= ? AND outcome IS NOT NULL
            """, (cutoff_date,))
            
            wins, losses = cursor.fetchone()
            conn.close()
            
            if wins is None or losses is None:
                return None
            
            total = wins + losses
            return (wins / total * 100) if total > 0 else None
            
        except Exception as e:
            print(f"Error calculating win rate: {e}")
            return None
    
    def check_service_status(self) -> Dict[str, any]:
        """Check if systemd service is running."""
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', 'mumo-signal-service'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            is_running = result.stdout.strip() == 'active'
            
            # Get service uptime
            uptime_result = subprocess.run(
                ['systemctl', 'show', 'mumo-signal-service', '--property=ActiveEnterTimestamp'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            uptime_seconds = 0
            if is_running and uptime_result.returncode == 0:
                # Parse timestamp and calculate uptime
                timestamp_line = uptime_result.stdout.strip()
                # This will need proper parsing in production
                uptime_seconds = 0  # Placeholder
            
            return {
                'is_running': is_running,
                'uptime_seconds': uptime_seconds,
                'last_check': datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"Error checking service status: {e}")
            return {
                'is_running': False,
                'uptime_seconds': 0,
                'last_check': datetime.now().isoformat(),
                'error': str(e)
            }
    
    def get_last_signal_time(self) -> Optional[str]:
        """Get timestamp of most recent signal."""
        try:
            conn = sqlite3.connect(self.signals_db)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT MAX(timestamp) FROM signals
            """)
            
            last_time = cursor.fetchone()[0]
            conn.close()
            return last_time
            
        except Exception as e:
            print(f"Error fetching last signal time: {e}")
            return None
    
    def record_daily_metrics(self):
        """Calculate and store daily metrics."""
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Get metrics
        signal_count = self.get_daily_signal_count(today)
        win_rate = self.get_win_rate(days=1)
        service_status = self.check_service_status()
        
        # Store in metrics database
        conn = sqlite3.connect(self.metrics_db)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO daily_metrics 
            (date, total_signals, win_rate, service_uptime_pct)
            VALUES (?, ?, ?, ?)
        """, (today, signal_count, win_rate, 100.0 if service_status['is_running'] else 0.0))
        
        conn.commit()
        conn.close()
    
    def get_health_summary(self) -> Dict[str, any]:
        """Generate comprehensive health summary."""
        return {
            'timestamp': datetime.now().isoformat(),
            'signals_today': self.get_daily_signal_count(),
            'win_rate_24h': self.get_win_rate(days=1),
            'win_rate_7d': self.get_win_rate(days=7),
            'win_rate_30d': self.get_win_rate(days=30),
            'service_status': self.check_service_status(),
            'last_signal': self.get_last_signal_time()
        }


if __name__ == "__main__":
    # Test the health monitor
    monitor = HealthMonitor()
    summary = monitor.get_health_summary()
    
    print("📊 Signal Service Health Summary")
    print("=" * 50)
    print(f"Timestamp: {summary['timestamp']}")
    print(f"Signals Today: {summary['signals_today']}")
    print(f"Win Rate (24h): {summary['win_rate_24h']:.2f}%" if summary['win_rate_24h'] else "Win Rate (24h): N/A")
    print(f"Win Rate (7d): {summary['win_rate_7d']:.2f}%" if summary['win_rate_7d'] else "Win Rate (7d): N/A")
    print(f"Service Running: {'✅ Yes' if summary['service_status']['is_running'] else '❌ No'}")
    print(f"Last Signal: {summary['last_signal']}")
