"""Deterministic minimal client derivatives; publication is a separate explicit step."""
import hashlib
import json
from pathlib import Path


def derive_web(raw, expected_sha256, parser_raw, *, identity_raw=None):
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('selected upstream app bytes changed')
    source = raw.decode('utf-8').replace('\r\n', '\n')
    replacements = (
        ('  for (const m of messages) {\n    if (m.role === "user") {',
         '  for (const m of messages) {\n    if (m._t31_incomplete) continue;\n    if (m.role === "user") {'),
        ('  const m = {role: "assistant", text: "", reasoning: "", time: Date.now()};',
         '  const t31DraftUser = messages[messages.length - 1];\n  const m = {role: "assistant", text: "", reasoning: "", time: Date.now()};'),
        ('  if (settings.seed) body.seed = +settings.seed;',
         '  if (settings.seed !== "" && settings.seed != null) body.seed = +settings.seed;'),
        ('    if (!m.text && m.reasoning) msg.reasoning_content = m.reasoning;',
         '    if (m.reasoning) msg.reasoning_content = m.reasoning;'),
        ('  let firstAt = null, thinkStart = null, usage = null, frame = 0;',
         '  let t31Reader = null;\n  let firstAt = null, thinkStart = null, usage = null, frame = 0;'),
        ('    const reader = r.body.getReader(), dec = new TextDecoder();',
         '    const reader = t31Reader = r.body.getReader();\n    const t31Stream = new T31CompletionStream();'),
        ('''    let buf = "";
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {stream: true});
      let nl;
      while ((nl = buf.indexOf("\\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line.startsWith("data:")) continue;              // ": keep-alive" comments while a long prompt is read
        const data = line.slice(5).trim();
        if (data === "[DONE]") continue;
        let j;
        try { j = JSON.parse(data); } catch (e) { continue; }''',
         '''    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      for (const j of t31Stream.feed(value)) {'''),
        ('    }\n  } catch (e) {\n    if (e.name === "AbortError") m.stopped = true;',
         '    }\n    t31Stream.finish();\n  } catch (e) {\n    controller.abort();\n    m._t31_incomplete = true;\n    t31DraftUser._t31_incomplete = true;\n    if (e.name === "AbortError") m.stopped = true;'),
        ('  }\n  if (thinkStart && m.thinkSecs == null)',
         '''  } finally {
    if (t31Reader) {
      if (controller.signal.aborted) { try { await t31Reader.cancel(); } catch (_) { /* retain original error */ } }
      try { t31Reader.releaseLock(); } catch (_) { /* retain original error */ }
    }
  }
  if (thinkStart && m.thinkSecs == null)'''),
    )
    # Existing native tool events and render/save behavior stay in the actual send().
    # Partial rows remain visible/persisted, but are excluded from the next prompt.
    for old, new in replacements:
        if source.count(old) != 1:
            raise ValueError('upstream client anchor changed: ' + old[:70])
        source = source.replace(old, new, 1)
    identity_prefix = ''
    if identity_raw is not None:
        # New immutable extension only: the default T31 derivative stays byte compatible.
        def bind(old, new):
            nonlocal source
            if source.count(old) != 1:raise ValueError('identity client anchor changed: '+old[:60])
            source=source.replace(old,new,1)
        bind('    const r = await fetch("v1/chat/completions",',
             '    const t33Expected = await t33FreshIdentity(controller.signal);\n    m.strata_runtime = structuredClone(t33Expected);\n    t31DraftUser.strata_runtime = structuredClone(t33Expected);\n    body.model = t33Expected.model;\n    const r = await fetch("v1/chat/completions",')
        bind('    const t31Stream = new T31CompletionStream();',
             '    const t31Stream = new T31CompletionStream(t33Expected, {normalize:T33Identity.normalizeIdentity, same:T33Identity.sameIdentity});')
        bind('    t31Stream.finish();',
             '    t31Stream.finish();\n    if (!T33Identity.sameIdentity(t33Expected, await t33FreshIdentity(controller.signal))) throw new Error("Runtime changed before response commit");')
        bind('    m._t31_incomplete = true;\n    t31DraftUser._t31_incomplete = true;',
             '    m._t31_incomplete = true;\n    t31DraftUser._t31_incomplete = true;\n    m.strata_incomplete = true;\n    t31DraftUser.strata_incomplete = true;')
        policy=identity_raw.decode('utf-8').replace('export function ','function ')
        identity_prefix=('const T33Identity = (() => {\n'+policy+'\nreturn {normalizeIdentity,sameIdentity};\n})();\n'
            'async function t33FreshIdentity(signal) {\n'
            '  const response = await fetch("metrics", {headers:headers(), signal, cache:"no-store"});\n'
            '  if (!response.ok) throw new Error("Runtime observation unavailable");\n'
            '  return T33Identity.normalizeIdentity((await response.json()).strata_runtime);\n}\n')
    parser = parser_raw.decode('utf-8').replace('export class ', 'class ')
    return ('// Selected family derivative; upstream SHA256=' + expected_sha256 + '\n' + identity_prefix +
            'const T31CompletionStream = (() => {\n' + parser +
            '\nreturn CompletionStream;\n})();\n// --- T31 actual app boundary ---\n' + source)


