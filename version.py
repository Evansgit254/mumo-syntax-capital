# Pure Quant Research Terminal Versioning Central
# Updated: 2026-06-26

VERSION_MAJOR = 5
VERSION_MINOR = 4
VERSION_PATCH = 0

# Status can be 'stable', 'beta', 'rc' (Release Candidate)
VERSION_STATUS = "stable"

RELEASE_NAME = "Client Portal API & Infrastructure"
RELEASE_NOTES = [
    "Introduced Client Portal Product Plan and core API foundation.",
    "Added client preferences and signal entitlement database schemas.",
    "Enhanced alert services and trade execution reliability.",
    "Expanded test coverage for server configuration and client APIs.",
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
