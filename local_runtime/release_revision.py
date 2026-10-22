"""Finite official 0.1.45.3 bundle revision of one saved normal authority.

Legacy receipts retain their validators. This revision never rewrites its parent
or treats metadata inheritance as a new full model-body verification.
"""
import copy
import importlib.metadata
import json
import re
from pathlib import Path
import subprocess
import time

from . import manifest as m

BASELINE='f5e61621c0dac970e62b12f7bbd181cf75a917da'
PARENT=m.LOCAL/'normal/installations/1792415837605671800/receipt.json'
PARENT_SHA='94600cc4e28cf81eb9cf557989d903d1a7c15da55faa8271bafd0bdb3822eb22'
PROFILE_SHA='10ab912b83aea46a3419990a72373d0bc0f9fa490c1d2ef4a8383b706b34bcb7'
ARCHIVE_SHA='61a42755d125ed45e36f3beaa7b74daa958322dcb957a699a5006b344d1c3654'
MANIFEST_SHA='fc055b98893a4dfb16bf03a1979d4783ca2f0a8b2e7d87c40ae08b71604f72e3'
RUNTIME=m.LOCAL/'runtimes'/('engine-0.1.45.3-'+ARCHIVE_SHA[:12])
PACKAGES=('numpy','jinja2','regex','pyyaml','tqdm','requests','pillow','psutil',
          'markupsafe','certifi','charset-normalizer','idna','urllib3','colorama')


def parent(n):
    n.no_links(PARENT)
    if m.digest(PARENT)!=PARENT_SHA:raise RuntimeError('Release parent receipt changed')
    value=m.read_json(PARENT)
    if value.get('kind')!=n.KIND or not value.get('full_content_verification_at'):
        raise RuntimeError('Release parent is not its fixed full proof')
    n.no_links(Path(value['profile']))
    if value['profile_sha256']!=PROFILE_SHA or m.digest(value['profile'])!=PROFILE_SHA:
        raise RuntimeError('Release parent profile changed')
    return value


def profile(n,directory,base=None):
    base=parent(n) if base is None else base
    cfg=copy.deepcopy(m.read_json(base['profile']))
    if cfg.get('env')!={}:raise RuntimeError('Normal flags must remain unspecified')
    cfg.update(exe=str(RUNTIME/'strata.exe'),lib_dirs=[str(RUNTIME),str(RUNTIME/'rocm/bin')],
               log=str(Path(directory)/'engine.log'))
    vision=cfg['vision'];vision.pop('rocm_root',None);vision.pop('hip_device',None)
    vision.update(reader_mode='official-bundle',exe=str(RUNTIME/'strata-vision-hip.exe'),
                  cpu_exe=str(RUNTIME/'strata-vision.exe'),temp_dir=str(Path(directory)/'tmp'))
    return cfg


def bundle(n,*,full=False):
    from strata_control import engine_component as ec,signing
    n.no_links(RUNTIME);n.no_links(RUNTIME/ec.MANIFEST)
    if m.digest(RUNTIME/ec.MANIFEST)!=MANIFEST_SHA:raise RuntimeError('Signed release manifest changed')
    component=ec.read_manifest(RUNTIME)
    signing.install_component_verifier(signing.load_trusted_keys(environ={}))
    if ec.verify_signature(component,{ec.ENV_REQUIRE_SIGNED:'1'})!='verified':raise RuntimeError('Release component signature unverified')
    ec.verify(component,full=full)
    expected={p for p,_,_ in component.files}|{ec.MANIFEST}
    actual={p.relative_to(RUNTIME).as_posix() for p in RUNTIME.rglob('*') if p.is_file()}
    if expected!=actual:raise RuntimeError('Release runtime inventory changed')
    for name in expected:n.no_links(RUNTIME/name)
    return [RUNTIME/name for name in sorted(expected)]


def python_paths(n):
    """Only the named runtime distributions in the existing read-only venv."""
    site=m.VENV_PYTHON.parent.parent/'Lib/site-packages'
    paths=[m.PYTHON,m.VENV_PYTHON,m.VENV_PYTHON.parent.parent/'pyvenv.cfg']
    paths.extend(site.glob('*.pth'))
    paths.extend(p for p in (site/'_virtualenv.py',site/'sitecustomize.py',site/'usercustomize.py') if p.is_file())
    for name in PACKAGES:
        found=list(importlib.metadata.distributions(path=[str(site)]))
        dist=next((d for d in found if d.metadata['Name'].lower().replace('_','-')==name.replace('_','-')),None)
        if dist is None:raise RuntimeError('Shared Python dependency missing: '+name)
        if not dist.files:raise RuntimeError('Shared Python distribution has no file proof: '+name)
        for entry in dist.files:
            path=Path(dist.locate_file(entry)).absolute()
            if path.suffix.lower()=='.pyc':continue
            # Wheel scripts outside site are not imported by the runtime.
            if not path.is_relative_to(site):continue
            if not path.is_file():raise RuntimeError('Shared Python distribution file missing: '+str(path))
            paths.append(path)
    paths.extend(p for p in m.PYTHON.parent.glob('python*.dll') if p.is_file())
    return list(dict.fromkeys(paths))


