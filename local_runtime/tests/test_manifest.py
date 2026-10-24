import copy
import json
from pathlib import Path
import tempfile
import time
import subprocess
import unittest
from unittest.mock import patch

from local_runtime import manifest


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'profiles/strata-baseline.json'
        self.config.parent.mkdir()
        self.config.write_text('{"arm":"baseline"}', encoding='utf-8')
        self.source = self.root / 'server.py'
        self.source.write_text('# server', encoding='utf-8')
        self.path = self.root / 'manifest.json'
        self.value = dict(version=1, root=str(self.root), arm='baseline', config=str(self.config),
                          config_sha256=manifest.digest(self.config), expires_at=time.time()+120,
                          source_files={str(self.source):manifest.digest(self.source)},
                          suite='smoke', max_posts=1, max_tokens=32, max_starts=1)
        self.semantic = patch.object(manifest, 'validate_semantics', return_value={})
        self.semantic.start()
        self.addCleanup(self.semantic.stop)

    def save(self):
        self.path.write_text(json.dumps(self.value), encoding='utf-8')
        return manifest.digest(self.path)

    def check(self):
        return manifest.verify(self.path, self.save(), root=self.root)

    def test_valid_bound_manifest(self):
        self.assertEqual(self.check()['arm'], 'baseline')

    def test_manifest_byte_change_is_rejected(self):
        approved = self.save()
        self.path.write_text(self.path.read_text()+' ', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'manifest'):
            manifest.verify(self.path, approved, root=self.root)

    def test_config_change_is_rejected(self):
        approved = self.save()
        self.config.write_text('{"arm":"other"}', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'config'):
            manifest.verify(self.path, approved, root=self.root)

    def test_source_change_is_rejected(self):
        approved = self.save()
        self.source.write_text('# changed', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'source'):
            manifest.verify(self.path, approved, root=self.root)

    def test_outside_root_config_is_rejected(self):
        self.value['config'] = str(self.root.parent / 'outside.json')
        with self.assertRaisesRegex(RuntimeError, 'root'):
            self.check()

    def test_expiry_and_excess_limits_are_rejected(self):
        original = copy.deepcopy(self.value)
        for key, value in [('expires_at',time.time()-1),('max_posts',2),('max_tokens',33),('max_starts',2)]:
            self.value = dict(original, **{key:value})
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                self.check()

    def test_junction_ancestor_config_is_rejected(self):
        link = self.root/'joined-profiles'
        quote = lambda value: "'"+str(value).replace("'","''")+"'"
        command = 'New-Item -ItemType Junction -Path '+quote(link)+' -Target '+quote(self.config.parent)+' | Out-Null'
        subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',command],check=True,capture_output=True)
        self.value['config'] = str(link/self.config.name)
        with self.assertRaisesRegex(RuntimeError, 'link'):
            self.check()


if __name__ == '__main__':
    unittest.main()
