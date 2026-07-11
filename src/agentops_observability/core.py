from __future__ import annotations

import datetime as dt
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Iterator

STATUSES = {"running", "completed", "failed", "cancelled"}
_SCHEMA = Path(__file__).with_name("schema.sql")
_ALLOWED_TABLES = frozenset({"sessions", "llm_calls", "tool_calls", "retries", "errors", "quality_scores"})


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _nonnegative(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True)
class SessionEvent:
    session_id: str
    provider: str = ""
    model: str = ""
    status: str = "running"
    created_at: str = field(default_factory=utc_now)
    ended_at: str | None = None

    def __post_init__(self) -> None:
        _nonempty(self.session_id, "session_id")
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {sorted(STATUSES)}")


@dataclass(frozen=True)
class LLMCallEvent:
    session_id: str
    provider: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _nonempty(self.session_id, "session_id")
        for name in ("prompt_tokens", "completion_tokens", "total_tokens", "latency_ms"):
            _nonnegative(getattr(self, name), name)
        if self.total_tokens != self.prompt_tokens + self.completion_tokens:
            raise ValueError("total_tokens must equal prompt_tokens + completion_tokens")


@dataclass(frozen=True)
class ToolCallEvent:
    session_id: str
    tool_name: str
    latency_ms: int = 0
    success: bool = True
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _nonempty(self.session_id, "session_id")
        _nonempty(self.tool_name, "tool_name")
        _nonnegative(self.latency_ms, "latency_ms")


@dataclass(frozen=True)
class RetryEvent:
    session_id: str
    operation: str
    retry_count: int = 1
    reason: str = ""
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _nonempty(self.session_id, "session_id")
        _nonempty(self.operation, "operation")
        if not isinstance(self.retry_count, int) or isinstance(self.retry_count, bool) or self.retry_count < 1:
            raise ValueError("retry_count must be an integer >= 1")


@dataclass(frozen=True)
class ErrorEvent:
    session_id: str
    error_type: str
    error_message: str
    fatal: bool = False
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _nonempty(self.session_id, "session_id")
        _nonempty(self.error_type, "error_type")
        _nonempty(self.error_message, "error_message")


@dataclass(frozen=True)
class QualityScoreEvent:
    session_id: str
    dimension: str
    quality_score: float
    metadata_json: str = "{}"
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _nonempty(self.session_id, "session_id")
        _nonempty(self.dimension, "dimension")
        if isinstance(self.quality_score, bool) or not 0 <= float(self.quality_score) <= 1:
            raise ValueError("quality_score must be between 0 and 1")
        parsed = json.loads(self.metadata_json)
        if not isinstance(parsed, dict):
            raise ValueError("metadata_json must encode a JSON object")


def _counts(total: int, success: int) -> None:
    if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in (total, success)):
        raise ValueError("counts must be non-negative integers")
    if success > total:
        raise ValueError("success count cannot exceed total")


def score_task_success(*, tasks_attempted: int, tasks_completed: int, fatal_errors: int = 0) -> float:
    _counts(tasks_attempted, tasks_completed)
    if not isinstance(fatal_errors, int) or isinstance(fatal_errors, bool) or fatal_errors < 0:
        raise ValueError("fatal_errors must be a non-negative integer")
    if tasks_attempted == 0:
        return 1.0
    base = tasks_completed / tasks_attempted
    penalty = min(fatal_errors / tasks_attempted, 1.0)
    return round(max(0.0, base * (1 - 0.5 * penalty)), 4)


def score_tool_accuracy(*, tools_called: int, tools_succeeded: int) -> float:
    _counts(tools_called, tools_succeeded)
    return 1.0 if tools_called == 0 else round(tools_succeeded / tools_called, 4)


def score_citation_correctness(*, citations_checked: int, citations_correct: int) -> float:
    _counts(citations_checked, citations_correct)
    return 1.0 if citations_checked == 0 else round(citations_correct / citations_checked, 4)


def aggregate_quality_score(scores: list[float], *, weights: list[float] | None = None) -> float:
    if any(isinstance(s, bool) or not 0 <= float(s) <= 1 for s in scores):
        raise ValueError("scores must be between 0 and 1")
    if not scores:
        return 1.0
    if weights is None:
        return round(mean(scores), 4)
    if len(weights) != len(scores) or any(w < 0 for w in weights):
        raise ValueError("weights must be non-negative and match scores")
    total = sum(weights)
    return 1.0 if total == 0 else round(sum(s * w for s, w in zip(scores, weights)) / total, 4)


