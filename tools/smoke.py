from __future__ import annotations
import hashlib,json,tempfile
from pathlib import Path
from agentops_observability.core import create_demo_database,aggregate_metrics,session_detail,agentops_metrics,agentops_session_summary
from agentops_observability.evaluation import evaluate_file
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as td:
    db=create_demo_database(Path(td)/'agentops.db')
    before=hashlib.sha256(db.read_bytes()).hexdigest()
    metrics=aggregate_metrics(db); detail=session_detail(db,'session_001')
    eval_result=evaluate_file(ROOT/'cases/agentops_smoke.jsonl')
    sidecar=[agentops_metrics(db),agentops_session_summary(db,'session_001')]
    after=hashlib.sha256(db.read_bytes()).hexdigest()
    assert before==after
    assert metrics['total_tokens']==850 and detail['total_tokens']==450 and eval_result['report']['pass_rate']==1
    print(json.dumps({'status':'pass','metrics':metrics,'session_001':detail,'eval_report':eval_result['report'],'sidecar_read_only':before==after,'sidecar_tools':[x['tool'] for x in sidecar]},indent=2,sort_keys=True))
