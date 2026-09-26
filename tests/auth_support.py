#!/usr/bin/env python3
"""Exercise ChatContext through HTTP against an isolated temporary database."""
import argparse
import concurrent.futures
import contextlib
import json
from pathlib import Path
import socket
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

@contextlib.contextmanager
def server(binary):
    with tempfile.TemporaryDirectory(prefix='chatcontext-auth-test-') as tmp:
        hooks=Path(tmp)/'pb_hooks'
        shutil.copytree(ROOT/'pb_hooks',hooks)
        (hooks/'failure_fixture.pb.js').write_text('''
onRecordCreateExecute((e) => {
  if(e.record.getString('record') === 'auditfailure001') throw new Error('Synthetic audit failure');
  e.next();
}, 'audit_log');
onRecordCreateExecute((e) => {
  if(e.record.id === 'dirfailure00001') throw new Error('Synthetic directory failure');
  e.next();
}, 'user_directory');
''')
        common = [str(Path(binary).resolve()), '--dir', str(Path(tmp)/'pb_data'), '--migrationsDir', str(ROOT/'pb_migrations'), '--hooksDir', str(hooks)]
        result = subprocess.run(common+['superuser','upsert','admin@example.com','SyntheticAdminPassword123!'],cwd=ROOT,capture_output=True,text=True)
        assert result.returncode == 0, result.stdout+result.stderr
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        with open(Path(tmp)/'server.log','w+') as log:
            proc=subprocess.Popen(common+['serve','--http',f'127.0.0.1:{port}'],cwd=ROOT,stdout=log,stderr=log)
            def request(method,path,body=None,token=None,expected=200):
                headers={'Content-Type':'application/json'}
                if token: headers['Authorization']=token
                req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=None if body is None else json.dumps(body).encode(),headers=headers,method=method)
                try:
                    with urllib.request.urlopen(req,timeout=20) as r: status,raw=r.status,r.read()
                except urllib.error.HTTPError as e: status,raw=e.code,e.read()
                assert status in (expected if isinstance(expected,tuple) else (expected,)), (method,path,status,raw.decode())
                return json.loads(raw) if raw else None
            try:
                for _ in range(150):
                    try: request('GET','/api/health'); break
                    except (OSError,AssertionError):
                        if proc.poll() is not None: log.seek(0); raise AssertionError(log.read())
                        time.sleep(.1)
                else: raise AssertionError('Server startup timed out')
                request.base_url = f'http://127.0.0.1:{port}'
                yield request
            finally:
                proc.terminate();proc.wait(timeout=15)
