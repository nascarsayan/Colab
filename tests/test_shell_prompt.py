import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
import test_creation_cli as fixtures

RC=Path(__file__).resolve().parents[1]/'src/shellrc.sh'

def script(name='SandyFinch'):
    return RC.read_text().replace('__COLAB_SESSION__',shlex.quote(name))

class Prompt(unittest.TestCase):
    def test_only_last_two_folders_and_literal_dollar(self):
        for path,expected in [('/content/drive/MyDrive/Code','MyDrive/Code'),('/a/b/c','b/c'),('/tmp','tmp'),('/','/'),('/a/My Drive/Project Files','My Drive/Project Files')]:
            with self.subTest(path=path):
                source=script()+'\nPWD='+shlex.quote(path)+'\n__colab_prompt\nprintf "%s" "$PS1"\n'
                p=subprocess.run(['/bin/bash','--noprofile','--norc'],input=source,env=dict(os.environ,NO_COLOR='1'),capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stderr)
                self.assertEqual(p.stdout,f'(SandyFinch) {expected} $ ')

    def test_prompt_updates_after_cd(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'one/two/three';path.mkdir(parents=True)
            source=script('MistyWillow')+'\ncd '+shlex.quote(str(path))+'''\n__colab_prompt
printf '%s\\n' "$PS1"
cd ..
__colab_prompt
printf '%s\\n' "$PS1"
'''
            p=subprocess.run(['/bin/bash','--noprofile','--norc'],input=source,env=dict(os.environ,NO_COLOR='1'),capture_output=True,text=True)
            self.assertEqual(p.stdout,'(MistyWillow) two/three $ \n(MistyWillow) one/two $ \n')

    def test_directory_text_is_not_executed_when_interactive_prompt_renders(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp);rc=home/'shellrc';rc.write_text(script())
            marker=home/'must-not-exist'
            dangerous='/tmp/$(touch must-not-exist)/leaf'
            commands='PWD='+shlex.quote(dangerous)+'\nexit\n'
            p=subprocess.run(['/bin/bash','--noprofile','--rcfile',str(rc),'-i'],input=commands,
                env={k:v for k,v in dict(os.environ,HOME=str(home),TERM='xterm-256color').items() if k!='NO_COLOR'},cwd=str(home),capture_output=True,text=True,timeout=10)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertFalse(marker.exists())

    def colored_prompt(self, failed=False, **extra):
        env={k:v for k,v in dict(os.environ,TERM='xterm-256color').items() if k!='NO_COLOR'}
        env.update(extra)
        source=script()+"\nPWD='/content/drive/MyDrive/Code'\n"+('false\n' if failed else 'true\n')+'__colab_prompt\nprintf "%s" "$PS1"\n'
        return subprocess.run(['/bin/bash','--noprofile','--norc'],input=source,env=env,capture_output=True,text=True,check=True).stdout

    def test_color_segments_and_readline_markers(self):
        value=self.colored_prompt()
        self.assertIn(r'\[\e[1;36m\](SandyFinch)',value)
        self.assertIn(r'\[\e[1;34m\]MyDrive/Code',value)
        self.assertIn(r'\[\e[1;32m\]$',value)
        self.assertEqual(value.count(r'\['),value.count(r'\]'))
        self.assertTrue(value.endswith(r'\[\e[0m\] '))

    def test_failed_command_turns_dollar_red(self):
        self.assertIn(r'\[\e[1;31m\]$',self.colored_prompt(failed=True))

    def test_plain_fallback_for_no_color_and_dumb_terminal(self):
        self.assertEqual(self.colored_prompt(NO_COLOR='1'),'(SandyFinch) MyDrive/Code $ ')
        self.assertEqual(self.colored_prompt(TERM='dumb'),'(SandyFinch) MyDrive/Code $ ')

class PromptWiring(unittest.TestCase):
    setUp=fixtures.CreationCLI.setUp
    script=fixtures.CreationCLI.script
    call=fixtures.CreationCLI.call
    calls=fixtures.CreationCLI.calls

    def test_connect_includes_selected_session_prompt_but_exec_does_not(self):
        p=self.call('session','create','SandyFinch');self.assertEqual(p.returncode,0,p.stderr)
        p=self.call('session','shell','-s','SandyFinch');self.assertEqual(p.returncode,0,p.stderr)
        commands=[json.loads(x) for x in (self.home/'ssh-calls.jsonl').read_text().splitlines()]
        self.assertIn('__colab_session=',commands[-1])
        self.assertIn('SandyFinch',commands[-1])
        self.assertIn('__colab_prompt',commands[-1])
        p=self.call('exec','-s','SandyFinch','echo hello');self.assertEqual(p.returncode,0,p.stderr)
        command=json.loads((self.home/'ssh-calls.jsonl').read_text().splitlines()[-1])
        self.assertNotIn('__colab_prompt',command)
