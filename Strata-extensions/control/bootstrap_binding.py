"""Pure T24 fixture launch binding; no registration or runtime authority."""
import hashlib
import json
import math
from pathlib import Path
import uuid

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def identity(value):
    if not isinstance(value,dict) or type(value.get('pid')) is not int or value['pid']<=0:raise ValueError('invalid parent PID')
    if type(value.get('created')) not in (int,float) or not math.isfinite(value['created']):raise ValueError('invalid birth')
    if not isinstance(value.get('exe'),str) or not value['exe']:raise ValueError('invalid executable')
    return {k:value[k] for k in ('pid','created','exe')}
def validate_target(target):
    if not isinstance(target,dict):raise ValueError('target object required')
    for key in ('context','runtime_epoch'):
        if type(target.get(key)) is not int or target[key]<1:raise ValueError('invalid '+key)
    for key in ('model_id','asset_revision','bundle_id','tokenizer_identity','binary','profile','cwd'):
        if not isinstance(target.get(key),str) or not target[key]:raise ValueError('invalid '+key)
    for key,length in [('bundle_id',64),('tokenizer_identity',64),('asset_revision',40)]:
        value=target[key]
        if len(value)!=length or any(c not in '0123456789abcdef' for c in value):raise ValueError('invalid '+key)
    argv=target.get('argv')
    if not isinstance(argv,list) or not argv or any(not isinstance(x,str) for x in argv) or argv[0]!=target['binary']:raise ValueError('invalid argv')
    placement=target.get('placement')
    if not isinstance(placement,dict) or placement.get('mode')!='single' or not isinstance(placement.get('primary'),str) or not placement['primary'] or placement.get('secondary') is not None:raise ValueError('fixture placement')
def freeze_launch(target,attempt,parent):
    validate_target(target);uuid.UUID(attempt)
    row=json.loads(canonical(target));row['binary_sha256']=digest(row['binary']);row['profile_sha256']=digest(row['profile'])
    snapshot=dict(schema='strata-t24-fixture-launch/v1',attempt=attempt,target=row,parent=identity(parent))
    snapshot['snapshot_id']=hashlib.sha256(canonical(snapshot)).hexdigest();return snapshot

def require_target_unchanged(snapshot):
    if not isinstance(snapshot,dict) or snapshot.get('schema')!='strata-t24-fixture-launch/v1':raise ValueError('snapshot schema')
    try:uuid.UUID(snapshot['attempt'])
    except (KeyError,TypeError,ValueError) as e:raise ValueError('attempt') from e
    identity(snapshot.get('parent'));validate_target(snapshot.get('target'))
    body={k:v for k,v in snapshot.items() if k!='snapshot_id'}
    if hashlib.sha256(canonical(body)).hexdigest()!=snapshot.get('snapshot_id'):raise ValueError('snapshot digest')
    for key in ('binary','profile'):
        if digest(snapshot['target'][key])!=snapshot['target'].get(key+'_sha256'):raise ValueError('target changed: '+key)
    return snapshot

def verify_bootstrap(snapshot,observed_argv,parent_identities):
    require_target_unchanged(snapshot)
    if canonical(observed_argv)!=canonical(snapshot['target']['argv']):raise ValueError('bootstrap argv changed')
    expected=identity(snapshot['parent'])
    if not any(canonical(identity(p))==canonical(expected) for p in parent_identities):raise ValueError('bootstrap parent unconfirmed')
    return snapshot['snapshot_id']
