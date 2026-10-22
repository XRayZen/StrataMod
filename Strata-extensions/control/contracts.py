"""T01 offline descriptor contracts, not an owner or activation authority.

Future providers pass launch snapshots to the existing official manager. These
pure functions do not read/write state, hash assets, start, stop or adopt owners.
"""
import re
import math

SOURCE_REVISIONS = {
    'strata': '477ac13cbe8e582c20484871ce459d20d82df09d',
    'mmnga': 'd4c07dde710cd009c47f36a8d002ff938b0eef67',
    'maya': '8d9a9b5d705049a87da853717cdc59440252de30',
    'lucebox': '81940128d118f4d2bc0070e4c772542938c7a5c3',
    'gguf': 'f924b94f19c1fea02c06a65c8475b0a45e2b88b1',
    'official_model': '1bae0e1088993b9b82de08f59de5be5a34e42170',
    'deepinfer': '774ce244b87cc0eb8d4b94ab9f5de2ab22049f01',
    'recipe': '935817c66f5d6e64838f419692545f06787e485f',
}
LAUNCH_FIELDS = ('bundle_id', 'tokenizer_identity', 'asset_revision',
                 'profile_snapshot', 'runtime_epoch', 'placement')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_contract(data):
    """Validate this planned contract version; this is not asset qualification."""
    require(isinstance(data, dict), 'descriptor must be an object')
    require(type(data.get('schema_version')) is int and data['schema_version'] == 1, 'unsupported schema')
    model = data.get('model', {})
    require(model == {
        'family': 'deepseek41', 'model_id': 'deepseek-v4.1-flash-1017-ud-q4_k_xl',
        'variant': 'UD-Q4_K_XL', 'revision': SOURCE_REVISIONS['gguf'],
        'shards': 9, 'planned_bytes': 500707576573,
        'quant_policy': 'preserve-source-native-types',
        'quant_dispatch': 'verified-block-layout-not-q4-label',
        'tokenizer_family': 'deepseek41', 'qwen_ple': False, 'shared_qwen_mtp': False,
    }, 'model family, asset or native quant contract mismatch')
    sources = data.get('sources', {})
    require(isinstance(sources, dict) and set(sources) == set(SOURCE_REVISIONS), 'fixed source set mismatch')
    for name, revision in SOURCE_REVISIONS.items():
        row = sources[name]
        require(isinstance(row, dict) and row.get('revision') == revision, f'{name}: fixed revision mismatch')
        require(row.get('adoption') == 'reference-only', f'{name}: adoption is not verified by T01')
        require(row.get('notice_status') == 'pending-before-code-adoption', f'{name}: notice not collected')
        require(isinstance(row.get('boundary'), str) and bool(row['boundary']), f'{name}: missing boundary')
    require(sources['maya'].get('license') == 'MIT', 'Maya notice contract')
    require(sources['lucebox'].get('license') == 'Apache-2.0', 'LuceBox notice contract')
    require(sources['deepinfer'].get('license') == 'Apache-2.0', 'DeepInfer notice contract')
    require(sources['recipe'].get('license') == 'MIT', 'Recipe notice contract')
    require(sources['recipe'].get('additional_notices') == ['tokenizer-separate-notice'], 'tokenizer notice contract')
    require(data.get('evidence') == {
        'header_inventory': 'pending-T03', 'native_layouts': 'pending-T03',
        'tokenizer_identity': 'pending-T03', 'native_build': 'pending-T06',
        'runtime': 'not-executed',
    }, 'planned metadata must not claim implementation evidence')
    require(data.get('owned_root') == 'C:/Develop/AI/Strata-extensions', 'owned deployment root mismatch')
    require(data.get('upstream_hooks') == ['cmake-backend-target', 'engine-family-dispatch',
                                         'serve-family-factory', 'official-manager-descriptor'], 'hook boundary mismatch')
    require(data.get('owner_integration') == {
        'authority': 'existing-official-manager', 'new_registry': False,
        'normal_start_receipt_required': False, 'legacy_plain_registration': 'preserved',
        'existing_source_and_process_guards': 'preserved',
    }, 'owner integration must preserve existing authority and guards')


