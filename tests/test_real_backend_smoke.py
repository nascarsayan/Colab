"""No-network smoke check against the locally installed Google backend, if present."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/'target/debug/Colab'
LAUNCHER=Path.home()/'.local/share/uv/tools/google-colab-cli/bin/colab'

@unittest.skipUnless(CLI.exists() and LAUNCHER.exists(),'Optional installed-backend smoke test')
class FreshMachine(unittest.TestCase):
    def test_start_initializes_lock_parent_and_missing_login_is_not_a_traceback(self):
        python=LAUNCHER.read_text().splitlines()[0].removeprefix('#!')
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp);private=home/'.config/Colab/backend/bin';private.mkdir(parents=True)
            (private/'colab').write_text('#!'+python+'\n')
            env=dict(os.environ,HOME=str(home),XDG_CONFIG_HOME=str(home/'.config'),PYTHON_KEYRING_BACKEND='keyring.backends.null.Keyring')
            for args in [('start','--account','test@gmail.com','-s','FreshTest'),('sessions',),('status',)]:
                with self.subTest(args=args):
                    p=subprocess.run([str(CLI),*args],env=env,capture_output=True,text=True,timeout=30)
                    self.assertNotEqual(p.returncode,0)
                    self.assertIn('Colab auth login',p.stderr)
                    self.assertNotIn('Traceback',p.stderr)
                    self.assertNotIn('Enter the authorization code',p.stdout+p.stderr)
                    self.assertNotIn('accounts.google.com',p.stdout+p.stderr)
                    self.assertNotIn('FileNotFoundError',p.stderr)
                    self.assertTrue((home/'.config/colab-cli').is_dir())

    def test_real_sdk_uses_account_specific_credentials_and_state(self):
        python=LAUNCHER.read_text().splitlines()[0].removeprefix('#!')
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp);profile=home/'.config/Colab/accounts/test-profile'
            env=dict(os.environ,HOME=str(home),COLAB_ACCOUNT='one@gmail.com',COLAB_PROFILE_DIR=str(profile),PYTHON_KEYRING_BACKEND='keyring.backends.null.Keyring')
            source="""from colab_cli import auth
from colab_cli.common import state
from pathlib import Path
import os
assert auth.KEYRING_USERNAME == 'Colab:one@gmail.com'
assert auth.LEGACY_TOKEN_PATH == os.environ['COLAB_PROFILE_DIR']+'/unused-legacy-token'
assert state.config_path == os.environ['COLAB_PROFILE_DIR']+'/sessions.json'
assert state.store.path == state.config_path
assert state.settings_store.path == os.environ['COLAB_PROFILE_DIR']+'/settings.json'
assert not state.store.list()
print('isolated')
"""
            p=subprocess.run([python,'-c',(ROOT/'src/runner.py').read_text(),source],env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual(p.stdout,'isolated\n')
            self.assertFalse((home/'.config/colab-cli/sessions.json').exists())
