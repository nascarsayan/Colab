"""Check legacy Drive relocation and preservation without privileged OS mounts."""
from pathlib import Path
import runpy
import tempfile
import types
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[1]/'src/drive_backend.py'
class DriveBackend(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.private=self.root/'private/drive';self.legacy=self.root/'content/drive'
        self.mounts=set();self.calls=[];self.fail=False;self.uncovered=False
        self.module=runpy.run_path(str(SCRIPT))
        self.addCleanup(patch.stopall)
        patch('os.path.ismount',side_effect=lambda p:Path(p) in self.mounts).start()
        patch('subprocess.run',side_effect=self.command).start()

    def command(self,args,**kwargs):
        self.calls.append(args)
        if self.fail:return types.SimpleNamespace(returncode=32,stderr='busy')
        self.private.rmdir();self.legacy.rename(self.private)
        self.legacy.mkdir()
        if self.uncovered:(self.legacy/'keep').write_text('local data')
        self.mounts.remove(self.legacy);self.mounts.add(self.private)
        return types.SimpleNamespace(returncode=0,stderr='')

    def prepare(self):return self.module['prepare'](self.private,self.legacy)
    def old_mount(self):
        (self.legacy/'MyDrive/Code').mkdir(parents=True)
        (self.legacy/'MyDrive/Code/keep').write_text('drive data')
        self.mounts.add(self.legacy)

    def test_existing_drive_moves_without_copying_or_remounting(self):
        self.old_mount()
        self.assertEqual(self.prepare(),'mounted')
        self.assertEqual(self.calls,[['mount','--move',str(self.legacy),str(self.private)]])
        self.assertFalse(self.legacy.exists())
        self.assertEqual((self.private/'MyDrive/Code/keep').read_text(),'drive data')
        self.assertEqual(self.prepare(),'mounted')
        self.assertEqual(len(self.calls),1)

    def test_files_uncovered_at_old_mountpoint_are_preserved(self):
        self.old_mount();self.uncovered=True
        self.assertEqual(self.prepare(),'mounted')
        self.assertEqual((self.legacy/'keep').read_text(),'local data')

    def test_fresh_runtime_requests_native_mount_without_creating_drive_files(self):
        self.assertEqual(self.prepare(),'needs-auth')
        self.assertFalse(self.private.exists());self.assertEqual(self.calls,[])

    def test_occupied_internal_location_is_not_overwritten(self):
        self.old_mount();self.private.mkdir(parents=True)
        (self.private/'keep').write_text('private data')
        with self.assertRaisesRegex(RuntimeError,'occupied'):self.prepare()
        self.assertEqual((self.private/'keep').read_text(),'private data')
        self.assertEqual(self.calls,[])

    def test_failed_move_leaves_original_drive_intact(self):
        self.old_mount();self.fail=True
        with self.assertRaisesRegex(RuntimeError,'Could not relocate'):self.prepare()
        self.assertEqual((self.legacy/'MyDrive/Code/keep').read_text(),'drive data')
        self.assertIn(self.legacy,self.mounts)
