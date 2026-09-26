#!/usr/bin/env python3
"""Command-line client for a ChatContext messaging server. Python 3 standard library only.

Configuration comes from three environment variables:
  CHATCONTEXT_URL             server address, for example https://chat.example.com
  CHATCONTEXT_USER_EMAIL     email of an account in the `users` collection
  CHATCONTEXT_USER_PASSWORD  password of that account (optional with Google login)

Exit codes: 0 success; 1 HTTP or transport error; 2 usage or configuration error;
3 `check` found schema differences; 4 HTTP 409 (read the record again, then retry).
"""
import argparse
import base64
import hashlib
import http.client
import http.server
import json
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ENV = ['CHATCONTEXT_URL', 'CHATCONTEXT_USER_EMAIL', 'CHATCONTEXT_USER_PASSWORD']
SCHEMA_FILE = Path(__file__).resolve().parent.parent / 'references' / 'schema.json'
STAMPS = ('created_by', 'updated_by')
ID_ALPHABET = 'abcdefghijklmnopqrstuvwxyz0123456789'
TIMEOUT = 30
USER_AGENT = 'ChatContext/1.0'
hidden = []  # The password and tokens. say() masks them in everything it prints.


class Fail(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def hide(value):
    if value:
        hidden.append(value)
    return value


def say(text, stream=sys.stderr):
    for value in hidden:
        text = text.replace(value, '***')
    print(text, file=stream)


def dump(data, pretty=False):
    if pretty:
        return json.dumps(data, indent=2, ensure_ascii=False)
    return json.dumps(data, separators=(',', ':'), ensure_ascii=False)


def config(names=ENV[:2]):
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise Fail(2, 'missing environment variable: ' + ', '.join(missing) + '. Ask the user to set every missing variable; do not look for credentials elsewhere.')
    url = os.environ[ENV[0]].rstrip('/')
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise Fail(2, 'CHATCONTEXT_URL must be an HTTP(S) URL without credentials, query, or fragment')
    if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise Fail(2, 'Use HTTPS for a remote ChatContext server')
    return {'url': url, 'email': os.environ[ENV[1]], 'password': hide(os.environ.get(ENV[2]))}


# Token cache: one file per server URL and email, readable only by the current user.

def cache_file(cfg):
    base = os.environ.get('XDG_CACHE_HOME') or str(Path.home() / '.cache')
    key = hashlib.sha256((cfg['url'] + '\n' + cfg['email']).encode()).hexdigest()[:32]
    return Path(base) / 'chatcontext' / (key + '.json')


def load_session(cfg):
    try:
        session = json.loads(cache_file(cfg).read_text())
        if not isinstance(session, dict) or session.get('url') != cfg['url'] or session.get('email') != cfg['email']:
            return None
        return session if isinstance(session.get('token'), str) and hide(session['token']) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_session(cfg, session):
    path = cache_file(cfg)
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.session-', delete=False) as handle:
            temporary = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            json.dump(session, handle)
        os.replace(temporary, path)
    except OSError as error:
        say(f'note: token not cached ({error.strerror}); sign-in will be required again')


# HTTP

class NoRedirect(urllib.request.HTTPRedirectHandler):
    """A followed redirect would turn a POST into a GET and could send the token to another host."""
    def redirect_request(self, *args):
        return None


opener = urllib.request.build_opener(NoRedirect)


def send(cfg, method, path, body=None, token=None, timeout=TIMEOUT):
    """Send one request. Returns (status, parsed JSON body, or the text when it is not JSON)."""
    headers = {'Content-Type': 'application/json', 'User-Agent': USER_AGENT}
    if token:
        headers['Authorization'] = token
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(cfg['url'] + path, data=data, headers=headers, method=method)
    try:
        with opener.open(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
        if 300 <= status < 400:
            raise Fail(1, f'HTTP {status}: the server redirects to {error.headers.get("Location")}. Set CHATCONTEXT_URL to the final address.')
    except (OSError, ValueError, http.client.HTTPException) as error:
        reason = getattr(error, 'reason', error)
        raise Fail(1, f'cannot reach {cfg["url"]}: {reason}. A write may have committed; inspect its record before retrying.')
    text = raw.decode('utf-8', 'replace')
    try:
        return status, json.loads(text) if text else None
    except ValueError:
        return status, text[:2000]


def login(cfg):
    if not cfg.get('password'):
        raise Fail(2, 'Set CHATCONTEXT_USER_PASSWORD for password login, or run cc.py login --google (team) / login --email (visitor).')
    status, data = send(cfg, 'POST', '/api/collections/users/auth-with-password', {'identity': cfg['email'], 'password': cfg['password']})
    if status != 200 or not isinstance(data, dict) or 'token' not in data:
        raise Fail(1, f'login as {cfg["email"]} failed: HTTP {status}\n{dump(data)}\nCheck the three CHATCONTEXT_ variables with the user. User credentials only.')
    return auth_session(cfg, data, 'password')


def auth_session(cfg, data, method):
    """Accept only the expected users identity; never retain provider metadata."""
    token = data.get('token') if isinstance(data, dict) else None
    if isinstance(token, str):
        hide(token)
    record = data.get('record') if isinstance(data, dict) else None
    if (not isinstance(token, str) or not token or not isinstance(record, dict) or record.get('collectionName') != 'users'
            or not record.get('id') or not isinstance(record.get('email'), str)
            or record['email'].casefold() != cfg['email'].casefold()):
        raise Fail(1, 'Authentication returned an unexpected identity; no session saved. Check CHATCONTEXT_USER_EMAIL.')
    session = {'url': cfg['url'], 'email': cfg['email'], 'token': token, 'method': method, 'refreshed_at': time.time()}
    save_session(cfg, session)
    return session


def oauth_send(cfg, method, path, body=None, token=None):
    try:
        return send(cfg, method, path, body, token)
    except Fail:
        # Redirect locations and transport errors may contain authorization credentials.
        raise Fail(1, 'OAuth authentication request failed; check the server URL and connection, then retry.') from None


def oauth_refresh_needed(session):
    """Unverified JWT claims only schedule renewal; the server always authenticates the token."""
    try:
        payload = session['token'].split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        now = time.time()
        refreshed_at = session['refreshed_at']
        return (not 0 <= now - refreshed_at < 300 or claims['exp'] <= now + 60)
    except (ValueError, TypeError, KeyError, IndexError):
        return True


def google_login(cfg, port=8765, timeout=180):
    if not 1 <= port <= 65535 or not 1 <= timeout <= 600:
        raise Fail(2, 'OAuth port must be 1–65535 and timeout must be 1–600 seconds')
    status, data = oauth_send(cfg, 'GET', '/api/collections/users/auth-methods')
    oauth = data.get('oauth2', {}) if isinstance(data, dict) else {}
    providers = oauth.get('providers', [])
    provider = next((p for p in providers if isinstance(p, dict) and p.get('name') == 'google'), None)
    if status != 200 or not oauth.get('enabled') or not provider:
        raise Fail(1, 'Google OAuth is not enabled on this ChatContext server.')
    auth_url = urllib.parse.urlsplit(provider.get('authURL', ''))
    if auth_url.scheme != 'https' or auth_url.hostname != 'accounts.google.com' or auth_url.username or auth_url.password or auth_url.fragment:
        raise Fail(1, 'Server returned an unexpected Google authorization URL.')
    state = secrets.token_urlsafe(32)
    verifier = hide(secrets.token_urlsafe(48))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    redirect = f'http://127.0.0.1:{port}/callback'
    metadata = urllib.parse.parse_qs(auth_url.query)
    client_ids = metadata.get('client_id', [])
    if len(client_ids) != 1 or not client_ids[0]:
        raise Fail(1, 'Server returned an invalid Google client ID.')
    params = {'client_id': client_ids[0]}
    params.update(state=state, code_challenge=challenge, code_challenge_method='S256', redirect_uri=redirect,
                  login_hint=cfg['email'], response_type='code', scope='openid email profile', access_type='online')
    url = urllib.parse.urlunsplit(auth_url._replace(query=urllib.parse.urlencode(params)))
    outcome = {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Callback URLs contain credentials.

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            values = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            code = values.get('code', [])
            valid_state = values.get('state', [])
            valid = (self.headers.get('Host') == f'127.0.0.1:{port}' and parsed.path == '/callback' and len(valid_state) == 1
                     and secrets.compare_digest(valid_state[0], state))
            if not valid:
                status, message = 400, 'Invalid sign-in callback. Return to your terminal.'
            elif 'error' in values:
                outcome['error'] = 'Google sign-in was denied or cancelled; run cc.py login --google to retry.'
                status, message = 400, 'Sign-in was cancelled. Return to your terminal.'
            elif len(code) != 1 or not code[0]:
                outcome['error'] = 'Google returned an invalid sign-in callback.'
                status, message = 400, 'Invalid sign-in callback. Return to your terminal.'
            else:
                outcome['code'] = hide(code[0])
                status, message = 200, 'Authorization received. Return to your terminal to check sign-in.'
            self.send_response(status)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(message.encode())

    class Listener(http.server.HTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(1)
            return connection, address

        def handle_error(self, request, client_address):
            pass  # Never print request data or exception tracebacks.

    try:
        server = Listener(('127.0.0.1', port), Callback)
    except OSError:
        raise Fail(1, f'Cannot listen on 127.0.0.1:{port}; check for another login process or choose --port.')
    with server:
        server.timeout = 0.25
        say(f'For SSH, forward this port: ssh -L {port}:127.0.0.1:{port} user@ssh-host')
        say('Open this URL in your browser (keep it private):\n' + url)
        deadline = time.monotonic() + timeout
        while not outcome and time.monotonic() < deadline:
            server.handle_request()
    if not outcome:
        raise Fail(1, 'Google sign-in timed out; run cc.py login --google to retry.')
    if 'error' in outcome:
        raise Fail(1, outcome['error'])
    status, data = oauth_send(cfg, 'POST', '/api/collections/users/auth-with-oauth2', {
        'provider': 'google', 'code': outcome['code'], 'codeVerifier': verifier, 'redirectURL': redirect,
    })
    if status != 200:
        raise Fail(1, f'Google sign-in failed: HTTP {status}. Check Workspace eligibility, account access, and the redirect URI with your operator.')
    return auth_session(cfg, data, 'google')


def token_rejected(cfg, token):
    return send(cfg, 'POST', '/api/context/query', {'sql': 'SELECT 1'}, token)[0] == 401


def call(cfg, method, path, body=None):
    """Authenticated request. Returns (status, data).

    Only the SQL endpoints answer an expired or revoked token with 401. The records API treats it as no
    token and answers 400, 403, or 404. So after such an error with a cached token, check the token,
    and if the server rejects it, log in once and send the request once more. The first attempt wrote nothing.
    """
    session = load_session(cfg)
    cached = session is not None
    if not cached:
        session = login(cfg)
    if session.get('method') in ('google', 'email') and (oauth_refresh_needed(session) or path == '/api/collections/users/auth-refresh'):
        # Renew at most every five minutes, or near expiry, to respect auth rate limits.
        status, data = oauth_send(cfg, 'POST', '/api/collections/users/auth-refresh', token=session['token'])
        if status != 200:
            raise Fail(1, f'Browser/email session could not be refreshed (HTTP {status}); sign in again with cc.py login --google or --email.')
        session = auth_session(cfg, data, session['method'])
        if path == '/api/collections/users/auth-refresh':
            return status, data
    status, data = send(cfg, method, path, body, session['token'])
    if cached and 400 <= status < 500 and status != 409 and (status == 401 or token_rejected(cfg, session['token'])):
        if session.get('method') in ('google', 'email'):
            raise Fail(1, 'Browser/email session was rejected; sign in again with cc.py login --google or --email.')
        session = login(cfg)
        status, data = send(cfg, method, path, body, session['token'])
    return status, data


def batch_failures(data):
    """The failed requests of a rejected batch as (index, status, message). The server reports them under data.requests."""
    try:
        failures = []
        for index, entry in data['data']['requests'].items():
            response = entry['response']
            fields = [f'{name}: {detail.get("message")}' for name, detail in (response.get('data') or {}).items() if isinstance(detail, dict)]
            failures.append((index, response.get('status'), ' '.join([response.get('message') or ''] + fields)))
        return failures
    except (AttributeError, KeyError, TypeError):
        return []


def must(cfg, method, path, body=None):
    """Like call(), but an HTTP error ends the command with the server's status and body on stderr."""
    status, data = call(cfg, method, path, body)
    if status < 400:
        return data
    lines = [f'HTTP {status} from {method} {path}', dump(data, pretty=True)]
    conflict = status == 409
    if path == '/api/batch':
        lines.append('Nothing in this batch was saved.')
        for index, inner_status, message in batch_failures(data):
            lines.append(f'Failed request index {index}: HTTP {inner_status}: {message}')
            conflict = conflict or inner_status == 409
    if conflict:
        lines.append('HTTP 409: another request changed the record first. Read it again, confirm the change still applies, then retry.')
    raise Fail(4 if conflict else 1, '\n'.join(lines))


# Messaging reads deliberately have no acknowledgement side effects.
BUSINESS = ('conversations', 'memberships', 'messages', 'reactions', 'read_receipts')
MAX_FILE = 25 * 1024 * 1024


def email_login(cfg, otp_id=None):
    if not otp_id:
        status, data = oauth_send(cfg, 'POST', '/api/collections/users/request-otp', {'email': cfg['email']})
        if status != 200 or not isinstance(data, dict) or not data.get('otpId'):
            raise Fail(1, 'Email code request failed; check the address and retry later.')
        say(dump({'otpId': data['otpId'], 'expires_in_seconds': 600}), sys.stdout)
        say('Run login --email --otp-id ID and enter the emailed code. A replacement invalidates the previous code.')
        return None
    import getpass
    code = hide(getpass.getpass('Email code: '))
    status, data = oauth_send(cfg, 'POST', '/api/collections/users/auth-with-otp', {'otpId': otp_id, 'password': code})
    if status != 200:
        raise Fail(1, 'Email sign-in failed; the code may be invalid, expired or replaced.')
    return auth_session(cfg, data, 'email')


def valid_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9]{15}', value):
        raise Fail(2, 'record id must be 15 lowercase letters or digits')
    return value


def sql_rows(cfg, sql):
    result = must(cfg, 'POST', '/api/context/query', {'sql': sql})
    if result.get('truncated'):
        raise Fail(1, 'Incomplete SQL result; narrow the query or reduce the page size.')
    return [dict(zip(result['columns'], row)) for row in result['rows']]


def self_id(cfg):
    result = must(cfg, 'POST', '/api/collections/users/auth-refresh')
    return valid_id(result['record']['id'])


def sync(cfg, after, limit):
    if after < 0 or not 1 <= limit <= 100:
        raise Fail(2, 'sync requires a nonnegative cursor and limit 1–100')
    rows = sql_rows(cfg, f'SELECT * FROM changes WHERE seq > {after} ORDER BY seq LIMIT {limit}')
    cursor = after
    for row in rows:
        if type(row.get('seq')) not in (int, float) or row['seq'] <= cursor or int(row['seq']) != row['seq']:
            raise Fail(1, 'Invalid change sequence; do not advance your cursor')
        cursor = int(row['seq'])
    return {'changes': rows, 'next_cursor': cursor, 'page_full': len(rows) == limit,
            'cache_policy': 'Revalidate cached records against current SQL visibility; absence of events does not preserve access.'}


def acknowledge(cfg, identifiers):
    account = self_id(cfg)
    identifiers = list(dict.fromkeys(valid_id(value) for value in identifiers))
    if not 1 <= len(identifiers) <= 20:
        raise Fail(2, 'ack accepts 1–20 message ids')
    existing = sql_rows(cfg, "SELECT message FROM read_receipts WHERE account = '" + account + "' AND message IN (" + ','.join("'"+value+"'" for value in identifiers) + ')')
    seen = {row['message'] for row in existing}
    requests = [{'method': 'POST', 'url': records('read_receipts'), 'body': {'message': value}} for value in identifiers if value not in seen]
    if requests:
        must(cfg, 'POST', '/api/batch', {'requests': requests})
    return {'acknowledged': identifiers}


def binary_request(cfg, method, path, data=None, content_type=None):
    must(cfg, 'POST', '/api/collections/users/auth-refresh')
    session = load_session(cfg)
    headers = {'User-Agent': USER_AGENT}
    # Protected downloads authenticate with their short-lived query token, matching browser clients.
    if method != 'GET':
        headers['Authorization'] = session['token']
    if content_type:
        headers['Content-Type'] = content_type
    request = urllib.request.Request(cfg['url'] + path, data=data, headers=headers, method=method)
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            raw = response.read(MAX_FILE + 1)
            if len(raw) > MAX_FILE:
                raise Fail(1, 'File exceeds the client size limit')
            return raw
    except urllib.error.HTTPError as error:
        raise Fail(4 if error.code == 409 else 1, f'File request failed: HTTP {error.code}') from None
    except (OSError, http.client.HTTPException):
        raise Fail(1, 'File transport failed; inspect the message attachments and checksum before retrying an upload') from None


def upload(cfg, filename, message):
    message = valid_id(message)
    source = Path(filename)
    with source.open('rb') as stream:
        raw = stream.read(MAX_FILE + 1)
    if not raw or len(raw) > MAX_FILE:
        raise Fail(2, 'Attachments must contain 1 byte to 25 MiB')
    boundary = secrets.token_hex(32)
    safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', source.name) or 'original.bin'
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="message"\r\n\r\n{message}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="original"; filename="{safe_name}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode() + raw + f'\r\n--{boundary}--\r\n'.encode()
    result = json.loads(binary_request(cfg, 'POST', records('attachments'), body, 'multipart/form-data; boundary=' + boundary))
    rows = sql_rows(cfg, f"SELECT * FROM attachments WHERE id = '{valid_id(result.get('id'))}'")
    if len(rows) != 1:
        raise Fail(1, 'Uploaded attachment is not yet visible; inspect the message before retrying')
    result = rows[0]
    if result.get('sha256') != hashlib.sha256(raw).hexdigest():
        raise Fail(1, 'Uploaded checksum differs; inspect the saved attachment before retrying')
    return result


def download(cfg, record, target):
    rows = sql_rows(cfg, f"SELECT * FROM attachments WHERE id = '{valid_id(record)}'")
    if len(rows) != 1:
        raise Fail(1, 'Attachment not visible')
    row = rows[0]
    filename = row.get('original')
    if not isinstance(filename, str) or not filename or '/' in filename or '\\' in filename:
        raise Fail(1, 'Invalid attachment filename')
    token = hide(must(cfg, 'POST', '/api/files/token')['token'])
    path = '/api/files/attachments/' + record + '/' + urllib.parse.quote(filename, safe='') + '?token=' + urllib.parse.quote(token, safe='')
    raw = binary_request(cfg, 'GET', path)
    if hashlib.sha256(raw).hexdigest() != row.get('sha256'):
        raise Fail(1, 'Attachment checksum mismatch; no file saved')
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
    return {'saved': str(target), 'sha256': row['sha256']}


def messaging(cfg, args):
    cmd = args.command
    if cmd == 'sync':
        return sync(cfg, args.after, args.limit)
    if cmd == 'ack':
        return acknowledge(cfg, args.ids)
    if cmd == 'upload':
        return upload(cfg, args.file, args.message)
    if cmd == 'download':
        return download(cfg, args.id, args.target)
    if cmd == 'display-name':
        # Team members publish only their own alias; an empty value restores the neutral "User".
        record = must(cfg, 'PATCH', records('users', self_id(cfg)), {'public_display_name': args.name})
        return {'id': record['id'], 'public_display_name': record.get('public_display_name', '')}
    if cmd in ('inbox', 'unread'):
        account = self_id(cfg)
        if cmd == 'inbox':
            return sql_rows(cfg, f"SELECT * FROM inbox WHERE account = '{account}' ORDER BY created DESC, id DESC LIMIT 100")
        return sql_rows(cfg, f"SELECT m.conversation, COUNT(*) AS unread FROM messages m JOIN conversations c ON c.id = m.conversation WHERE m.deleted = false AND m.author != '{account}' AND (c.kind IN ('dm','support') OR EXISTS (SELECT 1 FROM memberships s WHERE s.conversation = c.id AND s.account = '{account}' AND s.active = true)) AND NOT EXISTS (SELECT 1 FROM read_receipts r WHERE r.message = m.id AND r.account = '{account}') GROUP BY m.conversation")
    if cmd in ('channel', 'dm', 'support'):
        body = {'title': args.title}
        if cmd == 'channel':
            body['kind'] = 'private_channel' if args.private else 'public_channel'
        else:
            body['kind'] = cmd
        if cmd in ('channel', 'dm'):
            body['participants'] = [valid_id(value) for value in args.participants]
        if cmd == 'support' and args.visitor:
            body['visitor'] = valid_id(args.visitor)
        return must(cfg, 'POST', records('conversations'), body)
    if cmd in ('send', 'reply', 'note'):
        body = {'conversation': valid_id(args.conversation), 'body': sys.stdin.read() if args.body == '-' else args.body,
                'mentions': [valid_id(value) for value in args.mention]}
        if cmd == 'reply':
            body['parent'] = valid_id(args.parent)
            roots = sql_rows(cfg, f"SELECT internal FROM messages WHERE id = '{body['parent']}' AND conversation = '{body['conversation']}'")
            if len(roots) != 1:
                raise Fail(1, 'Thread root is not accessible in this conversation')
            body['internal'] = bool(roots[0]['internal'])
        if cmd == 'note':
            body['internal'] = True
        return must(cfg, 'POST', records('messages'), body)
    if cmd in ('edit', 'delete'):
        body = {'expected_revision': args.revision}
        require_revision(body)
        if cmd == 'delete':
            body['deleted'] = True
        else:
            body['body'] = sys.stdin.read() if args.body == '-' else args.body
        return must(cfg, 'PATCH', records('messages', valid_id(args.id)), body)
    raise Fail(2, 'Unknown messaging operation')


def add_messaging(commands, pretty):
    def command(name, description):
        return commands.add_parser(name, parents=[pretty], help=description)
    for name in ('channel', 'dm', 'support'):
        p = command(name, 'create a ' + name)
        p.add_argument('title')
        if name in ('channel', 'dm'):
            p.add_argument('--participants', nargs='*', default=[])
        if name == 'channel':
            p.add_argument('--private', action='store_true')
        if name == 'support':
            p.add_argument('--visitor', help='visitor account; omitted for own visitor conversation')
    for name in ('send', 'reply', 'note'):
        p = command(name, 'post a message; note is team-only')
        p.add_argument('conversation')
        if name == 'reply':
            p.add_argument('parent')
        p.add_argument('body', help='Markdown or - for stdin')
        p.add_argument('--mention', action='append', default=[])
    for name in ('edit', 'delete'):
        p = command(name, 'revision-checked message ' + name)
        p.add_argument('id')
        p.add_argument('--revision', type=int, required=True)
        if name == 'edit':
            p.add_argument('body')
    p = command('sync', 'fetch filtered change events without marking read; persist cursor after applying page')
    p.add_argument('--after', type=int, default=0)
    p.add_argument('--limit', type=int, default=100)
    p = command('ack', 'explicitly mark 1–20 messages read as this account')
    p.add_argument('ids', nargs='+')
    command('inbox', 'latest 100 visible mentions and thread replies')
    command('unread', 'private unread counts by subscribed conversation')
    p = command('upload', 'upload an immutable attachment to your own message')
    p.add_argument('message')
    p.add_argument('file')
    p = command('download', 'download a protected original and verify checksum; never overwrite')
    p.add_argument('id')
    p.add_argument('target')
    p = command('display-name', 'set your public directory alias (team members only); empty resets to User')
    p.add_argument('name')


# Commands

def read_json(text, kind, what):
    if text == '-':
        text = sys.stdin.read()
    try:
        value = json.loads(text)
    except ValueError as error:
        raise Fail(2, f'{what} is not valid JSON: {error}')
    if not isinstance(value, kind):
        raise Fail(2, f'{what} must be a JSON {"array" if kind is list else "object"}')
    return value


def require_revision(body):
    if type(body.get('expected_revision')) is not int or body['expected_revision'] < 1:
        raise Fail(2, 'updates require expected_revision from your last read; read the record before changing it')


def record_body(text):
    body = read_json(text, dict, 'the record body')
    for field in STAMPS:
        if field in body:
            del body[field]
            say(f'note: removed {field} from the body; the server sets it from your login')
    if not body:
        raise Fail(2, 'the record body has no fields to send')
    return body


def records(collection, record=None):
    path = f'/api/collections/{urllib.parse.quote(collection, safe="")}/records'
    return path if record is None else f'{path}/{urllib.parse.quote(record, safe="")}'


def columns(tables):
    return {table['name']: {column['name']: column.get('type') for column in table['columns']} for table in tables}


def check(cfg):
    """Compare the live SQL schema with references/schema.json. Returns the exit code."""
    try:
        reference = columns(json.loads(SCHEMA_FILE.read_text())['tables'])
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise Fail(2, f'cannot read {SCHEMA_FILE}: {error}')
    live = columns(must(cfg, 'GET', '/api/context/schema')['tables'])
    differences = []
    for table in sorted(set(live) | set(reference)):
        if table not in reference:
            differences.append(f'table {table}: on the server, not in the reference files')
        elif table not in live:
            differences.append(f'table {table}: in the reference files, not on the server')
        else:
            for column in sorted(set(live[table]) | set(reference[table])):
                if column not in reference[table]:
                    differences.append(f'column {table}.{column}: on the server, not in the reference files')
                elif column not in live[table]:
                    differences.append(f'column {table}.{column}: in the reference files, not on the server')
                elif live[table][column] != reference[table][column]:
                    differences.append(f'column {table}.{column}: type {live[table][column]} on the server, {reference[table][column]} in the reference files')
    if not differences:
        say(f'OK: the live schema matches references/schema.json ({len(live)} tables)', sys.stdout)
        return 0
    for line in differences:
        say(line, sys.stdout)
    say('The server is authoritative: run `cc.py schema` and follow the server\'s error messages where the reference files disagree. '
        'Ask the user to update this skill.', sys.stdout)
    return 3


def run(args):
    if args.command == 'newid':
        print(''.join(secrets.choice(ID_ALPHABET) for _ in range(15)))
        return 0
    if args.command == 'logout':
        cfg = config(ENV[:2])
        path = cache_file(cfg)
        path.unlink(missing_ok=True)
        say(f'removed {path}', sys.stdout)
        return 0
    cfg = config()
    if args.command == 'login':
        result = google_login(cfg, args.port, args.timeout) if args.google else email_login(cfg, args.otp_id) if args.email else login(cfg)
        if result is None:
            return 0
        say(f'Signed in as {cfg["email"]} at {cfg["url"]}', sys.stdout)
        return 0
    # Reject malformed writes before authentication or any network request.
    body = None
    if args.command in ('create', 'update'):
        if args.collection not in BUSINESS:
            raise Fail(2, 'Use messaging business collections only; provision accounts separately')
        body = record_body(args.json)
        if args.command == 'update':
            require_revision(body)
    elif args.command == 'batch':
        requests = read_json(args.json, list, 'the batch')
        if not all(isinstance(entry, dict) for entry in requests):
            raise Fail(2, 'each batch entry must be an object with method, url, and body')
        for entry in requests:
            method, url = entry.get('method'), entry.get('url', '')
            if method not in ('POST', 'PATCH') or not isinstance(url, str) or not re.fullmatch(r'/api/collections/(conversations|memberships|messages|reactions|read_receipts)/records(?:/[a-z0-9]{15})?', url):
                raise Fail(2, 'batch accepts only POST/PATCH business record URLs')
            if not isinstance(entry.get('body'), dict):
                raise Fail(2, 'each batch body must be an object')
            if method == 'PATCH':
                require_revision(entry['body'])
        body = {'requests': requests}
    if args.command in ('channel', 'dm', 'support', 'send', 'reply', 'note', 'edit', 'delete', 'sync', 'ack', 'inbox', 'unread', 'upload', 'download', 'display-name'):
        say(dump(messaging(cfg, args), args.pretty), sys.stdout)
        return 0
    if args.command == 'check':
        return check(cfg)
    if args.command == 'whoami':
        # OAuth calls persist refreshed tokens; password sessions keep their existing recovery behavior.
        refreshed = must(cfg, 'POST', '/api/collections/users/auth-refresh')
        hide(refreshed.get('token'))
        record = refreshed['record']
        data = {'id': record['id'], 'name': record.get('name', ''), 'public_display_name': record.get('public_display_name', ''), 'email': cfg['email'], 'url': cfg['url']}
    elif args.command == 'schema':
        data = must(cfg, 'GET', '/api/context/schema')
    elif args.command in ('sql', 'query'):
        query = sys.stdin.read() if args.query == '-' else args.query
        data = must(cfg, 'POST', '/api/context/query', {'sql': query})
        if isinstance(data, dict) and data.get('truncated'):
            say(f'WARNING: result truncated to {len(data.get("rows", []))} rows by the server\'s row or byte limit. Select fewer columns, narrow the query, or page with ORDER BY and LIMIT/OFFSET.')
    elif args.command == 'get':
        if not re.fullmatch(r'[a-z0-9]{15}', args.id):
            raise Fail(2, 'record id must be 15 lowercase letters or digits')
        schema = must(cfg, 'GET', '/api/context/schema')
        table = next((table for table in schema['tables'] if table['name'] == args.collection), None)
        if table is None or not any(column['name'] == 'id' for column in table['columns']):
            raise Fail(2, 'collection is not an SQL-readable table with an id column')
        identifier = '"' + table['name'].replace('"', '""') + '"'
        result = must(cfg, 'POST', '/api/context/query', {
            'sql': f"SELECT * FROM {identifier} WHERE id = '{args.id}' LIMIT 1"
        })
        if result.get('truncated'):
            raise Fail(1, 'record exceeds the SQL response limit; query only the needed fields')
        if not result['rows']:
            raise Fail(1, f'HTTP 404: record not found in {args.collection}')
        data = dict(zip(result['columns'], result['rows'][0]))
    elif args.command == 'create':
        data = must(cfg, 'POST', records(args.collection), body)
    elif args.command == 'update':
        data = must(cfg, 'PATCH', records(args.collection, args.id), body)
    elif args.command == 'batch':
        data = must(cfg, 'POST', '/api/batch', body)
    say(dump(data, args.pretty), sys.stdout)
    return 0


def parse(argv):
    pretty = argparse.ArgumentParser(add_help=False)
    pretty.add_argument('--pretty', action='store_true', default=argparse.SUPPRESS, help='indent the JSON output')
    parser = argparse.ArgumentParser(prog='cc.py', parents=[pretty], description='ChatContext messaging client. Reads with SQL, writes through the records API. Deletion is soft and revision checked.',
                                     epilog='Environment: ' + ', '.join(ENV) + '. JSON arguments may be "-" to read standard input. Exit codes: 0 ok, 1 HTTP or transport error, 2 usage or configuration, 3 check found differences, 4 HTTP 409.')
    commands = parser.add_subparsers(dest='command', required=True, metavar='command')
    def add(name, text, *arguments):
        command = commands.add_parser(name, parents=[pretty], help=text, description=text)
        for argument, argument_help in arguments:
            command.add_argument(argument, help=argument_help)
    oauth_login = commands.add_parser('login', help='sign in using Google, emailed code, or a provisioned password')
    modes = oauth_login.add_mutually_exclusive_group(required=True)
    modes.add_argument('--google', action='store_true')
    modes.add_argument('--email', action='store_true', help='request an email code; with --otp-id prompt for the code')
    modes.add_argument('--password', action='store_true', help='use provisioned password from environment')
    oauth_login.add_argument('--otp-id', help='challenge id returned by email code request')
    oauth_login.add_argument('--port', type=int, default=8765, help='loopback callback port; register the matching redirect URI')
    oauth_login.add_argument('--timeout', type=int, default=180, help='seconds to wait for the browser (1–600)')
    add('whoami', 'print the authenticated account id, name and server URL')
    add('check', 'compare the live schema with references/schema.json; exit 3 when they differ')
    add('schema', 'print the live SQL tables and columns')
    add('query', 'run one read-only SELECT', ('query', 'SQL text, or - for standard input'))
    add('sql', 'run one read-only SELECT', ('query', 'SQL text, or - for standard input'))
    add('get', 'read one record as an SQL row object', ('collection', 'collection name'), ('id', 'record id'))
    add('create', 'create one record', ('collection', 'collection name'), ('json', 'JSON object, or -'))
    add('update', 'change fields of one record', ('collection', 'collection name'), ('id', 'record id'), ('json', 'JSON object with the fields to change, or -'))
    add('batch', 'send up to 20 writes as one transaction', ('json', 'JSON array of {"method","url","body"}, or -'))
    add('newid', 'print a new 15-character record id for use inside a batch')
    add('logout', 'remove the cached token')
    add_messaging(commands, pretty)
    args = parser.parse_args(argv)
    args.pretty = getattr(args, 'pretty', False)
    return args


def main():
    try:
        return run(parse(sys.argv[1:]))
    except Fail as error:
        say(f'cc.py: {error}')
        return error.code
    except KeyboardInterrupt:
        return 130
    except Exception as error:  # No traceback: keep the output short and free of request data.
        say(f'cc.py: unexpected {type(error).__name__}: {error}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
