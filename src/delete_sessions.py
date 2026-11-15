"""Release exactly the snapshotted runtime endpoints; never allocate or mount Drive."""
import json
import sys
from colab_cli.common import state
endpoints = json.loads(sys.argv[1])
results = []
for endpoint in dict.fromkeys(endpoints):
    try:
        state.client.unassign(endpoint)
        for name, session in state.store.list().items():
            if session.endpoint == endpoint:
                state.store.remove(name)
        results.append({'endpoint': endpoint, 'deleted': True})
    except Exception as exc:
        # runner renders one readable error without exposing request credentials.
        results.append({'endpoint': endpoint, 'deleted': False})
        import re
        message = re.sub(r'https?://\S+', '[Google endpoint]', str(exc).splitlines()[0] if str(exc) else type(exc).__name__)
        print(f'Could not delete runtime {endpoint}: {message}', file=sys.stderr)
print(json.dumps(results))
if any(not result['deleted'] for result in results):
    sys.exit(1)
