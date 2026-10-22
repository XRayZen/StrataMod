"""Offline T05 transport/resume/integrity failures, using tiny temporary files."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import contextlib
import subprocess
import sys
import time

MODULE=Path(__file__).resolve().parents[2]/'native/artifact/full_acquire.py'
spec=importlib.util.spec_from_file_location('full_acquire',MODULE)
acquire=importlib.util.module_from_spec(spec);spec.loader.exec_module(acquire)

class Response(io.BytesIO):
    def __init__(self,data,start,length,total,etag='"tiny-content"',status=206,headers=None,fail=False):
        super().__init__(data);self.status=status;self.calls=0;self.fail=fail
        self.headers={'Content-Range':f'bytes {start}-{start+length-1}/{total}',
                      'Content-Length':str(length),'ETag':etag,'Content-Encoding':'identity'}
        if headers:self.headers.update(headers)
    def read(self,n=-1):
        self.calls+=1
        if self.fail and self.calls>1:raise OSError('injected interruption')
        return super().read(n)

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.data=b'tiny-real-test-content\x00\xff'*3
        self.row=dict(index=1,filename='UD-Q4_K_XL/tiny.gguf',bytes=len(self.data),lfs_sha256=hashlib.sha256(self.data).hexdigest())
        self.responses=[];self.requests=[]
    def tearDown(self):self.temp.cleanup()
    def transport(self,request,timeout):
        start,end=map(int,request.headers['Range'].removeprefix('bytes=').split('-'))
        self.requests.append((start,end));r=Response(self.data[start:end+1],start,end-start+1,len(self.data));self.responses.append(r);return r
    def download(self,**kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return acquire.download_file(self.row,self.root,'"tiny-content"',open_url=kwargs.pop('open_url',self.transport),chunk_bytes=8,**kwargs)
    def test_complete_stream_rename_and_receipt(self):
        result=self.download();self.assertEqual((self.root/'tiny.gguf').read_bytes(),self.data)
        self.assertFalse((self.root/'tiny.gguf.part').exists());self.assertEqual(result['sha256'],self.row['lfs_sha256'])
        self.assertTrue(result['same_file_rename']);self.assertEqual(self.requests[0],(0,7))
    def test_200_rejected_before_body(self):
        r=Response(self.data,0,8,len(self.data),status=200)
        with self.assertRaises(ValueError):self.download(open_url=lambda *a,**k:r)
        self.assertEqual(r.calls,0)
    def test_bad_header_rejected_before_body(self):
        for key,value in [('Content-Range','bytes 1-8/69'),('Content-Length','9'),('Content-Encoding','gzip'),('ETag','"wrong"')]:
            with self.subTest(key=key),tempfile.TemporaryDirectory() as d:
                r=Response(self.data[:8],0,8,len(self.data),headers={key:value})
                with self.assertRaises(ValueError):acquire.download_file(self.row,Path(d),'"tiny-content"',open_url=lambda *a,**k:r,chunk_bytes=8)
                self.assertEqual(r.calls,0)
    def test_short_excess_body_uncommitted(self):
        for data in (b'x',b'x'*9):
            with self.subTest(length=len(data)),tempfile.TemporaryDirectory() as d:
                r=Response(data,0,8,len(self.data))
                with self.assertRaises(ValueError):acquire.download_file(self.row,Path(d),'"tiny-content"',open_url=lambda *a,**k:r,chunk_bytes=8)
                self.assertFalse((Path(d)/'tiny.gguf').exists())
                self.assertEqual(json.loads((Path(d)/'tiny.gguf.part.json').read_text())['committed'],0)
    def test_interruption_resume_and_dirty_tail(self):
        def interrupted(request,timeout):
            start,end=map(int,request.headers['Range'][6:].split('-'))
            if start>=8:raise OSError('interrupt second range')
            return Response(self.data[start:end+1],start,8,len(self.data))
        with self.assertRaises(OSError):self.download(open_url=interrupted)
        checkpoint=json.loads((self.root/'tiny.gguf.part.json').read_text());self.assertEqual(checkpoint['committed'],8)
        with (self.root/'tiny.gguf.part').open('ab') as f:f.write(b'crash-tail')
        result=self.download();self.assertEqual(self.requests[0][0],8);self.assertTrue(result['resumed'])
        self.assertEqual((self.root/'tiny.gguf').read_bytes(),self.data)
    def test_modified_prefix_is_preserved(self):
        def interrupted(request,timeout):
            if request.headers['Range']!='bytes=0-7':raise OSError('stop')
            return Response(self.data[:8],0,8,len(self.data))
        with self.assertRaises(OSError):self.download(open_url=interrupted)
        part=self.root/'tiny.gguf.part';part.write_bytes(b'changed!')
        with self.assertRaises(ValueError):self.download()
        self.assertEqual(part.read_bytes(),b'changed!')
    def test_unknown_part_and_wrong_checkpoint_preserved(self):
        part=self.root/'tiny.gguf.part';part.write_bytes(b'unknown')
        with self.assertRaises(ValueError):self.download()
        self.assertEqual(part.read_bytes(),b'unknown')
        part.unlink();self.download();(self.root/'tiny.gguf').rename(part)
        state=self.root/'tiny.gguf.part.json';d=json.loads(state.read_text());d['source']['revision']='other';state.write_text(json.dumps(d))
        with self.assertRaises(ValueError):self.download()
        self.assertEqual(part.read_bytes(),self.data)
    def test_existing_final_valid_or_corrupt(self):
        final=self.root/'tiny.gguf';final.write_bytes(self.data);r=self.download();self.assertTrue(r['existing_final_verified'])
        final.write_bytes(b'keep corrupted original')
        with self.assertRaises(ValueError):self.download()
        self.assertEqual(final.read_bytes(),b'keep corrupted original')
    def test_sha_failure_never_renames(self):
        original=self.row['lfs_sha256'];self.row['lfs_sha256']='0'*64
        with self.assertRaises(ValueError):self.download()
        self.assertFalse((self.root/'tiny.gguf').exists());self.assertEqual((self.root/'tiny.gguf.part').read_bytes(),self.data)
        self.row['lfs_sha256']=original
    def test_checkpoint_tmp_is_not_overwritten(self):
        tmp=self.root/'tiny.gguf.part.json.tmp';tmp.write_bytes(b'unknown checkpoint tmp')
        with self.assertRaises(ValueError):self.download()
        self.assertEqual(tmp.read_bytes(),b'unknown checkpoint tmp')
    def test_remaining_capacity_no_double_subtract(self):
        (self.root/'tiny.gguf.part').write_bytes(b'a'*8)
        budget=acquire.storage_snapshot(self.root,[self.row],free_bytes=100000000)
        self.assertEqual(budget['remaining_model_bytes'],len(self.data)-8)
        self.assertEqual(budget['free_after_planned_increment'],100000000-(len(self.data)-8)-acquire.METADATA_ALLOWANCE)
    def test_insufficient_capacity(self):
        with self.assertRaises(ValueError):acquire.storage_snapshot(self.root,[self.row],free_bytes=1)
    def test_duplicate_sources_rejected(self):
        with self.assertRaises(ValueError):acquire.validate_source_set(dict(files=[self.row,self.row]))
    def test_complete_receipt_rejects_missing_and_mutation(self):
        good=dict(index=1,path=str(self.root/'tiny.gguf'),bytes=self.row['bytes'],sha256=self.row['lfs_sha256'])
        with self.assertRaises(ValueError):acquire.validate_full_rows([self.row],[])
        with self.assertRaises(ValueError):acquire.validate_full_rows([self.row],[good,good])
        wrong=dict(good,sha256='0'*64)
        with self.assertRaises(ValueError):acquire.validate_full_rows([self.row],[wrong])
    def test_receipt_scope_and_derived_mutation_rejected(self):
        base=dict(schema='strata-t05-full-model/v1',complete=True,repo=acquire.REPO,revision=acquire.REVISION,
            destination=str(self.root),total_bytes=self.row['bytes'],t03_inputs=acquire.FIXED_INPUTS,
            code=acquire.code_bindings(),files=[],checks={'trunk_layers':40})
        source=dict(files=[self.row])
        with patch.object(acquire,'verify_model',return_value={'trunk_layers':40}):
            acquire.validate_receipt(base,self.root,source,{}, {})
            for key,value in [('complete',False),('revision','other'),('total_bytes',1),('checks',{'trunk_layers':0})]:
                with self.subTest(key=key),self.assertRaises(ValueError):
                    acquire.validate_receipt(dict(base,**{key:value}),self.root,source,{}, {})
    def test_missing_trunk_rejected(self):
        with self.assertRaises(ValueError):acquire.validate_trunk(set())
        with self.assertRaises(ValueError):acquire.validate_trunk({f'fake{i}' for i in range(1043)})
    def test_checkpoint_range_history_mutation(self):
        good=[dict(status=206,start=0,end=7,total=72,etag='"tiny-content"',content_length=8)]
        acquire.validate_ranges(good,8,72,'"tiny-content"')
        for key,value in [('status',200),('start',1),('end',8),('etag','wrong'),('total',73)]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                acquire.validate_ranges([dict(good[0],**{key:value})],8,72,'"tiny-content"')
    def test_interrupted_owned_checkpoint_body_recovers(self):
        def interrupted(request,timeout):
            if request.headers['Range']!='bytes=0-7':raise OSError('stop')
            return Response(self.data[:8],0,8,len(self.data))
        with self.assertRaises(OSError):self.download(open_url=interrupted)
        state_path=self.root/'tiny.gguf.part.json';state=json.loads(state_path.read_text())
        Path(str(state_path)+'.tmp').write_bytes(acquire.checkpoint_owner_prefix(state['source'])+b'"committed":')
        self.download();self.assertEqual((self.root/'tiny.gguf').read_bytes(),self.data)
        self.assertFalse(Path(str(state_path)+'.tmp').exists())
    def test_two_process_resume_cannot_truncate_active_writer(self):
        script='''import importlib.util,pathlib,json,sys,time,io
p,root,role=sys.argv[1:];root=pathlib.Path(root)
s=importlib.util.spec_from_file_location('t05',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
data=b'tiny-real-test-content\\x00\\xff'*3
row=dict(index=1,filename='UD-Q4_K_XL/tiny.gguf',bytes=len(data),lfs_sha256=m.hashlib.sha256(data).hexdigest())
class R(io.BytesIO):
 status=206
 def __init__(self,a,b):
  super().__init__(data[a:b+1]);self.headers={'Content-Range':f'bytes {a}-{b}/{len(data)}','Content-Length':str(b-a+1),'ETag':'"tiny-content"'}
def transport(req,timeout):
 a,b=map(int,req.headers['Range'][6:].split('-'));return R(a,b)
original=m.checkpoint
def pause(path,state):
 if state['committed']==16:
  (root/'ready').write_text('ready')
  until=time.monotonic()+15
  while not (root/'release').exists():
   if time.monotonic()>until:raise RuntimeError('release timeout')
   time.sleep(.01)
 original(path,state)
if role=='A':m.checkpoint=pause
try:m.download_file(row,root,'"tiny-content"',open_url=transport,chunk_bytes=8)
except ValueError as error:
 print(error);sys.exit(3)
'''
        writer=subprocess.Popen([sys.executable,'-B','-c',script,str(MODULE),str(self.root),'A'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            until=time.monotonic()+10
            while not (self.root/'ready').exists():
                if writer.poll() is not None or time.monotonic()>until:self.fail('writer did not reach checkpoint interleave')
                time.sleep(.01)
            part=self.root/'tiny.gguf.part';state=self.root/'tiny.gguf.part.json'
            self.assertEqual(part.stat().st_size,16);self.assertEqual(json.loads(state.read_text())['committed'],8)
            raw_before=part.read_bytes();state_before=state.read_bytes()
            second=subprocess.run([sys.executable,'-B','-c',script,str(MODULE),str(self.root),'B'],capture_output=True,text=True,timeout=10)
            self.assertEqual(second.returncode,3);self.assertIn('busy',second.stdout)
            self.assertEqual(part.read_bytes(),raw_before);self.assertEqual(state.read_bytes(),state_before)
            (self.root/'release').write_text('go');out,err=writer.communicate(timeout=10)
            self.assertEqual(writer.returncode,0,msg=out+err)
            self.assertEqual((self.root/'tiny.gguf').read_bytes(),self.data)
            self.assertFalse((self.root/'tiny.gguf.part.lock').exists())
        finally:
            if writer.poll() is None:writer.kill();writer.communicate()

if __name__=='__main__':unittest.main()
