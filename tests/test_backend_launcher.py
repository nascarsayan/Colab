"""The private SDK launcher wins over the conflicting lowercase executable."""
import json
import unittest
import test_creation_cli as fixtures

class BackendLauncher(unittest.TestCase):
    setUp = fixtures.CreationCLI.setUp
    script = fixtures.CreationCLI.script
    call = fixtures.CreationCLI.call

    def test_google_module_is_invoked_with_private_interpreter(self):
        managed = self.home / '.config/Colab/backend/bin'
        managed.mkdir(parents=True)
        (managed/'colab').write_text((self.bin/'colab').read_text())
        (self.bin/'colab').write_text('#!/bin/sh\nexit 91\n')
        result = self.call('session', 'status', '-s', 'trainer')
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads((self.home/'cli-calls.jsonl').read_text())
        self.assertEqual(args, ['--auth','oauth2','--config',str(self.profile/'sessions.json'),'status','-s','trainer'])