def dependencies(n,base=None):
    base=parent(n) if base is None else base
    # The actual immutable data closure from the saved full proof, excluding old
    # engine/SDK/repair evidence. Keep the expert profile used by text as well.
    old=m.read_json(base['profile'])
    expert=Path(n.cal.arg_value(old['args'],'--expert-profile'))
    paths=[Path(p) for p in base['assets'] if Path(p).is_relative_to(m.DATA) or Path(p)==expert]
    return list(dict.fromkeys([*paths,*python_paths(n),*bundle(n)]))


def prove_assets(n,paths,prior,*,new_paths):
    assets={};inherited=[];hashed=[]
    for path in paths:
        path=Path(path);name=str(path);before=n.metadata(path)
        old=prior.get(name)
        if name not in new_paths and old is not None and old['metadata']==before:
            assets[name]=copy.deepcopy(old);inherited.append(name)
        else:
            sha=m.digest(path);n.check_metadata(path,before)
            assets[name]=dict(sha256=sha,metadata=before);hashed.append(name)
    return assets,dict(inherited=inherited,full_hashed=hashed)


def revision():
    def git(*args):return subprocess.check_output(['git','-C',str(m.ROOT),*args]).decode().strip()
    subprocess.run(['git','-C',str(m.ROOT),'merge-base','--is-ancestor',BASELINE,'HEAD'],check=True,capture_output=True)
    if git('status','--porcelain','--untracked-files=no'):raise RuntimeError('Release source must be committed and clean')
    return dict(commit=git('rev-parse','HEAD'),tree=git('rev-parse','HEAD^{tree}'),baseline=BASELINE)


def validate(n,value):
    base=parent(n);fixed=value.get('release_revision',{})
    if fixed.get('version')!=1 or fixed.get('parent')!=dict(path=str(PARENT),sha256=PARENT_SHA,full_at=base['full_content_verification_at']):
        raise RuntimeError('Release full-proof lineage changed')
    if fixed.get('source')!=revision() or value.get('sources')!=n.source_files():raise RuntimeError('Release exact source changed')
    if fixed.get('bundle')!=dict(archive_sha256=ARCHIVE_SHA,manifest_sha256=MANIFEST_SHA,root=str(RUNTIME)):
        raise RuntimeError('Release bundle authority changed')
    path=m.local_path(Path(value['profile']));n.no_links(path)
    if path.name!='profile.json' or m.digest(path)!=value.get('profile_sha256') or m.read_json(path)!=profile(n,path.parent,base):
        raise RuntimeError('Release profile changed outside finite delta')
    paths=dependencies(n,base)
    if set(value['assets'])!={str(p) for p in paths}:raise RuntimeError('Release dependency inventory changed')
    proof=fixed.get('asset_proof',{})
    inherited=proof.get('inherited',[]);hashed=proof.get('full_hashed',[])
    if len(set(inherited+hashed))!=len(inherited+hashed) or set(inherited+hashed)!=set(value['assets']):
        raise RuntimeError('Release asset proof partition changed')
    new={str(p) for p in bundle(n)}|{str(p) for p in python_paths(n)}
    if new&set(inherited):raise RuntimeError('New runtime/Python closure cannot inherit old hashes')
    for name in inherited:
        if value['assets'][name]!=base['assets'].get(name):raise RuntimeError('Inherited full asset hash changed')
    if value.get('assets_full_sha_read_this_revision') is not False:raise RuntimeError('No new full model pass was performed')
    if value.get('full_content_verification_at')!=base['full_content_verification_at']:raise RuntimeError('Parent full verification time changed')


def prepare(n):
    with n.runner.shared_operation():
        n.runner.production_inactive();base=parent(n);bundle(n,full=True)
        paths=dependencies(n,base);new={str(p) for p in bundle(n)}|{str(p) for p in python_paths(n)}
        assets,proof=prove_assets(n,paths,base['assets'],new_paths=new)
        directory=n.HOME/'installations'/str(time.time_ns());directory.mkdir(parents=True)
        path=directory/'profile.json';n.write(path,profile(n,directory,base))
        value=dict(kind=n.KIND,profile=str(path),profile_sha256=m.digest(path),sources=n.source_files(),assets=assets,
            full_content_verification_at=base['full_content_verification_at'],assets_full_sha_read_this_revision=False,
            verification_mode='release-full-new-closure-plus-inherited-model-metadata',normal_launch_full_asset_sha=False,
            release_revision=dict(version=1,parent=dict(path=str(PARENT),sha256=PARENT_SHA,full_at=base['full_content_verification_at']),
                source=revision(),bundle=dict(archive_sha256=ARCHIVE_SHA,manifest_sha256=MANIFEST_SHA,root=str(RUNTIME)),asset_proof=proof))
        validate(n,value);receipt=directory/'receipt.json';n.write(receipt,value)
        return dict(receipt=str(receipt),sha256=m.digest(receipt),activated=False,full_hashed=len(proof['full_hashed']),inherited=len(proof['inherited']))


