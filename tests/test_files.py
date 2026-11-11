import contextlib
import hashlib
import io
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RPC = (ROOT / 'src/file_rpc.py').read_text()


def file_entry(data):
    return {'kind': 'file', 'sha256': hashlib.sha256(data).hexdigest(), 'mode': 0o644}


class Files(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        argv = ['files', RPC, 'socket', str(self.base / 'state'), 'session', 'sync',
                str(self.base / 'local'), '<>', 'colab:' + str(self.base / 'remote'), '0']
        with patch.object(sys, 'argv', argv):
            self.module = runpy.run_path(str(ROOT / 'src/files.py'), run_name='tests')
        self.globals = self.module['run'].__globals__
        def local_rpc(endpoint, request, **kwargs):
            return subprocess.Popen([sys.executable, '-c', RPC, json.dumps(request)], **kwargs)
        self.module['Endpoint'].ssh = local_rpc
        self.local = self.base / 'local'
        self.remote = self.base / 'remote'
        self.local.mkdir()
        self.remote.mkdir()

    def sync(self, direction='<>', dry=False):
        self.globals.update(DIRECTION=direction, DRY='1' if dry else '0')
        with contextlib.redirect_stdout(io.StringIO()):
            self.module['run']()

    def test_bidirectional_updates_and_conflicts_preserve_both(self):
        (self.local / 'a').write_bytes(b'local')
        (self.remote / 'b').write_bytes(b'remote')
        self.sync()
        self.assertEqual((self.remote / 'a').read_bytes(), b'local')
        self.assertEqual((self.local / 'b').read_bytes(), b'remote')
        (self.remote / 'a').write_bytes(b'remote update')
        self.sync()
        self.assertEqual((self.local / 'a').read_bytes(), b'remote update')
        (self.local / 'a').write_bytes(b'left edit')
        (self.remote / 'a').write_bytes(b'right edit')
        (self.local / 'new').write_bytes(b'must not be copied on conflict')
        with self.assertRaisesRegex(RuntimeError, 'Sync conflicts'):
            self.sync()
        self.assertEqual((self.local / 'a').read_bytes(), b'left edit')
        self.assertEqual((self.remote / 'a').read_bytes(), b'right edit')
        self.assertFalse((self.remote / 'new').exists())

    def test_recursive_binary_names_and_empty_directories(self):
        (self.local / 'empty').mkdir()
        (self.local / 'nested').mkdir()
        data = bytes(range(256)) * 5000
        name = "nested/quote's space\nfile.bin"
        (self.local / name).write_bytes(data)
        self.sync('>')
        self.assertEqual((self.remote / name).read_bytes(), data)
        self.assertTrue((self.remote / 'empty').is_dir())
        self.sync('<>')

    def test_reverse_sync_and_no_deletion(self):
        (self.remote / 'x').write_bytes(b'value')
        (self.local / 'extra').write_bytes(b'keep')
        self.sync('<')
        self.assertEqual((self.local / 'x').read_bytes(), b'value')
        self.assertTrue((self.local / 'extra').exists())
        self.sync()
        (self.local / 'x').unlink()
        self.sync()
        self.assertEqual((self.local / 'x').read_bytes(), b'value')

    def test_dry_run_does_not_copy_or_advance_baseline(self):
        (self.local / 'a').write_bytes(b'new')
        self.sync(dry=True)
        self.assertFalse((self.remote / 'a').exists())
        self.assertEqual(list((self.base / 'state/sync').glob('*.json')), [])

    def test_failed_checksum_keeps_destination_and_removes_temp(self):
        path = self.local / 'file'
        path.write_bytes(b'old')
        rpc = self.globals['namespace']
        expected = rpc['entry'](path)
        with self.assertRaisesRegex(RuntimeError, 'Checksum mismatch'):
            rpc['commit'](str(self.local), 'file', file_entry(b'complete'), expected, io.BytesIO(b'partial'))
        self.assertEqual(path.read_bytes(), b'old')
        self.assertEqual(list(self.local.glob('.Colab-*')), [])

    def test_concurrent_destination_edit_is_not_overwritten(self):
        path = self.local / 'file'
        path.write_bytes(b'newer')
        rpc = self.globals['namespace']
        with self.assertRaisesRegex(RuntimeError, 'Destination changed'):
            rpc['commit'](str(self.local), 'file', file_entry(b'new'), file_entry(b'old'), io.BytesIO(b'new'))
        self.assertEqual(path.read_bytes(), b'newer')

    def test_symlink_and_type_conflicts_fail_before_writing(self):
        (self.local / 'link').symlink_to(self.remote, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Symlinks'):
            self.sync()
        (self.local / 'link').unlink()
        (self.local / 'same').write_bytes(b'file')
        (self.remote / 'same').mkdir()
        with self.assertRaisesRegex(RuntimeError, 'Sync conflicts'):
            self.sync()

    def test_first_sync_conflicting_files_need_explicit_resolution(self):
        (self.local / 'a').write_bytes(b'one')
        (self.remote / 'a').write_bytes(b'two')
        with self.assertRaisesRegex(RuntimeError, 'Sync conflicts'):
            self.sync()

    def test_unmounted_drive_never_becomes_an_ephemeral_destination(self):
        rpc = self.globals['namespace']
        with patch('os.path.ismount', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'Google Drive is not mounted'):
                rpc['safe_path']('/content/./drive/MyDrive/data')

    def test_successful_reverse_sync_records_original_endpoint_direction(self):
        (self.remote / 'a').write_bytes(b'remote')
        self.sync('<')
        records = list((self.base / 'state/sync').glob('*.target.json'))
        self.assertEqual(len(records), 1)
        record = json.loads(records[0].read_text())
        self.assertEqual(record['left'], str(self.local))
        self.assertEqual(record['right'], 'colab:' + str(self.remote))
        self.assertEqual(record['direction'], '<')
        self.assertEqual(record['session'], 'session')
        self.assertIn('last_success_utc', record)

    def test_orphaned_staging_files_are_not_synced(self):
        (self.local / '.Colab-interrupted').write_bytes(b'partial')
        (self.local / '.hidden-user-file').write_bytes(b'complete')
        self.sync('>')
        self.assertFalse((self.remote / '.Colab-interrupted').exists())
        self.assertEqual((self.remote / '.hidden-user-file').read_bytes(), b'complete')

    def test_copy_file_into_directory(self):
        (self.local / 'a').write_bytes(b'copied')
        self.globals.update(ACTION='cp', LEFT=str(self.local / 'a'), DIRECTION='>')
        self.sync('>')
        self.assertEqual((self.remote / 'a').read_bytes(), b'copied')


if __name__ == '__main__':
    unittest.main()
