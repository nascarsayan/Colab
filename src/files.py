"""Recursive copy and conflict-aware sync over one SSH master. No extra packages."""
from datetime import datetime, timezone
import contextlib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

RPC, SOCKET, STATE_DIR, SESSION, ACTION, LEFT, DIRECTION, RIGHT, DRY = sys.argv[1:10]
namespace = {'__name__': 'file_rpc'}
exec(RPC, namespace)


class Endpoint:
    def __init__(self, text):
        self.remote = text.startswith(('colab:', 'collab:'))
        self.root = text.split(':', 1)[1] if self.remote else os.path.abspath(os.path.expanduser(text))
        if not self.root or (self.remote and not self.root.startswith('/')):
            raise ValueError('Remote paths must be absolute, for example colab:/content/data')
        self.root = os.path.normpath(self.root)

    def name(self):
        return ('colab:' if self.remote else '') + self.root

    def ssh(self, request, **kwargs):
        remote = shlex.join(['python3', '-c', RPC, json.dumps(request)])
        return subprocess.Popen(['ssh', '-F', '/dev/null', '-S', SOCKET,
            '-o', 'ControlMaster=no', '-o', 'ProxyCommand=false', '-o', 'LogLevel=ERROR',
            '-T', 'root@colab-runtime', remote], **kwargs)

    def scan(self):
        if not self.remote:
            return namespace['inventory'](self.root)
        with self.ssh({'action': 'scan', 'root': self.root}, stdout=subprocess.PIPE) as p:
            data = p.stdout.read()
            if p.wait():
                raise RuntimeError(f'Could not read {self.name()}')
        return json.loads(data)

    def mkdir(self, relative):
        if self.remote:
            with self.ssh({'action': 'mkdir', 'root': self.root, 'relative': relative}) as p:
                if p.wait():
                    raise RuntimeError(f'Could not create directory in {self.name()}')
        else:
            namespace['safe_path'](self.root, relative).mkdir(parents=True, exist_ok=True)

    @contextlib.contextmanager
    def fetch(self, relative, expected):
        # Spool one file to disk, verify it, then atomically install it. This keeps
        # memory bounded and never installs a partial or corrupted transfer.
        with tempfile.TemporaryFile() as spool:
            h = hashlib.sha256()
            def consume(reader):
                for chunk in iter(lambda: reader.read(1024 * 1024), b''):
                    h.update(chunk)
                    spool.write(chunk)
            if self.remote:
                with self.ssh({'action': 'get', 'root': self.root, 'relative': relative}, stdout=subprocess.PIPE) as p:
                    consume(p.stdout)
                    if p.wait():
                        raise RuntimeError(f'Download interrupted: {relative}; destination unchanged')
            else:
                with open(namespace['safe_path'](self.root, relative), 'rb') as reader:
                    consume(reader)
            if h.hexdigest() != expected['sha256']:
                raise RuntimeError(f'Source changed while copying {relative}; destination unchanged')
            spool.seek(0)
            yield spool

    def put(self, relative, source, expected, stream):
        if not self.remote:
            namespace['commit'](self.root, relative, source, expected, stream)
        else:
            with self.ssh({'action': 'put', 'root': self.root, 'relative': relative,
                          'source': source, 'expected': expected}, stdin=stream) as p:
                if p.wait():
                    raise RuntimeError(f'Upload failed: {relative}; rerun to reconcile completed files')


def same(a, b):
    # Modes do not define content conflicts; bytes and file-vs-directory do.
    return a is not None and b is not None and a['kind'] == b['kind'] and a.get('sha256') == b.get('sha256')


