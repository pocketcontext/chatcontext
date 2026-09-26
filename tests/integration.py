#!/usr/bin/env python3
"""Synthetic HTTP integration and authorization tests; no application data is reused."""
import argparse
import concurrent.futures
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = 'SyntheticUserPassword123!'

@contextlib.contextmanager
def server(binary, env=None):
    with tempfile.TemporaryDirectory(prefix='chatcontext-test-') as tmp:
        hooks=Path(tmp)/'pb_hooks'
        shutil.copytree(ROOT/'pb_hooks',hooks)
        (hooks/'zz_failure_fixture.pb.js').write_text('''
onRecordCreateExecute(e=>{if(e.record.getString('record')==='auditfailure001')throw new Error('Synthetic audit failure');e.next();},'audit_log');
onRecordCreateExecute(e=>{if(e.record.id==='dirfailure00001')throw new Error('Synthetic directory failure');e.next();},'user_directory');
''')
        common=[str(Path(binary).resolve()),'--dir',str(Path(tmp)/'pb_data'),'--migrationsDir',str(ROOT/'pb_migrations'),'--hooksDir',str(hooks)]
        child_env={k:v for k,v in os.environ.items() if not k.startswith('CHATCONTEXT_')}
        child_env.update(env or {})
        result=subprocess.run(common+['superuser','upsert','admin@example.com','SyntheticAdminPassword123!'],cwd=ROOT,capture_output=True,text=True,env=child_env)
        assert result.returncode==0,result.stdout+result.stderr
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        with open(Path(tmp)/'server.log','w+') as log:
            proc=subprocess.Popen(common+['serve','--http',f'127.0.0.1:{port}'],cwd=ROOT,stdout=log,stderr=log,env=child_env)
            def request(method,path,body=None,token=None,expected=200):
                headers={'Content-Type':'application/json'}
                if token:headers['Authorization']=token
                req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=None if body is None else json.dumps(body).encode(),headers=headers,method=method)
                try:
                    with urllib.request.urlopen(req,timeout=25) as r:status,raw=r.status,r.read()
                except urllib.error.HTTPError as e:status,raw=e.code,e.read()
                assert status in (expected if isinstance(expected,tuple) else (expected,)),(method,path,status,raw.decode())
                return json.loads(raw) if raw else None
            try:
                for _ in range(150):
                    try:request('GET','/api/health');break
                    except (OSError,AssertionError):
                        if proc.poll() is not None:log.seek(0);raise AssertionError(log.read())
                        time.sleep(.1)
                else:log.seek(0);raise AssertionError('Startup timeout\n'+log.read())
                request.base_url=f'http://127.0.0.1:{port}'
                request.data_dir=Path(tmp)/'pb_data'
                yield request
            except Exception:
                log.seek(0)
                print(log.read()[-18000:])
                raise
            finally:
                proc.terminate();proc.wait(timeout=20)

def path(table):return '/api/collections/'+table+'/records'
def operator(request):return request('POST','/api/collections/_superusers/auth-with-password',{'identity':'admin@example.com','password':'SyntheticAdminPassword123!'})['token']
def account(request,op,email,team=False,admin=False):
    user=request('POST',path('users'),{'email':email,'name':email.split('@')[0],'verified':True,'password':PASSWORD,'passwordConfirm':PASSWORD},op)
    if team:request('POST',path('team_members'),{'account':user['id'],'is_admin':admin},op)
    token=request('POST','/api/collections/users/auth-with-password',{'identity':email,'password':PASSWORD})['token']
    return user,token

def query(request,sql,token):
    result=request('POST','/api/context/query',{'sql':sql},token)
    return [dict(zip(result['columns'],row)) if isinstance(row,list) else row for row in result['rows']]

