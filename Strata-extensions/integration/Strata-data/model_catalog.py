"""External variant catalog. Asset readiness is separate from GPU/vision validation."""
import hashlib
import types
from profile_defaults import approved_hashes
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent
CONTEXTS = (4096, 32768, 131072, 262144)
CATALOG = {
    'huihui-ud-q4_k_xl_v2': dict(label='Huihui Abliterated v2 UD-Q4_K_XL', prefix='Qwen3.8-Flash-Next-UD-Q4_K_XL', shards=4, ple_shard=2, receipt='huihui-ud-q4_k_xl_v2', revision='1130c24fabf6eacffe701306ebd16c7b04a9f942', supported=True, selectable=True, compat=True, require_pack_receipt=False, ple_io='mmap', public_contexts=(262144,)),
    'deepseek-v4.1-flash-1017-ud-q4_k_xl': dict(label='DeepSeek V4.1 Flash 1017 UD-Q4_K_XL', family='deepseek41', prefix='DeepSeek-V4.1-Flash-1017-UD-Q4_K_XL', shards=9, ple_shard=None, revision='f924b94f19c1fea02c06a65c8475b0a45e2b88b1', supported=True, selectable=True, public_contexts=(4096,32768,131072,262144,524288,1048576), max_context=1048576, default_context=262144),
}
ALIASES = {name: name for name, item in CATALOG.items() if item.get('selectable', True)}
SHARDS = {
    'huihui-ud-q4_k_xl_v2': [(10946624, '4448186216b3af4cc558bbce2c3213f01608f8f8b2e5267a9767971dd3ec8082'), (49859583136, 'ab283aba22daee321944dad65b09180810140fc75502c0791200cf01b85f9c75'), (49376141504, '2a8d2e69ba47fef6b42c953c07a24b5d4c59c1c2cdc89b2bc17e13e000a62fa0'), (12087983520, '0d626450754c554235f93653b8f7c874c7c2d35380b9efab5b0852d616b84702')],
}
PACK_FILES = ('dense.bin', 'index.txt', 'native_experts.txt', 'tokenizer/vocab.json', 'tokenizer/merges.txt', 'tokenizer/tokenizer.json', 'tokenizer/chat_template.jinja', 'tokenizer/token_type.json')


def _deepseek(model):
    return CATALOG.get(model, {}).get('family') == 'deepseek41'


def _family_provider(root):
    # Installed owned provider only; a development checkout is never silently
    # connected to ordinary runtime profiles. exec avoids import/pyc writes.
    path = root.parent / 'Strata-extensions' / 'control' / 'providers' / 'deepseek41.py'
    if not path.is_file():
        raise RuntimeError('DeepSeek family provider未配備: ' + str(path))
    module = types.ModuleType('strata_deepseek_profile_provider')
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def _family_profile(model, root, context=None):
    provider = _family_provider(root)
    if context is not None:
        require_public_context(model, context, root)
        path = root / 'profiles' / f'{model}-{context}.json'
        return provider.validate_profile(json.loads(path.read_text(encoding='utf-8-sig')), context)
    # Asset-only callers have no selected context. Use an existing valid family
    # profile, preferring the established default if present, never requiring it.
    candidates = list((root / 'profiles').glob(f'{model}-*.json'))
    default = root / 'profiles' / f"{model}-{CATALOG[model]['default_context']}.json"
    candidates.sort(key=lambda p: (p != default, p.name))
    errors = []
    for path in candidates:
        try:
            selected_context = int(path.stem[len(model) + 1:])
            require_public_context(model, selected_context, root)
            cfg = json.loads(path.read_text(encoding='utf-8-sig'))
            return provider.validate_profile(cfg, selected_context)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            errors.append(str(error))
    raise RuntimeError('有効なDeepSeek profileがありません。再確認・再選択できます: ' + ('; '.join(errors) if errors else str(root / 'profiles' / f'{model}-*.json')))


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def public_contexts(model):
    return CATALOG[model].get('public_contexts', CONTEXTS)


def require_public_context(model, context, root=ROOT):
    if model not in CATALOG or not CATALOG[model].get('selectable', True):
        raise RuntimeError('選択可能なモデルではありません。')
    valid_context = type(context) is int and (0 < context <= CATALOG[model]['max_context'] if _deepseek(model) else context in public_contexts(model))
    if not valid_context:
        raise RuntimeError('選択可能なcontextではありません。')


def shard_path(model, index, root=ROOT, context=None):
    if _deepseek(model):
        if type(index) is not int or not 1 <= index <= 9:
            raise RuntimeError('native source index must be 1..9')
        return pathlib.Path(_family_profile(model, root, context)['native_paths'][index - 1])
    item = CATALOG[model]
    return root / model / f"{item['prefix']}-{index:05d}-of-{item['shards']:05d}.gguf"


