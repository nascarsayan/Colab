"""Exercise account filtering, same-name isolation, and concurrent transports."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import unittest
import test_creation_cli as fixtures

CLI=fixtures.CLI
class Accounts(unittest.TestCase):
    setUp=fixtures.CreationCLI.setUp
    script=fixtures.CreationCLI.script

    def raw(self,*args):
        return subprocess.run([str(CLI),*args],env=self.env,capture_output=True,text=True,timeout=20)

    def add_second(self):
        path=self.home/'.config/Colab/accounts.json'
        data=json.loads(path.read_text())
        ident='22222222-2222-4222-8222-222222222222'
        data['accounts']['two@gmail.com']={'id':ident}
        path.write_text(json.dumps(data))
        self.second=self.home/'.config/Colab/accounts'/ident
        self.second.mkdir()

    def test_single_runtime_commands_require_explicit_email_before_backend(self):
        for command in [('session','shell'),('session','create'),('exec','pwd'),('run','hello.cu'),('files','copy','a','colab:/a'),('files','sync','a','>','colab:/a'),('drive','mount'),('session','delete'),('session','disconnect'),('session','start'),('session','url')]:
            p=self.raw(*command)
            self.assertNotEqual(p.returncode,0,command)
            self.assertIn('--account EMAIL is required',p.stderr)
        self.assertFalse((self.home/'calls.jsonl').exists())

    def test_account_list_offline_and_email_visible(self):
        self.add_second()
        self.env['PATH']=''
        p=self.raw('auth','list')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('one@gmail.com',p.stdout);self.assertIn('two@gmail.com',p.stdout)
        self.assertNotIn('setup',self.raw('--help').stdout)
        p=self.raw('auth','list','-a','two@gmail.com')
        self.assertNotIn('one@gmail.com',p.stdout);self.assertIn('two@gmail.com',p.stdout)

    def test_all_account_session_lists_and_status_with_account_filter(self):
        self.add_second()
        for cmd in ['list','status']:
            p=self.raw('session',cmd)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertIn('Account: one@gmail.com',p.stdout);self.assertIn('Account: two@gmail.com',p.stdout)
            p=self.raw('session',cmd,'-a','two@gmail.com')
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertNotIn('one@gmail.com',p.stdout);self.assertIn('two@gmail.com',p.stdout)
        calls=[json.loads(x) for x in (self.home/'cli-calls.jsonl').read_text().splitlines()]
        self.assertTrue(any(str(self.second/'sessions.json') in x for x in calls))
        self.assertTrue(any(str(self.profile/'sessions.json') in x for x in calls))

    def test_identical_names_and_concurrent_commands_use_isolated_connections(self):
        self.add_second()
        for email in ['one@gmail.com','two@gmail.com']:
            p=self.raw('-a',email,'session','create','trainer')
            self.assertEqual(p.returncode,0,p.stderr)
        # Fixture intentionally uses the SAME endpoint for both accounts too.
        self.assertIn('trainer',json.loads((self.profile/'sessions.json').read_text()))
        self.assertIn('trainer',json.loads((self.second/'sessions.json').read_text()))
        sockets=list((self.home/'.config/Colab/mux').glob('*.sock'))
        self.assertEqual(len(sockets),2)
        with ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(lambda email:self.raw('-a',email,'exec','-s','trainer','pwd'), ['one@gmail.com','two@gmail.com']*3))
        for result in results:
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout,'remote-ok\n')
        p=self.raw('-a','one@gmail.com','session','disconnect','-s','trainer')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(len(list((self.home/'.config/Colab/mux').glob('*.sock'))),1)

    def test_sync_targets_span_accounts_with_email_in_json_and_name_filter(self):
        self.add_second()
        for profile in [self.profile,self.second]:
            sync=profile/'sync';sync.mkdir()
            (sync/'pair.target.json').write_text(json.dumps({'session':'trainer','left':'/local','right':'colab:/remote','direction':'>','last_success_utc':'now'}))
        p=self.raw('files','targets','--json')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual({x['account'] for x in json.loads(p.stdout)},{'one@gmail.com','two@gmail.com'})
        p=self.raw('files','targets','--json','--account','two@gmail.com','-s','trainer')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual([x['account'] for x in json.loads(p.stdout)],['two@gmail.com'])
        p=self.raw('files','targets','--json','-s','missing')
        self.assertEqual(json.loads(p.stdout),[])

    def test_missing_account_is_actionable_and_does_not_allocate(self):
        p=self.raw('-a','unknown@gmail.com','session','create','trainer')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('not saved',p.stderr)
        self.assertFalse((self.home/'calls.jsonl').exists())

    def test_unavailable_account_does_not_hide_other_accounts(self):
        self.add_second()
        self.env['MOCK_FAIL_ACCOUNT']='one@gmail.com'
        p=self.raw('session','list')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('Account: two@gmail.com',p.stdout)
        self.assertIn('continuing with other accounts',p.stderr)
        self.assertIn('could not be queried',p.stderr)

    def test_list_session_filter_is_forwarded_to_each_account(self):
        self.add_second()
        # Record the native source and args without calling Google.
        interpreter=self.script('record-python', "import sys,json; print(json.dumps(sys.argv[3:]))" )
        # Version probe still needs a healthy response.
        interpreter.write_text('#!'+__import__('sys').executable+'\nimport sys,json\nif "importlib.metadata" in sys.argv[2]: print("0.8.0")\nelse: print(json.dumps(sys.argv[3:]))\n')
        managed=self.home/'.config/Colab/backend/bin';managed.mkdir(parents=True)
        (managed/'colab').write_text('#!'+str(interpreter)+'\n')
        p=self.raw('session','list','-s','trainer')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(p.stdout.count('"trainer"'),2)

    def test_migrated_account_reuses_live_legacy_master(self):
        import uuid
        (self.profile/'sessions.json').write_text(json.dumps({'trainer':{'endpoint':'old-runtime'}}))
        (self.profile/'legacy-mux').touch()
        mux=self.home/'.config/Colab/mux';mux.mkdir()
        socket=mux/(uuid.uuid5(uuid.NAMESPACE_URL,'old-runtime').hex+'.sock');socket.touch()
        p=self.raw('-a','one@gmail.com','exec','-s','trainer','pwd')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(list(mux.glob('*.sock')),[socket])
