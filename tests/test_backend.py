"""Regression tests for expired-session recovery; no Google credentials needed."""
import contextlib
import io
import json
import tempfile
from pathlib import Path
import runpy
import sys
import types
import unittest
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[1] / 'src/backend.py'

def assignment(endpoint='active', gpu='T4'):
    return types.SimpleNamespace(endpoint=endpoint, accelerator=types.SimpleNamespace(value=gpu),
        variant=types.SimpleNamespace(name='GPU'),
        runtime_proxy_info=types.SimpleNamespace(token='fresh', url='https://runtime.invalid', expires_at=lambda: 123))

class Recovery(unittest.TestCase):
    def execute(self, current=None, active=(), action='connect', gpu='', listing_error=None, owned=None, memory='', home=None):
        state = types.SimpleNamespace(client=Mock(), store=Mock())
        state.client.list_assignments.return_value = list(active)
        if listing_error:
            state.client.list_assignments.side_effect = listing_error
        state.store.get.return_value = current
        state.store.list.return_value = owned if owned is not None else ({'gpu-proxy': current} if current else {})
        provision = Mock()
        modules = {
            'colab_cli': types.ModuleType('colab_cli'),
            'colab_cli.commands': types.ModuleType('colab_cli.commands'),
            'colab_cli.common': types.SimpleNamespace(state=state),
            'colab_cli.state': types.SimpleNamespace(SessionState=lambda **kw: types.SimpleNamespace(**kw)),
            'colab_cli.commands.session': types.SimpleNamespace(new=provision),
        }
        out, err = io.StringIO(), io.StringIO()
        caught = None
        with (contextlib.ExitStack() as stack):
            temporary_home = stack.enter_context(tempfile.TemporaryDirectory()) if home is None else home
            stack.enter_context(patch('pathlib.Path.home', return_value=Path(temporary_home)))
            stack.enter_context(patch.dict(sys.modules, modules))
            stack.enter_context(patch.object(sys, 'argv', ['backend', action, 'gpu-proxy', gpu, '', memory]))
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            try:
                runpy.run_path(str(SCRIPT), run_name='__main__')
            except (SystemExit, RuntimeError) as exc:
                caught = exc
        return state, provision, out.getvalue(), err.getvalue(), caught

    def test_missing_session_provisions_default_t4_without_stdout(self):
        state, provision, out, err, exc = self.execute()
        provision.assert_called_once_with(session='gpu-proxy', gpu='T4', tpu=None, high_mem=False)
        self.assertEqual(out, '')
        self.assertIsNone(exc)

    def test_expired_session_preserves_accelerator(self):
        current = types.SimpleNamespace(endpoint='gone', accelerator='L4')
        state, provision, out, err, exc = self.execute(current=current)
        provision.assert_called_once_with(session='gpu-proxy', gpu='L4', tpu=None, high_mem=False)
        state.store.remove.assert_called_once_with('gpu-proxy')
        self.assertIn('expired', err)
        self.assertEqual(out, '')

    def test_active_session_refreshes_proxy_credentials(self):
        current = types.SimpleNamespace(endpoint='active', accelerator='T4', token='old')
        state, provision, out, err, exc = self.execute(current=current, active=[assignment()])
        self.assertEqual(current.token, 'fresh')
        state.store.add.assert_called_once_with(current)
        provision.assert_not_called()
        self.assertEqual(out, '')
        self.assertEqual(exc.code, 0)

    def test_missing_local_state_adopts_existing_runtime(self):
        state, provision, out, err, exc = self.execute(active=[assignment()])
        provision.assert_not_called()
        self.assertEqual(state.store.add.call_args.args[0].endpoint, 'active')
        self.assertEqual(out, '')
        self.assertIn('Attached', err)

    def test_ambiguous_runtimes_do_not_provision(self):
        state, provision, out, err, exc = self.execute(active=[assignment('one'), assignment('two')])
        provision.assert_not_called()
        self.assertIn('Multiple matching', str(exc))

    def test_auth_failure_does_not_delete_saved_session(self):
        current = types.SimpleNamespace(endpoint='saved', accelerator='T4')
        state, provision, out, err, exc = self.execute(current=current, listing_error=RuntimeError('auth failed'))
        state.store.remove.assert_not_called()
        provision.assert_not_called()
        self.assertEqual(str(exc), 'auth failed')

    def test_attach_does_not_create_runtime(self):
        state, provision, out, err, exc = self.execute(action='attach', gpu='T4')
        provision.assert_not_called()
        self.assertIn('unambiguous', str(exc))

    def test_create_does_not_alias_existing_matching_gpu(self):
        state, provision, out, err, exc = self.execute(action='create', gpu='T4', active=[assignment()])
        provision.assert_called_once_with(session='gpu-proxy', gpu='T4', tpu=None, high_mem=False)
        state.store.add.assert_not_called()
        self.assertEqual(exc.code, 0)

    def test_create_rejects_duplicate_session_name(self):
        current = types.SimpleNamespace(endpoint='active', accelerator='T4')
        state, provision, out, err, exc = self.execute(action='create', gpu='T4', current=current)
        provision.assert_not_called()
        self.assertIn('already exists', str(exc))

    def test_other_named_runtime_is_not_adopted(self):
        owned = {'another-session': types.SimpleNamespace(endpoint='active')}
        state, provision, out, err, exc = self.execute(active=[assignment()], owned=owned)
        provision.assert_called_once_with(session='gpu-proxy', gpu='T4', tpu=None, high_mem=False)
        state.store.add.assert_not_called()

    def test_create_cpu_and_tpu_route_to_correct_backend(self):
        for runtime, gpu, tpu in [('CPU', None, None), ('NONE', None, None), ('V5E1', None, 'V5E1'), ('V6E1', None, 'V6E1')]:
            with self.subTest(runtime=runtime):
                state, provision, out, err, exc = self.execute(action='create', gpu=runtime)
                provision.assert_called_once_with(session='gpu-proxy', gpu=gpu, tpu=tpu, high_mem=False)
                self.assertEqual(exc.code, 0)

    def test_high_memory_setting_is_forwarded(self):
        state, provision, out, err, exc = self.execute(action='create', gpu='A100', memory='true')
        provision.assert_called_once_with(session='gpu-proxy', gpu='A100', tpu=None, high_mem=True)

    def test_pruned_session_recovers_saved_runtime_and_memory(self):
        with tempfile.TemporaryDirectory() as home:
            self.execute(action='create', gpu='V6E1', memory='true', home=home)
            state, provision, out, err, exc = self.execute(home=home)
            provision.assert_called_once_with(session='gpu-proxy', gpu=None, tpu='V6E1', high_mem=True)

    def test_runtime_mismatch_does_not_replace_active_session(self):
        current = types.SimpleNamespace(endpoint='active', accelerator='T4')
        state, provision, out, err, exc = self.execute(current=current, active=[assignment()], action='start', gpu='A100')
        provision.assert_not_called()
        state.store.remove.assert_not_called()
        self.assertIn('create a different named session', str(exc))

if __name__ == '__main__':
    unittest.main()
