"""Git identity stays inside the separately approved experiment manifest."""
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from local_runtime import manifest as m


class GitRevisionTests(unittest.TestCase):
    def revision(self, head=None, tree='1' * 40):
        return dict(baseline=m.HEAD, head=head or m.HEAD, tree=tree)

    def test_legacy_requires_the_original_head(self):
        with patch.object(m, 'git_revision', return_value=self.revision()):
            m.require_git_revision({})
        with patch.object(m, 'git_revision', return_value=self.revision('2' * 40)):
            with self.assertRaises(RuntimeError):
                m.require_git_revision({})

    def test_new_revision_requires_exact_approved_baseline_head_and_tree(self):
        approved = self.revision('2' * 40)
        with patch.object(m, 'git_revision', return_value=approved):
            m.require_git_revision(dict(source_revision=dict(approved)))
            for key in ('baseline', 'head', 'tree'):
                changed = dict(approved, **{key: '3' * 40})
                with self.subTest(key=key), self.assertRaises(RuntimeError):
                    m.require_git_revision(dict(source_revision=changed))

    def test_git_observation_requires_baseline_ancestry(self):
        with patch.object(m.subprocess, 'check_output', side_effect=['2' * 40 + '\n', '1' * 40 + '\n']), \
                patch.object(m.subprocess, 'run') as run:
            self.assertEqual(m.git_revision(), self.revision('2' * 40))
            args = run.call_args.args[0]
            self.assertEqual(args[-4:], ['merge-base', '--is-ancestor', m.HEAD, '2' * 40])
            self.assertTrue(run.call_args.kwargs['check'])
        with patch.object(m.subprocess, 'check_output', side_effect=['2' * 40, '1' * 40]), \
                patch.object(m.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['git'])):
            with self.assertRaises(RuntimeError):
                m.git_revision()

    def test_git_failure_or_malformed_identity_is_rejected(self):
        with patch.object(m.subprocess, 'check_output', side_effect=OSError('unavailable')):
            with self.assertRaises(RuntimeError):
                m.git_revision()
        for output in ('', 'not-a-sha', '1' * 39):
            with self.subTest(output=output), patch.object(m.subprocess, 'check_output', return_value=output):
                with self.assertRaises(RuntimeError):
                    m.git_revision()

    def test_actual_existing_checkout_is_an_exact_baseline_descendant(self):
        actual = m.git_revision()
        self.assertEqual(actual['baseline'], m.HEAD)
        self.assertEqual(len(actual['head']), 40)
        self.assertEqual(len(actual['tree']), 40)
        m.require_git_revision(dict(source_revision=actual))

    def test_real_temporary_git_refs_tree_and_dirty_source_fail_closed(self):
        # Reuse existing official objects, without creating a commit or touching
        # a publication ref. Only this temporary repository's refs change.
        def git(root, *args):
            return subprocess.check_output(['git', '--no-optional-locks', '-C', str(root), *args],
                                           text=True, stderr=subprocess.PIPE).strip()
        original=m.ROOT
        common=git(original,'rev-parse','--path-format=absolute','--git-common-dir')
        parent=git(original,'rev-parse',m.HEAD+'^')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            subprocess.run(['git','init','--quiet',str(root)],check=True,capture_output=True)
            (root/'.git/objects/info/alternates').write_text((Path(common)/'objects').as_posix()+'\n',encoding='utf-8',newline='\n')
            git(root,'update-ref','HEAD',m.HEAD)
            with patch.object(m,'ROOT',root):
                exact=m.git_revision()
                m.require_git_revision({})
                m.require_git_revision(dict(source_revision=exact))
                for key in ('head','tree','baseline'):
                    with self.subTest(key=key),self.assertRaises(RuntimeError):
                        m.require_git_revision(dict(source_revision=dict(exact,**{key:'f'*40})))
                source=root/'module.py';source.write_text('# original\n',encoding='utf-8')
                expected={str(source):m.digest(source)}
                value=dict(root=str(root),arm='baseline',suite='smoke',memory_budget=m.memory_budget('smoke'),
                           source_revision=exact,source_files=expected)
                source.write_text('# dirty changed source\n',encoding='utf-8')
                with patch.object(m,'source_files',side_effect=lambda:{str(source):m.digest(source)}):
                    with self.assertRaisesRegex(RuntimeError,'source inventory'):
                        m.validate_semantics(value,verify_assets=False)
                git(root,'update-ref','HEAD',parent)
                with self.assertRaises(RuntimeError):m.require_git_revision({})
                with self.assertRaises(RuntimeError):m.require_git_revision(dict(source_revision=exact))
                # Exercise a genuine existing descendant, with only the test's
                # baseline changed. The production baseline constant is intact.
                with patch.object(m,'HEAD',parent):
                    git(root,'update-ref','HEAD',exact['head'])
                    descendant=m.git_revision()
                    m.require_git_revision(dict(source_revision=descendant))
                    git(root,'update-ref','HEAD',parent)
                    with self.assertRaises(RuntimeError):
                        m.require_git_revision(dict(source_revision=descendant))


if __name__ == '__main__':
    unittest.main()
