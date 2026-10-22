"""Pure normal-family launch values. Import never registers or starts anything."""
import copy
import hashlib
import json
import math
import os
import re
from pathlib import Path
import uuid

ABI = 'strata-deepseek-launch/v1'
FAMILY = 'deepseek41'


def helper_path(data_root):
    return Path(data_root).parent / 'Strata-extensions/control/deepseek_launch.py'


def canonical_attempt(value):
    if type(value) is not str or str(uuid.UUID(value)) != value:
        raise ValueError('Noncanonical launch attempt UUID')
    return value


def positive_epoch(value):
    if type(value) is not int or not 0 < value < 2**64:
        raise ValueError('Native runtime epoch must be a positive uint64')
    return value


def current_identity(pid=None):
    import psutil
    process=psutil.Process(os.getpid() if pid is None else pid)
    return dict(pid=process.pid,created=process.create_time(),exe=process.exe())


def verify_parent(binding):
    expected=binding.get('parent')
    actual=current_identity(os.getppid())
    if (type(expected) is not dict or type(expected.get('pid')) is not int
            or expected['pid']!=actual['pid'] or type(expected.get('created')) not in (int,float)
            or not math.isfinite(expected['created']) or abs(expected['created']-actual['created'])>=.00001
            or Path(expected.get('exe','')).resolve()!=Path(actual['exe']).resolve()):
        raise RuntimeError('Actual bootstrap parent identity mismatch')
    return actual


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execution_defaults(value):
    if type(value)is not dict or set(value)!={'devices','assignment','cut'}:
        raise ValueError('Execution defaults declaration')
    devices=value['devices']
    if type(devices)is not list or len(devices)!=2 or not all(type(v)is str and re.fullmatch(r'[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]',v)for v in devices)or len(set(devices))!=2:
        raise ValueError('Execution default PCI pair')
    path=Path(__file__).with_name('contracts.py');namespace={'__file__':str(path),'__name__':'strata_defaults_contract'}
    exec(compile(path.read_bytes(),str(path),'exec'),namespace)
    namespace['validate_placement'](dict(mode='expert-assist',primary=devices[0],secondary=devices[1],assignment=value['assignment']))
    namespace['validate_placement'](dict(mode='layer-split',primary=devices[0],secondary=devices[1],cut=value['cut'],head='secondary'))
    return copy.deepcopy(value)


def execution_capability(cfg):
    """Selected package declaration, bound to its exact native-args hook body."""
    package=cfg.get('runtime_package')
    if package is None:return False
    if type(package)is not dict or set(package)!={'id','manifest'}:raise ValueError('Execution package declaration')
    manifest=Path(package['manifest']).resolve();root=manifest.parent.parent
    value=json.loads(manifest.read_text(encoding='utf-8-sig'))
    if root.name!=package['id']or value.get('id')!=package['id']or value.get('schema')!='strata-t29-runtime-package/v1':raise ValueError('Execution package identity')
    hook=root/'Strata-extensions/models/deepseek41/server_hooks.py'
    rows=[r for r in value.get('files',[])if Path(r.get('path','')).resolve()==hook.resolve()]
    if len(rows)!=1 or type(rows[0].get('bytes'))is not int or hook.stat().st_size!=rows[0]['bytes']or digest(hook)!=rows[0].get('sha256'):raise ValueError('Selected native-args hook binding')
    extension=value.get('execution_extension')
    if extension is None:return False
    if type(extension)is not dict or extension.get('abi')!='strata-deepseek-execution/v1':raise ValueError('Unknown execution capability')
    return True


