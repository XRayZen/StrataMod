"""Freeze and replay the current T30 CPU candidate; never launches a model."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

OWN = Path(__file__).resolve().parents[2]
ROOT = OWN.parent
DATA = ROOT.parents[1]


def row(path):
    return dict(path=str(path),bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    contract=json.loads(Path(__file__).with_name('contract.json').read_text(encoding='utf-8'))
    paths=[(OWN if value.startswith('OWN/') else DATA)/value.split('/',1)[1] for value in contract['sources']]
    before=[row(path) for path in paths]
    baseline=json.loads((ROOT/'build-deepseek-t30/baseline-r1.json').read_text(encoding='utf-8'))
    protected=baseline['profile_before']+[item for item in baseline['source_records'] if Path(item['path']) not in paths]
    for item in protected:
        if row(Path(item['path']))['sha256']!=item['sha256']:
            raise RuntimeError('Out-of-scope baseline changed: '+item['path'])
    for index,path in enumerate(paths):
        target=output/'source'/str(index)/path.name
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
        before[index]['snapshot']=row(target)
    cases=[([sys.executable,'-E','-s','-B','-X','utf8',str(Path(__file__).with_name('test_runtime.py'))],OWN),
           ([sys.executable,'-E','-s','-B','-X','utf8','-m','unittest','test_startup_progress','test_runtime_temp_probe.TempProbeTests','test_runtime_safety'],DATA)]
    results=[]
    for index,(command,cwd) in enumerate(cases):
        result=subprocess.run(command,cwd=cwd,capture_output=True,text=True,encoding='utf-8')
        record=dict(command=command,cwd=str(cwd),exit=result.returncode,stdout=result.stdout,stderr=result.stderr)
        (output/f'cpu-{index}.json').write_text(json.dumps(record,indent=2),encoding='utf-8');results.append(record)
    after=[row(path) for path in paths]
    if [{k:v for k,v in item.items() if k!='snapshot'} for item in before]!=after:
        raise RuntimeError('T30 source changed during CPU validation')
    for item in protected:
        if row(Path(item['path']))['sha256']!=item['sha256']:
            raise RuntimeError('Out-of-scope source changed during CPU validation: '+item['path'])
    proof=dict(scope='CPU candidate only',source=before,cpu=results,protected=protected,native_spawn=False,GPU=False,model_qualified=False,T30_complete=False)
    (output/'verification.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
    if any(result['exit'] for result in results):raise RuntimeError('CPU candidate failed')
    print(json.dumps(row(output/'verification.json')))


if __name__=='__main__':main()
