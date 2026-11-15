"""Check real mount orchestration against controlled syscalls; no privileged mounts."""
import json
import os
from pathlib import Path
import runpy
import tempfile
import types
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[1]/'src/workspace_mount.py'
class Mount(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.content=self.root/'content';self.content.mkdir()
        self.backing=self.root/'private-drive';(self.backing/'MyDrive').mkdir(parents=True)
        self.registry=self.root/'private/workspaces.json'
        self.target=self.content/'Code'
        self.mounts={self.backing:self.backing};self.calls=[]
        self.module=runpy.run_path(str(SCRIPT))
        self.real_samefile=os.path.samefile
        self.addCleanup(patch.stopall)
        patch('os.path.ismount',side_effect=lambda p:Path(p) in self.mounts).start()
        patch('os.path.samefile',side_effect=lambda a,b:self.mounts.get(Path(a),Path(a))==Path(b)).start()
        patch('subprocess.run',side_effect=self.command).start()
        self.backings=(self.backing,)

    def command(self,args,**kwargs):
        self.calls.append(args)
        if args[0]=='mount':self.mounts[Path(args[-1])]=Path(args[-2])
        elif args[0]=='umount':self.mounts.pop(Path(args[-1]),None)
        return types.SimpleNamespace(returncode=0,stderr='')

    def prepare(self,drive='/content/drive/MyDrive/Code',target=None):
        self.module['prepare'](drive,str(target or self.target),content=self.content,backings=self.backings,registry=self.registry)

    def test_creates_only_selected_source_and_bind_mount_and_reuses_it(self):
        self.prepare()
        source=self.backing/'MyDrive/Code'
        self.assertTrue(source.is_dir())
        self.assertEqual(self.mounts[self.target],source)
        self.assertEqual(self.calls,[['mount','--bind',str(source),str(self.target)]])
        self.assertEqual(json.loads(self.registry.read_text())[str(self.target)]['source'],str(source))
        self.prepare()
        self.assertEqual(len(self.calls),1)

    def test_nested_drive_folder_has_direct_mount_target(self):
        target=self.content/'Work'
        self.prepare('/content/drive/MyDrive/Projects/Test',target)
        self.assertEqual(self.mounts[target],self.backing/'MyDrive/Projects/Test')

    def test_missing_backing_never_creates_temporary_workspace(self):
        self.mounts.clear()
        with self.assertRaisesRegex(RuntimeError,'Drive is not mounted'):self.prepare()
        self.assertFalse(self.target.exists())
        self.assertFalse((self.backing/'MyDrive/Code').exists())

    def test_nonempty_destination_and_symlinks_are_never_covered(self):
        self.target.mkdir();file=self.target/'precious';file.write_text('keep')
        with self.assertRaisesRegex(RuntimeError,'not an empty folder'):self.prepare()
        self.assertEqual(file.read_text(),'keep');self.assertEqual(self.calls,[])
        file.unlink();self.target.rmdir();self.target.symlink_to(self.backing/'MyDrive')
        with self.assertRaisesRegex(RuntimeError,'symlink'):self.prepare()
        self.assertEqual(self.calls,[])

    def test_source_symlink_cannot_create_folders_outside_drive(self):
        outside=self.root/'outside';outside.mkdir()
        (self.backing/'MyDrive/escape').symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError,'escapes'):self.prepare('/content/drive/MyDrive/escape/new')
        self.assertFalse((outside/'new').exists());self.assertEqual(self.calls,[])

    def test_nested_or_reserved_mount_path_is_rejected(self):
        for target in [self.content/'nested/Code',self.content/'drive',self.content/'.hidden']:
            with self.assertRaisesRegex(RuntimeError,'directly under'):self.prepare(target=target)
        self.assertEqual(self.calls,[])

    def test_unmanaged_mount_is_not_unmounted(self):
        self.target.mkdir();self.mounts[self.target]=self.backing/'elsewhere'
        with self.assertRaisesRegex(RuntimeError,'another mount'):self.prepare()
        self.assertEqual(self.calls,[])

    def test_stale_managed_bind_is_replaced_after_backing_changes(self):
        self.prepare()
        new=self.root/'new-drive';(new/'MyDrive').mkdir(parents=True)
        self.mounts.pop(self.backing);self.mounts[new]=new;self.backings=(new,)
        self.prepare()
        self.assertEqual([call[0] for call in self.calls],['mount','umount','mount'])
        self.assertEqual(self.mounts[self.target],new/'MyDrive/Code')

    def test_replaced_mount_is_not_mistaken_for_stale_managed_bind(self):
        self.prepare()
        metadata=json.loads(self.registry.read_text());metadata[str(self.target)]['identity']=[-1,-1]
        self.registry.write_text(json.dumps(metadata));self.mounts[self.target]=self.root/'unrelated'
        with self.assertRaisesRegex(RuntimeError,'replaced by another mount'):self.prepare()
        self.assertEqual(len(self.calls),1)
