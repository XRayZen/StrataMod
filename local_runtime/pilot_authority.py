"""Independent, finite P0/P1 authority. Normal receipts are immutable data proof only."""
from dataclasses import dataclass
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from . import manifest as m

KIND='stratamod-prefill-timing-pilot-v1'
BASE_HEAD='baafa177ec9e9791a472ce8c81c6ecfbe3aa3293'
BASE_TREE='1573732300dc951399c8edc6166fd3cee202fe7b'
PILOT=Path(r'C:\Develop\AI\.private\stratamod-prefill-timing-pilot-20261020')
NORMAL=Path(r'C:\Develop\AI\StrataMod')
PARENT_SHA='6285b63ce9149a6b4c00c4be6c4eb994b7cc4052022408b1ff2bdc38571a96f1'
PROFILE_SHA='394028cdaca3dbca1948375f67cb71cd6b3cd2fc0b2c62e45712715678f21f6e'
ARCHIVE_SHA='61a42755d125ed45e36f3beaa7b74daa958322dcb957a699a5006b344d1c3654'
COMPONENT_SHA='fc055b98893a4dfb16bf03a1979d4783ca2f0a8b2e7d87c40ae08b71604f72e3'
PLAN_SHA='eb79a37fbc3f227e8cd7f8febc28ecf4ef46eefb9eb8b394e4a3dcd9d4980fd0'
RESEARCH_SHA='5ee0fc97d34bb5b177d805e984ec3b46ee0dd51db2a001b162153b67c4aaf445'
ORDER=('00-unset','00-timing1','11-timing1','11-unset')
ARMS={name:dict(STRATA_HIP_WMMA=name[:2][0],STRATA_PF_FUSED=name[:2][1],
               **({'STRATA_PREFILL_TIMING':'1'} if name.endswith('timing1') else {})) for name in ORDER}
LIMITS=dict(starts=4,requests=12,request_seconds=120,max_tokens=128)
WARMUP='A separate warmup: name the three primary colors.'
CHANGED=('local_runtime/manifest.py','local_runtime/official_runtime.py','local_runtime/runtime_safety.py',
         'local_runtime/release_revision.py')
ADDED=('local_runtime/pilot_authority.py','local_runtime/prefill_timing_pilot.py','local_runtime/timing_parser.py',
       'local_runtime/pilot_analysis.py',
       'local_runtime/tests/test_pilot_authority.py','local_runtime/tests/test_prefill_timing_pilot.py',
       'local_runtime/tests/test_timing_parser.py')


def write(path,value):
    path=Path(path);tmp=path.with_suffix(path.suffix+'.new')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(path)


def no_links(path):
    path=Path(path)
    if not path.is_absolute() or '..' in path.parts:raise RuntimeError('Absolute normalized pilot path required')
    for part in (path,*path.parents):
        if part.exists() or part.is_symlink():
            row=part.lstat()
            if part.is_symlink() or getattr(row,'st_file_attributes',0)&0x400:raise RuntimeError('Pilot linked/reparse path refused')


@dataclass(frozen=True)
class PilotContext:
    source:Path
    pilot:Path
    normal:Path
    original:Path
    data:Path

    @property
    def runtime(self):return self.normal/'local_runtime/runtimes'/('engine-0.1.45.3-'+ARCHIVE_SHA[:12])
    @property
    def state(self):return self.pilot/'records/owned-runtime.json'
    @property
    def runs(self):return self.pilot/'runs'
    @property
    def authority(self):return self.pilot/'authority.json'
    @property
    def operator(self):return self.pilot/'pilot_cli.py'
    @property
    def python(self):return Path(sys._base_executable)
    @property
    def venv(self):return self.original/'.venv/Scripts/python.exe'

    def local(self,path):
        path=Path(path);no_links(path)
        if not path.is_relative_to(self.pilot):raise RuntimeError('Pilot write outside exact private root')
        return path


def production_context():
    result=PilotContext(m.ROOT,PILOT,NORMAL,NORMAL.parent/'Strata',NORMAL.parent/'Strata-data')
    if result.source!=Path(r'C:\Develop\AI\.private\stratamod-v020-integration'):
        raise RuntimeError('Pilot source root differs from reviewed private worktree')
    for path in (result.source,result.pilot,result.normal,result.original,result.data,result.runtime):no_links(path)
    return result