class AgentOpsStore:
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, timeout=5)
        self._conn.execute("PRAGMA foreign_keys=ON")
        if self.db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA.read_text(encoding="utf-8"))
        self._conn.commit()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def _insert(self, table: str, columns: tuple[str, ...], values: tuple) -> int:
        if table not in _ALLOWED_TABLES:
            raise ValueError("table not allowed")
        sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})"
        with self._tx() as conn:
            cur = conn.execute(sql, values)
            return int(cur.lastrowid)

    def insert_session(self, e: SessionEvent) -> int:
        return self._insert("sessions", ("session_id", "provider", "model", "status", "created_at", "ended_at"), (e.session_id, e.provider, e.model, e.status, e.created_at, e.ended_at))

    def insert_llm_call(self, e: LLMCallEvent) -> int:
        return self._insert("llm_calls", ("session_id", "provider", "model", "prompt_tokens", "completion_tokens", "total_tokens", "latency_ms", "created_at"), (e.session_id, e.provider, e.model, e.prompt_tokens, e.completion_tokens, e.total_tokens, e.latency_ms, e.created_at))

    def insert_tool_call(self, e: ToolCallEvent) -> int:
        return self._insert("tool_calls", ("session_id", "tool_name", "latency_ms", "success", "created_at"), (e.session_id, e.tool_name, e.latency_ms, int(e.success), e.created_at))

    def insert_retry(self, e: RetryEvent) -> int:
        return self._insert("retries", ("session_id", "retry_count", "operation", "reason", "created_at"), (e.session_id, e.retry_count, e.operation, e.reason, e.created_at))

    def insert_error(self, e: ErrorEvent) -> int:
        return self._insert("errors", ("session_id", "error_type", "error_message", "fatal", "created_at"), (e.session_id, e.error_type, e.error_message, int(e.fatal), e.created_at))

    def insert_quality_score(self, e: QualityScoreEvent) -> int:
        return self._insert("quality_scores", ("session_id", "dimension", "quality_score", "metadata_json", "created_at"), (e.session_id, e.dimension, float(e.quality_score), e.metadata_json, e.created_at))

    def update_session_status(self, session_id: str, status: str, *, ended_at: str | None = None) -> None:
        if status not in STATUSES:
            raise ValueError(f"invalid status: {status}")
        if status != "running" and ended_at is None:
            ended_at = utc_now()
        with self._tx() as conn:
            cur = conn.execute("UPDATE sessions SET status=?, ended_at=? WHERE session_id=?", (status, ended_at, session_id))
            if cur.rowcount != 1:
                raise LookupError(f"session not found: {session_id}")

    def count_table(self, table: str) -> int:
        if table not in _ALLOWED_TABLES:
            raise ValueError(f"invalid table: {table}")
        return int(self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def list_sessions(self, limit: int = 100) -> list[dict]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise ValueError("limit must be 1..1000")
        self._conn.row_factory = sqlite3.Row
        return [dict(r) for r in self._conn.execute("SELECT session_id,provider,model,status,created_at,ended_at FROM sessions ORDER BY created_at DESC LIMIT ?", (limit,))]

    def session_summary(self, session_id: str) -> dict:
        row = self._conn.execute("SELECT session_id FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            raise LookupError(f"session not found: {session_id}")
        out = {"session_id": session_id}
        for table in ("llm_calls", "tool_calls", "retries", "errors", "quality_scores"):
            out[table] = int(self._conn.execute(f"SELECT COUNT(*) FROM {table} WHERE session_id=?", (session_id,)).fetchone()[0])
        out["total_tokens"] = int(self._conn.execute("SELECT COALESCE(SUM(total_tokens),0) FROM llm_calls WHERE session_id=?", (session_id,)).fetchone()[0])
        return out


def existing_file(path: str | Path, *, label: str = "file") -> Path:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"{label} not found: {p}")
    if not p.is_file():
        raise ValueError(f"{label} is not a file: {p}")
    return p


def read_only_connection(db_path: str | Path) -> sqlite3.Connection:
    p = existing_file(db_path, label="SQLite database")
    conn = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    conn.row_factory = sqlite3.Row
    return conn


def aggregate_metrics(db_path: str | Path) -> dict[str, Any]:
    with read_only_connection(db_path) as conn:
        one = lambda q: conn.execute(q).fetchone()[0]
        return {
            "total_sessions": int(one("SELECT COUNT(*) FROM sessions")),
            "completed_sessions": int(one("SELECT COUNT(*) FROM sessions WHERE status='completed'")),
            "failed_sessions": int(one("SELECT COUNT(*) FROM sessions WHERE status='failed'")),
            "total_llm_calls": int(one("SELECT COUNT(*) FROM llm_calls")),
            "total_tool_calls": int(one("SELECT COUNT(*) FROM tool_calls")),
            "successful_tool_calls": int(one("SELECT COUNT(*) FROM tool_calls WHERE success=1")),
            "total_retries": int(one("SELECT COALESCE(SUM(retry_count),0) FROM retries")),
            "total_errors": int(one("SELECT COUNT(*) FROM errors")),
            "fatal_errors": int(one("SELECT COUNT(*) FROM errors WHERE fatal=1")),
            "total_tokens": int(one("SELECT COALESCE(SUM(total_tokens),0) FROM llm_calls")),
            "avg_latency_ms": round(float(one("SELECT COALESCE(AVG(latency_ms),0) FROM llm_calls")), 4),
            "avg_quality_score": round(float(one("SELECT COALESCE(AVG(quality_score),0) FROM quality_scores")), 4),
        }


def session_detail(db_path: str | Path, session_id: str) -> dict[str, Any]:
    if not session_id:
        raise ValueError("session_id is required")
    with read_only_connection(db_path) as conn:
        row = conn.execute("SELECT session_id,provider,model,status,created_at,ended_at FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            raise LookupError(f"session not found: {session_id}")
        counts = {t: int(conn.execute(f"SELECT COUNT(*) FROM {t} WHERE session_id=?", (session_id,)).fetchone()[0]) for t in ("llm_calls", "tool_calls", "retries", "errors", "quality_scores")}
        tokens = int(conn.execute("SELECT COALESCE(SUM(total_tokens),0) FROM llm_calls WHERE session_id=?", (session_id,)).fetchone()[0])
        quality = float(conn.execute("SELECT COALESCE(AVG(quality_score),0) FROM quality_scores WHERE session_id=?", (session_id,)).fetchone()[0])
        return {"session": dict(row), "counts": counts, "total_tokens": tokens, "avg_quality_score": round(quality, 4)}


def format_dashboard(metrics: dict[str, Any]) -> str:
    labels = (("total_sessions", "Total Sessions"), ("completed_sessions", "Completed Sessions"), ("failed_sessions", "Failed Sessions"), ("total_llm_calls", "LLM Calls"), ("total_tool_calls", "Tool Calls"), ("successful_tool_calls", "Successful Tool Calls"), ("total_retries", "Retries"), ("total_errors", "Errors"), ("fatal_errors", "Fatal Errors"), ("total_tokens", "Tokens"), ("avg_latency_ms", "Average LLM Latency (ms)"), ("avg_quality_score", "Average Quality Score"))
    width = 68
    lines = ["=" * width, "AGENTOPS OBSERVABILITY DASHBOARD", "=" * width]
    lines.extend(f"{label:<34} {metrics[key]}" for key, label in labels)
    lines.append("=" * width)
    return "\n".join(lines)


def agentops_metrics(db_path: str | Path) -> dict[str, Any]:
    p = existing_file(db_path, label="SQLite database")
    return {"tool": "agentops_metrics", "read_only": True, "db_path": str(p), "metrics": aggregate_metrics(p)}


def agentops_session_summary(db_path: str | Path, session_id: str) -> dict[str, Any]:
    p = existing_file(db_path, label="SQLite database")
    return {"tool": "agentops_session_summary", "read_only": True, "db_path": str(p), **session_detail(p, session_id)}


def eval_smoke_report(cases_path: str | Path) -> dict[str, Any]:
    from .evaluation import evaluate_file
    p = existing_file(cases_path, label="evaluation cases")
    return {"tool": "eval_smoke_report", "read_only": True, "cases_path": str(p), **evaluate_file(p)}


def list_tools() -> dict[str, Any]:
    return {"tools": [{"name": "agentops_metrics", "read_only": True, "required_args": ["db_path"]}, {"name": "agentops_session_summary", "read_only": True, "required_args": ["db_path", "session_id"]}, {"name": "eval_smoke_report", "read_only": True, "required_args": ["cases_path"]}]}


TOOLS: dict[str, Callable[..., dict[str, Any]]] = {"agentops_metrics": agentops_metrics, "agentops_session_summary": agentops_session_summary, "eval_smoke_report": eval_smoke_report}


def call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name not in TOOLS:
        raise ValueError(f"unknown or non-read-only tool: {name}")
    if not isinstance(args, dict):
        raise ValueError("args must be an object")
    return TOOLS[name](**args)


def create_demo_database(path: str | Path) -> Path:
    p = Path(path).expanduser().resolve()
    for suffix in ("", "-wal", "-shm"):
        f = Path(str(p) + suffix)
        if f.exists():
            f.unlink()
    with AgentOpsStore(p) as s:
        s.insert_session(SessionEvent("session_001", "mock", "research-agent", "completed", "2026-07-08T10:00:00+00:00", "2026-07-08T10:30:00+00:00"))
        s.insert_session(SessionEvent("session_002", "local", "decision-agent", "running", "2026-07-08T11:00:00+00:00"))
        for e in (
            LLMCallEvent("session_001", "mock", "research-agent", 100, 50, 150, 1200, "2026-07-08T10:01:00+00:00"),
            LLMCallEvent("session_001", "mock", "research-agent", 200, 100, 300, 800, "2026-07-08T10:02:00+00:00"),
            LLMCallEvent("session_002", "local", "decision-agent", 50, 25, 75, 600, "2026-07-08T11:01:00+00:00"),
            LLMCallEvent("session_002", "local", "decision-agent", 150, 75, 225, 900, "2026-07-08T11:02:00+00:00"),
            LLMCallEvent("session_002", "local", "decision-agent", 75, 25, 100, 1100, "2026-07-08T11:03:00+00:00"),
        ):
            s.insert_llm_call(e)
        for e in (
            ToolCallEvent("session_001", "read_file", 150, True, "2026-07-08T10:03:00+00:00"),
            ToolCallEvent("session_001", "write_file", 200, True, "2026-07-08T10:04:00+00:00"),
            ToolCallEvent("session_001", "terminal", 100, False, "2026-07-08T10:05:00+00:00"),
            ToolCallEvent("session_002", "read_file", 120, True, "2026-07-08T11:04:00+00:00"),
            ToolCallEvent("session_002", "terminal", 180, True, "2026-07-08T11:05:00+00:00"),
            ToolCallEvent("session_002", "patch", 90, True, "2026-07-08T11:06:00+00:00"),
        ):
            s.insert_tool_call(e)
        s.insert_retry(RetryEvent("session_001", "read_file", 2, "temporary issue", "2026-07-08T10:06:00+00:00"))
        s.insert_retry(RetryEvent("session_001", "write_file", 1, "patch conflict", "2026-07-08T10:07:00+00:00"))
        s.insert_retry(RetryEvent("session_002", "terminal", 3, "timeout", "2026-07-08T11:07:00+00:00"))
        s.insert_error(ErrorEvent("session_001", "ToolError", "command failed", True, "2026-07-08T10:08:00+00:00"))
        s.insert_error(ErrorEvent("session_002", "LLMError", "rate limit", False, "2026-07-08T11:08:00+00:00"))
        s.insert_error(ErrorEvent("session_002", "ValidationError", "invalid input", False, "2026-07-08T11:09:00+00:00"))
        for e in (
            QualityScoreEvent("session_001", "task_success", .95, '{"details":"completed"}', "2026-07-08T10:09:00+00:00"),
            QualityScoreEvent("session_001", "tool_accuracy", .87, '{"details":"one failed"}', "2026-07-08T10:10:00+00:00"),
            QualityScoreEvent("session_002", "task_success", .78, '{"details":"partial"}', "2026-07-08T11:10:00+00:00"),
            QualityScoreEvent("session_002", "tool_accuracy", .92, '{"details":"mostly successful"}', "2026-07-08T11:11:00+00:00"),
            QualityScoreEvent("session_002", "citation_correctness", .85, '{"details":"checked"}', "2026-07-08T11:12:00+00:00"),
        ):
            s.insert_quality_score(e)
    return p
