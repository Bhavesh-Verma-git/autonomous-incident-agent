"""
api/runner.py — Background graph execution with SSE event publishing.

Runs LangGraph in a background thread so FastAPI returns HTTP 202 immediately.
Uses LangGraph's stream() method to capture per-node events and publish them
to the IncidentRecord's event bus for real-time SSE streaming to clients.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from agents.models import Alert
from api.store import IncidentStore, IncidentRecord
from observability.tracer import get_langfuse_handler

log = logging.getLogger(__name__)


def _run_graph_thread(
    graph,
    store:         IncidentStore,
    record:        IncidentRecord,
    initial_state: dict,
    run_config:    dict,
) -> None:
    """
    Worker function executed in a background thread.

    Uses graph.stream() with stream_mode="updates" to get per-node deltas.
    Each node completion is published to the record's event bus so SSE
    clients can display real-time progress.
    """
    record.mark_running()
    log.info(f"[runner] Starting graph for incident {record.incident_id}")

    # ── Langfuse: one trace per incident ─────────────────────────────
    try:
        lf_handler = get_langfuse_handler(
            trace_name = "incident_investigation",
            session_id = record.incident_id,
            metadata   = {
                "service":  record.service,
                "severity": record.severity,
            },
        )
        run_config["callbacks"] = [lf_handler]
    except Exception:
        log.warning("[runner] Langfuse unavailable — tracing disabled for this run")

    try:
        final_state = None

        # stream() yields {"node_name": {state_delta}} after each node finishes
        for chunk in graph.stream(initial_state, run_config, stream_mode="updates"):
            for node_name, node_output in chunk.items():
                if node_name == "__interrupt__":
                    continue
                log.info(f"[runner] Node completed: {node_name}")

                # Build a human-friendly event for the dashboard
                event_data = _build_node_event(node_name, node_output)
                record.publish(event_data)

                # Track latest state by merging updates
                if final_state is None:
                    final_state = dict(initial_state)
                final_state.update(node_output)

        # Stream finished — check if we're paused at HITL or truly done
        if final_state and final_state.get("needs_human_input"):
            log.info(f"[runner] Graph paused at HITL for {record.incident_id}")
            record.mark_waiting()
            record.final_state = final_state
        else:
            log.info(f"[runner] Graph completed for {record.incident_id}")
            record.mark_completed(final_state or {})

    except Exception as exc:
        log.exception(f"[runner] Graph crashed for {record.incident_id}: {exc}")
        record.mark_failed(str(exc))


def _resume_graph_thread(
    graph,
    store:      IncidentStore,
    record:     IncidentRecord,
    run_config: dict,
) -> None:
    """
    Worker function for resuming a HITL-paused graph.
    LangGraph resumes from checkpoint when invoke() is called again with same thread_id.
    """
    record.mark_running()   # persists RUNNING status to SQLite via _save_callback
    record.publish({"event": "status", "data": "running", "message": "Resuming with engineer input..."})
    log.info(f"[runner] Resuming graph for incident {record.incident_id}")

    # ── Langfuse: continuation trace for the HITL resume ────────────────
    try:
        lf_handler = get_langfuse_handler(
            trace_name = "incident_investigation_resume",
            session_id = record.incident_id,
            metadata   = {"phase": "hitl_resume"},
        )
        run_config["callbacks"] = [lf_handler]
    except Exception:
        log.warning("[runner] Langfuse unavailable — tracing disabled for HITL resume")

    try:
        final_state = None

        for chunk in graph.stream(None, run_config, stream_mode="updates"):
            for node_name, node_output in chunk.items():
                if node_name == "__interrupt__":
                    continue
                log.info(f"[runner] (resume) Node completed: {node_name}")
                event_data = _build_node_event(node_name, node_output)
                record.publish(event_data)
                if final_state is None:
                    final_state = {}
                final_state.update(node_output)

        if final_state and final_state.get("needs_human_input"):
            log.info(f"[runner] Graph paused at HITL again for {record.incident_id}")
            record.mark_waiting()
            record.final_state = final_state
        else:
            log.info(f"[runner] Graph completed after resume for {record.incident_id}")
            record.mark_completed(final_state or {})

    except Exception as exc:
        log.exception(f"[runner] Graph crashed during resume for {record.incident_id}: {exc}")
        record.mark_failed(str(exc))


def _build_node_event(node_name: str, node_output: dict) -> dict:
    """
    Convert a raw LangGraph node output dict into a structured dashboard event.
    Extracts a human-readable summary from whichever analysis model is present.
    """
    if not isinstance(node_output, dict):
        return {
            "event":     "node_complete",
            "node":      node_name,
            "label":     node_name,
            "summary":   "Completed.",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # Map node names to friendly display names
    NODE_LABELS = {
        "log_analysis_node":        "📋 Log Analysis",
        "metric_analysis_node":     "📈 Metric Analysis",
        "deployment_analysis_node": "🚀 Deployment Analysis",
        "memory_retrieval_node":    "🧠 Memory Retrieval",
        "correlation_node":         "🔗 Correlation",
        "hitl_node":                "👤 Human Review",
        "report_generation_node":   "📄 Report Generation",
        "memory_store_node":        "💾 Memory Store",
    }
    label = NODE_LABELS.get(node_name, node_name)

    # Try to extract a text summary from common state fields
    summary = ""
    for key in ("log_analysis", "metric_analysis", "deployment_analysis"):
        obj = node_output.get(key)
        if obj and hasattr(obj, "summary"):
            summary = obj.summary
            break
    if not summary:
        obj = node_output.get("root_cause")
        if obj and hasattr(obj, "hypothesis"):
            summary = f"Hypothesis: {obj.hypothesis[:120]}"
            conf = getattr(obj, "confidence_score", None)
            if conf is not None:
                summary += f" (confidence: {conf:.0%})"
    if not summary:
        obj = node_output.get("incident_report")
        if obj and hasattr(obj, "report_id"):
            summary = f"Report {obj.report_id} generated."
    if not summary:
        obj = node_output.get("past_similar_incidents")
        if obj:
            summary = f"Retrieved {len(obj)} similar past incidents."
        else:
            summary = "Complete."

    return {
        "event":     "node_complete",
        "node":      node_name,
        "label":     label,
        "summary":   summary,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Public API ────────────────────────────────────────────────────────────────

def start_incident(
    graph,
    store:    IncidentStore,
    record:   IncidentRecord,
    alert:    Alert,
) -> None:
    """Launch the graph in a background thread. Returns immediately (HTTP 202)."""
    initial_state = {
        "alert":                  alert,
        "log_analysis":           None,
        "metric_analysis":        None,
        "deployment_analysis":    None,
        "log_status":             "pending",
        "metric_status":          "pending",
        "deployment_status":      "pending",
        "past_similar_incidents": None,
        "root_cause":             None,
        "needs_human_input":      False,
        "human_input":            None,
        "hitl_iteration":         0,
        "incident_report":        None,
    }
    run_config = {"configurable": {"thread_id": record.incident_id}}

    thread = threading.Thread(
        target=_run_graph_thread,
        args=(graph, store, record, initial_state, run_config),
        daemon=True,
        name=f"graph-{record.incident_id}",
    )
    thread.start()
    log.info(f"[runner] Launched thread '{thread.name}'")


def resume_incident(
    graph,
    store:       IncidentStore,
    record:      IncidentRecord,
    human_input: str,
) -> None:
    """Inject human context into a HITL-paused graph and resume execution."""
    run_config = {"configurable": {"thread_id": record.incident_id}}

    # Inject the engineer's context into the checkpointed state
    graph.update_state(
        config=run_config,
        values={"human_input": human_input, "needs_human_input": False},
    )

    thread = threading.Thread(
        target=_resume_graph_thread,
        args=(graph, store, record, run_config),
        daemon=True,
        name=f"graph-resume-{record.incident_id}",
    )
    thread.start()
    log.info(f"[runner] Launched resume thread '{thread.name}'")
