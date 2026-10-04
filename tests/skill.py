#!/usr/bin/env python3
"""Copied portable skill with synthetic team and visitor accounts on isolated server."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from integration import ROOT, server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', required=True)
    parser.add_argument('--write-schema', action='store_true')
    args = parser.parse_args()
    with server(args.binary) as request, tempfile.TemporaryDirectory(prefix='chatcontext-skill-') as tmp:
        admin = request('POST', '/api/collections/_superusers/auth-with-password', {'identity': 'admin@example.com', 'password': 'SyntheticAdminPassword123!'})['token']
        password = 'SyntheticUserPassword123!'
        def user(email, team=False):
            row = request('POST', '/api/collections/users/records', {'email': email, 'name': email.split('@')[0], 'verified': True, 'password': password, 'passwordConfirm': password}, admin)
            if team:
                request('POST', '/api/collections/team_members/records', {'account': row['id']}, admin)
            return row
        team = user('skill-team@example.com', True)
        peer = user('skill-peer@example.com', True)
        visitor = user('skill-visitor@example.net')
        other = user('skill-other@example.net')
        skill = Path(tmp) / 'portable'
        skill.mkdir();shutil.copy2(ROOT / 'skills/chatcontext/chatcontext', skill / 'chatcontext')
        env = {**os.environ, 'XDG_CACHE_HOME': str(Path(tmp) / 'cache'), 'CHATCONTEXT_URL': request.base_url, 'CHATCONTEXT_USER_EMAIL': team['email'], 'CHATCONTEXT_USER_PASSWORD': password}
        def cli(*argv, expected=0, email=None):
            result = subprocess.run([sys.executable, str(skill / 'chatcontext'), *argv], env={**env, 'CHATCONTEXT_USER_EMAIL': email or env['CHATCONTEXT_USER_EMAIL']}, cwd=tmp, capture_output=True, text=True)
            assert password not in result.stdout + result.stderr
            assert result.returncode == expected, (argv, result.stdout, result.stderr)
            return json.loads(result.stdout) if result.returncode == 0 and result.stdout.startswith(('{', '[')) else result.stdout
        identity = cli('whoami')
        assert identity['id'] == team['id']
        assert identity['public_display_name'] == ''
        assert cli('display-name', 'Skill Team')['public_display_name'] == 'Skill Team'
        assert cli('whoami')['public_display_name'] == 'Skill Team'
        assert cli('query', f"SELECT name FROM user_directory WHERE id = '{team['id']}'")['rows'] == [['Skill Team']]
        cli('display-name', 'Visitor alias', email=visitor['email'], expected=1)
        schema = cli('schema')
        snapshot = ROOT / 'skills/chatcontext/references/schema.json'
        if args.write_schema:
            snapshot.write_text(json.dumps(schema, indent=2) + '\n')
            (ROOT / 'src/chatcontext_client/schema.json').write_text(snapshot.read_text())
        assert json.loads(snapshot.read_text()) == schema, 'SQL schema changed; review and regenerate snapshot'
        assert json.loads((ROOT / 'src/chatcontext_client/schema.json').read_text()) == schema
        cli('check')
        channel = cli('channel', 'Synthetic private', '--private', '--participants', peer['id'])
        message = cli('send', channel['id'], 'Synthetic message', '--mention', peer['id'])
        assert cli('get', 'messages', message['id'])['body'] == 'Synthetic message'
        cli('edit', message['id'], 'Edited synthetic', '--revision', str(message['revision']))
        cli('edit', message['id'], 'Stale synthetic', '--revision', str(message['revision']), expected=4)
        reply = cli('reply', channel['id'], message['id'], 'Peer reply', email=peer['email'])
        cli('inbox')
        cli('unread')
        before = cli('query', 'SELECT COUNT(*) AS n FROM read_receipts')['rows'][0][0]
        page = cli('sync', '--after', '0', '--limit', '2')
        assert page['next_cursor'] > 0
        cli('get', 'messages', reply['id'])
        assert cli('query', 'SELECT COUNT(*) AS n FROM read_receipts')['rows'][0][0] == before
        cli('ack', reply['id'])
        cli('ack', reply['id'])
        assert cli('query', 'SELECT COUNT(*) AS n FROM read_receipts')['rows'][0][0] == before + 1
        dm = cli('dm', 'Synthetic group', '--participants', peer['id'])
        cli('send', dm['id'], 'DM synthetic')
        support = cli('support', 'Synthetic support', email=visitor['email'])
        visitor_message = cli('send', support['id'], 'Visitor question', email=visitor['email'])
        note = cli('note', support['id'], 'Private investigation')
        note_reply = cli('reply', support['id'], note['id'], 'Private follow-up')
        assert note_reply['internal'] is True
        cli('get', 'messages', note_reply['id'], email=visitor['email'], expected=1)
        cli('get', 'messages', note['id'], email=visitor['email'], expected=1)
        cli('get', 'messages', visitor_message['id'], email=other['email'], expected=1)
        answer = cli('reply', support['id'], visitor_message['id'], 'Synthetic answer')
        cli('get', 'messages', answer['id'], email=visitor['email'])
        original = Path(tmp) / 'original.txt'
        original.write_bytes(b'Synthetic protected attachment\n')
        attachment = cli('upload', visitor_message['id'], str(original), email=visitor['email'])
        saved = Path(tmp) / 'download.txt'
        cli('download', attachment['id'], str(saved))
        assert saved.read_bytes() == original.read_bytes()
        cli('download', attachment['id'], str(Path(tmp) / 'denied.txt'), email=other['email'], expected=1)
        current = cli('get', 'messages', visitor_message['id'], email=visitor['email'])
        cli('delete', visitor_message['id'], '--revision', str(current['revision']), email=visitor['email'])
        cli('download', attachment['id'], str(Path(tmp) / 'deleted.txt'), expected=1)
        events = cli('sync', '--after', '0')['changes']
        assert any(event['action'] == 'delete' and event['record'] == visitor_message['id'] for event in events)
        memberships = cli('query', f"SELECT id, revision FROM memberships WHERE conversation = '{channel['id']}' AND account = '{peer['id']}'")['rows']
        assert len(memberships) == 1
        cli('update', 'memberships', memberships[0][0], json.dumps({'active': False, 'expected_revision': memberships[0][1]}))
        cli('get', 'messages', message['id'], email=peer['email'], expected=1)
        after_revocation = cli('sync', '--after', '0', email=peer['email'])['changes']
        assert not any(event['conversation'] == channel['id'] for event in after_revocation)
        for collection in ('users', 'team_members', 'counters'):
            cli('query', f'SELECT * FROM {collection}', expected=1)
        cli('logout')
    print('Portable skill integration and schema checks passed.')


if __name__ == '__main__':
    main()
