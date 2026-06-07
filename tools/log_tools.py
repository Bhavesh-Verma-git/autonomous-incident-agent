# tools/log_tools.py - Pydantic models + query function for log retrieval.
#
# Input  model : LogQueryInput   -- what the caller passes in
# Output models: LogLine         -- one validated log entry
#                LogQueryResult  -- the full structured response
# Function     : query_logs()    -- reads logs.json, returns LogQueryResult

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Absolute path to the data file, resolved from THIS file's location.
# This works no matter which directory you run from (tests/, root, etc.)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOGS_FILE = os.path.join(_PROJECT_ROOT, "data", "synthetic", "logs.json")

# Internal design-annotation keys we embedded in the JSON for teaching purposes.
# These start with underscore and must be STRIPPED before passing to Pydantic,
# otherwise Pydantic sees unexpected fields and (in strict mode) raises errors.
_ANNOTATION_PREFIXES = ("_",)

_DATA_CACHE = None

def _load_data():
    global _DATA_CACHE
    if _DATA_CACHE is None:
        with open(_LOGS_FILE, "r", encoding="utf-8") as f:
            _DATA_CACHE = json.load(f)
    return _DATA_CACHE



def _strip_annotations(d: dict) -> dict:
    """Remove any key that starts with '_' from a dict (design notes, red herrings)."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


# ── Model: LogLine ─────────────────────────────────────────────────────────────

class LogLine(BaseModel):
    """
    One validated log entry parsed from synthetic data.

    WHY datetime for timestamp (not str)?
      Lets us compute: earliest_error - deploy_time  (Python timedelta)
      Pydantic auto-converts "2024-01-15T02:18:45Z" -> datetime object.
      If we stored str we'd need datetime.fromisoformat() everywhere — brittle.

    WHY str | None for trace_id / error_code?
      Synthetic data has "trace_id": null on INFO logs.
      Plain str would cause Pydantic to reject those valid entries.
    """
    timestamp: datetime
    level: str           # "ERROR", "WARN", "INFO", "DEBUG"
    service: str
    message: str
    trace_id: str | None = None      # null in JSON becomes None in Python
    error_code: str | None = None    # only present on error entries


# ── Model: LogQueryInput ───────────────────────────────────────────────────────

class LogQueryInput(BaseModel):
    """
    What the caller must provide to query logs for an incident.

    WHY Literal for level_filter?
      Without it, someone could pass "error" (lowercase) and the filter
      silently returns zero results instead of raising an error.
      Literal["ERROR", ...] catches the wrong value at the INPUT boundary.

    WHY bounds on limit (ge=1, le=200)?
      ge=1  -> prevents querying 0 logs (meaningless)
      le=200 -> prevents token budget explosion
    """
    incident_id: str = Field(
        ...,                          # '...' means REQUIRED, no default
        description="Incident to fetch logs for, e.g. 'INC-001'"
    )
    level_filter: list[Literal["ERROR", "WARN", "INFO", "DEBUG"]] = Field(
        default=["ERROR", "WARN"],
        description="Only return logs at these severity levels"
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Max number of log lines to return"
    )


# ── Model: LogQueryResult ──────────────────────────────────────────────────────

class LogQueryResult(BaseModel):
    """
    The structured result returned by query_logs().

    WHY pre-compute earliest_error?
      The correlation node must answer: "Did errors start AFTER the deploy?"
      We compute this in Python (deterministic) rather than asking the LLM
      to parse timestamps and find the minimum — LLMs are bad at arithmetic.

    WHY pre-compute error_codes_seen?
      Gives the correlation node a ready-made list like:
        ["DB_POOL_EXHAUSTED", "PAYMENT_CONFIRM_FAILED"]
      instead of forcing it to scan every log message again.

    WHY total_logs_found is the UNFILTERED count?
      Tells the downstream node how many logs the incident had in total,
      so it knows if it's only seeing a sample (when limit was applied).
    """
    incident_id: str
    service: str
    total_logs_found: int           # count BEFORE level_filter + limit
    logs: list[LogLine]             # the filtered, limited, validated entries
    earliest_error: datetime | None = None   # None if no ERROR-level logs
    error_codes_seen: list[str] = Field(
        default_factory=list,
        description="Unique error_code values across all returned logs"
    )


# ── Function: query_logs() ─────────────────────────────────────────────────────

def query_logs(query: LogQueryInput) -> LogQueryResult:
    """
    Read logs.json, find the incident, filter and validate the logs.

    Step-by-step walkthrough (useful for revision):

    1. LOAD   -- open the JSON file once and parse it
    2. FIND   -- iterate over incidents to find the one matching incident_id
    3. GUARD  -- raise ValueError immediately if incident_id doesn't exist
    4. FILTER -- keep only logs whose 'level' is in query.level_filter
    5. LIMIT  -- slice to query.limit entries (avoid token explosion)
    6. BUILD  -- convert each raw dict into a LogLine Pydantic object
                 (this is where Pydantic validates timestamps, etc.)
    7. DERIVE -- compute earliest_error and error_codes_seen in Python
    8. RETURN -- wrap everything into a LogQueryResult

    WHY raise ValueError instead of returning an empty result?
      An empty result looks like "no logs found" — a valid outcome.
      A missing incident_id is a programming error (wrong ID passed).
      These two cases must not look the same to the caller.
    """

    # ── Step 1: Load ───────────────────────────────────────────────────────────
    data = _load_data()
    incidents: list[dict] = data["incidents"]

    # ── Step 2: Find ───────────────────────────────────────────────────────────
    # next() with a default of None lets us search without a try/except.
    # The generator expression iterates until it finds the first match.
    incident = next(
        (inc for inc in incidents if inc["incident_id"] == query.incident_id),
        None   # default when no match is found
    )

    # ── Step 3: Guard ──────────────────────────────────────────────────────────
    if incident is None:
        raise ValueError(
            f"Incident '{query.incident_id}' not found in logs.json. "
            f"Valid IDs: {[i['incident_id'] for i in incidents]}"
        )

    raw_logs: list[dict] = incident.get("logs", [])   # empty list if key missing
    total_before_filter = len(raw_logs)                # save count BEFORE filtering

    # ── Step 4: Filter by level ────────────────────────────────────────────────
    # query.level_filter is already validated as Literal values (e.g. ["ERROR","WARN"])
    filtered = [log for log in raw_logs if log.get("level") in query.level_filter]

    # ── Step 5: Apply limit ────────────────────────────────────────────────────
    filtered = filtered[: query.limit]

    # ── Step 6: Build LogLine objects ──────────────────────────────────────────
    # Each raw dict may contain _design_note, _red_herring, etc.
    # We strip these annotation keys before passing to Pydantic because
    # they are not defined on LogLine — extra fields cause validation errors
    # in strict mode and are confusing to the LLM in any mode.
    log_lines: list[LogLine] = []
    for raw in filtered:
        clean = _strip_annotations(raw)
        log_lines.append(LogLine(
            timestamp=clean["timestamp"],
            level=clean["level"],
            service=clean["service"],
            message=clean["message"],
            trace_id=clean.get("trace_id"),       # may be absent or null
            error_code=clean.get("error_code"),   # may be absent
        ))

    # ── Step 7: Derive computed fields ─────────────────────────────────────────
    # earliest_error: look only at ERROR-level logs, find the minimum timestamp.
    # min() on an empty sequence raises ValueError, so we use default=None.
    error_timestamps = [
        line.timestamp for line in log_lines if line.level == "ERROR"
    ]
    earliest_error = min(error_timestamps, default=None)

    # error_codes_seen: unique, non-None error codes across all returned logs.
    # Set comprehension deduplicates; we convert to list for JSON serializability.
    error_codes_seen = list({
        line.error_code
        for line in log_lines
        if line.error_code is not None
    })

    # ── Step 8: Return ─────────────────────────────────────────────────────────
    return LogQueryResult(
        incident_id=query.incident_id,
        service=incident["affected_service"],  # from incident, not individual logs
        total_logs_found=total_before_filter,
        logs=log_lines,
        earliest_error=earliest_error,
        error_codes_seen=error_codes_seen,
    )
