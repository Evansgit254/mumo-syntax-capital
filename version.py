# Pure Quant Research Terminal Versioning Central
# Updated: 2026-07-01

VERSION_MAJOR = 5
VERSION_MINOR = 4
VERSION_PATCH = 1

# Status can be 'stable', 'beta', 'rc' (Release Candidate)
VERSION_STATUS = "stable"

RELEASE_NAME = "Deep History Stress Test"
RELEASE_NOTES = [
    "Added HistData.com automated M1 downloader (scripts/download_histdata.py).",
    "Routed DeepDataFetcher forex/H1 through local DukascopyLoader (M1 resample).",
    "DukascopyLoader now parses HistData semicolon-delimited ASCII format.",
    "Optimized backtest loop: searchsorted() replaces boolean masking (~100x faster).",
    "Added --symbols CLI flag for selective backtesting.",
    "Added verbose progress logging during data loading phase.",
    "Made ccxt import lazy (only needed for BTC-USD).",
    "Fixed win-counting: uses result=='TP1' instead of pips>0.",
    "Excluded OPEN/CLOSED/ERROR trades from header stats.",
]

def get_version():
    """Returns the full semantic version string."""
    version = f"{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}"
    if VERSION_STATUS != "stable":
        version += f"-{VERSION_STATUS}"
    return version

def get_system_banner():
    """Returns a visual banner for logs/CLIs."""
    return f"""
    ╔════════════════════════════════════════════════╗
    ║         PURE QUANT RESEARCH TERMINAL           ║
    ║                Version {get_version():<15} ║
    ║        {RELEASE_NAME:<34}║
    ╚════════════════════════════════════════════════╝
    """

if __name__ == "__main__":
    print(get_system_banner())
