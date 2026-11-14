"""The frontend must never invoke itself through Google's lowercase command."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CLI = Path(__file__).resolve().parents[1] / 'target/debug/Colab'


@unittest.skipUnless(CLI.exists(), 'Run cargo build first')
class BackendLauncher(unittest.TestCase):
    def test_google_module_is_invoked_with_private_interpreter(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            managed = home / '.config/Colab/backend/bin'
            managed.mkdir(parents=True)
            interpreter = home / 'private-python'
            interpreter.write_text('#!' + sys.executable + '\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
            interpreter.chmod(0o755)
            (managed / 'colab').write_text('#!' + str(interpreter) + '\n')
            collision = home / 'bin'
            collision.mkdir()
            # A global launcher named Colab/colab would exit unsuccessfully.
            for name in ['Colab', 'colab']:
                p = collision / name
                p.write_text('#!/bin/sh\nexit 91\n')
                p.chmod(0o755)
            env = dict(os.environ, HOME=str(home), PATH=str(collision))
            result = subprocess.run([str(CLI), 'sessions'], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            args=json.loads(result.stdout)
            self.assertEqual(args[0], '-c')
            self.assertIn('Boundary for every Google backend call', args[1])
            self.assertIn('colab_cli.cli',args[2])
            self.assertEqual(args[3:], ['--auth','oauth2','sessions'])