def plan(left, right, baseline=None, bidirectional=False, copy_all=False):
    operations, conflicts = [], []
    for rel in sorted(set(left) | (set(right) if bidirectional else set()), key=lambda p: (p.count('/'), p)):
        a, b = left.get(rel), right.get(rel)
        if a and b and a['kind'] != b['kind']:
            conflicts.append(rel or '.')
        elif a and b and a['kind'] == 'dir':
            continue
        elif not copy_all and same(a, b):
            continue
        elif not bidirectional:
            operations.append(('>', rel, a, b))
        elif a is None:
            operations.append(('<', rel, b, a))
        elif b is None:
            operations.append(('>', rel, a, b))
        elif same(a, (baseline or {}).get(rel)):
            operations.append(('<', rel, b, a))
        elif same(b, (baseline or {}).get(rel)):
            operations.append(('>', rel, a, b))
        else:
            conflicts.append(rel or '.')
    if conflicts:
        raise RuntimeError('Sync conflicts; no files copied. Resolve differing files or explicitly choose a one-way sync:\n' + '\n'.join(conflicts))
    return operations


def run():
    left, right = Endpoint(LEFT), Endpoint(RIGHT)
    if left.remote == right.remote:
        raise ValueError('Exactly one endpoint must use colab:/absolute/path')
    if DIRECTION == '<':
        left, right = right, left
    pair = json.dumps([SESSION, *sorted([left.name(), right.name()])])
    key = hashlib.sha256(pair.encode()).hexdigest()
    state_dir = Path(STATE_DIR) / 'sync'
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    baseline_path = state_dir / (key + '.json')
    with open(state_dir / (key + '.lock'), 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        a, b = left.scan(), right.scan()
        if ACTION == 'cp':
            if '' not in a:
                raise ValueError(f'Source does not exist: {left.name()}')
            # Files copied to an existing directory keep their basename. Directory
            # contents are always merged directly into the named destination.
            if a['']['kind'] == 'file' and b.get('', {}).get('kind') == 'dir':
                right.root = os.path.join(right.root, os.path.basename(left.root))
                b = right.scan()
        else:
            if any(tree.get('', {}).get('kind') == 'file' for tree in (a, b)):
                raise ValueError('sync operates on directories; use cp for individual files')
            if not a and (DIRECTION != '<>' or not b):
                raise ValueError(f'Source directory does not exist: {left.name()}')
        baseline = json.loads(baseline_path.read_text()) if baseline_path.exists() else {}
        operations = plan(a, b, baseline, DIRECTION == '<>', ACTION == 'cp')
        for direction, rel, source, expected in operations:
            src, dest = (left, right) if direction == '>' else (right, left)
            print(f'{"Would copy" if DRY == "1" else "Copy"} {src.name()}/{rel} -> {dest.name()}/{rel}', flush=True)
            if DRY == '1':
                continue
            if source['kind'] == 'dir':
                dest.mkdir(rel)
            else:
                with src.fetch(rel, source) as stream:
                    dest.put(rel, source, expected, stream)
        if DRY != '1' and ACTION == 'sync' and DIRECTION == '<>':
            # Never advance a baseline unless both trees actually converged.
            after_a, after_b = left.scan(), right.scan()
            if set(after_a) != set(after_b) or any(not same(after_a[k], after_b[k]) for k in after_a):
                raise RuntimeError('Concurrent edits detected; sync baseline was not advanced. Check files and retry.')
            with tempfile.NamedTemporaryFile(mode='w', dir=state_dir, delete=False) as out:
                json.dump(after_a, out, sort_keys=True)
                temporary = out.name
            os.replace(temporary, baseline_path)
        if DRY != '1' and ACTION == 'sync':
            # Pair metadata is separate from the content baseline so it can be
            # listed offline, including targets last used for one-way sync.
            record = {'session': SESSION, 'left': Endpoint(LEFT).name(),
                      'right': Endpoint(RIGHT).name(), 'direction': DIRECTION,
                      'last_success_utc': datetime.now(timezone.utc).isoformat()}
            with tempfile.NamedTemporaryFile(mode='w', dir=state_dir, delete=False) as out:
                json.dump(record, out, sort_keys=True)
                temporary = out.name
            os.replace(temporary, state_dir / (key + '.target.json'))
        print(f'{len(operations)} item(s) {"planned" if DRY == "1" else "copied"}; no deletions.', flush=True)


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print(f'Copy/sync failed: {exc}', file=sys.stderr)
        sys.exit(1)
