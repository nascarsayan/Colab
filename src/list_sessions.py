"""Return session inventory as JSON without SSH, mounting, or runtime allocation."""
import json
import os
from pathlib import Path
import sys
import uuid
from colab_cli.common import state

profile = Path(os.environ['COLAB_PROFILE_DIR'])
sessions = state.store.list()
assignments = state.client.list_assignments()
name_filter = sys.argv[1] if len(sys.argv) > 1 else ''
rows = []
for assignment in assignments:
    aliases = [name for name, session in sessions.items() if session.endpoint == assignment.endpoint]
    if name_filter and name_filter not in aliases:
        continue
    name = name_filter or (aliases[0] if aliases else '?')
    ident = uuid.uuid5(uuid.NAMESPACE_URL, name).hex
    workspace_file = profile / 'workspaces' / (ident + '.json')
    workspace = json.loads(workspace_file.read_text()) if workspace_file.exists() else {}
    source = workspace.get('drive_path', '/content/drive/MyDrive/Code').rstrip('/')
    remote = workspace.get('mount_path', '/content/' + source.split('/')[-1])
    drive_folder = '~' + source[len('/content/drive/MyDrive'):] if source == '/content/drive/MyDrive' or source.startswith('/content/drive/MyDrive/') else source
    local = workspace.get('local_dir')
    pairs = []
    for path in sorted((profile / 'sync').glob('*.target.json')):
        target = json.loads(path.read_text())
        if target.get('session') == name:
            pairs.append({k: target.get(k) for k in ('left','right','direction','last_success_utc')})
    session = sessions.get(name)
    rows.append(dict(session=name, names=aliases, endpoint=assignment.endpoint,
        runtime=('CPU' if assignment.accelerator.value == 'NONE' else assignment.accelerator.value), variant=assignment.variant.name,
        shape=assignment.machine_shape.name.replace("_", " ").title(),
        status=('BUSY' if session.running else 'IDLE') if session else 'UNKNOWN',
        workspace=remote, drive_folder=drive_folder, drive_access='read/write', drive_mount='not checked',
        drive_previously_mounted=(profile / 'drive' / (ident + '.enabled')).exists(),
        local_folder=local, pc_sync_direction='PC -> Colab' if local else None,
        pc_sync_when='before operations' if local else None, sync_pairs=pairs))
print(json.dumps(rows))
