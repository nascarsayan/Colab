"""Reuse or relocate the native Drive mount without restarting its filesystem."""
import os
from pathlib import Path
import subprocess
import sys

def prepare(private=Path('/root/.Colab/drive'), legacy=Path('/content/drive')):
    private.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if private.is_symlink():
        raise RuntimeError('Internal Drive location is a symlink; no files were changed.')
    if os.path.ismount(private):
        if not (private/'MyDrive').is_dir():
            raise RuntimeError('Internal mount does not expose My Drive; no mounts were changed.')
        return 'mounted'
    if private.exists() and (not private.is_dir() or any(private.iterdir())):
        raise RuntimeError('Internal Drive location is occupied; no files were changed.')
    if os.path.ismount(legacy) and (legacy/'MyDrive').is_dir():
        private.mkdir(exist_ok=True)
        result = subprocess.run(['mount', '--move', str(legacy), str(private)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError('Could not relocate the existing Drive mount: ' + result.stderr.strip())
        if not os.path.ismount(private) or not (private/'MyDrive').is_dir():
            raise RuntimeError('Relocated Drive mount could not be verified.')
        try: legacy.rmdir()  # Remove only an empty old mount directory.
        except OSError: pass
        return 'mounted'
    return 'needs-auth'

if __name__ == '__main__':
    try:
        print(prepare())
    except Exception as exc:
        print(f'Drive setup failed: {exc}', file=sys.stderr)
        sys.exit(1)
