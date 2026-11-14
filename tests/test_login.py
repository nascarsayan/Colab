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
    def invoke(self, requested='', actual='one@gmail.com', verified=True, failure=None, saved='secret-token', no_browser=False, legacy=False):
        with tempfile.TemporaryDirectory() as home:
            if legacy:
                old=Path(home)/'.config/colab-cli';old.mkdir(parents=True)
                (old/'sessions.json').write_text('{"trainer":{"endpoint":"old"}}')
                app=Path(home)/'.config/Colab';app.mkdir()
                (app/'id_ed25519').write_text('test-private-key')
                (app/'workspaces').mkdir()
                (app/'workspaces/config.json').write_text('{"remote":"/content/drive/MyDrive/Code"}')
            echo = Mock()
            auth = types.SimpleNamespace(typer=types.SimpleNamespace(echo=echo), KEYRING_SERVICE_NAME='google-colab-cli', KEYRING_USERNAME='oauth_token', _save_token_to_keyring=Mock(), _remove_legacy_token=Mock())
            def credentials(*args):
                auth.typer.echo('https://accounts.google.com/example', err=True)
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
            with patch.dict(sys.modules,modules), patch.dict(os.environ,{'COLAB_LOGIN_EMAIL':requested}), patch('pathlib.Path.home',return_value=Path(home)), patch.object(sys,'argv',['login']+(['--no-browser'] if no_browser else [])), patch('webbrowser.open',return_value=True) as browser, contextlib.redirect_stdout(out):
                try: runpy.run_path(str(SCRIPT),run_name='__main__')
                except Exception as exc: error=exc
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
        self.assertIn('one@gmail.com',out)

    def test_wrong_google_account_cannot_overwrite_requested_credentials(self):
        error,keyring,data,_,_=self.invoke(requested='two@gmail.com')
        self.assertIn('but two@gmail.com was requested',str(error))
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
