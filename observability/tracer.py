"""
observability/tracer.py — Langfuse tracing integration (boilerplate).

Langfuse works by wrapping LangChain's callback system.
Every LLM call made through LangChain will be automatically traced
when you pass the handler into your chain/graph invocation.

Usage in a node:
    from observability.tracer import get_langfuse_handler
    handler = get_langfuse_handler(trace_name="log_analysis")
    result = llm.invoke(prompt, config={"callbacks": [handler]})

Usage with LangGraph graph invocation:
    from observability.tracer import get_langfuse_handler
    handler = get_langfuse_handler(trace_name="incident_investigation")
    graph.invoke(initial_state, config={"callbacks": [handler]})
"""

from langfuse.callback import CallbackHandler
import config


def get_langfuse_handler(
    trace_name: str = "incident_response",
    user_id: str | None = None,
    session_id: str | None = None,
    metadata: dict | None = None,
) -> CallbackHandler:
    """
    Create a Langfuse callback handler for a single trace.

    Each call to this function creates a new trace in Langfuse.
    Pass the returned handler into any LangChain/LangGraph invocation
    via the `callbacks` config key.

    Args:
        trace_name:  Appears as the trace name in Langfuse UI
        user_id:     Optional user identifier for filtering
        session_id:  Optional session ID to group related traces
        metadata:    Extra key-value pairs attached to the trace

    Returns:
        A configured CallbackHandler ready for use
    """
    return CallbackHandler(
        public_key=config.LANGFUSE_PUBLIC_KEY,
        secret_key=config.LANGFUSE_SECRET_KEY,
        host=config.LANGFUSE_HOST,
        trace_name=trace_name,
        user_id=user_id,
        session_id=session_id,
        metadata=metadata or {},
    )
