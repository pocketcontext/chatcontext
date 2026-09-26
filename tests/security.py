#!/usr/bin/env python3
"""Adversarial filtered snapshots, alternate access paths and role revocation."""
import argparse
import urllib.request
import urllib.error
from integration import server, operator, account, path, query, upload, download, PASSWORD

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--binary',required=True);args=ap.parse_args()
    with server(args.binary) as request:
        op=operator(request)
        admin,at=account(request,op,'admin-team@example.test',True,True)
        alice,alt=account(request,op,'alice@example.test',True)
        bob,bt=account(request,op,'bob@example.test',True)
        visitor,vt=account(request,op,'visitor@example.test')
        other,ot=account(request,op,'other@example.test')
        create=lambda t,b,token:request('POST',path(t),b,token)
        support=create('conversations',{'kind':'support','title':'Private support'},vt)
        cid=support['id']
        public=create('messages',{'conversation':cid,'body':'Public response'},alt)
        private=create('messages',{'conversation':cid,'body':'Internal sensitive note','internal':True,'mentions':[bob['id']]},alt)
        internal_file,_=upload(request,private['id'],alt)
        create('reactions',{'message':private['id'],'emoji':'yes','active':True},bt)
        create('read_receipts',{'message':private['id']},bt)
        create('messages',{'conversation':cid,'body':'Internal reply','parent':private['id'],'internal':True},bt)
        # Every route must enforce note visibility, including derived records.
        for table in ['messages','attachments','reactions','read_receipts','inbox','changes','audit_log']:
            visible=query(request,'SELECT * FROM '+table,vt)
            assert not any(row.get('id')==private['id'] or row.get('message')==private['id'] or row.get('record')==private['id'] for row in visible),(table,visible)
            assert query(request,'SELECT * FROM '+table,ot)==[],table
            request('GET',path(table),token=vt,expected=(403,404))
        download(request,internal_file,alt,200)
        download(request,internal_file,vt,404)
        visitor_file_token=request('POST','/api/files/token',{},vt)['token']
        author_file_token=request('POST','/api/files/token',{},alt)['token']
        revoked_file_token=request('POST','/api/files/token',{},bt)['token']
        def raw_file(ft,bearer,expected):
            url=request.base_url+'/api/files/attachments/'+internal_file['id']+'/'+internal_file['original']+'?token='+ft
            req=urllib.request.Request(url,headers={'Authorization':bearer})
            try:
                with urllib.request.urlopen(req) as result: status=result.status
            except urllib.error.HTTPError as error: status=error.code
            assert status==expected,status
        raw_file(visitor_file_token,alt,404)
        raw_file(author_file_token,vt,200)
        request('POST',path('messages'),{'conversation':cid,'body':'Guessing note','parent':private['id']},vt,expected=(400,403,404))
        request('POST',path('read_receipts'),{'message':private['id']},vt,expected=(400,403,404))
        request('POST',path('reactions'),{'message':private['id'],'emoji':'x'},vt,expected=(400,403,404))
        request('POST',path('messages'),{'conversation':cid,'body':'Hidden mention','mentions':[admin['id']]},vt,expected=(400,403,404))
        create('messages',{'conversation':cid,'body':'Allowed mention','mentions':[alice['id']]},vt)
        directory=query(request,'SELECT * FROM user_directory',vt)
        assert {row['id'] for row in directory}=={visitor['id'],alice['id']},directory
        assert all(set(row)=={'id','name'} for row in directory)
        assert all(row['name']=='User' for row in directory),directory
        # Public identities are an explicit administrator choice, never users.name.
        alice_path=path('users')+'/'+alice['id']
        request('PATCH',alice_path,{'name':'Private Legal Name'},op)
        def label():
            return next(row['name'] for row in query(request,'SELECT * FROM user_directory',vt) if row['id']==alice['id'])
        assert label()=='User'
        request('PATCH',alice_path,{'public_display_name':'  Support Alice  '},at)
        assert label()=='Support Alice'
        request('PATCH',alice_path,{'name':'Different Private Name'},op)
        assert label()=='Support Alice'
        for token,record_id in ((vt,visitor['id']),(vt,alice['id']),(alt,alice['id'])):
            request('PATCH',path('users')+'/'+record_id,{'public_display_name':'Unapproved alias'},token,expected=(400,403,404))
        request('PATCH',path('user_directory')+'/'+alice['id'],{'name':'Forged alias'},vt,expected=(400,403,404))
        assert label()=='Support Alice'
        for value in ('', '   '):
            request('PATCH',alice_path,{'public_display_name':value},at)
            assert label()=='User'
        provisioned=create('users',{'email':'alias@example.test','name':'Private Provisioned Name',
            'public_display_name':'Support Helper','password':PASSWORD,'passwordConfirm':PASSWORD,'verified':True},at)
        assert next(row['name'] for row in query(request,'SELECT * FROM user_directory',at) if row['id']==provisioned['id'])=='Support Helper'
        assert provisioned['id'] not in {row['id'] for row in query(request,'SELECT * FROM user_directory',vt)}
        # Deleting the last public reply removes the author, despite internal notes.
        request('PATCH',path('messages')+'/'+public['id'],{'expected_revision':public['revision'],'deleted':True},alt)
        assert {row['id'] for row in query(request,'SELECT * FROM user_directory',vt)}=={visitor['id']}
        # Administrator power does not grant entry to private conversations.
        private_channel=create('conversations',{'kind':'private_channel','title':'Alice and Bob','participants':[bob['id']]},alt)
        dm=create('conversations',{'kind':'dm','title':'Private DM','participants':[bob['id']]},alt)
        for conversation in (private_channel,dm):
            message=create('messages',{'conversation':conversation['id'],'body':'Secret','mentions':[bob['id']]},alt)
            attached,_=upload(request,message['id'],alt)
            assert not any(row['id']==conversation['id'] for row in query(request,'SELECT * FROM conversations',at))
            for table in ['messages','attachments','inbox','changes','audit_log']:
                assert not any(row.get('id')==message['id'] or row.get('message')==message['id'] or row.get('conversation')==conversation['id'] for row in query(request,'SELECT * FROM '+table,at)),table
            download(request,attached,at,404)
            request('POST',path('memberships'),{'conversation':conversation['id'],'account':admin['id'],'active':True},at,expected=(400,403,404))
        # Public channel receipts must not appear in change/audit side channels.
        channel=create('conversations',{'kind':'public_channel','title':'Public'},alt)
        message=create('messages',{'conversation':channel['id'],'body':'Announcement'},alt)
        receipt=create('read_receipts',{'message':message['id']},bt)
        for token in (at,alt):
            assert not any(r['id']==receipt['id'] for r in query(request,'SELECT * FROM read_receipts',token))
            for table in ('changes','audit_log'):
                assert not any(r['record']==receipt['id'] for r in query(request,'SELECT * FROM '+table,token))
        # Existing SQL sessions are re-filtered immediately after role removal.
        membership=next(r for r in request('GET',path('team_members'),token=op)['items'] if r['account']==bob['id'])
        request('DELETE',path('team_members')+'/'+membership['id'],token=at,expected=204)
        for table in ['conversations','memberships','messages','attachments','reactions','read_receipts','inbox','changes','audit_log']:
            assert query(request,'SELECT * FROM '+table,bt)==[],table
        download(request,internal_file,bt,404)
        raw_file(revoked_file_token,alt,404)
        request('POST',path('messages'),{'conversation':cid,'body':'Revoked'},bt,expected=(400,403,404))
        # Assignment does not prevent the visitor from resolving their own ticket.
        assigned=request('PATCH',path('conversations')+'/'+cid,{'expected_revision':support['revision'],'assignee':alice['id']},alt)
        closed=request('PATCH',path('conversations')+'/'+cid,{'expected_revision':assigned['revision'],'status':'resolved'},vt)
        assert closed['status']=='resolved'
    print('PASS: indirect note isolation, directory privacy, private admin boundaries, receipt side channels and immediate team revocation')

if __name__=='__main__':main()
