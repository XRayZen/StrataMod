"""T31 fixed CPU component evidence; no listener, model, or settings mutation."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
OWN=HERE.parents[1]
ROOT=OWN.parent

def row(path):
    path=Path(path)
    with path.open('rb')as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    return dict(path=str(path),bytes=path.stat().st_size,sha256=sha)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    contract=json.loads((HERE/'contract.json').read_text())
    paths=[OWN/'clients/stream_contract.py',OWN/'clients/chat_adapter.py',OWN/'clients/web_stream.js',OWN/'clients/package_clients.py',HERE/'contract.json',HERE/'test_clients.py',HERE/'test_web_stream.mjs',Path(__file__).resolve(),OWN/'tests/providers/runtime_stage.py',Path('C:/Develop/AI/Strata-data/strata_cli.py'),Path('C:/Develop/AI/Strata/chat.py'),Path('C:/Develop/AI/Strata/serve/web/app.js')]
    before=[row(p)for p in paths]
    guard=json.loads((ROOT/'build-deepseek-t30/cpu-development-7/verification.json').read_text())
    protected=[];historical_deltas=[]
    publication_path=ROOT/'build-deepseek-t31/profile-publication-r1/verification.json'
    publication=json.loads(publication_path.read_text(encoding='utf-8'))if publication_path.is_file()else None
    published={r['path']:r for r in publication['published']}if publication else {}
    for previous in guard['source']+guard['protected']:
        current=row(previous['path'])
        if current['sha256']!=previous['sha256']or ('bytes'in previous and current['bytes']!=previous['bytes']):
            if Path(previous['path']).resolve()==Path('C:/Develop/AI/Strata-data/strata_cli.py').resolve():
                scope='approved selected-package chat dispatch; old snapshot unchanged'
            elif publication and publication['protected_before'].get(previous['path'])==previous['sha256']and published.get(previous['path'])==current:
                scope='approved known-old six DeepSeek profiles publication; old T30 snapshot unchanged'
            else:raise RuntimeError('T30 protected source/profile changed')
            historical_deltas.append(dict(accepted_T30=previous,current_T31=current,scope=scope))
        protected.append(current)
    snapshots=[]
    for p,r in zip(paths,before,strict=True):
        relative=p.relative_to(ROOT)if p.is_relative_to(ROOT)else Path('external/DATA')/p.relative_to('C:/Develop/AI/Strata-data')if p.is_relative_to('C:/Develop/AI/Strata-data')else Path('external/Strata')/p.relative_to('C:/Develop/AI/Strata')
        target=out/'source'/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
        if row(target)['sha256']!=r['sha256']:raise RuntimeError('source changed during snapshot')
        snapshots.append(dict(original=r,snapshot=row(target)))
    node=Path('C:/Program Files/nodejs/node.exe')
    sys.path.insert(0,str(OWN/'clients'))
    import package_clients
    upstream=paths[-1];web=out/'derived-app.js'
    package_clients.write_web_candidate(upstream,web,row(upstream)['sha256'])
    commands=[[sys.executable,'-E','-s','-B','-X','utf8',HERE/'test_clients.py','-v'],[node,HERE/'test_web_stream.mjs',web]]
    results=[]
    for n,cmd in enumerate(commands):
        actual=subprocess.run(list(map(str,cmd)),capture_output=True,text=True,encoding='utf-8')
        result=dict(command=list(map(str,cmd)),exit=actual.returncode,stdout=actual.stdout,stderr=actual.stderr)
        (out/f'CPU-{n}.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');results.append(result)
    if before!=[row(p)for p in paths]or any(row(r['path'])!=r for r in protected):raise RuntimeError('source/profile changed during CPU run')
    proof=dict(schema='T31-CPU-parser-component/v1',source=before,snapshots=snapshots,protected=protected,historical_T30_deltas=historical_deltas,T30_accepted_dependency=row(ROOT/'build-deepseek-t30/normal-cli-final-r1/verification.json'),approved_profile_publication=row(publication_path)if publication else None,runtimes=[row(sys.executable),row(node)],tests=results,derived_web=row(web),derived_web_scope='actual send/apiMessages controlled VM, not browser or model provider',TDD_red=[row(ROOT/'build-deepseek-t31/stream-tdd-red.json'),row(ROOT/'build-deepseek-t31/web-history-reasoning-red.json'),row(ROOT/'build-deepseek-t31/web-multidata-R1-red.json'),row(ROOT/'build-deepseek-t31/web-reader-R2-red.json')],remaining=contract['CPU_component_does_not_qualify'],model_executed=False,normal_settings_modified=False,shared_DATA_modified=True,T31_complete=False)
    (out/'verification.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')
    if any(r['exit']for r in results):raise RuntimeError('CPU parser component failed; original evidence retained')
    print(json.dumps(row(out/'verification.json')))

if __name__=='__main__':main()
