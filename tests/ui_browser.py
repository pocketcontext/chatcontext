#!/usr/bin/env python3
"""Production reader browser tests against isolated synthetic records."""
import argparse, contextlib, json, os, pathlib, shutil, subprocess, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PASSWORD='SyntheticUserPassword123!'
ROOT=pathlib.Path(__file__).resolve().parents[1]

@contextlib.contextmanager
def control_server(action):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            action(self.path);self.send_response(200);self.end_headers();self.wfile.write(b'{}')
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield 'http://127.0.0.1:'+str(server.server_port)
    finally:server.shutdown();server.server_close();thread.join()

def browser(base, fixture, action):
    with tempfile.TemporaryDirectory(prefix='reader-browser-') as temp, control_server(action) as controller:
        path=pathlib.Path(temp)/'fixture.json';path.write_text(json.dumps(fixture));path.chmod(0o600)
        env=dict(os.environ,READER_SCREENSHOT_DIR=os.environ.get('READER_SCREENSHOT_DIR',temp),READER_TEST_URL=base,READER_TEST_FIXTURE=str(path),READER_TEST_CONTROL=controller,READER_TEST_OUTPUT=str(pathlib.Path(temp)/'results'))
        result=subprocess.run(['pnpm','e2e'],cwd=ROOT/'ui',env=env)
        if result.returncode:raise SystemExit(result.returncode)

def run(binary):
    from integration import server, operator, account, path, query, upload
    with server(binary) as request:
        op=operator(request);user,token=account(request,op,'reader@example.com',True,True)
        foreign,ft=account(request,op,'foreign@example.com',True)
        create=lambda table,body,tok=token:request('POST',path(table),body,tok)
        records=[create('conversations',{'kind':'public_channel','title':f'Fixture conversation {i:02}'}) for i in range(35)]
        owned=create('conversations',{'kind':'private_channel','title':'Reader-only conversation'})
        first=records[0];message=create('messages',{'conversation':first['id'],'body':'Readable discussion evidence'})
        attachment,_=upload(request,message['id'],token)
        private=create('conversations',{'kind':'private_channel','title':'Restricted conversation'},ft)
        hidden=create('messages',{'conversation':private['id'],'body':'Private team secret'},ft)
        fixture=dict(authCollection='users',otherEmail='foreign@example.com',privateTable='conversations',privateId=owned['id'],privateText=owned['title'],email='reader@example.com',password=PASSWORD,table='conversations',label='Conversations',id=first['id'],title=first['title'],needle=records[-1]['title'],forbiddenTable='messages',forbiddenId=hidden['id'],forbiddenText='Private team secret',relationTitle='Readable discussion evidence',relationTable='messages',relationId=message['id'],fileTable='attachments',fileId=attachment['id'])
        def action(action):
            if action=='/revoke':request('PATCH',path('users')+'/'+user['id'],{'disabled':True},op)
            elif action=='/assert-unread':assert query(request,'SELECT id FROM read_receipts',token)==[]
        browser(request.base_url,fixture,action)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--binary',required=True);args=parser.parse_args()
    run(args.binary)
