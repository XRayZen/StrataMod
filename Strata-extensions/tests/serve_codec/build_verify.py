"""Task-local native frame and real installed official-codec qualification."""
import hashlib,importlib.util,json,os,shutil,subprocess,sys
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[3];HERE=Path(__file__).parent;BUILD=ROOT/'build-deepseek-t28'
OWN=[ROOT/'Strata-extensions/models/deepseek41/serve_codec.py']+[HERE/n for n in ['contract.json','codec_fixture.py','test_codec.py','build_verify.py','frame_fixture.cpp','CMakeLists.txt']]
def sha(p):return hashlib.file_digest(Path(p).open('rb'),'sha256').hexdigest()
def row(p):return dict(path=str(p),bytes=Path(p).stat().st_size,sha256=sha(p))
def save(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def module(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def verify(rows):
 for x in rows:
  if row(x['path'])!=x:raise ValueError('bound file changed '+x['path'])
def run(cmd,env=None):
 r=subprocess.run(list(map(str,cmd)),cwd=ROOT,env=env,capture_output=True,encoding='utf-8',errors='strict')
 if r.returncode:
  (BUILD/'last-failure.log').write_text(str(cmd)+'\n'+r.stdout+r.stderr,encoding='utf-8');raise RuntimeError(str(cmd)+'\n'+r.stdout+r.stderr)
 return r
def main():
 BUILD.mkdir(exist_ok=True);snapshot=BUILD/'immutable-source';native=BUILD/'native';native.mkdir(exist_ok=True);dep=[ROOT/'Strata-extensions/native/protocol'/n for n in ['generation.hpp','generation.cpp']]+[ROOT/'Strata-extensions/control/generation_frames.py']
 for p in OWN+dep:
  d=snapshot/p.relative_to(ROOT);d.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,d)
 identity=hashlib.sha256(''.join(str(p.relative_to(ROOT))+'|'+sha(p)+'\n' for p in [HERE/'frame_fixture.cpp']+dep[:2]).encode()).hexdigest();host=module('t28_native_toolchain',ROOT/'Strata-extensions/tests/native/build_verify.py');tools,env=host.toolchain(native)
 commands=[[tools['cmake'],'--fresh','-S',snapshot/HERE.relative_to(ROOT),'-B',native,'-G','Ninja',f'-DT28_ROOT={snapshot.as_posix()}',f'-DT28_SOURCE_ID={identity}',f'-DCMAKE_CXX_COMPILER={tools["compiler"].as_posix()}',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["resource_compiler"].as_posix()}',f'-DCMAKE_MT={tools["manifest_tool"].as_posix()}'],[tools['cmake'],'--build',native,'--verbose']]
 for i,c in enumerate(commands):
  r=run(c,env);(BUILD/f'build-{i}.log').write_text(r.stdout+r.stderr,encoding='utf-8')
 exe=native/'t28-frame.exe'
 if json.loads(run([exe,'--identity']).stdout)!={'source_id':identity}:raise ValueError('native compiled identity')
 t27=ROOT/'build-deepseek-t27';old=load(t27/'manifest.json');verify(old['bundle_files']);tokenizer=t27/'source/deepseek-recipe/static/tokenizers/v41/tokenizer.json';files=OWN+dep+[ROOT/'Strata-extensions/tests/native/build_verify.py',exe,t27/'manifest.json',tokenizer]+list(tools.values())+list(snapshot.rglob('*'));bound=[row(p) for p in sorted(set(files)) if p.is_file()]+old['bundle_files'];save(BUILD/'manifest.json',dict(schema='T28-controlled-codec/v1',binding=bound,source_id=identity,official_T27_manifest=row(t27/'manifest.json'),model_inference=False,normal_server=False,normal_caps_changed=False));fixed=sha(BUILD/'manifest.json');verify(bound)
 child=os.environ.copy();child.update(PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8',OPENCV_OPENCL_RUNTIME='disabled',PATH=os.pathsep.join([child.get('SystemRoot','C:/Windows')+'/System32',child.get('SystemRoot','C:/Windows')]))
 python=t27/'bundle/venv/Scripts/python.exe';r=run([python,'-X','utf8',HERE/'test_codec.py'],child);(BUILD/'unit.log').write_text(r.stdout+r.stderr,encoding='utf-8');r=run([python,'-X','utf8',HERE/'codec_fixture.py',ROOT,exe,fixed,BUILD/'outputs',BUILD/'codec-proof.json'],child);(BUILD/'codec.log').write_text(r.stdout+r.stderr,encoding='utf-8');verify(bound)
 receipt=load(BUILD/'codec-proof.json');loaded=[]
 for component in ['opencv_core','opencv_imgproc','opencv_imgcodecs']:
  matches=[Path(p) for p in receipt['loaded_modules'] if Path(p).name.lower().startswith(component) and Path(p).suffix.lower()=='.dll']
  if len(matches)!=1 or not matches[0].is_relative_to(t27/'bundle/venv/Lib/site-packages'):raise ValueError('installed wheel DLL path '+component)
  item=row(matches[0])
  if item not in old['bundle_files']:raise ValueError('installed wheel DLL identity')
  loaded.append(item)
 rejected=[]
 for p in [exe,ROOT/'Strata-extensions/models/deepseek41/serve_codec.py',tokenizer]:
  bad=row(p);bad['sha256']='0'*64
  try:verify([bad])
  except ValueError:rejected.append(str(p))
  else:raise ValueError('binding tamper accepted')
 save(BUILD/'binding-negatives.json',dict(rejected=rejected));save(BUILD/'loaded-DLL.json',loaded)
 if sha(BUILD/'manifest.json')!=fixed:raise ValueError('manifest changed')
 save(BUILD/'verification.json',dict(manifest=row(BUILD/'manifest.json'),exe=row(exe),codec=row(BUILD/'codec-proof.json'),binding_negatives=row(BUILD/'binding-negatives.json'),loaded_DLL=row(BUILD/'loaded-DLL.json'),unit=row(BUILD/'unit.log'),before_after=True,scope='real official codec/controlled native frames only; model producer/server pending'));print(r.stdout)
if __name__=='__main__':main()

