import contextlib
import io
from pathlib import Path
import runpy
import sys
import types
import unittest
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[1] / 'src/login.py'


class Login(unittest.TestCase):
    def invoke(self, no_browser=False, saved='sensitive token', failure=None):
        echo = Mock()
        auth = types.SimpleNamespace(typer=types.SimpleNamespace(echo=echo),
            KEYRING_SERVICE_NAME='google-colab-cli', KEYRING_USERNAME='oauth_token')
        def request():
            auth.typer.echo('  https://accounts.google.com/example  ', err=True)
            if failure:
                raise failure
            return []
        state = types.SimpleNamespace(client=types.SimpleNamespace(list_assignments=request))
        modules = {'colab_cli': types.SimpleNamespace(auth=auth),
                   'colab_cli.common': types.SimpleNamespace(state=state),
                   'keyring': types.SimpleNamespace(get_password=Mock(return_value=saved))}
        output, error = io.StringIO(), io.StringIO()
        code = 0
        with patch.dict(sys.modules, modules), patch.object(sys, 'argv', ['login'] + (['--no-browser'] if no_browser else [])), patch('webbrowser.open', return_value=True) as browser, contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            try:
                runpy.run_path(str(SCRIPT), run_name='__main__')
            except SystemExit as exc:
                code = exc.code
        self.assertIs(auth.typer.echo, echo)
        self.assertNotIn('sensitive token', output.getvalue() + error.getvalue())
        return code, browser, output.getvalue(), error.getvalue()

    def test_browser_opens_and_saved_credentials_are_verified(self):
        code, browser, out, err = self.invoke()
        self.assertEqual(code, 0)
        browser.assert_called_once_with('https://accounts.google.com/example')
        self.assertIn('saved in OS keyring', out)

    def test_headless_login_does_not_open_browser(self):
        code, browser, out, err = self.invoke(no_browser=True)
        self.assertEqual(code, 0)
        browser.assert_not_called()

    def test_unsaved_credentials_do_not_report_setup_success(self):
        code, browser, out, err = self.invoke(saved=None)
        self.assertEqual(code, 1)
        self.assertIn('credentials were not saved', err)

    def test_noninteractive_login_reports_code_prompt_requirement(self):
        code, browser, out, err = self.invoke(failure=EOFError())
        self.assertEqual(code, 1)
        self.assertIn('interactive terminal', err)
