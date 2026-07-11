from __future__ import annotations
import argparse,json
from .core import create_demo_database,aggregate_metrics,format_dashboard,session_detail,list_tools,call_tool
from .evaluation import evaluate_file

def main(argv: list[str]|None=None) -> int:
    p=argparse.ArgumentParser(prog="agentops-lab"); sub=p.add_subparsers(dest="command",required=True)
    s=sub.add_parser("seed-demo"); s.add_argument("--db",required=True)
    d=sub.add_parser("dashboard"); d.add_argument("--db",required=True); d.add_argument("--json",action="store_true")
    q=sub.add_parser("session"); q.add_argument("--db",required=True); q.add_argument("--session-id",required=True)
    e=sub.add_parser("eval"); e.add_argument("--cases",required=True)
    sub.add_parser("list-tools")
    c=sub.add_parser("call-tool"); c.add_argument("name"); c.add_argument("--args-json",default="{}")
    ns=p.parse_args(argv)
    if ns.command=="seed-demo": print(create_demo_database(ns.db)); return 0
    if ns.command=="dashboard":
        m=aggregate_metrics(ns.db); print(json.dumps(m,indent=2,sort_keys=True) if ns.json else format_dashboard(m)); return 0
    if ns.command=="session": print(json.dumps(session_detail(ns.db,ns.session_id),indent=2,sort_keys=True)); return 0
    if ns.command=="eval": print(json.dumps(evaluate_file(ns.cases),indent=2,sort_keys=True)); return 0
    if ns.command=="list-tools": print(json.dumps(list_tools(),indent=2,sort_keys=True)); return 0
    args=json.loads(ns.args_json)
    if not isinstance(args,dict): raise ValueError("--args-json must decode to an object")
    print(json.dumps(call_tool(ns.name,args),indent=2,sort_keys=True)); return 0
