"""Safety checks for the disposable-host lifecycle harness."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from check_document_lifecycle import Host, tree_snapshot


class DocumentLifecycleTests(unittest.TestCase):
    def test_snapshot_detects_state_replacement_and_added_backups(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / 'state.json'
            state.write_bytes(b'original')
            before = tree_snapshot([root])
            state.write_bytes(b'replaced')
            self.assertNotEqual(tree_snapshot([root]), before)
            state.write_bytes(b'original')
            (root / 'extra-backup').mkdir()
            self.assertNotEqual(tree_snapshot([root]), before)
            (root / 'extra-backup').rmdir()
            state.unlink()
            self.assertNotEqual(tree_snapshot([root]), before)

    def test_snapshot_refuses_symlinks(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / 'file'
            target.write_bytes(b'preserve')
            try:
                (root / 'link').symlink_to(target)
            except OSError:
                self.skipTest('symlink creation unavailable')
            with self.assertRaisesRegex(AssertionError, 'symlink'):
                tree_snapshot([root])
            self.assertEqual(target.read_bytes(), b'preserve')

    def test_macos_cleanup_preserves_changed_or_unowned_state(self):
        with TemporaryDirectory() as temporary, patch('check_document_lifecycle.platform.system', return_value='Darwin'):
            root = Path(temporary) / 'application-data'
            root.mkdir()
            state = root / 'state.json'
            state.write_bytes(b'original')
            host = Host.__new__(Host)
            host.roots = [root]
            host.owned_roots = []
            host.snapshot = {}
            host.clean()  # failed preflight must never delete existing state
            self.assertEqual(state.read_bytes(), b'original')
            host.owned_roots = [root]
            host.snapshot = tree_snapshot([root])
            state.write_bytes(b'external change')
            with self.assertRaisesRegex(AssertionError, 'preserving changed'):
                host.clean()
            self.assertEqual(state.read_bytes(), b'external change')
            state.write_bytes(b'original')
            host.clean()
            self.assertFalse(os.path.lexists(root))
