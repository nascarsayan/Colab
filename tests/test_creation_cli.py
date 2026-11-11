"""Exercise CLI -> backend runtime arguments without allocating cloud resources."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CLI = Path(__file__).resolve().parents[1] / 'target/debug/Colab'


@unittest.skipUnless(CLI.exists(), 'Run cargo build first')
class CreationCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        binary = root / 'bin'
        binary.mkdir()
        interpreter = binary / 'fake-python'
        interpreter.write_text('#!' + sys.executable + '\nimport json,sys\nprint(json.dumps(sys.argv[3:]))\n')
        interpreter.chmod(0o755)
        (binary / 'colab').write_text('#!' + str(interpreter) + '\n')
        (binary / 'colab').chmod(0o755)
        self.env = dict(os.environ, HOME=str(root), PATH=str(binary))

    def call(self, *args):
        return subprocess.run([str(CLI), *args], env=self.env, capture_output=True, text=True, timeout=10)

    def test_named_creation_runtime_and_high_memory_forwarding(self):
        for name, runtime, expected in [('cpu-job', 'CPU', 'NONE'), ('gpu-job', 'T4', 'T4'),
                ('l4-job', 'l4', 'L4'), ('g4-job', 'g4', 'G4'), ('a100-job', 'a100', 'A100'),
                ('h100-job', 'H100', 'H100'), ('tpu5', 'v5e1', 'V5E1'), ('tpu6', 'v6e-1', 'V6E1')]:
            with self.subTest(runtime=runtime):
                p = self.call('create', name, '--runtime', runtime, '--high-mem')
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(json.loads(p.stdout), ['create', name, expected, '', 'true'])

    def test_start_without_runtime_keeps_saved_configuration(self):
        p = self.call('start', '-s', 'trainer')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout), ['start', 'trainer', '', '', ''])

    def test_invalid_names_and_runtimes_rejected_before_backend(self):
        for args in [('create',), ('create', '../unsafe'), ('create', 'ok', '--runtime', 'invalid')]:
            with self.subTest(args=args):
                self.assertEqual(self.call(*args).returncode, 2)

    def test_legacy_gpu_alias_and_conflicting_flags(self):
        p = self.call('start', '-s', 'trainer', '--gpu', 'T4')
        self.assertEqual(json.loads(p.stdout), ['start', 'trainer', 'T4', '', ''])
        self.assertEqual(self.call('start', '--runtime', 'cpu', '--gpu', 'T4').returncode, 2)
