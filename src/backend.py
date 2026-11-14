"""Named, isolated Colab runtime management with persistent recovery settings."""
import json
import os
from pathlib import Path
import sys
import tempfile
(Path.home() / '.config/colab-cli').mkdir(parents=True, exist_ok=True)
from colab_cli.common import state
from colab_cli.state import SessionState
from colab_cli.commands.session import new

action, name, requested = sys.argv[1:4]
endpoint = (sys.argv[4] or None) if len(sys.argv) > 4 else None
memory_option = sys.argv[5] if len(sys.argv) > 5 else ''
if action == 'connect':
    sys.stdout = sys.stderr

settings_path = Path(__import__('os').environ.get('COLAB_PROFILE_DIR', str(Path.home() / '.config/Colab'))) / 'runtimes.json'
settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
current = state.store.get(name)
if action == 'create' and current:
    raise SystemExit(f'Session {name} already exists. Use start -s {name} to reuse it, or choose a different name.')
assignments = state.client.list_assignments()
saved = settings.get(name, {})
runtime = requested or (current.accelerator if current else saved.get('runtime', 'T4'))
runtime = runtime.upper().replace('-', '')
if runtime == 'CPU':
    runtime = 'NONE'
if runtime not in ('NONE', 'T4', 'L4', 'G4', 'H100', 'A100', 'V5E1', 'V6E1'):
    raise SystemExit(f'Unsupported runtime: {runtime}')
high_mem = (memory_option == 'true') if memory_option else (
    getattr(current, 'machine_shape', 'STANDARD') == 'HIGH_RAM' if current else saved.get('high_mem', False))


def remember():
    settings[name] = {**settings.get(name, {}), 'runtime': runtime, 'high_mem': high_mem}
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=settings_path.parent, delete=False) as out:
        json.dump(settings, out, sort_keys=True)
        out.flush()
        os.fsync(out.fileno())
        temporary = out.name
    os.replace(temporary, settings_path)


def allocate():
    remember()
    gpu = runtime if runtime in ('T4', 'L4', 'G4', 'H100', 'A100') else None
    tpu = runtime if runtime in ('V5E1', 'V6E1') else None
    new(session=name, gpu=gpu, tpu=tpu, high_mem=high_mem)


if action == 'create':
    # Explicit creation always allocates; it never aliases an existing endpoint.
    allocate()
    sys.exit(0)

active = next((a for a in assignments if current and a.endpoint == current.endpoint), None)
if active:
    if endpoint and current.endpoint != endpoint:
        raise SystemExit(f'Session {name} already refers to another runtime; choose another --session.')
    if current.accelerator.upper() != runtime:
        raise SystemExit(f'Session {name} uses {current.accelerator}; create a different named session for {runtime}.')
    if memory_option and (getattr(current, 'machine_shape', 'STANDARD') == 'HIGH_RAM') != high_mem:
        raise SystemExit(f'Session {name} has a different memory shape; create a different named session.')
    info = active.runtime_proxy_info
    current.token, current.url = info.token, info.url
    current.token_expires_at = info.expires_at()
    state.store.add(current)
    remember()
    if action != 'connect':
        print(f'Using session {name} ({current.endpoint})')
    sys.exit(0)

if current:
    print(f'Session {name} has expired; recovering a {runtime} runtime.', file=sys.stderr)
    remember()
    state.store.remove(name)
# Only unclaimed assignments are eligible for automatic adoption. An explicit
# endpoint in attach intentionally permits aliases, but creation never does.
claimed = {s.endpoint for n, s in state.store.list().items() if n != name}
candidates = [a for a in assignments if (
    a.endpoint == endpoint if endpoint else a.accelerator.value.upper() == runtime and a.endpoint not in claimed)]
if high_mem and not endpoint:
    candidates = [a for a in candidates if getattr(getattr(a, 'machine_shape', None), 'name', 'STANDARD') == 'HIGH_RAM']
if len(candidates) == 1:
    a = candidates[0]
    info = a.runtime_proxy_info
    # An explicit attachment takes the hardware of the selected endpoint.
    runtime = a.accelerator.value
    shape = getattr(getattr(a, 'machine_shape', None), 'name', 'STANDARD')
    high_mem = shape == 'HIGH_RAM'
    state.store.add(SessionState(name=name, endpoint=a.endpoint, token=info.token,
        url=info.url, token_expires_at=info.expires_at(),
        accelerator=runtime, variant=a.variant.name, machine_shape=shape))
    remember()
    print(f'Attached {name} to existing runtime {a.endpoint}')
elif action == 'attach':
    raise SystemExit('Specify an unambiguous unclaimed runtime endpoint using --endpoint; see Colab session list.')
elif candidates:
    raise SystemExit('Multiple matching unclaimed runtimes; use Colab session attach --account EMAIL --endpoint ENDPOINT.')
else:
    allocate()
