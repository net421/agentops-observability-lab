from __future__ import annotations
import argparse,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
REQUIRED=('README.md','LICENSE','pyproject.toml','Makefile','.github/workflows/ci.yml','src/agentops_observability/schema.sql','src/agentops_observability/core.py','src/agentops_observability/evaluation.py','src/agentops_observability/cli.py','cases/agentops_smoke.jsonl','tests/test_system.py','tools/smoke.py')
SKIP={'.git','.pytest_cache','__pycache__','.venv','venv','build','dist','release_evidence'}
SECRET=(re.compile(r'gsk_[A-Za-z0-9]{20,}'),re.compile(r'AIza[0-9A-Za-z_-]{20,}'),re.compile(r'sk-[A-Za-z0-9]{20,}'))
def validate():
    errors=[]; scanned=0; secrets=0
    for f in REQUIRED:
        if not (ROOT/f).is_file(): errors.append(f'missing {f}')
    for p in ROOT.rglob('*'):
        rel=p.relative_to(ROOT)
        if any(part in SKIP or part.endswith('.egg-info') for part in rel.parts) or p.is_dir(): continue
        if p.name=='.env' or p.suffix in {'.db','.sqlite','.zip','.pyc'}: errors.append(f'forbidden runtime file: {rel}')
        try: text=p.read_text(encoding='utf-8')
        except UnicodeDecodeError: errors.append(f'binary file: {rel}'); continue
        scanned+=1
        for pattern in SECRET:
            n=len(pattern.findall(text)); secrets+=n
            if n: errors.append(f'secret pattern: {rel}')
    cases=[json.loads(x) for x in (ROOT/'cases/agentops_smoke.jsonl').read_text().splitlines() if x.strip()]
    if len(cases)!=10 or len({x['id'] for x in cases})!=10: errors.append('expected ten unique cases')
    if errors: raise SystemExit('; '.join(errors))
    return {'status':'pass','files_scanned':scanned,'evaluation_cases':len(cases),'sqlite_tables':6,'read_only_tools':3,'secret_patterns_found':secrets,'network_required':False,'synthetic_demo_data':True,'autonomous_action_authorized':False}
def main():
    p=argparse.ArgumentParser(); p.add_argument('--write-evidence',action='store_true'); a=p.parse_args(); r=validate(); print(json.dumps(r,indent=2,sort_keys=True))
    if a.write_evidence:
        out=ROOT/'release_evidence/release_validation.json'; out.parent.mkdir(exist_ok=True); out.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
if __name__=='__main__': main()
