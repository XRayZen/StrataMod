"""One reviewed amdVision native revision; source-only and full verification stay separate."""
import copy
from pathlib import Path
import time

from . import manifest as m

PARENT=m.LOCAL/'normal/installations/1792384046493473800/receipt.json'
PARENT_SHA='4c4d829133124e4f5882092c62338c14f3aa5eec64ecb686946ced6d65717211'
SOURCE_DELTA={str(m.ROOT/name) for name in ('local_runtime/normal_runtime.py',
             'local_runtime/image_phase.py','local_runtime/amd_vision_revision.py')}


def parent(n):
    # This saved authority is verified directly. Its old source is deliberately
    # not compared with the new running reader during the preparation boundary.
    n.no_links(PARENT);n.no_links(n.FULL_BASE)
    if n.m.digest(PARENT)!=PARENT_SHA:
        raise RuntimeError('Reviewed Python-stage parent receipt changed')
    value=n.m.read_json(PARENT);base=n.revision_base()
    if value.get('full_verification_origin')!=dict(path=str(n.FULL_BASE),sha256=n.FULL_BASE_SHA):
        raise RuntimeError('Native revision full-proof lineage changed')
    for key in ('kind','assets','references','full_content_verification_at'):
        if value.get(key)!=base.get(key):raise RuntimeError('Native parent full proof changed: '+key)
    n.no_links(Path(value['profile']))
    if n.m.digest(value['profile'])!=value['profile_sha256']:
        raise RuntimeError('Reviewed parent profile changed')
    return value


def expected_assets(n,base,build):
    assets=copy.deepcopy(base['assets'])
    for name,row in build['changed_assets'].items():
        if assets.get(name)!=row['before']:
            raise RuntimeError('Native changed-input parent identity differs')
        assets[name]=copy.deepcopy(row['after'])
    if set(build['added_assets'])&set(base['assets']):
        raise RuntimeError('New native closure overlaps an inherited asset')
    assets.update(copy.deepcopy(build['added_assets']))
    path=str(n.image.M3_BUILD)
    if path in assets:raise RuntimeError('Native build evidence is self-referential')
    assets[path]=dict(sha256=n.image.M3_BUILD_SHA,metadata=n.metadata(path))
    return assets


def authority(n):
    return dict(version=1,parent=dict(path=str(PARENT),sha256=PARENT_SHA),
                build=dict(path=str(n.image.M3_BUILD),sha256=n.image.M3_BUILD_SHA))


def validate(n,value):
    base=parent(n);build=n.image.m3_native_manifest()
    if value.get('native_revision')!=authority(n):raise RuntimeError('Native revision authority changed')
    if value.get('sources')!=n.source_files():raise RuntimeError('Native revision source changed')
    changed={p for p in set(base['sources'])|set(value['sources']) if base['sources'].get(p)!=value['sources'].get(p)}
    if changed!=SOURCE_DELTA:raise RuntimeError('Native revision contains an unapproved source delta')
    if value.get('full_verification_origin')!=base['full_verification_origin']:
        raise RuntimeError('Native revision original full proof changed')
    for key in ('kind','references','full_content_verification_at'):
        if value.get(key)!=base.get(key):raise RuntimeError('Native revision inherited proof changed: '+key)
    if value.get('assets')!=expected_assets(n,base,build):
        raise RuntimeError('Native revision finite asset inventory changed')
    path=n.m.local_path(Path(value['profile']))
    if n.m.digest(path)!=value['profile_sha256'] or n.m.read_json(path)!=n.profile(path.parent):
        raise RuntimeError('Native revision profile changed')
    if value.get('assets_full_sha_read_this_revision') is not False:
        raise RuntimeError('Native revision must not claim a new full model pass')
    if set(value['assets'])!={str(p) for p in n.dependencies(n.m.read_json(path))}:
        raise RuntimeError('Native revision dependency closure changed')


def prepare(n):
    """Internal, one fixed native revision. Does not publish or activate."""
    with n.runner.shared_operation():
        n.runner.production_inactive()
        base=parent(n);build=n.image.m3_native_manifest();n.references()
        # Model and unchanged SDK bodies are never read here. Original hash
        # evidence is inherited only after current no-reparse metadata matches.
        for name,row in base['assets'].items():
            if name not in build['changed_assets']:n.check_metadata(name,row['metadata'])
        assets=expected_assets(n,base,build)
        changed=set(build['changed_assets'])|set(build['added_assets'])|{str(n.image.M3_BUILD)}
        for name in changed:
            row=assets[name];n.check_metadata(name,row['metadata'])
            if n.m.digest(name)!=row['sha256']:raise RuntimeError('New native artifact changed: '+name)
            n.check_metadata(name,row['metadata'])
        directory=n.HOME/'installations'/str(time.time_ns());directory.mkdir(parents=True)
        path=directory/'profile.json';n.write(path,n.profile(directory))
        value=copy.deepcopy(base)
        value.update(profile=str(path),profile_sha256=n.m.digest(path),sources=n.source_files(),assets=assets,
                     native_revision=authority(n),native_verified_at=time.time(),
                     assets_full_sha_read_this_revision=False,source_revision_at=time.time())
        validate(n,value)
        receipt=directory/'receipt.json';n.write(receipt,value)
        if n.m.read_json(receipt)!=value:raise RuntimeError('Native receipt persistence readback changed')
        return dict(receipt=str(receipt),sha256=n.m.digest(receipt),activated=False,
                    inherited_full_asset_sha=True,new_full_asset_passes=0,
                    native_artifact_hashes=len(changed))