def upload(request,message,token,expected=200):
    boundary='chatcontext-synthetic-boundary';content=b'Synthetic attachment original\n'
    payload=(f'--{boundary}\r\nContent-Disposition: form-data; name="message"\r\n\r\n{message}\r\n--{boundary}\r\nContent-Disposition: form-data; name="original"; filename="fixture.txt"\r\nContent-Type: text/plain\r\n\r\n').encode()+content+f'\r\n--{boundary}--\r\n'.encode()
    req=urllib.request.Request(request.base_url+path('attachments'),payload,{'Content-Type':'multipart/form-data; boundary='+boundary,'Authorization':token})
    try:
        with urllib.request.urlopen(req) as r:status,raw=r.status,r.read()
    except urllib.error.HTTPError as e:status,raw=e.code,e.read()
    assert status==expected,(status,raw)
    return json.loads(raw),content

def download(request,attachment,token,expected=200):
    ft=request('POST','/api/files/token',{},token)['token'] if token else ''
    url=request.base_url+'/api/files/attachments/'+attachment['id']+'/'+attachment['original']+'?token='+ft
    try:
        with urllib.request.urlopen(url) as r:status,data=r.status,r.read()
    except urllib.error.HTTPError as e:status,data=e.code,e.read()
    assert status==expected,(status,data)
    return data

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--binary',required=True);args=ap.parse_args()
    with server(args.binary) as request:
        op=operator(request)
        alice,at=account(request,op,'alice@example.com',True,True)
        bob,bt=account(request,op,'bob@example.com',True)
        eve,et=account(request,op,'eve@example.com',True,True)
        visitor,vt=account(request,op,'visitor@example.com')
        foreign,ft=account(request,op,'foreign@example.com')
        def create(t,b,tok=at,expected=200):return request('POST',path(t),b,tok,expected)
        def patch(t,r,b,tok=at,expected=200):return request('PATCH',path(t)+'/'+r['id'],dict(expected_revision=r['revision'],**b),tok,expected)
        def sql(q,tok=at):return query(request,q,tok)
        def ids(t,tok):return {r['id'] for r in sql('SELECT id FROM '+t,tok)}
        public=create('conversations',{'kind':'public_channel','title':'General'})
        private=create('conversations',{'kind':'private_channel','title':'Private','participants':[bob['id']]})
        dm=create('conversations',{'kind':'dm','title':'Alice and Bob','participants':[bob['id']]})
        group=create('conversations',{'kind':'dm','title':'Group','participants':[bob['id'],eve['id']]})
        support=create('conversations',{'kind':'support','title':'Visitor help'},vt)
        support2=create('conversations',{'kind':'support','title':'Second issue','visitor':visitor['id']})
        foreign_support=create('conversations',{'kind':'support','title':'Foreign help'},ft)
        assert ids('conversations',vt)=={support['id'],support2['id']}
        assert ids('conversations',ft)=={foreign_support['id']}
        assert private['id'] not in ids('conversations',et) and dm['id'] not in ids('conversations',et)
        assert {public['id'],support['id'],foreign_support['id']}<=ids('conversations',et)
        create('conversations',{'kind':'public_channel','title':'Forbidden'},vt,403)
        create('conversations',{'kind':'support','title':'Spoof','visitor':foreign['id']},vt,403)
        create('conversations',{'kind':'dm','title':'No participants'},at,400)
        private_message=create('messages',{'conversation':private['id'],'body':'private secret'})
        create('messages',{'conversation':private['id'],'body':'admin cannot read'},et,403)
        create('messages',{'conversation':support['id'],'body':'foreign injection'},ft,403)
        question=create('messages',{'conversation':support['id'],'body':'Please help'},vt)
        answer=create('messages',{'conversation':support['id'],'body':'We can help','parent':question['id'],'mentions':[visitor['id']]},bt)
        note=create('messages',{'conversation':support['id'],'body':'Internal secret','internal':True})
        create('messages',{'conversation':support['id'],'body':'Internal spoof','internal':True},vt,403)
        create('messages',{'conversation':support['id'],'body':'Bad note thread','parent':note['id'],'internal':False},bt,400)
        create('messages',{'conversation':support['id'],'body':'Cannot see root','parent':note['id']},vt,403)
        create('messages',{'conversation':support['id'],'body':'Bad cross thread','parent':private_message['id']},at,400)
        followup=create('messages',{'conversation':support['id'],'body':'Thanks','parent':question['id'],'mentions':[bob['id']]},vt)
        create('messages',{'conversation':support['id'],'body':'Directory probe','mentions':[eve['id']]},vt,400)
        assert note['id'] not in ids('messages',vt)
        assert not sql("SELECT * FROM changes WHERE internal = 1",vt)
        assert not sql('SELECT * FROM audit_log',vt)
        assert private_message['id'] not in {r['record'] for r in sql('SELECT record FROM audit_log',et)}
        assert sql('SELECT * FROM audit_log',at)
        visible_names=ids('user_directory',vt)
        assert visitor['id'] in visible_names and bob['id'] in visible_names and eve['id'] not in visible_names and alice['id'] not in visible_names
        # Only the author may change content; stale writes fail and retained originals are admin-scoped.
        patch('messages',question,{'body':'Spoof'},at,403)
        edited=patch('messages',question,{'body':'Please help again'},vt)
        patch('messages',question,{'body':'Stale'},vt,409)
        patch('messages',edited,{'conversation':foreign_support['id']},vt,(400,403))
        patch('messages',edited,{'internal':True},vt,400)
        note_doc,note_bytes=upload(request,note['id'],at)
        doc,data=upload(request,edited['id'],vt)
        assert download(request,doc,vt)==data
        download(request,doc,ft,404);download(request,note_doc,vt,404)
        assert download(request,note_doc,bt)==note_bytes
        download(request,doc,None,404)
        assert ids('attachments',vt)=={doc['id']}
        row=sql("SELECT sha256 FROM attachments WHERE id = '"+doc['id']+"'",vt)[0]
        assert row['sha256']==hashlib.sha256(data).hexdigest()
        patch('attachments',doc,{'message':followup['id']},vt,400)
        upload(request,answer['id'],vt,403)
        # Resolution and assignment independent of permission to reply.
        support=patch('conversations',support,{'assignee':bob['id']})
        patch('conversations',support,{'assignee':alice['id']},vt,400)
        support=patch('conversations',support,{'status':'resolved'},vt)
        create('messages',{'conversation':support['id'],'body':'Private followup','internal':True},bt)
        assert sql("SELECT status FROM conversations WHERE id = '"+support['id']+"'",vt)[0]['status']=='resolved'
        create('messages',{'conversation':support['id'],'body':'Still need help'},vt)
        assert sql("SELECT status FROM conversations WHERE id = '"+support['id']+"'",vt)[0]['status']=='open'
        # Receipts are explicit, private in channels, participant-visible in support/DM.
        assert not sql('SELECT * FROM read_receipts',vt)
        sql('SELECT * FROM messages',vt)
        assert not sql('SELECT * FROM read_receipts',vt)
        receipt=create('read_receipts',{'message':answer['id']},vt)
        assert receipt['id'] in ids('read_receipts',bt)
        create('read_receipts',{'message':note['id']},vt,403)
        create('read_receipts',{'message':answer['id'],'account':bob['id']},vt,403)
        create('read_receipts',{'message':answer['id']},vt,400)
        assert not sql("SELECT * FROM changes WHERE collection = 'read_receipts'",at)
        pubmsg=create('messages',{'conversation':public['id'],'body':'Public post'})
        pubreceipt=create('read_receipts',{'message':pubmsg['id']},bt)
        assert pubreceipt['id'] not in ids('read_receipts',at)
        # Mention and thread reply inbox never leaks note or foreign conversation content.
        assert answer['id'] in {r['message'] for r in sql('SELECT * FROM inbox',vt)}
        assert followup['id'] in {r['message'] for r in sql('SELECT * FROM inbox',bt)}
        assert not sql('SELECT * FROM inbox',ft)
        reaction=create('reactions',{'message':answer['id'],'emoji':'👍','active':True},vt)
        patch('reactions',reaction,{'active':False},bt,403)
        patch('reactions',reaction,{'active':False},vt)
        # Existing messages and files disappear immediately on private-channel removal, including admin.
        private_doc,_=upload(request,private_message['id'],at)
        membership=sql("SELECT * FROM memberships WHERE conversation = '"+private['id']+"' AND account = '"+bob['id']+"'")[0]
        assert download(request,private_doc,bt)
        membership=patch('memberships',membership,{'active':False})
        assert private['id'] not in ids('conversations',bt) and private_message['id'] not in ids('messages',bt)
        download(request,private_doc,bt,404)
        patch('memberships',membership,{'active':True},bt,403)
        membership=patch('memberships',membership,{'active':True})
        assert private_message['id'] in ids('messages',bt)
        create('memberships',{'conversation':dm['id'],'account':eve['id'],'active':True},at,400)
        patch('conversations',dm,{'participants':[eve['id']]},at,400)
        # Soft deletion removes ordinary content, files and inbox but emits a tombstone.
        deleted=patch('messages',edited,{'deleted':True},vt)
        assert deleted['body']=='' and deleted['mentions']==[]
        download(request,doc,vt,404)
        assert doc['id'] not in ids('attachments',vt)
        audit=sql("SELECT changes FROM audit_log WHERE record = '"+edited['id']+"'")
        assert 'Please help again' in json.dumps(audit)
        assert sql("SELECT * FROM changes WHERE record = '"+edited['id']+"' AND action = 'delete'",vt)
        # Archive rejects new messages and allows history.
        public=patch('conversations',public,{'archived':True})
        create('messages',{'conversation':public['id'],'body':'No'},bt,400)
        assert pubmsg['id'] in ids('messages',bt)
        # No direct business deletes or REST/realtime side-channel reads.
        request('DELETE',path('messages')+'/'+answer['id'],token=bt,expected=(403,404))
        for table in ['conversations','messages','memberships','attachments','audit_log']:
            request('GET',path(table),token=at,expected=403)
        request('GET',path('messages')+'/'+answer['id']+'?expand=author',token=vt,expected=(403,404))
        for table in ['users','team_members','counters','sqlite_master']:
            request('POST','/api/context/query',{'sql':'SELECT * FROM '+table},at,400)
        request('POST','/api/context/query',{'sql':'DELETE FROM messages'},at,400)
        request('POST','/api/context/query',{'sql':'SELECT * FROM messages'},expected=401)
        # Transactional audit/inbox/sequence changes roll back with records.
        before=sql('SELECT max(seq) AS n FROM changes')[0]['n']
        create('messages',{'id':'auditfailure001','conversation':support['id'],'body':'Rollback'},at,(400,500))
        assert not sql("SELECT * FROM messages WHERE id = 'auditfailure001'")
        assert sql('SELECT max(seq) AS n FROM changes')[0]['n']==before
        request('POST','/api/batch',{'requests':[{'method':'POST','url':path('messages'),'body':{'conversation':support['id'],'body':'Batch rollback'}},{'method':'POST','url':path('messages'),'body':{'conversation':support['id'],'body':''}}]},at,400)
        assert not sql("SELECT * FROM messages WHERE body = 'Batch rollback'")
        def race(i):return patch('messages',answer,{'body':'Concurrent '+str(i)},bt,(200,409))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(race,range(2)))
        assert sum('id' in r for r in results)==1
        sequences=[r['seq'] for r in sql('SELECT seq FROM changes ORDER BY seq')]
        assert len(sequences)==len(set(sequences)) and sequences==sorted(sequences)
        # Membership revocation in a batch prevents subsequent writes within that same transaction.
        own=sql("SELECT * FROM memberships WHERE conversation = '"+private['id']+"' AND account = '"+alice['id']+"'")[0]
        request('POST','/api/batch',{'requests':[{'method':'PATCH','url':path('memberships')+'/'+own['id'],'body':{'expected_revision':own['revision'],'active':False}},{'method':'POST','url':path('messages'),'body':{'conversation':private['id'],'body':'After revocation'}}]},at,400)
        assert private['id'] in ids('conversations',at)
    print('ChatContext integration passed')

if __name__=='__main__':main()
