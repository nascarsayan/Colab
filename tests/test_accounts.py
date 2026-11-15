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

    def test_single_runtime_operations_use_default_account(self):
        p=self.raw('session','create','trainer')
        self.assertEqual(p.returncode,0,p.stderr)
        p=self.raw('exec','pwd')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('Account: one',p.stderr)

    def test_account_list_offline_and_email_visible(self):
        self.add_second()
        self.env['PATH']=''
        p=self.raw('auth','list')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('one',p.stdout);self.assertIn('two',p.stdout)
        self.assertNotIn('setup',self.raw('--help').stdout)
        p=self.raw('auth','list','-a','two@gmail.com')
        self.assertNotIn('one ',p.stdout);self.assertIn('two',p.stdout)

    def test_all_account_session_lists_and_status_with_account_filter(self):
        self.add_second()
        for email in ['one@gmail.com','two@gmail.com']:
            self.assertEqual(self.raw('-a',email,'session','create','trainer').returncode,0)
        for cmd in ['list','status']:
            p=self.raw('session',cmd)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual(p.stdout.count('one'),1)
            self.assertEqual(p.stdout.count('two'),1)
            self.assertEqual(p.stderr,'')
            self.assertIn('WORKSPACE',p.stdout)
            p=self.raw('session',cmd,'-a','two@gmail.com')
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertNotIn('one ',p.stdout);self.assertIn('two',p.stdout)
        calls=[json.loads(x) for x in (self.home/'inventory-calls.jsonl').read_text().splitlines()]
        self.assertTrue(any(str(self.second) in x for x in calls))
        self.assertTrue(any(str(self.profile) in x for x in calls))

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
        self.assertEqual(self.raw('-a','two@gmail.com','session','create','trainer').returncode,0)
        self.env['MOCK_FAIL_ACCOUNT']='one@gmail.com'
        p=self.raw('session','list')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('two',p.stdout)
        self.assertIn('continuing with other accounts',p.stderr)
        self.assertIn('could not be queried',p.stderr)

    def test_list_session_filter_is_forwarded_to_each_account(self):
        self.add_second()
        p=self.raw('session','list','-s','trainer','--json')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(json.loads(p.stdout),[])
        calls=[json.loads(x) for x in (self.home/'inventory-calls.jsonl').read_text().splitlines()]
        self.assertEqual([row[2] for row in calls],['trainer','trainer'])

    def test_migrated_account_reuses_live_legacy_master(self):
        import uuid
        (self.profile/'sessions.json').write_text(json.dumps({'trainer':{'endpoint':'old-runtime'}}))
        (self.profile/'legacy-mux').touch()
        mux=self.home/'.config/Colab/mux';mux.mkdir()
        socket=mux/(uuid.uuid5(uuid.NAMESPACE_URL,'old-runtime').hex+'.sock');socket.touch()
        p=self.raw('-a','one@gmail.com','exec','-s','trainer','pwd')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(list(mux.glob('*.sock')),[socket])

    def test_default_switch_and_new_login_does_not_change_existing_default(self):
        self.add_second()
        p=self.raw('auth','default','two@gmail.com')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(json.loads((self.home/'.config/Colab/accounts.json').read_text())['default'],'two@gmail.com')
        p=self.raw('session','create','second-only')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertTrue((self.second/'sessions.json').exists())
        self.assertFalse((self.profile/'sessions.json').exists())

    def test_unique_session_name_selects_owner_and_duplicate_name_is_ambiguous(self):
        self.add_second()
        p=self.raw('-a','two@gmail.com','session','create','unique')
        self.assertEqual(p.returncode,0,p.stderr)
        p=self.raw('session','delete','unique')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('Account: two',p.stderr)
        for email in ['one@gmail.com','two@gmail.com']:
            self.assertEqual(self.raw('-a',email,'session','create','same').returncode,0)
        p=self.raw('session','delete','same')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('exists in multiple accounts',p.stderr)
        self.assertIn('--account EMAIL',p.stderr)

    def test_delete_all_across_accounts_and_with_filter(self):
        self.add_second()
        for email in ['one@gmail.com','two@gmail.com']:
            self.assertEqual(self.raw('-a',email,'session','create','trainer').returncode,0)
        p=self.raw('session','delete','all','-a','one@gmail.com')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(json.loads((self.profile/'sessions.json').read_text()),{})
        self.assertIn('trainer',json.loads((self.second/'sessions.json').read_text()))
        p=self.raw('session','delete','all')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(json.loads((self.second/'sessions.json').read_text()),{})
        calls=[json.loads(x) for x in (self.home/'deleted.jsonl').read_text().splitlines()]
        self.assertEqual([x[0] for x in calls],['one@gmail.com','two@gmail.com'])

    def test_delete_all_continues_after_partial_failure(self):
        self.add_second()
        for email in ['one@gmail.com','two@gmail.com']:
            self.assertEqual(self.raw('-a',email,'session','create','trainer').returncode,0)
        self.env['MOCK_DELETE_FAIL']='one@gmail.com'
        p=self.raw('session','delete','all')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('trainer',json.loads((self.profile/'sessions.json').read_text()))
        self.assertEqual(json.loads((self.second/'sessions.json').read_text()),{})
        self.assertIn('Some runtimes could not be deleted',p.stderr)

    def test_logout_default_selects_next_and_closes_only_that_account(self):
        self.add_second()
        for email in ['one@gmail.com','two@gmail.com']:
            self.assertEqual(self.raw('-a',email,'session','create','trainer').returncode,0)
        p=self.raw('auth','logout')
        self.assertEqual(p.returncode,0,p.stderr)
        data=json.loads((self.home/'.config/Colab/accounts.json').read_text())
        self.assertEqual(data['default'],'two@gmail.com')
        self.assertNotIn('one@gmail.com',data['accounts'])
        self.assertEqual(len(list((self.home/'.config/Colab/mux').glob('*.sock'))),1)
        p=self.raw('auth','logout','all')
        self.assertEqual(p.returncode,0,p.stderr)
        data=json.loads((self.home/'.config/Colab/accounts.json').read_text())
        self.assertEqual(data['accounts'],{})
        self.assertIsNone(data['default'])
        self.assertEqual(len(list((self.home/'.config/Colab/mux').glob('*.sock'))),0)
        p=self.raw('auth','list')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertNotIn('one@gmail.com',p.stdout)
        self.assertNotIn('two@gmail.com',p.stdout)

    def test_session_inventory_invalid_shape_is_a_readable_error(self):
        interpreter=self.script('invalid-python', 'import sys; print("0.8.0" if "importlib.metadata" in sys.argv[2] else \'["unexpected"]\')')
        managed=self.home/'.config/Colab/backend/bin';managed.mkdir(parents=True)
        (managed/'colab').write_text('#!'+str(interpreter)+'\n')
        p=self.raw('session','list')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('Invalid session inventory',p.stderr)
        self.assertNotIn('panicked',p.stderr)

    def test_auth_list_and_operations_recover_cached_legacy_login_automatically(self):
        path=self.home/'.config/Colab/accounts.json'
        path.unlink()
        self.env['MOCK_CACHED_EMAIL']='old@gmail.com'
        p=self.raw('auth','list')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('old',p.stdout)
        self.assertIn('--cached',json.loads((self.home/'cached-discovery.json').read_text()))
        self.assertNotIn('Google account ready',p.stdout+p.stderr)
        path.unlink()
        old=self.home/'.config/colab-cli';old.mkdir()
        (old/'sessions.json').write_text(json.dumps({'trainer':{'endpoint':'old-runtime'}}))
        p=self.raw('exec','-s','trainer','pwd')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(p.stdout,'remote-ok\n')
        self.assertIn('Account: old',p.stderr)

    def test_logout_all_prevents_automatic_legacy_rediscovery(self):
        self.assertEqual(self.raw('auth','logout','all').returncode,0)
        self.env['MOCK_CACHED_EMAIL']='one@gmail.com'
        p=self.raw('auth','list')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('No saved accounts',p.stdout)
        self.assertFalse((self.home/'cached-discovery.json').exists())

    def test_named_shell_uses_default_while_named_delete_checks_ownership(self):
        self.add_second()
        for email in ['one@gmail.com','two@gmail.com']:
            self.assertEqual(self.raw('-a',email,'session','create','trainer').returncode,0)
        p=self.raw('session','shell','-s','trainer')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('Account: one',p.stderr)
        p=self.raw('session','delete','trainer')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('exists in multiple accounts',p.stderr)

    def test_table_wraps_long_paths_and_json_preserves_them(self):
        self.env['COLUMNS']='120'
        local=self.home/('x'*80);local.mkdir()
        p=self.raw('session','create','trainer','--local-dir',str(local))
        self.assertEqual(p.returncode,0,p.stderr)
        p=self.raw('session','list')
        self.assertEqual(p.returncode,0,p.stderr)
        table=p.stdout.split('Drive folders are')[0]
        self.assertTrue(all(len(line)<=120 for line in table.splitlines()),table)
        p=self.raw('session','list','--json')
        self.assertEqual(json.loads(p.stdout)[0]['local_folder'],str(local))

    def test_compact_listing_is_one_row_and_details_are_opt_in(self):
        self.assertEqual(self.raw('session','create','PeachyBlossom').returncode,0)
        p=self.raw('session','list')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(len(p.stdout.splitlines()),2,p.stdout)
        self.assertIn('one',p.stdout)
        self.assertIn('/content/Code',p.stdout)
        for noise in ['gmail.com','ENDPOINT','SHAPE','SYNC','none','mount unchecked','read/write','endpoint-']:
            self.assertNotIn(noise,p.stdout)
        p=self.raw('session','list','--details')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('one',p.stdout)
        self.assertIn('endpoint-PeachyBlossom',p.stdout)
        self.assertIn('/content/Code',p.stdout)
        self.assertIn('mount not checked',p.stdout)

    def test_adaptive_listing_hides_columns_and_never_overflows(self):
        self.assertEqual(self.raw('session','create','PeachyBlossom').returncode,0)
        for width in [120,80,60,45,32,24,16,12,7,1]:
            with self.subTest(width=width):
                self.env['COLUMNS']=str(width)
                p=self.raw('session','list')
                self.assertEqual(p.returncode,0,p.stderr)
                self.assertEqual(len(p.stdout.splitlines()),2,p.stdout)
                self.assertTrue(all(len(line)<=width for line in p.stdout.splitlines()),p.stdout)
                if width<=45:self.assertNotIn('WORKSPACE',p.stdout)
                if width<=24:self.assertNotIn('RUNTIME',p.stdout)
        self.env['COLUMNS']='1'
        p=self.raw('session','list','--json')
        self.assertEqual(json.loads(p.stdout)[0]['session'],'PeachyBlossom')

    def test_hidden_account_keeps_duplicate_session_names_distinct(self):
        self.add_second()
        for email in ['one@gmail.com','two@gmail.com']:
            self.assertEqual(self.raw('-a',email,'session','create','trainer').returncode,0)
        self.env['COLUMNS']='24'
        p=self.raw('session','list')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertNotIn('ACCOUNT',p.stdout)
        self.assertIn('one/trainer',p.stdout)
        self.assertIn('two/trainer',p.stdout)
        self.assertTrue(all(len(line)<=24 for line in p.stdout.splitlines()))

    def test_real_terminal_geometry_is_used_when_columns_is_unset(self):
        import fcntl,pty,struct,termios
        self.assertEqual(self.raw('session','create','PeachyBlossom').returncode,0)
        master,slave=pty.openpty()
        try:
            fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',24,24,0,0))
            env=dict(self.env);env.pop('COLUMNS',None)
            p=subprocess.run([str(CLI),'session','list'],env=env,stdout=slave,stderr=subprocess.PIPE,text=True,timeout=20)
            self.assertEqual(p.returncode,0,p.stderr)
            os.close(slave);slave=None
            output=b''
            while True:
                try:
                    chunk=os.read(master,4096)
                    if not chunk:break
                    output+=chunk
                except OSError:break
            text=output.decode()
            self.assertNotIn('WORKSPACE',text)
            self.assertTrue(all(len(line)<=24 for line in text.splitlines()),text)
        finally:
            os.close(master)
            if slave is not None:os.close(slave)

    def test_unicode_paths_use_terminal_display_width(self):
        import unicodedata
        local=self.home/('資料'*12);local.mkdir()
        self.assertEqual(self.raw('session','create','PeachyBlossom','--local-dir',str(local)).returncode,0)
        for width in [120,80,60,45]:
            with self.subTest(width=width):
                self.env['COLUMNS']=str(width)
                p=self.raw('session','list')
                self.assertEqual(p.returncode,0,p.stderr)
                for line in p.stdout.splitlines():
                    measured=sum(0 if unicodedata.combining(ch) else 2 if unicodedata.east_asian_width(ch) in ('W','F') else 1 for ch in line)
                    self.assertLessEqual(measured,width,p.stdout)
        p=self.raw('session','list','--json')
        self.assertEqual(json.loads(p.stdout)[0]['local_folder'],str(local))

    def test_username_shorthand_for_session_operations_and_filters(self):
        self.add_second()
        self.assertEqual(self.raw('-a','one','session','create','trainer').returncode,0)
        self.assertEqual(self.raw('-a','two','session','create','other').returncode,0)
        p=self.raw('-a','ONE','exec','-s','trainer','pwd')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('Account: one',p.stderr)
        p=self.raw('session','list','-a','one','--json')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual([r['account'] for r in json.loads(p.stdout)],['one@gmail.com'])
        p=self.raw('auth','list','-a','two')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('two',p.stdout)
        self.assertNotIn('one@gmail.com',p.stdout)
        p=self.raw('files','targets','-a','one','--json')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(json.loads(p.stdout),[])
        p=self.raw('session','delete','all','-a','one')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(json.loads((self.profile/'sessions.json').read_text()),{})
        self.assertIn('other',json.loads((self.second/'sessions.json').read_text()))

    def test_username_shorthand_for_login_default_and_logout(self):
        self.add_second()
        p=self.raw('auth','login','-a','one','--no-browser')
        self.assertEqual(p.returncode,0,p.stderr)
        p=self.raw('auth','default','two')
        self.assertEqual(p.returncode,0,p.stderr)
        path=self.home/'.config/Colab/accounts.json'
        self.assertEqual(json.loads(path.read_text())['default'],'two@gmail.com')
        p=self.raw('auth','logout','-a','two')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertNotIn('two@gmail.com',json.loads(path.read_text())['accounts'])

    def test_username_cached_login_discovery_uses_full_email(self):
        (self.home/'.config/Colab/accounts.json').unlink()
        self.env['MOCK_CACHED_EMAIL']='old@gmail.com'
        p=self.raw('auth','login','-a','old','--no-browser')
        self.assertEqual(p.returncode,0,p.stderr)
        data=json.loads((self.home/'.config/Colab/accounts.json').read_text())
        self.assertIn('old@gmail.com',data['accounts'])
        self.assertNotIn('old',data['accounts'])

    def test_invalid_account_rejected_before_backend(self):
        for account in ['','one@','@gmail.com','one@@gmail.com','one two']:
            p=self.raw('session','list','-a',account)
            self.assertEqual(p.returncode,2,p.stderr)
        self.assertFalse((self.home/'inventory-calls.jsonl').exists())

    def test_full_non_gmail_email_stays_distinct_and_visible(self):
        self.add_second()
        path=self.home/'.config/Colab/accounts.json'
        data=json.loads(path.read_text())
        data['accounts']['one@work.example']=data['accounts'].pop('two@gmail.com')
        path.write_text(json.dumps(data))
        p=self.raw('-a','one','session','create','personal')
        self.assertEqual(p.returncode,0,p.stderr)
        p=self.raw('-a','ONE@WORK.EXAMPLE','session','create','work')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('Account: one@work.example',p.stderr)
        self.assertIn('personal',json.loads((self.profile/'sessions.json').read_text()))
        self.assertIn('work',json.loads((self.second/'sessions.json').read_text()))
        p=self.raw('auth','list')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertNotIn('@gmail.com',p.stdout)
        self.assertIn('one@work.example',p.stdout)
        p=self.raw('session','list','--details')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertNotIn('@gmail.com',p.stdout+p.stderr)
        self.assertIn('one@work.example',p.stdout)
        p=self.raw('session','list','--json')
        self.assertEqual({r['account'] for r in json.loads(p.stdout)},{'one@gmail.com','one@work.example'})
