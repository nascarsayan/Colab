"""Update account defaults or remove local credentials under the account lock."""
import json
import os
from pathlib import Path
import sys
import uuid
import keyring
from filelock import FileLock
from colab_cli import auth

root = Path.home() / '.config/Colab'
root.mkdir(parents=True, exist_ok=True)
path = root / 'accounts.json'
action, email = sys.argv[1:3]
label = email.removesuffix('@gmail.com')
clear_legacy = 'clear-legacy' in sys.argv[3:]

def forget(username):
    try:
        auth._run_with_timeout(keyring.delete_password, auth.KEYRING_SERVICE_NAME, username,
                               timeout=auth.KEYRING_TIMEOUT_SECONDS)
    except keyring.errors.PasswordDeleteError:
        pass

with FileLock(str(root / 'accounts.lock')):
    data = json.loads(path.read_text()) if path.exists() else {'accounts': {}}
    accounts = data['accounts']
    if email not in accounts:
        raise RuntimeError(f'Account {label} is not saved. Run Colab auth list.')
    if action == 'default':
        data['default'] = email
    elif action == 'logout':
        item = accounts[email]
        uuid.UUID(item['id'])
        profile = root / 'accounts' / item['id']
        forget('Colab:' + email)
        if (profile / 'legacy-mux').exists() or clear_legacy:
            forget('oauth_token')
            for name in ('token.json', 'sessions.json'):
                (Path.home() / '.config/colab-cli' / name).unlink(missing_ok=True)
        # Prevent rediscovery of an intentionally signed-out legacy account.
        data['legacy_signed_out'] = True
        (profile / 'sessions.json').unlink(missing_ok=True)
        data.setdefault('signed_out', {})[email] = accounts.pop(email)
        if data.get('default') not in accounts:
            data['default'] = next(iter(accounts), None)
    else:
        raise RuntimeError('Unknown account action')
    temp = path.with_suffix('.tmp')
    with open(temp, 'w', opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        json.dump(data, stream)
    temp.replace(path)
print(f'Default account: {label}' if action == 'default' else f'Logged out: {label}')
