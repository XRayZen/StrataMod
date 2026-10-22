"""HIP multiple-image request contracts, synthetic bytes/SVE only; no image decoder/GPU/HTTP."""
import contextlib
import copy
import hashlib
import io
from pathlib import Path
import struct
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from serve import server as s
from serve.frontend import ChatTemplate


class HipMulti(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.vision=s.Vision.__new__(s.Vision)
        self.vision.__dict__.update(hip_required=True,cleanup_pending=False,stopped=False,dir=Path(self.temp.name),
            cache={},lock=threading.Lock(),n_embd=2560,max_tokens=300,encode_timeout=60,encode_peak_s=0,
            elastic=False,proc=SimpleNamespace(stdin=io.StringIO(),poll=lambda:None))
        self.vision.checked_image=lambda data:data
        self.commands=[];self.bad_at=None
        def read(timeout,what,cancel=None):
            command=self.vision.proc.stdin.getvalue().splitlines()[-1];self.commands.append(command)
            if self.bad_at==len(self.commands):raise RuntimeError('encoder timeout')
            _,src,out=command.split();data=(self.vision.dir/src).read_bytes();n=data[0]
            nx=2 if n%2==0 else 1;ny=n//nx
            (self.vision.dir/out).write_bytes(struct.pack('<5i',0x31455653,n,nx,ny,2560)+struct.pack('<f',float(n))*n*2560)
            return f'OK {n} {nx} {ny} 1\n'
        self.vision._readline=read
        self.loads=[]
        def load(src,max_bytes=None,**kwargs):
            self.loads.append(src)
            if src=='bad':raise ValueError('ordinary unreadable source')
            return bytes([int(src)])+b'opaque-synthetic-bytes'
        self.loadpatch=patch.object(s.Vision,'load',side_effect=load);self.loadpatch.start();self.addCleanup(self.loadpatch.stop)
        tok=s.ByteTokenizer()
        self.service=s.Service(s.MockEngine(tok,'ok',max_context=262144),tok,
            ChatTemplate(s.ROOT/'serve/chat_template.jinja'),vision=self.vision)

    def messages(self,sources,role='user'):
        return [{'role':role,'content':[{'type':'image','source':src} for src in sources]}]

    def prepare(self,messages,**kw):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.service.prepare(messages,None,{},16,**kw)

    def test_two_four_history_duplicate_order_and_combined_records(self):
        messages=self.messages(['2','3'])+self.messages(['4','2'])
        ids,_,_=self.prepare(messages)
        expected=b''.join(self.vision.cache[hashlib.sha256(bytes([int(src)])+b'opaque-synthetic-bytes').hexdigest()[:32]][0].read_bytes()
                          for src in ['2','3','4','2'])
        self.assertEqual(Path(self.service.embeddings.path).read_bytes(),expected)
        self.assertEqual(ids.count(self.service.tok.encode(s.IMAGE_PAD,parse_special=True)[0]),11)
        self.assertEqual(len(self.commands),3)
        self.assertEqual(self.service.embeddings.keys[0],self.service.embeddings.keys[3])
        self.service.drop_embeddings()
        self.assertFalse(list(self.vision.dir.glob('req-*.sve')))

    def test_tool_prepass_fatal_second_encoder_failure_is_not_a_note(self):
        self.bad_at=2;messages=self.messages(['2','3','4'],role='tool')
        with self.assertRaises(s.ImageRequestFatal):self.prepare(messages)
        self.assertEqual(len(self.commands),2)
        self.assertTrue(all(item['type']=='image' for item in messages[0]['content']))
        self.assertFalse(list(self.vision.dir.glob('*.img')))
        self.assertFalse(list(self.vision.dir.glob('req-*.sve')))

    def test_ordinary_tool_source_failure_stays_note_and_other_image_survives(self):
        messages=self.messages(['bad','2'],role='tool')
        self.prepare(messages)
        self.assertEqual(messages[0]['content'][0]['type'],'text')
        self.assertEqual(len(self.commands),1)
        self.service.drop_embeddings()

    def test_tool_prepass_acquires_each_source_once_without_new_total_cap(self):
        self.prepare(self.messages(['2','3','2'],role='tool'))
        self.assertEqual(self.loads,['2','3'])
        request=self.service.embeddings.image_request
        self.assertEqual(request.source_bytes,2*len(b'\x02opaque-synthetic-bytes'))
        self.assertEqual(request.fetched,{})
        self.service.drop_embeddings()

    def test_feature_telemetry_counts_duplicate_occurrences_without_new_cap(self):
        self.prepare(self.messages(['2','2']))
        request=self.service.embeddings.image_request
        self.assertEqual(request.feature_bytes,2*(20+2*2560*4))
        self.assertEqual(len(self.commands),1)
        self.service.drop_embeddings()

    def test_ordinary_failed_fetches_do_not_add_a_new_aggregate_deadline(self):
        clock=[0.]
        def slow(*args,**kwargs):clock[0]+=200;raise ValueError('ordinary URL failure')
        with patch.object(s.time,'monotonic',side_effect=lambda:clock[0]),patch.object(s.Vision,'load',side_effect=slow):
            self.prepare(self.messages(['2','3','4'],role='tool'))
        self.assertEqual(clock[0],600)
        self.assertEqual(self.commands,[])

    def test_cancel_and_bad_cached_sve_are_fatal_before_next_encode(self):
        cancel=threading.Event();cancel.set()
        with self.assertRaises(s.ClientGone):self.prepare(self.messages(['2','3']),cancel=cancel)
        self.prepare(self.messages(['2']));self.service.drop_embeddings()
        path=next(iter(self.vision.cache.values()))[0];path.write_bytes(b'bad')
        with self.assertRaises(s.ImageRequestFatal):self.prepare(self.messages(['2','3']))
        self.assertEqual(len(self.commands),1)

    def test_metadata_audit_omits_source_and_data_but_keeps_occurrence_order(self):
        captured=io.StringIO()
        with contextlib.redirect_stdout(captured):self.service.prepare(self.messages(['2','3','2']),None,{},16)
        output=captured.getvalue()
        self.assertNotIn('opaque-synthetic-bytes',output)
        self.assertIn('combined_sha256',output)
        self.assertIn('"index": 2',output)
        self.service.drop_embeddings()

    def test_configured_token_cap_and_ready_width_remain_authoritative(self):
        self.vision.max_tokens=400;self.vision.n_embd=8
        request=s.HipImageRequest(self.messages(['2']),None,self.vision)
        path=self.vision.dir/'configured.sve'
        path.write_bytes(struct.pack('<5i',0x31455653,400,20,20,8)+struct.pack('<f',1.)*400*8)
        with contextlib.redirect_stdout(io.StringIO()):request.encoded(0,path,400,False,b'opaque')
        self.assertEqual(request.rows[0]['width'],8)
        for n,width in [(401,8),(400,9)]:
            path.write_bytes(struct.pack('<5i',0x31455653,n,1,n,width)+struct.pack('<f',1.)*n*width)
            with self.subTest(n=n,width=width),self.assertRaises(s.ImageRequestFatal):request.encoded(0,path,n,False,b'opaque')
        request.release_prepare()

    def test_nth_invalid_sve_is_fatal_and_removes_only_failed_temporary(self):
        original=self.vision._readline
        def corrupt(*args,**kwargs):
            line=original(*args,**kwargs)
            if len(self.commands)==2:
                out=self.vision.dir/self.commands[-1].split()[2]
                data=bytearray(out.read_bytes());data[20:24]=struct.pack('<f',float('nan'));out.write_bytes(data)
            return line
        self.vision._readline=corrupt
        with self.assertRaises(s.ImageRequestFatal):self.prepare(self.messages(['2','3','4'],role='tool'))
        self.assertEqual(len(self.commands),2)
        self.assertEqual(len(self.vision.cache),1)
        self.assertEqual(len(list(self.vision.dir.glob('*.sve'))),1)
        self.assertFalse(list(self.vision.dir.glob('*.img')))
        self.assertEqual(self.vision.request_pins,{})

    def test_mid_prepare_cancel_does_not_encode_next_image(self):
        cancel=threading.Event();original=self.vision._readline
        def cancel_after_first(*args,**kwargs):
            result=original(*args,**kwargs);cancel.set();return result
        self.vision._readline=cancel_after_first
        with self.assertRaises(s.ClientGone):self.prepare(self.messages(['2','3']),cancel=cancel)
        self.assertEqual(len(self.commands),1)
        self.assertFalse(list(self.vision.dir.glob('*.img')))
        self.assertFalse(list(self.vision.dir.glob('req-*.sve')))

    def test_context_and_literal_markers_preserve_original_semantics(self):
        messages=self.messages(['2','3'])
        messages[0]['content'].insert(0,{'type':'text','text':'literal <|image_pad|> in documentation'})
        ids,_,_=self.prepare(messages)
        self.assertEqual(ids.count(self.service.tok.encode(s.IMAGE_PAD,parse_special=True)[0]),5)
        self.service.drop_embeddings()
        self.service.engine.max_context=32
        with self.assertRaisesRegex(ValueError,'context'):self.prepare(messages)
        self.assertFalse(list(self.vision.dir.glob('req-*.sve')))
        self.assertEqual(self.vision.request_pins,{})

    def test_pinned_prior_request_cache_is_not_evicted_before_combination(self):
        request=s.HipImageRequest(self.messages(['2']),None,self.vision)
        with contextlib.redirect_stdout(io.StringIO()):first,_=self.vision.encode('2',request=request,occurrence=0)
        for index in range(65):
            path=self.vision.dir/f'dummy-{index}.sve';path.write_bytes(b'test-only')
            self.vision.cache[f'dummy-{index}']=(path,1)
        self.vision.encode('3')
        self.assertTrue(first.exists())
        request.release_prepare()
        self.assertEqual(self.vision.request_pins,{})

    def test_secondary_cleanup_failure_preserves_original_and_unproven_path(self):
        original=self.service.resolve_prefix
        def fail(*args,**kwargs):raise ValueError('original prefix failure')
        self.service.resolve_prefix=fail
        actual_unlink=Path.unlink
        def refuse_combined(path,*args,**kwargs):
            if path.name.startswith('req-'):raise PermissionError('combined is still held')
            return actual_unlink(path,*args,**kwargs)
        with patch.object(Path,'unlink',new=refuse_combined):
            with self.assertRaisesRegex(ValueError,'original prefix failure') as caught:
                self.prepare(self.messages(['2','3']),req={'strata_prefix':{}})
        self.assertIn('PermissionError',' '.join(caught.exception.__notes__))
        self.assertTrue(Path(self.service.embeddings.path).exists())
        self.assertEqual(self.vision.request_pins,{})
        self.service.resolve_prefix=original
        self.service.drop_embeddings()
        self.assertFalse(list(self.vision.dir.glob('req-*.sve')))


if __name__=='__main__':unittest.main(verbosity=2)
