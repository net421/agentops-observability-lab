# Integration guide

## Generic instrumentation

Create a session before recording related events. The schema enforces this relationship.

```python
from agentops_observability import AgentOpsStore, SessionEvent, ToolCallEvent

with AgentOpsStore("agentops.db") as store:
    store.insert_session(SessionEvent(session_id="job-42", provider="local", model="agent-v1"))
    store.insert_tool_call(ToolCallEvent(session_id="job-42", tool_name="search", latency_ms=85))
    store.update_session_status("job-42", "completed")
```

## MEL Governor

MEL Governor can record one session per research run, one LLM event per agent role, tool events for retrieval or file operations, and quality dimensions for source coverage, debate completion and validation status. This repository does not alter MEL Governor and does not require its package.

## Semantic Agent and Decision Twin

The same event contract can capture SQL planning, query execution, refusals, scenario simulation and human-approval gates. Integration is conceptual until an upstream repository explicitly pins and tests this package.
