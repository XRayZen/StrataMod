"""T33 CPU component snapshots. Does not launch a model or publish profiles."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
OWN=HERE.parents[1]
ROOT=OWN.parent
BUILD=ROOT/'build-deepseek-t33'
SOURCES=[OWN/'clients/runtime_identity.py',OWN/'clients/runtime_identity.js',*[HERE/n for n in ('client_contract.json','test_clients.py','test_clients.mjs','build_verify.py')]]
PROTECTED=[OWN/'clients'/n for n in ('stream_contract.py','web_stream.js','chat_adapter.py','package_clients.py')]+[OWN/'tests/providers/runtime_stage.py',Path('C:/Develop/AI/Strata-data/strata_cli.py'),Path('C:/Develop/AI/Pi/guard-extension.mjs')]

def row(path):
 p=Path(path);return dict(path=str(p.resolve()),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def save(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def main():
 out=BUILD/'pure-component-1';out.mkdir(exist_ok=False);before=[row(p)for p in SOURCES];protected=[row(p)for p in PROTECTED];maps=[]
 for p,r in zip(SOURCES,before,strict=True):
  target=out/'source'/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target);assert row(target)['sha256']==r['sha256'];maps.append(dict(original=r,snapshot=row(target)))
 commands=[[sys.executable,'-X','utf8','-B','-m','unittest','discover','-s',str(HERE),'-p','test_clients.py','-v'],[shutil.which('node'),str(HERE/'test_clients.mjs')]]
 results=[]
 for i,cmd in enumerate(commands):
  result=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8');log=out/f'CPU-{i}.log';log.write_text(result.stdout+result.stderr,encoding='utf-8');results.append(dict(command=cmd,exit=result.returncode,log=row(log)));assert result.returncode==0
 assert before==[row(p)for p in SOURCES]and protected==[row(p)for p in PROTECTED]
 value=dict(schema='T33-pure-identity-component/v1',sources=maps,protected=protected,results=results,red=row(BUILD/'pure-red.log'),pre=row(BUILD/'pre-r2.md'),settings_modified=False,installed_helpers_modified=False,actual_provider=False,actual_reasoning_tool=False,GPU=0,remaining=['service metrics/SSE install','stream and commit bindings','Pi actual message_end hook','finite package extension and activation','actual shortest reasoning/tool SDK cases and MCP coverage'])
 save(out/'verification.json',value);print(json.dumps(row(out/'verification.json')))
if __name__=='__main__':main()