def overlay(profile, options=None):
    if profile.get('family') != FAMILY:
        raise ValueError('Wrong launch family')
    cfg = copy.deepcopy(profile)
    placement_keys = {'mode','secondary_pci','assignment','cut'}
    selected = {k:v for k,v in (options or {}).items() if k in placement_keys and v is not None}
    for key, value in (options or {}).items():
        if key in ('routing_primary_bonus','routing_secondary_bonus','routing_ssd_penalty')and value is None:raise ValueError('routing coefficient must be finite [0,1]')
        if value is None:
            continue
        if key in ('device_cache_payload_bytes', 'ram_cache_payload_bytes','secondary_device_cache_payload_bytes'):
            if value != 'auto' and (type(value) is not int or value <= 0):
                raise ValueError('Cache payload must be auto or positive bytes')
            cfg.setdefault('cache_budget', {})[key] = value
        elif key in ('auto_cache_fraction', 'auto_row_fraction'):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError('Auto fraction must be finite [0,1]')
            cfg[key] = value
        elif key == 'primary_pci':
            if type(value) is not str or not value:
                raise ValueError('Primary PCI must be explicit')
            cfg[key] = value
            if cfg.get('placement'):
                cfg['placement']['primary'] = value
                if not selected and cfg['placement'].get('secondary') == value:
                    raise ValueError('Primary and secondary device must differ')
        elif key in ('projection_graph','dspark_draft','dspark_prefix','dspark_width','dspark_draft_credit','dspark_target_credit','tile_bytes','tile_rows','active_batch','routing_primary_bonus','routing_secondary_bonus','routing_ssd_penalty'):
            cfg[key]=copy.deepcopy(value)
        elif key in placement_keys:
            pass  # Apply the complete placement after all generic overrides.
        else:
            raise ValueError('Unknown launch overlay: ' + key)
    if selected:
        prior = cfg.get('placement',{})
        defaults = execution_defaults(cfg['execution_defaults']) if 'execution_defaults'in cfg else {}
        mode = selected.get('mode',prior.get('mode','single'))
        secondary = prior.get('secondary')
        if secondary is None or secondary==cfg['primary_pci']:
            devices=defaults.get('devices',[])
            secondary=next((v for v in devices if v!=cfg['primary_pci']),None)if cfg['primary_pci']in devices else None
        secondary=selected.get('secondary_pci',secondary)
        placement = dict(mode=mode,primary=cfg['primary_pci'],secondary=None if mode=='single'else secondary)
        if mode=='expert-assist':
            assignment=prior.get('assignment')if prior.get('mode')=='expert-assist'else None
            placement['assignment']=copy.deepcopy(selected.get('assignment',assignment if assignment is not None else defaults.get('assignment')))
        elif mode=='layer-split':
            cut=prior.get('cut')if prior.get('mode')=='layer-split'else None
            placement.update(cut=selected.get('cut',cut if cut is not None else defaults.get('cut')),head='secondary')
        if 'assignment'in selected and mode!='expert-assist' or 'cut'in selected and mode!='layer-split':
            raise ValueError('Placement option belongs to another mode')
        if mode=='single'and selected.get('secondary_pci')is not None:
            raise ValueError('Single mode does not assign secondary')
        path=Path(__file__).with_name('contracts.py');namespace={'__file__':str(path),'__name__':'strata_existing_placement_contract'}
        exec(compile(path.read_bytes(),str(path),'exec'),namespace)
        namespace['validate_placement'](placement)
        if cfg.get('runtime_package')and placement['mode']!='single'and not execution_capability(cfg):
            raise ValueError('Selected package does not declare this execution mode')
        cfg['placement']=placement
        if 'secondary'in cfg:cfg['secondary']=placement['secondary']
    path=Path(__file__).with_name('contracts.py');namespace={'__file__':str(path),'__name__':'strata_native_features'}
    exec(compile(path.read_bytes(),str(path),'exec'),namespace)
    namespace['native_feature_args'](cfg)
    return cfg


def server_command(cfg, config):
    return [cfg['python'], '-E', '-s', '-B', '-X', 'utf8', cfg['server_entry'],
            '--config', str(config), '--engine', 'strata', '--port', str(cfg.get('port', 18080))]


def native_command(cfg):
    """Expected existing adapter argv, used only for exact child ownership checks."""
    # Base StrataEngine prepends --serve; the fixed family adapter also emits it.
    # Bind the actual existing argv rather than silently changing that adapter.
    args = [cfg['exe'], '--serve', '--serve']
    for flag, value in (('artifact-root', cfg['artifact_root']), ('primary-pci', cfg['primary_pci']),
                        ('context', cfg['context']), ('bundle-id', cfg['bundle_id']),
                        ('runtime-epoch', cfg['runtime_epoch'])):
        args += ['--' + flag, str(value)]
    placement=cfg.get('placement')
    if placement is not None:
        path=Path(__file__).with_name('contracts.py');namespace={'__file__':str(path),'__name__':'strata_native_placement_contract'}
        exec(compile(path.read_bytes(),str(path),'exec'),namespace);namespace['validate_placement'](placement)
        if placement['primary']!=cfg['primary_pci']or('secondary'in cfg and placement['secondary']!=cfg['secondary']):
            raise ValueError('Native ownership placement PCI mismatch')
        capable=execution_capability(cfg)
        if not capable and placement['mode']!='single':raise ValueError('Selected package does not declare this execution mode')
        if capable:
            args += ['--mode',placement['mode']]
            if placement['secondary']is not None:args += ['--secondary-pci',placement['secondary']]
            if placement['mode']=='expert-assist':args += ['--secondary-experts',','.join(str(value)for value in placement['assignment'])]
            if placement['mode']=='layer-split':args += ['--layer-cut',str(placement['cut'])]
    for index, path in enumerate(cfg['native_paths'], 1):
        args += ['--source' + str(index), str(path)]
    for key, value in cfg.get('cache_budget', {}).items():
        args += ['--' + key.replace('_', '-'), str(value)]
    for key in ('auto_cache_fraction', 'auto_row_fraction', 'tile_bytes', 'tile_rows', 'active_batch'):
        if key in cfg:
            args += ['--' + key.replace('_', '-'), str(cfg[key])]
    path=Path(__file__).with_name('contracts.py');namespace={'__file__':str(path),'__name__':'strata_native_features'}
    exec(compile(path.read_bytes(),str(path),'exec'),namespace)
    return args + namespace['native_feature_args'](cfg) + list(cfg.get('args') or [])


