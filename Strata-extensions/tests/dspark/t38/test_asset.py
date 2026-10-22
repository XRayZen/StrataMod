import json,os,pathlib,struct,tempfile,unittest
from test_session import invoke
HERE=pathlib.Path(__file__).resolve().parent
WORK=pathlib.Path(os.environ.get('T38_WORK_ROOT',str(HERE.parents[3])))
PREFIX=WORK/'build-deepseek-t37/reference-source/luce-draft.prefix.bin'
class AssetTests(unittest.TestCase):
    def test_fixed_prefix(self):
        r=invoke('asset',PREFIX,7965746848)
        self.assertEqual((r['tensors'],r['data_start'],r['file_bytes']),(79,7296,7965746848))
        self.assertEqual(r['types'],{'0':36,'1':9,'8':25,'39':9})
    def test_prefix_and_schema_negatives(self):
        raw=PREFIX.read_bytes()
        for name,data,size in [('magic',b'BAD!'+raw[4:],7965746848),('short',raw[:31],7965746848),('version',raw[:4]+struct.pack('<I',4)+raw[8:],7965746848),('size',raw,7965746847),('shape',raw.replace(b'dflash.dspark.confidence.weight',b'dflash.dspark.confidence.weighX'),7965746848)]:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as tmp:
                p=pathlib.Path(tmp)/'prefix';p.write_bytes(data);invoke('asset',p,size,ok=False)
    def test_actual_artifact_stat_and_bounded_spans(self):
        receipt=json.loads((WORK/'build-deepseek-t37/artifact-receipt.json').read_text(encoding='utf-8'))
        p=pathlib.Path(receipt['file']['path']);self.assertEqual(p.stat().st_size,7965746848)
        r=invoke('span',PREFIX,p,'dflash.dspark.confidence.weight',0,0,1,10752)
        self.assertEqual(r['bytes'],10752)
        for params in [('dflash.dspark.confidence.weight',0,0,2,21504),('blk.0.ffn_gate_exps.weight',128,0,1,2720),('blk.0.ffn_gate_exps.weight',0,0,1,2719)]:invoke('span',PREFIX,p,*params,ok=False)
if __name__=='__main__':unittest.main()

