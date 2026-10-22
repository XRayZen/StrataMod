"""T31 transport/history tests; no model or normal settings are accessed."""
import importlib.util
import json
from pathlib import Path
import unittest
import sys
import subprocess
import shutil
import tempfile
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch

def load():
    path=Path(__file__).resolve().parents[2]/'clients/stream_contract.py'
    spec=importlib.util.spec_from_file_location('t31_stream',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def event(delta=None,finish=None,usage=None):
    value={'choices':[{'index':0,'delta':delta or {},'finish_reason':finish}]}if delta is not None or finish is not None else {'choices':[]}
    if usage is not None:value['usage']=usage
    return ('data: '+json.dumps(value,ensure_ascii=False)+'\n\n').encode()

class StreamTests(unittest.TestCase):
    def setUp(self):self.m=load()
    def parse(self,raw,step=1):
        parser=self.m.CompletionStream()
        for i in range(0,len(raw),step):parser.feed(raw[i:i+step])
        return parser.finish()
    def test_utf8_split_and_coalesced_terminal_content(self):
        raw=b': reading prompt\r\n\r\n'+event({'role':'assistant','reasoning_content':'考'})+event({'content':'您'},'length')+b'data: [DONE]\n\n'
        for step in (1,2,7,len(raw)):
            out=self.parse(raw,step)
            self.assertEqual(out['choices'][0]['message'],dict(role='assistant',content='您',reasoning_content='考'))
            self.assertIsNone(out['usage'])
    def test_partial_eof_error_cancel_and_missing_terminal_do_not_commit(self):
        prefix=event({'content':'partial'})
        for raw in (prefix,prefix+b'data: [DONE]\n\n',prefix+event({},'stop'),prefix+b'data: {bad}\n\n',prefix+b'data: {"error":{"message":"failed"}}\n\n'):
            with self.assertRaises(self.m.StreamError):self.parse(raw)
        parser=self.m.CompletionStream();parser.feed(prefix);parser.cancel()
        with self.assertRaises(self.m.StreamError):parser.finish()
    def test_tools_are_atomic_at_formal_terminal(self):
        a={'tool_calls':[{'index':0,'id':'call1','type':'function','function':{'name':'rea','arguments':'{"p'}}]}
        b={'tool_calls':[{'index':0,'function':{'name':'d','arguments':'ath":"x"}'}}]}
        out=self.parse(event(a)+event(b,'tool_calls')+b'data: [DONE]\n\n')
        self.assertEqual(out['choices'][0]['message']['tool_calls'][0],dict(id='call1',type='function',function={'name':'read','arguments':'{"path":"x"}'}))
        with self.assertRaises(self.m.StreamError):self.parse(event(a,'tool_calls')+b'data: [DONE]\n\n')
    def test_reasoning_only_and_unknown_usage_not_zero(self):
        out=self.parse(event({'reasoning_content':'only'},'stop')+b'data: [DONE]\n\n')
        self.assertEqual(out['choices'][0]['message']['content'],'');self.assertIsNone(out['usage'])
        out=self.parse(event({'content':'x'},'stop')+event(usage={'completion_tokens':1})+b'data: [DONE]\n\n')
        self.assertEqual(out['usage']['completion_tokens'],1)
    def test_invalid_utf8_trailing_event_duplicate_done_and_usage_type(self):
        good=event({'content':'x'},'stop')+b'data: [DONE]\n\n'
        for raw in (b'data: \xff\n\n',good+b'data: [DONE]\n\n',good+event({'content':'y'}),event({'content':'x'},'stop')+event(usage={'completion_tokens':True})+b'data: [DONE]\n\n'):
            with self.assertRaises(self.m.StreamError):self.parse(raw)
    def test_old_history_preserved_and_new_failed_turn_not_prompt(self):
        old=[{'role':'user','content':'old'},{'role':'assistant','content':'old answer'}]
        session=self.m.Turn(old,{'role':'user','content':'new'})
        session.feed(event({'content':'partial'}));session.cancel()
        self.assertEqual(session.history,old);self.assertEqual(session.draft['content'],'new')
        with self.assertRaises(self.m.StreamError):session.commit()
        good=self.m.Turn(old,{'role':'user','content':'new'})
        good.feed(event({'content':'answer'},'stop')+b'data: [DONE]\n\n');good.commit()
        self.assertEqual(good.history,old+[{'role':'user','content':'new'},{'role':'assistant','content':'answer'}])
        self.assertEqual(len(old),2)

    def test_failed_eof_cannot_resume_and_legacy_function_is_not_lost(self):
        parser=self.m.CompletionStream();parser.feed(event({'content':'partial'}))
        with self.assertRaises(self.m.StreamError):parser.finish()
        with self.assertRaises(self.m.StreamError):parser.feed(event({},'stop')+b'data: [DONE]\n\n')
        raw=event({'function_call':{'name':'read','arguments':'{"path":'}})+event({'function_call':{'arguments':'"x"}'}},'function_call')+b'data: [DONE]\n\n'
        self.assertEqual(self.parse(raw)['choices'][0]['message']['function_call'],dict(name='read',arguments='{"path":"x"}'))
        with self.assertRaises(self.m.StreamError):self.parse(b'data: {"choices":[],"extra":NaN}\n\n')

class ChatAdapterTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
        from clients import chat_adapter
        self.m=chat_adapter
    def test_default_options_omitted_and_all_efforts_preserved(self):
        messages=[{'role':'user','content':'hi'}]
        self.assertEqual(self.m.request_body(messages,None,None),dict(model='strata',messages=messages,stream=True))
        for level in self.m.EFFORTS:self.assertEqual(self.m.request_body(messages,level,1)['reasoning_effort'],level)
        self.assertEqual(messages,[{'role':'user','content':'hi'}])
    def test_real_adapter_iterator_formal_terminal_and_partial_failure(self):
        class Response:
            def __init__(self,raw):self.parts=[raw[:11],raw[11:],b''];self.closed=False
            def __enter__(self):return self
            def __exit__(self,*args):self.closed=True
            def read1(self,_):return self.parts.pop(0)
        response=Response(event({'content':'您'},'stop')+b'data: [DONE]\n\n')
        with patch.object(self.m.urllib.request,'urlopen',return_value=response):
            turn=self.m.stream('http://fixture',[],None,None)
            self.assertEqual(list(turn),[('', '您')]);self.assertEqual(turn.message,dict(role='assistant',content='您'))
        self.assertTrue(response.closed)
        response=Response(event({'content':'partial'}))
        with patch.object(self.m.urllib.request,'urlopen',return_value=response):
            turn=self.m.stream('http://fixture',[],None,None)
            with self.assertRaises(OSError):list(turn)
            self.assertIsNone(turn.message)
    def test_derived_chat_is_fixed_base_with_small_explicit_patch(self):
        source=Path('C:/Develop/AI/Strata/chat.py').read_bytes()
        import hashlib,ast
        generated=self.m.derive_chat(source,hashlib.sha256(source).hexdigest())
        tree=ast.parse(generated)
        defaults={}
        for node in ast.walk(tree):
            if isinstance(node,ast.Call)and isinstance(node.func,ast.Attribute)and node.func.attr=='add_argument'and node.args and isinstance(node.args[0],ast.Constant):
                defaults[node.args[0].value]={x.arg:ast.literal_eval(x.value) for x in node.keywords if x.arg in ('default','choices')}
        self.assertIsNone(defaults['--think']['default']);self.assertIsNone(defaults['--max-tokens']['default'])
        self.assertEqual(defaults['--think']['choices'],list(self.m.EFFORTS))
        self.assertIn('messages.append(turn.message)',generated)
        with self.assertRaises(ValueError):self.m.derive_chat(source,'0'*64)

    def test_actual_derived_main_with_controlled_http_history_success_and_eof(self):
        import hashlib
        for partial in (False,True):
            requests=[]
            class Handler(BaseHTTPRequestHandler):
                def log_message(self,*_):pass
                def do_POST(self):
                    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(body)
                    payload=event({'reasoning_content':'考','content':'您'},None if partial and len(requests)==1 else 'stop')
                    if not(partial and len(requests)==1):payload+=b'data: [DONE]\n\n'
                    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with tempfile.TemporaryDirectory()as directory:
                    root=Path(directory);entry=root/'clients/chat.py';entry.parent.mkdir()
                    target=root/'Strata-extensions/clients';target.mkdir(parents=True)
                    for name in ('chat_adapter.py','stream_contract.py'):shutil.copyfile(Path(__file__).resolve().parents[2]/'clients'/name,target/name)
                    source=Path('C:/Develop/AI/Strata/chat.py').read_bytes();entry.write_text(self.m.derive_chat(source,hashlib.sha256(source).hexdigest()),encoding='utf-8')
                    empty=root/'empty';empty.mkdir()
                    result=subprocess.run([sys.executable,'-E','-s','-B','-X','utf8',str(entry),'--port',str(server.server_port),'--no-think','--max-tokens','1'],input='hi\nnext\n/quit\n',cwd=empty,capture_output=True,text=True,encoding='utf-8',timeout=15)
                    self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(len(requests),2)
                    expected=[dict(role='user',content='next')]if partial else [dict(role='user',content='hi'),dict(role='assistant',content='您',reasoning_content='考'),dict(role='user',content='next')]
                    self.assertEqual(requests[1]['messages'],expected)
                    self.assertEqual(requests[0]['max_tokens'],1);self.assertEqual(requests[0]['reasoning_effort'],'none')
            finally:server.shutdown();server.server_close();thread.join()

class SelectedChatDispatchTests(unittest.TestCase):
    def test_client_extension_finite_selection_and_negatives(self):
        import importlib.util,tempfile,hashlib,copy
        root=Path(__file__).resolve().parents[3];spec=importlib.util.spec_from_file_location('t31_selected_builder',root/'Strata-extensions/tests/providers/runtime_stage.py');stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
        path=root/'build-deepseek-t31/package-input-candidate-r1/inputs.json';data=stage.selected_inputs(path)
        self.assertEqual(len(data['selected_files']),60)
        for mode in ('extra','duplicate','parent','protected','sum','old_schema','native'):
            changed=copy.deepcopy(data)
            if mode=='extra':changed['selected_files'][-1]['relative_destination']='unexpected/extra.py'
            elif mode=='duplicate':changed['selected_files'][-1]['relative_destination']=changed['selected_files'][0]['relative_destination']
            elif mode=='parent':changed['parent_id']='0'*64
            elif mode=='protected':changed['selected_files'][1]['sha256']='0'*64
            elif mode=='sum':changed['copy_payload_bytes']+=1
            elif mode=='old_schema':changed['schema']='strata-t29-deployment-input-plan/v1'
            else:changed['native_manifest']['sha256']='0'*64
            changed.pop('candidate_package_id');changed['candidate_package_id']=hashlib.sha256(json.dumps(changed,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            with tempfile.TemporaryDirectory()as temp:
                target=Path(temp)/'input.json';target.write_text(json.dumps(changed),encoding='utf-8')
                with self.assertRaises(ValueError):stage.selected_inputs(target)

    def test_selected_package_chat_and_legacy_argv(self):
        import importlib.util,tempfile
        from unittest import mock
        data=Path('C:/Develop/AI/Strata-data');old=list(sys.path)
        try:
            sys.path.insert(0,str(data));spec=importlib.util.spec_from_file_location('t31_actual_cli',data/'strata_cli.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        finally:sys.path[:]=old
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);(root/'clients').mkdir();(root/'clients/chat.py').write_text('# controlled entry',encoding='utf-8')
            import hashlib
            files=[]
            for relative in ('clients/chat.py','Strata-extensions/clients/chat_adapter.py','Strata-extensions/clients/stream_contract.py'):
                p=root/relative;p.parent.mkdir(parents=True,exist_ok=True)
                if not p.exists():p.write_text('# controlled helper',encoding='utf-8')
                files.append(dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
            manifest=root/'evidence/package-manifest.json';manifest.parent.mkdir();manifest.write_text(json.dumps(dict(id='a'*64,client_extension={},files=files)),encoding='utf-8')
            cfg=dict(family='deepseek41',python=str(root/'venv/Scripts/python.exe'),runtime_package=dict(id='a'*64,manifest=str(manifest)),host='127.0.0.1',port=18080)
            rt=mock.Mock();rt.state.return_value=dict(config='selected.json');rt.ready.return_value=None
            with mock.patch.object(cli.runtime.startup_progress,'family_launch',return_value=(None,cfg,{})),mock.patch.object(cli,'run_client',return_value=0)as run:
                self.assertEqual(cli.use_ready(rt,'chat'),0)
                argv,cwd,_=run.call_args.args;self.assertEqual(argv,[cfg['python'],'-E','-s','-B','-X','utf8',str(root/'clients/chat.py'),'--host','127.0.0.1','--port','18080']);self.assertEqual(cwd,str(root))
            with mock.patch.object(cli.runtime.startup_progress,'family_launch',return_value=None),mock.patch.object(cli,'run_client',return_value=0)as run:
                self.assertEqual(cli.use_ready(rt,'chat'),0);argv,cwd,_=run.call_args.args
                self.assertEqual(argv,[sys.executable,'-X','utf8',str(data.parent/'Strata/chat.py'),'--host','127.0.0.1','--port','18080'])
                self.assertEqual(cwd,str(data.parent/'Strata'))
            (root/'clients/chat.py').write_text('# changed controlled entry',encoding='utf-8')
            with mock.patch.object(cli.runtime.startup_progress,'family_launch',return_value=(None,cfg,{})),mock.patch.object(cli,'run_client')as run:
                with self.assertRaises(RuntimeError):cli.use_ready(rt,'chat')
                run.assert_not_called()
            (root/'clients/chat.py').unlink()
            with mock.patch.object(cli.runtime.startup_progress,'family_launch',return_value=(None,cfg,{})),mock.patch.object(cli,'run_client')as run:
                with self.assertRaises(RuntimeError):cli.use_ready(rt,'chat')
                run.assert_not_called()
            # This compatibility positive is pinned to the accepted parent declaration, including after new-profile publication.
            old_profile=Path(__file__).resolve().parents[3]/'build-deepseek-t29/deployment-candidate-r2/deepseek-v4.1-flash-1017-ud-q4_k_xl-4096.json'
            self.assertEqual(hashlib.sha256(old_profile.read_bytes()).hexdigest(),'a4872b34d6df040b7afac4900cd126b4f81c75a714ec3876cbc19193d42b3498')
            public=json.loads(old_profile.read_text(encoding='utf-8'))
            with mock.patch.object(cli.runtime.startup_progress,'family_launch',return_value=(None,public,{})),mock.patch.object(cli,'run_client',return_value=0)as run:
                self.assertEqual(cli.use_ready(rt,'chat'),0)
                self.assertEqual(run.call_args.args[0],[sys.executable,'-X','utf8',str(data.parent/'Strata/chat.py'),'--host','127.0.0.1','--port','18080'])

    def test_known_profile_batch_exact_and_foreign_rejection(self):
        spec=importlib.util.spec_from_file_location('t31_stage_publish',Path(__file__).resolve().parents[1]/'providers/runtime_stage.py');stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);rows=[]
            for n in range(2):
                old=root/f'{n}.json';new=root/f'{n}-new.json';old.write_bytes(b'old');new.write_bytes(b'new')
                rows.append(dict(known_old=stage.record(old),candidate=stage.record(new),destination=str(old)))
            foreign=Path(rows[1]['destination']);foreign.write_bytes(b'foreign')
            with self.assertRaises(ValueError):stage.replace_known_profile_batch(rows)
            self.assertEqual(Path(rows[0]['destination']).read_bytes(),b'old');self.assertEqual(foreign.read_bytes(),b'foreign')
            foreign.write_bytes(b'old');result=stage.replace_known_profile_batch(rows)
            self.assertEqual(len(result),2);self.assertTrue(all(Path(r['path']).read_bytes()==b'new'for r in result))
            with self.assertRaises(ValueError):stage.replace_known_profile_batch(rows)

    def test_numeric_config_exact_missing_duplicate_and_mutated(self):
        spec=importlib.util.spec_from_file_location('t31_numeric_config',Path(__file__).resolve().parents[1]/'providers/runtime_stage.py');stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
        with tempfile.TemporaryDirectory()as directory:
            p=Path(directory)/'config.json';p.write_text('{"bundle_id":"original"}',encoding='utf-8');r=stage.record(p)
            self.assertEqual(stage.numeric_config(dict(fixed_inputs=[r])),dict(bundle_id='original'))
            for rows in ([],[r,r]):
                with self.assertRaises(ValueError):stage.numeric_config(dict(fixed_inputs=rows))
            p.write_text('{"bundle_id":"candidate"}',encoding='utf-8')
            with self.assertRaises(ValueError):stage.numeric_config(dict(fixed_inputs=[r]))

    def test_profile_staging_failure_cleanup_then_next_operation(self):
        spec=importlib.util.spec_from_file_location('t31_stage_failure',Path(__file__).resolve().parents[1]/'providers/runtime_stage.py');stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);old=root/'profile.json';new=root/'candidate.json';old.write_bytes(b'old');new.write_bytes(b'new');rows=[dict(known_old=stage.record(old),candidate=stage.record(new),destination=str(old))];temp=old.with_name(old.name+'.t31-new')
            with patch.object(stage.os,'fsync',side_effect=OSError('controlled fsync failure')):
                with self.assertRaises(OSError):stage.replace_known_profile_batch(rows)
            self.assertEqual(old.read_bytes(),b'old');self.assertFalse(temp.exists())
            temp.write_bytes(b'foreign')
            with self.assertRaises(FileExistsError):stage.replace_known_profile_batch(rows)
            self.assertEqual(temp.read_bytes(),b'foreign');self.assertEqual(old.read_bytes(),b'old');temp.unlink()
            stage.replace_known_profile_batch(rows);self.assertEqual(old.read_bytes(),b'new')

if __name__=='__main__':unittest.main()