def validate_feature_info(cfg, info):
    # Missing/dynamic per-role observations remain unknown, not startup gates.
    if 'projection_graph'in cfg and 'projection_graph'in info:
        graph=info['projection_graph']
        if type(graph)is not dict or type(graph.get('requested'))is not bool or graph['requested']!=(cfg['projection_graph']=='on'):
            raise RuntimeError('Native INFO projection graph request mismatch')
    if cfg.get('dspark_draft'):
        for key,expected in (('dspark_enabled',True),('dspark_width',cfg.get('dspark_width',5))):
            if key in info and (type(info[key])is not type(expected)or info[key]!=expected):
                raise RuntimeError('Native INFO DSpark request mismatch: '+key)
        for key in ('dspark_draft_credit','dspark_target_credit'):
            if key in cfg and key in info and (type(info[key])is not int or info[key]!=cfg[key]):
                raise RuntimeError('Native INFO DSpark credit mismatch: '+key)
    return dict(info)


def validate_ready_info(cfg, info):
    """Observe native INFO fields; identity absent from INFO stays argv-bound."""
    if type(info) is not dict or info.get('family') != FAMILY or type(info.get('context')) is not int or info['context'] != cfg['context']:
        raise RuntimeError('Native INFO family/context mismatch')
    validate_feature_info(cfg,info)
    mode=cfg.get('placement',{}).get('mode','single')
    compute=mode in ('expert-assist','layer-split') and execution_capability(cfg)
    for key in ('device_slots','ram_slots',
                'device_cache_payload_bytes','ram_cache_payload_bytes'):
        if type(info.get(key)) is not int or info[key] <= 0:
            raise RuntimeError('Native INFO capacity unavailable: '+key)
    primary_row=not compute or mode=='expert-assist' or cfg['placement']['cut']>1
    for key in ('row_device_slots','row_ram_slots'):
        if type(info.get(key))is not int or (info[key]<=0 if primary_row else info[key]!=0):
            raise RuntimeError('Native INFO primary Row capacity mismatch: '+key)
    for key in ('device_cache_payload_bytes','ram_cache_payload_bytes'):
        declared=cfg.get('cache_budget',{}).get(key,'auto')
        expected=None if declared=='auto' else declared
        observed=info.get('declared_'+key)
        if 'declared_'+key not in info or observed != expected or (expected is not None and type(observed) is not int):
            raise RuntimeError('Native INFO declared budget mismatch: '+key)
        if expected is not None and info[key] > expected:
            raise RuntimeError('Native INFO payload exceeds declared budget: '+key)
    for key,default in (('auto_cache_fraction',.5),('auto_row_fraction',1/64)):
        if type(info.get(key)) not in (int,float) or info[key] != cfg.get(key,default):
            raise RuntimeError('Native INFO auto fraction mismatch: '+key)
    if compute:
        placement=cfg['placement'];secondary_row=mode=='layer-split' and placement['cut']<=14
        expected=dict(configured_mode=mode,effective_mode=mode,primary_pci=placement['primary'],requested_secondary_pci=placement['secondary'],actual_secondary_pci=placement['secondary'],secondary_experts=placement['assignment']if mode=='expert-assist'else None,layer_cut=placement['cut']if mode=='layer-split'else None,head_role='primary'if mode=='expert-assist'else'secondary')
        for key,value in expected.items():
            actual=info.get(key)
            if key not in info or type(actual)is not type(value)or actual!=value or (type(value)is list and any(type(x)is not int for x in actual)):
                raise RuntimeError('Native INFO execution role mismatch: '+key)
        for key in ('secondary_device_slots','secondary_ram_slots'):
            if type(info.get(key))is not int or info[key]<=0:raise RuntimeError('Native INFO secondary capacity unavailable: '+key)
        for key in ('secondary_row_device_slots','secondary_row_ram_slots'):
            if type(info.get(key))is not int or (info[key]<=0 if secondary_row else info[key]!=0):raise RuntimeError('Native INFO secondary Row capacity mismatch: '+key)
        def uint(key):
            value=info.get(key)
            if type(value)is not int or not 0<=value<2**64:raise RuntimeError('Native INFO accounting unavailable: '+key)
            return value
        weight=uint('weight_tile_bytes')
        if weight!=cfg.get('tile_bytes',2097152):raise RuntimeError('Native INFO tile size mismatch')
        minimum=2*weight+264*(int(primary_row)+int(secondary_row))
        p=uint('mode_primary_ram_payload_bytes');s=uint('mode_secondary_ram_payload_bytes');total=uint('mode_ram_target_bytes')
        if p!=info['ram_slots']*weight+info['row_ram_slots']*264 or s!=info['secondary_ram_slots']*weight+info['secondary_row_ram_slots']*264 or uint('ram_cache_payload_bytes')!=p+s:
            raise RuntimeError('Native INFO all-role RAM alias mismatch')
        if uint('mode_ram_minimum_payload_bytes')!=minimum or uint('working_minimum_payload_bytes')!=minimum or total!=p+s+uint('mode_ram_unused_bytes')or uint('mode_ram_extra_primary_bytes')+uint('mode_ram_extra_secondary_bytes')+minimum!=total:
            raise RuntimeError('Native INFO RAM total counted more than once or minimum mismatch')
        declared=cfg.get('cache_budget',{}).get('ram_cache_payload_bytes','auto')
        if declared!='auto'and total!=declared:raise RuntimeError('Native INFO all-role declared RAM target mismatch')
        if uint('actual_device_owned')!=uint('actual_primary_device_owned')or uint('actual_all_role_device_owned')!=uint('actual_primary_device_owned')+uint('actual_secondary_device_owned'):
            raise RuntimeError('Native INFO device role alias mismatch')
    return dict(info)


