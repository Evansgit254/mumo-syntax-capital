import os

REPLACEMENTS = {
    "mumo-*.service": "mumo-*.service",
    "mumo-*": "mumo-*",
    "mumo-backups": "mumo-backups",
    "SyslogIdentifier=mumo-": "SyslogIdentifier=mumo-",
    "Mumo-Trading-Bot": "Mumo-Trading-Bot",
    "mumo-trading-bot": "mumo-trading-bot",
    "mumo-syntax-capital": "mumo-syntax-capital", # Catch-all for pine script URL
}

def process_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        original_content = content
        for old_str, new_str in REPLACEMENTS.items():
            content = content.replace(old_str, new_str)
            
        if content != original_content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Updated {filepath}")
    except Exception as e:
        pass # Skip binaries or unreadable files

def main():
    exclude_dirs = {'.git', '.venv', 'venv', '__pycache__'}
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for file in files:
            if file.endswith(('.py', '.sh', '.md', '.service', '.timer', '.html', '.bat', '.json', '.pine')):
                process_file(os.path.join(root, file))

if __name__ == '__main__':
    main()
