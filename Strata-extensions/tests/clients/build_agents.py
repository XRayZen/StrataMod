"""T32 fixed integration CPU evidence; no native, listener, SDK request, or settings writes."""
from pathlib import Path
import argparse,json,hashlib,shutil,subprocess,sys,ast
HERE=Path(__file__).resolve().parent;OWN=HERE.parents[1];ROOT=OWN.parent;AI=ROOT.parents[2];BUILD=ROOT/'build-deepseek-t32'
def row(p):
 p=Path(p)
 with p.open('rb')as f:s=hashlib.file_digest(f,'sha256').hexdigest()
 return dict(path=str(p),bytes=p.stat().st_size,sha256=s)
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();out=args.output.resolve();out.mkdir(exist_ok=False)
 own=[OWN/'clients/runtime_binding.py',OWN/'clients/family_policy.mjs',*(HERE/n for n in ('agent_contract.json','test_agent_clients.py','test_agent_clients.mjs','build_agents.py'))]
 existing=[AI/'Strata-data/client_runtime.py',AI/'Strata-data/client_selection.py',*(AI/'Pi'/n for n in ('runtime_check.py','catalog_bridge.py','policy.mjs','native-arguments.mjs','thinking-audit.mjs','guard-extension.mjs','extensions/subagent/runtime.mjs')),*(AI/'Harness'/n for n in ('runtime_probe.py','runtime_binding.py','runtime_guard.mjs'))]
 paths=own+existing;before=[row(p)for p in paths];snapshots=[]
 for i,p in enumerate(paths):
  target=out/'source'/str(i)/p.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target);assert row(target)['sha256']==before[i]['sha256'];snapshots.append(dict(original=before[i],snapshot=row(target)))
 protected_paths=[AI/'Strata-data/profile_defaults.py',AI/'Strata-data/model_catalog.py',*sorted((AI/'Strata-data/profiles').glob('*.json')),AI/'Pi/local-policy.md']
 for p in (AI/'Pi/package.json',AI/'Harness/package.json'):
  if p.is_file():protected_paths.append(p)
 protected=[row(p)for p in protected_paths]
 old=json.loads((BUILD/'pure-component-1/verification.json').read_text(encoding='utf-8'));old_by_path={r['path']:r for r in old['existing_client_before_after']};diff=[]
 for p in existing:
  prior=old_by_path[str(p)];snapshot=BUILD/'before-source'/p.relative_to(AI);assert row(snapshot)['sha256']==prior['sha256'];diff.append(dict(before=prior,before_snapshot=row(snapshot),after=row(p)))
 installed=[]
 for p in own[:2]:
  target=AI/'Strata-extensions/clients'/p.name;assert row(target)['sha256']==row(p)['sha256'];installed.append(dict(source=row(p),target=row(target)))
 node=Path('C:/Program Files/nodejs/node.exe');commands=[[sys.executable,'-E','-s','-B','-X','utf8',str(HERE/'test_agent_clients.py'),'-v'],[str(node),str(HERE/'test_agent_clients.mjs')]];results=[]
 for i,cmd in enumerate(commands):
  p=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8');r=dict(command=cmd,exit=p.returncode,stdout=p.stdout,stderr=p.stderr);(out/f'CPU-{i}.json').write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8');results.append(r)
 for p in paths:
  if p.suffix=='.py':ast.parse(p.read_text(encoding='utf-8-sig'),filename=str(p))
  elif p.suffix=='.mjs':
   r=subprocess.run([str(node),'--check',str(p)],capture_output=True,text=True,encoding='utf-8');assert r.returncode==0,(p,r.stderr)
 assert [row(p)for p in paths]==before and [row(p)for p in protected_paths]==protected
 legacy=[row(BUILD/'legacy-CPU-r2'/f'{i}.json')for i in (0,1,2)]+[row(BUILD/'legacy-Pi-defaults-r3/verification.json')]
 for r in legacy:assert json.loads(Path(r['path']).read_text())['exit']==0
 refs=[row(BUILD/'pre-r1.md'),row(BUILD/'pure-component-1/verification.json'),row(BUILD/'pure-before-integration-map.json'),row(BUILD/'pure-TDD-red.txt'),row(BUILD/'Pi-alias-context-red-2.txt')]
 proof=dict(schema='T32-agent-integration-CPU/v1',source=before,snapshots=snapshots,existing_client_diff=diff,installed_helpers=installed,protected_before_after=protected,tests=results,legacy_regressions=legacy,runtimes=[row(sys.executable),row(node)],references=refs,pure_R1='strict type(int) on observation epoch and model metadata n_ctx; bool/equal float negatives passed',normal_SDK_requests=False,normal_fresh_owner_check=False,actual_tool_execution=False,native_listener_or_model=False,settings_modified=False,T32_complete=False,remaining=['fixed live SDK inputs/Q/flags samepre addendum','actual normal --check / overlay / installed helper paths','actual pinned Pi and DSH adapter provider requests','independent source and final review'],legacy_test_limitations='old tests asserting removed IQ4 catalog not re-registered; unchanged guardPath test temporary-directory teardown failure retained in legacy-CPU-r2/3.json; affected default/credential/unsupported checks passed')
 (out/'verification.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8');assert not any(r['exit']for r in results);print(row(out/'verification.json'))
if __name__=='__main__':main()
