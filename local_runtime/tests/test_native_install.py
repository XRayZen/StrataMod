"""Run the reviewed native writer only against test-owned lock/target paths."""
import hashlib,json,msvcrt,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from local_runtime import normal_runtime as normal

PS=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'

GUARD=r'''
import json,hashlib,msvcrt,os,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from local_runtime import normal_runtime as n
marker,first,second,target,code,mode=sys.argv[1:]
blocked=[]
for path in (first,second):
 with open(path,'r+b') as stream:
  stream.seek(0)
  try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
  except OSError:blocked.append(True)
  else:
   blocked.append(False);stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
if mode=='released':
 Path(marker+'.released').write_text(json.dumps(blocked),encoding='utf-8')
 sys.exit(0 if blocked==[False,False] else 31)
calls=[];run=n.subprocess.run
def observed(args,**kw):
 calls.append(dict(policy=os.environ.get('PSExecutionPolicyPreference'),no_profile='-NoProfile' in args))
 return run(args,**kw)
n.subprocess.run=observed
# The actual installer copy writes only this fixture's target and locks.
# Keep profile-enabled shell execution, but project command resolution to the
# fixture-owned path; collision refusal itself has separate unit coverage.
n.SHIM=Path(target)
which=n.shutil.which
n.shutil.which=lambda name: str(target) if name=='StrataMod' else which(name)
real_observed=observed
def fixture_lookup(args,**kw):
 result=real_observed(args,**kw)
 rows=json.loads(result.stdout) if result.stdout.strip() else []
 if isinstance(rows,dict):rows=[rows]
 for row in rows:
  if row.get('Kind')=='Application':row['Path']=target
 result.stdout=json.dumps(rows)
 return result
n.subprocess.run=fixture_lookup
n.check_shim_collision({})
Path(marker).write_text(json.dumps(dict(blocked=blocked,policy=os.environ.get('PSExecutionPolicyPreference'),shells=calls)),encoding='utf-8')
if blocked!=[True,True]:sys.exit(30)
if code!='0':sys.exit(int(code))
print(json.dumps(dict(status='checked',shim=target,bytes=len(n.SHIM_BYTES),sha256=hashlib.sha256(n.SHIM_BYTES).hexdigest(),asset_body_digest_calls=0)))
'''


class NativeInstallerTests(unittest.TestCase):
    def fixture(self):
        tmp=self.enterContext(tempfile.TemporaryDirectory(dir=normal.m.LOCAL/'records'))
        root=Path(tmp);locks=[root/'operation.lock',root/'runtime.lock']
        for p in locks:p.write_bytes(b'unchanged-lock')
        guard=root/'guard.py';guard.write_text(GUARD,encoding='utf-8')
        target=root/'StrataMod.cmd';marker=root/'guard.json'
        return root,locks,guard,target,marker

    def run_writer(self,fixture,*,check=False,code=0,prior=None):
        root,locks,guard,target,marker=fixture
        source=normal.NATIVE_INSTALLER.read_text(encoding='ascii')
        # The production helper has no target/guard/lock override arguments.
        # Only this isolated CPU copy substitutes these fixed literals.
        source=source.replace('$Root = $PSScriptRoot', "$Root = '"+str(normal.m.ROOT)+"'")
        source=source.replace("$Python = Join-Path (Split-Path $Root -Parent) 'Strata\\.venv\\Scripts\\python.exe'",
                              "$Python = '"+str(normal.m.PYTHON)+"'")
        source=source.replace("$Target = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.local\\bin\\StrataMod.cmd'",
                              "$Target = '"+str(target)+"'")
        source=source.replace("$LockPaths = @((Join-Path $Data 'records\\cli-operation.lock'), (Join-Path $Data 'records\\runtime.lock'))",
                              "$LockPaths = @('"+str(locks[0])+"', '"+str(locks[1])+"')")
        invoke=f"& $Python -B -X utf8 '{guard}' '{marker}' '{locks[0]}' '{locks[1]}' '{target}' '{code}' live"
        source=source.replace('& $Python -B -X utf8 -m local_runtime.normal_runtime install-guard',invoke)
        released=invoke.rsplit(' live',1)[0]+' released'
        source=source.replace('exit $ExitCode',released+'\nexit $ExitCode')
        script=root/'Install-StrataMod.ps1';script.write_text(source,encoding='ascii')
        cmd=root/'Install-StrataMod.cmd';cmd.write_bytes(normal.INSTALLER.read_bytes())
        env=dict(os.environ)
        env['__PYVENV_LAUNCHER__']=sys.executable
        if prior is None:env.pop('PSExecutionPolicyPreference',None)
        else:env['PSExecutionPolicyPreference']=prior
        args=[os.environ['ComSpec'],'/d','/c',str(cmd)]
        if check:args.append('--check')
        result=subprocess.run(args,cwd=normal.m.ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=40)
        self.assertTrue(Path(str(marker)+'.released').exists(),result.stdout+'\n'+result.stderr)
        released=json.loads(Path(str(marker)+'.released').read_text(encoding='utf-8'))
        observed=json.loads(marker.read_text(encoding='utf-8'))
        self.assertEqual(released,[False,False],result.stderr)
        for p in locks:self.assertEqual(p.read_bytes(),b'unchanged-lock')
        record=dict(test=self.id(),check=check,guard_exit=code,prior_policy=prior,
                    scope='CPU-only isolated script copy; fixed production target and both lock literals replaced by test-owned paths; no production alias write',
                    original_ps_sha256=hashlib.sha256(normal.NATIVE_INSTALLER.read_bytes()).hexdigest(),
                    original_cmd_sha256=hashlib.sha256(normal.INSTALLER.read_bytes()).hexdigest(),
                    fixture_ps_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),guard=observed,
                    after_finally_lock_blocked=released,exit_code=result.returncode,
                    target_bytes=target.read_bytes().hex() if target.exists() else None,
                    stdout=result.stdout,stderr=result.stderr)
        with (normal.m.LOCAL/'records/normal-state-retry-native-cpu-observations.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(record,ensure_ascii=False)+'\n')
        return result,observed

    def test_check_mode_holds_both_byte_locks_but_writes_no_target(self):
        f=self.fixture();result,marker=self.run_writer(f,check=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(marker['blocked'],[True,True])
        self.assertFalse(f[3].exists());self.assertIn('"checked"',result.stdout)

    def test_exact_create_and_idempotence_then_foreign_refusal(self):
        f=self.fixture();result,_=self.run_writer(f)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(f[3].read_bytes(),normal.SHIM_BYTES)
        before=f[3].stat().st_mtime_ns;result,_=self.run_writer(f)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(f[3].stat().st_mtime_ns,before)
        f[3].write_bytes(b'foreign');result,_=self.run_writer(f)
        self.assertNotEqual(result.returncode,0);self.assertEqual(f[3].read_bytes(),b'foreign')

    def test_guard_failure_never_creates_target_and_releases_locks(self):
        f=self.fixture();result,marker=self.run_writer(f,code=17)
        self.assertNotEqual(result.returncode,0);self.assertFalse(f[3].exists());self.assertEqual(marker['blocked'],[True,True])

    def test_caller_policy_absent_and_present_reaches_both_profile_lookups_unchanged(self):
        for prior in (None,'RemoteSigned'):
            with self.subTest(prior=prior):
                f=self.fixture();result,marker=self.run_writer(f,check=True,prior=prior)
                self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(marker['policy'],prior)
                self.assertTrue(marker['shells'])
                self.assertTrue(all(row==dict(policy=prior,no_profile=False) for row in marker['shells']))


if __name__=='__main__':unittest.main()