def context_for_state(state):
    ctx=production_context()
    if state.get('kind')!=KIND or state.get('pilot_root')!=str(ctx.pilot):raise RuntimeError('Wrong private pilot authority/root')
    return ctx


def arm_config(base,source,directory,arm):
    if arm not in ARMS:raise RuntimeError('Unapproved timing pilot arm')
    if base.get('env')!={}:raise RuntimeError('Normal semantic profile must retain env{}')
    from tools.calibrate import with_arg
    result=copy.deepcopy(base)
    result.update(cwd=str(source),log=str(directory/'engine.log'),env=copy.deepcopy(ARMS[arm]))
    result['args']=with_arg(result['args'],'--prompt-cache','0')
    result['vision']['temp_dir']=str(directory/'tmp')
    return result


def stopped_guard(root):
    if (root/'aborted.json').exists():raise RuntimeError('Pilot aborted; additional starts/requests forbidden')


def claim(root,name):
    no_links(root/name)
    try:
        with (root/name).open('x',encoding='utf-8') as f:f.write(str(time.time()))
    except FileExistsError:raise RuntimeError('Pilot claim already consumed; no replay') from None


def reserve_start(root,index):
    root=Path(root);stopped_guard(root)
    if type(index) is not int or not 0<=index<4:raise RuntimeError('Pilot four-start budget exceeded')
    if index:
        p=root/f'completion-{index-1}.json'
        if not p.is_file() or m.read_json(p).get('complete') is not True:raise RuntimeError('Prior pilot cohort exit is not complete')
        complete=m.read_json(p)
        if complete.get('cleanup',{}).get('complete') is not True or complete.get('cleanup',{}).get('port_free') is not True:
            raise RuntimeError('Prior pilot whole-cohort/port proof missing')
        if set(complete.get('samples',{}))!={'0','1','2'}:raise RuntimeError('Prior pilot completion sample binding missing')
        for slot in range(3):
            q=root/f'request-{index-1}-{slot}.sample.json'
            if not q.is_file() or m.read_json(q).get('valid') is not True:raise RuntimeError('Prior pilot sample invalid/missing')
            if m.digest(q)!=complete['samples'][str(slot)]:raise RuntimeError('Prior pilot completed sample changed')
    claim(root,f'start-{index}.claim')


def reserve_request(root,index,slot):
    root=Path(root);stopped_guard(root)
    if type(index) is not int or not 0<=index<4 or type(slot) is not int or not 0<=slot<3:
        raise RuntimeError('Pilot twelve-request budget exceeded')
    if not (root/f'start-{index}.claim').is_file():raise RuntimeError('Pilot start claim absent')
    if slot:
        p=root/f'request-{index}-{slot-1}.sample.json'
        if not p.is_file() or m.read_json(p).get('valid') is not True:raise RuntimeError('Prior pilot sample invalid/missing')
    claim(root,f'request-{index}-{slot}.claim')


def git(ctx,*args):
    return subprocess.check_output(['git','--no-optional-locks','-C',str(ctx.source),*args])


def source_proof(ctx,*,full=False):
    if git(ctx,'rev-parse','HEAD').decode().strip()!=BASE_HEAD or git(ctx,'rev-parse','HEAD^{tree}').decode().strip()!=BASE_TREE:
        raise RuntimeError('Pilot fixed base Git HEAD/tree changed')
    changed=git(ctx,'diff','--name-only','HEAD').decode().splitlines()
    untracked=git(ctx,'ls-files','--others','--exclude-standard').decode().splitlines()
    if set(changed)-set(CHANGED) or set(untracked)-set(ADDED):raise RuntimeError('Pilot source change outside reviewed finite paths')
    if any(not (ctx.source/p).is_file() for p in ADDED):raise RuntimeError('Reviewed pilot source closure is incomplete')
    files={p:m.digest(ctx.source/p) for p in ADDED}
    imports=m.source_files()
    result=dict(base_head=BASE_HEAD,base_git_tree=BASE_TREE,source_root=str(ctx.source),
                tracked_diff_sha256=hashlib.sha256(git(ctx,'diff','--binary','HEAD')).hexdigest(),
                extra_sources=files,imports=imports,operator_sha256=m.digest(ctx.operator))
    if full:
        names=[s.decode('utf-8') for s in git(ctx,'ls-files','--cached','--others','--exclude-standard','-z').split(b'\0') if s]
        rows={s:m.digest(ctx.source/s) for s in sorted(names)}
        result.update(raw_inventory=rows,raw_tree_digest=hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest())
    return result


