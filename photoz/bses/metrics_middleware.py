import json
import time
import logging
from contextlib import contextmanager
from django.db import connection

logger = logging.getLogger('metrics')


class QueryTimer:
    def __init__(self):
        self.query_count = 0
        self.total_db_time = 0.0

    def __call__(self, execute, sql, params, many, context):
        start = time.time()
        try:
            return execute(sql, params, many, context)
        finally:
            self.total_db_time += time.time() - start
            self.query_count += 1


class CloudWatchMetricsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        query_timer = QueryTimer()
        start = time.time()

        with connection.execute_wrapper(query_timer):
            response = self.get_response(request)

        request_latency_ms = (time.time() - start) * 1000
        db_latency_ms = query_timer.total_db_time * 1000
        query_count = query_timer.query_count
        if hasattr(request, 'resolver_match') and request.resolver_match:
            endpoint = request.resolver_match.view_name
        else:
            endpoint = request.path
        method = request.method
        status_code = response.status_code

        # Skip health check noise (Consul pings / every 10s, gets 302 redirect)
        if status_code == 302 and query_count == 0:
            return response

        emf_payload = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "PhotoZ/Application",
                        "Dimensions": [["Endpoint", "Method"]],
                        "Metrics": [
                            {"Name": "RequestLatency", "Unit": "Milliseconds"},
                            {"Name": "DatabaseLatency", "Unit": "Milliseconds"},
                            {"Name": "QueryCount", "Unit": "Count"},
                        ],
                    }
                ],
            },
            "Endpoint": endpoint,
            "Method": method,
            "StatusCode": status_code,
            "RequestLatency": round(request_latency_ms, 2),
            "DatabaseLatency": round(db_latency_ms, 2),
            "QueryCount": query_count,
        }

        logger.info(json.dumps(emf_payload))

        return response
