"""Test actual inventory and delete helpers against a fake SDK, without cloud side effects."""
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import types
import unittest
import uuid
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
class Inventory(unittest.TestCase):
    def invoke(self,name='',unknown=False):
        with tempfile.TemporaryDirectory() as temp:
            profile=Path(temp)
            ident=uuid.uuid5(uuid.NAMESPACE_URL,'trainer').hex
            workspace=profile/'workspaces';workspace.mkdir()
            (workspace/(ident+'.json')).write_text(json.dumps({'drive_path':'/content/drive/MyDrive/Projects','local_dir':'/pc/project'}))
            drive=profile/'drive';drive.mkdir();(drive/(ident+'.enabled')).touch()
            sync=profile/'sync';sync.mkdir()
            (sync/'pair.target.json').write_text(json.dumps({'session':'trainer','left':'/pc/data','right':'colab:/content/data','direction':'<>','last_success_utc':'today'}))
            session=types.SimpleNamespace(endpoint='gpu-endpoint',running=None,token='must-not-leak')
            assignment=types.SimpleNamespace(endpoint='gpu-endpoint',accelerator=types.SimpleNamespace(value='T4'),variant=types.SimpleNamespace(name='GPU'),machine_shape=types.SimpleNamespace(name='STANDARD'))
            assignments=[assignment]
            if unknown:assignments.append(types.SimpleNamespace(endpoint='notebook-runtime',accelerator=types.SimpleNamespace(value='NONE'),variant=types.SimpleNamespace(name='DEFAULT'),machine_shape=types.SimpleNamespace(name='STANDARD')))
            client=types.SimpleNamespace(list_assignments=Mock(return_value=assignments))
            state=types.SimpleNamespace(store=types.SimpleNamespace(list=lambda:{'trainer':session}),client=client)
            output=io.StringIO()
            with patch.dict(sys.modules,{'colab_cli.common':types.SimpleNamespace(state=state)}),patch.dict(os.environ,{'COLAB_PROFILE_DIR':temp}),patch.object(sys,'argv',['inventory',name]),contextlib.redirect_stdout(output):
                runpy.run_path(str(ROOT/'src/list_sessions.py'),run_name='__main__')
            self.assertNotIn('must-not-leak',output.getvalue());client.list_assignments.assert_called_once()
            return json.loads(output.getvalue())

    def test_inventory_has_folders_directions_and_explicit_mount_uncertainty(self):
        row=self.invoke()[0]
        self.assertEqual(row['session'],'trainer')
        self.assertEqual(row['drive_folder'],'~/Projects')
        self.assertEqual(row['workspace'],'/content/Projects')
        self.assertEqual(row['drive_access'],'read/write')
        self.assertEqual(row['drive_mount'],'not checked')
        self.assertTrue(row['drive_previously_mounted'])
        self.assertEqual(row['local_folder'],'/pc/project')
        self.assertEqual(row['pc_sync_direction'],'PC -> Colab')
        self.assertEqual(row['sync_pairs'][0]['direction'],'<>')

    def test_inventory_includes_unregistered_notebook_runtime(self):
        row=self.invoke(unknown=True)[1]
        self.assertEqual(row['session'],'?')
        self.assertEqual(row['endpoint'],'notebook-runtime')
        self.assertEqual(row['runtime'],'CPU')
        self.assertEqual(row['names'],[])

    def test_filter_applies_before_workspace_metadata(self):
        self.assertEqual(self.invoke(name='missing',unknown=True),[])

class DeleteSnapshot(unittest.TestCase):
    def test_only_snapshot_endpoints_are_deleted_once_and_failures_continue(self):
        current={'a':types.SimpleNamespace(endpoint='one'),'alias':types.SimpleNamespace(endpoint='one'),'unrelated':types.SimpleNamespace(endpoint='new-runtime')}
        seen=[]
        def unassign(endpoint):
            seen.append(endpoint)
            if endpoint=='bad':raise ConnectionError('Cannot reach https://google.invalid/?token=secret')
        state=types.SimpleNamespace(client=types.SimpleNamespace(unassign=unassign),store=types.SimpleNamespace(list=lambda:dict(current),remove=lambda name:current.pop(name)))
        output,error=io.StringIO(),io.StringIO()
        with patch.dict(sys.modules,{'colab_cli.common':types.SimpleNamespace(state=state)}),patch.object(sys,'argv',['delete',json.dumps(['one','one','bad','notebook'])]),contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):
            with self.assertRaises(SystemExit) as result:
                runpy.run_path(str(ROOT/'src/delete_sessions.py'),run_name='__main__')
        self.assertEqual(result.exception.code,1)
        self.assertEqual(seen,['one','bad','notebook'])
        self.assertEqual(list(current),['unrelated'])
        self.assertEqual([r['deleted'] for r in json.loads(output.getvalue())],[True,False,True])
        self.assertNotIn('token=secret',error.getvalue())
