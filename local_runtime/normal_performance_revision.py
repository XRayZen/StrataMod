"""Opt-in saved performance flags on a clean, release-descended local install.

Receipts keep installation-specific paths and hashes private. Existing release
and native revisions retain their original validators and defaults.
"""
import copy
import ctypes
import errno
import msvcrt
import os
from pathlib import Path
import re
import subprocess
import time
from . import manifest as m,release_revision as release

BASELINE='3d1fb48090e8f2cefc22d7b5845fb7f5b71f33fa'
FLAGS={'STRATA_HIP_WMMA':'1','STRATA_PF_FUSED':'1'}


def git(*args):
    return subprocess.check_output(['git','--no-optional-locks','-C',str(m.ROOT),*args]).decode().strip()


def revision():
    subprocess.run(['git','--no-optional-locks','-C',str(m.ROOT),'merge-base','--is-ancestor',BASELINE,'HEAD'],
                   check=True,capture_output=True)
    if git('status','--porcelain','--untracked-files=no'):
        raise RuntimeError('Performance revision requires committed, clean tracked/index source')
    return dict(baseline=BASELINE,commit=git('rev-parse','HEAD'),tree=git('rev-parse','HEAD^{tree}'))


def receipt(n,reference):
    if not isinstance(reference,dict) or set(reference)!={'path','sha256'} or not re.fullmatch('[0-9a-f]{64}',reference.get('sha256','')):
        raise RuntimeError('Exact private receipt reference required')
    path=m.local_path(Path(reference['path']));n.no_links(path)
    if path.name!='receipt.json' or path.parent.parent!=n.HOME/'installations':
        raise RuntimeError('Receipt must belong to this normal installation root')
    if m.digest(path)!=reference['sha256']:raise RuntimeError('Private parent receipt changed')
    value=m.read_json(path)
    if value.get('kind')!=n.KIND:raise RuntimeError('Expected normal receipt kind')
    profile_path=m.local_path(Path(value['profile']));n.no_links(profile_path)
    if profile_path!=path.parent/'profile.json' or m.digest(profile_path)!=value.get('profile_sha256'):
        raise RuntimeError('Parent profile must match its exact installation receipt')
    return value


def parent(n,reference):
    """Anchor inherited data to the original full proof, not a self-hashed JSON."""
    base=receipt(n,reference);fixed=base.get('release_revision',{})
    full=release.parent(n)
    if fixed.get('version')!=1 or fixed.get('parent')!=dict(path=str(release.PARENT),sha256=release.PARENT_SHA,
                                                         full_at=full['full_content_verification_at']):
        raise RuntimeError('Release parent full-proof lineage changed')
    if fixed.get('bundle')!=dict(archive_sha256=release.ARCHIVE_SHA,manifest_sha256=release.MANIFEST_SHA,root=str(release.RUNTIME)):
        raise RuntimeError('Release parent signed component changed')
    if (base.get('assets_full_sha_read_this_revision') is not False
            or base.get('full_content_verification_at')!=full['full_content_verification_at']):
        raise RuntimeError('Inherited full verification changed')
    if m.read_json(base['profile'])!=release.profile(n,Path(base['profile']).parent,full):
        raise RuntimeError('Release parent profile differs from its anchored configuration')
    paths=release.dependencies(n,full)
    if set(base['assets'])!={str(p) for p in paths}:raise RuntimeError('Release parent exact dependency inventory changed')
    component_paths={str(p) for p in release.bundle(n)}
    python_paths={str(p) for p in release.python_paths(n)}
    new=component_paths|python_paths
    inherited=set(base['assets'])-new
    proof=fixed.get('asset_proof',{})
    if (set(proof)!= {'inherited','full_hashed'} or set(proof['inherited'])!=inherited
            or set(proof['full_hashed'])!=new or len(proof['inherited'])!=len(inherited)
            or len(proof['full_hashed'])!=len(new)):
        raise RuntimeError('Release parent full/inherited proof partition changed')
    for name in inherited:
        if base['assets'][name]!=full['assets'].get(name):
            raise RuntimeError('Inherited model hash/metadata differs from immutable full proof')
    # The signed manifest is an independent authority for bundle hashes. Python
    # distribution files were fully hashed by the release installation; they are
    # rechecked by validate_assets(hash_small=True) at prepare/publish, not
    # misrepresented as hashes inherited from the older model proof.
    from strata_control import engine_component as ec
    component=ec.read_manifest(release.RUNTIME)
    expected={str(release.RUNTIME/name):sha for name,sha,_ in component.files}
    expected[str(release.RUNTIME/ec.MANIFEST)]=release.MANIFEST_SHA
    if set(expected)!=component_paths:raise RuntimeError('Signed component inventory changed')
    for name,sha in expected.items():
        if base['assets'][name].get('sha256')!=sha:
            raise RuntimeError('Bundle asset hash differs from signed component')
    return base


def profile(base):
    cfg=copy.deepcopy(m.read_json(base['profile']))
    if cfg.get('env')!={}:raise RuntimeError('Performance adoption requires unspecified parent flags')
    cfg['env']=dict(FLAGS)
    return cfg