def parent_proof(ctx):
    """Validate normal's own authority in its own isolated read-only interpreter."""
    code='''import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[2]);sys.path.insert(0,sys.argv[1])
from local_runtime import normal_runtime as n
p,v=n.selected();n.validate_assets(v)
print('_PILOT_PARENT_'+json.dumps(dict(pointer=p,receipt=v,profile=n.m.read_json(v['profile']),
    selection_sha256=n.m.digest(n.SELECTION)),separators=(',',':')))
'''
    process=subprocess.run([str(ctx.python),'-I','-B','-X','utf8','-c',code,str(ctx.normal),str(ctx.venv.parent.parent/'Lib/site-packages')],
                           capture_output=True,text=True,encoding='utf-8',check=True,
                           env={**os.environ,'GIT_OPTIONAL_LOCKS':'0'})
    lines=[s[len('_PILOT_PARENT_'):] for s in process.stdout.splitlines() if s.startswith('_PILOT_PARENT_')]
    if len(lines)!=1:raise RuntimeError('Normal immutable proof verifier returned no unique result')
    value=json.loads(lines[0]);pointer=value['pointer'];receipt=value['receipt']
    if pointer.get('sha256')!=PARENT_SHA or m.digest(pointer['receipt'])!=PARENT_SHA or receipt['profile_sha256']!=PROFILE_SHA:
        raise RuntimeError('Pilot immutable normal parent changed')
    if value['profile'].get('env')!={}:raise RuntimeError('Normal parent flags changed')
    return value


def parent_asset_path(ctx,name):
    """Five unchanged wheel entrypoints retain their inherited raw spelling."""
    path=Path(name)
    if '..' not in path.parts:no_links(path);return path
    site=ctx.original/'.venv/Lib/site-packages'
    names=('f2py.exe','numpy-config.exe','tqdm.exe','normalizer.exe','idna.exe')
    allowed={site/'../../Scripts'/basename for basename in names}
    if path not in allowed:raise RuntimeError('Inherited parent path outside exact wheel-script list')
    no_links(site)  # Check the traversed prefix before collapsing .. lexically.
    normalized=Path(os.path.abspath(path));expected=ctx.original/'.venv/Scripts'/path.name
    if normalized!=expected:raise RuntimeError('Inherited wheel script outside exact venv/Scripts')
    no_links(normalized)
    return path


def verify_parent(ctx,parent,*,full=False):
    pointer=parent['pointer'];receipt=parent['receipt']
    for path,expected in ((ctx.normal/'local_runtime/normal/installed.json',parent['selection_sha256']),
                          (Path(pointer['receipt']),PARENT_SHA),(Path(receipt['profile']),PROFILE_SHA)):
        no_links(path)
        if m.digest(path)!=expected:raise RuntimeError('Pilot normal data proof changed')
    for path,expected in receipt['sources'].items():
        no_links(Path(path))
        if m.digest(path)!=expected:raise RuntimeError('Normal immutable parent source changed')
    new=set(receipt['release_revision']['asset_proof']['full_hashed'])
    for path,row in receipt['assets'].items():
        inherited=parent_asset_path(ctx,path);st=inherited.stat()
        if row['metadata']!=dict(path=path,size=st.st_size,mtime_ns=st.st_mtime_ns,reparse=False):
            raise RuntimeError('Pilot inherited asset metadata changed')
        if full and path in new and m.digest(path)!=row['sha256']:raise RuntimeError('Stock/Python full dependency hash changed')


