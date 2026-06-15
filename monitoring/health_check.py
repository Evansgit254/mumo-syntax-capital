import requests
import subprocess
import os
import time
import logging

# Configuration
URL = "http://localhost:5000"
EXPECTED_PROCESSES = ["signal_service.py", "admin_server.py"]
MAX_RETRIES = 3
CHECK_INTERVAL = 300 # 5 minutes

logging.basicConfig(
    filename="monitoring/health.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def check_process(name):
    try:
        output = subprocess.check_output(["ps", "aux"]).decode()
        return name in output
    except Exception:
        return False

def check_dashboard():
    try:
        response = requests.head(URL, timeout=5)
        return response.status_code == 200
    except Exception:
        return False

def restart_services():
    logging.warning("⚠️  Governance Failure Detected. Triggering Auto-Heal (start_all.sh)...")
    try:
        # We use a hard reset since we likely have a port squatting or permission issue
        subprocess.run(["/home/evans/mumo-syntax-capital/start_all.sh"], shell=True)
    except Exception as e:
        logging.error(f"❌ Auto-Heal Failed: {e}")

def main():
    retries = 0
    while True:
        dashboard_up = check_dashboard()
        processes_up = all(check_process(p) for p in EXPECTED_PROCESSES)
        
        if not dashboard_up or not processes_up:
            retries += 1
            logging.warning(f"🕵️  Health Check Failed ({retries}/{MAX_RETRIES}). Dashboard: {dashboard_up}, Processes: {processes_up}")
            
            if retries >= MAX_RETRIES:
                restart_services()
                retries = 0
        else:
            if retries > 0:
                logging.info("✅ Health Restored.")
            retries = 0
            
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    # Ensure monitoring dir exists
    os.makedirs("monitoring", exist_ok=True)
    logging.info("🛰️  Institutional Health Watchdog Started.")
    main()
