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
            for args in [('start','-s','FreshTest'),('sessions',),('status',)]:
                with self.subTest(args=args):
                    p=subprocess.run([str(CLI),*args],env=env,capture_output=True,text=True,timeout=30)
                    self.assertNotEqual(p.returncode,0)
                    self.assertIn('Colab auth login',p.stderr)
                    self.assertNotIn('Traceback',p.stderr)
                    self.assertNotIn('Enter the authorization code',p.stdout+p.stderr)
                    self.assertNotIn('accounts.google.com',p.stdout+p.stderr)
                    self.assertNotIn('FileNotFoundError',p.stderr)
                    self.assertTrue((home/'.config/colab-cli').is_dir())
