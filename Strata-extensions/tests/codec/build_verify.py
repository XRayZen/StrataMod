"""T27 task-local official source/toolchain build; no shared installation."""
import argparse
import copy
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tomllib
import urllib.request
import venv
import zipfile

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
BUILD=ROOT/'build-deepseek-t27'
REF='935817c66f5d6e64838f419692545f06787e485f'
SOURCE=BUILD/'source/deepseek-recipe'
SHARED=Path('C:/Develop/AI/StrataMod')
SDK=SHARED/'.vision-venv-10.1/Lib/site-packages/_rocm_sdk_devel'
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def row(p):return {'path':str(p),'bytes':Path(p).stat().st_size,'sha256':sha(p)}
def save(p,o):Path(p).parent.mkdir(parents=True,exist_ok=True);Path(p).write_text(json.dumps(o,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def get(url):return urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Strata-T27-fixed-source'}),timeout=90)
def jget(url):return json.load(get(url))
def download(url,p,expected=None):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    if not p.exists():
        temporary=p.with_suffix(p.suffix+'.part')
        with get(url) as f,temporary.open('wb') as out:shutil.copyfileobj(f,out,1024*1024)
        temporary.rename(p)
    if expected and sha(p)!=expected:raise ValueError('official checksum mismatch: '+str(p))
    return row(p)
def extract(p,destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    with tarfile.open(p) as archive:
        for member in archive.getmembers():
            resolved=(destination/member.name).resolve()
            if not resolved.is_relative_to(destination.resolve()) or member.issym() or member.islnk():raise ValueError('archive boundary/link')
        archive.extractall(destination,filter='data')
def environment():
    vc=SHARED/'.vision-toolchain/vs/VC/Tools/MSVC/14.44.35207';win=SHARED/'.vision-toolchain/winsdk'
    inc=win/'microsoft.windows.sdk.cpp/c/Include/10.0.26100.0';lib=win/'microsoft.windows.sdk.cpp.x64/c';wb=win/'microsoft.windows.sdk.cpp/c/bin/10.0.26100.0/x64'
    tools={'cl':vc/'bin/Hostx64/x64/cl.exe','link':vc/'bin/Hostx64/x64/link.exe','dumpbin':vc/'bin/Hostx64/x64/dumpbin.exe',
      'cmake':SHARED/'.vision-venv-10.1/Lib/site-packages/cmake/data/bin/cmake.exe','ninja':SHARED/'.vision-venv-10.1/Scripts/ninja.exe','rc':wb/'rc.exe','mt':wb/'mt.exe',
      'libclang':SDK/'lib/llvm/bin/libclang.dll','clang':SDK/'lib/llvm/bin/clang.exe'}
    if (BUILD/'llvm/bin/libclang.dll').exists():tools.update(libclang=BUILD/'llvm/bin/libclang.dll',clang=BUILD/'llvm/bin/clang.exe')
    env=os.environ.copy();temporary=BUILD/'tmp';temporary.mkdir(parents=True,exist_ok=True);env['TMP']=env['TEMP']=str(temporary)
    env['INCLUDE']=os.pathsep.join(map(str,[vc/'include',inc/'ucrt',inc/'shared',inc/'um']))
    env['LIB']=os.pathsep.join(map(str,[vc/'lib/x64',lib/'ucrt/x64',lib/'um/x64']))
    env['PATH']=os.pathsep.join(map(str,[BUILD/'rust/bin',tools['clang'].parent,tools['cmake'].parent,tools['ninja'].parent,vc/'bin/Hostx64/x64',wb,SDK/'lib/llvm/bin',env.get('PATH','')]))
    env['CARGO_HOME']=str(BUILD/'cargo-home');env['RUSTUP_HOME']=str(BUILD/'rustup-home');env['CARGO_TARGET_DIR']=str(BUILD/'target');env['RUSTC']=str(BUILD/'rust/bin/rustc.exe');env['LIBCLANG_PATH']=str(tools['libclang'].parent);env['CLANG_PATH']=str(tools['clang'])
    env['PIP_CACHE_DIR']=str(BUILD/'pip-cache');env['PYTHONDONTWRITEBYTECODE']='1';env['PYTHONIOENCODING']='utf-8'
    for n in ['CARGO_ENCODED_RUSTFLAGS','RUSTFLAGS','RUSTUP_TOOLCHAIN']:env.pop(n,None)
    return tools,env
def run(cmd,env,log,cwd=ROOT,check=True,observe_libclang=False):
    observations=[]
    with Path(log).open('w',encoding='utf-8') as f:
        process=subprocess.Popen(list(map(str,cmd)),cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,text=True)
        if observe_libclang:
            # Build proof only: inspect modules of task-owned opencv generator
            # executables. No unrelated process state is returned or changed.
            prefix=str((BUILD/'target/release/build/opencv-').resolve()).replace("'","''")
            command="$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new(); $found=@(Get-CimInstance Win32_Process -Filter \"Name='build-script-build.exe'\" | Where-Object {$_.ExecutablePath -and $_.ExecutablePath.StartsWith('"+prefix+"')} | ForEach-Object {$p=Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue; $p.Modules | Where-Object {$_.ModuleName -ieq 'libclang.dll'} | ForEach-Object {[pscustomobject]@{pid=$p.Id;path=$_.FileName}}}); ConvertTo-Json -Compress -InputObject $found"
            while process.poll() is None and not observations:
                r=subprocess.run(['powershell.exe','-NoProfile','-Command',command],env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20)
                if r.returncode==0:
                    for x in json.loads(r.stdout or '[]'):
                        if x not in observations:observations.append(x)
        code=process.wait()
    if observe_libclang:save(BUILD/'build-libclang-loaded.json',{'observations':observations,'attempted':True,'scope':'owned generator only'})
    if check and code:raise RuntimeError(f'exit{code}: see {log}')
    return code
def init():
    BUILD.mkdir(parents=True,exist_ok=True)
    save(BUILD/'start-storage.json',{'free_bytes':shutil.disk_usage(BUILD).free,'T05_parent_snapshot':{'time':'2026-10-21T03:02:38.382+09:00','remaining_original':430601024080,'metadata':16777216},'work_envelope_estimate':21474836480,'not_all_future_build_guarantee':True})
    _,env=environment();code=run([SHARED/'.vision-venv-10.1/Scripts/python.exe',HERE/'codec_fixture.py'],env,BUILD/'tdd-red.txt',check=False)
    if not code or 'ModuleNotFoundError' not in (BUILD/'tdd-red.txt').read_text(encoding='utf-8'):raise ValueError('meaningful missing official binding RED absent')
    print('T27 missing-binding RED recorded')
def acquire():
    receipts=[];tree=jget(f'https://api.github.com/repos/deepseek-ai/deepseek-recipe/git/trees/{REF}?recursive=1')['tree']
    prefixes=('deepseek-recipe/','deepseek-recipe-core/','deepseek-recipe-encoding/','deepseek-recipe-image/','deepseek-recipe-macros/','deepseek-recipe-python/','static/tokenizers/v41/')
    roots=['Cargo.toml','Cargo.lock','rust-toolchain.toml','LICENSE','README.md','static/tokenizers/LICENSE']
    extras=['encoding-decoding-demo/Cargo.toml','encoding-decoding-demo/src/main.rs','server-rs/Cargo.toml','server-rs/src/main.rs']
    selected=[x for x in tree if x['type']=='blob' and (x['path'].startswith(prefixes) or x['path'] in roots+extras)]
    for x in selected:
        p=SOURCE/x['path'];r=download(f'https://raw.githubusercontent.com/deepseek-ai/deepseek-recipe/{REF}/{x["path"]}',p)
        body=p.read_bytes();blob=hashlib.sha1(f'blob {len(body)}\0'.encode()+body).hexdigest()
        if len(body)!=x['size'] or blob!=x['sha']:raise ValueError('Git object/body mismatch')
        receipts.append(dict(r,url=f'https://raw.githubusercontent.com/deepseek-ai/deepseek-recipe/{REF}/{x["path"]}',git_blob=x['sha']))
    save(BUILD/'recipe-source.json',{'revision':REF,'files':receipts,'patches':[]})
    manifest_url='https://static.rust-lang.org/dist/channel-rust-1.97.1.toml';manifest_path=BUILD/'downloads/channel-rust-1.97.1.toml';download(manifest_url,manifest_path)
    manifest=tomllib.loads(manifest_path.read_text(encoding='utf-8'));rust=[]
    for name in ['rustc','cargo','rust-std']:
        component=manifest['pkg'][name]['target']['x86_64-pc-windows-msvc'];url=component['xz_url'];p=BUILD/'downloads'/url.rsplit('/',1)[-1]
        r=download(url,p,component['xz_hash']);target=BUILD/'rust-unpack'/name;extract(p,target)
        outer=next(target.iterdir());part=outer/(name if name!='rust-std' else 'rust-std-x86_64-pc-windows-msvc')
        for entry in part.iterdir():
            if entry.is_dir():shutil.copytree(entry,BUILD/'rust'/entry.name,dirs_exist_ok=True)
        rust.append(dict(r,url=url,official_sha256=component['xz_hash'],version=manifest['pkg'][name]['version']))
    save(BUILD/'rust-source.json',{'manifest':row(manifest_path),'components':rust})
    ref=jget('https://api.github.com/repos/opencv/opencv/git/ref/tags/4.12.0')['object']
    commit=jget(ref['url'])['object']['sha'] if ref['type']=='tag' else ref['sha']
    url=f'https://codeload.github.com/opencv/opencv/tar.gz/{commit}';archive=BUILD/'downloads/opencv-4.12.0.tar.gz';r=download(url,archive);extract(archive,BUILD/'source/opencv')
    save(BUILD/'opencv-source.json',{'revision':commit,'tag':'4.12.0','archive':r,'url':url,'publisher_archive_checksum_verified':False})
    print(json.dumps({'recipe_files':len(receipts),'recipe_bytes':sum(r['bytes'] for r in receipts),'Rust_components':len(rust),'opencv_archive':r}))
def opencv():
    tools,env=environment();src=next((BUILD/'source/opencv').iterdir());prefix=BUILD/'opencv-install'
    flags={'BUILD_SHARED_LIBS':'ON','BUILD_LIST':'core,imgproc,imgcodecs','BUILD_ZLIB':'ON','BUILD_JPEG':'ON','BUILD_PNG':'ON','BUILD_WEBP':'ON','WITH_JPEG':'ON','WITH_PNG':'ON','WITH_WEBP':'ON'}
    for x in ['BUILD_TESTS','BUILD_PERF_TESTS','BUILD_EXAMPLES','BUILD_opencv_apps','BUILD_DOCS','BUILD_JAVA','BUILD_opencv_python2','BUILD_opencv_python3','BUILD_PROTOBUF','WITH_ADE','WITH_EIGEN','WITH_FFMPEG','WITH_GSTREAMER','WITH_GTK','WITH_IPP','WITH_ITT','WITH_JASPER','WITH_LAPACK','WITH_OPENCL','WITH_OPENCLAMDBLAS','WITH_OPENCLAMDFFT','WITH_OPENEXR','WITH_OPENJPEG','WITH_OPENMP','WITH_QUIRC','WITH_TBB','WITH_TIFF','WITH_V4L','WITH_1394']:flags[x]='OFF'
    # Windows 0.93 generated wrappers reference four public core OpenCL
    # declarations even with minimal headers. Preserve/provide that API.
    flags['WITH_OPENCL']='ON'
    cmd=[tools['cmake'],'-S',src,'-B',BUILD/'opencv-build','-G','Ninja','-DCMAKE_BUILD_TYPE=Release',f'-DCMAKE_INSTALL_PREFIX={prefix.as_posix()}',f'-DCMAKE_MAKE_PROGRAM={tools["ninja"].as_posix()}',f'-DCMAKE_C_COMPILER={tools["cl"].as_posix()}',f'-DCMAKE_CXX_COMPILER={tools["cl"].as_posix()}',f'-DCMAKE_RC_COMPILER={tools["rc"].as_posix()}',f'-DCMAKE_MT={tools["mt"].as_posix()}']+[f'-D{k}={v}' for k,v in flags.items()]
    commands=[cmd,[tools['cmake'],'--build',BUILD/'opencv-build','--parallel','8'],[tools['cmake'],'--install',BUILD/'opencv-build']]
    save(BUILD/'opencv-commands.json',[list(map(str,c)) for c in commands])
    for n,c in enumerate(commands):run(c,env,BUILD/f'opencv-{n}.txt')
    print('OpenCV build/install completed')
def llvm():
    source=jget('https://api.github.com/repos/llvm/llvm-project/releases/tags/llvmorg-19.1.7')
    asset=next(x for x in source['assets'] if x['name']=='clang+llvm-19.1.7-x86_64-pc-windows-msvc.tar.xz')
    before=shutil.disk_usage(BUILD).free;archive=BUILD/'downloads'/asset['name'];r=download(asset['browser_download_url'],archive)
    if r['bytes']!=845236708 or r['bytes']!=asset['size']:raise ValueError('official LLVM asset size')
    selected=[]
    with tarfile.open(archive) as tar:
        members=tar.getmembers()
        for m in members:
            parts=Path(m.name).parts;relative=Path(*parts[1:])
            name=relative.as_posix();base=relative.name.lower()
            use=name in ['bin/clang.exe','bin/libclang.dll'] or name.startswith('lib/clang/19/include/') or any(s in base for s in ['license','copyright','notice'])
            if not use or not m.isfile():continue
            dst=(BUILD/'llvm'/relative).resolve()
            if not dst.is_relative_to((BUILD/'llvm').resolve()) or m.issym() or m.islnk():raise ValueError('LLVM selected path boundary')
            dst.parent.mkdir(parents=True,exist_ok=True)
            with tar.extractfile(m) as f,dst.open('wb') as out:shutil.copyfileobj(f,out)
            selected.append(row(dst))
    if not (BUILD/'llvm/bin/libclang.dll').exists() or not (BUILD/'llvm/bin/clang.exe').exists():raise ValueError('LLVM required component absent')
    save(BUILD/'llvm-source.json',{'release':'llvmorg-19.1.7','asset_id':asset['id'],'asset_name':asset['name'],'url':asset['browser_download_url'],'archive':r,'publisher_checksum_verified':False,'selected':selected,'selected_bytes':sum(p['bytes'] for p in selected),'free_before':before,'free_after':shutil.disk_usage(BUILD).free,
      'prior_attempt':{'AMD24':'opencv locked binding compile errors retained; incompatibility hypothesis','LLVM18':'pre-stop snapshot zero; final partial 493879296 bytes, then exclusive-handle-checked single-file cleanup; MSVC14.44 required Clang19+; no protection override','stopped_only_owned_download':True}})
    print(json.dumps({'archive':r,'selected_files':len(selected),'selected_bytes':sum(p['bytes'] for p in selected)}))
def patch():
    commit='501fb53af1f610455e667136c41d914d44f4ff8d';target=BUILD/'cargo-home/registry/src/index.crates.io-1949cf8c6b5b557f/opencv-binding-generator-0.93.0/src/generator.rs'
    expected='deb2171491816e428ae244fc45424448d1e541489b7646e2db4ee55e1b822bfc'
    if sha(target)!=expected:raise ValueError('backport requires exact original generator file')
    directory=BUILD/'patches';directory.mkdir(exist_ok=True);before=directory/'generator.rs.original';shutil.copyfile(target,before)
    upstream=jget(f'https://api.github.com/repos/twistedfall/opencv-rust/commits/{commit}');save(directory/'upstream-commit.json',upstream)
    file,=upstream['files']
    if upstream['sha']!=commit or file['filename']!='binding-generator/src/generator.rs' or file['additions']!=20 or file['deletions']!=2:raise ValueError('unexpected upstream fix')
    patchfile=directory/'clang19-drop.patch'
    patchfile.write_text('diff --git a/binding-generator/src/generator.rs b/binding-generator/src/generator.rs\n--- a/binding-generator/src/generator.rs\n+++ b/binding-generator/src/generator.rs\n'+file['patch']+'\n',encoding='utf-8',newline='\n')
    package=target.parents[1];_,env=environment();command=['git','apply','-p2','--directory='+package.relative_to(ROOT).as_posix()]
    run(command+['--check',patchfile],env,directory/'apply-check.txt');run(command+[patchfile],env,directory/'apply.txt')
    save(directory/'receipt.json',{'upstream_commit':commit,'upstream_url':upstream['html_url'],'original_file':row(before),'patch':row(patchfile),'upstream_metadata':row(directory/'upstream-commit.json'),'consumed_patched_file':row(target),
      'scope':'Windows Clang19+clang-runtime build-worker Drop only; official Recipe/Python/OpenCV/Cargo.lock unchanged; no codec runtime lifetime/API change','whole_upstream_parent_file_identical':False,'publisher_pristine_after_patch':False})
    print(json.dumps(read(directory/'receipt.json')))
def wheel():
    tools,env=environment();buildenv=BUILD/'build-venv'
    patch_record=read(BUILD/'patches/receipt.json')
    if row(patch_record['consumed_patched_file']['path'])!=patch_record['consumed_patched_file']:raise ValueError('explicit backport not applied/bound before build')
    if (BUILD/'llvm-source.json').exists():
        provenance=read(BUILD/'llvm-source.json');provenance['prior_attempt']['LLVM18']=read(BUILD/'llvm-adjustment.json')
        retained=[];removed=[]
        for entry in provenance['selected']:
            p=Path(entry['path']).resolve()
            if p.parent==(BUILD/'llvm/bin').resolve() and p.suffix.lower()=='.dll' and p.name.lower()!='libclang.dll':
                # Only archive-owned candidate DLLs. The two consumed compiler
                # files directly import Windows system DLLs, as dumpbin records.
                if row(p)!=entry:raise ValueError('unexpected toolchain cleanup file')
                p.unlink();removed.append(entry)
            else:retained.append(entry)
        provenance['selected']=retained;provenance['selected_bytes']=sum(x['bytes'] for x in retained)
        if removed:provenance['removed_unused_candidate_DLLs']=removed
        save(BUILD/'llvm-source.json',provenance)
        for name in ['clang.exe','libclang.dll']:run([tools['dumpbin'],'/dependents',BUILD/'llvm/bin'/name],env,BUILD/f'llvm-{name}-imports.txt')
    if not (buildenv/'Scripts/python.exe').exists():venv.EnvBuilder(with_pip=True).create(buildenv)
    python=buildenv/'Scripts/python.exe';dependency_receipt=BUILD/'python-dependencies.json';packages=read(dependency_receipt)['requested'] if dependency_receipt.exists() else {}
    for name in ([] if packages else ['maturin','delvewheel','pytest']):
        info=jget(f'https://pypi.org/pypi/{name}/json');version=info['info']['version']
        if name=='maturin' and int(version.split('.')[0])!=1:raise ValueError('maturin official source requires >=1.9,<2')
        if name=='pytest' and not 8<=int(version.split('.')[0])<10:raise ValueError('official test dependency range')
        packages[name]=version
    package_dir=BUILD/'downloads/python-wheels';package_dir.mkdir(parents=True,exist_ok=True)
    if not dependency_receipt.exists():run([python,'-m','pip','download','--only-binary=:all:','--dest',package_dir]+[f'{n}=={v}' for n,v in packages.items()],env,BUILD/'pip-download.txt')
    proofs=[]
    for p in package_dir.glob('*.whl'):
        with zipfile.ZipFile(p) as archive:
            metadata=archive.read(next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))).decode()
        fields=dict(line.split(': ',1) for line in metadata.splitlines() if line.startswith(('Name: ','Version: ')))
        release=jget(f'https://pypi.org/pypi/{fields["Name"]}/{fields["Version"]}/json');declared=next(x for x in release['urls'] if x['filename']==p.name)
        if sha(p)!=declared['digests']['sha256']:raise ValueError('PyPI wheel published checksum mismatch')
        proofs.append(dict(row(p),url=declared['url'],published_sha256=declared['digests']['sha256']))
    save(BUILD/'python-dependencies.json',{'requested':packages,'wheels':proofs})
    run([python,'-m','pip','install','--no-index','--find-links',package_dir]+[f'{n}=={v}' for n,v in packages.items()],env,BUILD/'pip-install.txt')
    core=next((BUILD/'opencv-install').rglob('opencv_core4120.lib'));dll=next((BUILD/'opencv-install').rglob('opencv_core4120.dll'))
    headers=next((BUILD/'opencv-install').rglob('opencv2/core.hpp')).parent.parent
    env['OPENCV_INCLUDE_PATHS']=str(headers);env['OPENCV_LINK_PATHS']=str(core.parent);env['OPENCV_LINK_LIBS']='opencv_core4120,opencv_imgproc4120,opencv_imgcodecs4120'
    # cc appends environment flags after esaxx's static_crt(true) default.
    # Keep the official source unchanged and match Python/OpenCV's dynamic CRT.
    env['CXXFLAGS']='/MD'
    env['PATH']=str(dll.parent)+os.pathsep+str(buildenv/'Scripts')+os.pathsep+env['PATH']
    commands=[[python,'-m','maturin','build','--release','--locked','--interpreter',python,'--out',BUILD/'wheel-unrepaired']]
    save(BUILD/'wheel-build-environment.json',{'OPENCV_INCLUDE_PATHS':env['OPENCV_INCLUDE_PATHS'],'OPENCV_LINK_PATHS':env['OPENCV_LINK_PATHS'],'OPENCV_LINK_LIBS':env['OPENCV_LINK_LIBS'],'CXXFLAGS':env['CXXFLAGS'],'commands':[list(map(str,c)) for c in commands]})
    old=BUILD/'maturin-build.txt'
    if old.exists():shutil.copyfile(old,BUILD/('maturin-build-prior-'+sha(old)[:12]+'.txt'))
    if Path(env['CARGO_TARGET_DIR']).resolve()!=(BUILD/'target').resolve():raise ValueError('task-local build cleanup target')
    # opencv 0.93 build script does not fingerprint LIBCLANG_PATH. Regenerate its
    # task-owned outputs explicitly so a compiler switch cannot reuse old ASTs.
    clean=[BUILD/'rust/bin/cargo.exe','clean','-p','opencv','-p','opencv-binding-generator','-p','esaxx-rs','--release','--manifest-path',SOURCE/'deepseek-recipe-python/Cargo.toml']
    run(clean,env,BUILD/'opencv-generator-clean.txt')
    save(BUILD/'generator-input.json',{'clang':row(tools['clang']),'libclang':row(tools['libclang']),'CLANG_PATH':env['CLANG_PATH'],'LIBCLANG_PATH':env['LIBCLANG_PATH'],'clean_command':list(map(str,clean))})
    run(commands[0],env,old,SOURCE/'deepseek-recipe-python',observe_libclang=True)
    run([tools['dumpbin'],'/exports',dll],env,BUILD/'opencv-OpenCL-ON-exports.txt')
    wheel=next((BUILD/'wheel-unrepaired').glob('*.whl'));repaired=BUILD/'wheel-repaired'
    run([python,'-m','delvewheel','repair','--add-path',dll.parent,'-w',repaired,wheel],env,BUILD/'delvewheel-repair.txt')
    run([python,'-m','delvewheel','show',next(repaired.glob('*.whl'))],env,BUILD/'delvewheel-show.txt')
    fresh=BUILD/'bundle/venv'
    if not (fresh/'Scripts/python.exe').exists():venv.EnvBuilder(with_pip=True).create(fresh)
    _,freshenv=environment()
    for name in ['PYTHONPATH','PYTHONHOME','OPENCV_INCLUDE_PATHS','OPENCV_LINK_PATHS','OPENCV_LINK_LIBS']:freshenv.pop(name,None)
    # Build OpenCV directory is intentionally absent from this fresh process.
    run([fresh/'Scripts/python.exe','-m','pip','install','--no-index',next(repaired.glob('*.whl'))],freshenv,BUILD/'fresh-install.txt')
    run([fresh/'Scripts/python.exe','-m','pip','install','--no-index','--find-links',package_dir,f'pytest=={packages["pytest"]}'],freshenv,BUILD/'fresh-pytest-install.txt')
    pyd=next((fresh/'Lib/site-packages/deepseek_recipe').glob('*.pyd'));run([tools['dumpbin'],'/dependents',pyd],freshenv,BUILD/'native-imports.txt')
    run([BUILD/'rust/bin/cargo.exe','tree','--locked','--offline','-p','deepseek-recipe-python','--edges','normal'],env,BUILD/'runtime-cargo-tree.txt',SOURCE)
    print('Official repaired Windows wheel installed; qualification import not yet run')
def binding(manifest):
    if manifest['recipe_revision']!=REF or manifest['patches']!=[read(BUILD/'patches/receipt.json')]:raise ValueError('fixed source revision/patch provenance')
    for x in manifest['files']:
        if row(x['path'])!=x:raise ValueError('fixed source/artifact changed: '+x['path'])
    observed=[row(p) for p in sorted((BUILD/'bundle').rglob('*')) if p.is_file() and '__pycache__' not in p.parts]
    if observed!=manifest['bundle_files']:raise ValueError('installed bundle file set changed')
    _,env=environment()
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,env=env,text=True).strip()
    diff=subprocess.check_output(['git','diff','477ac13cbe8e582c20484871ce459d20d82df09d','--name-only','--','.',':(exclude)Strata-extensions'],cwd=ROOT,env=env,text=True).strip()
    if head!='477ac13cbe8e582c20484871ce459d20d82df09d' or diff:raise ValueError('upstream reference changed')
