import contextlib
import io
from pathlib import Path
import runpy
import sys
import types
import unittest
from unittest.mock import Mock,patch

SCRIPT=Path(__file__).resolve().parents[1]/'src/select_session.py'

def assignment(endpoint):
    return types.SimpleNamespace(endpoint=endpoint,machine_shape=types.SimpleNamespace(name='STANDARD'),
        accelerator=types.SimpleNamespace(value='T4'),variant=types.SimpleNamespace(name='GPU'),
        runtime_proxy_info=types.SimpleNamespace(token='token',url='https://runtime.invalid',expires_at=lambda:123))

class Selection(unittest.TestCase):
    def select(self,assignments,local,allow=False):
        state=types.SimpleNamespace(client=Mock(),store=Mock())
        state.client.list_assignments.return_value=assignments;state.store.list.return_value=local
        modules={'colab_cli':types.ModuleType('colab_cli'),'colab_cli.common':types.SimpleNamespace(state=state),
            'colab_cli.state':types.SimpleNamespace(SessionState=lambda **kwargs:types.SimpleNamespace(**kwargs))}
        out=io.StringIO();error=None
        with patch.dict(sys.modules,modules),patch.object(sys,'argv',['select','SunnyMarble','1' if allow else '0']),contextlib.redirect_stdout(out):
            try:runpy.run_path(str(SCRIPT),run_name='__main__')
            except SystemExit as exc:error=str(exc)
        return out.getvalue().strip(),state,error

    def test_server_order_wins_over_alphabetic_local_names(self):
        local={'Apple':types.SimpleNamespace(name='Apple',endpoint='second'),'Zebra':types.SimpleNamespace(name='Zebra',endpoint='first')}
        name,state,error=self.select([assignment('first'),assignment('second')],local)
        self.assertEqual(name,'Zebra');state.store.add.assert_not_called()

    def test_untracked_first_runtime_gets_generated_name_without_new_allocation(self):
        name,state,error=self.select([assignment('first')],{})
        self.assertEqual(name,'SunnyMarble');self.assertEqual(state.store.add.call_args.args[0].endpoint,'first')

    def test_empty_exec_is_actionable_but_start_gets_generated_name(self):
        self.assertIn('No active sessions',self.select([],{},False)[2])
        self.assertEqual(self.select([],{},True)[0],'SunnyMarble')
