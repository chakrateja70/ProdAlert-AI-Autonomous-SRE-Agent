from src.tools.metrics_search import get_metrics
print(get_metrics.invoke({"service_name": "payment-service"}))

from src.tools.logs_search import get_logs
print(get_logs.invoke({"service_name": "payment-service", "keyword": "ERROR"}))