def write_web_candidate(upstream, destination, expected_sha256):
    """Writes a new isolated file only; never overwrites the selected package."""
    target = Path(destination)
    raw = Path(upstream).read_bytes()
    parser = Path(__file__).with_name('web_stream.js').read_bytes()
    result = derive_web(raw, expected_sha256, parser)
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(result)
    return dict(path=str(target), sha256=hashlib.sha256(target.read_bytes()).hexdigest())


def candidate_inputs(parent_inputs, parent_package, native_manifest, output):
    """Seal a finite prospective file list. Does not install or publish profiles."""
    from .chat_adapter import derive_chat
    def record(path):
        path=Path(path).resolve()
        return dict(path=str(path),bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    def checked(row):
        p=Path(row.get('source',row.get('path','')))
        actual=record(p)
        if actual['sha256']!=row['sha256']or ('bytes'in row and actual['bytes']!=row['bytes']):raise ValueError('candidate source changed')
        return p
    parent=json.loads(Path(parent_inputs).read_text(encoding='utf-8'))
    installed=json.loads(Path(parent_package).read_text(encoding='utf-8'))
    if parent['candidate_package_id']!=installed['id']:raise ValueError('parent package identity')
    old_id=parent['candidate_package_id'];parent_root=Path(parent_package).parent.parent
    files=parent['selected_files']
    if len(files)!=55:raise ValueError('parent finite file list')
    for row in files:
        checked(row)
        if record(parent_root/row['relative_destination'])['sha256']!=row['sha256']:raise ValueError('installed parent copy changed')
    native=json.loads(Path(native_manifest).read_text(encoding='utf-8'))
    if native['schema']!='strata-t35-key-hoist-normal/v1' or native['new_normal_model_qualified']is not False:raise ValueError('new native candidate contract')
    for row in native['bindings']:checked(row)
    target=Path(output);target.mkdir(parents=True,exist_ok=False)
    selected={x['relative_destination']:dict(x)for x in files}
    app=checked(selected['base/serve/web/app.js']);raw=app.read_bytes()
    web=target/'app.js';write_web_candidate(app,web,hashlib.sha256(raw).hexdigest())
    chat_source=Path('C:/Develop/AI/Strata/chat.py');chat=target/'chat.py';raw=chat_source.read_bytes();chat.write_text(derive_chat(raw,hashlib.sha256(raw).hexdigest()),encoding='utf-8')
    def put(relative,p):
        r=record(p);selected[relative]=dict(source=r['path'],relative_destination=relative,bytes=r['bytes'],sha256=r['sha256'])
    put('base/serve/web/app.js',web);put('clients/chat.py',chat)
    for name in ('chat_adapter.py','stream_contract.py','web_stream.js','package_clients.py'):put('Strata-extensions/clients/'+name,Path(__file__).with_name(name))
    exe=Path(native_manifest).parent/'bundle/Strata-deepseek.exe';put('native/Strata-deepseek.exe',exe)
    result=dict(schema='strata-t31-client-package-input/v1',parent_inputs=record(parent_inputs),parent_package=record(parent_package),parent_id=old_id,native_manifest=dict(source=str(Path(native_manifest).resolve()),relative_destination='evidence/native-manifest.json',bytes=Path(native_manifest).stat().st_size,sha256=record(native_manifest)['sha256']),selected_files=list(selected.values()),copy_payload_bytes=sum(x['bytes']for x in selected.values()),expected_copy_count=60,native_numerical_qualification_pending=True,public_write_executed=False,runtime_python_created_at_final_location=True,venv_not_copied=True)
    if len(selected)!=60:raise ValueError('explicit client extension scope')
    result['candidate_package_id']=hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    dest=target/'inputs.json';dest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return record(dest)


def derive_identity_entry(raw, expected_sha256):
    if hashlib.sha256(raw).hexdigest()!=expected_sha256:raise ValueError('parent entry changed')
    text=raw.decode('utf-8');anchor='    hook.install(server,config)'
    if text.count(anchor)!=1:raise ValueError('family entry install anchor changed')
    eol='\r\n'if'\r\n'in text else'\n'
    return text.replace(anchor,anchor+eol+"    identity=load(OWN/'clients/runtime_identity.py','deepseek_http_runtime_identity')"+eol+'    identity.install(server,config)').encode('utf-8')


def identity_candidate_inputs(parent_manifest, output):
    """Exact finite identity extension of an accepted installed T31 package."""
    from .chat_adapter import derive_chat
    import os
    def record(path):
        path=Path(path).resolve();return dict(path=str(path),bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    def checked(item):
        path=Path(item['path'])
        if record(path)!=item:raise ValueError('identity parent file binding changed')
        return path
    parent_manifest=Path(parent_manifest).resolve();parent=json.loads(parent_manifest.read_text(encoding='utf-8'));root=parent_manifest.parent.parent
    if parent.get('schema')!='strata-t29-runtime-package/v1'or parent.get('id')!=root.name or'identity_extension'in parent or type(parent.get('client_extension'))is not dict:raise ValueError('identity extension accepted parent')
    old_input=parent['client_extension']['input'];old=json.loads(checked(old_input).read_text(encoding='utf-8'))
    if old.get('schema')!='strata-t31-client-package-input/v1'or old.get('candidate_package_id')!=parent['id']or len(old['selected_files'])!=60:raise ValueError('identity parent finite input')
    for item in parent['files']:checked(item)
    selected={}
    for item in old['selected_files']:
        relative=item['relative_destination'];parts=Path(relative).parts
        if relative.startswith(('/','\\'))or':'in relative or'..'in parts or'\\'in relative or relative in selected:raise ValueError('identity parent relative path')
        source=root/relative;r=record(source)
        if r['bytes']!=item['bytes']or r['sha256']!=item['sha256']:raise ValueError('identity parent selected copy')
        selected[relative]=dict(source=r['path'],relative_destination=relative,bytes=r['bytes'],sha256=r['sha256'])
    native=record(root/'evidence/native-manifest.json')
    if native['sha256']!=parent['native_manifest_sha256']:raise ValueError('identity native parent')
    target=Path(output);target.mkdir(parents=True,exist_ok=False)
    raw_app=Path('C:/Develop/AI/Strata/serve/web/app.js');raw_chat=Path('C:/Develop/AI/Strata/chat.py');app=raw_app.read_bytes();chat=raw_chat.read_bytes();app_sha=record(raw_app)['sha256'];chat_sha=record(raw_chat)['sha256']
    if derive_web(app,app_sha,(root/'Strata-extensions/clients/web_stream.js').read_bytes()).encode('utf-8')!=(root/'base/serve/web/app.js').read_bytes():raise ValueError('identity raw app parent reproduction')
    if derive_chat(chat,chat_sha).replace('\n',os.linesep).encode('utf-8')!=(root/'clients/chat.py').read_bytes():raise ValueError('identity raw chat parent reproduction')
    web=target/'app.js';web.write_text(derive_web(app,app_sha,Path(__file__).with_name('web_stream.js').read_bytes(),identity_raw=Path(__file__).with_name('runtime_identity.js').read_bytes()),encoding='utf-8',newline='\n')
    terminal=target/'chat.py';terminal.write_text(derive_chat(chat,chat_sha,bind_identity=True).replace('\r\n','\n'),encoding='utf-8',newline='\n')
    entry=target/'deepseek_serve.py';old_entry=root/'Strata-extensions/control/deepseek_serve.py';entry.write_bytes(derive_identity_entry(old_entry.read_bytes(),record(old_entry)['sha256']))
    def put(relative,path):
        r=record(path);selected[relative]=dict(source=r['path'],relative_destination=relative,bytes=r['bytes'],sha256=r['sha256'])
    put('base/serve/web/app.js',web);put('clients/chat.py',terminal);put('Strata-extensions/control/deepseek_serve.py',entry)
    for name in ('runtime_identity.py','runtime_identity.js','chat_adapter.py','stream_contract.py','web_stream.js','package_clients.py'):put('Strata-extensions/clients/'+name,Path(__file__).with_name(name))
    if len(selected)!=62:raise ValueError('identity finite paths')
    result=dict(schema='strata-t33-identity-package-input/v1',parent_inputs=old_input,parent_package=record(parent_manifest),parent_id=parent['id'],native_manifest=dict(source=native['path'],relative_destination='evidence/native-manifest.json',bytes=native['bytes'],sha256=native['sha256']),upstream=[record(raw_app),record(raw_chat)],selected_files=list(selected.values()),copy_payload_bytes=sum(x['bytes']for x in selected.values()),expected_copy_count=62,public_write_executed=False,runtime_python_created_at_final_location=True,venv_not_copied=True)
    result['candidate_package_id']=hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':')).encode()).hexdigest();dest=target/'inputs.json';dest.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');return record(dest)
