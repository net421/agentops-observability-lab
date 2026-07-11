from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any

@dataclass(frozen=True)
class EvalCase:
    id: str; task: str; expected_tools: tuple[str,...]; expected_citations: tuple[str,...]; checks: tuple[str,...]; max_latency_ms: int

def _str_tuple(value: object, name: str) -> tuple[str,...]:
    if not isinstance(value,list) or any(not isinstance(x,str) or not x for x in value): raise ValueError(f"{name} must be a list of non-empty strings")
    return tuple(value)

def load_cases(path: str | Path) -> list[EvalCase]:
    p=Path(path); cases=[]; seen=set()
    for line_no,line in enumerate(p.read_text(encoding="utf-8").splitlines(),1):
        if not line.strip(): continue
        try: d=json.loads(line)
        except json.JSONDecodeError as exc: raise ValueError(f"line {line_no}: invalid JSON") from exc
        try:
            case=EvalCase(str(d["id"]),str(d["task"]),_str_tuple(d["expected_tools"],"expected_tools"),_str_tuple(d["expected_citations"],"expected_citations"),_str_tuple(d["checks"],"checks"),int(d["max_latency_ms"]))
        except (KeyError,TypeError,ValueError) as exc: raise ValueError(f"line {line_no}: invalid case: {exc}") from exc
        if not case.id or not case.task or case.max_latency_ms < 0: raise ValueError(f"line {line_no}: invalid id, task or latency")
        if case.id in seen: raise ValueError(f"line {line_no}: duplicate id {case.id}")
        seen.add(case.id); cases.append(case)
    if not cases: raise ValueError("no evaluation cases found")
    return cases

def _pr(expected: tuple[str,...], actual: list[str]) -> tuple[float,float]:
    e=set(expected); a=set(actual)
    if not e and not a: return 1.0,1.0
    precision=1.0 if not a else len(e&a)/len(a)
    recall=1.0 if not e else len(e&a)/len(e)
    return round(precision,4),round(recall,4)

def compute_metrics(case: EvalCase, actual_tools: list[str], actual_citations: list[str], latency_ms: int) -> dict[str,Any]:
    if latency_ms < 0: raise ValueError("latency_ms cannot be negative")
    tp,tr=_pr(case.expected_tools,actual_tools); cp,cr=_pr(case.expected_citations,actual_citations)
    latency_score=1.0 if latency_ms <= case.max_latency_ms else 0.0
    task_success=1.0 if tp==tr==cp==cr==latency_score==1.0 else 0.0
    aggregate=round((tp+tr+cp+cr+latency_score+task_success)/6,4)
    return {"task_success":task_success,"tool_precision":tp,"tool_recall":tr,"citation_precision":cp,"citation_recall":cr,"latency_ms":latency_ms,"latency_score":latency_score,"aggregate_quality_score":aggregate}

def run_evaluation(cases: list[EvalCase], simulator: Callable[[EvalCase],tuple[list[str],list[str],int]]) -> list[dict[str,Any]]:
    return [{"case_id":c.id,**compute_metrics(c,*simulator(c))} for c in cases]

def deterministic_simulator(case: EvalCase) -> tuple[list[str],list[str],int]:
    return list(case.expected_tools),list(case.expected_citations),0

def generate_report(results: list[dict[str,Any]]) -> dict[str,Any]:
    if not results: raise ValueError("results cannot be empty")
    keys=("task_success","tool_precision","tool_recall","citation_precision","citation_recall","latency_score","aggregate_quality_score","latency_ms")
    report={f"avg_{k}":round(sum(float(r[k]) for r in results)/len(results),4) for k in keys}
    report.update({"total_cases":len(results),"passed_tasks":sum(r["task_success"]==1 for r in results)})
    report["pass_rate"]=round(report["passed_tasks"]/report["total_cases"],4)
    return report

def evaluate_file(path: str | Path) -> dict[str,Any]:
    cases=load_cases(path); results=run_evaluation(cases,deterministic_simulator)
    return {"case_count":len(cases),"report":generate_report(results),"results":results}
