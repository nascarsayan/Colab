"""Verify identity before saving credentials or registering an account."""
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
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[1] / 'src/login.py'

class Login(unittest.TestCase):
    def invoke(self, requested='', actual='one@gmail.com', verified=True, failure=None, saved='secret-token', no_browser=False, legacy=False, cached=False, no_credentials=False, existing=None):
        with tempfile.TemporaryDirectory() as home:
            if legacy:
                old=Path(home)/'.config/colab-cli';old.mkdir(parents=True)
                (old/'sessions.json').write_text('{"trainer":{"endpoint":"old"}}')
                app=Path(home)/'.config/Colab';app.mkdir()
                (app/'id_ed25519').write_text('test-private-key')
                (app/'workspaces').mkdir()
                (app/'workspaces/config.json').write_text('{"remote":"/content/drive/MyDrive/Code"}')
            if existing is not None:
                app=Path(home)/'.config/Colab';app.mkdir(parents=True,exist_ok=True)
                (app/'accounts.json').write_text(json.dumps(existing))
            echo = Mock()
            auth = types.SimpleNamespace(typer=types.SimpleNamespace(echo=echo), KEYRING_SERVICE_NAME='google-colab-cli', KEYRING_USERNAME='oauth_token', _save_token_to_keyring=Mock(), _remove_legacy_token=Mock())
            def credentials(*args):
                if no_credentials: auth._run_remote_flow({})
                if not cached: auth.typer.echo('https://accounts.google.com/example', err=True)
                if failure: raise failure
                auth._save_token_to_keyring('unverified-secret')
                return types.SimpleNamespace(to_json=lambda: 'secret-token')
            auth._get_google_auth_credentials = credentials
            keyring = types.SimpleNamespace(set_password=Mock(),get_password=Mock(return_value=saved),delete_password=Mock())
            response = Mock(); response.json.return_value={'email':actual,'verified_email':verified}
            session = Mock(); session.get.return_value=response
            modules={'colab_cli':types.SimpleNamespace(auth=auth), 'keyring':keyring,
                'filelock':types.SimpleNamespace(FileLock=lambda *_:contextlib.nullcontext()),
                'google.auth.transport.requests':types.SimpleNamespace(AuthorizedSession=lambda *_:session)}
            out=io.StringIO()
            error=None
            with patch.dict(sys.modules,modules), patch.dict(os.environ,{'COLAB_LOGIN_EMAIL':requested}), patch('pathlib.Path.home',return_value=Path(home)), patch.object(sys,'argv',['login']+(['--no-browser'] if no_browser else [])+(['--cached'] if cached else [])), patch('webbrowser.open',return_value=True) as browser, contextlib.redirect_stdout(out),contextlib.redirect_stderr(io.StringIO()):
                try: runpy.run_path(str(SCRIPT),run_name='__main__')
                except BaseException as exc: error=exc
            registry=Path(home)/'.config/Colab/accounts.json'
            data=json.loads(registry.read_text()) if registry.exists() else None
            if legacy and data:
                profile=Path(home)/'.config/Colab/accounts'/data['accounts'][actual]['id']
                self.assertIn('trainer',(profile/'sessions.json').read_text())
                self.assertEqual((profile/'id_ed25519').read_text(),'test-private-key')
                self.assertTrue((profile/'workspaces/config.json').exists())
                self.assertTrue((profile/'legacy-mux').exists())
            self.assertNotIn('secret-token',out.getvalue())
            return error,keyring,data,browser,out.getvalue()

    def test_email_verified_credentials_registered(self):
        error,keyring,data,browser,out=self.invoke()
        self.assertIsNone(error)
        self.assertIn('one@gmail.com',data['accounts'])
        keyring.set_password.assert_called_once_with('google-colab-cli','Colab:one@gmail.com','secret-token')
        browser.assert_called_once()
        self.assertIn('Google account ready: one.',out)
        self.assertNotIn('@gmail.com',out)

    def test_wrong_google_account_cannot_overwrite_requested_credentials(self):
        error,keyring,data,_,_=self.invoke(requested='two@gmail.com')
        self.assertIn('but two was requested',str(error))
        keyring.set_password.assert_not_called()
        self.assertIsNone(data)

    def test_unverified_email_cannot_be_registered(self):
        error,keyring,data,_,_=self.invoke(verified=False)
        self.assertIsNotNone(error);keyring.set_password.assert_not_called();self.assertIsNone(data)

    def test_keyring_failure_does_not_register_account(self):
        error,_,data,_,_=self.invoke(saved=None)
        self.assertIn('could not be saved',str(error));self.assertIsNone(data)

    def test_noninteractive_login_is_actionable(self):
        error,_,_,_,_=self.invoke(failure=EOFError())
        self.assertIn('interactive terminal',str(error))

    def test_headless_login_does_not_open_browser(self):
        error,_,_,browser,_=self.invoke(no_browser=True)
        self.assertIsNone(error);browser.assert_not_called()

    def test_legacy_login_preserves_sessions_workspace_and_transport_identity(self):
        error,_,data,_,_=self.invoke(legacy=True)
        self.assertIsNone(error)
        self.assertIn('one@gmail.com',data['accounts'])

    def test_cached_discovery_saves_verified_account_without_browser_or_output(self):
        error,_,data,browser,out=self.invoke(cached=True,legacy=True)
        self.assertIsNone(error)
        self.assertEqual(data['default'],'one@gmail.com')
        browser.assert_not_called()
        self.assertEqual(out,'')

    def test_cached_miss_never_launches_oauth_or_writes_credentials(self):
        error,keyring,data,browser,_=self.invoke(cached=True,no_credentials=True)
        self.assertIsInstance(error,SystemExit)
        self.assertEqual(error.code,3)
        self.assertIsNone(data)
        browser.assert_not_called();keyring.set_password.assert_not_called()

    def test_cached_discovery_does_not_register_mismatched_account(self):
        error,keyring,data,browser,_=self.invoke(cached=True,requested='two@gmail.com')
        self.assertIsInstance(error,SystemExit);self.assertEqual(error.code,3)
        self.assertIsNone(data);keyring.set_password.assert_not_called();browser.assert_not_called()

    def test_second_login_keeps_first_account_as_default(self):
        previous={'accounts':{'one@gmail.com':{'id':'11111111-1111-4111-8111-111111111111'}},'default':'one@gmail.com'}
        error,_,data,_,_=self.invoke(requested='two@gmail.com',actual='two@gmail.com',existing=previous)
        self.assertIsNone(error)
        self.assertEqual(data['default'],'one@gmail.com')
        self.assertEqual(list(data['accounts']),['one@gmail.com','two@gmail.com'])

    def test_relogin_reuses_signed_out_profile_and_preserves_default(self):
        ident='22222222-2222-4222-8222-222222222222'
        previous={'accounts':{'one@gmail.com':{'id':'11111111-1111-4111-8111-111111111111'}},'default':'one@gmail.com','signed_out':{'two@gmail.com':{'id':ident}},'legacy_signed_out':True}
        error,_,data,_,_=self.invoke(requested='two@gmail.com',actual='two@gmail.com',existing=previous)
        self.assertIsNone(error)
        self.assertEqual(data['accounts']['two@gmail.com']['id'],ident)
        self.assertNotIn('two@gmail.com',data['signed_out'])
        self.assertEqual(data['default'],'one@gmail.com')
