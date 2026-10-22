import copy,io,http.client,json,os,queue,threading,struct,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import runner as C
import live as L
class AcceptedPublicInfo(unittest.TestCase):
    def test_public_INFO_HTTP_partial_body_original_error_priority(self):
        cases=('200-partial','200-missing','200-wrongtype','200-save-error','HTTPError-partial','HTTPError-save-error','HTTPError-close-error')
        for case in cases:
            with self.subTest(case=case),tempfile.TemporaryDirectory(dir=C.HERE)as tmp:
                attempt=Path(tmp);t=L.ActualTransport.__new__(L.ActualTransport)
                t.attempt=attempt;t.base='http://CPU';t.spec={};t.binding={}
                C.save(attempt/'config.json',{'CPU_fixture':True});C.save(attempt/'spec.json',{'CPU_fixture':True})
                read_error=http.client.IncompleteRead(b'actual-partial',23)
                if case=='200-missing':read_error=OSError('unknown read fault')
                if case=='200-wrongtype':read_error.partial='not bytes'
                closed=[];calls=[]
                class BrokenResponse:
                    status=200
                    def read(self):raise read_error
                    def close(self):
                        closed.append('closed')
                        if case=='HTTPError-close-error':raise OSError('secondary close fault')
                response=BrokenResponse()
                original=L.urllib.error.HTTPError(t.base+'/metrics',503,'original HTTP status error',{},response)if case.startswith('HTTPError')else read_error
                def opened(request,timeout):
                    calls.append((request.get_method(),request.full_url,timeout))
                    if case.startswith('HTTPError'):raise original
                    return response
                path_open=Path.open
                def opened_file(path,*args,**kwargs):
                    if case.endswith('save-error')and path.name=='fresh-INFO-HTTP.partial.raw':raise OSError('secondary partial save fault')
                    return path_open(path,*args,**kwargs)
                with patch.object(C,'fresh_INFO_boundary',return_value={'CPU_fixture':True}),patch.object(L.urllib.request,'build_opener',return_value=types.SimpleNamespace(open=opened)),patch.object(Path,'open',new=opened_file),self.assertRaises(BaseException)as got:t.public_INFO()
                self.assertIs(got.exception,original);self.assertEqual(closed,['closed'])
                self.assertEqual(calls,[('GET',t.base+'/metrics',305)])
                receipt=C.load(attempt/'fresh-INFO-HTTP.json')
                self.assertEqual(receipt['HTTP_status'],503 if case.startswith('HTTPError')else 200)
                self.assertEqual(receipt['error']['type'],type(original).__name__)
                self.assertFalse((attempt/'fresh-INFO-HTTP.raw').exists())
                partial=attempt/'fresh-INFO-HTTP.partial.raw'
                if case in('200-missing','200-wrongtype'):
                    self.assertFalse(partial.exists());self.assertEqual(receipt['body_kind'],'unobserved');self.assertIsNone(receipt['body_record'])
                elif case.endswith('save-error'):
                    self.assertFalse(partial.exists());self.assertEqual(receipt['body_kind'],'partial_observed');self.assertIn('partial body save failed',str(original.__notes__))
                else:
                    self.assertEqual(partial.read_bytes(),b'actual-partial');self.assertEqual(receipt['body_kind'],'partial_saved');self.assertEqual(receipt['body_record'],C.row(partial))
                if case.startswith('HTTPError'):self.assertIn('body read failed',str(original.__notes__))
                if case=='HTTPError-close-error':self.assertIn('close failed',str(original.__notes__))

    def test_public_INFO_HTTP_adapter_raw_native_vs_decorated(self):
        parsed=dict(core_position=5,extra=None,legal={'x':[1,2]})
        class Response(io.BytesIO):
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
        for case in ('valid','bad-status','failed-receipt','mismatch','HTTP-error','open-error','save-error'):
            with self.subTest(case=case),tempfile.TemporaryDirectory(dir=C.HERE)as tmp:
                attempt=Path(tmp);t=L.ActualTransport.__new__(L.ActualTransport)
                t.attempt=attempt;t.base='http://CPU';t.spec={};t.binding={}
                C.save(attempt/'config.json',{'CPU_fixture':True});C.save(attempt/'spec.json',{'CPU_fixture':True})
                receipt=dict(ok=case!='failed-receipt',error=None,parsed=parsed)
                C.save(attempt/'fresh-INFO-receipt.json',receipt)
                decorated=dict(parsed,decorated_only=True)
                if case=='mismatch':decorated['core_position']=0
                raw=json.dumps({'engine':decorated}).encode()
                original=L.urllib.error.HTTPError('http://CPU/metrics',503,'original GET HTTP failure',{},io.BytesIO(raw))if case=='HTTP-error'else OSError('original GET failure')
                calls=[]
                def opened(request,timeout):
                    calls.append((request.get_method(),request.full_url,timeout))
                    if case in('HTTP-error','open-error','save-error'):raise original
                    response=Response(raw);response.status=503 if case=='bad-status'else 200
                    return response
                real_save=C.save
                def saved(path,value):
                    if case=='save-error'and path.name=='fresh-INFO-HTTP.json':raise OSError('secondary save')
                    return real_save(path,value)
                with patch.object(C,'fresh_INFO_boundary',return_value={'CPU_fixture':True}),patch.object(L.urllib.request,'build_opener',return_value=types.SimpleNamespace(open=opened)),patch.object(C,'save',side_effect=saved):
                    if case=='valid':self.assertEqual(t.public_INFO(),parsed)
                    elif case in('HTTP-error','open-error','save-error'):
                        with self.assertRaises(OSError)as got:t.public_INFO()
                        self.assertIs(got.exception,original)
                        if case=='save-error':self.assertIn('receipt save failed',str(original.__notes__))
                    else:
                        with self.assertRaises(ValueError):t.public_INFO()
                self.assertEqual(calls,[('GET','http://CPU/metrics',305)])
                self.assertEqual(C.load(attempt/'fresh-INFO-receipt.json')['parsed'],parsed)
                if case not in('open-error','save-error'):self.assertEqual((attempt/'fresh-INFO-HTTP.raw').read_bytes(),raw)
                if case!='save-error':
                    http=C.load(attempt/'fresh-INFO-HTTP.json');self.assertEqual(http['path'],'/metrics')
                    self.assertEqual(http['error']is None,case=='valid')

    def test_public_owner_binds_before_control_and_rejects_foreign(self):
        with tempfile.TemporaryDirectory(dir=C.HERE)as tmp:
            attempt=Path(tmp);exe=attempt/'native.exe'
            cohort=[dict(pid=101,birth=10.25,exe=str(attempt/'server.exe')),dict(pid=202,birth=20.5,exe=str(exe))]
            t=L.ActualTransport.__new__(L.ActualTransport);t.cohort=cohort;t.cfg=dict(exe=str(exe),runtime_epoch=9);t.mode='cache-only'
            t.spec=dict(output=str(attempt/'observer.jsonl'),run_id='CPU');t.binding=dict(engine=cohort[1],cohort=cohort,runtime_epoch=9,hook_sha256=C.HOOK)
            header=dict(schema='strata-t46-observer/v1',event='header',sequence=0,monotonic_ns=1,run_id='CPU',owner=dict(server=dict(pid=101,birth=10.25),engine=dict(pid=202,birth=20.5)),hook_sha256=C.HOOK,runtime_epoch=9,package_id=C.ID,bundle_id=C.BUNDLE,mode='cache-only')
            path=Path(t.spec['output'])
            def write(value):path.write_text(json.dumps(value)+'\n',encoding='utf8')
            write(header);bound=t.bind_public_owner();self.assertEqual(bound['owner'],header['owner'])
            self.assertEqual(t.bind_public_owner(),bound)
            for mutation in ('server-birth','engine-birth','epoch','hook','package','mode','sequence-type','partial'):
                bad=copy.deepcopy(header)
                if mutation=='server-birth':bad['owner']['server']['birth']+=1
                elif mutation=='engine-birth':bad['owner']['engine']['birth']+=1
                elif mutation=='epoch':bad['runtime_epoch']+=1
                elif mutation=='hook':bad['hook_sha256']='f'*64
                elif mutation=='package':bad['package_id']='f'*64
                elif mutation=='mode':bad['mode']='single'
                elif mutation=='sequence-type':bad['sequence']=False
                else:bad={}
                write(bad)
                with self.subTest(mutation=mutation),self.assertRaises(ValueError):t.bind_public_owner()

if __name__=='__main__':unittest.main(verbosity=2)