def source_receipts(model, root=ROOT):
    if _deepseek(model):
        return []  # Existing model qualification stays caller-owned; no new normal receipt registry.
    item = CATALOG[model]
    return [root / 'records' / f"verified-{item['receipt']}-{i}.json" for i in range(1, item['shards'] + 1)]


def verify_sources(model, root=ROOT, context=None):
    if _deepseek(model):
        return _family_provider(root).assets(_family_profile(model, root, context))
    if model not in CATALOG:
        raise RuntimeError('選択可能なモデルではありません（取消済みの種類は起動しません）。')
    item = CATALOG[model]
    if not item['supported']:
        raise RuntimeError('このモデルは起動できません。')
    for i, (size, sha) in enumerate(SHARDS[model], 1):
        receipt = source_receipts(model, root)[i - 1]
        data = json.loads(receipt.read_text(encoding='utf-8-sig'))
        source = shard_path(model, i, root)
        revision, filename = data.get('revision'), data.get('filename')
        if (revision != item['revision'] or filename != source.name
                or data.get('size') != size or data.get('sha256') != sha
                or data.get('actual_sha256') != sha or source.stat().st_size != size
                or (root / data.get('destination', '')).resolve() != source.resolve()):
            raise RuntimeError('固定source receipt/size/SHAが一致しません: ' + str(receipt))


def pack_ready_receipt(model, root=ROOT, data=None):
    if data is None:
        data = json.loads((root / 'records' / f'ready-{model}.json').read_text(encoding='utf-8-sig'))
    if (data.get('model') != model or data.get('state') != 'ready'
            or type(data.get('pack_exit')) is not int or data['pack_exit'] != 0
            or data.get('revision') != CATALOG[model]['revision']
            or type(data.get('ple_shard')) is not int or data['ple_shard'] != source_ple_shard(model, root)):
        raise RuntimeError('ownpack準備完了receiptが一致しません。')
    files = data.get('files')
    if not isinstance(files, list):
        raise RuntimeError('ownpack manifestがありません。')
    expected = set(PACK_FILES) | {'compat-bf16.json'}
    indexed = {row.get('relative_path'): row for row in files if isinstance(row, dict)}
    if len(indexed) != len(files) or not expected.issubset(indexed):
        raise RuntimeError('owncompat/tokenizer manifestが不足しています。')
    # This small receipt is written only after one full SHA verification of every pack file.
    # Bind the ready marker to its exact contents and identity, rather than trusting stat alone.
    reference = data.get('pack_verification', {})
    relative = f'records/verified-pack-{model}.json'
    verification_path = root / relative
    if (not isinstance(reference, dict) or reference.get('relative_path') != relative
            or verification_path.resolve() != verification_path.absolute()
            or not re.fullmatch(r'[0-9a-f]{64}', reference.get('sha256', ''))):
        raise RuntimeError('pack SHA検証receiptが未確認または変更されています。')
    verification_bytes = verification_path.read_bytes()
    if hashlib.sha256(verification_bytes).hexdigest() != reference['sha256']:
        raise RuntimeError('pack SHA検証receiptの実SHAが一致しません。')
    verified = json.loads(verification_bytes.decode('utf-8-sig'))
    pack_root = root / 'packs' / model
    if (not isinstance(verified, dict) or verified.get('model') != model or verified.get('revision') != CATALOG[model]['revision']
            or verified.get('state') != 'sha256_verified'
            or not isinstance(reference.get('receipt_id'), str)
            or not re.fullmatch(r'[0-9a-f]{32}', reference['receipt_id'])
            or verified.get('receipt_id') != reference['receipt_id']
            or verified.get('pack_directory') != str(pack_root.absolute())
            or pack_root.resolve() != pack_root.absolute()):
        raise RuntimeError('pack SHA検証receiptのmodel/path/identityが一致しません。')
    verified_files = verified.get('files')
    if not isinstance(verified_files, list):
        raise RuntimeError('pack SHA検証file一覧がありません。')
    verified_index = {row.get('relative_path'): row for row in verified_files if isinstance(row, dict)}
    if len(verified_index) != len(verified_files) or set(verified_index) != expected:
        raise RuntimeError('pack SHA検証file一覧が一致しません。')
    for name in expected:
        row = indexed[name]
        proof = verified_index[name]
        path = pack_root / name
        before = path.stat()
        if (type(row.get('bytes')) is not int or row['bytes'] <= 0 or path.stat().st_size != row['bytes']
                or not re.fullmatch(r'[0-9a-f]{64}', row.get('sha256', ''))
                or proof.get('path') != str(path.absolute()) or path.resolve() != path.absolute()
                or proof.get('sha256') != row['sha256'] or proof.get('bytes') != row['bytes']
                or proof.get('sha256_verified') is not True
                or type(proof.get('mtime_ns')) is not int or proof['mtime_ns'] != before.st_mtime_ns):
            raise RuntimeError('ownpack file/path/size/検証receiptが不正です: ' + name)
        # dense.bin is ~1.5GB: retain its creation-time verified SHA plus exact stat binding.
        # Metadata/tokenizer files are hashed on each readiness check to catch same-size edits.
        if name != 'dense.bin' and file_sha256(path) != row['sha256']:
            raise RuntimeError('ownpack small file実SHAが一致しません: ' + name)
        after = path.stat()
        if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            raise RuntimeError('ownpack検査中にfileが変更されました: ' + name)
    return data


