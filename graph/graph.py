"""
graph/graph.py — LangGraph incident-response graph.

Architecture:
  START
    │
    ├─► log_analysis_node ─────────────┐
    ├─► metric_analysis_node ──────────┤  (run in sequence — LangGraph 0.2
    └─► deployment_analysis_node ──────┘   does not parallelize by default)
                                       │
                               correlation_node
                                       │
                        add_conditional_edges (route_after_correlation)
                          │                       │
                    hitl_node            report_generation_node
                   [interrupt]                    │
                       │              memory_store_node
                 correlation_node               │
                   (re-runs with               END
                   human context)
"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.constants import Send

from graph.state import IncidentState
from agents.nodes import (
    log_analysis_node,
    metric_analysis_node,
    deployment_analysis_node,
    join_node,
    memory_retrieval_node,
    correlation_node,
    route_after_correlation,
    hitl_node,
    report_generation_node,
    memory_store_node,
)
import config


def build_graph(checkpointer=None):
    """
    Build and compile the incident-response StateGraph.

    Args:
        checkpointer: A LangGraph checkpointer instance.
                      Pass SqliteSaver for production/HITL.
                      Pass None (or MemorySaver) for simple unit tests.

    Returns:
        CompiledGraph ready to invoke.
    """
    builder = StateGraph(IncidentState)

    # ── 1. Register every node ────────────────────────────────────────────────
    builder.add_node("log_analysis_node",        log_analysis_node)
    builder.add_node("metric_analysis_node",     metric_analysis_node)
    builder.add_node("deployment_analysis_node", deployment_analysis_node)
    builder.add_node("join_node",                join_node)            # fan-in barrier
    builder.add_node("memory_retrieval_node",    memory_retrieval_node)
    builder.add_node("correlation_node",         correlation_node)
    builder.add_node("hitl_node",                hitl_node)
    builder.add_node("report_generation_node",   report_generation_node)
    builder.add_node("memory_store_node",        memory_store_node)

    # ── 2. Execution Mode (Sequential vs Parallel) ───────────────────────────
    if getattr(config, "EXECUTION_MODE", "parallel") == "sequential":
        # Run sequentially to save rate limits (log -> metric -> deployment -> join)
        builder.add_edge(START, "log_analysis_node")
        builder.add_edge("log_analysis_node", "metric_analysis_node")
        builder.add_edge("metric_analysis_node", "deployment_analysis_node")
        builder.add_edge("deployment_analysis_node", "join_node")
    else:
        # Run in parallel (fast, but requires high API rate limits)
        def start_all_analysis(state: IncidentState):
            return [
                Send("log_analysis_node", state),
                Send("metric_analysis_node", state),
                Send("deployment_analysis_node", state),
            ]
        builder.add_conditional_edges(START, start_all_analysis)
        builder.add_edge("log_analysis_node", "join_node")
        builder.add_edge("metric_analysis_node", "join_node")
        builder.add_edge("deployment_analysis_node", "join_node")

    # Single path from fan-in onward
    builder.add_edge("join_node",             "memory_retrieval_node")
    builder.add_edge("memory_retrieval_node", "correlation_node")

    # ── 3. Conditional edge at correlation ────────────────────────────────────
    # route_after_correlation returns "hitl_node" or "report_generation_node"
    builder.add_conditional_edges(
        "correlation_node",
        route_after_correlation,
        {
            "hitl_node":              "hitl_node",
            "report_generation_node": "report_generation_node",
        },
    )

    # ── 4. HITL loop → back to correlation with human context ─────────────────
    builder.add_edge("hitl_node", "correlation_node")

    # ── 5. Happy path → report → memory → END ────────────────────────────────
    builder.add_edge("report_generation_node", "memory_store_node")
    builder.add_edge("memory_store_node",      END)

    # ── 6. Compile ────────────────────────────────────────────────────────────
    # interrupt_before=["hitl_node"] means:
    #   "Pause execution BEFORE hitl_node runs, save state, return to caller."
    # The node will run on the NEXT invoke() with the same thread_id.
    compiled = builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["hitl_node"],
    )

    return compiled


def get_graph():
    """
    Convenience function that returns a graph with a persistent checkpointer.
    Used by main.py and the FastAPI layer.

    SqliteSaver keeps node state in SQLite so it survives restarts.
    """
    import os
    import sqlite3

    os.makedirs("memory", exist_ok=True)
    
    # We create a persistent connection that stays open for the life of the FastAPI process.
    conn = sqlite3.connect(config.SQLITE_DB_PATH, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    
    return build_graph(checkpointer=checkpointer)

