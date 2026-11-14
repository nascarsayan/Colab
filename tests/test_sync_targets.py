import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'target/debug/Colab'


@unittest.skipUnless(CLI.exists(), 'Run cargo build before these CLI integration tests')
class Targets(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.dir = self.home / '.config/Colab/sync'
        self.dir.mkdir(parents=True)
        self.env = dict(os.environ, HOME=str(self.home), PATH='')

    def run_cli(self, *args):
        return subprocess.run([str(CLI), 'sync-targets', *args], env=self.env,
                              capture_output=True, text=True, timeout=10)

    def test_listing_is_offline_and_filters_session(self):
        for session in ['gpu-proxy', 'other']:
            record = dict(session=session, left='/local/data', right='colab:/content/data',
                          direction='<>', last_success_utc='2026-11-11T12:00:00+00:00')
            (self.dir / (session + '.target.json')).write_text(json.dumps(record))
        p = self.run_cli('--json')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(json.loads(p.stdout)), 2)
        p = self.run_cli('--session', 'gpu-proxy', '--json')
        self.assertEqual([r['session'] for r in json.loads(p.stdout)], ['gpu-proxy'])
        p = self.run_cli('--all-sessions', '--json')
        self.assertEqual(len(json.loads(p.stdout)), 2)
        p = self.run_cli('--session', 'other')
        self.assertIn('[other]', p.stdout)
        self.assertIn('Last successful sync', p.stdout)

    def test_legacy_baseline_is_not_misidentified_as_a_target(self):
        (self.dir / 'oldhash.json').write_text('{"file": {"sha256": "abc"}}')
        p = self.run_cli('--json')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout), [])
        self.assertIn('Rerun', p.stderr)

    def test_empty_listing_does_not_create_files(self):
        p = self.run_cli()
        self.assertEqual(p.returncode, 0)
        self.assertIn('No recorded sync targets', p.stdout)
        self.assertEqual(list(self.dir.iterdir()), [])