def validate_placement(row):
    """Check logical roles only; hardware capability remains T21/T44/T45."""
    require(isinstance(row, dict), 'placement must be an object')
    mode = row.get('mode')
    require(mode in ('single', 'cache-only', 'expert-assist', 'layer-split'), 'unknown execution mode')
    require(isinstance(row.get('primary'), str) and bool(row['primary']), 'primary identity missing')
    secondary = row.get('secondary')
    allowed = {'mode', 'primary', 'secondary'}
    if mode == 'single':
        require(secondary is None, 'single mode cannot assign secondary')
    else:
        require(isinstance(secondary, str) and bool(secondary) and secondary != row['primary'], 'distinct secondary required')
    if mode == 'expert-assist':
        allowed.add('assignment')
        assignment = row.get('assignment')
        require(isinstance(assignment, list) and bool(assignment), 'secondary expert assignment required')
        require(all(type(expert) is int and 0 <= expert < 384 for expert in assignment), 'expert id outside model range')
        require(len(set(assignment)) == len(assignment), 'duplicate expert assignment')
    if mode == 'layer-split':
        allowed.update(('cut', 'head'))
        require(type(row.get('cut')) is int and 0 < row['cut'] < 40, 'cut must form two nonempty contiguous ranges')
        require(row.get('head') == 'secondary', 'head follows final contiguous range')
    require(set(row) == allowed, 'fields incompatible with execution mode')


def same_launch(expected, observed):
    """Compare immutable launch bindings; transfer-path observations are dynamic.

    Callers retain PID/create-time/exe/cohort/listener and handshake checks in
    the existing manager. This comparison alone grants no process authority.
    """
    for row in (expected, observed):
        if not isinstance(row, dict):
            return False
        if not all(isinstance(row.get(key), str) and bool(row[key]) for key in LAUNCH_FIELDS[:-1]):
            return False
        if not re.fullmatch('[0-9a-f]{40}', row['asset_revision']):
            return False
        if not re.fullmatch('[0-9a-f]{64}', row['profile_snapshot']):
            return False
        try:
            validate_placement(row.get('placement'))
        except ValueError:
            return False
    return all(expected[key] == observed[key] for key in LAUNCH_FIELDS)


# These are existing production producer options, not trial budgets or presets.
ROUTING_KEYS=('routing_primary_bonus','routing_secondary_bonus','routing_ssd_penalty')
NATIVE_FEATURE_KEYS=ROUTING_KEYS+('projection_graph','dspark_draft','dspark_prefix','dspark_width','dspark_draft_credit','dspark_target_credit')
PERFORMANCE_KEYS=('tile_bytes','tile_rows','active_batch')

def native_feature_args(config):
    from pathlib import Path
    args=[]
    for key in NATIVE_FEATURE_KEYS:
        if key not in config:continue
        value=config[key]
        if key in ROUTING_KEYS:
            require(type(value)in(int,float) and math.isfinite(value) and 0<=value<=1,'finite routing coefficient [0,1]: '+key)
            if value==0:value=0 # signed zero follows the native exact policy.
        elif key=='projection_graph':
            require(type(value)is str and value in ('off','on'),'projection_graph must be off or on')
        elif key in ('dspark_draft','dspark_prefix'):
            require(type(value)is str and bool(value) and '\0'not in value and Path(value).is_absolute(),'DSpark absolute '+key)
        else:
            require(type(value)is int and 0<value<2**64,'positive uint64 '+key)
        flag='--'+key.replace('_','-')
        require(flag not in (config.get('args')or[]),'duplicate typed/native argument '+flag)
        args.extend((flag,str(value)))
    draft=config.get('dspark_draft')
    if draft:
        require(bool(config.get('dspark_prefix')),'DSpark prefix required with draft')
    else:
        require(not any(key in config for key in ('dspark_prefix','dspark_draft_credit','dspark_target_credit')),'DSpark configuration without draft')
    for key in PERFORMANCE_KEYS:
        if key in config:require(type(config[key])is int and 0<config[key]<2**64,'positive uint64 '+key)
    return args
