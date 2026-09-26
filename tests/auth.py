#!/usr/bin/env python3
"""Synthetic identity, SMTP OTP, administrator and revocation integration checks."""
import argparse
import contextlib
import concurrent.futures
import queue
import re
import socketserver
import threading
import time
from auth_support import server

@contextlib.contextmanager
def smtp():
    delivered = queue.Queue()
    class SMTP(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b'220 localhost synthetic SMTP\r\n')
            while line := self.rfile.readline():
                command = line.split()[0].upper()
                if command in (b'EHLO', b'HELO'):
                    self.wfile.write(b'250 localhost\r\n')
                elif command == b'DATA':
                    self.wfile.write(b'354 Send data\r\n')
                    data = b''
                    while (part := self.rfile.readline()) != b'.\r\n':
                        if not part: return
                        data += part
                    delivered.put(data.decode())
                    self.wfile.write(b'250 Accepted\r\n')
                elif command == b'QUIT':
                    self.wfile.write(b'221 Bye\r\n'); return
                else: self.wfile.write(b'250 OK\r\n')
    with socketserver.ThreadingTCPServer(('127.0.0.1', 0), SMTP) as http:
        thread = threading.Thread(target=http.serve_forever, daemon=True); thread.start()
        try: yield http.server_address[1], delivered
        finally: http.shutdown(); thread.join()

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--binary', required=True); args = parser.parse_args()
    with smtp() as (port, mail), server(args.binary) as req:
        root = req('POST', '/api/collections/_superusers/auth-with-password', {'identity':'admin@example.com','password':'SyntheticAdminPassword123!'})['token']
        path = lambda name: '/api/collections/'+name+'/records'
        req('PATCH','/api/settings', {'smtp':{'enabled':True,'host':'127.0.0.1','port':port,'tls':False}, 'meta':{'senderAddress':'support@example.test','senderName':'Synthetic'}},root)
        users = req('GET','/api/collections/users',token=root)
        assert users['otp']['duration']==600 and users['otp']['length']==8 and users['authToken']['duration']==604800
        password = 'SyntheticPassword123!'
        def create(email, token=root):
            return req('POST',path('users'),{'email':email,'name':'Synthetic','password':password,'passwordConfirm':password,'verified':True},token)
        def login(email): return req('POST','/api/collections/users/auth-with-password',{'identity':email,'password':password})['token']
        req('POST',path('users'),{'email':'forbidden@example.test','password':password,'passwordConfirm':password},expected=(400,403))
        owner=create('owner@example.test'); membership=req('POST',path('team_members'),{'account':owner['id'],'is_admin':True},root)
        token=login('owner@example.test')
        assert req('GET',path('team_members'),token=token)['items'][0]['id']==membership['id']
        req('GET',path('team_members')+'/'+membership['id'],token=token)
        other=create('other@example.test'); other_token=login('other@example.test')
        req('GET',path('team_members'),token=other_token,expected=(403,404))
        req('GET',path('team_members')+'/'+membership['id'],token=other_token,expected=(403,404))
        req('POST',path('team_members'),{'account':other['id'],'is_admin':True},other_token,expected=(400,403))
        req('PATCH',path('team_members')+'/'+membership['id'],{'is_admin':False},token,expected=400)
        req('DELETE',path('team_members')+'/'+membership['id'],token=token,expected=400)
        req('PATCH',path('users')+'/'+owner['id'],{'disabled':True},token,expected=400)
        # Admins can provision an AI account, but cannot seize existing accounts.
        ai=create('ai@example.test',token)
        req('POST',path('team_members'),{'account':ai['id'],'is_admin':False},token)
        for payload in ({'password':password,'passwordConfirm':password},{'email':'taken@example.test'},{'verified':True}):
            req('PATCH',path('users')+'/'+other['id'],payload,token,expected=400)
        req('GET',path('users')+'/'+other['id'],token=token,expected=404)
        req('GET',path('users'),token=token,expected=403)
        # Directory projection must roll back together with failed identity creation.
        req('POST',path('users'),{'id':'dirfailure00001','email':'fail@example.test','name':'Fail','password':password,'passwordConfirm':password,'verified':True},root,expected=(400,500))
        req('GET',path('users')+'/dirfailure00001',token=root,expected=404)
        for value in (True,False):
            req('PATCH',path('users')+'/'+other['id'],{'disabled':value},token)
            req('GET','/api/context/schema',token=other_token,expected=(401,403))
        login('other@example.test')
        req('DELETE',path('users')+'/'+other['id'],token=root,expected=(400,403))
        def code(email):
            result=req('POST','/api/collections/users/request-otp',{'email':email})
            message=mail.get(timeout=10)
            digits=re.search(r'\b\d{8}\b',message)
            assert digits, message
            return {'otpId':result['otpId'],'password':digits[0]}
        email='visitor@example.test'
        old=code(email); current=code(email.upper())
        req('POST','/api/collections/users/auth-with-otp',old,expected=400)
        auth=req('POST','/api/collections/users/auth-with-otp',current)
        assert auth['record']['verified'] and auth['record']['name']=='Visitor'
        req('POST','/api/collections/users/auth-with-otp',current,expected=400)
        refreshed=req('POST','/api/collections/users/auth-refresh',token=auth['token'])
        assert refreshed['record']['id']==auth['record']['id']
        assert not any(row['account']==auth['record']['id'] for row in req('GET',path('team_members'),token=root)['items'])
        req('PATCH','/api/collections/users',{'otp':{'duration':10}},root)
        expired=code('expired@example.test')
        time.sleep(10.1)
        req('POST','/api/collections/users/auth-with-otp',expired,expected=400)
        req('PATCH','/api/collections/users',{'otp':{'duration':600}},root)
        attempt=code('attempts@example.test')
        for _ in range(5): req('POST','/api/collections/users/auth-with-otp',dict(attempt,password='00000000'),expected=400)
        req('POST','/api/collections/users/auth-with-otp',attempt,expected=429)
        raced=code('race@example.test')
        def consume(_): return req('POST','/api/collections/users/auth-with-otp',raced,expected=(200,400,429))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(consume,range(2)))
        assert sum('token' in response for response in responses)==1
        assert req('GET',path('login_attempts'),token=root)['items']
        req('POST','/api/context/query',{'sql':'SELECT * FROM login_attempts'},auth['token'],expected=400)
    print('PASS: email OTP delivery, case matching, single use, replacement, attempt cap, admin management, privacy and revocation')

if __name__=='__main__': main()
