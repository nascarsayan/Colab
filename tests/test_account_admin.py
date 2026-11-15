"""Validate real account metadata/credential removal without touching the real keyring."""
import contextlib
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[1]/'src/account_admin.py'
class AccountAdmin(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name);self.root=self.home/'.config/Colab';self.root.mkdir(parents=True)
        self.ids=['11111111-1111-4111-8111-111111111111','22222222-2222-4222-8222-222222222222']
        self.accounts={email:{'id':ident} for email,ident in zip(['one@gmail.com','two@gmail.com'],self.ids)}
        self.path=self.root/'accounts.json'
        self.path.write_text(json.dumps({'accounts':self.accounts,'default':'one@gmail.com'}))
        for ident in self.ids:
            profile=self.root/'accounts'/ident;profile.mkdir(parents=True)
            (profile/'sessions.json').write_text('{"trainer":{"token":"private"}}')
            (profile/'workspaces').mkdir()
        self.tokens={'Colab:one@gmail.com':'one-secret','Colab:two@gmail.com':'two-secret','oauth_token':'legacy-secret'}

    def invoke(self,*args,fail=False):
        class MissingPassword(Exception): pass
        def delete(service,username):
            if fail: raise RuntimeError('keyring locked')
            if username not in self.tokens:raise MissingPassword()
            self.tokens.pop(username)
        auth=types.SimpleNamespace(KEYRING_SERVICE_NAME='google-colab-cli',KEYRING_TIMEOUT_SECONDS=30,_run_with_timeout=lambda fn,*a,**kw:fn(*a))
        modules={'colab_cli':types.SimpleNamespace(auth=auth),'keyring':types.SimpleNamespace(delete_password=delete,errors=types.SimpleNamespace(PasswordDeleteError=MissingPassword)), 'filelock':types.SimpleNamespace(FileLock=lambda *_:contextlib.nullcontext())}
        import io
        with patch.dict(sys.modules,modules),patch('pathlib.Path.home',return_value=self.home),patch.object(sys,'argv',['admin',*args]),contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(str(SCRIPT),run_name='__main__')
        return json.loads(self.path.read_text())

    def test_default_is_persisted_without_changing_tokens(self):
        data=self.invoke('default','two@gmail.com')
        self.assertEqual(data['default'],'two@gmail.com')
        self.assertEqual(len(self.tokens),3)

    def test_logout_removes_only_selected_credentials_and_runtime_tokens(self):
        data=self.invoke('logout','one@gmail.com')
        self.assertNotIn('Colab:one@gmail.com',self.tokens)
        self.assertIn('Colab:two@gmail.com',self.tokens)
        self.assertEqual(data['default'],'two@gmail.com')
        self.assertFalse((self.root/'accounts'/self.ids[0]/'sessions.json').exists())
        self.assertTrue((self.root/'accounts'/self.ids[1]/'sessions.json').exists())
        self.assertTrue((self.root/'accounts'/self.ids[0]/'workspaces').is_dir())
        self.assertEqual(data['signed_out']['one@gmail.com']['id'],self.ids[0])
        self.assertTrue(data['legacy_signed_out'])

    def test_logout_all_clears_legacy_credentials_and_last_default(self):
        legacy=self.home/'.config/colab-cli';legacy.mkdir(parents=True)
        (legacy/'token.json').write_text('secret');(legacy/'sessions.json').write_text('secret')
        self.invoke('logout','one@gmail.com','clear-legacy')
        data=self.invoke('logout','two@gmail.com','clear-legacy')
        self.assertEqual(self.tokens,{})
        self.assertEqual(data['accounts'],{})
        self.assertIsNone(data['default'])
        self.assertFalse((legacy/'token.json').exists())
        self.assertFalse((legacy/'sessions.json').exists())

    def test_keyring_failure_keeps_account_registered_and_reports_failure(self):
        with self.assertRaisesRegex(RuntimeError,'keyring locked'):
            self.invoke('logout','one@gmail.com',fail=True)
        self.assertIn('one@gmail.com',json.loads(self.path.read_text())['accounts'])
