"""Expose one managed Drive folder directly under /content without copying data."""
import errno
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

BACKINGS = (Path('/root/.Colab/drive'), Path('/content/drive'))
REGISTRY = Path('/root/.Colab/workspaces.json')

def is_mount(path):
    if os.path.ismount(path):
        return True
    # os.path.ismount misses bind mounts whose source shares the parent's device.
    try:
        for line in Path('/proc/self/mountinfo').read_text().splitlines():
            field = line.split()[4]
            for escaped, value in ((r'\040', ' '), (r'\011', '\t'), (r'\134', '\\')):
                field = field.replace(escaped, value)
            if field == str(path):
                return True
    except OSError:
        pass
    return False

def prepare(drive_path, mount_path, *, content=Path('/content'), backings=BACKINGS, registry=REGISTRY):
    target = Path(mount_path)
    if target.parent != content or target.name.startswith('.') or target.name in ('drive', 'sample_data'):
        raise RuntimeError('Workspace must be directly under /content, e.g. /content/Code.')
    logical = Path(drive_path)
    tail = logical.relative_to('/content/drive')
    if '..' in tail.parts:
        raise RuntimeError('Invalid Drive source folder.')
    registry.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(str(registry) + '.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        backing = next((p for p in backings if is_mount(p) and (p/'MyDrive').is_dir()), None)
        if backing is None:
            raise RuntimeError('Google Drive is not mounted; workspace was not created.')
        source = backing / tail
        # Resolve the parent first, so a Drive symlink cannot redirect mkdir elsewhere.
        parent = source.parent.resolve()
        if not parent.is_relative_to(backing.resolve()):
            raise RuntimeError('Drive source escapes the mounted Drive.')
        source.mkdir(parents=True, exist_ok=True)
        source = source.resolve()
        if not source.is_relative_to(backing.resolve()):
            raise RuntimeError('Drive source escapes the mounted Drive.')
        entries = json.loads(registry.read_text()) if registry.exists() else {}
        previous = entries.get(str(target))
        if target.is_symlink():
            raise RuntimeError(f'{target} is a symlink. Choose another --mount-path.')
        ready = False
        if is_mount(target):
            if previous and previous['drive_path'] != drive_path:
                raise RuntimeError(f'{target} already has another mount. Choose another --mount-path.')
            try:
                ready = os.path.samefile(target, source)
            except OSError as exc:
                if exc.errno not in (errno.EIO, errno.ENOTCONN):
                    raise
                ready = False
            if not previous and not ready:
                raise RuntimeError(f'{target} already has another mount. Choose another --mount-path.')
            if not ready:
                try:
                    stat = target.stat()
                    identity = [stat.st_dev, stat.st_ino]
                except OSError as exc:
                    if exc.errno not in (errno.EIO, errno.ENOTCONN):
                        raise
                    identity = previous.get('identity')
                if identity != previous.get('identity'):
                    raise RuntimeError(f'{target} has been replaced by another mount; refusing to unmount it.')
                result = subprocess.run(['umount', str(target)], capture_output=True, text=True)
                if result.returncode:
                    raise RuntimeError(f'{target} is busy or could not be remounted. Exit shells using it and retry.')
        if not ready:
            if target.exists() and (not target.is_dir() or any(target.iterdir())):
                raise RuntimeError(f'{target} is not an empty folder. No files were changed; choose another --mount-path.')
            target.mkdir(exist_ok=True)
            result = subprocess.run(['mount', '--bind', str(source), str(target)], capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f'Could not mount the Drive folder at {target}: {result.stderr.strip()}')
        if not is_mount(target) or not os.path.samefile(target, source):
            raise RuntimeError('Drive workspace mount could not be verified; no command was started.')
        stat = target.stat()
        entries[str(target)] = dict(drive_path=drive_path, source=str(source), backing=str(backing), identity=[stat.st_dev, stat.st_ino])
        with tempfile.NamedTemporaryFile('w', dir=registry.parent, delete=False) as stream:
            json.dump(entries, stream)
            temporary = stream.name
        os.replace(temporary, registry)

if __name__ == '__main__':
    try:
        prepare(*sys.argv[1:3])
    except Exception as exc:
        print(f'Workspace setup failed: {exc}', file=sys.stderr)
        sys.exit(1)
