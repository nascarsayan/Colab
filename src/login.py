"""Use the official OAuth flow, opening its authorization URL automatically."""
import sys
import webbrowser
from colab_cli import auth
from colab_cli.common import state
import keyring

no_browser = '--no-browser' in sys.argv
original_echo = auth.typer.echo

def guided_echo(message='', *args, **kwargs):
    text = str(message).strip()
    if not no_browser and text.startswith('https://accounts.google.com/'):
        try:
            if not webbrowser.open(text):
                original_echo('Could not open a browser automatically; open the URL below.', err=True)
        except Exception:
            original_echo('Could not open a browser automatically; open the URL below.', err=True)
    return original_echo(message, *args, **kwargs)

try:
    auth.typer.echo = guided_echo
    # Authenticates/refreshes credentials and verifies access without allocating a VM.
    assignments = state.client.list_assignments()
    try:
        saved = keyring.get_password(auth.KEYRING_SERVICE_NAME, auth.KEYRING_USERNAME)
    except Exception as exc:
        raise RuntimeError('Google sign-in worked, but OS credential storage is unavailable. Unlock/configure your Keychain or Secret Service and retry login.') from exc
    if not saved:
        raise RuntimeError('Google sign-in worked, but credentials were not saved. Configure your OS keyring and retry login.')
    print(f'Google login verified; credentials saved in OS keyring. Active runtimes: {len(assignments)}')
except EOFError:
    print('Login needs an interactive terminal. Run Colab auth login, approve Google consent, then paste the displayed authorization code.', file=sys.stderr)
    sys.exit(1)
except Exception as exc:
    print(f'Google login failed: {exc}', file=sys.stderr)
    sys.exit(1)
finally:
    auth.typer.echo = original_echo
