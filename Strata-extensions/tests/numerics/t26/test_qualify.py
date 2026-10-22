"""T26 receipt adapter tests; no GPU or full payload hashing."""
import copy,json,unittest,hashlib,math
from pathlib import Path
import numpy as np
from qualify import compare_logits,validate_catalog,verify_refs,checked_logits,applicable_components
ROOT=Path(__file__).resolve().parents[4]
class QualificationTests(unittest.TestCase):
 def test_exact_teacher_forcing_and_unknown_terminal(self):
  q=np.zeros((3,129280),np.float32);q[0,37]=2;q[1,1024]=1
  result=compare_logits(q,q.copy(),[3,37,1024],[0,1,2],[37,1024,None],False)
  self.assertEqual(result['known_NLL_rows'],2);self.assertIsNone(result['target_NLL'][2]);self.assertEqual(result['max_abs'],0);self.assertEqual(result['KL'],[0,0,0])
 def test_numerical_and_semantic_mutations(self):
  q=np.zeros((3,129280),np.float32);cases=[]
  changed=q.copy();changed[2,1]=1;cases.append((changed,[3,37,1024],[0,1,2],[37,1024,None],False))
  nonfinite=q.copy();nonfinite[0,0]=np.nan;cases.append((nonfinite,[3,37,1024],[0,1,2],[37,1024,None],False))
  cases += [(q[:2],[3,37,1024],[0,1,2],[37,1024,None],False),(q[:,:-1],[3,37,1024],[0,1,2],[37,1024,None],False),(q,[True,37,1024],[0,1,2],[37,1024,None],False),(q,[3.,37,1024],[0,1,2],[37,1024,None],False),(q,[3,37,1024],[1,2,3],[37,1024,None],False),(q,[3,37,1024],[0,1,2],[3,37,None],False),(q,[3,37,1024],[0,1,2],[37,1024,None],True)]
  for args in cases:
   with self.subTest(case=str(args[1:])):
    with self.assertRaises(ValueError):compare_logits(q,*args)
 def test_original_asset_catalog_mutations(self):
  base=ROOT/'Strata-extensions';r=json.loads((base/'tests/artifact/full-model-receipt.json').read_text());i=json.loads((base/'tests/artifact/header-inventory.json').read_text());c=json.loads((base/'control/deepseek41.contract.json').read_text());self.assertEqual(validate_catalog(r,i,c)['tensors'],1043)
  for kind in ['missing','duplicate','LFS','revision','currentID','tokenizer','layout','family']:
   rr,ii,cc=copy.deepcopy((r,i,c))
   if kind=='missing':rr['files'].pop()
   elif kind=='duplicate':rr['files'][1]=rr['files'][0]
   elif kind=='LFS':rr['files'][0]['sha256']='0'*64
   elif kind=='revision':rr['revision']='unknown'
   elif kind=='currentID':rr['files'][0]['file_identity']['file_id']=True
   elif kind=='tokenizer':ii['shards'][0]['token_count']=1
   elif kind=='layout':next(x for x in ii['shards'] if x['tensors'])['tensors'][0]['type_id']=117
   else:cc['model']['family']='qwen'
   with self.subTest(case=kind):
    with self.assertRaises(ValueError):validate_catalog(rr,ii,cc)
 def test_fixed_native_Q_DLL_flags_bindings(self):
  directory=ROOT/'build-deepseek-t26/controlled-bindings';directory.mkdir(exist_ok=True)
  refs={}
  for name in ['EXE','Q','DLL','flags']:
   p=directory/(name+'.txt');p.write_text(name,encoding='utf-8');refs[name]=dict(path=str(p.relative_to(ROOT)),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
  self.assertEqual(set(verify_refs(refs)),set(refs))
  for name in refs:
   bad=copy.deepcopy(refs);bad[name]['sha256']='0'*64
   with self.assertRaises(ValueError):verify_refs(bad)
  for bad in [{}, {'EXE':dict(path='../outside',sha256='0'*64)}, {'EXE':dict(path=refs['EXE']['path'],sha256=True)}]:
   with self.assertRaises(ValueError):verify_refs(bad)
 def test_exact_file_length_including_partial_trailing_byte(self):
  path=ROOT/'build-deepseek-t26/controlled-logits.bin';raw=np.array([1,2],dtype='<f4').tobytes();path.write_bytes(raw);expected=hashlib.sha256(raw).hexdigest();self.assertEqual(checked_logits(path,8,expected).size,2)
  for wrong in [raw[:-1],raw+b'x',b'',raw[:4]+b'xxxx']:
   path.write_bytes(wrong)
   with self.assertRaises(ValueError):checked_logits(path,8,expected)
  path.write_bytes(raw)
 def test_large_common_logit_offset_retains_finite_NLL(self):
  q=np.full((3,129280),np.finfo(np.float32).max,np.float32);result=compare_logits(q,q.copy(),[3,37,1024],[0,1,2],[37,1024,None],False)
  for value in result['target_NLL'][:2]:self.assertAlmostEqual(value,math.log(129280),places=12)
 def test_wrong_component_scope_is_not_an_applicable_receipt(self):
  refs=json.loads(Path(__file__).with_name('contract.json').read_text())['fixed_inputs'];self.assertEqual(applicable_components(refs)['restored_values'],15360)
  for left,right in [('T25_restore','T25_helper'),('T20_branch','T20_CPU')]:
   wrong=copy.deepcopy(refs);wrong[left]=wrong[right]
   with self.assertRaises(ValueError):applicable_components(wrong)
if __name__=='__main__':unittest.main()
