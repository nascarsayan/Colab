"""Route the new public command tree through the same tested operations."""
import json
import unittest
import test_creation_cli as fixtures

class Hierarchy(unittest.TestCase):
    setUp=fixtures.CreationCLI.setUp
    script=fixtures.CreationCLI.script
    call=fixtures.CreationCLI.call
    calls=fixtures.CreationCLI.calls

    def test_root_help_only_advertises_the_public_tree(self):
        p=self.call('--help');self.assertEqual(p.returncode,0)
        for name in ['setup','auth','session','files','drive','exec','run']:
            self.assertRegex(p.stdout,rf'(?m)^  {name}\s')
        for name in ['create','start','shell','stop','disconnect','cp','sync','login','mount-drive']:
            self.assertNotRegex(p.stdout,rf'(?m)^  {name}\s')
        self.assertEqual(self.calls(),[])

    def test_session_create_connect_disconnect_and_stop(self):
        p=self.call('session','create','trainer','--runtime','cpu')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn(['create','trainer','NONE','','false'],self.calls())
        p=self.call('session','connect','-s','trainer')
        self.assertEqual(p.returncode,0,p.stderr);self.assertIn('remote-ok',p.stdout)
        p=self.call('session','disconnect','-s','trainer')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('trainer',json.loads((self.home/'.config/colab-cli/sessions.json').read_text()))
        p=self.call('session','stop','-s','trainer');self.assertEqual(p.returncode,0,p.stderr)
        records=[json.loads(x) for x in (self.home/'cli-calls.jsonl').read_text().splitlines()]
        self.assertIn(['--auth','oauth2','stop','-s','trainer'],records)

    def test_global_session_flag_works_at_each_level(self):
        for args in [('-s','trainer','session','status'),('session','-s','trainer','status'),('session','status','-s','trainer')]:
            p=self.call(*args);self.assertEqual(p.returncode,0,p.stderr)
        records=[json.loads(x) for x in (self.home/'cli-calls.jsonl').read_text().splitlines()]
        self.assertEqual(records,[['--auth','oauth2','status','-s','trainer']]*3)

    def test_file_group_routes_copy_sync_and_offline_targets(self):
        p=self.call('session','create','trainer');self.assertEqual(p.returncode,0,p.stderr)
        local=self.home/'data';local.mkdir()
        for args in [('files','copy'),('files','cp'),('file','copy')]:
            p=self.call(*args,'-s','trainer',str(local),'colab:/content/data');self.assertEqual(p.returncode,0,p.stderr)
        p=self.call('files','sync','-s','trainer',str(local),'>','colab:/content/data','--dry-run')
        self.assertEqual(p.returncode,0,p.stderr)
        records=[json.loads(x) for x in (self.home/'sync-calls.jsonl').read_text().splitlines()]
        self.assertEqual([r[3] for r in records],['cp','cp','cp','sync'])
        self.assertEqual(records[-1][-1],'1')
        p=self.call('files','targets','--json');self.assertEqual(json.loads(p.stdout),[])

    def test_auth_and_drive_groups(self):
        p=self.call('auth','login','--no-browser');self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(self.calls(),[])
        p=self.call('session','create','trainer');self.assertEqual(p.returncode,0,p.stderr)
        p=self.call('drive','mount','-s','trainer');self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('/content/drive/MyDrive/Code',p.stdout)

    def test_empty_groups_show_help_without_touching_google(self):
        for group in ['auth','session','files','drive']:
            p=self.call(group);self.assertNotEqual(p.returncode,0)
            self.assertIn('Usage:',p.stderr);self.assertNotIn('Traceback',p.stderr)
        self.assertEqual(self.calls(),[])
