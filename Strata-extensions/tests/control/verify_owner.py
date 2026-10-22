"""Fixed-source T24 host verification. Never invokes official runtime mutators."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

EXT=Path(__file__).resolve().parents[2]
BUILD=EXT.parent/'build-deepseek-t24'
DATA=Path('C:/Develop/AI/Strata-data')
PYTHON=Path('C:/Develop/AI/Strata/.venv/Scripts/python.exe')
FILES=[EXT/'control/owner_adapter.py',EXT/'control/bootstrap_binding.py',Path(__file__).with_name('test_owner_adapter.py'),Path(__file__).with_name('owned_child.py'),Path(__file__)]
DEPENDENCIES=[DATA/name for name in ('manage_runtime.py','strata_cli.py','official_runtime.py','startup_progress.py','server_bootstrap.py','model_catalog.py','profile_defaults.py','runtime_temp_probe.py','runtime_permissions.py','huihui_authority.py')]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def bindings():
    paths=FILES+DEPENDENCIES+[PYTHON,Path(sys._base_executable)]
    # Existing environment is read-only. Bind all installed psutil Python/native
    # files used by the process identity fixture, without copying an environment.
    import psutil
    paths+=sorted(p for p in Path(psutil.__file__).parent.rglob('*') if p.is_file() and p.suffix in ('.py','.pyd'))
    return [dict(path=str(p.resolve()),sha256=sha(p),bytes=p.stat().st_size) for p in paths]
def main():
    p=argparse.ArgumentParser();p.add_argument('--verify-only',action='store_true');a=p.parse_args()
    BUILD.mkdir(exist_ok=True);bundle=BUILD/'bundle-r3';bundle.mkdir(exist_ok=True);manifest=bundle/'manifest.json';proof=BUILD/'verification-r3.json'
    current=bindings()
    if a.verify_only:
        fixed=json.loads(manifest.read_text(encoding='utf-8'))
        if fixed['bound_files']!=current:raise ValueError('fixed T24 file binding changed')
    else:
        if manifest.exists():raise ValueError('fixed manifest exists; use --verify-only')
        fixed=dict(schema='strata-t24-host-owner-fixture/v1',scope='isolated fixture provider, not official DeepSeek start',bound_files=current,
                   writes=str(BUILD),live_mutators=False,normal_runtime_gate=False)
        manifest.write_text(json.dumps(fixed,indent=2)+'\n',encoding='utf-8')
    before=sha(manifest);report=BUILD/('reverify.json' if a.verify_only else 'test-results-r3.json')
    command=[str(PYTHON),'-B','-X','utf8',str(FILES[2]),'--output',str(report)]
    result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8')
    (BUILD/('reverify.log' if a.verify_only else 'verify.log')).write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    tests=json.loads(report.read_text(encoding='utf-8'))
    if not tests['successful'] or tests['tests']!=15 or tests['failures'] or tests['errors']:raise ValueError('test result incomplete')
    if current!=bindings() or sha(manifest)!=before:raise ValueError('verification binding changed')
    output=dict(schema='strata-t24-host-proof/v1',manifest_sha256=before,before_after_binding_equal=True,
                tests=tests,official_start_qualified=False,GPU_used=False,
                import_boundary='Existing manager/CLI imported with -B; only fixture subprocess patches ROOT/STATE/PORT and CLI ROOT. No Runtime/native/start/catalog/official mutator calls.',
                method='Explicit CLI then manager lock; existing cohort/port/PID guards; retained Popen only for test-owned cleanup.')
    if not a.verify_only:proof.write_text(json.dumps(output,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(tests=tests['tests'],failed=0,manifest_sha256=before,verification_sha256=sha(proof),bound_files=len(current),verify_only=a.verify_only)))
if __name__=='__main__':main()
