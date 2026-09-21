from pathlib import Path

from langchain.tools import ToolRuntime, tool

# repo root = src/tools/metrics_search.py -> tools -> src -> root
BASE_DIR = Path(__file__).resolve().parents[2]
METRICS_FILE_PATH = BASE_DIR / "files" / "sample_metrics.txt"

@tool
def get_metrics(service_name: str, runtime: ToolRuntime = None):
    """Get current metrics for a service like cpu, memory, error_rate, latency. Input: service_name"""
    try:
        with open(METRICS_FILE_PATH, 'r') as f:
            lines = f.readlines()
        
        matched = [line.strip() for line in lines if service_name in line]
        
        if not matched:
            return f"No metrics found for {service_name}"
        
        # Critical metrics first
        critical = [m for m in matched if "CRITICAL" in m]
        others = [m for m in matched if "CRITICAL" not in m]
        
        result = critical + others
        
        return "\n".join(result)
    except FileNotFoundError:
        return f"Metrics file not found. Make sure {METRICS_FILE_PATH} exists"