def source_ple_shard(model, root=ROOT):
    if _deepseek(model):
        return None
    item = CATALOG[model]
    if item['ple_shard'] is not None:
        return item['ple_shard']
    data = json.loads((root / 'records' / f'source-{model}.json').read_text(encoding='utf-8-sig'))
    ple = data.get('ple_shard')
    if (data.get('model') != model or data.get('revision') != item['revision']
            or type(ple) is not int or not 1 <= ple <= item['shards']
            or not isinstance(data.get('ple_tensor'), str) or not data['ple_tensor']):
        raise RuntimeError('実GGUF metadataで確認したPLE sourceがありません。')
    return ple


def validate_layout(cfg, model, context, ple_shard, root=ROOT):
    if _deepseek(model):
        return _family_provider(root).validate_profile(cfg, context)
    log = cfg.get('log')
    expected_log = root / 'logs' / f'{model}-{context}-engine.log'
    if (not isinstance(log, str) or not log or not pathlib.Path(log).is_absolute()
            or log != str(expected_log.absolute()) or pathlib.Path(log).resolve() != expected_log.absolute()
            or not expected_log.parent.is_dir() or (expected_log.exists() and not expected_log.is_file())):
        raise RuntimeError('variant profile log pathが未設定または不正です。')
    args = cfg['args']
    expected = {'--pack': str(root / 'packs' / model), '--native': str(shard_path(model, 1, root)),
                '--ple-gguf': str(shard_path(model, ple_shard, root)), '--mtp': str(root / 'mtp' / 'rt'),
                '--max-context': str(context),
                '--expert-cache': 'auto'}
    if CATALOG[model].get('ple_io'):
        expected['--ple-io'] = CATALOG[model]['ple_io']
    for flag, value in expected.items():
        if args.count(flag) != 1 or args[args.index(flag) + 1] != value:
            raise RuntimeError('variant profile引数が一致しません: ' + flag)
    repo = root.parent / 'Strata'
    if (cfg.get('model_name') != model or type(cfg.get('gpu')) is not int or cfg['gpu'] != 1
            or type(cfg.get('hip_ordinal')) is not int or cfg['hip_ordinal'] != 1
            or cfg.get('backend') != 'hip' or cfg.get('env') != {} or cfg.get('host') != '127.0.0.1'
            or cfg.get('port') != 18080 or cfg.get('parallel') != 1
            or pathlib.Path(cfg.get('exe', '')).resolve() != (repo / 'engine' / 'strata.exe').resolve()
            or pathlib.Path(cfg.get('cwd', '')).resolve() != repo.resolve()
            or pathlib.Path(cfg.get('tokenizer', '')).resolve() != (root / 'packs' / model / 'tokenizer').resolve()
            or cfg.get('vision') or any(name in cfg for name in ('layer_split', 'replicas', 'peer_device', 'helper_device'))):
        raise RuntimeError('検証済みsingleGPU/text-only profileではありません。')
    if any('peer' in str(x) or 'helper' in str(x) or 'layer-split' in str(x) or str(x) in ('--gpu', '--gpus') for x in args):
        raise RuntimeError('複数GPU指定は使用できません。')


def require_ready(model, root=ROOT, context=None):
    if _deepseek(model):
        _family_profile(model, root, context)
        return None
    item = CATALOG[model]
    ple = source_ple_shard(model, root)
    for name in PACK_FILES + (('compat-bf16.json',) if item['compat'] else ()):
        path = root / 'packs' / model / name
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError('ownpack/tokenizerが未準備です: ' + str(path))
    for name in ('experts.bin', 'dense.bin', 'dense.txt', 'draft_vocab.bin'):
        path = root / 'mtp' / 'rt' / name
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError('MTP runtimeが未準備です。')
    return ple


def availability(model, root=ROOT, context=None):
    if not CATALOG[model].get('selectable', True):
        return False, 'stock HIP実動作未検証。準備済みpackもGPU成功を意味せず、公開CLIから選択できません。'
    try:
        require_public_context(model, public_contexts(model)[-1], root)
        if _deepseek(model):
            require_ready(model, root, context)
        else:
            require_ready(model, root)
        if _deepseek(model):
            return True, 'native source/tokenizer/binary layout ready（通常CLI/manager起動接点はT30責任、実行資格とは別）'
        return True, 'source/pack ready（GPU実証とは別）'
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, IndexError) as error:
        return False, str(error)
