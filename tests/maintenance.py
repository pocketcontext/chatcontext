#!/usr/bin/env python3
"""Synthetic maintenance freeze, authorization, file and restart checks."""
import argparse
from contextlib import closing
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
import urllib.error
import urllib.request
from integration import ROOT, server

def multipart(request, table, fields, token, expected=200):
    boundary = 'synthetic-maintenance-boundary'
    content = b'Synthetic maintenance original'
    body = ''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k,v in fields.items()).encode()
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="original"; filename="fixture.txt"\r\nContent-Type: text/plain\r\n\r\n').encode() + content + f'\r\n--{boundary}--\r\n'.encode()
    req = urllib.request.Request(request.base_url + '/api/collections/' + table + '/records', body, {'Authorization':token, 'Content-Type':'multipart/form-data; boundary=' + boundary})
    try:
        with urllib.request.urlopen(req, timeout=10) as r: status, raw = r.status, r.read()
    except urllib.error.HTTPError as e: status, raw = e.code, e.read()
    assert status == expected, (status, raw)
    return json.loads(raw), content

def frozen_restart(binary, request, admin, token, frozen, table):
    """A fresh process preserves a frozen snapshot despite changed deploy settings."""
    with tempfile.TemporaryDirectory(prefix='chatcontext-frozen-restart-') as tmp:
        data = Path(tmp) / 'pb_data'
        data.mkdir()
        for source in request.data_dir.glob('*.db'):
            with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as read:
                with closing(sqlite3.connect(data / source.name)) as write:
                    read.backup(write)
        shutil.copy2(request.data_dir / 'maintenance.json', data / 'maintenance.json')
        if (request.data_dir / 'storage').exists():
            shutil.copytree(request.data_dir / 'storage', data / 'storage')
        def config_rows(path):
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                return (db.execute('SELECT * FROM _params ORDER BY id').fetchall(),
                        db.execute('SELECT * FROM _collections ORDER BY id').fetchall(),
                        db.execute('SELECT * FROM users ORDER BY id').fetchall(),
                        db.execute('SELECT * FROM _superusers ORDER BY id').fetchall())
        stored = config_rows(data / 'data.db')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = dict(os.environ, BASE_URL='https://must-not-apply.example.test',
                   CHATCONTEXT_GOOGLE_CLIENT_ID='synthetic-changed-client',
                   CHATCONTEXT_GOOGLE_CLIENT_SECRET='synthetic-changed-secret')
        common = [str(Path(binary).resolve()), '--dir', str(data),
                  '--migrationsDir', str(ROOT / 'pb_migrations'), '--hooksDir', str(ROOT / 'pb_hooks')]
        def call(method, path, body=None, identity=admin):
            req = urllib.request.Request(f'http://127.0.0.1:{port}' + path,
                data=None if body is None else json.dumps(body).encode(),
                headers={'Content-Type': 'application/json', 'Authorization': identity}, method=method)
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read())
        with (Path(tmp) / 'server.log').open('w+') as log:
            process = subprocess.Popen(common + ['serve', '--http', f'127.0.0.1:{port}'],
                                       cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                for _ in range(150):
                    if process.poll() is not None:
                        log.seek(0)
                        raise AssertionError(log.read())
                    try:
                        state = call('GET', '/api/context/maintenance')
                        break
                    except (OSError, ValueError):
                        time.sleep(.1)
                else:
                    raise AssertionError('frozen restart timed out')
                assert state['state'] == 'read_only' and state['generation'] == frozen['generation'], state
                assert config_rows(data / 'data.db') == stored, 'frozen bootstrap changed configuration'
                assert call('POST', '/api/context/query', {'sql': 'SELECT id FROM ' + table}, token)['rows']
                # Existing operator tokens can thaw after a full process restart.
                state = call('PUT', '/api/context/maintenance', {
                    'readOnly': False, 'expectedGeneration': frozen['generation']})
                assert state['state'] == 'writable', state
            finally:
                process.terminate()
                process.wait(timeout=15)

        # A migration introduced after the snapshot must never run while frozen.
        shutil.copy2(request.data_dir / 'maintenance.json', data / 'maintenance.json')
        migrations = Path(tmp) / 'pending_migrations'
        shutil.copytree(ROOT / 'pb_migrations', migrations)
        (migrations / '9999999999_pending.js').write_text('migrate((app) => {}, (app) => {});\n')
        command = [str(Path(binary).resolve()), 'serve', '--dir', str(data),
                   '--migrationsDir', str(migrations), '--hooksDir', str(ROOT / 'pb_hooks'),
                   '--http', f'127.0.0.1:{port}']
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
        assert result.returncode != 0, 'pending migration accepted during frozen startup'
        assert 'readonly database' in result.stdout + result.stderr, ('migration did not fail at the read-only database guard', result.stdout, result.stderr)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--binary',required=True); args=parser.parse_args()
    with server(args.binary) as request:
        records='/api/collections/'
        admin=request('POST',records+'_superusers/auth-with-password',{'identity':'admin@example.com','password':'SyntheticAdminPassword123!'})['token']
        password='SyntheticUserPassword123!'
        user=request('POST',records+'users/records',{'verified':True,'name':'Synthetic owner','email':'owner@example.test','password':password,'passwordConfirm':password},admin)
        foreign=request('POST',records+'users/records',{'verified':True,'name':'Synthetic foreign','email':'foreign@example.test','password':password,'passwordConfirm':password},admin)
        token=request('POST',records+'users/auth-with-password',{'identity':'owner@example.test','password':password})['token']
        outsider=request('POST',records+'users/auth-with-password',{'identity':'foreign@example.test','password':password})['token']
        request('POST', records + 'team_members/records', {'account':user['id'], 'is_admin':False}, admin)
        conversation = request('POST', records + 'conversations/records', {'kind':'private_channel','title':'Synthetic maintenance'}, token)
        message = request('POST', records + 'messages/records', {'conversation':conversation['id'],'body':'Synthetic maintenance'}, token)
        table = 'attachments'
        fields = {'message':message['id']}
        record, original = multipart(request, table, fields, token)
        file_table, file_id, filename = table, record['id'], record['original']
        def mutation(expected=200): return multipart(request, table, fields, token, expected)

        status=request('GET','/api/context/maintenance',token=admin)
        request('PUT','/api/context/maintenance',{'readOnly':True,'expectedGeneration':status['generation']},token,(401,403))
        frozen=request('PUT','/api/context/maintenance',{'readOnly':True,'expectedGeneration':status['generation']},admin)
        assert frozen['state']=='read_only'
        assert json.loads((request.data_dir/'maintenance.json').read_text()) == {'readOnly':True,'generation':frozen['generation']}
        def query(identity): return request('POST','/api/context/query',{'sql':'SELECT id FROM '+table},identity)['rows']
        assert query(token)==[[record['id']]]
        assert query(outsider)==[]
        file_path='/api/files/'+file_table+'/'+file_id+'/'+filename
        for identity, allowed in [(token,True),(outsider,False),(None,False)]:
            ft=request('POST','/api/files/token',{},identity)['token'] if identity else ''
            try:
                with urllib.request.urlopen(request.base_url+file_path+'?token='+ft,timeout=10) as response:
                    assert allowed and response.read()==original
            except urllib.error.HTTPError as error:
                assert not allowed and error.code in (401,403,404), error.code
        before={str(p.relative_to(request.data_dir)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (request.data_dir/'storage').rglob('*') if p.is_file()}
        request('POST',records+'users/auth-refresh',{},token)
        for identity in (token,admin):
            request('POST',records+table+'/records',{},identity,503)
            request('PATCH',records+table+'/records/'+record['id'],{},identity,503)
            request('POST','/api/batch',{'requests':[{'method':'POST','url':records+table+'/records','body':{}}]},identity,503)
        request('POST', records+'users/request-otp', {'email':'new-visitor@example.test'}, expected=503)
        mutation(503)
        assert before=={str(p.relative_to(request.data_dir)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (request.data_dir/'storage').rglob('*') if p.is_file()}
        frozen_restart(args.binary,request,admin,token,frozen,table)
        request('PUT','/api/context/maintenance',{'readOnly':False,'expectedGeneration':status['generation']},admin,409)
        thawed=request('PUT','/api/context/maintenance',{'readOnly':False,'expectedGeneration':frozen['generation']},admin)
        assert thawed['state']=='writable'
        mutation()
    print('PASS: maintenance preserves filtered reads, protected files, settings and tokens; blocks writes and explicitly thaws')

if __name__=='__main__': main()
