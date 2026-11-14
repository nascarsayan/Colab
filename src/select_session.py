"""Return the first active runtime in backend listing order, adopting it if needed."""
import sys
from colab_cli.common import state
from colab_cli.state import SessionState

candidate, allow_new = sys.argv[1:3]
assignments = state.client.list_assignments()
local = state.store.list()
if not assignments:
    if allow_new == '1':
        print(candidate)
    else:
        raise SystemExit('No active sessions. Run Colab session create [NAME] --runtime t4 (or --runtime cpu).')
else:
    first = assignments[0]
    found = next((s.name for s in local.values() if s.endpoint == first.endpoint), None)
    if found:
        print(found)
    else:
        info = first.runtime_proxy_info
        shape = getattr(first.machine_shape, 'name', 'STANDARD')
        state.store.add(SessionState(name=candidate, endpoint=first.endpoint, token=info.token,
            url=info.url, token_expires_at=info.expires_at(), accelerator=first.accelerator.value,
            variant=first.variant.name, machine_shape=shape))
        print(candidate)
