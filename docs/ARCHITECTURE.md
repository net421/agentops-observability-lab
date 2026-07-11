# Architecture

## Design goals

- Local-first operation with no required services.
- Deterministic, inspectable evidence.
- A small event contract usable by unrelated agent systems.
- Separation of writes (instrumentation) from reads (dashboards and sidecar).
- Fail-closed validation of malformed inputs and unsafe tool names.

## Components

### Event store

`AgentOpsStore` owns one SQLite connection, initializes the versioned schema and exposes typed insert methods. Foreign keys and bounded event validation prevent orphaned or invalid records.

### Metrics

Metrics open an existing database in URI read-only mode. They return aggregate counts, tokens, latency, tool success and quality scores. The text dashboard is deliberately dependency-free.

### Evaluation harness

JSONL cases define expected tools, expected citations, checks and latency budgets. The runner calculates precision, recall, exact task success and aggregate quality. The bundled simulator is deterministic and validates evaluation plumbing, not a model's real intelligence.

### Read-only sidecar

The sidecar exposes allow-listed tool-shaped functions. It never accepts arbitrary SQL and never opens an input database for writing. A later integration could wrap these functions in an MCP transport without changing their trust boundary.

## Integration contract

External systems only need to emit the event dataclasses. No project-specific import from MEL Governor, Semantic Agent or Decision Twin is required.
