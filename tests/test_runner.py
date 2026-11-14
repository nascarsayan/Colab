import contextlib
import io
import os
from pathlib import Path
import runpy
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

RUNNER=Path(__file__).resolve().parents[1]/'src/runner.py'

class Runner(unittest.TestCase):
    def invoke(self,source,allow_login=False,runtime=None):
        with tempfile.TemporaryDirectory() as home:
            auth=types.SimpleNamespace(_run_remote_flow=lambda *_:'allowed')
            modules={'colab_cli':types.SimpleNamespace(auth=auth)}
            if runtime is not None: modules['colab_cli.runtime']=types.SimpleNamespace(ColabRuntime=runtime)
            out,err=io.StringIO(),io.StringIO();code=0
            with patch.dict(sys.modules,modules),patch.dict(os.environ,{'COLAB_ALLOW_LOGIN':'1' if allow_login else '0','XDG_CONFIG_HOME':str(Path(home)/'.config')}),patch('pathlib.Path.home',return_value=Path(home)),patch.object(sys,'argv',['runner',source,'argument']),contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
                try:runpy.run_path(str(RUNNER),run_name='__main__')
                except SystemExit as exc:code=exc.code
            self.assertNotIn('Traceback',err.getvalue())
            self.assertTrue((Path(home)/'.config/colab-cli').is_dir())
            return code,out.getvalue(),err.getvalue()

    def test_missing_state_parent_created_before_backend(self):
        code,out,err=self.invoke("from pathlib import Path\n(Path.home()/'.config/colab-cli/sessions.json.lock').touch()\nimport sys\nprint(sys.argv[1])")
        self.assertEqual((code,out,err),(0,'argument\n',''))

    def test_no_internet_is_readable(self):
        code,out,err=self.invoke("raise ConnectionError('Network unreachable')")
        self.assertEqual(code,1);self.assertIn('Internet connection',err)

    def test_not_logged_in_does_not_prompt_or_consume_stdin(self):
        code,out,err=self.invoke("from colab_cli import auth\nauth._run_remote_flow({})")
        self.assertEqual(code,1);self.assertIn('Colab auth login',err);self.assertNotIn('https://',err)

    def test_login_explicitly_permits_oauth(self):
        self.assertEqual(self.invoke("from colab_cli import auth\nprint(auth._run_remote_flow({}))",True),(0,'allowed\n',''))

    def test_quota_context_and_typer_exit_are_translated(self):
        source='''class TooManyAssignmentsError(Exception): pass
class Exit(Exception): exit_code=1
try: raise TooManyAssignmentsError('Precondition Failed')
except Exception: raise Exit()
'''
        code,out,err=self.invoke(source)
        self.assertEqual(code,1);self.assertIn('session limit',err);self.assertIn('Colab session stop',err)

    def test_backend_exit_preserves_status_without_trace(self):
        code,out,err=self.invoke("class Exit(Exception): exit_code=7\nraise Exit()")
        self.assertEqual(code,7)
        self.assertEqual(self.invoke("class Exit(Exception): exit_code=0\nraise Exit()")[0],0)

    def test_unknown_error_redacts_query_url(self):
        code,out,err=self.invoke("raise RuntimeError('Failed https://google.invalid/?token=secret')")
        self.assertEqual(code,1);self.assertNotIn('token=secret',err)

    def test_drive_notebook_error_is_raised_before_traceback_rendering(self):
        class Runtime:
            def execute_code(self,*args,**kwargs):
                return [{'output_type':'error','ename':'ValueError','evalue':'mount failed','traceback':['Traceback: secret internal details']}]
        code,out,err=self.invoke('from colab_cli.runtime import ColabRuntime\nColabRuntime().execute_code("drive.mount")',runtime=Runtime)
        self.assertEqual(code,1)
        self.assertIn('Runtime setup failed (ValueError): mount failed',err)
        self.assertNotIn('secret internal details',err)