def prepare(ctx):
    if ctx.authority.exists():raise RuntimeError('Pilot authority already prepared; never overwrite')
    for p in (ctx.pilot/'records',ctx.runs):ctx.local(p).mkdir(parents=True,exist_ok=True)
    if m.digest(ctx.pilot/'implementation-plan-v1.md')!=PLAN_SHA:raise RuntimeError('Approved implementation plan changed')
    parent=parent_proof(ctx);verify_parent(ctx,parent,full=True)
    from strata_control import engine_component as ec,signing
    if m.digest(ctx.runtime/ec.MANIFEST)!=COMPONENT_SHA:raise RuntimeError('Fixed signed component manifest changed')
    component=ec.read_manifest(ctx.runtime);signing.install_component_verifier(signing.load_trusted_keys(environ={}))
    if ec.verify_signature(component,{ec.ENV_REQUIRE_SIGNED:'1'})!='verified':raise RuntimeError('Stock component signature is not verified')
    ec.verify(component,full=True)
    expected={p for p,_,_ in component.files}|{ec.MANIFEST}
    actual={p.relative_to(ctx.runtime).as_posix() for p in ctx.runtime.rglob('*') if p.is_file()}
    if expected!=actual:raise RuntimeError('Stock dependency closure inventory differs')
    for name in expected:no_links(ctx.runtime/name)
    from . import release_trial
    fixture=release_trial.cases(parent['profile']['tokenizer'])
    prior=m.read_json(ctx.normal/'local_runtime/release-trials/deploy-20261020-v5/manifest.json')
    if fixture!=prior['fixture'] or WARMUP!=prior['warmup']:raise RuntimeError('Prior exact fixture bytes/token IDs changed')
    fixed=dict(kind=KIND,version=1,plan_sha256=PLAN_SHA,research_sha256=RESEARCH_SHA,
               source=source_proof(ctx,full=True),parent_data_proof=parent,
               stock=dict(root=str(ctx.runtime),archive_sha256=ARCHIVE_SHA,manifest_sha256=COMPONENT_SHA,
                          build=m.read_json(ctx.runtime/'BUILD.json'),source_identity_proven=False),
               arms=ARMS,order=list(ORDER),limits=LIMITS,fixture=fixture,warmup=WARMUP,
               roots=dict(source=str(ctx.source),pilot=str(ctx.pilot),normal=str(ctx.normal),original=str(ctx.original),data=str(ctx.data)),
               normal_unchanged=dict(env={},prompt_cache=6),trial_prompt_cache=0,
               private_write_relocation=dict(user_environment=['USERPROFILE','LOCALAPPDATA','APPDATA'],
                   reason='Keep stock lifeline/process records private; identical for all four arms',
                   mutable=['config','logs','temp','comgr','user records','MCP tracking','claims','results'],
                   read_only=['normal stock runtime','shared Python/site-packages','models/pack/tokenizer/projector/expert profile']))
    with ctx.authority.open('x',encoding='utf-8') as f:json.dump(fixed,f,ensure_ascii=False,indent=2)
    return dict(authority=str(ctx.authority),sha256=m.digest(ctx.authority),prepared=True,activated=False)


def load(ctx,approved,*,full=False,fast=False):
    ctx.local(ctx.authority)
    if m.digest(ctx.authority)!=approved:raise RuntimeError('Exact Main-approved private pilot authority changed')
    value=m.read_json(ctx.authority)
    if (value.get('kind')!=KIND or value.get('version')!=1 or value.get('limits')!=LIMITS or value.get('arms')!=ARMS
            or value.get('order')!=list(ORDER) or value.get('normal_unchanged')!=dict(env={},prompt_cache=6)
            or value.get('trial_prompt_cache')!=0):raise RuntimeError('Pilot finite protocol changed')
    if value.get('plan_sha256')!=PLAN_SHA or value.get('research_sha256')!=RESEARCH_SHA:
        raise RuntimeError('Pilot approved plan identity changed')
    roots=dict(source=str(ctx.source),pilot=str(ctx.pilot),normal=str(ctx.normal),original=str(ctx.original),data=str(ctx.data))
    if value.get('roots')!=roots:raise RuntimeError('Pilot exact roots changed')
    if fast:
        return value
    proof=source_proof(ctx,full=full)
    expected=value['source'] if full else {k:v for k,v in value['source'].items() if k not in ('raw_inventory','raw_tree_digest')}
    if proof!=expected:raise RuntimeError('Reviewed pilot source/operator bytes changed')
    verify_parent(ctx,value['parent_data_proof'],full=full)
    if value.get('stock')!=dict(root=str(ctx.runtime),archive_sha256=ARCHIVE_SHA,manifest_sha256=COMPONENT_SHA,
                              build=m.read_json(ctx.runtime/'BUILD.json'),source_identity_proven=False):
        raise RuntimeError('Pilot signed stock runtime binding changed')
    from . import release_trial
    if value.get('fixture')!=release_trial.cases(value['parent_data_proof']['profile']['tokenizer']) or value.get('warmup')!=WARMUP:
        raise RuntimeError('Fixed private prompt bytes/token IDs changed')
    return value
