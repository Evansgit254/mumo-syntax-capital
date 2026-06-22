# Pure Quant Research Terminal Versioning Central
# Updated: 2026-05-29

VERSION_MAJOR = 5
VERSION_MINOR = 3
VERSION_PATCH = 1

# Status can be 'stable', 'beta', 'rc' (Release Candidate)
VERSION_STATUS = "stable"

RELEASE_NAME = "Robust MT5 Integration & Quant Audit"
RELEASE_NOTES = [
    "Enhanced MetaTrader 5 connection reliability in Windows VPS environments with multi-strategy discovery.",
    "Cleaned dependency versions in requirements.txt to prevent setup errors.",
    "Conducted quantitative audit of backtest database runs confirming CRT H1 mathematical edge.",
    "Fixed escape character syntax error in Windows VPS startup batch script.",
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
