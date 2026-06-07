# tools/deployment_tools.py - Pydantic models + query function for deployment history.

from __future__ import annotations

import json
import os
from datetime import datetime

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

# ── Model: DeploymentRecord ────────────────────────────────────────────────────

class DeploymentRecord(BaseModel):
    """
    One validated deployment event.

    WHY datetime for deployed_at (not str)?
      We need to compute: (incident_time - deployed_at).total_seconds() / 60
      Python can only do timedelta arithmetic on datetime objects, not strings.
      If we stored str, the LLM would have to estimate the gap — unreliable.

    WHY pre-compute minutes_before_incident?
      LLMs are bad at mental arithmetic on timestamps.
      "24.0 minutes before incident" is immediately actionable.
      "2024-01-15T02:02:00Z vs 2024-01-15T02:26:00Z" requires mental effort.

    WHY pre-compute is_same_service?
      The single most important signal: did the AFFECTED service get deployed?
      is_same_service=True + minutes_before_incident < 30 = very suspicious.
      We do this boolean logic in Python, not in the LLM's reasoning.
    """
    deploy_id: str
    service: str
    version: str
    deployed_at: datetime                  # NOT str -- enables timedelta
    deployed_by: str
    commit_message: str
    files_changed: list[str]
    rollback_available: bool
    status: str
    minutes_before_incident: float         # pre-computed, always positive
    is_same_service: bool                  # deploy.service == incident.affected_service


# ── Model: DeploymentQueryInput ───────────────────────────────────────────────

class DeploymentQueryInput(BaseModel):
    """
    WHY hours_before_incident has bounds (ge=1, le=24)?
      INC-002 had a 4-hour gap between deploy and failure.
      If we only looked 1 hour back, we'd miss it.
      24-hour cap prevents returning unrelated week-old deploys as noise.

    WHY include_other_services defaults to True?
      Several incidents have RED HERRING deployments from OTHER services
      that happened just before the incident.
      A good agent should SEE the red herrings and REJECT them — not have
      them hidden. include_other_services=True is the honest approach.
      You can set False to test the agent with no distractions.
    """
    incident_id: str = Field(..., description="Incident to retrieve deployment history for")
    hours_before_incident: int = Field(
        default=2,
        ge=1,
        le=24,
        description="How many hours before the incident timestamp to look back"
    )
    include_other_services: bool = Field(
        default=True,
        description="Include deployments of other services (surfaces red herrings)"
    )


# ── Model: DeploymentQueryResult ──────────────────────────────────────────────

class DeploymentQueryResult(BaseModel):
    """
    WHY has_any_deployment as a top-level bool?
      INC-007 (report-generator), INC-008 (media-service), INC-010 (shipping)
      have NO recent deployments. recent_deployments=[] is ambiguous — did we
      look and find nothing, or did we forget to look?
      has_any_deployment=False is explicit: "we looked, there was nothing."
      This prevents the LLM from hallucinating a phantom deployment.
    """
    incident_id: str
    incident_time: datetime
    deployments: list[DeploymentRecord]
    total_deployments_found: int
    has_any_deployment: bool


# ── Function: query_deployments() ─────────────────────────────────────────────

def query_deployments(query: DeploymentQueryInput) -> DeploymentQueryResult:
    """
    Read logs.json, find the incident, return deployment records in the window.

    Steps:
    1. LOAD        -- read logs.json
    2. FIND        -- locate incident by incident_id
    3. GUARD       -- raise if not found
    4. PARSE TIME  -- convert incident timestamp to timezone-aware datetime
    5. ITERATE     -- for each raw deployment in recent_deployments:
                       a. strip annotation keys
                       b. parse deployed_at as datetime
                       c. compute minutes_before_incident
                       d. compute is_same_service
                       e. apply hours_before_incident window filter
                       f. apply include_other_services filter
                       g. build DeploymentRecord
    6. RETURN      -- wrap in DeploymentQueryResult
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

    # Step 4: Parse incident time
    # The timestamp field is an ISO string like "2024-01-15T02:26:00Z"
    # We must make it timezone-aware (UTC) so we can subtract deployed_at
    # which Pydantic will also parse as timezone-aware.
    incident_time = datetime.fromisoformat(
        incident["timestamp"].replace("Z", "+00:00")
    )

    raw_deployments: list[dict] = incident.get("recent_deployments", [])

    # Step 5: Iterate and build validated DeploymentRecord objects
    records: list[DeploymentRecord] = []
    for raw in raw_deployments:
        # 5a. Strip annotation keys like _design_note
        clean = {k: v for k, v in raw.items() if not k.startswith("_")}

        # 5b. Parse deployed_at — could be "2024-01-15T02:02:00Z"
        deployed_at_str = clean["deployed_at"].replace("Z", "+00:00")
        deployed_at = datetime.fromisoformat(deployed_at_str)

        # 5c. Compute time gap — always positive because deploy is BEFORE incident
        # total_seconds() handles gaps > 60 minutes correctly (unlike .seconds)
        gap_seconds = (incident_time - deployed_at).total_seconds()
        minutes_before = round(gap_seconds / 60, 1)

        # 5d. Window filter — skip deploys outside the requested lookback window
        if minutes_before > query.hours_before_incident * 60:
            continue
        if minutes_before < 0:
            # Deploy happened AFTER the incident — exclude (shouldn't happen in our data)
            continue

        # 5e. is_same_service check
        is_same = clean["service"] == incident["affected_service"]

        # 5f. Filter out other-service deploys if caller doesn't want them
        if not query.include_other_services and not is_same:
            continue

        # 5g. Build the validated model
        records.append(DeploymentRecord(
            deploy_id=clean["deploy_id"],
            service=clean["service"],
            version=clean["version"],
            deployed_at=deployed_at,
            deployed_by=clean["deployed_by"],
            commit_message=clean["commit_message"],
            files_changed=clean.get("files_changed", []),
            rollback_available=clean.get("rollback_available", True),
            status=clean["status"],
            minutes_before_incident=minutes_before,
            is_same_service=is_same,
        ))

    # Step 6: Return
    return DeploymentQueryResult(
        incident_id=query.incident_id,
        incident_time=incident_time,
        deployments=records,
        total_deployments_found=len(records),
        has_any_deployment=len(records) > 0,
    )