def ready(n,state,cfg,value,monitor,observation,*,runtime_root=None):
    """Observe the actual official GPU/CPU reader, without inventing private traces."""
    runtime_root=RUNTIME if runtime_root is None else Path(runtime_root)
    status=n.safety.get_json('/v1/status');cap=status.get('vision',{})
    backend=cap.get('backend')
    if cap.get('available') is not True or backend not in ('hip','cpu') or cap.get('cleanup_pending') is not False or cap.get('error') is not None:
        raise RuntimeError('Official reader capability/alive/pending unknown')
    path=Path(cfg['vision']['exe'] if backend=='hip' else cfg['vision']['cpu_exe'])
    live=[r for r in observation['identities'] if Path(r['exe'])==path and n.safety.require_identity(n.safety.process_identity_status(r)) is not None]
    if len(live)!=1:raise RuntimeError('Actual official reader birth is absent/ambiguous')
    monitor.images=live
    native=next(r for r in observation['identities'] if Path(r['exe'])==Path(cfg['exe']))
    monitor.engine=native;deps={p:r['sha256'] for p,r in value['assets'].items()}
    text=n.gpu_observation.loaded_modules(native,deps,hash_files=False);n.gpu_observation.bind_module_hashes(text)
    modules=n.gpu_observation.loaded_modules(live[0],deps,hash_files=False);n.gpu_observation.bind_module_hashes(modules)
    for rows,names in ((text,m.CRITICAL_DLLS),(modules,('amdhip64_7.dll','hipblas.dll','rocblas.dll') if backend=='hip' else ())):
        for name in names:
            found=[r for r in rows if Path(r['path']).name.lower()==name]
            if len(found)!=1 or found[0].get('sha256')!=deps.get(found[0]['path']):raise RuntimeError('Release loaded DLL identity unknown: '+name)
            if not Path(found[0]['path']).is_relative_to(runtime_root):raise RuntimeError('Release DLL loaded outside sidecar')
    raw=Path(cfg['log']).read_text(encoding='utf-8',errors='replace')
    if 'GPU 0: AMD Radeon AI PRO R9700 (gfx1201)' not in raw:raise RuntimeError('Release text R9700/gfx1201 not confirmed')
    # The signed reader's quiet_log consumes INFO Device lines for its own
    # architecture check, but only emits WARN+. Bind the actual reader through
    # its signed DLLs, exact native argv and the same one-card mask as text.
    from serve.server import hip_visible,vision_env
    if (cfg.get('backend')!='hip' or cfg['vision'].get('reader_mode')!='official-bundle'
            or cfg['vision'].get('gpu') is not True or hip_visible(cfg)!=[1]
            or vision_env(cfg,dict(HIP_VISIBLE_DEVICES='1')).get('HIP_VISIBLE_DEVICES')!='1'):
        raise RuntimeError('Official reader/text physical HIP mask binding changed')
    for row in (native,live[0]):n.require_child_command(cfg,row['exe'],row.get('argv',[]))
    reported=re.findall(r'\bDevice (\d+): ([^\r\n]+)',raw)
    if backend=='hip' and any(index!='0' or not re.search(r'\bR9700, gfx1201\b',name) for index,name in reported):
        raise RuntimeError('Official reader supplemental device line contradicts R9700 binding')
    devices=[line for line in raw.splitlines() if re.search(r'Device 0: .*R9700, gfx1201\b',line)]
    windows=n.gpu_observation.windows_displays();adapter=n.gpu_observation.select_adapter(windows,n.gpu_observation.dxgi_adapters())
    state.update(phase='ready',loader=dict(text=text,image=modules,reader_backend=backend,windows=windows,adapter=adapter,
                 build=m.read_json(runtime_root/'BUILD.json'),reader_device_lines=devices,
                 reader_binding=dict(kind='signed-official-reader-mask-binding',physical_hip_ordinal=1,
                     logical_ordinal=0 if backend=='hip' else None,selected_alive_backend=backend,
                     device_stdout='supplementary lines present' if devices else 'INFO Device lines suppressed by official quiet_log',
                     graph_observation='not available in signed official reader'),
                 device_binding='same signed ROCm runtime + exact reader argv + shared text HIP mask 1 => logical 0 R9700/gfx1201 + OS PCI identity; CPU fallback separately identified',
                 private_trace='not available in official reader'))
