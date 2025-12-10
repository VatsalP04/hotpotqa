"""
LangSmith integration helpers for query decomposition.

Provides utilities for adding metadata and tags to LangSmith traces.
"""

import os
from typing import Optional, Dict, List, Any

try:
    from langsmith import traceable, Client
    LANGSMITH_AVAILABLE = True
except ImportError:
    LANGSMITH_AVAILABLE = False
    traceable = lambda **kwargs: lambda f: f
    Client = None


def get_langsmith_project() -> str:
    """Get LangSmith project name from environment."""
    return os.environ.get("LANGSMITH_PROJECT", "query-decomposition")


def is_langsmith_enabled() -> bool:
    """Check if LangSmith tracing is enabled."""
    return (
        LANGSMITH_AVAILABLE and 
        os.environ.get("LANGSMITH_TRACING", "false").lower() == "true"
    )


def create_traceable_decorator(
    name: str,
    step: str,
    metadata: Optional[Dict[str, Any]] = None,
    tags: Optional[List[str]] = None,
) -> callable:
    """
    Create a traceable decorator with metadata for decomposition steps.
    
    Args:
        name: Name of the trace
        step: Step type (planning, sub_answer, final_answer, query_rewrite)
        metadata: Additional metadata to include
        tags: Additional tags to include
    
    Returns:
        Decorator function
    """
    if not is_langsmith_enabled():
        return lambda f: f
    
    trace_metadata = {
        "step": step,
        "method": "query_decomposition",
    }
    if metadata:
        trace_metadata.update(metadata)
    
    trace_tags = ["decomposition", step]
    if tags:
        trace_tags.extend(tags)
    
    return traceable(
        name=name,
        run_type="llm",
        project_name=get_langsmith_project(),
        metadata=trace_metadata,
        tags=trace_tags,
    )


def add_metadata_to_trace(metadata: Dict[str, Any]) -> None:
    """
    Add metadata to the current LangSmith trace.
    
    This uses LangSmith's context manager if available.
    """
    if not is_langsmith_enabled():
        return
    
    try:
        from langsmith.run_helpers import tracing_context
        
        with tracing_context(metadata=metadata):
            pass
    except ImportError:
        # Fallback: metadata will be added via decorator
        pass

