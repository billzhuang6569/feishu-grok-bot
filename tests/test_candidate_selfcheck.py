"""In-process candidate checks using only temporary synthetic trees."""
import hashlib
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tools/candidate_selfcheck.py'
if not SOURCE.is_file():
    SOURCE = ROOT / 'tests/selfcheck.py'
    assert 'candidate_inventory_mismatch' in SOURCE.read_text()
CHECK = runpy.run_path(str(SOURCE))['check_candidate']


class CandidateSelfcheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.content('safe synthetic content')

    def content(self, text):
        data = text.encode()
        (self.root / 'sample.txt').write_bytes(data)
        (self.root / 'ALLOWLIST.json').write_text(json.dumps({
            'sample.txt': hashlib.sha256(data).hexdigest()}))

    def test_export_without_git(self):
        self.assertEqual(CHECK(self.root), 1)

    def test_root_git_directory_is_never_entered_or_read(self):
        git = self.root / '.git'
        git.mkdir()
        (git / 'opaque').write_text('synthetic metadata')
        original_iter = Path.iterdir
        original_read = Path.open
        def guarded_iter(path):
            self.assertNotEqual(path, git)
            return original_iter(path)
        def guarded_open(path, *args, **kwargs):
            self.assertNotIn(git, (path, *path.parents))
            return original_read(path, *args, **kwargs)
        with patch.object(Path, 'iterdir', guarded_iter), patch.object(Path, 'open', guarded_open):
            self.assertEqual(CHECK(self.root), 1)

    def test_root_git_file_is_never_read(self):
        git = self.root / '.git'
        git.write_text('gitdir: /synthetic/gitdir\n')
        original = Path.open
        def guarded(path, *args, **kwargs):
            self.assertNotEqual(path, git)
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', guarded):
            self.assertEqual(CHECK(self.root), 1)

    def test_runtime_garbage(self):
        for name in ('subdir/.git', '__pycache__', '.venv', 'venv'):
            with self.subTest(name=name):
                p = self.root / name
                p.mkdir(parents=True)
                with self.assertRaisesRegex(AssertionError, 'candidate_runtime_garbage'):
                    CHECK(self.root)
                p.rmdir()

    def test_extra_file(self):
        (self.root / 'extra').write_text('synthetic')
        with self.assertRaisesRegex(AssertionError, 'candidate_inventory_mismatch'):
            CHECK(self.root)

    def test_symlinks(self):
        for name in ('.git', 'link'):
            with self.subTest(name=name):
                p = self.root / name
                p.symlink_to(self.root / 'sample.txt')
                with self.assertRaisesRegex(AssertionError, 'candidate_symlink'):
                    CHECK(self.root)
                p.unlink()

    def test_static_scans(self):
        for text, error in (
            ('ou_' + 'a' * 16, 'identity_shape'),
            ('-----BEGIN ' + 'PRIVATE KEY-----', 'private_key'),
            ('ghp_' + 'a' * 20, 'credential_shape'),
        ):
            with self.subTest(error=error):
                self.content(text)
                with self.assertRaisesRegex(AssertionError, error):
                    CHECK(self.root)
