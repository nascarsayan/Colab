"""Use Google's OAuth flow; verify the email before saving an account profile."""
import json
import os
from pathlib import Path
import shutil
import sys
import uuid
import webbrowser
from filelock import FileLock
from colab_cli import auth
import keyring
from google.auth.transport.requests import AuthorizedSession

root = Path.home() / '.config/Colab'
root.mkdir(parents=True, exist_ok=True)
requested = os.environ.get('COLAB_LOGIN_EMAIL', '').strip().lower()
no_browser = '--no-browser' in sys.argv
cached_only = '--cached' in sys.argv
original_echo = auth.typer.echo
# New logins get a temporary credential entry. They never overwrite another account.
original_username = auth.KEYRING_USERNAME
registry_path = root / 'accounts.json'
existing = json.loads(registry_path.read_text()) if registry_path.exists() else {'accounts': {}}
if cached_only:
    def cached_required(*args, **kwargs):
        raise SystemExit(3)  # No reusable credentials; never open consent.
    auth._run_remote_flow = cached_required
    if not requested and existing.get('legacy_signed_out'):
        raise SystemExit(3)
if requested:
    auth.KEYRING_USERNAME = 'Colab:' + requested
    auth.LEGACY_TOKEN_PATH = str(root / 'unused-legacy-token')
elif existing['accounts']:
    # No email means add/select an account through Google, rather than silently reuse the default.
    auth.KEYRING_USERNAME = 'Colab:pending:' + str(uuid.uuid4())
    auth.LEGACY_TOKEN_PATH = str(root / 'unused-legacy-token')
if cached_only and requested and not keyring.get_password(auth.KEYRING_SERVICE_NAME, auth.KEYRING_USERNAME):
    if existing.get('legacy_signed_out'):
        raise SystemExit(3)
    auth.KEYRING_USERNAME = original_username
    auth.LEGACY_TOKEN_PATH = str(Path.home() / '.config/colab-cli/token.json')
pending_username = auth.KEYRING_USERNAME
# The SDK saves before returning. Defer writes until Google confirms the email,
# so an incorrect browser account cannot replace the requested account's token.
original_save = auth._save_token_to_keyring
original_remove = auth._remove_legacy_token
auth._save_token_to_keyring = lambda token: None
auth._remove_legacy_token = lambda: None

def guided_echo(message='', *args, **kwargs):
    text = str(message).strip()
    if text.startswith('https://accounts.google.com/'):
        from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
        parts = urlsplit(text)
        params = dict(parse_qsl(parts.query))
        if requested:
            params['login_hint'] = requested
        else:
            params['prompt'] = 'consent select_account'
        text = urlunsplit(parts._replace(query=urlencode(params)))
        message = text
        if not no_browser:
            try:
                webbrowser.open(text)
            except Exception:
                original_echo('Open the authorization URL below in your browser.', err=True)
    return original_echo(message, *args, **kwargs)

try:
    auth.typer.echo = guided_echo
    if not cached_only:
        print('Google may request separate Drive mount consent when a runtime first mounts Drive; that permission is runtime-specific.', file=sys.stderr)
    creds = auth._get_google_auth_credentials(str(Path.home() / '.colab-cli-oauth-config.json'))
    response = AuthorizedSession(creds).get('https://www.googleapis.com/oauth2/v2/userinfo', timeout=30)
    response.raise_for_status()
    info = response.json()
    email = str(info.get('email', '')).strip().lower()
    if not info.get('verified_email') or '@' not in email or any(c.isspace() for c in email):
        raise RuntimeError('Google did not return a verified email address.')
    if cached_only and requested and email != requested:
        raise SystemExit(3)
    if requested and email != requested:
        raise RuntimeError(f'Google signed in as {email.removesuffix("@gmail.com")}, but {requested.removesuffix("@gmail.com")} was requested. Retry login with the intended account.')
    keyring.set_password(auth.KEYRING_SERVICE_NAME, 'Colab:' + email, creds.to_json())
    if not keyring.get_password(auth.KEYRING_SERVICE_NAME, 'Colab:' + email):
        raise RuntimeError('Credentials could not be saved. Unlock/configure the OS keyring and retry.')
    with FileLock(str(root / 'accounts.lock')):
        data = json.loads(registry_path.read_text()) if registry_path.exists() else {'accounts': {}}
        if email not in data['accounts']:
            previous = data.setdefault('signed_out', {}).pop(email, None)
            ident = previous['id'] if previous else str(uuid.uuid4())
            uuid.UUID(ident)
            profile = root / 'accounts' / ident
            profile.mkdir(parents=True, mode=0o700, exist_ok=True)
            # Only the first verified legacy login owns the old single-account state.
            if not data['accounts'] and pending_username == original_username and not data.get('legacy_signed_out') and not previous:
                legacy = Path.home() / '.config/colab-cli/sessions.json'
                if legacy.exists():
                    shutil.copy2(legacy, profile / 'sessions.json')
                for name in ('runtimes.json', 'workspaces', 'drive', 'sync', 'id_ed25519', 'id_ed25519.pub'):
                    source = root / name
                    if source.is_dir(): shutil.copytree(source, profile / name)
                    elif source.exists(): shutil.copy2(source, profile / name)
                # Existing masters already belong to this verified legacy account.
                (profile / 'legacy-mux').touch(mode=0o600)
            data['accounts'][email] = {'id': ident}
        if data.get('default') not in data['accounts']:
            data['default'] = next(iter(data['accounts']), None)
        temp = registry_path.with_suffix('.tmp')
        with open(temp, 'w', opener=lambda p, flags: os.open(p, flags, 0o600)) as f:
            json.dump(data, f)
        temp.replace(registry_path)
    if not cached_only:
        print(f'Google account ready: {email.removesuffix("@gmail.com")}. Credentials saved in OS keyring.')
except EOFError as exc:
    raise RuntimeError('Login needs an interactive terminal. Run Colab auth login and paste the authorization code shown by Google.') from exc
finally:
    auth._save_token_to_keyring = original_save
    auth._remove_legacy_token = original_remove
    auth.typer.echo = original_echo
