"""Checks real native fixture evidence; this does not mirror graph implementation."""
import json
import hashlib
from pathlib import Path
import unittest

class NativeEvidence(unittest.TestCase):
    def test_contract(self):
        root=Path(__file__).resolve().parents[3]
        proof=json.loads((root/'build-deepseek-t39/host-markerprep-r2/verification.json').read_text(encoding='utf-8'))
        for binding in proof['bindings']+[proof['recipe'],proof['artifact']]:
            source=Path(binding['path'])
            self.assertEqual(source.stat().st_size,binding['bytes'])
            with source.open('rb') as stream:self.assertEqual(hashlib.file_digest(stream,'sha256').hexdigest(),binding['sha256'])
        self.assertEqual(proof['exit'],0)
        self.assertEqual(proof['host']['exit'],0)
        native=json.loads(proof['host']['stdout'])
        self.assertGreaterEqual(native['assertions'],60)
        self.assertFalse(native['GPU_executed'])
        self.assertFalse(native['actual_application'])

if __name__=='__main__':unittest.main()
