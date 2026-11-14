"""Exercise the native workflow with fake Google/SSH processes; no cloud allocation."""
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
        self.temp = tempfile.TemporaryDirectory(dir='/private/tmp' if sys.platform == 'darwin' else '/tmp')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.bin = self.home / 'bin'; self.bin.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(self.bin))
        interpreter = self.script('fake-python', '''import json,os,pathlib,sys
home=pathlib.Path(os.environ['HOME']);source=sys.argv[3];args=sys.argv[4:]
log=home/'calls.jsonl'
if 'Named, isolated Colab runtime' in source:
 action,name,runtime=args[:3]
 with log.open('a') as f:f.write(json.dumps(args)+'\\n')
 p=home/'.config/colab-cli/sessions.json';p.parent.mkdir(parents=True,exist_ok=True)
 state=json.loads(p.read_text()) if p.exists() else {}
 state[name]={'name':name,'endpoint':'endpoint-'+name};p.write_text(json.dumps(state))
elif 'Return the first active runtime' in source:
 p=home/'.config/colab-cli/sessions.json';state=json.loads(p.read_text()) if p.exists() else {}
 if state: print(next(iter(state)))
 elif args[1]=='1': print(args[0])
 else: print('Error: No active sessions. Run Colab session create.',file=sys.stderr);sys.exit(1)
elif 'from colab_cli.cli import app' in source:
 with (home/'cli-calls.jsonl').open('a') as f:f.write(json.dumps(args)+'\\n')
elif 'Recursive copy and conflict-aware sync' in source:
 if os.environ.get('MOCK_SYNC_FAIL'): print('Copy/sync failed: interrupted transfer',file=sys.stderr);sys.exit(1)
 with (home/'sync-calls.jsonl').open('a') as f:f.write(json.dumps(args[1:])+'\\n')
''')
        (self.bin/'colab').write_text('#!'+str(interpreter)+'\n');(self.bin/'colab').chmod(0o755)
        self.script('ssh-keygen', "import pathlib,sys; pathlib.Path(sys.argv[sys.argv.index('-f')+1]).write_text('fake key')")
        self.script('ssh', '''import os,pathlib,sys,json
args=sys.argv[1:];home=pathlib.Path(os.environ['HOME']);sock=pathlib.Path(args[args.index('-S')+1])
if '-O' in args:
 if args[args.index('-O')+1]=='check':sys.exit(0 if sock.exists() else 1)
 if sock.exists():sock.unlink()
elif '-M' in args:sock.touch()
else:
 with (home/'ssh-calls.jsonl').open('a') as f:f.write(json.dumps(args[-1])+'\\n')
 if args[-1].startswith('cd '):print('remote-ok')
''')

    def script(self,name,code):
        path=self.bin/name;path.write_text('#!'+sys.executable+'\n'+code+'\n');path.chmod(0o755);return path

    def call(self,*args):
        return subprocess.run([str(CLI),*args],env=self.env,capture_output=True,text=True,timeout=20)

    def calls(self):
        p=self.home/'calls.jsonl'
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def test_named_creation_runtime_and_high_memory_forwarding(self):
        for name,runtime,expected in [('cpu-job','CPU','NONE'),('gpu-job','T4','T4'),('l4-job','l4','L4'),('g4-job','g4','G4'),('a100-job','a100','A100'),('h100-job','H100','H100'),('tpu5','v5e1','V5E1'),('tpu6','v6e-1','V6E1')]:
            with self.subTest(runtime=runtime):
                p=self.call('create',name,'--runtime',runtime,'--high-mem')
                self.assertEqual(p.returncode,0,p.stderr)
                self.assertIn(['create',name,expected,'','true'],self.calls())

    def test_start_without_runtime_keeps_saved_configuration(self):
        p=self.call('start','-s','trainer');self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn(['start','trainer','','',''],self.calls())

    def test_invalid_names_and_runtimes_rejected_before_backend(self):
        for args in [('create','../unsafe'),('create','ok','--runtime','invalid')]:
            self.assertEqual(self.call(*args).returncode,2)
        self.assertEqual(self.calls(),[])

    def test_legacy_gpu_alias_and_conflicting_flags(self):
        p=self.call('start','-s','trainer','--gpu','T4');self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn(['start','trainer','T4','',''],self.calls())
        self.assertEqual(self.call('start','--runtime','cpu','--gpu','T4').returncode,2)

    def test_generated_name_default_drive_and_shell_directory(self):
        p=self.call('create');self.assertEqual(p.returncode,0,p.stderr)
        name=next(args[1] for args in self.calls() if args[0]=='create')
        self.assertRegex(name,r'^[A-Z][a-z]+[A-Z][a-z]+$')
        self.assertNotIn('gpu-proxy',p.stdout)
        p=self.call('shell');self.assertEqual(p.returncode,0,p.stderr)
        commands=(self.home/'ssh-calls.jsonl').read_text()
        self.assertIn('cd \'/content/drive/MyDrive/Code\'',commands)

    def test_first_open_session_is_default_and_explicit_name_overrides(self):
        self.assertEqual(self.call('create','ZestyFirst').returncode,0)
        self.assertEqual(self.call('create','BreezySecond').returncode,0)
        p=self.call('exec','pwd');self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('Using session ZestyFirst',p.stderr)
        p=self.call('exec','-s','BreezySecond','pwd');self.assertEqual(p.returncode,0,p.stderr)
        self.assertNotIn('Using session ZestyFirst',p.stderr)

    def test_local_folder_sync_happens_before_exec_and_can_be_skipped(self):
        local=self.home/'project';local.mkdir()
        p=self.call('create','trainer','--drive-path','~/Projects/Test','--local-dir',str(local))
        self.assertEqual(p.returncode,0,p.stderr)
        p=self.call('exec','-s','trainer','pwd');self.assertEqual(p.returncode,0,p.stderr)
        calls=[json.loads(x) for x in (self.home/'sync-calls.jsonl').read_text().splitlines()]
        self.assertEqual(len(calls),2)
        self.assertIn(str(local),calls[-1]);self.assertIn('>',calls[-1]);self.assertIn('colab:/content/drive/MyDrive/Projects/Test',calls[-1])
        p=self.call('--no-auto-sync','exec','-s','trainer','pwd');self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(len((self.home/'sync-calls.jsonl').read_text().splitlines()),2)

    def test_missing_local_folder_fails_before_allocating(self):
        p=self.call('create','trainer','--local-dir',str(self.home/'missing'))
        self.assertNotEqual(p.returncode,0);self.assertIn('does not exist',p.stderr);self.assertEqual(self.calls(),[])

    def test_no_active_session_does_not_allocate_for_exec(self):
        p=self.call('exec','pwd');self.assertNotEqual(p.returncode,0)
        self.assertIn('No active sessions',p.stderr);self.assertEqual(self.calls(),[])

    def test_copy_and_shell_also_sync_before_operation(self):
        local=self.home/'source';local.mkdir()
        p=self.call('create','trainer','--local-dir',str(local));self.assertEqual(p.returncode,0,p.stderr)
        p=self.call('cp','-s','trainer',str(local),'colab:/content/destination');self.assertEqual(p.returncode,0,p.stderr)
        calls=[json.loads(x) for x in (self.home/'sync-calls.jsonl').read_text().splitlines()]
        self.assertEqual([c[3] for c in calls],['sync','sync','cp'])
        p=self.call('shell','-s','trainer');self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(len((self.home/'sync-calls.jsonl').read_text().splitlines()),4)

    def test_disappearing_local_folder_prevents_remote_execution(self):
        local=self.home/'source';local.mkdir()
        self.assertEqual(self.call('create','trainer','--local-dir',str(local)).returncode,0)
        before=(self.home/'ssh-calls.jsonl').read_text()
        local.rmdir()
        p=self.call('exec','-s','trainer','dangerous-task')
        self.assertNotEqual(p.returncode,0);self.assertIn('local sync folder is missing',p.stderr)
        self.assertEqual((self.home/'ssh-calls.jsonl').read_text(),before)

    def test_invalid_drive_folder_is_rejected_before_allocation(self):
        p=self.call('create','trainer','--drive-path','~/../escape')
        self.assertNotEqual(p.returncode,0);self.assertIn('Invalid Drive folder',p.stderr)
        self.assertEqual(self.calls(),[])

    def test_failed_automatic_sync_blocks_remote_command(self):
        local=self.home/'source';local.mkdir()
        self.assertEqual(self.call('create','trainer','--local-dir',str(local)).returncode,0)
        self.env['MOCK_SYNC_FAIL']='1'
        p=self.call('exec','-s','trainer','dangerous-task')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('interrupted transfer',p.stderr)
        self.assertNotIn('dangerous-task',(self.home/'ssh-calls.jsonl').read_text())
