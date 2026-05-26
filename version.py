# SMC Institutional Trading System Versioning Central
# Generated: 2026-05-26

VERSION_MAJOR = 5
VERSION_MINOR = 1
VERSION_PATCH = 1

# Status can be 'stable', 'beta', 'rc' (Release Candidate)
VERSION_STATUS = "stable"

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
    ║        SMC INSTITUTIONAL TRADING SYSTEM        ║
    ║                Version {get_version():<15} ║
    ╚════════════════════════════════════════════════╝
    """

if __name__ == "__main__":
    print(get_system_banner())
