from pathlib import Path

from langchain.tools import ToolRuntime, tool

# repo root = src/tools/logs_search.py -> tools -> src -> root
BASE_DIR = Path(__file__).resolve().parents[2]
LOG_FILE_PATH = BASE_DIR / "files" / "sample_logs.txt"

@tool
def get_logs(service_name: str, keyword: str, runtime: ToolRuntime = None):
    """Search logs from dummy file. Input: service_name like 'payment-service', keyword like 'ERROR' or 'Timeout'"""
    try:
        with open(LOG_FILE_PATH, 'r') as f:
            lines = f.readlines()
        
        # Filter by service_name
        matched = [line for line in lines if service_name in line and keyword.lower() in line.lower()]
        
        if not matched:
            return f"No logs found for {service_name} with keyword {keyword}"
        
        # Last 10 relevant logs matrame return - Agent ki context ekkuva ivvakudadu
        return "\n".join(line.rstrip("\n") for line in matched[-10:])
    except FileNotFoundError:
        return f"Log file not found. Make sure {LOG_FILE_PATH} exists"