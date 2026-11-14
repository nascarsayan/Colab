"""Small filesystem RPC, executed locally or over the existing SSH socket."""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile


def safe_path(root, relative=''):
    root = Path(os.path.abspath(os.path.expanduser(root)))
    if root.is_symlink():
        raise ValueError(f'Symlinks are not supported: {root}')
    # Canonicalize the selected root's parent (macOS /tmp and /var are aliases).
    # Links in the selected tree itself are still rejected below.
    root = root.parent.resolve() / root.name
    drive = Path('/content/drive')
    if root == drive or drive in root.parents:
        if not os.path.ismount(drive) or not (drive / 'MyDrive').is_dir():
            raise RuntimeError('Google Drive is not mounted; no files were written. Run Colab drive mount --account EMAIL.')
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Invalid relative path')
    path = root / relative
    for part in [path, *path.parents]:
        if part.is_symlink():
            raise ValueError(f'Symlinks are not supported: {part}')
    return path


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def entry(path):
    if not path.exists():
        return None
    mode = path.stat().st_mode
    if stat.S_ISDIR(mode):
        return {'kind': 'dir'}
    if not stat.S_ISREG(mode):
        raise ValueError(f'Only regular files and directories are supported: {path}')
    return {'kind': 'file', 'sha256': digest(path), 'mode': stat.S_IMODE(mode) & 0o777}


def inventory(root):
    root = safe_path(root)
    if not root.exists():
        return {}
    result = {'': entry(root)}
    if root.is_dir():
        for parent, dirs, files in os.walk(root, followlinks=False):
            # A forcibly killed transfer can leave staging files behind. Never
            # treat these partial files as user data on a later sync.
            dirs[:] = [name for name in dirs if not name.startswith('.Colab-')]
            files = [name for name in files if not name.startswith('.Colab-')]
            for name in sorted(dirs + files):
                path = safe_path(root, str((Path(parent) / name).relative_to(root)))
                result[str(path.relative_to(root))] = entry(path)
    return result


def verify(path, expected):
    actual = entry(path)
    if actual != expected:
        raise RuntimeError(f'Destination changed since planning: {path}; retry after checking concurrent edits')


def commit(root, relative, source, expected, stream):
    path = safe_path(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_path(root, relative)
    verify(path, expected)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.Colab-', delete=False) as out:
            temporary = out.name
            h = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                out.write(chunk)
                h.update(chunk)
            out.flush()
            os.fsync(out.fileno())
        if h.hexdigest() != source['sha256']:
            raise RuntimeError(f'Checksum mismatch; destination left unchanged: {path}')
        os.chmod(temporary, source['mode'])
        safe_path(root, relative)
        verify(path, expected)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary:
            os.unlink(temporary)


def main():
    request = json.loads(sys.argv[1])
    action, root = request['action'], request['root']
    if action == 'scan':
        print(json.dumps(inventory(root)))
    elif action == 'get':
        path = safe_path(root, request['relative'])
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                sys.stdout.buffer.write(chunk)
    elif action == 'put':
        commit(root, request['relative'], request['source'], request['expected'], sys.stdin.buffer)
    elif action == 'mkdir':
        path = safe_path(root, request['relative'])
        path.mkdir(parents=True, exist_ok=True)
        safe_path(root, request['relative'])
    else:
        raise ValueError('Unknown filesystem action')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'File operation failed: {exc}', file=sys.stderr)
        sys.exit(1)
