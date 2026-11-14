"""Boundary for every Google backend call: initialize state and render safe errors."""
import os
from pathlib import Path
import re
import sys


def friendly(exc):
    chain, seen = [], set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc)); chain.append(exc)
        exc = exc.__cause__ or exc.__context__
    names = ' '.join(type(e).__name__ for e in chain)
    text = ' '.join(str(e) for e in chain).lower()
    if 'TooManyAssignments' in names or 'precondition failed' in text or '412' in text:
        return 'Google declined the runtime request: session limit, GPU quota, or capacity limit. Stop an unused session with Colab session delete -s NAME, try CPU, or retry later.'
    if any(s in names for s in ('ConnectionError', 'ConnectTimeout', 'ReadTimeout', 'gaierror', 'TimeoutError')):
        return 'Cannot reach Google Colab. Check your Internet connection, proxy/VPN, and Google service availability, then retry.'
    if any(s in names for s in ('RefreshError', 'DefaultCredentialsError')) or 'invalid_grant' in text:
        return 'Your Google login has expired or is unavailable. Run Colab auth login and retry.'
    if 'PermissionError' in names:
        return 'Permission denied while accessing local state or credentials. Check ownership of ~/.config/Colab and ~/.config/colab-cli, and unlock your OS keyring.'
    if 'ModuleNotFoundError' in names or 'ImportError' in names:
        return 'The Google backend installation is incomplete. Run Colab setup to repair it.'
    if '401' in text or 'unauthorized' in text:
        return 'Google rejected your login. Run Colab auth login and retry.'
    if '403' in text or 'forbidden' in text:
        return 'Google denied access. Check the selected account, granted permissions, and runtime entitlement.'
    if '429' in text:
        return 'Google is limiting requests or connections. Close unused connections, wait briefly, and retry.'
    if 'FileNotFoundError' in names:
        return 'A required file or state directory is missing. Run Colab setup --check; check any supplied paths.'
    if 'Exit' in names:
        return None
    message = str(chain[0]).strip().splitlines()[0] if str(chain[0]).strip() else type(chain[0]).__name__
    # Backend exception URLs can contain credentials or authorization parameters.
    message = re.sub(r'https?://\S+', '[Google endpoint]', message)
    return message


def run():
    home = Path.home()
    for path in (home / '.config/colab-cli', home / '.config/Colab',
                 Path(os.environ.get('XDG_CONFIG_HOME', str(home / '.config'))) / 'colab-cli'):
        path.mkdir(parents=True, exist_ok=True)
    source = sys.argv[1]
    sys.argv = ['Colab', *sys.argv[2:]]
    if os.environ.get('COLAB_ALLOW_LOGIN') != '1':
        from colab_cli import auth
        def login_required(*args, **kwargs):
            raise RuntimeError('You are not logged in. Run Colab auth login first.')
        auth._run_remote_flow = login_required
    # Some SDK automation commands print remote notebook tracebacks instead of
    # raising them. Convert error outputs before those commands render them.
    try:
        from colab_cli.runtime import ColabRuntime
    except ImportError:
        pass
    else:
        execute = ColabRuntime.execute_code
        def checked_execute(*args, **kwargs):
            outputs = execute(*args, **kwargs)
            for output in outputs:
                if output.get('output_type') == 'error':
                    name = output.get('ename', 'Error')
                    value = (str(output.get('evalue', '')).splitlines() or [''])[0]
                    raise RuntimeError(f'Runtime setup failed ({name}): {value}. Check Google Drive consent with Colab drive mount.')
            return outputs
        ColabRuntime.execute_code = checked_execute
    exec(compile(source, '<Colab>', 'exec'), {'__name__': '__main__'})


if __name__ == '__main__':
    try:
        run()
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print('Error: ' + exc.code, file=sys.stderr)
            sys.exit(1)
        raise
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            print('Cancelled.', file=sys.stderr)
            sys.exit(130)
        message = friendly(exc)
        if message:
            print('Error: ' + message, file=sys.stderr)
        sys.exit(getattr(exc, 'exit_code', 1))
