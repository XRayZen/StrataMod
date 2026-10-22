"""Write StrataMod's prepared plain profile from the generated V2 text profile."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT.parent / 'Strata-data'
MODEL = 'huihui-ud-q4_k_xl_v2'
CONTEXT = 262144
RUNTIME = ROOT / 'local_runtime' / 'runtimes' / 'engine-0.1.47-4c9bc08bc87b'
TARGET = ROOT / 'local_runtime' / 'normal' / 'plain-profile.json'


def set_arg(args, name, value):
    if args.count(name) > 1:
        raise RuntimeError('Repeated option: ' + name)
    if name in args:
        args[args.index(name) + 1] = str(value)
    else:
        args.extend([name, str(value)])


def main():
    base = json.loads((DATA / 'profiles' / f'{MODEL}-{CONTEXT}.json').read_text(encoding='utf-8-sig'))
    args = list(base['args'])
    set_arg(args, '--resident-budget-gib', 32)
    set_arg(args, '--expert-profile', str(ROOT / 'local_runtime' / 'normal' / 'profiles' / 'huihui-ud-q4_k_xl_v2-expert-base.bin'))
    set_arg(args, '--prefill', 'auto')
    set_arg(args, '--vram-reserve-mib', 2560)
    set_arg(args, '--pool-workers', 3)
    set_arg(args, '--prompt-cache', 6)
    args.append('--vision')
    model = Path(base['args'][base['args'].index('--native') + 1])
    cfg = dict(exe=str(RUNTIME / 'strata.exe'), args=args, cwd=str(ROOT),
               tokenizer=base['tokenizer'], model_name=MODEL,
               log=str(ROOT / 'local_runtime' / 'normal' / 'engine.log'),
               lib_dirs=[str(RUNTIME), str(RUNTIME / 'rocm' / 'bin')],
               backend='hip', gpu=1, hip_ordinal=1, gpus_asked=True, parallel=1,
               host='127.0.0.1', port=18080, open_browser=False,
               env={'STRATA_HIP_WMMA': '1', 'STRATA_PF_FUSED': '1'},
               lazy_load=False, vram_elastic=False, shared=False,
               vision=dict(backend='hip', gpu=True, exe=str(RUNTIME / 'strata-vision-hip.exe'),
                           model=str(model),
                           mmproj=str(DATA / 'vision-sidecars' / 'ista' / 'mmproj-Qwen3.8-Flash-Next-BF16.gguf'),
                           threads=4, max_tokens=300, elastic=False,
                           temp_dir=str(ROOT / 'local_runtime' / 'normal' / 'tmp'),
                           reader_mode='official-bundle',
                           cpu_exe=str(RUNTIME / 'strata-vision.exe')))
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(profile=str(TARGET), model=MODEL, context=CONTEXT, runtime=str(RUNTIME)), indent=2))


if __name__ == '__main__':
    main()
