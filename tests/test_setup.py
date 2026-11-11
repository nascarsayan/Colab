import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

CLI = Path(__file__).resolve().parents[1] / 'target/debug/Colab'


@unittest.skipUnless(CLI.exists(), 'Run cargo build first')
class Setup(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(self.bin))
        self.script('ssh', 'pass')
        self.script('ssh-keygen', "import pathlib,sys; p=pathlib.Path(sys.argv[sys.argv.index('-f')+1]); p.write_text('fake test key')")
        self.interpreter = self.script('fake-python', '''import sys
code = sys.argv[2] if len(sys.argv)>2 else ''
if 'importlib.metadata' in code: print('0.8.0')
else: print('guided-login-called')
''')
        self.uv_code = '''import os,pathlib,sys,json
home=pathlib.Path(os.environ['HOME'])
(home/'uv-args.json').write_text(json.dumps(sys.argv[1:]))
p=pathlib.Path(os.environ.get('UV_TOOL_BIN_DIR',str(home/'.local/bin')))/'colab';p.parent.mkdir(parents=True,exist_ok=True)
p.write_text('#!'+str(home/'bin/fake-python')+'\\n');p.chmod(0o755)
'''

    def script(self, name, code):
        path = self.bin / name
        path.write_text('#!' + sys.executable + '\n' + code + '\n')
        path.chmod(0o755)
        return path

    def backend(self):
        p = self.bin / 'colab'
        p.write_text('#!' + str(self.interpreter) + '\n')
        p.chmod(0o755)

    def call(self, *args):
        return subprocess.run([str(CLI), *args], env=self.env, capture_output=True, text=True, timeout=20)

    def test_check_never_installs_logs_in_or_generates_keys(self):
        self.backend()
        p = self.call('setup', '--check')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('Login was not checked', p.stdout)
        self.assertFalse((self.home / '.config').exists())
        self.assertNotIn('guided-login-called', p.stdout)

    def test_installs_backend_without_login_and_repeat_is_idempotent(self):
        self.script('uv', self.uv_code)
        p = self.call('setup', '--skip-login')
        self.assertEqual(p.returncode, 0, p.stderr)
        args = json.loads((self.home / 'uv-args.json').read_text())
        self.assertEqual(args, ['tool', 'install', '--python', '3.13', 'google-colab-cli==0.8.0'])
        self.assertTrue((self.home / '.config/Colab/id_ed25519').exists())
        (self.home / 'uv-args.json').unlink()
        p = self.call('setup', '--skip-login')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse((self.home / 'uv-args.json').exists())

    def test_default_setup_runs_login_but_does_not_allocate(self):
        self.backend()
        p = self.call('setup')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('guided-login-called', p.stdout)
        self.assertFalse((self.home / '.config/colab-cli/sessions.json').exists())

    def test_missing_openssh_is_actionable(self):
        (self.bin / 'ssh').unlink()
        p = self.call('setup')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('openssh-client', p.stderr)
        self.assertFalse((self.home / '.config').exists())

    def test_missing_uv_bootstraps_official_installer_with_no_shell_edits(self):
        uv_text = '#!' + sys.executable + '\n' + self.uv_code
        install_code = '''import os,pathlib
assert os.environ['UV_NO_MODIFY_PATH']=='1'
p=pathlib.Path(os.environ['UV_INSTALL_DIR'])/'uv';p.parent.mkdir(parents=True,exist_ok=True)
p.write_text(''' + repr(uv_text) + ''');p.chmod(0o755)
'''
        installer = '#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' -c ' + shlex.quote(install_code) + '\n'
        self.script('curl', '''import pathlib,sys,os
args=sys.argv[1:]
pathlib.Path(args[args.index('--output')+1]).write_text(''' + repr(installer) + ''')
(pathlib.Path(os.environ['HOME'])/'download-url').write_text(args[-1])
''')
        p = self.call('setup', '--skip-login')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual((self.home / 'download-url').read_text(), 'https://astral.sh/uv/0.13.7/install.sh')
        self.assertTrue((self.home / '.config/Colab/backend/bin/colab').exists())
