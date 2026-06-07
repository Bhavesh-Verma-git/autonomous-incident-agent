# tools/metric_tools.py - Pydantic models + query function for metric retrieval.

from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel, Field

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOGS_FILE = os.path.join(_PROJECT_ROOT, "data", "synthetic", "logs.json")

_DATA_CACHE = None

def _load_data():
    global _DATA_CACHE
    if _DATA_CACHE is None:
        with open(_LOGS_FILE, "r", encoding="utf-8") as f:
            _DATA_CACHE = json.load(f)
    return _DATA_CACHE

# Anomaly thresholds — these are engineering judgement calls.
# If a metric exceeds its threshold we flag it in anomalous_metrics.
# The correlation node doesn't have to rediscover these; we pre-compute them.
_THRESHOLDS: dict[str, float] = {
    "error_rate_percent":            5.0,   # > 5% error rate is bad
    "latency_p99_ms":             1000.0,   # > 1 second P99 is bad
    "memory_percent":               85.0,   # > 85% memory is risky
    "cpu_percent":                  80.0,   # > 80% CPU is risky
    "db_connection_pool_waiting":    5.0,   # any waiting is a signal
    "redis_rejected_commands_per_min": 0.0, # any rejection is critical
    "disk_usage_percent":           90.0,   # > 90% disk is critical
    "pod_restarts_last_hour":        1.0,   # any pod restart is notable
    "thread_pool_utilization_percent": 80.0,
    "checkout_error_rate_percent":   5.0,
    "order_service_error_rate_percent": 5.0,
}


# ── Model: MetricQueryInput ────────────────────────────────────────────────────

class MetricQueryInput(BaseModel):
    """
    WHY metric_names is list[str] and NOT Literal?
      Each incident has DIFFERENT metric keys:
        INC-001: db_connection_pool_active, db_query_count_per_request
        INC-010: fedex_api_429_responses, fedex_api_rate_limit_per_minute
      We cannot use Literal because the valid values change per incident.
      Empty list = "return all metrics" (caller wants everything).
    """
    incident_id: str = Field(..., description="Incident whose metrics to retrieve")
    metric_names: list[str] = Field(
        default_factory=list,
        description="Specific metric keys to return. Empty = return all."
    )


# ── Model: MetricQueryResult ───────────────────────────────────────────────────

class MetricQueryResult(BaseModel):
    """
    WHY dict[str, Any] for metrics (not a fixed schema)?
      Our 15 incidents each have different metric shapes.
      A fixed schema would require 15 different models.
      dict[str, Any] is the pragmatic choice — the values are
      validated individually by the anomaly-detection logic below.

    WHY pre-compute anomalous_metrics?
      Instead of showing the LLM raw numbers and asking it to judge,
      we apply engineering thresholds in Python and hand the LLM a list:
        ["error_rate_percent", "db_connection_pool_waiting"]
      The LLM then explains WHY these are anomalous, not WHETHER they are.

    WHY has_deployment_red_herring?
      Several incidents have _red_herring keys in their metrics JSON.
      This bool tells the correlation node to be extra skeptical about
      blaming the deployment — the data is designed to mislead.
    """
    incident_id: str
    service: str
    metrics: dict[str, Any]            # cleaned (no _ annotation keys)
    anomalous_metrics: list[str] = Field(default_factory=list)
    has_deployment_red_herring: bool = False


# ── Function: query_metrics() ──────────────────────────────────────────────────

def query_metrics(query: MetricQueryInput) -> MetricQueryResult:
    """
    Read logs.json, find the incident, return clean validated metrics.

    Steps:
    1. LOAD   -- read logs.json
    2. FIND   -- locate incident by incident_id
    3. GUARD  -- raise if not found
    4. CLEAN  -- strip all keys starting with '_' (design annotations)
    5. FILTER -- if metric_names specified, keep only those keys
    6. FLAG   -- check if raw metrics had any _red_herring keys
    7. DETECT -- compare each metric value to _THRESHOLDS
    8. RETURN -- build MetricQueryResult
    """

    # Step 1 & 2: Load and find
    data = _load_data()

    incident = next(
        (i for i in data["incidents"] if i["incident_id"] == query.incident_id),
        None
    )

    # Step 3: Guard
    if incident is None:
        raise ValueError(f"Incident '{query.incident_id}' not found in logs.json")

    raw_metrics: dict = incident.get("metrics", {})

    # Step 4: Detect red herrings BEFORE cleaning (annotation keys get stripped)
    has_red_herring = any(k.startswith("_red_herring") for k in raw_metrics)

    # Step 5: Clean — strip all annotation keys (those starting with '_')
    clean_metrics = {k: v for k, v in raw_metrics.items() if not k.startswith("_")}

    # Step 6: Filter — if caller wants specific metrics, honour that
    if query.metric_names:
        clean_metrics = {
            k: v for k, v in clean_metrics.items()
            if k in query.metric_names
        }

    # Step 7: Detect anomalies using thresholds
    # Only numeric metrics (int, float) are comparable to thresholds.
    # List metrics (like affected_services) are skipped.
    anomalous: list[str] = []
    for metric_name, value in clean_metrics.items():
        if isinstance(value, (int, float)) and metric_name in _THRESHOLDS:
            if value > _THRESHOLDS[metric_name]:
                anomalous.append(metric_name)

    # Step 8: Return
    return MetricQueryResult(
        incident_id=query.incident_id,
        service=incident["affected_service"],
        metrics=clean_metrics,
        anomalous_metrics=anomalous,
        has_deployment_red_herring=has_red_herring,
    )
