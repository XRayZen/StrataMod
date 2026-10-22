import importlib.util
import json
import math
from pathlib import Path
import struct
import unittest
import numpy as np

HERE = Path(__file__).resolve().parent
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

class ReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.q = load('t09_q', HERE / 'q_reference.py')
        cls.scalar = load('t04_scalar', HERE.parent / 'numerics/reference.py')

    def test_literals(self):
        vectors = json.loads((HERE.parent / 'numerics/known-vectors.json').read_text(encoding='utf-8'))['decode']
        for v in vectors:
            actual = self.q.decode(v['type_id'], bytes.fromhex(v['hex']))
            expected = self.scalar.decode_block(v['type_id'], bytes.fromhex(v['hex']))
            self.assertEqual(len(actual), len(expected))
            for a, b in zip(actual, expected):
                if math.isnan(b): self.assertTrue(math.isnan(a))
                else: self.assertEqual(struct.pack('<f', a), struct.pack('<f', b), v['name'])

    def test_random_blocks(self):
        rng = np.random.default_rng(20261021)
        for kind, size in [(0,4),(8,34),(39,17),(43,33)]:
            for _ in range(64):
                raw = rng.integers(0,256,size,dtype=np.uint8).tobytes()
                actual = self.q.decode(kind, raw)
                expected = self.scalar.decode_block(kind, raw)
                for a,b in zip(actual,expected):
                    if math.isnan(b): self.assertTrue(math.isnan(a))
                    else: self.assertEqual(struct.pack('<f', a),struct.pack('<f', b))

    def test_ordered_runtime_literals(self):
        for case in self.q.boundaries():
            w,x = case['weights'],case['inputs']
            got = self.q.ordered(w,x)
            self.assertEqual(int(got.view(np.uint32)[0,0]),case['expected_bits'],case['name'])

    def test_full_k_scalar_holdout(self):
        for k in [256,2304,5120]:
            rng = np.random.default_rng(49217+k)
            w = (rng.integers(-8192,8193,(3,k)).astype(np.float32)/8192).astype(np.float32)
            x = (rng.integers(-8192,8193,(2,k)).astype(np.float32)/8192).astype(np.float32)
            got = self.q.ordered(w,x)
            for b in range(2):
                for r in range(3):
                    acc = 0.0
                    for j in range(k):
                        acc = self.scalar.fp32(acc+self.scalar.fp32(float(w[r,j])*float(x[b,j])))
                    self.assertEqual(struct.pack('<f',got[b,r]),struct.pack('<f',acc))

    def test_reject(self):
        for kind,raw in [(67,b''),(117,b''),(39,b'x'),(8,b'x'),(43,b'x'),(0,b'x')]:
            with self.assertRaises(ValueError): self.q.decode(kind,raw)
        with self.assertRaises(ValueError): self.q.ordered(np.zeros((1,3),np.float32),np.zeros((1,2),np.float32))
        with self.assertRaises(ValueError): self.q.ordered(np.array([[np.nan]],np.float32),np.ones((1,1),np.float32))

if __name__ == '__main__': unittest.main()
