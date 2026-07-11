from pathlib import Path
import hashlib
import sqlite3
import pytest

from agentops_observability import *
from agentops_observability.cli import main
from agentops_observability.core import (
    aggregate_metrics,
    agentops_metrics,
    agentops_session_summary,
    call_tool,
    create_demo_database,
    eval_smoke_report,
    format_dashboard,
    list_tools,
    read_only_connection,
    session_detail,
)
from agentops_observability.evaluation import EvalCase, compute_metrics, evaluate_file, generate_report, load_cases

CASES = Path(__file__).resolve().parents[1] / "cases/agentops_smoke.jsonl"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_load_ten_domain_cases():
    cases = load_cases(CASES)
    assert len(cases) == 10
    assert all(case.id.startswith("agentops_") for case in cases)


def test_invalid_json_line(tmp_path):
    path = tmp_path / "invalid.jsonl"
    path.write_text("{bad}\n")
    with pytest.raises(ValueError, match="line 1"):
        load_cases(path)


def test_duplicate_case(tmp_path):
    line = '{"id":"x","task":"t","expected_tools":[],"expected_citations":[],"checks":[],"max_latency_ms":1}'
    path = tmp_path / "duplicate.jsonl"
    path.write_text(line + "\n" + line + "\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_cases(path)


def test_metrics_exact_success():
    case = EvalCase("x", "t", ("a",), ("c",), ("x",), 10)
    metrics = compute_metrics(case, ["a"], ["c"], 1)
    assert metrics["task_success"] == 1
    assert metrics["aggregate_quality_score"] == 1


def test_metrics_penalize_extra_tool():
    case = EvalCase("x", "t", ("a",), (), (), 10)
    metrics = compute_metrics(case, ["a", "b"], [], 1)
    assert metrics["tool_precision"] == .5
    assert metrics["task_success"] == 0


def test_evaluate_file_passes():
    result = evaluate_file(CASES)
    assert result["case_count"] == 10
    assert result["report"]["pass_rate"] == 1


def test_report_rejects_empty():
    with pytest.raises(ValueError):
        generate_report([])


def test_sidecar_tools_read_only(tmp_path):
    db = create_demo_database(tmp_path / "demo.db")
    before = digest(db)
    assert agentops_metrics(db)["metrics"]["total_tokens"] == 850
    assert agentops_session_summary(db, "session_001")["total_tokens"] == 450
    assert digest(db) == before


def test_eval_sidecar():
    assert eval_smoke_report(CASES)["report"]["pass_rate"] == 1


def test_tool_manifest():
    tools = list_tools()["tools"]
    assert {item["name"] for item in tools} == {"agentops_metrics", "agentops_session_summary", "eval_smoke_report"}
    assert all(item["read_only"] for item in tools)


def test_unknown_tool():
    with pytest.raises(ValueError):
        call_tool("write_database", {})


def test_cli_roundtrip(tmp_path, capsys):
    db = tmp_path / "demo.db"
    assert main(["seed-demo", "--db", str(db)]) == 0
    assert main(["dashboard", "--db", str(db), "--json"]) == 0
    assert "total_tokens" in capsys.readouterr().out
    assert main(["eval", "--cases", str(CASES)]) == 0
    assert "pass_rate" in capsys.readouterr().out


def test_session_rejects_empty_id():
    with pytest.raises(ValueError):
        SessionEvent("")


def test_session_rejects_status():
    with pytest.raises(ValueError):
        SessionEvent("x", status="unknown")


def test_llm_tokens_reconcile():
    with pytest.raises(ValueError):
        LLMCallEvent("x", prompt_tokens=1, completion_tokens=1, total_tokens=3)


def test_llm_negative_rejected():
    with pytest.raises(ValueError):
        LLMCallEvent("x", prompt_tokens=-1)


def test_tool_requires_name():
    with pytest.raises(ValueError):
        ToolCallEvent("x", "")


def test_retry_requires_positive_count():
    with pytest.raises(ValueError):
        RetryEvent("x", "op", 0)


def test_quality_bounds():
    with pytest.raises(ValueError):
        QualityScoreEvent("x", "q", 1.1)


def test_quality_metadata_object():
    with pytest.raises(ValueError):
        QualityScoreEvent("x", "q", .5, "[]")


def test_task_success_penalty():
    assert score_task_success(tasks_attempted=4, tasks_completed=4, fatal_errors=1) == .875


def test_task_success_empty():
    assert score_task_success(tasks_attempted=0, tasks_completed=0) == 1


def test_tool_accuracy():
    assert score_tool_accuracy(tools_called=4, tools_succeeded=3) == .75


def test_citation_correctness():
    assert score_citation_correctness(citations_checked=2, citations_correct=1) == .5


def test_aggregate_weighted():
    assert aggregate_quality_score([1, .5], weights=[3, 1]) == .875


def test_aggregate_rejects_bad_score():
    with pytest.raises(ValueError):
        aggregate_quality_score([2])


def test_store_all_event_types(tmp_path):
    db = tmp_path / "events.db"
    with AgentOpsStore(db) as store:
        store.insert_session(SessionEvent("s"))
        store.insert_llm_call(LLMCallEvent("s", prompt_tokens=2, completion_tokens=1, total_tokens=3))
        store.insert_tool_call(ToolCallEvent("s", "tool"))
        store.insert_retry(RetryEvent("s", "tool"))
        store.insert_error(ErrorEvent("s", "Error", "message"))
        store.insert_quality_score(QualityScoreEvent("s", "quality", .8))
        assert [store.count_table(table) for table in ("sessions", "llm_calls", "tool_calls", "retries", "errors", "quality_scores")] == [1] * 6
        assert store.session_summary("s")["total_tokens"] == 3


def test_foreign_key_rejects_orphan():
    with AgentOpsStore() as store:
        with pytest.raises(sqlite3.IntegrityError):
            store.insert_tool_call(ToolCallEvent("missing", "tool"))


def test_duplicate_session_rejected():
    with AgentOpsStore() as store:
        store.insert_session(SessionEvent("s"))
        with pytest.raises(sqlite3.IntegrityError):
            store.insert_session(SessionEvent("s"))


def test_count_table_allowlist():
    with AgentOpsStore() as store:
        with pytest.raises(ValueError):
            store.count_table("sessions; DROP TABLE sessions")


def test_update_status_and_missing():
    with AgentOpsStore() as store:
        store.insert_session(SessionEvent("s"))
        store.update_session_status("s", "completed")
        assert store.list_sessions()[0]["status"] == "completed"
        with pytest.raises(LookupError):
            store.update_session_status("missing", "failed")


def test_list_limit_validation():
    with AgentOpsStore() as store:
        with pytest.raises(ValueError):
            store.list_sessions(0)


def test_demo_metrics(tmp_path):
    db = create_demo_database(tmp_path / "demo.db")
    assert aggregate_metrics(db) == {
        "total_sessions": 2,
        "completed_sessions": 1,
        "failed_sessions": 0,
        "total_llm_calls": 5,
        "total_tool_calls": 6,
        "successful_tool_calls": 5,
        "total_retries": 6,
        "total_errors": 3,
        "fatal_errors": 1,
        "total_tokens": 850,
        "avg_latency_ms": 920.0,
        "avg_quality_score": 0.874,
    }


def test_session_detail(tmp_path):
    db = create_demo_database(tmp_path / "demo.db")
    detail = session_detail(db, "session_001")
    assert detail["counts"] == {"llm_calls": 2, "tool_calls": 3, "retries": 2, "errors": 1, "quality_scores": 2}
    assert detail["total_tokens"] == 450
    assert detail["avg_quality_score"] == .91


def test_missing_session(tmp_path):
    db = create_demo_database(tmp_path / "demo.db")
    with pytest.raises(LookupError):
        session_detail(db, "missing")


def test_read_only_connection_blocks_write(tmp_path):
    db = create_demo_database(tmp_path / "demo.db")
    with read_only_connection(db) as connection:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM sessions")


def test_dashboard_text(tmp_path):
    db = create_demo_database(tmp_path / "demo.db")
    text = format_dashboard(aggregate_metrics(db))
    assert "AGENTOPS OBSERVABILITY DASHBOARD" in text
    assert "850" in text