def prior(n,reference,base,parent_reference):
    old=receipt(n,reference);fixed=old.get('normal_performance_adoption',{})
    if (fixed.get('version')!=1 or fixed.get('flags')!=FLAGS
            or fixed.get('parent',{}).get('path')!=parent_reference['path']
            or fixed.get('parent',{}).get('sha256')!=parent_reference['sha256']
            or fixed.get('parent',{}).get('profile_sha256')!=base['profile_sha256']):
        raise RuntimeError('Prior raw adoption must identify this same release parent')
    if m.read_json(old['profile'])!=profile(base):raise RuntimeError('Current saved settings differ from the approved two flags')
    expected=copy.deepcopy(base);expected.pop('release_revision')
    for key in ('profile','profile_sha256','sources','normal_performance_adoption'):expected[key]=old[key]
    if old!=expected:raise RuntimeError('Prior adoption inherited assets/full proof changed')
    return old


def validate(n,value):
    fixed=value.get('normal_performance_adoption',{})
    if (set(fixed)!={'version','flags','release_parent','prior_installation','selection_before','source'}
            or fixed.get('version')!=2 or fixed.get('flags')!=FLAGS
            or value.get('kind')!=n.KIND or 'release_revision' in value or 'native_revision' in value):
        raise RuntimeError('Unsupported or ambiguous clean performance adoption')
    base=parent(n,fixed['release_parent']);prior(n,fixed['prior_installation'],base,fixed['release_parent'])
    if fixed['source']!=revision() or value.get('sources')!=n.source_files():
        raise RuntimeError('Exact clean performance source changed')
    selection=fixed['selection_before']
    if (set(selection)!={'path','sha256'} or selection['path']!=str(n.SELECTION)
            or not re.fullmatch('[0-9a-f]{64}',selection.get('sha256',''))):
        raise RuntimeError('Exact prior selection binding required')
    path=m.local_path(Path(value['profile']));n.no_links(path)
    if (path.name!='profile.json' or path.parent.parent!=n.HOME/'installations'
            or m.digest(path)!=value.get('profile_sha256') or m.read_json(path)!=profile(base)):
        raise RuntimeError('Normal settings changed outside the two adopted flags')
    expected=copy.deepcopy(base);expected.pop('release_revision')
    expected.update(profile=value['profile'],profile_sha256=value['profile_sha256'],sources=value['sources'],
                    normal_performance_adoption=copy.deepcopy(fixed))
    if value!=expected:raise RuntimeError('Normal assets/full proof changed')


def session_id(pid):
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.ProcessIdToSessionId.argtypes=[wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
    kernel.ProcessIdToSessionId.restype=wintypes.BOOL
    result=wintypes.DWORD()
    if not kernel.ProcessIdToSessionId(pid,ctypes.byref(result)):raise ctypes.WinError(ctypes.get_last_error())
    return result.value


def require_lock_parent(n,owner):
    """A fresh child verifies its saved parent and both existing byte locks."""
    if set(owner)!={'pid','created','exe','argv','session'} or owner.get('pid')!=os.getppid():
        raise RuntimeError('Lock coordinator must be this fresh interpreter parent')
    process=n.safety.require_identity(n.safety.process_identity_status(owner))
    if (process is None or process.cmdline()!=owner['argv'] or session_id(owner['pid'])!=owner['session']
            or session_id(os.getpid())!=owner['session']):
        raise RuntimeError('Lock coordinator birth/command/session changed')
    for name in ('cli-operation.lock','runtime.lock'):
        path=m.DATA/'records'/name;n.no_links(path)
        with path.open('r+b') as stream:
            if stream.seek(0,2)<1:raise RuntimeError('Existing shared lock is empty')
            stream.seek(0)
            try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            except OSError as error:
                if error.errno not in (errno.EACCES,errno.EAGAIN) and getattr(error,'winerror',None)!=33:raise
            else:
                stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
                raise RuntimeError('Coordinator must already hold both shared locks')
    return dict(parent=copy.deepcopy(owner),both_locks_exclusive=True)


def prepare_locked(n,descriptor,owner):
    """Operator-only helper; its verified parent holds operation then runtime."""
    lock_proof=require_lock_parent(n,owner)
    n.runner.production_inactive()
    state=n.status()
    if state.get('running') is not False or state.get('cleanup_pending') is not False:
        raise RuntimeError('Normal runtime must be positively stopped')
    if set(descriptor)!={'release_parent','prior_installation','selection_before'}:
        raise RuntimeError('Finite installation migration descriptor required')
    base=parent(n,descriptor['release_parent']);prior(n,descriptor['prior_installation'],base,descriptor['release_parent'])
    pointer=m.read_json(n.SELECTION)
    if pointer.get('receipt')!=descriptor['prior_installation']['path'] or pointer.get('sha256')!=descriptor['prior_installation']['sha256']:
        raise RuntimeError('Current selection is not the exact prior adoption')
    selection=dict(path=str(n.SELECTION),sha256=m.digest(n.SELECTION))
    if descriptor['selection_before']!=selection:raise RuntimeError('Selection changed before prepare')
    source=revision();sources=n.source_files()
    n.validate_assets(base,hash_small=True)
    directory=n.HOME/'installations'/str(time.time_ns());directory.mkdir()
    path=directory/'profile.json';n.write(path,profile(base))
    value=copy.deepcopy(base);value.pop('release_revision')
    value.update(profile=str(path),profile_sha256=m.digest(path),sources=sources,
        normal_performance_adoption=dict(version=2,flags=dict(FLAGS),source=source,**copy.deepcopy(descriptor)))
    validate(n,value);output=directory/'receipt.json';n.write(output,value)
    return dict(receipt=str(output),sha256=m.digest(output),activated=False,lock_proof=lock_proof)


def activation_precondition(n,value):
    validate(n,value)
    if m.digest(n.SELECTION)!=value['normal_performance_adoption']['selection_before']['sha256']:
        raise RuntimeError('Selection changed after review; activation refused')
