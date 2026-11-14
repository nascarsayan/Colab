"""List active assignments matching a local session name, without selecting a runtime."""
import sys
from colab_cli.common import state
from colab_cli.commands.session import _format_session_line
sessions, assignments = state.sync_sessions()
name = sys.argv[1]
session = sessions.get(name)
found = False
for assignment in assignments:
    if session and assignment.endpoint == session.endpoint:
        print(_format_session_line(name=name, endpoint=assignment.endpoint,
            accelerator=assignment.accelerator.value, variant=assignment.variant.name,
            machine_shape=assignment.machine_shape.name))
        found = True
if not found:
    print(f'No active session named {name}.')
