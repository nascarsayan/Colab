import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

CLI=Path(__file__).resolve().parents[1]/'target/debug/Colab'

@unittest.skipUnless(CLI.exists(),'Run cargo build first')
class RuntimeCatalog(unittest.TestCase):
    def invoke(self,*args):
        with tempfile.TemporaryDirectory() as home:
            p=subprocess.run([str(CLI),'runtime',*args],env=dict(os.environ,HOME=home,PATH=''),capture_output=True,text=True,timeout=10)
            self.assertFalse((Path(home)/'.config').exists(),'Catalog should not initialize state, log in, or connect')
            return p

    def test_json_lists_supported_hardware_offline(self):
        p=self.invoke('list','--json');self.assertEqual(p.returncode,0,p.stderr)
        rows=json.loads(p.stdout)
        self.assertEqual({r['runtime'] for r in rows},{'cpu','t4','l4','g4','h100','a100','v5e1','v6e1'})
        self.assertEqual(next(r['kind'] for r in rows if r['runtime']=='cpu'),'cpu')
        self.assertEqual(next(r['kind'] for r in rows if r['runtime']=='t4'),'gpu')
        self.assertEqual(next(r['kind'] for r in rows if r['runtime']=='v5e1'),'tpu')

    def test_human_listing_does_not_promise_account_availability(self):
        p=self.invoke('list');self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('account entitlement, quota, and capacity',p.stdout)
        self.assertIn('Colab session list',p.stdout)
        self.assertIn('Colab session create --account EMAIL --runtime TYPE',p.stdout)
