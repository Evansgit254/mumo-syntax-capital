import os
import psutil
import time
import subprocess

# --- CONFIGURATION ---
THRESHOLD_MB = 150  # Restart services if available memory < 150MB
SLEEP_INTERVAL = 300 # Run every 5 minutes

SERVICES = [
    "mumo-signal-service.service",
    "mumo-interactive-bot.service",
    "mumo-admin-dashboard.service",
    "mumo-signal-tracker.service"
]

def clear_system_caches():
    """Clears pagecache, dentries, and inodes."""
    print("🧹 Clearing system caches...")
    try:
        subprocess.run(["sudo", "sync"], check=True)
        with open("/proc/sys/vm/drop_caches", "w") as f:
            f.write("3")
        print("✅ Cache cleared.")
    except Exception as e:
        print(f"❌ Error clearing cache: {e}")

def check_memory_and_guard():
    mem = psutil.virtual_memory()
    available_mb = mem.available / (1024 * 1024)
    
    print(f"📊 Memory Check: {available_mb:.2f}MB available.")
    
    if available_mb < THRESHOLD_MB:
        print(f"🚨 CRITICAL MEMORY: {available_mb:.2f}MB < {THRESHOLD_MB}MB")
        clear_system_caches()
        
        # Check again after cache clear
        mem = psutil.virtual_memory()
        if (mem.available / (1024 * 1024)) < THRESHOLD_MB:
            print("⚠️ Cache clear insufficient. Restarting SMC services to free RAM...")
            for service in SERVICES:
                subprocess.run(["sudo", "systemctl", "restart", service])
            print("✅ Services restarted.")
    else:
        print("✅ Memory healthy.")

if __name__ == "__main__":
    print("🛡️ MUMO MEMORY GUARD STARTING (V23.1.3)")
    while True:
        check_memory_and_guard()
        time.sleep(SLEEP_INTERVAL)