def resolve(source, data_root, attempt, epoch, options=None, registered=None):
    source = Path(source).resolve()
    canonical_attempt(attempt)
    positive_epoch(epoch)
    source_hash = digest(source)
    cfg = overlay(json.loads(source.read_text(encoding='utf-8-sig')), options)
    context = cfg.get('context')
    if type(context) is not int or not 0 < context <= 1048576:
        raise ValueError('Invalid DeepSeek context')
    cfg['runtime_epoch'] = epoch
    target = Path(data_root) / 'records' / ('launch-' + attempt) / f"strata-{cfg['model_name']}-{context}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation: an attempt never overwrites a previously selected config.
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(cfg, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    if digest(source) != source_hash:
        raise RuntimeError('Saved profile changed during launch resolution')
    binding = dict(abi=ABI, attempt=attempt, runtime_epoch=epoch,
                   parent=current_identity(),
                   source_config=str(source), source_sha256=source_hash,
                   registered_config=str(registered) if registered else None,
                   config=str(target.resolve()), config_sha256=digest(target),
                   runtime_package=copy.deepcopy(cfg.get('runtime_package')),
                   bundle_id=cfg.get('bundle_id'), command=server_command(cfg, target))
    binding['helpers'] = [{'path': str(path.resolve()), 'sha256': digest(path)} for path in
                          (Path(__file__), Path(__file__).with_name('deepseek_bootstrap.py'))]
    with target.with_suffix('.launch.json').open('x', encoding='utf-8') as stream:
        json.dump(binding, stream, indent=2, allow_nan=False)
        stream.write('\n')
    return target, binding


def verify_binding(config, binding):
    path = Path(config).resolve()
    if binding.get('abi') != ABI or str(path) != binding.get('config') or digest(path) != binding.get('config_sha256'):
        raise RuntimeError('Resolved launch config binding mismatch')
    expected_helpers = (Path(__file__).resolve(), Path(__file__).with_name('deepseek_bootstrap.py').resolve())
    rows = binding.get('helpers', [])
    if len(rows) != 2 or any(Path(row['path']).resolve() != expected or digest(expected) != row['sha256']
                             for row, expected in zip(rows, expected_helpers)):
        raise RuntimeError('Selected family helper version changed')
    canonical_attempt(binding['attempt'])
    cfg = json.loads(path.read_text(encoding='utf-8-sig'))
    if cfg.get('family') != FAMILY or cfg.get('runtime_epoch') != positive_epoch(binding['runtime_epoch']):
        raise RuntimeError('Resolved launch family/epoch mismatch')
    if server_command(cfg, path) != binding['command']:
        raise RuntimeError('Selected launch command mismatch')
    return cfg