def tokenizer_comparison():
    sys.dont_write_bytecode=True
    path=ROOT/'Strata-extensions/native/artifact/gguf.py';spec=importlib.util.spec_from_file_location('t27_fixed_gguf',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    shard=read(ROOT/'Strata-extensions/tests/artifact/header-inventory.json')['shards'][0];prefix=Path(shard['prefix_path'])
    if sha(prefix)!=shard['prefix_sha256']:raise ValueError('T03 fixed header changed')
    metadata=module.parse_header(prefix.read_bytes(),shard['bytes'])['metadata'];hf=read(SOURCE/'static/tokenizers/v41/tokenizer.json')
    byid={index:text for text,index in hf['model']['vocab'].items()};byid.update({x['id']:x['content'] for x in hf['added_tokens']})
    tokens=metadata['tokenizer.ggml.tokens'];types=metadata['tokenizer.ggml.token_type'];merges=metadata['tokenizer.ggml.merges'];hm=[' '.join(x) if isinstance(x,list) else x for x in hf['model']['merges']]
    difference=[{'id':i,'GGUF':t,'official':byid.get(i)} for i,t in enumerate(tokens) if byid.get(i)!=t]
    flags=[{'id':x['id'],'official_added_special':x['special'],'gguf_type':types[x['id']]} for x in hf['added_tokens'] if x['special']!=(types[x['id']]==3)]
    official_added={x['id'] for x in hf['added_tokens']};gguf_added={i for i,t in enumerate(types) if t in [3,4]}
    receipt={'T03_prefix':row(prefix),'official_tokenizer':row(SOURCE/'static/tokenizers/v41/tokenizer.json'),'gguf_vocab':len(tokens),'official_vocab':len(byid),'token_text_differences':difference,
      'merges_equal':merges==hm,'gguf_merge_count':len(merges),'official_merge_count':len(hm),'special_flag_comparison':flags,'added_ID_membership_equal_GGUF_control_or_user_defined':official_added==gguf_added,'added_ID_membership_difference':sorted(official_added^gguf_added),
      'official_stream_classifier':'stream/decoder.rs is_special_token uses added_tokens_decoder.contains_key(id), not each added token special bool. PromptTokenizer likewise uses added vocabulary membership.','gguf_pre':metadata['tokenizer.ggml.pre'],'official_pre_tokenizer':hf['pre_tokenizer'],
      'model_tokenizer_integration_qualified':False,'scope':'Exact vocabulary/merge comparison only; GGUF pre name and flag semantics not assumed equivalent; no tokenizer replacement.'}
    save(BUILD/'tokenizer-comparison.json',receipt);return prefix
def freeze():
    tools,env=environment();prefix=tokenizer_comparison();sources=read(BUILD/'recipe-source.json')['files'];files=[{k:r[k] for k in ['path','bytes','sha256']} for r in sources]
    esaxx=next((BUILD/'target/release/build').glob('esaxx-rs-*/out/*-esaxx.o'))
    run([tools['dumpbin'],'/directives',esaxx],env,BUILD/'esaxx-object-directives.txt')
    registry=BUILD/'cargo-home/registry/src/index.crates.io-1949cf8c6b5b557f'
    files.extend(row(p) for p in [esaxx,esaxx.parent.parent/'output',registry/'esaxx-rs-0.1.10/build.rs',registry/'cc-1.4.5/src/lib.rs',BUILD/'esaxx-object-directives.txt'])
    files.extend([row(prefix),row(BUILD/'tokenizer-comparison.json')])
    for folder in [HERE,BUILD/'bundle',BUILD/'wheel-repaired']:
        files.extend(row(p) for p in sorted(folder.rglob('*')) if p.is_file() and '__pycache__' not in p.parts)
    for name in ['recipe-source.json','rust-source.json','llvm-source.json','llvm-adjustment.json','opencv-source.json','opencv-build-adjustment.json','python-dependencies.json','opencv-commands.json','wheel-build-environment.json','generator-input.json','build-libclang-loaded.json','maturin-build.txt','native-imports.txt','runtime-cargo-tree.txt','opencv-OpenCL-ON-exports.txt','delvewheel-repair.txt','delvewheel-show.txt','fresh-install.txt']:
        files.append(row(BUILD/name))
    files.extend(row(p) for p in tools.values())
    files.extend(row(p) for p in [Path(sys._base_executable),Path(sys.base_prefix)/'python312.dll',Path(sys.base_prefix)/'python3.dll'])
    files.extend(row(BUILD/'rust/bin'/n) for n in ['rustc.exe','cargo.exe'])
    files.extend(read(BUILD/'llvm-source.json')['selected'])
    patch_receipt=read(BUILD/'patches/receipt.json');files.append(patch_receipt['consumed_patched_file'])
    files.extend(row(p) for p in sorted((BUILD/'patches').rglob('*')) if p.is_file())
    files.extend(row(p) for p in sorted((BUILD/'downloads').rglob('*')) if p.is_file())
    priors=['Strata-extensions/native/artifact/gguf.py','Strata-extensions/native/artifact/quant_layouts.json','Strata-extensions/tests/artifact/header-inventory.json','Strata-extensions/tests/artifact/fixture-receipts.json',
      'build-deepseek-t06/bundle/manifest.json','build-deepseek-t08/bundle/manifest.json','build-deepseek-t16/bundle/manifest.json','build-deepseek-t17/bundle/manifest.json']
    files.extend(row(ROOT/p) for p in priors)
    # The source archive and compile commands bind OpenCV; package cache archives
    # are verified by Cargo against the original --locked checksums.
    cache=[]
    locked=tomllib.loads((SOURCE/'Cargo.lock').read_text(encoding='utf-8'))['package'];checksums={p['name']+'-'+p['version']+'.crate':p.get('checksum') for p in locked}
    for p in sorted((BUILD/'cargo-home/registry/cache').rglob('*.crate')):
        if sha(p)!=checksums[p.name]:raise ValueError('Cargo locked archive checksum')
        cache.append(row(p))
    files.extend(cache)
    # Absolute paths are part of this local developer proof, not a runtime gate.
    manifest={'schema':'t27-fixed-trial/v2','recipe_revision':REF,'patches':[patch_receipt],'files':files,'bundle_files':[row(p) for p in sorted((BUILD/'bundle').rglob('*')) if p.is_file() and '__pycache__' not in p.parts],'tools':{n:row(p) for n,p in tools.items()},'source_files':len(sources),'cargo_archives':len(cache),
      'source_roles':{'owned_interpreted_recipe_and_tests':[str(p) for p in sorted(HERE.glob('*')) if p.is_file()],
        'compiled_official_crates':['deepseek-recipe','deepseek-recipe-core','deepseek-recipe-encoding','deepseek-recipe-image','deepseek-recipe-macros','deepseek-recipe-python'],
        'reference_only_workspace_members':['encoding-decoding-demo','server-rs'],'dependency_lock':row(SOURCE/'Cargo.lock'),'Strata_upstream':'reference only; no engine source compiled in T27'},
      'scope':'official Windows Python CPU codec; model inference/GPU/HTTP server unperformed','work_envelope_estimate':21474836480,'free_before_tests':shutil.disk_usage(BUILD).free}
    binding(manifest);save(BUILD/'manifest.json',manifest);print(json.dumps({'manifest':row(BUILD/'manifest.json'),'bound_files':len(files)}))
def verify():
    manifest=read(BUILD/'manifest.json');fixed=sha(BUILD/'manifest.json');binding(manifest);_,env=environment()
    for name in ['PYTHONPATH','PYTHONHOME','OPENCV_INCLUDE_PATHS','OPENCV_LINK_PATHS','OPENCV_LINK_LIBS']:env.pop(name,None)
    env['OPENCV_OPENCL_RUNTIME']='disabled' # CPU qualification child only
    env['PYTHONUTF8']='1' # Official test read_text() uses the process default.
    python=BUILD/'bundle/venv/Scripts/python.exe';tokenizer=SOURCE/'static/tokenizers/v41/tokenizer.json'
    run([python,HERE/'codec_fixture.py',tokenizer,HERE/'codec_contract.json',BUILD/'codec-receipt.json'],env,BUILD/'codec-fixture.txt')
    receipt=read(BUILD/'codec-receipt.json')
    package=Path(receipt['module']).resolve();site=(BUILD/'bundle/venv/Lib/site-packages').resolve()
    if not package.is_relative_to(site) or not Path(receipt['native_module']).resolve().is_relative_to(site) or receipt['version']!='0.2.0':raise ValueError('fresh installed package identity')
    opencv=[Path(p) for p in receipt['loaded_modules'] if 'opencv_' in Path(p).name.lower()]
    if len(opencv)!=3 or any(not p.resolve().is_relative_to(site) for p in opencv):raise ValueError('OpenCV loaded outside repaired installed wheel')
    run([python,'-m','pytest','-q','-p','no:cacheprovider',SOURCE/'deepseek-recipe-python/tests/test_bindings.py','--junitxml='+str(BUILD/'official-tests.xml')],env,BUILD/'official-tests.txt')
    binding(manifest)
    if sha(BUILD/'manifest.json')!=fixed:raise ValueError('manifest changed during CPU qualification')
    save(BUILD/'verification.json',{'manifest_sha256':fixed,'codec_receipt':row(BUILD/'codec-receipt.json'),'official_tests':row(BUILD/'official-tests.xml'),'loaded_OpenCV':[row(p) for p in opencv],
      'binding_before_after':True,'model_inference':False,'GPU_executed':False,'generated_bytes':sum(p.stat().st_size for p in BUILD.rglob('*') if p.is_file()),'free_after':shutil.disk_usage(BUILD).free})
    print(json.dumps({'verified':True,'verification':row(BUILD/'verification.json')}))
def negatives():
    manifest=read(BUILD/'manifest.json');binding(manifest);count=0
    for key,value in [('recipe_revision','0'*40),('patches',['not-applied'])]:
        bad=copy.deepcopy(manifest);bad[key]=value
        try:binding(bad)
        except ValueError:count+=1
        else:raise AssertionError('false provenance accepted')
    candidates=[next(x for x in manifest['files'] if x['path'].endswith('codec_fixture.py')),next(x for x in manifest['files'] if x['path'].endswith('.pyd')),next(x for x in manifest['files'] if x['path'].endswith('.whl'))]
    for i,entry in enumerate(candidates):
        p=BUILD/f'negative-tamper-{i}.bin';shutil.copyfile(entry['path'],p)
        with p.open('r+b') as f:f.seek(-1,2);last=f.read(1);f.seek(-1,2);f.write(bytes([last[0]^1]))
        bad=copy.deepcopy(manifest);next(x for x in bad['files'] if x['path']==entry['path'])['path']=str(p)
        try:binding(bad)
        except ValueError:count+=1
        else:raise AssertionError('changed same-identity source/native artifact accepted')
    save(BUILD/'binding-negatives.json',{'passed':count,'GPU_executed':False,'normal_runtime_gate_added':False});print(count)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['init','acquire','opencv','llvm','patch','wheel','freeze','verify','negatives']);a=p.parse_args();globals()[a.mode]()
